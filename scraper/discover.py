"""Open arbitrary URLs and print what they contain, for building new parsers.

    python discover.py URL [URL ...]

For each URL: the page title, every JSON response it fetched (URL + a long
excerpt), and the structural summary from inspect_snapshots. Meant to run in
CI (see .github/workflows/discover.yml) when the scraping host can't reach a
site directly.
"""

from __future__ import annotations

import json
import sys

from common import SNAPSHOT_DIR, Browser, log, save_snapshot, slug
from inspect_snapshots import summarize

JSON_EXCERPT = 4000


def main() -> None:
    urls = [u for arg in sys.argv[1:] for u in arg.split()]
    browser = Browser()
    try:
        for url in urls:
            name = "discover-" + slug(url)[:80]
            print(f"\n{'#' * 100}\n# {url}\n{'#' * 100}")
            try:
                cap = browser.open(url)
            except Exception as err:  # noqa: BLE001 - report and move on
                print("FAILED:", err)
                continue
            save_snapshot(name, cap)
            print(f"FINAL URL: {cap.url}")
            print(f"JSON RESPONSES ({len(cap.json_docs)}):")
            for u, body in cap.json_docs:
                if "iconify" in u or "cdn-cgi" in u:
                    continue
                print(f"--- {u}")
                print(json.dumps(body, ensure_ascii=False)[:JSON_EXCERPT])
            summarize(SNAPSHOT_DIR / f"{name}.html")
    finally:
        browser.close()
    log("done")


if __name__ == "__main__":
    main()
