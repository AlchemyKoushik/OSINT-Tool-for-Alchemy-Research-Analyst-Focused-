@echo off
setlocal

if not defined FRONTEND_DIR (
    echo [ERROR] FRONTEND_DIR is not set.
    pause
    exit /b 1
)

if not defined PYTHON_EXE (
    echo [ERROR] PYTHON_EXE is not set.
    pause
    exit /b 1
)

if not defined FRONTEND_LOG (
    echo [ERROR] FRONTEND_LOG is not set.
    pause
    exit /b 1
)

title Frontend Logs
cd /d "%FRONTEND_DIR%"

echo =================================
echo Frontend Console
echo =================================
echo [INFO] Working directory: %FRONTEND_DIR%
echo [INFO] Python: %PYTHON_EXE%
echo [INFO] Log file: %FRONTEND_LOG%
echo [INFO] Starting static server on http://127.0.0.1:3000
echo.

"%PYTHON_EXE%" -m http.server 3000 --bind 127.0.0.1 >> "%FRONTEND_LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo [ERROR] Frontend process exited with an error. Review the logs above.
    pause
    exit /b 1
)

echo.
echo [INFO] Frontend process exited normally.
pause
exit /b 0
