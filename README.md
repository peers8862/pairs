# hledger-company

A command-line business accounting tool built on [hledger](https://hledger.org). Track assets, liabilities, net worth, revenue, expenses, payroll, and more — all in plain text.

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

All financial data lives in hledger journals. Metadata lives in YAML. One `include` line connects everything to your main ledger.

## Requirements

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.8+ | [python.org](https://www.python.org/downloads/) |
| PyYAML | 5.0+ | `pip install pyyaml` |
| hledger | 1.29+ | [hledger.org/install](https://hledger.org/install.html) |
| Typst | 0.11+ | [typst.app](https://github.com/typst/typst/releases) (optional, for PDF invoices) |

## Install

```bash
git clone <repo-url> hledger-company
cd hledger-company
chmod +x company
ln -s "$(pwd)/company" ~/.local/bin/company
```

## Quick start

```bash
company init                  # first-time setup
company asset add             # record a capital asset
company asset amort           # generate amortization entries
company liability add         # record a loan or debt
company worth                 # see your net worth
```

## Commands

```
company init                    First-time setup
company generate                Regenerate journals from YAML
company config                  View/edit configuration
company status                  System status and pending items
company where <query>           Find entities and entries
company worth                   Net worth report
company journal                 Synthesized journal for any period
company pairs                   BitLedger pair reference table
company pair                    Interactive entry from any pair

company asset add|list|show|edit|dispose|amort|writedown|summary
company liability add|list|show|pay|payments|reclassify
company expense add|list
company income add              Non-operating income
company transfer                Asset-to-asset moves
company revenue project|log|invoice|paid|outstanding|status|export|undo|rate|defer|recognize|deferred
company contact add|list|show|edit|remove
company contract add|list|show|edit
company payroll run|list
company equity invest|draw|convert
company division list           Show divisions with counts
company tax summary|remit
company recurring add|list|generate
company budget set|vs
company year new|close
```

Use `company <command> --help` for details on any command.

## How it works

You describe things in YAML (assets, liabilities, contacts, contracts). The tool generates hledger journal entries from that data. hledger gives you reports.

```
YAML metadata ──→ company generate ──→ .journal files ──→ hledger reports
   (you edit)         (tool runs)        (tool writes)      (you query)
```

Your main hledger journal includes one file:
```
include ~/path/to/hledger-company/include/company.journal
```

That single include pulls in everything — account declarations, all years, all modules.

## File structure

```
hledger-company/
├── company                  # CLI
├── config.yaml              # settings
├── assets/                  # one YAML per capital asset
├── liabilities/             # one YAML per loan/debt
├── contacts/                # one YAML per person/company
├── contracts/               # one YAML per agreement
├── journal/                 # your manual entries (opening balances, adjustments)
│   └── 2026/
├── generated/               # tool-written journals (amortization, payments, etc.)
│   └── 2026/
├── include/                 # aggregation (include chain for hledger)
├── invoices/                # per-invoice journals + PDFs
├── templates/               # Typst templates
└── docs/                    # design documentation
```

## Net worth

The headline command:

```bash
$ company worth

══════════════════════════════════════════════════════════════
  Company Net Worth — Clairlea Consulting
  As of 2026-07-15
══════════════════════════════════════════════════════════════

  ASSETS
    Current Assets                               $57,000.00
    Fixed Assets (net book value)                $81,000.00
  TOTAL ASSETS                                  $138,000.00

  LIABILITIES                                    $61,500.00

  NET WORTH (Equity)                             $76,500.00
══════════════════════════════════════════════════════════════
```

## Design

This tool maps to the [BitLedger](https://bitpads.org) account pair matrix — 14 binary codes covering every possible double-entry relationship. See `company-tool-design-ref.md` for the mapping and `docs/` for full design documentation.

## License

MIT
