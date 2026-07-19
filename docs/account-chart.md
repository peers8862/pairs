# pair Default Account Chart

## Complete Account Hierarchy

```
; ═══════════════════════════════════════════════════════
; ASSETS
; ═══════════════════════════════════════════════════════

account Assets:Current:Chequing
account Assets:Current:Savings
account Assets:Current:Petty Cash
account Assets:Current:Accounts Receivable
account Assets:Current:Prepaid Expenses

account Assets:Fixed:Equipment
account Assets:Fixed:Vehicles
account Assets:Fixed:Furniture
account Assets:Fixed:Leasehold Improvements
account Assets:Fixed:Intellectual Property

account Assets:Accumulated Amortization:Equipment
account Assets:Accumulated Amortization:Vehicles
account Assets:Accumulated Amortization:Furniture
account Assets:Accumulated Amortization:Leasehold Improvements
account Assets:Accumulated Amortization:Intellectual Property

; ═══════════════════════════════════════════════════════
; LIABILITIES
; ═══════════════════════════════════════════════════════

account Liabilities:Current:Accounts Payable
account Liabilities:Current:Credit Card
account Liabilities:Current:HST Payable
account Liabilities:Current:Payroll Payable
account Liabilities:Current:Income Tax Payable
account Liabilities:Current:Unearned Revenue
account Liabilities:Current:Current Portion of Long-Term Debt

account Liabilities:Long-Term:Bank Loan
account Liabilities:Long-Term:Vehicle Loan
account Liabilities:Long-Term:Shareholder Loan

; ═══════════════════════════════════════════════════════
; EQUITY
; ═══════════════════════════════════════════════════════

account Equity:Owner Investment
account Equity:Owner Draws
account Equity:Retained Earnings

; ═══════════════════════════════════════════════════════
; INCOME (OPERATING)
; ═══════════════════════════════════════════════════════

account Income:Operating:Consulting
account Income:Operating:Services
account Income:Operating:Product Sales
account Income:Operating:Recurring Revenue

; ═══════════════════════════════════════════════════════
; INCOME (NON-OPERATING)
; ═══════════════════════════════════════════════════════

account Income:Non-Operating:Interest Income
account Income:Non-Operating:Gain on Disposal
account Income:Non-Operating:Foreign Exchange Gain
account Income:Non-Operating:Other Income

; ═══════════════════════════════════════════════════════
; EXPENSES (OPERATING)
; ═══════════════════════════════════════════════════════

account Expenses:Operating:Payroll:Salaries
account Expenses:Operating:Payroll:Benefits
account Expenses:Operating:Payroll:Employer Contributions
account Expenses:Operating:Rent
account Expenses:Operating:Utilities
account Expenses:Operating:Insurance
account Expenses:Operating:Office Supplies
account Expenses:Operating:Software Subscriptions
account Expenses:Operating:Professional Fees
account Expenses:Operating:Travel
account Expenses:Operating:Meals and Entertainment
account Expenses:Operating:Marketing
account Expenses:Operating:Telecommunications
account Expenses:Operating:Bank Fees
account Expenses:Operating:Repairs and Maintenance

; ═══════════════════════════════════════════════════════
; EXPENSES (NON-OPERATING)
; ═══════════════════════════════════════════════════════

account Expenses:Non-Operating:Amortization
account Expenses:Non-Operating:Interest Expense
account Expenses:Non-Operating:Loss on Disposal
account Expenses:Non-Operating:Foreign Exchange Loss
account Expenses:Non-Operating:Income Tax Expense
```

## BitLedger Pair → Account Mapping

| Code | Pair | Debit (DR) | Credit (CR) | Example |
|------|------|------------|-------------|---------|
| 0000 | Op Expense / Asset | `Expenses:Operating:Office Supplies` | `Assets:Current:Chequing` | Paid for supplies |
| 0001 | Op Expense / Liability | `Expenses:Operating:Software Subscriptions` | `Liabilities:Current:Credit Card` | Software on credit card |
| 0010 | Non-Op Expense / Asset | `Expenses:Non-Operating:Amortization` | `Assets:Accumulated Amortization:Equipment` | Monthly amortization |
| 0011 | Non-Op Expense / Liability | `Expenses:Non-Operating:Interest Expense` | `Liabilities:Current:Accounts Payable` | Interest accrued |
| 0100 | Op Income / Asset | `Assets:Current:Chequing` | `Income:Operating:Consulting` | Client payment received |
| 0101 | Op Income / Liability | `Liabilities:Current:Unearned Revenue` | `Income:Operating:Services` | Recognize deferred revenue |
| 0110 | Non-Op Income / Asset | `Assets:Current:Chequing` | `Income:Non-Operating:Interest Income` | Bank interest received |
| 0111 | Non-Op Income / Liability | `Liabilities:Current:Accounts Payable` | `Income:Non-Operating:Gain on Disposal` | Gain recognized |
| 1000 | Asset / Liability | `Assets:Fixed:Equipment` | `Liabilities:Long-Term:Bank Loan` | Equipment on credit |
| 1001 | Asset / Equity | `Assets:Current:Chequing` | `Equity:Owner Investment` | Owner invests cash |
| 1010 | Liability / Equity | `Liabilities:Long-Term:Shareholder Loan` | `Equity:Owner Investment` | Loan → equity conversion |
| 1011 | Asset / Asset | `Assets:Current:Chequing` | `Assets:Current:Savings` | Internal transfer |
| 1100 | Liability / Liability | `Liabilities:Long-Term:Bank Loan` | `Liabilities:Current:Current Portion of Long-Term Debt` | Reclassify current portion |
| 1101 | Equity / Equity | `Equity:Retained Earnings` | `Equity:Owner Draws` | Draw from retained earnings |

## Debit/Credit Convention

BitLedger pair `X / Y` means:
- **Direction In (normal):** X is debited, Y is credited
- **Direction Out (reversal):** X is credited, Y is debited

This aligns with standard double-entry: Assets and Expenses increase on debit; Liabilities, Equity, and Income increase on credit.
