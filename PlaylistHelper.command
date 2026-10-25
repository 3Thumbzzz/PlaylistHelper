#!/bin/bash
# Launch PlaylistHelper from source on macOS (double-click in Finder).
# The first run creates a private Python environment in .venv and installs the packages.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
    echo "or use the ready-made PlaylistHelper.dmg instead."
    read -r -n 1 -p "Press any key to close."
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Setting up (first run only)..."
    python3 -m venv .venv || { read -r -n 1 -p "Could not create .venv. Press any key."; exit 1; }
fi
if ! .venv/bin/python -c "import PySide6, requests, ytmusicapi, pyrekordbox" 2>/dev/null; then
    .venv/bin/python -m pip install -r requirements.txt || { read -r -n 1 -p "Install failed. Press any key."; exit 1; }
fi

exec .venv/bin/python playlist_helper.py
