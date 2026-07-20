"""Investment purchases and disposals with adjusted cost base tracking.

ACB (weighted average) is what the CRA requires for identical properties in
non-registered accounts. FIFO and specific-lot identification are US concepts
and are not permissible here.
"""


class InsufficientHoldingError(Exception):
    """Raised when a disposal exceeds the quantity held."""


_EPSILON = 1e-9


def compute_acb_from_events(events):
    """Replay buy/sell events and return (quantity, cost, average).

    Args:
        events: list of (kind, quantity, total_cost) tuples in chronological
            order, where kind is 'buy' or 'sell'. A sell's total_cost is
            ignored — its basis is derived from the running average.

    Returns:
        (quantity, cost, average). average is 0.0 when quantity is 0.

    Raises:
        InsufficientHoldingError: a sell exceeds the quantity held.
    """
    qty = 0
    cost = 0.0

    for kind, event_qty, total_cost in events:
        if kind == 'buy':
            qty += event_qty
            cost += total_cost
        elif kind == 'sell':
            if event_qty > qty + _EPSILON:
                raise InsufficientHoldingError(
                    f"Cannot sell {event_qty}; only {qty} held"
                )
            # Reduce cost proportionally so the average is unchanged.
            # Reducing by lot instead would be FIFO.
            basis = event_qty * (cost / qty) if qty else 0.0
            cost -= basis
            qty -= event_qty
            # Snap float dust from a full disposal to exact zero.
            if abs(qty) < _EPSILON:
                qty = 0
                cost = 0.0

    average = (cost / qty) if qty else 0.0
    return qty, cost, average
