# Quantamental Risk Engine v2.1 — Revised Spec (continuing from v1.2.3 codebase)

> **Purpose:** This replaces the v2.0 spec. Codebase is already at v1.2.3 — do NOT rebuild from scratch. This document records what exists, what's incomplete, and what to do next.
>
> **For Claude Code:** if v2.0 spec contradicts this document, this wins. The code on disk is the ground truth; v2.0 was written before any code existed.

---

## 0. Where we are right now (audit of v1.2.3 codebase)

### 0.1 What's already built and working
- **Stack:** Python 3.12+, FastAPI, Jinja2, HTMX, **SQLite via aiosqlite** (NOT Postgres — see §0.4), uvloop, ccxt, yfinance, cryptography, redis-py, httpx
- **Database:** 18 tables defined in `core/database.py` covering accounts, snapshots, trades, history, OHLCV cache, regime signals/labels, backtest sessions, settings. WAL mode, ~13MB live DB with real data.
- **Risk engine:** full ATR-based sizing chain (`core/risk_engine.py`) with VWAP slippage, sector caps, eligibility checks
- **Account system:** `accounts` table with encrypted API keys (`ENV_MASTER_KEY`), `account_registry`, multi-account switching. Active account tracked in `app_state.active_account_id`.
- **Exchange layer:** Binance USD-M futures via ccxt + native WebSocket manager (`core/ws_manager.py`)
- **Regime module (partial):** signal fetchers wired (VIX/yfinance, FRED 10Y+HY, CoinGecko, Binance OI/funding, derived BTC rvol), rule-based classifier with `macro_only` and `full` modes, batch `classify_range()` writing to `regime_labels`, full UI page (`templates/regime.html`) with overview/backfill/config tabs
- **Backtest engine:** `core/backtest_runner.py` (~26K) consumes `regime_label` per trade and applies `regime_multipliers` from config
- **Quantower plugin (scaffolded):** `QuantowerRiskPlugin/` C# project with `RiskEngineConnection.cs`, `RiskEngineEventMapper.cs`, `BacktestUploader.cs`, plugin entry point. Connects via `ws://localhost:8000/ws/platform` with REST fallback.
- **Platform bridge:** `core/platform_bridge.py` with `/ws/platform`, `/api/platform/event`, `/api/platform/positions`, `/api/platform/state` already wired
- **Templates:** dashboard, calculator, history, analytics, backtest, regime, params, accounts fragment
- **Persistence:** pre-trade log (CSV + DB), execution log, trade history, position changes, equity cashflows, exchange history, snapshots

### 0.2 What's incomplete (the actual TODO list)

**Regime module — major gaps:**
1. **Live regime is not wired into sizing.** `core/risk_engine.py` does not read regime state. `app_state` has no `current_regime` field. The classifier writes to a table; live sizing doesn't read from it. This is the single highest-leverage missing piece — it's the entire reason the regime module exists.
2. **No "current regime" computation.** `classify_range()` is a batch operation over historical signals. There is no `compute_current_regime()` that runs the classifier against the latest available signal values to produce a live label.
3. **No regime refresh scheduler.** `main.py` has no periodic task that fetches fresh signals and re-classifies. A signal fetched once during backfill goes stale.
4. **BTC dominance fetcher stores raw BTC market cap, not dominance.** `core/regime_fetcher.py` lines ~218–222 admits this. The classifier's `btc_dom_change_*` thresholds therefore don't behave as their names imply. Either (a) find a working free total-mcap endpoint, or (b) replace the signal with ETH/BTC ratio (Binance data already on hand).
5. **Classifier output is just a string.** v2.0 spec called for `{regime, confidence, stability_bars, sizing_multiplier}`. Currently only the label is produced; multipliers live in config and are looked up downstream.
6. **`REGIME_MULTIPLIERS` not in config.** The values are hardcoded in `templates/regime.html` (1.2 / 1.0 / 1.0 / 0.7 / 0.4) and in the backtest config. Centralize in `config.py`.

**Minor / housekeeping (resolved into Phase 0):**
7. Stray file `=0.2.36` at project root → delete (Phase 0.4)
8. No `tests/` directory → add minimal scaffold + smoke test (Phase 0.5), broaden in Phase E1
9. No PWA shell installed → Phase D
10. `requirements.txt` no version pinning → `uv pip compile` lockfile (Phase 0.4)
11. `debug-3bf805.log` and `_debug_log()` calls in `core/database.py` → verify and remove (Phase 0.4)
12. Accounts UI fragment is 66 lines (just a picker, not the v2.0 §7.5 overview) → not a v2.1 priority; defer to v3.0 if multi-account use grows
13. Redis dep + warning on every startup → not unused; the bus is central with 6 callers, but a graceful in-process fallback handles everything. Rename to `event_bus`, strip Redis layer, keep pattern (Phase 0.2)
14. uvloop installed but unused on Windows → keep with platform marker (Phase 0.3) so it's free perf on Linux/WSL and transparently skipped on Windows

### 0.3 What was in v2.0 spec that no longer applies
- **"Paper accounts as `paper:*`"** — moot. The engine already runs against a real read-only Binance account, which serves the same role (live data, no execution risk if API key has read-only perms). Don't build a separate paper account abstraction.
- **`broker_account_id` / `terminal_links` schema** — not implemented; the simpler `accounts(id, name, exchange, ...)` schema works for current scope. Defer the broker/terminal split until you actually have a second broker (Quantower → IBKR vs Quantower → AMP).
- **`is_paper` field** — not needed if we don't introduce paper accounts.
- **Phase 6 "Quantower bridge last"** — already partially built. Reorder: finish regime live wiring first, then finish Quantower plugin (which is mostly there).

### 0.4 SQLite vs Postgres decision (final)
**Stay on SQLite.** Reasons:
- 13MB DB with real data already in production. Migration is destructive work for zero current benefit.
- Single-process, single-user, single-machine — exactly SQLite's sweet spot.
- WAL mode is already enabled.
- Numeric precision concern from v2.0 §spec discussion: address by using Python `Decimal` in critical sizing paths and validating with unit tests, NOT by switching DB engines.
- Revisit only if (a) you ever need multi-process writers, or (b) any single table crosses 50M rows.

---

## 1. Core Philosophy (unchanged from v2.0)

The engine is **not** an auto-trader. It is a **pre-trade gatekeeper + post-trade logger** for a discretionary pilot.

- I identify trades manually.
- The engine decides: (a) am I allowed to take this trade right now, (b) what size, (c) log it with full context.
- The engine **refuses** trades that violate risk rules. It does not "suggest" — it blocks.
- Orderflow reads stay discretionary. The regime classifier is the only thing that goes through statistical validation.

**Invariant:** every trade passes through the engine first. No engine approval = no trade.

---

## 2. Stack (current — do not change)

| Layer | Choice | Status |
|---|---|---|
| Language | Python 3.12 | ✅ in use |
| Async | asyncio + uvloop | ✅ in use (uvloop kept with `sys_platform != 'win32'` marker — Windows skips it) |
| Web | FastAPI | ✅ in use |
| Frontend | HTMX + Jinja2 | ✅ in use |
| **DB** | **SQLite (aiosqlite, WAL mode)** | ✅ in use — keep, do not migrate |
| Caching | in-process (`app_state` singleton) | ✅ in use |
| ~~Redis~~ | ~~declared in requirements~~ | ❌ dropping in Phase 0.2 — pub/sub pattern survives as in-process `event_bus` |
| Exchange | ccxt + native WebSocket | ✅ in use |
| TradFi data | yfinance | ✅ in use |
| Macro data | FRED API | ✅ in use (CoinGecko removed when btc_dominance dropped — Phase B1) |
| Credential encryption | cryptography (`ENV_MASTER_KEY`) | ✅ in use |
| Broker bridge | Quantower C# plugin (scaffolded) | ⚠️ scaffolded, finishing in Phase C |
| PWA shell | manifest + service worker | ❌ not installed yet, Phase D |

**Do NOT introduce in v2.1:** Postgres, TimescaleDB, Kafka, additional message brokers, alternative web frameworks, ML libraries (sklearn/torch) for regime work — keep the rule-based classifier until §5 below has 6+ months of live tagged trades.

---

## 3. v2.1 Build Order (continuing from v1.2.3)

### Phase 0 — Foundation prep (do these first, they're cheap and unblock everything)

**0.1 Add `broker_account_id` to accounts schema**
- Migration `core/migrations/000_add_broker_account_id.py`: `ALTER TABLE accounts ADD COLUMN broker_account_id TEXT NOT NULL DEFAULT ''`
- One-shot backfill: on startup, for any account with empty `broker_account_id`, pull from Binance API (account UID) and persist
- Update `account_registry` + accounts API + accounts UI fragment to accept/display the field
- This unblocks future broker integration without changing anything live today

**0.2 Drop Redis dependency — rename to `event_bus`, keep pub/sub pattern**

**Investigation finding:** `redis_bus` is architecturally central (6 callers across `main.py`, `api/routes.py`, `core/ws_manager.py`, `core/exchange.py`, `core/data_logger.py`, `core/handlers.py`) with 5 event channels. The original author built a graceful in-process fallback inside `RedisBus.publish()` — when Redis is unavailable, `publish()` directly awaits registered handlers via `_dispatch()`. Everything has been running on the fallback path the whole time.

**Approach: rename + simplify, do NOT remove the pub/sub pattern.** The bus is genuinely useful (decouples publishers from handlers, single chokepoint for logging/metrics, easy handler registration). Keep it; just remove the Redis layer that never works anyway.

Concrete steps:
- Rename `core/redis_bus.py` → `core/event_bus.py`
- Strip out the `redis.asyncio` import, `_pub_client`/`_sub_client`/`_pubsub` fields, `connect()` body, `run()` method, `close()` Redis-specific lines
- Class becomes a pure in-process pub/sub: just `_handlers: Dict[str, List[Handler]]`, `subscribe()`, `unsubscribe()`, `publish()` → `_dispatch()`
- Channel constants (`CH_ACCOUNT_UPDATED`, etc.) stay unchanged — they're useful as namespacing
- Module singleton renamed: `redis_bus` → `event_bus`
- Sed across all 6 caller files: `from core.redis_bus import redis_bus` → `from core.event_bus import event_bus`, and `redis_bus.publish/subscribe/...` → `event_bus.publish/subscribe/...`
- In `main.py` lifespan: remove `await redis_bus.connect()` and the `_spawn(redis_bus.run(), ...)` call. `event_bus` needs no startup or background task — it's purely synchronous registration + async dispatch on publish.
- Remove `redis>=5.0.0` from `requirements.txt`
- Remove `REDIS_URL` from `config.py`
- The `redis-py` dep is gone, the connection-failed warning is gone, every event continues to flow through exactly the same handlers

Test after: every behavior should be identical. WS account updates still trigger reconciler, risk calculations still log, etc. If anything breaks, it's a publisher/subscriber mismatch elsewhere — investigate before declaring complete.

**0.3 uvloop — keep with platform marker, not required**
- Update `requirements.txt`: `uvloop>=0.21.0; sys_platform != 'win32'`
- This way Windows installs don't even attempt it; Linux/WSL get it for free
- The existing `try/except ImportError` in `main.py` already handles missing uvloop gracefully — no code change needed

**0.4 Cleanup**
- Delete stray `=0.2.36` file at project root
- Verify and remove `_debug_log()` + `debug-3bf805.log` if no longer needed
- Pin requirements: `uv pip compile requirements.txt -o requirements.lock` (commit both)

**0.5 Add `tests/` directory + smoke test**
- `tests/__init__.py`, `tests/conftest.py` with pytest config
- One smoke test: import all modules in `core/`, assert no import errors. This catches the most common regressions cheaply.

### Phase A — Regime → live sizing wiring (highest priority)

**Goal:** make the regime classifier actually affect risk sizing. This unlocks the entire purpose of the regime module.

**A1. Add live regime state to `app_state`**
- New dataclass `RegimeState` in `core/state.py` with: `label`, `multiplier`, `mode`, `confidence` (placeholder 1.0 for now), `stability_bars` (placeholder 0), `signals_snapshot` (dict), `computed_at` (UTC timestamp), `is_stale` (property — true if older than N minutes).
- Add `app_state.current_regime: Optional[RegimeState] = None`.
- Reset cleanly in `reset_for_account_switch()` (regime is account-independent — actually, **don't** reset it, since macro signals are global. Note this in code comment.)

**A2. Centralize multipliers in `config.py`**
- New constant `REGIME_MULTIPLIERS = {"risk_on_trending": 1.2, "risk_on_choppy": 1.0, "neutral": 1.0, "risk_off_defensive": 0.7, "risk_off_panic": 0.4}`
- New constant `REGIME_REFRESH_INTERVAL_SEC = 600` (10 min default)
- Update `templates/regime.html` to read from API instead of hardcoding.
- Update `backtest_runner.py` to read from `config.REGIME_MULTIPLIERS` if not overridden.

**A3. Add `compute_current_regime()` in `core/regime_classifier.py`**
- Reads latest available value of each signal from `regime_signals` (most-recent date <= today).
- Falls back to `macro_only` mode if `agg_oi_change` or `avg_funding` are stale (> 24h).
- Returns a populated `RegimeState`.
- Does NOT write to `regime_labels` (that table is daily historical, not live state).

**A4. Background refresh task in `main.py`**
- New async task `regime_refresh_loop()` runs every `REGIME_REFRESH_INTERVAL_SEC`:
  1. Compute current regime from existing signal data
  2. Update `app_state.current_regime`
  3. Log a line if the label changed since last refresh
- Started in the lifespan startup alongside other background tasks.
- Note: this loop does NOT refetch signals from external APIs. That's a **separate** slower scheduler (see A5).

**A5. Signal refresh scheduler (slower, separate)**
- Add `signal_refresh_loop()` running once per hour: pulls VIX (yfinance), FRED series (US10Y, HY spread), and once per 4–8h pulls Binance OI + funding.
- Update timestamps so `compute_current_regime()` can detect stale signals.
- Failures non-fatal — log and continue. The classifier handles missing signals gracefully.

**A6. Wire multiplier into `calculate_position_size()`**
- Read `app_state.current_regime.multiplier` (default 1.0 if None or stale).
- Apply to `risk_usdt`: `risk_usdt = individual_risk × total_equity × regime_multiplier`.
- **NOT behind a startup feature flag.** Regime sizing is on by default for all calculations.
- Per-trade override via the **calculator UI** (see A7): a checkbox "apply regime multiplier" defaults to ON. When user unchecks it, the calc result shows BOTH numbers — `size_with_regime` and `size_without_regime` — so the user sees what they're overriding.
- The decision dict returned exposes: `regime_label`, `regime_multiplier`, `regime_applied` (bool — false when user overrode), `size_without_regime` (always populated for reference), `regime_stale` (bool — true if `current_regime.is_stale`).
- Pre-trade log records: `regime_label`, `regime_multiplier_applied`, `regime_override` (bool — true if user manually unchecked). This makes post-hoc analysis possible: "did my overrides do better or worse than letting the regime size?"

**A7. UI surfacing**
- Calculator page (`templates/calculator.html`):
  - Live regime badge + multiplier shown above the size result
  - "Apply regime multiplier" checkbox, default ON
  - When ON: result shows `size` (regime-adjusted) prominently
  - When OFF: result shows BOTH `size_without_regime` and `size_with_regime` side-by-side, so the user always sees what the regime would have suggested
  - Stale indicator: if `regime_stale = true`, multiplier auto-falls back to 1.0 and a warning shows ("regime data > N min old, ignoring multiplier")
- Regime page (`templates/regime.html`) gains a "Live Now" panel above the historical timeline showing the live `current_regime` (distinct from `get_latest_regime_label()` which reads yesterday's daily bucket).
- Params page (`templates/params.html`): no toggle here — regime sizing is per-trade, not global. But add a read-only display of current `REGIME_MULTIPLIERS` so the user knows what's being applied.

**A8. Tests**
- Create `tests/` directory with `pytest`.
- `tests/test_regime_classifier.py`: rule coverage — for each regime, construct a signal dict that should produce that label, assert it does. Edge cases: missing signals, threshold boundaries.
- `tests/test_risk_engine.py`: position sizing math with and without regime multiplier; verify `regime_applied = False` when feature flag is off.
- `tests/test_compute_current_regime.py`: feed synthetic `regime_signals` rows, assert correct `RegimeState` produced.

### Phase B — Regime data quality

**B1. Remove BTC dominance signal entirely**

The current implementation stores raw BTC market cap and the free CoinGecko endpoint doesn't provide reliable historical total-mcap. Rather than fix it, drop it — the remaining macro signals (VIX, US10Y, HY spread, BTC rvol, OI change, funding) are sufficient.

Concrete changes:
- Delete `fetch_btc_dominance()` from `core/regime_fetcher.py`
- Remove `btc_dominance` from `ALL_SIGNALS` and `MACRO_ONLY_SIGNALS` in `core/regime_classifier.py`
- Strip BTC dominance branches from `classify_regime()` (the `is_dom_declining` and `dom_change_pct > btc_dom_change_bear` blocks)
- Remove `btc_dom_change_bull` and `btc_dom_change_bear` from `config.REGIME_THRESHOLDS`
- Remove the BTC dominance card from `templates/regime.html` and its endpoint usage
- Remove `COINGECKO_API_KEY` from config and `.env.example` if no other CoinGecko call remains
- Migration `core/migrations/001_drop_btc_dominance.py`: `DELETE FROM regime_signals WHERE signal_name = 'btc_dominance'`

After removal, re-verify the rule tree still produces all 5 regimes for plausible signal combinations. May need to relax the `risk_on_trending` rule in macro_only mode (currently uses `is_low_vix and is_vol_compressed and is_dom_declining` — the dom_declining clause needs replacement or removal).

**B2. Add `confidence` and `stability_bars` to classifier output**
- `confidence`: simple heuristic — fraction of expected signals that were present and within plausible ranges. 1.0 if all signals present and non-extreme; lower as signals go missing or hit threshold edges.
- `stability_bars`: count of consecutive prior dates with the same label in `regime_labels`. Cheap query (`ORDER BY date DESC LIMIT 30`).
- Wire both into `RegimeState` and the calculator UI.

**B3. Optional: regime transition matrix view**
- Add `/api/regime/transitions` returning a 5x5 transition probability matrix from `regime_labels`.
- Add a panel on the regime page rendering it. Useful for sanity-checking thresholds: if every regime flips daily, thresholds are too tight; if one regime dominates 90%, they're too loose.

### Phase C — Quantower plugin completion

The plugin scaffolding is in place. Finish the integration so live trading can begin.

**C1. Validation spike (1 day, before more code)**
- Build the plugin, install in Quantower, run end-to-end:
  - Subscribe to fills + position changes
  - Verify events arrive at `/ws/platform`
  - Verify `/api/platform/state` returns risk state correctly to the plugin
- Document any SDK quirks discovered. Don't write more bridge code until a real fill round-trips.

**C2. Reconciliation on connect**
- On WS connect from plugin, engine pulls Quantower's current position snapshot via REST (already a route exists) and overwrites local position state. Never trust local DB over live broker truth.
- On WS disconnect, engine flips into "standalone monitoring" mode — last-known positions, marked to last Binance quote, clearly labeled stale.

**C3. Account identity — add `broker_account_id` now**

Add now (Phase C, but before Quantower wiring), not later. It's a 5-minute schema migration and makes account identity unambiguous.

Concrete changes:
- Migration `core/migrations/002_add_broker_account_id.py`: `ALTER TABLE accounts ADD COLUMN broker_account_id TEXT NOT NULL DEFAULT ''`
- Update `account_registry.create_account()` and update endpoints to accept the field
- For existing rows, populate via Binance: pull the account UID from the API on next refresh and write back. One-shot backfill script that runs once on startup if any row has empty `broker_account_id`.
- UI: show broker_account_id on the accounts list as a small monospace badge

When Quantower fills arrive, the bridge maps `(exchange, broker_account_id)` to internal `accounts.id`. If unmatched, create a new account row with default name `"<exchange>:<broker_account_id>"` and flag for the user to rename.

**C3.1 Defer `terminal_links` table.** The terminal_links concept (tracking which terminal — Quantower vs Sierra vs NinjaTrader — feeds a given account) is genuinely useful but only matters once you have a 2nd terminal. Defer until then. For now, just record `source_terminal` as a TEXT field on each fill/event for debugging.

**C4. UI polish**
- Account selector shows connection status (live via plugin / standalone / disconnected).
- A persistent banner appears when in standalone mode so you never confuse estimated P&L with broker-truth P&L.

### Phase D — PWA shell

**D1. Install minimal PWA**
- `templates/manifest.json` — name, icons (192, 512 PNG, generate from existing favicon if any), `display: standalone`, theme color matching dark UI
- `static/service-worker.js` — network-first for `/api/*`, `/hx/*`, `/ws/*`; cache-first for `/static/*`
- `<head>` of `base.html`: link manifest, register SW
- Two FastAPI routes: `GET /manifest.json` and `GET /service-worker.js` with correct MIME types and `Service-Worker-Allowed: /` header

**D2. Install + autostart**
- Install via Chrome/Edge address bar.
- Document Windows autostart: drop the installed PWA shortcut into `shell:startup` (or write a `.bat` that starts uvicorn then opens the PWA).

### Phase E — Hygiene (after the above)

**E1. Tests broaden out**
- Beyond Phase A8 unit tests: add `tests/test_database.py` covering migrations, upserts, regime queries
- Smoke test: spin engine in test mode against a fixture SQLite DB, assert all routes return 200
- Optional: GitHub Actions yaml for CI even if you don't run it remotely

**E2. Documentation**
- Create `ARCHITECTURE.md` at repo root: a one-page tour of `core/`, `api/`, `templates/`, `data/` — for future-Aryo and any AI assistant joining the project
- Move this spec into the repo as `SPEC_v2.1.md`
- Add a "Migrations" section to `ARCHITECTURE.md` explaining the `core/migrations/` lightweight pattern

**E3. Lock file maintenance**
- Schedule a monthly `uv pip compile --upgrade` to keep deps current
- Document in `ARCHITECTURE.md` how to update deps safely

---

## 4. What is explicitly NOT in v2.1

- ❌ Postgres migration
- ❌ Paper-account abstraction (real read-only Binance account already serves this role)
- ❌ ML regime classifier (rules only; revisit after ≥6 months of live tagged trades)
- ❌ Full `terminal_links` / `broker_account_id` schema (deferred until 2nd broker arrives)
- ❌ Auto-order-routing (engine remains a gatekeeper, not an executor)
- ❌ L2/L3 orderflow backtester
- ❌ Mobile-tuned PWA layout
- ❌ Multi-user auth
- ❌ Cloud deployment

---

## 5. v3.0 Roadmap (unchanged from v2.0 — for reference)

Carry forward the deferred-features list from v2.0 §15. Highlights worth re-stating now that v2.1 is closer:

- Auto-routing of orders from engine to broker (only after months of click-to-copy proves the sizing logic)
- ML regime classifier (GMM, HMM, supervised) trained against live tagged trades
- Cross-account portfolio aggregate dashboard with FX normalization
- Sierra Chart plugin (mirror of Quantower bridge contract)
- Regime-conditional parameter optimization
- Telegram/Discord alerts on risk events + regime transitions
- Trade review UI with chart replay
- Engine as Windows Service (currently launched via uvicorn + `launch.bat`)
- Postgres migration *if and only if* one of the SQLite triggers in §0.4 fires

**v3.0 entry criteria:**
1. v2.1 in daily use ≥3 months without structural bugs
2. ≥100 real trades logged with regime tags
3. Any v3.0 feature has a measured problem it solves, not hypothetical

---

## 6. Conventions (reaffirmed + new)

- Type hints on all new code; type-check the regime module with `mypy --strict` first.
- All monetary values: `Decimal` in critical paths (sizing, P&L), `float` in display-only paths. Add a typed wrapper module.
- All timestamps UTC in storage, local-zone only at the display layer.
- Pydantic models on every API boundary.
- No bare `except:`. Log and re-raise or handle specifically.
- Secrets via `.env` + `ENV_MASTER_KEY` for credential encryption (already in place).
- Tests live in `tests/`. Each new module gets at least a smoke test.
- Migrations: any schema change goes in `core/migrations/NNN_description.py` and is applied on startup if not yet recorded in `migrations_log`. SQLite-style — no Alembic needed at this scale.

---

## 7. Resolved decisions (these are no longer open)

1. **Regime sizing — on by default, per-trade override on the calculator page.** No global startup feature flag. The calculator UI has a "apply regime multiplier" checkbox (default ON); when unchecked, the result panel shows both `size_with_regime` and `size_without_regime` so the user always sees what they're overriding. Pre-trade log records `regime_multiplier_applied` and `regime_override` for post-hoc analysis.

2. **BTC dominance — drop entirely.** Not fix, not replace. Phase B1 removes it from fetcher, classifier, schema, UI, and config. Remaining macro signals are sufficient.

3. **Redis — drop the dep, keep the bus pattern.** Phase 0.2. The bus has 6 callers and 5 event channels, with a graceful in-process fallback that's been running the whole time anyway. Rename `redis_bus` → `event_bus`, strip the Redis-specific code, keep the pub/sub interface. All call sites change one import line.

4. **uvloop — keep with platform marker.** Phase 0.3. Free perf on Linux/WSL, transparently skipped on Windows. Existing import-guard pattern in `main.py` already handles it gracefully.

5. **`broker_account_id` — add now.** Phase 0.1. Five-minute migration. Unblocks future broker work without changing anything live today.

6. **`terminal_links` table — defer.** Only matters with a 2nd terminal (Sierra, NinjaTrader). Add when needed. For now, log `source_terminal` as a TEXT field on each fill/event for debugging.

---

**End of spec. Treat the codebase as ground truth; this document is the diff to apply on top of it.**
