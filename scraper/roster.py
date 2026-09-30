"""Generic "list of people" extraction used by the Senate and House scrapers."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import (Capture, clean, extract_cards, flatten, looks_like_name,
                    name_from_obj, people_lists_from_json, pick, strip_honorific,
                    all_table_rows)

PARTY_RX = r"party|affil|partido"
DISTRICT_RX = r"district|distrito|constituen|represent|province|lone"
PHOTO_RX = r"photo|image|img|picture|avatar|thumb|portrait"
LINK_RX = r"url|link|slug|profile|permalink|href"


def people_from_capture(cap: Capture) -> tuple[str, list[dict]]:
    """Return (method, people). Each person: name, fields, photo, profile_url."""
    candidates: list[tuple[str, list[dict]]] = []

    for url, doc in cap.json_docs:
        for items in people_lists_from_json(doc):
            people = []
            for obj in items:
                name = name_from_obj(obj)
                if not name:
                    continue
                flat = flatten(obj)
                photo = pick(flat, PHOTO_RX)
                link = pick(flat, LINK_RX)
                people.append({
                    "name": strip_honorific(name),
                    "fields": flat,
                    "photo": urljoin(url, photo) if photo and not photo.startswith("data:") else "",
                    "profile_url": urljoin(cap.url, link) if link and ("/" in link or "." in link) else "",
                })
            candidates.append((f"json:{url}", people))

    soup = BeautifulSoup(cap.html, "lxml")
    for rows in all_table_rows(soup):
        people = []
        for row in rows:
            name = pick(row, r"^name|member|senator|representative|official") or next(
                (v for k, v in row.items() if not k.startswith("__") and not k.endswith("__href") and looks_like_name(v)), "")
            if not name or not looks_like_name(name):
                continue
            href = next((v for k, v in row.items() if k.endswith("__href")), "")
            people.append({
                "name": strip_honorific(name),
                "fields": {k: v for k, v in row.items() if not k.startswith("__")},
                "photo": urljoin(cap.url, row["__img"]) if row.get("__img") else "",
                "profile_url": urljoin(cap.url, href) if href else "",
            })
        candidates.append(("table", people))

    cards = extract_cards(soup, cap.url)
    candidates.append(("cards", [{
        "name": c.name,
        "fields": {f"line{i}": s for i, s in enumerate(c.subtitle)},
        "photo": c.img,
        "profile_url": c.href,
    } for c in cards]))

    candidates = [(m, p) for m, p in candidates if p]
    if not candidates:
        return "none", []
    # Prefer structured sources when they are about as complete as the best.
    best_n = max(len(p) for _, p in candidates)
    order = {"json": 0, "table": 1, "cards": 2}
    method, people = min(
        (c for c in candidates if len(c[1]) >= best_n * 0.9),
        key=lambda c: order[c[0].split(":")[0]],
    )
    return method, people


def party_and_district(fields: dict[str, str]) -> tuple[str, str]:
    party = pick(fields, PARTY_RX)
    district = pick(fields, DISTRICT_RX)
    if not party or not district:
        # Card subtitles are unlabeled lines; guess by content.
        for v in fields.values():
            v = clean(v)
            if not district and ("district" in v.lower() or "lone" in v.lower()):
                district = v
            elif not party and 1 < len(v) <= 40 and (v.isupper() or "party" in v.lower()):
                party = v
    return party, district
