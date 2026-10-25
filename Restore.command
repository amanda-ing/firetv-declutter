#!/bin/bash
# macOS: double-click to undo everything firetv-declutter changed on your Fire TV.
cd "$(dirname "$0")" || exit 1
exec python3 firetv_declutter.py --restore
