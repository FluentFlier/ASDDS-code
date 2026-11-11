#!/usr/bin/env python3
"""Create audited, structurally cleaned sleep-log files for every rescue input.

Both the standard 120-second detector sessions and the legacy 10-second logging
sessions use the approved biological filter of strictly more than 120 seconds.
Distinct start times remain separate, including overlapping or one-second-
separated events. Only records sharing an identical start time are collapsed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
PIPELINE_VERSION = "2.0"

LEGACY_10_SECOND_FILES = {
    "sleep_log_20250715.json",
    "sleep_log_20250717.json",
    "sleep_log_20250722.json",
    "sleep_log_20250827.json",
    "sleep_log_20250903.json",
    "sleep_log_20250909.json",
    "sleep_log_20250918.json",
    "sleep_log_20250924.json",
    "sleep_log_20250925.json",
    "sleep_log_20250930.json",
    "sleep_log_20251001.json",
}


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def timestamp_duration(record: dict[str, Any]) -> int:
    return int((parse_time(record["end_time"]) - parse_time(record["start_time"])).total_seconds())


def canonical_without_completion(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "bout_complete"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_array(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return payload


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=False) + "\n")


def load_primary_indexes(primary_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    completed_by_start: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources_by_signature: dict[str, list[str]] = defaultdict(list)

    for path in sorted(primary_dir.glob("sleep_log*")):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        rows = load_json_array(path)
        for row in rows:
            signature = canonical_without_completion(row)
            if path.name not in sources_by_signature[signature]:
                sources_by_signature[signature].append(path.name)
            if row.get("bout_complete") is True:
                completed = dict(row)
                completed["_source_file"] = path.name
                completed_by_start[row["start_time"]].append(completed)

    return completed_by_start, sources_by_signature


def select_record(
    start_time: str,
    group: list[tuple[int, dict[str, Any]]],
    completed_by_start: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], str, str | None]:
    group_signatures = {canonical_without_completion(row) for _, row in group}
    completed_matches = [
        row
        for row in completed_by_start.get(start_time, [])
        if canonical_without_completion({key: value for key, value in row.items() if key != "_source_file"})
        in group_signatures
    ]

    if completed_matches:
        selected = max(
            completed_matches,
            key=lambda row: (parse_time(row["end_time"]), float(row.get("duration_seconds", 0))),
        )
        source_file = selected.get("_source_file")
        return {key: value for key, value in selected.items() if key != "_source_file"}, "bout_complete", source_file

    selected = max(
        (row for _, row in group),
        key=lambda row: (parse_time(row["end_time"]), float(row.get("duration_seconds", 0))),
    )
    return dict(selected), "latest_checkpoint", None


def process_file(
    input_path: Path,
    output_path: Path,
    completed_by_start: dict[str, list[dict[str, Any]]],
    sources_by_signature: dict[str, list[str]],
    detector_regime: str = "standard_120_second",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = load_json_array(input_path)
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)

    for index, row in enumerate(rows):
        for required in ("start_time", "end_time", "duration_seconds"):
            if required not in row:
                raise ValueError(f"{input_path}: row {index} is missing {required}")
        duration = timestamp_duration(row)
        if duration < 0:
            raise ValueError(f"{input_path}: row {index} has a negative duration")
        signature = canonical_without_completion(row)
        if signature not in sources_by_signature:
            raise ValueError(f"{input_path}: row {index} has no primary-source match")
        groups[row["start_time"]].append((index, row))

    selected_events: list[dict[str, Any]] = []
    audit_events: list[dict[str, Any]] = []

    for start_time, group in groups.items():
        selected, selection_basis, selected_source = select_record(start_time, group, completed_by_start)
        duration = timestamp_duration(selected)
        retained = duration > 120
        source_files = sorted(
            {
                source
                for _, candidate in group
                for source in sources_by_signature[canonical_without_completion(candidate)]
            }
        )

        audit_event = {
            "detector_regime": detector_regime,
            "start_time": selected["start_time"],
            "selected_end_time": selected["end_time"],
            "timestamp_duration_seconds": duration,
            "selected_original_duration_seconds": selected.get("duration_seconds"),
            "raw_record_count": len(group),
            "raw_row_indices": [index for index, _ in group],
            "selection_basis": selection_basis,
            "endpoint_status": (
                "final_detector_wake" if selection_basis == "bout_complete" else "lower_bound_checkpoint"
            ),
            "selected_source_file": selected_source,
            "matching_primary_files": source_files,
            "retained": retained,
            "exclusion_reason": None if retained else "timestamp_duration_not_greater_than_120_seconds",
        }
        audit_events.append(audit_event)

        if retained:
            selected_events.append(
                {
                    "start_time": selected["start_time"],
                    "end_time": selected["end_time"],
                    "duration_seconds": duration,
                }
            )

    selected_events.sort(key=lambda row: (parse_time(row["start_time"]), parse_time(row["end_time"])))
    audit_by_start = {event["start_time"]: event for event in audit_events}

    running_end: datetime | None = None
    previous_end: datetime | None = None
    overlap_count = 0
    one_second_gap_count = 0

    for event in selected_events:
        start = parse_time(event["start_time"])
        end = parse_time(event["end_time"])
        gap = None if previous_end is None else int((start - previous_end).total_seconds())
        overlap_seconds = 0 if running_end is None else max(0, int((running_end - start).total_seconds()))
        overlap = overlap_seconds > 0
        if overlap:
            overlap_count += 1
        if gap == 1:
            one_second_gap_count += 1

        audit_by_start[event["start_time"]].update(
            {
                "gap_from_previous_selected_end_seconds": gap,
                "one_second_gap_from_previous": gap == 1,
                "overlap_with_any_previous": overlap,
                "overlap_seconds": overlap_seconds,
                "relationship_action": "kept_separate",
            }
        )
        previous_end = end
        running_end = end if running_end is None else max(running_end, end)

    for event in audit_events:
        if not event["retained"]:
            event.update(
                {
                    "gap_from_previous_selected_end_seconds": None,
                    "one_second_gap_from_previous": False,
                    "overlap_with_any_previous": False,
                    "overlap_seconds": 0,
                    "relationship_action": "excluded_by_duration_rule",
                }
            )

    audit_events.sort(key=lambda row: (parse_time(row["start_time"]), parse_time(row["selected_end_time"])))
    write_json(output_path, selected_events)

    finalized_count = sum(event["selection_basis"] == "bout_complete" for event in audit_events)
    checkpoint_count = sum(event["selection_basis"] == "latest_checkpoint" for event in audit_events)
    retained_finalized_count = sum(
        event["retained"] and event["selection_basis"] == "bout_complete" for event in audit_events
    )
    retained_checkpoint_count = sum(
        event["retained"] and event["selection_basis"] == "latest_checkpoint" for event in audit_events
    )
    exact_120_excluded = sum(
        not event["retained"] and event["timestamp_duration_seconds"] == 120 for event in audit_events
    )
    shorter_than_120_excluded = sum(
        not event["retained"] and event["timestamp_duration_seconds"] < 120
        for event in audit_events
    )

    summary = {
        "detector_regime": detector_regime,
        "duration_threshold_seconds": 120,
        "input_file": input_path.name,
        "output_file": output_path.name,
        "input_sha256": sha256_file(input_path),
        "output_sha256": sha256_file(output_path),
        "raw_rows": len(rows),
        "unique_start_times": len(groups),
        "same_start_snapshots_removed": len(rows) - len(groups),
        "exact_120_second_bouts_excluded": exact_120_excluded,
        "shorter_than_120_second_bouts_excluded": shorter_than_120_excluded,
        "other_duration_exclusions": sum(
            not event["retained"] and event["timestamp_duration_seconds"] > 120
            for event in audit_events
        ),
        "retained_bouts": len(selected_events),
        "finalized_groups_selected": finalized_count,
        "lower_bound_groups_selected": checkpoint_count,
        "retained_finalized_bouts": retained_finalized_count,
        "retained_lower_bound_bouts": retained_checkpoint_count,
        "retained_overlapping_bouts": overlap_count,
        "retained_one_second_gaps": one_second_gap_count,
    }
    return summary, audit_events


def write_summary_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    fieldnames = list(summaries[0].keys())
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summaries)
    os.replace(temporary, path)


def run(root: Path, output_dir: Path) -> None:
    rescue_dir = root / "json files to be rescued"
    primary_dir = root / "bee_motion_logs"
    candidates = sorted(rescue_dir.glob("sleep_log_*.json"))
    candidate_names = {path.name for path in candidates}

    missing_legacy = LEGACY_10_SECOND_FILES - candidate_names
    if missing_legacy:
        raise ValueError(f"Expected legacy files are missing: {sorted(missing_legacy)}")

    process_paths = candidates
    if len(process_paths) != 34:
        raise ValueError(f"Expected 34 rescue candidates; found {len(process_paths)}")

    completed_by_start, sources_by_signature = load_primary_indexes(primary_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    per_file_audits: dict[str, list[dict[str, Any]]] = {}

    for input_path in process_paths:
        output_path = output_dir / f"{input_path.stem}_clean.json"
        detector_regime = (
            "legacy_10_second_logging"
            if input_path.name in LEGACY_10_SECOND_FILES
            else "standard_120_second"
        )
        summary, audit_events = process_file(
            input_path,
            output_path,
            completed_by_start,
            sources_by_signature,
            detector_regime=detector_regime,
        )
        summaries.append(summary)
        per_file_audits[input_path.name] = audit_events

    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "rules": {
            "same_start_times": "collapse_to_one_bout",
            "completed_selection": "bout_complete_source_record",
            "older_selection": "latest_checkpoint_lower_bound",
            "duration_filter": "timestamp_derived_duration_strictly_greater_than_120_seconds",
            "duration_filter_scope": "applied_to_both_detector_regimes",
            "distinct_start_times": "always_keep_separate",
            "overlaps": "keep_separate_and_flag",
            "one_second_gaps": "keep_separate_and_flag",
            "july_8_2026": "included",
            "legacy_10_second_files": "processed_as_lower_bound_checkpoints",
        },
        "processed_file_count": len(summaries),
        "standard_120_second_file_count": sum(
            item["detector_regime"] == "standard_120_second" for item in summaries
        ),
        "legacy_10_second_file_count": sum(
            item["detector_regime"] == "legacy_10_second_logging" for item in summaries
        ),
        "deferred_file_count": 0,
        "totals": {
            "raw_rows": sum(item["raw_rows"] for item in summaries),
            "unique_start_times": sum(item["unique_start_times"] for item in summaries),
            "same_start_snapshots_removed": sum(item["same_start_snapshots_removed"] for item in summaries),
            "exact_120_second_bouts_excluded": sum(item["exact_120_second_bouts_excluded"] for item in summaries),
            "shorter_than_120_second_bouts_excluded": sum(
                item["shorter_than_120_second_bouts_excluded"] for item in summaries
            ),
            "other_duration_exclusions": sum(item["other_duration_exclusions"] for item in summaries),
            "retained_bouts": sum(item["retained_bouts"] for item in summaries),
            "finalized_groups_selected": sum(item["finalized_groups_selected"] for item in summaries),
            "lower_bound_groups_selected": sum(
                item["lower_bound_groups_selected"] for item in summaries
            ),
            "retained_finalized_bouts": sum(item["retained_finalized_bouts"] for item in summaries),
            "retained_lower_bound_bouts": sum(item["retained_lower_bound_bouts"] for item in summaries),
            "retained_overlapping_bouts": sum(item["retained_overlapping_bouts"] for item in summaries),
            "retained_one_second_gaps": sum(item["retained_one_second_gaps"] for item in summaries),
        },
        "files": summaries,
    }

    write_json(output_dir / "rescue_manifest.json", manifest)
    write_summary_csv(output_dir / "rescue_manifest.csv", summaries)
    write_json(output_dir / "rescue_record_audit.json", per_file_audits)
    write_json(output_dir / "legacy_10_second_files.json", sorted(LEGACY_10_SECOND_FILES))
    write_json(output_dir / "deferred_10_second_files.json", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Rescue workspace root",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: <root>/json files to be rescued/cleaned)",
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    output_dir = (
        arguments.output_dir.resolve()
        if arguments.output_dir is not None
        else root / "json files to be rescued" / "cleaned"
    )
    run(root, output_dir)


if __name__ == "__main__":
    main()
