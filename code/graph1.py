#!/usr/bin/env python3
"""
graph.py — Bee Sleep Pattern Analyzer (Tkinter GUI).

Loads pairs of JSON sleep-log files, merges consecutive sleep intervals,
and plots horizontal bar-charts of sleep bouts across a 12 PM–12 PM axis
with scotophase overlay.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import matplotlib
matplotlib.use("TkAgg")           # Explicit backend before pyplot import
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------------------------------------------------------------------
LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt=DATE_FMT,
                    stream=sys.stdout)
logger = logging.getLogger("bee_graph")


# ---------------------------------------------------------------------------
class BeeSleepAnalyzer:
    def __init__(self, root):
        self.root = root
        self.root.title("Bee Sleep Pattern Analyzer")
        self.root.geometry("1200x800")

        self.bee_data = {}          # {name: {"first_day": path, "second_day": path}}
        self.current_figure = None
        self.canvas = None

        self.setup_gui()

    # ---------------------------------------------------------------
    # GUI layout
    # ---------------------------------------------------------------
    def setup_gui(self):
        self.control_frame = ttk.Frame(self.root, padding="5")
        self.control_frame.pack(fill=tk.X, padx=5, pady=5)

        self.plot_frame = ttk.Frame(self.root)
        self.plot_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._create_file_section()
        self._create_scotophase_section()
        self._create_bee_section()
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

    def _create_analysis_section(self):
        frame = ttk.Frame(self.control_frame)
        frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(frame, text="Analyze Selected Bees",
                   command=self._analyze_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame, text="Save Graph",
                   command=self._save_graph).pack(side=tk.LEFT, padx=5)
        ttk.Button(frame, text="Clear Plot",
                   command=self._clear_plot).pack(side=tk.LEFT, padx=5)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
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

        first = self.first_day_path.get().strip()
        second = self.second_day_path.get().strip()
        if not first or not second:
            messagebox.showwarning("Warning", "Please select both JSON files first.")
            return

        # Validate files are readable JSON
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

    # ---------------------------------------------------------------
    # Data processing
    # ---------------------------------------------------------------
    @staticmethod
    def _load_and_process(first_path, second_path):
        with open(first_path) as fh:
            d1 = json.load(fh)
        with open(second_path) as fh:
            d2 = json.load(fh)

        df1 = pd.DataFrame(d1)
        df2 = pd.DataFrame(d2)

        for df in (df1, df2):
            df["start_time"] = pd.to_datetime(df["start_time"])
            df["end_time"] = pd.to_datetime(df["end_time"])

        combined = pd.concat([df1, df2]).sort_values("start_time").reset_index(drop=True)

        # Use individual entries instead of merging.
        # Keep only entries with duration > 120 seconds.
        # If bout_complete column exists, prefer those entries to avoid
        # double-counting intermediate logs.
        if "bout_complete" in combined.columns:
            complete = combined[combined["bout_complete"] == True]
            if not complete.empty:
                combined = complete

        bouts = []
        for _, row in combined.iterrows():
            dur = (row["end_time"] - row["start_time"]).total_seconds()
            if dur > 120:
                bouts.append((row["start_time"], row["end_time"]))

        # Deduplicate overlapping entries (logging artifact from sliding buffer)
        if not bouts:
            return bouts, combined["start_time"].min()
        bouts.sort()
        deduped = [bouts[0]]
        for s, e in bouts[1:]:
            prev_s, prev_e = deduped[-1]
            if s < prev_e:
                # Overlapping - extend to cover both
                deduped[-1] = (min(prev_s, s), max(prev_e, e))
            else:
                deduped.append((s, e))

        return deduped, combined["start_time"].min()

    @staticmethod
    def _merge_intervals(df, max_gap_seconds=120):
        if df.empty:
            return []
        merged = []
        cur_start = df.iloc[0]["start_time"]
        cur_end = df.iloc[0]["end_time"]
        for _, row in df.iloc[1:].iterrows():
            if (row["start_time"] - cur_end).total_seconds() <= max_gap_seconds:
                cur_end = max(cur_end, row["end_time"])
            else:
                merged.append((cur_start, cur_end))
                cur_start = row["start_time"]
                cur_end = row["end_time"]
        merged.append((cur_start, cur_end))
        return merged

    # ---------------------------------------------------------------
    # Plotting
    # ---------------------------------------------------------------
    def _plot_sleep_patterns(self, bee_dict):
        if self.current_figure:
            plt.close(self.current_figure)

        self.current_figure = plt.Figure(figsize=(14, 7))
        ax = self.current_figure.add_subplot(111)

        colors = ["#2196F3", "#4CAF50", "#9C27B0", "#FF9800", "#00BCD4"]
        hour_adj = 12  # axis starts at noon

        # Scotophase shaded background
        first_info = next(iter(bee_dict.values()))
        sc_s = first_info["scoto_start"].hour + first_info["scoto_start"].minute / 60
        sc_e = first_info["scoto_end"].hour + first_info["scoto_end"].minute / 60
        if sc_e < sc_s:
            sc_e += 24
        sc_s_adj = (sc_s - hour_adj) % 24
        sc_e_adj = (sc_e - hour_adj) % 24
        if sc_e_adj < sc_s_adj:
            sc_e_adj += 24
        ax.axvspan(sc_s_adj, sc_e_adj, alpha=0.12, color="gray", label="Scotophase")

        bar_width = 0.15  # width in hours on x-axis
        max_dur = 0

        for i, (bee_name, info) in enumerate(bee_dict.items()):
            colour = colors[i % len(colors)]
            intervals = info["merged_intervals"]
            labelled = False
            for j, (start, end) in enumerate(intervals):
                # X position: start time mapped to 12PM-12PM axis
                s_h = (start.hour + start.minute / 60 - hour_adj) % 24
                # Y value: duration in minutes
                dur_min = (end - start).total_seconds() / 60.0
                if dur_min > max_dur:
                    max_dur = dur_min

                # Offset bars slightly for multiple bees
                offset = (i - (len(bee_dict) - 1) / 2.0) * bar_width
                label = bee_name if not labelled else ""
                labelled = True
                ax.bar(s_h + offset, dur_min, width=bar_width,
                       color=colour, alpha=0.7, label=label,
                       edgecolor="white", linewidth=0.5)

        # X-axis: hours from noon to noon
        hours = [(h + hour_adj) % 24 for h in range(25)]
        ax.set_xticks(range(25))
        ax.set_xticklabels(["{:02d}:00".format(h) for h in hours])
        ax.set_xlim(-0.5, 24.5)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)

        # Y-axis: duration
        ax.set_ylim(0, max_dur * 1.15 if max_dur > 0 else 10)
        ax.set_ylabel("Sleep Bout Duration (minutes)")
        ax.set_xlabel("Time of Day (12 PM - 12 PM)")
        ax.set_title("Bee Sleep Patterns -- Bout Duration Over Time")
        ax.grid(True, alpha=0.25, axis="y", linestyle="--")
        ax.grid(True, alpha=0.15, axis="x", linestyle=":")

        # Legend (Python 3.6 safe)
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(list(by_label.values()), list(by_label.keys()),
                  loc="upper right", bbox_to_anchor=(1.0, 1.0), fontsize=8)
        self.current_figure.tight_layout()

        if self.canvas:
            self.canvas.get_tk_widget().destroy()
        self.canvas = FigureCanvasTkAgg(self.current_figure, self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------
    def _analyze_selected(self):
        selection = self.bee_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select at least one bee to analyze.")
            return

        # Validate scotophase times
        try:
            scoto_start = datetime.strptime(self.start_time.get().strip(), "%H:%M")
            scoto_end = datetime.strptime(self.end_time.get().strip(), "%H:%M")
        except ValueError:
            messagebox.showerror("Error", "Invalid scotophase time. Use HH:MM (e.g. 18:00).")
            return

        bee_dict = {}
        for idx in selection:
            name = self.bee_listbox.get(idx)
            files = self.bee_data[name]
            try:
                df, rec_start = self._load_and_process(files["first_day"], files["second_day"])
                bee_dict[name] = {
                    "merged_intervals": df,
                    "record_start": rec_start,
                    "scoto_start": scoto_start,
                    "scoto_end": scoto_end,
                }
                logger.info("Processed '%s': %d bouts (>120s)", name, len(df))
            except Exception as exc:
                logger.exception("Error processing bee '%s'", name)
                messagebox.showerror("Error", f"Error processing {name}:\n{exc}")
                return

        if bee_dict:
            self._plot_sleep_patterns(bee_dict)

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
                messagebox.showinfo("Saved", "Graph saved to:\n{}".format(filepath))
            except Exception as exc:
                logger.exception("Error saving graph")
                messagebox.showerror("Error", "Could not save graph:\n{}".format(exc))

    def _clear_plot(self):
        if self.current_figure:
            plt.close(self.current_figure)
            self.current_figure = None
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        logger.info("Plot cleared")


def main():
    root = tk.Tk()
    BeeSleepAnalyzer(root)
    root.mainloop()


if __name__ == "__main__":
    main()