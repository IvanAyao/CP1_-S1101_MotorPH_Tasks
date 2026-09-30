"""Senators of the 20th Congress from senate.gov.ph.

The page is a JavaScript app that loads its roster from the Senate's own API
(`/hq/senators/congress/<id>`). We read that JSON for names, positions and
biographies, and take photos and profile links from the rendered cards.
"""

from __future__ import annotations

import argparse
import re
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from common import (Browser, clean, dedupe, extract_cards, log, record, save_snapshot,
                    slug, write_dataset)
from roster import party_and_district, people_from_capture

URL = "https://senate.gov.ph/senators/20-congress-senators"
API_RX = re.compile(r"/senators/congress/\d+")
SKIP_DETAIL = re.compile(r"^(id|congress_ids|image_upload_id|flag|lis_code|biography|description|status|name|position)$")


def key(name: str) -> str:
    """Comparable form of a name: 'Paolo Benigno "Bam" Aquino IV' -> 'paolo-benigno-bam-aquino-iv'."""
    return slug(re.sub(r"[\"'“”.]", "", name))


def short_bio(html: str, limit: int = 700) -> str:
    text = clean(BeautifulSoup(html or "", "lxml").get_text(" "))
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0]
    return cut + "."


def from_api(cap) -> list[dict]:
    for url, doc in cap.json_docs:
        if API_RX.search(url) and isinstance(doc, dict) and isinstance(doc.get("senators"), list):
            return [s for s in doc["senators"] if (s.get("status") or "active").lower() == "active"]
    return []


def scrape(browser: Browser) -> list[dict]:
    cap = browser.open(URL)
    save_snapshot("senate", cap)
    soup = BeautifulSoup(cap.html, "lxml")

    # Photos and profile links from the rendered page, keyed by name.
    photos = {key(c.name): c.img for c in extract_cards(soup, cap.url) if c.img}
    profiles = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"/senator/([^/?#]+)", a["href"])
        if m:
            profiles[key(unquote(m.group(1)).replace("-", " "))] = urljoin(cap.url, a["href"])

    api = from_api(cap)
    records = []
    if api:
        log(f"senate: {len(api)} senators via API")
        for s in api:
            name = clean(s.get("name"))
            k = key(name)
            details = {kk: clean(v) for kk, v in s.items()
                       if not SKIP_DETAIL.match(kk) and isinstance(v, (str, int)) and clean(v) and len(clean(v)) < 200}
            bio = short_bio(s.get("biography") or s.get("description") or "")
            if bio:
                details["biography"] = bio
            role = clean(s.get("position"))
            records.append(record(
                name=name,
                position=f"Senator · {role}" if role and role.lower() != "senator" else "Senator",
                level="senate",
                party=clean(s.get("party") or s.get("political_party") or ""),
                district="Nationwide",
                photo=photos.get(k, ""),
                profile_url=profiles.get(k, ""),
                source="Senate of the Philippines",
                source_url=URL,
                details=details,
            ))
        return dedupe(records)

    # Fallback: no API seen, parse the rendered listing.
    method, people = people_from_capture(cap)
    log(f"senate: {len(people)} people via {method}")
    for p in people:
        f = p["fields"]
        party, _ = party_and_district(f)
        position = "Senator"
        lowered = " ".join(f.values()).lower()
        for label in ("Senate President Pro Tempore", "Senate President",
                      "Majority Leader", "Minority Leader"):
            if label.lower() in lowered:
                position = f"Senator · {label}"
                break
        records.append(record(
            name=p["name"],
            position=position,
            level="senate",
            party=party,
            district="Nationwide",
            photo=p["photo"],
            profile_url=p["profile_url"] or profiles.get(key(p["name"]), ""),
            source="Senate of the Philippines",
            source_url=URL,
            details={k: clean(v) for k, v in f.items() if k.startswith("line")},
        ))
    return dedupe(records)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    browser = Browser(headless=not args.headed)
    try:
        records = scrape(browser)
    finally:
        browser.close()
    write_dataset("senate", records, URL, min_count=20, max_count=26)


if __name__ == "__main__":
    main()
