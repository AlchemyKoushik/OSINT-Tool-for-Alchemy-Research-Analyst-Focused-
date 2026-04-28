@echo off
setlocal

echo =================================
echo Starting Full Stack Application...
echo =================================

cd /d "%~dp0"

REM Activate virtual environment
call "venv\Scripts\activate.bat"
echo [INFO] Virtual environment activated.

REM Start backend in new window
echo [INFO] Starting Backend...
start "Backend" cmd /k ""%~dp0venv\Scripts\activate.bat" && cd /d "%~dp0backend" && uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

REM Start frontend static server in new window
echo [INFO] Starting Frontend server...
start "Frontend" cmd /k ""%~dp0venv\Scripts\activate.bat" && cd /d "%~dp0frontend" && python -m http.server 3000 --bind 127.0.0.1"

REM Wait for services to start
echo [INFO] Waiting for backend to initialize...
timeout /t 5 > nul

REM Open Chrome with frontend
echo [INFO] Opening Chrome on frontend...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" http://127.0.0.1:3000
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" http://127.0.0.1:3000
) else (
    start "" http://127.0.0.1:3000
)

echo =================================
echo Application Started Successfully
echo =================================

pause
