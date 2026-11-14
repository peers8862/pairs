"""Characterisation tests for the /api/search argument-injection guard.

The guard lives in lib/report_builder.py::safe_query_terms (shared with
the report builder's CLI/web paths); modules/web.py::_safe_query_terms
is only the local name delegating to it, and the guard is only
reachable through the app, so these tests exercise it through POST
/api/search with a fixture journal, which is also the behaviour that
matters: a smuggled leading-dash term must be rejected, and prefix
queries (amt:/type:/expr:) must keep working.

Landmine (TODO.md): do NOT "fix" the guard by inserting a '--' separator
before the query terms. hledger stops parsing prefix: query syntax after
'--', so amt:>100 would silently match nothing. The leading-dash rejection
is the whole guard. test_amt_prefix_query_still_matches is the regression
test for that: it fails if a '--' ever appears in the hledger argv.

Requires FastAPI + TestClient (README.md documents `pip install fastapi
uvicorn` in .venv) and hledger on PATH; skipped otherwise, following the
existing needs_hledger pattern. No entity data is created: the journal path
is monkeypatched to a tmp fixture journal, never the real entities/ tree.
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

"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    journal = tmp_path / "company.journal"
    journal.write_text(JOURNAL)
    # _get_journal_path() reads the module-global get_entity_journal; point
    # it at the fixture instead of the real (user-owned) entities/ tree.
    monkeypatch.setattr(web, "get_entity_journal", lambda: journal)
    return TestClient(web.create_app())


def _search(client, query, mode="register"):
    resp = client.post("/api/search", json={"query": query, "mode": mode})
    assert resp.status_code == 200, resp.text
    return resp.json()


@needs_hledger
def test_amt_prefix_query_still_matches(client):
    """amt:>100 must return the 500 row and not the 50 row.

    Regression test for the '--' landmine: if a '--' separator were ever
    inserted before the query terms, hledger would stop parsing the amt:
    prefix and this would return zero entries instead of one.
    """
    data = _search(client, "amt:>100")
    assert data["ok"] is True
    assert data["query"] == "amt:>100"  # echoed verbatim, no '--' added
    assert data["total"] == 1
    assert data["entries"][0]["description"] == "Big purchase"


@needs_hledger
def test_plain_term_query_passes(client):
    data = _search(client, "Supplies")
    assert data["ok"] is True
    assert data["total"] == 2


@needs_hledger
def test_quoted_term_with_space_passes(client):
    data = _search(client, 'desc:"Big purchase"')
    assert data["ok"] is True
    assert data["total"] == 1
    assert data["entries"][0]["description"] == "Big purchase"


@needs_hledger
def test_leading_dash_output_file_rejected(client):
    """A smuggled --output-file= must never reach hledger's argv."""
    data = _search(client, "--output-file=/tmp/x")
    assert data["ok"] is False
    assert data["entries"] == []
    assert data["total"] == 0
    assert "-" in data["error"]


@needs_hledger
def test_leading_dash_flag_rejected(client):
    data = _search(client, "-f /etc/passwd")
    assert data["ok"] is False
    assert data["entries"] == []
    assert data["total"] == 0


@needs_hledger
def test_dash_after_a_good_term_rejected(client):
    """The guard applies to every term, not just the first."""
    data = _search(client, "Supplies --output-file=/tmp/x")
    assert data["ok"] is False
    assert data["entries"] == []


@needs_hledger
def test_unbalanced_quotes_reported(client):
    data = _search(client, 'desc:"oops')
    assert data["ok"] is False
    assert "nbalanced" in data["error"]
