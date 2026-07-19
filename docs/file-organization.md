# pair — File Organization

## Directory Tree

```
pair/
├── pair                             # CLI entry point (executable)
├── config.yaml                      # tool settings, defaults
├── config.example.yaml              # reference schema (committed)
│
├── contacts/                        # [STANDALONE] one YAML per contact
│   ├── acme-corp.yaml
│   └── clairlea.yaml               # your billing entity (role: entity)
│
├── contracts/                       # [STANDALONE] one YAML per contract
│   └── acme-retainer-2026.yaml
│
├── assets/                          # [STANDALONE] one YAML per capital asset
│   ├── macbook-pro-2025.yaml
│   └── office-furniture.yaml
│
├── liabilities/                     # [STANDALONE] one YAML per liability
│   ├── equipment-loan.yaml
│   └── line-of-credit.yaml
│
├── projects/                        # [STANDALONE] billing projects (from consult)
│   └── acme-consulting.yaml
│
├── journal/                         # [USER-EDITABLE] general entry journals
│   ├── 2025/
│   │   ├── opening.journal         # opening balances
│   │   ├── adjustments.journal     # manual adjustments
│   │   └── closing.journal         # year-end closing entries
│   └── 2026/
│       ├── opening.journal
│       └── adjustments.journal
│
├── generated/                       # [GENERATED] tool writes, never hand-edit
│   ├── 2025/
│   │   ├── amortization.journal
│   │   ├── loan-payments.journal
│   │   ├── payroll.journal
│   │   └── revenue.journal
│   └── 2026/
│       ├── amortization.journal
│       ├── loan-payments.journal
│       ├── payroll.journal
│       └── revenue.journal
│
├── include/                         # [AGGREGATION] include chain
│   ├── company.journal             # TOP-LEVEL: user includes this one file
│   ├── accounts.journal            # account declarations (from chart)
│   ├── 2025.journal                # per-year aggregator
│   └── 2026.journal                # per-year aggregator
│
├── invoices/                        # per-invoice journals + PDFs
│   ├── 2026-001.journal
│   └── 2026-001.pdf
│
├── timesheets/                      # time tracking (from consult)
│   ├── unbilled.yaml
│   └── billed/
│
├── templates/                       # Typst templates for PDFs
│   └── invoice.typ
│
├── output/                          # rendered PDFs, reports
├── build/                           # intermediate template data
├── docs/                            # documentation (committed)
├── README.md
├── DESIGN.md
├── LICENSE
└── .gitignore
```

## Include Chain

User's main hledger journal (`~/.hledger.journal`) includes ONE line:

```hledger
include ~/making/pair/include/company.journal
```

### `include/company.journal` — top-level aggregator

```hledger
; pair — managed by 'pair' tool
; Do not edit manually. Run 'pair generate' to rebuild.

include accounts.journal
include 2025.journal
include 2026.journal
```

### `include/2026.journal` — per-year aggregator

```hledger
; Year 2026 — managed by 'pair' tool

; User-editable journals
include ../journal/2026/opening.journal
include ../journal/2026/adjustments.journal

; Generated journals (do not edit)
include ../generated/2026/amortization.journal
include ../generated/2026/loan-payments.journal
include ../generated/2026/payroll.journal
include ../generated/2026/revenue.journal

; Invoices
include ../invoices/2026-*.journal
```

### `include/accounts.journal` — account declarations

Generated from the account chart config. Gives hledger type information for correct `bs`/`is` reports:

```hledger
; Generated from account chart — do not edit manually

account Assets:Current:Chequing                    ; type:A
account Assets:Fixed:Equipment                     ; type:A
account Assets:Accumulated Amortization:Equipment  ; type:A, contra
account Liabilities:Current:HST Payable            ; type:L
account Equity:Owner Investment                    ; type:E
account Income:Operating:Consulting                ; type:R
account Expenses:Operating:Office Supplies         ; type:X
account Expenses:Non-Operating:Amortization        ; type:X
; ... (full chart)
```

## File Categories

### Standalone YAML (user creates/edits)
- One file per entity
- Stored in module directories: `assets/`, `liabilities/`, `contacts/`, `contracts/`, `projects/`
- Tool reads these to generate journals
- Naming: `kebab-case-slug.yaml`

### Generated journals (tool writes)
- In `generated/<year>/<module>.journal`
- Regenerated atomically (write tmp → rename)
- Every file begins with a header:

```hledger
; ══════════════════════════════════════════════════════════
; GENERATED — do not edit manually
; Source: assets/*.yaml
; Regenerate: pair generate --module amortization
; Last generated: 2026-07-15T21:53:00
; ══════════════════════════════════════════════════════════
```

### User-editable journals
- In `journal/<year>/<purpose>.journal`
- For opening balances, adjustments, year-end entries
- User writes these directly in hledger format
- Tool never overwrites them

### Aggregation files
- In `include/`
- Tool manages the `include` directives
- One entry point (`company.journal`), per-year files, account declarations

## Year Boundaries

- `pair year new 2027` scaffolds `journal/2027/`, `generated/2027/`, adds `include/2027.journal`
- Updates `include/company.journal` to add the new year
- `journal/<year>/closing.journal` holds year-end entries (retained earnings transfer)
- `journal/<year+1>/opening.journal` carries forward opening balances

## Gitignore Strategy

**Committed:**
- CLI script, README, LICENSE, docs
- `config.example.yaml`
- `include/` (structure)
- `journal/` (user's books — these ARE the accounting record)
- `generated/` (reproducible but tracked for audit trail)
- `assets/`, `liabilities/`, `contracts/`, `projects/` (entity data)
- `templates/`

**Gitignored:**
- `config.yaml` (private settings)
- `contacts/` (PII)
- `output/`, `build/` (ephemeral)
- `timesheets/` (work-in-progress)
- `invoices/*.pdf` (large binaries)
- `__pycache__/`

### `.gitignore`

```gitignore
# Private
config.yaml
contacts/

# Ephemeral
output/
build/
timesheets/

# Binaries
invoices/*.pdf

# Python
__pycache__/
*.pyc
```

## Design Principles

1. **Separation of concerns** — YAML = metadata, `.journal` = financial entries, `include/` = wiring
2. **User-editable vs generated is directory-level** — `journal/` is yours, `generated/` is the tool's
3. **Single include point** — user's main journal needs one `include` line
4. **Year as organizing boundary** — adding a year is additive (new dirs + new include)
5. **Reproducibility** — `pair generate` rebuilds all of `generated/` from YAML
6. **Auditability** — generated journals tracked in git for history
7. **Privacy** — PII (contacts) gitignored; financial records tracked
