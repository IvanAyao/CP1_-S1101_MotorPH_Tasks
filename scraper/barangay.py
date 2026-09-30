"""Barangay officials from the DILG Barangay Officials Directory.

The directory covers ~42,000 barangays, so this scraper is resumable: finished
drill-down paths are stored in scraper/state/barangay_progress.json and each
run continues where the last one stopped (use --max-minutes to fit CI limits).

The directory is browsed by cascading dropdowns (region -> province ->
city/municipality -> barangay). We walk every combination, and at each leaf
harvest the results table (following pagination) plus any JSON the page
fetched. If the page has no dropdowns we just page through its table.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict

from bs4 import BeautifulSoup

from common import (DATA_DIR, ROOT, Browser, all_table_rows, clean, dedupe, flatten,
                    iter_object_lists, log, now_iso, save_snapshot, slug)
from officials import rows_to_officials

URL = "https://www.dilg.gov.ph/barangay-officials-directory"
SOURCE = "DILG – Barangay Officials Directory"
OUT_DIR = DATA_DIR / "barangay"
STATE = ROOT / "scraper" / "state" / "barangay_progress.json"
PLACEHOLDER = re.compile(r"^(-+|select|choose|all|--.*|pumili|please)", re.I)
MAX_PAGES = 200


def level_name(select_meta: dict, idx: int) -> str:
    text = " ".join(select_meta.get(k, "") for k in ("name", "id", "label")).lower()
    for key in ("region", "province", "barangay"):
        if key in text:
            return key
    if re.search(r"city|municipal|lgu|town", text):
        return "lgu"
    return ["region", "province", "lgu", "barangay"][idx] if idx < 4 else f"level{idx}"


def visible_selects(browser: Browser) -> list[dict]:
    return browser.page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('select').forEach((s, i) => {
        const st = getComputedStyle(s);
        if (st.display === 'none' || st.visibility === 'hidden') {
          // select2/chosen hide the real <select>; still usable via select_option
          if (!s.nextElementSibling || !/select2|chosen/.test(s.nextElementSibling.className || '')) return;
        }
        const lab = s.id && document.querySelector(`label[for="${s.id}"]`);
        out.push({
          index: i, name: s.name || '', id: s.id || '',
          label: lab ? lab.innerText : (s.getAttribute('aria-label') || ''),
          options: [...s.options].map(o => ({value: o.value, text: o.text.trim()})),
        });
      });
      return out;
    }""")


def real_options(meta: dict) -> list[dict]:
    return [o for o in meta["options"] if o["value"] and not PLACEHOLDER.match(o["text"])]


def choose(browser: Browser, meta: dict, value: str) -> None:
    browser.reset_capture()
    loc = browser.page.locator("select").nth(meta["index"])
    loc.select_option(value=value, force=True)
    loc.dispatch_event("change")
    try:
        browser.page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    browser.page.wait_for_timeout(int(browser.delay * 1000))


def submit_if_any(browser: Browser) -> None:
    for sel in ("button[type=submit]:visible", "input[type=submit]:visible",
                "button:has-text('Search'):visible", "button:has-text('View'):visible",
                "button:has-text('Filter'):visible"):
        loc = browser.page.locator(sel).first
        try:
            if loc.count():
                browser.reset_capture()
                loc.click(timeout=10_000)
                try:
                    browser.page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    pass
                browser.page.wait_for_timeout(int(browser.delay * 1000))
                return
        except Exception:
            continue


def harvest(browser: Browser) -> list[dict]:
    """All result rows on the current view, following pagination."""
    rows: list[dict] = []
    seen = set()
    for _ in range(MAX_PAGES):
        cap = browser.capture()
        page_rows = [r for t in all_table_rows(BeautifulSoup(cap.html, "lxml")) for r in t]
        for _, doc in cap.json_docs:
            for _, items in iter_object_lists(doc):
                if len(items) >= 2 and any(re.search(r"name|position|barangay", k, re.I) for k in items[0]):
                    page_rows += [flatten(x) for x in items]
        sig = json.dumps(page_rows[:3], sort_keys=True)
        if sig in seen:
            break
        seen.add(sig)
        rows += page_rows
        if not browser.click_next():
            break
    return rows


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"done": [], "started_at": now_iso()}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))


def flush(records: list[dict]) -> None:
    """Merge newly scraped records into per-province files and rebuild the index."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_file[f"{slug(r['region'] or 'unknown')}--{slug(r['province'] or r['lgu'] or 'unknown')}"].append(r)
    for key, new in by_file.items():
        path = OUT_DIR / f"{key}.json"
        old = json.loads(path.read_text())["records"] if path.exists() else []
        replaced = {(r["lgu"], r["barangay"]) for r in new}
        merged = dedupe([r for r in old if (r["lgu"], r["barangay"]) not in replaced] + new)
        path.write_text(json.dumps({
            "dataset": "barangay", "source_url": URL, "scraped_at": now_iso(),
            "region": new[0]["region"], "province": new[0]["province"],
            "count": len(merged), "records": merged,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    write_index()


def write_index() -> None:
    files = []
    for path in sorted(OUT_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        doc = json.loads(path.read_text())
        recs = doc["records"]
        files.append({
            "file": f"barangay/{path.name}",
            "region": doc.get("region", ""),
            "province": doc.get("province", ""),
            "count": doc["count"],
            "barangays": len({(r["lgu"], r["barangay"]) for r in recs if r["barangay"]}),
            "lgus": sorted({r["lgu"] for r in recs if r["lgu"]}),
            "scraped_at": doc["scraped_at"],
        })
    (OUT_DIR / "index.json").write_text(json.dumps({
        "dataset": "barangay", "source_url": URL, "scraped_at": now_iso(),
        "count": sum(f["count"] for f in files), "files": files,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def scrape(browser: Browser, *, deadline: float, only_region: str | None, reset: bool) -> int:
    state = {"done": [], "started_at": now_iso()} if reset else load_state()
    done = set(state["done"])
    cap = browser.open(URL)
    save_snapshot("barangay", cap)
    pending: list[dict] = []
    total = 0

    def leaf(ctx: dict[str, str], key: str) -> None:
        nonlocal total
        submit_if_any(browser)
        rows = harvest(browser)
        recs = rows_to_officials(rows, source=SOURCE, source_url=URL, defaults=ctx)
        log(f"barangay: {' / '.join(ctx.values())} -> {len(recs)} officials")
        pending.extend(recs)
        total += len(recs)
        done.add(key)
        if len(pending) > 2000:
            flush(pending)
            pending.clear()
            state["done"] = sorted(done)
            save_state(state)

    def walk(depth: int, ctx: dict[str, str], path: list[str]) -> bool:
        """Returns False when the time budget ran out."""
        if time.time() > deadline:
            return False
        selects = visible_selects(browser)
        if depth >= len(selects) or not real_options(selects[depth]):
            key = " > ".join(path) or "all"
            if key not in done:
                leaf(ctx, key)
            return True
        meta = selects[depth]
        lvl = level_name(meta, depth)
        for opt in real_options(meta):
            key = " > ".join(path + [opt["text"]])
            if depth == 0 and only_region and only_region.lower() not in opt["text"].lower():
                continue
            if key in done:
                continue
            choose(browser, meta, opt["value"])
            if not walk(depth + 1, {**ctx, lvl: clean(opt["text"])}, path + [opt["text"]]):
                return False
            if depth + 1 < len(visible_selects(browser)):
                done.add(key)  # every child of this option is finished
        return True

    finished = walk(0, {}, [])
    if pending:
        flush(pending)
    state["done"] = sorted(done)
    state["finished"] = finished
    state["updated_at"] = now_iso()
    if finished:
        state["completed_at"] = now_iso()
    save_state(state)
    write_index()
    log(f"barangay: +{total} officials this run; {'complete' if finished else 'paused (time budget), rerun to continue'}")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=300)
    ap.add_argument("--region", help="only scrape regions whose name contains this text")
    ap.add_argument("--reset", action="store_true", help="forget progress and start over")
    ap.add_argument("--delay", type=float, default=0.8, help="seconds between requests")
    args = ap.parse_args()
    browser = Browser(headless=not args.headed, delay=args.delay)
    try:
        scrape(browser, deadline=time.time() + args.max_minutes * 60,
               only_region=args.region, reset=args.reset)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
