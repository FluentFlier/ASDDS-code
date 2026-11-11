#!/usr/bin/env python3
"""gpiodemo.py — Simple LED blink test for Jetson GPIO pin 7."""

import signal
import sys
import time

import Jetson.GPIO as GPIO

LED_PIN = 7
_running = True


def _shutdown(signum, _frame):
    global _running
    print(f"\nReceived {signal.Signals(signum).name} — stopping.")
    _running = False


def main():
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

    print(f"Blinking LED on pin {LED_PIN}.  Press Ctrl+C to stop.")

    try:
        while _running:
            GPIO.output(LED_PIN, GPIO.HIGH)
            print("LED ON")
            time.sleep(2)
            if not _running:
                break
            GPIO.output(LED_PIN, GPIO.LOW)
            print("LED OFF")
            time.sleep(2)
    finally:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()
        print("GPIO cleaned up. Exiting.")


if __name__ == "__main__":
    main()
