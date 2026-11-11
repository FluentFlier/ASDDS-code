#!/bin/bash
# program_launcher.sh — Interactive launcher for ASDDS bee-sleep scripts
# Run from the Jetson:  bash ~/PyPro/program_launcher.sh

set -euo pipefail

# Use the folder containing this launcher.  This keeps a copied handoff bundle
# self-contained while still allowing an override for bench testing.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROG_DIR="${ASDDS_PROG_DIR:-$SCRIPT_DIR}"
LOG_DIR="${ASDDS_LOG_DIR:-$HOME/Desktop/bee_motion_logs}"

PROGRAMS=(
    "cont_disrupt.py"
    "led_sleep_detect_clean.py"
    "scotophase_disrupt.py"
    "sunset_start.py"
    "bee_sleep_detect_revised_sessionfile.py"
)
NUM_PROGRAMS=${#PROGRAMS[@]}

# --------------------------------------------------------------------------
validate_time() {
    local t="$1"
    # Accept HH:MMAM/PM  (e.g. 06:05PM, 12:00AM)
    if [[ ! "$t" =~ ^(0[1-9]|1[0-2]):([0-5][0-9])(AM|PM)$ ]]; then
        return 1
    fi
    return 0
}

# --------------------------------------------------------------------------
if [ -t 1 ] && command -v clear >/dev/null 2>&1; then
    clear
fi
echo "╔══════════════════════════════════╗"
echo "║   ASDDS  Program  Launcher      ║"
echo "╚══════════════════════════════════╝"
echo ""
for i in "${!PROGRAMS[@]}"; do
    echo "  $((i+1)). ${PROGRAMS[i]}"
done
echo ""

# Prompt for program number (1..NUM_PROGRAMS)
while true; do
    read -rp "Enter program number (1-${NUM_PROGRAMS}): " prog_num
    if [[ "$prog_num" =~ ^[0-9]+$ ]] && (( prog_num >= 1 && prog_num <= NUM_PROGRAMS )); then
        break
    fi
    echo "  Invalid — enter a number between 1 and ${NUM_PROGRAMS}."
done

prog_index=$((prog_num - 1))
prog_name="${PROGRAMS[prog_index]}"
prog_path="$PROG_DIR/$prog_name"

if [ ! -f "$prog_path" ]; then
    echo "Error: $prog_name not found at $prog_path"
    exit 1
fi

echo ""
echo "▶  Launching: $prog_name"
echo ""
run_date=$(date +%Y%m%d)

# The selected program's exit status is handled below.  Temporarily disable
# errexit so cleanup, graph generation, and the final status message always run.
set +e

# --------------------------------------------------------------------------
# scotophase_disrupt.py needs start AND end time
if [ "$prog_name" = "scotophase_disrupt.py" ]; then
    while true; do
        read -rp "  Solenoid START time (HH:MMAM/PM, e.g. 06:05PM): " start_time
        validate_time "$start_time" && break
        echo "  Invalid format — use HH:MMAM/PM."
    done
    while true; do
        read -rp "  Solenoid END   time (HH:MMAM/PM, e.g. 06:30PM): " end_time
        validate_time "$end_time" && break
        echo "  Invalid format — use HH:MMAM/PM."
    done
    echo -e "${start_time}\n${end_time}" | python3 "$prog_path"

# sunset_start.py needs start time only
elif [ "$prog_name" = "sunset_start.py" ]; then
    while true; do
        read -rp "  Solenoid START time (HH:MMAM/PM, e.g. 06:05PM): " start_time
        validate_time "$start_time" && break
        echo "  Invalid format — use HH:MMAM/PM."
    done
    echo "${start_time}" | python3 "$prog_path"

# Other programs — no interactive input needed
else
    python3 "$prog_path"
fi

# --------------------------------------------------------------------------
program_exit=$?

# Create a graph automatically from the run-date JSON.  Graphing is best-effort
# and never hides a detector failure or changes its exit status.
graph_script="$PROG_DIR/auto_graph.py"
graph_input="$LOG_DIR/sleep_log_${run_date}.json"
graph_exit=0
if [ -f "$graph_script" ] && [ -f "$graph_input" ]; then
    echo ""
    echo "Creating end-of-run graph..."
    python3 "$graph_script" "$graph_input"
    graph_exit=$?
elif [ ! -f "$graph_script" ]; then
    echo ""
    echo "⚠  Automatic graph skipped: $graph_script is missing."
else
    echo ""
    echo "ℹ  Automatic graph skipped: no sleep log was created for ${run_date}."
fi

if [ $graph_exit -ne 0 ]; then
    echo "⚠  The experiment data remains intact, but graph generation failed."
fi

if [ $program_exit -ne 0 ]; then
    echo ""
    echo "⚠  $prog_name exited with code $program_exit"
    exit "$program_exit"
else
    echo ""
    echo "✓  $prog_name completed."
fi

exit 0
