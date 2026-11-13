# Pairs plan: backlog, decisions and build log

This folder tracks how Pairs grew from a bookkeeping tool into a planning tool for
early-stage companies. It covers scenarios, runway, KPIs, fundraising, the cap table
and growth. Each of these is an opt-in feature pack (see `docs/commands.md`,
"Feature Packs").

It is a published copy of the maintainer's working plan. Personal file paths and
the titles of private source documents have been replaced with neutral text. The
source workbooks were read for concepts and logic only: no figures or company data
were carried over.

## Files

| File | What it holds |
|---|---|
| `index.csv` | The list of files below |
| `items.csv` | Backlog items: summary, dependencies, value/effort, phase, status |
| `phases.csv` | The build phases P0–P7: which items each one combined, and its PR |
| `decisions.csv` | Open and decided questions, with the proposed and the final answer |
| `observations.csv` | What each source document showed, and what it implies for Pairs |
| `sources.csv` | The source documents analysed (described, not linked) |
| `metric_buckets.csv`, `metrics.csv` | The KPI catalogue: 11 buckets, with built-in and anticipated metrics |
| `artifacts.csv` | PRs and other outputs |
| `log.csv` | Dated, one-line entries |
| `plan.xlsx` | A workbook generated from the CSVs. Never edit it by hand |

The CSVs are the source of truth. Keep `index.csv` listing every CSV, and
regenerate the workbook after edits. The maintainer uses `mach sheets build docs/plan`.

## Status (2026-11-13)

Phases P0–P7 are merged (PRs #1–#9). Two earlier items are still open:

- I35: balance sheet projection. Monthly profit & loss and cash already exist.
- I38: valuation methods. Deferred by decision D16.

Further intake ideas not yet built are I47–I56, marked `later`.
