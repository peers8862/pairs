# hledger-company — Command Surface

## Discovery

The tool finds its data directory by looking for `config.yaml` starting from CWD and walking upward. `company init` always operates in CWD.

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

### `company init`

First-time setup. Interactive.

```bash
company init
```

Creates: `config.yaml`, directory structure, `include/company.journal`, `include/accounts.journal`

Asks: company name, entity slug, currency, journal file path, bank account name, fiscal year start.

### `company generate`

Regenerate all journals from YAML sources.

```bash
company generate                    # regenerate everything
company generate --module amort     # just amortization
company generate --module payments  # just loan payments
company generate --year 2026        # just one year
company generate --dry-run          # preview without writing
```

Reads: `assets/*.yaml`, `liabilities/*.yaml`
Writes: `generated/<year>/*.journal`, `include/*.journal`

### `company year new <YYYY>`

Scaffold a new fiscal year.

```bash
company year new 2027
```

Creates: `journal/2027/`, `generated/2027/`, `include/2027.journal`
Updates: `include/company.journal`

### `company year close <YYYY>`

Generate closing entries for a completed fiscal year.

```bash
company year close 2025
company year close 2025 --dry-run
```

Generates: closing entries that zero out revenue/expense accounts into retained earnings.
Writes: `generated/<year>/closing.journal`

### `company config`

View or edit configuration.

```bash
company config                      # display current config
company config --edit               # open config.yaml in $EDITOR
company config currency             # show specific field
company config currency CAD         # set specific field
```

Reads/writes: `config.yaml`

### `company status`

Show system status and pending items.

```bash
company status
```

Displays: outstanding invoices, upcoming payments, expiring contracts, assets due for amortization, deferred revenue awaiting recognition.

### `company where <query>`

Find entities and entries matching a search query.

```bash
company where "acme"                # find contacts, contracts, invoices mentioning acme
company where "2026-03"             # find entries in March 2026
company where "equipment"           # find assets, expenses by category
```

Searches across: contacts, contracts, assets, liabilities, invoices, journal entries.

### `company pairs`

Display the BitLedger account pair reference table.

```bash
company pairs                       # full table (14 pairs)
company pairs --normal              # normal operation pairs only
company pairs --reversals           # reversal/correction pairs only
company pairs --edge                # edge-case pairs only
company pairs 5                     # show detail for pair #5
```

### `company pair`

Interactive entry from any BitLedger pair. Prompts for pair selection, then walks through the entry fields for that pair type.

```bash
company pair                        # interactive pair selection
company pair 3                      # start from pair #3 directly
```

Generates: journal entry in the appropriate module journal.

---

## Asset Module

### `company asset add`

Record a new capital asset. Interactive.

```bash
company asset add
company asset add --batch --name "MacBook Pro" --cost 4299 --category equipment \
    --date 2026-03-15 --life 60 --method straight-line --salvage 500
company asset add --division operations
```

Creates: `assets/<slug>.yaml`
Generates: acquisition entry in `generated/<year>/assets.journal`

### `company asset list`

```bash
company asset list                  # all active assets
company asset list --all            # include disposed
company asset list --category equipment
company asset list --division operations
company asset list --detail         # full breakdown per asset
company asset list --sort cost      # sort by cost|nbv|date|name
company asset list --format csv     # CSV output
company asset list --schedule       # show amortization schedule
```

### `company asset show <slug>`

```bash
company asset show macbook-pro-2026
```

Shows: name, cost, NBV, amortization schedule, remaining life.

### `company asset edit <slug>`

```bash
company asset edit macbook-pro-2026
```

Interactive edit of YAML fields. Regenerates affected journals.

### `company asset dispose <slug>`

```bash
company asset dispose macbook-pro-2026
company asset dispose macbook-pro-2026 --method sold --proceeds 1500 --date 2027-06-10
```

Updates: `assets/<slug>.yaml` (adds disposal section)
Generates: disposal entry in `generated/<year>/assets.journal`

### `company asset amort`

Generate/regenerate amortization entries.

```bash
company asset amort                 # all assets, current year
company asset amort --all           # all assets, all years
company asset amort --asset macbook-pro-2026
company asset amort --through 2026-12-31
```

Writes: `generated/<year>/amortization.journal`

### `company asset writedown <slug>`

Record a partial impairment (write-down) of an asset's book value.

```bash
company asset writedown macbook-pro-2026
company asset writedown macbook-pro-2026 --amount 1000 --date 2026-06-30 \
    --reason "screen damage"
```

Updates: `assets/<slug>.yaml` (adds impairment record)
Generates: impairment entry in `generated/<year>/assets.journal`

### `company asset summary`

Aggregate asset view by category.

```bash
company asset summary               # summary by category
company asset summary --division ops
```

Shows: total cost, total NBV, count, and amortization remaining — grouped by category.

---

## Liability Module

### `company liability add`

```bash
company liability add
company liability add --batch --name "Vehicle Loan" --type loan --principal 35000 \
    --rate 5.49 --term 60 --start 2026-01-15
```

Creates: `liabilities/<slug>.yaml`
Generates: creation entry in `generated/<year>/liabilities.journal`

### `company liability list`

```bash
company liability list              # all active
company liability list --type loan
```

### `company liability show <slug>`

Shows: remaining balance, payment schedule, interest paid to date.

### `company liability pay <slug>`

Record a payment.

```bash
company liability pay vehicle-loan-2026
company liability pay vehicle-loan-2026 --amount 668.54 --date 2026-02-15
```

Generates: payment entry in `generated/<year>/loan-payments.journal`

### `company liability payments`

Generate scheduled payment entries.

```bash
company liability payments                  # all, current year
company liability payments --through 2026-12-31
company liability payments --liability vehicle-loan-2026
```

Writes: `generated/<year>/loan-payments.journal`

### `company liability reclassify <slug>`

Reclassify a liability between liability accounts (e.g., move from long-term to current, or between account categories).

```bash
company liability reclassify vehicle-loan-2026
company liability reclassify vehicle-loan-2026 --to "Liabilities:Current:Vehicle Loan" \
    --date 2026-07-01
```

Updates: `liabilities/<slug>.yaml` (account field)
Generates: reclassification entry in `generated/<year>/liabilities.journal`

---

## Expense Module

### `company expense add`

```bash
company expense add
company expense add --batch --desc "Office Supplies" --amount 147.50 \
    --account "Expenses:Operating:Office Supplies" --from chequing --date 2026-07-10
company expense add --division admin
```

Appends to: `generated/<year>/expenses.journal`

### `company expense list`

```bash
company expense list                # current month
company expense list --period 2026-Q2
company expense list --category software
company expense list --division operations
```

---

## Income Module

### `company income add`

Record non-operating income (interest, gains, one-off receipts).

```bash
company income add
company income add --batch --desc "Bank interest" --amount 42.50 \
    --account "Revenue:Non-Operating:Interest" --to chequing --date 2026-07-01
```

Appends to: `generated/<year>/income.journal`

---

## Transfer Module

### `company transfer`

Record an asset-to-asset transfer (e.g., move funds between bank accounts).

```bash
company transfer
company transfer --batch --from chequing --to savings --amount 5000 --date 2026-07-01
```

Appends to: `generated/<year>/transfers.journal`

---

## Contact Module

### `company contact add`

```bash
company contact add
company contact add --batch --name "Acme Corp" --role client --email billing@acme.com
```

Creates: `contacts/<slug>.yaml`

### `company contact list`

```bash
company contact list
company contact list --role vendor
company contact list --role entity
```

### `company contact show <slug>`

### `company contact edit <slug>`

### `company contact remove <slug>`

Requires `--yes` or confirmation.

---

## Contract Module

### `company contract add`

```bash
company contract add
```

Creates: `contracts/<slug>.yaml`

### `company contract list`

```bash
company contract list               # active contracts
company contract list --status expired
company contract list --expiring 30  # expiring within 30 days
```

### `company contract show <slug>`

### `company contract edit <slug>`

---

## Revenue Module

All revenue commands, namespaced under `revenue`:

```bash
company revenue project add         # create client project
company revenue project list        # list projects
company revenue rate <project>      # update rate
company revenue log                 # log time (interactive)
company revenue log --batch         # batch log
company revenue log edit            # edit entry
company revenue status              # unbilled summary
company revenue invoice             # generate invoice
company revenue paid                # record payment
company revenue outstanding         # unpaid invoices + aging
company revenue export              # CSV export
company revenue undo                # remove last entry
```

### `company revenue defer`

Record a prepayment (deferred revenue) received from a client.

```bash
company revenue defer
company revenue defer --batch --project acme-web --amount 12000 \
    --date 2026-07-01 --periods 6 --desc "6-month retainer"
```

Generates: entry crediting deferred revenue liability, debiting bank.
Creates: `deferred/<slug>.yaml`

### `company revenue recognize <slug>`

Recognize a portion of deferred revenue as earned.

```bash
company revenue recognize acme-web-retainer
company revenue recognize acme-web-retainer --amount 2000 --date 2026-08-01
```

Generates: entry debiting deferred revenue, crediting earned revenue.
Updates: `deferred/<slug>.yaml` (tracks recognized amounts)

### `company revenue deferred`

List all deferred revenue items and their recognition status.

```bash
company revenue deferred            # all active deferred items
company revenue deferred --all      # include fully recognized
```

Shows: original amount, recognized to date, remaining, next recognition date.

---

## Payroll Module

### `company payroll run`

```bash
company payroll run
company payroll run --period 2026-07-01_to_2026-07-15
```

Interactive: select employees/contractors, enter hours/amounts, confirm.
Creates: `payroll/<period>.yaml`
Generates: entries in `generated/<year>/payroll.journal`

### `company payroll list`

```bash
company payroll list                # recent pay runs
company payroll list --year 2026
```

---

## Equity Module

### `company equity invest`

Owner puts money into the business.

```bash
company equity invest --amount 10000 --date 2026-01-01
```

### `company equity draw`

Owner takes money out.

```bash
company equity draw --amount 2000 --date 2026-07-01
```

### `company equity convert`

Convert a liability to equity (e.g., shareholder loan conversion).

```bash
company equity convert
company equity convert --liability shareholder-loan --amount 25000 --date 2026-07-01
```

Generates: entry debiting the liability account, crediting equity.
Updates: `liabilities/<slug>.yaml` (marks converted portion)

---

## Division Module

### `company division list`

Show all divisions with entity counts.

```bash
company division list
```

Shows: division name, number of assets, expenses, and revenue entries per division.

---

## Worth Module

### `company worth`

Net worth report (headline command).

```bash
company worth                       # current net worth
company worth --period 2026-06-30   # as of date
company worth --monthly             # monthly trend
company worth --quarterly           # quarterly trend
company worth --detail              # full account breakdown
company worth --division operations # filter by division
company worth --raw                 # pass-through to hledger bs
```

---

## Help

```
$ company

company — business accounting on hledger

Commands:
  init                    First-time setup
  generate                Regenerate journals from YAML
  year new|close          Scaffold or close a fiscal year
  config                  View/edit configuration
  status                  System status and pending items
  where <query>           Find entities and entries
  worth                   Net worth report
  pairs                   BitLedger pair reference table
  pair                    Interactive entry from any pair

  asset add|list|show|edit|dispose|amort|writedown|summary
  liability add|list|show|pay|payments|reclassify
  expense add|list
  income add
  transfer                Asset-to-asset moves
  contact add|list|show|edit|remove
  contract add|list|show|edit
  revenue project|log|invoice|paid|outstanding|status|export|undo|rate|defer|recognize|deferred
  payroll run|list
  equity invest|draw|convert
  division list

Use 'company <command> --help' for details.
```
