# pair — Outstanding Work

Companion to `STATUS.md` (which records what exists). This records what is
deferred, known-broken, or unverified. Updated 2026-07-21.

## Decisions pending

- **Active entity `peers` is incomplete.** `global.yaml` has `active: peers`, but
  `entities/peers/include/` has `2026.journal`, `accounts.journal` and
  `company.journal` and **no `entity.journal`** — the master file
  `get_entity_journal()` returns. Every hledger call for that entity fails, so
  pair-code inference in the advanced entry overlay reports "unavailable"
  (visibly, by design). `deskone` is intact. Options: create the missing
  `entity.journal` including the three files already there; switch `active` back
  to `deskone`; or leave it. Not actioned — entity data is the user's.
- **AAPL/TSLA `config.yaml` corrections** are applied in the working tree but
  intentionally uncommitted: `.gitignore` marks entity config as private user
  data. They persist locally; do not `git add` them.

## Unverified

- **Commodity trade modal (Buy/Sell)** — endpoints tested end to end, but the UI
  was never rendered in a browser. Playwright now works in this repo, so it can
  be smoke-tested the same way the entry overlay and search were.

## Missing tests

- `/api/search` has **no automated tests** — notably for query composition and
  the argument-injection guard. This is security-relevant (see below) and should
  not stay uncovered.
- CLI command layer for trades (`cmd_buy` / `cmd_sell` / `_parse_flags` /
  `_to_number`) has no automated tests; only the pure builders are covered.
- `pair entry --advanced` (CLI) has no automated tests.

## Market / trades hardening (deferred)

- Flag path lets a negative or zero `--qty` / `--price` reach
  `build_buy_entry` / `build_sell_entry` and raise an uncaught `ValueError`
  (raw traceback). Fails before any write, so no data corruption.
- Malformed `--date` raises in `_write` before any write — safe but ungraceful.
- `build_sell_entry` / `cmd_sell` use an exact float comparison for
  `qty > held_qty`, unlike `compute_acb_from_events` which uses `_EPSILON`.
  Could false-reject a full fractional sell; not reproduced.

## CLI → web parity gaps

The web still lacks these `pair market` commands:

- `verify [--deep]` — **recommended next.** Read-only; catches broken
  `fetch_pair` values, which directly protects the buy/sell flow.
- `show` (price history detail), `chart SYMBOL`, `alert` (add/list/check/remove).
- Tag editing (the web filters by tag but cannot add/remove; the CLI can).

## Consolidation

- `/api/recent` still backs the Dash register's pagination while search now goes
  through `/api/search`. Worth pointing both at one endpoint.

## Landmine — do not "fix"

`modules/web.py :: _safe_query_terms` rejects query terms beginning with `-`.
This is the argument-injection guard: hledger parses any argv item starting with
`-` as a flag, so a smuggled `--output-file=` turns a read-only report into an
arbitrary file write. Do **not** replace it with a `--` separator: hledger stops
parsing `prefix:` query syntax after `--`, so `amt:`/`type:`/`expr:` silently
match nothing (`amt:>100` drops from 421 rows to 0). There is a comment saying so
at the call site.

## Deferred by design (own specs)

Transaction editing/deletion; periodic (`~`) and auto-posting (`=`) rule
authoring; directive authoring (`account`, `commodity`, `P`); lot-syntax UI;
dividends/DRIP, stock splits, return of capital, superficial-loss rules.
