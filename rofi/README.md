# pair-rofi

Near-fullscreen rofi overlay for the Pairs accounting tool. Press one key to access your entire ledger system.

## Install

```bash
# Symlink into PATH
ln -s "$(pwd)/pair-rofi" ~/.local/bin/pair-rofi

# Copy theme
mkdir -p ~/.config/pair-rofi
cp ledger.rasi ~/.config/pair-rofi/
```

## Keybind

Add to your window manager config:

**i3 / sway:**
```
bindsym $mod+p exec pair-rofi
```

**Other WMs:**
Bind `pair-rofi` to your preferred key combo.

## Requirements

- rofi 1.7+
- python3 (for pair commands)
- A terminal emulator (xterm by default, set `$TERMINAL` to override)

## Configuration

Set environment variables or edit the script header:

```bash
export TERMINAL="alacritty -e"   # your terminal
```

## Keybinds within the overlay

| Key | Action |
|-----|--------|
| Enter | Select / drill down |
| Ctrl+Enter | Open in terminal |
| Escape | Back / close |
| Type | Filter list |
| Ctrl+X | Quick expense (from anywhere) |

## Theme

The `ledger.rasi` theme gives a near-fullscreen dark monospace look. Edit to taste.
