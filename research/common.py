"""axe-core tags, Indic script counts, and the 100-character pair rule."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research" / "data"
AXE = ROOT / "node_modules" / "axe-core" / "axe.min.js"
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
MINIMUM_GAIN = 100
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
GIGW_URL = "https://guidelines.india.gov.in/lifecycle-management/"
GIGW_CLAUSES = ["5.4.10", "5.4.6"]

SCRIPTS = {
    "Devanagari": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Gujarati": (0x0A80, 0x0AFF),
    "Odia": (0x0B00, 0x0B7F),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
    "Arabic": (0x0600, 0x06FF),
}


def count_scripts(text: str, minimum: int = 1) -> dict[str, int]:
    counts = {name: 0 for name in SCRIPTS}
    for ch in text:
        code = ord(ch)
        for name, (start, end) in SCRIPTS.items():
            if start <= code <= end:
                counts[name] += 1
                break
    return {name: n for name, n in counts.items() if n >= minimum}


def provenance(script: str, source: str, retrieved: str) -> dict:
    return {"script": script, "source": source, "retrieved": retrieved}


def axe_violations(page) -> list[dict]:
    if page.evaluate("() => typeof axe !== 'object'"):
        page.add_script_tag(path=str(AXE))
    raw = page.evaluate(
        """(tags) => axe.run(document, {
            runOnly: { type: 'tag', values: tags },
            resultTypes: ['violations']
        })""",
        WCAG_TAGS,
    )
    found = []
    for item in raw.get("violations", []):
        found.append(
            {
                "id": item.get("id"),
                "impact": item.get("impact"),
                "help": item.get("help"),
                "wcag": [tag for tag in item.get("tags", []) if str(tag).startswith("wcag")],
                "nodes": len(item.get("nodes") or []),
            }
        )
    found.sort(key=lambda item: item["id"])
    return found
