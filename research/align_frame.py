#!/usr/bin/env python3
"""Score shallow language homepages already listed in site_frame.json.

Keeps a pair only when the frame fetched a one-segment language URL.
Runs axe-core on those URLs. e-Sevai is left to align_esevai.py.
Writes research/data/frame_alignment.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright

from common import (
    AXE,
    DATA,
    GIGW_CLAUSES,
    GIGW_URL,
    MINIMUM_GAIN,
    UA,
    axe_violations,
    count_scripts,
    provenance,
)

FRAME = DATA / "site_frame.json"
OUT = DATA / "frame_alignment.json"

LANG_SCRIPT = {
    "hi": "Devanagari",
    "mr": "Devanagari",
    "as": "Bengali",
    "bn": "Bengali",
    "gu": "Gujarati",
    "or": "Odia",
    "od": "Odia",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Gurmukhi",
    "ur": "Arabic",
}
LANG_CODES = set(LANG_SCRIPT) | {"en"}
SKIP_PATH = (
    "screen-reader",
    "sitemap",
    "contact",
    "feedback",
    "organization",
    "documentdetails",
    "whos-who",
    "goals-and-roles",
    "telephone",
    "history-of",
    "pride-of",
    "department-registration",
    ".pdf",
    ".zip",
)
def path_of(url: str) -> str:
    return urlparse(url).path.lower()


def shallow_language_url(url: str, hint: str | None) -> bool:
    path = path_of(url).strip("/")
    if not path or any(bit in path for bit in SKIP_PATH):
        return False
    parts = [part for part in path.split("/") if part]
    if len(parts) != 1:
        return False
    token = parts[0]
    return token in LANG_CODES or (hint in LANG_CODES if hint else False)


def script_of(scripts: dict, name: str) -> int:
    return int((scripts or {}).get(name, 0))


def dominant_script(scripts: dict) -> str | None:
    indic = {name: count for name, count in (scripts or {}).items() if count}
    if not indic:
        return None
    return max(indic, key=indic.get)


def choose_pairs(frame: dict) -> tuple[list[dict], list[dict]]:
    pairs = []
    skipped = []
    for row in frame["rows"]:
        label = row.get("state") or row["name"]
        if row["profile"] == "unreachable":
            continue
        home_scripts = (row.get("homepage") or {}).get("scripts") or {}
        pages = [
            {
                "url": row["url"],
                "hint": "home",
                "scripts": home_scripts,
            }
        ]
        for alt in row.get("alternates") or []:
            url = alt.get("final_url") or alt.get("url")
            if alt.get("status") != 200 or alt.get("error") or not url:
                continue
            if not shallow_language_url(url, alt.get("hint")):
                continue
            pages.append({"url": url, "hint": alt.get("hint"), "scripts": alt.get("scripts") or {}})

        english = [page for page in pages if page["hint"] == "en" or path_of(page["url"]).strip("/") == "en"]
        regional = []
        for page in pages:
            if page["hint"] == "en" or path_of(page["url"]).strip("/") == "en":
                continue
            hint = page["hint"] if page["hint"] in LANG_SCRIPT else None
            script = LANG_SCRIPT.get(hint) if hint else dominant_script(page["scripts"])
            if script and script_of(page["scripts"], script) >= MINIMUM_GAIN:
                regional.append({**page, "script": script, "hint": hint or page["hint"]})
        if not english and script_of(home_scripts, dominant_script(home_scripts) or "") < MINIMUM_GAIN:
            english = [pages[0]]
        if not regional or not english:
            if row["profile"] in ("confirmed_second_version", "indic_text_on_homepage", "alternate_link_only"):
                skipped.append(
                    {
                        "name": label,
                        "url": row["url"],
                        "profile": row["profile"],
                        "reason": "no shallow English and regional homepage pair in the frame",
                    }
                )
            continue

        en_page = min(english, key=lambda page: sum((page["scripts"] or {}).values()))

        def explicit_lang(url: str) -> bool:
            token = path_of(url).strip("/").split("/")[0]
            return token in LANG_SCRIPT

        kept = []
        for other in regional:
            same_script = [page for page in regional if page["script"] == other["script"]]
            if any(explicit_lang(page["url"]) for page in same_script) and not explicit_lang(other["url"]):
                continue
            kept.append(other)
        regional = kept
        seen = set()
        for other in regional:
            if other["url"].rstrip("/") == en_page["url"].rstrip("/"):
                continue
            key = (en_page["url"], other["url"])
            if key in seen:
                continue
            seen.add(key)
            gain = script_of(other["scripts"], other["script"]) - script_of(en_page["scripts"], other["script"])
            if gain < MINIMUM_GAIN:
                skipped.append(
                    {
                        "name": label,
                        "url": row["url"],
                        "profile": row["profile"],
                        "reason": f"probe gain for {other['script']} was {gain}, below {MINIMUM_GAIN}",
                        "en_url": en_page["url"],
                        "other_url": other["url"],
                    }
                )
                continue
            pairs.append(
                {
                    "name": label,
                    "stratum": row["stratum"],
                    "profile": row["profile"],
                    "script": other["script"],
                    "hint": other["hint"],
                    "en_url": en_page["url"],
                    "other_url": other["url"],
                    "probe_gain": gain,
                }
            )
    return pairs, skipped


def audit(page, url: str) -> dict:
    response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_timeout(1500)
    text = page.locator("body").inner_text()
    return {
        "requested_url": url,
        "final_url": page.url,
        "http_status": response.status if response else None,
        "scripts": count_scripts(text),
        "violations": axe_violations(page),
        "error": None,
    }


def align(pair: dict, en: dict, other: dict) -> dict:
    script = pair["script"]
    gain = script_of(other["scripts"], script) - script_of(en["scripts"], script)
    comparable = gain >= MINIMUM_GAIN
    en_ids = {item["id"]: item for item in en["violations"]}
    other_ids = {item["id"]: item for item in other["violations"]}
    record = {
        **pair,
        "en_final_url": en["final_url"],
        "other_final_url": other["final_url"],
        "live_en_scripts": en["scripts"],
        "live_other_scripts": other["scripts"],
        "live_gain": gain,
        "comparable": comparable,
        "error": None,
    }
    if not comparable:
        record.update(
            {
                "reason": "The regional page did not gain enough of its script, so identical axe results are not scored.",
                "content_gap": True,
                "accessibility_scored": False,
                "accessibility_gap": None,
                "gigw": list(GIGW_CLAUSES),
            }
        )
        return record
    only_en = sorted(en_ids.keys() - other_ids.keys())
    only_other = sorted(other_ids.keys() - en_ids.keys())
    record.update(
        {
            "reason": "The regional page gained its script, so the two URLs are scored as one step in two languages.",
            "content_gap": False,
            "accessibility_scored": True,
            "accessibility_gap": bool(only_en or only_other),
            "accessibility_only_en": only_en,
            "accessibility_only_other": only_other,
            "shared_failures": sorted(en_ids.keys() & other_ids.keys()),
        }
    )
    return record


def main() -> None:
    if not AXE.exists():
        raise SystemExit(f"missing {AXE}; run npm install axe-core in the repo root")
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    pairs, skipped = choose_pairs(frame)
    print(f"auditing {len(pairs)} pairs; skipping {len(skipped)}", flush=True)

    results = []
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        context = browser.new_context(user_agent=UA, locale="en-IN", ignore_https_errors=True)
        page = context.new_page()
        for index, pair in enumerate(pairs, start=1):
            print(f"[{index}/{len(pairs)}] {pair['name']} {pair['hint']}", flush=True)
            try:
                try:
                    en = audit(page, pair["en_url"])
                except Exception:
                    parsed = urlparse(pair["en_url"])
                    if parsed.path.rstrip("/") != "/en":
                        raise
                    fallback = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
                    pair = {**pair, "en_url": fallback, "en_fallback": pair["en_url"]}
                    en = audit(page, fallback)
                other = audit(page, pair["other_url"])
                results.append(align(pair, en, other))
            except Exception as exc:
                results.append({**pair, "error": f"{type(exc).__name__}: {exc}", "comparable": None})
                page.close()
                page = context.new_page()
            row = results[-1]
            print(
                f"    comparable={row.get('comparable')} content_gap={row.get('content_gap')} "
                f"accessibility_gap={row.get('accessibility_gap')} {row.get('error') or ''}",
                flush=True,
            )
        browser.close()

    scored = [row for row in results if row.get("error") is None and row.get("comparable")]
    generated_at = datetime.now(timezone.utc).isoformat()
    source = "research/data/site_frame.json"
    report = {
        "generated_at": generated_at,
        "source": source,
        "provenance": provenance("research/align_frame.py", source, generated_at),
        "obligation": {
            "source": "GIGW 3.0",
            "url": GIGW_URL,
            "clauses": list(GIGW_CLAUSES),
        },
        "rule": f"Comparable when the regional page has at least {MINIMUM_GAIN} more characters of its script than the English page.",
        "not_included": "Tamil Nadu e-Sevai is in esevai_rev101_alignment.json. Sites with no shallow language URL are skipped.",
        "summary": {
            "pairs_attempted": len(results),
            "comparable": len(scored),
            "content_gaps": sum(1 for row in results if row.get("content_gap")),
            "accessibility_gaps": sum(1 for row in scored if row.get("accessibility_gap")),
            "failed": sum(1 for row in results if row.get("error")),
            "skipped": len(skipped),
        },
        "pairs": results,
        "skipped": skipped,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
