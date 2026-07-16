# Install & Launch

## Prerequisites

- Python 3.8+
- PyYAML: `pip install pyyaml`
- hledger: https://hledger.org/install.html

## Install

```bash
cd ~/making/hledger-company
chmod +x company
```

Option A — symlink into PATH:
```bash
ln -s "$(pwd)/company" ~/.local/bin/company
```

Option B — alias in your shell rc:
```bash
alias company='~/making/hledger-company/company'
```

## First run

```bash
company init
```

Follow the prompts. Then add the include line it gives you to your main hledger journal.

## Verify

```bash
company --help       # see all commands
company worth        # net worth (will be $0 until you add data)
company asset add    # record your first asset
```

## Daily use

```bash
company asset amort              # extend amortization entries
company liability payments       # extend loan payment entries
company expense add              # record an expense
company revenue log              # log billable time
company worth                    # check net worth
```
