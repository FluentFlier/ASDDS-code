import importlib
import os
import sys
import types
import unittest
from collections import deque
from datetime import datetime, timedelta


CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)


def import_detector_module():
    cv2 = types.ModuleType("cv2")
    numpy = types.ModuleType("numpy")
    jetson = types.ModuleType("Jetson")
    gpio = types.ModuleType("Jetson.GPIO")
    jetson.GPIO = gpio

    replacements = {
        "cv2": cv2,
        "numpy": numpy,
        "Jetson": jetson,
        "Jetson.GPIO": gpio,
    }
    previous = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    try:
        sys.modules.pop("led_sleep_detect_clean", None)
        return importlib.import_module("led_sleep_detect_clean")
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


detector_module = import_detector_module()
CaliBeeMotionDetector = detector_module.CaliBeeMotionDetector
RollingMotionAverage = detector_module.RollingMotionAverage
SleepBoutStateMachine = detector_module.SleepBoutStateMachine


class FakeLogger(object):
    def __init__(self):
        self.messages = []

    def _add(self, level, message, *args):
        self.messages.append((level, message % args if args else message))

    def info(self, message, *args):
        self._add("info", message, *args)

    def warning(self, message, *args):
        self._add("warning", message, *args)

    def error(self, message, *args):
        self._add("error", message, *args)

    def critical(self, message, *args):
        self._add("critical", message, *args)


class FakeBout(object):
    def to_record(self, threshold, minimum_duration_seconds):
        return {
            "start_time": "2026-07-21 12:00:00",
            "end_time": "2026-07-21 12:03:00",
            "duration_seconds": 180.0,
            "average_motion": 0.001,
            "motion_range": {"min": 0.0, "max": 0.002},
        }


class FailOnceWriter(object):
    def __init__(self):
        self.attempts = 0
        self.records = []

    def append(self, record):
        self.attempts += 1
        if self.attempts == 1:
            raise OSError("temporary disk failure")
        self.records.append(record)
        return True


class FailedCamera(object):
    def isOpened(self):
        return True

    def read(self):
        return False, None


class RecordingState(object):
    def __init__(self):
        self.calls = []

    def update(self, now, motion_score, monotonic_time=None, metric_score=None):
        self.calls.append(
            {
                "now": now,
                "motion_score": motion_score,
                "monotonic_time": monotonic_time,
                "metric_score": metric_score,
            }
        )
        return None


class DetectorPersistenceTests(unittest.TestCase):
    def make_detector(self):
        detector = CaliBeeMotionDetector.__new__(CaliBeeMotionDetector)
        detector.logger = FakeLogger()
        detector.log_writer = FailOnceWriter()
        detector._pending_records = []
        detector._last_persist_attempt = None
        return detector

    def test_failed_bout_write_is_retained_and_retried(self):
        detector = self.make_detector()

        detector._record_bout(FakeBout())
        self.assertEqual(1, len(detector._pending_records))

        self.assertTrue(detector._flush_pending_records(force=True))
        self.assertEqual([], detector._pending_records)
        self.assertEqual(1, len(detector.log_writer.records))
        self.assertEqual(
            "2026-07-21 12:00:00",
            detector.log_writer.records[0]["start_time"],
        )

    def test_readding_same_pending_bout_does_not_duplicate_retry(self):
        detector = self.make_detector()

        detector._record_bout(FakeBout())
        detector._record_bout(FakeBout())

        self.assertEqual([], detector._pending_records)
        self.assertEqual(1, len(detector.log_writer.records))

    def test_permanent_camera_failure_returns_nonzero_status(self):
        detector = self.make_detector()
        detector.state = SleepBoutStateMachine()
        detector._shutdown_requested = False
        detector.frame_count = 0
        detector.motion_history = []
        detector.detection_window = RollingMotionAverage()
        detector.set_led_state = lambda sleeping: None
        detector._cleanup = lambda camera=None: None
        detector_module.cv2.CAP_GSTREAMER = object()
        detector_module.cv2.VideoCapture = lambda pipeline, backend: FailedCamera()

        self.assertEqual(2, detector.run())

    def test_detector_classifies_with_average_and_keeps_raw_motion_for_metrics(self):
        detector = self.make_detector()
        detector.state = RecordingState()
        now = datetime(2026, 7, 21, 12, 0, 0)

        detector.update_sleep_state(now, 0.02, 0.004, monotonic_time=100.0)

        call = detector.state.calls[0]
        self.assertEqual(0.004, call["motion_score"])
        self.assertEqual(0.02, call["metric_score"])
        self.assertEqual(100.0, call["monotonic_time"])

    def test_candidate_reset_clears_detection_average_but_not_display_history(self):
        detector = self.make_detector()
        detector.motion_history = deque([0.004, 0.006], maxlen=300)
        detector.detection_window = RollingMotionAverage(minimum_samples=1)
        detector.detection_window.add(1.0, 0.004)

        detector._handle_transition(
            {
                "type": "candidate_cancelled",
                "cancelled_at": datetime(2026, 7, 21, 12, 0, 1),
            },
            instant_motion=0.006,
            detection_motion=0.006,
        )

        self.assertEqual([0.004, 0.006], list(detector.motion_history))
        self.assertIsNone(detector.detection_window.average)

    def test_candidate_start_resets_average_but_sleep_confirmation_keeps_it(self):
        detector = self.make_detector()
        detector.detection_window = RollingMotionAverage(minimum_samples=1)
        detector.detection_window.add(1.0, 0.004)
        detector.set_led_state = lambda sleeping: None

        detector._handle_transition(
            {
                "type": "candidate_started",
                "start_time": datetime(2026, 7, 21, 12, 0, 0),
            }
        )
        self.assertIsNone(detector.detection_window.average)

        detector.detection_window.add(2.0, 0.003)
        detector._handle_transition(
            {
                "type": "sleep_confirmed",
                "start_time": datetime(2026, 7, 21, 12, 0, 0),
                "confirmation_time": datetime(2026, 7, 21, 12, 2, 1),
            }
        )
        self.assertAlmostEqual(0.003, detector.detection_window.average)

    def test_failed_candidate_cannot_seed_the_next_candidate(self):
        detector = self.make_detector()
        detector.state = SleepBoutStateMachine(
            threshold=0.005, minimum_duration_seconds=120
        )
        detector.detection_window = RollingMotionAverage(
            window_seconds=120, minimum_samples=3
        )
        detector.set_led_state = lambda sleeping: None
        base = datetime(2026, 7, 21, 12, 0, 0)

        def feed(second, raw_motion):
            average = detector.detection_window.add(second, raw_motion)
            if detector.detection_window.ready:
                detector.update_sleep_state(
                    base + timedelta(seconds=second),
                    raw_motion,
                    average,
                    monotonic_time=second,
                )

        for second in range(3):
            feed(second, 0.001)
        self.assertEqual("candidate", detector.state.status)
        self.assertEqual(base + timedelta(seconds=2), detector.state.candidate_start)
        self.assertIsNone(detector.detection_window.average)

        for second in range(3, 6):
            feed(second, 0.02)
        self.assertEqual("active", detector.state.status)
        self.assertIsNone(detector.detection_window.average)

        for second in range(6, 9):
            feed(second, 0.001)
        self.assertEqual("candidate", detector.state.status)
        self.assertEqual(base + timedelta(seconds=8), detector.state.candidate_start)

    def test_interrupted_bout_is_not_written_as_a_completed_matlab_row(self):
        detector = self.make_detector()
        detector.detection_window = RollingMotionAverage(minimum_samples=1)
        detector.detection_window.add(1.0, 0.001)
        detector.set_led_state = lambda sleeping: None

        bout_state = SleepBoutStateMachine(
            threshold=0.005, minimum_duration_seconds=0
        )
        base = datetime(2026, 7, 21, 12, 0, 0)
        bout_state.update(base, 0.001, monotonic_time=0.0)
        bout_state.update(base + timedelta(seconds=1), 0.001, monotonic_time=1.0)
        interrupted = bout_state.interrupt("camera_read_failed")

        detector._handle_transition(interrupted)

        self.assertEqual([], detector._pending_records)
        self.assertEqual([], detector.log_writer.records)
        self.assertIsNone(detector.detection_window.average)
        self.assertTrue(
            any(
                "not added to MATLAB JSON" in message
                for _level, message in detector.logger.messages
            )
        )

    def test_production_average_and_persistence_do_not_chatter_near_threshold(self):
        detector = self.make_detector()
        detector.state = SleepBoutStateMachine(
            threshold=0.005,
            minimum_duration_seconds=120,
            transition_persistence_seconds=2,
        )
        detector.detection_window = RollingMotionAverage(
            window_seconds=120, minimum_samples=31
        )
        detector.set_led_state = lambda sleeping: None
        base = datetime(2026, 7, 21, 12, 0, 0)
        transition_types = []

        for frame_number in range(30 * 300):
            tick = frame_number / 30.0
            raw_motion = (
                0.0048 if (frame_number // 15) % 2 == 0 else 0.0052
            )
            average = detector.detection_window.add(tick, raw_motion)
            if not detector.detection_window.ready:
                continue
            transition = detector.state.update(
                base + timedelta(seconds=tick),
                average,
                monotonic_time=tick,
                metric_score=raw_motion,
            )
            if transition is None:
                continue
            transition_types.append(transition["type"])
            detector._handle_transition(transition, raw_motion, average)

        self.assertEqual(
            ["candidate_started", "sleep_confirmed"], transition_types
        )


if __name__ == "__main__":
    unittest.main()
