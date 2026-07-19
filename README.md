# Pairs

A command-line business accounting tool built on [hledger](https://hledger.org). Track assets, liabilities, net worth, revenue, expenses, payroll, and more — all in plain text.

Supports multiple entities (Company/Project) and holding structures from a single installation.

## What it does

- Capital asset tracking with automatic amortization (straight-line and declining balance)
- Liability management with principal/interest payment scheduling
- Net worth reporting (assets at book value minus liabilities)
- Revenue and invoicing (time logging, PDF invoices, payment tracking)
- Expense recording with category and tax tracking
- Contact and contract management
- Tax remittance summaries
- Recurring entry automation
- Synthesized journal output for any date range
- Multi-entity (Company/Project) with per-entity journals and instant switching
- All 14 BitLedger accounting pairs covered by dedicated commands

All financial data lives in hledger journals. Metadata lives in YAML. One `include` line per entity connects to your main ledger.

## Requirements

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.8+ | [python.org](https://www.python.org/downloads/) |
| PyYAML | 5.0+ | `pip install pyyaml` |
| hledger | 1.29+ | [hledger.org/install](https://hledger.org/install.html) |
| Typst | 0.11+ | [typst.app](https://github.com/typst/typst/releases) (optional, for PDF invoices) |

Optional (for dashboards, charts, market data):

| Tool | What for | Install |
|------|----------|---------|
| hledger-ui | TUI interface | Bundled with hledger install |
| hledger-web | Web interface | Bundled with hledger install |
| puffin | TUI dashboard | [github.com/siddhantac/puffin](https://github.com/siddhantac/puffin/releases) |
| pricehist | Price fetching | `pipx install pricehist` |
| fava | Beancount web UI | `pipx install fava` |
| hledger-utils | Charts + editing | `pipx install hledger-utils` |
| matplotlib | Chart generation | `pip install matplotlib` (in .venv) |
| gum | CLI link mode | [github.com/charmbracelet/gum](https://github.com/charmbracelet/gum) |
| rofi | Popup link mode | `sudo apt install rofi` |
| fastapi + uvicorn | PWA server | `pip install fastapi uvicorn` (in .venv) |

## Install

```bash
git clone <repo-url> pair
cd pair
chmod +x pair
ln -s "$(pwd)/pair" ~/.local/bin/pair
ln -s "$(pwd)/pairs" ~/.local/bin/pairs
```

## Quick start

```bash
pair init                  # first-time setup (creates first entity)
pair asset add             # record a capital asset
pair asset amort           # generate amortization entries
pair liability add         # record a loan or debt
pair worth                 # see your net worth
```

## Commands

```
pair init                    First-time setup
pair generate                Regenerate journals from YAML
pair config                  View/edit configuration
pair status                  System status and pending items
pair where <query>           Find entities and entries
pair worth                   Net worth report
pair journal                 Synthesized journal for any period
pair pairs                   BitLedger pair reference table
pair entry                    Interactive entry from any pair

pair entity list            List all entities
pair entity add             Add a new entity
pair entity use <slug>      Switch active entity
pair switch <slug>           Switch active entity (shortcut)

pair asset add|list|show|edit|dispose|amort|writedown|summary
pair liability add|list|show|pay|payments|reclassify
pair expense add|list
pair income add              Non-operating income
pair transfer                Asset-to-asset moves
pair revenue project|log|invoice|paid|outstanding|status|export|undo|rate|defer|recognize|deferred
pair contact add|list|show|edit|remove
pair contract add|list|show|edit
pair payroll run|list
pair equity invest|draw|convert
pair division list           Show divisions with counts
pair tax summary|remit
pair recurring add|list|generate
pair budget set|vs
pair year new|close

pair dash                    Launch dashboards (TUI, web, charts)
pair chart                   Generate charts and visualizations
pair market                  Commodity tracking, prices, portfolio
pair account                 Account registry with metadata
pair export                  Export data (CSV, Beancount, JSON, PostgreSQL)
pair report                  Passthrough to hledger (register, bs, is, bal...)
pair link                    Progressive entry assembly (gum CLI)
pair .                       Popup entry assembly (rofi)
pair web                     PWA server (localhost:8100)
pair prices                  Show recent prices (alias)
```

### Link mode expressions

All 14 accounting pairs are addressable via minimal shorthand:

```
<       Paid op expense from asset
>       Op expense on credit
<<      Non-op expense from asset (amortization)
>>      Non-op expense on credit (interest accrued)
<.      Op income received as asset
>.      Op income recognized from liability
<<.     Non-op income received as asset
>>.     Non-op income from liability (debt forgiven)
<.>     Asset from liability (received loan)
<..     Asset from equity (owner invested)
>..     Liability from equity (dividend declared)
..<     Asset to asset (internal transfer)
..>     Liability to liability (refinance)
..      Equity to equity (year-end close)
```

Append `/` for reversal. Amount optional after space (e.g., `< 3650`).

Use `pair <command> --help` for details on any command.

## How it works

You describe things in YAML (assets, liabilities, contacts, contracts). The tool generates hledger journal entries from that data. hledger gives you reports.

```
YAML metadata ──→ pair generate ──→ .journal files ──→ hledger reports
   (you edit)         (tool runs)        (tool writes)      (you query)
```

Your main hledger journal includes one file per entity:
```
include ~/path/to/pair/entities/clairlea/include/company.journal
```

That single include pulls in everything — account declarations, all years, all modules.

## File structure

```
pair/
├── pair                     # CLI
├── pairs                    # symlink (reference tables)
├── global.yaml              # active entity, entity list
├── lib/                     # shared library code
├── modules/                 # shared module code
├── templates/               # Typst templates
├── .venv/                   # Python venv (matplotlib, etc.)
├── web/                     # PWA frontend (index.html, manifest, sw.js)
│   └── static/              # icons
├── entities/
│   └── clairlea/            # one directory per entity
│       ├── config.yaml      # entity settings (incl. market commodities)
│       ├── accounts.yaml    # account registry with metadata
│       ├── puffin.json      # auto-generated puffin TUI config
│       ├── assets/          # one YAML per capital asset
│       ├── liabilities/     # one YAML per loan/debt
│       ├── contacts/        # one YAML per person/organization
│       ├── contracts/       # one YAML per agreement
│       ├── journal/         # your manual entries (opening balances, adjustments)
│       │   └── 2026/
│       ├── generated/       # tool-written journals (amortization, payments, etc.)
│       │   └── 2026/
│       ├── include/         # aggregation (include chain for hledger)
│       └── invoices/        # per-invoice journals + PDFs
└── docs/                    # design documentation
```

## Multiple entities

```bash
pair init                    # creates your first entity
pair entity add              # add another
pair entity list             # see all entities
pair switch acme-holdings    # change active entity
pair worth                   # operates on active entity
```

Each entity is fully isolated — own config, data, and journal file. Switching is instant.

## Net worth

The headline command:

```bash
$ pair worth

  [clairlea]
══════════════════════════════════════════════════════════════
  Entity Net Worth — Clairlea Consulting
  As of 2026-07-16
══════════════════════════════════════════════════════════════

  ASSETS
    Current Assets                               $57,000.00
    Fixed Assets (net book value)                $81,000.00
  TOTAL ASSETS                                  $138,000.00

  LIABILITIES                                    $61,500.00

  NET WORTH (Equity)                             $76,500.00
══════════════════════════════════════════════════════════════
```

## Dashboards

Launch interactive interfaces for your active entity:

```bash
$ pair dash

  [deskone] Dashboards
  ──────────────────────────────────────────────────
   1) tui        puffin TUI dashboard
   2) web        hledger-web (browser, localhost:5000)
   3) lit        hledger-lit (streamlit charts)
   4) fava       fava (beancount web UI with charts)
   5) ui         hledger-ui (curses)
```

Direct access: `pair dash web`, `pair dash 3`, `pair dash lit -- --port 9000`

## Web app (PWA)

Full-featured progressive web app for entry, reporting, and management:

```bash
$ pair web
  [DeskOne] Starting Pairs PWA on http://localhost:8100
```

Features:
- **Dashboard** — net worth with sparklines, quick entry box, recent transactions
- **Pairs** — link-mode entry with all 14 expressions and fuzzy account search
- **Manage** — assets, liabilities, equity, income, expenses, payroll, recurring, contracts, contacts, commodities
- **Charts** — net worth, P&L, revenue, expenses, cash flow, commodity prices (Chart.js)
- **Reports** — balance sheet, income statement, cash flow, register (hledger passthrough)
- **Codes** — full 14-pair reference table with expressions

Entity switcher in the header. Installable as PWA on any device.

The dashboard entry box is a universal launcher:
- Type a description → start building a journal entry
- Type pairs shorthand (`<.`, `<<`, etc.) → jump to Pairs entry mode
- Type a tab name (`assets`, `payroll`, etc.) → jump to that Manage tab

## Charts and visualization

```bash
$ pair chart

  [deskone] Charts
  ──────────────────────────────────────────────────
   1) prices     Price history (all commodities)
   2) sankey     Cash flow diagram (plotly)
   3) bar        Terminal bar chart
   4) plot       Matplotlib chart (any query)
   5) vega       Vega-lite interactive HTML
   6) treemap    Expense treemap
```

Direct: `pair chart prices`, `pair chart treemap`, `pair chart bar revenue -M`

## Market and commodities

Track stocks, crypto, currencies with automated price fetching:

```bash
pair market add shopify        # Yahoo search → select → configure
pair market fetch              # update all prices via pricehist
pair market verify --deep      # check connectivity + price gaps
pair market show               # current prices table
pair market chart BTC          # price history chart
pair market tag BTC crypto     # organize with tags
pair market list --tag tech    # filter by tag
```

Commodities support rich metadata: type, sector, geography, strategy, risk, tax account, tags, and groups.

## Account registry

Annotate your chart of accounts with institution info, links, and alerts:

```bash
pair account add "Assets:Current:Business Chequing"
pair account show 1            # detail view with balance
pair account tree              # visual tree from hledger
pair account find TD           # search by any field
pair account reconcile 1       # check against statement
pair account link 1 --asset vehicle
pair account tag 1 operating
```

Data stored in `accounts.yaml` per entity. Hledger declarations remain separate.

## Export

```bash
pair export csv                # balance report as CSV
pair export beancount          # full journal for fava
pair export json               # journal as JSON
pair export psql               # push to PostgreSQL
```

## Accounting pairs

The tool is organized around the [BitLedger](https://bitpads.org) account pair matrix — 14 binary codes covering every possible double-entry relationship. Type `pairs` to see the reference table, or `pair` with no args to create an entry from any pair interactively.

See `entity-tool-design-ref.md` for the full mapping and `docs/` for design documentation.

## License

MIT
