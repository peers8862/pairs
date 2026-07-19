# pair — Design

## Core principle

hledger is the single source of truth for all financial state. The tool generates and manages `.journal` files. YAML stores metadata that doesn't belong in a ledger (contact info, contract terms, amortization schedules, etc.).

## Modules / command groups

| Module | What it tracks | hledger mapping |
|--------|---------------|-----------------|
| **asset** | Capital assets (equipment, vehicles, IP), purchase date, cost, useful life, salvage value | `Assets:Fixed:*` with periodic amortization postings |
| **liability** | Loans, credit lines, leases, payables | `Liabilities:*` with payment schedules |
| **expense** | Operating expenses, receipts, categories | `Expenses:*` journal entries |
| **revenue** | Income streams (inherits from consult's invoicing) | `Income:*` entries |
| **payroll** | Contractors/employees, pay periods, deductions | `Expenses:Payroll:*` + `Liabilities:Payroll Payable` |
| **contract** | Agreements metadata — parties, terms, renewals, links to revenue/expense | YAML only (references journal accounts) |
| **contact** | Clients, vendors, employees — name, role, details | YAML only (referenced by other modules) |
| **worth** | Net worth reporting — rolls up assets, liabilities, amortization | Reads from hledger via `hledger bs` |

## Amortization approach

- User records an asset with: cost, date acquired, useful life (months), salvage value, method (straight-line or declining balance)
- Tool generates monthly/annual amortization journal entries: `Expenses:Amortization` / `Assets:Accumulated Amortization:*`
- A `pair asset amort` command regenerates or extends amortization entries
- Net book value = Cost − Accumulated Amortization (visible in `pair worth`)

## Net worth view

- `pair worth` runs `hledger bs` filtered to the entity's accounts
- Shows: total assets (fixed + current), total liabilities, equity/net worth
- Optionally shows breakdown by category and change over time

## Dependencies

- **Python 3.8+** — same as before
- **PyYAML** — same as before
- **hledger** — backbone
- Typst stays optional (only if invoicing/PDF generation is used)
- No new dependencies needed

## File structure

```
pair/
├── pair                     # CLI entry point
├── config.yaml
├── config.example.yaml
├── assets/                  # per-asset YAML (metadata + amortization schedule)
├── liabilities/             # per-liability YAML
├── contacts/                # per-contact YAML
├── contracts/               # per-contract YAML
├── payroll/                 # pay run records
├── journals/                # generated hledger journals (by year + type)
│   ├── 2026/
│   │   ├── assets.journal
│   │   ├── amortization.journal
│   │   ├── liabilities.journal
│   │   ├── expenses.journal
│   │   ├── payroll.journal
│   │   └── revenue.journal
├── invoices/                # carried over from consult
├── templates/               # typst templates for invoices/reports
└── docs/
```

## Build approach

Keep the consult billing features intact as the `revenue` / `invoice` module — it's proven and useful. Layer the new modules alongside it using the same patterns (YAML data, interactive prompts, journal generation).

## Priority order

1. Assets + amortization
2. Liabilities
3. Net worth reporting (`pair worth`)
4. Expenses
5. Contacts
6. Contracts
7. Payroll
8. Revenue/invoicing (already exists, just rename)
