"""Barangay officials from DILG regional offices (official).

DILG's national barangay directory doesn't answer from outside the
Philippines, but some regional offices publish their own lists — e.g. DILG
Region X's punong barangay directories for the 2023 term, as embedded Google
Sheets that their owner allows to be downloaded. Each page's sheets are
downloaded with Google's standard export (a refused download is skipped,
never worked around), parsed with the DILG sheet parser and stored in the
per-province barangay files the app loads on demand.

Barangay officials elected in October 2023 serve until the next barangay
elections, which RA 12326 (2026) moved to November 2028.

Add a region by adding its page to PAGES.
"""

from __future__ import annotations

import argparse

import barangay
import dilg_lgu
from common import Browser, log
from dilg_regions import sheet_ids

PAGES = {
    # region name: page publishing its barangay officials
    "Region X (Northern Mindanao)": "https://region10.dilg.gov.ph/punong-barangay-directories/",
}
BARANGAY_LEVELS = {"punong_barangay", "kagawad", "sk_chair", "sk_kagawad", "barangay_secretary", "barangay_treasurer"}
MIN_PER_PAGE = 100  # a region has hundreds of barangays


def source_label(region: str) -> str:
    return f"DILG {region} – Barangay Officials (2023 term)"


def parse(data: bytes, region: str, url: str, sheet_id: str) -> list[dict]:
    found = dilg_lgu.parse(data, source=source_label(region), source_url=url, defaults={"region": region})
    out = []
    for o in found:
        if o["level"] not in BARANGAY_LEVELS or not o["barangay"]:
            continue
        o["dataset"] = "barangay"
        o["details"]["published_via"] = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        o["details"]["term"] = "2023–2028"
        out.append(o)
    return out


def import_page(browser: Browser, region: str, url: str) -> list[dict]:
    ids = sheet_ids(browser, url)
    log(f"dilg-barangay: {region}: {len(ids)} sheet(s) on {url}")
    records = []
    for sid in ids:
        try:
            data = dilg_lgu.download(sid)
        except SystemExit as err:  # owner doesn't allow download: skip it
            log(f"dilg-barangay: sheet {sid} not downloadable ({err})")
            continue
        found = parse(data, region, url, sid)
        log(f"dilg-barangay: sheet {sid}: {len(found)} barangay officials")
        records += found
    return records


def run(browser: Browser | None = None) -> dict[str, int]:
    own = browser is None
    browser = browser or Browser()
    counts = {}
    try:
        for region, url in PAGES.items():
            try:
                records = import_page(browser, region, url)
            except Exception as err:  # noqa: BLE001 - one region must not stop the rest
                log(f"dilg-barangay: {region} FAILED: {err}")
                continue
            counts[region] = len(records)
            if len(records) >= MIN_PER_PAGE:
                barangay.flush(records)
            else:
                log(f"dilg-barangay: {region}: only {len(records)} records parsed; not saved")
    finally:
        if own:
            browser.close()
    log(f"dilg-barangay: {counts}")
    return counts


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == "__main__":
    main()
