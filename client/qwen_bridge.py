import http.server
import json
import os
import queue
import socketserver
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np
import requests
import rumps
import scipy.io.wavfile as wav
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
        self.audio_data = []
        self.keyboard_ctrl = keyboard.Controller()
        self.hotkey_listener = None
        self.shift_key_listener = None
        self.last_shift_press_time = 0
        self.backend_process = None

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

    def language_polling_loop(self):
        def _loop():
            while True:
                lang = self.get_current_input_language()
                if lang != getattr(self, "current_language_ui", None):
                    self.current_language_ui = lang
                    self.queue_task(lambda l=lang: self._set_lang_text(l))
                time.sleep(
                    0.5
                    if self.is_recording or getattr(self, "is_processing", False)
                    else 1.5
                )

        threading.Thread(target=_loop, daemon=True).start()

    def _set_lang_text(self, lang):
        if lang == "zh":
            text = "中"
        elif lang == "ja":
            text = "日"
        else:
            text = "英"
        if hasattr(self, "lang_text"):
            self.canvas.itemconfig(self.lang_text, text=text)

    def get_current_input_language(self):
        """Detect current macOS input method language."""
        try:
            # Query the global AppleSelectedInputSources to detect the system-level input method.
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
            if any(
                x in output
                for x in [
                    "SCIM",
                    "ITABC",
                    "Pinyin",
                    "Wubi",
                    "Zhuyin",
                    "Cangjie",
                    "Stroke",
                    "Chinese",
                ]
            ):
                return "zh"
            if any(
                x in output
                for x in [
                    "Kotoeri",
                    "Japanese",
                    "Romaji",
                    "Kana",
                    "Hiragana",
                    "Katakana",
                ]
            ):
                return "ja"
            return "en"
        except Exception as e:
            return "en"  # Default to en if not clearly zh

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

        threading.Thread(target=_warmup, daemon=True).start()

    def setup_ui(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.indicator = tk.Toplevel(self.root, takefocus=0)
        self.indicator.title("ASR_DOT")
        self.indicator.overrideredirect(True)
        self.indicator.attributes("-topmost", True)

        try:
            # Safely access the Tk widget ID, with fallback for different environments
            widget_id = getattr(self.indicator, "_w", None)
            if widget_id is not None:
                self.indicator.tk.call(
                    "::tk::unsupported::MacWindowStyle",
                    "style",
                    widget_id,
                    "help",
                    "no-shadow",
                )
            else:
                # Alternative approach if _w is not available
                self.indicator.tk.call(
                    "::tk::unsupported::MacWindowStyle",
                    "style",
                    str(self.indicator.winfo_id()),
                    "help",
                    "no-shadow",
                )
        except:
            pass

        self.indicator.attributes("-alpha", 0.0)
        self.ind_w = 48
        self.ind_h = 24
        self.indicator.geometry(f"{self.ind_w}x{self.ind_h}+0+0")

        self.indicator.config(bg="#3a3a3c")

        self.canvas = tk.Canvas(
            self.indicator,
            width=self.ind_w,
            height=self.ind_h,
            highlightthickness=0,
            borderwidth=0,
            bg="#3a3a3c",
        )
        self.canvas.pack()

        # Draw status dot
        dot_r = 5
        self.dot = self.canvas.create_oval(
            7,
            self.ind_h / 2 - dot_r,
            7 + dot_r * 2,
            self.ind_h / 2 + dot_r,
            fill="#FF3B30",
            outline="",
        )

        # Draw language text (e.g. 中 / 英)
        self.lang_text = self.canvas.create_text(
            24,
            self.ind_h / 2,
            text="中",
            fill="white",
            font=("System", 13, "bold"),
            anchor="w",
        )
        self.current_language_ui = "zh"

    def setup_rumps(self):
        self.app = rumps.App("MacOverSpeak", template=True)
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
                "Clear ASR Context", callback=lambda _: self.clear_asr_context()
            )
        )
        self.app.menu.add(
            rumps.MenuItem(
                "Settings...", callback=lambda _: self.queue_task(self.open_settings)
            )
        )
        self.app.menu.add(None)
        self.app.menu.add(rumps.MenuItem("Quit", callback=lambda _: self.on_closing()))

    def clear_asr_context(self):
        def _clear():
            try:
                clear_url = self.config.get("clear_url")
                if not clear_url:
                    clear_url = "http://127.0.0.1:8333/clear/"
                requests.get(clear_url, timeout=10)
                print("ASR context and memory cleared.")
                rumps.notification("MacOverSpeak", "Success", "ASR Context Cleared")
            except Exception as e:
                print(f"Clear Context Error: {e}")
                rumps.notification("MacOverSpeak", "Error", f"Failed to clear context: {e}")

        threading.Thread(target=_clear, daemon=True).start()

    def update_rumps_icon(self, state):
        colors = {
            "REC": "#FF3B30",
            "PROC": "#FFCC00",
            "TYPE": "#34C759",
            "HIDE": "#AAAAAA",
        }
        color = colors.get(state, "#AAAAAA")
        # Generate a small image for the icon
        width, height = 32, 32
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        dc.ellipse([4, 4, 28, 28], fill=color)

        temp_icon = os.path.join(os.path.expanduser("~"), ".mac_over_speak_icon.png")
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
        self.update_rumps_icon(state)

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
        themes = {
            "REC": "#FF3B30",
            "PROC": "#FFCC00",
            "TYPE": "#34C759",
        }
        if state in themes:
            self.canvas.itemconfig(self.dot, fill=themes[state])
            self.indicator.attributes("-alpha", 0.95)
            self.update_tray_status(state)
        else:
            self.indicator.attributes("-alpha", 0.0)
            self.update_tray_status("HIDE")
        self.indicator.update_idletasks()

    def start_recording(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.audio_data = []
        self.set_ui("REC")

        def callback(indata, frames, time, status):
            if self.is_recording:
                self.audio_data.append(indata.copy())

        try:
            # Small delay to ensure previous stream is fully released by OS
            time.sleep(0.1)
            self.stream = sd.InputStream(
                samplerate=self.config.get("sample_rate"), channels=1, callback=callback
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
                    self.stream.stop()
                    self.stream.close()
                except Exception as e:
                    print(f"[Stream] Error closing stream: {e}")
                self.stream = None
            
            # Start inference
            self._run_inference_and_type()

        processing_thread = threading.Thread(target=_cleanup_and_start_processing)
        processing_thread.daemon = True
        processing_thread.start()

    def _run_inference_and_type(self):
        if not self.audio_data:
            print("[Inference] No audio data captured.")
            self.is_processing = False
            self.set_ui("HIDE")
            return
        
        try:
            temp_file = os.path.join(os.path.expanduser("~"), "input_asr.wav")
            wav_data = np.concatenate(self.audio_data)
            wav.write(temp_file, self.config.get("sample_rate"), wav_data)

            # Detect language automatically from background polled state
            detected_lang = getattr(self, "current_language_ui", "en")
            print(f"[Inference] Starting API request. Lang: {detected_lang}")

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

    def on_closing(self):
        print("Shutting down...")
        if self.backend_process:
            try:
                self.backend_process.terminate()
                print("Backend terminated.")
            except:
                pass

        try:
            self.root.destroy()
        except:
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
