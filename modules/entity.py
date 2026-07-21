"""pair entity — multi-entity (Company/Project) management."""

import sys
import yaml
from pathlib import Path

from lib.helpers import (
    BASE_DIR, GLOBAL_CONFIG_FILE,
    load_global_config, save_global_config, get_active_entity, entity_dir_for,
    entity_state, visible_entities, hidden_entities,
    prompt, validate_slug, ensure_dir, expand_path, slugify, save_config, confirm
)
from lib.journal import write_journal_atomic


# ─── Directory structure for an entity ───────────────────────────────────────

ENTITY_DIRS = [
    'assets',
    'liabilities',
    'contacts',
    'contracts',
    'projects',
    'deferred',
    'recurring',
    'journal',
    'generated',
    'include',
    'invoices',
    'timesheets',
]

# Default base for new entities/standalone projects. Entities used to live in
# the repo at BASE_DIR/entities; new ones default here instead, and get an
# explicit `path` in global.yaml (resolved by entity_dir_for).
DOCS_BASE = Path.home() / 'Documents' / 'Accounting'
ENTITIES_BASE = DOCS_BASE / 'Entities'
PROJECTS_BASE = DOCS_BASE / 'Projects'
ARCHIVE_BASE = DOCS_BASE / 'Pairs' / 'Archive'

# Files that mark a folder as an existing hledger ledger (registration signal).
JOURNAL_EXTS = ('.journal', '.j', '.hledger')


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route: list, add, use, show (default)."""
    if not args or args[0] == 'show':
        cmd_show()
    elif args[0] == 'list':
        cmd_list()
    elif args[0] in ('create', 'add'):
        cmd_create(args[1:])
    elif args[0] == 'use':
        cmd_use(args[1:])
    elif args[0] == 'path':
        cmd_path(args[1:])
    elif args[0] == 'move':
        cmd_move(args[1:])
    elif args[0] == 'remove':
        cmd_remove(args[1:])
    elif args[0] == 'restore':
        cmd_restore(args[1:])
    elif args[0] == 'archive':
        cmd_archive(args[1:])
    elif args[0] == 'delete':
        cmd_delete(args[1:])
    elif args[0] == 'archived':
        cmd_archived()
    elif args[0] in ('--help', '-h'):
        print_help()
    else:
        print(f"Unknown entity subcommand: {args[0]}")
        print("Usage: pair entity [show|list|create|use|path|move|remove|restore|archive|delete|archived]")
        sys.exit(1)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_show():
    """Display active entity name and slug."""
    config = load_global_config()
    if not config:
        print("No entities configured. Run 'pair init' first.")
        return

    active = config.get('active')
    entities = config.get('entities', [])

    if not active or not entities:
        print("No active entity. Run 'pair init' first.")
        return

    # Find the active entity details
    for e in entities:
        if e['slug'] == active:
            print(f"Active entity (Company/Project): {e['name']} ({e['slug']})")
            return

    print(f"Active entity slug: {active} (details not found)")


def cmd_list():
    """Show all entities from global.yaml with active marker."""
    config = load_global_config()
    if not config:
        print("No entities configured. Run 'pair init' first.")
        return

    active = config.get('active')
    entities = config.get('entities', [])

    if not entities:
        print("No entities configured. Run 'pair init' first.")
        return

    shown = visible_entities(config)
    print("Entities (Company/Project):\n")
    for e in shown:
        marker = " *" if e['slug'] == active else "  "
        kind = e.get('kind', 'entity')
        suffix = "  (project)" if kind == 'project' else ""
        print(f"  {marker} {e['name']} ({e['slug']}){suffix}")

    hidden = len(entities) - len(shown)
    print(f"\n  * = active")
    if hidden:
        print(f"  {hidden} removed/archived — see 'pair entity archived'")


def _find_journal_file(folder):
    """Return the first hledger-parseable ledger file in folder, else None.

    Detection is extension-then-parseability: an extension match that hledger
    cannot parse is treated as no ledger, so a broken file yields a fresh
    create rather than a false registration.
    """
    import subprocess
    if not folder.exists():
        return None
    candidates = sorted(
        [p for p in folder.rglob('*') if p.suffix in JOURNAL_EXTS and p.is_file()],
        key=lambda p: (len(p.relative_to(folder).parts), p.name))
    for path in candidates:
        try:
            r = subprocess.run(['hledger', '-f', str(path), 'stats'],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return path
        except Exception:
            continue
    return None


def _scan_structure(folder):
    """Return (found, missing) lists of standard subfolders in folder."""
    found = [d for d in ENTITY_DIRS if (folder / d).is_dir()]
    missing = [d for d in ENTITY_DIRS if not (folder / d).is_dir()]
    return found, missing


def cmd_add(args=None):
    """Backward-compatible alias for cmd_create."""
    cmd_create(args or [])


def cmd_create(args=None):
    """Create or register an entity or project, interactively."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        return
    entities = config.get('entities', []) or []
    known_slugs = {e.get('slug') for e in entities}

    print("\n  pair create — new entity or project\n")

    # 1. Kind.
    kind = prompt("  Create an (e)ntity or (p)roject?", default='e').strip().lower()
    kind = 'project' if kind.startswith('p') else 'entity'

    # 2. Parent, for projects (optional — a project may stand alone).
    parent = None
    if kind == 'project':
        raw = prompt("  Parent entity slug (blank = standalone)", required=False).strip()
        if raw:
            if raw not in known_slugs:
                print(f"\n  No entity with slug '{raw}'. Known: {', '.join(sorted(s for s in known_slugs if s))}\n")
                return
            parent = raw

    # 3. Name / slug.
    name = prompt(f"  {kind.capitalize()} name")
    slug = prompt("  Slug (short identifier)", default=slugify(name), validator=validate_slug)
    if slug in known_slugs:
        print(f"\n  Error: '{slug}' already exists in global.yaml.\n")
        return

    # 4. Destination (default per kind/parent; overridable).
    if kind == 'project' and parent:
        default_dir = entity_dir_for(parent, config) / 'projects' / slug
    elif kind == 'project':
        default_dir = PROJECTS_BASE / slug
    else:
        default_dir = ENTITIES_BASE / slug
    raw_dest = prompt("  Folder location", default=str(default_dir)).strip()
    dest = expand_path(raw_dest).resolve()

    # 5. Registration fork: an existing hledger ledger here means "adopt it".
    registering = False
    journal_file = None
    existing = _find_journal_file(dest)
    if existing:
        rel = existing.relative_to(dest) if dest in existing.parents else existing.name
        print(f"\n  Found an existing hledger journal here: {rel}")
        if not confirm("  Register this existing folder (use this journal)?", default_yes=True):
            print("  Cancelled — choose a different location or move the file.\n")
            return
        registering = True
        journal_file = str(existing)
        found, missing = _scan_structure(dest)
        print(f"\n  Standard folders found:   {', '.join(found) if found else '(none)'}")
        if missing:
            print(f"  Will be created:          {', '.join(missing)}")
        else:
            print("  All standard folders present — nothing to create.")

    # 6. Remaining details.
    currency = prompt("  Default currency", default=config.get('currency', 'CAD') if isinstance(config.get('currency'), str) else 'CAD')
    if not journal_file:
        journal_file = str(dest / 'include' / 'company.journal')
    bank_account = f"Assets:Current:{prompt('  Primary bank account name', default='Chequing')}"

    if registering:
        _register_missing(dest, name, slug, currency, journal_file, bank_account)
    else:
        _create_entity_structure(dest, name, slug, currency, journal_file, bank_account)

    # 7. Register in global.yaml.
    entry = {'name': name, 'slug': slug, 'currency': currency,
             'kind': kind, 'journal_file': journal_file}
    if parent:
        entry['parent'] = parent
    # Store path whenever it isn't the legacy in-repo default.
    if dest.resolve() != (BASE_DIR / 'entities' / slug).resolve():
        entry['path'] = str(dest)
    entities.append(entry)
    config['entities'] = entities
    save_global_config(config)

    label = f"project (under {parent})" if parent else kind
    verb = "registered" if registering else "created"
    print(f"\n  ✓ {name} {verb} as {label} at {dest}")
    print(f"  Switch to it with: pair switch {slug}\n")


def _register_missing(dest, name, slug, currency, journal_file, bank_account):
    """Non-destructive: create only the standard folders/files that are absent."""
    for d in ENTITY_DIRS:
        ensure_dir(dest / d)
    cfg = dest / 'config.yaml'
    if not cfg.exists():
        _write_entity_config(dest, name, slug, currency, journal_file, bank_account)
        print(f"  Created config.yaml")
    else:
        print(f"  Kept existing config.yaml")
    acct = dest / 'include' / 'accounts.journal'
    if not acct.exists():
        write_journal_atomic(acct, _default_accounts(bank_account, currency))
        print(f"  Created include/accounts.journal")


def cmd_use(args):
    """Change active entity in global.yaml."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        sys.exit(1)

    if not args:
        print("Usage: pair entity use <slug>")
        print("       pair switch <slug>")
        sys.exit(1)

    slug = args[0]
    entities = config.get('entities', [])

    # Validate that slug exists
    found = None
    for e in entities:
        if e['slug'] == slug:
            found = e
            break

    if not found:
        print(f"No entity with slug '{slug}'.")
        print("Available entities:")
        for e in entities:
            print(f"  {e['slug']} — {e['name']}")
        sys.exit(1)

    config['active'] = slug
    save_global_config(config)
    _write_prompt_cache(slug)
    print(f"Switched to: {found['name']} ({slug})")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _write_entity_config(entity_dir, name, slug, currency, journal_file, bank_account):
    """Write config.yaml for an entity/project."""
    config = {
        'pair': {'name': name, 'slug': slug, 'currency': currency},
        'journal_file': journal_file,
        'accounts': {
            'bank': bank_account,
            'receivable': 'Assets:Current:Accounts Receivable',
            'payable': 'Liabilities:Current:Accounts Payable',
        },
        'divisions': [],
        'defaults': {'fiscal_year_start': 1},
    }
    config_path = entity_dir / 'config.yaml'
    ensure_dir(config_path.parent)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _create_entity_structure(entity_dir, name, slug, currency, journal_file, bank_account):
    """Create full directory structure and config for an entity."""
    # Create directories
    for d in ENTITY_DIRS:
        ensure_dir(entity_dir / d)

    # Create config.yaml
    _write_entity_config(entity_dir, name, slug, currency, journal_file, bank_account)
    print(f"  Created {slug}/config.yaml")

    # Create accounts.journal
    accounts_path = entity_dir / 'include' / 'accounts.journal'
    write_journal_atomic(accounts_path, _default_accounts(bank_account, currency))
    print(f"  Created {slug}/include/accounts.journal")

    # Create company.journal (the entity's own master include).
    company_journal_path = entity_dir / 'include' / 'company.journal'
    write_journal_atomic(company_journal_path, f"""; {name} — master include file
; Generated by: pair create

include accounts.journal
""")
    print(f"  Created {slug}/include/company.journal")

    # If journal_file points outside the entity's own include dir, it's an
    # external main ledger to wire up. If it points at the entity's own
    # company.journal (the self-contained default), there's nothing to include.
    journal_path = expand_path(journal_file).resolve()
    own_master = company_journal_path.resolve()
    if journal_path == own_master:
        return

    include_line = f"include {company_journal_path}\n"
    if not journal_path.exists():
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, 'w') as f:
            f.write(f"; {name} — main ledger\n; Created by: pair create\n\n")
            f.write(include_line)
        print(f"\n  Created {journal_file} with include line.")
    else:
        content = journal_path.read_text()
        if str(company_journal_path) not in content:
            print(f"\n  Add this line to {journal_file}:")
            print(f"    {include_line.strip()}")
        else:
            print(f"  {journal_file} already includes this entity.")


def _default_accounts(bank_account, currency):
    """Generate default accounts.journal content."""
    return f"""; pair account declarations
; Generated by: pair

; Assets — Current
account Assets:Current:Chequing                              ; type:A
account Assets:Current:Savings                               ; type:A
account Assets:Current:Petty Cash                            ; type:A
account Assets:Current:Accounts Receivable                   ; type:A
account Assets:Current:Prepaid Expenses                      ; type:A

; Assets — Fixed
account Assets:Fixed:Equipment                               ; type:A
account Assets:Fixed:Vehicles                                ; type:A
account Assets:Fixed:Furniture                               ; type:A
account Assets:Fixed:Leasehold Improvements                  ; type:A
account Assets:Fixed:Intellectual Property                   ; type:A

; Assets — Accumulated Amortization (contra)
account Assets:Accumulated Amortization:Equipment            ; type:A
account Assets:Accumulated Amortization:Vehicles             ; type:A
account Assets:Accumulated Amortization:Furniture            ; type:A
account Assets:Accumulated Amortization:Leasehold Improvements ; type:A
account Assets:Accumulated Amortization:Intellectual Property ; type:A

; Liabilities — Current
account Liabilities:Current:Accounts Payable                 ; type:L
account Liabilities:Current:Credit Card                      ; type:L
account Liabilities:Current:HST Payable                      ; type:L
account Liabilities:Current:Payroll Payable                  ; type:L
account Liabilities:Current:Income Tax Payable               ; type:L
account Liabilities:Current:Unearned Revenue                 ; type:L

; Liabilities — Long-Term
account Liabilities:Long-Term:Bank Loan                      ; type:L
account Liabilities:Long-Term:Vehicle Loan                   ; type:L
account Liabilities:Long-Term:Shareholder Loan               ; type:L

; Equity
account Equity:Owner Investment                              ; type:E
account Equity:Owner Draws                                   ; type:E
account Equity:Retained Earnings                             ; type:E

; Income — Operating
account Income:Operating:Consulting                          ; type:R
account Income:Operating:Services                            ; type:R
account Income:Operating:Product Sales                       ; type:R
account Income:Operating:Recurring Revenue                   ; type:R

; Income — Non-Operating
account Income:Non-Operating:Interest Income                 ; type:R
account Income:Non-Operating:Gain on Disposal                ; type:R
account Income:Non-Operating:Foreign Exchange Gain           ; type:R
account Income:Non-Operating:Other Income                    ; type:R

; Expenses — Operating
account Expenses:Operating:Payroll:Salaries                  ; type:X
account Expenses:Operating:Payroll:Benefits                  ; type:X
account Expenses:Operating:Payroll:Employer Contributions    ; type:X
account Expenses:Operating:Rent                              ; type:X
account Expenses:Operating:Utilities                         ; type:X
account Expenses:Operating:Insurance                         ; type:X
account Expenses:Operating:Office Supplies                   ; type:X
account Expenses:Operating:Software Subscriptions            ; type:X
account Expenses:Operating:Professional Fees                 ; type:X
account Expenses:Operating:Travel                            ; type:X
account Expenses:Operating:Meals and Entertainment           ; type:X
account Expenses:Operating:Marketing                         ; type:X
account Expenses:Operating:Telecommunications               ; type:X
account Expenses:Operating:Bank Fees                         ; type:X
account Expenses:Operating:Repairs and Maintenance           ; type:X

; Expenses — Non-Operating
account Expenses:Non-Operating:Amortization                  ; type:X
account Expenses:Non-Operating:Interest Expense              ; type:X
account Expenses:Non-Operating:Loss on Disposal              ; type:X
account Expenses:Non-Operating:Foreign Exchange Loss         ; type:X
account Expenses:Non-Operating:Income Tax Expense            ; type:X
"""


# ─── Entity folder location ──────────────────────────────────────────────────

def _resolve_slug(args):
    """Split args into (slug, rest). A leading known slug is consumed."""
    config = load_global_config()
    slugs = [e.get('slug') for e in config.get('entities', []) or []]
    if args and args[0] in slugs:
        return args[0], args[1:]
    return get_active_entity(), args


def _set_entity_path(slug, new_dir):
    """Record an entity's folder location in global.yaml.

    Storing the default location would be noise, so it is recorded only when
    the folder actually lives somewhere else.
    """
    config = load_global_config()
    default = BASE_DIR / 'entities' / slug
    for entry in config.get('entities', []) or []:
        if entry.get('slug') == slug:
            if Path(new_dir).resolve() == default.resolve():
                entry.pop('path', None)
            else:
                entry['path'] = str(new_dir)
            save_global_config(config)
            return True
    return False


def cmd_path(args):
    """Show, or register, an entity's folder location."""
    slug, rest = _resolve_slug(args)
    if not slug:
        print("\n  No active entity.\n")
        return

    current = entity_dir_for(slug)
    if not rest:
        exists = "" if current.exists() else "   (missing!)"
        print(f"\n  {slug}: {current}{exists}\n")
        return

    new_dir = expand_path(rest[0]).resolve()
    if not new_dir.exists():
        print(f"\n  Not found: {new_dir}")
        print("  'path' registers a folder that already exists.")
        print(f"  To move the folder there, use: pair entity move {slug} {rest[0]}\n")
        return
    if not new_dir.is_dir():
        print(f"\n  Not a directory: {new_dir}\n")
        return

    if _set_entity_path(slug, new_dir):
        print(f"\n  {slug} now resolves to: {new_dir}\n")
    else:
        print(f"\n  Entity '{slug}' not found in global.yaml\n")


def cmd_move(args):
    """Physically move an entity's folder, then update global.yaml."""
    import shutil

    assume_yes = any(a in ('--yes', '-y', '--batch') for a in args)
    args = [a for a in args if a not in ('--yes', '-y', '--batch')]

    slug, rest = _resolve_slug(args)
    if not slug:
        print("\n  No active entity.\n")
        return
    if not rest:
        print("\n  Usage: pair entity move [<slug>] <dest> [--yes]\n")
        return

    src = entity_dir_for(slug).resolve()
    if not src.exists():
        print(f"\n  Nothing to move — {slug} is not at {src}")
        print(f"  If you moved it yourself, register it: pair entity path {slug} <dir>\n")
        return

    # mv semantics: an existing directory means "move into it".
    raw = expand_path(rest[0])
    dest = (raw / slug).resolve() if raw.is_dir() else raw.resolve()

    if dest == src:
        print(f"\n  {slug} is already at {src}\n")
        return
    if dest.exists() and any(dest.iterdir()):
        print(f"\n  Destination exists and is not empty: {dest}\n")
        return
    if src in dest.parents:
        print(f"\n  Cannot move a folder inside itself: {dest}\n")
        return

    print(f"\n  Move entity '{slug}'")
    print(f"    from: {src}")
    print(f"      to: {dest}")
    if not assume_yes:
        try:
            proceed = confirm("\n  Proceed?", default_yes=False)
        except EOFError:
            # Non-interactive without --yes: refuse rather than traceback.
            print("\n  Not confirmed (no input). Re-run with --yes to move.\n")
            return
        if not proceed:
            print("  Cancelled.\n")
            return

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dest))
    except Exception as e:
        print(f"\n  Move failed, nothing changed: {e}\n")
        return

    # Only now update config: a stale path is worse than none.
    if not _set_entity_path(slug, dest):
        print(f"\n  Moved to {dest}, but '{slug}' was not in global.yaml.")
        print(f"  Register it with: pair entity path {slug} {dest}\n")
        return

    print(f"\n  ✓ {slug} moved to {dest}\n")


# ─── Lifecycle: remove / restore / archive / delete ──────────────────────────

def _find_entry(config, slug):
    for e in config.get('entities', []) or []:
        if e.get('slug') == slug:
            return e
    return None


def _owned_projects(config, slug):
    return [e for e in config.get('entities', []) or []
            if e.get('parent') == slug and entity_state(e) == 'active']


def _lifecycle_target(args, verb):
    """Resolve and validate the slug for a lifecycle command."""
    args = [a for a in args if not a.startswith('-')]
    if not args:
        print(f"\n  Usage: pair entity {verb} <slug>\n")
        return None, None
    slug = args[0]
    config = load_global_config()
    entry = _find_entry(config, slug)
    if not entry:
        print(f"\n  No entity or project with slug '{slug}'\n")
        return None, None
    if slug == get_active_entity() and verb != 'restore':
        print(f"\n  '{slug}' is the active entity. Switch away first:  pair switch <other>\n")
        return None, None
    owned = _owned_projects(config, slug)
    if owned and verb != 'restore':
        print(f"\n  '{slug}' owns {len(owned)} project(s): {', '.join(o['slug'] for o in owned)}")
        print(f"  {verb.capitalize()} or reparent those first.\n")
        return None, None
    return config, entry


def cmd_remove(args):
    """Hide an entity/project from lists and references. Files untouched."""
    config, entry = _lifecycle_target(args, 'remove')
    if not config:
        return
    slug = entry['slug']
    if entry.get('removed'):
        print(f"\n  '{slug}' is already removed.\n")
        return
    entry['removed'] = True
    save_global_config(config)
    print(f"\n  ✓ '{slug}' removed from lists. Files left at {entity_dir_for(slug, config)}")
    print(f"  Bring it back with: pair entity restore {slug}\n")


def cmd_restore(args):
    """Undo a remove or archive."""
    config, entry = _lifecycle_target(args, 'restore')
    if not config:
        return
    slug = entry['slug']
    state = entity_state(entry)
    if state == 'active':
        print(f"\n  '{slug}' is already active.\n")
        return

    if state == 'archived':
        import shutil
        current = entity_dir_for(slug, config)
        target = expand_path(entry.get('prev_path') or (ENTITIES_BASE / slug))
        if current.exists():
            if target.exists() and any(target.iterdir()):
                print(f"\n  Cannot restore — destination exists and is not empty: {target}\n")
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(target))
        entry['path'] = str(target)
        entry.pop('prev_path', None)
        entry.pop('archived', None)
        print(f"\n  ✓ '{slug}' restored to {target}")
    else:
        entry.pop('removed', None)
        print(f"\n  ✓ '{slug}' restored to lists")

    save_global_config(config)
    print(f"  Switch to it with: pair switch {slug}\n")


def cmd_archive(args):
    """Move an entity/project folder into the archive base, keep a reference."""
    import shutil
    config, entry = _lifecycle_target(args, 'archive')
    if not config:
        return
    slug = entry['slug']
    if entry.get('archived'):
        print(f"\n  '{slug}' is already archived.\n")
        return

    src = entity_dir_for(slug, config)
    dest = (ARCHIVE_BASE / slug).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f"\n  Archive slot already occupied: {dest}\n")
        return

    print(f"\n  Archive '{slug}'")
    print(f"    from: {src}")
    print(f"      to: {dest}")
    if not confirm("\n  Proceed?", default_yes=False):
        print("  Cancelled.\n")
        return

    if src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dest))
        except Exception as e:
            print(f"\n  Archive failed, nothing changed: {e}\n")
            return
    else:
        print(f"  (folder not found at {src} — recording the archive anyway)")

    entry['prev_path'] = str(src)
    entry['path'] = str(dest)
    entry['archived'] = True
    save_global_config(config)
    print(f"\n  ✓ '{slug}' archived to {dest}")
    print(f"  See archived items with: pair entity archived")
    print(f"  Bring it back with:      pair entity restore {slug}\n")


def cmd_delete(args):
    """Permanently delete an entity/project — files and registration."""
    import shutil
    assume_yes = any(a in ('--yes', '-y') for a in args)
    config, entry = _lifecycle_target(args, 'delete')
    if not config:
        return
    slug = entry['slug']
    folder = entity_dir_for(slug, config)

    count = 0
    if folder.exists():
        count = sum(1 for _ in folder.rglob('*') if _.is_file())

    print(f"\n  DELETE '{slug}' — this cannot be undone.")
    print(f"    folder: {folder}{'' if folder.exists() else '   (missing)'}")
    print(f"    files:  {count}")
    print(f"\n  Alternatives: 'pair entity remove {slug}' (hide, keep files)")
    print(f"                'pair entity archive {slug}' (move to archive)")

    if not assume_yes:
        try:
            typed = prompt(f"\n  Type the slug '{slug}' to confirm", required=False)
        except EOFError:
            print("\n  Not confirmed (no input). Re-run with --yes to delete.\n")
            return
        if (typed or '').strip() != slug:
            print("  Slug did not match. Cancelled.\n")
            return

    if folder.exists():
        try:
            shutil.rmtree(folder)
        except Exception as e:
            print(f"\n  Delete failed, registration left intact: {e}\n")
            return

    config['entities'] = [e for e in config.get('entities', []) or [] if e.get('slug') != slug]
    save_global_config(config)
    print(f"\n  ✓ '{slug}' deleted ({count} files removed)\n")


def cmd_archived():
    """List removed and archived entities/projects."""
    config = load_global_config()
    hidden = hidden_entities(config)
    if not hidden:
        print("\n  Nothing removed or archived.\n")
        return
    print("\n  Removed / archived:\n")
    for e in hidden:
        state = entity_state(e)
        kind = e.get('kind', 'entity')
        print(f"    [{state:8}] {e.get('name', e['slug'])} ({e['slug']}) — {kind}")
        print(f"               {entity_dir_for(e['slug'], config)}")
    print("\n  Restore with: pair entity restore <slug>\n")


def print_help():
    print("""pair entity — manage entities (Company/Project)

Usage:
  pair entity               Show active entity
  pair entity show          Show active entity
  pair entity list          List all entities
  pair entity create        Create/register an entity or project
  pair create <...>         Same (shortcut)
  pair entity add           Alias for create
  pair entity use <slug>    Switch active entity
  pair switch <slug>        Switch active entity (shortcut)

Lifecycle:
  pair entity remove <slug>   Hide from lists (files kept, reversible)
  pair entity restore <slug>  Undo a remove or archive
  pair entity archive <slug>  Move folder to the archive, keep a reference
  pair entity archived        List removed/archived items
  pair entity delete <slug>   Permanently delete files + registration

Entity folder location:
  pair entity path                      Show where the active entity lives
  pair entity path <slug>               Show where <slug> lives
  pair entity path [<slug>] <dir>       Register an existing folder (no move)
  pair entity move [<slug>] <dest>      Move the folder there and update config
                                        (add --yes to skip the confirmation)

  'move' follows mv semantics: if <dest> is an existing directory the folder
  is moved into it as <dest>/<slug>; otherwise <dest> is the new folder path.
  Use 'path' when you have already moved a folder yourself.
""")


def _write_prompt_cache(slug):
    """Write active entity to ~/.pair_prompt for shell PS1 integration."""
    prompt_file = Path.home() / '.pair_prompt'
    try:
        prompt_file.write_text(f"[{slug}] ")
    except OSError:
        pass  # non-critical
