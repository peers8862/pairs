"""Journal file management for hledger-company."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

from lib.helpers import BASE_DIR, ensure_dir, load_config


GENERATED_DIR = BASE_DIR / "generated"
JOURNAL_DIR = BASE_DIR / "journal"
INCLUDE_DIR = BASE_DIR / "include"


# ─── Tag management ──────────────────────────────────────────────────────────

def _tag_enabled(key):
    """Check if a tag key is enabled in config.yaml.

    If the tags: section is missing from config, all tags are enabled.
    If the section exists, a tag is enabled if its key is True or absent.
    """
    from lib.helpers import CONFIG_FILE
    import yaml
    if not CONFIG_FILE.exists():
        return True
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return True
    tags_section = config.get("tags")
    if tags_section is None:
        return True
    return tags_section.get(key, True)


def build_tags(pair, source=None, division=None, **extra):
    """Build a tag dict for a journal entry, respecting config.

    Args:
        pair: str — required BitLedger pair code (e.g. 'AE', 'AL')
        source: str or None — source module/file that generated this entry
        division: str or None — business division
        **extra: additional tag key=value pairs (e.g. category, seq, period)

    Returns:
        dict of tag_key: tag_value for all enabled tags that have values.
    """
    # Collect all candidate tags
    candidates = {"pair": pair}
    if source is not None:
        candidates["source"] = source
    if division is not None:
        candidates["division"] = division
    candidates.update(extra)

    # Filter to only enabled tags with non-None values
    return {
        k: v for k, v in candidates.items()
        if v is not None and _tag_enabled(k)
    }


# ─── Generated file header ───────────────────────────────────────────────────

def generated_header(source_desc, regenerate_cmd):
    """Return the standard header for generated journal files."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return (
        f"; ══════════════════════════════════════════════════════════════\n"
        f"; GENERATED — do not edit manually\n"
        f"; Source: {source_desc}\n"
        f"; Regenerate: {regenerate_cmd}\n"
        f"; Last generated: {now}\n"
        f"; ══════════════════════════════════════════════════════════════\n"
        f"\n"
    )


# ─── Atomic file writing ─────────────────────────────────────────────────────

def write_journal_atomic(path, content):
    """Write content to path atomically (write tmp, then rename)."""
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.journal.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def append_journal(path, entry):
    """Append a journal entry to a file, creating it if needed."""
    path = Path(path)
    ensure_dir(path.parent)
    with open(path, 'a') as f:
        f.write(entry)
        if not entry.endswith('\n'):
            f.write('\n')


# ─── Journal entry formatting ────────────────────────────────────────────────

def format_entry(date, description, postings, tags=None):
    """Format a single hledger journal entry.

    Args:
        date: str YYYY-MM-DD
        description: str transaction description
        postings: list of (account, currency, amount) tuples
        tags: dict of tag key:value pairs (optional)

    Returns:
        str: formatted journal entry with trailing newline
    """
    tag_str = ""
    if tags:
        pairs = [f"{k}:{v}" for k, v in tags.items()]
        tag_str = "  ; " + ", ".join(pairs)

    lines = [f"{date} * {description}{tag_str}"]

    for account, currency, amount in postings:
        # Right-align amount at column 56
        amount_str = f"{currency} {amount:.2f}" if amount >= 0 else f"{currency} {amount:.2f}"
        padding = max(1, 52 - len(account))
        lines.append(f"    {account}{' ' * padding}{amount_str}")

    lines.append("")  # blank line after entry
    return "\n".join(lines) + "\n"


# ─── Include chain management ────────────────────────────────────────────────

def ensure_year_structure(year):
    """Create year directories and aggregator if they don't exist."""
    year_str = str(year)

    # Create directories
    ensure_dir(GENERATED_DIR / year_str)
    ensure_dir(JOURNAL_DIR / year_str)

    # Create year aggregator in include/ if missing
    year_include = INCLUDE_DIR / f"{year_str}.journal"
    if not year_include.exists():
        ensure_dir(INCLUDE_DIR)
        content = (
            f"; Year {year_str} — managed by 'company' tool\n"
            f"\n"
            f"; User-editable journals\n"
            f"include ../journal/{year_str}/opening.journal\n"
            f"include ../journal/{year_str}/adjustments.journal\n"
            f"\n"
            f"; Generated journals (do not edit)\n"
            f"include ../generated/{year_str}/amortization.journal\n"
            f"include ../generated/{year_str}/loan-payments.journal\n"
            f"include ../generated/{year_str}/expenses.journal\n"
            f"include ../generated/{year_str}/assets.journal\n"
            f"include ../generated/{year_str}/payroll.journal\n"
            f"include ../generated/{year_str}/revenue.journal\n"
            f"\n"
            f"; Invoices\n"
            f"include ../invoices/{year_str}-*.journal\n"
        )
        write_journal_atomic(year_include, content)

        # Create empty user journals so includes don't error
        for name in ('opening', 'adjustments'):
            jpath = JOURNAL_DIR / year_str / f"{name}.journal"
            if not jpath.exists():
                write_journal_atomic(jpath, f"; {name.title()} entries for {year_str}\n\n")

        # Create empty generated journals so includes don't error
        for name in ('amortization', 'loan-payments', 'expenses', 'assets', 'payroll', 'revenue'):
            gpath = GENERATED_DIR / year_str / f"{name}.journal"
            if not gpath.exists():
                write_journal_atomic(gpath, "")

    # Update company.journal to include this year
    update_company_journal()


def update_company_journal():
    """Rebuild include/company.journal from existing year files."""
    ensure_dir(INCLUDE_DIR)
    company_journal = INCLUDE_DIR / "company.journal"

    # Find all year includes
    years = sorted([
        f.stem for f in INCLUDE_DIR.glob("*.journal")
        if f.stem.isdigit()
    ])

    lines = [
        "; hledger-company — managed by 'company' tool\n",
        "; Do not edit manually. Run 'company generate' to rebuild.\n",
        "\n",
        "include accounts.journal\n",
    ]
    for year in years:
        lines.append(f"include {year}.journal\n")

    write_journal_atomic(company_journal, "".join(lines))
