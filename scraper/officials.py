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
    (r"\bsb[\s_-]*members?\b|sangguniang[\s_-]*bayan", "councilor", "Councilor"),
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
            if level == "sk_chair":
                # Only the chairperson is SK chair; members are SK kagawads and
                # the appointed secretary/treasurer are their own posts.
                m = re.search(r"secretary|treasurer", p)
                if m:
                    return "other", f"SK {m.group(0).title()}"
                if not re.search(r"chair|president", p):
                    return "sk_kagawad", "SK Kagawad"
            return level, label
    return "other", clean(position).title()


def split_name(row: dict[str, str]) -> str:
    """'First Middle Last Suffix' from separate name columns, if present."""
    last = pick(row, r"^(last_?name|surname|family_name|lname)")
    first = pick(row, r"^(first_?name|given_name|fname)")
    if not (first and last):
        return ""
    middle = pick(row, r"^(middle_?(name|initial)|mi|mname)")
    suffix = pick(row, r"^(suffix|ext|extension|name_extension)")
    if middle and len(middle) == 1:
        middle += "."
    return clean(" ".join(p for p in (first, middle, last, suffix) if p))


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
        if "@" in address and " " not in address.strip():
            address = ""  # an "email address" column, already kept as contact

        pos_val = pick(row, r"^(position|designation|office|title|elective_position)")
        name_val = pick(row, r"^(name|full_name|official|name_of_official|complete_name)") or split_name(row)
        if pos_val and name_val:  # long form
            level, label = classify(pos_val)
            district = pick(row, r"district")
            # "TERM IN PRESENT POSITION: 3RD" -> consecutive term 3
            term = re.match(r"\s*(\d+)", pick(row, r"term_in_present|term_in_position|no_of_terms|^term_no"))
            out.append(record(name=strip_honorific(name_val), position=label, level=level, source=source,
                              source_url=source_url, contact=contact, party=pick(row, r"party"),
                              district=district,
                              details={"address": address, "position_raw": pos_val,
                                       "term": term.group(1) if term else ""}, **ctx))
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
