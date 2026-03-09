#!/bin/bash

# Mac Over Speak - DMG Build Script
# This script automates the process of bundling the Python application into a macOS .app
# and then creating a standard .dmg installer.

set -e

PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT"

# Initialize shell for conda activate
eval "$(conda shell.bash hook)"
conda activate qwen3-asr

# 1. Clean up previous builds
echo "--- Starting Build Process (Conda: qwen3-asr) ---"
echo "🧹 Cleaning up old build artifacts..."
rm -rf client/build client/dist client/*.dmg build dist *.dmg

# 2. Build the .app bundle with PyInstaller
echo "📦 Building the application bundle (.app)..."
cd client
python3 -m PyInstaller --clean MacOverSpeak.spec

# 3. Create the DMG installer with dmgbuild
echo "💿 Creating the DMG installer..."
# We use dmgbuild which reads the configuration from dmg_settings.py
# The background is set to 'builtin-arrow' and it creates a symlink to /Applications
python3 -m dmgbuild -s dmg_settings.py "Mac Over Speak" ../MacOverSpeak.dmg

cd "$PROJECT_ROOT"

echo "✅ Build Complete!"
echo "📂 Installer created: $PROJECT_ROOT/MacOverSpeak.dmg"
echo "🚀 You can now distribute this DMG file."
