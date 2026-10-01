"""Senate bills per senator, from BetterGov's Open Congress Data.

The Senate's own bills pages are behind bot protection and the legacy LIS is
offline, so bills come from BetterGov's public dataset
(https://github.com/bettergovph/open-congress-data), which transcribes the
Senate's Legislative Information System. It is a public, non-government
source: every bill is labelled as such, keeps its link to the official
Senate page, and carries the dataset's "as of" date because status values
are only as fresh as the snapshot.

Bills are matched to senators by the Senate LIS author code (e.g. "GSHER"),
which both the Senate's API and the dataset use. Records scraped before the
code was stored fall back to matching by name.

The dataset covers Senate bills from the 13th Congress (2004) on, and each
person's chamber memberships per Congress. From these every senator gets a
service record (first Congress as senator, Senate terms) and bill counts per
term, so long-serving and new senators can be compared fairly. The full
bill list per senator, grouped by term, goes to app/data/bills/<id>.json and
is loaded only when that page is opened.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from pathlib import Path

import common
from common import clean, log, now_iso

REPO = "https://github.com/bettergovph/open-congress-data"
SOURCE = "BetterGov Open Congress Data"
CONGRESS = 20
MAX_PER_SENATOR = 400


FIRST_CONGRESS = 13  # earliest Senate bills in the dataset (2004)

# Sector of a bill = the Senate committee it was referred to on first reading
# (its primary committee), grouped. This is the Senate's own classification;
# titles are not guessed from. Order matters: first match wins.
SECTORS = [
    ("agriculture", r"agricultur|agrarian|food"),
    ("health", r"health"),
    ("education", r"education"),
    ("labor", r"labor|migrant"),
    ("transport", r"public services"),
    ("infrastructure", r"public works|housing|urban planning"),
    ("environment", r"environment|climate"),
    ("energy", r"energy"),
    ("tourism", r"tourism"),
    ("economy", r"ways and means|trade|bank|finance|economic|cooperative|government corporations"),
    ("justice", r"justice|constitutional"),
    ("public_order", r"public order"),
    ("defense", r"defense|peace|foreign|maritime|marawi"),
    ("local_gov", r"local government"),
    ("social", r"social justice|women|youth|children|cultural communities"),
    ("science", r"science|innovation|sustainable development"),
    ("culture_sports", r"culture|arts|sports|games"),
    ("governance", r"civil service|electoral|rules|accounts|accountability|public information|mass media"),
]


def sector_of(committee: str) -> str:
    for key, rx in SECTORS:
        if committee and re.search(rx, committee, re.I):
            return key
    return "other"
LAW = re.compile(r"approved by the president|lapsed into law", re.I)


def fetch(dest: Path) -> tuple[Path, str]:
    """Sparse, shallow clone of the Senate bills, people and Congress years."""
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse", REPO, str(dest)],
                   check=True, timeout=600)
    house = [f"data/document/hb/{c}" for c in range(FIRST_CONGRESS, CONGRESS + 1)]
    subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set",
                    "data/document/sb", *house, "data/person", "data/congress"], check=True, timeout=1500)
    as_of = subprocess.run(["git", "-C", str(dest), "log", "-1", "--format=%cs"],
                           check=True, capture_output=True, text=True).stdout.strip()
    return dest / "data", as_of


def load_people(folder: Path) -> dict[str, dict]:
    """LIS author code -> {"senate": [congresses], "house": [congresses]}."""
    out: dict[str, dict] = {}
    for path in folder.glob("*.toml"):
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        keys = [clean(k) for k in doc.get("senate_website_keys") or [] if clean(k)]
        if not keys:
            continue
        chambers: dict[str, set] = {"senate": set(), "house": set()}
        for m in doc.get("memberships") or []:
            if m.get("type") == "chamber" and m.get("subtype") in chambers and m.get("congress"):
                chambers[m["subtype"]].add(int(m["congress"]))
        entry = {k: sorted(v) for k, v in chambers.items()}
        for k in keys:
            out[k] = entry
    return out


def load_congresses(folder: Path) -> dict[int, dict]:
    out = {}
    for path in folder.glob("*.toml"):
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        n = doc.get("congress_number")
        if n:
            start = doc.get("start_year")
            # The sitting Congress has no end year yet; Congresses last three years.
            end = doc.get("end_year") or (start + 3 if start else None)
            out[int(n)] = {"start": start, "end": end, "ordinal": clean(doc.get("ordinal"))}
    return out


def senate_terms(congresses: list[int]) -> int:
    """A Senate term is six years, i.e. two Congresses: count each unbroken
    run of Senate Congresses as ceil(run / 2) terms."""
    terms, run, prev = 0, 0, None
    for c in sorted(congresses):
        if prev is not None and c != prev + 1:
            terms += -(-run // 2)
            run = 0
        run += 1
        prev = c
    return terms + -(-run // 2)


def load_bills(folder: Path) -> list[dict]:
    bills = []
    for path in sorted(folder.glob("*.toml")):
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        meta = doc.get("meta", {})
        status = (doc.get("status") or [{}])[-1]
        bills.append({
            "congress": int(meta.get("congress") or CONGRESS),
            "number": clean(doc.get("name")) or f"SBN-{meta.get('bill_number')}",
            "bill_number": meta.get("bill_number") or 0,
            "title": clean(meta.get("title") or meta.get("long_title")),
            "date": clean(meta.get("date_filed")),
            "status": clean(status.get("status")),
            "status_date": clean(status.get("date")),
            "url": clean(meta.get("senate_website_permalink")),
            "authors": [clean(c) for c in meta.get("senate_website_author_codes", []) if clean(c)],
            "authors_raw": clean(meta.get("authors_raw")),
            "committee": next((clean(c.get("name")) for c in doc.get("committees") or []
                               if c.get("type") == "primary" and clean(c.get("name"))), ""),
        })
    return bills


def norm(text: str) -> set[str]:
    """Name words, ignoring initials (siblings share them: Raffy T. / Erwin T. Tulfo)."""
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 1}


def name_index(bills: list[dict]) -> dict[str, tuple[str, str]]:
    """Author code -> (last name, first name), learnt from single-author bills."""
    out: dict[str, tuple[str, str]] = {}
    for b in bills:
        if len(b["authors"]) == 1 and "," in b["authors_raw"] and ";" not in b["authors_raw"]:
            last, first = (p.strip() for p in b["authors_raw"].split(",", 1))
            out.setdefault(b["authors"][0], (last, first))
    return out


def match_codes(senator: dict, names: dict[str, tuple[str, str]]) -> list[str]:
    """Author codes for a senator. The Senate API may list several ("ZJMIG, ZMIGU")."""
    codes = [c.strip() for c in re.split(r"[,;\s]+", senator.get("lis_code") or "") if c.strip()]
    if codes:
        return codes
    words = norm(senator["name"])
    hits = [code for code, (last, first) in names.items()
            if norm(last) <= words and (norm(first) & words)]
    return hits[:1] if len(hits) == 1 else []


# Only "... became Republic Act No. N" — histories also cite laws being amended.
RA_NO = re.compile(r"\bbecame\s+REPUBLIC\s+ACT\s+NO\.?\s*(\d{4,5})", re.I)
ON_DATE = re.compile(r"(?:\bon\s+([A-Z]+\s+\d{1,2},\s+\d{4})\s+and\s+became\s+REPUBLIC|"
                     r"REPUBLIC\s+ACT\s+NO\.?\s*\d{4,5}\s+ON\s+([A-Z]+\s+\d{1,2},\s+\d{4}))", re.I)
LAPSED = re.compile(r"lapsed into law|without executive approval", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def iso_date(text: str) -> str:
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", text or "")
    if not m or m.group(1).lower() not in MONTHS:
        return ""
    return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def load_laws(root: Path) -> list[dict]:
    """Every Republic Act the Senate and House bill histories record since the
    13th Congress: number, title, date, and whether the President signed it
    or it lapsed into law (Art. VI Sec. 27(1)). The bill that itself became
    the law is preferred for the title and date."""
    laws: dict[str, dict] = {}
    for chamber in ("sb", "hb"):
        for folder in sorted((root / "document" / chamber).glob("*")):
            for path in folder.glob("*.toml"):
                doc = tomllib.loads(path.read_text(encoding="utf-8"))
                acts = [clean(h.get("action")) for h in doc.get("history") or []]
                text = " ".join(acts)
                numbers = RA_NO.findall(text)
                if not numbers:
                    continue
                meta = doc.get("meta", {})
                status = (doc.get("status") or [{}])[-1]
                direct = bool(re.search(r"approved by the president|lapsed into law", status.get("status", ""), re.I))
                ra = numbers[-1]
                m = ON_DATE.search(text)
                date = (clean(status.get("date")) if direct else "") or (iso_date(m.group(1) or m.group(2)) if m else "")
                entry = {
                    "ra": ra, "date": date, "lapsed": bool(LAPSED.search(text)),
                    "title": clean(meta.get("title") or meta.get("long_title")),
                    "bill": clean(doc.get("name")), "congress": int(meta.get("congress") or 0),
                    "url": clean(meta.get("senate_website_permalink") or meta.get("congress_website_permalink")),
                    "direct": direct,
                }
                old = laws.get(ra)
                if not old or (direct and not old["direct"]) or (not old["date"] and entry["date"]):
                    laws[ra] = entry
    return sorted(laws.values(), key=lambda l: (l["date"], int(l["ra"])))


def write_laws(laws: list[dict], as_of: str) -> None:
    (common.DATA_DIR / "laws.json").write_text(json.dumps({
        "source": SOURCE, "source_url": REPO, "source_type": "public", "as_of": as_of,
        "note": "Republic Acts recorded in Senate and House bill histories since the 13th Congress.",
        "count": len(laws), "laws": [{k: v for k, v in l.items() if k != "direct"} for l in laws],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"laws: {len(laws)} Republic Acts (as of {as_of})")


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def attach(bills: list[dict], as_of: str, people: dict[str, dict] | None = None,
           congresses: dict[int, dict] | None = None) -> dict:
    path = common.DATA_DIR / "senate.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    people, congresses = people or {}, congresses or {}
    for b in bills:
        b.setdefault("congress", CONGRESS)
        b.setdefault("committee", "")
        b["sector"] = sector_of(b["committee"])
    names = name_index([b for b in bills if b["congress"] == CONGRESS] or bills)
    by_code: dict[str, list[dict]] = defaultdict(list)
    for b in bills:
        for code in b["authors"]:
            by_code[code].append(b)
    years = lambda c: (f"{congresses[c]['start']}–{congresses[c]['end']}" if c in congresses else "")
    bills_dir = common.DATA_DIR / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)

    matched = 0
    for rec in doc["records"]:
        codes = match_codes(rec, names)
        seen, items = set(), []
        for code in codes:
            for b in by_code.get(code, []):
                if (b["congress"], b["number"]) not in seen:
                    seen.add((b["congress"], b["number"]))
                    items.append(b)
        items.sort(key=lambda b: (-b["congress"], -b["bill_number"]))
        role = lambda b: "main" if b["authors"] and b["authors"][0] in codes else "co"
        current = [b for b in items if b["congress"] == CONGRESS]
        rec["bills"] = [{
            "number": b["number"], "title": b["title"], "date": b["date"],
            "status": b["status"], "url": b["url"],
            "coauthored": role(b) == "co", "sector": b["sector"],
        } for b in current[:MAX_PER_SENATOR]]
        rec["bills_count"] = len(current)

        # Service record from the dataset's chamber memberships; without one,
        # fall back to the Congresses in which the senator filed bills.
        member = next((people[c] for c in codes if c in people), None)
        senate = sorted(set(member["senate"] if member else {b["congress"] for b in items}))
        rec["service"] = {
            "senate_congresses": senate,
            "house_congresses": member["house"] if member else [],
            "first_senate_congress": senate[0] if senate else None,
            "first_senate_year": congresses.get(senate[0], {}).get("start") if senate else None,
            "senate_terms": senate_terms(senate) if senate else 0,
            "basis": "membership" if member else "bills",
        }
        # Counts per Senate term (Congress) covered by the bill data.
        terms = []
        for c in sorted({c for c in senate if c >= FIRST_CONGRESS} | {b["congress"] for b in items}, reverse=True):
            tb = [b for b in items if b["congress"] == c]
            terms.append({"congress": c, "years": years(c), "filed": len(tb),
                          "main": sum(role(b) == "main" for b in tb),
                          "law": sum(bool(LAW.search(b["status"] or "")) for b in tb)})
        rec["bill_terms"] = terms
        # Bills per sector: this term [filed, main] and whole career [filed, main, law].
        sectors: dict[str, dict] = {"term": {}, "career": {}}
        for b in items:
            is_main, is_law = role(b) == "main", bool(LAW.search(b["status"] or ""))
            c = sectors["career"].setdefault(b["sector"], [0, 0, 0])
            c[0] += 1; c[1] += is_main; c[2] += is_law
            if b["congress"] == CONGRESS:
                tm = sectors["term"].setdefault(b["sector"], [0, 0])
                tm[0] += 1; tm[1] += is_main
        rec["bill_sectors"] = sectors
        rec["bills_all"] = len(items)
        rec["law_all"] = sum(t["law"] for t in terms)

        rid = rec.get("id") or common.slug(rec["name"])
        (bills_dir / f"{rid}.json").write_text(json.dumps({
            "id": rid, "name": rec["name"], "as_of": as_of, "source": SOURCE, "source_url": REPO,
            "source_type": "public",
            "terms": [{**t, "bills": [{
                "number": b["number"], "title": b["title"], "date": b["date"], "status": b["status"],
                "status_date": b.get("status_date", ""), "url": b["url"], "role": role(b),
                "sector": b["sector"], "committee": b["committee"],
                "law": bool(LAW.search(b["status"] or "")),
            } for b in items if b["congress"] == t["congress"]]} for t in terms],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        rec["bills_file"] = f"bills/{rid}.json"
        if items:
            matched += 1
            rec.setdefault("lis_code", ", ".join(codes))
    doc["bills_source"] = {
        "name": SOURCE,
        "url": REPO,
        "source_type": "public",
        "note": "Public, non-government dataset transcribed from the Senate Legislative "
                "Information System; each bill links to its official Senate page.",
        "congress": CONGRESS,
        "first_congress": min((b["congress"] for b in bills), default=CONGRESS),
        "congresses": {str(c): {"years": years(c), "ordinal": ordinal(c)} for c in sorted({b["congress"] for b in bills})},
        "sector_basis": "Senate committee the bill was referred to on first reading (primary committee)",
        "sectors": [k for k, _ in SECTORS] + ["other"],
        "as_of": as_of,
        "bill_count": sum(b["congress"] == CONGRESS for b in bills),
        "bill_count_all": len(bills),
        "imported_at": now_iso(),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"bills: {len(bills)} Senate bills since the {ordinal(doc['bills_source']['first_congress'])} Congress "
        f"(as of {as_of}) matched to {matched}/{len(doc['records'])} senators")
    return doc


def run() -> None:
    if not (common.DATA_DIR / "senate.json").exists():
        raise SystemExit("bills: no senate.json yet")
    with tempfile.TemporaryDirectory() as tmp:
        root, as_of = fetch(Path(tmp) / "occ")
        run_from(root, as_of)


def run_from(root: Path, as_of: str) -> None:
    bills = [b for folder in sorted((root / "document" / "sb").iterdir()) if folder.is_dir()
             and folder.name.isdigit() and int(folder.name) >= FIRST_CONGRESS for b in load_bills(folder)]
    if sum(b["congress"] == CONGRESS for b in bills) < 100:
        raise SystemExit(f"bills: only {len(bills)} bills found; keeping previous data")
    attach(bills, as_of, load_people(root / "person"), load_congresses(root / "congress"))
    write_laws(load_laws(root), as_of)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-dir", help="use an existing checkout's data/ folder")
    ap.add_argument("--as-of", default="")
    args = ap.parse_args()
    if args.from_dir:
        run_from(Path(args.from_dir), args.as_of)
    else:
        run()


if __name__ == "__main__":
    main()
