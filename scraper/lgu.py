"""LGU directory (cities/municipalities, local chief executives) from PSA RSSO NCR."""

from __future__ import annotations

import argparse

from bs4 import BeautifulSoup

from common import (Browser, all_table_rows, clean, dedupe, log, pick, save_snapshot,
                    slug, write_dataset)
from officials import rows_to_officials

URL = "https://rssoncr.psa.gov.ph/lgu-directory"
SOURCE = "PSA RSSO NCR – LGU Directory"
MAX_PAGES = 50


def scrape(browser: Browser) -> tuple[list[dict], list[dict]]:
    cap = browser.open(URL)
    save_snapshot("lgu", cap)
    rows: list[dict] = []
    seen_pages = set()
    for page_no in range(1, MAX_PAGES + 1):
        page_rows = [r for t in all_table_rows(BeautifulSoup(cap.html, "lxml")) for r in t]
        sig = tuple(sorted(map(str, page_rows)))[:5]
        if sig in seen_pages:
            break
        seen_pages.add(sig)
        log(f"lgu: page {page_no} -> {len(page_rows)} rows")
        rows += page_rows
        if not browser.click_next():
            break
        cap = browser.capture()
    return from_rows(rows)


def from_rows(rows: list[dict], source: str = SOURCE) -> tuple[list[dict], list[dict]]:
    """Directory table rows -> (LGU list, official records)."""
    lgus = []
    for r in rows:
        name = pick(r, r"^(lgu|city|municipality|name)")
        if not name:
            continue
        lgus.append({
            "id": slug(name),
            "name": name,
            "region": pick(r, r"region") or "NCR",
            "province": pick(r, r"province|district"),
            "address": pick(r, r"address"),
            "contact": pick(r, r"contact|tel|phone|mobile"),
            "email": pick(r, r"email"),
            "website": pick(r, r"website|url|site"),
            "details": {k: clean(v) for k, v in r.items() if not k.startswith("__")},
        })
    officials = rows_to_officials(rows, source=source, source_url=URL, defaults={"region": "NCR"})
    return dedupe(lgus, key=lambda x: x["id"]), dedupe(officials)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    browser = Browser(headless=not args.headed)
    try:
        lgus, officials = scrape(browser)
    finally:
        browser.close()
    # NCR has 16 cities + 1 municipality (Pateros).
    write_dataset("lgu", officials, URL, min_count=10,
                  extra_meta={"lgus": lgus, "lgu_count": len(lgus)})


if __name__ == "__main__":
    main()
