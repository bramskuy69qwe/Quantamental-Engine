# MN-1 Phase 2: Monitoring Expansion Design

**Date**: 2026-05-12
**Depends on**: Phase 1 enumeration

---

## 1. Monitoring Data Model

### MonitoringEvent

```python
@dataclass
class MonitoringEvent:
    kind: str                          # e.g. "regime_stale", "rate_limit_burst"
    severity: str                      # "info" | "warning" | "critical"
    message: str                       # Human-readable description
    timestamp: datetime                # UTC
    resolved: bool = False             # Auto-clears when condition clears
    resolved_at: Optional[datetime] = None
    context: Dict[str, Any] = field(default_factory=dict)  # Check-specific data
```

**Severity semantics**:
- **info**: Noteworthy but no action needed (regime transition, plugin
  reconnect)
- **warning**: Degraded but operational (regime stale, news feed down,
  rate-limit event)
- **critical**: Action required or data integrity at risk (DB unreachable,
  all data feeds stale, IP ban)

### Storage

**In-memory ring buffer** (max 100 events) on MonitoringService. Serves
two purposes:
1. UI reads active events via API endpoint
2. Recent history for pattern detection (e.g., rate-limit burst frequency)

**Persisted to log**: Every new MonitoringEvent also writes a structured
JSON log entry via the existing `monitoring` logger — lands in
`risk_engine.jsonl` for grep-based analysis.

No separate DB table. Events are ephemeral signals, not historical data.

### Consumption

**API endpoint**: `GET /api/monitoring/events` → returns active
(unresolved) events as JSON array. Dashboard polls this.

**In-UI**: Banner on dashboard showing worst active event (same pattern
described in `connection_status_ui.md` Phase A — single dismissible
banner, worst severity wins).

**Future webhook**: MonitoringEvent's shape is forward-compatible with
webhook payload:
```json
{
  "kind": "rate_limit_burst",
  "severity": "warning",
  "message": "5 rate-limit events in 30 minutes",
  "timestamp": "2026-05-12T06:56:23Z",
  "context": {"count": 5, "window_minutes": 30}
}
```
Webhook dispatch not built in MN-1 — data model supports it when needed.

---

## 2. Per-Check Design (6 New Checks)

### Check 4: Regime data freshness

| Aspect | Value |
|--------|-------|
| Signal source | `app_state.regime_state.is_stale` (already exists, threshold 90 min from `config.REGIME_STALE_MINUTES`) |
| Evaluation | `regime_state.is_stale is True` |
| Threshold | **90 minutes** — matches existing `config.REGIME_STALE_MINUTES`. Rationale: regime refresh runs hourly (TradFi) + every 4h (crypto). 90 min means 1 missed TradFi cycle. |
| Polling interval | 60s (default — regime changes slowly) |
| Severity | **warning** — regime falls back to neutral multiplier (1.0x), sizing still works but not regime-adjusted |
| Auto-resolve | Yes — when `regime_state.is_stale` becomes False |

### Check 5: News feed health

| Aspect | Value |
|--------|-------|
| Signal source | DB query: most recent news row timestamp vs now |
| Evaluation | No news rows inserted in last `threshold` minutes |
| Threshold | **60 minutes** — Finnhub polls every ~5-15 min (observed in verification logs). 60 min = 4+ missed cycles. Rationale: news_fetcher logs show "Finnhub news: upserted 100 items" every 5-15 min during normal operation. |
| Polling interval | 60s (default) |
| Severity | **info** — news has no financial calculation impact (per audit: Group 5, lowest priority) |
| Auto-resolve | Yes — when fresh news row appears |

### Check 6: Plugin connection health

| Aspect | Value |
|--------|-------|
| Signal source | `platform_bridge.is_connected` (bool property, checks `len(_ws_clients) > 0`) |
| Evaluation | `not platform_bridge.is_connected` AND engine previously had plugin connected (avoids alerting during standalone mode) |
| Threshold | Immediate (binary: connected or not) |
| Polling interval | 60s (default) |
| Severity | **warning** — plugin loss triggers fallback to direct exchange paths. Data still flows but at reduced fidelity (WS instead of Quantower fills). |
| Auto-resolve | Yes — when plugin reconnects |
| Special case | If engine has NEVER had plugin connected (standalone mode), skip this check entirely. Track via `_ever_connected` flag set on first plugin hello. |

### Check 7: Reconciler health

| Aspect | Value |
|--------|-------|
| Signal source | DB query: count of `exchange_history` rows where `backfill_completed=0 AND open_time>0 AND trade_key NOT LIKE 'qt:%'` |
| Evaluation | Uncalculated row count > threshold |
| Threshold | **20 rows** — normal operation has 0-5 pending rows (new trades waiting for settle delay). 20 means multiple symbols stuck. Rationale: AN-1 showed SIRENUSDT/ONUSDT stuck rows; 20 is well above normal churn. |
| Polling interval | **300s (5 min)** — DB query, not time-critical. Justification: reconciler runs on trade-close events, not on polling interval. Checking more often than 5 min adds DB load without benefit. |
| Severity | **warning** — reconciler failure means MFE/MAE not computed, analytics degraded but trading unaffected |
| Auto-resolve | Yes — when count drops below threshold |

### Check 8: Database health

| Aspect | Value |
|--------|-------|
| Signal source | Simple `SELECT 1` on the DB connection |
| Evaluation | Query fails or times out (>5s) |
| Threshold | **Query timeout 5s** — SQLite on local disk should respond in <10ms. 5s is generous. Rationale: local SQLite, not network DB. Any >5s response indicates disk issue or lock contention. |
| Polling interval | **120s (2 min)** — less frequent than data checks. Justification: DB failure is catastrophic (all reads/writes fail) and self-evident from other checks failing. This is a canary, not primary detection. |
| Severity | **critical** — DB loss means no persistence, no snapshot recovery, no trade history |
| Auto-resolve | Yes — when query succeeds again |

### Check 9: Rate-limit frequency

| Aspect | Value |
|--------|-------|
| Signal source | In-memory counter: increment on each `handle_rate_limit_error()` call |
| Evaluation | Count of rate-limit events in rolling window exceeds threshold |
| Threshold | **5 events in 30 minutes** — verification window data: the May 10 burst had 5 clusters in ~30 min. Normal operation has 0. Rationale: 1-2 isolated 429s are expected under load; 5+ in 30 min indicates systematic overload (RL-4 pattern). |
| Polling interval | 60s (default — checks counter) |
| Severity | **warning** at 5 events; **critical** at any 418 (IP ban) |
| Auto-resolve | Yes — when rolling window clears |
| Implementation note | `handle_rate_limit_error()` increments a thread-safe counter. MonitoringService reads and evaluates. Counter stores (timestamp, was_ban) tuples for window analysis. |

---

## 3. Architecture

### Recommendation: Stay one MonitoringService

**Justification**: 9 checks (3 existing + 6 new) is well under the
15-20 split threshold. All checks share:
- Same polling loop infrastructure
- Same MonitoringEvent emission pattern
- Same log sink
- Same API surface

Splitting into DataHealth/ConnectionHealth/RateLimit would create 3
files with ~3 checks each — more import surface and coordination
overhead than a single flat service.

**When to split**: If checks grow past ~15, or if a check requires a
fundamentally different execution model (e.g., event-driven instead of
polling). Neither applies today.

### Check execution order

Within each 60s cycle:
1. P&L anomaly (existing)
2. WS staleness (existing)
3. Position mismatch (existing)
4. Regime freshness (new — fast, reads in-memory state)
5. News feed health (new — DB query, lightweight)
6. Plugin connection (new — fast, reads in-memory bool)
7. Rate-limit frequency (new — reads in-memory counter)
8. Reconciler health (new — runs every 5th cycle, DB query)
9. DB health (new — runs every 2nd cycle, `SELECT 1`)

Checks 8 and 9 run less frequently via cycle counter to avoid
unnecessary DB load.

---

## 4. Alert Surfacing

### In-UI display

Add to dashboard template (existing `ws_status` fragment area):
- If any active MonitoringEvent with severity >= warning exists,
  show a banner: `"{kind}: {message}"` with severity-appropriate styling
  (yellow for warning, red for critical).
- Banner auto-dismisses when event auto-resolves.
- Clicking banner links to `/api/monitoring/events` (JSON detail).

### Persistent log entries

Every MonitoringEvent writes a structured JSON log entry:
```json
{
  "ts": "...", "level": "WARNING", "logger": "monitoring",
  "message": "ALERT: regime data stale (95 min since last classification)",
  "event": "regime_stale", "severity": "warning",
  "context": {"age_minutes": 95, "threshold_minutes": 90}
}
```

This preserves grep-based analysis (the proven pattern from verification
windows) while adding structured fields for future processing.

### Future webhook signature

```python
async def _dispatch_webhook(event: MonitoringEvent) -> None:
    """Placeholder — not implemented in MN-1."""
    # POST to config.MONITORING_WEBHOOK_URL with:
    # {kind, severity, message, timestamp, context}
    pass
```

Define the function signature and the config key now. Wire later when
external routing is needed.

---

## 5. Commit Strategy

### Split into 2 commits

**Commit 1**: MonitoringEvent data model + API endpoint + rate-limit
counter infrastructure + UI banner placeholder.

Justification: the data model is the foundation. The API endpoint and
counter are consumed by all 6 checks. Landing these first gives a
testable surface before the checks themselves.

**Commit 2**: All 6 new checks added to MonitoringService.

Justification: the checks are independent of each other (no
dependencies between them) but all depend on Commit 1's data model.
Landing them together is safe because each is a self-contained
`_check_*` method with its own test.

---

## Migration Cost Estimate

| Change | Lines |
|--------|-------|
| MonitoringEvent dataclass | +15 |
| In-memory event ring buffer + emit/resolve | +30 |
| API endpoint `/api/monitoring/events` | +15 |
| Rate-limit counter in handle_rate_limit_error | +10 |
| 6 new check methods | +90 |
| Tests (2 per check + data model tests) | +80 |
| UI banner template update | +10 |
| **Total** | **~250** |
