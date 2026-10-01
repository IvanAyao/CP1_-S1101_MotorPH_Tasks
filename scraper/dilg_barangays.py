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
import re

import barangay
import dilg_lgu
from common import Browser, log
from dilg_regions import SHEET_ID

PAGES = {
    # page publishing barangay officials: region it covers
    "https://region10.dilg.gov.ph/punong-barangay-directories/": "Region X (Northern Mindanao)",
    # DILG Aurora's directory: a filtered copy of DILG Central Office's
    # public barangay officials file (Aurora province).
    "https://www.riseaurora.region3.dilg.gov.ph/lgus/lgus": "Region III (Central Luzon)",
}
DRIVE_FILE = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)([A-Za-z0-9_-]{25,})")
# The barangay council (Sangguniang Barangay): the punong barangay, seven
# kagawads and the SK chairperson. SK members and the appointed secretary
# and treasurer are left out to keep ~42,000 barangays manageable.
BARANGAY_LEVELS = {"punong_barangay", "kagawad", "sk_chair"}
ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V", "6": "VI", "7": "VII", "8": "VIII",
         "9": "IX", "10": "X", "11": "XI", "12": "XII", "13": "XIII"}
REGION_NAMES = {
    "NCR": "NCR (Metro Manila)", "CAR": "CAR (Cordillera)", "I": "Region I (Ilocos Region)",
    "II": "Region II (Cagayan Valley)", "III": "Region III (Central Luzon)", "IVA": "Region IV-A (CALABARZON)",
    "IVB": "MIMAROPA Region", "V": "Region V (Bicol Region)", "VI": "Region VI (Western Visayas)",
    "NIR": "Negros Island Region (NIR)", "VII": "Region VII (Central Visayas)", "VIII": "Region VIII (Eastern Visayas)",
    "IX": "Region IX (Zamboanga Peninsula)", "X": "Region X (Northern Mindanao)", "XI": "Region XI (Davao Region)",
    "XII": "Region XII (SOCCSKSARGEN)", "XIII": "Region XIII (Caraga)", "BARMM": "BARMM (Bangsamoro)",
}


def region_name(text: str) -> str:
    """'REGION 3', 'Region III', 'REGION IV-A', 'MIMAROPA' -> the app's region names."""
    t = re.sub(r"[\s-]+", "", (text or "").upper()).replace("REGION", "")
    t = re.sub(r"\(.*", "", t)
    if t in {"MIMAROPA", "IVB"}:
        t = "IVB"
    elif t in {"CALABARZON", "IVA", "4A"}:
        t = "IVA"
    elif t in {"ARMM", "BARMM", "BANGSAMORO"}:
        t = "BARMM"
    elif t in {"CARAGA"}:
        t = "XIII"
    t = ROMAN.get(t, t)
    return REGION_NAMES.get(t, text)
MIN_PER_PAGE = 100  # a region has hundreds of barangays


def source_label(region: str) -> str:
    return f"DILG {region} – Barangay Officials (2023 term)"


def parse(data: bytes, region: str | None, url: str, sheet_id: str = "", *, source: str | None = None) -> list[dict]:
    """Barangay council members from a DILG sheet. With no `region`, each
    row's own region column is used (e.g. DILG's national file)."""
    found = dilg_lgu.parse(data, source=source or source_label(region or "national"), source_url=url,
                           defaults={"region": region or ""})
    out = []
    for o in found:
        if not o["barangay"] or o["level"] not in BARANGAY_LEVELS:
            continue
        o["dataset"] = "barangay"
        o["region"] = region or region_name(o["region"])  # sheets say e.g. "Region 10"
        o["contact"] = ""  # personal numbers and emails aren't needed to compare officials
        if sheet_id:
            o["details"]["published_via"] = f"https://drive.google.com/open?id={sheet_id}"
        o["details"]["term_years"] = "2023–2028"
        out.append(o)
    return out


def file_ids(browser: Browser, url: str) -> list[str]:
    """Google Sheets and Drive files a page embeds or links to."""
    cap = browser.open(url)
    urls = browser.page.evaluate("""() => [
        ...[...document.querySelectorAll('iframe[src]')].map(f => f.src),
        ...[...document.querySelectorAll('a[href]')].map(a => a.href),
    ]""")
    ids = []
    for u in urls + [cap.html]:
        for rx in (SHEET_ID, DRIVE_FILE):
            for m in rx.finditer(u):
                if m.group(1) not in ids:
                    ids.append(m.group(1))
    return ids


def import_page(browser: Browser, region: str, url: str) -> list[dict]:
    ids = file_ids(browser, url)
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
        for url, region in PAGES.items():
            try:
                records = import_page(browser, region, url)
            except Exception as err:  # noqa: BLE001 - one region must not stop the rest
                log(f"dilg-barangay: {region} FAILED: {err}")
                continue
            counts[url] = len(records)
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
