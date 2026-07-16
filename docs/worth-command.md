# `company worth` — Net Worth Reporting

## Default Output

```
$ company worth

══════════════════════════════════════════════════════════════
  Company Net Worth — Clairlea Consulting
  As of 2026-07-15
══════════════════════════════════════════════════════════════

  ASSETS
  ──────────────────────────────────────────────────────────

  Current Assets
    Chequing                                     $45,000.00
    Accounts Receivable                          $12,000.00
                                                 ──────────
    Total Current Assets                         $57,000.00

  Fixed Assets                          Cost        Amort        NBV
    Equipment                      $80,000.00  ($20,000.00)  $60,000.00
    Vehicle                        $35,000.00  ($14,000.00)  $21,000.00
                                                             ──────────
    Total Fixed Assets                                       $81,000.00

                                                             ──────────
  TOTAL ASSETS                                              $138,000.00


  LIABILITIES
  ──────────────────────────────────────────────────────────

  Long-term
    Business Loan                                $50,000.00

  Short-term
    Credit Line                                   $8,000.00
    Accounts Payable                              $3,500.00
                                                 ──────────
  TOTAL LIABILITIES                              $61,500.00


  ══════════════════════════════════════════════════════════
  NET WORTH (Equity)                             $76,500.00
  ══════════════════════════════════════════════════════════
```

## hledger Queries Under the Hood

```python
JOURNAL = expand_path(config['journal_file'])

# 1. Current assets (exclude Fixed and Accumulated Amortization)
hledger -f {JOURNAL} bal "Assets:Current" --no-total --output-format=csv

# 2. Fixed asset cost
hledger -f {JOURNAL} bal "Assets:Fixed" --no-total --output-format=csv

# 3. Accumulated amortization (negative/contra)
hledger -f {JOURNAL} bal "Assets:Accumulated Amortization" --no-total --output-format=csv

# 4. Liabilities
hledger -f {JOURNAL} bal "Liabilities" --no-total --output-format=csv
```

CSV output is parsed deterministically — avoids text alignment/truncation issues.

## Amortization in the Report

Account structure:
```
Assets:Fixed:Equipment                              $80,000  (original cost)
Assets:Accumulated Amortization:Equipment          -$20,000  (contra-asset)
```

Pairing logic strips prefixes to match:
- `Assets:Fixed:Equipment` → key `Equipment`
- `Assets:Accumulated Amortization:Equipment` → key `Equipment`

NBV = cost + accumulated (where accumulated is stored negative) = 80000 + (-20000) = 60000

## Flags

### `--period <date>`
Net worth as of a specific date:
```bash
company worth --period 2026-06-30
```
Passes `-e 2026-07-01` to hledger (exclusive end date).

### `--monthly`
Period-over-period change:
```
$ company worth --monthly

  Net Worth — Monthly Change (2026)

  Month        Assets    Liabilities   Net Worth    Change
  ─────────────────────────────────────────────────────────
  Jan        $120,500      $70,000     $50,500
  Feb        $122,000      $68,500     $53,500    +$3,000
  Mar        $125,300      $67,000     $58,300    +$4,800
  Apr        $128,000      $65,500     $62,500    +$4,200
  May        $130,500      $64,000     $66,500    +$4,000
  Jun        $133,800      $62,500     $71,300    +$4,800
  Jul        $138,000      $61,500     $76,500    +$5,200
  ─────────────────────────────────────────────────────────
  YTD                                             +$26,000
```

### `--quarterly` / `--yearly`
Same as monthly but grouped by quarter/year.

### `--detail`
Full account tree instead of summary:
```bash
company worth --detail
```

### `--raw`
Pass-through to `hledger bs`:
```bash
company worth --raw   # → hledger bs -f <journal>
```

### `--cost` / `--value=now`
Multi-currency conversion (passed to hledger):
```bash
company worth --value=now    # convert all to default currency at today's rate
```

## Liability Classification

Uses YAML metadata from `liabilities/*.yaml`:
- `type: loan` + `term_months > 12` → Long-term
- `type: credit-line`, `type: payable` → Short-term
- Fallback heuristics if no YAML: "Loan"/"Mortgage" → long-term, "Payable"/"Card" → short-term

## Multi-Currency

When mixed currencies exist:
```
  NET WORTH                                CAD 76,500.00
                                           USD  5,200.00

  (Use --cost or --value=now for converted totals)
```

## Implementation

The command:
1. Reads config to find journal path
2. Runs 4 hledger queries (current assets, fixed assets, accumulated amort, liabilities)
3. Parses CSV output
4. Pairs fixed assets with their amortization accounts
5. Classifies liabilities using YAML metadata
6. Renders formatted report to terminal
