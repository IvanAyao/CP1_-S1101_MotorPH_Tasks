# Pili.PH — Philippine Officials Directory

A mobile-first web app for finding, comparing and shortlisting Philippine elected
officials: Senators, House Representatives, LGU officials and Barangay officials.
All data is scraped automatically from official government websites. Nothing
is entered by hand.

| Tab | What it does |
|---|---|
| **Opisyal** | Search every official. Filter by Senado / Kamara / Gobernador / Alkalde / Konsehal / Barangay |
| **Hanapin** | Browse by place: Region → Province → City/Municipality → Barangay |
| **Ihambing** | Compare two officials side by side |
| **Pili Ko** | Build your 2028 shortlist (saved only on the device, shareable as text), with a countdown to election day (May 8, 2028) |
| **Datos** | Counts, party breakdown, sources and last-updated dates |

Every profile links back to its official source page and shows when it was last scraped.

## Data sources

| Dataset | Source | Refresh |
|---|---|---|
| Senate (20th Congress) | https://senate.gov.ph/senators/20-congress-senators | weekly |
| House of Representatives | https://www.congress.gov.ph/house-members | weekly |
| LGU directory (NCR) | https://rssoncr.psa.gov.ph/lgu-directory | weekly |
| Barangay officials | https://www.dilg.gov.ph/barangay-officials-directory | daily chunks until complete, resumable |

## Layout

```
app/                 static site (no build step), deployed to GitHub Pages
  data/              JSON written by the scrapers
    manifest.json    dataset list, counts, timestamps
    barangay/        one file per province + index.json (loaded lazily)
scraper/             Python + Playwright scrapers
  common.py          browser, JSON/table/card extraction, validation, output
  senate.py house.py lgu.py barangay.py
  run_all.py         runs everything, rebuilds manifest.json
  tests/             end-to-end tests against local fixture sites
.github/workflows/
  scrape.yml         scheduled scraping, commits data back to the repo
  pages.yml          deploys app/ to GitHub Pages
  test.yml           scraper tests
```

## How the scrapers work

Each source is loaded in headless Chromium, so JavaScript-built listings still
render. Every JSON response the page fetches is also captured. Records are taken
from, in order of preference, captured JSON APIs, then HTML tables, then repeated
"card" elements. Pagination ("Next" links/buttons) and infinite scroll are followed.

The DILG directory is walked through its cascading dropdowns (region → province →
city → barangay). Progress is saved in `scraper/state/barangay_progress.json`, so
each run continues where the last one stopped.

**Safety rails:** a dataset is only written if its record count is plausible
(e.g. 20–26 senators, 250–340 representatives). Otherwise the previous data is
kept and the workflow fails loudly. Raw page snapshots are uploaded as a workflow
artifact so a layout change can be diagnosed.

## Running locally

```bash
pip install -r scraper/requirements.txt
python -m playwright install chromium

cd scraper
python run_all.py --only senate house lgu     # quick datasets
python barangay.py --region "Region VII" --max-minutes 30
python -m pytest tests -q

# serve the app
cd ../app && python -m http.server 8000       # http://localhost:8000
```

`PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome` reuses an existing Chromium.

## Launch checklist

1. Merge to `main`.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Actions → "Scrape official data" → Run workflow** (leave "only" empty) for the
   first data load. Check the run log and, if anything failed, the `snapshots-*` artifact.
4. `pages.yml` redeploys automatically after each scrape.

## Notes

- The earlier mockup showed performance scores, attendance, bills passed and SALN
  figures. None of the four sources publish those, so the app does not show them
  rather than invent numbers. They can be added once a source is chosen
  (e.g. Senate/House legislative records, the Ombudsman for SALN).
- The PSA RSSO NCR directory covers NCR LGUs only. Governors and mayors outside
  NCR need an additional source.
- Not affiliated with any government agency, party or candidate.
