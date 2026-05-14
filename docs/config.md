# Configuration Storage Policy

How the engine resolves per-account and global configuration at runtime.

**Last updated**: 2026-05-15 (v2.4 Phase 1)

---

## Storage tiers

| Tier | Store | Scope | Hot-reload |
|------|-------|-------|------------|
| Per-account behaviour | `account_settings` table (per-account DB) | One row per account | No (restart) |
| Per-account risk numerics | `account_params` table (legacy DB) | Key-value, REAL only | Yes (UI form) |
| Infrastructure | `.env` + `config.py` | Global | No (restart) |

`account_settings` is the v2.4 source of truth for typed, per-account
configuration. Legacy `account_params` remains active for risk numerics
during the v2.4 transition; engine code will be rewired in Phase 2.

---

## account_settings columns

Accessor: `core.db_account_settings.get_account_settings(account_id)`

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `account_id` | INTEGER PK | — | Foreign key to `accounts.id` |
| `timezone` | TEXT | `'UTC'` | IANA timezone for reset boundaries and display |
| `dd_rolling_window_days` | INTEGER | 30 | Rolling DD window in calendar days |
| `dd_warning_threshold` | REAL | NULL | Absolute DD ratio triggering warning state |
| `dd_limit_threshold` | REAL | NULL | Absolute DD ratio triggering limit state |
| `dd_recovery_threshold` | REAL | 0.50 | Fraction of DD peak equity must recover for early-unblock |
| `dd_enforcement_mode` | TEXT | `'advisory'` | `advisory` (log only) or `enforced` (block calculator) |
| `weekly_pnl_warning_threshold` | REAL | NULL | Weekly loss ratio triggering warning |
| `weekly_pnl_limit_threshold` | REAL | NULL | Weekly loss ratio triggering limit |
| `weekly_pnl_enforcement_mode` | TEXT | `'advisory'` | Same as DD enforcement mode |
| `strategy_preset` | TEXT | NULL | Informational: which preset seeded this account |
| `analytics_default_period` | TEXT | `'monthly'` | UI default period for analytics views |
| `week_start_dow` | INTEGER | 1 | ISO weekday for week start (1=Monday, 7=Sunday) |

---

## Environment variables

Read once at import time by `config.py`. Changes require restart.

| Variable | Required | Purpose |
|----------|----------|---------|
| `ENV_MASTER_KEY` | Yes | Fernet key for encrypting stored API credentials |
| `BINANCE_API_KEY` | No | Legacy fallback; prefer per-account encrypted storage |
| `BINANCE_API_SECRET` | No | Legacy fallback |
| `HTTP_PROXY` | No | HTTP proxy for all exchange REST calls |
| `FRED_API_KEY` | No | FRED macro data (regime classifier) |
| `FINNHUB_API_KEY` | No | Market news feed |
| `BWE_NEWS_WS_URL` | No | BWE news WebSocket endpoint |
| `PLATFORM_TOKEN` | No | Quantower platform bridge authentication |

---

## Strategy preset seeding

`core.strategy_presets.apply_preset(account_id, preset_name)` writes
preset-specific values to `account_settings` columns. Five presets:
`scalping`, `day_trading`, `swing`, `position`, `custom`. `custom` is a
no-op (records the name, doesn't change values).

Presets are a starting point, not a lock. Individual settings remain
editable after creation. The preset name is stored in
`account_settings.strategy_preset` for the record.

See `core/strategy_presets.py:STRATEGY_PRESETS` for the value table.

---

## How to add a new account setting

1. **Migration**: new `.sql` file in `core/migrations/` using the
   table-rebuild pattern (see `docs/migrations.md`). Add the column
   with a safe default.
2. **Dataclass**: add the field to `AccountSettings` in
   `core/db_account_settings.py`. Field name must match the column name
   exactly.
3. **Whitelist**: `_UPDATABLE` auto-derives from the dataclass fields.
   No manual update needed unless the field is the PK.
4. **Tests**: add get/update coverage in `tests/test_db_account_settings.py`.
5. **Preset** (if applicable): add the column to the relevant preset
   entries in `core/strategy_presets.py`.

---

## Cross-references

- Migration system: [`docs/migrations.md`](migrations.md)
- Adapter capabilities: [`docs/adapters/binance.md`](adapters/binance.md),
  [`docs/adapters/bybit.md`](adapters/bybit.md)
- Architecture overview: [`README.md`](../README.md)
- v2.4 plan: [`v2.4.md`](../v2.4.md)
