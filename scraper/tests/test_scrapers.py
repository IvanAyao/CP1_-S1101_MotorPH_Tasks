"""End-to-end tests of the extraction machinery against local fixture sites.

The fixtures mimic common layouts (card grid, JS + JSON API with pagination,
paginated HTML table, cascading dropdowns). They use fictional names and do
not reflect the real government sites' markup.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from functools import partial
from pathlib import Path
from urllib.parse import unquote

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import barangay  # noqa: E402
import common  # noqa: E402
import house  # noqa: E402
import lgu  # noqa: E402
import senate  # noqa: E402
from common import Browser, extract_cards, looks_like_name, strip_honorific  # noqa: E402
from officials import classify, rows_to_officials  # noqa: E402

FIXTURES = HERE / "fixtures"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/hq/senators/congress/28"):
            self.path = "/hq/senators/congress/28.json"
        if self.path.startswith("/api/members"):
            page = self.path.split("page=")[-1]
            self.path = f"/api/members_page{page}.json"
        if self.path.startswith("/img/"):
            self.send_response(404)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        if self.path.endswith(".json"):
            self.send_header("Content-Type", "application/json")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(FIXTURES)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    b = Browser(delay=0.1)
    yield b
    b.close()


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "SNAPSHOT_DIR", tmp_path / "snap")
    monkeypatch.setattr(common, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(barangay, "OUT_DIR", tmp_path / "data" / "barangay")
    monkeypatch.setattr(barangay, "STATE", tmp_path / "state.json")
    return tmp_path


def test_name_helpers():
    assert looks_like_name("Juan A. Dela Cruz")
    assert looks_like_name("Ma. Teresa B. Santos-Reyes")
    assert not looks_like_name("Home")
    assert not looks_like_name("About the Senate of the Philippines and its many committees")
    assert not looks_like_name("Tel: 8123-4567")
    assert strip_honorific("Hon. Sen. Juan Dela Cruz") == "Juan Dela Cruz"


def test_classify_positions():
    assert classify("Punong Barangay")[0] == "punong_barangay"
    assert classify("Vice Mayor")[0] == "vice_mayor"
    assert classify("SK Chairperson")[0] == "sk_chair"
    assert classify("Barangay Kagawad")[0] == "kagawad"
    assert classify("City Mayor")[0] == "mayor"
    assert classify("Sangguniang Kabataan Chairperson")[0] == "sk_chair"
    assert classify("SK Kagawad")[0] == "sk_kagawad"
    assert classify("Sangguniang Barangay Member")[0] == "kagawad"
    assert classify("Sangguniang Panlungsod Member")[0] == "councilor"


def test_wide_and_long_rows():
    wide = [{"lgu": "Pateros", "mayor": "Hon. Juan Dela Cruz", "vice_mayor": "Maria Santos", "address": "Pateros"}]
    recs = rows_to_officials(wide, source="s", source_url="u", defaults={"region": "NCR"})
    assert {(r["name"], r["level"], r["lgu"]) for r in recs} == {
        ("Juan Dela Cruz", "mayor", "Pateros"), ("Maria Santos", "vice_mayor", "Pateros")}
    long = [{"position": "Punong Barangay", "name": "Pedro Reyes"}]
    recs = rows_to_officials(long, source="s", source_url="u", defaults={"barangay": "Cogon", "lgu": "X"})
    assert recs[0]["level"] == "punong_barangay" and recs[0]["barangay"] == "Cogon"


def test_senate_api_with_menu_noise(site, browser, monkeypatch):
    """Mirrors the live page: a 31-link menu, heading cards, and a JSON API."""
    monkeypatch.setattr(senate, "URL", f"{site}/senate.html")
    recs = senate.scrape(browser)
    assert len(recs) == 24  # inactive senator excluded, menu links ignored
    by_name = {r["name"]: r for r in recs}
    first = by_name["Juan Dela Cruz"]
    assert first["position"] == "Senator · Senate President"
    assert first["photo"].endswith("/hq/uploads/500.jpg")
    assert first["profile_url"].endswith("/senator/Juan-Dela-Cruz")
    assert "Fictional test record number 0" in first["details"]["biography"]
    quoted = by_name['Maria "Ma" B. Santos']
    assert unquote(quoted["profile_url"]).endswith('/senator/Maria-"Ma"-B.-Santos')
    assert quoted["photo"]


def test_senate_cards_fallback(site, browser, monkeypatch):
    monkeypatch.setattr(senate, "URL", f"{site}/senate_cards.html")
    recs = senate.scrape(browser)
    assert len(recs) == 24
    first = recs[0]
    assert first["name"].count(" ") >= 2 and not first["name"].startswith("Sen.")
    assert first["position"] == "Senator · Senate President"
    assert first["profile_url"].endswith("/senators/sen0")
    assert first["photo"].endswith("/img/sen0.jpg")
    assert first["party"] == "NP"


def test_house_json_api_with_pagination(site, browser, monkeypatch):
    monkeypatch.setattr(house, "URL", f"{site}/house.html")
    recs = house.scrape(browser)
    assert len(recs) == 300
    district = [r for r in recs if r["position"] == "District Representative"]
    partylist = [r for r in recs if r["position"] == "Party-list Representative"]
    assert len(district) == 250 and len(partylist) == 50
    assert district[0]["province"] == "Cebu"
    assert district[0]["party"] == "NUP"


def test_lgu_table_pagination(site, browser, monkeypatch):
    monkeypatch.setattr(lgu, "URL", f"{site}/lgu.html")
    lgus, officials = lgu.scrape(browser)
    assert len(lgus) == 17
    assert len(officials) == 34
    pateros = [o for o in officials if o["lgu"] == "Pateros"]
    assert {o["level"] for o in pateros} == {"mayor", "vice_mayor"}
    assert all(o["region"] == "NCR" for o in officials)


def test_barangay_cascading_selects_and_resume(site, browser, monkeypatch, isolated_output):
    monkeypatch.setattr(barangay, "URL", f"{site}/barangay.html")
    import time
    n = barangay.scrape(browser, deadline=time.time() + 120, only_region=None, reset=True)
    assert n == 5 * 4  # 5 barangays x 4 officials
    index = json.loads((isolated_output / "data" / "barangay" / "index.json").read_text())
    assert index["count"] == 20
    assert {f["province"] for f in index["files"]} == {"Bohol", "Benguet"}
    bohol = json.loads((isolated_output / "data" / "barangay" / "region-vii--bohol.json").read_text())
    cogon = [r for r in bohol["records"] if r["barangay"] == "Cogon"]
    assert {r["level"] for r in cogon} == {"punong_barangay", "kagawad", "sk_chair"}
    assert all(r["lgu"] == "Tagbilaran City" for r in cogon)

    # A second run resumes and finds nothing left to do.
    assert barangay.scrape(browser, deadline=time.time() + 120, only_region=None, reset=False) == 0


def test_write_dataset_rejects_bad_counts(isolated_output):
    with pytest.raises(SystemExit):
        common.write_dataset("senate", [], "u", min_count=20)
    assert not (isolated_output / "data" / "senate.json").exists()


def test_waits_past_bot_check_page(site, browser, monkeypatch):
    """congress.gov.ph shows a Cloudflare check page before the real one."""
    monkeypatch.setattr(house, "URL", f"{site}/challenge.html")
    recs = house.scrape(browser)
    assert len(recs) == 300
