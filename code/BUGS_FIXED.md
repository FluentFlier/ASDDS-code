# ASDDS Bug Report & Fixes

All issues found in the PyPro codebase during audit, with the fixes applied.

---

## CRITICAL — Data Integrity

### 1. Massive log duplication (all detector scripts)
**Bug:** While a bee is sleeping, `log_sleep_period()` is called **every frame** once
`MIN_SLEEP_DURATION` is met. The `LOG_INTERVAL` throttle only prevents writes every 120 s,
but each write records the **same** `start_time` with a progressively longer `duration_seconds`.
This means a single 8-hour sleep bout generates ~240 near-duplicate entries.

**Evidence from your logs:**
- `sleep_log_20260214.json`: 720 entries, **717 duplicate start_times**
- `sleep_log_20251126.json`: 510 entries, **509 duplicates**
- `sleep_log_20250116.json`: 434 entries, **433 duplicates**

**Fix:** Added `log_sleep_end()` — a separate method called exactly once when the bee
transitions from sleeping → active. The running `log_sleep_period()` still fires every
`LOG_INTERVAL` for liveness, but now the authoritative duration is the `bout_complete: true`
entry written at wake-up.

### 2. `max_motion` always 100.0 (all detector scripts)
**Bug:** The background subtractor (`MOG2`) produces near-100% motion on its very first
frames as it initializes. Since `max_motion` is a running global maximum starting at 0.0,
it locks to 100.0 within the first second and never recovers.

**Evidence:** Every single log file across 120+ sessions shows `"max": 100.0`.

**Fix:** Added a `WARMUP_FRAMES = 90` (~3 s at 30 fps) constant. Min/max tracking is
skipped until frame_count exceeds this threshold.

### 3. Corrupt log files from non-atomic writes
**Bug:** The write pattern is read-all → append → write-all. If the process is killed
mid-write (power loss, SIGKILL, OOM), the JSON file is truncated/corrupted.

**Evidence:** `sleep_log_20250115.json` and `sleep_log_20250124.json` fail to parse.

**Fix:** Writes now go to a `tempfile.mkstemp()` temp file, then `os.replace()` (POSIX
atomic rename) moves it into place. On failure, falls back to direct write. Corrupt files
are renamed to `.bak` instead of silently discarded.

---

## HIGH — Functional Bugs

### 4. Historical `MIN_SLEEP_DURATION` regime and comment drift
**Bug:** Historical disruption versions used a short confirmation/logging regime,
and later copies contained comments that still described 10 seconds even after
the handoff constants had been standardized to 120 seconds. This made the
current runtime configuration and historical data regime easy to conflate.

**Fix:** The current handoff scripts use **120 seconds** and their comments now
match the code. The rescue pipeline separately identifies the 11 historical
short-regime files and applies the same strict timestamp-derived `>120 seconds`
analysis filter to them. Historical regime labels are preserved in the audit.

### 5. `program_launcher.sh` — off-by-one and missing handler
**Bug:** The PROGRAMS array has 4 entries, but input validation accepts `1-5`:
```bash
if [[ "$prog_num" =~ ^[1-5]$ ]]; then
```
Selecting 5 causes an empty `prog_name` and `python3 ""` error.

Also: `sunset_start.py` requires a start-time input (just like `scotophase_disrupt.py`),
but the launcher only pipes input for `scotophase_disrupt.py`. Running `sunset_start.py`
through the launcher hangs waiting for stdin.

**Fix:** Validation now uses `NUM_PROGRAMS` dynamically. Added an `elif` block for
`sunset_start.py` that prompts for and pipes the start time.

### 6. No signal handling → GPIO left HIGH on kill
**Bug:** If the process receives SIGTERM (e.g., `kill`, system shutdown, `systemctl stop`),
the `try/finally` block only catches exceptions — SIGTERM is not caught, so GPIO pins
remain in their last state. On the Jetson, this means the solenoid could stay energized.

**Fix:** All scripts now register `signal.signal(SIGINT, ...)` and
`signal.signal(SIGTERM, ...)` handlers that set a `_shutdown_requested` flag. The main
loop checks this flag and exits cleanly through the `finally` block.

---

## MEDIUM — Performance & Code Quality

### 7. O(n) `list.pop(0)` on motion_buffer
**Bug:** `motion_buffer` is a plain `list`, and `pop(0)` is O(n) — shifting all remaining
elements. At 30 fps with a 120-second buffer, that's up to ~3,600 elements shifted per frame.

**Fix:** Changed `motion_buffer` to `collections.deque` and replaced `pop(0)` with
`popleft()` (O(1)).

### 8. Unused variable `current_range`
**Bug:** `current_range = self.max_motion - self.min_motion` is computed in
`analyze_frame()` in `cont_disrupt.py` and `led_sleep_detect.py` but never used.

**Fix:** Removed.

### 9. No camera-failure retry
**Bug:** A single failed `cap.read()` (`ret == False`) breaks the entire loop. Transient
I2C glitches on the CSI bus are common on Jetson and shouldn't terminate the experiment.

**Fix:** Added a `consecutive_failures` counter with `MAX_CAMERA_RETRIES = 5`. Only
exits after 5 consecutive failures.

---

## LOW — Logging & Observability

### 10. All output via `print()` — no timestamps, no levels, no file log
**Fix:** Replaced all `print()` calls with Python's `logging` module. Each script now
creates:
- **Console handler** (INFO+) for real-time terminal output with timestamps
- **File handler** (DEBUG+) writing to
  `~/Desktop/bee_motion_logs/detector_<mode>_<timestamp>.log`

### 11. `graph.py` — no file validation
**Bug:** If the user selects a non-JSON file or an empty file, the error message is an
unhelpful Python traceback inside a messagebox.

**Fix:** Added pre-validation in `_add_bee()`: checks file exists, is valid JSON, and
contains a non-empty array before accepting.

### 12. `gpiodemo.py` — no cleanup on exit
**Bug:** Ctrl+C during the blink loop leaves the LED in whatever state it was in.

**Fix:** Added signal handler and `finally` block that sets LED LOW and calls
`GPIO.cleanup()`.

---

## Summary of files changed

| File | Changes |
|---|---|
| `led_sleep_detect.py` | Logging, signals, warmup, deque, atomic writes, bout-end logging, camera retry |
| `cont_disrupt.py` | Same as above + fixed comment on MIN_SLEEP_DURATION |
| `scotophase_disrupt.py` | Same + solenoid end > start validation, solenoid state transition logging |
| `sunset_start.py` | Same + solenoid state transition logging |
| `graph.py` | Logging, file validation, explicit matplotlib backend, merge-interval bugfix |
| `program_launcher.sh` | Fixed 1-5→1-4 range, added sunset_start.py input handling, shellcheck-clean |
| `led_blink/gpiodemo.py` | Signal handling, GPIO cleanup |
