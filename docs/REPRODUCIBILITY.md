# Reproducibility guide

## Goal

After following this guide, a new researcher or lab member can verify the
tracked data, rerun both cleaning pipelines, regenerate comparison plots and
printable PDFs, and run the software tests without Jetson hardware.

## Supported environment

- Python 3.10 or newer.
- macOS or Linux.
- Allow at least 1 GB for the checkout, dependencies, and regenerated files;
  the optional release video needs another 1.3 GB.
- Jetson hardware is required only for live acquisition and GPIO tests.

The last local verification used Python 3.10.14. The repository CI uses Python
3.10 on Ubuntu.

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-analysis.txt
```

Verify imports:

```bash
python -c "import matplotlib, numpy, pandas, reportlab; print('analysis dependencies OK')"
```

Expected:

```text
analysis dependencies OK
```

## Verify the tracked snapshot first

```bash
python3 -m unittest discover -s code/tests
python3 scripts/verify_repository.py
```

Expected test summary:

```text
Ran 48 tests
OK
```

Expected repository summary starts with:

```text
Repository verification passed
```

If this fails before regeneration, stop and inspect the named file. A hash
failure means a tracked source or generated output differs from its manifest.

## Rebuild the focused rescue outputs

```bash
python3 rescue_sleep_logs.py
```

Expected output directory:

```text
json files to be rescued/cleaned/
```

Key expected totals:

- 34 processed files.
- 14,454 raw rows.
- 2,649 retained bouts.
- 7,316 same-start snapshots removed.

The process writes each file atomically. It never writes into the 34-source
input directory except under its existing `cleaned/` child.

## Rebuild the remaining primary outputs

```bash
python3 clean_bee_motion_logs.py
```

Expected output directory:

```text
bee_motion_logs/cleaned/
```

Key expected totals:

- 161 primary sleep files discovered.
- 34 filenames excluded because they are already in the rescue batch.
- 127 remaining files considered.
- 125 cleaned files.
- 2 zero-byte sources recorded as uncleanable.
- 29,798 raw rows.
- 3,033 retained bouts.

## Regenerate rescue comparison plots

```bash
python3 plot_rescue_comparisons.py
```

Expected terminal JSON includes:

```json
{
  "plot_count": 34
}
```

Expected directory:

```text
json files to be rescued/cleaned/comparison_plots/
```

Each plot uses a noon-to-noon time axis and the same y-axis range in its raw and
clean panels. It recalculates raw durations from timestamps so the comparison
focuses on structural cleanup.

## Regenerate printable condition PDFs

```bash
python3 build_condition_plot_pages.py
```

Expected files:

```text
output/pdf/printable_disrupted_plots.pdf
output/pdf/printable_intact_plots.pdf
output/pdf/printable_disrupted_intact_plots.pdf
```

The script requires condition-specific plot copies under:

```text
json files to be rescued/cleaned/Disrupted/plots/
json files to be rescued/cleaned/Intact/plots/
```

It intentionally includes only the 19 assigned sessions.

## One-command rebuild

```bash
make reproduce
```

This runs both cleaners, comparison plots, PDFs, tests, and repository
verification in that order.

## Excel workbook boundary

The tracked workbook is:

```text
outputs/bee_sleep_condition_plots_20260721/bee_sleep_condition_plots.xlsx
```

The original workbook builder is not in this repository. The workbook and its
preview PNGs can be reviewed, but exact regeneration is not currently part of
`make reproduce`. A future task should reconstruct the builder from the cleaned
condition files and verify it against the retained workbook.

## Troubleshooting

### `ModuleNotFoundError: matplotlib`

Activate the environment and reinstall dependencies:

```bash
source .venv/bin/activate
python -m pip install -r requirements-analysis.txt
```

### `ModuleNotFoundError: reportlab`

The PDF builder needs ReportLab:

```bash
python -m pip install 'reportlab>=4,<5'
```

### Rescue pipeline reports no primary-source match

Cause: a rescue row changed, a primary file is missing, or the input is not the
audited source version.

Action:

1. Do not bypass the check.
2. Run `python3 scripts/verify_repository.py`.
3. Compare the source hash with `rescue_manifest.json`.
4. Restore the audited source from Git before rerunning.

### Remaining cleaner reports JSON decode failure

Two known files are zero bytes and are recorded in
`bee_motion_logs/cleaned/uncleanable_files.json`. Any additional decode failure
is new and should stop the release.

### Jetson import failure on a desktop computer

`Jetson.GPIO` and the JetPack GStreamer stack are hardware-specific. Do not
install them merely to run desktop data checks. The unit tests isolate or mock
hardware dependencies.

### Jetson camera cannot open

Run on-device:

```bash
bash ~/PyPro/check_jetson.sh
```

Then verify CSI ribbon orientation, camera availability, GStreamer support,
desktop-session display access, and permissions. Do not replace JetPack OpenCV
with the generic pip wheel.

## Success criteria

- All 48 unit tests pass.
- Repository verification passes.
- Rescue totals remain 14,454 raw rows and 2,649 retained bouts.
- Remaining-primary totals remain 29,798 raw rows and 3,033 retained bouts.
- No raw-source SHA-256 changes.
- The 34 rescue plots and three printable PDFs exist.
- The Jetson handoff files match their `code/` counterparts.

Any expected-total change is a new analysis version and requires an explicit
decision entry, regenerated manifests, updated docs, and professor review.
