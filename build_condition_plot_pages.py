#!/usr/bin/env python3
"""Build one printable comparison-plot page per experimental condition."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
CLEAN_DIR = ROOT / "json files to be rescued" / "cleaned"
OUTPUT_DIR = ROOT / "output" / "pdf"
PAGE_SIZE = (17 * inch, 22 * inch)

GROUPS = {
    "Disrupted": {
        "accent": "#9F1239",
        "dates": [
            "20250715",
            "20250717",
            "20250722",
            "20250903",
            "20250909",
            "20250918",
            "20250924",
            "20250925",
            "20250930",
            "20251001",
        ],
    },
    "Intact": {
        "accent": "#166534",
        "dates": [
            "20250731",
            "20250805",
            "20250806",
            "20250807",
            "20250813",
            "20250826",
            "20250827",
            "20250911",
            "20250916",
        ],
    },
}


def readable_date(date_code: str) -> str:
    return datetime.strptime(date_code, "%Y%m%d").strftime("%B %-d, %Y")


def plot_path(group_name: str, date_code: str) -> Path:
    return (
        CLEAN_DIR
        / group_name
        / "plots"
        / f"sleep_log_{date_code}_original_vs_clean.png"
    )


def draw_group_page(pdf: canvas.Canvas, group_name: str) -> None:
    page_width, page_height = PAGE_SIZE
    accent = HexColor(GROUPS[group_name]["accent"])
    dates = GROUPS[group_name]["dates"]
    margin = 0.3 * inch
    title_height = 0.5 * inch
    subtitle_height = 0.27 * inch
    footer_height = 0.2 * inch
    column_gap = 0.18 * inch
    row_gap = 0.08 * inch

    pdf.setFillColor(white)
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    pdf.setFillColor(accent)
    pdf.rect(
        margin,
        page_height - margin - title_height,
        page_width - 2 * margin,
        title_height,
        fill=1,
        stroke=0,
    )
    pdf.setFillColor(white)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(
        page_width / 2,
        page_height - margin - title_height + 10,
        f"{group_name} - original vs cleaned sleep-log plots",
    )

    pdf.setFillColor(HexColor("#334155"))
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(
        page_width / 2,
        page_height - margin - title_height - 14,
        (
            f"{len(dates)} sessions | Timestamp-derived duration >120 seconds | "
            "Distinct start times remain separate"
        ),
    )

    grid_top = page_height - margin - title_height - subtitle_height
    grid_bottom = margin + footer_height
    grid_height = grid_top - grid_bottom
    grid_width = page_width - 2 * margin
    cell_width = (grid_width - column_gap) / 2
    cell_height = (grid_height - 4 * row_gap) / 5
    label_height = 0.22 * inch

    for index, date_code in enumerate(dates):
        row = index // 2
        column = index % 2
        cell_left = margin + column * (cell_width + column_gap)
        cell_top = grid_top - row * (cell_height + row_gap)
        cell_bottom = cell_top - cell_height

        pdf.setFillColor(accent)
        pdf.setFont("Helvetica-Bold", 9.5)
        pdf.drawCentredString(
            cell_left + cell_width / 2,
            cell_top - 10,
            f"{readable_date(date_code)} | sleep_log_{date_code}_clean.json",
        )

        available_height = cell_height - label_height
        image_width = cell_width
        image_height = image_width / 2.5
        if image_height > available_height:
            image_height = available_height
            image_width = image_height * 2.5
        image_x = cell_left + (cell_width - image_width) / 2
        image_y = cell_bottom + (available_height - image_height) / 2
        pdf.drawImage(
            str(plot_path(group_name, date_code)),
            image_x,
            image_y,
            width=image_width,
            height=image_height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )

    pdf.setFillColor(HexColor("#64748B"))
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(
        page_width / 2,
        0.16 * inch,
        "Page size: 17 x 22 inches. Print at actual size or choose Fit to Page.",
    )


def build_single_page(group_name: str, path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE, pageCompression=1)
    draw_group_page(pdf, group_name)
    pdf.showPage()
    pdf.save()


def build_combined(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE, pageCompression=1)
    for group_name in ("Disrupted", "Intact"):
        draw_group_page(pdf, group_name)
        pdf.showPage()
    pdf.save()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for group_name, details in GROUPS.items():
        for date_code in details["dates"]:
            path = plot_path(group_name, date_code)
            if not path.exists():
                raise FileNotFoundError(path)

    build_single_page(
        "Disrupted", OUTPUT_DIR / "printable_disrupted_plots.pdf"
    )
    build_single_page("Intact", OUTPUT_DIR / "printable_intact_plots.pdf")
    build_combined(OUTPUT_DIR / "printable_disrupted_intact_plots.pdf")


if __name__ == "__main__":
    main()
