import http.server
import json
import os
import signal
import queue
import socketserver
import subprocess
import sys
import threading
import tempfile
import time
import tkinter as tk
import wave
from tkinter import ttk

import plistlib
import requests
import rumps
import sounddevice as sd
from PIL import Image, ImageDraw
from pynput import keyboard

# macOS 核心库支持暂不需要，取消基于焦点的追踪以避免多余的权限请求
HAS_PYOBJC = True

# --- CONFIGURATION DEFAULTS ---
DEFAULT_CONFIG = {
    "api_url": "http://127.0.0.1:8333/transcribe/",
    "warmup_url": "http://127.0.0.1:8333/warmup/",
    "status_url": "http://127.0.0.1:8333/status/",
    "clear_url": "http://127.0.0.1:8333/clear/",
    "language": "zh",
    "sample_rate": 16000,
    "max_record_seconds": 300,
}
CONFIG_FILE = os.path.expanduser("~/.mac_over_speak_config.json")


def get_bundle_dir():
    if getattr(sys, "frozen", False):
        # In PyInstaller Mac bundle, _MEIPASS is the Contents/Resources dir usually
        # but the actual executable path is where the app sits.
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except Exception as e:
                print(f"Load Config Error: {e}")

    def save(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Save Config Error: {e}")

    def get(self, key):
        return self.config.get(key)

    def set(self, key, value):
        self.config[key] = value
        self.save()


class SettingsWindow:
    def __init__(
        self,
        parent,
        config_manager,
        on_save_callback,
        is_main_launch=False,
        client=None,
    ):
        self.window = tk.Toplevel(parent)
        self.window.title("Mac Over Speak Settings")
        self.window.geometry("450x420")
        self.config_manager = config_manager
        self.on_save_callback = on_save_callback
        self.is_main_launch = is_main_launch
        self.client = client

        self.recorder_listener = None
        self.current_recording_var = None
        self.current_recording_btn = None
        self.recorded_keys = set()

        self.setup_ui()

        # Bring to front
        self.window.lift()
        self.window.attributes("-topmost", True)
        if self.client and hasattr(self.client, "schedule_task"):
            self.client.schedule_task(
                500, lambda: self.window.attributes("-topmost", False)
            )
        else:
            self.window.after(500, lambda: self.window.attributes("-topmost", False))

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self):
        frame = ttk.Frame(self.window, padding="20")
        frame.pack(fill="both", expand=True)

        if self.is_main_launch:
            ttk.Label(
                frame, text="Welcome! App is initializing...", font=("", 12, "bold")
            ).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        # API URL
        ttk.Label(frame, text="API URL:").grid(row=1, column=0, sticky="w", pady=5)
        self.api_url_var = tk.StringVar(value=self.config_manager.get("api_url"))
        ttk.Entry(frame, textvariable=self.api_url_var, width=30).grid(
            row=1, column=1, pady=5, sticky="we"
        )

        # Language
        ttk.Label(frame, text="Language (zh/en):").grid(
            row=4, column=0, sticky="w", pady=5
        )
        self.lang_var = tk.StringVar(value=self.config_manager.get("language"))
        ttk.Entry(frame, textvariable=self.lang_var, width=10).grid(
            row=4, column=1, sticky="w", pady=5
        )

        # Warm-up Button
        ttk.Button(frame, text="Warm-up LLM Now", command=self.trigger_warmup).grid(
            row=5, column=0, columnspan=2, pady=15
        )

        # Save Button
        btn_text = "Start & Hide" if self.is_main_launch else "Save & Restart"
        ttk.Button(frame, text=btn_text, command=self.save).grid(
            row=6, column=0, columnspan=2, pady=10
        )

    def trigger_warmup(self):
        warmup_url = self.config_manager.get("warmup_url")
        threading.Thread(target=lambda: requests.get(warmup_url, timeout=300)).start()
        print("Warm-up request sent.")

    def save(self):
        self.config_manager.set("api_url", self.api_url_var.get())
        self.config_manager.set("language", self.lang_var.get())
        self.on_save_callback()
        self.on_close()

    def on_close(self):
        self.window.destroy()


class ASRClient:
    def __init__(self):

        self.task_queue = queue.Queue()
        self.config = ConfigManager()
        self.is_recording = False
        self.is_processing = False
        self.stream = None
        self.recording_file_path = None
        self.recording_wave = None
        self.recording_frame_count = 0
        self.recording_lock = threading.Lock()
        self.limit_stop_requested = False
        self.keyboard_ctrl = keyboard.Controller()
        self.hotkey_listener = None
        self.shift_key_listener = None
        self.last_shift_press_time = 0
        self.backend_process = None
        self.external_backend_pid = self._read_external_backend_pid()
        self._is_closing = False

        # UI State
        self.llm_status = "Starting..."
        self.current_shortcut = "Double Shift"

        self.start_ipc_server()
        self.setup_ui()
        self.ensure_backend_running()
        self.start_hotkey_listener()
        self.language_polling_loop()

        # Register cleanup
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # System Tray Icon (rumps)
        self.setup_rumps()

        # Start LLM warm-up immediately instead of waiting for settings
        # This must be called AFTER setup_rumps because it updates the rumps menu
        self.warmup_llm()

    def _read_external_backend_pid(self):
        raw_pid = os.environ.get("MAC_OVER_SPEAK_API_PID", "").strip()
        if not raw_pid:
            return None

        try:
            return int(raw_pid)
        except ValueError:
            print(f"Ignoring invalid MAC_OVER_SPEAK_API_PID: {raw_pid}")
            return None

    def _terminate_pid(self, pid, label):
        try:
            os.kill(pid, 0)
        except OSError:
            return

        try:
            os.kill(pid, signal.SIGTERM)
            print(f"{label} terminated (PID: {pid}).")
        except OSError as e:
            print(f"Failed to terminate {label} PID {pid}: {e}")

    def language_polling_loop(self):
        def _loop():
            while True:
                is_preparing = getattr(self, "llm_status", "") in ["Starting...", "Warming up..."]
                lang = self.get_current_input_language()
                
                # We want to trigger when lang changes OR when preparing (for animation)
                if lang != getattr(self, "current_language_ui", None) or is_preparing:
                    # Don't update current_language_ui here, let _set_lang_text do it
                    # so that we detect the change correctly in the next loop
                    self.queue_task(lambda l=lang: self._set_lang_text(l))
                
                # Faster polling for more immediate response
                time.sleep(
                    0.15 
                    if self.is_recording or getattr(self, "is_processing", False) or is_preparing
                    else 0.35
                )

        threading.Thread(target=_loop, daemon=True).start()

    def _set_lang_text(self, lang):
        self.current_language_ui = lang
        self.update_tray_status(getattr(self, "current_ui_state", "HIDE"))

    def get_current_input_language(self):
        """Detect current macOS input method language by reading system plist directly."""
        try:
            # Read the plist file directly instead of spawning a 'defaults' process.
            # This is much faster and avoids Mach port messaging errors.
            plist_path = os.path.expanduser("~/Library/Preferences/com.apple.HIToolbox.plist")
            if not os.path.exists(plist_path):
                return "en"

            with open(plist_path, "rb") as f:
                pl = plistlib.load(f)
            
            selected_sources = pl.get("AppleSelectedInputSources", [])
            output = str(selected_sources)

            if any(
                x.lower() in output.lower()
                for x in [
                    "scim",
                    "itabc",
                    "pinyin",
                    "wubi",
                    "zhuyin",
                    "cangjie",
                    "stroke",
                    "chinese",
                    "pinyin.simplified",
                ]
            ):
                return "zh"
            if any(
                x.lower() in output.lower()
                for x in [
                    "kotoeri",
                    "japanese",
                    "romaji",
                    "kana",
                    "hiragana",
                    "katakana",
                ]
            ):
                return "ja"
            return "en"
        except Exception as e:
            # Fallback to subprocess if plist reading fails for any reason
            try:
                result = subprocess.run(
                    [
                        "defaults",
                        "read",
                        "com.apple.HIToolbox",
                        "AppleSelectedInputSources",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                output = result.stdout
                if "SCIM" in output or "Pinyin" in output or "Chinese" in output:
                    return "zh"
                if "Japanese" in output or "Kotoeri" in output:
                    return "ja"
            except:
                pass
            return "en"

    def start_ipc_server(self):
        # Create a custom handler class that can access the ASRClient instance
        class IPCRequestHandler(http.server.BaseHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                # Store reference to the ASRClient instance
                self.asr_client = kwargs.pop("asr_client", None)
                super().__init__(*args, **kwargs)

            def log_message(self, format, *args):
                pass

            def do_GET(self):
                if self.path == "/toggle":
                    if self.asr_client:
                        self.asr_client.queue_task(self.asr_client.toggle_recording)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(404)
                    self.end_headers()

        class IPCServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            # Pass the ASRClient instance to the handler
            self.ipc_server = IPCServer(
                ("127.0.0.1", 8334),
                lambda *args, **kwargs: IPCRequestHandler(
                    *args, asr_client=self, **kwargs
                ),
            )
            threading.Thread(target=self.ipc_server.serve_forever, daemon=True).start()
            print("IPC trigger listening at http://127.0.0.1:8334/toggle")
        except Exception as e:
            print(f"App is already running (IPC port in use). Exiting...")
            os._exit(1)

    def toggle_recording(self):
        if hasattr(self, "is_processing") and self.is_processing:
            return

        if self.is_recording:
            self.stop_and_process()
        else:
            self.start_recording()

    def ensure_backend_running(self):
        # Check if API is already responding
        try:
            status_url = self.config.get("status_url")
            if not status_url:
                status_url = "http://127.0.0.1:8333/status/"
            requests.get(status_url, timeout=1)
            print("Backend already running.")
            return
        except:
            pass

        print("Starting backend service...")
        log_path = os.path.expanduser("~/.mac_over_speak_backend.log")
        try:
            with open(log_path, "w") as log_file:
                # Pass "backend" as an argument to self-launch as backend
                if getattr(sys, "frozen", False):
                    # For macOS bundles, we need to be careful about environment variables
                    env = os.environ.copy()
                    # Ensure the binary can find its own libs if they are relative
                    self.backend_process = subprocess.Popen(
                        [sys.executable, "backend"],
                        stdout=log_file,
                        stderr=log_file,
                        env=env,
                    )
                else:
                    self.backend_process = subprocess.Popen(
                        [sys.executable, __file__, "backend"],
                        stdout=log_file,
                        stderr=log_file,
                    )
            print(
                f"Backend started (PID: {self.backend_process.pid}). Logs at {log_path}"
            )
        except Exception as e:
            print(f"Failed to start backend: {e}")
            with open(log_path, "a") as f:
                f.write(f"FATAL: Failed to start backend subprocess: {e}\n")

    def warmup_llm(self):
        self.llm_status = "Warming up..."
        self.update_rumps_menu()

        def _warmup():
            # Wait a few seconds for backend to boot if we just started it
            time.sleep(2)
            try:
                warmup_url = self.config.get("warmup_url")
                if not warmup_url:
                    warmup_url = "http://127.0.0.1:8333/warmup/"
                requests.get(warmup_url, timeout=300)
                self.llm_status = "Ready"
                print("LLM Warm-up successful.")
            except:
                self.llm_status = "Offline"
                print("LLM Warm-up failed or timed out.")
            self.queue_task(self.update_rumps_menu)
            self.queue_task(lambda: self.update_tray_status(getattr(self, "current_ui_state", "HIDE")))

        threading.Thread(target=_warmup, daemon=True).start()

    def setup_ui(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.current_ui_state = "HIDE"
        self.current_language_ui = "zh"

    def setup_rumps(self):
        self.app = rumps.App("MacOverSpeak", template=False)
        self.update_rumps_menu()
        self.update_rumps_icon("HIDE")

        # Timer to tick Tkinter main loop
        self.tk_timer = rumps.Timer(self.tick_tk, 0.05)
        self.tk_timer.start()

    def tick_tk(self, _):
        while True:
            try:
                task = self.task_queue.get_nowait()
                task()
            except queue.Empty:
                break
            except Exception as e:
                print(f"Task Queue Error: {e}")

        try:
            self.root.update()
        except tk.TclError:
            self.on_closing()
        except:
            pass

    def update_rumps_menu(self):
        self.app.menu.clear()
        self.app.menu.add(rumps.MenuItem(f"LLM: {self.llm_status}"))
        self.app.menu.add(rumps.MenuItem(f"Shortcut: {self.current_shortcut}"))
        self.app.menu.add(None)
        self.app.menu.add(
            rumps.MenuItem(
                "Toggle Recording", callback=lambda _: self.toggle_recording_safe()
            )
        )
        self.app.menu.add(
            rumps.MenuItem(
                "Clear ASR Memory", callback=lambda _: self.clear_asr_context()
            )
        )
        self.app.menu.add(
            rumps.MenuItem(
                "Hard Restart Service", callback=lambda _: self.queue_task(self.hard_restart)
            )
        )
        self.app.menu.add(
            rumps.MenuItem(
                "Settings...", callback=lambda _: self.queue_task(self.open_settings)
            )
        )
        self.app.menu.add(None)
        self.app.menu.add(rumps.MenuItem("Quit", callback=lambda _: self.on_closing()))

    def hard_restart(self):
        print("Hard restarting service...")
        import subprocess
        
        project_root = get_bundle_dir()
        start_sh = os.path.join(project_root, "start.sh")
        
        # Use single quotes for shell and shlex-like safety
        if getattr(sys, "frozen", False):
            # For bundled app
            script = f"sleep 1; open '{sys.executable}'"
        else:
            if os.path.exists(start_sh):
                # When running from source, it's safer to cd first
                script = f"sleep 1; cd '{project_root}'; bash start.sh"
            else:
                # Fallback to direct python script run
                script = f"sleep 1; cd '{project_root}'; '{sys.executable}' '{__file__}'"
                
        subprocess.Popen(script, shell=True, start_new_session=True)
        self.on_closing()

    def clear_asr_context(self):
        def _clear():
            try:
                clear_url = self.config.get("clear_url")
                if not clear_url:
                    clear_url = "http://127.0.0.1:8333/clear/"
                requests.get(clear_url, timeout=10)
                print("ASR model unloaded and memory cleared.")
                rumps.notification("MacOverSpeak", "Success", "ASR Memory Cleared")
            except Exception as e:
                print(f"Clear Context Error: {e}")
                rumps.notification("MacOverSpeak", "Error", f"Failed to clear context: {e}")

        threading.Thread(target=_clear, daemon=True).start()

    def update_rumps_icon(self, state, lang=None):
        if lang is None:
            lang = getattr(self, "current_language_ui", "zh")

        # Preparing state (Warming up)
        is_ready = getattr(self, "llm_status", "") == "Ready"
        is_preparing = getattr(self, "llm_status", "") in ["Starting...", "Warming up..."]
        
        colors = {
            "REC": "#FF3B30",
            "PROC": "#FFCC00",
            "TYPE": "#34C759",
            "HIDE": "#FFFFFF" if is_ready else "#AAAAAA",
        }
        color = colors.get(state, "#AAAAAA")
        # Generate a small image for the icon
        # Size 44x44 for higher DPI support internally by rumps
        width, height = 44, 44
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)

        # Draw main circle
        dc.ellipse([2, 2, 42, 42], fill=color)

        if state == "HIDE" and is_preparing:
            # Draw circular loading indicator
            angle = getattr(self, "loading_angle", 0)
            self.loading_angle = (angle + 36) % 360 # Smaller steps for smoother animation
            # Draw rotating arc
            dc.arc([10, 10, 34, 34], start=angle, end=angle+300, fill="white", width=4)
            
            # Force rumps to refresh by using alternating icon paths
            icon_index = getattr(self, "_icon_refresh_toggle", 0)
            self._icon_refresh_toggle = (icon_index + 1) % 2
            temp_icon = os.path.join(os.path.expanduser("~"), f".mac_over_speak_icon_{icon_index}.png")
            
            image.save(temp_icon)
            self.app.icon = temp_icon
            return

        # Draw language text
        # Mapping lang code to display character
        lang_char = {"zh": "中", "ja": "日", "en": "英"}.get(lang, "英")

        from PIL import ImageFont
        try:
            # Try to find a system font that supports CJK
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
            ]
            font = None
            for path in font_paths:
                if os.path.exists(path):
                    font = ImageFont.truetype(path, 28)
                    break
            if not font:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        # Calculate text position (center of icon)
        try:
            # Pillow 9.2.0+ uses getbbox/getlabel
            left, top, right, bottom = dc.textbbox((0, 0), lang_char, font=font)
            text_w = right - left
            text_h = bottom - top
            x = (width - text_w) / 2
            y = (height - text_h) / 2 - top # Offset by top to better center vertically
        except AttributeError:
            # Older Pillow
            text_w, text_h = dc.textsize(lang_char, font=font)
            x = (width - text_w) / 2
            y = (height - text_h) / 2

        # Draw character in white for visibility on colors, or black on yellow/white
        is_light_bg = state in ["PROC", "TYPE"] or (state == "HIDE" and is_ready)
        text_color = "black" if is_light_bg else "white"
        dc.text((x, y), lang_char, font=font, fill=text_color)

        # Force rumps to refresh by using alternating icon paths (bypass cache)
        icon_index = getattr(self, "_icon_refresh_toggle", 0)
        self._icon_refresh_toggle = (icon_index + 1) % 2
        temp_icon = os.path.join(os.path.expanduser("~"), f".mac_over_speak_icon_{icon_index}.png")
        
        image.save(temp_icon)
        self.app.icon = temp_icon

    def open_settings(self, is_launch=False):
        SettingsWindow(
            self.root,
            self.config,
            self.on_settings_saved,
            is_main_launch=is_launch,
            client=self,
        )

    def on_settings_saved(self):
        self.start_hotkey_listener()
        self.warmup_llm()

    def update_tray_status(self, state):
        self.update_rumps_icon(state, lang=self.current_language_ui)

    def start_hotkey_listener(self):
        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except:
                pass

        if hasattr(self, "shift_key_listener") and self.shift_key_listener:
            try:
                self.shift_key_listener.stop()
            except:
                pass

        def on_press(key):
            try:
                if (
                    key == keyboard.Key.shift
                    or key == keyboard.Key.shift_l
                    or key == keyboard.Key.shift_r
                ):
                    current_time = time.time()
                    if current_time - self.last_shift_press_time < 0.4:
                        self.toggle_recording_safe()
                        self.last_shift_press_time = 0
                    else:
                        self.last_shift_press_time = current_time
            except AttributeError:
                pass

        try:
            self.shift_key_listener = keyboard.Listener(on_press=on_press)
            self.shift_key_listener.start()
        except Exception as e:
            print(f"Shift Listener Error: {e}")

    def queue_task(self, func):
        self.task_queue.put(func)

    def schedule_task(self, ms, func):
        threading.Timer(ms / 1000.0, lambda: self.queue_task(func)).start()

    def toggle_recording_safe(self):
        self.queue_task(self.toggle_recording)

    def set_ui(self, state):
        self.queue_task(lambda: self._update_ui_internal(state))

    def _update_ui_internal(self, state):
        self.current_ui_state = state
        self.update_tray_status(state)

    def start_recording(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.limit_stop_requested = False
        self.recording_frame_count = 0
        self.set_ui("REC")

        sample_rate = int(self.config.get("sample_rate") or DEFAULT_CONFIG["sample_rate"])
        max_record_seconds = int(
            self.config.get("max_record_seconds")
            or DEFAULT_CONFIG["max_record_seconds"]
        )
        max_record_frames = sample_rate * max_record_seconds

        temp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        self.recording_file_path = temp_handle.name
        temp_handle.close()
        self.recording_wave = wave.open(self.recording_file_path, "wb")
        self.recording_wave.setnchannels(1)
        self.recording_wave.setsampwidth(2)
        self.recording_wave.setframerate(sample_rate)

        def callback(indata, frames, time, status):
            if status:
                print(f"[Record] Stream status: {status}")
            if not self.is_recording:
                return

            with self.recording_lock:
                if self.recording_wave is None:
                    return

                remaining_frames = max_record_frames - self.recording_frame_count
                if remaining_frames <= 0:
                    if not self.limit_stop_requested:
                        self.limit_stop_requested = True
                        self.queue_task(self.stop_and_process)
                    return

                chunk = indata[:remaining_frames] if frames > remaining_frames else indata
                self.recording_wave.writeframes(chunk.tobytes())
                self.recording_frame_count += len(chunk)

                if (
                    self.recording_frame_count >= max_record_frames
                    and not self.limit_stop_requested
                ):
                    self.limit_stop_requested = True
                    print(
                        f"[Record] Auto-stopping after reaching {max_record_seconds}s limit."
                    )
                    self.queue_task(self.stop_and_process)

        try:
            # Small delay to ensure previous stream is fully released by OS
            time.sleep(0.1)
            self.stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                callback=callback,
            )
            self.stream.start()
        except Exception as e:
            print(f"Audio Start Error: {e}")
            self.is_recording = False
            if hasattr(self, "stream") and self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except:
                    pass
                self.stream = None
            self._close_recording_file()
            self._cleanup_recording_file()
            self.set_ui("HIDE")

    def stop_and_process(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.is_processing = True
        self.set_ui("PROC")

        def _cleanup_and_start_processing():
            # Close stream in background to release hardware without blocking UI
            if hasattr(self, "stream") and self.stream:
                try:
                    print("[Stream] Stopping and closing stream...")
                    self.stream.abort()
                    self.stream.close()
                except Exception as e:
                    print(f"[Stream] Error closing stream: {e}")
                self.stream = None

            self._close_recording_file()
            
            # Start inference
            self._run_inference_and_type()

        processing_thread = threading.Thread(target=_cleanup_and_start_processing)
        processing_thread.daemon = True
        processing_thread.start()

    def _run_inference_and_type(self):
        temp_file = self.recording_file_path
        if not temp_file or not os.path.exists(temp_file):
            print("[Inference] No audio file captured.")
            self.is_processing = False
            self.set_ui("HIDE")
            return

        try:
            file_size = os.path.getsize(temp_file)
            if file_size <= 44:
                print("[Inference] Audio file is empty.")
                self.is_processing = False
                self.set_ui("HIDE")
                return

            # Detect language automatically from background polled state
            detected_lang = getattr(self, "current_language_ui", "en")
            print(
                f"[Inference] Starting API request. Lang: {detected_lang}, "
                f"frames: {self.recording_frame_count}, bytes: {file_size}"
            )

            with open(temp_file, "rb") as f:
                api_url = self.config.get("api_url")
                if not api_url:
                    api_url = "http://127.0.0.1:8333/transcribe/"
                r = requests.post(
                    api_url,
                    files={"audio": f},
                    data={"language": detected_lang},
                    timeout=30,
                )
                text = r.json().get("text", "")

            if text:
                print(f"[Inference] Text received: {text[:20]}...")
                self.set_ui("TYPE")
                # Offload clipboard and typing to background to avoid main thread jitter
                self._paste_text_background(text)
            else:
                print("[Inference] No text returned from API.")
                self.is_processing = False
                self.set_ui("HIDE")
        except Exception as e:
            print(f"[Inference] Error: {e}")
            self.is_processing = False
            self.set_ui("HIDE")
        finally:
            self._cleanup_recording_file()

    def _paste_text_background(self, text):
        def _paste_worker():
            try:
                # Use subprocess for clipboard
                import subprocess
                print("[Paste] Copying to clipboard...")
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
                
                # Small wait before typing
                time.sleep(0.1)
                
                print("[Paste] Injecting Cmd+V...")
                with self.keyboard_ctrl.pressed(keyboard.Key.cmd):
                    self.keyboard_ctrl.tap("v")
                
                print("[Paste] Success.")
            except Exception as e:
                print(f"[Paste] Error: {e}")
            
            # Use queue to update UI and state on main thread
            self.schedule_task(500, self._finalize_processing)

        threading.Thread(target=_paste_worker, daemon=True).start()

    def _finalize_processing(self):
        self.is_processing = False
        self.set_ui("HIDE")

    def _close_recording_file(self):
        with self.recording_lock:
            if self.recording_wave is None:
                return
            try:
                self.recording_wave.close()
            except Exception as e:
                print(f"[Record] Error closing WAV file: {e}")
            finally:
                self.recording_wave = None

    def _cleanup_recording_file(self):
        temp_file = self.recording_file_path
        self.recording_file_path = None
        self.recording_frame_count = 0
        self.limit_stop_requested = False
        if not temp_file:
            return
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception as e:
            print(f"[Record] Failed to remove temp audio file {temp_file}: {e}")

    def on_closing(self):
        if self._is_closing:
            return
        self._is_closing = True

        print("Shutting down...")
        if self.backend_process:
            try:
                self.backend_process.terminate()
                print(f"Backend terminated (PID: {self.backend_process.pid}).")
            except Exception as e:
                print(f"Failed to terminate backend subprocess: {e}")
        elif self.external_backend_pid:
            self._terminate_pid(self.external_backend_pid, "API service")

        try:
            self.root.destroy()
        except Exception:
            pass

        rumps.quit_application()

        # Fallback force quit to guarantee start.sh proceeds to API kill
        def force_quit():
            time.sleep(1)
            os._exit(0)

        threading.Thread(target=force_quit, daemon=True).start()


if __name__ == "__main__":
    # Check if we should run as backend
    if len(sys.argv) > 1 and sys.argv[1] == "backend":
        print("Backend Process Starting...")
        # Add project root to path for api module imports
        project_root = get_bundle_dir()
        if project_root not in sys.path:
            sys.path.append(project_root)

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
        try:
            from django.core.management import execute_from_command_line

            execute_from_command_line(
                [sys.argv[0], "runserver", "127.0.0.1:8333", "--noreload"]
            )
        except Exception as e:
            print(f"Backend Error: {e}")
            sys.exit(1)
    else:
        # Run as UI Client
        client = ASRClient()
        print("\n[!] Mac Over Speak Active")
        print("    Hotkey: Double Tap Shift\n")
        client.app.run()
