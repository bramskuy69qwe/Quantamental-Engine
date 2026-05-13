# Binance USDⓈ-M Futures Adapter

## API Surface
### REST Endpoints Used
| Endpoint | Purpose | Last Verified | Doc Reference |
|----------|---------|---------------|---------------|
| GET /fapi/v1/openOrders | Basic open orders | 2026-05-13 | <link> |
| GET /fapi/v1/openAlgoOrders | Conditional orders | 2026-05-13 | <link> |
| GET /fapi/v1/userTrades | Trade history | ... | ... |
| ... | ... | ... | ... |

### WebSocket Events Handled
| Event | Purpose | Handler | Last Verified |
|-------|---------|---------|---------------|
| ORDER_TRADE_UPDATE | Basic order lifecycle | ws_manager.py:142 | 2026-05-13 |
| ALGO_UPDATE | Conditional order lifecycle | ws_manager.py:??? | 2026-05-13 (new) |
| ACCOUNT_UPDATE | Account state changes | ws_manager.py:??? | 2026-05-11 |

### WebSocket Events Acknowledged but NOT Handled
- STRATEGY_UPDATE, GRID_UPDATE: out of scope

## Account Configuration Assumptions
- Hedge mode (positionSide = LONG/SHORT)
- One-way mode supported via resolve_tpsl_direction helper
- USDT-M Futures (not COIN-M, not Portfolio Margin)
- PAPI not supported — returns 404 on PAPI endpoints

## Known Quirks
- positionSide = "BOTH" in one-way mode (handled by helper)
- retry_after_ms only populated for 418 (parsed from "banned until")
- exchange_history income API: trade_key is timestamp_symbol (no tradeId)
- ALGO_UPDATE uses different field names (o.at, o.aid) vs ORDER_TRADE_UPDATE

## Recent Migrations / Watch List
- **2025-12-09**: Conditional orders → Algo Service. New endpoint 
  /fapi/v1/openAlgoOrders, WS event ALGO_UPDATE. Engine retrofitted 
  via OM-5 (2026-05-13).
- **2024-10-17**: Trade history limited to 1 year. Not affecting engine.

## Changelog Watch
- Source: https://developers.binance.com/docs/derivatives/change-log
- Cadence: Monthly or before each engine release
- Last reviewed: 2026-05-13