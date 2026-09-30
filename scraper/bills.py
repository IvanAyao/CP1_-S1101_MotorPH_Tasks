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

from common import DATA_DIR, clean, log, now_iso

REPO = "https://github.com/bettergovph/open-congress-data"
SOURCE = "BetterGov Open Congress Data"
CONGRESS = 20
MAX_PER_SENATOR = 400


def fetch(dest: Path) -> tuple[Path, str]:
    """Sparse, shallow clone of just the Senate bills of this Congress."""
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--sparse", REPO, str(dest)],
                   check=True, timeout=600)
    subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", f"data/document/sb/{CONGRESS}"],
                   check=True, timeout=600)
    as_of = subprocess.run(["git", "-C", str(dest), "log", "-1", "--format=%cs"],
                           check=True, capture_output=True, text=True).stdout.strip()
    return dest / "data" / "document" / "sb" / str(CONGRESS), as_of


def load_bills(folder: Path) -> list[dict]:
    bills = []
    for path in sorted(folder.glob("*.toml")):
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        meta = doc.get("meta", {})
        status = (doc.get("status") or [{}])[-1]
        bills.append({
            "number": clean(doc.get("name")) or f"SBN-{meta.get('bill_number')}",
            "bill_number": meta.get("bill_number") or 0,
            "title": clean(meta.get("title") or meta.get("long_title")),
            "date": clean(meta.get("date_filed")),
            "status": clean(status.get("status")),
            "status_date": clean(status.get("date")),
            "url": clean(meta.get("senate_website_permalink")),
            "authors": [clean(c) for c in meta.get("senate_website_author_codes", []) if clean(c)],
            "authors_raw": clean(meta.get("authors_raw")),
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


def match_code(senator: dict, names: dict[str, tuple[str, str]]) -> str:
    if senator.get("lis_code"):
        return senator["lis_code"]
    words = norm(senator["name"])
    hits = [code for code, (last, first) in names.items()
            if norm(last) <= words and (norm(first) & words)]
    return hits[0] if len(hits) == 1 else ""


def attach(bills: list[dict], as_of: str) -> dict:
    path = DATA_DIR / "senate.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    names = name_index(bills)
    by_code: dict[str, list[dict]] = defaultdict(list)
    for b in bills:
        for code in b["authors"]:
            by_code[code].append(b)

    matched = 0
    for rec in doc["records"]:
        code = match_code(rec, names)
        items = sorted(by_code.get(code, []), key=lambda b: -b["bill_number"])
        rec["bills"] = [{
            "number": b["number"], "title": b["title"], "date": b["date"],
            "status": b["status"], "url": b["url"],
            "coauthored": len(b["authors"]) > 1,
        } for b in items[:MAX_PER_SENATOR]]
        rec["bills_count"] = len(items)
        if items:
            matched += 1
            rec.setdefault("lis_code", code)
    doc["bills_source"] = {
        "name": SOURCE,
        "url": REPO,
        "source_type": "public",
        "note": "Public, non-government dataset transcribed from the Senate Legislative "
                "Information System; each bill links to its official Senate page.",
        "congress": CONGRESS,
        "as_of": as_of,
        "bill_count": len(bills),
        "imported_at": now_iso(),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"bills: {len(bills)} Senate bills (as of {as_of}) matched to {matched}/{len(doc['records'])} senators")
    return doc


def run() -> None:
    if not (DATA_DIR / "senate.json").exists():
        raise SystemExit("bills: no senate.json yet")
    with tempfile.TemporaryDirectory() as tmp:
        folder, as_of = fetch(Path(tmp) / "occ")
        bills = load_bills(folder)
    if len(bills) < 100:
        raise SystemExit(f"bills: only {len(bills)} bills found; keeping previous data")
    attach(bills, as_of)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-dir", help="use an existing checkout's data/document/sb/<congress> folder")
    ap.add_argument("--as-of", default="")
    args = ap.parse_args()
    if args.from_dir:
        attach(load_bills(Path(args.from_dir)), args.as_of)
    else:
        run()


if __name__ == "__main__":
    main()
