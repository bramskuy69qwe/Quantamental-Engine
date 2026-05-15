@echo off
title QUANTAMENTAL ENGINE v2.4
echo.
echo  ===================================================
echo   QUANTAMENTAL ENGINE v2.4  --  Binance USD-M
echo  ===================================================
echo.

REM Activate virtual environment if present
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Install deps on first run
pip show fastapi >nul 2>&1 || (
    echo Installing dependencies...
    pip install -r requirements.txt
)

echo Starting server on http://localhost:8000
echo Press Ctrl+C to stop.
echo.

REM Start server, then open as standalone PWA window after a short delay
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:8000"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

pause
