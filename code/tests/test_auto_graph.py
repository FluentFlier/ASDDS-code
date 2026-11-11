import json
import os
import sys
import tempfile
import unittest
from datetime import datetime


CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import auto_graph


class AutoGraphTests(unittest.TestCase):
    def write_log(self, directory, rows):
        path = os.path.join(directory, "sleep_log_20260721.json")
        with open(path, "w") as handle:
            json.dump(rows, handle)
        return path

    def test_duplicate_snapshots_keep_latest_end_and_overlaps_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(
                directory,
                [
                    {"start_time": "2026-07-21 18:00:00", "end_time": "2026-07-21 18:03:00"},
                    {"start_time": "2026-07-21 18:00:00", "end_time": "2026-07-21 18:05:00"},
                    {"start_time": "2026-07-21 18:04:00", "end_time": "2026-07-21 18:10:00"},
                ],
            )

            bouts = auto_graph.load_bouts(path)

            self.assertEqual(1, len(bouts))
            self.assertEqual(datetime(2026, 7, 21, 18, 0), bouts[0][0])
            self.assertEqual(datetime(2026, 7, 21, 18, 10), bouts[0][1])

    def test_bout_crossing_noon_is_split_between_rows(self):
        bouts = [
            (
                datetime(2026, 7, 21, 11, 30),
                datetime(2026, 7, 21, 12, 30),
            )
        ]

        pieces = auto_graph.split_bouts_by_experiment_day(bouts)

        self.assertEqual(2, len(pieces))
        self.assertEqual([(23.5, 0.5)], pieces[datetime(2026, 7, 20, 12, 0)])
        self.assertEqual([(0.0, 0.5)], pieces[datetime(2026, 7, 21, 12, 0)])

    def test_empty_log_still_produces_png(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, [])
            output = os.path.join(directory, "summary.png")

            result = auto_graph.render_graph(path, output)

            self.assertEqual(output, result)
            self.assertTrue(os.path.isfile(output))
            self.assertGreater(os.path.getsize(output), 1000)

    def test_invalid_timestamp_is_rejected_with_row_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(
                directory,
                [{"start_time": "bad", "end_time": "2026-07-21 18:03:00"}],
            )
            with self.assertRaisesRegex(ValueError, "row 1"):
                auto_graph.load_bouts(path)


if __name__ == "__main__":
    unittest.main()
