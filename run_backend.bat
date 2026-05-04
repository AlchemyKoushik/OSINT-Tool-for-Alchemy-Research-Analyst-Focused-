@echo off
setlocal

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "BACKEND_DIR=%REPO_ROOT%\backend"
set "BACKEND_ENV_FILE=%BACKEND_DIR%\.env"
set "BACKEND_ENV_EXAMPLE=%BACKEND_DIR%\.env.example"
set "LOG_DIR=%REPO_ROOT%\runtime_logs"
set "BACKEND_LOG=%LOG_DIR%\backend.log"
set "PYTHON_EXE="

echo =================================
echo Starting Backend...
echo =================================

cd /d "%REPO_ROOT%"

call :stop_port 8000 "Backend"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
break > "%BACKEND_LOG%"

if not exist "%BACKEND_DIR%\main.py" (
    echo [ERROR] Backend entrypoint not found: %BACKEND_DIR%\main.py
    pause
    exit /b 1
)

if not exist "%BACKEND_ENV_FILE%" (
    echo [WARN] Backend env file not found: %BACKEND_ENV_FILE%
    if exist "%BACKEND_ENV_EXAMPLE%" (
        echo [INFO] Fill in the required keys in backend\.env based on backend\.env.example, then run this file again.
    ) else (
        echo [INFO] Create backend\.env with the required API and storage keys, then run this file again.
    )
    pause
    exit /b 1
)

call :set_python "%REPO_ROOT%\venv\Scripts\python.exe"
if defined PYTHON_EXE goto :python_found

call :set_python "%REPO_ROOT%\.venv\Scripts\python.exe"
if defined PYTHON_EXE goto :python_found

call :set_python "%REPO_ROOT%\..\venv\Scripts\python.exe"
if defined PYTHON_EXE goto :python_found

call :set_python "C:\Python314\python.exe"
if defined PYTHON_EXE goto :python_found

call :set_python "C:\Users\KoushikBhandary\AppData\Local\Programs\Python\Python311\python.exe"
if defined PYTHON_EXE goto :python_found

for %%P in (python.exe py.exe) do (
    where %%P >nul 2>nul
    if not errorlevel 1 (
        call :set_python "%%~$PATH:P"
        if defined PYTHON_EXE goto :python_found
    )
)

echo [ERROR] Could not find a usable Python with uvicorn installed.
pause
exit /b 1

:python_found
echo [INFO] Using Python: %PYTHON_EXE%
echo [INFO] Working directory: %BACKEND_DIR%
echo [INFO] Backend logs will stream in this window.
echo [INFO] Log file: %BACKEND_LOG%
echo.

cd /d "%BACKEND_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONUNBUFFERED='1'; & '%PYTHON_EXE%' -m uvicorn main:app --host 127.0.0.1 --port 8000 2>&1 | Tee-Object -FilePath '%BACKEND_LOG%' -Append"

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

:set_python
set "CANDIDATE_PYTHON=%~1"

if not exist "%CANDIDATE_PYTHON%" exit /b 0

"%CANDIDATE_PYTHON%" -c "import uvicorn" >nul 2>nul
if errorlevel 1 exit /b 0

set "PYTHON_EXE=%CANDIDATE_PYTHON%"
exit /b 0

:stop_port
set "TARGET_PORT=%~1"
set "TARGET_NAME=%~2"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:":%TARGET_PORT%" ^| findstr /C:"LISTENING"') do (
    if not "%%P"=="0" (
        echo [INFO] Stopping existing %TARGET_NAME% process on port %TARGET_PORT% ^(PID %%P^)
        taskkill /PID %%P /F >nul 2>nul
    )
)

timeout /t 1 >nul
exit /b 0
