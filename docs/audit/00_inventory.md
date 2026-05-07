# Phase 1a — File Inventory

**Codebase**: Quantamental Engine v2.3.1  
**Date**: 2026-05-07  
**Branch**: `audit/v2.3.1`  
**Total Python LOC**: ~13,900 (78 non-empty files)  
**Total Template LOC**: ~6,600 (48 HTML files)

---

## Layer Key

| Layer | Description |
|-------|-------------|
| **entrypoint** | Application bootstrap, FastAPI app creation, lifespan |
| **route** | HTTP/WS request handlers (FastAPI routers) |
| **service** | Orchestration, background tasks, event wiring, DB domain methods |
| **core** | Domain logic coupled to I/O (order lifecycle, event bus, DB coordinator) |
| **quant** | Pure financial math, classifiers, analytics (should be I/O-free) |
| **state** | Mutable shared state containers, caches, registries |
| **adapter** | Concrete implementations of external system integrations |
| **config** | Constants, enums, environment variables |
| **util** | Cross-cutting helpers (logging, encryption, formatting) |

---

## Python Source Files

### Entrypoint

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `main.py` | 165 | FastAPI app creation, lifespan (startup/shutdown), static mount, router inclusion | entrypoint |

### Configuration

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `config.py` | 142 | Environment variables, API keys, fee defaults, ATR params, WS reconnect config, regime multipliers | config |
| `core/constants.py` | 28 | Time unit constants (MS_PER_MINUTE/HOUR/DAY), timeframe-to-ms lookup | config |
| `core/order_state.py` | 67 | OrderStatus enum, valid state transition map, terminal status set | config |
| `core/adapters/binance/constants.py` | 48 | Binance WS endpoints, REST rate limits, order type mappings (unified ↔ Binance) | config |
| `core/adapters/bybit/constants.py` | 56 | Bybit V5 WS endpoints, REST rate limits, order type mappings (unified ↔ Bybit) | config |

### State Management

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/state.py` | 428 | Global AppState singleton: ExchangeInfo, AccountState, PortfolioStats, WSStatus, PositionInfo, params dict, caches | state |
| `core/data_cache.py` | 636 | Single-writer state manager (Nautilus-style): versioned position/account snapshots, conflict resolution (Platform > WS > REST), lock ordering | state |
| `core/account_registry.py` | 366 | In-memory credential cache: decrypted API keys per account, CCXT factory access, active account tracking | state |
| `core/connections.py` | 201 | ConnectionsManager: in-memory cache of 3rd-party data provider API keys (Finnhub, BWE) | state |
| `api/cache.py` | 125 | API-layer caching: equity backfill series, funding rate snapshots, recent order lists | state |

### Quant / Pure Logic

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/risk_engine.py` | 434 | ATR-based position sizing, regime multipliers, leverage calc, margin checks, drawdown/weekly-loss gates | quant |
| `core/analytics.py` | 309 | Performance math: returns, Sharpe, Sortino, max drawdown, win rate, PnL attribution, annualization | quant |
| `core/backtest_runner.py` | 627 | Historical replay engine: signal-scan mode, regime filters, equity curves, trade detail generation | **service** (reclassified from quant — orchestrates DB I/O into pure logic; Phase 1d must flag extractable quant logic) |
| `core/regime_classifier.py` | 305 | Rule-based macro regime classifier: 5-state (risk-on-trending → risk-off-panic), trend/vol/yield/funding logic | quant |
| `core/reconciler.py` | 169 | Post-trade MFE/MAE calculator: highest/lowest price vs entry/exit during hold period | quant |

### Core Domain Logic

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/order_manager.py` | 406 | Order lifecycle state machine: validation, TP/SL linkage, fill processing, reconciliation, transition logging | core |
| `core/event_bus.py` | 113 | In-process asyncio pub/sub: 5 risk channels (account_updated, positions_refreshed, risk_calculated, params_updated, trade_closed) | core |
| `core/database.py` | 689 | Async SQLite coordinator: schema creation, connection pooling, WAL mode, mixin composition for all db_* modules | core |
| `core/db_router.py` | 169 | Database router: selects correct SQLite file (legacy combined vs split per-exchange) for reads/writes | core |

### Adapters — Exchange

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/adapters/__init__.py` | 89 | Public adapter API: get_adapter(), to_position_info(), map_market_type(), adapter resolution by exchange:market_type | adapter |
| `core/adapters/base.py` | 104 | BaseExchangeAdapter: shared ThreadPoolExecutor, CCXT instance management, common rate limiting | adapter |
| `core/adapters/protocols.py` | 266 | Normalized data models (NormalizedAccount, Position, Order, Trade, Income) and ExchangeAdapter Protocol class | adapter |
| `core/adapters/registry.py` | 76 | Decorator-based adapter registration and lookup by exchange:market_type composite key | adapter |
| `core/adapters/binance/__init__.py` | 7 | Binance USD-M Futures adapter package export | adapter |
| `core/adapters/binance/rest_adapter.py` | 334 | Binance REST: account info, positions, orders, trades, income normalized to protocol models | adapter |
| `core/adapters/binance/ws_adapter.py` | 168 | Binance WS: stream naming, message parsing, event routing for user-data and market streams | adapter |
| `core/adapters/bybit/__init__.py` | 7 | Bybit Linear Perpetual adapter package export | adapter |
| `core/adapters/bybit/rest_adapter.py` | 403 | Bybit V5 REST: account, positions, orders, trades, income normalized to protocol models | adapter |
| `core/adapters/bybit/ws_adapter.py` | 217 | Bybit V5 WS: auth, topic subscription, message parsing for private and public channels | adapter |
| `core/exchange.py` | 368 | CCXT REST wrapper: account fetch, position fetch, TP/SL creation, listen key lifecycle; delegates to adapter layer | adapter (**NOTE**: (a) holds singleton state — must appear in Phase 1b state map; (b) imported directly by quant/service code — each importer is a boundary violation for Phase 1c/1d) |
| `core/exchange_factory.py` | 157 | Per-account CCXT instance cache with adapter resolution; invalidation on account switch | adapter |
| `core/exchange_market.py` | 268 | Market data REST: OHLCV fetch, orderbook, mark price, MFE/MAE price range queries | adapter |
| `core/exchange_income.py` | 410 | Income/equity REST: equity backfill (BOD), trade history, funding rates, dividend income queries | adapter |
| `core/ws_manager.py` | 547 | WebSocket lifecycle manager: stream subscription, user-data/market handlers, reconnect with exponential backoff | adapter |

### Adapters — External Data

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/news_fetcher.py` | 340 | News + economic calendar fetchers (Finnhub REST, BWE WebSocket), sentiment scoring, date normalization | adapter |
| `core/regime_fetcher.py` | 558 | Macro signal fetchers: DXY, bonds, equities, crypto indices (via FRED, yfinance, httpx), funding rates | adapter |
| `core/ohlcv_fetcher.py` | 282 | Historical OHLCV ingestion: async CCXT fetch, dedup, resample to target timeframe, DB persistence | adapter |

### Adapters — Platform Integration

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/platform_bridge.py` | 810 | Quantower plugin integration: WS server, message parsing, order relay, fill processing, position state sync | adapter (**DECOMPOSITION TARGET**: 810 LOC spanning 4 responsibilities — WS server, message parsing, order relay, state sync. Phase 1b must map every state field touched; Phase 1d must propose 3–4 module split as structural redesign candidate) |

### Services — Background & Orchestration

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/schedulers.py` | 478 | Background task registry: BOD equity, regime refresh, news fetch, account refresh, health checks, auto-export | service |
| `core/monitoring.py` | 131 | Health check loop: periodic verification of exchange REST, WS, DB connectivity every 60s | service |
| `core/handlers.py` | 213 | Event bus handlers: account update, position refresh, risk calc, params update, trade-closed processing | service (Phase 1d must inspect each handler for business logic that belongs in core — flag under category 3) |

### Services — Database Domain Methods

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/db_orders.py` | 788 | Orders/fills/closed_positions tables: CRUD, sorting, filtering, status aggregation, MFE/MAE persistence | service |
| `core/db_trades.py` | 319 | Pre-trade log, execution log, trade history, position notes: domain persistence with sorting/filtering | service |
| `core/db_analytics.py` | 359 | Analytics queries: journal stats, equity series, PnL curves, MFE/MAE aggregation, performance metrics | service |
| `core/db_snapshots.py` | 175 | Account snapshots + position changes: balance/position state recording at points in time | service |
| `core/db_regime.py` | 153 | Regime signals + regime labels: macro state persistence and retrieval | service |
| `core/db_settings.py` | 190 | Settings + accounts tables: config and encrypted credential storage | service |
| `core/db_exchange.py` | 133 | Exchange history table: trade/fill persistence from exchange REST responses | service |
| `core/db_news.py` | 126 | News items + economic calendar tables: event persistence and retrieval | service |
| `core/db_backtest.py` | 124 | Backtest sessions, trades, equity: historical replay result persistence | service |
| `core/db_models.py` | 67 | Potential models table: trading model definition storage | service |
| `core/db_ohlcv.py` | 63 | OHLCV cache table: market data caching for backtests and analysis | service |
| `core/db_equity.py` | 38 | Equity cashflow table: dividend/funding/commission line-item recording | service |

### Routes (HTTP/WS Handlers)

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `api/router.py` | 40 | Combines all domain sub-routers into single APIRouter for main.py mounting | route |
| `api/routes_dashboard.py` | 297 | Home page: account summary, position cards, wallet info, WS connection status | route |
| `api/routes_analytics.py` | 416 | Performance analytics: PnL curves, equity series, Sharpe/Sortino, calendar heatmaps, funding exposure | route |
| `api/routes_accounts.py` | 391 | Multi-account management: create/edit/delete/activate accounts, credential encryption/rotation | route |
| `api/routes_history.py` | 309 | Trade history pagination: pre-trade log, execution log, trade journal, position notes | route |
| `api/routes_backtest.py` | 223 | Historical replay: create/run backtests, macro signal scanning, results display | route |
| `api/routes_regime.py` | 180 | Macro regime dashboard: classifier output, signal details, news items, calendar events | route |
| `api/routes_connections.py` | 157 | 3rd-party data provider management: Finnhub/BWE API key CRUD, connection testing | route |
| `api/routes_orders.py` | 155 | Order/fill/closed-position tables: paginated, sortable, searchable with date filters | route |
| `api/routes_params.py` | 83 | Risk parameter editor: ATR multiplier, SL%, TP tiers, regime mode overrides, position limits | route |
| `api/routes_calculator.py` | 80 | Risk/position size calculator: equity %, ATR-based sizing, slippage, margin requirements | route |
| `api/routes_models.py` | 66 | Model configuration CRUD: create/edit/list potential trading models | route |
| `api/routes_platform.py` | 54 | JSON API for Quantower plugin: account state, positions, open orders, risk snapshot | route |
| `api/routes_news.py` | 45 | Economic calendar + news feed endpoints | route |
| `api/routes_config.py` | 16 | Config page: serves tabbed account + connections UI shell | route |

### Utilities

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/data_logger.py` | 244 | CSV logging, periodic equity/account snapshots, manual XLSX exports (daily/monthly) | util |
| `api/helpers.py` | 157 | Shared template utilities: _fmt (number formatting), _hold_time, _ctx (base context), _paginate_list | util |
| `core/crypto.py` | 69 | Symmetric encryption/decryption for API credentials (Fernet AES-256) | util |
| `core/log_formatter.py` | 57 | JSON log formatter for RotatingFileHandler | util |
| `core/audit.py` | 45 | Credential audit logger: lifecycle events to data/logs/audit.jsonl | util |

### Migrations

| Path | Lines | Purpose | Layer |
|------|------:|---------|-------|
| `core/migrations/__init__.py` | 7 | Migration package: version tracking, idempotent application | util |
| `core/migrations/000_split_databases.py` | 349 | One-shot migration: split legacy combined DB into per-exchange SQLite files | service |

### Package Markers (empty)

| Path | Lines | Layer |
|------|------:|-------|
| `api/__init__.py` | 0 | — |
| `core/__init__.py` | 0 | — |

---

## Template Files (Jinja2 + HTMX)

### Page Templates

| Path | Lines | Purpose |
|------|------:|---------|
| `templates/base.html` | 655 | Base layout: nav, sidebar, JS imports, WS connection, ECharts theme |
| `templates/regime.html` | 891 | Macro regime dashboard: signal gauges, charts, news feed, calendar |
| `templates/calculator.html` | 677 | Risk calculator: position sizer, orderbook, margin estimator |
| `templates/backtest.html` | 565 | Backtester UI: parameter form, equity curve, trade table |
| `templates/history.html` | 263 | Trade history: tabbed tables with pagination |
| `templates/analytics.html` | 110 | Analytics shell: loads fragments for PnL, excursions, funding |
| `templates/dashboard.html` | 88 | Dashboard shell: loads fragment panels via HTMX |
| `templates/config.html` | 72 | Config shell: tabbed account + connections management |

### Fragment Templates (HTMX partials)

| Path | Lines | Purpose |
|------|------:|---------|
| `templates/fragments/equity_ohlc.html` | 318 | ECharts equity OHLC candlestick + line chart |
| `templates/fragments/dashboard_body.html` | 236 | Main dashboard content: positions, PnL summary, risk meters |
| `templates/fragments/calc_result.html` | 200 | Calculator result panel: sizing, margin, fees, slippage |
| `templates/fragments/history_tables.html` | 184 | History tab container with table switching |
| `templates/fragments/account_detail.html` | 177 | Account detail/edit form with credential fields |
| `templates/fragments/analytics/overview_stats.html` | 174 | Performance stats grid: Sharpe, MDD, win rate, expectancy |
| `templates/fragments/analytics/excursions.html` | 133 | MFE/MAE scatter plots |
| `templates/fragments/backtest/results.html` | 123 | Backtest results: equity curve + trade list |
| `templates/fragments/history/exchange_table.html` | 118 | Exchange-sourced trade history table |
| `templates/fragments/history/open_positions.html` | 113 | Open positions table with live PnL |
| `templates/fragments/analytics/calendar_pnl.html` | 102 | Calendar heatmap of daily PnL |
| `templates/fragments/analytics/r_multiples.html` | 87 | R-multiple distribution histogram |
| `templates/fragments/analytics/var_display.html` | 85 | Value-at-Risk display |
| `templates/fragments/history/pre_trade_table.html` | 86 | Pre-trade analysis log table |
| `templates/fragments/history_table.html` | 82 | Generic history table wrapper |
| `templates/fragments/history/trade_history_table.html` | 81 | Closed trade history table |
| `templates/fragments/history/closed_positions_table.html` | 79 | Closed positions with MFE/MAE |
| `templates/fragments/analytics/beta_exposure.html` | 75 | Beta/correlation exposure chart |
| `templates/fragments/accounts.html` | 73 | Account list management panel |
| `templates/fragments/analytics/funding_tracker.html` | 73 | Funding rate tracking table |
| `templates/fragments/analytics/pairs_table.html` | 73 | Per-pair performance breakdown |
| `templates/fragments/dashboard_journal_stats.html` | 70 | Journal statistics summary |
| `templates/fragments/history/execution_table.html` | 68 | Execution log table |
| `templates/fragments/history/order_history_table.html` | 68 | Historical order table |
| `templates/fragments/history/fills_table.html` | 66 | Fill detail table |
| `templates/fragments/history/_pagination.html` | 62 | Reusable pagination controls |
| `templates/fragments/history/open_orders_table.html` | 55 | Open orders table |
| `templates/fragments/history/live_trades_table.html` | 51 | Live (in-progress) trades table |
| `templates/fragments/dashboard_top.html` | 43 | Top bar: equity, daily PnL, margin ratio |
| `templates/fragments/history_pretrade.html` | 43 | Pre-trade log panel |
| `templates/fragments/dashboard_secondary.html` | 35 | Secondary stats: weekly PnL, exposure |
| `templates/fragments/backtest/sessions_list.html` | 35 | Backtest session selector |
| `templates/fragments/calculator_orderbook.html` | 34 | Orderbook depth display |
| `templates/fragments/account_list.html` | 31 | Account list dropdown/selector |
| `templates/fragments/history/_table_controls.html` | 31 | Table filter/sort controls |
| `templates/fragments/orderbook.html` | 21 | Minimal orderbook fragment |
| `templates/fragments/dashboard_exchange_info.html` | 21 | Exchange info: server time, latency, fees |
| `templates/fragments/history/_sort_header.html` | 19 | Sortable column header partial |
| `templates/fragments/ws_status.html` | 16 | WebSocket connection status indicator |
| `templates/fragments/ws_log.html` | 6 | WebSocket log line partial |

---

## Static Assets

| Path | Purpose |
|------|---------|
| `static/echarts-theme-qe.js` | Custom ECharts theme for all dashboard charts |
| `static/manifest.json` | PWA manifest for installable web app |
| `static/service-worker.js` | Service worker for offline caching |
| `static/icon-192.png` | PWA icon (192×192) |
| `static/icon-512.png` | PWA icon (512×512) |

## Configuration Files

| Path | Lines | Purpose |
|------|------:|---------|
| `requirements.txt` | 19 | Python package dependencies (FastAPI, ccxt, aiosqlite, pandas, etc.) |
| `.gitignore` | 38 | Git exclusion rules |
| `data/params.json.migrated` | — | Migrated risk parameters (legacy, now in DB) |

---

## Summary by Layer

| Layer | Files | Total LOC | % of Code |
|-------|------:|----------:|----------:|
| **quant** | 4 | 1,217 | 8.8% |
| **core** | 4 | 1,377 | 9.9% |
| **state** | 5 | 1,756 | 12.6% |
| **adapter** | 19 | 4,598 | 33.1% |
| **service** | 16 | 3,502 | 25.2% |
| **route** | 15 | 2,612 | — |
| **config** | 5 | 341 | 2.5% |
| **util** | 7 | 928 | 6.7% |
| **entrypoint** | 1 | 165 | 1.2% |

Note: route LOC excluded from core engine percentage since templates are
the primary UI; routes are thin wiring.

---

## Dependency Graph (simplified)

```
                    ┌─────────┐
                    │ main.py │  entrypoint
                    └────┬────┘
                         │
                  ┌──────┴──────┐
                  │ api/router  │  routes
                  │ routes_*    │
                  └──────┬──────┘
                         │ imports
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────┴────┐   ┌──────┴──────┐  ┌─────┴──────┐
    │  state  │   │   service   │  │   adapter   │
    │ state.py│   │ schedulers  │  │ exchange.py │
    │ data_   │   │ handlers    │  │ ws_manager  │
    │  cache  │   │ monitoring  │  │ adapters/*  │
    │ acct_   │   │ db_*        │  │ news_fetch  │
    │  reg    │   │             │  │ regime_fetch│
    └────┬────┘   └──────┬──────┘  │ platform_  │
         │               │         │  bridge     │
         │        ┌──────┴──────┐  └─────┬──────┘
         │        │    core     │        │
         └────────┤ order_mgr   ├────────┘
                  │ event_bus   │
                  │ database    │
                  │ db_router   │
                  └──────┬──────┘
                         │
                  ┌──────┴──────┐
                  │    quant    │
                  │ risk_engine │
                  │ analytics   │
                  │ backtest    │
                  │ regime_cls  │
                  │ reconciler  │
                  └──────┬──────┘
                         │
                  ┌──────┴──────┐
                  │   config    │
                  │ config.py   │
                  │ constants   │
                  │ order_state │
                  └─────────────┘
```

Note: Arrows flow downward (imports). Lateral imports exist between
adapter↔state and service↔adapter layers — these are audit targets.

---

## Downstream Phase Directives

**Phase 1b (state map):** Seven state sources must each be a labeled section
with per-field reader/writer enumeration: app_state, data_cache,
account_registry, connections_manager, api/cache, core/exchange.py singleton,
core/platform_bridge.py internal state. Cross-container state (same logical
field in two containers) is itself a finding.

**Phase 1c (boundary map):** core/adapters/protocols.py gets a dedicated
subsection. The second-vendor test must include a non-crypto-perp venue
(Interactive Brokers TradFi equities/options, or a spot-only exchange).
Specifically assess: order types, symbol format, position model, margin model,
fee model, time-in-force. Anything that wouldn't translate is vendor leakage
at the protocol level.

**Phase 1c (boundary map):** Every external importer of core/exchange.py must
be listed by file:line. Phase 1d must flag each as a category 3 finding.

**Phase 1d (per-file):** core/platform_bridge.py must include a structural
redesign proposal (3–4 module split). core/backtest_runner.py must flag
extractable pure quant logic. core/handlers.py must inspect each handler
for misplaced business logic.
