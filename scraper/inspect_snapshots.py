"""Print a compact structural summary of saved page snapshots.

Used in CI so a parser can be fixed from the workflow log alone:
visible text, links, tables, forms/selects, iframes, candidate card groups
and captured JSON responses for each snapshot in scraper/snapshots/.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from bs4 import BeautifulSoup

from common import SNAPSHOT_DIR, clean, extract_cards, looks_like_name

LIMIT = 6000


def summarize(path) -> None:
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    print(f"\n{'=' * 30} {path.name} ({len(html):,} bytes) {'=' * 30}")
    print("TITLE:", clean(soup.title.get_text()) if soup.title else "-")

    for f in soup.find_all("iframe"):
        print("IFRAME:", f.get("src"))
    for form in soup.find_all("form"):
        print("FORM:", form.get("action"), form.get("method"), [
            (i.name, i.get("name") or i.get("id"), i.get("type")) for i in form.find_all(["input", "select", "button"])][:20])
    for s in soup.find_all("select"):
        opts = [clean(o.get_text()) for o in s.find_all("option")]
        print(f"SELECT name={s.get('name')} id={s.get('id')} options({len(opts)}):", opts[:15])

    for i, t in enumerate(soup.find_all("table")):
        rows = t.find_all("tr")
        print(f"TABLE {i}: {len(rows)} rows; class={t.get('class')}")
        for r in rows[:4]:
            print("   |", " | ".join(clean(c.get_text(" "))[:40] for c in r.find_all(["th", "td"])))

    # Repeated element signatures that contain a name.
    sigs = Counter()
    for el in soup.find_all(True):
        cls = ".".join(sorted(el.get("class") or []))
        if cls and looks_like_name(clean(el.get_text(" "))[:80]):
            sigs[f"{el.name}.{cls}"] += 1
    print("NAME-BEARING ELEMENT SIGNATURES:", sigs.most_common(15))

    cards = extract_cards(soup, "https://x/")
    print(f"CARDS picked ({len(cards)}):")
    for c in cards[:40]:
        print("   -", c.name, "|", " / ".join(c.subtitle[:4])[:120], "|", c.href[-60:])

    links = [(clean(a.get_text(" "))[:50], a["href"]) for a in soup.find_all("a", href=True)]
    print(f"LINKS ({len(links)}):")
    for t, h in links[:160]:
        print(f"   {t!r} -> {h[:110]}")

    scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
    print("SCRIPTS:", scripts[:25])
    body = soup.body or soup
    for s in body.find_all(["script", "style", "noscript", "svg"]):
        s.decompose()
    text = clean(body.get_text(" | "))
    print(f"TEXT ({len(text):,} chars):\n{text[:LIMIT]}")

    jpath = path.with_suffix(".json")
    if jpath.exists():
        docs = json.loads(jpath.read_text())
        print(f"JSON RESPONSES ({len(docs)}):")
        for d in docs[:30]:
            body = d["body"]
            shape = type(body).__name__
            if isinstance(body, dict):
                shape += " keys=" + ",".join(list(body)[:12])
            elif isinstance(body, list):
                shape += f" len={len(body)}"
            print(f"   {d['url'][:140]} :: {shape}")
            print("     ", json.dumps(body, ensure_ascii=False)[:600])


def main() -> None:
    global LIMIT
    if len(sys.argv) > 1:
        LIMIT = int(sys.argv[1])
    files = sorted(SNAPSHOT_DIR.glob("*.html"))
    if not files:
        print("no snapshots")
    for f in files:
        summarize(f)


if __name__ == "__main__":
    main()
