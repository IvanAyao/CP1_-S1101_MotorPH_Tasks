# data-inbox — saved copies of official pages

Some official sites block automated tools (congress.gov.ph and the PSA LGU
directory use Cloudflare bot protection), or only answer visitors in the
Philippines (DILG). Anyone can still open them in a normal browser. Save
the pages here, and the **Import saved pages** workflow turns them into the
app's data and redeploys the site.

| Folder | Save pages from |
|---|---|
| `house/` | https://www.congress.gov.ph/house-members (every page of the list) |
| `lgu/` | https://rssoncr.psa.gov.ph/lgu-directory |
| `barangay/` | https://www.dilg.gov.ph/barangay-officials-directory |
| `senate/` | Not needed: the Senate site is scraped automatically |

## How to save a page

- **Phone (Chrome):** open the page and wait until the list shows, then
  tap ⋮ → ⬇ (Download). This saves an `.mhtml` file.
- **Computer:** open the page and wait until the list shows, then press
  Ctrl+S (⌘S on Mac) and choose *Webpage, Complete* or *Single file*.
- **Excel / CSV downloads** from the agency work too (`.xlsx`, `.csv`).

For long lists split across pages, save each page as a separate file.
For barangay files you can add folders to say where they're from, e.g.
`barangay/Region VII/Bohol/Tagbilaran City/cogon.mhtml`.

## How to upload (works from a phone browser)

1. Open this folder on github.com, e.g.
   `https://github.com/IvanAyao/CP1_-S1101_MotorPH_Tasks/tree/main/data-inbox/house`
2. **Add file → Upload files**, pick the saved files, **Commit changes**.
3. The import runs automatically; the site updates a minute or two later.
   Check progress under the **Actions** tab ("Import saved pages").

Each record is labelled as a saved copy of its official source, with the
date it was imported. An upload that yields no records never wipes
existing data.
