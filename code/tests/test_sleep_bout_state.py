import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta


CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from sleep_bout_state import (
    RollingMotionAverage,
    SleepBoutStateMachine,
    SleepLogWriter,
)


BASE = datetime(2026, 7, 8, 20, 0, 0)


class SleepBoutStateMachineTests(unittest.TestCase):
    def make_state(self):
        return SleepBoutStateMachine(threshold=0.005, minimum_duration_seconds=120)

    def test_exactly_120_seconds_does_not_confirm(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        transition = state.update(BASE + timedelta(seconds=120), 0.001)
        self.assertIsNone(transition)
        self.assertEqual("candidate", state.status)

        transition = state.update(BASE + timedelta(seconds=120, microseconds=1), 0.001)
        self.assertEqual("sleep_confirmed", transition["type"])
        self.assertEqual(BASE, transition["start_time"])

    def test_failed_candidate_resets_start_and_statistics(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        cancelled = state.update(BASE + timedelta(seconds=60), 0.006)
        self.assertEqual("candidate_cancelled", cancelled["type"])
        self.assertEqual("active", state.status)

        second_start = BASE + timedelta(seconds=61)
        started = state.update(second_start, 0.002)
        self.assertEqual(second_start, started["start_time"])
        self.assertEqual(1, state.motion_count)
        self.assertAlmostEqual(0.002, state.motion_sum)

    def test_raw_motion_is_used_for_metrics_not_smoothed_detection_score(self):
        state = SleepBoutStateMachine(
            threshold=0.005,
            minimum_duration_seconds=0,
        )
        state.update(BASE, 0.004, metric_score=0.02)
        state.update(
            BASE + timedelta(seconds=1),
            0.004,
            metric_score=0.03,
        )
        bout = state.update(
            BASE + timedelta(seconds=2),
            0.006,
            metric_score=0.9,
        )["bout"]

        self.assertAlmostEqual(0.025, bout.average_motion)
        self.assertAlmostEqual(0.02, bout.minimum_motion)
        self.assertAlmostEqual(0.03, bout.maximum_motion)

    def test_one_completed_record_for_an_entire_bout(self):
        state = self.make_state()
        transitions = []
        transitions.append(state.update(BASE, 0.001))
        for second in (30, 60, 90, 120, 121, 180, 240, 300):
            transitions.append(state.update(BASE + timedelta(seconds=second), 0.001))
        transitions.append(state.update(BASE + timedelta(seconds=360), 0.006))

        completed = [
            transition["bout"]
            for transition in transitions
            if transition and transition["type"] == "bout_completed"
        ]
        self.assertEqual(1, len(completed))
        self.assertEqual(BASE, completed[0].start_time)
        self.assertEqual(BASE + timedelta(seconds=360), completed[0].end_time)
        self.assertTrue(completed[0].bout_complete)

    def test_consecutive_bouts_are_unique_and_never_overlap(self):
        state = self.make_state()
        bouts = []

        state.update(BASE, 0.001)
        state.update(BASE + timedelta(seconds=121), 0.001)
        first = state.update(BASE + timedelta(seconds=180), 0.006)
        bouts.append(first["bout"])

        second_start = BASE + timedelta(seconds=181)
        state.update(second_start, 0.001)
        state.update(second_start + timedelta(seconds=121), 0.001)
        second = state.update(second_start + timedelta(seconds=160), 0.006)
        bouts.append(second["bout"])

        self.assertEqual(2, len(bouts))
        self.assertLessEqual(bouts[0].end_time, bouts[1].start_time)
        self.assertNotEqual(bouts[0].start_time, bouts[1].start_time)

    def test_above_threshold_frame_ends_sleep_without_short_gap_merge(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        state.update(BASE + timedelta(seconds=121), 0.001)
        ended = state.update(BASE + timedelta(seconds=122), 0.006)
        self.assertEqual("bout_completed", ended["type"])
        self.assertEqual("active", state.status)
        restarted = state.update(BASE + timedelta(seconds=123), 0.001)
        self.assertEqual("candidate_started", restarted["type"])
        self.assertEqual(BASE + timedelta(seconds=123), restarted["start_time"])

    def test_shutdown_writes_only_a_confirmed_bout_as_incomplete(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        self.assertIsNone(state.finalize(BASE + timedelta(seconds=60)))

        state = self.make_state()
        state.update(BASE, 0.001)
        state.update(BASE + timedelta(seconds=121), 0.001)
        bout = state.finalize(BASE + timedelta(seconds=180))
        self.assertIsNotNone(bout)
        self.assertFalse(bout.bout_complete)
        self.assertEqual("experiment_stopped", bout.end_reason)

    def test_out_of_order_timestamps_are_rejected(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        with self.assertRaises(ValueError):
            state.update(BASE - timedelta(seconds=1), 0.001)

    def test_monotonic_clock_controls_confirmation_across_wall_clock_changes(self):
        state = self.make_state()
        state.update(BASE, 0.001, monotonic_time=1000.0)

        transition = state.update(
            BASE + timedelta(days=1), 0.001, monotonic_time=1120.0
        )
        self.assertIsNone(transition)
        self.assertEqual("candidate", state.status)

        confirmed = state.update(
            BASE - timedelta(days=1), 0.001, monotonic_time=1120.001
        )
        self.assertEqual("sleep_confirmed", confirmed["type"])

        completed = state.update(BASE, 0.006, monotonic_time=1130.0)["bout"]
        record = completed.to_record(
            threshold=0.005, minimum_duration_seconds=120
        )
        self.assertEqual(130.0, record["duration_seconds"])

    def test_record_uses_exact_legacy_matlab_schema(self):
        state = self.make_state()
        state.update(BASE, 0.001)
        state.update(BASE + timedelta(seconds=121), 0.002)
        bout = state.update(BASE + timedelta(seconds=180), 0.006)["bout"]

        record = bout.to_record(
            threshold=0.005, minimum_duration_seconds=120
        )

        self.assertEqual(
            {
                "start_time",
                "end_time",
                "duration_seconds",
                "average_motion",
                "motion_range",
            },
            set(record),
        )
        self.assertEqual({"min", "max"}, set(record["motion_range"]))

    def test_observation_interruption_cancels_candidate(self):
        state = self.make_state()
        state.update(BASE, 0.001, monotonic_time=1000.0)
        state.update(BASE + timedelta(seconds=60), 0.001, monotonic_time=1060.0)

        interrupted = state.interrupt("camera_observation_gap")

        self.assertEqual("candidate_cancelled", interrupted["type"])
        self.assertEqual("camera_observation_gap", interrupted["reason"])
        self.assertEqual("active", state.status)

    def test_observation_interruption_clears_hidden_active_persistence(self):
        state = SleepBoutStateMachine(
            threshold=0.005,
            minimum_duration_seconds=120,
            transition_persistence_seconds=2,
        )
        state.update(BASE, 0.001, monotonic_time=1000.0)
        self.assertIsNotNone(state.low_pending_time)

        self.assertIsNone(state.interrupt("camera_observation_gap"))
        self.assertIsNone(state.low_pending_time)

        after_gap = state.update(
            BASE + timedelta(seconds=10), 0.001, monotonic_time=1010.0
        )
        self.assertIsNone(after_gap)
        self.assertEqual("active", state.status)

    def test_observation_interruption_truncates_confirmed_bout(self):
        state = self.make_state()
        state.update(BASE, 0.001, monotonic_time=1000.0)
        state.update(BASE + timedelta(seconds=121), 0.001, monotonic_time=1121.0)
        last_observation = BASE + timedelta(seconds=150)
        state.update(last_observation, 0.001, monotonic_time=1150.0)

        interrupted = state.interrupt("camera_read_failed")
        bout = interrupted["bout"]

        self.assertEqual("bout_interrupted", interrupted["type"])
        self.assertEqual(last_observation, bout.end_time)
        self.assertEqual("camera_read_failed", bout.end_reason)
        self.assertFalse(bout.bout_complete)
        self.assertEqual(150.0, bout.duration_seconds)
        self.assertEqual("active", state.status)

    def test_transition_persistence_blocks_near_threshold_chatter(self):
        state = SleepBoutStateMachine(
            threshold=0.005,
            minimum_duration_seconds=120,
            transition_persistence_seconds=2,
        )

        transitions = []
        for half_second in range(600):
            now = BASE + timedelta(seconds=half_second / 2.0)
            motion = 0.0048 if half_second % 2 == 0 else 0.0052
            transition = state.update(
                now,
                motion,
                monotonic_time=half_second / 2.0,
            )
            if transition is not None:
                transitions.append(transition["type"])

        self.assertEqual([], transitions)
        self.assertEqual("active", state.status)

    def test_transition_persistence_allows_sustained_low_and_high_motion(self):
        state = SleepBoutStateMachine(
            threshold=0.005,
            minimum_duration_seconds=120,
            transition_persistence_seconds=2,
        )

        self.assertIsNone(state.update(BASE, 0.001, monotonic_time=0.0))
        started = state.update(
            BASE + timedelta(seconds=2), 0.001, monotonic_time=2.0
        )
        self.assertEqual("candidate_started", started["type"])

        confirmed = state.update(
            BASE + timedelta(seconds=123), 0.001, monotonic_time=123.0
        )
        self.assertEqual("sleep_confirmed", confirmed["type"])

        self.assertIsNone(
            state.update(BASE + timedelta(seconds=124), 0.006, monotonic_time=124.0)
        )
        completed = state.update(
            BASE + timedelta(seconds=126), 0.006, monotonic_time=126.0
        )
        self.assertEqual("bout_completed", completed["type"])
        self.assertEqual(BASE + timedelta(seconds=124), completed["bout"].end_time)


class RollingMotionAverageTests(unittest.TestCase):
    def test_window_discards_samples_older_than_120_seconds(self):
        window = RollingMotionAverage(window_seconds=120, minimum_samples=1)
        window.add(0.0, 0.001)
        window.add(120.0, 0.003)
        self.assertAlmostEqual(0.002, window.average)

        window.add(120.001, 0.005)

        self.assertEqual(2, len(window.samples))
        self.assertAlmostEqual(0.004, window.average)

    def test_window_is_not_ready_until_minimum_samples_arrive(self):
        window = RollingMotionAverage(window_seconds=120, minimum_samples=3)
        window.add(0.0, 0.001)
        window.add(0.1, 0.001)
        self.assertFalse(window.ready)
        window.add(0.2, 0.001)
        self.assertTrue(window.ready)

    def test_clear_removes_average_and_prevents_history_reuse(self):
        window = RollingMotionAverage(window_seconds=120, minimum_samples=1)
        window.add(100.0, 0.02)

        window.clear()

        self.assertIsNone(window.average)
        self.assertFalse(window.ready)
        self.assertAlmostEqual(0.001, window.add(1.0, 0.001))

    def test_120_second_average_absorbs_repeated_single_frame_noise(self):
        window = RollingMotionAverage(window_seconds=120, minimum_samples=31)
        for frame_number in range(300):
            raw_motion = 0.006 if frame_number % 10 == 9 else 0.004
            window.add(frame_number / 30.0, raw_motion)

        self.assertTrue(window.ready)
        self.assertLess(window.average, 0.005)


class SleepLogWriterTests(unittest.TestCase):
    def make_record(self, start_time, end_time, duration):
        return {
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration,
            "average_motion": 0.001,
            "motion_range": {"min": 0.0, "max": 0.002},
        }

    def test_start_date_filename_does_not_rotate_at_midnight(self):
        experiment_start = datetime(2026, 7, 8, 23, 59, 0)
        with tempfile.TemporaryDirectory() as directory:
            writer = SleepLogWriter(directory, experiment_start)
            self.assertEqual(
                os.path.join(directory, "sleep_log_20260708.json"), writer.path
            )
            record = self.make_record(
                "2026-07-08 23:59:00", "2026-07-09 04:00:00", 14460
            )
            self.assertTrue(writer.append(record))
            self.assertTrue(os.path.exists(writer.path))
            self.assertFalse(
                os.path.exists(os.path.join(directory, "sleep_log_20260709.json"))
            )

    def test_empty_json_file_is_created_when_experiment_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = SleepLogWriter(directory, BASE)

            with open(writer.path, "r") as handle:
                records = json.load(handle)
            self.assertEqual([], records)

    def test_records_append_once_and_duplicate_start_time_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = SleepLogWriter(directory, BASE)
            first = self.make_record("one", "one-end", 180)
            second = self.make_record("two", "two-end", 240)
            self.assertTrue(writer.append(first))
            self.assertFalse(writer.append(first))
            self.assertTrue(writer.append(second))

            with open(writer.path, "r") as handle:
                records = json.load(handle)
            self.assertEqual(["one", "two"], [record["start_time"] for record in records])

    def test_enriched_existing_row_is_converted_to_legacy_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = SleepLogWriter(directory, BASE)
            enriched = self.make_record("one", "one-end", 180)
            enriched.update(
                {
                    "bout_id": "internal-one",
                    "confirmation_time": "confirmation",
                    "bout_complete": True,
                    "end_reason": "motion_above_threshold",
                    "detection_config": {"sleep_threshold": 0.005},
                    "software_version": "2.0-clean-bouts",
                }
            )
            writer._write_atomic([enriched])

            self.assertFalse(writer.append(enriched))

            with open(writer.path, "r") as handle:
                records = json.load(handle)
            self.assertEqual(set(writer.LEGACY_FIELDS), set(records[0]))

    def test_enriched_file_is_converted_when_writer_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sleep_log_20260708.json")
            enriched = self.make_record("one", "one-end", 180)
            enriched["bout_id"] = "internal-one"
            enriched["software_version"] = "2.0-clean-bouts"
            with open(path, "w") as handle:
                json.dump([enriched], handle)

            writer = SleepLogWriter(directory, BASE)

            with open(writer.path, "r") as handle:
                records = json.load(handle)
            self.assertEqual(set(writer.LEGACY_FIELDS), set(records[0]))

    def test_state_machine_and_writer_produce_unique_non_overlapping_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = SleepLogWriter(directory, BASE)
            state = SleepBoutStateMachine(
                threshold=0.005, minimum_duration_seconds=120
            )

            completed = []
            timeline = [
                (0, 0.001),
                (60, 0.001),
                (121, 0.001),
                (300, 0.001),
                (360, 0.006),
                (361, 0.001),
                (482, 0.001),
                (600, 0.001),
                (660, 0.006),
            ]
            for seconds, motion in timeline:
                transition = state.update(BASE + timedelta(seconds=seconds), motion)
                if transition and transition["type"] == "bout_completed":
                    completed.append(transition["bout"])
                    writer.append(
                        transition["bout"].to_record(
                            threshold=0.005, minimum_duration_seconds=120
                        )
                    )

            with open(writer.path, "r") as handle:
                records = json.load(handle)
            self.assertEqual(2, len(completed))
            self.assertEqual(2, len(records))
            self.assertLessEqual(completed[0].end_time, completed[1].start_time)
            self.assertEqual(len(records), len({row["start_time"] for row in records}))


if __name__ == "__main__":
    unittest.main()
