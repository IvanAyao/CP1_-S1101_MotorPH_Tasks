"""Run every scraper and rebuild app/data/manifest.json.

Each scraper is independent: one failing (site down, layout changed) keeps its
previous data and does not block the others. Exit code is non-zero if any
failed, so CI surfaces it.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback

from common import DATA_DIR, Browser, log, now_iso, source_type, write_dataset
import barangay
import bills
import dilg_lgu
import dilg_regions
import house
import lgu
import senate
import wikipedia

DATASETS = {
    "senate": ("senate.json", senate.URL, "Senate of the Philippines"),
    "house": ("house.json", house.URL, "House of Representatives"),
    "lgu": ("lgu.json", lgu.URL, lgu.SOURCE),
    "barangay": ("barangay/index.json", barangay.URL, barangay.SOURCE),
}


def build_manifest() -> None:
    entries = []
    for key, (file, url, label) in DATASETS.items():
        path = DATA_DIR / file
        meta = {"key": key, "file": file, "source": label, "source_url": url,
                "count": 0, "scraped_at": None}
        meta["source_type"] = source_type(url)
        if path.exists():
            doc = json.loads(path.read_text())
            if doc.get("source_label"):
                label = doc["source_label"]
                meta.update(source=label, source_url=doc.get("source_url", url))
            meta.update(count=doc.get("count", 0), scraped_at=doc.get("scraped_at"))
            method = doc.get("method", "")
            if method == "wikipedia":
                meta["source_type"] = "public"
            elif method == "official+wikipedia":
                meta["source_type"] = "official+public"
            if method == "wikipedia":
                meta.update(source="Wikipedia (unofficial)", source_url=doc.get("source_url", url))
            elif method == "official+wikipedia":
                meta["source"] = f"{label} + Wikipedia (unofficial)"
            elif method == "saved-copy":
                meta["source"] = f"{label} (saved copy, {doc.get('copied_on', '')})"
        entries.append(meta)
        bills_src = doc.get("bills_source") if key == "senate" and path.exists() else None
        if bills_src:
            entries.append({"key": "bills", "file": file, "source": f"Senate bills · {bills_src['name']}",
                            "source_url": bills_src["url"], "source_type": bills_src.get("source_type", "public"),
                            "count": bills_src.get("bill_count", 0), "scraped_at": bills_src.get("imported_at"),
                            "as_of": bills_src.get("as_of")})
    (DATA_DIR / "manifest.json").write_text(json.dumps(
        {"generated_at": now_iso(), "datasets": entries}, indent=1, ensure_ascii=False))
    log("manifest rebuilt")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", choices=list(DATASETS), help="subset to run")
    ap.add_argument("--barangay-minutes", type=float, default=240)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    wanted = args.only or list(DATASETS)

    failures = []
    browser = Browser(headless=not args.headed)
    try:
        for key in ("senate", "house", "lgu"):
            if key not in wanted:
                continue
            try:
                if key == "senate":
                    write_dataset("senate", senate.scrape(browser), senate.URL, min_count=20, max_count=26)
                elif key == "house":
                    write_dataset("house", house.scrape(browser), house.URL, min_count=250, max_count=340)
                else:
                    lgus, officials = lgu.scrape(browser)
                    write_dataset("lgu", officials, lgu.URL, min_count=10,
                                  extra_meta={"lgus": lgus, "lgu_count": len(lgus)})
            except (Exception, SystemExit) as err:  # noqa: BLE001
                log(f"{key} FAILED: {err}")
                traceback.print_exc()
                failures.append(key)
        # Official DILG directory of elected LGU officials (FOI release).
        if "lgu" in wanted:
            try:
                dilg_lgu.merge_into_lgu(dilg_lgu.run(browser))
            except (Exception, SystemExit) as err:  # noqa: BLE001
                log(f"dilg FAILED: {err}")
                traceback.print_exc()
                failures.append("dilg")
        # DILG regional offices' published lists (official).
        if "lgu" in wanted:
            try:
                dilg_regions.run(browser)
            except (Exception, SystemExit) as err:  # noqa: BLE001
                log(f"dilg-region FAILED: {err}")
                traceback.print_exc()
                failures.append("dilg-region")
        # Senate bills per senator (public BetterGov dataset, labelled as such).
        if "senate" in wanted:
            try:
                bills.run()
            except (Exception, SystemExit) as err:  # noqa: BLE001
                log(f"bills FAILED: {err}")
                traceback.print_exc()
                failures.append("bills")
        # Where official sites block us, fill gaps from Wikipedia (labelled
        # unofficial). Official records are never replaced.
        fallback = [k for k, want in (("house", "house"), ("governors", "lgu"), ("mayors", "lgu")) if want in wanted]
        if fallback:
            try:
                wikipedia.run(fallback)
            except (Exception, SystemExit) as err:  # noqa: BLE001
                log(f"wikipedia FAILED: {err}")
                traceback.print_exc()
                failures.append("wikipedia")
        if "barangay" in wanted:
            try:
                barangay.scrape(browser, deadline=time.time() + args.barangay_minutes * 60,
                                only_region=None, reset=False)
            except Exception as err:  # noqa: BLE001
                log(f"barangay FAILED: {err}")
                traceback.print_exc()
                failures.append("barangay")
    finally:
        browser.close()
        build_manifest()

    if failures:
        raise SystemExit(f"failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
