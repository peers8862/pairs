# pair — Journal Generation Rules

## Conventions

```
YYYY-MM-DD * Description  ; tag:value, tag:value
    Account:Name                          CURRENCY AMOUNT
    Account:Name                          CURRENCY AMOUNT
```

- Status: always `*` (cleared) — generated entries are authoritative
- Currency: 3-letter code before amount (e.g. `CAD 88.86`)
- Amounts: positive = debit, negative = credit
- Tags: `pair:XXXX` (BitLedger code), `source:path/to/file.yaml`, plus module-specific
- Rounding: 2 decimal places; last posting computed as balancing amount
- Blank line between entries; file ends with newline
- Idempotent: regeneration replaces entire file atomically

---

## 1. Asset Acquisition

**BitLedger pair:** `1011` (Asset/Asset — cash) or `1000` (Asset/Liability — financed)

### Cash purchase

```journal
2026-03-15 * Acquire asset: MacBook Pro 16" M4  ; pair:1011, source:assets/macbook-pro-2026.yaml, category:equipment
    Assets:Fixed:Equipment                         CAD 4299.00
    Assets:Current:Chequing                        CAD -4299.00
```

### Financed purchase

```journal
2026-03-15 * Acquire asset: Delivery Van  ; pair:1000, source:assets/delivery-van.yaml, category:vehicle, liability:vehicle-loan-2026
    Assets:Fixed:Vehicles                          CAD 45000.00
    Liabilities:Long-Term:Vehicle Loan             CAD -45000.00
```

---

## 2. Amortization

**BitLedger pair:** `0010` (Non-Op Expense / Asset)
**Output:** `generated/<year>/amortization.journal`

### 2a. Straight-line

Formula: `monthly = (cost - salvage_value) / useful_life_months`

```journal
2026-04-01 * Amortization: MacBook Pro 16" M4 (4/60)  ; pair:0010, source:assets/macbook-pro-2026.yaml, period:2026-04, seq:4/60
    Expenses:Non-Operating:Amortization            CAD 63.32
    Assets:Accumulated Amortization:Equipment      CAD -63.32
```

### 2b. Declining balance

Formula: `monthly = (rate / 12) * (cost - accumulated_amortization)`

Never amortizes below salvage value.

```journal
2026-04-01 * Amortization: Delivery Van (4/60)  ; pair:0010, source:assets/delivery-van.yaml, period:2026-04, seq:4/60, book_value:42187.50
    Expenses:Non-Operating:Amortization            CAD 703.13
    Assets:Accumulated Amortization:Vehicles       CAD -703.13
```

### 2c. Partial first period

If acquired mid-month, prorate: `first_month = monthly * (days_remaining / days_in_month)`

```journal
2026-03-15 * Amortization: MacBook Pro 16" M4 (1/60) partial  ; pair:0010, source:assets/macbook-pro-2026.yaml, period:2026-03, seq:1/60, partial:17/31
    Expenses:Non-Operating:Amortization            CAD 34.72
    Assets:Accumulated Amortization:Equipment      CAD -34.72
```

### 2d. Final period

Last entry adjusted so total accumulated equals exactly `cost - salvage_value`:

```journal
2031-03-01 * Amortization: MacBook Pro 16" M4 (60/60) final  ; pair:0010, source:assets/macbook-pro-2026.yaml, period:2031-03, seq:60/60, final:true
    Expenses:Non-Operating:Amortization            CAD 52.00
    Assets:Accumulated Amortization:Equipment      CAD -52.00
```

No entries generated after useful life exhausted.

---

## 3. Asset Disposal

**BitLedger pair:** `0110` (gain) or `0010` (loss)
**Output:** `generated/<year>/assets.journal`

### Logic

```
book_value = cost - accumulated_amortization
gain_or_loss = proceeds - book_value
gain_or_loss > 0 → credit Income:Non-Operating:Gain on Disposal
gain_or_loss < 0 → debit Expenses:Non-Operating:Loss on Disposal
gain_or_loss == 0 → no gain/loss line
```

### Sale at gain

```journal
2027-06-10 * Dispose asset: MacBook Pro 16" M4 (sale)  ; pair:0110, source:assets/macbook-pro-2026.yaml, disposal:sold, proceeds:1500.00
    Assets:Current:Chequing                        CAD 1500.00
    Assets:Accumulated Amortization:Equipment      CAD 2332.67
    Assets:Fixed:Equipment                         CAD -4299.00
    Income:Non-Operating:Gain on Disposal          CAD -533.67
```

### Sale at loss

```journal
2027-06-10 * Dispose asset: Delivery Van (sale)  ; pair:0010, source:assets/delivery-van.yaml, disposal:sold, proceeds:25000.00
    Assets:Current:Chequing                        CAD 25000.00
    Assets:Accumulated Amortization:Vehicles       CAD 15000.00
    Expenses:Non-Operating:Loss on Disposal        CAD 5000.00
    Assets:Fixed:Vehicles                          CAD -45000.00
```

### Scrap (zero proceeds)

```journal
2027-06-10 * Dispose asset: Old Printer (scrap)  ; pair:0010, source:assets/old-printer.yaml, disposal:scrapped, proceeds:0.00
    Assets:Accumulated Amortization:Equipment      CAD 800.00
    Expenses:Non-Operating:Loss on Disposal        CAD 200.00
    Assets:Fixed:Equipment                         CAD -1000.00
```

---

## 4. Liability Creation

**BitLedger pair:** `1000` (Asset / Liability)
**Output:** `generated/<year>/liabilities.journal`

### Loan proceeds received

```journal
2026-01-15 * New liability: Vehicle Loan  ; pair:1000, source:liabilities/vehicle-loan-2026.yaml, type:loan, term:60
    Assets:Current:Chequing                        CAD 35000.00
    Liabilities:Long-Term:Vehicle Loan             CAD -35000.00
```

### Lease (asset + liability simultaneously)

```journal
2026-02-01 * New liability: Office Lease  ; pair:1000, source:liabilities/office-lease.yaml, type:lease, term:36
    Assets:Fixed:Leasehold Improvements            CAD 86400.00
    Liabilities:Long-Term:Office Lease             CAD -86400.00
```

---

## 5. Liability Payment

**BitLedger pair:** `1000` (Asset/Liability — principal) + `0011` (Non-Op Expense/Liability — interest)
**Output:** `generated/<year>/loan-payments.journal`

### Monthly payment with principal + interest split

```journal
2026-02-15 * Payment: Vehicle Loan (2/60)  ; pair:1000, source:liabilities/vehicle-loan-2026.yaml, seq:2/60
    Liabilities:Long-Term:Vehicle Loan             CAD 508.48
    Expenses:Non-Operating:Interest Expense        CAD 160.06
    Assets:Current:Chequing                        CAD -668.54
```

Interest calculation: `monthly_interest = remaining_principal * (annual_rate / 12 / 100)`
Principal portion: `payment_amount - monthly_interest`

---

## 6. Expense

**BitLedger pair:** `0000` (paid from asset) or `0001` (on credit)
**Output:** `generated/<year>/expenses.journal`

### Paid from bank

```journal
2026-07-10 * Office Supplies - Staples  ; pair:0000, category:office
    Expenses:Operating:Office Supplies             CAD 147.50
    Assets:Current:Chequing                        CAD -147.50
```

### On credit card

```journal
2026-07-10 * Software - GitHub Teams  ; pair:0001, category:software, recurring:monthly
    Expenses:Operating:Software Subscriptions      CAD 25.00
    Liabilities:Current:Credit Card                CAD -25.00
```

Note: Expenses don't have a `source:` YAML file. The journal entry IS the record. No separate YAML per expense — that would be over-engineering.

---

## 7. Revenue / Invoice (from consult)

**BitLedger pair:** `0100` (Op Income / Asset)
**Output:** `invoices/<year>-<num>.journal`

### Invoice raised

```journal
2026-07-01 * Invoice 2026-004  ; pair:0100, invoice:2026-004, client:acme-corp, project:acme-consulting
    Assets:Current:Accounts Receivable             CAD 3042.45
    Income:Operating:Consulting                    CAD -2692.43
    Liabilities:Current:HST Payable                CAD -350.02
```

### Payment received

```journal
2026-07-15 * Payment received: Invoice 2026-004  ; pair:1011, invoice:2026-004, client:acme-corp
    Assets:Current:Chequing                        CAD 3042.45
    Assets:Current:Accounts Receivable             CAD -3042.45
```

---

## 8. Payroll

**BitLedger pair:** `0001` (accrual), `1000` (disbursement), `0000` (contractor)
**Output:** `generated/<year>/payroll.journal`

### Employee pay run (accrual)

```journal
2026-07-15 * Payroll: 2026-07-01 to 2026-07-15  ; pair:0001, source:payroll/2026-07-15.yaml, period:2026-07-01_to_2026-07-15
    Expenses:Operating:Payroll:Salaries            CAD 4500.00
    Expenses:Operating:Payroll:Employer Contributions  CAD 382.88
    Liabilities:Current:Payroll Payable            CAD -3253.12
    Liabilities:Current:Income Tax Payable         CAD -900.00
    Liabilities:Current:Payroll Payable            CAD -729.76
```

### Disbursement (net pay)

```journal
2026-07-15 * Payroll disbursement  ; pair:1000, source:payroll/2026-07-15.yaml
    Liabilities:Current:Payroll Payable            CAD 3253.12
    Assets:Current:Chequing                        CAD -3253.12
```

### Contractor payment

```journal
2026-07-15 * Contractor: Jane Smith  ; pair:0000, contact:jane-smith, period:2026-07-01_to_2026-07-15
    Expenses:Operating:Payroll:Salaries            CAD 3000.00
    Assets:Current:Chequing                        CAD -3000.00
```

---

## Summary: Module → File → Pair

| Module | Output file | Primary pairs |
|--------|-------------|---------------|
| Asset acquisition | `generated/<year>/assets.journal` | 1011, 1000 |
| Amortization | `generated/<year>/amortization.journal` | 0010 |
| Asset disposal | `generated/<year>/assets.journal` | 0110, 0010 |
| Liability creation | `generated/<year>/liabilities.journal` | 1000 |
| Liability payment | `generated/<year>/loan-payments.journal` | 1000 |
| Expense | `generated/<year>/expenses.journal` | 0000, 0001 |
| Revenue/Invoice | `invoices/<num>.journal` | 0100 |
| Payroll | `generated/<year>/payroll.journal` | 0001, 1000, 0000 |
