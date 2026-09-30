"""House members, governors and city mayors from Wikipedia (unofficial).

Used where the official sites block automated access. Every record is
labelled "Wikipedia (unofficial)" with a link to the article revision date,
and official data (live scrape or saved copy) always takes precedence: this
script only writes a dataset when it has no official records.

Pages are read through the MediaWiki API (action=parse), which returns the
rendered article HTML without needing a browser.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup, Tag

from common import DATA_DIR, USER_AGENT, clean, dedupe, log, norm_key, record, strip_honorific, write_dataset

API = "https://en.wikipedia.org/w/api.php"
SOURCE = "Wikipedia (unofficial)"

PAGES = {
    "house": "List of current members of the House of Representatives of the Philippines",
    "governors": "List of current Philippine governors",
    "mayors": "List of current Philippine city mayors",
}


def fetch(page: str) -> tuple[str, str]:
    """(html, revision timestamp) of a Wikipedia article."""
    q = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "text|revid",
                                "format": "json", "formatversion": "2", "redirects": "1"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        doc = json.load(resp)
    return doc["parse"]["text"], str(doc["parse"].get("revid", ""))


def page_url(page: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page.replace(" ", "_"))


def cell_text(cell: Tag) -> str:
    """Visible text of a cell: no footnote markers, list items/lines joined by '; '."""
    cell = BeautifulSoup(str(cell), "lxml")
    for junk in cell.find_all(["sup", "style"]):
        junk.decompose()  # footnote markers like [1]
    for br in cell.find_all("br"):
        br.replace_with("; ")
    for li in cell.find_all("li"):
        li.append("; ")
    text = clean(cell.get_text(" "))
    text = re.sub(r"\s*;\s*(;\s*)*", "; ", text).strip("; ")
    return text


def tidy(key: str, value: str) -> str:
    value = re.sub(r"\(\s*list\s*\)", "", value)                   # "Abra ( list )"
    value = re.sub(r"\(\s*\d{4}-\d{2}-\d{2}\s*\)", "", value)       # hidden sort date
    value = re.sub(r"\(\s*age\s+\d+\s*\)", "", value)                # goes stale
    return clean(value)


def is_partylist(constituency: str) -> bool:
    c = constituency.lower()
    if re.search(r"party.?list", c):
        return True
    # District seats read "Province–1st" or "Province at-large".
    return not ("–" in constituency or "-" in constituency and re.search(r"\d(st|nd|rd|th)", c)
                or "at-large" in c or "lone" in c or "district" in c)


def province_of(constituency: str) -> str:
    return clean(re.split(r"–| at-large| lone", constituency, maxsplit=1, flags=re.I)[0])


def expand_table(table: Tag) -> tuple[list[str], list[list[Tag]]]:
    """Header names and body rows with rowspan/colspan cells repeated."""
    rows = table.find_all("tr")
    header: list[str] = []
    grid: list[list[Tag]] = []
    pending: dict[int, tuple[Tag, int]] = {}  # column -> (cell, rows left)
    for tr in rows:
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        if not header and all(c.name == "th" for c in cells):
            for c in cells:
                header += [norm_key(cell_text(c)) or f"col{len(header)}"] * int(c.get("colspan", 1) or 1)
            continue
        out: list[Tag] = []
        col = 0
        it = iter(cells)
        while True:
            if col in pending:
                cell, left = pending[col]
                out.append(cell)
                pending[col] = (cell, left - 1)
                if left - 1 <= 0:
                    del pending[col]
                col += 1
                continue
            cell = next(it, None)
            if cell is None:
                break
            span = int(cell.get("colspan", 1) or 1)
            rs = int(cell.get("rowspan", 1) or 1)
            for _ in range(span):
                out.append(cell)
                if rs > 1:
                    pending[col] = (cell, rs - 1)
                col += 1
        # Trailing spanned cells after the last real one.
        while col in pending:
            cell, left = pending[col]
            out.append(cell)
            pending[col] = (cell, left - 1)
            if left - 1 <= 0:
                del pending[col]
            col += 1
        grid.append(out)
    return header, grid


def tables(html: str) -> list[tuple[str, list[str], list[dict[str, str]], list[dict[str, Tag]]]]:
    """(section heading, headers, text rows, cell rows) for every wikitable."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for t in soup.select("table.wikitable"):
        heading = t.find_previous(["h2", "h3", "h4"])
        header, grid = expand_table(t)
        if not header:
            continue
        text_rows, cell_rows = [], []
        for cells in grid:
            text_rows.append({h: tidy(h, cell_text(c)) for h, c in zip(header, cells)})
            cell_rows.append(dict(zip(header, cells)))
        out.append((clean(heading.get_text(" ")) if heading else "", header, text_rows, cell_rows))
    return out


def col(header: list[str], *patterns: str) -> str | None:
    for pat in patterns:
        for h in header:
            if re.search(pat, h):
                return h
    return None


def person(cell: Tag | None) -> tuple[str, str]:
    """(name, wikipedia link) from a table cell."""
    if cell is None:
        return "", ""
    for a in cell.find_all("a", href=True):
        if a["href"].startswith("/wiki/") and not a.find_parent("sup"):
            name = clean(a.get_text(" "))
            if len(name.split()) >= 2:
                return strip_honorific(name), "https://en.wikipedia.org" + a["href"]
    return strip_honorific(cell_text(cell)), ""


def photo(cell: Tag | None) -> str:
    img = cell.find("img") if cell is not None else None
    if not img or not img.get("src"):
        return ""
    src = img["src"]
    return ("https:" + src) if src.startswith("//") else src


def officials(kind: str, html: str, revid: str) -> list[dict]:
    page = PAGES[kind]
    recs = []
    for heading, header, text_rows, cell_rows in tables(html):
        name_col = col(header, r"^(representative|member|governor|mayor|name|incumbent)$",
                       r"representative|member|governor|mayor|incumbent|name")
        if not name_col:
            continue
        party_col = col(header, r"^party$", r"party")
        photo_col = col(header, r"image|portrait|photo")
        vice = bool(re.search(r"vice", name_col))
        for text, cells in zip(text_rows, cell_rows):
            name, wiki = person(cells.get(name_col))
            if not name or len(name.split()) < 2 or re.search(r"\bvacant\b", name, re.I):
                continue
            place_col = col(header, r"constituency|district|province|city|lgu")
            details = {k: v for k, v in text.items()
                       if v and k not in {name_col, party_col, photo_col, place_col} and len(v) < 300}
            details["wikipedia_revision"] = revid
            common = dict(name=name, party=text.get(party_col, "") if party_col else "",
                          photo=photo(cells.get(photo_col)) if photo_col else photo(cells.get(name_col)),
                          profile_url=wiki, source=SOURCE, source_url=page_url(page), details=details)
            if kind == "house":
                constituency = text.get(col(header, r"constituency|district") or "", "")
                partylist = "party-list" in heading.lower() or is_partylist(constituency)
                recs.append(record(
                    position="Party-list Representative" if partylist else "District Representative",
                    level="house", district=constituency or "Party-list",
                    province="" if partylist else province_of(constituency), **common))
            elif kind == "governors":
                province = text.get(col(header, r"province") or "", "")
                recs.append(record(position="Vice Governor" if vice else "Governor",
                                   level="vice_governor" if vice else "governor",
                                   province=province, **common))
            else:
                city = text.get(col(header, r"city|lgu|municipality") or "", "")
                recs.append(record(position="Vice Mayor" if vice else "Mayor",
                                   level="vice_mayor" if vice else "mayor", lgu=city, **common))
    return dedupe(recs)


def official_count(dataset: str) -> int:
    """Records in an existing dataset that did NOT come from Wikipedia."""
    path = DATA_DIR / f"{dataset}.json"
    if not path.exists():
        return 0
    doc = json.loads(path.read_text())
    return sum(1 for r in doc.get("records", []) if "wikipedia" not in r.get("source", "").lower())


def run(kinds: list[str]) -> None:
    if "house" in kinds:
        if official_count("house"):
            log("house: official data present; not replacing with Wikipedia")
        else:
            html, rev = fetch(PAGES["house"])
            recs = officials("house", html, rev)
            log(f"house: {len(recs)} from Wikipedia")
            write_dataset("house", recs, page_url(PAGES["house"]), min_count=250, max_count=340,
                          extra_meta={"method": "wikipedia", "wikipedia_revision": rev})

    local = [k for k in ("governors", "mayors") if k in kinds]
    if local:
        # Keep official records (e.g. NCR from PSA); Wikipedia fills the rest.
        existing = []
        path = DATA_DIR / "lgu.json"
        meta = {}
        if path.exists():
            doc = json.loads(path.read_text())
            existing = [r for r in doc.get("records", []) if "wikipedia" not in r.get("source", "").lower()]
            meta = {k: v for k, v in doc.items() if k in {"lgus", "lgu_count"}}
        official_keys = {(r["level"], (r.get("lgu") or r.get("province") or "").lower()) for r in existing}
        wiki = []
        for kind in local:
            html, rev = fetch(PAGES[kind])
            found = officials(kind, html, rev)
            log(f"{kind}: {len(found)} from Wikipedia")
            wiki += [r for r in found if (r["level"], (r.get("lgu") or r.get("province") or "").lower()) not in official_keys]
        write_dataset("lgu", existing + wiki, page_url(PAGES["governors"]), min_count=50,
                      extra_meta={**meta, "method": "official+wikipedia" if existing else "wikipedia"})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", choices=["house", "governors", "mayors"])
    args = ap.parse_args()
    run(args.only or ["house", "governors", "mayors"])


if __name__ == "__main__":
    main()
