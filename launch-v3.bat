@echo off

REM v3.0 launcher — same engine process as launch.bat, but opens the React
REM /v3 surface instead of the Jinja root. Differences from launch.bat are
REM deliberate (HANDOFF recipe): prefer the .venv interpreter (user-site
REM Python lacks pytest-timeout and is not the supported runtime) and NO
REM --reload (reload workers double-run the schedulers).

REM Read project name from config.py — single source of truth
for /f "delims=" %%i in ('python -c "import config; print(config.PROJECT_NAME)"') do set QE_NAME=%%i

title %QE_NAME% - v3
echo.
echo  ===================================================
echo   %QE_NAME%  --  Binance USD-M  --  /v3 (React)
echo  ===================================================
echo.

REM Clock sync first (best effort): a drifted clock causes Binance -1021
REM "Timestamp ahead" and the engine hangs on "Connecting to exchange...".
w32tm /resync >nul 2>&1
if errorlevel 1 (
    echo  [warn] clock resync failed - run "w32tm /resync" as Administrator
    echo         if startup hangs on "Connecting to exchange".
) else (
    echo  Clock synced.
)
echo.

REM Interpreter: prefer .venv (the supported runtime), then venv, then PATH.
set PY=python
if exist venv\Scripts\python.exe  set PY=venv\Scripts\python.exe
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe

REM Install deps on first run
"%PY%" -m pip show fastapi >nul 2>&1 || (
    echo Installing dependencies...
    "%PY%" -m pip install -r requirements.txt
)

echo Starting server on http://localhost:8000 (UI: http://localhost:8000/v3)
echo Press Ctrl+C to stop.
echo.

REM Start server, then open the /v3 React surface as a standalone window
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:8000/v3"
"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000

pause
