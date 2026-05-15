# Integration Test Harness

Scenario-based tests that exercise the full order lifecycle through
real ingest paths (enrichment, correlation, fill classification,
event emission) against ephemeral SQLite databases.

## Adding a new scenario

1. Create `tests/integration/scenarios/<name>.py`.
2. Define a module-level `scenario = Scenario(...)` instance.
3. Use `ScenarioEvent` for each step (calc_created, order_persisted,
   fill_received, order_modified, order_canceled).
4. Define `ExpectedState` with expected fills, orders, and trade_events.
5. Run `pytest tests/integration/ -v` to verify.

## Common patterns

- **calc_id="*"** in ExpectedFill/ExpectedOrder: matches any non-NULL value.
- **slippage_tolerance**: default 1e-6; increase for floating-point-heavy scenarios.
- **payload_includes**: subset match for ExpectedEvent — only specified keys are checked.
- Events are sorted by `t_ms` before replay.

## File structure

```
tests/integration/
  scenario.py          — dataclass types (Scenario, ScenarioEvent, Expected*)
  driver.py            — replay engine + assertion helpers
  test_scenarios.py    — pytest parametrized runner (auto-discovers scenarios/)
  scenarios/
    happy_path_market.py
    scratch_trade_limit.py
    tp_pulled_in.py
    sl_moved_closer.py
    canceled_entry.py
    market_entry_with_tpsl.py
```
