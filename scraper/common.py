"""Shared helpers for the Pili.PH scrapers.

The source sites are rendered in a real browser (Playwright) because several of
them build their listings with JavaScript. While a page loads we also capture
every JSON response it fetches: when a site is backed by an API, that JSON is a
far more reliable source than the rendered markup.

Records are extracted from three places, in order of preference:
  1. JSON payloads captured from the page's own network requests
  2. HTML tables
  3. Repeated "cards" (elements holding a name, and usually a photo or link)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "app" / "data"
SNAPSHOT_DIR = ROOT / "scraper" / "snapshots"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 PiliPH-DataBot/1.0 (+civic directory)"
)

NAME_KEYS = ("full_name", "fullname", "name", "member_name", "membername",
             "senator", "representative", "official", "official_name",
             "display_name", "title")
FIRST_KEYS = ("first_name", "firstname", "fname", "given_name")
LAST_KEYS = ("last_name", "lastname", "lname", "surname", "family_name")
MIDDLE_KEYS = ("middle_name", "middlename", "mname", "middle_initial")

INTERSTITIAL = re.compile(
    r"just a moment|performing security verification|checking your browser|attention required",
    re.I,
)

HONORIFICS = re.compile(
    r"^(hon\.?|honorable|sen\.?|senator|rep\.?|representative|cong\.?|"
    r"congressman|congresswoman|mayor|gov\.?|governor|atty\.?|dr\.?|engr\.?)\s+",
    re.I,
)


def log(*args: Any) -> None:
    print(f"[{datetime.now():%H:%M:%S}]", *args, file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(text: Any) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", clean(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def strip_honorific(name: str) -> str:
    name = clean(name)
    prev = None
    while prev != name:
        prev, name = name, HONORIFICS.sub("", name)
    return name


def looks_like_name(text: str) -> bool:
    """A person's name: 2-8 words, mostly letters, no sentence punctuation."""
    text = strip_honorific(text)
    if not 4 <= len(text) <= 80:
        return False
    words = text.replace(",", " ").split()
    if not 2 <= len(words) <= 8:
        return False
    if re.search(r"[!?:;@/|]|https?|www\.|\d{3,}", text):
        return False
    letters = sum(c.isalpha() for c in text)
    return letters / max(len(text.replace(" ", "")), 1) > 0.8


def norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #

def name_from_obj(obj: dict) -> str:
    keys = {norm_key(k): v for k, v in obj.items() if isinstance(v, (str, int))}
    first = next((keys[k] for k in FIRST_KEYS if keys.get(k)), "")
    last = next((keys[k] for k in LAST_KEYS if keys.get(k)), "")
    middle = next((keys[k] for k in MIDDLE_KEYS if keys.get(k)), "")
    if first and last:
        return clean(" ".join(str(p) for p in (first, middle, last) if p))
    for k in NAME_KEYS:
        v = keys.get(k)
        if isinstance(v, str) and looks_like_name(v):
            return clean(v)
    return ""


def iter_object_lists(node: Any, path: str = "$") -> Iterable[tuple[str, list[dict]]]:
    """Yield every list of dicts found anywhere inside a JSON document."""
    if isinstance(node, list):
        dicts = [x for x in node if isinstance(x, dict)]
        if dicts and len(dicts) >= len(node) * 0.8:
            yield path, dicts
        for i, x in enumerate(node[:50]):
            yield from iter_object_lists(x, f"{path}[{i}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from iter_object_lists(v, f"{path}.{k}")


def people_lists_from_json(doc: Any) -> list[list[dict]]:
    """Lists of dicts in which most entries carry a person's name."""
    found = []
    for _, items in iter_object_lists(doc):
        named = [x for x in items if name_from_obj(x)]
        if named and len(named) >= len(items) * 0.6:
            found.append(items)
    return found


def flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts to `a_b` keys holding scalar strings."""
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}{norm_key(k)}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "_"))
        elif isinstance(v, list):
            if v and all(isinstance(x, (str, int, float)) for x in v):
                out[key] = ", ".join(clean(x) for x in v)
            elif v and all(isinstance(x, dict) for x in v):
                names = [clean(x.get("name") or x.get("title") or "") for x in v]
                if any(names):
                    out[key] = ", ".join(n for n in names if n)
        elif v is not None and v != "":
            out[key] = clean(v)
    return out


# --------------------------------------------------------------------------- #
# HTML extraction
# --------------------------------------------------------------------------- #

def table_rows(table: Tag) -> list[dict[str, str]]:
    """Rows of an HTML table as dicts keyed by normalised header text."""
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = None
    thead = table.find("thead")
    if thead and thead.find("tr"):
        header_cells = thead.find("tr").find_all(["th", "td"])
    elif rows[0].find("th"):
        header_cells = rows[0].find_all(["th", "td"])
    headers = [norm_key(c.get_text(" ")) or f"col{i}" for i, c in enumerate(header_cells or [])]

    out = []
    for tr in rows:
        if thead and tr.find_parent("thead"):
            continue
        cells = tr.find_all(["td", "th"])
        if not cells or (header_cells and cells == header_cells):
            continue
        if not tr.find("td"):
            continue
        row: dict[str, str] = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else f"col{i}"
            row[key] = clean(cell.get_text(" "))
            link = cell.find("a", href=True)
            if link and f"{key}__href" not in row:
                row[f"{key}__href"] = link["href"]
            img = cell.find("img")
            if img and img.get("src"):
                row.setdefault("__img", img["src"])
        if any(v for k, v in row.items() if not k.endswith("__href")):
            out.append(row)
    return out


def all_table_rows(soup: BeautifulSoup) -> list[list[dict[str, str]]]:
    return [r for r in (table_rows(t) for t in soup.find_all("table")) if r]


@dataclass
class Card:
    name: str
    subtitle: list[str] = field(default_factory=list)
    href: str = ""
    img: str = ""


def extract_cards(soup: BeautifulSoup, base_url: str) -> list[Card]:
    """Find repeated elements that each hold one person's name.

    We look at every element containing exactly one name-like text node in a
    heading/link/strong, group elements by their tag+class signature, and keep
    the biggest group: listings are almost always a run of identical cards.
    """
    groups: dict[str, list[Card]] = {}
    heading_groups: set[str] = set()
    for el in soup.find_all(["li", "div", "article", "a", "section", "figure"]):
        if el.find_parent(["nav", "header", "footer"]) or el.find_parent(attrs={"role": "navigation"}):
            continue
        name_el = None
        for cand in el.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "a", "span", "p"], limit=12):
            txt = clean(cand.get_text(" "))
            if looks_like_name(txt):
                name_el = cand
                break
        if not name_el:
            continue
        text_len = len(clean(el.get_text(" ")))
        if text_len > 400:  # a container of many cards, not a card
            continue
        sig = el.name + "." + ".".join(sorted(el.get("class") or []))
        name = strip_honorific(clean(name_el.get_text(" ")))
        subtitle = []
        for s in el.stripped_strings:
            s = clean(s)
            if s and s != clean(name_el.get_text(" ")) and len(s) < 120 and s not in subtitle:
                subtitle.append(s)
        a = el if el.name == "a" and el.get("href") else el.find("a", href=True)
        img = el.find("img")
        img_src = ""
        if img:
            img_src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if re.fullmatch(r"h[1-6]", name_el.name):
            heading_groups.add(sig)
        groups.setdefault(sig, []).append(Card(
            name=name,
            subtitle=subtitle[:6],
            href=urljoin(base_url, a["href"]) if a else "",
            img=urljoin(base_url, img_src) if img_src else "",
        ))
    if not groups:
        return []
    # Listings of people title each card with a heading; menus are bare links.
    best_sig = max(groups, key=lambda g: len({c.name for c in groups[g]}) * (2 if g in heading_groups else 1))
    best = groups[best_sig]
    seen, out = set(), []
    for c in best:
        if c.name.lower() not in seen:
            seen.add(c.name.lower())
            out.append(c)
    return out


# --------------------------------------------------------------------------- #
# Browser
# --------------------------------------------------------------------------- #

@dataclass
class Capture:
    url: str
    html: str
    json_docs: list[tuple[str, Any]]


class Browser:
    """Thin Playwright wrapper that records JSON responses per page load."""

    def __init__(self, headless: bool = True, delay: float = 1.0):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # PLAYWRIGHT_CHROMIUM_PATH lets you reuse a preinstalled Chromium.
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") or None
        self._browser = self._pw.chromium.launch(headless=headless, executable_path=exe)
        self._ctx = self._browser.new_context(user_agent=USER_AGENT, locale="en-PH")
        self.page = self._ctx.new_page()
        self.delay = delay
        self._json: list[tuple[str, Any]] = []
        self.page.on("response", self._on_response)

    def _on_response(self, resp) -> None:
        try:
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype or resp.status >= 400:
                return
            self._json.append((resp.url, resp.json()))
        except Exception:
            pass

    def reset_capture(self) -> None:
        self._json = []

    def capture(self) -> Capture:
        self.page.wait_for_timeout(300)
        return Capture(self.page.url, self.page.content(), list(self._json))

    def open(self, url: str, wait_selector: str | None = None, retries: int = 3) -> Capture:
        self.reset_capture()
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                self.wait_past_interstitial()
                try:
                    self.page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    pass
                if wait_selector:
                    self.page.wait_for_selector(wait_selector, timeout=30_000)
                self.scroll_to_bottom()
                time.sleep(self.delay)
                return self.capture()
            except Exception as err:  # noqa: BLE001 - retry any navigation failure
                last_err = err
                log(f"  retry {attempt + 1}/{retries} for {url}: {err}")
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"could not load {url}: {last_err}")

    def wait_past_interstitial(self, timeout_s: float = 90) -> None:
        """Wait while a bot-protection check page is showing.

        Cloudflare shows "Just a moment..." / "Performing security
        verification" and then reloads into the real page on its own.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                title = self.page.title()
                text = self.page.evaluate("document.body ? document.body.innerText.slice(0, 400) : ''")
            except Exception:
                title, text = "", ""  # page is navigating
            if not INTERSTITIAL.search(f"{title} {text}"):
                return
            self.page.wait_for_timeout(2000)
        raise RuntimeError("stuck on a bot-protection check page")

    def scroll_to_bottom(self, max_rounds: int = 30) -> None:
        """Trigger lazy-loaded / infinite-scroll listings."""
        last = -1
        for _ in range(max_rounds):
            height = self.page.evaluate("document.body ? document.body.scrollHeight : 0")
            if height == last:
                break
            last = height
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(600)

    def click_next(self) -> bool:
        """Click a pagination 'next' control if one is enabled. Returns success."""
        selectors = [
            "a[rel=next]",
            ".pagination .next:not(.disabled) a",
            ".pagination li:not(.disabled) a[aria-label*=Next i]",
            ".paginate_button.next:not(.disabled)",
            "button[aria-label*=next i]:not([disabled])",
            "a:has-text('Next'):visible",
            "a:has-text('›'):visible",
            "a:has-text('»'):visible",
        ]
        for sel in selectors:
            loc = self.page.locator(sel).first
            try:
                if loc.count() and loc.is_visible() and loc.is_enabled():
                    cls = (loc.get_attribute("class") or "") + (loc.get_attribute("aria-disabled") or "")
                    if "disabled" in cls or "true" in cls:
                        continue
                    self.reset_capture()
                    loc.click(timeout=10_000)
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        pass
                    time.sleep(self.delay)
                    return True
            except Exception:
                continue
        return False

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def save_snapshot(name: str, cap: Capture) -> None:
    """Keep raw page + JSON for debugging when a site changes its layout."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / f"{name}.html").write_text(cap.html, encoding="utf-8")
    if cap.json_docs:
        (SNAPSHOT_DIR / f"{name}.json").write_text(
            json.dumps([{"url": u, "body": b} for u, b in cap.json_docs], ensure_ascii=False)[:20_000_000],
            encoding="utf-8",
        )


def dedupe(records: list[dict], key=lambda r: (r.get("name", "").lower(), r.get("position", ""), r.get("lgu", ""), r.get("barangay", ""))) -> list[dict]:
    seen, out = set(), []
    for r in records:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def write_dataset(name: str, records: list[dict], source_url: str, *,
                  min_count: int, max_count: int | None = None,
                  path: Path | None = None, extra_meta: dict | None = None) -> Path:
    """Validate and write a dataset. Refuses to overwrite good data with junk."""
    n = len(records)
    if n < min_count or (max_count is not None and n > max_count):
        raise SystemExit(
            f"{name}: got {n} records, expected {min_count}..{max_count or '∞'}; "
            "keeping previous data. Inspect scraper/snapshots/ to update the parser."
        )
    path = path or DATA_DIR / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "dataset": name,
        "source_url": source_url,
        "scraped_at": now_iso(),
        "count": n,
        **(extra_meta or {}),
        "records": records,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{name}: wrote {n} records -> {path}")
    return path


def source_type(url: str) -> str:
    """'official' for Philippine government sites (.gov.ph), else 'public'.

    Every source used is publicly accessible; 'public' marks non-government
    publishers such as Wikipedia or civic open-data projects. 'private' is
    reserved for privately run sources (none are used).
    """
    host = urlparse(url or "").hostname or ""
    return "official" if host == "gov.ph" or host.endswith(".gov.ph") else "public"


def record(*, name: str, position: str, level: str, source: str, source_url: str,
           **fields: Any) -> dict:
    """Build a record in the shared schema used by the app."""
    rec = {
        "id": "",
        "name": strip_honorific(name),
        "position": clean(position),
        "level": level,
        "party": "",
        "district": "",
        "region": "",
        "province": "",
        "lgu": "",
        "barangay": "",
        "photo": "",
        "profile_url": "",
        "contact": "",
        "source": source,
        "source_url": source_url,
        "details": {},
    }
    for k, v in fields.items():
        if k == "details":
            rec["details"] = {kk: clean(vv) for kk, vv in (v or {}).items() if clean(vv)}
        elif v is not None:
            rec[k] = clean(v)
    rec["source_type"] = source_type(rec["source_url"])
    rec["id"] = slug("-".join(p for p in (level, rec["province"], rec["lgu"], rec["barangay"], rec["district"], rec["name"]) if p))
    return rec


def pick(row: dict[str, str], *patterns: str) -> str:
    """First non-empty value whose key matches any regex pattern."""
    for pat in patterns:
        rx = re.compile(pat)
        for k, v in row.items():
            if k.endswith("__href"):
                continue
            if rx.search(k) and clean(v):
                return clean(v)
    return ""
