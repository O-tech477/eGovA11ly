#!/usr/bin/env python3
"""Write eGovA11y_implementation_note.pdf from the JSON files in research/data."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research" / "data"
OUT = ROOT / "eGovA11y_implementation_note.pdf"
FIG = Path("/tmp/egov_note_figs")

INK = Color(0.12, 0.12, 0.12)
MUTED = Color(0.33, 0.33, 0.33)

SHORT = {
    "Andaman and Nicobar Islands": "Andaman & Nicobar",
    "Dadra and Nagar Haveli and Daman and Diu": "DNHDD",
    "Food Processing Industries (MoFPI)": "Food Processing",
    "Heavy Industries (MoHI)": "Heavy Industries",
    "Defence (MoD)": "Defence",
}
LANG = {
    "hi": "Hindi",
    "gu": "Gujarati",
    "as": "Assamese",
    "or": "Odia",
    "ta": "Tamil",
    "ANHindi": "Hindi",
}


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def pair_label(row: dict) -> str:
    path = urlparse(row.get("other_final_url") or row["other_url"]).path.strip("/")
    token = path.split("/")[0] if path else row.get("hint")
    lang = LANG.get(token) or LANG.get(row.get("hint"), row["script"])
    return f"{SHORT.get(row['name'], row['name'])} ({lang})"


def charts(esevai: dict, frame: dict) -> tuple[Path, Path]:
    FIG.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "Liberation Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#222222",
            "xtick.color": "#222222",
            "ytick.color": "#222222",
            "text.color": "#222222",
            "axes.labelcolor": "#222222",
            "font.size": 9,
        }
    )

    pages = esevai["pages"]
    portal, service = pages["portal_entry"], pages["service_list"]
    fig, ax = plt.subplots(figsize=(7.15, 2.45), dpi=150)
    x = range(2)
    width = 0.36
    english = [portal["tamil_chars_en"], service["tamil_chars_en"]]
    tamil = [portal["tamil_chars_ta"], service["tamil_chars_ta"]]
    b1 = ax.bar([i - width / 2 for i in x], english, width, color="#9aa0a6", label="English session")
    b2 = ax.bar([i + width / 2 for i in x], tamil, width, color="#0f6e56", label="Tamil session")
    ax.set_xticks(list(x), ["Portal", "Service list"])
    ax.set_ylabel("Tamil characters")
    ax.set_title("Tamil characters after the e-Sevai language switch", loc="left", fontsize=11, pad=8)
    ax.legend(frameon=False, loc="upper right")
    ax.set_ylim(0, max(tamil) * 1.18)
    for bars in (b1, b2):
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{int(height):,}",
                (bar.get_x() + bar.get_width() / 2, height),
                ha="center",
                va="bottom",
                fontsize=8,
                xytext=(0, 2),
                textcoords="offset points",
            )
    fig.tight_layout()
    esevai_path = FIG / "esevai.png"
    fig.savefig(esevai_path)
    plt.close(fig)

    rows = sorted(frame["pairs"], key=lambda row: row["live_gain"])
    colors = []
    for row in rows:
        if not row["comparable"]:
            colors.append("#8a5a2a")
        elif row["accessibility_gap"]:
            colors.append("#b42318")
        else:
            colors.append("#0f6e56")
    fig, ax = plt.subplots(figsize=(7.15, 4.15), dpi=150)
    ax.barh([pair_label(row) for row in rows], [row["live_gain"] for row in rows], color=colors, height=0.72)
    ax.axvline(100, color="#222222", lw=0.8, ls=(0, (3, 2)))
    ax.set_xlabel("Extra characters of the regional script")
    ax.set_title("Script gain on the 13 homepage pairs", loc="left", fontsize=11, pad=8)
    top = max(row["live_gain"] for row in rows)
    ax.set_xlim(0, top * 1.12)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color="#0f6e56"),
        plt.Rectangle((0, 0), 1, 1, color="#b42318"),
        plt.Rectangle((0, 0), 1, 1, color="#8a5a2a"),
    ]
    ax.legend(handles, ["Same axe rules", "Rule on one side only", "Under 100, not scored"], frameon=False, loc="lower right")
    fig.tight_layout()
    frame_path = FIG / "frame.png"
    fig.savefig(frame_path)
    plt.close(fig)
    return esevai_path, frame_path


def side_phrase(row: dict) -> str:
    parts = []
    if row["accessibility_only_en"]:
        parts.append(", ".join(row["accessibility_only_en"]) + " on the English page")
    if row["accessibility_only_other"]:
        parts.append(", ".join(row["accessibility_only_other"]) + " on the regional page")
    return f"{pair_label(row)}: {'; '.join(parts)}."


def build() -> None:
    sites = load("site_frame.json")
    esevai = load("esevai_rev101_alignment.json")
    frame = load("frame_alignment.json")
    counts = sites["summary"]["counts"]
    portal = esevai["pages"]["portal_entry"]
    service = esevai["pages"]["service_list"]
    summary = frame["summary"]
    gaps = [row for row in frame["pairs"] if row.get("accessibility_gap")]
    content = [row for row in frame["pairs"] if row.get("content_gap")]
    same = [row for row in frame["pairs"] if row.get("comparable") and not row.get("accessibility_gap")]
    empty = [row for row in same if not row["shared_failures"]]

    esevai_fig, frame_fig = charts(esevai, frame)
    pdfmetrics.registerFont(TTFont("Body", "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Bold", "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Italic", "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Italic.ttf"))

    body = ParagraphStyle("body", fontName="Body", fontSize=10, leading=13.2, textColor=INK, alignment=TA_LEFT, spaceAfter=7)
    h = ParagraphStyle("h", fontName="Body-Bold", fontSize=11.5, leading=14, textColor=INK, spaceBefore=8, spaceAfter=4)
    title = ParagraphStyle("title", fontName="Body-Bold", fontSize=15, leading=18, textColor=INK, spaceAfter=2)
    cap = ParagraphStyle("cap", fontName="Body-Italic", fontSize=8.5, leading=11, textColor=MUTED, spaceBefore=1, spaceAfter=6)
    small = ParagraphStyle("small", fontName="Body", fontSize=9, leading=12, textColor=INK, spaceAfter=3)

    gap_text = " ".join(side_phrase(row) for row in gaps)
    content_text = " ".join(
        f"{pair_label(row)} gained {row['live_gain']:,} {row['script']} characters, so it stays under the line and its axe output is unscored."
        for row in content
    )
    empty_name = empty[0]["name"] if empty else "none"
    shared = ", ".join(portal["shared_failures"])

    story = [
        Paragraph("What we ran on the language pairs", title),
        Paragraph("eGovA11y · 23 September 2026", small),
        Spacer(1, 2 * mm),
        Paragraph("What we did", h),
        Paragraph(
            f"The site list is the Integrated Government Online Directory, igod.gov.in, pulled on 22 September 2026. "
            f"build_frame.py kept the state-portal link on each state and union-territory page, and the first page of union ministries. "
            f"That file has {counts['rows']} rows: {counts['by_stratum']['state_portal']} state portals and "
            f"{counts['by_stratum']['union_ministry']} ministries. "
            f"{counts['by_profile']['unreachable']} homepages did not load. "
            f"Schemes, departments, districts, and courts are listed in the file as deferred. "
            f"WAccess already published a homepage violation count on the old directory, so this pass did not repeat that census.",
            body,
        ),
        Paragraph(
            "audit_esevai_pair.py opened Tamil Nadu e-Sevai, Community Certificate (REV-101), at tnesevai.tn.gov.in. "
            "The site loads in Tamil. English is the “English Version” postback on the same URL, in a separate browser session. "
            "The certificate form needs a login, so the script stops at the portal and the public service list.",
            body,
        ),
        Paragraph(
            f"align_frame.py then took other homepages from that directory file. "
            f"A URL is kept only when the file already has a short language path, such as /hi, /or, /as, or /ANHindi/. "
            f"PDFs, sitemaps, and contact pages are dropped. "
            f"The script opened {summary['pairs_attempted']} pairs and skipped {summary['skipped']} sites that had no such URL. "
            f"e-Sevai is not in that file.",
            body,
        ),
        Paragraph("How a pair is scored", h),
        Paragraph(
            "Firefox, through Playwright, runs axe-core 4.13.0 with the tags wcag2a, wcag2aa, wcag21a, wcag21aa, and wcag22aa. "
            "The wait is DOMContentLoaded plus 1.5 seconds. "
            "A page counts as a pair when the regional session has at least 100 more characters of its own script than the English session. "
            "Under that line the row is a content gap under GIGW 3.0 clauses 5.4.10 and 5.4.6, and the axe output is left unscored. "
            "Over the line, a rule that fails on one side only is an accessibility gap. Rules that fail on both sides are shared.",
            body,
        ),
        Paragraph("e-Sevai", h),
        KeepTogether(
            [
                Image(str(esevai_fig), width=172 * mm, height=59 * mm),
                Paragraph(
                    "Grey bars are the English session. Green bars are the Tamil session. The service-list bars are both 16.",
                    cap,
                ),
            ]
        ),
        Paragraph(
            f"The portal has {portal['tamil_chars_en']} Tamil characters in the English session and "
            f"{portal['tamil_chars_ta']:,} in the Tamil session. Both sessions fail the same five rules: {shared}. "
            f"The service list has {service['tamil_chars_en']} Tamil characters in each session, and it still names Community Certificate in English. "
            f"That list is a content gap under clauses 5.4.10 and 5.4.6.",
            body,
        ),
        Paragraph("Other homepages", h),
        KeepTogether(
            [
                Image(str(frame_fig), width=172 * mm, height=100 * mm),
                Paragraph(
                    "Green bars match on both languages. Red bars have a rule on one side only. The brown bar is Culture, under 100 characters.",
                    cap,
                ),
            ]
        ),
        Paragraph(
            f"{summary['comparable']} pairs cleared 100 characters. {len(same)} of them fail the same axe rules on both sides. "
            f"{empty_name} is in that group, and axe reported no A/AA violation on either homepage. "
            f"{len(gaps)} pairs have a one-sided rule. {gap_text} {content_text}",
            body,
        ),
        Paragraph(
            "The character count shows that the other script was on the page. "
            "Whether the two URLs are the same service still has to be read by hand. "
            "Heavy Industries was requested at the homepage and the browser finished on /hi. "
            "Food Processing’s /en address did not load, so the English URL stored for that pair is the site root.",
            body,
        ),
        Paragraph("Next", h),
        Paragraph(
            "Read the comparable homepages and mark which URLs are the same page. "
            "Run this check on one service page, not the homepage, for a state that already has two language roots. "
            "Continue the union-ministry pages on igod past the first page.",
            body,
        ),
        Paragraph(
            "File sources are in research/data/sources.json. "
            "GIGW 3.0 clauses 5.4.6 and 5.4.10: https://guidelines.india.gov.in/lifecycle-management/. "
            "WCAG 2.1 and 2.2: https://www.w3.org/TR/WCAG21/ and https://www.w3.org/TR/WCAG22/. "
            "axe-core 4.13.0, pinned in package.json. "
            "WAccess: Boyalakuntla, Venigalla, and Chimalakonda, arXiv:2107.06799.",
            small,
        ),
    ]

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Body", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, "eGovA11y")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title="eGovA11y — what we ran",
        author="eGovA11y",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
