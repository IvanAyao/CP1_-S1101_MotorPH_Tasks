"""State of the Nation Address transcripts, from official copies uploaded by hand.

The official transcripts (Official Gazette, Presidential Communications
Office) sit behind bot protection, which is not bypassed. A person saves the
transcript from a normal browser and uploads it to data-inbox/sona/:

    .html/.htm   "Save page as"
    .mhtml/.mht  Chrome "Download page" (keeps the page's address)
    .pdf         the official PDF
    .txt         plain text

Optionally add the page address in a file with the same name ending in
".url" (e.g. 2024-07-22.pdf + 2024-07-22.url). MHTML files carry it already.

Each transcript is matched to a President by its date (from the file name,
e.g. 2024-07-22.pdf, or the first date in the text). Only copies whose
address is on an official government site are kept as official; copies
without an address are kept and labelled as of unrecorded origin.

From each speech, sentences that report something done, with a figure
(e.g. "we have built 5,000 classrooms"), are quoted word for word and
grouped by sector. They are the President's own claims, not verified, and
the extraction is automatic, so the app links the full transcript.
"""

from __future__ import annotations

import argparse
import email
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import common
from common import ROOT, clean, log

INBOX = ROOT / "data-inbox" / "sona"
EXTS = {".html", ".htm", ".mhtml", ".mht", ".pdf", ".txt"}
MAX_HIGHLIGHTS = 80

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
DATE_TEXT = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
DATE_NAME = re.compile(r"(\d{4})[-_.](\d{2})[-_.](\d{2})")

# A reported result: a figure plus a verb of something done (English, or a
# Filipino verb in the completed aspect), and no future or wish wording.
FIGURE = re.compile(r"\d")
DONE_EN = re.compile(
    r"\b(have|has|had)\s+(?:\w+\s+){0,2}?(built|constructed|completed|distributed|created|generated|provided|delivered|"
    r"achieved|lifted|reduced|increased|opened|installed|hired|enrolled|released|awarded|connected|energized|"
    r"rehabilitated|repaired|served|vaccinated|insured|signed|approved|passed|paid|planted|trained|rescued|"
    r"arrested|recovered|collected|saved|added|expanded|restored|finished|given|benefited|reached|exceeded|"
    r"surpassed|attracted|issued|launched|funded|allocated|granted|covered|cut|brought|helped|assisted)\b"
    r"|\b(built|constructed|completed|distributed|created|generated|delivered|achieved|lifted|reduced|opened|"
    r"installed|hired|enrolled|released|awarded|energized|rehabilitated|vaccinated|planted|trained|rescued|"
    r"recovered|collected|expanded|restored|finished|benefited|exceeded|surpassed|attracted|launched|granted|"
    r"rose|grew|fell|declined|dropped|went up|went down|increased|decreased)\b", re.I)
DONE_TL_WORDS = re.compile(r"\b(naipatayo|naitayo|natapos|naipamahagi|nabigyan|naipasa|nakapagtapos|natulungan|"
                           r"tumaas|bumaba|lumago|naibaba|naitaas|nakumpleto|naayos|nailunsad|naipagawa|nakapagpatayo|"
                           r"nakapagbigay|naibigay|naihatid|nakinabang|naabot|nalampasan|naaresto|nasamsam)\b", re.I)
FUTURE = re.compile(r"\b(will|shall|would|going to|plan|plans|aim|aims|target|targets|propose|proposes|urge|urging|"
                    r"ask (?:congress|you)|hope|let us|must|should|by 20\d\d|gagawin|gagawa|isusulong|itatayo|"
                    r"magpapatayo|ipapasa|sana|dapat|hinihiling|nais|plano|layunin|tutulong|bibigyan|ibibigay)\b", re.I)

SECTORS = [
    ("agriculture", r"farm|rice|palay|magsasaka|irrigat|agricultur|fisher|mangingisda|corn|coconut|niyog|livestock|food"),
    ("health", r"health|hospital|ospital|philhealth|vaccin|bakuna|doctor|nurse|medical|medicine|gamot|kalusugan|patient"),
    ("education", r"school|classroom|teacher|student|paaralan|guro|estudyante|scholar|tuition|universit|college|learner|deped|tesda"),
    ("infrastructure", r"road|bridge|airport|port|rail|subway|expressway|kalsada|tulay|daan|build|infrastructure|flood|dam|housing|pabahay"),
    ("energy", r"power|electric|kuryente|energy|megawatt|internet|wi-?fi|digital|broadband|water|tubig|tower"),
    ("labor", r"\bjobs?\b|trabaho|employ|hanapbuhay|worker|manggagawa|\bofws?\b|migrant|wage|sahod|livelihood"),
    ("social", r"4ps|pantawid|ayuda|cash|assistance|tulong|poor|mahirap|senior|pwd|indigent|feeding|social pension|family|pamilya"),
    ("public_order", r"drug|droga|crime|krimen|police|pulis|pnp|shabu|illegal|terror|insurgen|npa|rebel|peace|kapayapaan"),
    ("defense", r"\bafp\b|military|militar|navy|coast guard|west philippine sea|sovereign|soldier|sundalo|defen"),
    ("economy", r"gdp|econom|ekonomiya|invest|inflation|poverty|kahirapan|revenue|tax|buwis|export|tourist|tourism|growth|peso|budget|trade|credit rating|debt"),
    ("governance", r"corrupt|katiwalian|government service|bureaucra|e-?gov|national id|philsys|red tape|ease of doing"),
    ("environment", r"environment|kalikasan|climate|forest|tree|puno|mining|disaster|typhoon|bagyo|waste|pollution"),
]


def sector_of(text: str) -> str:
    for key, rx in SECTORS:
        if re.search(rx, text, re.I):
            return key
    return "other"


def read_file(path: Path) -> tuple[str, str]:
    """Plain text of a transcript, and the address it was saved from (if known)."""
    ext = path.suffix.lower()
    url = ""
    side = path.with_suffix(".url")
    if side.exists():
        found = re.search(r"https?://\S+", side.read_text(encoding="utf-8", errors="replace"))
        url = found.group(0) if found else ""
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages), url
    raw = path.read_bytes()
    if ext == ".txt":
        return raw.decode("utf-8", errors="replace"), url
    html = ""
    if ext in {".mhtml", ".mht"}:
        msg = email.message_from_bytes(raw)
        url = url or clean(msg.get("Snapshot-Content-Location", ""))
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
                break
    else:
        html = raw.decode("utf-8", errors="replace")
        saved = re.search(r"<!-- saved from url=\(\d+\)(\S+) -->", html)
        url = url or (saved.group(1) if saved else "")
    soup = BeautifulSoup(html, "lxml")
    if not url:
        canon = soup.find("link", rel="canonical") or soup.find("meta", property="og:url")
        url = (canon.get("href") or canon.get("content") or "") if canon else ""
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    # The speech is the element holding the most paragraph text.
    best = max(soup.find_all(["article", "main", "div", "section"]) or [soup],
               key=lambda el: sum(len(p.get_text()) for p in el.find_all("p", recursive=False)), default=soup)
    paras = [p.get_text(" ", strip=True) for p in best.find_all("p")] or [soup.get_text("\n")]
    return "\n".join(paras), url


def speech_date(path: Path, text: str) -> str:
    m = DATE_NAME.search(path.stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for m in DATE_TEXT.finditer(text[:3000]):
        d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        if 1935 <= d.year <= date.today().year:
            return d.isoformat()
    return ""


def is_official(url: str) -> bool:
    """Government sites (Official Gazette, PCO, etc.) are all under .gov.ph."""
    return (urlparse(url).hostname or "").endswith(".gov.ph")


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.replace(" ", " "))
    # Split after . ! ? unless it ends a number or an abbreviation like "No." or "Php".
    parts = re.split(r"(?<!\b[A-Z])(?<!\bNo)(?<!\bSt)(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<=[.!?])\s+(?=[A-Z“\"‘'])", text)
    return [clean(p) for p in parts if p.strip()]


def highlights(text: str) -> list[dict]:
    out, seen = [], set()
    for s in sentences(text):
        # A figure that is more than a date or a year.
        figures = re.sub(r"\b(19|20)\d\d\b", "", DATE_TEXT.sub("", s))
        if not 30 <= len(s) <= 450 or not FIGURE.search(figures) or FUTURE.search(s):
            continue
        if not (DONE_EN.search(s) or DONE_TL_WORDS.search(s)):
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"text": s, "sector": sector_of(s)})
    return out[:MAX_HIGHLIGHTS]


def president_on(day: str, presidents: list[dict]) -> dict | None:
    for p in presidents:
        for t in p.get("terms", []):
            if t["start"] <= day and (not t["end"] or day <= t["end"]):
                return p
    return None


def run(inbox: Path = INBOX) -> dict:
    exe = json.loads((common.DATA_DIR / "executive.json").read_text(encoding="utf-8"))
    presidents = [r for r in exe["records"] if r["level"] == "president"]
    paths = sorted(p for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in EXTS) if inbox.is_dir() else []
    speeches = []
    for path in paths:
        name = path.relative_to(inbox)
        text, url = read_file(path)
        day = speech_date(path, text)
        if len(text) < 2000:
            log(f"  {name}: too little text ({len(text)} characters); skipped")
            continue
        who = president_on(day, presidents) if day else None
        if not who:
            log(f"  {name}: no date or no President for {day or 'unknown date'}; name the file YYYY-MM-DD.<ext>")
            continue
        found = highlights(text)
        official = is_official(url)
        speeches.append({
            "date": day, "president_id": who["id"], "president": who["name"], "file": str(name),
            "source_url": url if url.startswith("http") else "",
            "source_type": "official" if official else "unknown",
            "source": "Official transcript (saved copy)" if official else "Uploaded transcript (origin not recorded)",
            "words": len(text.split()), "highlights": found,
        })
        log(f"  {name}: {who['name']}, {day}, {len(found)} reported results")
    speeches.sort(key=lambda s: s["date"])
    # One transcript per date: prefer an official copy.
    by_day: dict[str, dict] = {}
    for s in speeches:
        if s["date"] not in by_day or (s["source_type"] == "official" and by_day[s["date"]]["source_type"] != "official"):
            by_day[s["date"]] = s
    speeches = list(by_day.values())
    if not speeches:
        raise SystemExit("sona: no usable transcripts in data-inbox/sona; keeping previous data")
    doc = {"source": "State of the Nation Address transcripts (official copies uploaded by hand)",
           "as_of": date.today().isoformat(), "count": len(speeches),
           "note": "Highlights are sentences quoted word for word that report a result with a figure; they are the "
                   "President's own claims, not independently verified, and are picked automatically.",
           "speeches": speeches}
    (common.DATA_DIR / "sona.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"sona: {len(speeches)} speeches")
    return doc


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    run()


if __name__ == "__main__":
    main()
