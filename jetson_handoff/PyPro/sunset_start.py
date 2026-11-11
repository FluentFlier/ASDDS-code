#!/usr/bin/env python3

import cv2
import numpy as np
from datetime import datetime, date, timedelta
import json
import os
from collections import deque
import Jetson.GPIO as GPIO

class CaliBeeMotionDetector:
    def __init__(self):
        # GPIO Setup
        self.led_pin = 18
        self.solenoid_pin = 7
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.led_pin, GPIO.OUT, initial=GPIO.LOW)      # LED
        GPIO.setup(self.solenoid_pin, GPIO.OUT, initial=GPIO.LOW) # Solenoid

        self.log_dir = os.path.expanduser("~/Desktop/bee_motion_logs")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=100,
            varThreshold=15,
            detectShadows=False
        )

        self.current_sleep_start = None
        self.SLEEP_THRESHOLD = 0.005  # Set to 0.005% (very low threshold)
        self.MIN_SLEEP_DURATION = 120  # 2 minutes
        self.LOG_INTERVAL = 120

        # Get solenoid start time from researcher in HH:MM AM/PM format
        while True:
            try:
                time_input = input("Enter solenoid start time (HH:MM AM/PM format, e.g., 06:05PM): ")
                # Parse the input time
                parsed_time = datetime.strptime(time_input, "%I:%M%p")
                # Combine with today's date
                today = date.today()
                self.SOLENOID_START_TIME = datetime.combine(today, parsed_time.time())
                # If the time has already passed today, assume next day
                if self.SOLENOID_START_TIME < datetime.now():
                    self.SOLENOID_START_TIME += timedelta(days=1)
                self.SOLENOID_START_TIME_STR = time_input
                break
            except ValueError:
                print("Please enter a valid time in HH:MM AM/PM format (e.g., 06:05PM).")

        self.motion_buffer = []
        self.last_log_time = None

        # Keep track of motion history for calibration
        self.motion_history = deque(maxlen=300)
        self.max_motion = 0.0
        self.min_motion = float('inf')

    def set_led_state(self, is_sleeping, current_time):
        """Control LED and Solenoid based on sleep state and solenoid start time"""
        # Control LED immediately
        led_state = GPIO.HIGH if is_sleeping else GPIO.LOW
        GPIO.output(self.led_pin, led_state)

        # Control Solenoid based on start time and sleep state
        if is_sleeping and current_time >= self.SOLENOID_START_TIME:
            GPIO.output(self.solenoid_pin, GPIO.HIGH)
        else:
            GPIO.output(self.solenoid_pin, GPIO.LOW)

    def analyze_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        mask = self.bg_subtractor.apply(blurred, learningRate=0.01)

        motion_pixels = cv2.countNonZero(mask)
        motion_intensity = (motion_pixels / mask.size) * 100

        self.motion_history.append(motion_intensity)
        self.max_motion = max(self.max_motion, motion_intensity)
        self.min_motion = min(self.min_motion, motion_intensity)

        avg_motion = np.mean(self.motion_history)

        info_lines = [
            f"Current Motion: {motion_intensity:.5f}%",
            f"Range: {self.min_motion:.5f}% - {self.max_motion:.5f}%",
            f"Avg (10s): {avg_motion:.5f}%",
            f"Sleep Threshold: {self.SLEEP_THRESHOLD:.5f}%"
        ]

        for i, line in enumerate(info_lines):
            cv2.putText(mask, line,
                        (10, 25 + (i * 25)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, 255, 2)

        return mask, motion_intensity, avg_motion

    def log_sleep_period(self, start_time, end_time, avg_motion):
        if (self.last_log_time is None or
            (end_time - self.last_log_time).total_seconds() >= self.LOG_INTERVAL):

            log_entry = {
                "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_seconds": (end_time - start_time).total_seconds(),
                "average_motion": avg_motion,
                "motion_range": {
                    "min": float(self.min_motion),
                    "max": float(self.max_motion)
                }
            }

            log_file = os.path.join(self.log_dir,
                                    f"sleep_log_{datetime.now().strftime('%Y%m%d')}.json")

            try:
                logs = []
                if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
                    try:
                        with open(log_file, 'r') as f:
                            logs = json.load(f)
                    except json.JSONDecodeError:
                        print("Warning: Could not read existing log file, starting fresh")

                logs.append(log_entry)

                with open(log_file, 'w') as f:
                    json.dump(logs, f, indent=4)

                self.last_log_time = end_time

            except Exception as e:
                print(f"Error logging sleep period: {e}")

    def run(self):
        pipeline = (
            "nvarguscamerasrc sensor-id=0 ! "
            "video/x-raw(memory:NVMM), width=1280, height=720, format=(string)NV12, framerate=30/1 ! "
            "nvvidconv flip-method=0 ! "
            "video/x-raw, width=640, height=360, format=(string)BGRx ! "
            "videoconvert ! "
            "video/x-raw, format=(string)BGR ! appsink"
        )

        print("Initializing camera...")
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            print("Error: Could not open camera")
            return

        print(f"Started motion detection. Logs will be saved to: {self.log_dir}")
        print(f"Initial sleep threshold: {self.SLEEP_THRESHOLD:.5f}%")
        print(f"Solenoid start time: {self.SOLENOID_START_TIME_STR}")
        print("Press 'q' to quit")
        print("Press 'r' to reset min/max values")

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                mask, motion_intensity, avg_motion = self.analyze_frame(frame)
                current_time = datetime.now()

                self.motion_buffer.append({
                    'time': current_time,
                    'intensity': motion_intensity
                })

                while (self.motion_buffer and
                       (current_time - self.motion_buffer[0]['time']).total_seconds() >
                       self.MIN_SLEEP_DURATION):
                    self.motion_buffer.pop(0)

                if len(self.motion_buffer) > 30:
                    buffer_avg = sum(m['intensity'] for m in self.motion_buffer) / len(self.motion_buffer)

                    if buffer_avg < self.SLEEP_THRESHOLD:
                        if self.current_sleep_start is None:
                            self.current_sleep_start = self.motion_buffer[0]['time']
                            print(f"Potential sleep state detected... (Motion: {buffer_avg:.5f}%)")
                        elif (current_time - self.current_sleep_start).total_seconds() >= self.MIN_SLEEP_DURATION:
                            cv2.putText(mask, "SLEEP DETECTED",
                                        (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
                            self.set_led_state(True, current_time)
                            self.log_sleep_period(self.current_sleep_start, current_time, buffer_avg)
                    else:
                        if self.current_sleep_start is not None:
                            print(f"Motion detected: {buffer_avg:.5f}% - Active state")
                        self.current_sleep_start = None
                        self.set_led_state(False, current_time)
                        cv2.putText(mask, "ACTIVE",
                                    (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)

                cv2.imshow('Motion Detection', mask)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('r'):
                    self.max_motion = 0.0
                    self.min_motion = float('inf')
                    print("Reset min/max values")

        finally:
            GPIO.cleanup()
            cap.release()
            cv2.destroyAllWindows()

def main():
    detector = CaliBeeMotionDetector()
    detector.run()

if __name__ == "__main__":
    main()
