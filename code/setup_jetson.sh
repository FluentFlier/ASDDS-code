#!/bin/bash
# Complete ASDDS setup for a Jetson Nano.
# Run as the normal desktop user from ~/PyPro, not with sudo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_TAILSCALE=true

for argument in "$@"; do
    case "$argument" in
        --skip-tailscale)
            INSTALL_TAILSCALE=false
            ;;
        --help)
            echo "Usage: bash setup_jetson.sh [--skip-tailscale]"
            exit 0
            ;;
        *)
            echo "Unknown option: $argument"
            exit 2
            ;;
    esac
done

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this script as the normal Jetson desktop user, not with sudo."
    echo "The script will request sudo only for system installation steps."
    exit 1
fi

if [ "$SCRIPT_DIR" != "$HOME/PyPro" ]; then
    echo "This setup expects the handoff folder at: $HOME/PyPro"
    echo "Current folder: $SCRIPT_DIR"
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer requires the Ubuntu/Debian apt-get package manager."
    exit 1
fi

echo ""
echo "ASDDS Jetson setup"
echo "User: $(id -un)"
echo "Host: $(hostname)"
echo "Folder: $SCRIPT_DIR"
echo ""

echo "[1/6] Installing required Ubuntu packages..."
sudo apt-get update
sudo apt-get install -y \
    openssh-server \
    avahi-daemon \
    unzip \
    rsync \
    tmux \
    curl \
    ca-certificates \
    python3-matplotlib

echo "[2/6] Enabling remote-access services..."
sudo systemctl enable --now ssh
sudo systemctl enable --now avahi-daemon

if command -v ufw >/dev/null 2>&1 \
    && sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
    sudo ufw allow OpenSSH
fi

echo "[3/6] Preparing ASDDS files and output folders..."
chmod +x \
    "$SCRIPT_DIR/program_launcher.sh" \
    "$SCRIPT_DIR/launch_asdds.sh" \
    "$SCRIPT_DIR/install_desktop_icon.sh" \
    "$SCRIPT_DIR/check_jetson.sh" \
    "$SCRIPT_DIR/auto_graph.py" \
    "$SCRIPT_DIR/setup_jetson.sh"
mkdir -p "$HOME/Desktop/bee_motion_logs/graphs"

echo "[4/6] Installing the desktop launcher..."
bash "$SCRIPT_DIR/install_desktop_icon.sh"

if [ "$INSTALL_TAILSCALE" = true ]; then
    echo "[5/6] Installing secure anywhere-access with Tailscale..."
    if ! command -v tailscale >/dev/null 2>&1; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    sudo systemctl enable --now tailscaled

    current_tailscale_address=$(tailscale ip -4 2>/dev/null | head -n 1 || true)
    if [ -z "$current_tailscale_address" ]; then
        echo "Tailscale needs authorization. Open the URL printed below on your Mac."
        sudo tailscale up
    fi
    sudo tailscale set --hostname=asdds-jetson
else
    echo "[5/6] Tailscale skipped by request."
fi

echo "[6/6] Running the ASDDS preflight..."
preflight_status=0
bash "$SCRIPT_DIR/check_jetson.sh" || preflight_status=$?

echo ""
echo "ASDDS setup summary"
echo "Local username: $(id -un)"
echo "Local hostname: $(hostname)"
echo "LAN address(es): $(hostname -I 2>/dev/null || true)"
if command -v tailscale >/dev/null 2>&1; then
    tailscale_address=$(tailscale ip -4 2>/dev/null | head -n 1 || true)
    if [ -n "$tailscale_address" ]; then
        echo "Tailscale address: $tailscale_address"
        echo "Tailscale name: asdds-jetson"
    else
        echo "Tailscale address: not authorized yet"
    fi
fi
echo "Desktop icon: $HOME/Desktop/ASDDS Program Launcher.desktop"
echo "Results folder: $HOME/Desktop/bee_motion_logs"
echo "Boot services: ssh=$(systemctl is-enabled ssh 2>/dev/null || true), tailscaled=$(systemctl is-enabled tailscaled 2>/dev/null || true)"

if [ "$preflight_status" -ne 0 ]; then
    echo ""
    echo "Setup completed, but the preflight found a missing requirement."
    echo "Resolve the FAIL line(s) above before running an experiment."
    exit "$preflight_status"
fi

echo ""
echo "Setup complete. The CSI camera, LED, and solenoid still need an on-device bench test."
exit 0
