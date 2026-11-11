#!/bin/bash
# Guided Mac-to-Jetson deployment and remote-access setup for ASDDS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_PATH="$HOME/.ssh/id_ed25519_asdds_jetson"
SSH_ALIAS="asdds-jetson"
SSH_OPTIONS=(-o ConnectTimeout=12 -o ServerAliveInterval=30)

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script is intended to run from macOS."
    exit 1
fi

for required_file in setup_jetson.sh program_launcher.sh led_sleep_detect_clean.py; do
    if [ ! -f "$SCRIPT_DIR/$required_file" ]; then
        echo "Missing $required_file beside setup_mac.sh."
        echo "Extract the complete handoff ZIP before running this script."
        exit 1
    fi
done

echo ""
echo "ASDDS Mac setup"
echo "This first connection must be made while the Mac can reach the Jetson on its LAN."
echo "On the Jetson, run 'whoami' and 'hostname -I' if you need these values."
echo ""

read -rp "Jetson username: " JETSON_USER
read -rp "Jetson LAN IP or .local hostname: " JETSON_HOST

if [ -z "$JETSON_USER" ] || [ -z "$JETSON_HOST" ]; then
    echo "Username and host are required."
    exit 1
fi

REMOTE_TARGET="$JETSON_USER@$JETSON_HOST"

echo ""
echo "Preparing Tailscale on this Mac for access outside the lab..."
if [ ! -d "/Applications/Tailscale.app" ]; then
    open "https://tailscale.com/download/mac"
    echo "Install Tailscale from the page that just opened and sign in."
else
    open -a Tailscale >/dev/null 2>&1 || true
    echo "Make sure the Tailscale menu-bar app is signed in."
fi
read -rp "When Mac Tailscale is installed and signed in, press Enter to continue... " _unused

echo ""
echo "[1/7] Checking the initial SSH connection..."
if ! ssh "${SSH_OPTIONS[@]}" "$REMOTE_TARGET" 'echo "Connected to $(hostname) as $(id -un)"'; then
    echo ""
    echo "Could not reach the Jetson over SSH. On the Jetson, run:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y openssh-server"
    echo "  sudo systemctl enable --now ssh"
    echo "Then rerun this Mac script."
    exit 1
fi

echo "[2/7] Creating and installing a dedicated SSH key..."
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [ ! -f "$KEY_PATH" ]; then
    ssh-keygen -t ed25519 -f "$KEY_PATH" -C "Mac access to ASDDS Jetson"
fi

# Store the encrypted key in the logged-in user's macOS Keychain/ssh-agent so
# local tools such as VS Code and Codex can reuse it without blocking on an
# interactive passphrase prompt for every connection.
if ! ssh-add --apple-use-keychain "$KEY_PATH" 2>/dev/null; then
    ssh-add -K "$KEY_PATH" 2>/dev/null || ssh-add "$KEY_PATH"
fi

ssh "${SSH_OPTIONS[@]}" "$REMOTE_TARGET" \
    'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; read -r key; grep -qxF "$key" ~/.ssh/authorized_keys || printf "%s\n" "$key" >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys' \
    < "$KEY_PATH.pub"

KEYED_SSH=(ssh -i "$KEY_PATH" "${SSH_OPTIONS[@]}")
"${KEYED_SSH[@]}" "$REMOTE_TARGET" 'echo "SSH key authentication passed"'

echo "[3/7] Backing up the current Jetson program folder..."
"${KEYED_SSH[@]}" "$REMOTE_TARGET" \
    'if [ -d ~/PyPro ]; then cp -a ~/PyPro ~/PyPro.backup.$(date +%Y%m%d_%H%M%S); fi'

echo "[4/7] Copying the complete ASDDS handoff to the Jetson..."
rsync -av --progress \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    -e "ssh -i $KEY_PATH -o ConnectTimeout=12" \
    "$SCRIPT_DIR/" \
    "$REMOTE_TARGET:~/PyPro/"

echo "[5/7] Running the complete Jetson installer..."
echo "The Jetson may ask for its sudo password and print a Tailscale sign-in URL."
ssh -tt -i "$KEY_PATH" "${SSH_OPTIONS[@]}" "$REMOTE_TARGET" \
    'bash ~/PyPro/setup_jetson.sh'

tailscale_address=$("${KEYED_SSH[@]}" "$REMOTE_TARGET" \
    'tailscale ip -4 2>/dev/null | head -n 1' || true)
if [ -n "$tailscale_address" ]; then
    echo "Testing the Jetson Tailscale route at $tailscale_address..."
    if ssh -i "$KEY_PATH" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        "$JETSON_USER@$tailscale_address" true; then
        PERMANENT_HOST="$tailscale_address"
    else
        echo "Tailscale is not reachable from this Mac yet; using the LAN host for now."
        PERMANENT_HOST="$JETSON_HOST"
        tailscale_address=""
    fi
else
    PERMANENT_HOST="$JETSON_HOST"
fi

echo "[6/7] Creating the permanent '$SSH_ALIAS' Mac SSH shortcut..."
mkdir -p "$HOME/.ssh/config.d"
chmod 700 "$HOME/.ssh/config.d"
SSH_ENTRY="$HOME/.ssh/config.d/asdds-jetson.conf"
{
    echo "Host $SSH_ALIAS"
    echo "    HostName $PERMANENT_HOST"
    echo "    User $JETSON_USER"
    echo "    IdentityFile $KEY_PATH"
    echo "    AddKeysToAgent yes"
    echo "    UseKeychain yes"
    echo "    ServerAliveInterval 30"
    echo "    ServerAliveCountMax 3"
} > "$SSH_ENTRY"
chmod 600 "$SSH_ENTRY"

SSH_CONFIG="$HOME/.ssh/config"
touch "$SSH_CONFIG"
chmod 600 "$SSH_CONFIG"
if ! grep -Eq '^[[:space:]]*Include[[:space:]]+~/.ssh/config.d/\*' "$SSH_CONFIG"; then
    temporary_config=$(mktemp "$HOME/.ssh/config.asdds.XXXXXX")
    {
        echo "Include ~/.ssh/config.d/*"
        cat "$SSH_CONFIG"
    } > "$temporary_config"
    chmod 600 "$temporary_config"
    mv "$temporary_config" "$SSH_CONFIG"
fi

ssh -o ConnectTimeout=15 "$SSH_ALIAS" 'echo "Permanent SSH shortcut passed"'

if [ -n "$tailscale_address" ]; then
    echo ""
    echo "For durable unattended access, disable key expiry for the trusted Jetson."
    echo "The Tailscale Machines page will open. Find 'asdds-jetson', open its"
    echo "three-dot menu, and choose 'Disable key expiry'."
    open "https://login.tailscale.com/admin/machines"
    read -rp "After disabling key expiry for asdds-jetson, press Enter... " _unused
fi

echo "[7/7] Preparing Mac tools and backup folders..."
mkdir -p "$HOME/Documents/ASDDS_Jetson_Backups/bee_motion_logs"

if command -v code >/dev/null 2>&1; then
    code --install-extension ms-vscode-remote.remote-ssh >/dev/null || true
else
    echo "VS Code's 'code' command was not found. Install the Remote - SSH extension"
    echo "from VS Code if you want graphical remote editing."
fi

echo ""
echo "Mac setup complete."
echo "Connect: ssh $SSH_ALIAS"
echo "Jetson files: /home/$JETSON_USER/PyPro"
echo "Pull results:"
echo "  rsync -av --progress $SSH_ALIAS:~/Desktop/bee_motion_logs/ $HOME/Documents/ASDDS_Jetson_Backups/bee_motion_logs/"
echo ""
if [ -n "$tailscale_address" ]; then
    echo "The SSH shortcut uses the Jetson Tailscale address: $tailscale_address"
else
    echo "The SSH shortcut currently uses the LAN host: $JETSON_HOST"
    echo "After Tailscale is authorized, rerun setup_mac.sh to switch it automatically."
fi
