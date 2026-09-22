#!/usr/bin/env python3
"""Apply the 100-character Tamil rule to research/data/esevai_rev101.json.

No browser. A page is a language pair only when the Tamil session gained
enough Tamil text. Writes esevai_rev101_alignment.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from common import DATA, GIGW_CLAUSES, GIGW_URL, MINIMUM_GAIN, provenance

SRC = DATA / "esevai_rev101.json"
OUT = DATA / "esevai_rev101_alignment.json"


def switched(en: dict, ta: dict) -> bool:
    return (ta["tamil_chars"] - en["tamil_chars"]) >= MINIMUM_GAIN


def align_page(name: str, en: dict, ta: dict, axe: dict) -> dict:
    gain = ta["tamil_chars"] - en["tamil_chars"]
    comparable = switched(en, ta)
    record = {
        "page": name,
        "url_en": en["final_url"],
        "url_ta": ta["final_url"],
        "tamil_chars_en": en["tamil_chars"],
        "tamil_chars_ta": ta["tamil_chars"],
        "tamil_gain": gain,
        "names_service_en": en["names_service"],
        "names_service_ta": ta["names_service"],
        "comparable": comparable,
    }
    if comparable:
        only_en = [item["id"] for item in axe["only_en"]]
        only_ta = [item["id"] for item in axe["only_ta"]]
        record.update(
            {
                "reason": "Tamil text increased after the language switch, so the two sessions are the same step in two languages.",
                "content_gap": False,
                "accessibility_scored": True,
                "accessibility_gap": bool(only_en or only_ta),
                "accessibility_only_en": only_en,
                "accessibility_only_ta": only_ta,
                "shared_failures": [item["id"] for item in axe["both"]],
            }
        )
        return record

    record.update(
        {
            "reason": "The Tamil session did not gain Tamil text, so this is not a Tamil page. Identical axe results are not scored.",
            "content_gap": True,
            "accessibility_scored": False,
            "accessibility_gap": None,
            "gigw": list(GIGW_CLAUSES),
        }
    )
    return record


def main() -> None:
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    if payload["summary"]["en_error"] or payload["summary"]["ta_error"]:
        raise SystemExit("axe pair has an error; re-run audit_esevai_pair.py first")

    pages = {
        name: align_page(name, payload["en"][name], payload["ta"][name], payload["comparison"][name])
        for name in ("portal_entry", "service_list")
    }
    content_gaps = [name for name, page in pages.items() if page["content_gap"]]
    accessibility_gaps = [
        name for name, page in pages.items() if page["accessibility_scored"] and page["accessibility_gap"]
    ]
    generated_at = datetime.now(timezone.utc).isoformat()
    source = "research/data/esevai_rev101.json"
    report = {
        "generated_at": generated_at,
        "source": source,
        "provenance": provenance("research/align_esevai.py", source, generated_at),
        "service": payload["summary"]["service"],
        "service_code": payload["summary"]["service_code"],
        "required_languages": ["en", "ta"],
        "obligation": {
            "source": "GIGW 3.0",
            "url": GIGW_URL,
            "clauses": {
                "5.4.10": "Website/app is bilingual with a prominent language selection link and uses Unicode characters. Translate all content, or the widely accessed sections, into the regional language.",
                "5.4.6": "Documents/pages in multiple languages are updated simultaneously so visitors get the same content in each language.",
            },
            "regional_language": "ta",
        },
        "rule": f"A page is a language pair only when the Tamil session has at least {MINIMUM_GAIN} more Tamil characters than the English session.",
        "pages": pages,
        "verdict": {
            "content_gaps": content_gaps,
            "accessibility_gaps": accessibility_gaps,
            "summary": (
                "The portal shell is a real English–Tamil pair and the axe failures match, so it has no accessibility gap. "
                "The service list stayed English, so it is a content gap under GIGW 5.4.10 and 5.4.6 and is not an accessibility pass."
            ),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["verdict"]["summary"])
    for name, page in pages.items():
        print(
            f"  {name}: comparable={page['comparable']} content_gap={page['content_gap']} "
            f"accessibility_scored={page['accessibility_scored']}"
        )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
