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

### `pair pairs`

Display the BitLedger account pair reference table.

```bash
pair pairs                       # full table (14 pairs)
pair pairs --normal              # normal operation pairs only
pair pairs --reversals           # reversal/correction pairs only
pair pairs --edge                # edge-case pairs only
pair pairs 5                     # show detail for pair #5
```

### `pair entry`

Interactive entry from any BitLedger pair. Prompts for pair selection, then walks through the entry fields for that pair type.

```bash
pair entry                        # interactive pair selection
pair entry 3                      # start from pair #3 directly
```

Generates: journal entry in the appropriate module journal.

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

### `pair asset summary`

Aggregate asset view by category.

```bash
pair asset summary               # summary by category
pair asset summary --division ops
```

Shows: total cost, total NBV, count, and amortization remaining — grouped by category.

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
```

Appends to: `generated/<year>/expenses.journal`

### `pair expense list`

```bash
pair expense list                # current month
pair expense list --period 2026-Q2
pair expense list --category software
pair expense list --division operations
```

---

## Income Module

### `pair income add`

Record non-operating income (interest, gains, one-off receipts).

```bash
pair income add
pair income add --batch --desc "Bank interest" --amount 42.50 \
    --account "Revenue:Non-Operating:Interest" --to chequing --date 2026-07-01
```

Appends to: `generated/<year>/income.journal`

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
```

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

  entity list|add|use     Entity (Company/Project) management
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

Use 'pair <command> --help' for details.
```
