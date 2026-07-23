# Pairs:RemoteAcc — Accounts slice (design spec)

First vertical slice of RemoteAcc: QuickBooks sandbox **Chart of Accounts →
Pairs Accounts tab**, read-only, under a new RemoteAcc entity `QB-Demo-ONE`.
Proves the whole spine on the smallest, safest domain. Background and the full
gap analysis: `docs/remoteacc-quickbooks-research.md`.

## Core decision: sync QB into a local hledger journal

RemoteAcc does **not** render QB through a bespoke data layer. It **syncs QB into a
machine-owned hledger journal**, and the existing Pairs engine (Records, Accounts,
Reports, charts, search — all hledger-backed) runs against it **unchanged**. QuickBooks
remains system of record; the journal is a **derived, regenerable projection** that
doubles as a point-in-time backup.

Consequence: from Pairs' *read* side a RemoteAcc entity is just an hledger entity whose
journal is machine-maintained. The accounting-backend "interface" mostly dissolves for
reads (both LocalHledger and RemoteAcc read hledger). The real seam is two things: the
**sync job** and the **capability descriptor** (what the UI shows/hides).

### Two-file split (never clobber manual data)

Sync **regenerates**, it does not edit-in-place. The entity's books are split so a sync
can never touch the user's own data:

- `entities/qb-demo-one/synced.journal` — machine-owned. **Wholesale-regenerated** from
  QB each sync. Never hand-edited. Deterministic and always correct because QB is source.
- `entities/qb-demo-one/overlay.journal` — the user's manual layer (reclassifications,
  annotations, groupings — the option-C local overlay). Hand-authored / Pairs-authored.
- `entities/qb-demo-one/company.journal` — master aggregator, `include`s both.

Regenerating `synced.journal` never touches `overlay.journal`. This preserves both
invariants: **read-only to QB**, and **a local overlay for interaction**.

### Sync = full regenerate (v1)

Each sync rewrites `synced.journal` from QB wholesale. No incremental/CDC state in v1 —
deterministic and idempotent beats efficient for the first slice. CDC/webhook-driven
incremental sync is a later optimization, not a v1 requirement.

### Backup value

After each sync, snapshot `synced.journal` (git commit, or timestamped copy). That yields
**version-controlled QB history with diffs** — point-in-time state QuickBooks does not
expose easily. This is a feature, not just a safety copy.

Snapshots live **in the entity's own directory** (which is private user data, outside or
gitignored from the Pairs repo) — never committed to the Pairs codebase. If git-based, the
entity dir is its own repo. This keeps the backup private, consistent with the standing
rule that entity journals/config are the user's data.

### Boundary the journal cannot hold

The journal captures financial *substance* (accounts, postings, balances) — which powers
Records/Reports/charts for free. QB richness that does not fit double-entry (invoice status
lifecycle, AR linkage, Items catalog, custom fields) is **out of scope for the journal**
and stays as separate cached metadata when the later "Build" rows need it.

## Entity model

`QB-Demo-ONE` in `global.yaml` carries a backend marker instead of a hand-authored journal:

```yaml
- name: QB-Demo-ONE
  slug: qb-demo-one
  kind: remoteacc
  backend: quickbooks
  currency: CAD
  realm_id: "9341457577936251"        # sandbox company (Sandbox Company CA 8564)
  journal_file: <path>/qb-demo-one/company.journal   # synced + overlay master
```

`kind: remoteacc` is what tells Pairs to (a) read the capability descriptor and (b) offer a
"Sync" action, rather than treat the journal as user-authored.

## Data path (boundary decision — settled)

```
Pairs sync job (Python)
   → MCP client  → existing TS MCP server (~/making/quickbooks-with-ai)
   → qbo_query(entity: "Account")
   → raw QB Account rows
   → map to hledger  → write synced.journal
```

Pairs speaks to the **already-authed, already-hardened** MCP server as a client. Pairs never
touches QB tokens — the TS repo owns the OAuth lifecycle (rotation, 0600 perms). Verified
live: `whoami` connects to the sandbox today.

> Note: the MCP's `qbo_query` is single-page (no pagination yet). Fine for the Chart of
> Accounts (well under the page cap); pagination is a later connector task.

## The map (`account.*`)

QB `Account` → hledger. Constant vocabulary Pairs codes against (never QB field names):

| Constant name | From QB field | Use |
|---|---|---|
| `account.name` | `FullyQualifiedName` | hledger account path (respect sub-account nesting) |
| `account.type` | `AccountType` | Asset/Liability/Equity/Income/Expense — drives Pairs type filters |
| `account.classification` | `Classification` | coarse grouping |
| `account.balance` | `CurrentBalance` | balance snapshot |
| `account.currency` | `CurrencyRef` | commodity |
| `account.active` | `Active` | hide inactive |
| `account.qb_id` | `Id` | stable back-reference (tag) |

**Rendering with balances:** `account` directives give the tree; a single dated
**balance-snapshot transaction** books each account to its `CurrentBalance` against an
opening/equity account, so `hledger bal` and the Accounts tab show real numbers. The
snapshot is point-in-time, which is correct for a lens/backup.

## Capability descriptor (first cut)

`QB-Demo-ONE` advertises what the UI may show. First entries:

```
accounts:      { read: true,  write: false }
transactions:  { read: false }        # next slice
payroll:       { source: browser, live_charts: false }   # no QB API
custom_fields: { source: graphql, enabled: false }       # deferred
writes:        none                    # overlay-only; no write-back to QB
```

Pairs' nav/interface is a function of this: reduce what QB can't do, don't offer write
affordances the backend forbids.

## Scope of THIS slice

In:
- Create the `QB-Demo-ONE` RemoteAcc entity + capability descriptor.
- Sync job: pull `Account` via MCP client, regenerate `synced.journal`
  (account directives + balance-snapshot transaction), leave `overlay.journal` alone.
- Accounts tab renders it through the existing hledger path.
- A "Sync" action (CLI and/or web) that regenerates and (optionally) snapshots.

Out (deferred, explicitly):
- Transactions, Records population from QB, AR/AP, Items, Budgets, custom fields.
- Write-back to QB; CDC/incremental sync; pagination.
- A Pairs-side MCP server for AI; multi-key read/write permissioning (lives in the QB MCP).

## Success criteria

1. `QB-Demo-ONE` selectable as an entity; capability descriptor loaded.
2. Running Sync produces a valid `synced.journal` that `hledger` parses.
3. Accounts tab shows the sandbox Chart of Accounts with types and balances, via the
   unchanged hledger path.
4. Editing `overlay.journal` survives a re-sync (not clobbered).
5. QB never mutated; no QB tokens handled by Pairs.
