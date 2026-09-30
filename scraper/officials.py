"""Turn directory table rows into official records.

LGU and barangay directories come in two shapes:
  * "long": one row per official, with a position column
      | Barangay | Position | Name |
  * "wide": one row per LGU/barangay, one column per office
      | LGU | Mayor | Vice Mayor | Address |
Both are handled here.
"""

from __future__ import annotations

import re

from common import clean, looks_like_name, pick, record, strip_honorific

LEVEL_BY_POSITION = [
    (r"vice[\s_-]*gov", "vice_governor", "Vice Governor"),
    (r"governor|gobernador", "governor", "Governor"),
    (r"vice[\s_-]*mayor|bise[\s_-]*alkalde", "vice_mayor", "Vice Mayor"),
    (r"mayor|alkalde", "mayor", "Mayor"),
    (r"board[\s_-]*member|bokal|sp[\s_-]*member|panlalawigan", "board_member", "Provincial Board Member"),
    (r"\bsk\b|sangguniang[\s_-]*kabataan|youth", "sk_chair", "SK Chairperson"),
    (r"kagawad|sangguniang[\s_-]*barangay|barangay[\s_-]*member|sbm", "kagawad", "Barangay Kagawad"),
    (r"council|konsehal|sanggunian", "councilor", "Councilor"),
    (r"punong|chairman|chairperson|kapitan|captain|p\.?b\.?$", "punong_barangay", "Punong Barangay"),
    (r"secretary|kalihim", "barangay_secretary", "Barangay Secretary"),
    (r"treasurer|ingat", "barangay_treasurer", "Barangay Treasurer"),
]

CONTEXT_COLS = r"^(no|num|number|region|province|lgu|city|municipality|barangay|address|contact|tel|phone|email|district|zip|psgc|income|class|population)"


def classify(position: str) -> tuple[str, str]:
    p = position.lower()
    for rx, level, label in LEVEL_BY_POSITION:
        if re.search(rx, p):
            if level == "sk_chair" and "kagawad" in p:
                return "sk_kagawad", "SK Kagawad"
            return level, label
    return "other", clean(position).title()


def rows_to_officials(rows: list[dict[str, str]], *, source: str, source_url: str,
                      defaults: dict[str, str]) -> list[dict]:
    out = []
    for row in rows:
        ctx = {
            "region": pick(row, r"region") or defaults.get("region", ""),
            "province": pick(row, r"province") or defaults.get("province", ""),
            "lgu": pick(row, r"^(lgu|city|municipality|city_municipality|municipality_city|name_of_lgu|local_government)")
                   or defaults.get("lgu", ""),
            "barangay": pick(row, r"barangay(?!_(official|captain|chair|kagawad|secretary|treasurer))")
                        or defaults.get("barangay", ""),
        }
        contact = pick(row, r"contact|tel|phone|mobile|email")
        address = pick(row, r"address")

        pos_val = pick(row, r"^(position|designation|office|title)")
        name_val = pick(row, r"^(name|full_name|official|name_of_official)")
        if pos_val and name_val:  # long form
            level, label = classify(pos_val)
            out.append(record(name=name_val, position=label, level=level, source=source,
                              source_url=source_url, contact=contact,
                              details={"address": address, "position_raw": pos_val}, **ctx))
            continue

        for col, val in row.items():  # wide form
            if col.startswith("__") or col.endswith("__href") or re.search(CONTEXT_COLS, col):
                continue
            level, label = classify(col.replace("_", " "))
            if level == "other":
                continue
            names = [n for n in re.split(r"\s*(?:;|\n|/)\s*", val) if n]
            for n in names:
                if looks_like_name(n):
                    out.append(record(name=strip_honorific(n), position=label, level=level,
                                      source=source, source_url=source_url, contact=contact,
                                      details={"address": address}, **ctx))
    return out
