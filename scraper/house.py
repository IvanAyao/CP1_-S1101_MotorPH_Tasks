"""Members of the House of Representatives from congress.gov.ph."""

from __future__ import annotations

import argparse
import re

from common import Browser, clean, dedupe, log, pick, record, save_snapshot, write_dataset
from roster import party_and_district, people_from_capture

URL = "https://www.congress.gov.ph/house-members"
MAX_PAGES = 60


def province_of(district: str) -> str:
    """'Cebu, 3rd District' / 'Lone District of Aklan' -> 'Cebu' / 'Aklan'."""
    d = clean(district)
    m = re.search(r"lone district of (.+)", d, re.I)
    if m:
        return m.group(1).strip()
    d = re.sub(r"\b(\d+(st|nd|rd|th)|lone|legislative)\b.*?district\b", "", d, flags=re.I)
    return d.strip(" ,-–") if d.strip(" ,-–") != district else ""


def scrape(browser: Browser) -> list[dict]:
    cap = browser.open(URL)
    save_snapshot("house", cap)
    all_people = []
    method, people = people_from_capture(cap)
    all_people += people
    log(f"house: page 1 -> {len(people)} via {method}")

    for page_no in range(2, MAX_PAGES + 1):
        if not browser.click_next():
            break
        browser.scroll_to_bottom()
        cap = browser.capture()
        method, people = people_from_capture(cap)
        new = [p for p in people if p["name"] not in {x["name"] for x in all_people}]
        log(f"house: page {page_no} -> {len(people)} ({len(new)} new) via {method}")
        if not new:
            break
        all_people += new

    records = []
    for p in all_people:
        f = p["fields"]
        party, district = party_and_district(f)
        is_partylist = bool(re.search(r"party[- ]?list", " ".join(f.values()), re.I))
        records.append(record(
            name=p["name"],
            position="Party-list Representative" if is_partylist else "District Representative",
            level="house",
            party=party,
            district=district or ("Party-list" if is_partylist else ""),
            province="" if is_partylist else province_of(district),
            region=pick(f, r"region"),
            photo=p["photo"],
            profile_url=p["profile_url"],
            source="House of Representatives",
            source_url=URL,
            details={k: v for k, v in f.items() if len(clean(v)) < 200},
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
    # 20th Congress: ~254 district + up to 63 party-list seats.
    write_dataset("house", records, URL, min_count=250, max_count=340)


if __name__ == "__main__":
    main()
