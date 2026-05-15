@echo off
cd /d "%~dp0"
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Validator Pro  —  Web Server           ║
echo  ║   http://localhost:8502                  ║
echo  ╚══════════════════════════════════════════╝
echo.

:: Check for .env
if not exist ".env" (
    echo  [!] .env file not found.
    echo      Copy .env.example to .env and fill in your tokens.
    echo.
    pause
    exit /b 1
)

echo Installing / verifying dependencies...
python -m pip install -r requirements.txt -q

echo.
echo Starting FastAPI server on http://localhost:8502
echo Press Ctrl+C to stop.
echo.
python -m uvicorn server:app --host 0.0.0.0 --port 8502 --reload
pause
