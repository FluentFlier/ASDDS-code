#!/usr/bin/env python3
"""
cont_disrupt.py — Continuous sleep-disruption mode.

Historical continuous-disruption detector using GPIO pin 18 for the LED.
The current handoff version uses the same 120-second confirmation duration as
the other current detector modes. Older experiment files may come from a prior
short-confirmation regime and are labeled separately by the rescue pipeline.

GPIO Pin: 18 (BOARD) — LED
"""

import cv2
import numpy as np
from datetime import datetime
import json
import os
import sys
import signal
import tempfile
import logging
from collections import deque

import Jetson.GPIO as GPIO

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(log_dir: str) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("bee_cont_disrupt")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FMT, datefmt=DATE_FMT))
    logger.addHandler(ch)

    log_file = os.path.join(
        log_dir, f"detector_cont_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FMT, datefmt=DATE_FMT))
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------
class CaliBeeMotionDetector:
    LED_PIN = 18
    SLEEP_THRESHOLD = 0.005
    MIN_SLEEP_DURATION = 120       # seconds of low motion required
    LOG_INTERVAL = 120
    WARMUP_FRAMES = 90
    MAX_CAMERA_RETRIES = 5
    MOTION_HISTORY_LEN = 300

    def __init__(self):
        self.log_dir = os.path.expanduser("~/Desktop/bee_motion_logs")
        self.logger = _setup_logging(self.log_dir)
        self.logger.info("Initialising CaliBeeMotionDetector (continuous disruption)")

        # --- GPIO ----------------------------------------------------------
        try:
            GPIO.setmode(GPIO.BOARD)
            GPIO.setup(self.LED_PIN, GPIO.OUT, initial=GPIO.LOW)
            self.logger.info("GPIO pin %d configured (LED)", self.LED_PIN)
        except Exception as exc:
            self.logger.critical("GPIO setup failed: %s", exc)
            raise

        # --- Background subtractor -----------------------------------------
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=15, detectShadows=False
        )

        # --- State ---------------------------------------------------------
        self.current_sleep_start = None
        self.motion_buffer: deque = deque()
        self.last_log_time = None
        self.motion_history: deque = deque(maxlen=self.MOTION_HISTORY_LEN)
        self.max_motion = 0.0
        self.min_motion = float("inf")
        self.frame_count = 0
        self._shutdown_requested = False

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ------------------------------------------------------------------
    def _signal_handler(self, signum, _frame):
        self.logger.warning("Received %s — shutting down", signal.Signals(signum).name)
        self._shutdown_requested = True

    def _cleanup(self, cap=None):
        self.logger.info("Cleaning up resources…")
        try:
            GPIO.output(self.LED_PIN, GPIO.LOW)
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
        if cap:
            try:
                cap.release()
            except Exception:
                pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        self.logger.info("Cleanup complete.")

    # ------------------------------------------------------------------
    def set_led_state(self, is_sleeping: bool):
        try:
            GPIO.output(self.LED_PIN, GPIO.HIGH if is_sleeping else GPIO.LOW)
        except Exception as exc:
            self.logger.error("GPIO write failed: %s", exc)

    # ------------------------------------------------------------------
    def analyze_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        mask = self.bg_subtractor.apply(blurred, learningRate=0.01)

        motion_pixels = cv2.countNonZero(mask)
        motion_intensity = (motion_pixels / mask.size) * 100

        self.motion_history.append(motion_intensity)

        if self.frame_count >= self.WARMUP_FRAMES:
            self.max_motion = max(self.max_motion, motion_intensity)
            if self.min_motion == float("inf"):
                self.min_motion = motion_intensity
            else:
                self.min_motion = min(self.min_motion, motion_intensity)

        avg_motion = float(np.mean(self.motion_history))

        info_lines = [
            f"Motion: {motion_intensity:.5f}%",
            f"Range: {self.min_motion:.5f}% - {self.max_motion:.5f}%",
            f"Avg(10s): {avg_motion:.5f}%",
            f"Thresh: {self.SLEEP_THRESHOLD:.5f}%",
        ]
        for i, line in enumerate(info_lines):
            cv2.putText(mask, line, (10, 25 + i * 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2)

        return mask, motion_intensity, avg_motion

    # ------------------------------------------------------------------
    # Atomic JSON logging
    # ------------------------------------------------------------------
    def _log_file_path(self) -> str:
        return os.path.join(
            self.log_dir, f"sleep_log_{datetime.now().strftime('%Y%m%d')}.json"
        )

    def _read_log(self, path: str) -> list:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return []
        try:
            with open(path, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError) as exc:
            self.logger.warning("Corrupt log %s (%s) — backing up", path, exc)
            backup = path + f".bak.{datetime.now().strftime('%H%M%S')}"
            try:
                os.rename(path, backup)
            except OSError:
                pass
            return []

    def _write_log_atomic(self, path: str, logs: list):
        dir_name = os.path.dirname(path)
        try:
            fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(logs, fh, indent=4)
            os.replace(tmp, path)
        except Exception as exc:
            self.logger.error("Atomic write failed: %s", exc)
            try:
                with open(path, "w") as fh:
                    json.dump(logs, fh, indent=4)
            except Exception as exc2:
                self.logger.error("Fallback write failed: %s", exc2)

    def log_sleep_period(self, start_time, end_time, avg_motion):
        if (self.last_log_time is not None
                and (end_time - self.last_log_time).total_seconds() < self.LOG_INTERVAL):
            return

        log_entry = {
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round((end_time - start_time).total_seconds(), 3),
            "average_motion": round(avg_motion, 8),
            "motion_range": {
                "min": round(float(self.min_motion), 6) if self.min_motion != float("inf") else None,
                "max": round(float(self.max_motion), 6),
            },
        }

        path = self._log_file_path()
        logs = self._read_log(path)
        logs.append(log_entry)
        self._write_log_atomic(path, logs)
        self.last_log_time = end_time
        self.logger.info("Logged sleep bout: %s → %s (%.0fs)",
                         log_entry["start_time"], log_entry["end_time"],
                         log_entry["duration_seconds"])

    def log_sleep_end(self, start_time, end_time, avg_motion):
        log_entry = {
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round((end_time - start_time).total_seconds(), 3),
            "average_motion": round(avg_motion, 8),
            "motion_range": {
                "min": round(float(self.min_motion), 6) if self.min_motion != float("inf") else None,
                "max": round(float(self.max_motion), 6),
            }
        }
        path = self._log_file_path()
        logs = self._read_log(path)
        logs.append(log_entry)
        self._write_log_atomic(path, logs)
        self.last_log_time = end_time
        self.logger.info("Sleep bout ENDED: %s → %s (%.0fs)",
                         log_entry["start_time"], log_entry["end_time"],
                         log_entry["duration_seconds"])

    # ------------------------------------------------------------------
    def run(self):
        pipeline = (
            "nvarguscamerasrc sensor-id=0 ! "
            "video/x-raw(memory:NVMM), width=1280, height=720, "
            "format=(string)NV12, framerate=30/1 ! "
            "nvvidconv flip-method=0 ! "
            "video/x-raw, width=640, height=360, format=(string)BGRx ! "
            "videoconvert ! "
            "video/x-raw, format=(string)BGR ! appsink"
        )

        self.logger.info("Opening CSI camera…")
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            self.logger.critical("Could not open camera — exiting")
            self._cleanup()
            return

        self.logger.info("Camera opened. Log dir: %s", self.log_dir)
        self.logger.info("Threshold=%.5f%%  MinDuration=%ds  LogInterval=%ds",
                         self.SLEEP_THRESHOLD, self.MIN_SLEEP_DURATION, self.LOG_INTERVAL)
        self.logger.info("Press 'q' to quit, 'r' to reset min/max")

        consecutive_failures = 0

        try:
            while not self._shutdown_requested:
                ret, frame = cap.read()
                if not ret:
                    consecutive_failures += 1
                    self.logger.warning("Frame read failed (%d/%d)",
                                        consecutive_failures, self.MAX_CAMERA_RETRIES)
                    if consecutive_failures >= self.MAX_CAMERA_RETRIES:
                        self.logger.error("Too many frame failures — exiting")
                        break
                    continue
                consecutive_failures = 0
                self.frame_count += 1

                mask, motion_intensity, avg_motion = self.analyze_frame(frame)
                current_time = datetime.now()

                self.motion_buffer.append({"time": current_time, "intensity": motion_intensity})
                while (self.motion_buffer
                       and (current_time - self.motion_buffer[0]["time"]).total_seconds()
                       > self.MIN_SLEEP_DURATION):
                    self.motion_buffer.popleft()

                if self.frame_count >= self.WARMUP_FRAMES and len(self.motion_buffer) > 30:
                    buffer_avg = sum(m["intensity"] for m in self.motion_buffer) / len(self.motion_buffer)

                    if buffer_avg < self.SLEEP_THRESHOLD:
                        if self.current_sleep_start is None:
                            self.current_sleep_start = self.motion_buffer[0]["time"]
                            self.logger.info("Potential sleep onset (motion=%.5f%%)", buffer_avg)
                        elif (current_time - self.current_sleep_start).total_seconds() >= self.MIN_SLEEP_DURATION:
                            cv2.putText(mask, "SLEEP DETECTED",
                                        (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
                            self.set_led_state(True)
                            self.log_sleep_period(self.current_sleep_start, current_time, buffer_avg)
                    else:
                        if self.current_sleep_start is not None:
                            duration = (current_time - self.current_sleep_start).total_seconds()
                            if duration >= self.MIN_SLEEP_DURATION:
                                self.log_sleep_end(self.current_sleep_start, current_time, buffer_avg)
                            self.logger.info("Active state resumed (motion=%.5f%%)", buffer_avg)
                        self.current_sleep_start = None
                        self.set_led_state(False)
                        cv2.putText(mask, "ACTIVE",
                                    (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)

                cv2.imshow("Motion Detection", mask)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    self.logger.info("Quit requested by user")
                    break
                elif key == ord("r"):
                    self.max_motion = 0.0
                    self.min_motion = float("inf")
                    self.logger.info("Min/max motion values reset")

        except Exception as exc:
            self.logger.exception("Unhandled exception: %s", exc)
        finally:
            self._cleanup(cap)


def main():
    detector = CaliBeeMotionDetector()
    detector.run()


if __name__ == "__main__":
    main()
