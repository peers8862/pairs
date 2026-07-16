# hledger-company — Command Surface

CLI entry point: `company`

---

## Data directory discovery

The tool searches for `config.yaml` starting from the current working directory and walking upward until `/`. If found, that directory becomes the data root. If not found, all commands except `company init` exit with:

```
No config.yaml found. Run 'company init' to set up, or run from within a company directory.
```

`company init` always operates in the current directory.

---

## Help output format

```
company - plain-text accounting for your business

Usage: company <module> <verb> [args] [flags]

Modules:
  asset          Capital assets and amortization
  liability      Loans, credit lines, payables
  expense        Operating expenses
  revenue        Income, invoicing, payments
  payroll        Contractors and employees
  contract       Agreements and terms
  contact        People and organizations
  worth          Net worth and reporting

Setup:
  init           First-time setup
  generate       Regenerate all journals from YAML sources

Global flags:
  --help, -h     Show help for any command
  --yes, -y      Skip confirmations
  --batch        Non-interactive mode (read from stdin or flags)
  --quiet, -q    Suppress non-essential output

Run 'company <module> --help' for module-specific commands.
Run 'company <command> --help' for detailed usage.
```

---

## Global commands

### `company init`

```
company init [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with --yes for defaults) |
| Does | Creates config.yaml, directory structure, and first entity |
| Writes | `config.yaml`, directories: `assets/`, `liabilities/`, `contacts/`, `contracts/`, `payroll/`, `journals/`, `invoices/`, `templates/`, `output/`, `build/` |

#### Init flow

1. Company name — "What is the company name?"
2. Entity slug — "Short identifier (lowercase, hyphens ok)" [derived from name]
3. Business number — "Business/tax number (optional)"
4. Email — "Contact email"
5. Phone — "Phone (optional)"
6. Currency — "Default currency" [CAD]
7. Tax rate — "Default tax %" [13]
8. Fiscal year start — "Fiscal year start month" [1]
9. hledger journal — "Path to your hledger journal file" [~/.hledger.journal]
10. Account names (with defaults):
    - Receivable: `Assets:Accounts Receivable`
    - Income: `Income:Revenue`
    - Tax liability: `Liabilities:HST Payable`
    - Bank: `Assets:Chequing`
    - Fixed assets: `Assets:Fixed`
    - Amortization expense: `Expenses:Amortization`
    - Accumulated amortization: `Assets:Accumulated Amortization`
11. Payment terms — "Default payment terms" [Net 30 days]
12. Invoice prefix — "Invoice number prefix (optional)"

Creates config.yaml and all directories. Copies `config.example.yaml` if available.

---

### `company generate`

```
company generate [--year YYYY] [--module MODULE] [--dry-run]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Regenerates all hledger journal files from YAML source data |
| Reads | All YAML in `assets/`, `liabilities/`, `payroll/`, `invoices/`, `config.yaml` |
| Writes | `journals/<year>/assets.journal`, `journals/<year>/amortization.journal`, `journals/<year>/liabilities.journal`, `journals/<year>/expenses.journal`, `journals/<year>/payroll.journal`, `journals/<year>/revenue.journal` |

Flags:
- `--year YYYY` — only regenerate for a specific year (default: all years with data)
- `--module MODULE` — only regenerate one module (e.g., `--module asset`)
- `--dry-run` — show what would be written without writing

---

## Module: asset

### `company asset add`

```
company asset add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Records a new capital asset with amortization parameters |
| Reads | `config.yaml` |
| Writes | `assets/<slug>.yaml`, `journals/<year>/assets.journal`, `journals/<year>/amortization.journal` |

Interactive prompts:
- Asset name
- Slug (derived from name)
- Category (equipment, vehicle, furniture, technology, other)
- Date acquired [today]
- Cost (purchase price)
- Salvage value [0]
- Useful life in months
- Amortization method (straight-line, declining-balance) [straight-line]
- Acquisition method (cash, credit, lease) [cash]
- Vendor contact (optional, from contacts)
- Notes (optional)

Batch flags: `--name`, `--cost`, `--date`, `--life`, `--salvage`, `--method`, `--category`, `--acquisition`

### `company asset list`

```
company asset list [--active] [--category CATEGORY] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all assets with current book value |
| Reads | `assets/*.yaml` |
| Writes | nothing |

Flags:
- `--active` — only assets not fully amortized (default: all)
- `--category CATEGORY` — filter by category
- `--format FORMAT` — `table` (default), `csv`, `yaml`

### `company asset show <slug>`

```
company asset show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full details of an asset including amortization schedule |
| Reads | `assets/<slug>.yaml` |
| Writes | nothing |

### `company asset edit <slug>`

```
company asset edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits an asset's metadata (walks through fields showing current values) |
| Reads | `assets/<slug>.yaml` |
| Writes | `assets/<slug>.yaml`, regenerates affected journals |

### `company asset remove <slug>`

```
company asset remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm unless --yes) |
| Does | Removes an asset record and its generated journal entries |
| Reads | `assets/<slug>.yaml` |
| Writes | removes `assets/<slug>.yaml`, regenerates `journals/<year>/assets.journal`, `journals/<year>/amortization.journal` |

### `company asset dispose <slug>`

```
company asset dispose <slug> [--date DATE] [--amount AMOUNT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records disposal/sale of an asset, calculates gain or loss |
| Reads | `assets/<slug>.yaml`, `config.yaml` |
| Writes | `assets/<slug>.yaml` (marks disposed), regenerates journals |

---

## Module: liability

### `company liability add`

```
company liability add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Records a new liability (loan, credit line, lease, payable) |
| Reads | `config.yaml` |
| Writes | `liabilities/<slug>.yaml`, `journals/<year>/liabilities.journal` |

Interactive prompts:
- Name/description
- Slug
- Type (loan, credit-line, lease, payable, other)
- Creditor (optional, from contacts)
- Principal amount
- Interest rate % (0 for interest-free)
- Start date
- Term (months, or ongoing)
- Payment frequency (monthly, biweekly, quarterly, annual)
- Payment amount (or calculate from principal + interest + term)
- Account name [Liabilities:<Name>]
- Notes (optional)

### `company liability list`

```
company liability list [--active] [--type TYPE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all liabilities with current balance |
| Reads | `liabilities/*.yaml` |
| Writes | nothing |

### `company liability show <slug>`

```
company liability show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full liability details including payment schedule and balance |
| Reads | `liabilities/<slug>.yaml` |
| Writes | nothing |

### `company liability edit <slug>`

```
company liability edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits a liability's terms |
| Reads | `liabilities/<slug>.yaml` |
| Writes | `liabilities/<slug>.yaml`, regenerates journals |

### `company liability remove <slug>`

```
company liability remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a liability record |
| Reads | `liabilities/<slug>.yaml` |
| Writes | removes file, regenerates journals |

### `company liability pay <slug>`

```
company liability pay <slug> [--date DATE] [--amount AMOUNT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records a payment against a liability |
| Reads | `liabilities/<slug>.yaml`, `config.yaml` |
| Writes | `liabilities/<slug>.yaml`, `journals/<year>/liabilities.journal` |

---

## Module: expense

### `company expense add`

```
company expense add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Records an operating expense |
| Reads | `config.yaml` |
| Writes | `journals/<year>/expenses.journal` |

Interactive prompts:
- Date [today]
- Amount
- Category (from configured expense categories or freeform)
- Payee/vendor (optional, from contacts)
- Description
- Account [Expenses:<Category>]
- Payment method (cash, bank, credit) [bank]
- Receipt reference (optional)
- Tags (optional, comma-separated)

Batch flags: `--date`, `--amount`, `--category`, `--payee`, `--description`, `--account`, `--tags`

### `company expense list`

```
company expense list [--from DATE] [--to DATE] [--category CATEGORY] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists expenses matching filters |
| Reads | `journals/*/expenses.journal` |
| Writes | nothing |

### `company expense show <id>`

```
company expense show <id>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows details of a specific expense entry |
| Reads | `journals/*/expenses.journal` |
| Writes | nothing |

### `company expense edit <id>`

```
company expense edit <id> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits an expense entry |
| Reads | `journals/*/expenses.journal` |
| Writes | `journals/<year>/expenses.journal` |

### `company expense remove <id>`

```
company expense remove <id> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes an expense entry |
| Reads | `journals/*/expenses.journal` |
| Writes | `journals/<year>/expenses.journal` |

---

## Module: revenue

Inherits and extends consult's billing system.

### `company revenue log`

```
company revenue log [--batch] [--project PROJECT]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Logs billable/non-billable time to a project |
| Reads | `config.yaml`, `projects/<slug>.yaml` |
| Writes | `timesheets/unbilled.yaml` |

Interactive prompts: date, project, hours, focus/description, type (billable/research/admin), tax override, tags.

### `company revenue log edit`

```
company revenue log edit [--project PROJECT]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits a previously logged time entry |
| Reads | `timesheets/unbilled.yaml` |
| Writes | `timesheets/unbilled.yaml` |

### `company revenue status`

```
company revenue status [--project PROJECT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows unbilled hours and amounts per project |
| Reads | `timesheets/unbilled.yaml`, `projects/*.yaml` |
| Writes | nothing |

### `company revenue invoice`

```
company revenue invoice [--project PROJECT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (--yes skips confirmation) |
| Does | Generates an invoice PDF and hledger journal entry from unbilled time |
| Reads | `timesheets/unbilled.yaml`, `config.yaml`, `projects/<slug>.yaml`, `templates/*.typ` |
| Writes | `output/invoice-<number>.pdf`, `invoices/<year>/<number>.journal`, `timesheets/billed/<number>.yaml`, `build/<number>.yaml` |

### `company revenue paid`

```
company revenue paid [--invoice NUMBER] [--amount AMOUNT] [--date DATE] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records payment received against an outstanding invoice |
| Reads | `timesheets/billed/*.yaml`, `config.yaml` |
| Writes | `timesheets/billed/<number>.yaml`, `invoices/<year>/<number>-payment.journal` |

### `company revenue outstanding`

```
company revenue outstanding [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows unpaid invoices grouped by aging bucket |
| Reads | `timesheets/billed/*.yaml` |
| Writes | nothing |

### `company revenue export`

```
company revenue export [--project PROJECT] [--from DATE] [--to DATE] [--type TYPE] [--tag TAG] [--all]
```

| | |
|---|---|
| Mode | Scriptable (outputs to stdout) |
| Does | Exports time entries to CSV |
| Reads | `timesheets/unbilled.yaml`, `timesheets/billed/*.yaml` (with --all) |
| Writes | stdout (CSV) |

### `company revenue undo`

```
company revenue undo [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm unless --yes) |
| Does | Removes the last logged time entry |
| Reads | `timesheets/unbilled.yaml` |
| Writes | `timesheets/unbilled.yaml` |

### `company revenue project add`

```
company revenue project add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Creates a new client billing project |
| Reads | `config.yaml` |
| Writes | `projects/<slug>.yaml` |

### `company revenue project list`

```
company revenue project list [--active]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all revenue projects |
| Reads | `projects/*.yaml` |
| Writes | nothing |

### `company revenue rate <project>`

```
company revenue rate <project> [--amount AMOUNT] [--from DATE] [--type TYPE]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Adds a new effective rate for a project |
| Reads | `projects/<slug>.yaml` |
| Writes | `projects/<slug>.yaml` |

---

## Module: payroll

### `company payroll add`

```
company payroll add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Adds a contractor or employee to the payroll roster |
| Reads | `config.yaml`, `contacts/*.yaml` |
| Writes | `payroll/people/<slug>.yaml` |

Interactive prompts:
- Person (select from contacts or create new)
- Role/title
- Type (employee, contractor)
- Pay rate (hourly, salary, per-deliverable)
- Pay amount
- Pay frequency (weekly, biweekly, monthly)
- Start date
- Deductions (if employee): tax, CPP, EI, other
- Account [Expenses:Payroll:<Name>]

### `company payroll list`

```
company payroll list [--active] [--type TYPE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists people on payroll |
| Reads | `payroll/people/*.yaml` |
| Writes | nothing |

### `company payroll show <slug>`

```
company payroll show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows payroll details for a person including pay history |
| Reads | `payroll/people/<slug>.yaml`, `payroll/runs/*.yaml` |
| Writes | nothing |

### `company payroll edit <slug>`

```
company payroll edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits payroll configuration for a person |
| Reads | `payroll/people/<slug>.yaml` |
| Writes | `payroll/people/<slug>.yaml` |

### `company payroll remove <slug>`

```
company payroll remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a person from payroll (marks inactive) |
| Reads | `payroll/people/<slug>.yaml` |
| Writes | `payroll/people/<slug>.yaml` |

### `company payroll run`

```
company payroll run [--date DATE] [--person SLUG] [--yes]
```

| | |
|---|---|
| Mode | Interactive (--yes for auto-confirm) |
| Does | Runs payroll for the current period, generating payment entries |
| Reads | `payroll/people/*.yaml`, `config.yaml` |
| Writes | `payroll/runs/<date>.yaml`, `journals/<year>/payroll.journal` |

### `company payroll history`

```
company payroll history [--person SLUG] [--from DATE] [--to DATE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows payroll run history |
| Reads | `payroll/runs/*.yaml` |
| Writes | nothing |

---

## Module: contract

### `company contract add`

```
company contract add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Records a contract/agreement with terms and dates |
| Reads | `contacts/*.yaml` |
| Writes | `contracts/<slug>.yaml` |

Interactive prompts:
- Contract name
- Slug
- Type (service, employment, lease, vendor, other)
- Counterparty (from contacts)
- Start date
- End date (or ongoing)
- Value (total contract value, optional)
- Renewal (auto, manual, none) [none]
- Renewal notice period (days, if applicable)
- Linked project (optional, from projects)
- File reference (path to PDF/scan, optional)
- Notes

### `company contract list`

```
company contract list [--active] [--type TYPE] [--expiring DAYS]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists contracts, optionally filtered |
| Reads | `contracts/*.yaml` |
| Writes | nothing |

Flags:
- `--active` — only current contracts
- `--type TYPE` — filter by type
- `--expiring DAYS` — contracts expiring within N days

### `company contract show <slug>`

```
company contract show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full contract details |
| Reads | `contracts/<slug>.yaml` |
| Writes | nothing |

### `company contract edit <slug>`

```
company contract edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits contract details |
| Reads | `contracts/<slug>.yaml` |
| Writes | `contracts/<slug>.yaml` |

### `company contract remove <slug>`

```
company contract remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a contract record |
| Reads | `contracts/<slug>.yaml` |
| Writes | removes `contracts/<slug>.yaml` |

---

## Module: contact

### `company contact add`

```
company contact add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Adds a person or organization to the contact directory |
| Reads | nothing |
| Writes | `contacts/<slug>.yaml` |

Interactive prompts:
- Name
- Slug (derived)
- Type (client, vendor, employee, contractor, other)
- Organization (optional)
- Email (optional)
- Phone (optional)
- Address (optional, multi-line)
- Notes (optional)
- Tags (optional, comma-separated)

Batch flags: `--name`, `--type`, `--email`, `--phone`, `--org`, `--tags`

### `company contact list`

```
company contact list [--type TYPE] [--tag TAG] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all contacts |
| Reads | `contacts/*.yaml` |
| Writes | nothing |

### `company contact show <slug>`

```
company contact show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows contact details and linked contracts/projects |
| Reads | `contacts/<slug>.yaml`, `contracts/*.yaml`, `projects/*.yaml` |
| Writes | nothing |

### `company contact edit <slug>`

```
company contact edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits contact information |
| Reads | `contacts/<slug>.yaml` |
| Writes | `contacts/<slug>.yaml` |

### `company contact remove <slug>`

```
company contact remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a contact (warns if referenced by contracts/projects) |
| Reads | `contacts/<slug>.yaml`, `contracts/*.yaml`, `projects/*.yaml` |
| Writes | removes `contacts/<slug>.yaml` |

---

## Module: worth

### `company worth`

```
company worth [--date DATE] [--period monthly|quarterly|annual] [--months N]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows net worth statement: assets, liabilities, and equity |
| Reads | Runs `hledger bs` against configured journal; reads `assets/*.yaml` for book values |
| Writes | nothing |

Output:
```
Company Net Worth — 2026-07-15

  Assets
    Current assets
      Chequing                          $12,340.00
      Accounts Receivable                $1,567.14
    Fixed assets
      MacBook Pro (net book value)       $1,800.00
      Office Furniture (NBV)               $450.00
    ──────────────────────────────────────────────
    Total assets                        $16,157.14

  Liabilities
      HST Payable                          $287.50
      Equipment Loan                     $3,200.00
    ──────────────────────────────────────────────
    Total liabilities                    $3,487.50

  ════════════════════════════════════════════════
  Net worth                             $12,669.64

  Change (30d):  +$2,340.00  (+22.7%)
```

Flags:
- `--date DATE` — as-of date (default: today)
- `--period monthly|quarterly|annual` — show trend over time
- `--months N` — how many months of trend (default: 6)

### `company worth breakdown`

```
company worth breakdown [--module MODULE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows detailed breakdown of worth by category/module |
| Reads | `hledger bs`, `assets/*.yaml`, `liabilities/*.yaml` |
| Writes | nothing |

### `company worth trend`

```
company worth trend [--months N] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows net worth over time as a sparkline or table |
| Reads | Runs `hledger bs` at multiple points |
| Writes | nothing |

Flags:
- `--months N` — number of months (default: 12)
- `--format FORMAT` — `table` (default), `csv`, `spark`

---

## Module: entity (subcommand of init/config)

### `company entity add`

```
company entity add [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Adds another billing entity to config |
| Reads | `config.yaml` |
| Writes | `config.yaml` |

### `company entity list`

```
company entity list
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all configured entities |
| Reads | `config.yaml` |
| Writes | nothing |

### `company entity edit <slug>`

```
company entity edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits entity configuration |
| Reads | `config.yaml` |
| Writes | `config.yaml` |

---

## Flag conventions

| Flag | Short | Meaning |
|------|-------|---------|
| `--yes` | `-y` | Skip interactive confirmations (accept defaults/proceed) |
| `--batch` | `-b` | Fully non-interactive; all values must come from flags or stdin |
| `--quiet` | `-q` | Suppress informational output (errors still print) |
| `--format` | `-f` | Output format: `table`, `csv`, `yaml`, `json` |
| `--from` | | Start date filter (YYYY-MM-DD) |
| `--to` | | End date filter (YYYY-MM-DD) |
| `--date` | `-d` | Specific date for an operation |
| `--help` | `-h` | Show help for command |
| `--dry-run` | | Show what would happen without writing |
| `--active` | | Filter to active/current records only |

---

## Interaction model

- **Interactive by default**: All `add`/`edit` commands prompt the user through fields one at a time, showing defaults in brackets. Press enter to accept default.
- **--batch mode**: All values supplied via flags. Missing required values cause an error with usage hint. No prompts.
- **--yes mode**: Prompts still appear but confirmations ("Generate? Y/n", "Remove? y/N") are auto-accepted.
- **Confirmations for destructive actions** default to No (must type `y`): removes, disposes.
- **Confirmations for generative actions** default to Yes (press enter): invoicing, pay runs.

---

## File layout (complete)

```
hledger-company/
├── company                  # CLI entry point
├── config.yaml              # entity config, defaults, accounts
├── config.example.yaml      # reference schema
├── assets/                  # per-asset YAML metadata
│   └── <slug>.yaml
├── liabilities/             # per-liability YAML
│   └── <slug>.yaml
├── contacts/                # per-contact YAML
│   └── <slug>.yaml
├── contracts/               # per-contract YAML
│   └── <slug>.yaml
├── payroll/
│   ├── people/              # payroll config per person
│   │   └── <slug>.yaml
│   └── runs/                # pay run records
│       └── <date>.yaml
├── projects/                # revenue projects (from consult)
│   └── <slug>.yaml
├── timesheets/
│   ├── unbilled.yaml        # pending time entries
│   └── billed/              # archived per invoice
│       └── <number>.yaml
├── journals/                # generated hledger journals
│   └── <year>/
│       ├── assets.journal
│       ├── amortization.journal
│       ├── liabilities.journal
│       ├── expenses.journal
│       ├── payroll.journal
│       └── revenue.journal
├── invoices/                # invoice-specific journals
│   └── <year>/
│       ├── <number>.journal
│       └── <number>-payment.journal
├── output/                  # generated PDFs
├── build/                   # intermediate template data
├── templates/               # Typst templates
│   └── invoice.typ
└── docs/
```

---

## Command count summary

| Module | Commands |
|--------|----------|
| init | 1 |
| generate | 1 |
| asset | 6 (add, list, show, edit, remove, dispose) |
| liability | 6 (add, list, show, edit, remove, pay) |
| expense | 5 (add, list, show, edit, remove) |
| revenue | 11 (log, log edit, status, invoice, paid, outstanding, export, undo, project add, project list, rate) |
| payroll | 7 (add, list, show, edit, remove, run, history) |
| contract | 5 (add, list, show, edit, remove) |
| contact | 5 (add, list, show, edit, remove) |
| worth | 3 (worth, breakdown, trend) |
| entity | 3 (add, list, edit) |
| **Total** | **53** |
