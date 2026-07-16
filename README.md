# Pairs

A command-line business accounting tool built on [hledger](https://hledger.org). Track assets, liabilities, net worth, revenue, expenses, payroll, and more — all in plain text.

Supports multiple companies and holding structures from a single installation.

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
- Multi-company with per-company journals and instant switching
- All 14 BitLedger accounting pairs covered by dedicated commands

All financial data lives in hledger journals. Metadata lives in YAML. One `include` line per company connects to your main ledger.

## Requirements

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.8+ | [python.org](https://www.python.org/downloads/) |
| PyYAML | 5.0+ | `pip install pyyaml` |
| hledger | 1.29+ | [hledger.org/install](https://hledger.org/install.html) |
| Typst | 0.11+ | [typst.app](https://github.com/typst/typst/releases) (optional, for PDF invoices) |

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
pair init                  # first-time setup (creates first company)
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

pair company list            List all companies
pair company add             Add a new company
pair company use <slug>      Switch active company
pair switch <slug>           Switch active company (shortcut)

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
```

Use `pair <command> --help` for details on any command.

## How it works

You describe things in YAML (assets, liabilities, contacts, contracts). The tool generates hledger journal entries from that data. hledger gives you reports.

```
YAML metadata ──→ pair generate ──→ .journal files ──→ hledger reports
   (you edit)         (tool runs)        (tool writes)      (you query)
```

Your main hledger journal includes one file per company:
```
include ~/path/to/pair/companies/clairlea/include/company.journal
```

That single include pulls in everything — account declarations, all years, all modules.

## File structure

```
pair/
├── pair                     # CLI
├── pairs                    # symlink (reference tables)
├── global.yaml              # active company, company list
├── lib/                     # shared library code
├── modules/                 # shared module code
├── templates/               # Typst templates
├── companies/
│   └── clairlea/            # one directory per company
│       ├── config.yaml      # company settings
│       ├── assets/          # one YAML per capital asset
│       ├── liabilities/     # one YAML per loan/debt
│       ├── contacts/        # one YAML per person/company
│       ├── contracts/       # one YAML per agreement
│       ├── journal/         # your manual entries (opening balances, adjustments)
│       │   └── 2026/
│       ├── generated/       # tool-written journals (amortization, payments, etc.)
│       │   └── 2026/
│       ├── include/         # aggregation (include chain for hledger)
│       └── invoices/        # per-invoice journals + PDFs
└── docs/                    # design documentation
```

## Multiple companies

```bash
pair init                    # creates your first company
pair company add             # add another
pair company list            # see all companies
pair switch acme-holdings    # change active company
pair worth                   # operates on active company
```

Each company is fully isolated — own config, data, and journal file. Switching is instant.

## Net worth

The headline command:

```bash
$ pair worth

  [clairlea]
══════════════════════════════════════════════════════════════
  Company Net Worth — Clairlea Consulting
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

## Accounting pairs

The tool is organized around the [BitLedger](https://bitpads.org) account pair matrix — 14 binary codes covering every possible double-entry relationship. Type `pairs` to see the reference table, or `pair` with no args to create an entry from any pair interactively.

See `company-tool-design-ref.md` for the full mapping and `docs/` for design documentation.

## License

MIT
