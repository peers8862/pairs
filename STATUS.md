# pair — Feature Status

## Core Infrastructure

- [BUILT] CLI entry point (`pair`) with module-based dispatch
- [BUILT] lib/helpers.py — prompts, validators, money, config, slugify, global flag parsing
- [BUILT] lib/journal.py — format_entry, build_tags, atomic writes, include chain management, year scaffolding
- [BUILT] lib/yaml_store.py — generic YAML CRUD (load, save, list, delete, exists)
- [BUILT] `build_tags()` — central tag construction, config-driven enable/disable per tag type
- [BUILT] Auto-slug generation from entity names on all add commands
- [BUILT] Global flags: --help, --yes, --batch, --dry-run, --date, --quiet

## Modules

### Asset (`pair asset`)
- [BUILT] `add` — interactive + --batch, auto-slug, division prompt, payment method (cash/financed)
- [BUILT] `list` — table with totals, --all (disposed), --category, --division, --sort (name/cost/nbv/date), --detail (expanded columns), --format csv
- [BUILT] `summary` — aggregate by category (count, total cost, total NBV)
- [BUILT] `show <slug>` — full details + NBV + remaining months
- [BUILT] `show <slug> --schedule` — month-by-month amortization table through end of life
- [BUILT] `edit <slug>` — all fields editable, confirmation prompts on sensitive fields (cost, date, method)
- [BUILT] `dispose <slug>` — sold/scrapped/donated/traded-in, gain/loss calculation
- [BUILT] `amort` — generate amortization entries, straight-line + declining balance, partial periods, final adjustment, --asset, --through, --all
- [BUILT] `writedown <slug>` — partial impairment without full disposal (pair 0010)
- [BUILT] Declining balance rate: warns if >1, rejects if >100, offers conversion

### Liability (`pair liability`)
- [BUILT] `add` — interactive, auto PMT calculation, all loan types (loan/lease/credit-line/payable)
- [BUILT] `list` — with remaining balance, --all, --type filter
- [BUILT] `show <slug>` — details, payments made, total interest, remaining balance
- [BUILT] `pay <slug>` — single payment with automatic principal/interest split
- [BUILT] `payments` — bulk generate scheduled entries, --through, --liability
- [BUILT] `reclassify <slug>` — move between liability accounts (pair 1100)

### Worth (`pair worth`)
- [BUILT] Default report — current/fixed assets, liabilities (long/short term), net equity
- [BUILT] `--detail` — cost/amort/NBV columns for fixed assets
- [BUILT] `--period <date>` — point-in-time snapshot
- [BUILT] `--monthly` / `--quarterly` — trend over time via hledger
- [BUILT] `--division` — filter to one division
- [BUILT] `--raw` — pass-through to hledger bs
- [BUILT] Hybrid: computes from YAML + queries hledger for current assets when available

### Revenue (`pair revenue`)
- [BUILT] `project add` / `project list` — billing project management
- [BUILT] `rate <project>` — update rate for a project
- [BUILT] `log` / `log --batch` / `log edit` — time entry management
- [BUILT] `status` — unbilled summary
- [BUILT] `invoice` — generate invoice (PDF + journal)
- [BUILT] `paid` — record payment received
- [BUILT] `outstanding` — unpaid invoices with aging
- [BUILT] `export` — CSV export of time entries
- [BUILT] `undo` — remove last entry
- [BUILT] `defer` — record prepayment received, create deferred YAML, journal entry
- [BUILT] `recognize <slug>` — manually draw down deferred revenue, track remaining
- [BUILT] `deferred` — list all deferred items with balances

### Expense (`pair expense`)
- [BUILT] `add` — interactive + --batch, category selection, bank/credit-card, --division
- [BUILT] `list` — with --period (YYYY, YYYY-MM, YYYY-QN), --category, --division

### Income (`pair income`)
- [BUILT] `add` — non-operating income (interest, grants, gains, insurance, other), pair 0110/0111

### Transfer (`pair transfer`)
- [BUILT] Interactive asset-to-asset move (bank-to-bank, petty cash), pair 1011

### Contact (`pair contact`)
- [BUILT] `add` — interactive, auto-slug, all roles (client/vendor/employee/lender/entity)
- [BUILT] `list` — with --role filter, count
- [BUILT] `show <slug>` — full details + cross-reference tracking (which assets/liabilities/contracts reference this contact)
- [BUILT] `edit <slug>` — interactive field editing
- [BUILT] `remove <slug>` — with reference warning and confirmation

### Contract (`pair contract`)
- [BUILT] `add` — interactive, parties, renewal terms, linked assets/liabilities
- [BUILT] `list` — with --status, --type, --expiring N (days), expiry warnings (⚠/✗)
- [BUILT] `show <slug>` — full details, party resolution, days until expiry
- [BUILT] `edit <slug>` — interactive field editing

### Equity (`pair equity`)
- [BUILT] `invest` — owner puts cash in (pair 1001)
- [BUILT] `draw` — owner takes cash out (pair 1001 reversed)
- [BUILT] `convert` — convert liability to equity / debt-for-equity swap (pair 1010)

### Tax (`pair tax`)
- [BUILT] `summary` — HST collected vs paid, net owing, period-aware (--period, --year)
- [BUILT] `remit` — record remittance payment to CRA

### Recurring (`pair recurring`)
- [BUILT] `add` — define entry with frequency (monthly/quarterly/annual/biweekly), accounts, pair code
- [BUILT] `list` — show all with last generated date
- [BUILT] `generate` — fill in missing occurrences through a date, --entry, --through, --dry-run
- [BUILT] `remove <slug>` — delete definition (generated entries preserved)

### Budget (`pair budget`)
- [BUILT] `set` — set monthly budget per account per year
- [BUILT] `vs` — compare actual vs budget for a period, variance with warnings

### Payroll (`pair payroll`)
- [BUILT] `run` — contractor (simple) or employee (with deductions: CPP, EI, tax)
- [BUILT] `list` — show pay runs for a year

### Division (`pair division`)
- [BUILT] `list` — show configured divisions with entity counts across modules

### Year (`pair year`)
- [BUILT] `new <YYYY>` — scaffold directories, includes, empty journals
- [BUILT] `close <YYYY>` — generate closing entries (zero income/expense into retained earnings, pair 1101)

## Core Commands

- [BUILT] `pair init` — first-time setup, creates config, dirs, account chart, journal file if missing
- [BUILT] `pair config` — view current config, prompt to edit (name, currency, divisions, tags, style)
- [BUILT] `pair generate` — regenerate all generated journals from YAML, --module, --year, --dry-run
- [BUILT] `pair journal` — synthesized output for any period, --from/--to, --year, --module, --output, --with-accounts
- [BUILT] `pair status` — include chain health, pending amortization/payments, entity counts
- [BUILT] `pair where <query>` — search YAML filenames/content and journal entries
- [BUILT] `pair pairs` — BitLedger reference table (wide 3-column + grouped), --normal, --reversals, --edge, <number> drill-down
- [BUILT] `pair entry` — interactive entry creation from any of 14 pairs, direction choice, smart account defaults, preview

## BitLedger Pair Coverage

- [BUILT] 0000 Op Expense / Asset — expense, payroll, recurring
- [BUILT] 0001 Op Expense / Liability — expense, payroll
- [BUILT] 0010 Non-Op Expense / Asset — asset amort, asset writedown, asset dispose (loss)
- [BUILT] 0011 Non-Op Expense / Liability — liability pay (interest portion), pair command
- [BUILT] 0100 Op Income / Asset — revenue invoice/paid, pair command
- [BUILT] 0101 Op Income / Liability — revenue defer/recognize, pair command
- [BUILT] 0110 Non-Op Income / Asset — income add, asset dispose (gain)
- [BUILT] 0111 Non-Op Income / Liability — income add (accrued), pair command
- [BUILT] 1000 Asset / Liability — asset add (financed), liability add, liability pay, tax remit
- [BUILT] 1001 Asset / Equity — equity invest, equity draw
- [BUILT] 1010 Liability / Equity — equity convert
- [BUILT] 1011 Asset / Asset — asset add (cash), transfer, revenue paid
- [BUILT] 1100 Liability / Liability — liability reclassify
- [BUILT] 1101 Equity / Equity — year close

## Configuration

- [BUILT] `config.yaml` — entity name/slug/currency, journal file, accounts, fiscal year start
- [BUILT] `divisions: []` — optional list of division names
- [BUILT] `tags: {}` — per-tag enable/disable (pair, source, division, category, seq, period)
- [BUILT] `style: {}` — operational preferences (revenue: invoice|simple)
- [PLANNING] `defaults.last_division` — auto-track last used division for convenience

## Documentation

- [BUILT] README.md — overview, requirements, install, quick start, commands, file structure
- [BUILT] docs/install.md — prerequisites, install, first run, daily use
- [BUILT] docs/account-chart.md — full hierarchy + BitLedger pair-to-account mapping
- [BUILT] docs/yaml-schemas.md — contact, asset, liability, contract schemas with examples
- [BUILT] docs/file-organization.md — directory tree, include chain, git strategy
- [BUILT] docs/journal-rules.md — exact hledger entries for all modules
- [BUILT] docs/worth-command.md — net worth report design with mocked output
- [BUILT] docs/commands.md — full command surface with syntax and flags
- [BUILT] docs/migration.md — consult → pair migration table and build order
- [BUILT] entity-tool-design-ref.md — BitLedger pair table + module mapping

### Report (`pair report`)
- [BUILT] Passthrough to hledger with auto-resolved entity journal
- [BUILT] Supports all hledger commands: bs, is, register, cashflow, bal, accounts, stats
- [BUILT] Fallback from entity.journal to company.journal for older entities

### Link Mode (`pair link`)
- [BUILT] CLI progressive entry assembly via gum
- [BUILT] All 14 pair expressions: `< > << >> <. >. <<. >>. <.> <.. >.. ..< ..> ..`
- [BUILT] `/` suffix for reversals
- [BUILT] Inline amount: `< 3650`, `<. 4500`
- [BUILT] Leaf-name display with category hints
- [BUILT] Fuzzy account matching with priority ordering
- [BUILT] Auto-resolve when only one counterpart option

### Popup Mode (`pair .`)
- [BUILT] Rofi-based floating popup with two-column layout
- [BUILT] Same 14 expressions as link mode
- [BUILT] Progressive entry assembly in right panel
- [BUILT] Dark One Dark themed, pango-escaped

### PWA (`pair web`)
- [BUILT] FastAPI + vanilla JS progressive web app
- [BUILT] Dashboard: net worth sparklines, revenue/P&L sparklines, quick entry box, recent transactions
- [BUILT] Quick entry: description → account (autocomplete) → amount → tags → date → write
- [BUILT] Universal launcher: pairs shorthand, tab names, or description from one input
- [BUILT] Pair identity badge: auto-infers which of 14 pairs from account types
- [BUILT] Counterpart priority ordering based on accounting relationships
- [BUILT] Pairs tab: all 14 expressions with fuzzy account search
- [BUILT] Manage tab: assets, liabilities, equity, income, expenses, payroll, recurring, contracts, contacts, commodities
- [BUILT] Payroll: YTD summary, employee list, recent runs, run new payroll from web
- [BUILT] Charts tab (Chart.js): net worth, P&L, revenue, expenses, cash flow, commodity prices
- [BUILT] Reports tab: BS, IS, cashflow, register with period filter
- [BUILT] Codes tab: full 14-pair reference with expression column
- [BUILT] Entity switcher in header
- [BUILT] PWA manifest + service worker for installability
- [BUILT] Auto-include links.journal in year file on first write
- [BUILT] Commodity directive (CAD 1,000.00) for 2-decimal display

## Pending

- [PENDING] Inventory/COGS module — stock quantities, cost layering (FIFO/LIFO/average), purchase costing, sales reducing inventory. Deferred: complex domain, only needed for product businesses.
- [PENDING] Bank reconciliation CSV import — the module structure exists but does not do CSV/OFX import or statement matching. Significant feature for future phase.
- [PENDING] Narrow terminal fallback for `pair pairs` wide table — currently assumes wide terminal
- [PENDING] `defaults.last_division` auto-tracking — division prompt works without it, minor convenience

## Planning / Future

- [PLANNING] `pair asset transfer <slug> --to <division>` — move asset between divisions
- [PLANNING] Division-level P&L reporting — income statement per division
- [PLANNING] `pair revenue receive` — quick cash receipt without full invoice (for style: simple)
- [PLANNING] Multi-currency worth report with conversion flags (--cost, --value=now)
- [PLANNING] `entity report` — customizable report builder wrapping hledger queries
- [PLANNING] Migration script for existing consult users (automate entity → contact conversion)
- [PLANNING] Refactor all existing modules to call `build_tags()` instead of inline tag dicts
- [PLANNING] Receipt file linking — `receipt:path/to/file.pdf` tag on expense entries
