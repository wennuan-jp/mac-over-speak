# How to use 
open System settings -> Privacy & Security -> Microphone -> Terminal -> ON
open System settings -> Privacy & Security -> Accessibility -> Terminal -> ON
open System settings -> Privacy & Security -> Accessibility -> add this app -> ON


Building a bridge between MBP M4 (MacOS) and Qwen3 ASR service

---

### Phase 1: Environment & Dependencies

Since I'm on Apple Silicon (M4), I'll need the native versions of these libraries for the best performance.

- [X] 1. **Install system-level dependencies:**
```bash
brew install portaudio # Required for microphone access
```


- [X] 2. **Install Python libraries:**
```bash
conda activate qwen3-asr

pip install pynput sounddevice scipy requests pyautogui

```



---

### Phase 2: The Core Logic Components

#### 1. The Hotkey & Mouse Listener

On macOS, `pynput` is the standard for global listeners.  "Forward" key on a mouth-operated mouse is typically interpreted by macOS as `Button.x1` or `Button.x2`.

#### 2. The UI Indicator (HUD)

We will use a specialized `tkinter` configuration. By using `overrideredirect(True)` and `wm_attributes("-topmost", True)`, we create a floating "pill" at the top of your screen that shows the current state.

---

### Phase 3: The Complete Implementation Script

Save this as `qwen_bridge.py`. Replace `YOUR_ENDPOINT_URL` with your actual Qwen3 service address.

```python
import threading
import time
import requests
import sounddevice as sd
import scipy.io.wavfile as wav
import pyautogui
import tkinter as tk
from pynput import mouse, keyboard

# --- CONFIGURATION ---
API_URL = "http://localhost:8333/transcribe/"
SAMPLE_RATE = 16000
TEMP_FILE = "input.wav"

class ASRClient:
    def __init__(self):
        self.is_recording = False
        self.audio_data = []
        self.setup_ui()
        
    def setup_ui(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        # Position: Center Top
        w, h = 180, 35
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        self.root.geometry(f"{w}x{h}+{x}+40")
        
        self.label = tk.Label(self.root, text="READY", fg="white", font=("Arial", 10, "bold"))
        self.label.pack(expand=True, fill="both")
        self.root.withdraw() # Start hidden

    def set_ui(self, state):
        themes = {
            "REC": ("#FF3B30", "● RECORDING"), # Red
            "PROC": ("#FFCC00", "⚙ PROCESSING"), # Yellow
            "TYPE": ("#34C759", "✔ TYPING"),      # Green
        }
        if state in themes:
            bg, txt = themes[state]
            self.root.deiconify()
            self.root.configure(bg=bg)
            self.label.configure(bg=bg, text=txt)
        else:
            self.root.withdraw()
        self.root.update()

    def start_recording(self):
        if self.is_recording: return
        self.is_recording = True
        self.audio_data = []
        self.set_ui("REC")
        
        def callback(indata, frames, time, status):
            if self.is_recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback)
        self.stream.start()

    def stop_and_process(self):
        if not self.is_recording: return
        self.is_recording = False
        self.stream.stop()
        self.set_ui("PROC")
        
        # Save & Send
        import numpy as np
        wav_data = np.concatenate(self.audio_data)
        wav.write(TEMP_FILE, SAMPLE_RATE, wav_data)
        
        try:
            with open(TEMP_FILE, 'rb') as f:
                r = requests.post(API_URL, files={'file': f}, data={'language': 'zh'})
                text = r.json().get('text', '')
            
            if text:
                self.set_ui("TYPE")
                pyautogui.write(text) # Injects text into active widget
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(0.5)
        self.set_ui("HIDE")

client = ASRClient()

# --- INPUT LISTENERS ---
def on_click(x, y, button, pressed):
    # Mouse Button 4 (Forward) is usually Button.x1
    if button == mouse.Button.x1:
        client.start_recording() if pressed else client.stop_and_process()

def on_key(key):
    # Logic for Control + F5
    if key == keyboard.Key.f5:
        # Check for control modifier here or use keyboard.GlobalHotKeys
        pass

# Start listeners in background
mouse_listener = mouse.Listener(on_click=on_click)
mouse_listener.start()

# Keep UI alive
client.root.mainloop()

```

---

### Phase 4: Permissions (Crucial for M4 Macs)

When you run the script for the first time, it will fail or hang unless you do the following:

1. **Microphone:** Go to *System Settings > Privacy & Security > Microphone*. Ensure your **Terminal** or **IDE** is toggled **ON**.
2. **Accessibility:** Go to *System Settings > Privacy & Security > Accessibility*. Add your **Terminal/IDE**. This is required for `pyautogui` to "type" for you.
3. **Input Monitoring:** Required for the global hotkey/mouse listener to work while the script is in the background.

---

### Final Polish Steps

* **The "Forward" Key:** If `mouse.Button.x1` doesn't trigger, run a small script to `print(button)` inside `on_click` to see exactly what your mouth-operated device identifies as.
* **Active Widget:** `pyautogui.write()` works by simulating keyboard presses. Make sure your text cursor is blinking in the target widget *before* you finish speaking.

**Would you like me to show you how to wrap this into a `.app` bundle so it stays in your Menu Bar and starts automatically on boot?**
---

### Packaging & Distribution

To build the standalone `.app` bundle and the `.dmg` installer, follow the instructions in the [main README](../../README.md#📦-build--packaging-dmg).

**Key files for building:**
*   `MacOverSpeak.spec`: PyInstaller configuration.
*   `dmg_settings.py`: dmgbuild appearance settings.