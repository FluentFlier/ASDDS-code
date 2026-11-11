#!/usr/bin/env python3
"""
motor_mimic.py -- Motor control script to mimic bee-like activity patterns.
Runs independently alongside the sleep detection scripts.

Modes:
  1. Fixed Interval   -- Motor activates every X seconds for Y seconds
  2. Random Dormancy  -- 2 min dormancy windows with random bursts in between
  3. Scheduled Burst  -- N repetitions at a fixed interval starting at a set time
  4. Bee Mimic        -- Randomised activity/rest cycles that mimic real bee patterns
"""

import time
import random
import signal
import sys
from datetime import datetime, date, timedelta

try:
    import Jetson.GPIO as GPIO
except ImportError:
    print("WARNING: Jetson.GPIO not found, running in dry-run mode")
    GPIO = None

# ---------------------------------------------------------------
# Config
# ---------------------------------------------------------------
MOTOR_PIN = 11  # Change to your motor GPIO pin (BOARD numbering)
MOTOR_ON_TIME = 3  # Default pulse duration in seconds

# ---------------------------------------------------------------
# GPIO helpers
# ---------------------------------------------------------------
def setup_gpio():
    if GPIO:
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(MOTOR_PIN, GPIO.OUT, initial=GPIO.LOW)

def motor_on(duration=MOTOR_ON_TIME):
    ts = datetime.now().strftime("%H:%M:%S")
    print("[{}] Motor ON for {:.2f}s".format(ts, duration))
    if GPIO:
        GPIO.output(MOTOR_PIN, GPIO.HIGH)
    time.sleep(duration)
    if GPIO:
        GPIO.output(MOTOR_PIN, GPIO.LOW)
    print("[{}] Motor OFF".format(datetime.now().strftime("%H:%M:%S")))

def cleanup():
    if GPIO:
        GPIO.cleanup()
    print("\nMotor cleanup done. Exiting.")

def handle_exit(sig, frame):
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# ---------------------------------------------------------------
# Mode 1: Fixed Interval
# ---------------------------------------------------------------
def mode_fixed_interval():
    """Motor activates every X seconds for Y seconds, runs forever or N times."""
    print("\n=== MODE 1: Fixed Interval ===")
    interval = float(input("Interval between activations (seconds): "))
    duration = float(input("Motor ON duration per activation (seconds) [0.5]: ") or "0.5")
    reps_input = input("Number of repetitions (leave blank for infinite): ").strip()
    reps = int(reps_input) if reps_input else None

    count = 0
    print("\nStarting fixed interval mode...")
    print("  Interval: {}s | Duration: {}s | Reps: {}".format(
        interval, duration, reps if reps else "infinite"))
    print("Press Ctrl+C to stop\n")

    while reps is None or count < reps:
        motor_on(duration)
        count += 1
        if reps:
            print("  [{}/{}]".format(count, reps))
        if reps is None or count < reps:
            time.sleep(interval)

    print("\nCompleted {} activations.".format(count))

# ---------------------------------------------------------------
# Mode 2: Random Dormancy
# ---------------------------------------------------------------
def mode_random_dormancy():
    """2 minute dormancy windows with random short bursts of activity."""
    print("\n=== MODE 2: Random Dormancy ===")
    dormancy_min = float(input("Min dormancy period (seconds) [90]: ") or "90")
    dormancy_max = float(input("Max dormancy period (seconds) [150]: ") or "150")
    burst_min = int(input("Min pulses per burst [1]: ") or "1")
    burst_max = int(input("Max pulses per burst [4]: ") or "4")
    pulse_dur = float(input("Pulse duration (seconds) [0.3]: ") or "0.3")
    reps_input = input("Number of bursts (leave blank for infinite): ").strip()
    reps = int(reps_input) if reps_input else None

    count = 0
    print("\nStarting random dormancy mode...")
    print("  Dormancy: {}-{}s | Pulses/burst: {}-{} | Pulse: {}s".format(
        dormancy_min, dormancy_max, burst_min, burst_max, pulse_dur))
    print("Press Ctrl+C to stop\n")

    while reps is None or count < reps:
        # Dormancy period
        dorm = random.uniform(dormancy_min, dormancy_max)
        print("[{}] Dormant for {:.1f}s...".format(
            datetime.now().strftime("%H:%M:%S"), dorm))
        time.sleep(dorm)

        # Burst of activity
        num_pulses = random.randint(burst_min, burst_max)
        print("[{}] Burst: {} pulses".format(
            datetime.now().strftime("%H:%M:%S"), num_pulses))
        for p in range(num_pulses):
            motor_on(pulse_dur)
            if p < num_pulses - 1:
                gap = random.uniform(0.1, 0.8)
                time.sleep(gap)

        count += 1
        if reps:
            print("  [{}/{}]".format(count, reps))

    print("\nCompleted {} bursts.".format(count))

# ---------------------------------------------------------------
# Mode 3: Scheduled Burst
# ---------------------------------------------------------------
def mode_scheduled_burst():
    """Wait until a set time, then do N repetitions at a fixed interval."""
    print("\n=== MODE 3: Scheduled Burst ===")

    while True:
        try:
            time_input = input("Start time (HH:MM AM/PM, e.g., 06:05PM): ")
            parsed = datetime.strptime(time_input, "%I:%M%p")
            start_time = datetime.combine(date.today(), parsed.time())
            if start_time < datetime.now():
                start_time += timedelta(days=1)
            break
        except ValueError:
            print("Invalid format. Use HH:MM AM/PM (e.g., 06:05PM).")

    reps = int(input("Number of repetitions: "))
    interval = float(input("Interval between reps (seconds): "))
    duration = float(input("Motor ON duration (seconds) [0.5]: ") or "0.5")

    wait = (start_time - datetime.now()).total_seconds()
    print("\nWaiting until {} ({:.0f}s from now)...".format(
        start_time.strftime("%I:%M %p"), wait))
    print("  Reps: {} | Interval: {}s | Duration: {}s".format(reps, interval, duration))
    print("Press Ctrl+C to cancel\n")

    time.sleep(wait)
    print("[{}] Starting scheduled burst!".format(datetime.now().strftime("%H:%M:%S")))

    for i in range(reps):
        motor_on(duration)
        print("  [{}/{}]".format(i + 1, reps))
        if i < reps - 1:
            time.sleep(interval)

    print("\nCompleted {} scheduled activations.".format(reps))

# ---------------------------------------------------------------
# Mode 4: Bee Mimic
# ---------------------------------------------------------------
def mode_bee_mimic():
    """Randomised activity/rest cycles mimicking bee movement patterns.
    Short grooming bursts, longer rest, occasional sustained movement."""
    print("\n=== MODE 4: Bee Mimic ===")

    while True:
        try:
            time_input = input("Start time (HH:MM AM/PM, e.g., 06:05PM): ")
            parsed = datetime.strptime(time_input, "%I:%M%p")
            start_time = datetime.combine(date.today(), parsed.time())
            if start_time < datetime.now():
                start_time += timedelta(days=1)
            break
        except ValueError:
            print("Invalid format. Use HH:MM AM/PM (e.g., 06:05PM).")

    run_minutes = float(input("Run duration (minutes) [60]: ") or "60")
    end_time = start_time + timedelta(minutes=run_minutes)

    wait = (start_time - datetime.now()).total_seconds()
    print("\nWaiting until {} ({:.0f}s from now)...".format(
        start_time.strftime("%I:%M %p"), wait))
    print("  Will run for {} minutes until {}".format(
        run_minutes, end_time.strftime("%I:%M %p")))
    print("Press Ctrl+C to cancel\n")

    time.sleep(wait)
    print("[{}] Starting bee mimic mode!".format(datetime.now().strftime("%H:%M:%S")))

    event_count = 0
    while datetime.now() < end_time:
        # Pick a random behaviour
        behaviour = random.choices(
            ["rest", "groom", "walk", "sustained"],
            weights=[50, 25, 15, 10],
            k=1
        )[0]

        if behaviour == "rest":
            rest = random.uniform(90, 180)
            remaining = (end_time - datetime.now()).total_seconds()
            rest = min(rest, remaining)
            if rest <= 0:
                break
            print("[{}] Resting for {:.0f}s".format(
                datetime.now().strftime("%H:%M:%S"), rest))
            time.sleep(rest)

        elif behaviour == "groom":
            # Quick short pulses (grooming)
            n = random.randint(2, 5)
            print("[{}] Grooming: {} quick pulses".format(
                datetime.now().strftime("%H:%M:%S"), n))
            for _ in range(n):
                motor_on(random.uniform(0.1, 0.4))
                time.sleep(random.uniform(0.2, 0.6))
            event_count += 1

        elif behaviour == "walk":
            # Medium duration movement
            dur = random.uniform(0.5, 2.0)
            print("[{}] Walking: {:.1f}s".format(
                datetime.now().strftime("%H:%M:%S"), dur))
            motor_on(dur)
            event_count += 1

        elif behaviour == "sustained":
            # Longer active period (exploring/foraging-like)
            dur = random.uniform(2.0, 5.0)
            print("[{}] Sustained movement: {:.1f}s".format(
                datetime.now().strftime("%H:%M:%S"), dur))
            motor_on(dur)
            time.sleep(random.uniform(0.5, 1.5))
            # Sometimes a second burst
            if random.random() < 0.5:
                motor_on(random.uniform(0.5, 2.0))
            event_count += 1

    print("\nBee mimic complete. {} activity events over {:.0f} minutes.".format(
        event_count, run_minutes))

# ---------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------
def main():
    setup_gpio()
    print("=" * 50)
    print("  Motor Mimic -- Bee Activity Simulator")
    print("=" * 50)
    print("  Motor pin: {} (BOARD)".format(MOTOR_PIN))
    print()
    print("  1. Fixed Interval    -- Every X seconds")
    print("  2. Random Dormancy   -- ~2 min rest + random bursts")
    print("  3. Scheduled Burst   -- N reps at a set time")
    print("  4. Bee Mimic         -- Randomised bee-like patterns")
    print()

    choice = input("Select mode (1-4): ").strip()

    try:
        if choice == "1":
            mode_fixed_interval()
        elif choice == "2":
            mode_random_dormancy()
        elif choice == "3":
            mode_scheduled_burst()
        elif choice == "4":
            mode_bee_mimic()
        else:
            print("Invalid choice.")
    finally:
        cleanup()

if __name__ == "__main__":
    main()