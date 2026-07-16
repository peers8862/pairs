# Install & Launch

## Prerequisites

- Python 3.8+
- PyYAML: `pip install pyyaml`
- hledger: https://hledger.org/install.html

## Install

```bash
cd ~/making/hledger-company
chmod +x pair
```

Option A — symlink into PATH:
```bash
ln -s "$(pwd)/pair" ~/.local/bin/pair
ln -s "$(pwd)/pairs" ~/.local/bin/pairs
```

Option B — alias in your shell rc:
```bash
alias company='~/making/hledger-company/company'
```

## First run

```bash
pair init
```

Follow the prompts. Then add the include line it gives you to your main hledger journal.

## Verify

```bash
pair --help       # see all commands
pair worth        # net worth (will be $0 until you add data)
pair asset add    # record your first asset
```

## Daily use

```bash
pair asset amort              # extend amortization entries
pair liability payments       # extend loan payment entries
pair expense add              # record an expense
pair revenue log              # log billable time
pair worth                    # check net worth
```
