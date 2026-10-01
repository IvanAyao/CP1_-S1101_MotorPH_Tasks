"""Every President and Vice President of the Philippines, from Wikidata.

Wikidata's "position held" statements (public, CC0) give everyone who has
held each office, with start and end dates and their order (e.g. 17th
President), every other office they held, party and photo. The sitting
holders are those with a term that has no end date. Each person also gets
the lead summary of their English Wikipedia article (CC BY-SA), labelled
and linked, describing their career and time in office. Both are public,
non-government sources and are labelled as such.

For Presidents, the laws of each term come from app/data/laws.json (built
by bills.py from Senate and House bill histories, 2004 onwards): Republic
Acts dated within the term, signed or lapsed into law without signature.
Older histories miss many laws, so the RA number range of the term is kept
as an estimate of the total, with the share the list covers.

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
SELECT ?officeLabel ?person ?personLabel ?start ?end ?ordinal ?died WHERE {
  VALUES ?label { "President of the Philippines"@en "Vice President of the Philippines"@en }
  ?office rdfs:label ?label .
  ?person p:P39 ?st . ?st ps:P39 ?office .
  OPTIONAL { ?st pq:P580 ?start } OPTIONAL { ?st pq:P582 ?end } OPTIONAL { ?st pq:P1545 ?ordinal }
  OPTIONAL { ?person wdt:P570 ?died }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

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


def summary(article_url: str) -> str:
    """Lead summary of the English Wikipedia article (plain text)."""
    if not article_url:
        return ""
    title = article_url.rsplit("/wiki/", 1)[-1]
    req = urllib.request.Request(SUMMARY + title, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return clean(json.load(res).get("extract", ""))
    except Exception as err:  # noqa: BLE001 - a missing summary must not stop the rest
        log(f"executive: no Wikipedia summary for {title}: {err}")
        return ""


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


def load_laws() -> tuple[list[dict], str]:
    path = common.DATA_DIR / "laws.json"
    if not path.exists():
        return [], ""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["laws"], doc.get("as_of", "")


def laws_between(laws: list[dict], start: str, end: str, as_of: str) -> dict:
    """Laws dated within a presidency. Law data starts in 2004 (13th
    Congress), so earlier terms have none and partly covered terms say so."""
    if not laws or not start:
        return {}
    first = min(l["date"] for l in laws if l.get("date"))
    if end and end[:10] < first:
        return {"laws_note": "before_data"}
    inside = [l for l in laws if l.get("date") and l["date"] >= start[:10] and (not end or l["date"] < end[:10])]
    out = {"laws_signed": sum(not l["lapsed"] for l in inside), "laws_lapsed": sum(l["lapsed"] for l in inside),
           "laws_from": max(start[:10], first), "laws_to": (end or "")[:10], "laws_as_of": as_of}
    # Older bill histories are incomplete, but Republic Acts are numbered in
    # order, so the first and last numbers of the term give how many were
    # enacted in it, and the share the list covers.
    ras = sorted(int(l["ra"]) for l in inside if str(l.get("ra", "")).isdigit())
    if ras:
        est = ras[-1] - ras[0] + 1
        out.update({"ra_first": ras[0], "ra_last": ras[-1], "laws_est": est,
                    "laws_coverage": round(100 * len(inside) / est)})
    if start[:10] < first:
        out["laws_note"] = "partial"
    return out


def build(holders: list[dict], positions: dict[str, list[dict]], people: dict[str, dict],
          summaries: dict[str, str] | None = None, laws: list[dict] | None = None, as_of: str = "") -> list[dict]:
    """One record per person and office, with all their terms in it."""
    summaries, laws = summaries or {}, laws or []
    grouped: dict[tuple, list[dict]] = {}
    for h in holders:
        office = clean(h.get("officeLabel"))
        if office in OFFICES:
            grouped.setdefault((h["person"].rsplit("/", 1)[-1], office), []).append(h)
    out = []
    for (q, office), rows in grouped.items():
        level, label = OFFICES[office]
        terms = sorted({((r.get("start") or "")[:10], (r.get("end") or "")[:10], clean(r.get("ordinal"))) for r in rows})
        terms = [{"start": a, "end": b, "ordinal": o} for a, b, o in terms if a]
        if not terms:
            continue
        current = not terms[-1]["end"] and not rows[0].get("died")
        items = career(positions.get(q, []))
        info = people.get(q, {})
        first, last = terms[0], terms[-1]
        span = f"{year(first['start'])}–{year(last['end']) if last['end'] else (int(year(last['start'])) + 6 if current else '')}"
        prior = [i for i in items if i["title"] != office]
        rec = record(
            name=clean(rows[0].get("personLabel")), position=label, level=level,
            source=SOURCE, source_url=f"https://www.wikidata.org/wiki/{q}",
            party=clean(info.get("partyLabel")), district="Nationwide",
            photo=f"{info['image']}?width=300" if info.get("image") else "",
            profile_url=info.get("article", ""),
            details={"took_office": first["start"], "term": span, "born": (info.get("birth") or "")[:10],
                     "prior_experience": career_text(prior)},
        )
        rec["source_type"] = "public"
        rec["current"] = current
        rec["terms"] = terms
        rec["ordinal"] = next((t["ordinal"] for t in reversed(terms) if t["ordinal"]), "")
        rec["career"] = items
        rec["successive_terms"] = successive_terms(items, office) if items else len(terms)
        if summaries.get(q):
            rec["summary"] = summaries[q]
            rec["summary_source"] = info.get("article", "")
        if level == "president":
            rec.update(laws_between(laws, first["start"], last["end"], as_of))
        out.append(rec)
    order = {"president": 0, "vice_president": 1}
    return sorted(out, key=lambda r: (order[r["level"]], not r["current"], r["details"]["took_office"]), reverse=False)


def run() -> list[dict]:
    holders = query(HOLDERS)
    qs = sorted({h["person"].rsplit("/", 1)[-1] for h in holders})
    log(f"executive: {len(holders)} terms, {len(qs)} people")
    positions = {q: query(POSITIONS % {"q": q}) for q in qs}
    people = {q: (query(PERSON % {"q": q}) or [{}])[0] for q in qs}
    summaries = {q: summary(people[q].get("article", "")) for q in qs}
    laws, as_of = load_laws()
    records = build(holders, positions, people, summaries, laws, as_of)
    current = [(r["position"], r["name"]) for r in records if r["current"]]
    log(f"executive: {len(records)} records; current: {current}")
    if sorted(l for l, _ in current) != sorted(OFFICES[o][1] for o in OFFICES):
        raise SystemExit(f"executive: expected one sitting President and Vice President, got {current}")
    write_dataset("executive", records, URL, min_count=20, max_count=80,
                  extra_meta={"method": "public", "source_label": SOURCE, "fetched_at": now_iso()})
    return records


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == "__main__":
    main()
