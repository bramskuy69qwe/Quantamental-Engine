"""
Combines all domain routers into a single APIRouter for mounting in main.py.

Import order matters for route precedence — FastAPI matches the first route
that fits, so fixed paths (e.g. /accounts/activate-selected) must be
registered before path-param routes (e.g. /accounts/{account_id}).
routes_accounts.py handles this internally.
"""
from fastapi import APIRouter

from api.routes_dashboard  import router as dashboard_router
from api.routes_calculator import router as calculator_router
from api.routes_history    import router as history_router
from api.routes_params     import router as params_router
from api.routes_analytics  import router as analytics_router
from api.routes_accounts   import router as accounts_router
from api.routes_platform   import router as platform_router
from api.routes_backtest   import router as backtest_router
from api.routes_models     import router as models_router
from api.routes_regime     import router as regime_router
from api.routes_news        import router as news_router
from api.routes_connections import router as connections_router
from api.routes_config      import router as config_router
from api.routes_orders      import router as orders_router
from api.routes_admin       import router as admin_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(calculator_router)
router.include_router(history_router)
router.include_router(params_router)
router.include_router(analytics_router)
router.include_router(accounts_router)
router.include_router(platform_router)
router.include_router(backtest_router)
router.include_router(models_router)
router.include_router(regime_router)
router.include_router(news_router)
router.include_router(connections_router)
router.include_router(config_router)
router.include_router(orders_router)
router.include_router(admin_router)
