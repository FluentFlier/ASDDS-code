# ASDDS Jetson Nano handoff

This folder is a self-contained runtime handoff. The recommended detector is
`led_sleep_detect_clean.py` (launcher option 2). Its detection logic is split
between that file and `sleep_bout_state.py`, so both files must stay together.

## Automated setup (recommended)

There are now two guided setup scripts:

- On the Mac, extract the handoff ZIP and run `bash PyPro/setup_mac.sh`. It
  creates the SSH key, copies this folder, invokes the Jetson installer,
  stores the key in the macOS Keychain, configures the `ssh asdds-jetson`
  shortcut, and prepares remote backups. Local Mac tools such as VS Code and
  Codex can then use that same SSH connection when you ask them to.
- On the Jetson, `bash ~/PyPro/setup_jetson.sh` installs packages, enables SSH,
  installs the desktop icon, configures Tailscale, and runs preflight.

The Mac must be able to reach an already-running SSH server on the Jetson for
the first copy. If SSH is not enabled yet, run these three commands once in a
local Jetson terminal, then run the Mac script:

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
```

Sudo password entry and browser approval of the Tailscale login remain
interactive by design; neither password nor account token is stored.

The setup enables `ssh` and `tailscaled` as boot services and assigns the
Tailscale machine name `asdds-jetson`, so it reconnects after normal shutdowns
and reboots. The Mac installer also opens the Tailscale Machines page and asks
you to disable key expiry for this trusted Jetson. That one browser choice is
required for long-lived unattended access; revoke the device immediately if
the Jetson is lost or replaced.

## Copy to the Jetson

From another computer, copy the entire `PyPro` folder to the Jetson user's
home directory. For example:

```bash
scp -r PyPro jetson@JETSON_IP:~/PyPro
```

On the Jetson:

```bash
cd ~/PyPro
chmod +x program_launcher.sh launch_asdds.sh install_desktop_icon.sh check_jetson.sh auto_graph.py
bash check_jetson.sh
bash install_desktop_icon.sh
```

The installer creates **ASDDS Bee Sleep Launcher** on the Jetson desktop. If
Ubuntu displays an untrusted-launcher warning, right-click the icon and choose
**Allow Launching** once. Double-clicking the icon then opens the program
launcher in a terminal and keeps that terminal open long enough to read the
final status.

JetPack normally supplies OpenCV, NumPy, the CSI-camera GStreamer components,
and Jetson.GPIO. Automatic PNG graphing additionally needs Matplotlib:

```bash
sudo apt-get update
sudo apt-get install python3-matplotlib
```

Do not replace JetPack's OpenCV with the generic `opencv-python` pip wheel;
the JetPack build supplies the GStreamer support used by the CSI camera.

## Start and stop an experiment

Run the launcher from the Jetson desktop session:

```bash
bash ~/PyPro/program_launcher.sh
```

Choose option 2 for the July 21 revised clean-bout detector. Press `q` in the
camera window to end normally. `Ctrl+C` and `SIGTERM` also request a safe
shutdown and turn the GPIO output off.

The launcher reports the detector's real exit status. After the program ends,
it automatically graphs the run-date JSON when that file exists. Outputs are:

- JSON: `~/Desktop/bee_motion_logs/sleep_log_YYYYMMDD.json`
- detector log: `~/Desktop/bee_motion_logs/detector_clean_*.log`
- automatic PNG: `~/Desktop/bee_motion_logs/graphs/sleep_log_YYYYMMDD_summary.png`

Only completed bouts are written to the MATLAB-compatible JSON. If the
experiment is stopped while a bee is still sleeping, that interrupted bout is
documented in the detector log but is not presented as a completed bout in the
JSON or graph.

## Graph an existing file manually

The graph utility is headless and does not need Tkinter or an open window:

```bash
python3 ~/PyPro/auto_graph.py \
  ~/Desktop/bee_motion_logs/sleep_log_20260721.json
```

It makes a noon-to-noon sleep timeline, shades the default 18:00-06:00
scotophase, and summarizes bout count, total sleep, and longest bout. It also
de-duplicates same-start snapshots from older JSON logs before plotting.

## Handoff file map

- `led_sleep_detect_clean.py`: recommended camera/GPIO detector.
- `sleep_bout_state.py`: tested state machine and atomic JSON writer required by the detector.
- `program_launcher.sh`: interactive launcher and automatic graph hook.
- `launch_asdds.sh`: terminal wrapper used by the desktop shortcut.
- `install_desktop_icon.sh`: installs and trusts the desktop shortcut.
- `ASDDS Program Launcher.desktop`: Ubuntu desktop-entry definition.
- `setup_jetson.sh`: complete Jetson dependency, service, icon, and Tailscale setup.
- `setup_mac.sh`: guided Mac deployment, SSH-key, alias, and remote-editing setup.
- `auto_graph.py`: non-interactive end-of-run PNG generator.
- `cont_disrupt.py`, `scotophase_disrupt.py`, `sunset_start.py`: legacy experimental modes retained by the launcher.
- `bee_sleep_detect_revised_sessionfile.py`: earlier session-file detector retained as launcher option 5; option 2 is the handoff recommendation.
- `check_jetson.sh`: dependency and source preflight.

## Verification boundary

The source, state transitions, JSON persistence, graph logic, and launcher
syntax are tested off-device. The CSI camera, GPIO numbering, LED, and solenoid
must be bench-tested on the actual Jetson because those devices are not
available in this workspace.
