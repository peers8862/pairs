# Design: Advanced Entry Creation (web overlay + CLI)

**Date:** 2026-07-21
**Status:** Approved, pending implementation plan
**Reference:** hledger 1.52 manual (`hledger help`; https://hledger.org/1.52/hledger.html)

## Problem

Pairs' entry creation is deliberately constrained to "link mode": the `/api/entry`
endpoint (`modules/web.py:350`) and the CLI's `cmd_pair` (`modules/pairs.py:525`) both
produce **exactly two postings, one amount, one commodity (entity currency)**, tagged
with one of the 14 pair codes.

That constraint is a good on-ramp and should stay as the default. But it cannot express
most of what hledger's journal format supports, and what real bookkeeping needs:

| hledger capability | Reachable in Pairs today |
|---|---|
| N postings (splits) | no — always 2 |
| Multiple commodities in one entry | no — entity currency only |
| Costs (`@` unit / `@@` total) | no |
| Balance assertions (`=`, `==`, `=*`, `==*`) | no |
| Per-posting dates (`date:` tag) | no |
| Status marks (unmarked / `!` / `*`) | no |
| Transaction code `(...)` | no |
| `payee | note` split description | no |
| Arbitrary tags | no — only `pair:`/`mode:`/`expr:` |
| Amountless posting (hledger infers it) | no |
| Virtual postings, lot syntax | no |

## Scope

**In scope:** an Advanced entry surface — a web overlay on the Dash entry box, and a
parallel CLI command — that can express the full journal-entry grammar above, validated
by hledger before writing.

**Out of scope for this spec:** advanced search (its own spec, next cycle); editing or
deleting existing transactions; CSV import; periodic (`~`) and auto-posting (`=`) rule
authoring; directive authoring (`account`, `commodity`, `P`).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Engine | Delegate to the hledger binary | True parity for free, zero semantic drift. Pairs already shells out to hledger in 8 modules. Reimplementing the grammar makes "lack nothing" a moving target across hledger versions. |
| Overlay shape | Structured form + live raw preview | Guided but full-power. The preview shows exactly what hledger parsed, so there is no daylight between displayed and written. Also protects against the two-space delimiter trap — see "Validity is not correctness" below. |
| Pair codes | Auto-infer, user-overridable; `compound` for N-posting | Keeps advanced entries first-class in the pairs model where the model genuinely fits, without forcing a bad label onto a 4-posting split. |
| Write target | `generated/<year>/entries.journal` | Separate from pair-code `links.journal`; both auto-included via `ensure_generated_include`. |
| CLI | Parallel command sharing the same Python core | Satisfies "both CLI and web" without duplicating serializer / validator / inference. |

## Architecture

The overlay never interprets hledger semantics itself. It round-trips through the binary.

```
Form state (JS) ──serialize──> POST /api/entry/preview {journal_text}
                                     │
                          hledger -f- print -x      (parse + make explicit)
                          hledger -f- check         (balanced / valid?)
                                     │
   preview pane <── {ok, rendered, balance, errors, inferred_pair} ──┘

[Write] ──> POST /api/entry/advanced {journal_text, pair}
              └─ re-validate server-side, append to
                 generated/<year>/entries.journal + ensure_generated_include
```

Form edits are debounced (~250ms) and re-validated on each settle. Validation runs
against the entry text piped to hledger on stdin (`-f-`), *not* against the live
journal, so a preview can never mutate data.

Balance assertions are the one case needing the real journal for meaningful evaluation.
For preview purposes, assertions are checked syntactically only, and the write path
performs the authoritative check by validating the appended result. This is called out
in Error handling below.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `lib/entry.py :: serialize_entry(fields) -> str` | Turn structured fields into journal text | none (pure) |
| `lib/entry.py :: infer_pair(types) -> code \| 'compound'` | Map posting account types to one of the 14 pair codes | pairs table |
| `lib/entry.py :: validate_entry(text) -> Result` | Run hledger, return ok/rendered/errors | hledger subprocess |
| `lib/entry.py :: record_entry(text, date) -> year` | Append + wire include (non-printing) | `lib.journal` |
| `modules/web.py` endpoints | HTTP surface for preview/write | `lib.entry` |
| `modules/pairs.py` (or new) advanced CLI cmd | Interactive multi-posting prompt | `lib.entry` |
| `web/index.html` overlay | Form UI, live preview, autocomplete | endpoints |

`serialize_entry` and `infer_pair` are pure and testable without hledger or journals.

## The overlay (web)

Trigger: an **Advanced** button beside the Dash quick-entry box. Opens a
generously-sized modal (wider than the existing commodity/trade modals), following the
established modal pattern in `web/index.html`.

**Header fields:** date (defaults today) · status (unmarked / `!` pending / `*` cleared)
· optional code `(...)` · description, with `|` splitting payee and note · free-form
tags (`k:v, k:v`).

**Postings list:** dynamic rows, each with account (autocomplete) · amount · optional
cost (`@` unit or `@@` total, toggled) · optional balance assertion (`=` or `==`) ·
optional per-row comment. Rows can be added and removed. One posting may be left
amountless — hledger infers it, and the UI must not treat that as an error.

**Live pane:** the journal text as hledger re-rendered it (`print -x`), a running
balance indicator, and ✓/✗ with hledger's actual error text on failure.

**Footer:** inferred pair code (dropdown, overridable, clearable) · Cancel · Write.
Write is disabled while validation is failing.

**Account autocomplete** is sourced from hledger's known accounts, matching how the
existing entry box already assists.

## Pair inference

`infer_pair(posting_account_types)`:

1. Exactly two postings → map the two account types (A/L/E/R/X, with C/V/G treated as
   their parent types per the manual's subtype rules) onto the matching entry in the
   14-pair table; return its code.
2. More than two postings, or a type combination with no table entry → return
   `compound`.

The user may override or clear the result. The chosen value is written as a `pair:` tag
(plus `mode:advanced`) so existing pair-keyed views keep working.

Account types come from hledger (`hledger accounts --types`), which already applies the
manual's declaration-then-inference precedence rules — so Pairs does not re-derive them.

## Error handling

| Case | Behavior |
|---|---|
| hledger reports a parse error | Preview shows hledger's stderr verbatim; Write disabled |
| Transaction unbalanced | Balance indicator shows the residual; Write disabled |
| Exactly one amountless posting | Valid — hledger infers it; not an error |
| Two or more amountless postings | hledger errors; surfaced as-is |
| Balance assertion fails on write | Write rejected, hledger's assertion message returned; nothing appended |
| hledger binary missing | Advanced button disabled with an explanatory tooltip; basic entry unaffected |
| Client sends malformed text directly | Server re-validates; never trusts the client |
| Mistyped delimiter yields a valid-but-wrong account name | hledger reports ok; the preview pane is the mitigation — see "Validity is not correctness" |

Writes are append-only and re-validated server-side immediately before appending.

### Validity is not correctness

hledger account names may contain spaces and punctuation, and are terminated only by
**two or more** spaces. A consequence, confirmed by testing against hledger 1.52.1:

```
2026-07-21 test
    assets:a @@@ bad        <- parses fine: an account named "assets:a @@@ bad",
                               with its amount inferred. NOT an error.
```

So a passing hledger check does **not** mean the entry expresses what the user intended;
a mistyped delimiter silently produces a valid entry with a garbled account name.

Two mitigations, both already in the design:

1. The structured form emits the two-space delimiter itself — the user never types it,
   so this class of error is largely unreachable from the form.
2. The live preview shows the re-rendered parse, where a garbled account name is
   visible. The preview is therefore a correctness aid, not just a formatting nicety,
   and must render the parsed account names prominently rather than only the raw input.

Verified behaviours (hledger 1.52.1): unbalanced entries error; two amountless postings
error; costs (`@`/`@@`) and balance assertions parse and round-trip; a single amountless
posting is inferred and is not an error.

## Testing

- **Unit (pure, no hledger):** `serialize_entry` for every field combination — status
  marks, code, `payee | note`, tags, costs `@`/`@@`, assertions `=`/`==`, per-posting
  comments, amountless posting, multi-commodity. `infer_pair` for each 2-posting type
  combination, plus `compound` cases.
- **Integration (real hledger):** preview endpoint against valid, unbalanced,
  syntax-error, multi-commodity, cost-bearing, and assertion-bearing entries; assert the
  ok/error classification matches hledger's own verdict.
- **Round-trip:** write an advanced entry to a temp journal, then `hledger print` it and
  confirm it parses and appears with the expected postings and tags.
- **Regression:** existing `/api/entry` link-mode path unchanged; its tests still pass.
- **Browser render:** the overlay must be verified in a real browser before being called
  done. If that verification cannot be performed, say so explicitly rather than implying
  it was checked.

## Deferred to later specs

Advanced search (hledger query parity) — the next cycle, and the reason this spec
establishes the hledger-delegation pattern. Also: transaction editing/deletion,
periodic and auto-posting rule authoring, directive authoring, and lot-syntax UI.
