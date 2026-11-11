#!/usr/bin/env python3
"""
graph.py — Bee Sleep Pattern Analyzer (Tkinter GUI).

Loads pairs of JSON sleep-log files, deduplicates sleep intervals,
and plots sleep bouts across a 12 PM–12 PM axis with scotophase overlay.

Three chart types available:
  1. Horizontal Bar  — each bee on its own row, bars span bout start→end  [DEFAULT]
  2. Raster Plot     — one tick mark per bout start; good for timing clustering
  3. Heatmap         — 30-min bins, color = fraction of bin spent asleep per bee
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt=DATE_FMT,
                    stream=sys.stdout)
logger = logging.getLogger("bee_graph")

COLORS   = ["#2196F3", "#4CAF50", "#9C27B0", "#FF9800", "#00BCD4",
            "#F44336", "#009688", "#FF5722", "#3F51B5", "#8BC34A"]
HOUR_ADJ = 12    # axis starts at noon
BIN_MIN  = 30    # heatmap bin size in minutes


# ---------------------------------------------------------------------------
class BeeSleepAnalyzer:
    def __init__(self, root):
        self.root = root
        self.root.title("Bee Sleep Pattern Analyzer")
        self.root.geometry("1200x850")

        self.bee_data      = {}   # {name: {"first_day": path, "second_day": path}}
        self.last_bee_dict = {}   # cache for chart-type switching without re-loading
        self.current_figure = None
        self.canvas = None

        self.setup_gui()

    # -----------------------------------------------------------------------
    # GUI
    # -----------------------------------------------------------------------
    def setup_gui(self):
        self.control_frame = ttk.Frame(self.root, padding="5")
        self.control_frame.pack(fill=tk.X, padx=5, pady=5)

        self.plot_frame = ttk.Frame(self.root)
        self.plot_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._create_file_section()
        self._create_scotophase_section()
        self._create_bee_section()
        self._create_chart_type_section()
        self._create_analysis_section()

    def _create_file_section(self):
        frame = ttk.LabelFrame(self.control_frame, text="File Selection", padding="5")
        frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(frame, text="First Day File:").grid(row=0, column=0, sticky=tk.W)
        self.first_day_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.first_day_path, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Browse",
                   command=lambda: self._browse_file(self.first_day_path)).grid(row=0, column=2)

        ttk.Label(frame, text="Second Day File:").grid(row=1, column=0, sticky=tk.W)
        self.second_day_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.second_day_path, width=50).grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="Browse",
                   command=lambda: self._browse_file(self.second_day_path)).grid(row=1, column=2)

    def _create_scotophase_section(self):
        frame = ttk.LabelFrame(self.control_frame, text="Scotophase Settings", padding="5")
        frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(frame, text="Start Time (HH:MM):").grid(row=0, column=0, sticky=tk.W)
        self.start_time = tk.StringVar(value="18:00")
        ttk.Entry(frame, textvariable=self.start_time, width=10).grid(row=0, column=1, padx=5)

        ttk.Label(frame, text="End Time (HH:MM):").grid(row=0, column=2, sticky=tk.W)
        self.end_time = tk.StringVar(value="06:00")
        ttk.Entry(frame, textvariable=self.end_time, width=10).grid(row=0, column=3, padx=5)

    def _create_bee_section(self):
        frame = ttk.LabelFrame(self.control_frame, text="Bee Management", padding="5")
        frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(frame, text="Bee Name:").grid(row=0, column=0, sticky=tk.W)
        self.bee_name = tk.StringVar()
        ttk.Entry(frame, textvariable=self.bee_name, width=20).grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Add Bee", command=self._add_bee).grid(row=0, column=2, padx=5)

        self.bee_listbox = tk.Listbox(frame, height=3, selectmode=tk.MULTIPLE)
        self.bee_listbox.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=5)
        ttk.Button(frame, text="Remove Selected",
                   command=self._remove_bee).grid(row=2, column=0, columnspan=3, pady=5)

    def _create_chart_type_section(self):
        frame = ttk.LabelFrame(self.control_frame, text="Chart Type", padding="5")
        frame.pack(fill=tk.X, padx=5, pady=5)

        self.chart_type = tk.StringVar(value="horizontal_bar")

        charts = [
            ("horizontal_bar",
             "Horizontal Bar  [DEFAULT]  —  each bee on its own row; bars span full bout "
             "duration. Best for seeing when and how long each bout lasts."),
            ("raster",
             "Raster Plot  —  one tick per bout start, height proportional to duration. "
             "Best for spotting timing clusters and comparing onset patterns across bees."),
            ("heatmap",
             "Heatmap  —  30-min bins colored by fraction of time spent asleep. "
             "Best for comparing overall sleep density across many bees at once."),
        ]

        for val, desc in charts:
            ttk.Radiobutton(
                frame,
                text=desc,
                variable=self.chart_type,
                value=val,
                command=self._on_chart_type_change,
            ).pack(anchor=tk.W, pady=2)

    def _create_analysis_section(self):
        frame = ttk.Frame(self.control_frame)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(frame, text="Analyze Selected Bees",
                   command=self._analyze_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame, text="Save Graph",
                   command=self._save_graph).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame, text="Clear Plot",
                   command=self._clear_plot).pack(side=tk.LEFT, padx=5)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _browse_file(self, path_var):
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if filename:
            path_var.set(filename)

    def _add_bee(self):
        name = self.bee_name.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Please enter a bee name.")
            return

        first  = self.first_day_path.get().strip()
        second = self.second_day_path.get().strip()
        if not first or not second:
            messagebox.showwarning("Warning", "Please select both JSON files first.")
            return

        for label, path in [("First day", first), ("Second day", second)]:
            if not os.path.isfile(path):
                messagebox.showerror("Error", f"{label} file not found:\n{path}")
                return
            try:
                with open(path) as fh:
                    data = json.load(fh)
                if not isinstance(data, list) or len(data) == 0:
                    raise ValueError("Expected a non-empty JSON array")
            except Exception as exc:
                messagebox.showerror("Error", f"{label} file is invalid:\n{exc}")
                return

        if name in self.bee_data:
            messagebox.showwarning("Warning", f"Bee '{name}' already added.")
            return

        self.bee_data[name] = {"first_day": first, "second_day": second}
        self.bee_listbox.insert(tk.END, name)
        self.bee_name.set("")
        logger.info("Added bee '%s'", name)

    def _remove_bee(self):
        for idx in reversed(self.bee_listbox.curselection()):
            name = self.bee_listbox.get(idx)
            self.bee_listbox.delete(idx)
            self.bee_data.pop(name, None)
            logger.info("Removed bee '%s'", name)

    def _on_chart_type_change(self):
        """Re-draw immediately when the user switches chart type — no reload needed."""
        if self.last_bee_dict:
            self._draw(self.last_bee_dict)

    # -----------------------------------------------------------------------
    # Data processing
    # -----------------------------------------------------------------------
    @staticmethod
    def _load_and_process(first_path, second_path):
        """Return deduplicated list of (start, end) datetime tuples and earliest timestamp."""
        with open(first_path) as fh:
            d1 = json.load(fh)
        with open(second_path) as fh:
            d2 = json.load(fh)

        df1 = pd.DataFrame(d1)
        df2 = pd.DataFrame(d2)

        for df in (df1, df2):
            df["start_time"] = pd.to_datetime(df["start_time"])
            df["end_time"]   = pd.to_datetime(df["end_time"])

        combined = pd.concat([df1, df2]).sort_values("start_time").reset_index(drop=True)

        # Prefer completed bouts if the column exists (avoids sliding-buffer duplicates).
        if "bout_complete" in combined.columns:
            complete = combined[combined["bout_complete"] == True]
            if not complete.empty:
                combined = complete

        bouts = []
        for _, row in combined.iterrows():
            dur = (row["end_time"] - row["start_time"]).total_seconds()
            if dur > 120:
                bouts.append((row["start_time"], row["end_time"]))

        rec_start = combined["start_time"].min()

        if not bouts:
            return [], rec_start

        # Merge overlapping entries.
        bouts.sort()
        deduped = [bouts[0]]
        for s, e in bouts[1:]:
            prev_s, prev_e = deduped[-1]
            if s < prev_e:
                deduped[-1] = (min(prev_s, s), max(prev_e, e))
            else:
                deduped.append((s, e))

        return deduped, rec_start

    # -----------------------------------------------------------------------
    # Shared axis utilities
    # -----------------------------------------------------------------------
    @staticmethod
    def _to_axis_hours(dt):
        """Map a datetime to fractional hours on the noon-to-noon axis."""
        return (dt.hour + dt.minute / 60 + dt.second / 3600 - HOUR_ADJ) % 24

    @staticmethod
    def _apply_time_axis(ax):
        """Shared X-axis ticks and label (noon to noon)."""
        hour_labels = [(h + HOUR_ADJ) % 24 for h in range(25)]
        ax.set_xticks(range(25))
        ax.set_xticklabels(["{:02d}:00".format(h) for h in hour_labels],
                           rotation=45, ha="right", fontsize=8)
        ax.set_xlim(-0.5, 24.5)
        ax.set_xlabel("Time of Day  (12 PM → 12 PM)", fontsize=10)

    @staticmethod
    def _shade_scotophase(ax, scoto_start, scoto_end):
        """Dark-grey shading for the scotophase (night) period."""
        def _ah(dt):
            return (dt.hour + dt.minute / 60 - HOUR_ADJ) % 24

        sc_s = _ah(scoto_start)
        sc_e = _ah(scoto_end)
        kw   = dict(alpha=0.15, color="#424242")

        if sc_e > sc_s:
            ax.axvspan(sc_s, sc_e, label="Scotophase (dark)", **kw)
        else:
            # Wraps midnight on the adjusted axis — two rectangles needed.
            ax.axvspan(sc_s, 24,  label="Scotophase (dark)", **kw)
            ax.axvspan(0,   sc_e, **kw)

    # -----------------------------------------------------------------------
    # Chart 1 — Horizontal Bar (DEFAULT)
    # -----------------------------------------------------------------------
    def _plot_horizontal_bar(self, ax, bee_dict):
        """
        One labeled row per bee. Horizontal bars span from bout start to end.
        Width = duration; position = time of day. Clearest view of individual schedules.
        """
        bar_height  = 0.55
        row_spacing = 1.0
        bee_names   = list(bee_dict.keys())
        n_bees      = len(bee_names)

        first_info = next(iter(bee_dict.values()))
        self._shade_scotophase(ax, first_info["scoto_start"], first_info["scoto_end"])

        for i, bee_name in enumerate(bee_names):
            colour   = COLORS[i % len(COLORS)]
            y_bottom = i * row_spacing - bar_height / 2

            xranges = []
            for start, end in bee_dict[bee_name]["bouts"]:
                s_h   = self._to_axis_hours(start)
                dur_h = (end - start).total_seconds() / 3600.0
                xranges.append((s_h, dur_h))

            if xranges:
                ax.broken_barh(xranges, (y_bottom, bar_height),
                               facecolors=colour, alpha=0.85,
                               edgecolors="white", linewidth=0.6,
                               label=bee_name)

        self._apply_time_axis(ax)
        ax.set_yticks([i * row_spacing for i in range(n_bees)])
        ax.set_yticklabels(bee_names, fontsize=9)
        ax.set_ylim(-row_spacing * 0.75,
                    (n_bees - 1) * row_spacing + row_spacing * 0.75)
        ax.set_ylabel("Bee", fontsize=10)
        ax.set_title("Sleep Bouts — Horizontal Bar Chart\n"
                     "Each bar = one sleep bout   |   Bar width = duration",
                     fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.2, axis="x", linestyle="--")

    # -----------------------------------------------------------------------
    # Chart 2 — Raster Plot
    # -----------------------------------------------------------------------
    def _plot_raster(self, ax, bee_dict):
        """
        One vertical tick per bout onset. Tick height proportional to bout duration.
        Bees stacked on Y. Excellent for spotting circadian timing clusters.
        """
        bee_names = list(bee_dict.keys())
        n_bees    = len(bee_names)

        first_info = next(iter(bee_dict.values()))
        self._shade_scotophase(ax, first_info["scoto_start"], first_info["scoto_end"])

        for i, bee_name in enumerate(bee_names):
            colour = COLORS[i % len(COLORS)]

            for start, end in bee_dict[bee_name]["bouts"]:
                s_h    = self._to_axis_hours(start)
                dur_h  = (end - start).total_seconds() / 3600.0
                # Scale tick height: short bouts get thin ticks, long bouts taller — capped at 0.8
                tick_h = min(0.8, 0.15 + dur_h * 0.25)
                ax.vlines(s_h, i - tick_h / 2, i + tick_h / 2,
                          colors=colour, linewidth=2.5, alpha=0.85)

            # Invisible scatter point purely for the legend entry
            ax.plot([], [], color=colour, linewidth=3, label=bee_name)

        self._apply_time_axis(ax)
        ax.set_yticks(range(n_bees))
        ax.set_yticklabels(bee_names, fontsize=9)
        ax.set_ylim(-0.75, n_bees - 0.25)
        ax.set_ylabel("Bee", fontsize=10)
        ax.set_title("Sleep Bout Onsets — Raster Plot\n"
                     "Each tick = one sleep bout   |   Tick height ∝ duration",
                     fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.2, axis="x", linestyle="--")

    # -----------------------------------------------------------------------
    # Chart 3 — Heatmap
    # -----------------------------------------------------------------------
    def _plot_heatmap(self, ax, bee_dict):
        """
        Rows = bees, columns = 30-min time bins.
        Cell color = fraction of that bin spent asleep (0=awake → 1=fully asleep).
        Reveals shared patterns and sleep density at a glance across the whole group.
        """
        n_bins    = int(24 * 60 / BIN_MIN)
        bin_edges = np.linspace(0, 24, n_bins + 1)
        bee_names = list(bee_dict.keys())
        n_bees    = len(bee_names)

        # Build sleep-fraction matrix (rows=bees, cols=bins)
        matrix = np.zeros((n_bees, n_bins))
        for i, bee_name in enumerate(bee_names):
            for start, end in bee_dict[bee_name]["bouts"]:
                s_h   = self._to_axis_hours(start)
                dur_h = (end - start).total_seconds() / 3600.0
                e_h   = s_h + dur_h
                for b in range(n_bins):
                    overlap = min(e_h, bin_edges[b + 1]) - max(s_h, bin_edges[b])
                    if overlap > 0:
                        matrix[i, b] += overlap / (BIN_MIN / 60.0)

        matrix = np.clip(matrix, 0, 1)

        im = ax.imshow(matrix, aspect="auto", origin="upper",
                       cmap="Blues", vmin=0, vmax=1,
                       extent=[-0.5, 24.5, n_bees - 0.5, -0.5])

        cbar = ax.get_figure().colorbar(im, ax=ax, pad=0.02, fraction=0.03)
        cbar.set_label("Fraction of bin spent asleep", fontsize=9)
        cbar.ax.tick_params(labelsize=8)

        # Scotophase overlay on top of the image
        first_info = next(iter(bee_dict.values()))

        def _ah(dt):
            return (dt.hour + dt.minute / 60 - HOUR_ADJ) % 24

        sc_s = _ah(first_info["scoto_start"])
        sc_e = _ah(first_info["scoto_end"])
        kw   = dict(alpha=0.18, color="#424242")

        if sc_e > sc_s:
            ax.axvspan(sc_s, sc_e, label="Scotophase (dark)", **kw)
        else:
            ax.axvspan(sc_s, 24,  label="Scotophase (dark)", **kw)
            ax.axvspan(0,   sc_e, **kw)

        self._apply_time_axis(ax)
        ax.set_yticks(range(n_bees))
        ax.set_yticklabels(bee_names, fontsize=9)
        ax.set_ylabel("Bee", fontsize=10)
        ax.set_title(f"Sleep Density — Heatmap  ({BIN_MIN}-min bins)\n"
                     "Darker blue = more time asleep in that window",
                     fontsize=11, fontweight="bold")

    # -----------------------------------------------------------------------
    # Dispatch
    # -----------------------------------------------------------------------
    def _draw(self, bee_dict):
        """Close old figure and render the currently selected chart type."""
        if self.current_figure:
            plt.close(self.current_figure)

        n_bees     = len(bee_dict)
        fig_height = max(5, 2 + n_bees * 1.1)
        self.current_figure = plt.Figure(figsize=(14, fig_height))
        ax = self.current_figure.add_subplot(111)

        chart = self.chart_type.get()
        if chart == "horizontal_bar":
            self._plot_horizontal_bar(ax, bee_dict)
        elif chart == "raster":
            self._plot_raster(ax, bee_dict)
        elif chart == "heatmap":
            self._plot_heatmap(ax, bee_dict)

        # Deduplicated legend
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(list(by_label.values()), list(by_label.keys()),
                  loc="upper right", fontsize=8, framealpha=0.9)

        self.current_figure.tight_layout()

        if self.canvas:
            self.canvas.get_tk_widget().destroy()
        self.canvas = FigureCanvasTkAgg(self.current_figure, self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # -----------------------------------------------------------------------
    def _analyze_selected(self):
        selection = self.bee_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select at least one bee to analyze.")
            return

        try:
            scoto_start = datetime.strptime(self.start_time.get().strip(), "%H:%M")
            scoto_end   = datetime.strptime(self.end_time.get().strip(), "%H:%M")
        except ValueError:
            messagebox.showerror("Error", "Invalid scotophase time. Use HH:MM (e.g. 18:00).")
            return

        bee_dict = {}
        for idx in selection:
            name  = self.bee_listbox.get(idx)
            files = self.bee_data[name]
            try:
                bouts, rec_start = self._load_and_process(files["first_day"],
                                                          files["second_day"])
                bee_dict[name] = {
                    "bouts":        bouts,
                    "record_start": rec_start,
                    "scoto_start":  scoto_start,
                    "scoto_end":    scoto_end,
                }
                logger.info("Processed '%s': %d bouts (>120 s)", name, len(bouts))
            except Exception as exc:
                logger.exception("Error processing bee '%s'", name)
                messagebox.showerror("Error", f"Error processing {name}:\n{exc}")
                return

        if bee_dict:
            self.last_bee_dict = bee_dict   # cache so chart-type toggle redraws instantly
            self._draw(bee_dict)

    def _save_graph(self):
        if not self.current_figure:
            messagebox.showwarning("Warning", "No graph to save. Run analysis first.")
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("PDF Document", "*.pdf"),
                       ("SVG Image", "*.svg"), ("All files", "*.*")],
            title="Save Graph As")
        if filepath:
            try:
                self.current_figure.savefig(filepath, dpi=300, bbox_inches="tight")
                logger.info("Graph saved to '%s'", filepath)
                messagebox.showinfo("Saved", f"Graph saved to:\n{filepath}")
            except Exception as exc:
                logger.exception("Error saving graph")
                messagebox.showerror("Error", f"Could not save graph:\n{exc}")

    def _clear_plot(self):
        if self.current_figure:
            plt.close(self.current_figure)
            self.current_figure = None
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        self.last_bee_dict = {}
        logger.info("Plot cleared")


def main():
    root = tk.Tk()
    BeeSleepAnalyzer(root)
    root.mainloop()


if __name__ == "__main__":
    main()