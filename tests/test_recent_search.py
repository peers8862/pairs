"""Consolidate /api/recent onto /api/search (I65).

Before this batch the two endpoints ran two separate hledger-register
implementations that could drift:
- GET /api/recent: hand-rolled CSV splitting (line.split('","')),
  its own grouping, limit/offset pagination, and an `or desc:` query
  so a bare term also matches descriptions. Backs the Dash register
  pagination (web/index.html loadRecords).
- POST /api/search: csv.DictReader + _group_search_rows, limit only
  (no offset), raw query or composed fields, mode register|print.

After: one shared runner (_run_hledger_csv) and one grouper
(_group_search_rows) behind both. /api/search gains `offset`
(default 0, so existing callers are unaffected); /api/recent is a
thin wrapper that keeps its exact response shape
{entries, total, offset, limit} and its `or desc:` semantics. Both
paths still go through _safe_query_terms — the consolidation must
never weaken the leading-dash guard.

The Dash register only reads id/date/description and
postings[].account/amount, so the shared grouper's extra fields
(code, per-posting total) are additive and safe there.
"""

import shutil

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import modules.web as web  # noqa: E402

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

JOURNAL = """2026-01-05 * Big purchase
    Expenses:Operating:Supplies    CAD 500.00
    Assets:Current:Chequing        CAD -500.00

2026-01-06 * Small purchase
    Expenses:Operating:Supplies    CAD 50.00
    Assets:Current:Chequing        CAD -50.00

2026-01-07 * Tiny purchase
    Expenses:Operating:Supplies    CAD 5.00
    Assets:Current:Chequing        CAD -5.00

2026-01-08 * Client invoice
    Assets:Current:Chequing        CAD 1000.00
    Income:Services                CAD -1000.00

2026-01-09 * Rent
    Expenses:Operating:Rent        CAD 800.00
    Assets:Current:Chequing        CAD -800.00
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    journal = tmp_path / "company.journal"
    journal.write_text(JOURNAL)
    monkeypatch.setattr(web, "get_entity_journal", lambda: journal)
    return TestClient(web.create_app())


def _shape(entries):
    """The contract the Dash register depends on: identity, order, postings."""
    return [(e["id"], e["date"], e["description"],
             [(p["account"], p["amount"]) for p in e["postings"]])
            for e in entries]


def _recent(client, **params):
    resp = client.get("/api/recent", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _search(client, **body):
    resp = client.post("/api/search", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


@needs_hledger
def test_recent_and_search_agree_on_entries_and_total(client):
    recent = _recent(client, limit=100, offset=0)
    search = _search(client, query="", mode="register", limit=100)
    assert recent["total"] == 5
    assert search["total"] == 5
    assert _shape(recent["entries"]) == _shape(search["entries"])
    # Newest first on both.
    assert recent["entries"][0]["description"] == "Rent"
    assert recent["entries"][-1]["description"] == "Big purchase"


@needs_hledger
def test_search_offset_paginates_like_recent(client):
    recent = _recent(client, limit=2, offset=2)
    search = _search(client, query="", mode="register", limit=2, offset=2)
    assert recent["total"] == 5 and search["total"] == 5
    assert _shape(recent["entries"]) == _shape(search["entries"])
    assert [e["description"] for e in recent["entries"]] == [
        "Tiny purchase", "Small purchase"]


@needs_hledger
def test_search_offset_beyond_total_returns_empty_page(client):
    search = _search(client, query="", mode="register", limit=2, offset=99)
    assert search["entries"] == []
    assert search["total"] == 5
    recent = _recent(client, limit=2, offset=99)
    assert recent["entries"] == []
    assert recent["total"] == 5


@needs_hledger
def test_recent_keeps_response_shape(client):
    data = _recent(client, limit=2, offset=1)
    assert data["offset"] == 1 and data["limit"] == 2
    assert len(data["entries"]) == 2
    first = data["entries"][0]
    assert first["description"] == "Client invoice"
    assert first["postings"][0]["account"] == "Assets:Current:Chequing"


@needs_hledger
def test_recent_bare_term_still_matches_description(client):
    """The `or desc:` behaviour is recent's, and the consolidation keeps it:
    'Small' is a description word, not an account name."""
    data = _recent(client, limit=100, offset=0, query="Small")
    assert [e["description"] for e in data["entries"]] == ["Small purchase"]


@needs_hledger
def test_guard_rejects_leading_dash_on_both_paths(client):
    recent = _recent(client, limit=100, offset=0, query="-f /etc/passwd")
    assert recent["entries"] == []
    assert "cannot start with '-'" in recent.get("error", "")
    search = _search(client, query="-f /etc/passwd", mode="register")
    assert search["ok"] is False
    assert search["entries"] == []
    assert "cannot start with '-'" in search["error"]


@needs_hledger
def test_search_print_mode_unaffected_by_offset(client):
    data = _search(client, query="acct:Expenses", mode="print",
                   limit=10, offset=0)
    assert data["ok"] is True
    assert data["mode"] == "print"
    assert data["total"] == 4  # Big, Small, Tiny, Rent
    page = _search(client, query="acct:Expenses", mode="print",
                   limit=2, offset=2)
    assert page["total"] == 4
    assert len(page["entries"]) == 2
    assert page["entries"] != data["entries"][:2]
