import threading
import time
import requests
import sounddevice as sd
import scipy.io.wavfile as wav
import pyautogui
import tkinter as tk
from tkinter import ttk
import numpy as np
import os
import json
from pynput import mouse, keyboard

# macOS 核心库支持 (用于追踪焦点光标位置)
try:
    from AppKit import NSWorkspace
    from Quartz import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        AXUIElementCopyParameterizedAttributeValue,
        kAXFocusedUIElementAttribute,
        kAXSelectedTextRangeAttribute,
        kAXBoundsForRangeParameterizedAttribute,
        AXValueGetValue,
        kAXValueCGRectType
    )
    HAS_PYOBJC = True
except ImportError:
    HAS_PYOBJC = False

# --- CONFIGURATION DEFAULTS ---
DEFAULT_CONFIG = {
    "api_url": "http://127.0.0.1:8333/transcribe/",
    "warmup_url": "http://127.0.0.1:8333/warmup/",
    "hotkey_start": "<f5>",
    "hotkey_stop": "<esc>",
    "language": "zh",
    "sample_rate": 16000
}
CONFIG_FILE = os.path.expanduser("~/.mac_over_speak_config.json")

class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except Exception as e:
                print(f"Load Config Error: {e}")

    def save(self):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Save Config Error: {e}")

    def get(self, key):
        return self.config.get(key)

    def set(self, key, value):
        self.config[key] = value
        self.save()

class SettingsWindow:
    def __init__(self, parent, config_manager, on_save_callback):
        self.window = tk.Toplevel(parent)
        self.window.title("Mac Over Speak Settings")
        self.window.geometry("400x350")
        self.config_manager = config_manager
        self.on_save_callback = on_save_callback
        
        self.setup_ui()

    def setup_ui(self):
        frame = ttk.Frame(self.window, padding="20")
        frame.pack(fill="both", expand=True)

        # API URL
        ttk.Label(frame, text="API URL:").grid(row=0, column=0, sticky="w", pady=5)
        self.api_url_var = tk.StringVar(value=self.config_manager.get("api_url"))
        ttk.Entry(frame, textvariable=self.api_url_var, width=30).grid(row=0, column=1, pady=5)

        # Hotkeys
        ttk.Label(frame, text="Start Hotkey (e.g. <f5>):").grid(row=1, column=0, sticky="w", pady=5)
        self.hotkey_start_var = tk.StringVar(value=self.config_manager.get("hotkey_start"))
        ttk.Entry(frame, textvariable=self.hotkey_start_var, width=15).grid(row=1, column=1, sticky="w", pady=5)

        ttk.Label(frame, text="Stop Hotkey (e.g. <esc>):").grid(row=2, column=0, sticky="w", pady=5)
        self.hotkey_stop_var = tk.StringVar(value=self.config_manager.get("hotkey_stop"))
        ttk.Entry(frame, textvariable=self.hotkey_stop_var, width=15).grid(row=2, column=1, sticky="w", pady=5)

        # Language
        ttk.Label(frame, text="Language (zh/en):").grid(row=3, column=0, sticky="w", pady=5)
        self.lang_var = tk.StringVar(value=self.config_manager.get("language"))
        ttk.Entry(frame, textvariable=self.lang_var, width=10).grid(row=3, column=1, sticky="w", pady=5)

        # Warm-up Button
        ttk.Button(frame, text="Warm-up LLM Now", command=self.trigger_warmup).grid(row=4, column=0, columnspan=2, pady=15)

        # Save Button
        ttk.Button(frame, text="Save & Restart Listeners", command=self.save).grid(row=5, column=0, columnspan=2, pady=10)
        
        ttk.Label(frame, text="* Hotkey format: <f5>, <cmd>+<alt>+s, etc.", font=("", 10, "italic")).grid(row=6, column=0, columnspan=2)

    def trigger_warmup(self):
        warmup_url = self.config_manager.get("warmup_url")
        threading.Thread(target=lambda: requests.get(warmup_url, timeout=300)).start()
        print("Warm-up request sent.")

    def save(self):
        self.config_manager.set("api_url", self.api_url_var.get())
        self.config_manager.set("hotkey_start", self.hotkey_start_var.get())
        self.config_manager.set("hotkey_stop", self.hotkey_stop_var.get())
        self.config_manager.set("language", self.lang_var.get())
        self.on_save_callback()
        self.window.destroy()

class ASRClient:
    def __init__(self):
        self.config = ConfigManager()
        self.is_recording = False
        self.audio_data = []
        self.keyboard_ctrl = keyboard.Controller() 
        self.hotkey_listener = None
        
        if HAS_PYOBJC:
            self.ax_system_wide = AXUIElementCreateSystemWide()
        
        self.setup_ui()
        self.start_hotkey_listener()
        
        # Async Warm-up on start
        self.warmup_llm()

    def warmup_llm(self):
        def _warmup():
            try:
                requests.get(self.config.get("warmup_url"), timeout=300)
                print("LLM Warm-up successful.")
            except:
                print("LLM Warm-up failed or timed out.")
        threading.Thread(target=_warmup, daemon=True).start()

    def setup_ui(self):
        self.root = tk.Tk()
        self.root.withdraw()
        
        # Create a simple menu or way to open settings
        # On macOS, we could use a status bar icon, but for now a simple hotkey to open settings?
        # Let's just provide a manual way to call it if needed, or open it on first run.

        self.indicator = tk.Toplevel(self.root, takefocus=0)
        self.indicator.title("ASR_DOT")
        self.indicator.overrideredirect(True)
        self.indicator.attributes("-topmost", True)
        
        try:
            self.indicator.tk.call('::tk::unsupported::MacWindowStyle', 'style', self.indicator._w, 'help', 'no-shadow')
        except:
            pass

        self.indicator.attributes("-alpha", 0.0)
        self.dot_size = 14
        self.indicator.geometry(f"{self.dot_size}x{self.dot_size}+0+0")
        
        self.canvas = tk.Canvas(self.indicator, width=self.dot_size, height=self.dot_size, 
                                highlightthickness=0, borderwidth=0)
        self.canvas.pack()
        self.dot = self.canvas.create_oval(0, 0, self.dot_size, self.dot_size, fill="#FF3B30", outline="")

        self.update_position_loop()

    def open_settings(self):
        SettingsWindow(self.root, self.config, self.start_hotkey_listener)

    def start_hotkey_listener(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()

        hotkeys = {
            self.config.get("hotkey_start"): self.safe_start_recording,
            self.config.get("hotkey_stop"): self.safe_stop_and_process,
            "<cmd>+,": self.open_settings # Fixed hotkey for settings
        }
        
        print(f"Registering hotkeys: {hotkeys}")
        self.hotkey_listener = keyboard.GlobalHotKeys(hotkeys)
        self.hotkey_listener.start()

    def safe_start_recording(self):
        self.root.after(0, self.start_recording)

    def safe_stop_and_process(self):
        self.root.after(0, self.stop_and_process)

    def update_position_loop(self):
        target_x, target_y = -1, -1
        if HAS_PYOBJC:
            try:
                system_wide = self.ax_system_wide
                ret, focused_element = AXUIElementCopyAttributeValue(system_wide, kAXFocusedUIElementAttribute, None)
                if ret == 0:
                    ret, selected_range = AXUIElementCopyAttributeValue(focused_element, kAXSelectedTextRangeAttribute, None)
                    if ret == 0:
                        ret, rect_value = AXUIElementCopyParameterizedAttributeValue(
                            focused_element, kAXBoundsForRangeParameterizedAttribute, selected_range, None
                        )
                        if ret == 0:
                            import corefoundation
                            ok, rect = AXValueGetValue(rect_value, kAXValueCGRectType, None)
                            if ok:
                                screen_h = self.root.winfo_screenheight()
                                target_x = rect.origin.x
                                target_y = screen_h - rect.origin.y - rect.size.height + 25 
            except:
                pass

        if target_x != -1:
            self.indicator.geometry(f"+{int(target_x)}+{int(target_y)}")
        
        self.root.after(30, self.update_position_loop)

    def set_ui(self, state):
        self.root.after(0, lambda: self._update_ui_internal(state))

    def _update_ui_internal(self, state):
        themes = {
            "REC": "#FF3B30",
            "PROC": "#FFCC00",
            "TYPE": "#34C759",
        }
        if state in themes:
            self.canvas.itemconfig(self.dot, fill=themes[state])
            self.indicator.attributes("-alpha", 0.9)
        else:
            self.indicator.attributes("-alpha", 0.0)
        self.indicator.update_idletasks()

    def start_recording(self):
        if self.is_recording: return
        self.is_recording = True
        self.audio_data = []
        self.set_ui("REC")
        
        def callback(indata, frames, time, status):
            if self.is_recording:
                self.audio_data.append(indata.copy())

        try:
            self.stream = sd.InputStream(samplerate=self.config.get("sample_rate"), channels=1, callback=callback)
            self.stream.start()
        except Exception as e:
            print(f"Audio Start Error: {e}")
            self.is_recording = False
            self.set_ui("HIDE")

    def stop_and_process(self):
        if not self.is_recording: return
        self.is_recording = False
        try:
            self.stream.stop()
            self.stream.close()
        except:
            pass
        self.set_ui("PROC")
        processing_thread = threading.Thread(target=self._run_inference_and_type)
        processing_thread.daemon = True
        processing_thread.start()

    def _run_inference_and_type(self):
        if not self.audio_data:
            self.set_ui("HIDE")
            return
        try:
            temp_file = "input.wav"
            wav_data = np.concatenate(self.audio_data)
            wav.write(temp_file, self.config.get("sample_rate"), wav_data)
            
            with open(temp_file, 'rb') as f:
                r = requests.post(self.config.get("api_url"), 
                                 files={'audio': f}, 
                                 data={'language': self.config.get("language")}, 
                                 timeout=15)
                text = r.json().get('text', '')
            
            if text:
                self.set_ui("TYPE")
                self.root.after(200, lambda: self._paste_text_in_main_thread(text))
            else:
                self.set_ui("HIDE")
        except Exception as e:
            print(f"Task Error: {e}")
            self.set_ui("HIDE")

    def _paste_text_in_main_thread(self, text):
        import subprocess
        try:
            subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
            self.root.after(100, self._trigger_paste_in_main_thread)
        except Exception as e:
            print(f"Clipboard Error: {e}")
            self.set_ui("HIDE")

    def _trigger_paste_in_main_thread(self):
        try:
            with self.keyboard_ctrl.pressed(keyboard.Key.cmd):
                self.keyboard_ctrl.tap('v')
        except Exception as e:
            print(f"Keyboard injection Error: {e}")
        self.root.after(500, lambda: self.set_ui("HIDE"))

if __name__ == "__main__":
    client = ASRClient()
    print("\n[!] Mac Over Speak Active")
    print(f"    Start: {client.config.get('hotkey_start')} | Stop: {client.config.get('hotkey_stop')}")
    print("    Settings: Cmd+Alt+, (逗号)")
    print("    确保已授予辅助功能权限。\n")
    client.root.mainloop()

