# Advanced Entry — Implementation Plan (compact)

**Spec:** `docs/superpowers/specs/2026-07-21-advanced-entry-design.md`
**Goal:** Full journal-grammar entry creation via a Dash overlay + CLI, validated by hledger.

## Constraints
- Delegate to hledger; never reimplement its grammar. Validate via `hledger -f- print -x`.
- Run Python via `.venv/bin/python`. Tests: `.venv/bin/python -m pytest`.
- Write to `generated/<year>/entries.journal` + `ensure_generated_include`.
- Pair code auto-inferred, overridable, `compound` when the 2-account model doesn't fit.
- A passing hledger check is not proof of correctness (delimiter trap) — preview shows the parse.

## Pair inference table (type pair → code)
Op vs Non-Op comes from the account path (`Expenses:Non-Operating` → non-op), not hledger type.

| types | op | non-op |
|---|---|---|
| X + A | 0000 | 0010 |
| X + L | 0001 | 0011 |
| R + A | 0100 | 0110 |
| R + L | 0101 | 0111 |
| A + L | 1000 | |
| A + E | 1001 | |
| L + E | 1010 | |
| A + A | 1011 | |
| L + L | 1100 | |
| E + E | 1101 | |

Anything else, or >2 postings → `compound`.

---

## Task 1: `lib/entry.py` core (pure + validation)
**Files:** create `lib/entry.py`, `tests/test_entry.py`

- `serialize_entry(fields) -> str` — header (date, status, code, `payee | note`, tags) + posting rows (account, amount, `@`/`@@` cost, `=`/`==` assertion, comment). Emits the two-space delimiter itself. Amountless posting allowed.
- `infer_pair(postings) -> code|'compound'` — per table above.
- `validate_entry(text) -> {ok, rendered, errors}` — `hledger -f- print -x` on stdin.
- `record_entry(text, date_str) -> year` — append to `generated/<year>/entries.journal` + `ensure_generated_include`.

TDD: tests first for `serialize_entry` (all field combos incl. cost, assertion, tags, amountless, multi-commodity) and `infer_pair` (each type pair + compound). Integration tests for `validate_entry` against real hledger: valid / unbalanced / two-amountless / cost / assertion.

Commit: `feat: add advanced entry core (serialize, infer_pair, validate)`

## Task 2: web endpoints
**Files:** modify `modules/web.py`

- `POST /api/entry/preview` `{journal_text}` → `{ok, rendered, errors, inferred_pair}`. Read-only.
- `POST /api/entry/advanced` `{journal_text, pair}` → re-validate, inject `pair:`/`mode:advanced`, `record_entry`, return status.
- `GET /api/accounts/list` (or reuse existing) for autocomplete, sourced from hledger.

Verify with TestClient: valid write round-trips through `hledger print`; unbalanced → 400; bad pair → 400. Back up + restore `generated/` around tests.

Commit: `feat: advanced entry preview/write endpoints`

## Task 3: Dash overlay
**Files:** modify `web/index.html`

- **Advanced** button beside quick-entry box.
- Wide modal: header fields (date, status ▾, code, `payee | note`, tags); dynamic posting rows (account+autocomplete, amount, cost toggle, assertion, comment, remove); add-row.
- Live pane (debounced ~250ms → `/api/entry/preview`): rendered parse, balance, ✓/✗ with hledger's error text. Write disabled while invalid.
- Footer: inferred pair ▾ (overridable/clearable), Cancel, Write.

Verify: `node --check` on extracted JS; unique IDs; functions defined. Browser render if reachable — state plainly if not.

Commit: `feat: advanced entry overlay on Dash`

## Task 4: CLI parity
**Files:** modify `modules/pairs.py` (dispatch) + use `lib/entry.py`

- `pair entry --advanced`: prompt header fields, then posting rows until blank; show inferred pair (accept/override); validate via `validate_entry`; print the parse; confirm; `record_entry`.
- Reject cleanly on hledger error (show its message), write nothing.

Verify: run against a temp journal; full suite green.

Commit: `feat: pair entry --advanced (CLI parity)`

---

## Deferred
Advanced search (own spec, next). Editing/deleting txns, periodic/auto rules, directive authoring, lot-syntax UI.
