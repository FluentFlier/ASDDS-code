#!/usr/bin/env python3
"""Bee sleep detector with one non-overlapping record per sleep event.

Key behavior:
* A fresh candidate begins at the current time, never at an old buffer time.
* Sleep decisions use the older detector's 120-second rolling motion average.
* A two-second persistence gate prevents near-threshold noise from chattering
  between candidate and active without changing the calibrated threshold.
* That average resets when a new candidate starts, a candidate fails, a bout
  ends, or camera continuity breaks, so history cannot leak between events.
* Candidate-to-sleep confirmation does not reset the average because both
  states belong to the same continuous bout.
* Averaged low motion must continue for strictly more than 120 seconds.
* Any failed candidate or completed bout clears all detection state.
* A completed bout is written exactly once, when sustained motion resumes.
* Interrupted bouts are described in the detector log but are not inserted
  into the MATLAB JSON as if they were completed bouts.
* Camera gaps over one second break continuity instead of counting as sleep.
* Failed log writes remain queued for retry and cause a non-zero exit if unresolved.
* One ``sleep_log_YYYYMMDD.json`` file is used for the entire experiment,
  where ``YYYYMMDD`` is captured when this process starts.
* Each JSON row retains the five-field legacy format expected by MATLAB.

This retains the useful 120-second smoothing behavior of the older detector
without its stale-buffer starts, duplicate rows, or overlapping records.
GPIO Pin: 7 (BOARD), LED.
"""

import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime

import cv2
import Jetson.GPIO as GPIO
import numpy as np

from sleep_bout_state import (
    RollingMotionAverage,
    SleepBoutStateMachine,
    SleepLogWriter,
)


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
SOFTWARE_VERSION = "2.5-audited-state-scoped-average"


def setup_logging(log_dir, experiment_start):
    os.makedirs(log_dir, exist_ok=True)
    logger_name = "bee_sleep_clean.{}.{}".format(
        os.getpid(), experiment_start.strftime("%Y%m%d_%H%M%S")
    )
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(console)

    detector_log = os.path.join(
        log_dir,
        "detector_clean_{}.log".format(experiment_start.strftime("%Y%m%d_%H%M%S")),
    )
    file_handler = logging.FileHandler(detector_log)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(file_handler)
    return logger


class CaliBeeMotionDetector(object):
    LED_PIN = 7
    SLEEP_THRESHOLD = 0.005
    MIN_SLEEP_DURATION = 120
    DETECTION_WINDOW_SECONDS = 120.0
    DETECTION_MINIMUM_SAMPLES = 31
    TRANSITION_PERSISTENCE_SECONDS = 2.0
    WARMUP_FRAMES = 90
    MAX_CAMERA_RETRIES = 5
    MAX_OBSERVATION_GAP_SECONDS = 1.0
    MOTION_HISTORY_LEN = 300
    PERSIST_RETRY_INTERVAL_SECONDS = 5.0

    def __init__(self, log_dir=None, experiment_start=None):
        self.experiment_start = experiment_start or datetime.now()
        self.log_dir = os.path.abspath(
            os.path.expanduser(log_dir or "~/Desktop/bee_motion_logs")
        )
        self.logger = setup_logging(self.log_dir, self.experiment_start)
        self.log_writer = SleepLogWriter(
            self.log_dir, self.experiment_start, logger=self.logger
        )
        self.state = SleepBoutStateMachine(
            threshold=self.SLEEP_THRESHOLD,
            minimum_duration_seconds=self.MIN_SLEEP_DURATION,
            transition_persistence_seconds=self.TRANSITION_PERSISTENCE_SECONDS,
        )

        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.LED_PIN, GPIO.OUT, initial=GPIO.LOW)

        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=15, detectShadows=False
        )
        self.motion_history = deque(maxlen=self.MOTION_HISTORY_LEN)
        self.detection_window = RollingMotionAverage(
            window_seconds=self.DETECTION_WINDOW_SECONDS,
            minimum_samples=self.DETECTION_MINIMUM_SAMPLES,
        )
        self.frame_count = 0
        self.session_min_motion = float("inf")
        self.session_max_motion = 0.0
        self._shutdown_requested = False
        self._pending_records = []
        self._last_persist_attempt = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("Initialised clean-bout detector %s", SOFTWARE_VERSION)
        self.logger.info("Experiment start: %s", self.experiment_start.strftime(DATE_FORMAT))
        self.logger.info("Sleep output: %s", self.log_writer.path)

    def _signal_handler(self, signum, _frame):
        self.logger.warning(
            "Received %s; requesting graceful shutdown", signal.Signals(signum).name
        )
        self._shutdown_requested = True

    def set_led_state(self, sleeping):
        try:
            GPIO.output(self.LED_PIN, GPIO.HIGH if sleeping else GPIO.LOW)
        except Exception as exc:
            self.logger.error("GPIO write failed: %s", exc)

    def analyze_frame(self, frame, monotonic_time):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        mask = self.bg_subtractor.apply(blurred, learningRate=0.01)
        motion_pixels = cv2.countNonZero(mask)
        motion_intensity = (motion_pixels / mask.size) * 100

        self.motion_history.append(motion_intensity)
        display_average = float(np.mean(self.motion_history))
        detection_average = self.detection_window.add(
            monotonic_time, motion_intensity
        )

        if self.frame_count >= self.WARMUP_FRAMES:
            self.session_min_motion = min(self.session_min_motion, motion_intensity)
            self.session_max_motion = max(self.session_max_motion, motion_intensity)

        minimum_display = (
            self.session_min_motion
            if self.session_min_motion != float("inf")
            else 0.0
        )
        lines = [
            "Motion: {:.5f}%".format(motion_intensity),
            "Range: {:.5f}% - {:.5f}%".format(
                minimum_display, self.session_max_motion
            ),
            "Avg(10s): {:.5f}%".format(display_average),
            "Detect avg(120s): {:.5f}%{}".format(
                detection_average,
                "" if self.detection_window.ready else " WARMING",
            ),
            "Threshold: {:.5f}%".format(self.SLEEP_THRESHOLD),
        ]
        for index, line in enumerate(lines):
            cv2.putText(
                mask,
                line,
                (10, 25 + index * 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                255,
                2,
            )
        return mask, motion_intensity, display_average, detection_average

    def _flush_pending_records(self, force=False):
        if not self._pending_records:
            return True

        now = time.monotonic()
        if (
            not force
            and self._last_persist_attempt is not None
            and now - self._last_persist_attempt < self.PERSIST_RETRY_INTERVAL_SECONDS
        ):
            return False
        self._last_persist_attempt = now

        while self._pending_records:
            record = self._pending_records[0]
            try:
                appended = self.log_writer.append(record)
            except Exception as exc:
                self.logger.error(
                    "Could not persist bout %s; retained for retry: %s",
                    record["start_time"],
                    exc,
                )
                return False

            self._pending_records.pop(0)
            if appended:
                self.logger.info(
                    "Recorded one bout: %s -> %s (%.3f s)",
                    record["start_time"],
                    record["end_time"],
                    record["duration_seconds"],
                )
            else:
                self.logger.warning(
                    "Bout %s was already persisted; cleared pending retry",
                    record["start_time"],
                )
        return True

    def _record_bout(self, bout):
        record = bout.to_record(
            threshold=self.SLEEP_THRESHOLD,
            minimum_duration_seconds=self.MIN_SLEEP_DURATION,
        )
        if not any(
            pending["start_time"] == record["start_time"]
            for pending in self._pending_records
        ):
            self._pending_records.append(record)
        self._flush_pending_records(force=True)

    def _handle_transition(
        self, transition, instant_motion=None, detection_motion=None
    ):
        if transition is None:
            return

        transition_type = transition["type"]
        motion_detail = ""
        if instant_motion is not None and detection_motion is not None:
            motion_detail = " (instant={:.5f}%, detect_avg={:.5f}%)".format(
                instant_motion, detection_motion
            )
        if transition_type == "candidate_started":
            self.logger.info(
                "Fresh sleep candidate started at %s%s",
                transition["start_time"].strftime(DATE_FORMAT),
                motion_detail,
            )
            self.detection_window.clear()
        elif transition_type == "candidate_cancelled":
            self.logger.info(
                "Sleep candidate reset at %s%s%s",
                transition["cancelled_at"].strftime(DATE_FORMAT),
                " ({})".format(transition["reason"])
                if transition.get("reason")
                else "",
                motion_detail,
            )
            self.detection_window.clear()
        elif transition_type == "sleep_confirmed":
            self.logger.info(
                "Sleep confirmed: start=%s confirmation=%s%s",
                transition["start_time"].strftime(DATE_FORMAT),
                transition["confirmation_time"].strftime(DATE_FORMAT),
                motion_detail,
            )
            self.set_led_state(True)
        elif transition_type == "bout_completed":
            self._record_bout(transition["bout"])
            self.set_led_state(False)
            self.detection_window.clear()
        elif transition_type == "bout_interrupted":
            self._log_incomplete_bout(transition["bout"])
            self.set_led_state(False)
            self.detection_window.clear()

    def update_sleep_state(
        self,
        now,
        motion_intensity,
        smoothed_motion,
        monotonic_time=None,
    ):
        """Update state using smoothed motion while retaining raw bout metrics.

        The 120-second detection average supplies the classification score.
        Instantaneous motion is retained only for the bout's output metrics.
        """
        transition = self.state.update(
            now,
            smoothed_motion,
            monotonic_time=monotonic_time,
            metric_score=motion_intensity,
        )
        self._handle_transition(transition, motion_intensity, smoothed_motion)

    def _interrupt_observation(self, reason):
        self._handle_transition(self.state.interrupt(reason))
        self.detection_window.clear()

    def _log_incomplete_bout(self, bout):
        self.logger.warning(
            "Confirmed bout was not added to MATLAB JSON because it was incomplete: "
            "start=%s end=%s duration=%.3f s reason=%s",
            bout.start_time.strftime(DATE_FORMAT),
            bout.end_time.strftime(DATE_FORMAT),
            bout.duration_seconds,
            bout.end_reason,
        )

    def _finalize_open_bout(self):
        bout = self.state.finalize(datetime.now(), monotonic_time=time.monotonic())
        if bout is not None:
            self._log_incomplete_bout(bout)

    def _cleanup(self, camera=None):
        try:
            GPIO.output(self.LED_PIN, GPIO.LOW)
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

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

        self.logger.info("Opening CSI camera")
        camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not camera.isOpened():
            self.logger.critical("Could not open camera")
            self._cleanup(camera)
            return 1

        self.logger.info(
            "Detection uses %.0f-second state-scoped average: threshold=%.5f%%, transition persistence=%.1f s, sleep confirmation >%d s",
            self.DETECTION_WINDOW_SECONDS,
            self.SLEEP_THRESHOLD,
            self.TRANSITION_PERSISTENCE_SECONDS,
            self.MIN_SLEEP_DURATION,
        )
        consecutive_failures = 0
        last_valid_frame_tick = None
        exit_code = 0
        try:
            while not self._shutdown_requested:
                available, frame = camera.read()
                if not available:
                    consecutive_failures += 1
                    self.logger.warning(
                        "Frame read failed (%d/%d)",
                        consecutive_failures,
                        self.MAX_CAMERA_RETRIES,
                    )
                    if consecutive_failures >= self.MAX_CAMERA_RETRIES:
                        self.logger.error("Too many consecutive frame failures")
                        self._interrupt_observation("camera_read_failed")
                        exit_code = 2
                        break
                    continue

                consecutive_failures = 0
                now = datetime.now()
                monotonic_now = time.monotonic()
                if (
                    last_valid_frame_tick is not None
                    and monotonic_now - last_valid_frame_tick
                    > self.MAX_OBSERVATION_GAP_SECONDS
                ):
                    gap_seconds = monotonic_now - last_valid_frame_tick
                    self.logger.warning(
                        "Camera observation gap of %.3f seconds; resetting sleep continuity",
                        gap_seconds,
                    )
                    self._interrupt_observation("camera_observation_gap")
                last_valid_frame_tick = monotonic_now

                self.frame_count += 1
                (
                    mask,
                    motion_intensity,
                    _display_average,
                    detection_average,
                ) = self.analyze_frame(frame, monotonic_now)

                if (
                    self.frame_count >= self.WARMUP_FRAMES
                    and self.detection_window.ready
                ):
                    self.update_sleep_state(
                        now,
                        motion_intensity,
                        detection_average,
                        monotonic_now,
                    )

                self._flush_pending_records()

                cv2.putText(
                    mask,
                    "State: {}".format(self.state.status.upper()),
                    (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    255,
                    2,
                )
                if self.state.sleeping:
                    state_text = "SLEEP DETECTED"
                elif self.state.status == "candidate":
                    state_text = "SLEEP CANDIDATE"
                else:
                    state_text = "ACTIVE"
                cv2.putText(
                    mask,
                    state_text,
                    (10, 205),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    255,
                    2,
                )
                cv2.imshow("Motion Detection", mask)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    self.logger.info("Quit requested by user")
                    break
                if key == ord("r"):
                    self.session_min_motion = float("inf")
                    self.session_max_motion = 0.0
                    self.logger.info("Session min/max display reset")
        except Exception as exc:
            self.logger.exception("Unhandled exception in main loop: %s", exc)
            self._interrupt_observation("processing_error")
            exit_code = 3
        finally:
            try:
                try:
                    self._finalize_open_bout()
                except Exception as exc:
                    self.logger.exception("Could not finalize open bout: %s", exc)
                    exit_code = 3

                self._flush_pending_records(force=True)
                if self._pending_records:
                    self.logger.critical(
                        "%d completed bout(s) could not be persisted",
                        len(self._pending_records),
                    )
                    exit_code = 4
            finally:
                self._cleanup(camera)
        return exit_code


def main():
    detector = CaliBeeMotionDetector()
    return detector.run()


if __name__ == "__main__":
    sys.exit(main())
