# Market Alerts

Price drop alerts based on previous close. Get notified when a tracked commodity falls X% from its last closing price at any point during the following trading day.

## Watchlist Concept

There is no separate "watchlist" data structure. The existing `market.commodities` list in your entity config is already a pure tracking registry — it records what you want price data for, with no implication of ownership.

You can alert on any commodity:
- Ones you hold (tracked because they're in your portfolio)
- Ones you're watching (tracked just for alerts/charts, no purchase)

When you `pair market alert add` for a symbol not yet in your commodities list, the tool offers to register it on the spot. This adds it to `market.commodities` (so prices can be fetched) without any accounting entry.

---

## Commands

```
pair market alert add [SYMBOL]       Add a new alert (inline or interactive)
pair market alert list               List all active alerts
pair market alert remove [SYMBOL]    Remove an alert
pair market alert check [SYMBOL]     One-shot check (all or specific)
pair market alert check --loop       Poll until market close
pair market alert check --tag TAG    Check only alerts with tag
pair market alert check --group NAME Check only alerts in group
```

### Inline vs Interactive

```bash
# Inline (direct citation)
pair market alert add SHOP.TO --threshold 3 --tag tech-stocks

# Interactive (pick from configured commodities list)
pair market alert add
```

Both paths supported everywhere: specify symbol inline or omit to choose from a list.

---

## Configuration

Stored in entity `config.yaml` under `market.alerts`:

```yaml
market:
  commodities:
    - symbol: SHOP.TO
      name: Shopify Inc
      source: yahoo
      fetch_pair: SHOP.TO
      currency: CAD

  alerts:
    defaults:
      interval: 5m           # check frequency
      source: yfinance       # price source for live quotes
      notify: desktop        # desktop | terminal | both

    groups:
      - name: tech-stocks
        tags: [equity, tsx]
        interval: 5m
        symbols: [SHOP.TO, APPL]
      - name: crypto
        tags: [crypto]
        interval: 1m
        source: yfinance
        symbols: [BTC]
      - name: fx
        tags: [currency]
        interval: 15m
        symbols: [USD]

    rules:
      - symbol: SHOP.TO
        type: drop_from_close
        threshold: 3.0
        tags: [tech-stocks, equity]
      - symbol: BTC
        type: drop_from_close
        threshold: 5.0
        tags: [crypto]
        interval: 1m          # per-rule override
      - symbol: USD
        type: drop_from_close
        threshold: 1.0
        tags: [fx]
```

### Hierarchy

Interval and source resolve in order: rule > group > defaults.

---

## How It Works

1. **Previous close**: most recent P directive in `prices.journal` dated before today
2. **Live price**: fetched via configured source (yfinance by default)
3. **Compare**: `(close - current) / close * 100`
4. **Alert**: if drop >= threshold, trigger notification

### Execution Modes

| Mode | Usage |
|------|-------|
| One-shot | `pair market alert check` — runs once, exits |
| Loop | `pair market alert check --loop --interval 5` — polls every N minutes |
| Cron | `*/5 9-16 * * 1-5 pair market alert check` — external scheduling |

### Notification

| Method | Mechanism |
|--------|-----------|
| `terminal` | Colored output to stdout |
| `desktop` | `notify-send` (Linux) |
| `both` | Both of the above |

---

## Filtering

```bash
# By tag
pair market alert check --tag crypto
pair market alert list --tag equity

# By group
pair market alert check --group tech-stocks

# By symbol (direct)
pair market alert check SHOP.TO BTC
```

Tags and groups allow flexible slicing. A symbol can belong to multiple tags. Groups define a named collection with shared defaults.

---

## Data Sources

### Primary: yfinance (recommended default)

- **Cost**: Free, no API key required
- **Coverage**: Stocks (NYSE, TSX, global), crypto, FX
- **Intervals**: 1-minute bars available (last 7 days of history)
- **Rate limit**: ~360 requests/hour (unofficial, recently tightened)
- **Risk**: Unofficial API; Yahoo can throttle or break without notice
- **Install**: `pip install yfinance`
- **Batch support**: Yes — one call can fetch multiple tickers

For a small watchlist (4-10 symbols), per-minute polling is well within limits.

### Secondary: pricehist (already installed)

- **Cost**: Free, no API key
- **Coverage**: Depends on source backend (yahoo, bankofcanada, ecb, coinbasepro)
- **Intervals**: Daily only (end-of-day close prices)
- **Use case**: Historical price fills, not real-time alerts
- **Already used by**: `pair market fetch`

### Evaluated and not selected: Twelve Data

twelvedata.com — commercial financial data API (Singapore, 5+ years).

**Free tier (Basic plan):**
- 8 API credits per minute (resets each minute)
- 800 requests per day hard cap
- Only 3 exchanges on free tier: US equities, forex, crypto
- WebSocket: 8 trial credits (effectively unusable)
- Requires free API key signup

**Why not suitable for this project:**
- TSX not available on free tier — SHOP.TO requires Grow plan at $79/mo USD
- Adds key management complexity with no benefit over yfinance
- 8 req/min is tight for multi-symbol polling
- WebSocket (push-based real-time) locked behind paid plans
- No advantage over yfinance for the same asset coverage

**Could revisit if:**
- yfinance becomes permanently unreliable
- Project moves to paid data sources
- Need for institutional-grade SLA

### Crypto-specific alternatives (future)

| Source | Free Tier | Auth | Notes |
|--------|-----------|------|-------|
| CoinGecko | 10,000 calls/month, 100/min | Demo key | Broad crypto coverage |
| Binance | 1,200 req/min | None | Best rate limits, crypto only |
| CoinMarketCap | 15,000 credits/month, 50/min | Free key | Also has keyless public API |
| Coinpaprika | 1,000 req/day | None | Simple, no signup |

These can be added as per-commodity source options if yfinance proves unreliable for crypto.

---

## Granularity Limits

| Asset Type | Min Practical Interval | Source | Notes |
|------------|----------------------|--------|-------|
| Stocks (TSX/NYSE) | 1 minute | yfinance | Near-real-time via Yahoo |
| Crypto | 1 minute or less | yfinance / Binance | Markets never close |
| FX | 1 minute | yfinance | Moves slowly; 15m practical |
| Sub-minute (tick) | Not available free | Paid L1/L2 feeds | Out of scope |

Interval is configurable per-commodity, per-group, or per-alert-rule.

---

## Dependencies

For alert functionality:
- `yfinance` — `pip install yfinance`
- `notify-send` — pre-installed on most Linux desktops (libnotify)

No API keys needed for default configuration.
