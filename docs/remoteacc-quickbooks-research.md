# Pairs:RemoteAcc — QuickBooks research & gap analysis

Reference notes for the **RemoteAcc** alt-mode, where an external accounting service
is the system of record and Pairs is a read-first lens over it. QuickBooks Online (QBO)
is the one and only RemoteAcc backend for the foreseeable future.

Companion to the `~/making/quickbooks-with-ai` repo (the QB connector + MCP server).
This doc distils the QB API surface **in light of Pairs** so we don't re-read Intuit's
docs for every decision. It is tactical, not exhaustive — the source docs still exist for
depth. Verified against current Intuit docs, mid-2026 (sources at the bottom).

## Design frame (decided)

- **Alt-mode, not a fork.** RemoteAcc is a second *accounting-backend* behind one
  interface, so base-Pairs improvements to shared components (Records, Accounts,
  Contacts, charts) are inherited automatically. Two backends, one codebase:
  `LocalHledger` (today's Pairs) and `RemoteAcc:QuickBooks`.
- **Read-only lens now, write-back later (option C).** Manual adjustments live as a
  **local overlay** (reclassifications, groupings, annotations) that never mutate QB.
  The map is designed so a confirmation-gated write path *can* be added later without
  committing to it now. The QB MCP's read-only posture is a deliberate starting point;
  per-user / per-device read vs read-write permissioning is planned there (not in Pairs).
- **Capability descriptor drives the UI.** The backend advertises what it supports
  (entities, read vs write, live-API vs browser vs absent). Pairs' nav/interface is a
  *function* of that descriptor — payroll and custom fields (below) are descriptor
  entries, not special-cased code.
- **Neutral map syntax.** Pairs never knows QB field names (`TotalAmt`, `CustomerRef`).
  It speaks a constant vocabulary (`invoice.total`, `invoice.counterparty`); the QB side
  owns resolution. A small typed **command contract** (`get(entity, filter)`,
  `capabilities()`, later `propose_write(change)`) is Pairs' half — and the natural place
  future write-permissioning attaches. This does **not** require a second MCP server;
  Pairs is a client of the QB data path, and a Pairs-MCP only earns its place if the
  consumer is an AI service driving Pairs itself.

## QuickBooks API surface

All entities below are read/write via the REST **Accounting API** (OAuth 2.0, SQL-ish
`query` endpoint) unless noted.

**Transaction entities:** Invoice, Payment, SalesReceipt, Estimate, CreditMemo,
RefundReceipt, Bill, BillPayment, VendorCredit, Purchase (expense), PurchaseOrder,
JournalEntry, Deposit, Transfer.

**Master data:** Customer, Vendor, Employee, Item (products/services), Account (chart of
accounts), Class, Department (Location), TaxCode, TaxRate, PaymentMethod, Term.

**Other:** TimeActivity (timesheets), Budget, Attachable (attachments), Preferences,
CompanyInfo.

**Reports API** — separate endpoint (`/reports/{name}`), read-only, pre-computed by QB:
ProfitAndLoss, BalanceSheet, CashFlow, AgedReceivables, AgedPayables, TrialBalance,
GeneralLedger, and more. Note: excludes zero/inactive rows by default (`showrows=all`).
Date params vary per report — always check the report's own reference.

**Infrastructure (the cache-freshness machinery):**
- **Batch** — up to 30 operations per request.
- **CDC** (Change Data Capture) — poll entities changed since a timestamp; 30-day
  retention. The incremental-refresh path for a local cache.
- **Webhooks** — push on Create/Update/Delete/Merge/Void across most entities;
  CloudEvents + HMAC-SHA256 signature.

**Gotchas that carry into the map layer:**
- **`SyncToken`** optimistic locking — only matters once we write; every update must echo
  the current token or QB rejects it. #1 source of write failures.
- **Refresh-token rotation** — access tokens die ~hourly; each refresh may return a *new*
  refresh token that must be persisted (already handled in the QB repo).
- **Dual OAuth scopes** — Accounting (`com.intuit.quickbooks.accounting`) and Payments
  (`com.intuit.quickbooks.payment`) are separate; custom fields add a third family
  (`app-foundations.custom-field-definitions`).

## The custom-fields trap (most important finding)

There are **two** custom-field systems and they barely overlap:

- **Classic REST** exposes only the **first 3 String-type** custom fields on sales
  transactions. Number/Date/List fields, and anything past the first three, are invisible
  to it.
- The **new Custom Fields API is GraphQL** (`CustomFieldDefinition` mutations, scope
  `app-foundations.custom-field-definitions[.read]`) — the *only* way to read the rest.
- **Plus:** ~4 custom fields, sales transactions only.
  **Advanced:** ~10–12 per transaction type, across sales *and* expense transactions
  *and* customers (exact caps drift per Intuit release; treat as "Advanced = many, on more
  entities").

**Implication:** an Advanced company's "elite" custom-field usage is mostly invisible to
the REST connector we've built. If custom fields matter to the client, the connector needs
a **GraphQL path alongside REST** — a real scoped piece of work, encoded in the capability
descriptor, not a field mapping.

## Plus vs Advanced (what the tier gates)

- **Plus:** Classes, Locations/Departments, Budgets, Projects, 1099s, up to 5 users, ~4
  sales custom fields.
- **Advanced (adds):** up to 25 users, custom roles (granular scoped permissions),
  workflows/approvals, batch invoicing, Revenue Recognition, Fixed Asset Manager
  (auto-depreciation), custom report builder / Performance Center, Spreadsheet Sync, and
  the expanded custom fields above. Several Advanced-only screens (custom reports,
  Performance Center) have **no clean API** → browser-only.

## Gap analysis: QuickBooks × Pairs

Verdict key — **Persist**: Pairs already covers it, lens maps cleanly · **Adapt**: exists
but shape differs · **Build**: real gap, decide per-part · **Browser**: no API, needs
Claude-in-Chrome · **Native**: Pairs-native strength QB lacks or does worse.

| QB capability | API? | Pairs today | Verdict |
|---|---|---|---|
| Chart of Accounts (`Account`) | ✅ | Accounts tab (hledger tree) | **Persist** |
| Transactions (`JournalEntry`, `Purchase`, `Deposit`, `Transfer`) | ✅ | Records / register | **Persist** |
| Customers / Vendors / Employees | ✅ | Contacts (role-based) | **Persist** — QB splits 3 types, Pairs unifies by role |
| Reports (P&L, BS, Cash Flow, Trial Balance) | ✅ Reports | Reports tab (BS/IS/CF/register) | **Persist/Adapt** — render QB's pre-computed reports instead of recomputing |
| AR aging / AP aging | ✅ Reports | — | **Build** — high value, low effort (report call) |
| Invoices (`Invoice` lifecycle, status, balance) | ✅ | `consult` invoicing (generate only) | **Adapt** — Pairs generates invoices but tracks no live AR ledger |
| Bills / AP (`Bill`, `BillPayment`, `VendorCredit`) | ✅ | — | **Build** — no accounts-payable workflow in Pairs |
| Items (products/services catalog) | ✅ | — | **Build** — needed for invoice line items |
| Estimates / SalesReceipts / CreditMemos | ✅ | — | **Build** (lower priority) |
| Payments received (`Payment`) | ✅ | posting only | **Adapt** — Pairs sees the posting, not the AR linkage |
| Classes & Locations (dimensional tags) | ✅ | Pair-codes + tags + projects | **Adapt** — different dimensional model; map, don't rebuild |
| Budgets (`Budget`) | ✅ | — | **Build** — genuine gap; pairs well with contract run-rates |
| Tax (`TaxCode`, `TaxRate`, `TaxAgency`) | ✅ | Simple HST tracking | **Adapt** — QB is multi-rate/multi-agency |
| Custom fields | ⚠️ REST=3 strings; GraphQL=rest | — | **Build (conditional)** — see trap above |
| Attachments (`Attachable`) | ✅ | — | **Build** (low priority) — receipts/docs |
| TimeActivity (timesheets) | ✅ | Contracts/rates, `consult` hours | **Adapt/Build** — adjacent to the hours model |
| Payroll (runs, pay stubs, detail) | ❌ none | Native payroll (CPP/EI/tax) | **Browser** — API dead zone; descriptor greys out live payroll charts |
| Advanced custom reports / Performance Center | ⚠️ partial | Charts tab | **Browser** for the rest |
| Investments / ACB (buy/sell, market data) | — | Native ACB engine | **Native** — QB has no cost-base engine |
| Amortization modeling (SL/DB, salvage) | — | Native | **Native** — QB Fixed Asset Manager is Advanced-only + no clean API |
| Pair-codes vocabulary | — | Native | **Native** — no QB analog |
| Contract run-rate totals | — | Native | **Native** — no QB equivalent |

## Three headlines

1. **The viewing/reporting layer maps onto QB almost for free.** Accounts, Records,
   Contacts, Reports all "persist." The lens can be rich on day one against the REST reads
   already built.
2. **The real build gaps cluster in transactional AR/AP** — Bills/AP, Items catalog, live
   Invoice/AR ledger, Budgets. QB does these; Pairs doesn't. Each is an independent
   "part," and each earns interface + nav space only when the descriptor says QB supports
   it.
3. **Two hard boundaries the descriptor must encode** — Payroll (no API → browser-only, no
   live charts) and custom fields (REST sees almost nothing → GraphQL or bust).

## Suggested build order (cheapest-and-highest-value first)

Not committed — the sequencing to react to part-by-part:

1. **AR-aging / AP-aging view** — pure report calls, immediate value.
2. **Live Invoice / AR ledger** — upgrade `consult` invoicing from generate-only to a
   tracked AR view.
3. **Items catalog** — unlocks proper invoice/bill line items.
4. **Bills / AP workflow** — the biggest genuinely-missing domain.
5. **Budgets** — composes with the contract run-rate work.
6. **Custom fields (conditional)** — only if the client uses them; triggers the GraphQL
   connector path.

## Sources

- Intuit Developer — [Create custom fields](https://developer.intuit.com/app/developer/qbo/docs/workflows/create-custom-fields)
  · [Enhanced Custom Fields for QBO Advanced](https://help.developer.intuit.com/s/article/Enhanced-Custom-Fields-for-QuickBooks-Online-Advanced)
- Intuit Developer blog — [Custom Fields API (Dec 2025)](https://blogs.intuit.com/2025/12/01/custom-fields-api-extending-quickbooks-online-with-flexible-metadata/)
- [QuickBooks API: Complete Developer's Guide 2026](https://dev.to/zuplo/quickbooks-api-complete-developers-guide-2026-3l77)
- Intuit Developer — [Reports API best practices](https://medium.com/intuitdev/quickbooks-online-reports-api-best-practices-and-troubleshooting-31edc9934b4c)
- Local: `~/making/quickbooks-with-ai/docs/integration-map.md` (master integration map),
  `api/src/mcp/server.ts` (read-only MCP tools).
