# MATLAB Jetson–SwarmSight comparison

`plot_jetson_swarmsight.m` produces an aligned figure containing:

1. Jetson sleep-bout intervals from a JSON file;
2. independently derived SwarmSight right-antenna low-activity intervals; and
3. the 10-second and trailing 120-second absolute angular-speed traces.

The code reads its inputs without changing them. It supports both the current
five-field Jetson rows and compact cleaned rows because only `start_time` and
`end_time` are required.

## Run the included experiment

In MATLAB, set the current folder to the repository and run:

```matlab
run('matlab/run_jetson_swarmsight_example.m')
```

The example writes a 300-dpi PNG under
`outputs/jetson_swarmsight_matlab/` and returns the aligned traces, detected
periods, and agreement metrics in `results`.

To run the audited numeric and figure-export check for these exact files:

```matlab
run('matlab/validate_july21_reference.m')
```

It verifies 327,665 SwarmSight rows, 37 Jetson bouts, 42 independently derived
right-antenna low-activity periods, the calculated threshold and speed cap,
five agreement metrics, and successful PNG export. The expected values were
calculated independently from the same immutable inputs.

## Run another experiment

The SwarmSight CSV must contain `Frame` and `RightAngle`. Supply the timestamp
of video frame 1 and the actual video frame rate:

```matlab
result = plot_jetson_swarmsight( ...
    '/path/to/sleep_log_YYYYMMDD.json', ...
    '/path/to/swarmsight.csv', ...
    'VideoStart', datetime(2026, 7, 21, 18, 2, 19), ...
    'FrameRate', 5, ...
    'Label', 'Bee 1, session 1', ...
    'OutputFile', '/path/to/comparison.png');
```

When a CSV filename contains `JL-YYMMDD-HHMMSS_Cam`, `VideoStart` can be
omitted and will be inferred. Verify that inferred time against the original
video or acquisition record.

For multiple experiments, append entries to a struct array and use the batch
wrapper:

```matlab
experiments(1).JetsonJson = '/data/session1.json';
experiments(1).SwarmCsv = '/data/session1.csv';
experiments(1).VideoStart = datetime(2026, 7, 21, 18, 2, 19);
experiments(1).FrameRate = 5;
experiments(1).Label = 'Session 1';

experiments(2).JetsonJson = '/data/session2.json';
experiments(2).SwarmCsv = '/data/session2.csv';
experiments(2).VideoStart = datetime(2026, 7, 22, 18, 5, 0);
experiments(2).FrameRate = 5;
experiments(2).Label = 'Session 2';

results = batch_plot_jetson_swarmsight(experiments, ...
    'OutputDir', '/data/comparison_figures');
```

## Analysis defaults and cautions

- Only the right antenna is used because the July 21 left-antenna trace was
  nearly frozen.
- Angular differences are wrapped at ±180 degrees before conversion to
  degrees/second.
- Frame-level speeds are capped at their 99th percentile to limit tracker
  jumps, then averaged into 10-second bins and smoothed over 120 seconds.
- Low activity must persist for **strictly more than 120 seconds**.
- With no supplied threshold, an Otsu threshold is calculated independently
  from each SwarmSight session. This is useful for exploration but does not
  define a validated biological sleep threshold.
- For comparisons across experiments, choose and document one fixed
  `LowActivityThreshold` from a training/calibration set, then apply that same
  value to held-out sessions.
- Jetson and SwarmSight timestamps are assumed to use the same local clock.
  Check clock offsets before interpreting disagreement.

The MATLAB scripts create derived figures only. They do not alter raw JSON,
CSV, video, acquisition code, or the repository cleaning rules.
