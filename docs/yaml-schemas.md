# pair — YAML Schemas

## Cross-reference convention

All cross-references use the **slug** of the target entity (the filename without `.yaml`). Slug = filename stem. No separate IDs.

```
vendor: acme-office-supplies    # → contacts/acme-office-supplies.yaml
```

---

## 1. Contact (`contacts/<slug>.yaml`)

Contacts are referenced by all other entity types. Define them first.

```yaml
# contacts/acme-office-supplies.yaml

# --- Required ---
name: Acme Office Supplies
slug: acme-office-supplies
role: vendor                      # client | vendor | employee | lender | entity

# --- Optional ---
company: Acme Corp International
email: billing@acme-supplies.ca
phone: 613-555-0199
address: |
  42 Bank Street
  Ottawa, ON K1P 5N4
payment_terms: Net 30 days
notes: |
  Primary supplier for office equipment.
  Contact Sarah for bulk orders.

# --- Billing identity (only for role: entity) ---
billing:
  business_number: 123-456-789-RT0001
  currency: CAD
  tax: 13
  invoice_prefix: "CLR-"
  next_invoice: 2026-005
  template: null
  accounts:
    receivable: Assets:Current:Accounts Receivable
    income: Income:Operating:Consulting
    tax_liability: Liabilities:Current:HST Payable
    bank: Assets:Current:Chequing
```

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | ✓ | string | Display name |
| `slug` | ✓ | string | Matches filename |
| `role` | ✓ | enum | `client`, `vendor`, `employee`, `lender`, `entity` |
| `company` | | string | Organization they belong to |
| `email` | | string | |
| `phone` | | string | |
| `address` | | multiline | |
| `payment_terms` | | string | e.g. "Net 30 days" |
| `notes` | | multiline | |
| `billing` | | map | Only for role=entity (your own companies) |

---

## 2. Asset (`assets/<slug>.yaml`)

```yaml
# assets/macbook-pro-2026.yaml

# --- Required ---
name: MacBook Pro 16" M4
slug: macbook-pro-2026
category: equipment               # equipment | vehicle | furniture | software | other
purchase_date: 2026-03-15
cost: 4299.00
useful_life_months: 60
amortization_method: straight-line  # straight-line | declining-balance

# --- Optional ---
salvage_value: 500.00             # defaults to 0
declining_balance_rate: null      # required if method is declining-balance (e.g. 0.40)
vendor: acme-office-supplies      # → contacts/acme-office-supplies.yaml
payment_method: cash              # cash | financed
linked_liability: null            # slug of liability if financed
currency: CAD
accounts:
  asset: Assets:Fixed:Equipment
  amortization_expense: Expenses:Non-Operating:Amortization
  accumulated: Assets:Accumulated Amortization:Equipment
notes: |
  Serial: C02ZX1234567
  AppleCare+ until 2029-03-15

# --- Disposal (added when asset is disposed) ---
disposal:
  date: null
  proceeds: null
  method: null                    # sold | scrapped | donated | traded-in
```

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | ✓ | string | Display name |
| `slug` | ✓ | string | Matches filename |
| `category` | ✓ | enum | `equipment`, `vehicle`, `furniture`, `software`, `other` |
| `purchase_date` | ✓ | date | YYYY-MM-DD |
| `cost` | ✓ | number | Original cost |
| `useful_life_months` | ✓ | integer | Amortization period |
| `amortization_method` | ✓ | enum | `straight-line`, `declining-balance` |
| `salvage_value` | | number | Default 0 |
| `declining_balance_rate` | | number | Required for declining-balance |
| `vendor` | | slug | Reference to contact |
| `payment_method` | | enum | `cash`, `financed` |
| `linked_liability` | | slug | Reference to liability |
| `currency` | | string | Default from config |
| `accounts` | | map | Override defaults |
| `notes` | | multiline | |
| `disposal` | | map | Added on disposal |

---

## 3. Liability (`liabilities/<slug>.yaml`)

```yaml
# liabilities/vehicle-loan-2026.yaml

# --- Required ---
name: Vehicle Loan - Honda CR-V
slug: vehicle-loan-2026
type: loan                        # loan | lease | credit-line | payable
principal: 35000.00
interest_rate: 5.49               # annual percentage
term_months: 60
start_date: 2026-01-15

# --- Optional ---
payment_schedule: monthly         # monthly | biweekly | quarterly | annual
payment_amount: 668.54            # fixed payment (tool calculates if omitted)
lender: td-bank                   # → contacts/td-bank.yaml
currency: CAD
accounts:
  liability: Liabilities:Long-Term:Vehicle Loan
  interest_expense: Expenses:Non-Operating:Interest Expense
  payment_source: Assets:Current:Chequing
notes: |
  Auto-debits on the 15th of each month.
  Early repayment penalty: 3 months interest.
```

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | ✓ | string | Display name |
| `slug` | ✓ | string | Matches filename |
| `type` | ✓ | enum | `loan`, `lease`, `credit-line`, `payable` |
| `principal` | ✓ | number | Original amount |
| `interest_rate` | ✓ | number | Annual % |
| `term_months` | ✓ | integer | Total term |
| `start_date` | ✓ | date | YYYY-MM-DD |
| `payment_schedule` | | enum | Default `monthly` |
| `payment_amount` | | number | Tool calculates if omitted |
| `lender` | | slug | Reference to contact |
| `currency` | | string | Default from config |
| `accounts` | | map | Override defaults |
| `notes` | | multiline | |

---

## 4. Contract (`contracts/<slug>.yaml`)

Contracts are metadata-only — they don't directly generate journal entries but link to entities that do.

```yaml
# contracts/acme-maintenance-2026.yaml

# --- Required ---
name: Annual Maintenance Agreement
slug: acme-maintenance-2026
type: service                     # service | lease | employment | subscription
parties:
  - contact: acme-office-supplies
    role: provider
  - contact: clairlea
    role: client
start_date: 2026-01-01
status: active                    # active | expired | terminated | pending

# --- Optional ---
end_date: 2026-12-31
value: 2400.00
payment_terms: Net 30 days
payment_schedule: monthly         # monthly | quarterly | annual | one-time
renewal:
  type: auto                      # auto | manual | none
  notice_days: 30
currency: CAD
linked_assets:
  - macbook-pro-2026
linked_liabilities: []
notes: |
  Covers all office equipment maintenance.
  Includes 2 on-site visits per year.
```

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | ✓ | string | Display name |
| `slug` | ✓ | string | Matches filename |
| `type` | ✓ | enum | `service`, `lease`, `employment`, `subscription` |
| `parties` | ✓ | list | At least one party |
| `parties[].contact` | ✓ | slug | Reference to contact |
| `parties[].role` | ✓ | string | Freeform role |
| `start_date` | ✓ | date | YYYY-MM-DD |
| `status` | ✓ | enum | `active`, `expired`, `terminated`, `pending` |
| `end_date` | | date | Null for open-ended |
| `value` | | number | Total value |
| `payment_terms` | | string | |
| `payment_schedule` | | enum | |
| `renewal` | | map | Renewal terms |
| `linked_assets` | | list of slugs | |
| `linked_liabilities` | | list of slugs | |
| `notes` | | multiline | |

---

## Cross-reference diagram

```
┌─────────────┐       vendor        ┌─────────────┐
│   Asset     │ ───────────────────→ │   Contact   │
└─────────────┘                      └─────────────┘
                                           ↑
┌─────────────┐       lender               │
│  Liability  │ ───────────────────────────┘
└─────────────┘                            ↑
                                           │
┌─────────────┐   parties[].contact        │
│  Contract   │ ───────────────────────────┘
│             │   linked_assets      ┌─────────────┐
│             │ ───────────────────→ │   Asset     │
│             │   linked_liabilities ┌─────────────┐
│             │ ───────────────────→ │  Liability  │
└─────────────┘
```

## Design decisions

1. **Slug = filename** — no separate ID field; slug is identifier and filename stem.
2. **Accounts are optional overrides** — tool has defaults based on category/type.
3. **Disposal is inline** — lives in the asset file. `disposal.date` set = disposed.
4. **Contracts are metadata-only** — they link to entities that generate journals, useful for tracking and auditing.
5. **Entities are contacts** — billing identities (your own companies) are contacts with `role: entity` and a `billing:` section.
