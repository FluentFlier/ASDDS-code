# Experiment and acquisition method

## Purpose and evidence boundary

This document records what can be established from the acquisition code,
stored logs, generated artifacts, and saved correspondence. It does not fill
missing biological metadata with assumptions.

The repository does not currently establish the bee species, colony, animal
identifiers, replicate structure, housing conditions, light cycle, camera
calibration, apparatus geometry, or full treatment schedule. Add those facts
only from the laboratory record or direct confirmation by the experiment owner.

## Research objective currently supported by the files

The system measures image motion in a bee arena, classifies sustained low
motion as a sleep candidate, records sleep intervals, displays sleep state on
an LED, and supports modes that can activate a solenoid during selected sleep
periods.

The stored data and condition outputs indicate a comparison between sessions
labeled `Disrupted` and `Intact`. The precise biological treatment definition,
experimental unit, and planned statistical contrast are not encoded in the
repository and require professor confirmation.

## Hardware known from code

| Component | Repository evidence | Current implementation |
|---|---|---|
| Compute | Jetson-specific imports and GStreamer pipeline | NVIDIA Jetson Nano / JetPack environment |
| Camera | `nvarguscamerasrc sensor-id=0` | CSI camera, sensor 0 |
| Capture | GStreamer string in detector scripts | 1280 x 720, NV12, 30 fps |
| Processing frame | GStreamer conversion | 640 x 360 BGR |
| Sleep indicator | `led_sleep_detect_clean.py` | LED on BOARD pin 7 |
| Continuous-disruption indicator/output | `cont_disrupt.py` | BOARD pin 18 |
| Scotophase indicator | `scotophase_disrupt.py` | LED on BOARD pin 7 |
| Scotophase disruption actuator | `scotophase_disrupt.py` | Solenoid on BOARD pin 33 |

Pin assignments are software facts, not a wiring verification. Confirm voltage,
driver circuitry, flyback protection, active-high polarity, common ground, and
safe shutdown behavior on the physical apparatus.

## Recommended current detector

Use `code/led_sleep_detect_clean.py` through launcher option 2.

### Image processing

For each camera frame, the detector:

1. Converts BGR to grayscale.
2. Applies a 7 x 7 Gaussian blur.
3. Applies OpenCV MOG2 background subtraction with history 100,
   `varThreshold=15`, shadows disabled, and learning rate `0.01`.
4. Counts nonzero foreground-mask pixels.
5. Converts that count to motion percentage:

   `motion_intensity = nonzero_pixels / total_pixels * 100`

6. Maintains a short display history and a 120-second time-based detection
   average.

### Current detection parameters

| Parameter | Value | Meaning |
|---|---:|---|
| `SLEEP_THRESHOLD` | `0.005` | Detection-average motion percentage threshold |
| `MIN_SLEEP_DURATION` | `120` seconds | Low motion must persist strictly longer than this |
| `DETECTION_WINDOW_SECONDS` | `120.0` | Time span of detection average |
| `DETECTION_MINIMUM_SAMPLES` | `31` | Minimum samples before the average is ready |
| `TRANSITION_PERSISTENCE_SECONDS` | `2.0` | Sustained state required around threshold transitions |
| `WARMUP_FRAMES` | `90` | Initial frames excluded from session min/max tracking |
| `MAX_CAMERA_RETRIES` | `5` | Consecutive failures allowed before exit |
| `MAX_OBSERVATION_GAP_SECONDS` | `1.0` | Larger gaps interrupt continuity |
| `MOTION_HISTORY_LEN` | `300` | Samples used by display average |

### State and output behavior

- A candidate starts at the current observation, never at a stale buffer time.
- A failed candidate clears candidate state and the detection average.
- Candidate confirmation preserves the same continuous bout.
- A confirmed bout ends after sustained above-threshold motion.
- One row is written per completed bout.
- A shutdown or camera gap can create an interrupted event in the detector log,
  but it is not presented as a completed MATLAB row.
- Failed JSON writes stay queued for retry. An unresolved pending write causes a
  nonzero process exit.
- One file named `sleep_log_YYYYMMDD.json` is chosen from the experiment start
  date and does not rotate at midnight.

## Launcher modes

Run `bash code/program_launcher.sh` on the Jetson. The launcher currently lists:

| Option | Script | Intended use | Caution |
|---:|---|---|---|
| 1 | `cont_disrupt.py` | Continuous disruption mode / pin 18 output | Historical architecture; current code constant is 120 seconds |
| 2 | `led_sleep_detect_clean.py` | Recommended clean non-overlapping detector | Preferred for new acquisition |
| 3 | `scotophase_disrupt.py` | Solenoid only during a prompted start/end window | Historical architecture; bench-test solenoid fail-safe |
| 4 | `sunset_start.py` | Solenoid after prompted start time | Older script; not covered by the clean state-machine design |
| 5 | `bee_sleep_detect_revised_sessionfile.py` | Earlier session-file detector | Retained for history, not recommended over option 2 |

The launcher automatically graphs `sleep_log_<run-date>.json` after the detector
exits when that file exists. Graph generation is best-effort and does not mask
the detector exit status.

## Historical acquisition behavior

Many stored logs came from earlier scripts that wrote a checkpoint approximately
every 120 seconds during a still-active bout. Those rows share a start time but
have progressively later end times. Some historical disruption sessions used a
shorter logging or confirmation regime. The rescue manifest identifies 11 such
files based on the previously approved file list.

The current handoff scripts use `MIN_SLEEP_DURATION = 120`. Do not use the
current constant to rewrite the historical detector regime in methods or data
interpretation.

## Output schema for new acquisition

The clean detector writes one JSON array. Each completed row has:

```json
{
  "start_time": "2026-07-21 18:30:00",
  "end_time": "2026-07-21 18:35:30",
  "duration_seconds": 330.0,
  "average_motion": 0.0012,
  "motion_range": {
    "min": 0.0,
    "max": 0.01
  }
}
```

The analysis cleanup outputs use a different three-field schema documented in
`DATA_AND_CLEANING.md`.

## On-device preflight

Copy `jetson_handoff/PyPro/` to the Jetson and run:

```bash
cd ~/PyPro
chmod +x program_launcher.sh check_jetson.sh auto_graph.py
bash check_jetson.sh
```

Expected: the script reports the required files and Jetson dependencies. Review
every warning before starting a live experiment.

Do not install the generic `opencv-python` wheel over JetPack OpenCV. JetPack's
OpenCV build provides the GStreamer integration required for the CSI camera.

## Required metadata still missing

The next laboratory documentation pass should add:

- bee species and strain, if applicable;
- colony and individual/replicate identifiers;
- definition of experimental unit;
- apparatus or arena identifier;
- camera model, lens, distance, orientation, exposure, and lighting;
- environmental temperature and humidity;
- photoperiod and exact scotophase definition;
- definition of `Disrupted` and `Intact`;
- treatment schedule and solenoid stimulus details;
- run start/end, operator, exclusions, restarts, and hardware incidents;
- mapping from each JSON date to animal, treatment, and replicate;
- planned statistical outcomes and exclusion rules.

See `PROFESSOR_REVIEW.md` for the decisions that need authoritative answers.
