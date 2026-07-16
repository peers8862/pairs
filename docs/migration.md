# hledger-company — Migration from consult

## Command Migration Table

| consult command | hledger-company command | Status | Changes |
|---|---|---|---|
| `consult init` | `pair init` | Rework | Broader scope: sets up all module dirs, account chart, include chain |
| `consult entity add` | `pair contact add --role entity` | Rename + Rework | Entities become contacts with `role: entity` + `billing:` section |
| `consult entity list` | `pair contact list --role entity` | Rename | Filter by role |
| `consult entity edit <slug>` | `pair contact edit <slug>` | Rename | Broader schema |
| `consult project new` | `pair revenue project add` | Rename | Direct port |
| `consult project list` | `pair revenue project list` | Rename | Direct port |
| `consult rate <project>` | `pair revenue rate <project>` | Rename | Direct port |
| `consult log` | `pair revenue log` | Rename | Direct port |
| `consult log --batch` | `pair revenue log --batch` | Rename | Direct port |
| `consult log edit` | `pair revenue log edit` | Rename | Direct port |
| `consult status` | `pair revenue status` | Rename | Direct port |
| `consult invoice` | `pair revenue invoice` | Minor rework | Journal path may change; invoices keep own dir |
| `consult paid` | `pair revenue paid` | Minor rework | Same as invoice |
| `consult outstanding` | `pair revenue outstanding` | Rename | Direct port |
| `consult export` | `pair revenue export` | Rename | Direct port |
| `consult undo` | `pair revenue undo` | Rename | Direct port |

## Helper Function Reusability

| Helper | Reusable | Notes |
|--------|----------|-------|
| `prompt()` | ✓ As-is | Every module needs interactive prompts |
| `validate_slug()` | ✓ As-is | Universal slug validation |
| `validate_date()` | ✓ As-is | All modules have dates |
| `validate_positive_number()` | ✓ As-is | Costs, amounts, rates |
| `money()` | ✓ As-is | 2-decimal rounding everywhere |
| `expand_path()` | ✓ As-is | Journal path resolution |
| `load_config()` / `save_config()` | ✓ Schema expands | Same load/save pattern |
| `validate_tax()` | Revenue only | Keep in revenue module |
| `validate_type()` | Revenue only | Keep in revenue module |
| `get_effective_rate()` | Revenue only | Rate history lookup |
| `compute_hourly_rate()` | Revenue only | Stays in revenue |
| `ensure_include()` | Generalize | All modules need include management |

## Architectural Changes

### 1. Module split

The monolithic `consult` file becomes:

```
company                     # entry point + dispatch
lib/
  helpers.py               # prompt, validators, money, expand_path
  journal.py               # ensure_include, journal writing, header generation
  yaml_store.py            # generic load/save/list for YAML directories
modules/
  revenue.py              # all consult cmd_* functions
  asset.py                # new
  liability.py            # new
  expense.py              # new
  contact.py              # new
  contract.py             # new
  payroll.py              # new
  worth.py                # new
  equity.py               # new
```

### 2. Command dispatch

Replace flat if/elif with module-based router:

```python
MODULES = {
    'asset': modules.asset,
    'liability': modules.liability,
    'revenue': modules.revenue,
    'worth': modules.worth,
    # ...
}

module = MODULES.get(sys.argv[1])
module.dispatch(sys.argv[2:])
```

### 3. Generic YAML store

Abstract the load/save/list pattern:

```python
def load_entity(directory, slug):
    """Load <directory>/<slug>.yaml"""

def save_entity(directory, slug, data):
    """Write <directory>/<slug>.yaml"""

def list_entities(directory):
    """Return list of slugs in directory"""
```

## Migration Path for Existing consult Users

**Low risk.** Existing data formats are preserved:

1. `projects/*.yaml` — no format change
2. `timesheets/unbilled.yaml` — no format change
3. `timesheets/billed/` — no format change
4. `invoices/` — per-invoice journals stay
5. `templates/` — no change

**Migration script would:**
1. Move entity data from `config.yaml` → `contacts/<slug>.yaml` (add `role: entity`, nest billing fields)
2. Create new directories (`assets/`, `liabilities/`, `contacts/`, `contracts/`, `journal/`, `generated/`, `include/`)
3. Generate `include/` chain files
4. Update config schema (add defaults for new modules)
5. Existing journals and PDFs untouched

**User impact:** Replace `consult` with `pair revenue` in aliases/scripts. Everything else is additive.

## Build Order

1. Extract helpers → `lib/`
2. Wrap existing consult commands under `pair revenue *`
3. Build asset module (add, list, show, amort, dispose)
4. Build liability module (add, list, pay, payments)
5. Build worth module (net worth reporting)
6. Build remaining modules (expense, contact, contract, payroll, equity)
7. Migration script for existing consult users
