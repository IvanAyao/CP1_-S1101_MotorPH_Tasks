"""Local officials elected in 2025, from OpenHalalan (public, ODbL).

OpenHalalan (https://github.com/RobertRLeung/OpenHalalan) is an open
dataset of every national and local election winner since 2001, built mainly
from COMELEC's published results. It covers governors, vice governors,
provincial board members, mayors, vice mayors and councilors nationwide
(barangay posts are not included). It is a public, non-government source and
is labelled as such; its licence (ODbL v1.0) requires attribution and that
derived data stays open.

These are 2025 election winners, not a live roster: an official may since
have died, resigned or been succeeded. So they only fill gaps. Official DILG
regional lists win for their whole region, and Wikipedia entries (which track
the current holder) win for the offices they cover.

The winners of earlier elections give each official's consecutive terms in
the same post, which shows who reaches the three-term limit in 2028.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

import common
from common import clean, dedupe, log, record, write_dataset
from dilg_lgu import tidy_case

REPO = "https://github.com/RobertRLeung/OpenHalalan"
URL = "https://raw.githubusercontent.com/RobertRLeung/OpenHalalan/main/data/output/NLE_Winners_2004-2025.csv"
SOURCE = "OpenHalalan – 2025 election winners (COMELEC results)"
YEAR = "2025"
MIN_RECORDS = 10_000  # about 17,500 local posts were filled in 2025

POSITIONS = {
    "GOVERNOR": ("governor", "Governor"),
    "VICE GOVERNOR": ("vice_governor", "Vice Governor"),
    "PROVINCIAL BOARD MEMBER": ("board_member", "Provincial Board Member"),
    "MAYOR": ("mayor", "Mayor"),
    "VICE MAYOR": ("vice_mayor", "Vice Mayor"),
    "COUNCILOR": ("councilor", "Councilor"),
}
REGIONS = {
    "NATIONAL CAPITAL REGION": "NCR (Metro Manila)",
    "CORDILLERA ADMINISTRATIVE REGION": "CAR (Cordillera)",
    "REGION I": "Region I (Ilocos Region)",
    "REGION II": "Region II (Cagayan Valley)",
    "REGION III": "Region III (Central Luzon)",
    "REGION IV A": "Region IV-A (CALABARZON)",
    "REGION IV B": "MIMAROPA Region",
    "REGION V": "Region V (Bicol Region)",
    "REGION VI": "Region VI (Western Visayas)",
    "NEGROS ISLAND REGION": "Negros Island Region (NIR)",
    "REGION VII": "Region VII (Central Visayas)",
    "REGION VIII": "Region VIII (Eastern Visayas)",
    "REGION IX": "Region IX (Zamboanga Peninsula)",
    "REGION X": "Region X (Northern Mindanao)",
    "REGION XI": "Region XI (Davao Region)",
    "REGION XII": "Region XII (SOCCSKSARGEN)",
    "REGION XIII": "Region XIII (Caraga)",
    "BARMM": "BARMM (Bangsamoro)",
}
# Names the dataset spells without Ñ or "City".
PLACE_FIX = {
    "LAS PINAS": "Las Piñas", "PARANAQUE": "Parañaque", "BINAN": "Biñan", "DASMARINAS": "Dasmariñas",
    "SANTO NINO": "Santo Niño", "PENARANDA": "Peñaranda", "PENABLANCA": "Peñablanca", "PINAN": "Piñan",
    "SPECIAL GEOGRAPHIC AREA": "Special Geographic Area (BARMM)", "TAWI TAWI": "Tawi-Tawi",
}
# Cities that Wikipedia lists without a province (their Wikipedia names).
CITY_PROVINCE = {
    "angeles": "pampanga", "baguio": "benguet", "butuan": "agusan del norte", "cagayan de oro": "misamis oriental",
    "cebu": "cebu", "cotabato": "maguindanao del norte", "dagupan": "pangasinan", "davao": "davao del sur",
    "general santos": "south cotabato", "iligan": "lanao del norte", "iloilo": "iloilo", "lapu lapu": "cebu",
    "lucena": "quezon", "mandaue": "cebu", "naga": "camarines sur", "olongapo": "zambales", "ormoc": "leyte",
    "puerto princesa": "palawan", "santiago": "isabela", "tacloban": "leyte", "zamboanga": "zamboanga del sur",
    "bacolod": "negros occidental", "isabela": "basilan",
}
METRO_MANILA = "metro manila"


def key(text: str) -> str:
    """Comparable place name: no accents, "City of"/"City", punctuation or case."""
    t = unicodedata.normalize("NFD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^city of |\bcity\b|\bmunicipality of\b", " ", t)
    return re.sub(r"[^a-z]+", " ", t).strip()


def province_key(province: str) -> str:
    k = key(province)
    return METRO_MANILA if k.startswith("ncr") or k == METRO_MANILA else k


def place_name(text: str, *, ncr: bool = False) -> str:
    raw = clean(text).upper()
    if ncr and raw == "QUEZON":
        return "Quezon City"
    return PLACE_FIX.get(raw) or tidy_case(raw)


def person_name(row: dict) -> str:
    first, middle, last = (tidy_case(clean(row.get(k, "")).upper()) for k in ("First Name", "Middle Name", "Last Name"))
    suffix = ""
    m = re.match(r"^(.*?)[ ,]+(JR|SR|II|III|IV)\.?$", last, re.I)
    if m:
        last, suffix = m.group(1), m.group(2)
        suffix = suffix.title() + "." if suffix.upper() in {"JR", "SR"} else suffix.upper()
    initial = f"{middle[0]}." if middle else ""
    return " ".join(p for p in (first, initial, last) if p) + (f" {suffix}" if suffix else "")


def load(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def same_person(a: dict, b: dict) -> bool:
    """Same last name (suffix included) and first name, and the middle names
    agree when both are known, so a father and son sharing a name (usually
    with different middle names) are not merged."""
    if a["Last Name"] != b["Last Name"] or a["First Name"] != b["First Name"]:
        return False
    return not (a["Middle Name"] and b["Middle Name"]) or a["Middle Name"] == b["Middle Name"]


def consecutive_terms(history: dict, row: dict) -> int:
    """Wins in the same post and place in 2025, 2022, 2019… without a break."""
    wins = history.get((row["Position"], row["Province"], row["City"], row["Last Name"]), [])
    years = {w["Year"] for w in wins if same_person(w, row)}
    n = 0
    for y in ("2025", "2022", "2019", "2016", "2013"):
        if y not in years:
            break
        n += 1
    return n


def officials(rows: list[dict]) -> list[dict]:
    history: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        history[(r["Position"], r["Province"], r["City"], r["Last Name"])].append(r)
    out = []
    for r in rows:
        if r["Year"] != YEAR or r["Position"] not in POSITIONS:
            continue
        level, label = POSITIONS[r["Position"]]
        ncr = r["Province"].startswith("NCR")
        terms = consecutive_terms(history, r)
        out.append(record(
            name=person_name(r), position=label, level=level, source=SOURCE, source_url=REPO,
            party="Independent" if clean(r.get("Party")) == "IND" else clean(r.get("Party")),
            region=REGIONS.get(r["Region"], tidy_case(r["Region"])),
            province="Metro Manila" if ncr else place_name(r["Province"]),
            lgu=place_name(r["City"], ncr=ncr) if r["City"] else "",
            details={"elected": YEAR, "term": str(terms), "full_name": tidy_case(r.get("Full Name", "").upper())},
        ))
    return dedupe(out)


def merge(found: list[dict]) -> dict:
    """Add winners for offices no better source covers; returns counts."""
    path = common.DATA_DIR / "lgu.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    existing = [r for r in doc.get("records", []) if r.get("source") != SOURCE]

    # Official DILG regional lists cover their whole region.
    official_regions = {key(r.get("region", "")) for r in existing
                        if r.get("source_type") == "official" and r.get("region")}
    # Other records (Wikipedia) cover their own office.
    covered: set[tuple] = set()
    for r in existing:
        prov = province_key(r.get("province", ""))
        lgu = key(r.get("lgu", ""))
        if not prov and lgu:
            prov = CITY_PROVINCE.get(lgu, "")
        covered.add((r["level"], prov, lgu))
        if lgu and not prov:
            covered.add((r["level"], "*", lgu))  # province unknown: match on city alone

    added, skipped_region, skipped_office = [], 0, 0
    for o in found:
        if key(o["region"]) in official_regions:
            skipped_region += 1
            continue
        prov, lgu = province_key(o["province"]), key(o["lgu"])
        if (o["level"], prov, lgu) in covered or (lgu and (o["level"], "*", lgu) in covered):
            skipped_office += 1
            continue
        added.append(o)
    # Term numbers for records from other sources (e.g. DILG lists), matched
    # by office and surname.
    terms = {}
    for o in found:
        terms[(o["level"], province_key(o["province"]), key(o["lgu"]), key(o["name"].split()[-1]))] = o["details"]["term"]
    for r in existing:
        if r.get("details", {}).get("term"):
            continue
        prov = province_key(r.get("province", "")) or CITY_PROVINCE.get(key(r.get("lgu", "")), "")
        words = [w for w in key(r["name"]).split() if w not in {"jr", "sr", "ii", "iii", "iv"}]
        t = terms.get((r["level"], prov, key(r.get("lgu", "")), words[-1] if words else ""))
        if t:
            r.setdefault("details", {})["term"] = t
            r["details"]["term_source"] = "OpenHalalan"
    merged = existing + added
    official_sources = sorted({r["source"] for r in merged if r.get("source_type") == "official"})
    write_dataset("lgu", merged, REPO, min_count=len(existing),
                  extra_meta={"method": "official+public" if official_sources else "public",
                              "source_label": " + ".join(official_sources + ["Wikipedia", "OpenHalalan"]),
                              "lgus": doc.get("lgus", []),
                              "openhalalan": {"source": SOURCE, "url": REPO, "license": "ODbL v1.0",
                                              "records": len(added), "year": YEAR}})
    counts = {"added": len(added), "in_official_regions": skipped_region, "covered_by_other_sources": skipped_office}
    log(f"openhalalan: {counts}")
    return counts


def run(data: bytes | None = None) -> dict:
    if data is None:
        req = urllib.request.Request(URL, headers={"User-Agent": "pili-ph-data (+https://github.com/IvanAyao/Pili_App_PH)"})
        with urllib.request.urlopen(req, timeout=120) as res:
            data = res.read()
    found = officials(load(data))
    if len(found) < MIN_RECORDS:
        raise SystemExit(f"openhalalan: only {len(found)} {YEAR} winners found; keeping previous data")
    return merge(found)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="use a downloaded NLE_Winners CSV")
    args = ap.parse_args()
    run(Path(args.file).read_bytes() if args.file else None)


if __name__ == "__main__":
    main()
