# MN-1 Phase 1: Monitoring State Enumeration

**Date**: 2026-05-12
**Source**: `core/monitoring.py`, `core/state.py` (WSStatus),
api routes, 39 loggers across codebase

---

## What Exists Today

### MonitoringService (core/monitoring.py)

Polling-based, 60s interval background task. 3 health checks:

| Check | Trigger | Action |
|-------|---------|--------|
| P&L anomaly | Equity drop >1% in 5min window | WARNING + `pnl_anomaly` event |
| WS staleness | `seconds_since_update > 45s AND not using_fallback` | WARNING + `ws_stale` event |
| Position count mismatch | In-memory count != DB snapshot | WARNING + `position_count_mismatch` event |

All write structured JSON to `data/logs/risk_engine.jsonl`.

### WSStatus — De Facto Monitoring Surface (core/state.py)

| Field | Type | Source |
|-------|------|--------|
| `connected` | bool | ws_manager on connect/disconnect |
| `last_update` | datetime | Every WS event |
| `latency_ms` | float | Exchange event timestamp vs now |
| `reconnect_attempts` | int | ws_manager reconnect (max 15) |
| `using_fallback` | bool | Fallback loop when WS stale >30s |
| `rate_limited_until` | datetime | handle_rate_limit_error() |
| `logs` | List[str] | Ring buffer (max 10) for UI |

Properties: `seconds_since_update`, `is_stale` (>30s), `is_rate_limited`.

### Health Endpoint

| Endpoint | Returns | Checks |
|----------|---------|--------|
| `GET /api/ready` | `{"ready": bool}` | `not app_state.is_initializing` (bootstrap only) |

No ongoing health validation. No degradation reporting.

### Logging (39 loggers)

24 core + 14 route + 1 root. All write to `risk_engine.jsonl` via
RotatingFileHandler. Currently the primary observability mechanism —
grep-based monitoring (as used throughout Phase 2 verification windows).

---

## What's Observable Today

### Rate-limit state (RL-1/RL-3/SR-7)

- `rate_limited_until` field on WSStatus
- `handle_rate_limit_error()` logs: "RL-1: 429 detected — REST calls paused for 120s"
- IP ban logs: "RL-1: IP banned until <timestamp>"
- `is_rate_limited` property read by reconciler, regime_fetcher, schedulers

### Connection state

- WS connected/disconnected transitions
- Fallback mode activation/deactivation
- Reconnect attempts (up to 15)
- Latency per WS event

### Data staleness

- WS: `is_stale` at 30s → fallback, MonitoringService warns at 45s
- Regime: `RegimeState.is_stale` at 90min — used locally, NOT alerted
- Position: DB vs memory comparison at 60s intervals

---

## What's NOT Observable (6 missing checks)

Cross-referenced with audit MN-1 finding ("only 3 of ~9 needed
health checks") and operational experience from verification windows:

| Subsystem | Gap | Operational evidence |
|-----------|-----|---------------------|
| **Regime data freshness** | `RegimeState.is_stale` exists but no alert fires. No health check in MonitoringService. | Regime updates observed in logs ("Regime updated: ...") but staleness invisible without grep. |
| **News feed health** | No health check. news_fetcher logs errors but no uptime/freshness metric. | Finnhub fetches visible in logs; failures would be silent unless grepped. |
| **Plugin connection health** | `platform_bridge.is_connected` exists but no health endpoint or MonitoringService check. | Plugin loss not monitored — engine falls back silently. |
| **Reconciler health** | No success/failure rate tracking. Per-symbol errors logged but no aggregate metric. | Reconciler completions visible in logs ("Reconciler: ... mfe=...") but failure rate invisible. During May 7/10 events, reconciler 429 bursts only visible through grep. |
| **Database health** | No periodic connection check. | DB unavailability would surface as per-query exceptions, not proactive detection. |
| **Rate-limit frequency** | `rate_limited_until` is binary (limited or not). No tracking of HOW OFTEN rate limits fire. | RL-4 finding (periodic 429 bursts) was only discoverable through manual log analysis. MonitoringService doesn't count rate-limit events. |

---

## Patterns From Verification Windows

The grep-based monitoring used throughout Phase 2 surfaced patterns
that should be automatically detectable:

| Pattern | How we found it | What monitoring should do |
|---------|-----------------|--------------------------|
| 429 burst clusters (RL-4) | Manual grep, timestamp analysis | Count rate-limit events per window, alert on frequency |
| 418 IP ban escalation | Manual grep for "banned until" | Immediate alert on any 418 (severity upgrade from 429) |
| Silent market data loss (WS-1) | Code review, not runtime | Detect missing mark price updates per symbol (staleness per-symbol, not just aggregate) |
| Reconciler stuck rows (AN-1) | Manual DB query | Track uncalculated row count, alert on growth |
| Deleted-function safety | Grep for function names in logs | N/A (code-level, not runtime) |

---

## Summary

| Category | Exists | Missing |
|----------|--------|---------|
| Health checks | 3 (P&L, WS stale, position mismatch) | 6 (regime, news, plugin, reconciler, DB, rate-limit frequency) |
| Health endpoint | 1 (bootstrap-only `/api/ready`) | Ongoing health summary endpoint |
| Alert routing | WARNING to log file | No real-time notification, no severity escalation |
| Per-symbol staleness | Aggregate only (one `last_update` for all WS) | Per-symbol mark price freshness |
| Event counting | None | Rate-limit frequency, reconciler success/failure rate |
