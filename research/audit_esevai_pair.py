#!/usr/bin/env python3
"""axe-core on Tamil Nadu e-Sevai, English and Tamil sessions.

Community Certificate (REV-101). Tamil is the default page. English is the
"English Version" postback on the same URL. The form is behind sign-in, so
the checked pages are the portal and Pages/EsevaiServiceList.aspx.
Writes research/data/esevai_rev101.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from common import AXE, DATA, UA, WCAG_TAGS, axe_violations, count_scripts, provenance

OUT = DATA / "esevai_rev101.json"
HOME = "https://www.tnesevai.tn.gov.in/"
SERVICE_HREF = "a[href='Pages/EsevaiServiceList.aspx']"
SERVICE_CODE = "REV-101"
SERVICE_NAME = "Community Certificate"


def language_evidence(page) -> dict:
    text = page.locator("body").inner_text()
    return {
        "final_url": page.url,
        "title": page.title(),
        "html_lang": page.evaluate("() => document.documentElement.getAttribute('lang')"),
        "tamil_chars": count_scripts(text).get("Tamil", 0),
        "offers_english_switch": page.locator("a", has_text="English Version").count() > 0,
        "offers_tamil_switch": page.locator("a", has_text="தமிழ் வடிவம்").count() > 0,
        "names_service": SERVICE_CODE in text or SERVICE_NAME in text,
    }


def run_axe(page) -> dict:
    # Inject axe only after the language postback. add_init_script crashes Firefox here.
    violations = axe_violations(page)
    return {
        "violation_count": sum(item["nodes"] for item in violations),
        "rule_count": len(violations),
        "violations": violations,
        "error": None,
    }


def settle(page) -> None:
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)


def open_portal(page, language: str) -> None:
    page.goto(HOME, wait_until="domcontentloaded", timeout=45_000)
    settle(page)
    if language == "en":
        # Playwright's click waits for a navigation this postback does not
        # finish. Invoke the control and wait until the Tamil switch is present.
        page.evaluate("() => document.getElementById('lnkLanguageChange').click()")
        page.wait_for_function(
            "() => document.body && document.body.innerText.includes('தமிழ் வடிவம்')",
            timeout=20_000,
        )
        page.wait_for_timeout(1500)
    evidence = language_evidence(page)
    if language == "ta" and not evidence["offers_english_switch"]:
        raise RuntimeError("Tamil portal entry did not show an English Version switch")
    if language == "en" and not evidence["offers_tamil_switch"]:
        raise RuntimeError("English Version postback did not switch the portal entry")


def open_service_list(page) -> None:
    page.locator(SERVICE_HREF).first.click()
    page.wait_for_url("**/EsevaiServiceList.aspx", timeout=45_000)
    settle(page)
    if not language_evidence(page)["names_service"]:
        raise RuntimeError(f"service list did not name {SERVICE_CODE}")


def snapshot(page) -> dict:
    evidence = language_evidence(page)
    audit = run_axe(page)
    return {**evidence, **audit}


def compare(en: dict, ta: dict) -> dict:
    en_rules = {item["id"]: item for item in en["violations"]}
    ta_rules = {item["id"]: item for item in ta["violations"]}
    both_ids = sorted(en_rules.keys() & ta_rules.keys())
    only_en = sorted(en_rules.keys() - ta_rules.keys())
    only_ta = sorted(ta_rules.keys() - en_rules.keys())

    def side(rule_id: str, rules: dict) -> dict:
        item = rules[rule_id]
        return {
            "id": rule_id,
            "impact": item["impact"],
            "help": item["help"],
            "wcag": item["wcag"],
            "nodes": item["nodes"],
        }

    return {
        "nodes_en": en["violation_count"],
        "nodes_ta": ta["violation_count"],
        "rules_en": en["rule_count"],
        "rules_ta": ta["rule_count"],
        "tamil_chars_en": en["tamil_chars"],
        "tamil_chars_ta": ta["tamil_chars"],
        "both": [
            {
                "id": rule_id,
                "help": en_rules[rule_id]["help"],
                "wcag": en_rules[rule_id]["wcag"],
                "nodes_en": en_rules[rule_id]["nodes"],
                "nodes_ta": ta_rules[rule_id]["nodes"],
            }
            for rule_id in both_ids
        ],
        "only_en": [side(rule_id, en_rules) for rule_id in only_en],
        "only_ta": [side(rule_id, ta_rules) for rule_id in only_ta],
    }


def audit_language(browser, language: str) -> dict:
    # bypass_csp crashes Firefox on this site's language postback.
    # axe is injected with add_script_tag after the page has settled.
    context = browser.new_context(
        user_agent=UA,
        locale="en-IN",
        ignore_https_errors=True,
    )
    page = context.new_page()
    try:
        open_portal(page, language)
        portal = snapshot(page)
        open_service_list(page)
        service_list = snapshot(page)
        return {"portal_entry": portal, "service_list": service_list, "error": None}
    except Exception as exc:
        return {
            "portal_entry": None,
            "service_list": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        context.close()


def main() -> None:
    if not AXE.exists():
        raise SystemExit(f"missing {AXE}; run npm install axe-core in the repo root")

    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        ta = audit_language(browser, "ta")
        en = audit_language(browser, "en")
        browser.close()

    comparison = {}
    if en["error"] is None and ta["error"] is None:
        comparison = {
            "portal_entry": compare(en["portal_entry"], ta["portal_entry"]),
            "service_list": compare(en["service_list"], ta["service_list"]),
        }

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "summary": {
            "generated_at": generated_at,
            "provenance": provenance("research/audit_esevai_pair.py", HOME, generated_at),
            "engine": "axe-core",
            "tags": WCAG_TAGS,
            "service": SERVICE_NAME,
            "service_code": SERVICE_CODE,
            "portal": HOME,
            "language_mechanism": "ASP.NET postback on one URL (English Version / தமிழ் வடிவம்), not two URLs",
            "application_form": "behind sign-in; not audited",
            "compared_pages": ["portal_entry", "service_list"],
            "en_error": en["error"],
            "ta_error": ta["error"],
        },
        "en": en,
        "ta": ta,
        "comparison": comparison,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "comparison": comparison}, indent=2, ensure_ascii=False))
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
