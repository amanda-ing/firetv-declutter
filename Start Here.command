#!/bin/bash
# macOS: double-click to declutter your Fire TV.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is needed. Install it from https://www.python.org/downloads/ (or accept macOS's offer to install developer tools), then try again."
  read -r -p "Press Enter to close. " _; exit 1
fi
exec python3 firetv_declutter.py "$@"
