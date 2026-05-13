"""
One-shot conditional orders endpoint test.

Tests two Binance endpoints for conditional order access:
1. FAPI Algo (Dec 2025): /fapi/v1/order/algo/conditional/openOrders
   Available to all USDⓈ-M Futures accounts.
2. PAPI fallback: /papi/v1/um/conditional/openOrders
   Requires Portfolio Margin.

Usage:
    py -3 scripts/test_papi_conditional.py

Reads API credentials from the accounts table (Account 1),
decrypted via ENV_MASTER_KEY from .env.
"""
import os
import sys
import json
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ccxt


def get_credentials():
    """Get API credentials from accounts DB or .env fallback.

    ENV_MASTER_KEY must be loaded before decrypt() works — load .env first.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))

    db_path = os.path.join(ROOT, "data", "risk_engine.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT api_key_enc, api_secret_enc FROM accounts WHERE id=1")
            row = cur.fetchone()
            conn.close()
            if row and row[0] and row[1]:
                from core.crypto import decrypt
                return decrypt(row[0]), decrypt(row[1])
        except Exception as e:
            print(f"[warn] Could not read accounts DB: {e}")

    # Fallback to raw .env credentials
    key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")
    if key and secret:
        return key, secret

    print("[error] No API credentials found in accounts DB or .env")
    sys.exit(1)


def print_orders(response, label):
    """Pretty-print conditional order response."""
    print(f"\n[SUCCESS] {label} returned {len(response)} conditional order(s)")
    if response:
        print("\n[data] First order (raw):")
        print(json.dumps(response[0], indent=2, default=str))
        print(f"\n[data] All {len(response)} order(s):")
        for o in response:
            # FAPI Algo uses algoId/algoType/algoStatus + triggerPrice
            # PAPI uses strategyId/strategyType/strategyStatus + stopPrice
            oid = o.get("algoId") or o.get("strategyId") or "?"
            otype = o.get("orderType") or o.get("strategyType") or "?"
            ostatus = o.get("algoStatus") or o.get("strategyStatus") or "?"
            stop = o.get("triggerPrice") or o.get("stopPrice") or "?"
            print(f"  id={oid} | {o.get('symbol')} | "
                  f"{o.get('side')} {otype} | "
                  f"status={ostatus} | "
                  f"trigger={stop} | "
                  f"positionSide={o.get('positionSide')}")
    else:
        print("\n[info] Empty list — no conditional orders currently open.")
        print("       If you have TP/SL set on Binance, they should appear here.")


def main():
    api_key, api_secret = get_credentials()
    print(f"[info] Using API key: {api_key[:8]}...{api_key[-4:]}")

    ex = ccxt.binanceusdm({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
    })

    # Proxy support (match engine config)
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    if proxy:
        ex.proxies = {"http": proxy, "https": proxy}

    # ── Test 1a: FAPI Algo (all symbols) ────────────────────────────────
    print("\n" + "=" * 60)
    print("[test 1a] FAPI Algo: GET /fapi/v1/openAlgoOrders (all symbols)")
    print("=" * 60)
    try:
        response = ex.request("openAlgoOrders", "fapiPrivate", "GET", {})
        orders = response if isinstance(response, list) else response.get("orders", [response])
        print_orders(orders, "FAPI Algo (all)")
    except ccxt.ExchangeError as e:
        print(f"\n[FAIL] Exchange error: {e}")
    except ccxt.AuthenticationError as e:
        print(f"\n[FAIL] Auth error: {e}")
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")

    # ── Test 1b: FAPI Algo (SAGAUSDT only) ───────────────────────────────
    print("\n" + "=" * 60)
    print("[test 1b] FAPI Algo: GET /fapi/v1/openAlgoOrders?symbol=SAGAUSDT")
    print("=" * 60)
    try:
        response = ex.request("openAlgoOrders", "fapiPrivate", "GET", {"symbol": "SAGAUSDT"})
        orders = response if isinstance(response, list) else response.get("orders", [response])
        print_orders(orders, "FAPI Algo (SAGAUSDT)")
    except ccxt.ExchangeError as e:
        print(f"\n[FAIL] Exchange error: {e}")
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")

    # ── Test 2: PAPI endpoint (PM accounts only) ────────────────────────
    print("\n" + "=" * 60)
    print("[test 2] PAPI: GET /papi/v1/um/conditional/openOrders")
    print("=" * 60)
    try:
        response = ex.papiGetUmConditionalOpenOrders()
        print_orders(response if isinstance(response, list) else [response], "PAPI")
    except ccxt.ExchangeError as e:
        err = str(e)
        print(f"\n[FAIL] Exchange error: {e}")
        if "portfolio" in err.lower() or "-1016" in err or "not available" in err.lower():
            print("       → Confirmed: PAPI requires Portfolio Margin (not enabled).")
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")

    # ── Test 3: Basic open orders (comparison) ──────────────────────────
    print("\n" + "=" * 60)
    print("[test 3] FAPI Basic: GET /fapi/v1/openOrders (comparison)")
    print("=" * 60)
    try:
        response = ex.fapiPrivateGetOpenOrders()
        print(f"\n[info] Basic openOrders returned {len(response)} order(s)")
        for o in response:
            print(f"  orderId={o.get('orderId')} | {o.get('symbol')} | "
                  f"{o.get('side')} {o.get('type')} | "
                  f"status={o.get('status')} | "
                  f"stopPrice={o.get('stopPrice')}")
        if not response:
            print("       (empty — no basic open orders)")
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
