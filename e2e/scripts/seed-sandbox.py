"""Seed the SANDBOX engine's DBs for Phase-4 mutation testing.

Run against E:\\tmp\\qe-sandbox ONLY (refuses anything else). Idempotent:
deletes prior e2e-seeded rows (marked ids) before inserting.

What it seeds and why:
 1. accounts mirrored global.db -> legacy risk_engine.db. The RUNNING engine's
    account registry reads the LEGACY DB (core/db_settings.get_all_accounts on
    db._conn); provision_test_env's split flow leaves legacy accounts EMPTY -
    fine for pytest (fixtures rebind) but an engine booted from a provisioned
    tree loads 0 accounts. First real sandbox boot surfaced this.
 2. A second INACTIVE account (id 2) - the account-activate/switch target.
 3. closed_positions x4 (per-account DB): TP_PLANNED / SL_PLANNED /
    MIXED (mfe+mae NULL -> must render em-dash) / MANUAL_OTHER without
    close_note (-> Linkage SET-REASON inbox + clickable History badge).
    backfill_completed=1 so the reconciler NEVER treats seeds as work queue
    (the clean_overattributed_excursions lesson).
 4. One filled order with link_status=NEEDS_MANUAL_REVIEW + one ACTIVE calc
    whose legs sit within the loose-finder tolerances -> the Linkage inbox
    manual-link flow has a real target.
"""
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SANDBOX = Path(r"E:\tmp\qe-sandbox")
DATA = SANDBOX / "data"
LEGACY = DATA / "risk_engine.db"
GLOBAL = DATA / "global.db"
PER_ACCOUNT = DATA / "per_account" / "quantower__binancefutures__binance.db"

ACC_COLS = ("id, name, exchange, market_type, api_key_enc, api_secret_enc, is_active, "
            "created_at, broker_account_id, link_window_seconds, maker_fee, taker_fee, "
            "environment, key_version, config_json")


def main() -> int:
    if not (SANDBOX / ".env").exists() or not LEGACY.exists():
        print(f"REFUSED: {SANDBOX} is not a provisioned sandbox")
        return 2
    # Belt-and-braces: refuse if this data looks live-shaped (real creds present).
    g = sqlite3.connect(GLOBAL)
    creds = g.execute("SELECT COALESCE(MAX(LENGTH(api_key_enc)),0) FROM accounts").fetchone()[0]
    if creds and creds > 0:
        print("REFUSED: accounts carry non-empty credentials - not a scrubbed sandbox")
        return 3

    now_ms = int(time.time() * 1000)
    hour = 3_600_000
    now_iso = datetime.now(timezone.utc)

    # 1+2. accounts: mirror global -> legacy, then ensure the second account in both.
    rows = g.execute(f"SELECT {ACC_COLS} FROM accounts ORDER BY id").fetchall()
    lg = sqlite3.connect(LEGACY)
    ph = ",".join("?" * 15)
    for row in rows:
        lg.execute(f"INSERT OR REPLACE INTO accounts ({ACC_COLS}) VALUES ({ph})", row)
    # Second account: UNIQUE(exchange, broker_account_id) exists — an OR REPLACE
    # with the same 'binance'/'binance' pair silently DELETED row 1 on the first
    # attempt. Distinct broker id + OR IGNORE, then assert both rows survived.
    second = list(rows[0])
    second[0] = 2
    second[1] = "Sandbox Second (Binance Futures)"
    second[6] = 0  # is_active
    second[8] = "binance2"  # broker_account_id — MUST differ (unique with exchange)
    pa = sqlite3.connect(PER_ACCOUNT)
    for conn in (lg, g, pa):
        conn.execute(f"INSERT OR IGNORE INTO accounts ({ACC_COLS}) VALUES ({ph})", second)
        conn.commit()
    got = {r[0] for r in lg.execute("SELECT id FROM accounts")}
    if got != {1, 2}:
        print(f"SEED FAILED: legacy accounts ids = {got}, expected {{1, 2}}")
        return 4

    # 3. closed_positions - marked terminal_position_ids, reconciler-inert.
    # TARGET = LEGACY risk_engine.db: the engine's DatabaseManager (db._conn)
    # reads trading tables from the legacy store (the split's per-account files
    # are resolver-routed residue - live bug #4's writer->legacy shape). First
    # seed attempt went to per-account and every door read empty.
    for stale in (pa,):
        stale.execute("DELETE FROM closed_positions WHERE terminal_position_id LIKE 'e2e:%'")
        stale.execute("DELETE FROM orders WHERE exchange_order_id LIKE 'e2e9%'")
        stale.execute("DELETE FROM pre_trade_log WHERE calc_id LIKE 'e2e-sandbox%'")
        stale.commit()
    pa = lg  # all trading-data seeds below land in LEGACY
    pa.execute("DELETE FROM closed_positions WHERE terminal_position_id LIKE 'e2e:%'")
    cp_cols = ("account_id, terminal_position_id, symbol, direction, quantity, entry_price, "
               "exit_price, entry_time_ms, exit_time_ms, realized_pnl, total_fees, net_pnl, "
               "funding_fees, mfe, mae, backfill_completed, hold_time_ms, exit_reason, "
               "source, tp_price, sl_price, close_note, tpsl_amended")
    cp_ph = ",".join("?" * 23)
    seeds = [
        (1, "e2e:BTCUSDT:LONG:1", "BTCUSDT", "long", 0.010, 60000.0, 61200.0,
         now_ms - 26 * hour, now_ms - 25 * hour, 12.0, 0.48, 11.52, -0.1,
         14.5, -3.2, 1, hour, "TP_PLANNED", "binance_ws", 61200.0, 59000.0, None, 0),
        (1, "e2e:ETHUSDT:SHORT:1", "ETHUSDT", "short", 0.30, 2600.0, 2650.0,
         now_ms - 22 * hour, now_ms - 20 * hour, -15.0, 0.62, -15.62, 0.0,
         6.0, -18.0, 1, 2 * hour, "SL_PLANNED", "binance_ws", 2500.0, 2650.0, None, 1),
        # NB: fresh schema declares mfe/mae NOT NULL — the NULL-excursion state the
        # UI renders as em-dash exists only on legacy live rows; not seedable here.
        (1, "e2e:BNBUSDT:LONG:1", "BNBUSDT", "long", 0.50, 550.0, 561.0,
         now_ms - 9 * hour, now_ms - 8 * hour, 5.5, 0.22, 5.28, 0.0,
         2.6, -1.1, 1, hour, "MIXED", "binance_ws", 570.0, 540.0, None, 2),
        (1, "e2e:XRPUSDT:SHORT:1", "XRPUSDT", "short", 40.0, 2.30, 2.25,
         now_ms - 5 * hour, now_ms - 4 * hour, 2.0, 0.08, 1.92, 0.0,
         3.1, -1.4, 1, hour, "MANUAL_OTHER", "binance_ws", 2.10, 2.45, None, 0),
    ]
    for s in seeds:
        pa.execute(f"INSERT INTO closed_positions ({cp_cols}) VALUES ({cp_ph})", s)

    # 4. NEEDS_MANUAL_REVIEW order + candidate calc (loose-finder compatible).
    pa.execute("DELETE FROM orders WHERE exchange_order_id LIKE 'e2e9%'")
    pa.execute("DELETE FROM pre_trade_log WHERE calc_id LIKE 'e2e-sandbox%'")
    pa.execute(
        "INSERT INTO orders (account_id, exchange_order_id, client_order_id, symbol, side, "
        "order_type, status, price, quantity, filled_qty, avg_fill_price, reduce_only, "
        "position_side, source, created_at_ms, updated_at_ms, last_seen_ms, link_status, "
        "tp_trigger_price, sl_trigger_price) "
        # tp/sl triggers REQUIRED: find_candidate_calcs needs >=1 leg within 5%,
        # and the legs it compares are entry/tp/sl. A trigger-less order + a calc
        # without effective_entry yields ZERO comparable legs -> the resolver
        # correctly shows "no candidate calcs" (first seed's defect, not a bug).
        "VALUES (1, 'e2e900001', 'e2e-client-1', 'ADAUSDT', 'BUY', 'MARKET', 'FILLED', 0.5000, "
        "100.0, 100.0, 0.5000, 0, 'LONG', 'binance_ws', ?, ?, ?, 'NEEDS_MANUAL_REVIEW', "
        "0.5200, 0.4800)",
        (now_ms - hour // 2, now_ms - hour // 2, now_ms),
    )
    # Second review order with NO candidate calc — the mark-unplanned target
    # (manual-link consumes the ADA order; two flows need two targets).
    pa.execute(
        "INSERT INTO orders (account_id, exchange_order_id, client_order_id, symbol, side, "
        "order_type, status, price, quantity, filled_qty, avg_fill_price, reduce_only, "
        "position_side, source, created_at_ms, updated_at_ms, last_seen_ms, link_status) "
        "VALUES (1, 'e2e900002', 'e2e-client-2', 'XLMUSDT', 'SELL', 'MARKET', 'FILLED', 0, "
        "50.0, 50.0, 0.4000, 0, 'SHORT', 'binance_ws', ?, ?, ?, 'NEEDS_MANUAL_REVIEW')",
        (now_ms - hour // 3, now_ms - hour // 3, now_ms),
    )
    pa.execute(
        "INSERT INTO pre_trade_log (calc_id, timestamp, ticker, side, average, effective_entry, "
        "tp_price, sl_price, tp_amount_pct, sl_amount_pct, size, notional, est_loss, est_r, eligible, "
        "status, window_seconds, account_id, model_name) "
        "VALUES ('e2e-sandbox-calc-1', ?, 'ADAUSDT', 'long', 0.5010, 0.5010, 0.5200, 0.4800, 100, "
        "100, 100.0, 50.10, 2.10, 1.5, 1, 'active', 21600, 1, 'e2e-seed-model')",  # 6h window - the expiry sweep killed a 300s calc before the suite reached it
        (now_iso.isoformat(),),
    )
    pa.commit()

    print("accounts (legacy):", lg.execute("SELECT id, name, is_active FROM accounts").fetchall())
    print("closed seeds:", pa.execute(
        "SELECT symbol, exit_reason, mfe, tpsl_amended FROM closed_positions "
        "WHERE terminal_position_id LIKE 'e2e:%'").fetchall())
    print("order:", pa.execute(
        "SELECT exchange_order_id, link_status FROM orders WHERE exchange_order_id LIKE 'e2e9%'").fetchall())
    print("calc:", pa.execute(
        "SELECT calc_id, status FROM pre_trade_log WHERE calc_id LIKE 'e2e-sandbox%'").fetchall())
    print("SEED OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
