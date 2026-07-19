# pair-rofi — Full Specification

## Design Intent

A near-fullscreen overlay that feels like switching to a dedicated accounting terminal — not a popup, not a dialog. Press the keybind and the screen transforms into the ledger system. Press Escape and you're back to whatever you were doing.

Mid-80s mainframe aesthetic. Monospace. Minimal. Fast. Like accessing a financial system on a dumb terminal.

## Visual Design

### Screen Layout (1366x768 example)

```
┌─ 2px border ──────────────────────────────────────────────────────────────────────────────┐
│ 20px padding                                                                               │
│                                                                                            │
│   PAIRS ─── Babb ─── [Current View]                         Esc: back   ?: keybinds       │
│   ────────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                            │
│   [MESSAGE AREA — command output, reports, reference tables]                               │
│   (takes up most of the screen)                                                            │
│   (content from pair commands rendered here)                                               │
│                                                                                            │
│                                                                                            │
│                                                                                            │
│                                                                                            │
│                                                                                            │
│                                                                                            │
│   ────────────────────────────────────────────────────────────────────────────────────────  │
│   > Back                                                                                   │
│     [Action 1]                                                                             │
│     [Action 2]                                                                             │
│     [Action 3]                                                                             │
│   ────────────────────────────────────────────────────────────────────────────────────────  │
│   Enter: select   Ctrl+E: edit   Ctrl+D: delete   Ctrl+N: new   Shift+Enter: copy         │
│                                                                                            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Dimensions

- Window: 95% width, 90% height, centered
- Outer padding: 20px all sides
- Message area: dynamic height (fills available space)
- List area: 8-12 lines (context-dependent)
- Font: monospace 11pt (system default, or Terminus, or Fixed)

### Color Palette

```
Background:        #0a0a0a (near-black)
Surface:           #111111 (slightly lighter — header/footer)
Border:            #333333 (visible but subtle)
Text primary:      #b0b0b0 (light gray)
Text dimmed:       #666666 (headers, hints)
Text bright:       #ffffff (selected item, emphasis)
Selection bg:      #1a1a1a (barely lighter)
Selection border:  #555555 (left accent on selected)
Alert:             #aa4444 (budget overrun, expiry warning)
```

No greens, blues, or accent colors. Strictly grayscale with a single muted red for warnings.

## Keybinds

### Navigation

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move through list items |
| Page Up / Page Down | Jump list by page |
| Home / End | First / last item |
| Escape | Back one level (or close if at root) |
| Backspace | Back one level (when input is empty) |
| / or typing | Filter current list |

### Actions on selected item

| Key | Exit Code | Action |
|-----|-----------|--------|
| Enter | 0 | Primary action (drill down / view in rofi) |
| Ctrl+Enter | 10 | Open in terminal (scrollable, editable) |
| Shift+Enter | 11 | Copy value to clipboard |
| Ctrl+E | 12 | Edit selected item |
| Ctrl+D | 13 | Delete selected item (with confirmation) |
| Ctrl+N | 14 | New / Add in current context |
| Ctrl+R | 15 | Refresh current view |
| Ctrl+S | 16 | Export / save current view to file |
| Ctrl+X | 17 | Quick expense (from anywhere) |
| ? | 18 | Show keybind help |
| Tab | 19 | Toggle preview (details in message area) |

### Global shortcuts (available from any level)

| Key | Action |
|-----|--------|
| Ctrl+W | Jump to Net Worth |
| Ctrl+B | Jump to Budget |
| Ctrl+P | Jump to Pairs Reference |
| Ctrl+X | Quick Expense entry |
| Ctrl+T | Quick Transfer |

## Menu Structure

### Level 0 — Root

```
RECENT ─────────────────────────────
  [last action 1]
  [last action 2]
  [last action 3]
────────────────────────────────────
ACTIONS ────────────────────────────
  New Entry (pair)
  Quick Expense
  Quick Transfer
  Net Worth
────────────────────────────────────
MODULES ────────────────────────────
  Assets
  Liabilities
  Expenses
  Income
  Revenue
  Budget
────────────────────────────────────
MANAGEMENT ─────────────────────────
  Contacts
  Contracts
  Payroll
  Tax
  Recurring
────────────────────────────────────
SYSTEM ─────────────────────────────
  Pairs Reference
  Switch Entity [babb]
  Status
  Config
  Generate
```

### Level 1 — Module menus

Each module shows its actions. Examples:

**Assets:**
```
msg: "4 active assets | Total NBV: $30,626"

  Add asset
  List all
  Summary (by category)
  ──────────────
  Show asset...
  Edit asset...
  Amortize all
  Dispose...
  Write down...
```

**Budget:**
```
msg: "Active: 2026 Operating Budget | 3 scenarios"

  Create budget
  List budgets
  Show budget...
  Edit budget...
  ──────────────
  Budget vs Actual
  Budget vs Actual (YTD)
  Forecast
  Compare budgets
  ──────────────
  Activate...
  Remove...
```

**Liabilities:**
```
msg: "2 active | Total owing: $27,080"

  Add liability
  List all
  ──────────────
  Record payment...
  Generate payments
  Reclassify...
  ──────────────
  Show...
```

### Level 2 — Entity selection

When an action needs a specific entity, show the list with useful info:

**Select asset:**
```
msg: "Select an asset"

  macbook-pro-16    MacBook Pro 16"         NBV: $2,365    42mo left
  delivery-van      Delivery Van            NBV: $28,262   59mo left
  standing-desk     Standing Desk           NBV: $1,030    104mo left
```

**Select liability:**
```
msg: "Select a liability"

  vehicle-loan      Vehicle Loan            $19,280 remaining
  credit-line       Business Credit Line    $7,800 remaining
```

### Level 3 — Detail view (output in message area)

After selecting an entity, show its details in the message area with actions below:

```
msg:
  MacBook Pro 16"
  ──────────────────────────────────────────
  Category:     equipment
  Purchase:     2025-01-15
  Cost:         $4,299.00
  NBV:          $2,364.68
  Remaining:    42 months
  Method:       straight-line

list:
  > Back
    Edit
    Show schedule
    Dispose
    Write down
    Open in terminal
```

## Special Flows

### Quick Expense (rofi-native, no terminal)

Chained prompts within rofi:

```
Step 1: prompt "Description:" → user types "Staples office supplies"
Step 2: list of categories → user picks "office"
Step 3: prompt "Amount:" → user types "147.50"
Step 4: prompt "Date [2026-07-16]:" → user hits enter
Step 5: executes pair expense add --batch ...
Step 6: msg "✓ Recorded: Staples office supplies — $147.50 (office)"
         list: [Record another] [Back to menu]
```

### Quick Transfer (rofi-native)

```
Step 1: list "From account:" → picks "Chequing"
Step 2: list "To account:" → picks "Savings"  
Step 3: prompt "Amount:" → "5000"
Step 4: prompt "Date [today]:" → enter
Step 5: executes pair transfer --batch ...
Step 6: msg "✓ Transferred: $5,000 Chequing → Savings"
```

### New Entry (pair selector)

```
Step 1: show 14 pairs list
Step 2: user picks one (or types to filter)
Step 3: show direction choice (Normal / Reversal)
Step 4: opens terminal with pair entry pre-loaded
```

### Entity Switch

```
msg: "Active entity: Babb"

list:
  clairlea    Clairlea Consulting
  babb        Babb ✓
  rental      Rental Corp

→ User picks clairlea
→ Executes pair switch clairlea
→ msg updates: "Switched to: Clairlea Consulting"
→ Header updates: "PAIRS ─── Clairlea ─── ..."
```

### Calculator Mode

When input starts with `=`, evaluate as math:

```
input: = 4299 / 60
msg: "71.65"

input: = 12000 * 0.13
msg: "1560.00"
```

Useful for quick amount calculations before entering them.

### Inline Budget Editing

From budget show view, Ctrl+E on a line:

```
msg: (budget table displayed)

User arrows to "Payroll" line, hits Ctrl+E
→ prompt: "Payroll [$4,500/mo]:" 
→ user types "6000"
→ budget updated inline
→ msg refreshes to show new table
```

## Notification Indicators

The root menu shows contextual alerts without being asked:

```
  Budget                    ⚠ 2 lines over budget
  Contracts                 ⚠ 1 expiring in 14 days
  Tax                       ● Q3 remittance due
  Recurring                 3 entries pending
```

These are computed on menu load by running quick checks against the data.

## History / Recent Actions

Top of root menu shows last 3-5 actions (stored in a small cache file):

```
RECENT ─────────────────────────────
  Expense: GitHub Teams — $25 (2min ago)
  Asset show: macbook-pro-16 (1hr ago)
  Worth (yesterday)
```

Selecting a recent action repeats it (or views it).

## Bookmarks

User can pin views to the root menu:

```
pair-rofi bookmark "Budget vs Actual YTD"
pair-rofi bookmark "Worth --detail"
```

Shows as a BOOKMARKS section in root menu. Stored in a config file.

## Terminal Launch Behavior

When opening a terminal for interactive commands:

- Use configured terminal: `$TERMINAL -e "pair asset add"`
- Terminal stays open after command (hold mode) so user sees output
- Terminal title set to the command: `"pair — asset add"`
- Terminal size: 100x30 (reasonable for our output widths)
- After terminal closes, rofi can optionally re-launch (configurable)

## Preview via Tab

Pressing Tab on a list item shows its details in the message area without leaving the list:

```
list:
  macbook-pro-16 ←──── Tab pressed on this
  delivery-van
  standing-desk

msg: (updates live to show macbook-pro details)
  MacBook Pro 16"
  Cost: $4,299  NBV: $2,365  Method: straight-line
  Purchase: 2025-01-15  Remaining: 42mo
```

Arrow to next item, Tab again — preview updates. Fast browsing without drilling down.

## Config File

```bash
# ~/.config/pair-rofi/config
PAIR_CMD="/home/morgen/making/pairs/pair"
TERMINAL="xterm -hold -e"
THEME="$HOME/.config/pair-rofi/ledger.rasi"
RECENT_FILE="$HOME/.config/pair-rofi/recent"
BOOKMARKS_FILE="$HOME/.config/pair-rofi/bookmarks"
RELAUNCH_AFTER_TERMINAL=true
CALCULATOR_ENABLED=true
NOTIFICATIONS_ENABLED=true
```

## File Structure

```
pairs/
└── rofi/
    ├── pair-rofi           # main launcher script (bash)
    ├── ledger.rasi         # rofi theme file
    ├── config.example      # config template
    ├── SPEC.md             # this file
    └── README.md           # install + keybind instructions
```

## Implementation Notes

- Script is bash (~200-300 lines)
- Each "screen" is a function that constructs mesg + list and calls rofi
- Exit codes from keybinds determine what happens next (loop structure)
- Entity lists fetched via `pair <module> list --format csv` (already supported for assets)
- Need to add `--format csv` to other list commands for rofi integration
- Recent history stored as a simple line-per-entry file (last 10)
- Notifications computed on root menu load (adds ~100ms — acceptable)
- Calculator uses `bc` or python eval

## Open Decisions Resolved

1. **Width:** Near-fullscreen (95% x 90%), adaptive only if needed for very small screens
2. **Long output:** Displayed in message area. For truly long content, "Open in terminal" action
3. **Tax in quick expense:** Yes, if entity config has tax > 0, add one HST prompt step
4. **Ctrl+Enter:** Opens in terminal — confirmed
5. **Paging:** Not needed — message area scrolls in newer rofi versions, or we truncate + offer terminal view
