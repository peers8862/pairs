"""Inventory / COGS module (I68) — full module: stock quantities, cost
layering (FIFO/LIFO/average), purchase costing, sales reducing inventory.

Design (owner-scoped full, 2026-11-14):
- Data lives in the YAML store, `inventory/<slug>.yaml` (lib.yaml_store,
  same pattern as assets): {name, slug, unit, method, layers}. Layers are
  stored as strings ({qty, unit_cost, date}) because yaml.safe_dump cannot
  represent Decimal.
- Costing method is per-item, chosen at `add` (--method fifo|lifo|average,
  default fifo). No entity-wide default — different goods may need
  different methods.
- Accounts: a single `Assets:Inventory` for all items (the YAML is the
  per-item truth), `Expenses:COGS` (first of the lib.statements COGS tuple,
  so the P&L reads it), `Income:Sales`, bank from config `accounts.bank`
  (default Assets:Current:Chequing, the repo-wide convention).
- A purchase writes one entry, pair 1011 (asset/asset, same as a cash
  asset acquisition in docs/journal-rules.md).
- A sale writes TWO 2-posting entries, because the repo's own
  lib.entry.infer_pair returns COMPOUND for anything but 2 postings — one
  4-posting entry cannot honestly carry a single pair code. Revenue leg:
  pair 0100 (operating revenue vs asset: bank vs Income:Sales). COGS leg:
  pair 0000 (operating expense vs asset: Expenses:COGS vs
  Assets:Inventory). Both entries are tagged item:<slug>.
- One truth for inventory: every buy/sell writes the journal AND updates
  the YAML, so the YAML layer total always equals the hledger
  Assets:Inventory balance; `pair inventory check` verifies exactly that.
  Oversell / unknown item fail with a clear message + exit 1 and write
  nothing (cost is computed before any write happens).

Tests drive the CLI against a tmp entity dir (the tests/test_asset_transfer
pattern) — no real entity data is touched. Requires hledger on PATH for
the balance assertions.
"""

import shutil
import subprocess
from decimal import Decimal

import pytest
import yaml

import lib.helpers as H
import lib.ui as UI
import lib.inventory as INV
import modules.inventory as M
from lib.yaml_store import load_entity, save_entity

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

D = Decimal


# ─── costing engine ─────────────────────────────────────────────────────────

def _layers(*specs):
    """specs: (qty, unit_cost, date) tuples → engine layers."""
    return [INV.layer(D(q), D(c), d) for q, c, d in specs]


def test_fifo_consumes_oldest_first():
    layers = _layers((10, "5.00", "2026-01-05"), (10, "7.00", "2026-01-20"))
    cost, rest = INV.sell(layers, "fifo", D(12))
    assert cost == D("64.00")  # 10x5.00 + 2x7.00
    assert INV.on_hand_qty(rest) == D(8)
    assert INV.on_hand_value(rest) == D("56.00")  # 8 @ 7.00
    assert rest == [INV.layer(D(8), D("7.00"), "2026-01-20")]


def test_lifo_consumes_newest_first():
    layers = _layers((10, "5.00", "2026-01-05"), (10, "7.00", "2026-01-20"))
    cost, rest = INV.sell(layers, "lifo", D(12))
    assert cost == D("80.00")  # 10x7.00 + 2x5.00
    assert INV.on_hand_qty(rest) == D(8)
    assert INV.on_hand_value(rest) == D("40.00")  # 8 @ 5.00


def test_average_uses_running_average():
    layers = _layers((10, "5.00", "2026-01-05"))
    layers = INV.add_purchase(layers, "average", D(10), D("7.00"), "2026-01-20")
    assert INV.on_hand_value(layers) == D("120.00")
    cost, rest = INV.sell(layers, "average", D(12))
    assert cost == D("72.00")  # 12 x 6.00 average
    assert INV.on_hand_value(rest) == D("48.00")  # 8 @ 6.00


def test_average_rounds_cost_to_cents():
    layers = _layers((3, "10.00", "2026-01-05"))
    layers = INV.add_purchase(layers, "average", D(1), D("10.01"), "2026-01-06")
    assert INV.on_hand_value(layers) == D("40.01")
    cost, rest = INV.sell(layers, "average", D(1))
    assert cost == D("10.00")  # 10.0025 rounds half-up to 10.00
    assert INV.on_hand_value(rest) == D("30.01")  # value kept exact


def test_sell_all_empties_layers():
    layers = _layers((5, "2.00", "2026-01-05"))
    cost, rest = INV.sell(layers, "fifo", D(5))
    assert cost == D("10.00")
    assert rest == []
    assert INV.on_hand_qty(rest) == D(0)
    assert INV.on_hand_value(rest) == D("0.00")


def test_oversell_raises_and_leaves_layers_untouched():
    layers = _layers((5, "2.00", "2026-01-05"))
    with pytest.raises(INV.InsufficientStockError):
        INV.sell(layers, "fifo", D(6))
    assert INV.on_hand_qty(layers) == D(5)


def test_unknown_method_raises():
    layers = _layers((5, "2.00", "2026-01-05"))
    with pytest.raises(ValueError):
        INV.sell(layers, "weighted", D(1))


def test_layer_yaml_round_trip():
    layers = _layers((10, "5.00", "2026-01-05"), (10, "7.00", "2026-01-20"))
    raw = INV.layers_to_raw(layers)
    assert raw == [
        {"qty": "10", "unit_cost": "5.00", "date": "2026-01-05"},
        {"qty": "10", "unit_cost": "7.00", "date": "2026-01-20"},
    ]
    assert INV.layers_from_raw(raw) == layers


# ─── CLI ────────────────────────────────────────────────────────────────────

@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "get_entity_dir", lambda: tmp_path)
    cfg = {
        "pair": {"currency": "CAD"},
        "accounts": {"bank": "Assets:Current:Chequing"},
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    return tmp_path


def _add_item(entity, slug="widget", method="fifo"):
    M.cmd_add({}, [slug, "--name", "Widget", "--unit", "unit",
                   "--method", method])
    return load_entity("inventory", slug)


def _journal(entity, year="2026"):
    return entity / "generated" / year / "inventory.journal"


def test_add_defaults_to_fifo(entity):
    item = _add_item(entity)
    assert item["method"] == "fifo"
    assert item["layers"] == []
    assert item["unit"] == "unit"


def test_add_lifo_and_duplicate_rejected(entity):
    _add_item(entity, method="lifo")
    assert load_entity("inventory", "widget")["method"] == "lifo"
    with pytest.raises(SystemExit):
        M.cmd_add({}, ["widget", "--name", "Again"])
    with pytest.raises(SystemExit):
        M.cmd_add({}, ["other", "--name", "Other", "--unit", "unit",
                       "--method", "weighted"])


def test_buy_writes_purchase_entry_and_layers(entity):
    _add_item(entity)
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "5.00",
                   "--date", "2026-01-05"])
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "7.00",
                   "--date", "2026-01-20"])
    item = load_entity("inventory", "widget")
    assert INV.on_hand_qty(INV.layers_from_raw(item["layers"])) == D(20)
    text = _journal(entity).read_text()
    assert "pair:1011" in text
    assert "item:widget" in text
    assert "Assets:Inventory" in text
    assert "CAD 50.00" in text and "CAD 70.00" in text
    # The year aggregator includes the new journal (not orphaned).
    assert "include ../generated/2026/inventory.journal" in (
        entity / "include" / "2026.journal").read_text()


@needs_hledger
def test_sell_writes_revenue_and_cogs_and_keeps_books_consistent(entity):
    _add_item(entity)
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "5.00",
                   "--date", "2026-01-05"])
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "7.00",
                   "--date", "2026-01-20"])
    M.cmd_sell({}, ["widget", "--qty", "12", "--price", "10.00",
                    "--date", "2026-02-01"])
    item = load_entity("inventory", "widget")
    rest = INV.layers_from_raw(item["layers"])
    assert INV.on_hand_qty(rest) == D(8)
    assert INV.on_hand_value(rest) == D("56.00")  # FIFO: 8 @ 7.00

    text = _journal(entity).read_text()
    # Revenue leg: bank vs Income:Sales, pair 0100.
    assert "pair:0100" in text
    assert "Income:Sales" in text
    assert "CAD 120.00" in text
    # COGS leg: Expenses:COGS vs Assets:Inventory, pair 0000.
    assert "pair:0000" in text
    assert "Expenses:COGS" in text
    assert "CAD 64.00" in text
    # hledger reads the entries and the books agree with the YAML.
    r = subprocess.run(["hledger", "-f", str(_journal(entity)),
                        "bal", "Assets:Inventory"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "56.00" in r.stdout
    r = subprocess.run(["hledger", "-f", str(_journal(entity)),
                        "bal", "Expenses:COGS"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "64.00" in r.stdout


@needs_hledger
def test_sell_lifo_cogs_differs_from_fifo(entity):
    _add_item(entity, method="lifo")
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "5.00",
                   "--date", "2026-01-05"])
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "7.00",
                   "--date", "2026-01-20"])
    M.cmd_sell({}, ["widget", "--qty", "12", "--price", "10.00",
                    "--date", "2026-02-01"])
    text = _journal(entity).read_text()
    assert "CAD 80.00" in text  # LIFO COGS: 10x7 + 2x5
    item = load_entity("inventory", "widget")
    assert INV.on_hand_value(INV.layers_from_raw(item["layers"])) == D("40.00")


def test_sell_more_than_held_fails_and_writes_nothing(entity):
    _add_item(entity)
    M.cmd_buy({}, ["widget", "--qty", "5", "--cost", "5.00",
                   "--date", "2026-01-05"])
    before = _journal(entity).read_text()
    with pytest.raises(SystemExit):
        M.cmd_sell({}, ["widget", "--qty", "6", "--price", "10.00",
                        "--date", "2026-02-01"])
    assert _journal(entity).read_text() == before
    item = load_entity("inventory", "widget")
    assert INV.on_hand_qty(INV.layers_from_raw(item["layers"])) == D(5)


def test_buy_sell_unknown_item_fails_and_writes_nothing(entity):
    with pytest.raises(SystemExit):
        M.cmd_buy({}, ["ghost", "--qty", "1", "--cost", "5.00"])
    with pytest.raises(SystemExit):
        M.cmd_sell({}, ["ghost", "--qty", "1", "--price", "10.00"])
    assert not (entity / "generated").exists()


def test_buy_bad_numbers_fail_and_write_nothing(entity):
    _add_item(entity)
    with pytest.raises(SystemExit):
        M.cmd_buy({}, ["widget", "--qty", "0", "--cost", "5.00"])
    with pytest.raises(SystemExit):
        M.cmd_buy({}, ["widget", "--qty", "1", "--cost", "-5.00"])
    with pytest.raises(SystemExit):
        M.cmd_buy({}, ["widget", "--qty", "1", "--cost", "5.00",
                       "--date", "2026-13-45"])
    assert not (entity / "generated").exists()


def test_list_and_show(entity, capsys):
    _add_item(entity)
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "5.00",
                   "--date", "2026-01-05"])
    M.cmd_list({}, [])
    out = capsys.readouterr().out
    assert "widget" in out and "10" in out and "50.00" in out
    M.cmd_show({}, ["widget"])
    out = capsys.readouterr().out
    assert "Widget" in out and "fifo" in out and "5.00" in out


@needs_hledger
def test_check_matches_yaml_to_books(entity, capsys, monkeypatch):
    _add_item(entity)
    M.cmd_buy({}, ["widget", "--qty", "10", "--cost", "5.00",
                   "--date", "2026-01-05"])
    M.cmd_sell({}, ["widget", "--qty", "4", "--price", "10.00",
                    "--date", "2026-02-01"])
    # _book_inventory_balance imports get_entity_journal from lib.ui at
    # call time (the tests/test_entry_advanced pattern): patch the lib.ui
    # attribute, since lib.ui binds get_entity_dir at import time and the
    # H-level patch does not reach it once another test imported lib.ui.
    (entity / "include").mkdir(exist_ok=True)
    monkeypatch.setattr(UI, "get_entity_journal",
                        lambda: entity / "include" / "entity.journal")
    (entity / "journal" / "2026").mkdir(parents=True, exist_ok=True)
    (entity / "journal" / "2026" / "opening.journal").write_text("")
    (entity / "journal" / "2026" / "adjustments.journal").write_text("")
    (entity / "include" / "entity.journal").write_text(
        "include 2026.journal\n")
    M.cmd_check({}, [])
    out = capsys.readouterr().out
    assert "match" in out.lower()

    # Drift the YAML by hand: the check must notice and fail.
    item = load_entity("inventory", "widget")
    item["layers"] = [{"qty": "99", "unit_cost": "5.00",
                       "date": "2026-01-05"}]
    save_entity("inventory", "widget", item)
    with pytest.raises(SystemExit):
        M.cmd_check({}, [])
    out = capsys.readouterr().out
    assert "differ" in out.lower() or "drift" in out.lower()
