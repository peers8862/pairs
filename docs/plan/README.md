# Pairs plan: backlog, decisions and build log

This folder tracks how Pairs grew from a bookkeeping tool into a planning tool for
early-stage companies. It covers scenarios, runway, KPIs, fundraising, the cap table
and growth. Each of these is an opt-in feature pack (see `docs/commands.md`,
"Feature Packs").

It is a published copy of the maintainer's working plan. Personal file paths and
the titles of private source documents have been replaced with neutral text. The
source workbooks were read for concepts and logic only: no figures or company data
were carried over.

## Files

| File | What it holds |
|---|---|
| `index.csv` | The list of files below |
| `items.csv` | Backlog items: summary, dependencies, value/effort, phase, status |
| `phases.csv` | The build phases P0–P7: which items each one combined, and its PR |
| `decisions.csv` | Open and decided questions, with the proposed and the final answer |
| `observations.csv` | What each source document showed, and what it implies for Pairs |
| `sources.csv` | The source documents analysed (described, not linked) |
| `metric_buckets.csv`, `metrics.csv` | The KPI catalogue: 11 buckets, with built-in and anticipated metrics |
| `artifacts.csv` | PRs and other outputs |
| `log.csv` | Dated, one-line entries |
| `plan.xlsx` | A workbook generated from the CSVs. Never edit it by hand |

The CSVs are the source of truth. Keep `index.csv` listing every CSV, and
regenerate the workbook after edits. The maintainer uses `mach sheets build docs/plan`.

## Status (2026-11-13)

Phases P0–P7 are merged (PRs #1–#9). One earlier item is still open:

- I38: valuation methods. Deferred by decision D16.

I35 (projected three statements) was completed 2026-11-13 at full O24/O25
scope (decision D20); monthly profit & loss, balance sheet and cash flow
now all exist.

Further intake ideas not yet built are I47 and I52–I56, marked `later`
(I48–I51 are done).

On 2026-11-13 the core backlog from TODO.md and STATUS.md was folded in as
I57–I79 (23 items, all `idea`): `/api/search` and CLI trade/entry tests, trade
hardening, market-verify web parity, `/api/recent` consolidation, the
commodity-modal browser smoke test, the peers entity decision, Inventory/COGS,
bank-rec CSV import, and the STATUS.md Planning / Future items. That brings
the open count to 31: I35 (partial), I38 (later) and 29 ideas (I47, I52–I56,
I57–I79). Note: `plan.xlsx` has not been regenerated from these CSV edits yet;
run `mach sheets build docs/plan` to rebuild it.

Also on 2026-11-13 the two injection holes found by the audit were fixed
and added as I80 (pricehist flag injection guard) and I81 (journal newline
validation), both marked `done`; the open count stays 31 and the item total
is now 79 (48 done).

Also on 2026-11-13 raw mode in `/api/entry/advanced` was kept but hardened
as I82 (decision D19): the write path now rejects any raw transaction date
differing from the entry date, since the file is picked by the date field
while hledger reads the date from the text. The item total is now 80
(49 done); the open count stays 31.

Also on 2026-11-13 I35 was built at full O24/O25 scope (decision D20):
`assumptions:` block per scenario, working-capital days, equipment and
depreciation, debt and interest, tax loss carryforward — all derived, never
hand-entered lines, with the balance asserted every projected month and cash
tied out to operating/investing/financing flows. The item total stays 80
(50 done); the open count is now 30: I38 (later) and 29 ideas.

Also on 2026-11-13 I63 (`pair market verify` in the web) was built:
`verify_commodities()` in modules/market.py is now the shared core used by
both the CLI and the new POST /api/market/verify endpoint, with a Verify
button (verify-all and per-commodity) in the Commodities tab. The gap check
now matches symbols exactly (BTC no longer matches BTCX lines), stored
prices report freshness, and both CLI and web accept a symbol filter.
Identity is deliberately NOT verified from pricehist output alone (a wrong
fetch_pair pointing at a different valid instrument is indistinguishable
without a second price source); the returned P-line symbols are exposed
for inspection. The item total stays 80 (51 done); the open count is now
29: I38 (later) and 28 ideas.

Also on 2026-11-13 the CLI trade hardening batch (I60–I62) was built, and
I58 with it: bad `--qty` / `--price` / `--date` / `--fee` on buy and sell
now fail gracefully — a clear message and exit 1 on the CLI, HTTP 400 on
the web, nothing written — instead of a raw traceback or a malformed date
landing in the journal. The sell price check that was missing entirely was
added (same rule as buy), fee must be >= 0 and FX > 0 in the builders, and
the sell quantity check mirrors `compute_acb_from_events` (`_EPSILON`:
within-epsilon sells snap to the held quantity; genuinely over-held sells
still raise `InsufficientHoldingError`). One shared strict date rule
(`validate_trade_date`: zero-padded YYYY-MM-DD shape plus a real calendar
date) is used by the builders, `_resolve_common`, and the web endpoints.
The item total stays 80 (55 done); the open count is now 25: I38 (later)
and 24 ideas.

Also on 2026-11-13 the planning items batch (I70–I79) was built, in
numeric order, test-first: narrow terminal fallback for `pair pairs`,
`defaults.last_division` auto-tracking, `pair asset transfer`,
division-level P&L, `pair revenue receive`, multi-currency worth flags,
the consult-user migration script, the build_tags() refactor, and receipt
file linking on expenses. I76 (entity report builder) was left open under
the stop rule — no builder scaffolding exists and "customisable" is
undefined, so it needs an owner decision before building. The item total
stays 80 (73 done); the open count is now 7: I38 (later) and 6 ideas
(I57, I59, I67, I68, I69, I76).

## Cheap ideas batch (2026-11-13)

**I55 — Runway what-if sliders, done.** The Growth tab's "What if (not saved)"
pattern is ported to Runway: revenue x / cost x sliders multiply the projected
revenue / expense of every planned month (plan amounts plus the recent-pace
base in `add` mode; funding is never scaled — a what-if changes how the
business performs, not how much it raises), hire delay shifts salary-driver
rules later by N months, and revenue start shift moves revenue occurrences
later. The shifts happen on the dated occurrences before they are totalled
(`scenario_monthly(..., whatif=...)` with a rule-id → driver map built across
layers); percent-rule amounts stay where they were computed and manual entries
are not shifted. Surface: query params `rev` / `cost` / `hire_delay` /
`rev_shift` on `GET /api/runway` (bad values are 400), flags `--rev` /
`--cost` / `--hire-delay` / `--rev-shift` on `pair runway`, and four range
sliders plus Reset in the Runway tab with a "What-if preview — not saved."
note. Nothing is persisted; the saved scenario is never touched (a test
re-reads it after a what-if build). Tests: `tests/test_runway_whatif.py` (14:
lib multipliers incl. base pace and funding-untouched, scenario shifts,
`build()` end to end, web params incl. defaults-neutral and 400s). The item
total stays 80 (56 done); the open count is now 24: I38 (later) and 23 ideas.

**I52 — CAC allocation by category, done.** `cac_allocation` in config.yaml maps report categories to fractions (0–1, validated; unknown categories rejected). `lib/cac.py` computes the allocated acquisition spend per month from the books (hledger, summarised by report category); `modules/kpi.ledger_series` feeds it into the KPI `acquisition_spend`, now ledger-sourced, so the derived `cac = acquisition_spend / new_customers` is computed from the books — a typed value still wins. No allocation configured means no feed, no behaviour change. Tests: `tests/test_cac.py` (10).

**I53 — Stage bands, done.** `stage_bands` in config.yaml maps stage names to `{start, end}` YYYY-MM ranges (no defaults — nothing invented; an open band runs to the last month with spending; overlap / bad months / start-after-end rejected). `lib/stages.py` totals `Expenses:*` per band from the books; `pair stages` CLI + `GET /api/stages`. Documented in `docs/commands.md`. Tests: `tests/test_stages.py` (14).

**I54 — Traction vs ownership chart, done.** One chart with a chosen traction metric, founder ownership and cash over time — `GET /api/chart/traction?metric=&months=&end=`, `pair traction`, drawn in Company > Overview with a metric picker. Traction is any KPI metric (default paying customers); ownership is founder % of fully diluted shares from the register's dated issuances/grants (`lib/captable.founder_pct_by_month`; undated counts always, SAFEs/notes dilute only on conversion; versions are undated what-ifs and are NOT used); cash is month-end cash from the runway rows. Each line is scaled to its own min-max (the units differ). Tests: `tests/test_traction_chart.py` (10).

**I56 — KPI starting column and unit retention, done.** (1) An opt-in starting column in the KPI grid — the month before the window, the opening value for stock metrics / previous month for flow metrics; `pair kpi --start`, `GET /api/kpis?start=1`, checkbox in the web KPIs tab; off by default, existing output unchanged. (2) A retention factor on `units` rules — optional `retention` 0–1; active[i] = new[i] + retention·active[i−1], revenue is active units × price, the unit-cost (COGS) line stays on new units only; validated in `lib/plan_rules` (retention only on units, 0–1), `--retention` flag on `pair scenario rule add`, shown in `describe()`. Tests: `tests/test_kpi_start_retention.py` (13).

**I47 — Credit line in projections, done.** New assumptions `credit_line_limit` (0 = off) and `credit_line_rate` (annual fraction, [0, 1)); the line draws to the runway cash floor when cash would fall below it, repays when cash allows above it, capped at the limit; interest on the beginning drawn balance (the I35 convention, no circularity) lands in the net interest line; the floor is passed from the runway summary via `modules/runway.statements()`, and with no floor given the line holds cash at 0. Balance-sheet line `bs_credit_line`; the sheet is still asserted balanced every month. A credit line already in the books stays inside other liabilities/debt and is not separately tracked — the line state only tracks new draws. Tests: `tests/test_statements_credit.py` (13).

**I64 — Market show / chart / alert in the web, done.** `GET /api/market/prices/{symbol}` is the per-symbol show detail (latest price/date, entry count, full dated series — the same data `pair market chart SYMBOL` plots); `GET /api/chart/prices` now parses through the same shared `read_price_history` instead of its own copy. Alerts are full parity: `GET`/`POST`/`DELETE /api/market/alerts` + `POST /api/market/alerts/check`, rules in entity config under `market.alerts` exactly as the CLI stores them, and evaluation through the shared `evaluate_alerts` (which `_alert_check_once` now calls too). The shared path also fixed a CLI blind spot: the previous close is looked up by fetch pair (`SHOP.TO`, `BTC-CAD`), not by rule symbol, so SHOP/BTC rules finally find their closes. UI: alerts panel (add/list/remove/check-now) and a per-row History button in the Commodities tab. Tests: `tests/test_market_web_parity.py` (18).

**I65 — Consolidate /api/recent onto /api/search, done.** One shared runner (`_run_hledger_csv`) and grouper (`_group_search_rows`) behind both endpoints; `/api/search` gained `offset` (default 0, existing callers unaffected); `/api/recent` is a thin wrapper keeping its response shape and its bare-term-matches-description behaviour — now a union of two runs, since the old `or` infix term is parsed by this hledger as just another AND term and matched nothing. Both paths still go through `_safe_query_terms`. Tests: `tests/test_recent_search.py` (7).

**I66 — Browser smoke test for the commodity trade modal, done.** Real browser run, not a stub: `tests/test_browser_trade_modal.py` renders the Commodities tab in headless Chromium 158 (in-process uvicorn + Playwright 1.65.0), opens the Buy modal and records a buy, opens the Sell modal with the live holding preview and records a sale, with no page errors. The three jsdelivr Chart.js requests are fulfilled from vendored copies under `tests/fixtures/chartjs/` because this VM's browser cannot reach the CDN and the page's top-level `Chart.defaults.*` statements abort all page JavaScript when Chart is undefined. Setup: `pip install playwright && python -m playwright install chromium` (playwright==1.65.0 added to requirements-dev.txt).

The item total stays 80 (64 done); the open count is now 16: I38 (later) and 15 ideas.

## Planning items batch (2026-11-13)

**I70 — Narrow terminal fallback for `pair pairs`, done.** `show_wide_table()` needs ~125 columns; below `WIDE_MIN_WIDTH = 130` a stacked per-pair layout renders instead (all lines within the terminal width). `terminal_width()` uses `shutil.get_terminal_size(fallback=(200, 24))` so piped output stays wide; `--narrow` / `--wide` flags added; the help usage block wraps too. Tests: `tests/test_pairs_narrow.py` (5).

**I71 — `defaults.last_division` auto-tracking, done.** `prompt_division(config)` and `resolve_division_flag(config, division)` in `lib/helpers.py`: the prompt defaults to the stored last division (a stale value falls back to the first division) and records the choice; an explicit `--division` flag always wins and is itself recorded. Wired into expense add (batch + interactive) and asset add. Tests: `tests/test_last_division.py` (13).

**I72 — `pair asset transfer <slug> --to <division>`, done.** Division lives only in asset YAML, so the transfer updates the YAML and writes a balanced journal entry at net book value (same asset account debited/credited, pair 1011, tagged with the new division + `transfer:old->new`); zero-NBV assets update YAML only. Unknown slug/division, missing `--to`, and bad dates fail with exit 1 and nothing written; same-division is a no-op; records last_division. Tests: `tests/test_asset_transfer.py` (8).

**I73 — Division-level P&L reporting, done.** `pair income statement [--division DIV] [--period P]` runs hledger's own `is` filtered by `tag:division=<div>` (output captured and re-printed so it is capsys-testable); `GET /api/income-statement` returns the same figures as JSON (income/expenses/net + items, credit-normal roots flipped to positive). Shared `validate_division(config, division)` in `lib/helpers.py`. Only transactions tagged with the division count; untagged entries are excluded per-division, included entity-wide. Tests: `tests/test_division_pl.py` (8).

**I74 — `pair revenue receive`, done.** A direct cash receipt (pair 0110, bank vs entity income account, no invoice/receivable, no tax — the amount is the full receipt, all to income); accounts resolved like `cmd_invoice` (project → legacy `entities:` section in config.yaml; income default `Income:Consulting`); `--project` records `last_project`; writes via `format_entry` to `generated/<year>/revenue.journal`. Tests: `tests/test_revenue_receive.py` (7).

**I75 — Multi-currency worth report, done.** `pair worth --cost` / `--value=now` (mutually exclusive; only `--value=now` supported). Both imply `-X <entity currency>` so the total stays single-currency — without it, valued holdings stay in their price currency and the total would mix commodities. New Investments section (Assets:Investments via hledger) appears only when valued rows exist, so the default report is unchanged. Holdings with no price are omitted under `--value=now` and named in a note (`--cost` still shows them at cost). Flags thread through `--raw` and `--monthly`/`--quarterly`. Verified against hledger 1.52.1 empirically. Tests: `tests/test_worth_multicurrency.py` (6).

**I76 — Entity report builder, LEFT OPEN.** No report-builder scaffolding exists anywhere in the repo — no saved-report concept, no report definitions in config, no `entity report` command; the only mentions are the STATUS.md line and the tracker row. `pair report` is a raw hledger passthrough with no builder. Open question for the owner: what does "customisable" mean — saved named reports in config.yaml, a flag-driven query builder, or a web UI? Left `idea` under the stop rule; do not invent it. Any future builder must route user-supplied query terms through `_safe_query_terms` and never insert a `--` separator.

**I77 — Migration script for consult users, done.** `pair entity migrate --from <consult-config.yaml> [--dry-run]` converts each consult `entities:` entry to `contacts/<slug>.yaml` with role: entity and the billing section nested exactly per the contact schema (missing accounts fall back to the contact defaults; `journal_file` preserved on the record). Creates the standard pair directories; skips contacts that already exist (idempotent); the source config is only read, never modified; journals and PDFs untouched. The include-chain and config-schema steps from `docs/migration.md` are out of scope (covered by `pair init`). Tests: `tests/test_consult_migrate.py` (7), synthetic fixtures only.

**I78 — Refactor modules to call build_tags(), done.** Pure refactor — 31 inline tag-dict sites in 18 files now call `build_tags()`; conditional post-creation mutations (division, period, client, reversal, user tags) kept as-is on the mutable dict it returns. One intended semantic change: inline dicts ignored a config `tags:` section disabling a key; `build_tags()` respects it. Rendered tag order changes only at the three link sites (pair now first; hledger treats tags as a set; no test pins the order). Deliberately left: `modules/pairs.py` (already the build_tags call site; its fallback is the import guard) and `modules/expense.py` `tags = {}` (a journal-entry parser, not construction). Tests: `tests/test_build_tags_refactor.py` (4: grep-based no-inline-dicts check with explicit allowlist, import check, default-config identity, disabled-tag behaviour).

**I79 — Receipt file linking, done.** `pair expense add --receipt <path>` (batch) plus an interactive prompt records a `receipt:<path>` tag via `build_tags()` + `format_entry`, so the I81 `require_single_line` rule covers the tag value. The file must exist — a missing file fails with exit 1 and nothing written; relative paths resolve against the entity dir and are stored relative to it (absolute paths outside the entity dir stored as given). `pair expense list` parses the tag back and prints a Receipt line under the entry. CLI-only: `/api/expenses` is a hledger balance summary, not the entry parser. Tests: `tests/test_expense_receipt.py` (9).

The item total stays 80 (73 done); the open count is now 7: I38 (later) and 6 ideas (I57, I59, I67, I68, I69, I76).

## Search-guard verification + entry --advanced tests (2026-11-13)

**I57 — Automated tests for /api/search, done (verify-and-mark, no new test).** The groundwork batch's `tests/test_search_guard.py` (7 tests) was read and run green against the summary element by element: query composition — `amt:>100` prefix (`test_amt_prefix_query_still_matches`), plain term (`test_plain_term_query_passes`), quoted term with space (`test_quoted_term_with_space_passes`); leading-dash rejection — output-file style (`test_leading_dash_output_file_rejected`), flag style (`test_leading_dash_flag_rejected`), dash after a good term (`test_dash_after_a_good_term_rejected`); the `--` separator regression — `test_amt_prefix_query_still_matches` asserts the query is echoed verbatim (`amt:>100`, no `--` added) and returns the 1 matching row, which fails if a `--` is ever inserted before the hledger query terms.

**I59 — CLI `pair entry --advanced` tests, done.** The path exists: `pair entry --advanced` / `-a` routes via `dispatch_pair` in `modules/pairs.py` to `cmd_pair_advanced` — a fully interactive prompt-driven entry (date, status, code, payee, note, tags, then N postings with amount/cost/assertion) sharing `lib.entry` with the web `/api/entry/advanced` overlay. Tests: `tests/test_entry_advanced.py` (13: happy path writes with `mode:advanced, pair:0000` inferred from X+A, written file balances in hledger with the blank 2nd amount inferred, cost `@` and assertion `=` branches, pair override `-`, unknown-account inference-unavailable path, 3-posting compound entry, decline writes nothing, `--advanced` / `-a` dispatch routing). Pre-fix 3 failed / 10 passed: the three failure paths (fewer than two postings, hledger-rejected entry, bad date) printed a clear message but returned silently (exit 0). Fixed in `modules/pairs.py`: all three failure returns in `cmd_pair_advanced` (including the untestable tagging-recheck path) now `sys.exit(1)` per the repo CLI convention established in the I60–I62 batch; a user declining the final confirm still returns normally (exit 0) — a cancellation, not a failure. Three of the pre-fix failures were test bugs, fixed in the tests (bare amounts are written as typed, no currency; assertions need a currency on the amount or the CAD balance is 0).

The item total stays 80 (76 done); the open count is now 4: I38 (later) and 3 ideas (I68, I69, I76).
