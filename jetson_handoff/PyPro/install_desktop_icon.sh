#!/bin/bash
# Install the ASDDS program launcher icon for the current Jetson user.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_DIR="$HOME/PyPro"
DESKTOP_DIR="$HOME/Desktop"
SOURCE_ENTRY="$SCRIPT_DIR/ASDDS Program Launcher.desktop"
DEST_ENTRY="$DESKTOP_DIR/ASDDS Program Launcher.desktop"

if [ "$SCRIPT_DIR" != "$EXPECTED_DIR" ]; then
    echo "This bundle must be located at $EXPECTED_DIR before installing the icon."
    echo "Current location: $SCRIPT_DIR"
    exit 1
fi

if [ ! -f "$SOURCE_ENTRY" ]; then
    echo "Desktop shortcut template is missing: $SOURCE_ENTRY"
    exit 1
fi

mkdir -p "$DESKTOP_DIR"
install -m 755 "$SOURCE_ENTRY" "$DEST_ENTRY"
chmod +x "$SCRIPT_DIR/program_launcher.sh" "$SCRIPT_DIR/launch_asdds.sh"

# GNOME/Nautilus may require the launcher to be explicitly trusted. This is
# best-effort because older Jetson desktop releases do not expose this command.
if command -v gio >/dev/null 2>&1; then
    gio set "$DEST_ENTRY" metadata::trusted true >/dev/null 2>&1 || true
fi

echo "Desktop icon installed: $DEST_ENTRY"
echo "If Ubuntu asks whether to trust it, right-click the icon and select 'Allow Launching'."
