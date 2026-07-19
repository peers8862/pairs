# pair — Design Reference

## BitLedger Account Pair Table

Source: `~/babb-repos/bitpads-standard/protocol docs/markdown/BitLedger_Protocol_v3.md` (Section 6.1)

A 4-bit field (bits 33-36) encoding both sides of a double-entry transaction. 14 valid accounting pairs plus 2 control codes. Every possible movement of value between account categories is covered.

| Code | Account Pair | Direction In (Primary) | Direction Out (Primary) |
|------|---|---|---|
| 0000 | Op Expense / Asset | Expense receives goods or service | Expense reversal, return to supplier |
| 0001 | Op Expense / Liability | Expense incurred on credit | Liability reduces, expense reversed |
| 0010 | Non-Op Expense / Asset | Non-core expense from asset | Non-core expense reversal |
| 0011 | Non-Op Expense / Liability | Non-core expense on credit | Non-core liability reduces |
| 0100 | Op Income / Asset | Revenue received as asset | Revenue reversed, asset returned |
| 0101 | Op Income / Liability | Revenue earned, not yet received | Earned revenue reversed |
| 0110 | Non-Op Income / Asset | One-time income received | One-time income reversed |
| 0111 | Non-Op Income / Liability | One-time income earned on credit | Credit income reversed |
| 1000 | Asset / Liability | Asset acquired on credit | Liability repaid from asset |
| 1001 | Asset / Equity | Owner contributes asset | Asset distributed to owner |
| 1010 | Liability / Equity | Equity converts to liability | Liability converts to equity |
| 1011 | Asset / Asset | Asset received — internal transfer | Asset disbursed — internal transfer |
| 1100 | Liability / Liability | Liability assumed from third party | Liability transferred to third party |
| 1101 | Equity / Equity | Equity reallocated in | Equity reallocated out |
| 1110 | Correction / Netting | Correction — inference suspended | Netting — inference suspended |
| 1111 | Compound Continuation | See compound transactions | See compound transactions |

## Relevance to pair

This matrix defines the complete set of accounting relationships. Every command in pair that generates a journal entry maps to one of these pairs:

| pair module | Primary pairs used |
|---|---|
| **asset** (acquisition) | 1000 (Asset/Liability — bought on credit), 0000 (Expense/Asset — if expensed), 1011 (Asset/Asset — cash purchase) |
| **asset** (amortization) | 0010 (Non-Op Expense/Asset — amortization expense reducing asset value) |
| **liability** (payment) | 1000 (Asset/Liability — repayment from bank) |
| **expense** | 0000 (Op Expense/Asset), 0001 (Op Expense/Liability) |
| **revenue** | 0100 (Op Income/Asset), 0101 (Op Income/Liability — accrued revenue) |
| **payroll** | 0000 (Op Expense/Asset — paying wages), 0001 (Op Expense/Liability — accruing wages) |
| **equity** | 1001 (Asset/Equity — owner investment/draw), 1010 (Liability/Equity — debt conversion) |
