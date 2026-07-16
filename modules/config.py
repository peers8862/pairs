"""Configuration viewer and editor for pair."""

import sys
import yaml

from lib.helpers import (
    load_config,
    save_config,
    prompt,
    prompt_choice,
    confirm,
    parse_global_flags,
)


# ─── Tag keys and defaults ───────────────────────────────────────────────────

DEFAULT_TAGS = {
    "pair": True,
    "source": True,
    "division": True,
    "category": True,
    "seq": True,
    "period": True,
}

STYLE_REVENUE_CHOICES = ["invoice", "simple"]


# ─── Display ─────────────────────────────────────────────────────────────────

def _print_config(config):
    """Print config.yaml contents in a readable format."""
    print()
    print("══════════════════════════════════════════════════════════════")
    print("  Configuration — config.yaml")
    print("══════════════════════════════════════════════════════════════")
    print()

    company = config.get("pair", {})
    print(f"  Company name:     {company.get('name', '—')}")
    print(f"  Slug:             {company.get('slug', '—')}")
    print(f"  Currency:         {company.get('currency', '—')}")
    print()

    print(f"  Journal file:     {config.get('journal_file', '—')}")
    print()

    accounts = config.get("accounts", {})
    print("  Accounts:")
    print(f"    Bank:           {accounts.get('bank', '—')}")
    print(f"    Receivable:     {accounts.get('receivable', '—')}")
    print(f"    Payable:        {accounts.get('payable', '—')}")
    print()

    defaults = config.get("defaults", {})
    print(f"  Fiscal year start: month {defaults.get('fiscal_year_start', 1)}")
    print()

    divisions = config.get("divisions", [])
    if divisions:
        print(f"  Divisions:        {', '.join(divisions)}")
    else:
        print("  Divisions:        (none)")
    print()

    tags = config.get("tags", DEFAULT_TAGS)
    print("  Tags:")
    for key, enabled in tags.items():
        status = "on" if enabled else "off"
        print(f"    {key:<12}    {status}")
    print()

    style = config.get("style", {})
    print(f"  Style:")
    print(f"    Revenue:        {style.get('revenue', 'invoice')}")
    print()
    print("══════════════════════════════════════════════════════════════")
    print()


# ─── Editor ──────────────────────────────────────────────────────────────────

def _edit_config(config):
    """Walk through editable fields and update config in place."""
    print("\nEditing configuration (press Enter to keep current value):\n")

    # Company name
    company = config.setdefault("pair", {})
    company["name"] = prompt(
        "Company name",
        default=company.get("name", ""),
    )

    # Currency
    company["currency"] = prompt(
        "Currency",
        default=company.get("currency", "CAD"),
    )

    # Journal file
    config["journal_file"] = prompt(
        "Journal file",
        default=config.get("journal_file", "~/.hledger.journal"),
    )

    # Bank account
    accounts = config.setdefault("accounts", {})
    accounts["bank"] = prompt(
        "Bank account",
        default=accounts.get("bank", "Assets:Current:Chequing"),
    )

    # Divisions
    divisions = config.get("divisions", [])
    current_div_str = ", ".join(divisions) if divisions else ""
    div_input = prompt(
        "Divisions (comma-separated, or blank for none)",
        default=current_div_str,
        required=False,
    )
    if div_input:
        config["divisions"] = [d.strip() for d in div_input.split(",") if d.strip()]
    else:
        config["divisions"] = []

    # Tags on/off
    print("\nTags (enable/disable per tag):")
    tags = config.get("tags", dict(DEFAULT_TAGS))
    for key in DEFAULT_TAGS:
        current = tags.get(key, True)
        current_str = "on" if current else "off"
        choice = prompt_choice(
            f"  Tag '{key}' (currently {current_str})",
            ["on", "off"],
            default="on" if current else "off",
        )
        tags[key] = (choice == "on")
    config["tags"] = tags

    # Revenue style
    style = config.setdefault("style", {})
    current_revenue = style.get("revenue", "invoice")
    style["revenue"] = prompt_choice(
        "Revenue style",
        STYLE_REVENUE_CHOICES,
        default=current_revenue,
    )

    return config


# ─── Command entry point ─────────────────────────────────────────────────────

def cmd_config(args):
    """Handle 'pair config' command.

    With no args: display config and offer to edit.
    """
    flags, remaining = parse_global_flags(args)

    if flags["help"]:
        print("Usage: pair config")
        print()
        print("View and edit project configuration.")
        print()
        print("Displays current config.yaml and prompts to edit.")
        sys.exit(0)

    config = load_config()
    _print_config(config)

    if flags["batch"]:
        # Non-interactive mode — just display
        return

    if confirm("Edit?", default_yes=False):
        config = _edit_config(config)
        save_config(config)
        print("\n✓ Configuration saved.")
    else:
        print("No changes.")
