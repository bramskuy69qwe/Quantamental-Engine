# Changelog

## [v2.4.3] — 2026-05-19

### Summary

Bundle A closure release — wraps the Phase 5 UX primitive chapter into
one tag. 5 tasks since v2.4.2 (Tasks 121-125), 1 HIGH + 3 MEDs full + 2
MEDs partial resolved. Five reusable primitives shipped with a
documented decision-tree convention. Combined ledger drops from 82
active at v2.4.2 to 76 active at v2.4.3.

This is the UX-polish chapter — no money-at-risk or hardening work.
v2.4.1 closed CRIT/HIGH-tier trading-loop work; v2.4.2 closed
adapter-hardening + credential surface; v2.4.3 closes the UX primitive
foundation.

### Resolved (HIGH)

- **FE-HIGH-001** (Task 121) Plugin OFF indicator misread — header
  "◌ Plugin · OFF · +437ms" composite that the eye grouped into
  "engine offline · 437ms latency" replaced by the StatusIndicator
  primitive showing `Quantower · Connected` (green) or `Quantower
  · Disconnected` (red). WS-status latency display kept in its own
  cluster to the right; no longer visually grouped with the plugin
  state.

### Resolved (MED)

- **FE-MED-001** (Task 122) Analytics overview card spacing — 5 cards
  on Analytics → Overview drifted to loose 10px×12px rhythm vs
  History's tight 8px×10px. Card primitive built (slot-content via
  `{% call %}` + `caller()`); all 5 cards migrated to tight rhythm
  matching History.
- **FE-MED-002** (Task 123) History table row drift — TableRow
  primitive built (open/close pair for sibling-list bodies). All 3
  history tables migrated (Position History, Order History, Trade
  History/fills). Trade History SIDE column split into ACTION
  (Open/Close) + SIDE (LONG/SHORT) per calibration #3 — each cell
  now single-coloured, matching Position History rhythm.
- **FE-MED-006** (Task 124) 7 empty-state treatments consolidated —
  EmptyState primitive built (plain macro, info / action tones).
  9 template-side migrations (5 history tables, dashboard, 3
  analytics fragments) + 1 JS-side migration (Regime not-backfilled
  cards). JS-consumable primitive pattern surfaced: client-side JS
  emits the same `.es-*` class structure as the macro.
- **FE-MED-007** (Task 125, partial) PeriodSelector visual
  normalization — primitive built; Regime global "All:" selector +
  History page presets + Regime per-card JS-rendered selectors all
  migrated to the same `.ps + .preset-btn` class structure.
  Precedence-rule operator-UX question (which selector wins when
  global and per-card both set?) explicitly deferred.
- **FE-MED-008** (Task 124, partial) Regime not-backfilled cards —
  visual treatment normalized via EmptyState action tone (BTC
  Market Cap + Aggregate OI Change cards). Feature-level
  pre-select-signal-in-Backfill deferred (data/feature work, not
  UI primitive).

### Infrastructure / architecture

- **5 UX primitives shipped** in `templates/primitives/`:
  - StatusIndicator (Task 121) — plain macro for parameter-driven
    state displays. Severity vocab: `success / warning / error /
    info / neutral` mapped to existing CSS vars.
  - Card (Task 122) — slot-content panel via `{% call %}` +
    `caller()`. Title + subtitle + body + footer, composes on
    existing `.card` + `.card-p8` utility classes.
  - TableRow (Task 123) — sibling-list-slot via open/close pair
    (`tr_open` + `tr_close`). Hover + clickable + selected states
    without disturbing cell typography.
  - EmptyState (Task 124) — plain macro, info / action tones,
    optional CTA (button or anchor).
  - PeriodSelector (Task 125) — plain macro, options list +
    current value, two transition modes (JS template / HTMX
    template).
- **Pattern conventions documented** in `templates/primitives/README.md`:
  - Decision tree: contiguous block → `{% call %}` + `caller()`;
    sibling list → open/close pair; parameter-driven → plain macro.
  - Class-prefix table per primitive (`.si-*`, `.card-*`, `.tr-p-*`,
    `.es-*`, `.ps-*`).
  - Jinja2 nested-comment gotcha + compile-render-before-commit
    discipline documented (MED-047 cross-reference).
  - "Compose on existing utility classes" convention — primitives
    don't reinvent typography or spacing utilities, they build
    structure atop what exists.
- **CLAUDE.md updated** with the Jinja2 nested-comment gotcha alongside
  MED-047 template-wiring discipline. Reinforces "compile-render
  before committing" rule.
- **JS-consumable primitive pattern** established (Tasks 124 + 125):
  when a primitive's consumer is JS-rendered (Regime chart cards), the
  JS emits the same class structure the macro emits. Primitive CSS
  becomes a shared visual language across server- and client-rendered
  surfaces.

### Reframed / clarified

- Audit-doc clarification: FE-MED-002's "Trade History" screenshot
  evidence (`ss_4313zsgql`) maps to `fills_table.html` (whose section
  label is `Trade History (N entries)`), not `trade_history_table.html`
  (the closed-trades summary). Path made explicit in the audit-doc
  entry.

### Audit ledger state at tag

**76 active findings** — 0 CRIT / 2 HIGH / 47 MED / 27 LOW.

Remaining HIGHs (both architecturally deferred):
- **HIGH-001** — No API authentication. Architecturally deferred to
  Phase 8 (deployment-context decision needed).
- **HIGH-002** — Engine ↔ Quantower plugin coupling via WebSocket + DB
  polling. Architecturally deferred to Phase 6 (broader rework).

**First time the ledger has held at Top 2 across multiple consecutive
tasks** (Tasks 121-125 all resolved MED-tier without HIGH movement).
All actionable HIGH-tier work in the audit response is now closed; the
remaining HIGHs are explicitly named-phase deferrals, not open work.

### Test suite

1752 passed, 6 skipped. Test count growth across Bundle A:
- Task 121 (+21 cases): StatusIndicator + FE-HIGH-001 migration pins.
- Task 122 (+21): Card + Analytics migration.
- Task 123 (+29): TableRow + 3 history-table migrations + Trade
  History column split.
- Task 124 (+46): EmptyState + 10 migration sites.
- Task 125 (+33): PeriodSelector + 3 migration sites.

### Latent observations (recorded in audit doc, not filed as findings)

Bundle A surfaced 4 composite-primitive candidates worth tracking:
- WsStatus composite (Task 121 latent) — multi-field display in
  `ws_status.html`: StatusIndicator + numeric readouts (latency + age
  + clock offset). Card has now landed; natural follow-up.
- Regime Timeline mode+period combo (Task 125 latent) — two segmented
  controls (Swim/Bars/Blocks/Heat/Stack + period) that should
  visually coordinate.
- Card header_actions slot (Task 122 latent) — action buttons in card
  header right corner. Future header-slot expansion.
- Form-field cluster (Task 125 latent) — Config / Add Account modal
  has 15-20 repeated `<label>` + `<input>` clusters.

None blocked Bundle A close. Filed as latent in the audit doc, not as
new findings; consumer-driven filing when a real second use case
appears.

---

## [v2.4.2] — 2026-05-18

### Summary

Bundle B closure release — wraps the Phase 5 adapter-hardening + credential-
hardening + input-validation + DB-init follow-ups into one tag. 11 tasks since
v2.4.1.1 (Tasks 109-119), 6 HIGH + 7 MED resolved, 2 reframings, 2 operator-
decision encodings. Combined ledger drops from 92 active at v2.4.1.1 to 82
active at v2.4.2.

No money-at-risk fixes in this release — v2.4.1's CRIT/HIGH-tier trading-loop
work was already complete. v2.4.2 is the operational-hardening tag.

### Resolved (HIGH)

- **FE-HIGH-002** (Task 111) Add Account modal — Bybit / MEXC now exposed
  alongside Binance with `(Beta)` tag suffix. Registry-driven dropdown via
  new `list_rest_exchanges()` helper. Unblocked Phase 5 Bundle B end-to-end
  verification for non-Binance accounts.
- **FE-HIGH-006** (Task 113) Trade Events Log row expansion — raw single-line
  JSON `<pre>` replaced with a CSS-grid key-value layout. Nested values use
  `tojson`; null renders as muted-italic "null"; empty payload surfaces a
  "No payload data." hint.
- **HIGH-028** (Task 115) Bybit weight-tracker reconciliation — adapted mirror
  of Task 99's Binance HIGH-014. Bybit V5 publishes per-endpoint remaining
  quota rather than global used weight, so saturation `(limit - status) / limit`
  scales to `tracker.max_weight` for a unit-compatible reconcile signal.
  Fail-safe across 7 edge cases.
- **HIGH-029** (Task 116) Credential traceback leak parallels — `SensitiveStr`
  applied at 5 routes_accounts entry points (`create_account`, `update_account`,
  `add_account_modal`, `test_account_preview`, `update_account_detail`) +
  `crypto.decrypt` return + 3 production decrypt consumers
  (`account_registry.load_all`, `connections.load_all`, `ws_manager` user-data
  reconnect). Closes the broader exchange-credential surface Task 100's narrow
  fix had explicitly left for follow-up.
- **HIGH-030** (Task 117) Bybit account-field validation — adapted mirror of
  HIGH-013. Bybit V5 UNIFIED responses have two layers (`result.list[0]`
  account-aggregate + per-coin USDT); validation accepts either layer as
  authoritative. Structural-path checks + critical-field presence checks +
  non-critical-field warn-only handling.
- **HIGH-031** (Task 118) MEXC account-field validation — pure mirror of
  HIGH-013 with one Bybit-style structural-path check (`raw['USDT'] or
  raw['total']` fallback). Read-only adapter context bounds blast radius to
  display/analytics, but validation fails loud anyway. Closes the "adapter
  response sanity" family (HIGH-013/030/031 — all 3 production REST adapters
  now validated).

### Resolved (MED)

- **FE-MED-005** (Task 112) Calculator Recent card — timestamps now relative
  ("Just now", "5m ago", "2h ago", "Yesterday HH:MM", absolute fallback).
  Storage switched from `HH:MM` string to epoch ms. Backward-compat with
  legacy localStorage entries.
- **FE-MED-011** (Task 112) Calculator preview labels — `_size (contracts)`
  → `Size (Contracts)`; `Notional / est_size (USDT)` → `Notional / Est. Size
  (USDT)`. Underscore-style identifiers no longer leak to operator UI.
- **FE-MED-012** (Task 112) Calculator depth / fee labels disambiguated —
  `1% Depth (USDT)` → `1% Depth from Mid (USDT)`; `{Maker|Taker} Fee (2×)`
  → `{Maker|Taker} Fee — Round-trip (Entry + Exit)`.
- **MED-046** (Task 119) DB init SQL split footgun — `_CREATE_STATEMENTS.split(";")`
  loop replaced with `sqlite3.executescript()`. Handles `--` line comments
  containing semicolons (the Task 104a `incomplete input` failure mode).
- **MED-048** (Task 114) Server-side exchange whitelist — `_validate_exchange`
  + new registry helpers (`is_valid_rest_exchange`, `get_supported_rest_exchanges`)
  wired into all 4 client-trust account routes. Strict case-sensitive; 400
  with operator-friendly message on rejection.
- **MED-049** (Task 119) market_type whitelist — symmetric helper
  `_validate_market_type` + registry primitives (`is_valid_market_type`,
  `get_supported_market_types`) wired into `update_account_detail`. Closes
  the gap where market_type-only edits skipped re-validation.
- **MED-050** (Task 119) Position / order fetch per-record validation across
  Binance + Bybit + MEXC adapters. Per-record granularity (not fail-closed)
  — vanishing position is operator-visible in UI while list-blanking is not.
  Routing-critical fields validated (symbol + amount for positions; id +
  symbol for orders); malformed records logged + skipped, valid records
  pass through unchanged.

### Reframed

- **FE-HIGH-003** → **FE-MED-017** (Task 110) BTCUSDT events confirmed test
  pollution per operator. No real-data corruption — log-hygiene severity.
- **FE-HIGH-004** → **FE-MED-016** (Task 110) 1 Hz `ws_status` polling is
  intentional for live-latency display (`+437ms` in header), not a static-
  boolean concern. SSE migration is optimization opportunity, not a bug.
  Audit-impact-imprecision calibration: 5th example in the pattern.

### Operator decisions encoded (Task 110, 2026-05-18)

- Desktop-only product (no mobile support targeted).
- Calculator timestamps: relative format ("Just now", "5m ago", etc.).
- Bybit / MEXC Add Account modal: `(Beta)` tag suffix presentation.
- Decision provenance recorded in `v2_4_audit_fix_plan.md` Open Dependencies
  section.

### New findings filed (deferred)

- **MED-047** (Task 109) Template wiring pins use source-string greps without
  compile-test — surfaced when Task 108 caught FE-CRIT-001 via a behavioral
  test that source-grep pins missed. Discipline addition in CLAUDE.md.
- **MED-048** (Task 112, resolved Task 114).
- **MED-049** (Task 115, resolved Task 119).
- **MED-050** (Task 118, resolved Task 119).

### Audit ledger state at tag

**82 active findings** — 0 CRIT / 3 HIGH / 52 MED / 27 LOW.

Remaining HIGHs:
- **HIGH-001** — No API auth (architecturally deferred to Phase 8;
  deployment-context decision needed).
- **HIGH-002** — Engine ↔ Quantower plugin coupling via WebSocket + DB polling
  rather than well-defined contract (architecturally deferred to Phase 6).
- **FE-HIGH-001** — Header "Plugin OFF" misread as "engine offline"
  (operationally actionable inside Phase 5 Bundle A — header redesign +
  primitives).

Closed families this release:
- **Adapter response-sanity** (HIGH-013/030/031) — all 3 production REST
  adapters have account-field validation.
- **Credential-hardening** (HIGH-024/029) — full credential lifecycle
  wrapped in SensitiveStr at boundaries.
- **Defense-in-depth input + DB-init** (MED-046/048/049/050) — Bundle B
  MED-tier follow-ups fully resolved.

### Test suite

1602 passed, 6 skipped (`LOW-023` TestClient deadlock pattern — see
`tests/test_task108_hotfix_v2_4_1_1.py` for the skip rationale).

---

## [v2.4.1.1] — 2026-05-18

### Summary

Hotfix release closing the FE-CRIT-001 release-blocker discovered by the
frontend audit-01 immediately after the v2.4.1 tag. The account detail panel
silently returned HTTP 500 because Task 104b's template addition used a
Python list comprehension inside a Jinja2 `{% set %}` (`[p[0] for p in ...]`
— not Jinja2-valid syntax). Bundled four other small fixes since the same
audit-01 pass surfaced them and they all touch UI / config / template files.

### Resolved

- **FE-CRIT-001** Account detail panel HTTP 500 → namespace-based loop pattern
  in `templates/fragments/account_detail.html` replaces the invalid
  comprehension. Pre-fix the template never rendered; the audit-01 silent-500
  was the render-failure surfacing.
- **FE-HIGH-005** Regime "As of undefined" → JS in `templates/regime.html`
  read `data.date`; endpoint at `api/routes_regime.py:42` returns
  `computed_at`. JS rewritten with the correct field name + null fallback.
- **FE-MED-014** Account auto-load on single-account install → collapsed by
  FE-CRIT-001 fix. `templates/config.html:38-43` already had
  `hx-trigger="load"` on the detail panel; only the 500 was blocking it.
- **FE-LOW-001** `PROJECT_VERSION_` stale at `"v2.4"` → bumped to `"v2.4.1.1"`.

### Filed + Resolved same commit

- **FE-MED-015** HTMX 4xx/5xx swaps fail silently with no user surface →
  global `htmx:responseError` + `htmx:sendError` listeners added to
  `templates/base.html`. Renders a fixed-position toast for ~5 s; logs full
  detail to console. Audit-01 explicitly called for this as FE-CRIT-001's
  recommended secondary fix; if it had existed pre-FE-CRIT-001 the audit
  would have surfaced the 500 in one click instead of hiding for a full
  audit pass.

### Audit ledger state after v2.4.1.1

**91 active** — 0 CRIT / 11 HIGH / 53 MED / 27 LOW.

CRIT count returned to zero. Top 5 now headed by HIGH-001 (auth, Phase 8
deferred); no active CRIT-tier blocker remains for the v2.4.1.1 tag push.

### Tests

- `tests/test_task108_hotfix_v2_4_1_1.py` adds 12 cases (9 active + 3 skipped
  per LOW-023 pattern). Full pytest: 1465 passed, 6 skipped, 26.47 s.
- Direct Jinja2-render test (`TestAccountDetailTemplateCompiles`) loads the
  actual template file and renders against a synthetic context — catches
  FE-CRIT-001-class syntax errors without needing the FastAPI/uvicorn stack
  (which is what previously deadlocked TestClient-based pin tests).

### Out of scope (deferred)

- Other FE-* findings (Phase 5 work; bundle plan = Task 109).
- Pushing v2.4.1.1 to origin (operator decision after smoke confirms).

---

## [v2.4.1] — 2026-05-18

### Summary

v2.4.1 closes Phases 1–4 of the v2.4 audit response. Across 92 original audit
findings + 9 emergent discoveries (101 total), 24 HIGH/CRIT-tier issues were
resolved, 8 race-framed findings were verified false (structurally impossible
under Python's asyncio + GIL semantics), and 2 cross-section duplicates were
consolidated. Six HIGH-tier findings remain deferred and are documented as
known-deferred at tag time (HIGH-001 auth to Phase 8; HIGH-002 db._conn to
Phase 6; HIGH-028 / 029 / 030 / 031 as exchange-adapter parallels to be
addressed in Phase 5+).

Audit ledger state at tag: **0 CRIT / 6 HIGH / 39 MED / 21 LOW = 66 active**.

### Resolved (CRIT)
- **CRIT-001** (Task 88): N+1 query in fills enrichment — batch-fetch pre_trade_log + orders. ~31× speedup on 50-fill positions.
- **CRIT-002** (Task 85): Slippage divide-by-zero guard in risk_engine.
- **CRIT-004** (Task 87): TP/SL exec-link semantics correction (1/1 — was misleading 3/3).
- **CRIT-006** (Task 89): Active-account scoping in data_logger; cross-account snapshot leakage closed.
- **CRIT-008** (Task 88.1): Missing pre_trade_log.calc_id column on legacy DBs — migration added.

### Resolved (HIGH)
Phase 1–3:
- **HIGH-003** (Task 88.1): Two missing pre_trade_log indexes for the calc-to-fill query path.
- **HIGH-009** (Task 92): Close-fee overfill cap in `_build_close_row_for_fill`.
- **HIGH-020** (Task 93): fetch_account null-check.
- **HIGH-021** (Task 94): Contract-spec TTL reduction (24 h → 4 h) + admin force-refresh endpoint.

Phase 4:
- **HIGH-007 + HIGH-014 + HIGH-015 + LOW-019** (Task 99): Adapter observability + Binance weight-tracker header reconciliation + fee-fetch log + price-extremes log.
- **HIGH-008** (Task 103): Scheduler AuthenticationError handling + `app_state.auth_failed_accounts` state.
- **HIGH-010** (Task 105): `core/crypto.decrypt` silent fallback → `CredentialDecryptionError` + 3 caller updates.
- **HIGH-011 + MED-003 + MED-022** (Task 101): SQL injection defense — filter-column whitelist, route-level sort validator, LIKE-prefix parameterization.
- **HIGH-013 + MED-018** (Task 102): Trust-but-verify exchange responses — critical-field validation + negative-equity clamp.
- **HIGH-017 + HIGH-018** (Task 98): DD-gate fail-closed on settings-read failure + pubsub except narrowing (subscriber retention).
- **HIGH-022 + HIGH-023 + MED-036** (Task 97): Route input validation — backtest date-range bounds + cross-parameter `warning < limit` checks + max-position-count runtime guard.
- **HIGH-024** (Task 100): Credential leak prevention — `SensitiveStr` wrapper, narrow scope on routes_connections.
- **HIGH-026** (Task 95): Silent-swallow remediation in `_build_close_row_for_fill` — structured engine_event emission.
- **HIGH-027** (Tasks 104a + 104b): Calc-to-fill matching window — schema (per-account default, per-calc override) + `compute_exec_match` window logic + UI countdown (4-state: LINKABLE / EXPIRING_SOON / EXPIRED / LINKED_CONFIRMED).

### Verified false (audit framing imprecise; pin tests added)
- **CRIT-003**: max() on empty close_fills — already guarded.
- **CRIT-005**: WS-reconnect race — single-coroutine reconnect path is structurally serialized.
- **HIGH-004 / HIGH-005 / HIGH-006**: Already guarded.
- **HIGH-012**: Account-switch deferred-close closure race — lambda captures function parameter, not attribute.
- **HIGH-019**: Engine actively places TP/SL — engine is passive observer (Quantower plugin places).
- **HIGH-025**: Partial-fill TP/SL re-enrichment — already correct.

### Filed during fix phase (resolved or deferred)
- **CRIT-008** (filed + resolved Task 88.1).
- **LOW-022 + MED-043** (filed + resolved Task 85b).
- **HIGH-026** (filed Task 90.5d? — resolved Task 95).
- **MED-044** (filed Task 89; OPEN, target Phase 4).
- **HIGH-027** (filed Task 93; resolved Tasks 104a + 104b).
- **HIGH-028** (filed Task 99.1; deferred — Bybit reconciliation parallel to HIGH-014).
- **HIGH-029** (filed Task 100; deferred — exchange-credential traceback leak parallel to HIGH-024).
- **LOW-023** (filed Task 101.1; OPEN — full-suite TestClient hang root cause).
- **HIGH-030 + HIGH-031** (filed Task 102.1; deferred — Bybit + MEXC account-field parallels to HIGH-013).
- **MED-045** (filed + resolved Task 103.5).
- **MED-046** (filed Task 104b; OPEN — `_CREATE_STATEMENTS.split(";")` footgun in database.py).

### Infrastructure
- **pytest-timeout** (Task 101.1): 30 s default per test (`pyproject.toml` `[tool.pytest.ini_options]`). Caught the LOW-023 hang on first full-suite run. CLAUDE.md documents the test-discipline playbook.
- **concurrent-log-handler** (Task 103.5): replaces stdlib `RotatingFileHandler` to fix the Windows multi-process log-rotation `PermissionError [WinError 32]` observed at runtime after Task 103.

### Calibration patterns documented (audit doc)
- **Race-framing false-positive rate: 8 of 15 (53 %)** — race-framed findings should default to verify-before-assume. CRIT-003, CRIT-005, HIGH-004, HIGH-005, HIGH-006, HIGH-012, HIGH-019, HIGH-025 are all real-bug-but-not-race or already-guarded.
- **Audit-impact-imprecision pattern: 4 examples** — HIGH-019 (wrong architecture), HIGH-026 (already-logged), HIGH-013 (wrong direction — collapses to micro, not excessive), HIGH-008 (wrong mechanism — retry-hammers, doesn't crash). Implication: trace downstream consumers independently of audit's described mechanism.

### Deferred at v2.4.1 tagging (documented as known-deferred)
- **HIGH-001** — Authentication on all endpoints. Phase 8 (deployment context decision needed).
- **HIGH-002** — `db._conn` private-attribute access across 24 sites. Phase 6 (architectural refactor).
- **HIGH-028** — Bybit weight-tracker reconciliation. Sister to HIGH-014's Binance fix (Task 99); deferred during the same task.
- **HIGH-029** — Credential traceback leak in `api/routes_accounts.py` (5 sites) + `core/account_registry.py` decrypt sites. Parallel to HIGH-024's narrow scope (Task 100).
- **HIGH-030** — Bybit account-field validation. Sister to HIGH-013's Binance fix (Task 102).
- **HIGH-031** — MEXC account-field validation. Reduced impact (read-only adapter) but completes the trust-but-verify family.
- **MED-046** — SQL-split footgun in `core/database.py`. Discovered Task 104a, filed Task 104b. Follow-up cleanup.

### Phase 4 task ledger

| Task | Findings | Branch tip |
|------|----------|------------|
| 95 | HIGH-026 | e352593 |
| 96 | HIGH-012 (verified false) | 625a909 |
| 97 + 97.1 | HIGH-022 + HIGH-023 + MED-036 + wiring pins | a26d2dd / 6edd30b |
| 98 | HIGH-017 + HIGH-018 | f2d2533 |
| 99 + 99.1 | HIGH-007 + HIGH-014 + HIGH-015 + LOW-019 + HIGH-028 filing | 435add1 / 3f7baf8 |
| 100 | HIGH-024 + HIGH-029 filing | 853b91f |
| 101 + 101.1 | HIGH-011 + MED-003 + MED-022 + pytest-timeout + LOW-023 filing | dda5519 / 848b467 |
| 102 + 102.1 | HIGH-013 + MED-018 + HIGH-030 + HIGH-031 filings | 5ea794b / 560e63d |
| 103 + 103.5 | HIGH-008 + MED-045 (filed + resolved) | 1cb8787 / 0f7548e |
| 104a + 104b | HIGH-027 backend + frontend + MED-046 filing | 78f76a8 / 0d1fa93 |
| 105 | HIGH-010 | 938e50f |

Full pytest at tag: **1456 passed, 3 skipped** (LOW-023 skipped pending fixture refactor).

---

(Prior history of v2.4 development lives in `v2.4.md`, `v2_4_audit_fix_plan.md`,
and the per-task commit messages.)
