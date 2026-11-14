"""Inventory costing engine (I68) — pure functions, no filesystem.

A layer is a dict {'qty': Decimal, 'unit_cost': Decimal, 'date': str}.
Layers are stored in YAML as strings ({'qty': '10', 'unit_cost': '5.00',
'date': '2026-01-05'}) because yaml.safe_dump cannot represent Decimal;
layers_to_raw / layers_from_raw convert at the store boundary.

Methods (per item, chosen at `pair inventory add`):
- fifo: consume oldest layers first.
- lifo: consume newest layers first.
- average: a single layer holds the running average unit cost; on a
  purchase the average is recomputed from the combined value, on a sale
  the cost out is qty * average rounded to cents and the remaining value
  is kept exact (unit cost recomputed from the remaining value, so no
  rounding drift accumulates in the layer).

All money is Decimal, rounded to cents with ROUND_HALF_UP (the same
_cents convention as lib.statements).
"""

from decimal import Decimal, ROUND_HALF_UP

METHODS = ("fifo", "lifo", "average")
DEFAULT_METHOD = "fifo"

CENT = Decimal("0.01")
ZERO = Decimal("0")


class InsufficientStockError(ValueError):
    """Selling more than is on hand."""


def layer(qty, unit_cost, date):
    """One cost layer. qty / unit_cost are Decimal."""
    return {"qty": Decimal(qty), "unit_cost": Decimal(unit_cost),
            "date": str(date)}


def layers_from_raw(raw):
    """YAML dicts ({qty, unit_cost, date} as strings) → engine layers."""
    return [layer(Decimal(str(r["qty"])), Decimal(str(r["unit_cost"])),
                  r.get("date", "")) for r in (raw or [])]


def layers_to_raw(layers):
    """Engine layers → YAML-safe dicts (exact strings, no float drift)."""
    out = []
    for lyr in layers:
        qty = lyr["qty"]
        cost = lyr["unit_cost"]
        out.append({
            "qty": _dec_str(qty),
            "unit_cost": _money_str(cost),
            "date": lyr.get("date", ""),
        })
    return out


def _dec_str(value):
    """Decimal → shortest exact string ('10', '2.5'), never scientific."""
    text = format(value, "f")
    return text


def _money_str(value):
    """Decimal → 2dp money string."""
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _cents(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def on_hand_qty(layers):
    """Total units on hand."""
    total = ZERO
    for lyr in layers:
        total += lyr["qty"]
    return total


def on_hand_value(layers):
    """Total value on hand at cost, to the cent."""
    total = ZERO
    for lyr in layers:
        total += lyr["qty"] * lyr["unit_cost"]
    return _cents(total)


def add_purchase(layers, method, qty, unit_cost, date):
    """Add a purchase layer. Returns a NEW list; inputs untouched.

    Average method keeps a single layer: the new average unit cost is
    (old value + new cost) / (old qty + new qty), unrounded — the value
    stays exact and rounding happens only when cost is taken out.
    """
    qty = Decimal(qty)
    unit_cost = Decimal(unit_cost)
    if qty <= 0:
        raise ValueError("Purchase quantity must be positive.")
    if unit_cost < 0:
        raise ValueError("Purchase unit cost cannot be negative.")
    layers = [dict(lyr) for lyr in layers]
    if method == "average":
        old_qty = on_hand_qty(layers)
        old_value = sum((l["qty"] * l["unit_cost"] for l in layers), ZERO)
        new_qty = old_qty + qty
        new_value = old_value + qty * unit_cost
        avg = new_value / new_qty
        return [layer(new_qty, avg, str(date))]
    if method not in ("fifo", "lifo"):
        raise ValueError(f"Unknown costing method: {method}")
    layers.append(layer(qty, unit_cost, date))
    return layers


def sell(layers, method, qty):
    """Take qty units out under the costing method.

    Returns (cost_out: Decimal to the cent, new_layers). Raises
    InsufficientStockError when qty exceeds what is on hand; the input
    list is never mutated, so a failed sale leaves the item untouched.
    """
    qty = Decimal(qty)
    if qty <= 0:
        raise ValueError("Sale quantity must be positive.")
    if method not in METHODS:
        raise ValueError(f"Unknown costing method: {method}")
    held = on_hand_qty(layers)
    if qty > held:
        raise InsufficientStockError(
            f"Not enough stock: have {format(held, 'f')}, "
            f"tried to sell {format(qty, 'f')}.")
    layers = [dict(lyr) for lyr in layers]
    if method == "average":
        value = sum((l["qty"] * l["unit_cost"] for l in layers), ZERO)
        avg = value / held
        cost = _cents(qty * avg)
        remaining_qty = held - qty
        if remaining_qty == 0:
            return cost, []
        remaining_value = value - cost
        return cost, [layer(remaining_qty,
                            remaining_value / remaining_qty,
                            layers[-1].get("date", ""))]
    remaining = qty
    cost = ZERO
    out = []
    ordered = layers if method == "fifo" else list(reversed(layers))
    consumed = []
    for lyr in ordered:
        if remaining == 0:
            consumed.append(lyr)
            continue
        take = min(lyr["qty"], remaining)
        cost += take * lyr["unit_cost"]
        remaining -= take
        left = lyr["qty"] - take
        if left > 0:
            kept = dict(lyr)
            kept["qty"] = left
            consumed.append(kept)
    if method == "lifo":
        consumed.reverse()
    # Preserve original (chronological) layer order in the result.
    out = sorted(consumed, key=lambda l: (l.get("date", ""),))
    # sorted() is stable, so same-date layers keep their insertion order.
    cost = _cents(cost)
    return cost, [l for l in out if l["qty"] > 0]
