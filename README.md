# ASDDS research code and handoff

This repository is a public code reference for the ASDDS bee sleep motion-
detection experiment. It includes the recommended Jetson runtime, preserved
historical detector scripts, data-cleaning and plotting tools, MATLAB comparison
functions, and offline tests. It does not include raw or cleaned experiment
data, private correspondence, condition plots, or manuscript files.

## Quick start: inspect and test the code

Requirements: Python 3.10 or newer. Analysis scripts use the dependencies in
[`requirements-analysis.txt`](requirements-analysis.txt). The live Jetson
runtime additionally uses JetPack-provided OpenCV and Jetson.GPIO.

```bash
git clone https://github.com/FluentFlier/ASDDS-code.git
cd ASDDS-code
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-analysis.txt
python -m unittest discover -s code/tests
```

The tests are hardware-independent. They do not verify CSI camera, GPIO, LED,
or solenoid behavior on a physical Jetson.

## Use the code

### Jetson acquisition

The recommended clean detector is `code/led_sleep_detect_clean.py` with its
state and persistence helper `code/sleep_bout_state.py`. The deployable mirror
is under [`jetson_handoff/PyPro/`](jetson_handoff/PyPro/). Use launcher option
2 only; legacy options remain for historical reference and are not equally
validated. Start with [`code/JETSON_HANDOFF.md`](code/JETSON_HANDOFF.md).

### Clean and analyze logs

The rescue and remaining-primary cleaning scripts operate on JSON inputs you
supply. This repository does not ship those experimental files. The commands
and required directory layout are documented in
[`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md); cleaning rules and output
schemas are in [`docs/DATA_AND_CLEANING.md`](docs/DATA_AND_CLEANING.md).

### MATLAB comparison

Reusable MATLAB functions are in [`matlab/`](matlab/README.md). They require
paired Jetson JSON and SwarmSight CSV inputs. Those inputs are not distributed
here. See the MATLAB README for the expected formats and run commands.

## Code map

| Need | Source |
|---|---|
| Recommended Jetson detector | `code/led_sleep_detect_clean.py` |
| Detector state and atomic JSON writer | `code/sleep_bout_state.py` |
| Deployable Jetson copy | `jetson_handoff/PyPro/` |
| Focused rescue cleaner | `rescue_sleep_logs.py` |
| Remaining-primary cleaner | `clean_bee_motion_logs.py` |
| Rescue comparison plots and condition pages | `plot_rescue_comparisons.py`, `build_condition_plot_pages.py` |
| MATLAB Jetson–SwarmSight comparison | `matlab/` |
| Offline tests | `code/tests/` |

## Cite and identify the code version

GitHub's **Cite this repository** entry is generated from
[`CITATION.cff`](CITATION.cff). Human-readable citation instructions are in
[`CITATION.md`](CITATION.md), with BibTeX in [`CITATION.bib`](CITATION.bib).
Cite a release or commit permalink so readers can identify the exact code.

The code was copied from the canonical private research archive at ASDDS commit
[`a223963`](https://github.com/FluentFlier/ASDDS/commit/a223963cd1da8d89148b502b7b12af6d4eefb553).
The archive remains private; it contains experimental data and other research
materials that are not included here.

## Important limitations

- The source is released under BSD-3-Clause. See [`LICENSE`](LICENSE) for the
  terms of reuse and redistribution.
- The source snapshot is a research handoff, not a packaged or supported
  software release.
- Historical detector scripts and acquisition settings are not proof of what
  ran in each 2025 experiment.
- Cleaning outputs depend on the separate research data archive; cleaned
  outputs preserve overlaps and label checkpoint endpoints as lower bounds.
- Jetson hardware behavior still requires on-device validation.

## Status

This code reference is a research handoff. Author order and a fixed archival
release are not yet confirmed. See the canonical archive's
release notes for scientific and data-status limitations.
