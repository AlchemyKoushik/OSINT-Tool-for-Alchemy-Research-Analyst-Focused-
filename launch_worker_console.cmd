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

title Worker Logs
cd /d "%BACKEND_DIR%"

echo =================================
echo Research Worker Console
echo =================================
echo [INFO] Working directory: %BACKEND_DIR%
echo [INFO] Python: %PYTHON_EXE%
echo [INFO] Starting dedicated worker loop...
echo.

set "APP_ROLE=worker"
set "PYTHONUNBUFFERED=1"
if not defined LOG_LEVEL set "LOG_LEVEL=INFO"
echo [INFO] APP_ROLE=%APP_ROLE%
echo [INFO] LOG_LEVEL=%LOG_LEVEL%
echo [INFO] PYTHONUNBUFFERED=%PYTHONUNBUFFERED%
echo.
"%PYTHON_EXE%" -u -m workers.worker

if errorlevel 1 (
    echo.
    echo [ERROR] Worker process exited with an error.
    pause
    exit /b 1
)

echo.
echo [INFO] Worker process exited normally.
pause
exit /b 0
