# Mac Over Speak 🎙️

An AI-powered ASR (Automatic Speech Recognition) tool for macOS, designed to provide a faster and more accurate "Speak to Type" experience than the system's built-in dictation.

## 🏗️ Architecture

The project uses a **Two-Process Architecture** to ensure smooth performance:

*   **`client/` (The Face)**: A lightweight UI (Python/Tkinter) that manages recording, global hotkeys, and simulates keyboard typing.
*   **`api/` (The Brain)**: A Django-based engine that hosts the **Qwen3-ASR** model. It handles the resource-heavy AI transcription.

> [!NOTE]
> Running the **client** will automatically detect and start the **api** in the background if it's not already running. This separation allows the UI to stay responsive while the AI model works.

## 🚀 Key Features

- **Qwen3-ASR Integration**: High-accuracy speech recognition.
- **Local Native Support**: Runs entirely on your Mac.
- **Global Hotkeys**: Configurable keyboard triggers for hands-free typing. 
- **Non-blocking UI**: Floating status indicator for real-time feedback.

## ⚙️ Installation & Setup

Before running or building the project, ensure you have the necessary dependencies installed in your Conda environment:

```bash
# Create and activate environment (if not already done)
conda create -n qwen3-asr python=3.12
conda activate qwen3-asr

# Install dependencies
pip install -r requirements.txt

# Install system dependencies (required for sounddevice)
brew install portaudio
```

## 📦 Build & Packaging (.dmg)

We provide a one-click build script to generate a standard macOS `.dmg` installer. This script automates the concatenation of PyInstaller bundling and DMG creation.

### One-Click Build
Simply run the following command from the project root:

```bash
./build_dmg.sh
```
This will generate **`MacOverSpeak.dmg`** in the project root.

### Manual Steps (Under the hood)

If you need to perform the steps manually, follow this process:

1. **Build the App Bundle (`.app`)**:
   ```bash
   cd client
   python3 -m PyInstaller --clean MacOverSpeak.spec
   ```
2. **Create the DMG Installer**:
   ```bash
   cd client
   python3 -m dmgbuild -s dmg_settings.py "Mac Over Speak" ../MacOverSpeak.dmg
   ```

**Project Configuration Files:**
*   **`client/MacOverSpeak.spec`**: Configures PyInstaller to include data files (like the API server) and sets app metadata.
*   **`client/dmg_settings.py`**: Defines the DMG's appearance, background, and icon positions.
*   **`requirements.txt`**: Contains the full list of frozen dependencies for the `qwen3-asr` environment.

---

## 🛠️ Troubleshooting

### "Trace/BPT trap: 5" or "Process not trusted"
If the program crashes with this error when you click "Record" in settings, it means macOS is blocking the keyboard listener for security.

**The Fix:**
1.  Open **System Settings** > **Privacy & Security**.
2.  Go to **Accessibility**.
3.  Ensure your **Terminal** (or iTerm2/VS Code) is toggled **ON**.
4.  Also check **Input Monitoring** (usually right below Accessibility) and ensure your Terminal is toggled **ON** there as well.
5.  If it's already ON, try removing it (using the minus `-` button) and adding it back.
6.  **Restart your Terminal** before running the script again.

> [!IMPORTANT]
> This is a standard macOS security requirement for any app that listens for global hotkeys.

> [!TIP]
> Make sure you have `portaudio` installed (`brew install portaudio`) before building, as `sounddevice` depends on it.