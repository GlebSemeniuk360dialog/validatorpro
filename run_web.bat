@echo off
cd /d "%~dp0"
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Validator Pro  —  Web Server           ║
echo  ║   http://localhost:8502                  ║
echo  ╚══════════════════════════════════════════╝
echo.
echo Installing/verifying dependencies...
python -m pip install fastapi "uvicorn[standard]" python-dotenv -q

echo.
echo Starting FastAPI server on port 8502...
python -m uvicorn server:app --host 0.0.0.0 --port 8502 --reload
pause
