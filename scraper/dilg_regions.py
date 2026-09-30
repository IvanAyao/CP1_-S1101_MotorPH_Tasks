"""Elected local officials 2025-2028 from DILG regional offices (official).

Some DILG regional sites publish their region's list of local officials on
a public page that embeds a Google Sheet. We open each page, find the
spreadsheets it embeds or links to, and download them with Google's
standard export, which the sheet's owner allows (a refused download is
skipped, never worked around). Pages behind a verification check are
skipped too.

Add a region by adding its page to REGION_PAGES.
"""

from __future__ import annotations

import argparse
import re

from common import Browser, log
import dilg_lgu

REGION_PAGES = {
    # region name: page that publishes the 2025-2028 local officials list
    "Region X (Northern Mindanao)": "https://region10.dilg.gov.ph/local-officials-for-the-term-2025-2028/",
}
SHEET_ID = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{25,})")
MIN_PER_REGION = 200  # a region has dozens of LGUs, each with 10+ elective posts


def source_label(region: str) -> str:
    return f"DILG {region} – Local Officials 2025–2028"


def sheet_ids(browser: Browser, url: str) -> list[str]:
    cap = browser.open(url)
    urls = browser.page.evaluate("""() => [
        ...[...document.querySelectorAll('iframe[src]')].map(f => f.src),
        ...[...document.querySelectorAll('a[href]')].map(a => a.href),
    ]""")
    ids = []
    for u in urls + [cap.html]:
        for m in SHEET_ID.finditer(u):
            if m.group(1) not in ids:
                ids.append(m.group(1))
    return ids


def import_region(browser: Browser, region: str, url: str) -> list[dict]:
    ids = sheet_ids(browser, url)
    log(f"dilg-region: {region}: {len(ids)} sheet(s) on {url}: {ids}")
    officials = []
    for sid in ids:
        try:
            data = dilg_lgu.download(sid)
        except SystemExit as err:  # owner doesn't allow download: skip it
            log(f"dilg-region: {region}: sheet {sid} not downloadable ({err})")
            continue
        found = dilg_lgu.parse(data, source=source_label(region), source_url=url,
                               defaults={"region": region})
        for o in found:
            o["details"]["published_via"] = f"https://docs.google.com/spreadsheets/d/{sid}"
        officials += found
    return officials


def run(browser: Browser | None = None) -> dict[str, int]:
    own = browser is None
    browser = browser or Browser()
    counts = {}
    try:
        for region, url in REGION_PAGES.items():
            try:
                officials = import_region(browser, region, url)
            except Exception as err:  # noqa: BLE001 - one region must not stop the rest
                log(f"dilg-region: {region} FAILED: {err}")
                continue
            counts[region] = len(officials)
            if len(officials) >= MIN_PER_REGION:
                dilg_lgu.merge_into_lgu(officials, source=source_label(region), source_url=url,
                                        min_count=MIN_PER_REGION)
            else:
                log(f"dilg-region: {region}: only {len(officials)} officials parsed; not merged")
    finally:
        if own:
            browser.close()
    log(f"dilg-region: {counts}")
    return counts


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == "__main__":
    main()
