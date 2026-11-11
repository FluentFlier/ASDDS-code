#!/usr/bin/env python3
"""Create a PNG summary from a bee sleep JSON log.

This utility is intentionally headless so it can run from the Jetson launcher
after an experiment ends.  It uses Matplotlib's non-interactive ``Agg``
backend and never opens a GUI window.
"""

from __future__ import print_function

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
NOON_HOUR = 12


def load_bouts(json_path):
    """Load, validate, de-duplicate, and merge overlapping sleep bouts."""
    with open(json_path, "r") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("sleep log must contain a JSON array")

    # Older detector builds wrote repeated snapshots with the same start time.
    # Keeping the latest end time makes those files graphable without drawing
    # hundreds of copies of the same bout.
    by_start = {}
    for row_number, row in enumerate(payload, 1):
        if not isinstance(row, dict):
            raise ValueError("row {} is not a JSON object".format(row_number))
        try:
            start = datetime.strptime(row["start_time"], TIME_FORMAT)
            end = datetime.strptime(row["end_time"], TIME_FORMAT)
        except KeyError as exc:
            raise ValueError(
                "row {} is missing {}".format(row_number, exc.args[0])
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "row {} has an invalid timestamp: {}".format(row_number, exc)
            )
        if end <= start:
            raise ValueError("row {} ends before it starts".format(row_number))
        previous = by_start.get(start)
        if previous is None or end > previous:
            by_start[start] = end

    ordered = sorted(by_start.items())
    merged = []
    for start, end in ordered:
        if merged and start < merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _noon_floor(moment):
    noon = moment.replace(hour=NOON_HOUR, minute=0, second=0, microsecond=0)
    if moment < noon:
        noon -= timedelta(days=1)
    return noon


def split_bouts_by_experiment_day(bouts):
    """Split intervals into noon-to-noon rows for plotting."""
    pieces = {}
    for start, end in bouts:
        cursor = start
        while cursor < end:
            row_start = _noon_floor(cursor)
            row_end = row_start + timedelta(days=1)
            piece_end = min(end, row_end)
            offset_hours = (cursor - row_start).total_seconds() / 3600.0
            width_hours = (piece_end - cursor).total_seconds() / 3600.0
            pieces.setdefault(row_start, []).append((offset_hours, width_hours))
            cursor = piece_end
    return pieces


def default_output_path(json_path):
    log_dir = os.path.dirname(os.path.abspath(json_path))
    graph_dir = os.path.join(log_dir, "graphs")
    stem = os.path.splitext(os.path.basename(json_path))[0]
    return os.path.join(graph_dir, "{}_summary.png".format(stem))


def render_graph(json_path, output_path=None):
    """Render one sleep-log summary and return the output path."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bouts = load_bouts(json_path)
    output_path = os.path.abspath(output_path or default_output_path(json_path))
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    total_hours = sum((end - start).total_seconds() for start, end in bouts) / 3600.0
    durations = [(end - start).total_seconds() / 60.0 for start, end in bouts]
    longest_minutes = max(durations) if durations else 0.0

    pieces = split_bouts_by_experiment_day(bouts)
    if pieces:
        row_starts = sorted(pieces)
    else:
        # An empty but valid session should still produce a useful handoff artifact.
        fallback = datetime.fromtimestamp(os.path.getmtime(json_path))
        row_starts = [_noon_floor(fallback)]

    figure_height = max(3.8, 2.6 + 0.65 * len(row_starts))
    figure, axis = plt.subplots(figsize=(13, figure_height))

    for row_index, row_start in enumerate(row_starts):
        # Default scotophase is 18:00-06:00, i.e. hours 6-18 on a noon axis.
        axis.broken_barh(
            [(6, 12)],
            (row_index - 0.38, 0.76),
            facecolors="#d9d9d9",
            edgecolors="none",
            zorder=0,
        )
        if pieces.get(row_start):
            axis.broken_barh(
                pieces[row_start],
                (row_index - 0.27, 0.54),
                facecolors="#2474b5",
                edgecolors="#123c5a",
                linewidth=0.5,
                zorder=2,
            )

    hour_labels = ["{:02d}:00".format((NOON_HOUR + hour) % 24) for hour in range(25)]
    axis.set_xlim(0, 24)
    axis.set_xticks(range(25))
    axis.set_xticklabels(hour_labels, rotation=45, ha="right", fontsize=8)
    axis.set_ylim(-0.7, len(row_starts) - 0.3)
    axis.set_yticks(range(len(row_starts)))
    axis.set_yticklabels(
        ["{} to {}".format(day.strftime("%Y-%m-%d"), (day + timedelta(days=1)).strftime("%Y-%m-%d")) for day in row_starts],
        fontsize=9,
    )
    axis.set_xlabel("Time of day (noon to noon)")
    axis.set_ylabel("Experiment day")
    axis.grid(axis="x", alpha=0.2, linestyle="--")
    bout_label = "bout" if len(bouts) == 1 else "bouts"
    axis.set_title(
        "Bee sleep summary\n{} {} | {:.2f} total hours | {:.1f} min longest bout".format(
            len(bouts), bout_label, total_hours, longest_minutes
        ),
        fontweight="bold",
    )
    if not bouts:
        axis.text(
            12,
            0,
            "No completed sleep bouts were recorded",
            ha="center",
            va="center",
            fontsize=12,
            color="#555555",
            zorder=3,
        )
    axis.text(
        0.995,
        0.02,
        "Blue = sleep bout   Gray = default scotophase (18:00-06:00)",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color="#555555",
    )
    figure.tight_layout()

    descriptor, temporary_path = tempfile.mkstemp(
        dir=output_dir or None, suffix=".png"
    )
    os.close(descriptor)
    try:
        figure.savefig(temporary_path, dpi=160, bbox_inches="tight")
        os.replace(temporary_path, output_path)
    finally:
        plt.close(figure)
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return output_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Create a headless PNG summary from one bee sleep JSON log."
    )
    parser.add_argument("json_file", help="sleep_log_YYYYMMDD.json to graph")
    parser.add_argument(
        "--output",
        help="PNG destination (default: a graphs folder beside the JSON log)",
    )
    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    json_path = os.path.abspath(os.path.expanduser(arguments.json_file))
    if not os.path.isfile(json_path):
        print("Graph not created: JSON file not found: {}".format(json_path), file=sys.stderr)
        return 2
    try:
        output_path = render_graph(json_path, arguments.output)
    except Exception as exc:
        print("Graph not created: {}".format(exc), file=sys.stderr)
        return 1
    print("Graph saved: {}".format(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
