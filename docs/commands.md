# pair — Command Surface

## Discovery

The tool finds its data directory by looking for `config.yaml` starting from CWD and walking upward. `pair init` always operates in CWD.

## Global Flags

| Flag | Effect |
|------|--------|
| `--help` | Show help for command |
| `--yes` | Skip confirmations |
| `--batch` | Fully non-interactive (requires all values via flags) |
| `--quiet` | Suppress non-essential output |
| `--dry-run` | Show what would be generated without writing |
| `--date <YYYY-MM-DD>` | Override today's date for entries |

---

## Core Commands

### `pair init`

First-time setup. Interactive.

```bash
pair init
```

Creates: `config.yaml`, directory structure, `include/company.journal`, `include/accounts.journal`

Asks: entity name (Company/Project), slug, currency, journal file path, bank account name, fiscal year start.

### `pair generate`

Regenerate all journals from YAML sources.

```bash
pair generate                    # regenerate everything
pair generate --module amort     # just amortization
pair generate --module payments  # just loan payments
pair generate --year 2026        # just one year
pair generate --dry-run          # preview without writing
```

Reads: `assets/*.yaml`, `liabilities/*.yaml`
Writes: `generated/<year>/*.journal`, `include/*.journal`

### `pair year new <YYYY>`

Scaffold a new fiscal year.

```bash
pair year new 2027
```

Creates: `journal/2027/`, `generated/2027/`, `include/2027.journal`
Updates: `include/company.journal`

### `pair year close <YYYY>`

Generate closing entries for a completed fiscal year.

```bash
pair year close 2025
pair year close 2025 --dry-run
```

Generates: closing entries that zero out revenue/expense accounts into retained earnings.
Writes: `generated/<year>/closing.journal`

### `pair config`

View or edit configuration.

```bash
pair config                      # display current config
pair config --edit               # open config.yaml in $EDITOR
pair config currency             # show specific field
pair config currency CAD         # set specific field
```

Reads/writes: `config.yaml`

### `pair status`

Show system status and pending items.

```bash
pair status
```

Displays: outstanding invoices, upcoming payments, expiring contracts, assets due for amortization, deferred revenue awaiting recognition.

### `pair where <query>`

Find entities and entries matching a search query.

```bash
pair where "acme"                # find contacts, contracts, invoices mentioning acme
pair where "2026-03"             # find entries in March 2026
pair where "equipment"           # find assets, expenses by category
```

Searches across: contacts, contracts, assets, liabilities, invoices, journal entries.

### `pair report` — passthrough + report builder

`pair report <hledger-cmd>` passes arguments through to hledger against
the active entity's journal. The report builder (I76) sits alongside it:
a report is a named hledger query (command + terms + display options),
validated before it runs, and the CLI, config.yaml, and the web UI all
run through the same core, so they can never drift.

```bash
pair report list                               # saved reports from config.yaml
pair report run monthly-expenses               # run a saved report
pair report build --cmd register --acct Expenses
pair report build --cmd bs --period 2026 --save year-bs
pair report build --cmd register --amt 100 --amt-op '>' --save big-items
```

Saved reports live in config.yaml (no defaults):

```yaml
reports:
  monthly-expenses:
    title: Monthly expenses
    command: register
    query: "acct:Expenses"
    monthly: true
```

Definition keys: `title` (optional, defaults to the name), `command`
(required: register, print, bal, balance, bs, is, accounts), `query`
(optional hledger query terms), `period` (optional: YYYY, YYYY-MM,
YYYY-MM-DD or YYYYQn), `monthly` / `tree` / `flat` (optional true/false).
Unknown keys, unknown commands, bad periods, and query terms starting
with '-' are rejected — the same leading-dash guard as /api/search, so
a saved report can never smuggle a flag into hledger. Web: the Reports
tab lists and runs saved reports and builds ad-hoc ones
(`GET /api/reports`, `POST /api/reports/run`, `POST /api/reports/build`).

### `pair pairs`

Display the BitLedger account pair reference table.

```bash
pair pairs                       # full table (14 pairs)
pair pairs --normal              # normal operation pairs only
pair pairs --reversals           # reversal/correction pairs only
pair pairs --edge                # edge-case pairs only
pair pairs 5                     # show detail for pair #5
pair pairs --narrow              # stacked per-pair layout (narrow terminal)
pair pairs --wide                # force the wide table
```

Below ~130 columns the stacked layout is used automatically.

### `pair entry`

Interactive entry from any BitLedger pair. Prompts for pair selection, then walks through the entry fields for that pair type.

```bash
pair entry                        # interactive pair selection
pair entry 3                      # start from pair #3 directly
```

Generates: journal entry in the appropriate module journal.

### `pair entity migrate`

Convert consult entities to pair contacts (see `docs/migration.md`).

```bash
pair entity migrate --from <consult-config.yaml>
pair entity migrate --from <consult-config.yaml> --dry-run
```

Each `entities:` entry becomes `contacts/<slug>.yaml` (role: entity, billing nested per the contact schema); the standard pair directories are created; contacts that already exist are skipped. The source config is only read, never modified; journals and PDFs are untouched.

---

## Asset Module

### `pair asset add`

Record a new capital asset. Interactive.

```bash
pair asset add
pair asset add --batch --name "MacBook Pro" --cost 4299 --category equipment \
    --date 2026-03-15 --life 60 --method straight-line --salvage 500
pair asset add --division operations
```

Creates: `assets/<slug>.yaml`
Generates: acquisition entry in `generated/<year>/assets.journal`

### `pair asset list`

```bash
pair asset list                  # all active assets
pair asset list --all            # include disposed
pair asset list --category equipment
pair asset list --division operations
pair asset list --detail         # full breakdown per asset
pair asset list --sort cost      # sort by cost|nbv|date|name
pair asset list --format csv     # CSV output
pair asset list --schedule       # show amortization schedule
```

### `pair asset show <slug>`

```bash
pair asset show macbook-pro-2026
```

Shows: name, cost, NBV, amortization schedule, remaining life.

### `pair asset edit <slug>`

```bash
pair asset edit macbook-pro-2026
```

Interactive edit of YAML fields. Regenerates affected journals.

### `pair asset dispose <slug>`

```bash
pair asset dispose macbook-pro-2026
pair asset dispose macbook-pro-2026 --method sold --proceeds 1500 --date 2027-06-10
```

Updates: `assets/<slug>.yaml` (adds disposal section)
Generates: disposal entry in `generated/<year>/assets.journal`

### `pair asset amort`

Generate/regenerate amortization entries.

```bash
pair asset amort                 # all assets, current year
pair asset amort --all           # all assets, all years
pair asset amort --asset macbook-pro-2026
pair asset amort --through 2026-12-31
```

Writes: `generated/<year>/amortization.journal`

### `pair asset writedown <slug>`

Record a partial impairment (write-down) of an asset's book value.

```bash
pair asset writedown macbook-pro-2026
pair asset writedown macbook-pro-2026 --amount 1000 --date 2026-06-30 \
    --reason "screen damage"
```

Updates: `assets/<slug>.yaml` (adds impairment record)
Generates: impairment entry in `generated/<year>/assets.journal`

### `pair asset transfer <slug>`

Move an asset between divisions.

```bash
pair asset transfer macbook-pro-2026 --to operations
pair asset transfer macbook-pro-2026 --to operations --date 2026-11-13
```

Updates `assets/<slug>.yaml` (division) and writes a balanced journal entry at net book value (same asset account debited/credited, pair 1011, tagged with the new division). Zero-NBV assets update the YAML only; transferring to the same division is a no-op.

### `pair asset summary`

Aggregate asset view by category.

```bash
pair asset summary               # summary by category
pair asset summary --division ops
```

Shows: total cost, total NBV, count, and amortization remaining — grouped by category.

---

## Inventory Module

Stock quantities with FIFO/LIFO/average cost layering (I68). Data lives in
`inventory/<slug>.yaml`: {name, slug, unit, method, layers}. The costing
method is per-item, chosen at `add` (default fifo) — different goods may
need different methods, so there is no entity-wide default.

One truth for inventory: every buy/sell writes the journal AND updates the
YAML, so the YAML layer total always equals the hledger `Assets:Inventory`
balance. `pair inventory check` verifies exactly that.

```bash
pair inventory add widget --name "Widget" --unit unit --method fifo
pair inventory buy widget --qty 10 --cost 5.00 --date 2026-01-05
pair inventory buy widget --qty 10 --cost 7.00 --date 2026-01-20
pair inventory sell widget --qty 12 --price 10.00 --date 2026-02-01
pair inventory list
pair inventory show widget
pair inventory check
```

Accounts: a single `Assets:Inventory` for all items (the YAML is the
per-item truth), `Expenses:COGS` (the first of the lib.statements COGS
tuple, so the P&L reads it), `Income:Sales`, bank from config
`accounts.bank`. Entries land in `generated/<year>/inventory.journal`
(registered in the year aggregator, not orphaned).

- Buy: one entry, pair 1011 (asset/asset, same as a cash asset
  acquisition): `Assets:Inventory +total` / bank `-total`.
- Sell: TWO 2-posting entries — lib.entry.infer_pair returns COMPOUND for
  anything but 2 postings, so one 4-posting entry cannot honestly carry a
  single pair code. Revenue leg, pair 0100 (operating revenue vs asset):
  bank `+total` / `Income:Sales -total`. COGS leg, pair 0000 (operating
  expense vs asset): `Expenses:COGS +cogs` / `Assets:Inventory -cogs`.
  Both entries are tagged `item:<slug>`.

Selling more than is held, or an unknown item, fails with a clear message
and exit 1 and writes nothing — cost is computed before any write happens.
`pair inventory check` exits 1 when the YAML total drifts from the books.

---

## Bank Reconciliation

CSV/OFX import plus automatic statement matching (I69). Import stores
statement lines only — it never writes to the journal; matching records
which statement line corresponds to which journal posting. Unmatched
lines are findings to investigate, not entries to auto-book (deliberately
not built: auto-booking from a bank file is a trust step for the owner).

```bash
pair account import statement.csv --account Assets:Current:Chequing \
    --mapping chequing-csv
pair account import statement.ofx --account Assets:Current:Savings
pair account match Assets:Current:Chequing [--window 3]
pair account reconcile Assets:Current:Chequing
```

Data: `statements/<slug>.yaml` (one file per account, slug is the
slugified account path), with `imports:` (file, sha256, imported_at,
lines) and `lines:` (date, description, amount, fitid, source_file,
matched, status).

Idempotency, two layers: (1) the file's sha256 is recorded — re-importing
the same file is a no-op; (2) a line-level dedup key (account, date,
amount, description, fitid-or-'') skips lines already in the store, so
overlapping statements do not duplicate. Known limit: two genuinely
identical same-day purchases with byte-identical descriptions (CSV, no
FITID) share a key and dedup to one line.

CSV column mapping is DECLARED, never guessed: a named mapping in
config.yaml `statement_mappings:` (see config.example.yaml), referenced
with `--mapping NAME`, or `--col-date/--col-desc/--col-amount` (or
`--col-debit/--col-credit`) flags. `date_format` is declared in the
mapping (default `%Y-%m-%d`). A missing column fails with a clear
message and writes nothing. OFX needs no mapping (fixed field names).

Matching rules: a journal posting is a candidate when the amount matches
exactly (to the cent) and the dates are within the window (default ±3
days, `--window` to override). Exactly one candidate → matched. Several
→ the uniquely closest date wins; a tie on distance is ambiguous. None
→ unmatched. Re-running match only touches lines still unmatched;
matched lines keep their match.

`pair account reconcile` behaves as before, plus one read-only line
when a statement store exists for the account: the matched / unmatched /
ambiguous counts. Web UI is not part of this item: CLI only.

---

## Liability Module

### `pair liability add`

```bash
pair liability add
pair liability add --batch --name "Vehicle Loan" --type loan --principal 35000 \
    --rate 5.49 --term 60 --start 2026-01-15
```

Creates: `liabilities/<slug>.yaml`
Generates: creation entry in `generated/<year>/liabilities.journal`

### `pair liability list`

```bash
pair liability list              # all active
pair liability list --type loan
```

### `pair liability show <slug>`

Shows: remaining balance, payment schedule, interest paid to date.

### `pair liability pay <slug>`

Record a payment.

```bash
pair liability pay vehicle-loan-2026
pair liability pay vehicle-loan-2026 --amount 668.54 --date 2026-02-15
```

Generates: payment entry in `generated/<year>/loan-payments.journal`

### `pair liability payments`

Generate scheduled payment entries.

```bash
pair liability payments                  # all, current year
pair liability payments --through 2026-12-31
pair liability payments --liability vehicle-loan-2026
```

Writes: `generated/<year>/loan-payments.journal`

### `pair liability reclassify <slug>`

Reclassify a liability between liability accounts (e.g., move from long-term to current, or between account categories).

```bash
pair liability reclassify vehicle-loan-2026
pair liability reclassify vehicle-loan-2026 --to "Liabilities:Current:Vehicle Loan" \
    --date 2026-07-01
```

Updates: `liabilities/<slug>.yaml` (account field)
Generates: reclassification entry in `generated/<year>/liabilities.journal`

---

## Expense Module

### `pair expense add`

```bash
pair expense add
pair expense add --batch --desc "Office Supplies" --amount 147.50 \
    --account "Expenses:Operating:Office Supplies" --from chequing --date 2026-07-10
pair expense add --division admin
pair expense add --batch --desc "Team lunch" --amount 85.00 --category meals \
    --receipt receipts/lunch.pdf
```

Appends to: `generated/<year>/expenses.journal`

`--receipt PATH` records a `receipt:<path>` tag on the entry. The file must exist; relative paths resolve against the entity dir and are stored relative to it. `pair expense list` shows the receipt under the entry.

### `pair expense list`

```bash
pair expense list                # current month
pair expense list --period 2026-Q2
pair expense list --category software
pair expense list --division operations
```

---

## Feature Packs

The baseline (books, reports, contacts, budgets, payroll…) is always on. Optional packs add commands and web views. `pair init` asks which to turn on.

| Pack | Adds | Needs |
|---|---|---|
| `scenarios` | `pair scenario`, web Plan tab | |
| `runway` | `pair runway`, Plan > Runway | scenarios |
| `executive` | `pair profile`, `pair kpi`, web Company tab (Profile, KPIs) | |
| `captable` | `pair round`, `pair investor`, `pair captable`, Company > Fundraising / Cap table | |
| `growth` | `pair growth`, Plan > Growth (with what-if sliders) | scenarios |

```bash
pair features                         # list packs, on/off and where it is set
pair features enable runway           # this install (global.yaml: features: [...])
pair features disable growth --entity # this company only (config.yaml features: {growth: false})
pair features inherit growth          # drop the company override
```

A company setting wins over the install setting. Turning a pack on also turns on what it needs. When a pack is off its commands print how to enable it and its web APIs answer 404. Web: ⚙ settings > Feature packs.

## Scenario Module

What-if expenses and revenue kept outside the real books. Items repeat weekly,
monthly, quarterly, semi-annually or annually, for N occurrences or N months. Each scenario is a folder,
`scenarios/<slug>/`, holding `scenario.yaml` and `expenses.journal`. Entries
are tagged `scenario:<slug>`. No include file references `scenarios/`, so real
ledgers, reports and totals never count them; scenario reports load the real
journal and the scenario journal side by side. `add` and `report` warn if an
include file ever pulls a scenario in.

```bash
pair scenario new "Studio move" --desc "Lease a studio from March"
pair scenario add studio-move --batch --desc "Studio lease" --amount 1800 \
    --category rent --date 2026-03-31 --repeat 10     # monthly, day clamped to month end
pair scenario add studio-move --batch --desc "Camera" --amount 3200 \
    --account "Expenses:Operating:Equipment" --from credit-card --date 2026-05-10
pair scenario add studio-move --batch --desc "Insurance" --amount 1200 \
    --category insurance --date 2026-02-01 --every annual --months 24
pair scenario add studio-move --batch --desc "Sponsorship" --amount 3000 \
    --account "Income:Operating:Sales" --date 2026-01-15 --every quarterly --repeat 4   # revenue
pair scenario list
pair scenario show studio-move                         # entries
pair scenario report studio-move --year 2026           # Actual | Scenario | Actual+Scn per account
pair scenario report studio-move --start 2026-04-01 --months 18   # any window
pair scenario report studio-move --monthly             # scenario expenses by month
pair scenario remove studio-move
```

With budgets:

```bash
pair budget vs --full --scenario studio-move           # whole year: budget vs actual + scenario
pair budget forecast --scenario studio-move            # year-end projection including planned items
```

---

### Rules (one stored line per planned item)

A rule is kept once in `scenario.yaml` and turned into dated entries (`rules.journal`, regenerated on every change). Drivers say how the amount behaves:

| Driver | Meaning | Flags |
|---|---|---|
| `fixed` | same amount each time | `--amount` |
| `growth` | changes by a % each occurrence | `--amount --rate 0.05` |
| `step` | new amount from a date | `--amount --step 2027-01-01=1700` |
| `percent` | share of the scenario's revenue that month (or of another rule) | `--percent 0.029 [--of r2]` |
| `units` | units × price, units growing; optional cost per unit (COGS); optional retention (0–1) keeps part of the base each period, so revenue is active units × price | `--units --price [--unit-growth --retention --unit-cost]` |
| `salary` | a hire: salary/12 + benefits, yearly raise, one-off setup | `--salary --benefits --raise --setup-cost` |

Kinds: `expense`, `revenue`, `funding` (`--instrument equity|safe|note|debt|grant`; cash in, not profit). Timing: `--start`, `--every weekly|monthly|quarterly|semiannual|annual|once`, then `--end DATE`, `--months N` or `--repeat N`.

```bash
pair scenario rule add lean --name "Card fees" --driver percent --percent 0.029
pair scenario rule add lean --name "Dev hire" --driver salary --salary 90000 --benefits 0.12 --start 2027-01-01 --months 18
pair scenario rule add lean --name "Pre-seed" --kind funding --instrument safe --amount 150000 --every once
pair scenario rule list lean
pair scenario copy lean "Lean + studio"     # same rules, new scenario
pair scenario migrate lean                  # group old manual entries into rules
```

Report categories (`report_categories` in config.yaml) group accounts into Salaries & Benefits, Marketing & Sales, Product & Materials, Legal & Accounting and Overhead by default.

## Runway Module  `[runway pack]`

Cash, burn and runway. Past months come from the books (revenue, expenses, real cash balance); future months from a scenario. With no transactions yet, give a starting cash.

```bash
pair runway                                   # recent pace only, 18 months
pair runway --scenario lean                   # recent pace + the scenario on top (what-ifs)
pair runway --scenario full-model --replace   # the scenario is the whole plan
pair runway --scenario lean --cash 40000 --months 24 --raise 250000
```

Shows cash by month, burn (actual and planned), runway in months and the month cash runs out, the cash floor (N months of expenses, or a fixed amount) and when cash dips below it, the break-even month, a **raise target** (planned burn × buffer months, 15 by default, because founders tend to underestimate costs and build time by about a third) and **Sources & Uses** (the raise split by report category in proportion to planned spend).

Settings in config.yaml:

```yaml
runway:
  starting_cash: 25000
  cash_accounts: [Assets:Current:Chequing, Assets:Current:Savings]
  min_cash_months: 3
  min_cash: 10000
  buffer_months: 15
  trailing_months: 3
  burn_window: 12
```

Web: Plan > Runway. Budget forecasts with `--scenario` use the same rule as `add` mode: actuals to date, the run rate for the rest of the year, plus the scenario's planned items.

What-if sliders (preview only, nothing is saved) sit on the Runway tab and as flags: `pair runway --rev 1.2 --cost 0.9 --hire-delay 3 --rev-shift 2` scales projected revenue / costs and shifts hires and revenue starts later. See `GET /api/runway?rev=&cost=&hire_delay=&rev_shift=`.

CAC allocation (`cac_allocation` in config.yaml) counts a % of each report category as acquisition cost, so the KPI `acquisition_spend` — and the derived CAC — is computed from the books instead of typed in:

```yaml
cac_allocation:
  Marketing & Sales: 1.0
  Salaries & Benefits: 0.25
```

## Stages Module

Total spending by company stage, from the books. Stage bands come from config.yaml (no defaults):

```bash
pair stages
```

```yaml
stage_bands:
  startup: {start: 2024-01, end: 2024-12}
  seed: {start: 2025-01, end: 2025-06}
  growth: {start: 2025-07}
```

An open band (no end) runs to the last month with spending. Spending is all `Expenses:*` postings in the band's months. Web: `GET /api/stages`.

## Traction chart

One chart — a chosen traction metric, founder ownership and cash over time (Company > Overview):

```bash
pair traction --metric mrr --months 24
```

Traction is any KPI metric; ownership is founder % of fully diluted shares from the captable register's dated issuances and grants (SAFEs/notes dilute only when converted); cash is month-end cash from the runway rows. Web: `GET /api/chart/traction?metric=&months=&end=`.

## Profile and KPI Modules  `[executive pack]`

**Profile** — who the company is (stored under `profile:` in the entity config). `status` is `real` or `speculative` (an idea or a company not formed yet; scenarios, runway and KPIs work without books).

```bash
pair profile
pair profile set stage seed
pair profile set founders "Ana Diaz, Raj Patel"
pair profile set market_share_5y 0.02
pair profile link "Pitch deck" https://...
```

**KPIs** — company, product and founder metrics in 11 buckets (profile, financial, unit economics, usage, pipeline, marketing, fundraising, founder momentum, delivery, team, non-dilutive). Each metric is `manual` (typed in), `ledger` (from the books: revenue, expenses, cogs, cash) or `derived` (a formula over other metrics that month).

```bash
pair kpi                                   # metrics with data, last 6 months
pair kpi --start                           # also show the starting column (month before the window)
pair kpi list --bucket momentum            # ids, units, sources, formulas
pair kpi set investor_meetings 5 --month 2026-11
pair kpi set churn 3%                      # percents can be typed with %
pair kpi add "Podcast listens" --bucket marketing
pair kpi add "Demo to close" --bucket pipeline --unit percent --formula "sales_count / demos"
pair kpi project mrr 0.08                  # carry MRR forward 8% a month
pair kpi project bucket:marketing 0.05     # gear a whole group
pair kpi --months 6 --project 6
```

Files: `kpis/values.csv` (metric, month, value, note), `kpis/definitions.yaml` (your own metrics), `kpis/projections.yaml`. Web: Company > Profile and Company > KPIs (type into a cell to record it).

## Fundraising and Cap Table  `[captable pack]`

**Rounds** hold the type, instrument (SAFE, note, equity, debt, grant), target, anticipated close and terms (cap, discount, interest, price). **Investors** move through stages (1st call → 2nd call → due diligence → documents requested → soft committed → agreement sent → signed → capital received, or passed). Rounds show target vs soft-committed, signed and received. Connections, meetings and conversions feed Company > KPIs automatically.

```bash
pair round add "Pre-seed 2027" --type pre-seed --instrument safe --target 500000 --cap 5000000 --discount 0.2
pair investor add "Ann Angel" --organization "Angels North" --investor-type "angel (pro)" --round pre-seed-2027 --amount 50000
pair investor meeting ann-angel "Walked through the deck" --date 2026-11-12
pair investor stage ann-angel "soft committed"
pair investor receive ann-angel --dry-run      # preview
pair investor receive ann-angel                # writes the books AND the cap table
```

`receive` writes the cash entry (bank / Equity:SAFE, Equity:Share Capital or Liabilities:Long-Term:Convertible Notes) to `generated/<year>/equity.journal`, and records the SAFE/note, or shares at the round price, in the cap table — entered once, both stay in step.

**Cap table** (`captable/register.yaml`): holders by group, share classes, issuances, option pool and grants, open SAFEs and notes. **Versions** (`captable/versions/`) are contemplated futures built from steps — SAFE, note, priced round (pre-money or % sold, pool top-up to a target), option grant — and never change the real table.

```bash
pair captable holder "Ana Diaz" --group founder
pair captable issue ana-diaz 4500000
pair captable pool 1000000
pair captable version new "Seed at 8M pre"
pair captable version step seed-at-8m-pre --type safe --holder angels --amount 300000 --cap 5000000
pair captable version step seed-at-8m-pre --type priced --name Seed --investment 2000000 --pre-money 8000000 --pool-target 0.1
pair captable compare
```

Priced rounds convert open notes and SAFEs (pre-money notes at min(price × (1 − discount), cap ÷ pre-round shares); post-money SAFEs own amount ÷ cap of the post-SAFE capitalisation). Notes accrue simple interest. Web: Company > Fundraising and Company > Cap table.

**Class terms and exit waterfall** — preferred classes carry a liquidation preference (`liq_pref`, a multiple of invested), `participating` (with an optional `participation_cap` multiple) and `seniority` (higher is paid first; equal is shared pro rata). `pair captable exit <value>` (or Cap table > Exit waterfall) shows who gets what: open notes are repaid first, preferences by seniority, then the rest per share; non-participating preferred and SAFEs convert when that pays more, capped participating classes stop at the cap or convert. Also shows each holder's multiple on invested and the split at ¼×, ½×, 1×, 2×, 4× the exit. Simplified: no dividends, escrow or carve-outs; options net-exercise; the unallocated pool is ignored.

```bash
pair captable class seed --liq-pref 1 --participating yes --participation-cap 3 --seniority 2
pair captable exit 30000000 [--version seed-at-8m-pre] [--vested]
```

**Vesting** — `--vesting 48/12` (months/cliff) on `issue` (founder reverse vesting) and `grant`, starting at `--date`; the table shows unvested amounts and the waterfall can count vested only.

**Pro-rata** — a version's priced step with `--pro-rata` lets existing investors take their fully diluted share of the new money; the rest goes to new investors. Priced steps can also set the new class's terms.

**Investor types and contacts** — holders carry an investor type (friends & family, angel, VC, …) shown as a breakdown; `pair investor add … --create-contact` or `pair investor contact <id>` creates a Contacts record (role investor), and money received carries the type and contact to the cap table.

**Progress updates list** — `pair investor updates` lists everyone you talked to, including those who passed, with last contact and last update; `--emails` prints the address list and `--sent` records an update. An investor can be marked "no progress updates".

## Growth Engine  `[growth pack]`

A growth model lives in a scenario. Channels bring sign-ups each month, one funnel turns them into paying customers (sales deals arrive as paying), monthly cohorts shrink by a retention curve, and pricing tiers plus cost to serve turn customers into money. The results are added to the scenario as revenue, acquisition spend, sales cost and cost to serve, so **Runway includes them automatically**.

| Channel | Inputs |
|---|---|
| `paid` | spend, spend change %, cost per 1000 views, click rate, sign-up rate |
| `paid_cpa` | spend, spend change %, cost per sign-up |
| `viral` | invites per new user × invite acceptance (builds on last month's new users) |
| `organic` | visitors, visitor growth, sign-up rate |
| `sales` | reps, add a rep every N months, deals per rep, ramp months, cost per rep |
| `partners` | partners, new partners per month, sign-ups per partner |

```bash
pair growth init lean
pair growth channel add lean --type viral --name Referrals --invites 1.5 --invite-conversion 0.15
pair growth set lean retention 0.8,0.9,0.95      # month-on-month; last value repeats
pair growth set lean funnel.paid_conversion 0.12
pair growth show lean                             # month by month + LTV, CAC, LTV:CAC, payback
pair runway --scenario lean --replace
```

Unit economics: revenue per customer (tier mix), gross margin after cost to serve, expected lifetime (sum of the retention curve, 60-month cap), LTV, CAC (acquisition + sales cost ÷ new paying), LTV:CAC and payback months, and the first month contribution turns positive. Web: Plan > Growth, with **what-if sliders** (spend, conversion, retention, price) that preview without saving.

## Views: compare, layers, budgets, statements, overview

**Layers** — a scenario can build on others: `pair scenario layer hire-editor base` makes "hire-editor" = its own lines + everything in "base". Changing the base updates every scenario built on it. Loops are refused.

**Compare** (runway pack) — side by side revenue, expenses, net, funding, end and lowest cash, burn, runway, cash-out month, break-even and raise target:

```bash
pair scenario compare base hire-editor aggressive --replace --cash 60000 --months 18
```

**Scenario → budget** — `pair scenario budget hire-editor --year 2027 --activate` writes a monthly budget from the plan's expense lines (then `pair budget vs --full`).

**Statements** — Plan > Runway > Statements: monthly profit & loss (revenue, cost of goods sold, gross profit, operating expenses by report category, operating income, non-operating, net income) and cash, actual months from the books then the plan. With an `assumptions:` block in the scenario, the balance sheet is projected too (working capital from DSO/DPO/DIO days, equipment/depreciation from hires, debt/interest, tax-loss carryforward). A credit line draws automatically to the runway's cash floor and repays when cash allows:

```yaml
assumptions:
  credit_line_limit: 50000   # max drawn; 0 = no auto-draw
  credit_line_rate: 0.12     # annual fraction on the drawn balance
```

**Export** — Plan > Runway: download runway, statements or the comparison as CSV.

**Company > Overview** (executive pack) — one page in order: who we are (profile) → traction (latest metrics, change over 3 months, founder momentum) → money (cash, burn, runway, raise target) → plan (the profile's `plan_scenario`) → fundraising (open rounds) → ownership (cap table). Set the plan with `pair profile set plan_scenario <slug>`.

## Income Module

### `pair income add`

Record non-operating income (interest, gains, one-off receipts).

```bash
pair income add
pair income add --batch --desc "Bank interest" --amount 42.50 \
    --account "Revenue:Non-Operating:Interest" --to chequing --date 2026-07-01
```

Appends to: `generated/<year>/income.journal`

### `pair income statement`

Income statement (P&L), optionally per division.

```bash
pair income statement
pair income statement --division operations
pair income statement --division operations --period 2026
```

Runs hledger's own `is` filtered by `tag:division=<div>` when a division is given (only transactions tagged with that division count; untagged entries are excluded per-division, included entity-wide). Also at `GET /api/income-statement`.

---

## Transfer Module

### `pair transfer`

Record an asset-to-asset transfer (e.g., move funds between bank accounts).

```bash
pair transfer
pair transfer --batch --from chequing --to savings --amount 5000 --date 2026-07-01
```

Appends to: `generated/<year>/transfers.journal`

---

## Contact Module

### `pair contact add`

```bash
pair contact add
pair contact add --batch --name "Acme Corp" --role client --email billing@acme.com
```

Creates: `contacts/<slug>.yaml`

### `pair contact list`

```bash
pair contact list
pair contact list --role vendor
pair contact list --role entity
```

### `pair contact show <slug>`

### `pair contact edit <slug>`

### `pair contact remove <slug>`

Requires `--yes` or confirmation.

---

## Contract Module

### `pair contract add`

```bash
pair contract add
```

Creates: `contracts/<slug>.yaml`

### `pair contract list`

```bash
pair contract list               # active contracts
pair contract list --status expired
pair contract list --expiring 30  # expiring within 30 days
```

### `pair contract show <slug>`

### `pair contract edit <slug>`

---

## Revenue Module

All revenue commands, namespaced under `revenue`:

```bash
pair revenue project add         # create client project
pair revenue project list        # list projects
pair revenue rate <project>      # update rate
pair revenue log                 # log time (interactive)
pair revenue log --batch         # batch log
pair revenue log edit            # edit entry
pair revenue status              # unbilled summary
pair revenue invoice             # generate invoice
pair revenue paid                # record payment
pair revenue outstanding         # unpaid invoices + aging
pair revenue export              # CSV export
pair revenue undo                # remove last entry
```

### `pair revenue receive`

Quick cash receipt without a full invoice.

```bash
pair revenue receive --amount 500 --desc "Consulting" --date 2026-11-13
pair revenue receive --amount 500 --client acme --project acme-web
```

Direct receipt (pair 0110, bank vs entity income account, no receivable, no tax — the amount is the full receipt, all to income). Writes to `generated/<year>/revenue.journal`.

### `pair revenue defer`

Record a prepayment (deferred revenue) received from a client.

```bash
pair revenue defer
pair revenue defer --batch --project acme-web --amount 12000 \
    --date 2026-07-01 --periods 6 --desc "6-month retainer"
```

Generates: entry crediting deferred revenue liability, debiting bank.
Creates: `deferred/<slug>.yaml`

### `pair revenue recognize <slug>`

Recognize a portion of deferred revenue as earned.

```bash
pair revenue recognize acme-web-retainer
pair revenue recognize acme-web-retainer --amount 2000 --date 2026-08-01
```

Generates: entry debiting deferred revenue, crediting earned revenue.
Updates: `deferred/<slug>.yaml` (tracks recognized amounts)

### `pair revenue deferred`

List all deferred revenue items and their recognition status.

```bash
pair revenue deferred            # all active deferred items
pair revenue deferred --all      # include fully recognized
```

Shows: original amount, recognized to date, remaining, next recognition date.

---

## Payroll Module

### `pair payroll run`

```bash
pair payroll run
pair payroll run --period 2026-07-01_to_2026-07-15
```

Interactive: select employees/contractors, enter hours/amounts, confirm.
Creates: `payroll/<period>.yaml`
Generates: entries in `generated/<year>/payroll.journal`

### `pair payroll list`

```bash
pair payroll list                # recent pay runs
pair payroll list --year 2026
```

---

## Equity Module

### `pair equity invest`

Owner puts money into the business.

```bash
pair equity invest --amount 10000 --date 2026-01-01
```

### `pair equity draw`

Owner takes money out.

```bash
pair equity draw --amount 2000 --date 2026-07-01
```

### `pair equity convert`

Convert a liability to equity (e.g., shareholder loan conversion).

```bash
pair equity convert
pair equity convert --liability shareholder-loan --amount 25000 --date 2026-07-01
```

Generates: entry debiting the liability account, crediting equity.
Updates: `liabilities/<slug>.yaml` (marks converted portion)

---

## Division Module

### `pair division list`

Show all divisions with entity counts.

```bash
pair division list
```

Shows: division name, number of assets, expenses, and revenue entries per division.

---

## Worth Module

### `pair worth`

Net worth report (headline command).

```bash
pair worth                       # current net worth
pair worth --period 2026-06-30   # as of date
pair worth --monthly             # monthly trend
pair worth --quarterly           # quarterly trend
pair worth --detail              # full account breakdown
pair worth --division operations # filter by division
pair worth --raw                 # pass-through to hledger bs
pair worth --cost                # value investments at cost, converted to entity currency
pair worth --value=now           # value investments at current prices, converted to entity currency
```

`--cost` and `--value=now` are mutually exclusive. Holdings with no price are omitted under `--value=now` and named in a note.

---

## Help

```
$ pair

pair — business accounting on hledger

Commands:
  init                    First-time setup
  generate                Regenerate journals from YAML
  year new|close          Scaffold or close a fiscal year
  config                  View/edit configuration
  status                  System status and pending items
  where <query>           Find entities and entries
  worth                   Net worth report
  pairs                   BitLedger pair reference table
  entry                   Interactive entry from any pair

  entity list|add|use|migrate  Entity (Company/Project) management
  asset add|list|show|edit|dispose|amort|writedown|transfer|summary
  liability add|list|show|pay|payments|reclassify
  expense add|list
  income add|statement
  transfer                Asset-to-asset moves
  contact add|list|show|edit|remove
  contract add|list|show|edit
  revenue project|log|invoice|paid|outstanding|status|export|undo|rate|defer|recognize|deferred|receive
  payroll run|list
  equity invest|draw|convert
  division list

Use 'pair <command> --help' for details.
```
