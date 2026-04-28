@echo off
setlocal

echo =================================
echo Starting Backend...
echo =================================

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at venv\Scripts\activate.bat
    pause
    exit /b 1
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [INFO] Virtual environment activated.
echo [INFO] Changing directory to backend...
cd /d "%~dp0backend"

echo [INFO] Running FastAPI server with reload...
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

echo [INFO] Backend process exited.
pause
