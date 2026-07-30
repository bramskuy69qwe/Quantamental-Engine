@echo off

REM THE launcher (Jinja retirement 2026-07-30: the React app owns /, and the
REM legacy launch.bat is archived — its --reload spawned workers that
REM DOUBLE-RAN the live schedulers). Deliberate properties: prefer the .venv
REM interpreter (user-site Python is not the supported runtime), NO --reload,
REM best-effort clock resync before boot.

REM Read project name from config.py — single source of truth
for /f "delims=" %%i in ('python -c "import config; print(config.PROJECT_NAME)"') do set QE_NAME=%%i

title %QE_NAME%
echo.
echo  ===================================================
echo   %QE_NAME%  --  Binance USD-M
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

echo Starting server on http://localhost:8000
echo Press Ctrl+C to stop.
echo.

REM Start server, then open the app as a standalone window
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:8000"
"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000

pause
