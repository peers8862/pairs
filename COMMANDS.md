# pair — Command Surface

CLI entry point: `pair`

---

## Data directory discovery

The tool searches for `config.yaml` starting from the current working directory and walking upward until `/`. If found, that directory becomes the data root. If not found, all commands except `pair init` exit with:

```
No config.yaml found. Run 'pair init' to set up, or run from within an entity directory.
```

`pair init` always operates in the current directory.

---

## Help output format

```
pair - plain-text accounting for your business

Usage: pair <module> <verb> [args] [flags]

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

Run 'pair <module> --help' for module-specific commands.
Run 'pair <command> --help' for detailed usage.
```

---

## Global commands

### `pair init`

```
pair init [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with --yes for defaults) |
| Does | Creates config.yaml, directory structure, and first entity |
| Writes | `config.yaml`, directories: `assets/`, `liabilities/`, `contacts/`, `contracts/`, `payroll/`, `journals/`, `invoices/`, `templates/`, `output/`, `build/` |

#### Init flow

1. Entity name — "What is the entity name (Company/Project)?"
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

### `pair generate`

```
pair generate [--year YYYY] [--module MODULE] [--dry-run]
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

### `pair asset add`

```
pair asset add [--yes] [--batch]
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

### `pair asset list`

```
pair asset list [--active] [--category CATEGORY] [--format FORMAT]
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

### `pair asset show <slug>`

```
pair asset show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full details of an asset including amortization schedule |
| Reads | `assets/<slug>.yaml` |
| Writes | nothing |

### `pair asset edit <slug>`

```
pair asset edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits an asset's metadata (walks through fields showing current values) |
| Reads | `assets/<slug>.yaml` |
| Writes | `assets/<slug>.yaml`, regenerates affected journals |

### `pair asset remove <slug>`

```
pair asset remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm unless --yes) |
| Does | Removes an asset record and its generated journal entries |
| Reads | `assets/<slug>.yaml` |
| Writes | removes `assets/<slug>.yaml`, regenerates `journals/<year>/assets.journal`, `journals/<year>/amortization.journal` |

### `pair asset dispose <slug>`

```
pair asset dispose <slug> [--date DATE] [--amount AMOUNT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records disposal/sale of an asset, calculates gain or loss |
| Reads | `assets/<slug>.yaml`, `config.yaml` |
| Writes | `assets/<slug>.yaml` (marks disposed), regenerates journals |

---

## Module: liability

### `pair liability add`

```
pair liability add [--yes] [--batch]
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

### `pair liability list`

```
pair liability list [--active] [--type TYPE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all liabilities with current balance |
| Reads | `liabilities/*.yaml` |
| Writes | nothing |

### `pair liability show <slug>`

```
pair liability show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full liability details including payment schedule and balance |
| Reads | `liabilities/<slug>.yaml` |
| Writes | nothing |

### `pair liability edit <slug>`

```
pair liability edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits a liability's terms |
| Reads | `liabilities/<slug>.yaml` |
| Writes | `liabilities/<slug>.yaml`, regenerates journals |

### `pair liability remove <slug>`

```
pair liability remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a liability record |
| Reads | `liabilities/<slug>.yaml` |
| Writes | removes file, regenerates journals |

### `pair liability pay <slug>`

```
pair liability pay <slug> [--date DATE] [--amount AMOUNT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records a payment against a liability |
| Reads | `liabilities/<slug>.yaml`, `config.yaml` |
| Writes | `liabilities/<slug>.yaml`, `journals/<year>/liabilities.journal` |

---

## Module: expense

### `pair expense add`

```
pair expense add [--yes] [--batch]
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

### `pair expense list`

```
pair expense list [--from DATE] [--to DATE] [--category CATEGORY] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists expenses matching filters |
| Reads | `journals/*/expenses.journal` |
| Writes | nothing |

### `pair expense show <id>`

```
pair expense show <id>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows details of a specific expense entry |
| Reads | `journals/*/expenses.journal` |
| Writes | nothing |

### `pair expense edit <id>`

```
pair expense edit <id> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits an expense entry |
| Reads | `journals/*/expenses.journal` |
| Writes | `journals/<year>/expenses.journal` |

### `pair expense remove <id>`

```
pair expense remove <id> [--yes]
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

### `pair revenue log`

```
pair revenue log [--batch] [--project PROJECT]
```

| | |
|---|---|
| Mode | Interactive (batch with --batch) |
| Does | Logs billable/non-billable time to a project |
| Reads | `config.yaml`, `projects/<slug>.yaml` |
| Writes | `timesheets/unbilled.yaml` |

Interactive prompts: date, project, hours, focus/description, type (billable/research/admin), tax override, tags.

### `pair revenue log edit`

```
pair revenue log edit [--project PROJECT]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits a previously logged time entry |
| Reads | `timesheets/unbilled.yaml` |
| Writes | `timesheets/unbilled.yaml` |

### `pair revenue status`

```
pair revenue status [--project PROJECT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows unbilled hours and amounts per project |
| Reads | `timesheets/unbilled.yaml`, `projects/*.yaml` |
| Writes | nothing |

### `pair revenue invoice`

```
pair revenue invoice [--project PROJECT] [--yes]
```

| | |
|---|---|
| Mode | Interactive (--yes skips confirmation) |
| Does | Generates an invoice PDF and hledger journal entry from unbilled time |
| Reads | `timesheets/unbilled.yaml`, `config.yaml`, `projects/<slug>.yaml`, `templates/*.typ` |
| Writes | `output/invoice-<number>.pdf`, `invoices/<year>/<number>.journal`, `timesheets/billed/<number>.yaml`, `build/<number>.yaml` |

### `pair revenue paid`

```
pair revenue paid [--invoice NUMBER] [--amount AMOUNT] [--date DATE] [--yes]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Records payment received against an outstanding invoice |
| Reads | `timesheets/billed/*.yaml`, `config.yaml` |
| Writes | `timesheets/billed/<number>.yaml`, `invoices/<year>/<number>-payment.journal` |

### `pair revenue outstanding`

```
pair revenue outstanding [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows unpaid invoices grouped by aging bucket |
| Reads | `timesheets/billed/*.yaml` |
| Writes | nothing |

### `pair revenue export`

```
pair revenue export [--project PROJECT] [--from DATE] [--to DATE] [--type TYPE] [--tag TAG] [--all]
```

| | |
|---|---|
| Mode | Scriptable (outputs to stdout) |
| Does | Exports time entries to CSV |
| Reads | `timesheets/unbilled.yaml`, `timesheets/billed/*.yaml` (with --all) |
| Writes | stdout (CSV) |

### `pair revenue undo`

```
pair revenue undo [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm unless --yes) |
| Does | Removes the last logged time entry |
| Reads | `timesheets/unbilled.yaml` |
| Writes | `timesheets/unbilled.yaml` |

### `pair revenue project add`

```
pair revenue project add [--yes] [--batch]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Creates a new client billing project |
| Reads | `config.yaml` |
| Writes | `projects/<slug>.yaml` |

### `pair revenue project list`

```
pair revenue project list [--active]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all revenue projects |
| Reads | `projects/*.yaml` |
| Writes | nothing |

### `pair revenue rate <project>`

```
pair revenue rate <project> [--amount AMOUNT] [--from DATE] [--type TYPE]
```

| | |
|---|---|
| Mode | Interactive (scriptable with flags) |
| Does | Adds a new effective rate for a project |
| Reads | `projects/<slug>.yaml` |
| Writes | `projects/<slug>.yaml` |

---

## Module: payroll

### `pair payroll add`

```
pair payroll add [--yes] [--batch]
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

### `pair payroll list`

```
pair payroll list [--active] [--type TYPE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists people on payroll |
| Reads | `payroll/people/*.yaml` |
| Writes | nothing |

### `pair payroll show <slug>`

```
pair payroll show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows payroll details for a person including pay history |
| Reads | `payroll/people/<slug>.yaml`, `payroll/runs/*.yaml` |
| Writes | nothing |

### `pair payroll edit <slug>`

```
pair payroll edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits payroll configuration for a person |
| Reads | `payroll/people/<slug>.yaml` |
| Writes | `payroll/people/<slug>.yaml` |

### `pair payroll remove <slug>`

```
pair payroll remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a person from payroll (marks inactive) |
| Reads | `payroll/people/<slug>.yaml` |
| Writes | `payroll/people/<slug>.yaml` |

### `pair payroll run`

```
pair payroll run [--date DATE] [--person SLUG] [--yes]
```

| | |
|---|---|
| Mode | Interactive (--yes for auto-confirm) |
| Does | Runs payroll for the current period, generating payment entries |
| Reads | `payroll/people/*.yaml`, `config.yaml` |
| Writes | `payroll/runs/<date>.yaml`, `journals/<year>/payroll.journal` |

### `pair payroll history`

```
pair payroll history [--person SLUG] [--from DATE] [--to DATE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows payroll run history |
| Reads | `payroll/runs/*.yaml` |
| Writes | nothing |

---

## Module: contract

### `pair contract add`

```
pair contract add [--yes] [--batch]
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

### `pair contract list`

```
pair contract list [--active] [--type TYPE] [--expiring DAYS]
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

### `pair contract show <slug>`

```
pair contract show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows full contract details |
| Reads | `contracts/<slug>.yaml` |
| Writes | nothing |

### `pair contract edit <slug>`

```
pair contract edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits contract details |
| Reads | `contracts/<slug>.yaml` |
| Writes | `contracts/<slug>.yaml` |

### `pair contract remove <slug>`

```
pair contract remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a contract record |
| Reads | `contracts/<slug>.yaml` |
| Writes | removes `contracts/<slug>.yaml` |

---

## Module: contact

### `pair contact add`

```
pair contact add [--yes] [--batch]
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

### `pair contact list`

```
pair contact list [--type TYPE] [--tag TAG] [--format FORMAT]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all contacts |
| Reads | `contacts/*.yaml` |
| Writes | nothing |

### `pair contact show <slug>`

```
pair contact show <slug>
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows contact details and linked contracts/projects |
| Reads | `contacts/<slug>.yaml`, `contracts/*.yaml`, `projects/*.yaml` |
| Writes | nothing |

### `pair contact edit <slug>`

```
pair contact edit <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Edits contact information |
| Reads | `contacts/<slug>.yaml` |
| Writes | `contacts/<slug>.yaml` |

### `pair contact remove <slug>`

```
pair contact remove <slug> [--yes]
```

| | |
|---|---|
| Mode | Interactive (confirm) |
| Does | Removes a contact (warns if referenced by contracts/projects) |
| Reads | `contacts/<slug>.yaml`, `contracts/*.yaml`, `projects/*.yaml` |
| Writes | removes `contacts/<slug>.yaml` |

---

## Module: worth

### `pair worth`

```
pair worth [--date DATE] [--period monthly|quarterly|annual] [--months N]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows net worth statement: assets, liabilities, and equity |
| Reads | Runs `hledger bs` against configured journal; reads `assets/*.yaml` for book values |
| Writes | nothing |

Output:
```
Entity Net Worth — 2026-07-15

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

### `pair worth breakdown`

```
pair worth breakdown [--module MODULE]
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Shows detailed breakdown of worth by category/module |
| Reads | `hledger bs`, `assets/*.yaml`, `liabilities/*.yaml` |
| Writes | nothing |

### `pair worth trend`

```
pair worth trend [--months N] [--format FORMAT]
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

### `pair entity add`

```
pair entity add [--yes]
```

| | |
|---|---|
| Mode | Interactive |
| Does | Adds another billing entity to config |
| Reads | `config.yaml` |
| Writes | `config.yaml` |

### `pair entity list`

```
pair entity list
```

| | |
|---|---|
| Mode | Scriptable |
| Does | Lists all configured entities |
| Reads | `config.yaml` |
| Writes | nothing |

### `pair entity edit <slug>`

```
pair entity edit <slug> [--yes]
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
pair/
├── pair                     # CLI entry point
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

---

## `pair report`

```
pair report <hledger-command> [args...]
```

| Field | Detail |
|-------|--------|
| Does | Passes any hledger command through to the active entity's journal |
| Reads | Active entity's journal file (entity.journal or company.journal) |
| Writes | Nothing |

Examples:
- `pair report bs` — balance sheet
- `pair report is -p 2026-Q2` — income statement for Q2
- `pair report register expenses -M` — monthly expense register
- `pair report cashflow` — cash flow statement

---

## `pair link`

```
pair link
```

| Field | Detail |
|-------|--------|
| Does | Progressive entry assembly via gum CLI |
| Reads | Entity accounts (via hledger), config |
| Writes | `generated/<year>/links.journal` |
| Requires | gum (charmbracelet/gum) |

Expressions (all 14 pairs):

| Expression | Pair | Description |
|---|---|---|
| `<` | 1 | Op expense paid from asset |
| `>` | 2 | Op expense on credit |
| `<<` | 3 | Non-op expense from asset |
| `>>` | 4 | Non-op expense on credit |
| `<.` | 5 | Op income received as asset |
| `>.` | 6 | Op income from liability |
| `<<.` | 7 | Non-op income received |
| `>>.` | 8 | Non-op income from liability |
| `<.>` | 9 | Asset from liability (loan) |
| `<..` | 10 | Asset from equity |
| `>..` | 11 | Liability from equity |
| `..<` | 12 | Asset to asset transfer |
| `..>` | 13 | Liability to liability |
| `..` | 14 | Equity to equity |

Append `/` for reversal. Amount optional after space.

---

## `pair .`

```
pair .
```

| Field | Detail |
|-------|--------|
| Does | Rofi popup entry assembly with two-column layout |
| Reads | Entity accounts, config |
| Writes | `generated/<year>/links.journal` |
| Requires | rofi 1.7+ |

Same 14 expressions as `pair link`. Left panel: selection. Right panel: assembling entry preview.

---

## `pair web`

```
pair web [--port PORT]
```

| Field | Detail |
|-------|--------|
| Does | Starts PWA server for progressive entry, dashboards, charts, reporting |
| Reads | Entity config, YAML data, hledger journals |
| Writes | `generated/<year>/links.journal`, `generated/<year>/payroll.journal` |
| Requires | fastapi, uvicorn (in .venv) |
| Default port | 8100 |

Tabs:
- **Dashboard** — net worth + sparklines, quick entry, recent transactions
- **Pairs** — link-mode entry with 14 expressions
- **Manage** — assets, liabilities, equity, income, expenses, payroll, recurring, contracts, contacts, commodities
- **Charts** — net worth, P&L, revenue, expenses, cash flow, commodity prices
- **Reports** — balance sheet, income statement, cash flow, register
- **Codes** — 14-pair reference table

API endpoints:
- `GET /api/status` — entity, currency, date
- `GET /api/pairs` — 14 pair definitions
- `GET /api/accounts?expr=` — account list with leaf display
- `POST /api/entry` — write journal entry
- `GET /api/worth` — net worth breakdown
- `GET /api/recent?limit=` — recent transactions (grouped)
- `GET /api/entities` — list entities
- `POST /api/switch?slug=` — change active entity
- `GET /api/report?cmd=&period=` — hledger report passthrough
- `GET /api/assets` — asset YAML data
- `GET /api/liabilities` — liability YAML data
- `GET /api/contacts` — contact YAML data
- `GET /api/contracts` — contract YAML data
- `GET /api/recurring` — recurring YAML data
- `GET /api/expenses?period=` — expense balances
- `GET /api/equity?period=` — equity balances
- `GET /api/income?period=` — income balances
- `GET /api/tax` — tax account balances
- `GET /api/commodities` — commodity list with latest prices
- `GET /api/payroll` — employees, YTD totals, recent runs
- `POST /api/payroll/run` — record a pay run
- `GET /api/chart/networth` — monthly net worth time series
- `GET /api/chart/profitloss` — monthly P&L time series
- `GET /api/chart/revenue` — monthly revenue breakdown
- `GET /api/chart/expenses` — monthly expense breakdown
- `GET /api/chart/cashflow` — monthly cash balances
- `GET /api/chart/prices` — commodity price history
- `GET /api/pairs-ref` — full 14-pair reference data
- `GET /api/status-items` — pending items and alerts
