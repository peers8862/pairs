"""pair revenue — time logging, invoicing, and payment tracking."""

import sys
import os
import re
import csv
import yaml
import subprocess
from datetime import date, datetime
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

from lib.helpers import (
    prompt, validate_slug, validate_date, validate_positive_number,
    money, expand_path, ensure_dir, load_config, save_config,
    parse_global_flags, confirm, prompt_choice, BASE_DIR
)
from lib.journal import (
    format_entry, generated_header, write_journal_atomic, append_journal,
    ensure_year_structure, GENERATED_DIR, JOURNAL_DIR, INCLUDE_DIR
)


# ─── Paths ───────────────────────────────────────────────────────────────────

PROJECTS_DIR = BASE_DIR / "projects"
TIMESHEETS_DIR = BASE_DIR / "timesheets"
UNBILLED_FILE = TIMESHEETS_DIR / "unbilled.yaml"
BILLED_DIR = TIMESHEETS_DIR / "billed"
INVOICES_DIR = BASE_DIR / "invoices"
OUTPUT_DIR = BASE_DIR / "output"
BUILD_DIR = BASE_DIR / "build"
TEMPLATES_DIR = BASE_DIR / "templates"


# ─── Private helpers ─────────────────────────────────────────────────────────

def _validate_tax(value):
    """Must be a number or 'exempt'."""
    if value.lower() == "exempt":
        return None
    try:
        n = Decimal(value)
        if n < 0:
            return "Must be >= 0 or 'exempt'."
    except Exception:
        return "Must be a number or 'exempt'."
    return None


def _validate_type(value):
    """Type must be alpha + hyphens only."""
    if not re.match(r'^[a-z][a-z-]*[a-z]$|^[a-z]$', value):
        return "Must be lowercase letters and hyphens only."
    return None


def _get_effective_rate(project, entry_date):
    """Look up the effective rate for a given date from project rate history."""
    rates = project.get("rates", [])
    if not rates:
        return None, None
    rates_sorted = sorted(rates, key=lambda r: r["from"])
    effective = None
    for r in rates_sorted:
        if entry_date >= r["from"]:
            effective = r
        else:
            break
    return effective, project.get("rate_type", "hourly")


def _compute_hourly_rate(rate_entry, rate_type, hours_per_day):
    """Compute effective hourly rate from a rate entry."""
    if rate_type == "daily":
        daily = Decimal(str(rate_entry["daily_rate"]))
        hpd = Decimal(str(hours_per_day))
        return money(daily / hpd)
    else:
        return Decimal(str(rate_entry["hourly_rate"]))


def _load_unbilled():
    """Load unbilled entries."""
    if not UNBILLED_FILE.exists():
        return {"entries": []}
    with open(UNBILLED_FILE) as f:
        data = yaml.safe_load(f)
    return data if data and "entries" in data else {"entries": []}


def _save_unbilled(data):
    """Write unbilled entries."""
    ensure_dir(TIMESHEETS_DIR)
    with open(UNBILLED_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load_project(slug):
    """Load a project YAML by slug."""
    path = PROJECTS_DIR / f"{slug}.yaml"
    if not path.exists():
        print(f"Project '{slug}' not found.")
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _save_project(slug, data):
    """Write a project YAML."""
    ensure_dir(PROJECTS_DIR)
    path = PROJECTS_DIR / f"{slug}.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _list_projects():
    """Return list of project slugs."""
    ensure_dir(PROJECTS_DIR)
    return [p.stem for p in PROJECTS_DIR.glob("*.yaml")]


def _parse_selection(s, max_val):
    """Parse selection like '1-3,5,7' into 0-based indices."""
    indices = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= max_val:
                        indices.add(i - 1)
            except ValueError:
                pass
        else:
            try:
                i = int(part)
                if 1 <= i <= max_val:
                    indices.add(i - 1)
            except ValueError:
                pass
    return sorted(indices)


def _increment_invoice_number(current):
    """Increment invoice number like '2026-001' → '2026-002'."""
    match = re.match(r'^(.+-)(\d+)$', current)
    if match:
        prefix = match.group(1)
        num = int(match.group(2)) + 1
        width = len(match.group(2))
        return f"{prefix}{num:0{width}d}"
    return current


def _ensure_include(journal_path, invoices_dir):
    """Ensure the journal file has an include for the invoices directory."""
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return

    include_pattern = str(invoices_dir / "*.journal")
    try:
        rel = os.path.relpath(include_pattern, journal_path.parent)
    except ValueError:
        rel = include_pattern

    include_line = f"include {rel}"

    with open(journal_path) as f:
        content = f.read()

    if rel in content or str(invoices_dir) in content:
        return

    answer = prompt(f"Add '{include_line}' to {journal_path}? (Y/n)", default="Y")
    if answer.lower().startswith("y"):
        with open(journal_path, "a") as f:
            f.write(f"\n{include_line}\n")
        print(f"✓ Added include to {journal_path}")


def _get_invoice_template(config, entity_slug, project_data):
    """Resolve template path: project > entity > default."""
    if project_data and project_data.get("template"):
        t = TEMPLATES_DIR / project_data["template"]
        if t.exists():
            return t

    entity = config.get("entities", {}).get(entity_slug, {})
    if entity.get("template"):
        t = TEMPLATES_DIR / entity["template"]
        if t.exists():
            return t

    return TEMPLATES_DIR / "invoice.typ"


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route revenue subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'project':
        sub = action_args[0] if action_args else None
        if sub == 'add':
            cmd_project_add(flags, action_args[1:])
        elif sub == 'list':
            cmd_project_list(flags, action_args[1:])
        else:
            print("Usage: pair revenue project [add|list]")
    elif action == 'rate':
        slug = action_args[0] if action_args else None
        cmd_rate(flags, slug)
    elif action == 'log':
        if flags.get('batch') or '--batch' in action_args:
            cmd_log_batch(flags, action_args)
        elif action_args and action_args[0] == 'edit':
            cmd_log_edit(flags, action_args[1:])
        else:
            cmd_log(flags, action_args)
    elif action == 'status':
        cmd_status(flags, action_args)
    elif action == 'invoice':
        cmd_invoice(flags, action_args)
    elif action == 'paid':
        cmd_paid(flags, action_args)
    elif action == 'outstanding':
        cmd_outstanding(flags, action_args)
    elif action == 'export':
        cmd_export(flags, action_args)
    elif action == 'undo':
        cmd_undo(flags, action_args)
    elif action == 'defer':
        cmd_defer(flags, action_args)
    elif action == 'recognize':
        cmd_recognize(flags, action_args)
    elif action == 'deferred':
        cmd_deferred(flags, action_args)
    else:
        print(f"Unknown revenue action: {action}")
        print_help()
        sys.exit(1)


# ─── Help ────────────────────────────────────────────────────────────────────

def print_help():
    """Print revenue module help."""
    print("""
Usage: pair revenue <command> [options]

Commands:
  project add       Create a new billing project
  project list      List projects
  rate <project>    Update rate for a project
  log               Log time entry (interactive)
  log --batch       Log multiple entries (batch mode)
  log edit          Edit a previous time entry
  status            Show unbilled time summary
  invoice           Generate invoice from unbilled time
  paid              Record payment received
  outstanding       Show unpaid invoices (aging report)
  export            Export time entries to CSV
  undo              Remove last time entry
  defer             Record prepayment (deferred revenue)
  recognize <slug>  Recognize portion of deferred revenue
  deferred          List all deferred revenue items

Options for 'export':
  --project SLUG    Filter by project
  --from DATE       Filter from date
  --to DATE         Filter to date
  --tag TAG         Filter by tag
  --type TYPE       Filter by entry type
  --all             Include billed entries

Global flags:
  --batch           Batch mode for log
  --date DATE       Override date
  --yes / -y        Skip confirmations
  --help / -h       Show this help
""".strip())


# ─── Project commands ────────────────────────────────────────────────────────

def cmd_project_add(flags, args):
    """Create a new billing project."""
    config = load_config()
    entities = config.get("entities", {})
    if not entities:
        print("No entities. Run 'pair init' first.")
        return

    print("Create a new project\n")

    # Pick entity
    default_entity = config.get("defaults", {}).get("entity")
    if len(entities) == 1:
        entity_slug = list(entities.keys())[0]
        print(f"Entity: {entity_slug}")
    else:
        entity_slug = prompt(
            "Entity", default=default_entity,
            validator=lambda v: None if v in entities else f"Unknown entity. Options: {', '.join(entities.keys())}"
        )

    entity = entities[entity_slug]

    slug = prompt("Project slug (short name)", validator=validate_slug)
    if (PROJECTS_DIR / f"{slug}.yaml").exists():
        print(f"Project '{slug}' already exists.")
        return

    client = prompt("Client name")
    project_name = prompt("Project name")
    currency = prompt("Currency", default=entity.get("currency", "CAD"))
    tax_val = prompt("Default tax %", default=str(entity.get("tax", 13)), validator=_validate_tax)
    tax = tax_val if tax_val.lower() == "exempt" else (int(tax_val) if tax_val.isdigit() else float(tax_val))

    # Rate setup
    print("\nRate configuration:")
    rate_type = prompt("Rate type - (d)aily or (h)ourly", default="d")
    rate_type = "daily" if rate_type.lower().startswith("d") else "hourly"

    if rate_type == "daily":
        daily_rate = prompt("Daily rate", validator=validate_positive_number)
        hours_per_day = prompt("Hours per day", default="7.5", validator=validate_positive_number)
        effective_from = prompt("Effective from date", default=date.today().isoformat(), validator=validate_date)
        hourly = money(Decimal(daily_rate) / Decimal(hours_per_day))
        print(f"  Effective hourly: ${hourly}/h (from ${daily_rate}/day ÷ {hours_per_day}h)")
        rate_entry = {"from": effective_from, "daily_rate": float(daily_rate)}
    else:
        hourly_rate = prompt("Hourly rate", validator=validate_positive_number)
        effective_from = prompt("Effective from date", default=date.today().isoformat(), validator=validate_date)
        rate_entry = {"from": effective_from, "hourly_rate": float(hourly_rate)}

    # Optional overrides
    journal_override = prompt("Journal file override (optional, enter to use entity default)", required=False)
    template_override = prompt("Invoice template (filename in templates/, or enter for entity/default)", required=False)

    project_data = {
        "entity": entity_slug,
        "client": client,
        "project": project_name,
        "currency": currency,
        "tax": tax,
        "rate_type": rate_type,
        "active": True,
        "rates": [rate_entry],
    }
    if rate_type == "daily":
        project_data["hours_per_day"] = float(hours_per_day)
    if journal_override:
        project_data["journal_file"] = journal_override
    if template_override:
        project_data["template"] = template_override

    _save_project(slug, project_data)
    config.setdefault("defaults", {})["last_project"] = slug
    save_config(config)
    print(f"\n✓ Created project '{slug}' → {client} / {project_name}")


def cmd_project_list(flags, args):
    """List all projects."""
    slugs = _list_projects()
    if not slugs:
        print("No projects. Run 'pair revenue project add'.")
        return

    print(f"{'Slug':<20} {'Client':<25} {'Project':<20} {'Entity':<12} {'Active'}")
    print("-" * 85)
    for slug in sorted(slugs):
        p = _load_project(slug)
        if p:
            active = "✓" if p.get("active", True) else "—"
            print(f"{slug:<20} {p.get('client',''):<25} {p.get('project',''):<20} {p.get('entity',''):<12} {active}")


# ─── Rate command ────────────────────────────────────────────────────────────

def cmd_rate(flags, slug=None):
    """Update rate for a project."""
    if not slug:
        print("Usage: pair revenue rate <project-slug>")
        return

    project = _load_project(slug)
    if not project:
        return

    rate_type = project.get("rate_type", "hourly")
    rates = project.get("rates", [])
    hours_per_day = project.get("hours_per_day", 7.5)

    if rates:
        current = sorted(rates, key=lambda r: r["from"])[-1]
        if rate_type == "daily":
            hourly = money(Decimal(str(current["daily_rate"])) / Decimal(str(hours_per_day)))
            print(f"Current rate: ${current['daily_rate']}/day ({hours_per_day}h = ${hourly}/h) effective from {current['from']}")
        else:
            print(f"Current rate: ${current['hourly_rate']}/h effective from {current['from']}")

    print(f"\nAdd new rate for '{slug}':")
    if rate_type == "daily":
        new_rate = prompt("New daily rate", validator=validate_positive_number)
        new_hpd = prompt("Hours per day", default=str(hours_per_day), validator=validate_positive_number)
        effective = prompt("Effective from", default=date.today().isoformat(), validator=validate_date)
        rate_entry = {"from": effective, "daily_rate": float(new_rate)}
        project["hours_per_day"] = float(new_hpd)
        hourly = money(Decimal(new_rate) / Decimal(new_hpd))
        print(f"\n✓ New rate: ${new_rate}/day ({new_hpd}h = ${hourly}/h) effective {effective}")
    else:
        new_rate = prompt("New hourly rate", validator=validate_positive_number)
        effective = prompt("Effective from", default=date.today().isoformat(), validator=validate_date)
        rate_entry = {"from": effective, "hourly_rate": float(new_rate)}
        print(f"\n✓ New rate: ${new_rate}/h effective {effective}")

    project.setdefault("rates", []).append(rate_entry)
    _save_project(slug, project)


# ─── Log command ─────────────────────────────────────────────────────────────

def cmd_log(flags, args):
    """Log time entry interactively."""
    config = load_config()
    last_project = config.get("defaults", {}).get("last_project")
    slugs = _list_projects()

    if not slugs:
        print("No projects. Run 'pair revenue project add' first.")
        return

    print("Log time entry\n")

    # Select project
    project_slug = prompt(
        "Project", default=last_project,
        validator=lambda v: None if v in slugs else f"Unknown. Options: {', '.join(slugs)}"
    )
    project = _load_project(project_slug)
    if not project:
        return

    rate_type = project.get("rate_type", "hourly")
    hours_per_day = project.get("hours_per_day", 7.5)
    default_tax = str(project.get("tax", 13))

    # Update last used project
    config.setdefault("defaults", {})["last_project"] = project_slug
    save_config(config)

    while True:
        entry_date = prompt("Date", default=flags.get('date') or date.today().isoformat(), validator=validate_date)
        hours = prompt("Hours", validator=validate_positive_number)
        focus = prompt("Focus/description")
        entry_type = prompt("Type", default="billable", validator=_validate_type)
        tags_raw = prompt("Tags (comma-separated, optional)", required=False)
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        # Resolve rate
        rate_entry, rt = _get_effective_rate(project, entry_date)
        if rate_entry:
            if rt == "daily":
                effective_hourly = _compute_hourly_rate(rate_entry, rt, hours_per_day)
                rate_display = f"{effective_hourly}/h from {rate_entry['daily_rate']}/day"
            else:
                effective_hourly = Decimal(str(rate_entry["hourly_rate"]))
                rate_display = f"{effective_hourly}/h"
        else:
            effective_hourly = None
            rate_display = "none (no rate for this date)"

        rate_input = prompt(
            "Rate", default=rate_display if effective_hourly else None,
            validator=validate_positive_number if not effective_hourly else None
        )
        if rate_input == rate_display:
            rate_val = float(effective_hourly)
        else:
            try:
                rate_val = float(rate_input)
            except ValueError:
                rate_val = float(effective_hourly) if effective_hourly else 0

        tax_input = prompt("Tax %", default=default_tax, validator=_validate_tax)
        tax_val = tax_input if tax_input.lower() == "exempt" else (int(tax_input) if tax_input.isdigit() else float(tax_input))

        entry = {
            "project": project_slug,
            "date": entry_date,
            "hours": float(hours),
            "focus": focus,
            "type": entry_type,
            "rate": rate_val,
            "tax": tax_val,
        }
        if tags:
            entry["tags"] = tags

        unbilled = _load_unbilled()
        unbilled["entries"].append(entry)
        _save_unbilled(unbilled)

        amount = money(Decimal(hours) * Decimal(str(rate_val)))
        print(f"✓ Logged {hours}h @ ${rate_val} = ${amount}")

        again = prompt("\nAdd another?", default="y")
        if not again.lower().startswith("y"):
            break
        print()


# ─── Log batch ───────────────────────────────────────────────────────────────

def cmd_log_batch(flags, args):
    """Log multiple time entries in batch mode."""
    config = load_config()
    last_project = config.get("defaults", {}).get("last_project")
    slugs = _list_projects()

    if not slugs:
        print("No projects. Run 'pair revenue project add' first.")
        return

    print("Batch log entries\n")
    print("Format: DATE HOURS FOCUS (one per line, Ctrl+D to finish)\n")

    project_slug = prompt(
        "Project", default=last_project,
        validator=lambda v: None if v in slugs else f"Unknown. Options: {', '.join(slugs)}"
    )
    project = _load_project(project_slug)
    if not project:
        return

    entry_type = prompt("Type for all entries", default="billable", validator=_validate_type)
    default_tax = str(project.get("tax", 13))
    tax_input = prompt("Tax % for all entries", default=default_tax, validator=_validate_tax)
    tax_val = tax_input if tax_input.lower() == "exempt" else (int(tax_input) if tax_input.isdigit() else float(tax_input))

    rate_type = project.get("rate_type", "hourly")
    hours_per_day = project.get("hours_per_day", 7.5)

    config.setdefault("defaults", {})["last_project"] = project_slug
    save_config(config)

    print("\nEnter lines (DATE HOURS FOCUS):")
    unbilled = _load_unbilled()
    count = 0
    total_hours = Decimal("0")

    try:
        while True:
            line = input("  ").strip()
            if not line or line == ".":
                break
            parts = line.split(None, 2)
            if len(parts) < 3:
                print("  ⚠ Need: DATE HOURS FOCUS")
                continue

            entry_date, hours_str, focus = parts

            if validate_date(entry_date):
                print(f"  ⚠ Invalid date: {entry_date}")
                continue
            if validate_positive_number(hours_str):
                print(f"  ⚠ Invalid hours: {hours_str}")
                continue

            # Resolve rate
            rate_entry, rt = _get_effective_rate(project, entry_date)
            if rate_entry:
                if rt == "daily":
                    rate_val = float(_compute_hourly_rate(rate_entry, rt, hours_per_day))
                else:
                    rate_val = float(rate_entry["hourly_rate"])
            else:
                print(f"  ⚠ No rate defined for {entry_date}. Skipping.")
                continue

            entry = {
                "project": project_slug,
                "date": entry_date,
                "hours": float(hours_str),
                "focus": focus,
                "type": entry_type,
                "rate": rate_val,
                "tax": tax_val,
            }
            unbilled["entries"].append(entry)
            count += 1
            total_hours += Decimal(hours_str)

    except EOFError:
        pass

    _save_unbilled(unbilled)
    print(f"\n✓ Logged {count} entries ({total_hours}h)")


# ─── Log edit ────────────────────────────────────────────────────────────────

def cmd_log_edit(flags, args):
    """Edit a previous time entry."""
    unbilled = _load_unbilled()
    entries = unbilled.get("entries", [])

    if not entries:
        print("No entries to edit.")
        return

    # Show recent entries
    show_count = min(20, len(entries))
    print(f"Recent entries (last {show_count}):\n")
    start = len(entries) - show_count
    for i, e in enumerate(entries[start:], start + 1):
        print(f"  {i}. {e.get('date'):<12} {e.get('hours'):>5.2f}h  {e.get('project'):<16} {e.get('focus','')[:30]}")

    print()
    choice = prompt("Entry number to edit (or 'q' to cancel)")
    if choice.lower() == "q":
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(entries):
            print("Invalid selection.")
            return
    except ValueError:
        print("Invalid selection.")
        return

    entry = entries[idx]
    print(f"\nEditing entry (press enter to keep current value):\n")

    entry["date"] = prompt("Date", default=entry.get("date", ""), validator=validate_date)
    hours = prompt("Hours", default=str(entry.get("hours", "")), validator=validate_positive_number)
    entry["hours"] = float(hours)
    entry["focus"] = prompt("Focus", default=entry.get("focus", ""))
    entry["type"] = prompt("Type", default=entry.get("type", "billable"), validator=_validate_type)
    tags_raw = prompt("Tags", default=",".join(entry.get("tags", [])), required=False)
    entry["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    rate = prompt("Rate", default=str(entry.get("rate", "")), validator=validate_positive_number)
    entry["rate"] = float(rate)
    tax_input = prompt("Tax", default=str(entry.get("tax", 13)), validator=_validate_tax)
    entry["tax"] = tax_input if tax_input.lower() == "exempt" else (int(tax_input) if tax_input.isdigit() else float(tax_input))

    _save_unbilled(unbilled)
    print("✓ Entry updated.")


# ─── Status ──────────────────────────────────────────────────────────────────

def cmd_status(flags, args):
    """Show unbilled time summary."""
    unbilled = _load_unbilled()
    entries = unbilled.get("entries", [])

    if not entries:
        print("No unbilled entries.")
        return

    # Group by project
    by_project = {}
    for e in entries:
        slug = e["project"]
        by_project.setdefault(slug, []).append(e)

    for slug, proj_entries in sorted(by_project.items()):
        project = _load_project(slug)
        if project:
            print(f"\n{slug} — {project.get('client', '')} / {project.get('project', '')} ({project.get('currency', 'CAD')})")
        else:
            print(f"\n{slug} (project file missing)")

        # Group by type
        by_type = {}
        for e in proj_entries:
            t = e.get("type", "billable")
            by_type.setdefault(t, []).append(e)

        for t, t_entries in sorted(by_type.items()):
            total_hours = sum(Decimal(str(e["hours"])) for e in t_entries)
            total_amount = sum(money(Decimal(str(e["hours"])) * Decimal(str(e["rate"]))) for e in t_entries)
            if t == "billable":
                print(f"  {t:<12} {total_hours:>6}h  →  ${total_amount}")
            else:
                print(f"  {t:<12} {total_hours:>6}h  (not billed)")

        all_hours = sum(Decimal(str(e["hours"])) for e in proj_entries)
        print(f"  {'total':<12} {all_hours:>6}h")


# ─── Invoice ─────────────────────────────────────────────────────────────────

def cmd_invoice(flags, args):
    """Generate invoice from unbilled time entries."""
    config = load_config()
    unbilled = _load_unbilled()
    entries = unbilled.get("entries", [])

    if not entries:
        print("No unbilled entries.")
        return

    slugs = _list_projects()
    last_project = config.get("defaults", {}).get("last_project")

    # Select project
    project_slug = prompt(
        "Project", default=last_project,
        validator=lambda v: None if v in slugs else f"Unknown. Options: {', '.join(slugs)}"
    )
    project = _load_project(project_slug)
    if not project:
        return

    entity_slug = project.get("entity")
    entity = config.get("entities", {}).get(entity_slug, {})

    # Filter entries for this project (billable only)
    proj_entries = [e for e in entries if e["project"] == project_slug and e.get("type", "billable") == "billable"]
    if not proj_entries:
        print(f"No billable unbilled entries for '{project_slug}'.")
        return

    # Display entries
    currency = project.get("currency", "CAD")
    print(f"\nUnbilled billable entries for {project.get('client')} / {project.get('project')} ({currency}):\n")
    print(f"  {'#':<4} {'Date':<12} {'Hours':>6} {'Rate':>8} {'Focus':<30} {'Tax'}")
    print(f"  {'-'*4} {'-'*10}   {'-'*6} {'-'*8} {'-'*30} {'-'*7}")

    for i, e in enumerate(proj_entries, 1):
        tax_str = "exempt" if e.get("tax") == "exempt" else f"{e.get('tax', 13)}%"
        print(f"  {i:<4} {e['date']:<12} {e['hours']:>6.2f} {e['rate']:>8.2f} {e.get('focus',''):<30} {tax_str}")

    # Selection
    print()
    choice = prompt("Include all? (Y/n/select)", default="Y")
    if choice.lower() == "n":
        print("Cancelled.")
        return
    elif choice.lower() == "select":
        sel_input = prompt("Entry numbers (e.g. 1-3,5,7)")
        selected_indices = _parse_selection(sel_input, len(proj_entries))
        if not selected_indices:
            print("No valid selection.")
            return
        selected_entries = [proj_entries[i] for i in selected_indices]
    else:
        selected_entries = proj_entries

    # Invoice details
    prefix = entity.get("invoice_prefix", "")
    next_inv = entity.get("next_invoice", "2026-001")
    invoice_num = prompt("Invoice number", default=f"{prefix}{next_inv}")
    invoice_date = prompt("Invoice date", default=date.today().isoformat(), validator=validate_date)
    notes = prompt("Invoice notes (optional)", required=False) or None

    # Calculate totals
    taxable_entries = [e for e in selected_entries if e.get("tax") != "exempt" and e.get("tax", 0) > 0]
    exempt_entries = [e for e in selected_entries if e.get("tax") == "exempt" or e.get("tax", 0) == 0]

    # Group taxable by rate %
    tax_groups = {}
    for e in taxable_entries:
        pct = e.get("tax", 13)
        tax_groups.setdefault(pct, []).append(e)

    taxable_subtotal = sum(money(Decimal(str(e["hours"])) * Decimal(str(e["rate"]))) for e in taxable_entries)
    exempt_subtotal = sum(money(Decimal(str(e["hours"])) * Decimal(str(e["rate"]))) for e in exempt_entries)

    total_tax = Decimal("0")
    tax_breakdown = []
    for pct, group_entries in sorted(tax_groups.items()):
        group_sub = sum(money(Decimal(str(e["hours"])) * Decimal(str(e["rate"]))) for e in group_entries)
        group_tax = money(group_sub * Decimal(str(pct)) / Decimal("100"))
        total_tax += group_tax
        tax_breakdown.append({"percent": pct, "subtotal": float(group_sub), "tax": float(group_tax)})

    grand_total = taxable_subtotal + exempt_subtotal + total_tax

    # Show summary
    print(f"\nSummary:")
    if taxable_subtotal:
        print(f"  Taxable subtotal:  ${taxable_subtotal} {currency}")
    for tb in tax_breakdown:
        print(f"  Tax ({tb['percent']}%):        ${money(Decimal(str(tb['tax'])))} {currency}")
    if exempt_subtotal:
        print(f"  Exempt subtotal:   ${exempt_subtotal} {currency}")
    print(f"  {'─' * 35}")
    print(f"  Total due:         ${grand_total} {currency}")

    answer = prompt("\nGenerate? (Y/n)", default="Y")
    if answer.lower() == "n":
        print("Cancelled.")
        return

    # Build invoice data for template
    line_items = []
    for e in selected_entries:
        amount = money(Decimal(str(e["hours"])) * Decimal(str(e["rate"])))
        line_items.append({
            "date": e["date"],
            "hours": e["hours"],
            "rate": e["rate"],
            "focus": e.get("focus", ""),
            "tax": e.get("tax", 13),
            "amount": float(amount),
        })

    invoice_data = {
        "invoice_number": invoice_num,
        "invoice_date": invoice_date,
        "entity": {
            "name": entity.get("name", ""),
            "business_number": entity.get("business_number"),
            "email": entity.get("email", ""),
            "phone": entity.get("phone"),
            "payment_terms": entity.get("payment_terms", "Net 30 days"),
        },
        "client": project.get("client", ""),
        "project": project.get("project", ""),
        "currency": currency,
        "rate_type": project.get("rate_type", "hourly"),
        "hours_per_day": project.get("hours_per_day"),
        "line_items": line_items,
        "taxable_subtotal": float(taxable_subtotal),
        "exempt_subtotal": float(exempt_subtotal),
        "tax_breakdown": tax_breakdown,
        "total_tax": float(total_tax),
        "grand_total": float(grand_total),
        "notes": notes,
    }

    # Write intermediate YAML for template
    ensure_dir(BUILD_DIR)
    build_file = BUILD_DIR / f"{invoice_num}.yaml"
    with open(build_file, "w") as f:
        yaml.dump(invoice_data, f, default_flow_style=False, sort_keys=False)

    # Write hledger journal
    year = invoice_date[:4]
    inv_dir = INVOICES_DIR / year
    ensure_dir(inv_dir)
    journal_file = inv_dir / f"{invoice_num}.journal"

    accts = entity.get("accounts", {})
    recv_acct = f"{accts.get('receivable', 'Assets:Accounts Receivable')}:{project.get('client', 'Client')}"
    income_acct = accts.get("income", "Income:Consulting")
    tax_acct = accts.get("tax_liability", "Liabilities:HST Payable")

    with open(journal_file, "w") as f:
        tags = f"invoice:{invoice_num}, client:{project.get('client','')}, project:{project.get('project','')}, entity:{entity_slug}"
        f.write(f"{invoice_date} * Invoice {invoice_num}  ; {tags}\n")
        f.write(f"    {recv_acct:<50} {currency} {grand_total}\n")

        income_total = taxable_subtotal + exempt_subtotal
        f.write(f"    {income_acct:<50} {currency} {-income_total}\n")

        if total_tax > 0:
            f.write(f"    {tax_acct:<50} {currency} {-total_tax}\n")
        f.write("\n")

    # Generate PDF via typst
    template_path = _get_invoice_template(config, entity_slug, project)
    ensure_dir(OUTPUT_DIR)
    pdf_path = OUTPUT_DIR / f"invoice-{invoice_num}.pdf"

    try:
        result = subprocess.run(
            ["typst", "compile", str(template_path), str(pdf_path),
             "--root", str(BASE_DIR),
             "--input", f"data=/build/{invoice_num}.yaml"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"✓ {pdf_path}")
        else:
            print(f"⚠ PDF generation failed: {result.stderr}")
            print(f"  Template data saved to: {build_file}")
    except FileNotFoundError:
        print(f"⚠ typst not found. Template data saved to: {build_file}")

    print(f"✓ {journal_file}")

    # Archive entries
    ensure_dir(BILLED_DIR)
    billed_file = BILLED_DIR / f"{invoice_num}.yaml"
    billed_data = {
        "invoice": invoice_num,
        "entity": entity_slug,
        "client": project.get("client"),
        "project_slug": project_slug,
        "project_name": project.get("project"),
        "date": invoice_date,
        "currency": currency,
        "subtotal": float(taxable_subtotal + exempt_subtotal),
        "tax": float(total_tax),
        "total": float(grand_total),
        "status": "outstanding",
        "payments": [],
        "entries": selected_entries,
    }
    with open(billed_file, "w") as f:
        yaml.dump(billed_data, f, default_flow_style=False, sort_keys=False)

    # Remove invoiced entries from unbilled
    remaining = [e for e in entries if e not in selected_entries]
    _save_unbilled({"entries": remaining})

    # Increment invoice counter
    entity["next_invoice"] = _increment_invoice_number(next_inv)
    save_config(config)

    # Add include to journal file if needed
    journal_path = project.get("journal_file") or entity.get("journal_file")
    if journal_path:
        _ensure_include(expand_path(journal_path), inv_dir)

    print(f"✓ Entries archived to {billed_file}")


# ─── Paid ────────────────────────────────────────────────────────────────────

def cmd_paid(flags, args):
    """Record payment received for an invoice."""
    config = load_config()

    # Find outstanding invoices
    outstanding = []
    if BILLED_DIR.exists():
        for f in sorted(BILLED_DIR.glob("*.yaml")):
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data and data.get("status") != "paid":
                paid_so_far = sum(Decimal(str(p.get("amount", 0))) for p in data.get("payments", []))
                remaining = money(Decimal(str(data["total"])) - paid_so_far)
                if remaining > 0:
                    data["_file"] = f
                    data["_remaining"] = float(remaining)
                    outstanding.append(data)

    if not outstanding:
        print("No outstanding invoices.")
        return

    print("Outstanding invoices:\n")
    for i, inv in enumerate(outstanding, 1):
        days = (date.today() - date.fromisoformat(inv["date"])).days
        remaining = inv["_remaining"]
        total = inv["total"]
        partial = f" (${remaining} remaining)" if remaining != total else ""
        print(f"  {i}. {inv['invoice']:<14} {inv.get('client',''):<25} ${total:>10.2f} {inv.get('currency','CAD')}  ({days} days){partial}")

    print()
    choice = prompt("Which invoice?")
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(outstanding):
            print("Invalid selection.")
            return
    except ValueError:
        print("Invalid selection.")
        return

    inv = outstanding[idx]
    remaining = Decimal(str(inv["_remaining"]))
    currency = inv.get("currency", "CAD")

    pay_date = prompt("Payment date", default=date.today().isoformat(), validator=validate_date)
    pay_amount = prompt("Amount received", default=str(remaining), validator=validate_positive_number)
    pay_amount = Decimal(pay_amount)

    # Get deposit account
    entity_slug = inv.get("entity")
    entity = config.get("entities", {}).get(entity_slug, {})
    accts = entity.get("accounts", {})
    bank_acct = prompt("Deposited to account", default=accts.get("bank", "Assets:Chequing"))

    # Record payment
    inv_file = inv["_file"]
    with open(inv_file) as f:
        inv_data = yaml.safe_load(f)

    inv_data.setdefault("payments", []).append({
        "date": pay_date,
        "amount": float(pay_amount),
    })

    # Check if fully paid
    total_paid = sum(Decimal(str(p["amount"])) for p in inv_data["payments"])
    if total_paid >= Decimal(str(inv_data["total"])):
        inv_data["status"] = "paid"
        inv_data["paid_date"] = pay_date

    with open(inv_file, "w") as f:
        yaml.dump(inv_data, f, default_flow_style=False, sort_keys=False)

    # Write payment journal entry
    recv_acct = f"{accts.get('receivable', 'Assets:Accounts Receivable')}:{inv.get('client', 'Client')}"
    year = pay_date[:4]
    inv_dir = INVOICES_DIR / year
    ensure_dir(inv_dir)
    payment_file = inv_dir / f"{inv['invoice']}-payment.journal"

    # Append (in case of partial payments)
    with open(payment_file, "a") as f:
        f.write(f"{pay_date} * Payment received {inv['invoice']}  ; invoice:{inv['invoice']}, client:{inv.get('client','')}\n")
        f.write(f"    {bank_acct:<50} {currency} {pay_amount}\n")
        f.write(f"    {recv_acct:<50} {currency} {-pay_amount}\n")
        f.write("\n")

    status_msg = "✓ Fully paid" if inv_data["status"] == "paid" else f"  ${money(remaining - pay_amount)} remaining"
    print(f"\n✓ Recorded ${pay_amount} {currency} payment for {inv['invoice']}. {status_msg}")


# ─── Outstanding ─────────────────────────────────────────────────────────────

def cmd_outstanding(flags, args):
    """Show unpaid invoices with aging buckets."""
    if not BILLED_DIR.exists():
        print("No invoices yet.")
        return

    outstanding = []
    for f in sorted(BILLED_DIR.glob("*.yaml")):
        with open(f) as fh:
            data = yaml.safe_load(fh)
        if data and data.get("status") != "paid":
            paid_so_far = sum(Decimal(str(p.get("amount", 0))) for p in data.get("payments", []))
            remaining = money(Decimal(str(data["total"])) - paid_so_far)
            if remaining > 0:
                data["_remaining"] = float(remaining)
                outstanding.append(data)

    if not outstanding:
        print("No outstanding invoices. All paid! 🎉")
        return

    # Aging buckets
    current = []    # 0-30 days
    over_30 = []    # 31-60
    over_60 = []    # 61-90
    over_90 = []    # 90+

    for inv in outstanding:
        days = (date.today() - date.fromisoformat(inv["date"])).days
        inv["_days"] = days
        if days <= 30:
            current.append(inv)
        elif days <= 60:
            over_30.append(inv)
        elif days <= 90:
            over_60.append(inv)
        else:
            over_90.append(inv)

    total_outstanding = sum(Decimal(str(inv["_remaining"])) for inv in outstanding)
    print(f"Outstanding: ${total_outstanding}\n")

    def print_bucket(label, items):
        if not items:
            return
        print(f"  {label}:")
        for inv in items:
            print(f"    {inv['invoice']:<14} {inv.get('client',''):<25} ${inv['_remaining']:>10.2f} {inv.get('currency','CAD')}  ({inv['_days']}d)")
        print()

    print_bucket("Current (0-30 days)", current)
    print_bucket("30+ days", over_30)
    print_bucket("60+ days", over_60)
    print_bucket("90+ days ⚠", over_90)


# ─── Export ──────────────────────────────────────────────────────────────────

def cmd_export(flags, args):
    """Export time entries to CSV."""
    unbilled = _load_unbilled()
    entries = unbilled.get("entries", [])

    # Parse flags from args
    project_filter = None
    from_date = None
    to_date = None
    tag_filter = None
    type_filter = None

    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project_filter = args[i + 1]
            i += 2
        elif args[i] == "--from" and i + 1 < len(args):
            from_date = args[i + 1]
            i += 2
        elif args[i] == "--to" and i + 1 < len(args):
            to_date = args[i + 1]
            i += 2
        elif args[i] == "--tag" and i + 1 < len(args):
            tag_filter = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            type_filter = args[i + 1]
            i += 2
        elif args[i] == "--all":
            # Include billed entries too
            if BILLED_DIR.exists():
                for f in BILLED_DIR.glob("*.yaml"):
                    with open(f) as fh:
                        data = yaml.safe_load(fh)
                    if data and "entries" in data:
                        entries.extend(data["entries"])
            i += 1
        else:
            i += 1

    # Filter
    filtered = entries
    if project_filter:
        filtered = [e for e in filtered if e.get("project") == project_filter]
    if from_date:
        filtered = [e for e in filtered if e.get("date", "") >= from_date]
    if to_date:
        filtered = [e for e in filtered if e.get("date", "") <= to_date]
    if tag_filter:
        filtered = [e for e in filtered if tag_filter in e.get("tags", [])]
    if type_filter:
        filtered = [e for e in filtered if e.get("type", "billable") == type_filter]

    if not filtered:
        print("No entries match filters.")
        return

    # Output CSV
    writer = csv.writer(sys.stdout)
    writer.writerow(["project", "date", "hours", "rate", "amount", "type", "tax", "focus", "tags"])
    for e in sorted(filtered, key=lambda x: (x.get("project", ""), x.get("date", ""))):
        amount = money(Decimal(str(e["hours"])) * Decimal(str(e["rate"])))
        tags = ";".join(e.get("tags", []))
        writer.writerow([
            e.get("project", ""),
            e.get("date", ""),
            e["hours"],
            e["rate"],
            float(amount),
            e.get("type", "billable"),
            e.get("tax", ""),
            e.get("focus", ""),
            tags,
        ])


# ─── Undo ────────────────────────────────────────────────────────────────────

def cmd_undo(flags, args):
    """Remove last time entry."""
    unbilled = _load_unbilled()
    entries = unbilled.get("entries", [])

    if not entries:
        print("No entries to undo.")
        return

    last = entries[-1]
    print(f"Last entry:")
    print(f"  Project: {last.get('project')}")
    print(f"  Date:    {last.get('date')}")
    print(f"  Hours:   {last.get('hours')}")
    print(f"  Focus:   {last.get('focus', '')}")
    print(f"  Type:    {last.get('type', 'billable')}")

    answer = prompt("\nRemove this entry? (y/N)", default="N")
    if answer.lower().startswith("y"):
        entries.pop()
        _save_unbilled(unbilled)
        print("✓ Entry removed.")
    else:
        print("Cancelled.")


# ─── Deferred Revenue ────────────────────────────────────────────────────────

DEFERRED_DIR = BASE_DIR / "deferred"


def _load_deferred(slug):
    """Load a deferred revenue YAML by slug."""
    path = DEFERRED_DIR / f"{slug}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _save_deferred(slug, data):
    """Save a deferred revenue YAML."""
    ensure_dir(DEFERRED_DIR)
    path = DEFERRED_DIR / f"{slug}.yaml"
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _list_deferred():
    """Return list of deferred revenue slugs."""
    ensure_dir(DEFERRED_DIR)
    return sorted([p.stem for p in DEFERRED_DIR.glob("*.yaml")])


def cmd_defer(flags, args):
    """Record a prepayment received (deferred revenue)."""
    from lib.helpers import slugify, save_config, validate_slug

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank_account = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    print("Record deferred revenue (prepayment received)\n")

    description = prompt("Description")
    default_slug = slugify(description)
    slug = prompt("Slug (identifier)", default=default_slug, validator=validate_slug)

    # Check if already exists
    if _load_deferred(slug):
        print(f"  Deferred item '{slug}' already exists.")
        sys.exit(1)

    amount = prompt("Amount", validator=validate_positive_number)
    from_contact = prompt("From (contact slug)", required=False)
    defer_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                        validator=validate_date)
    liability_account = prompt("Liability account",
                               default="Liabilities:Current:Unearned Revenue")

    amount_val = money(amount)

    # Create YAML record
    deferred_data = {
        'name': description,
        'slug': slug,
        'total': float(amount_val),
        'recognized_to_date': 0.0,
        'currency': currency,
        'date': defer_date,
        'from': from_contact or None,
        'accounts': {
            'bank': bank_account,
            'liability': liability_account,
        },
        'recognitions': [],
    }
    _save_deferred(slug, deferred_data)
    print(f"\n  Saved: deferred/{slug}.yaml")

    # Write journal entry: DR Bank, CR Unearned Revenue
    postings = [
        (bank_account, currency, float(amount_val)),
        (liability_account, currency, float(-amount_val)),
    ]

    tags = {
        'pair': '1001',
        'source': f'deferred/{slug}.yaml',
    }

    entry = format_entry(defer_date, f"Deferred revenue: {description}", postings, tags)

    year = defer_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "revenue.journal"
    append_journal(journal_path, entry)

    print(f"  Journal entry written to generated/{year}/revenue.journal")
    print(f"  Total deferred: {currency} {amount_val:,.2f}")


def cmd_recognize(flags, args):
    """Recognize a portion of deferred revenue."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')

    # Get slug from args or prompt
    slug = args[0] if args else None
    if not slug:
        # List available deferred items
        slugs = _list_deferred()
        if not slugs:
            print("No deferred revenue items found. Use 'pair revenue defer' first.")
            return
        print("Deferred revenue items:")
        for s in slugs:
            d = _load_deferred(s)
            if d:
                remaining = Decimal(str(d['total'])) - Decimal(str(d['recognized_to_date']))
                print(f"  {s:<25} remaining: {d['currency']} {remaining:,.2f}")
        print()
        slug = prompt("Slug to recognize")

    deferred = _load_deferred(slug)
    if not deferred:
        print(f"Deferred item '{slug}' not found.")
        sys.exit(1)

    total = Decimal(str(deferred['total']))
    recognized = Decimal(str(deferred['recognized_to_date']))
    remaining = total - recognized

    if remaining <= 0:
        print(f"  '{slug}' is fully recognized. No remaining balance.")
        return

    print(f"\n  {deferred['name']}")
    print(f"  Total: {deferred['currency']} {total:,.2f}")
    print(f"  Recognized: {deferred['currency']} {recognized:,.2f}")
    print(f"  Remaining: {deferred['currency']} {remaining:,.2f}\n")

    amount = prompt("Amount to recognize", validator=validate_positive_number)
    amount_val = money(amount)

    if amount_val > remaining:
        print(f"  Cannot recognize more than remaining balance ({deferred['currency']} {remaining:,.2f}).")
        sys.exit(1)

    recognize_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                            validator=validate_date)

    # Update YAML
    deferred['recognized_to_date'] = float(recognized + amount_val)
    if 'recognitions' not in deferred:
        deferred['recognitions'] = []
    deferred['recognitions'].append({
        'date': recognize_date,
        'amount': float(amount_val),
    })
    _save_deferred(slug, deferred)

    # Write journal entry: DR Unearned Revenue, CR Income:Operating
    liability_account = deferred['accounts']['liability']
    income_account = 'Income:Operating:Consulting'

    postings = [
        (liability_account, deferred['currency'], float(amount_val)),
        (income_account, deferred['currency'], float(-amount_val)),
    ]

    tags = {
        'pair': '0110',
        'source': f'deferred/{slug}.yaml',
    }

    entry = format_entry(recognize_date, f"Recognize revenue: {deferred['name']}", postings, tags)

    year = recognize_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "revenue.journal"
    append_journal(journal_path, entry)

    new_remaining = remaining - amount_val
    print(f"\n  Recognized: {deferred['currency']} {amount_val:,.2f}")
    print(f"  Remaining:  {deferred['currency']} {new_remaining:,.2f}")
    print(f"  Written to: generated/{year}/revenue.journal")


def cmd_deferred(flags, args):
    """List all deferred revenue items with status."""
    config = load_config()

    slugs = _list_deferred()
    if not slugs:
        print("No deferred revenue items. Use 'pair revenue defer' to create one.")
        return

    print(f"\n{'Name':<30} {'Total':>12} {'Recognized':>12} {'Remaining':>12}")
    print("─" * 70)

    grand_total = Decimal('0')
    grand_recognized = Decimal('0')
    grand_remaining = Decimal('0')

    for slug in slugs:
        d = _load_deferred(slug)
        if not d:
            continue
        total = Decimal(str(d['total']))
        recognized = Decimal(str(d['recognized_to_date']))
        remaining = total - recognized
        currency = d.get('currency', 'CAD')

        name_display = d['name'][:28] if len(d['name']) > 28 else d['name']
        print(f"  {name_display:<28} {currency} {total:>9,.2f}"
              f"  {currency} {recognized:>9,.2f}"
              f"  {currency} {remaining:>9,.2f}")

        grand_total += total
        grand_recognized += recognized
        grand_remaining += remaining

    print("─" * 70)
    cur = d.get('currency', 'CAD') if d else 'CAD'
    print(f"  {'TOTAL':<28} {cur} {grand_total:>9,.2f}"
          f"  {cur} {grand_recognized:>9,.2f}"
          f"  {cur} {grand_remaining:>9,.2f}")
    print()
