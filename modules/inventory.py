"""pair inventory — stock quantities with FIFO/LIFO/average cost layering (I68).

Data lives in the YAML store, `inventory/<slug>.yaml` (lib.yaml_store, the
assets pattern): {name, slug, unit, method, layers}. The costing method is
per-item, chosen at `add` (--method fifo|lifo|average, default fifo).

One truth for inventory: every buy/sell writes the journal AND updates the
YAML, so the YAML layer total always equals the hledger Assets:Inventory
balance. `pair inventory check` verifies exactly that.

Journal shape (see lib.entry.infer_pair — it returns COMPOUND for
anything but 2 postings, so a sale cannot honestly carry one pair code as
a single 4-posting entry):
- buy:  one entry, pair 1011 (asset/asset, cash purchase, same as a cash
  asset acquisition in docs/journal-rules.md):
  Assets:Inventory +total / bank -total.
- sell: two entries, both tagged item:<slug>. Revenue leg, pair 0100
  (operating revenue vs asset): bank +total / Income:Sales -total.
  COGS leg, pair 0000 (operating expense vs asset): Expenses:COGS +cogs /
  Assets:Inventory -cogs.

Accounts: single Assets:Inventory for all items (the YAML is the
per-item truth), Expenses:COGS (first of the lib.statements COGS tuple,
so the P&L reads it), Income:Sales, bank from config accounts.bank
(default Assets:Current:Chequing).
"""

import re
import subprocess
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

from lib.helpers import (
    load_config, prompt, prompt_choice, slugify, validate_date,
    validate_slug, parse_global_flags,
)
from lib.yaml_store import load_entity, save_entity, list_entities, entity_exists
from lib.journal import (
    build_tags, format_entry, append_journal, ensure_year_structure,
    ensure_generated_include, get_generated_dir,
)
import lib.inventory as INV

MODULE = "inventory"

INVENTORY_ACCOUNT = "Assets:Inventory"
COGS_ACCOUNT = "Expenses:COGS"
SALES_ACCOUNT = "Income:Sales"

_BAL_TOTAL = re.compile(r"^\s*[A-Z]{3}\s+(-?[\d,]+\.\d{2})\s*$")


def _flag(args, name, default=None):
    """Value after --name in args, or default."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _decimal(value, label):
    """Parse a Decimal flag value, or exit with a clear message."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        print(f"Invalid {label}: {value!r}")
        sys.exit(1)


def _positive(value, label):
    number = _decimal(value, label)
    if number <= 0:
        print(f"{label.capitalize()} must be positive: {value}")
        sys.exit(1)
    return number


def _non_negative(value, label):
    number = _decimal(value, label)
    if number < 0:
        print(f"{label.capitalize()} cannot be negative: {value}")
        sys.exit(1)
    return number


def _date(flags, args, default=None):
    """--date from the action args, else the global --date flag, else today.

    parse_global_flags eats --date at dispatch time, so a --date given on
    the command line arrives in flags['date']; direct calls pass it in
    args. Accept both.
    """
    value = _flag(args, "--date") or flags.get("date")
    if value is None:
        return default or date.today().strftime("%Y-%m-%d")
    err = validate_date(value)
    if err:
        print(f"  {err}")
        sys.exit(1)
    return value


def _require_item(slug):
    item = load_entity(MODULE, slug)
    if item is None:
        print(f"  Inventory item '{slug}' not found.")
        print("  See `pair inventory list` or add it with `pair inventory add`.")
        sys.exit(1)
    return item


def _write_entries(entries, year):
    """Append entries to generated/<year>/inventory.journal and register
    the include so the year aggregator sees them (not orphaned)."""
    ensure_year_structure(year)
    path = get_generated_dir() / year / "inventory.journal"
    for entry in entries:
        append_journal(path, entry)
    ensure_generated_include(year, "inventory.journal")


def _bank_account(config):
    return config.get("accounts", {}).get("bank", "Assets:Current:Chequing")


def _currency(config):
    return config.get("pair", {}).get("currency", "CAD")


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Add an inventory item: `pair inventory add <slug> [--name --unit --method]`."""
    config = load_config()
    slug = args[0] if args else None
    if not slug:
        slug = prompt("Slug (identifier)", validator=validate_slug)
    err = validate_slug(slug)
    if err:
        print(f"  {err}")
        sys.exit(1)
    if entity_exists(MODULE, slug):
        print(f"  Inventory item '{slug}' already exists.")
        sys.exit(1)

    name = _flag(args, "--name") or prompt("Item name")
    unit = _flag(args, "--unit") or prompt("Unit", default="unit",
                                           required=False) or "unit"
    method = _flag(args, "--method")
    if method is None:
        method = prompt_choice("Costing method", list(INV.METHODS),
                               default=INV.DEFAULT_METHOD)
    if method not in INV.METHODS:
        print(f"  Unknown costing method: {method} "
              f"(choose one of {', '.join(INV.METHODS)})")
        sys.exit(1)

    item = {
        "name": name, "slug": slug, "unit": unit, "method": method,
        "layers": [],
    }
    save_entity(MODULE, slug, item)
    print(f"  Added '{name}' ({slug}), costing method: {method}.")


def cmd_buy(flags, args):
    """Record a purchase: `pair inventory buy <slug> --qty N --cost C [--date D]`.

    --cost is the unit cost. The purchase lands at its cost in
    Assets:Inventory (pair 1011).
    """
    config = load_config()
    if not args:
        print("  Usage: pair inventory buy <slug> --qty N --cost C [--date D]")
        sys.exit(1)
    slug = args[0]
    item = _require_item(slug)
    if _flag(args, "--qty") is None or _flag(args, "--cost") is None:
        print("  Usage: pair inventory buy <slug> --qty N --cost C [--date D]")
        sys.exit(1)
    qty = _positive(_flag(args, "--qty"), "quantity")
    unit_cost = _non_negative(_flag(args, "--cost"), "unit cost")
    entry_date = _date(flags, args)
    currency = _currency(config)

    layers = INV.layers_from_raw(item.get("layers", []))
    try:
        new_layers = INV.add_purchase(layers, item["method"], qty,
                                      unit_cost, entry_date)
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    total = qty * unit_cost

    text = format_entry(
        entry_date,
        f"Purchase inventory: {item['name']} x{format(qty, 'f')} "
        f"@ {unit_cost:.2f}",
        [(INVENTORY_ACCOUNT, currency, float(total)),
         (_bank_account(config), currency, float(-total))],
        tags=build_tags("1011", source=f"inventory/{slug}.yaml",
                        item=slug))
    _write_entries([text], entry_date[:4])
    item["layers"] = INV.layers_to_raw(new_layers)
    save_entity(MODULE, slug, item)
    print(f"  Bought {format(qty, 'f')} {item.get('unit', 'unit')} of "
          f"'{item['name']}' for {currency} {total:.2f} "
          f"({INV.on_hand_qty(new_layers)} on hand).")


def cmd_sell(flags, args):
    """Record a sale: `pair inventory sell <slug> --qty N --price P [--date D]`.

    --price is the unit sale price. Cost is taken out of the layers under
    the item's method and lands in Expenses:COGS; the revenue leg is
    bank vs Income:Sales. Cost is computed BEFORE anything is written,
    so an oversell fails with nothing changed.
    """
    config = load_config()
    if not args:
        print("  Usage: pair inventory sell <slug> --qty N --price P [--date D]")
        sys.exit(1)
    slug = args[0]
    item = _require_item(slug)
    if _flag(args, "--qty") is None or _flag(args, "--price") is None:
        print("  Usage: pair inventory sell <slug> --qty N --price P [--date D]")
        sys.exit(1)
    qty = _positive(_flag(args, "--qty"), "quantity")
    unit_price = _non_negative(_flag(args, "--price"), "unit price")
    entry_date = _date(flags, args)
    currency = _currency(config)

    layers = INV.layers_from_raw(item.get("layers", []))
    try:
        cogs, new_layers = INV.sell(layers, item["method"], qty)
    except (ValueError, INV.InsufficientStockError) as e:
        print(f"  {e}")
        sys.exit(1)
    total = qty * unit_price
    bank = _bank_account(config)

    revenue = format_entry(
        entry_date,
        f"Sale of inventory: {item['name']} x{format(qty, 'f')}",
        [(bank, currency, float(total)),
         (SALES_ACCOUNT, currency, float(-total))],
        tags=build_tags("0100", source=f"inventory/{slug}.yaml",
                        item=slug))
    cogs_entry = format_entry(
        entry_date,
        f"Cost of goods sold: {item['name']} x{format(qty, 'f')}",
        [(COGS_ACCOUNT, currency, float(cogs)),
         (INVENTORY_ACCOUNT, currency, float(-cogs))],
        tags=build_tags("0000", source=f"inventory/{slug}.yaml",
                        item=slug))
    _write_entries([revenue, cogs_entry], entry_date[:4])
    item["layers"] = INV.layers_to_raw(new_layers)
    save_entity(MODULE, slug, item)
    print(f"  Sold {format(qty, 'f')} {item.get('unit', 'unit')} of "
          f"'{item['name']}' for {currency} {total:.2f} "
          f"(COGS {currency} {cogs:.2f}, "
          f"{INV.on_hand_qty(new_layers)} on hand).")


def cmd_list(flags, args):
    """List items with quantity on hand and value at cost."""
    items = [load_entity(MODULE, s) for s in list_entities(MODULE)]
    items = [i for i in items if i]
    if not items:
        print("  No inventory items yet. Add one with `pair inventory add`.")
        return
    print(f"\n  {'Slug':<16}{'Name':<22}{'Method':<9}{'Qty':>10}{'Value':>14}")
    print("  " + "-" * 71)
    for item in items:
        layers = INV.layers_from_raw(item.get("layers", []))
        print(f"  {item['slug']:<16}{item.get('name', ''):<22}"
              f"{item.get('method', ''):<9}"
              f"{format(INV.on_hand_qty(layers), 'f'):>10}"
              f"{INV.on_hand_value(layers):>14.2f}")
    print()


def cmd_show(flags, args):
    """Show one item with its cost layers."""
    if not args:
        print("  Usage: pair inventory show <slug>")
        sys.exit(1)
    item = _require_item(args[0])
    layers = INV.layers_from_raw(item.get("layers", []))
    print(f"\n  {item.get('name', '')} ({item['slug']})")
    print(f"  Method: {item.get('method', '')}    Unit: {item.get('unit', '')}")
    print(f"  On hand: {format(INV.on_hand_qty(layers), 'f')}   "
          f"Value at cost: {INV.on_hand_value(layers):.2f}")
    if layers:
        print(f"\n  {'Date':<12}{'Qty':>10}{'Unit cost':>12}{'Value':>12}")
        print("  " + "-" * 46)
        for lyr in layers:
            print(f"  {lyr.get('date', ''):<12}"
                  f"{format(lyr['qty'], 'f'):>10}"
                  f"{lyr['unit_cost']:>12.2f}"
                  f"{lyr['qty'] * lyr['unit_cost']:>12.2f}")
    print()


def _book_inventory_balance():
    """hledger Assets:Inventory balance from the entity journal.

    Returns (Decimal balance, error str or ''). Missing journal or
    missing hledger is an error, not a zero — a silent zero would hide
    a broken books setup.
    """
    from lib.ui import get_entity_journal
    journal = get_entity_journal()
    if not journal.exists():
        return None, "No entity journal found."
    result = subprocess.run(
        ["hledger", "-f", str(journal), "bal", INVENTORY_ACCOUNT],
        capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()[:500]
    total = None
    for line in result.stdout.splitlines():
        match = _BAL_TOTAL.match(line)
        if match:
            total = Decimal(match.group(1).replace(",", ""))
    return (total if total is not None else Decimal("0"), "")


def cmd_check(flags, args):
    """Reconcile the YAML layer totals against the hledger
    Assets:Inventory balance. Exits 1 on any drift."""
    items = [load_entity(MODULE, s) for s in list_entities(MODULE)]
    items = [i for i in items if i]
    yaml_total = Decimal("0")
    for item in items:
        yaml_total += INV.on_hand_value(
            INV.layers_from_raw(item.get("layers", [])))
    balance, err = _book_inventory_balance()
    if err:
        print(f"  Cannot check: {err}")
        sys.exit(1)
    print(f"  Inventory on hand (YAML layers): {yaml_total:.2f}")
    print(f"  Assets:Inventory (books):        {balance:.2f}")
    if yaml_total == balance:
        print("  ✓ Inventory matches the books.")
        return
    diff = balance - yaml_total
    print(f"  ✗ Inventory differs from the books by {diff:.2f} "
          f"(books minus YAML).")
    print("  Check for manual inventory postings outside "
          "`pair inventory`, or a YAML edit that skipped the journal.")
    sys.exit(1)


# ─── Dispatch ───────────────────────────────────────────────────────────────

def dispatch(args):
    """Route inventory subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags["help"]:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == "add":
        cmd_add(flags, action_args)
    elif action == "buy":
        cmd_buy(flags, action_args)
    elif action == "sell":
        cmd_sell(flags, action_args)
    elif action == "list":
        cmd_list(flags, action_args)
    elif action == "show":
        cmd_show(flags, action_args)
    elif action == "check":
        cmd_check(flags, action_args)
    else:
        print(f"Unknown inventory action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair inventory — stock quantities with FIFO/LIFO/average costing

Actions:
  add <slug> [--name NAME] [--unit UNIT] [--method fifo|lifo|average]
                      Add an inventory item (default method: fifo)
  buy <slug> --qty N --cost C [--date D]
                      Record a purchase at unit cost C
  sell <slug> --qty N --price P [--date D]
                      Record a sale at unit price P (COGS from layers)
  list                Items with quantity on hand and value at cost
  show <slug>         Item detail with cost layers
  check               Reconcile YAML layer totals vs Assets:Inventory

Accounts: Assets:Inventory, Expenses:COGS, Income:Sales, bank from
config accounts.bank. A sale writes two entries (revenue pair 0100,
COGS pair 0000); a purchase writes one (pair 1011).
""")
