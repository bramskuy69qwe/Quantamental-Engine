@echo off
title Quantamental Risk Engine v2.1
echo.
echo  ===================================================
echo   Quantamental Risk Engine v2.1  --  Binance USD-M
echo  ===================================================
echo.

REM Activate virtual environment if present
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Install Python deps on first run
pip show fastapi >nul 2>&1 || (
    echo Installing Python dependencies...
    pip install -r requirements.txt
)

REM ── Frontend build ───────────────────────────────────────────────────────────
REM Install JS deps on first run
if not exist frontend\node_modules (
    echo Installing frontend dependencies...
    cd frontend
    npm install
    cd ..
)

REM Build frontend if static/index.html is missing
if not exist static\index.html (
    echo Building frontend...
    cd frontend
    npm run build
    cd ..
)

REM ── Launch ───────────────────────────────────────────────────────────────────
echo Starting server on http://localhost:8000
echo Press Ctrl+C to stop.
echo.

REM Open browser after a 3-second delay so the server has time to start
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

REM Start FastAPI server (blocking)
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
