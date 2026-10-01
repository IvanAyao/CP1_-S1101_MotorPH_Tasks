"""The sitting President and Vice President, from Wikidata (public, CC0).

Wikidata's "position held" statements give who holds each office now (no
end date) and every office each of them has held, with start and end
dates, plus party and photo. It is a public, non-government source and is
labelled as such; every record links to its Wikidata item.

For the President, the laws of the term come from app/data/laws.json (built
by bills.py from Senate and House bill histories): Republic Acts dated from
the day the term began, signed or lapsed into law without signature.

Eligibility in 2028 follows the Constitution (Art. VII, Sec. 4): the
President may not be re-elected; the Vice President may serve at most two
successive terms.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

import common
from common import clean, log, now_iso, record, write_dataset

SPARQL = "https://query.wikidata.org/sparql"
SOURCE = "Wikidata (public, CC0)"
URL = "https://www.wikidata.org/"
OFFICES = {
    "President of the Philippines": ("president", "President of the Philippines"),
    "Vice President of the Philippines": ("vice_president", "Vice President of the Philippines"),
}
USER_AGENT = "pili-ph-data/1.0 (https://github.com/IvanAyao/Pili_App_PH)"

HOLDERS = """
SELECT ?officeLabel ?person ?personLabel ?start WHERE {
  VALUES ?label { "President of the Philippines"@en "Vice President of the Philippines"@en }
  ?office rdfs:label ?label .
  ?person p:P39 ?st . ?st ps:P39 ?office ; pq:P580 ?start .
  FILTER NOT EXISTS { ?st pq:P582 ?end }
  FILTER NOT EXISTS { ?person wdt:P570 ?died }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""

POSITIONS = """
SELECT ?posLabel ?start ?end ?districtLabel ?ofLabel WHERE {
  wd:%(q)s p:P39 ?st . ?st ps:P39 ?pos .
  OPTIONAL { ?st pq:P580 ?start } OPTIONAL { ?st pq:P582 ?end }
  OPTIONAL { ?st pq:P768 ?district } OPTIONAL { ?st pq:P642 ?of }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} ORDER BY ?start"""

PERSON = """
SELECT ?partyLabel ?image ?birth ?article WHERE {
  OPTIONAL { wd:%(q)s p:P102 ?ps . ?ps ps:P102 ?party . FILTER NOT EXISTS { ?ps pq:P582 ?e } }
  OPTIONAL { wd:%(q)s wdt:P18 ?image }
  OPTIONAL { wd:%(q)s wdt:P569 ?birth }
  OPTIONAL { ?article schema:about wd:%(q)s ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def query(sparql: str) -> list[dict]:
    url = f"{SPARQL}?{urllib.parse.urlencode({'query': sparql, 'format': 'json'})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as res:
        data = json.load(res)
    return [{k: v.get("value", "") for k, v in row.items()} for row in data["results"]["bindings"]]


def year(iso: str) -> str:
    return (iso or "")[:4]


def career(rows: list[dict]) -> list[dict]:
    """Offices held, oldest first, without duplicate statements."""
    out, seen = [], set()
    for r in rows:
        title = clean(r.get("posLabel"))
        if not title or title.startswith("Q"):
            continue
        place = clean(r.get("districtLabel") or r.get("ofLabel"))
        item = {"title": title, "place": place if place and not place.startswith("Q") else "",
                "start": (r.get("start") or "")[:10], "end": (r.get("end") or "")[:10]}
        k = (item["title"], item["place"], item["start"])
        if k not in seen:
            seen.add(k)
            out.append(item)
    return sorted(out, key=lambda i: i["start"] or "9999")


def career_text(items: list[dict]) -> str:
    def span(i):
        return f"{year(i['start']) or '?'}–{year(i['end']) or 'present'}"
    return "; ".join(f"{i['title']}{', ' + i['place'] if i['place'] else ''} ({span(i)})" for i in items)


def successive_terms(items: list[dict], title: str) -> int:
    """Successive terms in an office, counting back from the current one
    (a later term starting within a year of the previous one's end)."""
    held = [i for i in items if i["title"] == title]
    if not held:
        return 0
    n, prev = 1, held[-1]
    for i in reversed(held[:-1]):
        if i["end"] and prev["start"] and int(year(prev["start"])) - int(year(i["end"]) or 0) <= 1:
            n += 1
            prev = i
        else:
            break
    return n


def laws_in_term(start: str) -> dict:
    path = common.DATA_DIR / "laws.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    laws = [l for l in doc["laws"] if l.get("date") and l["date"] >= start[:10]]
    return {"laws_signed": sum(not l["lapsed"] for l in laws), "laws_lapsed": sum(l["lapsed"] for l in laws),
            "laws_from": start[:10], "laws_as_of": doc.get("as_of", "")}


def build(holders: list[dict], positions: dict[str, list[dict]], people: dict[str, dict]) -> list[dict]:
    out = []
    for h in holders:
        office = clean(h.get("officeLabel"))
        if office not in OFFICES:
            continue
        level, label = OFFICES[office]
        q = h["person"].rsplit("/", 1)[-1]
        items = career(positions.get(q, []))
        info = people.get(q, {})
        start = (h.get("start") or "")[:10]
        prior = [i for i in items if i["title"] != office]
        rec = record(
            name=clean(h.get("personLabel")), position=label, level=level,
            source=SOURCE, source_url=f"https://www.wikidata.org/wiki/{q}",
            party=clean(info.get("partyLabel")), district="Nationwide",
            photo=f"{info['image']}?width=300" if info.get("image") else "",
            profile_url=info.get("article", ""),
            details={"took_office": start, "term": f"{year(start)}–{int(year(start)) + 6}" if year(start) else "",
                     "born": (info.get("birth") or "")[:10],
                     "prior_experience": career_text(prior)},
        )
        rec["source_type"] = "public"
        rec["career"] = items
        rec["successive_terms"] = successive_terms(items, office)
        if level == "president":
            rec.update(laws_in_term(start))
        out.append(rec)
    return out


def run() -> list[dict]:
    holders = query(HOLDERS)
    log(f"executive: holders {[(h.get('officeLabel'), h.get('personLabel'), h.get('start', '')[:10]) for h in holders]}")
    qs = {h["person"].rsplit("/", 1)[-1] for h in holders}
    positions = {q: query(POSITIONS % {"q": q}) for q in qs}
    people = {q: (query(PERSON % {"q": q}) or [{}])[0] for q in qs}
    records = build(holders, positions, people)
    if {r["level"] for r in records} != {"president", "vice_president"}:
        raise SystemExit(f"executive: expected a President and a Vice President, got {[r['position'] for r in records]}")
    write_dataset("executive", records, URL, min_count=2, max_count=2,
                  extra_meta={"method": "public", "source_label": SOURCE, "fetched_at": now_iso()})
    return records


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == "__main__":
    main()
