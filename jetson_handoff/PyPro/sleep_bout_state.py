#!/usr/bin/env python3
"""Pure sleep-bout state and JSON persistence for the LED detector.

This module deliberately has no OpenCV or Jetson.GPIO imports.  The state
machine can therefore be tested with synthetic timestamps before it is used on
the camera hardware.
"""

import json
import logging
import os
import tempfile
from collections import deque
from datetime import datetime


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class CompletedBout(object):
    """One completed or experiment-truncated detector-defined sleep bout."""

    def __init__(
        self,
        start_time,
        confirmation_time,
        end_time,
        average_motion,
        minimum_motion,
        maximum_motion,
        sample_count,
        bout_complete,
        end_reason,
        duration_seconds=None,
    ):
        self.start_time = start_time
        self.confirmation_time = confirmation_time
        self.end_time = end_time
        self.average_motion = average_motion
        self.minimum_motion = minimum_motion
        self.maximum_motion = maximum_motion
        self.sample_count = sample_count
        self.bout_complete = bout_complete
        self.end_reason = end_reason
        self.duration_seconds = duration_seconds

    def to_record(self, threshold, minimum_duration_seconds):
        """Return the legacy LED-detector JSON schema expected by MATLAB.

        Confirmation and completion details stay available on this object and
        in the detector log, but are deliberately not added to the JSON row.
        Older analysis software expects every row to have these five fields.
        """
        return {
            "start_time": self.start_time.strftime(TIME_FORMAT),
            "end_time": self.end_time.strftime(TIME_FORMAT),
            "duration_seconds": round(
                self.duration_seconds
                if self.duration_seconds is not None
                else (self.end_time - self.start_time).total_seconds(),
                3,
            ),
            "average_motion": round(self.average_motion, 8),
            "motion_range": {
                "min": round(self.minimum_motion, 6),
                "max": round(self.maximum_motion, 6),
            },
        }


class RollingMotionAverage(object):
    """Time-bounded motion average that can be reset at event boundaries."""

    def __init__(self, window_seconds=120.0, minimum_samples=31):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if minimum_samples < 1:
            raise ValueError("minimum_samples must be positive")
        self.window_seconds = float(window_seconds)
        self.minimum_samples = int(minimum_samples)
        self.samples = deque()
        self.total = 0.0
        self.last_tick = None

    @property
    def ready(self):
        return len(self.samples) >= self.minimum_samples

    @property
    def average(self):
        if not self.samples:
            return None
        return self.total / len(self.samples)

    def add(self, monotonic_time, motion_score):
        tick = float(monotonic_time)
        value = float(motion_score)
        if self.last_tick is not None and tick < self.last_tick:
            raise ValueError("motion-average timestamps must be non-decreasing")
        self.last_tick = tick
        self.samples.append((tick, value))
        self.total += value
        while self.samples and tick - self.samples[0][0] > self.window_seconds:
            _old_tick, old_value = self.samples.popleft()
            self.total -= old_value
        return self.average

    def clear(self):
        self.samples.clear()
        self.total = 0.0
        self.last_tick = None


class SleepBoutStateMachine(object):
    """Detect non-overlapping bouts from a continuous motion score.

    A candidate starts after the averaged score has stayed below threshold for
    the configured transition-persistence period. It must then stay below the
    threshold for strictly more than ``minimum_duration_seconds``. Sustained
    above-threshold motion cancels an unconfirmed candidate or ends a confirmed
    bout. A zero persistence value retains the immediate-transition behavior.
    """

    def __init__(
        self,
        threshold=0.005,
        minimum_duration_seconds=120.0,
        transition_persistence_seconds=0.0,
    ):
        if minimum_duration_seconds < 0:
            raise ValueError("minimum_duration_seconds cannot be negative")
        if transition_persistence_seconds < 0:
            raise ValueError("transition_persistence_seconds cannot be negative")
        self.threshold = float(threshold)
        self.minimum_duration_seconds = float(minimum_duration_seconds)
        self.transition_persistence_seconds = float(transition_persistence_seconds)
        self.last_observation_time = None
        self.last_observation_tick = None
        self._reset_event_state()

    @property
    def status(self):
        if self.sleeping:
            return "sleeping"
        if self.candidate_start is not None:
            return "candidate"
        return "active"

    def _reset_metrics(self):
        self.motion_sum = 0.0
        self.motion_count = 0
        self.motion_min = None
        self.motion_max = None

    def _reset_event_state(self):
        self.sleeping = False
        self.candidate_start = None
        self.candidate_start_tick = None
        self.sleep_start = None
        self.sleep_start_tick = None
        self.confirmation_time = None
        self.confirmation_tick = None
        self.low_pending_time = None
        self.low_pending_tick = None
        self.high_pending_time = None
        self.high_pending_tick = None
        self._reset_metrics()

    @staticmethod
    def _elapsed(now, monotonic_time, start_time, start_tick):
        if monotonic_time is not None and start_tick is not None:
            return monotonic_time - start_tick
        return (now - start_time).total_seconds()

    def _clear_low_pending(self):
        self.low_pending_time = None
        self.low_pending_tick = None

    def _clear_high_pending(self):
        self.high_pending_time = None
        self.high_pending_tick = None

    def _record_low_motion(self, motion_score):
        value = float(motion_score)
        self.motion_sum += value
        self.motion_count += 1
        self.motion_min = value if self.motion_min is None else min(self.motion_min, value)
        self.motion_max = value if self.motion_max is None else max(self.motion_max, value)

    def _check_time(self, now, monotonic_time=None):
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime")
        if monotonic_time is None:
            if self.last_observation_time is not None and now < self.last_observation_time:
                raise ValueError("observation timestamps must be non-decreasing")
        else:
            monotonic_time = float(monotonic_time)
            if (
                self.last_observation_tick is not None
                and monotonic_time < self.last_observation_tick
            ):
                raise ValueError("monotonic timestamps must be non-decreasing")
        self.last_observation_time = now
        self.last_observation_tick = monotonic_time
        return monotonic_time

    def update(self, now, motion_score, monotonic_time=None, metric_score=None):
        """Process one score and return a transition dictionary or ``None``."""
        monotonic_time = self._check_time(now, monotonic_time)
        motion_score = float(motion_score)
        metric_score = motion_score if metric_score is None else float(metric_score)
        low_motion = motion_score < self.threshold

        if self.sleeping:
            if low_motion:
                self._clear_high_pending()
                self._record_low_motion(metric_score)
                return None

            if self.high_pending_time is None:
                self.high_pending_time = now
                self.high_pending_tick = monotonic_time
            high_elapsed = self._elapsed(
                now,
                monotonic_time,
                self.high_pending_time,
                self.high_pending_tick,
            )
            if high_elapsed < self.transition_persistence_seconds:
                return None

            bout = self._make_bout(
                self.high_pending_time,
                True,
                "motion_above_threshold",
                end_tick=self.high_pending_tick,
            )
            self._reset_event_state()
            return {"type": "bout_completed", "bout": bout}

        if low_motion:
            if self.candidate_start is None:
                self._clear_high_pending()
                if self.low_pending_time is None:
                    self.low_pending_time = now
                    self.low_pending_tick = monotonic_time
                low_elapsed = self._elapsed(
                    now,
                    monotonic_time,
                    self.low_pending_time,
                    self.low_pending_tick,
                )
                if low_elapsed < self.transition_persistence_seconds:
                    return None
                self.candidate_start = now
                self.candidate_start_tick = monotonic_time
                self._clear_low_pending()
                self._reset_metrics()
                self._record_low_motion(metric_score)
                return {"type": "candidate_started", "start_time": now}

            self._clear_high_pending()
            self._record_low_motion(metric_score)
            elapsed = (
                monotonic_time - self.candidate_start_tick
                if monotonic_time is not None and self.candidate_start_tick is not None
                else (now - self.candidate_start).total_seconds()
            )
            if elapsed > self.minimum_duration_seconds:
                self.sleeping = True
                self.sleep_start = self.candidate_start
                self.sleep_start_tick = self.candidate_start_tick
                self.confirmation_time = now
                self.confirmation_tick = monotonic_time
                return {
                    "type": "sleep_confirmed",
                    "start_time": self.sleep_start,
                    "confirmation_time": self.confirmation_time,
                }
            return None

        self._clear_low_pending()
        if self.candidate_start is not None:
            if self.high_pending_time is None:
                self.high_pending_time = now
                self.high_pending_tick = monotonic_time
            high_elapsed = self._elapsed(
                now,
                monotonic_time,
                self.high_pending_time,
                self.high_pending_tick,
            )
            if high_elapsed < self.transition_persistence_seconds:
                return None
            cancelled_start = self.candidate_start
            self._reset_event_state()
            return {
                "type": "candidate_cancelled",
                "start_time": cancelled_start,
                "cancelled_at": now,
            }

        return None

    def _make_bout(self, end_time, bout_complete, end_reason, end_tick=None):
        if not self.sleeping or self.sleep_start is None or self.confirmation_time is None:
            raise RuntimeError("cannot complete a bout that was never confirmed")
        average = self.motion_sum / self.motion_count if self.motion_count else 0.0
        minimum = self.motion_min if self.motion_min is not None else 0.0
        maximum = self.motion_max if self.motion_max is not None else 0.0
        duration_seconds = (
            end_tick - self.sleep_start_tick
            if end_tick is not None and self.sleep_start_tick is not None
            else (end_time - self.sleep_start).total_seconds()
        )
        return CompletedBout(
            start_time=self.sleep_start,
            confirmation_time=self.confirmation_time,
            end_time=end_time,
            average_motion=average,
            minimum_motion=minimum,
            maximum_motion=maximum,
            sample_count=self.motion_count,
            bout_complete=bout_complete,
            end_reason=end_reason,
            duration_seconds=duration_seconds,
        )

    def interrupt(self, end_reason="observation_interrupted"):
        """End any open detection state at the last valid observation."""
        if self.sleeping:
            bout = self._make_bout(
                self.last_observation_time,
                False,
                end_reason,
                end_tick=self.last_observation_tick,
            )
            self._reset_event_state()
            return {"type": "bout_interrupted", "bout": bout}

        if self.candidate_start is not None:
            cancelled_start = self.candidate_start
            cancelled_at = self.last_observation_time
            self._reset_event_state()
            return {
                "type": "candidate_cancelled",
                "start_time": cancelled_start,
                "cancelled_at": cancelled_at,
                "reason": end_reason,
            }

        # ACTIVE can still contain a short, not-yet-visible persistence timer.
        # A camera gap must clear it so evidence never crosses the gap.
        self._reset_event_state()
        return None

    def finalize(self, now, monotonic_time=None):
        """Close a confirmed bout at experiment shutdown, if one is open."""
        monotonic_time = self._check_time(now, monotonic_time)
        if not self.sleeping:
            self._reset_event_state()
            return None
        bout = self._make_bout(
            now, False, "experiment_stopped", end_tick=monotonic_time
        )
        self._reset_event_state()
        return bout


class SleepLogWriter(object):
    """Append unique legacy-format bouts using atomic writes."""

    LEGACY_FIELDS = (
        "start_time",
        "end_time",
        "duration_seconds",
        "average_motion",
        "motion_range",
    )

    def __init__(self, log_dir, experiment_start, logger=None):
        self.log_dir = os.path.abspath(os.path.expanduser(log_dir))
        self.experiment_start = experiment_start
        self.logger = logger or logging.getLogger(__name__)
        os.makedirs(self.log_dir, exist_ok=True)
        self.path = os.path.join(
            self.log_dir,
            "sleep_log_{}.json".format(experiment_start.strftime("%Y%m%d")),
        )
        self._normalize_existing_file()
        if not os.path.exists(self.path):
            self._write_atomic([])

    def _read(self):
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return []
        try:
            with open(self.path, "r") as handle:
                payload = json.load(handle)
            if not isinstance(payload, list):
                raise ValueError("sleep log must contain a JSON array")
            return payload
        except (ValueError, IOError) as exc:
            backup = "{}.bak.{}".format(
                self.path, datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            self.logger.error("Unreadable sleep log %s: %s", self.path, exc)
            os.replace(self.path, backup)
            self.logger.error("Moved unreadable log to %s", backup)
            return []

    def _write_atomic(self, records):
        descriptor = None
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(dir=self.log_dir, suffix=".tmp")
            with os.fdopen(descriptor, "w") as handle:
                descriptor = None
                json.dump(records, handle, indent=4)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def _legacy_record(self, record):
        """Strip newer metadata so every row has the MATLAB-era schema."""
        missing = [field for field in self.LEGACY_FIELDS if field not in record]
        if missing:
            raise ValueError(
                "sleep record is missing legacy field(s): {}".format(
                    ", ".join(missing)
                )
            )
        motion_range = record["motion_range"]
        if not isinstance(motion_range, dict) or not all(
            field in motion_range for field in ("min", "max")
        ):
            raise ValueError("sleep record has an invalid motion_range")
        return {
            "start_time": record["start_time"],
            "end_time": record["end_time"],
            "duration_seconds": record["duration_seconds"],
            "average_motion": record["average_motion"],
            "motion_range": {
                "min": motion_range["min"],
                "max": motion_range["max"],
            },
        }

    def _normalize_existing_file(self):
        """Convert an enriched file from an earlier clean build on startup."""
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return
        existing_records = self._read()
        records = [self._legacy_record(existing) for existing in existing_records]
        if records != existing_records:
            self._write_atomic(records)
            self.logger.info("Converted existing sleep rows to legacy JSON format")

    def append(self, record):
        """Append one record, using its legacy start time as the unique key."""
        existing_records = self._read()
        records = [self._legacy_record(existing) for existing in existing_records]
        record = self._legacy_record(record)
        start_time = record["start_time"]
        if any(existing.get("start_time") == start_time for existing in records):
            if records != existing_records:
                self._write_atomic(records)
                self.logger.info("Converted existing sleep rows to legacy JSON format")
            self.logger.warning(
                "Bout starting %s is already present; duplicate write skipped",
                start_time,
            )
            return False
        records.append(record)
        self._write_atomic(records)
        return True
