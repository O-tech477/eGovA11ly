#!/usr/bin/env python3
"""Harvest igod.gov.in into research/data/site_frame.json.

State portals (one per state/UT page) and the first page of union ministries.
Each row is the homepage plus at most four same-site language links.
No axe run. Source URL is stored on the file.
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urljoin, urlparse

from common import DATA, count_scripts, provenance
IGOD = "https://igod.gov.in"
UA = (
    "eGovA11yResearch/0.1 "
    "(academic accessibility study; homepage language inventory; "
    "+https://igod.gov.in source frame)"
)

# Directory strata harvested in this pass. Deferred strata stay listed so the
# sample is not quietly widened later.
ACTIVE_STRATA = ("union_ministry", "state_portal")

LANGUAGE_LABELS = {
    "english": "en",
    "hindi": "hi",
    "हिंदी": "hi",
    "हिन्दी": "hi",
    "tamil": "ta",
    "தமிழ்": "ta",
    "telugu": "te",
    "తెలుగు": "te",
    "kannada": "kn",
    "ಕನ್ನಡ": "kn",
    "malayalam": "ml",
    "മലയാളം": "ml",
    "marathi": "mr",
    "मराठी": "mr",
    "bengali": "bn",
    "bangla": "bn",
    "বাংলা": "bn",
    "gujarati": "gu",
    "ગુજરાતી": "gu",
    "punjabi": "pa",
    "ਪੰਜਾਬੀ": "pa",
    "odia": "or",
    "oriya": "or",
    "ଓଡ଼ିଆ": "or",
    "assamese": "as",
    "অসমীয়া": "as",
    "urdu": "ur",
    "اردو": "ur",
    "konkani": "kok",
    "sanskrit": "sa",
}

PATH_LANG = {
    "en", "hi", "ta", "te", "kn", "ml", "mr", "bn", "gu", "pa", "or", "od",
    "as", "ur", "kok", "mni", "sa", "ne", "doi", "mai", "sat", "sd",
}

SCRIPT_TO_LIKELY = {
    "Devanagari": "hi",
    "Bengali": "bn",
    "Gurmukhi": "pa",
    "Gujarati": "gu",
    "Odia": "or",
    "Tamil": "ta",
    "Telugu": "te",
    "Kannada": "kn",
    "Malayalam": "ml",
    "Arabic": "ur",
}


@dataclass
class Org:
    stratum: str
    name: str
    url: str | None
    state: str | None
    igod_detail: str | None
    source_page: str


@dataclass
class FetchResult:
    requested_url: str
    final_url: str | None = None
    status: int | None = None
    error: str | None = None
    html_lang: str | None = None
    hreflang: list[dict] = field(default_factory=list)
    scripts: dict = field(default_factory=dict)
    tls_unverified: bool = False
    content_type: str | None = None


def _opener(jar: CookieJar | None, unverified: bool = False) -> urllib.request.OpenerDirector:
    handlers: list = []
    if jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(jar))
    if unverified:
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    return urllib.request.build_opener(*handlers)


def http_get(
    url: str,
    *,
    jar: CookieJar | None = None,
    referer: str | None = None,
    ajax: bool = False,
    timeout: int = 20,
    max_bytes: int = 600_000,
    unverified: bool = False,
) -> tuple[int, str, str, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    if referer:
        req.add_header("Referer", referer)
    if ajax:
        req.add_header("X-Requested-With", "XMLHttpRequest")
    opener = _opener(jar, unverified=unverified)
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes)
        charset = resp.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return resp.status, resp.geturl(), text, resp.headers.get("Content-Type")


def igod_get(url: str, jar: CookieJar, referer: str | None = None, ajax: bool = False) -> str:
    _status, _final, text, _ctype = http_get(url, jar=jar, referer=referer, ajax=ajax, timeout=30)
    return text


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_org_rows(html: str, *, stratum: str, source_page: str, state: str | None) -> list[Org]:
    rows: list[Org] = []
    parts = re.split(r'<div class="search-row\b[^"]*">', html)
    for part in parts[1:]:
        title = re.search(
            r'<a href="(https?://[^"]+)" class="search-title"[^>]*>(.*?)</a>',
            part,
            re.S,
        )
        detail = re.search(
            r'href="(https://igod\.gov\.in/[^"]*?/organization/[^"]+)"',
            part,
        )
        name = _clean(title.group(2)) if title else ""
        url = title.group(1).strip() if title else None
        if url and urlparse(url).netloc.endswith("igod.gov.in"):
            url = None
        if not name and not url:
            continue
        rows.append(
            Org(
                stratum=stratum,
                name=name or "(unnamed)",
                url=url,
                state=state,
                igod_detail=detail.group(1) if detail else None,
                source_page=source_page,
            )
        )
    return rows


def parse_listing_meta(html: str) -> dict:
    def grab(name: str, default: str) -> int:
        m = re.search(rf"var {name}\s*=\s*'(\d+)'", html)
        return int(m.group(1)) if m else int(default)

    more = re.search(
        r"organizations_list_more/'\+start\+'/'\+limit",
        html,
    )
    prefix = None
    built = re.search(
        r'''url:\s*"([^"]+index\.php)"\+'/'\+'([^']+)'\+'/'\+'([^']+)'\+'/'\+'organizations_list_more/' ''',
        html,
    )
    if built:
        prefix = f"{built.group(1)}/{built.group(2)}/{built.group(3)}/organizations_list_more"
    elif more:
        prefix = None
    return {
        "count": grab("count", "0"),
        "items_on_first_page": grab("items_on_first_page", "25"),
        "more_prefix": prefix,
    }


def harvest_listing(jar: CookieJar, url: str, stratum: str, state: str | None = None) -> list[Org]:
    html = igod_get(url, jar)
    rows = parse_org_rows(html, stratum=stratum, source_page=url, state=state)
    meta = parse_listing_meta(html)
    remaining = meta["count"] - meta["items_on_first_page"]
    if remaining > 0 and meta["more_prefix"]:
        time.sleep(0.4)
        more_url = f"{meta['more_prefix']}/{meta['items_on_first_page']}/{remaining}"
        more_html = igod_get(more_url, jar, referer=url, ajax=True)
        if "search-row" not in more_html:
            raise RuntimeError(f"pagination failed for {url}: {more_url}")
        rows.extend(parse_org_rows(more_html, stratum=stratum, source_page=more_url, state=state))
    # Directory pages can repeat a site; keep the first sighting.
    seen: set[tuple] = set()
    unique: list[Org] = []
    for row in rows:
        key = (row.stratum, row.state, (row.url or "").rstrip("/").lower(), row.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def harvest_state_portals(jar: CookieJar) -> list[Org]:
    states_html = igod_get(f"{IGOD}/index.php/sg/states", jar)
    states = re.findall(
        r'href="(https://igod\.gov\.in/index\.php/sg/[A-Z]{2}/categories)"[^>]*>(.*?)</a>',
        states_html,
        re.S,
    )
    portals: list[Org] = []
    for url, raw_name in states:
        state = _clean(raw_name)
        time.sleep(0.35)
        html = igod_get(url, jar, referer=f"{IGOD}/index.php/sg/states")
        block = re.search(r"<h3>\s*State Portal\s*</h3>(.*?)(?:<h3>|</div>\s*</div>)", html, re.S)
        chunk = block.group(1) if block else ""
        found = parse_org_rows(chunk, stratum="state_portal", source_page=url, state=state)
        if not found:
            link = re.search(
                r'<a href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                chunk,
                re.S,
            )
            if link and not urlparse(link.group(1)).netloc.endswith("igod.gov.in"):
                found = [
                    Org(
                        stratum="state_portal",
                        name=_clean(link.group(2)) or f"Official portal of {state}",
                        url=link.group(1).strip(),
                        state=state,
                        igod_detail=None,
                        source_page=url,
                    )
                ]
        portals.extend(found)
        print(f"  state portal {state}: {len(found)}", flush=True)
    return portals


class _LangExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_lang: str | None = None
        self.hreflang: list[dict] = []
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._buf: list[str] = []
        self.text_parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "html" and not self.html_lang:
            self.html_lang = ad.get("lang") or ad.get("xml:lang") or None
        if tag == "link" and "alternate" in ad.get("rel", "").lower() and ad.get("hreflang"):
            self.hreflang.append({"hreflang": ad.get("hreflang", ""), "href": ad.get("href", "")})
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag == "a" and ad.get("href"):
            self._href = ad["href"]
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._buf)))
            self._href = None
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._href is not None:
            self._buf.append(data)
        if data.strip():
            self.text_parts.append(data)


def norm_lang(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip().lower().replace("_", "-")
    token = token.split("-")[0]
    if token == "od":
        return "or"
    if re.fullmatch(r"[a-z]{2,3}", token):
        return token
    return None


def language_hint(href: str, anchor_text: str) -> str | None:
    text = anchor_text.strip().lower()
    if text in LANGUAGE_LABELS:
        return LANGUAGE_LABELS[text]
    # "Hindi version", "Read in Tamil"
    for label, code in LANGUAGE_LABELS.items():
        if label.isascii() and re.search(rf"\b{re.escape(label)}\b", text):
            return code
    path = urlparse(href).path.lower()
    parts = [p for p in path.split("/") if p]
    for part in parts:
        if part in PATH_LANG:
            return "or" if part == "od" else part
    query = urlparse(href).query.lower()
    m = re.search(r"(?:^|&)(?:lang|language)=([a-z]{2,3})\b", query)
    if m and m.group(1) in PATH_LANG:
        code = m.group(1)
        return "or" if code == "od" else code
    return None


def same_site(a: str, b: str) -> bool:
    ha = urlparse(a).hostname or ""
    hb = urlparse(b).hostname or ""
    if ha.startswith("www."):
        ha = ha[4:]
    if hb.startswith("www."):
        hb = hb[4:]
    return bool(ha) and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha))


def fetch_page(url: str) -> FetchResult:
    result = FetchResult(requested_url=url)
    try:
        try:
            status, final, html, ctype = http_get(url, timeout=18, max_bytes=500_000)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if "CERTIFICATE" in str(reason).upper() or "SSL" in str(reason).upper():
                status, final, html, ctype = http_get(url, timeout=18, max_bytes=500_000, unverified=True)
                result.tls_unverified = True
            else:
                raise
        result.status = status
        result.final_url = final
        result.content_type = ctype
        if ctype and "html" not in ctype.lower() and "<html" not in html[:500].lower():
            return result
        parser = _LangExtractor()
        parser.feed(html)
        result.html_lang = norm_lang(parser.html_lang)
        result.hreflang = parser.hreflang
        result.scripts = count_scripts(" ".join(parser.text_parts)[:200_000], minimum=15)
        result._anchors = parser.anchors  # type: ignore[attr-defined]
        result._html_ok = True  # type: ignore[attr-defined]
    except Exception as exc:  # network failures are data, not crashes
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def candidate_alternates(page_url: str, anchors: list[tuple[str, str]], hreflang: list[dict]) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()

    def add(href: str, hint: str | None, via: str) -> None:
        absolute = urljoin(page_url, href)
        if not absolute.startswith("http"):
            return
        if not same_site(page_url, absolute):
            return
        key = absolute.split("#")[0].rstrip("/")
        base = page_url.split("#")[0].rstrip("/")
        if key == base or key in seen:
            return
        seen.add(key)
        found.append({"url": absolute, "hint": hint, "via": via})

    for item in hreflang:
        add(item.get("href", ""), norm_lang(item.get("hreflang")), "hreflang")
    for href, text in anchors:
        hint = language_hint(href, text)
        if hint:
            add(href, hint, "anchor")
    return found[:8]


def inventory(org: Org) -> dict:
    record = asdict(org)
    record["probed_at"] = datetime.now(timezone.utc).isoformat()
    if not org.url:
        record["profile"] = "no_url_in_directory"
        record["homepage"] = None
        record["alternates"] = []
        return record

    home = fetch_page(org.url)
    anchors = getattr(home, "_anchors", [])
    hreflang = home.hreflang
    cands = []
    if home.status and home.error is None:
        cands = candidate_alternates(home.final_url or org.url, anchors, hreflang)

    alternates = []
    for cand in cands[:4]:
        alt = fetch_page(cand["url"])
        alternates.append(
            {
                "url": cand["url"],
                "hint": cand["hint"],
                "via": cand["via"],
                "status": alt.status,
                "final_url": alt.final_url,
                "html_lang": alt.html_lang,
                "scripts": alt.scripts,
                "error": alt.error,
            }
        )

    codes = set()
    if home.html_lang:
        codes.add(home.html_lang)
    for name in home.scripts:
        codes.add(SCRIPT_TO_LIKELY[name])
    confirmed = []
    for alt in alternates:
        if alt["status"] and alt["status"] < 400 and not alt["error"]:
            confirmed.append(alt)
            if alt["html_lang"]:
                codes.add(alt["html_lang"])
            if alt["hint"]:
                codes.add(alt["hint"])
            for name in alt["scripts"]:
                codes.add(SCRIPT_TO_LIKELY[name])

    if home.error or not home.status:
        profile = "unreachable"
    elif len(codes) >= 2 and confirmed:
        profile = "confirmed_second_version"
    elif len(codes) >= 2 and home.scripts:
        profile = "indic_text_on_homepage"
    elif cands:
        profile = "alternate_link_only"
    else:
        profile = "no_alternate_detected"

    home_out = {
        "requested_url": home.requested_url,
        "final_url": home.final_url,
        "status": home.status,
        "error": home.error,
        "html_lang": home.html_lang,
        "hreflang": home.hreflang,
        "scripts": home.scripts,
        "tls_unverified": home.tls_unverified,
    }
    record.update(
        {
            "homepage": home_out,
            "language_codes": sorted(codes),
            "alternates": alternates,
            "profile": profile,
        }
    )
    return record


def build() -> dict:
    jar = CookieJar()
    print("harvesting union ministries", flush=True)
    ministries = harvest_listing(
        jar,
        f"{IGOD}/index.php/ug/E002/organizations",
        stratum="union_ministry",
    )
    print(f"  ministries: {len(ministries)} ({sum(1 for m in ministries if m.url)} with a URL)", flush=True)
    print("harvesting state portals", flush=True)
    portals = harvest_state_portals(jar)
    orgs = ministries + portals

    print(f"probing {sum(1 for o in orgs if o.url)} homepages", flush=True)
    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(inventory, org): org for org in orgs}
        done = 0
        for fut in as_completed(futures):
            rec = fut.result()
            records.append(rec)
            done += 1
            if done % 10 == 0 or done == len(orgs):
                print(f"  probed {done}/{len(orgs)}", flush=True)

    records.sort(key=lambda r: (r["stratum"], r.get("state") or "", r["name"]))
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "generated_at": generated_at,
        "source": IGOD,
        "provenance": provenance("research/build_frame.py", IGOD, generated_at),
        "strata_harvested": list(ACTIVE_STRATA),
        "strata_deferred": [
            "union_scheme",
            "state_department",
            "district",
            "judiciary",
            "legislature",
        ],
        "counts": {
            "rows": len(records),
            "with_url": sum(1 for r in records if r.get("url")),
            "by_stratum": {},
            "by_profile": {},
        },
        "method": {
            "frame": "igod.gov.in category listings, session-backed organizations_list_more pagination",
            "probe": "one homepage GET plus at most four same-site language alternates",
            "confirmed_second_version": "homepage signals plus an alternate URL that returned a page show two language codes",
            "not_done": "no WCAG/axe/LLM audit; districts and departments not harvested",
        },
    }
    for rec in records:
        summary["counts"]["by_stratum"][rec["stratum"]] = summary["counts"]["by_stratum"].get(rec["stratum"], 0) + 1
        summary["counts"]["by_profile"][rec["profile"]] = summary["counts"]["by_profile"].get(rec["profile"], 0) + 1

    DATA.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "rows": records}
    out = DATA / "site_frame.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {out}", flush=True)
    return payload


if __name__ == "__main__":
    build()
