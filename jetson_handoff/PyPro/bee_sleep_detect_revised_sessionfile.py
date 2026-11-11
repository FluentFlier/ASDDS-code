#!/usr/bin/env python3
"""
Bee sleep detector - revised version

Changes from original:
- Prevents overlapping sleep bouts
- Sleep onset includes the initial 120 seconds of inactivity
- Wake requires 15 seconds of continuous movement
- Uses one JSON file for the whole experiment
- Restores camera overlay and ACTIVE/SLEEP DETECTED display
- Keeps original JSON output format
"""

import cv2
import numpy as np
import json
import os
import tempfile
import signal
from datetime import datetime
from collections import deque
import Jetson.GPIO as GPIO


class CaliBeeMotionDetector:

    LED_PIN = 7

    SLEEP_THRESHOLD = 0.005
    MIN_SLEEP_DURATION = 120
    WAKE_CONFIRM_DURATION = 15

    WARMUP_FRAMES = 90
    MOTION_HISTORY_LEN = 300

    def __init__(self):

        self.log_dir = os.path.expanduser("~/Desktop/bee_motion_logs")
        os.makedirs(self.log_dir, exist_ok=True)

        # One file for entire recording session, locked to the run start date
        self.session_date = datetime.now().strftime("%Y%m%d")
        self.log_file = os.path.join(
            self.log_dir,
            f"sleep_log_{self.session_date}.json"
        )

        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.LED_PIN, GPIO.OUT, initial=GPIO.LOW)

        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100,
            varThreshold=15,
            detectShadows=False
        )

        self.motion_history = deque(maxlen=self.MOTION_HISTORY_LEN)

        self.sleeping = False
        self.sleep_start_time = None
        self.low_motion_start = None
        self.wake_motion_start = None

        self.frame_count = 0

        self.min_motion = float("inf")
        self.max_motion = 0.0

        self.shutdown = False

        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)


    def stop(self, *args):
        self.shutdown = True


    def set_led(self, sleeping):
        GPIO.output(
            self.LED_PIN,
            GPIO.HIGH if sleeping else GPIO.LOW
        )


    def analyze_frame(self, frame):

        gray = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2GRAY
        )

        blurred = cv2.GaussianBlur(
            gray,
            (7, 7),
            0
        )

        mask = self.bg_subtractor.apply(
            blurred,
            learningRate=0.01
        )

        motion_pixels = cv2.countNonZero(mask)

        motion = (
            motion_pixels / mask.size
        ) * 100

        self.motion_history.append(motion)

        if self.frame_count >= self.WARMUP_FRAMES:
            self.min_motion = min(
                self.min_motion,
                motion
            )

            self.max_motion = max(
                self.max_motion,
                motion
            )

        avg_motion = np.mean(self.motion_history)

        # Original style overlay
        lines = [
            f"Motion: {motion:.5f}%",
            f"Range: {self.min_motion:.5f}% - {self.max_motion:.5f}%",
            f"Avg(10s): {avg_motion:.5f}%",
            f"Thresh: {self.SLEEP_THRESHOLD:.5f}%"
        ]

        for i, line in enumerate(lines):
            cv2.putText(
                mask,
                line,
                (10, 25 + i*25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                255,
                2
            )

        return mask, motion, avg_motion


    def load_logs(self):

        if not os.path.exists(self.log_file):
            return []

        try:
            with open(self.log_file, "r") as f:
                return json.load(f)
        except:
            return []


    def save_logs(self, logs):

        fd, tmp = tempfile.mkstemp(
            dir=self.log_dir,
            suffix=".tmp"
        )

        with os.fdopen(fd, "w") as f:
            json.dump(
                logs,
                f,
                indent=4
            )

        os.replace(
            tmp,
            self.log_file
        )


    def log_sleep(self, start, end):

        logs = self.load_logs()

        entry = {
            "start_time": start.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "end_time": end.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "duration_seconds":
                (end-start).total_seconds(),
            "average_motion":
                float(np.mean(self.motion_history)),
            "motion_range": {
                "min":
                    self.min_motion
                    if self.min_motion != float("inf")
                    else 0.0,
                "max":
                    self.max_motion
            }
        }

        logs.append(entry)

        self.save_logs(logs)


    def update_sleep_state(self, now, motion, mask):

        low_motion = motion < self.SLEEP_THRESHOLD


        if not self.sleeping:

            if low_motion:

                if self.low_motion_start is None:
                    self.low_motion_start = now

                elif (
                    now - self.low_motion_start
                ).total_seconds() >= self.MIN_SLEEP_DURATION:

                    self.sleeping = True

                    # Include first 120 seconds
                    self.sleep_start_time = self.low_motion_start

                    self.set_led(True)

            else:
                self.low_motion_start = None


        else:

            if not low_motion:

                if self.wake_motion_start is None:
                    self.wake_motion_start = now

                elif (
                    now - self.wake_motion_start
                ).total_seconds() >= self.WAKE_CONFIRM_DURATION:

                    self.log_sleep(
                        self.sleep_start_time,
                        now
                    )

                    self.sleeping = False
                    self.sleep_start_time = None
                    self.wake_motion_start = None

                    self.set_led(False)

            else:
                self.wake_motion_start = None


        if self.sleeping:
            cv2.putText(
                mask,
                "SLEEP DETECTED",
                (10,150),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                255,
                2
            )
        else:
            cv2.putText(
                mask,
                "ACTIVE",
                (10,150),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                255,
                2
            )


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

        cap = cv2.VideoCapture(
            pipeline,
            cv2.CAP_GSTREAMER
        )

        if not cap.isOpened():
            raise RuntimeError("Camera failed")

        try:

            while not self.shutdown:

                ret, frame = cap.read()

                if not ret:
                    continue

                self.frame_count += 1

                mask, motion, avg = self.analyze_frame(frame)

                now = datetime.now()

                if self.frame_count >= self.WARMUP_FRAMES:

                    self.update_sleep_state(
                        now,
                        motion,
                        mask
                    )

                cv2.imshow(
                    "Motion Detection",
                    mask
                )

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

        finally:

            GPIO.output(
                self.LED_PIN,
                GPIO.LOW
            )

            GPIO.cleanup()
            cap.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    detector = CaliBeeMotionDetector()
    detector.run()
