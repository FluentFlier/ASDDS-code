#!/bin/bash
# Read-only preflight checks for the ASDDS Jetson handoff bundle.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failures=0

check_import() {
    local module="$1"
    local label="$2"
    if python3 -c "import ${module}" >/dev/null 2>&1; then
        echo "PASS  Python module: ${label}"
    else
        echo "FAIL  Python module missing: ${label}"
        failures=$((failures + 1))
    fi
}

echo "ASDDS Jetson preflight"
echo "Bundle: $SCRIPT_DIR"
python3 --version
echo ""

check_import "cv2" "OpenCV (cv2)"
check_import "numpy" "NumPy"
check_import "Jetson.GPIO" "Jetson.GPIO"
check_import "matplotlib" "Matplotlib (automatic graphing)"

if python3 -m py_compile \
    "$SCRIPT_DIR/led_sleep_detect_clean.py" \
    "$SCRIPT_DIR/sleep_bout_state.py" \
    "$SCRIPT_DIR/auto_graph.py" \
    "$SCRIPT_DIR/cont_disrupt.py" \
    "$SCRIPT_DIR/scotophase_disrupt.py" \
    "$SCRIPT_DIR/sunset_start.py" \
    "$SCRIPT_DIR/bee_sleep_detect_revised_sessionfile.py"; then
    echo "PASS  Python source compiles"
else
    echo "FAIL  Python source compile check"
    failures=$((failures + 1))
fi

if bash -n "$SCRIPT_DIR/program_launcher.sh"; then
    echo "PASS  Launcher shell syntax"
else
    echo "FAIL  Launcher shell syntax"
    failures=$((failures + 1))
fi

if bash -n \
    "$SCRIPT_DIR/launch_asdds.sh" \
    "$SCRIPT_DIR/install_desktop_icon.sh" \
    "$SCRIPT_DIR/setup_jetson.sh"; then
    echo "PASS  Desktop launcher shell syntax"
else
    echo "FAIL  Desktop launcher shell syntax"
    failures=$((failures + 1))
fi

if command -v gst-inspect-1.0 >/dev/null 2>&1 \
    && gst-inspect-1.0 nvarguscamerasrc >/dev/null 2>&1; then
    echo "PASS  CSI camera GStreamer source is installed"
else
    echo "WARN  nvarguscamerasrc was not detected; CSI camera operation still needs a hardware check"
fi

if [ -z "${DISPLAY:-}" ]; then
    echo "WARN  DISPLAY is unset; the detector's live OpenCV window cannot open in this shell"
else
    echo "PASS  DISPLAY is set ($DISPLAY)"
fi

echo ""
if [ "$failures" -eq 0 ]; then
    echo "Preflight passed. Camera, GPIO pins, LED, and solenoid still require an on-device bench test."
    exit 0
fi

echo "Preflight failed with $failures missing or invalid requirement(s)."
exit 1
