# Data dictionary and cleaning protocol

## Scope

This document defines the raw and cleaned JSON structures, the two cleanup
pipelines, their lineage rules, and the limits on scientific interpretation.

## Directory-level data model

### `bee_motion_logs/`

Primary historical files copied from the acquisition environment.

- `sleep_log*.json`: sleep-record arrays.
- `sleep_log_20250124_Deadbee`: JSON content without a `.json` suffix, retained
  under its original name.
- `detector*.log`: diagnostic runtime text logs.
- `*.png`: historical figures or screenshots.
- `cleaned/`: generated cleaned copies of primary files not included in the
  focused rescue set.

### `json files to be rescued/`

Thirty-four copied source files selected for focused reconstruction. Their
cleaned outputs and audit products are under `cleaned/`.

## Raw historical JSON schema

Most primary rows include:

| Field | Type | Meaning |
|---|---|---|
| `start_time` | string | Whole-second local timestamp, `%Y-%m-%d %H:%M:%S` |
| `end_time` | string | Whole-second local timestamp |
| `duration_seconds` | number | Historical timer duration, often subsecond precision |
| `average_motion` | number | Motion statistic written by detector version in use |
| `motion_range` | object | Historical `min` and `max` motion values |
| `bout_complete` | boolean, optional | Explicit final wake/completion marker in newer logs |
| `solenoid_active` | boolean, optional | Disruption-state field in some historical rows |
| `solenoid_window` | object, optional | Scheduled disruption window in some rows |

Not all versions use the same optional fields. The raw records are preserved so
version-specific information remains available.

## Cleaned analysis schema

Every cleaned row intentionally contains only:

```json
{
  "start_time": "2026-03-18 21:48:34",
  "end_time": "2026-03-18 22:03:07",
  "duration_seconds": 873
}
```

`duration_seconds` is an integer derived from whole-second timestamps. Motion
fields are omitted because selecting an endpoint from several checkpoints does
not create one clearly defined aggregate motion measurement.

## Pipeline A: focused rescue

Command:

```bash
python3 rescue_sleep_logs.py
```

Inputs:

- 34 files in `json files to be rescued/`.
- all valid matching records in `bee_motion_logs/`, used as primary endpoint
  evidence.

Outputs:

- one `sleep_log_YYYYMMDD_clean.json` per rescue input;
- `rescue_manifest.json` and `.csv`;
- `rescue_record_audit.json`;
- `legacy_10_second_files.json`;
- `deferred_10_second_files.json`, currently an empty list.

The pipeline fails instead of writing output when a rescue record has no
matching primary-source signature.

## Pipeline B: remaining primary files

Command:

```bash
python3 clean_bee_motion_logs.py
```

Scope:

1. Find top-level files matching `bee_motion_logs/sleep_log*`.
2. Exclude the 34 filenames already present in the focused rescue input set.
3. Process every remaining valid source independently.
4. Record unreadable files without fabricating cleaned output.

Outputs:

- 125 `*_clean.json` files;
- `cleaning_manifest.json`;
- `cleaning_record_audit.json`;
- `already_rescued_files.json`;
- `uncleanable_files.json`.

## Record selection algorithm

For one input file:

1. Validate that the payload is a JSON array of objects.
2. Validate required fields: `start_time`, `end_time`, and `duration_seconds`.
3. Match each raw record to at least one primary-source signature after ignoring
   only the `bout_complete` field.
4. Group rows by exact `start_time` string.
5. Within each group:
   - prefer a matching primary record marked `bout_complete: true`;
   - if several completed matches exist, choose the latest end time, then the
     largest stored duration;
   - otherwise choose the group row with latest end time, then largest stored
     duration.
6. Recalculate integer duration from parsed timestamps.
7. Exclude duration `<= 120` seconds.
8. Keep all retained groups with different starts separate.
9. Sort by start time, then end time.

## Endpoint interpretation

### `final_detector_wake`

The selected source record had `bout_complete: true`. It is final according to
the detector implementation. It is not an independent behavioral observation.

### `lower_bound_checkpoint`

No explicit completion record matched. The selected endpoint is the last saved
time at which the historical detector still reported the bout. The true wake
could have occurred later.

Do not compare finalized and lower-bound durations as if their censoring were
identical without a sensitivity analysis.

## Why duration is recomputed

Raw timestamps use whole seconds while stored duration often retains fractions
of a second. The cleanup uses:

```text
integer(end_time - start_time in seconds)
```

This makes the threshold deterministic and auditable. It loses subsecond
precision that is not represented in the stored timestamps.

## Why the threshold is strictly greater than 120 seconds

The approved analysis rule requires `duration_seconds > 120`. A candidate with
exactly 120 seconds is excluded. The same biological filter is applied to the
standard and historical short-regime rescue files.

This threshold is a project decision, not a universal biological definition.
Any change requires a new documented analysis version and regenerated
manifests.

## Overlap policy

Different start times are not merged or deleted. The record audit calculates:

- gap from the previous selected end;
- whether the gap is exactly one second;
- whether the bout overlaps any earlier retained bout;
- maximum overlap in seconds at that point;
- relationship action, currently `kept_separate`.

The policy differs from an early recommendation in the source correspondence
to resolve or merge overlaps. That recommendation did not specify a defensible
rule for competing onsets. The approved rescue policy therefore preserves the
candidates and exposes the uncertainty.

## Manifest fields

Each file summary includes:

| Field | Meaning |
|---|---|
| `detector_regime` | File-level historical category |
| `input_file`, `output_file` | Lineage filenames |
| `input_sha256`, `output_sha256` | Integrity hashes |
| `raw_rows` | Source rows processed |
| `unique_start_times` | Same-start groups |
| `same_start_snapshots_removed` | Raw rows minus groups |
| `exact_120_second_bouts_excluded` | Selected candidates equal to threshold |
| `shorter_than_120_second_bouts_excluded` | Selected candidates below threshold |
| `retained_bouts` | Cleaned rows |
| `finalized_groups_selected` | Groups selected from completion records |
| `lower_bound_groups_selected` | Groups selected from checkpoints |
| `retained_overlapping_bouts` | Retained rows flagged as overlapping |
| `retained_one_second_gaps` | Retained rows starting one second after prior selected end |

## Record-audit fields

The record audit retains, for every unique start:

- source regime and filenames;
- selected start and end;
- timestamp-derived and original stored duration;
- source row indices and raw group count;
- selection basis and endpoint status;
- retention decision and exclusion reason;
- gap and overlap relationship fields.

This audit is the correct source for sensitivity analyses. Do not try to infer
selection history from the compact cleaned rows alone.

## Condition mapping

The condition mapping used for printable reports is hardcoded in
`build_condition_plot_pages.py`: 10 `Disrupted`, 9 `Intact`, and 15 unassigned
rescue sessions. The mapping is incomplete experimental metadata and must be
confirmed before final analysis.

## Integrity checks

Run:

```bash
python3 scripts/verify_repository.py
```

The verifier checks source/output hashes, schema, order, unique starts,
timestamp-derived duration, the strict threshold, audited counts, zero-byte
exceptions, condition scope, handoff parity, and major deliverables.

## Rules for downstream analysis

- Use cleaned files for bout-level summaries, not raw checkpoint rows.
- Preserve the endpoint-status distinction.
- Declare whether and how overlaps are handled.
- Do not assign treatment condition from date alone.
- Do not treat the two cleaned collections as independent datasets without
  reviewing lineage.
- Keep the raw source hash and cleaning-pipeline version with derived results.
- Record any exclusions in a new machine-readable manifest.
