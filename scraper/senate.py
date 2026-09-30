"""Senators of the 20th Congress from senate.gov.ph."""

from __future__ import annotations

import argparse

from common import Browser, clean, dedupe, log, pick, record, save_snapshot, write_dataset
from roster import party_and_district, people_from_capture

URL = "https://senate.gov.ph/senators/20-congress-senators"
POSITION_RX = r"position|title|designation|role"


def scrape(browser: Browser) -> list[dict]:
    cap = browser.open(URL)
    save_snapshot("senate", cap)
    method, people = people_from_capture(cap)
    log(f"senate: {len(people)} people via {method}")

    records = []
    for p in people:
        f = p["fields"]
        party, _ = party_and_district(f)
        title = pick(f, POSITION_RX)
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
            profile_url=p["profile_url"],
            source="Senate of the Philippines",
            source_url=URL,
            details={"title": title, **{k: clean(v) for k, v in f.items() if k.startswith("line")}},
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
