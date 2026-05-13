# Quantamental Engine

Pre-trade risk gatekeeper and post-trade logger for discretionary crypto
futures trading. The engine provides real-time position monitoring, ATR-based
position sizing with macro regime multipliers, and a browser-based dashboard
served as a PWA. It connects to exchanges via a vendor-neutral adapter layer
and optionally bridges to Quantower for desktop charting integration.

Currently deployed against Binance USDM-M and Bybit Linear perpetuals, with
MEXC read-only integration queued for v2.4.5.

---

## Architecture

The engine follows a **core + adapter ring** pattern established during the
v2.3.1 audit. The core engine is broker-agnostic: every external connection
(exchanges, the Quantower platform bridge, regime data sources, news feeds)
routes through a vendor-neutral adapter layer defined by Python protocols in
`core/adapters/protocols.py`.

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
         +----+----+ +---+---+ +-----+-----+
         | Binance | | Bybit | | Quantower |
         | adapter | |adapter| |  bridge   |
         +---------+ +-------+ +-----------+
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
| Frontend | Jinja2 + HTMX (server-rendered HTML fragments), PWA |
| Database | SQLite via aiosqlite (WAL mode, multi-DB split) |
| Exchange connectivity | ccxt >=4.3.20 + native WebSocket (websockets) |
| Macro data | yfinance (VIX), FRED API (yields, spreads) |
| Data processing | pandas, numpy |
| Encryption | cryptography (Fernet, AES-256 for API keys) |
| HTTP client | httpx (async) |
| Broker bridge | Quantower C# plugin via WebSocket |
| Testing | pytest + pytest-asyncio (574 tests) |

---

## Status

- **Current**: v2.3.1 (audit complete, 6 buckets closed, 40 findings resolved)
- **Next**: v2.4 (gate promotion, Redis pub/sub + WebSocket push, monthly
  drawdown, rolling-window enforcement, UI architecture improvements)
- **Queued**: v2.4.5 (MEXC integration, read-only adapter)

See [v2.4.md](v2.4.md) for the full v2.4 planning artifact.

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
│   │   └── bybit/             # Bybit Linear adapter (REST + WS)
│   ├── risk_engine.py         # ATR-based position sizing, regime multipliers
│   ├── exchange.py            # REST orchestration (fetch, enrich, TP/SL)
│   ├── ws_manager.py          # WebSocket lifecycle and dispatch
│   ├── order_manager.py       # Single-writer order enforcement
│   ├── order_state.py         # Order state machine, TP/SL matching
│   ├── data_cache.py          # In-memory data cache (positions, orders)
│   ├── state.py               # Global state (AppState, RegimeState)
│   ├── schedulers.py          # Background tasks (BOD, regime, news, ping)
│   ├── event_bus.py           # In-process async pub/sub
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
├── tests/                     # pytest suite (574 tests, 111-row baseline)
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
- **[v2.4 Planning](v2.4.md)** — Gate promotion, execution quality, and UI
  architecture roadmap.

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
