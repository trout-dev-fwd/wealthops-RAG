#!/usr/bin/env bash
# Build WealthOps Assistant as a single-file executable with PyInstaller.
# Run from the repo root: ./build.sh
# Output: dist/WealthOps Assistant[.exe]

set -euo pipefail

pip install pyinstaller --quiet

pyinstaller \
  --onefile \
  --windowed \
  --name "WealthOps Assistant" \
  --icon app/assets/icon.ico \
  --add-data "app/assets/dollar.gif:assets" \
  app/main.py

echo ""
echo "Build complete: dist/WealthOps Assistant"
