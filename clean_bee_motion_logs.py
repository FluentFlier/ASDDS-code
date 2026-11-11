#!/usr/bin/env python3
"""Clean the bee-motion sleep logs that were not part of the rescue batch.

Each source file is handled independently and is never modified.  Cleaned
copies are written under ``bee_motion_logs/cleaned``.  The cleaning rules match
the approved rescue pipeline: collapse records that share a start time, prefer
an explicit completed-bout endpoint when one exists, otherwise retain the
latest checkpoint, recompute duration from timestamps, and keep only bouts
strictly longer than 120 seconds.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rescue_sleep_logs import (
    PIPELINE_VERSION as RESCUE_PIPELINE_VERSION,
    atomic_write_text,
    canonical_without_completion,
    load_json_array,
    process_file,
    sha256_file,
    write_json,
)


PIPELINE_VERSION = "1.0"


def cleaned_name(source: Path) -> str:
    """Return a JSON output name without requiring the source to have a suffix."""
    stem = source.stem if source.suffix == ".json" else source.name
    return f"{stem}_clean.json"


def build_primary_indexes(
    valid_sources: dict[Path, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """Index valid primary records without failing on unrelated empty files."""
    completed_by_start: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources_by_signature: dict[str, list[str]] = defaultdict(list)

    for path in sorted(valid_sources):
        for row in valid_sources[path]:
            signature = canonical_without_completion(row)
            if path.name not in sources_by_signature[signature]:
                sources_by_signature[signature].append(path.name)
            if row.get("bout_complete") is True:
                completed = dict(row)
                completed["_source_file"] = path.name
                completed_by_start[row["start_time"]].append(completed)

    return completed_by_start, sources_by_signature


def render_readme(manifest: dict[str, Any]) -> str:
    totals = manifest["totals"]
    return f"""# Cleaned Remaining Bee-Motion Logs

This folder contains cleaned copies of the sleep logs in the parent
`bee_motion_logs/` directory that were not already handled by the separate
34-file rescue batch. The source files are preserved unchanged.

## Scope

- Primary sleep-log files found: {manifest['source_file_count']}
- Already handled by the rescue batch: {manifest['already_rescued_file_count']}
- Remaining files successfully cleaned: {manifest['processed_file_count']}
- Remaining files that could not be parsed: {manifest['uncleanable_file_count']}

## Cleaning rules

1. Process every source file independently; never combine files.
2. Collapse records sharing the same `start_time` to one bout.
3. Prefer a matching record with `bout_complete: true`; otherwise use the
   latest checkpoint for that start time.
4. Recalculate duration from `start_time` and `end_time`.
5. Retain only durations strictly greater than 120 seconds.
6. Keep different start times separate, including overlaps and one-second gaps.
7. Sort each cleaned file chronologically.

## Results

- Raw rows processed: {totals['raw_rows']:,}
- Unique start-time groups: {totals['unique_start_times']:,}
- Same-start snapshots removed: {totals['same_start_snapshots_removed']:,}
- Candidates shorter than 120 seconds excluded: {totals['shorter_than_120_second_bouts_excluded']:,}
- Candidates exactly 120 seconds excluded: {totals['exact_120_second_bouts_excluded']:,}
- Cleaned bouts retained: {totals['retained_bouts']:,}

`cleaning_manifest.json` contains file-level counts and hashes.
`cleaning_record_audit.json` contains the decision record for every distinct
start time. `uncleanable_files.json` records source files that contained no
parseable JSON; no cleaned data was fabricated for them.

## Reproduction

From the workspace root:

```bash
python3 clean_bee_motion_logs.py
```
"""


def run(root: Path, output_dir: Path) -> dict[str, Any]:
    primary_dir = root / "bee_motion_logs"
    rescue_dir = root / "json files to be rescued"
    source_paths = sorted(path for path in primary_dir.glob("sleep_log*") if path.is_file())
    already_rescued_names = {
        path.name for path in rescue_dir.glob("sleep_log_*.json") if path.is_file()
    }
    remaining_paths = [path for path in source_paths if path.name not in already_rescued_names]

    valid_sources: dict[Path, list[dict[str, Any]]] = {}
    invalid_sources: dict[Path, str] = {}
    for path in source_paths:
        try:
            valid_sources[path] = load_json_array(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            invalid_sources[path] = f"{type(error).__name__}: {error}"

    completed_by_start, sources_by_signature = build_primary_indexes(valid_sources)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    per_file_audits: dict[str, list[dict[str, Any]]] = {}
    uncleanable: list[dict[str, Any]] = []

    for input_path in remaining_paths:
        if input_path in invalid_sources:
            uncleanable.append(
                {
                    "input_file": input_path.name,
                    "size_bytes": input_path.stat().st_size,
                    "input_sha256": sha256_file(input_path),
                    "reason": invalid_sources[input_path],
                }
            )
            continue

        rows = valid_sources[input_path]
        detector_regime = (
            "primary_log_with_completion_markers"
            if any(row.get("bout_complete") is True for row in rows)
            else "checkpoint_only_primary_log"
        )
        output_path = output_dir / cleaned_name(input_path)
        summary, audit_events = process_file(
            input_path,
            output_path,
            completed_by_start,
            sources_by_signature,
            detector_regime=detector_regime,
        )
        summaries.append(summary)
        per_file_audits[input_path.name] = audit_events

    total_fields = (
        "raw_rows",
        "unique_start_times",
        "same_start_snapshots_removed",
        "exact_120_second_bouts_excluded",
        "shorter_than_120_second_bouts_excluded",
        "other_duration_exclusions",
        "retained_bouts",
        "finalized_groups_selected",
        "lower_bound_groups_selected",
        "retained_finalized_bouts",
        "retained_lower_bound_bouts",
        "retained_overlapping_bouts",
        "retained_one_second_gaps",
    )
    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "cleaning_rules_version": RESCUE_PIPELINE_VERSION,
        "source_directory": "bee_motion_logs",
        "output_directory": "bee_motion_logs/cleaned",
        "source_file_count": len(source_paths),
        "already_rescued_file_count": len(source_paths) - len(remaining_paths),
        "remaining_file_count": len(remaining_paths),
        "processed_file_count": len(summaries),
        "uncleanable_file_count": len(uncleanable),
        "rules": {
            "file_scope": "exclude_names_already_present_in_the_34_file_rescue_batch",
            "file_relationship": "process_each_source_independently",
            "same_start_times": "collapse_to_one_bout",
            "completed_selection": "bout_complete_source_record",
            "older_selection": "latest_checkpoint_lower_bound",
            "duration_filter": "timestamp_derived_duration_strictly_greater_than_120_seconds",
            "distinct_start_times": "always_keep_separate",
            "overlaps": "keep_separate_and_flag",
            "one_second_gaps": "keep_separate_and_flag",
        },
        "totals": {
            field: sum(summary[field] for summary in summaries) for field in total_fields
        },
        "files": summaries,
        "uncleanable_files": uncleanable,
    }

    write_json(output_dir / "cleaning_manifest.json", manifest)
    write_json(output_dir / "cleaning_record_audit.json", per_file_audits)
    write_json(output_dir / "already_rescued_files.json", sorted(already_rescued_names))
    write_json(output_dir / "uncleanable_files.json", uncleanable)
    atomic_write_text(output_dir / "README.md", render_readme(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Workspace root",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <root>/bee_motion_logs/cleaned)",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    output_dir = (
        arguments.output_dir.resolve()
        if arguments.output_dir is not None
        else root / "bee_motion_logs" / "cleaned"
    )
    run(root, output_dir)


if __name__ == "__main__":
    main()
