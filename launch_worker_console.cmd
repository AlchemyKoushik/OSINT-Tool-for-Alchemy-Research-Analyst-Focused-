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
"%PYTHON_EXE%" -m workers.worker

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
