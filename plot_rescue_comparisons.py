#!/usr/bin/env python3
"""Plot the raw rescue inputs beside their structurally cleaned outputs.

Durations are recalculated from start/end timestamps in both panels so the
comparison isolates the rescue rules instead of sub-second timer noise stored
in the original ``duration_seconds`` field.  Time-of-day is displayed on a
noon-to-noon axis so overnight sessions remain continuous across midnight.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def timestamp_duration(record: dict[str, Any]) -> int:
    return int(
        (parse_time(record["end_time"]) - parse_time(record["start_time"])).total_seconds()
    )


def noon_axis_hour(value: str) -> float:
    stamp = parse_time(value)
    hour = stamp.hour + stamp.minute / 60 + stamp.second / 3600
    return (hour - 12) % 24


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def duration_ceiling(maximum: int) -> int:
    if maximum <= 600:
        step = 120
    elif maximum <= 1800:
        step = 300
    elif maximum <= 7200:
        step = 600
    else:
        step = 1800
    return max(240, int(math.ceil(maximum / step) * step))


def time_label(value: float, _position: int | None = None) -> str:
    hour = int(round((value + 12) % 24)) % 24
    if hour == 0:
        return "12 AM"
    if hour == 12:
        return "12 PM"
    return f"{hour % 12} {'AM' if hour < 12 else 'PM'}"


def plot_file(
    date_code: str,
    raw_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    stats: dict[str, Any],
    output_path: Path,
) -> None:
    raw_points = [(noon_axis_hour(row["start_time"]), timestamp_duration(row)) for row in raw_rows]
    clean_points = [
        (noon_axis_hour(row["start_time"]), timestamp_duration(row)) for row in clean_rows
    ]
    all_durations = [duration for _, duration in raw_points + clean_points]
    y_max = duration_ceiling(max(all_durations, default=240))

    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axes = plt.subplots(1, 2, figsize=(14, 5.7), sharex=True, sharey=True)
    figure.suptitle(
        f"Sleep bouts — {datetime.strptime(date_code, '%Y%m%d').strftime('%B %-d, %Y')}",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )

    raw_long = [(x, y) for x, y in raw_points if y > 120]
    raw_exact = [(x, y) for x, y in raw_points if y == 120]
    raw_short = [(x, y) for x, y in raw_points if y < 120]
    if raw_long:
        axes[0].scatter(
            [x for x, _ in raw_long],
            [y for _, y in raw_long],
            s=18,
            alpha=0.48,
            color="#2563eb",
            edgecolors="none",
            label="Raw record (>120 s)",
        )
    if raw_exact:
        axes[0].scatter(
            [x for x, _ in raw_exact],
            [y for _, y in raw_exact],
            s=18,
            alpha=0.72,
            color="#d97706",
            marker="x",
            linewidths=0.8,
            label="Raw record (=120 s)",
        )
    if raw_short:
        axes[0].scatter(
            [x for x, _ in raw_short],
            [y for _, y in raw_short],
            s=15,
            alpha=0.42,
            color="#64748b",
            edgecolors="none",
            label="Raw record (<120 s)",
        )
    if clean_points:
        axes[1].scatter(
            [x for x, _ in clean_points],
            [y for _, y in clean_points],
            s=28,
            alpha=0.78,
            color="#059669",
            marker="D",
            edgecolors="white",
            linewidths=0.35,
            label="Retained clean bout",
        )

    axes[0].set_title(f"Original records  n={len(raw_rows):,}", fontweight="bold")
    axes[1].set_title(f"Cleaned bouts  n={len(clean_rows):,}", fontweight="bold")
    axes[0].text(
        0.02,
        0.97,
        (
            f"{stats['same_start_snapshots_removed']:,} repeated snapshots collapsed\n"
            f"{stats['shorter_than_120_second_bouts_excluded']:,} selected <120 s candidates excluded\n"
            f"{stats['exact_120_second_bouts_excluded']:,} selected 120 s candidates excluded"
        ),
        transform=axes[0].transAxes,
        va="top",
        fontsize=9,
        color="#334155",
        bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#cbd5e1", "pad": 5},
    )

    for axis in axes:
        axis.axhline(120, color="#d97706", linestyle="--", linewidth=1.0, alpha=0.72)
        axis.set_xlim(0, 24)
        axis.set_ylim(0, y_max)
        axis.set_xticks([0, 4, 8, 12, 16, 20, 24])
        axis.xaxis.set_major_formatter(FuncFormatter(time_label))
        axis.yaxis.set_major_locator(MaxNLocator(nbins=7, integer=True))
        axis.tick_params(axis="x", labelrotation=25)
        axis.set_xlabel("Time of day (noon → next noon)")
        axis.grid(True, alpha=0.23)
        axis.legend(loc="upper right", fontsize=8, frameon=True)
    axes[0].set_ylabel("Duration (seconds)")

    figure.text(
        0.5,
        0.015,
        "Both panels use timestamp-derived durations and identical axes. Distinct starts remain separate.",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.94))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def build_visualization_fragment(
    records: list[dict[str, Any]], totals: dict[str, Any]
) -> str:
    data_json = json.dumps(records, separators=(",", ":"))
    return f"""<div id="sleep-rescue-comparison">
  <style>
    #sleep-rescue-comparison {{ color: var(--foreground); font-family: var(--font-sans); }}
    #sleep-rescue-comparison .summary {{ display:flex; flex-wrap:wrap; gap:8px 24px; padding:4px 0 14px; color:var(--muted-foreground); font-size:12px; }}
    #sleep-rescue-comparison .legend {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; padding:8px 0 12px; font-size:12px; }}
    #sleep-rescue-comparison .key {{ display:inline-flex; gap:6px; align-items:center; }}
    #sleep-rescue-comparison .swatch {{ width:10px; height:10px; border-radius:50%; background:var(--viz-series-1); }}
    #sleep-rescue-comparison .swatch.exact {{ background:var(--viz-series-4); border-radius:1px; }}
    #sleep-rescue-comparison .swatch.clean {{ background:var(--viz-series-2); border-radius:2px; transform:rotate(45deg); }}
    #sleep-rescue-comparison .session {{ padding:14px 0 18px; border-top:1px solid var(--border); }}
    #sleep-rescue-comparison .session-head {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px 18px; margin-bottom:8px; }}
    #sleep-rescue-comparison .date {{ font-size:15px; font-weight:650; }}
    #sleep-rescue-comparison .counts {{ font-size:12px; color:var(--muted-foreground); font-variant-numeric:tabular-nums; }}
    #sleep-rescue-comparison .plots {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; }}
    #sleep-rescue-comparison .plot-label {{ font-size:12px; font-weight:600; margin:0 0 3px; }}
    #sleep-rescue-comparison canvas {{ display:block; width:100%; height:230px; }}
    #sleep-rescue-comparison .axis-note {{ margin-top:5px; text-align:center; font-size:11px; color:var(--muted-foreground); }}
    @media (max-width:700px) {{
      #sleep-rescue-comparison .plots {{ grid-template-columns:1fr; gap:16px; }}
      #sleep-rescue-comparison canvas {{ height:210px; }}
    }}
  </style>
  <div class="summary"><span>{len(records)} rescued sessions</span><span>{totals['raw_rows']:,} original records → {totals['retained_bouts']:,} cleaned bouts</span><span>Time axis: noon → next noon</span></div>
  <div class="legend" aria-label="Legend">
    <span class="key"><i class="swatch"></i>Original &gt;120 s</span>
    <span class="key"><i class="swatch exact"></i>Original =120 s</span>
    <span class="key">Gray = original &lt;120 s</span>
    <span class="key"><i class="swatch clean"></i>Cleaned bout</span>
    <span class="key">Dashed line = 120 s threshold</span>
  </div>
  <div class="sessions"></div>
  <script>
  (() => {{
    const root = document.getElementById('sleep-rescue-comparison');
    const records = {data_json};
    const styles = getComputedStyle(root);
    const color = name => styles.getPropertyValue(name).trim();
    const sessions = root.querySelector('.sessions');
    const formatDate = code => new Intl.DateTimeFormat(undefined, {{year:'numeric',month:'long',day:'numeric'}}).format(new Date(`${{code.slice(0,4)}}-${{code.slice(4,6)}}-${{code.slice(6,8)}}T12:00:00`));
    records.forEach((record, index) => {{
      const section = document.createElement('section');
      section.className = 'session';
      section.innerHTML = `<div class="session-head"><span class="date">${{formatDate(record.date)}}</span><span class="counts">${{record.rawCount.toLocaleString()}} raw → ${{record.cleanCount.toLocaleString()}} clean · ${{record.collapsed.toLocaleString()}} snapshots collapsed · ${{record.below.toLocaleString()}} &lt;120 s excluded · ${{record.excluded.toLocaleString()}} =120 s excluded</span></div><div class="plots"><div><div class="plot-label">Original records</div><canvas data-kind="raw" aria-label="Original records for ${{formatDate(record.date)}}"></canvas></div><div><div class="plot-label">Cleaned bouts</div><canvas data-kind="clean" aria-label="Cleaned bouts for ${{formatDate(record.date)}}"></canvas></div></div><div class="axis-note">Time of day (12 PM → 12 AM → next 12 PM) · Duration in seconds</div>`;
      sessions.appendChild(section);
      section.querySelectorAll('canvas').forEach(canvas => {{ canvas.dataset.index = String(index); }});
    }});

    const draw = canvas => {{
      const record = records[Number(canvas.dataset.index)];
      const kind = canvas.dataset.kind;
      const points = kind === 'raw' ? record.raw : record.clean;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(280, Math.round(rect.width));
      const height = Math.max(190, Math.round(rect.height));
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const ctx = canvas.getContext('2d');
      ctx.scale(ratio, ratio);
      const pad = {{left:50,right:12,top:8,bottom:30}};
      const innerW = width-pad.left-pad.right;
      const innerH = height-pad.top-pad.bottom;
      const sx = x => pad.left + x/24*innerW;
      const sy = y => pad.top + innerH - y/record.yMax*innerH;
      ctx.font = '10px ' + (color('--font-sans') || 'system-ui');
      ctx.strokeStyle = color('--border');
      ctx.fillStyle = color('--muted-foreground');
      ctx.lineWidth = 1;
      [0, .25, .5, .75, 1].forEach(frac => {{
        const y = pad.top + innerH*(1-frac);
        ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(width-pad.right,y); ctx.stroke();
        ctx.textAlign='right'; ctx.textBaseline='middle'; ctx.fillText(Math.round(record.yMax*frac).toLocaleString(),pad.left-6,y);
      }});
      const ticks = [[0,'12 PM'],[6,'6 PM'],[12,'12 AM'],[18,'6 AM'],[24,'12 PM']];
      ticks.forEach(([x,label]) => {{
        const px=sx(x); ctx.beginPath(); ctx.moveTo(px,pad.top); ctx.lineTo(px,pad.top+innerH); ctx.stroke();
        ctx.textAlign=x===0?'left':x===24?'right':'center'; ctx.textBaseline='top'; ctx.fillText(label,px,pad.top+innerH+7);
      }});
      const threshold=sy(120);
      ctx.save(); ctx.setLineDash([5,4]); ctx.strokeStyle=color('--viz-series-4'); ctx.beginPath(); ctx.moveTo(pad.left,threshold); ctx.lineTo(width-pad.right,threshold); ctx.stroke(); ctx.restore();
      points.forEach(([x,y]) => {{
        const px=sx(x), py=sy(y);
        if (kind==='clean') {{
          ctx.fillStyle=color('--viz-series-2'); ctx.save(); ctx.translate(px,py); ctx.rotate(Math.PI/4); ctx.fillRect(-2.5,-2.5,5,5); ctx.restore();
        }} else if (y===120) {{
          ctx.fillStyle=color('--viz-series-4'); ctx.fillRect(px-1.7,py-1.7,3.4,3.4);
        }} else if (y<120) {{
          ctx.fillStyle=color('--muted-foreground'); ctx.globalAlpha=.42; ctx.beginPath(); ctx.arc(px,py,1.8,0,Math.PI*2); ctx.fill(); ctx.globalAlpha=1;
        }} else {{
          ctx.fillStyle=color('--viz-series-1'); ctx.globalAlpha=.48; ctx.beginPath(); ctx.arc(px,py,2.1,0,Math.PI*2); ctx.fill(); ctx.globalAlpha=1;
        }}
      }});
    }};
    const drawAll = () => root.querySelectorAll('canvas').forEach(draw);
    let resizeTimer;
    window.addEventListener('resize', () => {{ clearTimeout(resizeTimer); resizeTimer=setTimeout(drawAll,120); }});
    requestAnimationFrame(drawAll);
  }})();
  </script>
</div>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("json files to be rescued"),
        help="Directory containing raw sleep_log JSON files",
    )
    parser.add_argument(
        "--clean-dir",
        type=Path,
        default=Path("json files to be rescued/cleaned"),
        help="Directory containing cleaned files and rescue_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("json files to be rescued/cleaned/comparison_plots"),
        help="Directory for static comparison plots",
    )
    parser.add_argument(
        "--visualization-output",
        type=Path,
        help="Optional path for a self-contained inline visualization fragment",
    )
    args = parser.parse_args()

    manifest_path = args.clean_dir / "rescue_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, Any]] = []
    visualization_records: list[dict[str, Any]] = []

    for stats in manifest["files"]:
        raw_path = args.source_dir / stats["input_file"]
        clean_path = args.clean_dir / stats["output_file"]
        raw_rows = load_rows(raw_path)
        clean_rows = load_rows(clean_path)
        date_code = raw_path.stem.removeprefix("sleep_log_")
        plot_name = f"sleep_log_{date_code}_original_vs_clean.png"
        plot_file(date_code, raw_rows, clean_rows, stats, args.output_dir / plot_name)

        raw_points = [
            [round(noon_axis_hour(row["start_time"]), 4), timestamp_duration(row)]
            for row in raw_rows
        ]
        clean_points = [
            [round(noon_axis_hour(row["start_time"]), 4), timestamp_duration(row)]
            for row in clean_rows
        ]
        y_max = duration_ceiling(max([point[1] for point in raw_points + clean_points], default=240))
        index_rows.append(
            {
                "date": date_code,
                "plot_file": plot_name,
                "raw_records": len(raw_rows),
                "clean_bouts": len(clean_rows),
                "same_start_snapshots_collapsed": stats["same_start_snapshots_removed"],
                "exact_120_second_candidates_excluded": stats[
                    "exact_120_second_bouts_excluded"
                ],
                "shorter_than_120_second_candidates_excluded": stats[
                    "shorter_than_120_second_bouts_excluded"
                ],
                "y_axis_max_seconds": y_max,
            }
        )
        visualization_records.append(
            {
                "date": date_code,
                "rawCount": len(raw_rows),
                "cleanCount": len(clean_rows),
                "collapsed": stats["same_start_snapshots_removed"],
                "excluded": stats["exact_120_second_bouts_excluded"],
                "below": stats["shorter_than_120_second_bouts_excluded"],
                "yMax": y_max,
                "raw": raw_points,
                "clean": clean_points,
            }
        )

    csv_path = args.output_dir / "comparison_plot_index.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(index_rows[0]))
        writer.writeheader()
        writer.writerows(index_rows)
    atomic_write(
        args.output_dir / "comparison_plot_index.json",
        json.dumps(index_rows, indent=2) + "\n",
    )

    if args.visualization_output:
        atomic_write(
            args.visualization_output,
            build_visualization_fragment(visualization_records, manifest["totals"]),
        )

    print(
        json.dumps(
            {
                "plot_count": len(index_rows),
                "output_dir": str(args.output_dir.resolve()),
                "visualization_output": (
                    str(args.visualization_output.resolve()) if args.visualization_output else None
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
