# Meridian

Pre-trade risk gatekeeper and post-trade logger for discretionary crypto
futures trading. The engine provides real-time position monitoring, ATR-based
position sizing with macro regime multipliers, and a browser-based dashboard
served as a PWA. It connects to exchanges via a vendor-neutral adapter layer.

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
         +----+----+ +---+---+ +----+----+
         | Binance | | Bybit | |  MEXC   |
         | adapter | |adapter| |adapter* |
         +---------+ +-------+ +---------+
                                * read-only (capability flags)
```

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
| Testing | pytest + pytest-asyncio + pytest-timeout (4,400+ tests) |

---

## Status

- **Current**: v3.1 (Meridian — the React cockpit IS the app, served at `/`)
  - **Jinja retirement complete (2026-07-30)**: the React shell owns `/`
    (`/v3` 307s there); the 8 Jinja page twins and their routes are deleted.
    Gate for the promotion was the Phase-7 live-acceptance report
    (`docs/audits/2026-07-29-v3.0-e2e-phase7-acceptance.md`) — a full
    Playwright E2E program (control sweep, order permutations, seeded monkey,
    sandboxed mutations, 8 operator-in-the-loop live-trade scenarios) that
    found and fixed 9 engine defects along the way
  - Surviving Jinja: `/config` (account create/delete), `orders/needs_link`,
    the `admin/*` pages, and every `/fragments/*` route (the `?format=json`
    doors the React pages read)
  - v3.0: ground-up presentation-layer rebuild against the Meridian design
    reference — precompiled React served as static JS from FastAPI (no Node
    at runtime, all deps vendored offline), SSE live transport, one shared
    primitive layer; design-consistency audit: 34 findings, all closed or
    explicitly refuted
  - v2.7: DB-backed library of reusable, exchange-agnostic models;
    backtest-import adapter framework (MultiCharts first); calculator pre-fill
    + close-time model tagging
  - v2.6: Quantower plugin removed — the engine is exchange-direct only
    (observe-only Binance WS)
  - v2.5 arc: correlation-log observability spine (registry now 42
    categories), linkage battery (62 pins), attribution reconciler
    (`core/position_identity.py`)
  - SSE-driven dashboard with HTMX morphing (flicker-free updates)
  - Observability: `engine_events` + `trade_events` + correlation log
- **Next**: v3.0 (ground-up UI rebuild —
  [docs/design/v3.0_models_tab_design_prompt.md](docs/design/v3.0_models_tab_design_prompt.md))

The displayed product version is `PROJECT_VERSION_` in [config.py](config.py)
— the single source of truth, bumped at program close (see CLAUDE.md
§ "Release hygiene"). Historical specs: [v2.4.md](docs/archive/v2.4.md),
[v2.5-v2.7_roadmap.md](docs/archive/v2.5-v2.7_roadmap.md); current designs live in
`docs/design/`.

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
│   ├── database.py            # SQLite manager (delegates to db_*.py)
│   ├── monitoring.py          # System health checks (8 checks)
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
└── docs/                      # Documentation (see below)
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
- **[v2.4 Spec + Status](docs/archive/v2.4.md)** — Gate promotion, execution quality, UI
  architecture, and history redesign. Includes implementation status section.
- **[v2.4 Release Notes](docs/release_notes/v2.4.md)** — User-facing summary
  of what v2.4 delivers.
- **[v2.5–v2.7 Roadmap](docs/archive/v2.5-v2.7_roadmap.md)** — Backtesting subsystem,
  defensive ML, integration backtest. *(The in-engine backtest runner was
  retired 2026-08-04 by operator decision — external report imports via the
  Models page are the ratified backtesting lane.)*

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
# Optional: EXEC_LINK_PRICE_TOL=0.0005

# Run
uvicorn main:app --host 0.0.0.0 --port 8000

# Tests
pytest tests/
```

The engine creates SQLite databases in `data/` on first startup. Schema
migrations in `core/migrations/` are applied automatically.

**Calc-linkage knobs** (`accounts.config_json`: match window, skew/price
tolerances, deviation thresholds, webhook, notification subscriptions) are
LIVE matcher inputs edited on the legacy page at `/config?tab=calc-linkage`
— linked from the React Config page header (M1, 2026-08-04). A full React
editor is a planned separate task.

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
