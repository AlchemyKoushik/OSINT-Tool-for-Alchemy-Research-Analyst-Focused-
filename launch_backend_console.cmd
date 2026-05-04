@echo off
setlocal

if not defined BACKEND_DIR (
    echo [ERROR] BACKEND_DIR is not set.
    pause
    exit /b 1
)

if not defined PYTHON_EXE (
    echo [ERROR] PYTHON_EXE is not set.
    pause
    exit /b 1
)

if not defined BACKEND_LOG (
    echo [ERROR] BACKEND_LOG is not set.
    pause
    exit /b 1
)

title Backend Logs
cd /d "%BACKEND_DIR%"

echo =================================
echo Backend Console
echo =================================
echo [INFO] Working directory: %BACKEND_DIR%
echo [INFO] Python: %PYTHON_EXE%
echo [INFO] Log file: %BACKEND_LOG%
echo [INFO] Starting uvicorn on http://127.0.0.1:8000
echo.

"%PYTHON_EXE%" -m uvicorn main:app --host 127.0.0.1 --port 8000 >> "%BACKEND_LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo [ERROR] Backend process exited with an error. Review the logs above.
    pause
    exit /b 1
)

echo.
echo [INFO] Backend process exited normally.
pause
exit /b 0
