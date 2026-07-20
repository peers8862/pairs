# Design: `pair market buy` / `pair market sell`

**Date:** 2026-07-20
**Status:** Approved, pending implementation plan

## Problem

Adding a commodity to `market.commodities` only tracks its *price*. It records no
ownership. The journal currently holds zero commodity postings, so fetched `P`
directives are a price database attached to nothing.

There is no purchase flow. `modules/asset.py` is not it — that handles depreciable
fixed assets with amortization schedules, which do not apply to securities.

## Scope

In scope: buying and selling commodities, with adjusted cost base (ACB) tracking and
realized gain/loss postings.

Out of scope for this round: dividends, DRIP, stock splits, return of capital,
superficial-loss rules, and multi-currency cash accounts. Each is a separate spec.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Buy + sell | Sells require cost basis, which shapes the whole data model |
| Cost basis | ACB (weighted average) | CRA requires it for identical properties in non-registered accounts. FIFO and specific-lot are US concepts and are not permissible here. |
| ACB state | Derived at sell time; cached only for display | A stale number in a table is cosmetic; a stale number in a disposal entry is a tax error |
| Account tree | `Assets:Investments:<TaxAccount>:<SYMBOL>` | Keeps registered and non-registered separable, which is the line the CRA cares about |
| Formatter | New `format_commodity_entry()` | Isolates new behavior; zero regression risk to the modules depending on `format_entry` |
| Code location | New `modules/investment.py` | `modules/market.py` is ~1900 lines and already spans fetching, charting, alerts, and export |

## Command surface

```
pair market buy  [SYMBOL] --qty N --price P --date D --account taxable \
                          --cash "Assets:Current:Business Chequing" --fee F --desc TEXT
pair market sell [SYMBOL] --qty N --price P --date D --account taxable --fee F --desc TEXT
```

Flags when supplied, interactive prompts when not, matching `cmd_transfer`
(`modules/transfer.py:49`).

- `SYMBOL` resolves through `_find_commodity`, so list indices work as elsewhere.
- `--account` defaults to the commodity's `tax_account` in config, falling back to `taxable`.
- `--cash` defaults to `config.accounts.bank`.
- `--price` defaults to the latest `P` directive for the symbol.
- `--fee` defaults to 0.

`market.py` dispatches `buy` and `sell` to `modules/investment.py`.

## Posting shape

Entity currency is CAD; several tracked commodities quote in USD. Buying a USD
security from a CAD account is a two-currency transaction requiring an explicit rate,
and the CRA wants ACB in CAD at the transaction-date rate regardless.

Resolution: record **total cost in entity currency** using hledger's `@@` syntax.

```
2026-07-20 * Buy TSLA | 10 sh  ; pair:1011, price:372.73, fee:9.95, fx:1.3660
    Assets:Investments:Taxable:TSLA                10 TSLA @@ CAD 5101.44
    Assets:Current:Business Chequing              CAD -5101.44
```

Reconciling that total: `10 × 372.73 USD = 3727.30 USD`, at `fx 1.3660` gives
`5091.49 CAD`, plus `9.95` commission gives `5101.44 CAD`.

**Fees are always expressed in entity currency (CAD)**, since they are charged against
the cash account. A USD-denominated commission must be converted before being passed
as `--fee`.

This sidesteps FX: the recorded figure is what actually left the bank account, so ACB
is denominated in CAD by construction. Unit price, fee, and FX rate are preserved as
transaction tags for audit without complicating the postings.

Commission is **folded into the `@@` total**, not posted as an expense — per CRA,
commission is added to ACB on acquisition and deducted from proceeds on disposition.

`fx` is tagged only when the commodity's quote currency differs from entity currency.
It is derived as `total_cad / (qty * unit_price)` and is informational.

### Sell

Continuing the position above (10 shares at ACB 5101.44, average 510.144/sh), selling
6 shares for gross proceeds of CAD 3520.00 less a 9.95 commission:

```
2026-07-25 * Sell TSLA | 6 sh  ; pair:0110, acb_per_unit:510.144, fee:9.95
    Assets:Current:Business Chequing              CAD 3510.05
    Assets:Investments:Taxable:TSLA               -6 TSLA @@ CAD 3060.86
    Income:Non-Operating:Capital Gains            CAD -449.19
```

Basis is `6 × 510.144 = 3060.86`; gain is `3510.05 − 3060.86 = 449.19`. The remaining
position is 4 shares carrying `5101.44 − 3060.86 = 2040.58` of cost, average unchanged
at 510.144.

`Income:Non-Operating:Capital Gains` does not yet exist in the chart of accounts and is
created on first use. Its name is read from `config.accounts.capital_gains`, defaulting
to that path.

## Pair codes

The existing 14-pair taxonomy covers this; no new codes are needed.

| Operation | Pair | Meaning |
|---|---|---|
| Buy | `1011` | Asset / Asset — internal transfer; cash converts to shares |
| Sell at gain | `0110` | Non-Op Income / Asset — "Interest, grant, gain" |
| Sell at loss | `0010` | Non-Op Expense / Asset — "Amortization, loss" |
| Sell at break-even | `1011` | Asset / Asset — no gain or loss component |

The pair code on a disposal therefore records its outcome.

## ACB algorithm

On sell, query `hledger -f <journal> reg Assets:Investments:<Account>:<SYMBOL>` and
replay postings chronologically:

```
buy:   qty  += n
       cost += total_paid

sell:  basis = qty_sold * (cost / qty)
       cost -= basis
       qty  -= qty_sold
```

Average cost per unit is always `cost / qty`. Sells reduce accumulated cost
proportionally and never alter the average — this is precisely what distinguishes ACB
from FIFO, and is the single most important behavior to keep under test.

Gain is `proceeds - fee - basis`.

**Registered accounts short-circuit.** When `--account` is `tfsa` or `rrsp`, no ACB is
computed and no gain/loss posting is written, because those gains are not taxable. The
command states this in its output rather than silently omitting the posting.

### Caching

ACB is cached per `(account, symbol)` in `config.yaml` under `market.acb_cache`, keyed
with the journal file's mtime.

- **Sells never read the cache.** They always derive fresh.
- **Display surfaces (web commodities table) read the cache**, recomputing when the
  journal mtime differs from the cached value.

Journal mtime is a sound invalidation signal here because every write path goes through
`append_journal`.

## Error handling

| Case | Behavior |
|---|---|
| Sell qty exceeds holding | Refuse; print held quantity. Never write a negative position. |
| Symbol absent from `market.commodities` | Warn and offer to add, since prices will not fetch otherwise |
| Registered account on sell | Skip gain/loss; state the reason in output |
| No `--price` and no `P` directive | Prompt; required |
| Zero or negative qty/price | Reject via `validate_positive_number` |
| Resulting journal unparseable | Surface `hledger` stderr; do not write |
| `--account` not in tfsa/rrsp/taxable/corporate | Reject with the valid list |

## Precision

`format_commodity_entry` accepts explicit precision per posting: **2 decimal places for
money, up to 8 for quantities.**

This is the defect that makes a new formatter necessary. `lib/journal.py:147` applies
`f"{currency} {amount:.2f}"` to every posting, which would render `0.00431 BTC` as
`0.00` — a silently wrong entry that still balances. Quantity precision must never be
money precision.

Trailing zeros in quantities are stripped so whole-share purchases read `10 TSLA`
rather than `10.00000000 TSLA`.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `modules/investment.py :: cmd_buy` | Parse/prompt, build postings, write | `lib.journal`, `lib.helpers` |
| `modules/investment.py :: cmd_sell` | As above, plus ACB and gain/loss | `compute_acb` |
| `modules/investment.py :: compute_acb` | Replay postings, return `(qty, cost, avg)` | `hledger` subprocess |
| `lib/journal.py :: format_commodity_entry` | Emit lot-syntax entries at correct precision | none |
| `modules/market.py :: dispatch` | Route `buy`/`sell` subcommands | `modules.investment` |

`compute_acb` is pure given its hledger output, so it is testable without writing
journals.

## Testing

- **Unit — ACB replay:** buy/buy/sell/buy/sell sequences; verify the average is
  unchanged by sells; verify a FIFO implementation would produce a different number and
  fail the test.
- **Unit — precision:** `0.00431 BTC` survives a round trip; whole shares render without
  trailing zeros.
- **Unit — fee folding:** commission raises ACB on buy and reduces proceeds on sell.
- **Unit — guards:** sell-more-than-held, bad account, negative qty.
- **Golden files:** formatter output for buy, sell-at-gain, sell-at-loss, registered sell.
- **Integration:** write each golden entry to a temp journal and assert
  `hledger -f tmp print` exits 0. This validates that real hledger accepts the lot
  syntax rather than trusting our reading of the format.
- **Regression:** `format_entry` output byte-identical for all existing callers.

## Prerequisite

Two config entries must be corrected before recording any purchase, since a wrong
currency in `config.yaml` is a one-line edit while the same error in a journal entry is
an accounting correction:

- `appl` — misspelled ticker using the legacy `pair: appl/CAD` key. Fetch fails with
  `Invalid pair 'APPL/CAD'`. Should be `AAPL` with `fetch_pair: AAPL`.
- `TSLA` — `currency: CAD` in config while fetched prices land as `USD`.

The web Add-Commodity modal defaults currency to the entity currency, which is wrong for
foreign-listed securities and will keep reproducing the `TSLA` fault. `_infer_currency`
only applies when a search result is clicked, not when a symbol is typed manually.

## Open questions deferred to later specs

- Dividends and DRIP.
- Stock splits and return of capital.
- Superficial-loss rules on repurchase within 30 days.
- Web UI parity for buy/sell (this spec covers the CLI; the web forms follow the same
  endpoints pattern established for commodities CRUD).
