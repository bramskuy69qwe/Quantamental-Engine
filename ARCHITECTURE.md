# Quantamental Engine v2.1 — Architecture

Pre-trade risk gatekeeper + post-trade logger for discretionary crypto futures trading on Binance USD-M perpetuals.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, asyncio |
| Frontend | Jinja2 + HTMX (server-rendered HTML fragments) |
| Database | SQLite (aiosqlite, WAL mode) |
| Exchange | Binance via ccxt + native WebSocket |
| Macro data | yfinance (VIX), FRED API (yields, spreads) |
| Broker bridge | Quantower C# plugin via WebSocket |
| PWA | manifest.json + service worker |

## Directory Layout

```
.
├── main.py                    # FastAPI entry point, lifespan, app creation (~110 lines)
├── config.py                  # All configuration constants, env vars
├── requirements.txt           # Dependencies (pinned ranges)
│
├── api/                       # FastAPI route handlers (all return Jinja2 HTML for HTMX)
│   ├── router.py              # Combines all domain sub-routers
│   ├── helpers.py             # Shared: templates, _fmt, _ctx, _paginate_list
│   ├── cache.py               # Mutable caching: equity backfill, funding rates
│   ├── routes_dashboard.py    # /, /fragments/dashboard/*
│   ├── routes_calculator.py   # /calculator, risk sizing
│   ├── routes_history.py      # /history, trade logs
│   ├── routes_params.py       # /params, risk parameter editor
│   ├── routes_analytics.py    # /analytics, PnL analysis
│   ├── routes_accounts.py     # /accounts, multi-account management
│   ├── routes_backtest.py     # /backtest, historical replay
│   ├── routes_regime.py       # /regime, macro classifier
│   ├── routes_platform.py     # /ws/platform, Quantower bridge endpoints
│   ├── routes_models.py       # /api/models
│   └── routes_news.py         # /api/news, economic calendar
│
├── core/                      # Business logic (no web framework deps)
│   ├── state.py               # Global singleton: AppState, RegimeState, PositionInfo, etc.
│   ├── constants.py           # Shared time/size constants (MS_PER_DAY, etc.)
│   ├── risk_engine.py         # ATR-based position sizing with regime multipliers
│   ├── exchange.py            # Core CCXT wrapper: account, positions, TP/SL, listen key
│   ├── exchange_market.py     # Market data: OHLCV, orderbook, mark price, MFE/MAE
│   ├── exchange_income.py     # Income history, equity backfill, trade history, funding rates
│   ├── exchange_factory.py    # Per-account CCXT instance factory
│   ├── ws_manager.py          # Binance WebSocket: user data + market streams
│   ├── platform_bridge.py     # Quantower plugin integration (WS + REST)
│   ├── schedulers.py          # Background tasks: BOD, regime, news, ping, account refresh
│   ├── event_bus.py           # In-process async pub/sub (6 channels)
│   ├── regime_classifier.py   # Rule-based 5-state macro regime classifier
│   ├── regime_fetcher.py      # Signal fetchers: VIX, FRED, Binance OI/funding, rvol
│   ├── backtest_runner.py     # Historical trade replay with regime multipliers
│   ├── reconciler.py          # Post-trade MFE/MAE reconciliation
│   ├── account_registry.py    # Multi-account credential management (encrypted)
│   ├── crypto.py              # AES-256 encryption for API keys
│   ├── database.py            # SQLite manager (thin coordinator, delegates to db_*.py)
│   ├── db_snapshots.py        # account_snapshots, position_changes queries
│   ├── db_trades.py           # pre_trade_log, execution_log, trade_history
│   ├── db_exchange.py         # exchange_history queries
│   ├── db_analytics.py        # Journal stats, equity series, daily stats
│   ├── db_backtest.py         # Backtest sessions and results
│   ├── db_regime.py           # regime_signals, regime_labels
│   ├── db_ohlcv.py            # OHLCV cache queries
│   ├── db_equity.py           # equity_cashflow queries
│   ├── db_settings.py         # Settings and accounts table queries
│   ├── db_models.py           # Model/strategy metadata
│   ├── db_news.py             # News events
│   ├── db_router.py           # Routes queries to per-account vs global DBs
│   ├── analytics.py           # Computed analytics (R-multiples, beta, calendar)
│   ├── data_logger.py         # Daily/monthly snapshots, XLSX export
│   ├── monitoring.py          # Live system health checks
│   ├── news_fetcher.py        # Finnhub news + economic calendar
│   ├── ohlcv_fetcher.py       # OHLCV data fetching utilities
│   ├── handlers.py            # Event bus handlers
│   ├── log_formatter.py       # JSON log formatting
│   └── migrations/            # Schema migrations (applied on startup)
│       └── 000_split_databases.py
│
├── templates/                 # Jinja2 templates (HTMX-driven)
│   ├── base.html              # Layout shell (header, nav, PWA registration)
│   ├── dashboard.html         # Live positions, account state
│   ├── calculator.html        # Pre-trade risk calculator
│   ├── history.html           # Trade log viewer
│   ├── analytics.html         # PnL analysis
│   ├── backtest.html          # Backtest config + results
│   ├── regime.html            # Regime state + history
│   ├── params.html            # Risk parameter editor
│   └── fragments/             # HTMX partial fragments (~25 files)
│
├── static/                    # PWA assets
│   ├── manifest.json
│   ├── service-worker.js
│   ├── icon-192.png
│   └── icon-512.png
│
├── data/                      # Runtime data (gitignored)
│   ├── risk_engine.db         # Main SQLite DB (WAL mode)
│   ├── global.db              # Global settings
│   ├── ohlcv/                 # OHLCV cache DB
│   ├── per_account/           # Per-account databases
│   ├── logs/                  # Rotating JSON logs
│   ├── snapshots/             # Daily/weekly BOD snapshots (CSV)
│   └── params.json            # Active risk parameters
│
├── QuantowerRiskPlugin/       # C# .NET 8 Quantower integration plugin
├── tests/                     # pytest test suite
│   ├── test_smoke.py          # Import all modules (catch regressions)
│   ├── test_database.py       # DB init, migrations, upserts
│   └── test_routes.py         # Route smoke tests (all pages return 200)
│
└── quantamental_engine_v2.1_spec.md  # Full v2.1 specification
```

## Dependency Direction

```
config  <--  core/*  <--  api/*  <--  main.py
```

No module in `core/` imports from `api/`. `main.py` imports from both. Nothing imports from `main.py`.

Known circular dependencies (marked with `# late import: circular dep`):
- `exchange` <-> `platform_bridge` (plugin provides market data fallback)
- `ws_manager` <-> `platform_bridge` (fill refresh path)
- `exchange` -> `account_registry` / `exchange_factory` (startup ordering)

## Database

SQLite with WAL mode. 18+ tables across multiple DB files:
- `data/risk_engine.db` — main DB (snapshots, trades, history, regime)
- `data/global.db` — global settings
- `data/ohlcv/binancefutures.db` — OHLCV cache
- `data/per_account/<name>.db` — per-account data

Schema is defined in `core/database.py` (`_CREATE_STATEMENTS`). Migrations in `core/migrations/` are applied idempotently on every startup.

## Migrations

Pattern: `core/migrations/NNN_description.py`. Each migration is a function that receives the DB connection and runs `ALTER TABLE` / `CREATE INDEX` statements. Applied on startup if not yet recorded. SQLite-friendly — no Alembic.

## Background Tasks

All spawned from `core/schedulers.py:start_background_tasks()`:

| Task | Interval | Purpose |
|------|----------|---------|
| startup_fetch | once | Binance REST init + WS connect |
| bod_scheduler | midnight local | BOD reset + daily snapshot |
| auto_export | 24h (configurable) | DB -> XLSX export |
| account_refresh | 30s / 5s | REST safety net for positions |
| ping | 1s | Exchange latency measurement |
| history_refresh | 5 min | BOD/SOW equity + trade history |
| regime_refresh | 10 min | Regime re-classify + signal fetch |
| news_refresh | 60s | Finnhub news + calendar |
| bwe_ws | persistent | BWE news WebSocket |
| monitoring | persistent | System health checks |

## Updating Dependencies

```bash
# Review what would change
pip install --dry-run -r requirements.txt

# Apply updates
pip install --upgrade -r requirements.txt

# Freeze current state to lock file
pip freeze > requirements.lock
```

Run `pytest tests/` after any dependency update to verify nothing broke.
