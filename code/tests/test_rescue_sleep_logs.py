import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import rescue_sleep_logs


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class CompleteRescuePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temporary_directory.name)
        rescue_sleep_logs.run(WORKSPACE_ROOT, cls.output_dir)
        cls.manifest = json.loads(
            (cls.output_dir / "rescue_manifest.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def test_all_34_files_are_processed_and_none_are_deferred(self):
        self.assertEqual("2.0", self.manifest["pipeline_version"])
        self.assertEqual(34, self.manifest["processed_file_count"])
        self.assertEqual(23, self.manifest["standard_120_second_file_count"])
        self.assertEqual(11, self.manifest["legacy_10_second_file_count"])
        self.assertEqual(0, self.manifest["deferred_file_count"])
        deferred = json.loads(
            (self.output_dir / "deferred_10_second_files.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], deferred)

    def test_audited_totals_are_stable(self):
        self.assertEqual(
            {
                "raw_rows": 14454,
                "unique_start_times": 7138,
                "same_start_snapshots_removed": 7316,
                "exact_120_second_bouts_excluded": 504,
                "shorter_than_120_second_bouts_excluded": 3985,
                "other_duration_exclusions": 0,
                "retained_bouts": 2649,
                "finalized_groups_selected": 1551,
                "lower_bound_groups_selected": 5587,
                "retained_finalized_bouts": 1418,
                "retained_lower_bound_bouts": 1231,
                "retained_overlapping_bouts": 849,
                "retained_one_second_gaps": 3,
            },
            self.manifest["totals"],
        )

    def test_every_clean_file_is_sorted_unique_and_uses_exact_schema(self):
        for summary in self.manifest["files"]:
            rows = json.loads(
                (self.output_dir / summary["output_file"]).read_text(
                    encoding="utf-8"
                )
            )
            expected_order = sorted(
                rows,
                key=lambda row: (
                    datetime.strptime(row["start_time"], TIME_FORMAT),
                    datetime.strptime(row["end_time"], TIME_FORMAT),
                ),
            )
            self.assertEqual(expected_order, rows, summary["output_file"])
            self.assertEqual(
                len(rows), len({row["start_time"] for row in rows})
            )
            for row in rows:
                self.assertEqual(
                    {"start_time", "end_time", "duration_seconds"}, set(row)
                )
                calculated = int(
                    (
                        datetime.strptime(row["end_time"], TIME_FORMAT)
                        - datetime.strptime(row["start_time"], TIME_FORMAT)
                    ).total_seconds()
                )
                self.assertEqual(calculated, row["duration_seconds"])
                self.assertGreater(row["duration_seconds"], 120)

    def test_legacy_files_are_checkpoint_only(self):
        legacy = [
            summary
            for summary in self.manifest["files"]
            if summary["detector_regime"] == "legacy_10_second_logging"
        ]
        self.assertEqual(11, len(legacy))
        self.assertTrue(
            all(summary["retained_finalized_bouts"] == 0 for summary in legacy)
        )
        self.assertEqual(673, sum(summary["retained_bouts"] for summary in legacy))


if __name__ == "__main__":
    unittest.main()
