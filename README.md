# Quantamental Engine

Pre-trade risk gatekeeper and post-trade logger for discretionary crypto
futures trading. The engine provides real-time position monitoring, ATR-based
position sizing with macro regime multipliers, and a browser-based dashboard
served as a PWA. It connects to exchanges via a vendor-neutral adapter layer.
A Quantower plugin is an **optional execution-side integration** — the
engine does not depend on it for data flow.

Currently deployed against Binance USDM-M and Bybit Linear perpetuals, with
MEXC read-only integration via adapter capability flags.

---

## Architecture

The engine follows a **core + adapter ring** pattern established during the
v2.3.1 audit. The core engine is broker-agnostic: every external connection
(exchanges, regime data sources, news feeds) routes through a vendor-neutral
adapter layer defined by Python protocols in `core/adapters/protocols.py`.

```
                    +-----------+
                    |  FastAPI   |
                    |  routes    |
                    +-----+-----+
                          |
                    +-----+-----+
                    | core/*.py  |  Engine core (state, risk, scheduling)
                    +-----+-----+
                          |
              +-----------+-----------+
              |           |           |
         +----+----+ +---+---+ +----+----+      [Quantower plugin]
         | Binance | | Bybit | |  MEXC   |  ←   (optional, execution-side
         | adapter | |adapter| |adapter* |       only; not a data dependency)
         +---------+ +-------+ +---------+
                                * read-only (capability flags)
```

**Quantower plugin (optional execution-side integration).** As of v2.5,
exchange-WS is the primary data path. The plugin — if the operator chooses
to run QT alongside the engine — pushes fills + position snapshots to
`/ws/platform` and consumes risk-state updates for chart overlays. Operating
in "standalone" mode (plugin absent) is the supported default. The
`core/platform_bridge.py` module that handles plugin traffic is marked
legacy / archive-candidate; see its docstring for the deprecation timeline.

Engine core never imports exchange libraries directly. Adapters implement
`ExchangeAdapter` / `WSAdapter` protocols and are resolved at runtime by
`core/exchange_factory.py`. See [docs/adapters/](docs/adapters/) for the
full adapter inventory.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ (tested on 3.13) |
| Web framework | FastAPI + Uvicorn |
| Frontend | Jinja2 + HTMX 1.9.12 + Idiomorph (server-rendered, SSE-driven), PWA |
| Event bus | InProcessBus (default) or Redis pub/sub (`PUBSUB_BACKEND`) |
| Database | SQLite via aiosqlite (WAL mode, per-account DB split) |
| Exchange connectivity | ccxt >=4.3.20 + native WebSocket (websockets) |
| Macro data | yfinance (VIX), FRED API (yields, spreads) |
| Data processing | pandas, numpy |
| Encryption | cryptography (Fernet, AES-256 for API keys) |
| HTTP client | httpx (async) |
| Broker bridge | Quantower C# plugin via WebSocket *(legacy / optional — not a data dependency as of v2.5; archive candidate)* |
| Testing | pytest + pytest-asyncio (1247 tests) |

---

## Status

- **Current**: v2.4 (in audit phase — 1247 tests passing)
  - SSE-driven dashboard with HTMX morphing (flicker-free updates)
  - Multi-exchange: Binance, Bybit, MEXC (read-only via capability flags)
  - History page redesign: 3-card layout, fill drawer, exec link, trade events log
  - Per-account timezone, analytics periods, strategy presets
  - Rate-limit architecture (weight tracker, fan-out coordination)
  - `calc_id` propagation for slippage tracking and fills↔pre_trade_log matching
  - Observability: `engine_events` + `trade_events` audit trail
- **Previous**: v2.3.1 (audit complete, 6 buckets closed, 40 findings resolved)
- **Next**: v2.5 (backtesting subsystem, defensive ML)

See [v2.4.md](v2.4.md) for spec + implementation status, and
[v2.5-v2.7_roadmap.md](v2.5-v2.7_roadmap.md) for downstream phases.

---

## Repository Structure

```
.
├── main.py                    # FastAPI entry point, lifespan, app creation
├── config.py                  # Configuration constants, env vars
├── requirements.txt           # Dependencies (pinned ranges)
│
├── core/                      # Engine core (state, risk, scheduling, data)
│   ├── adapters/              # Exchange and platform adapters
│   │   ├── protocols.py       # Vendor-neutral adapter protocols
│   │   ├── binance/           # Binance USDM-M adapter (REST + WS)
│   │   ├── bybit/             # Bybit Linear adapter (REST + WS)
│   │   └── mexc/              # MEXC read-only adapter (capability flags)
│   ├── risk_engine.py         # ATR-based position sizing, regime multipliers
│   ├── exchange.py            # REST orchestration (fetch, enrich, TP/SL)
│   ├── ws_manager.py          # WebSocket lifecycle and dispatch
│   ├── order_manager.py       # Single-writer order enforcement
│   ├── order_state.py         # Order state machine, TP/SL matching
│   ├── data_cache.py          # In-memory data cache (positions, orders)
│   ├── state.py               # Global state (AppState, RegimeState)
│   ├── schedulers.py          # Background tasks (BOD, regime, news, ping)
│   ├── event_bus.py           # Async pub/sub (InProcess or Redis)
│   ├── regime_classifier.py   # Rule-based 5-state macro regime classifier
│   ├── platform_bridge.py     # Quantower plugin integration
│   ├── database.py            # SQLite manager (delegates to db_*.py)
│   ├── monitoring.py          # System health checks (9 checks)
│   └── migrations/            # Schema migrations (applied on startup)
│
├── api/                       # FastAPI route handlers (Jinja2 + HTMX)
│   ├── router.py              # Combines domain sub-routers
│   └── routes_*.py            # Per-domain routes (dashboard, calculator, etc.)
│
├── templates/                 # Jinja2 templates (HTMX-driven)
│   ├── *.html                 # Page shells
│   └── fragments/             # HTMX partial fragments (~25 files)
│
├── static/                    # PWA assets (manifest, service worker, icons)
├── tests/                     # pytest suite (1247 tests, 111-row baseline)
├── scripts/                   # Utility scripts
├── data/                      # Runtime data (gitignored: DBs, logs, snapshots)
├── docs/                      # Documentation (see below)
└── QuantowerRiskPlugin/       # C# .NET Quantower integration plugin
```

---

## Documentation

- **[Adapter Maintenance Interfaces](docs/adapters/)** — `binance.md`,
  `bybit.md`. Full API surface inventory with VERIFIED / LISTED / ASSUMED
  tags, known quirks, WS architecture, and migration watch lists.
- **[Audit Closeout v2.3.1](docs/audit/AUDIT_CLOSEOUT.md)** — Synthesis of
  the full deep audit: findings inventory, v2.4 dependency list,
  architectural patterns established, verification status.
- **[Audit Finding Registry](docs/audit/AUDIT_REPORT.md)** — Canonical
  finding registry from the v2.3.1 audit.
- **[Historical Audit Artifacts](docs/past/)** — Per-finding design docs,
  workflow logs, and prior version specs.
- **[v2.4 Spec + Status](v2.4.md)** — Gate promotion, execution quality, UI
  architecture, and history redesign. Includes implementation status section.
- **[v2.4 Release Notes](docs/release_notes/v2.4.md)** — User-facing summary
  of what v2.4 delivers.
- **[v2.5–v2.7 Roadmap](v2.5-v2.7_roadmap.md)** — Backtesting subsystem,
  defensive ML, integration backtest.

---

## Setup

```bash
# Clone and create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env             # Edit with API keys, master encryption key
# Required: ENV_MASTER_KEY (Fernet key for API key encryption)
# Required: Exchange API credentials (added via /accounts UI)
# Optional: PUBSUB_BACKEND=redis REDIS_URL=redis://localhost:6379/0
# Optional: EXCHANGE_REFRESH_HZ=1.0 EXEC_LINK_PRICE_TOL=0.0005

# Run
uvicorn main:app --host 0.0.0.0 --port 8000

# Tests
pytest tests/
```

The engine creates SQLite databases in `data/` on first startup. Schema
migrations in `core/migrations/` are applied automatically.

---

## Architectural Principles

Patterns established and validated during the v2.3.1 audit. See
[AUDIT_CLOSEOUT.md](docs/audit/AUDIT_CLOSEOUT.md) for full details.

- **Core + adapter ring** — No broker-specific code outside the adapter
  layer. Engine core imports only vendor-neutral protocols. Adding an
  exchange means implementing `ExchangeAdapter` + `WSAdapter`, not
  modifying core.

- **Adapter capability flags** (v2.4+) — Adapters declare what they
  support via a `capabilities` dict (`orders`, `conditional_orders`,
  `market_data`, `account_query`, `position_query`, `historical_equity`).
  Engine factory checks capabilities at wire time and refuses to
  instantiate dependent components (e.g. calculator for an adapter
  without `orders`). First user: v2.4.5 MEXC read-only adapter.

- **Adapter documentation discipline** — Every adapter endpoint tagged
  VERIFIED / LISTED / ASSUMED. Lesson from the audit: 2 of 3 API surface
  assumptions were wrong. Don't trust inferred knowledge.

- **Smoke-diff baseline** — 111-row deterministic baseline detects
  regression in sizing, ATR, slippage, and analytics math. Pure-function
  safety net: empty diff = no regression on exercised paths.

- **Structural != operational** — Static analysis identifies what code
  does; operational verification confirms it works in production.
  Both are required before closing a finding.

- **Per-commit stop-and-report** — Multi-layer judgment at every commit
  boundary. Enables scope correction, discovery capture, and
  verification-period additions during implementation.

---

## Dependency Direction

```
config  <--  core/*  <--  api/*  <--  main.py
```

No module in `core/` imports from `api/`. `main.py` imports from both.
Nothing imports from `main.py`.
