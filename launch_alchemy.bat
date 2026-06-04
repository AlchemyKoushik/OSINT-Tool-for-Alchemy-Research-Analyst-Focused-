@echo off
setlocal

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "BACKEND_DIR=%REPO_ROOT%\backend"
set "FRONTEND_DIR=%REPO_ROOT%\frontend"
set "BACKEND_ENV_FILE=%BACKEND_DIR%\.env"
set "PYTHON_EXE="
set "FRONTEND_URL=http://127.0.0.1:3000"
set "BACKEND_URL=http://127.0.0.1:8000"

echo =================================
echo Alchemy OSINT Local Launcher
echo =================================
echo [INFO] Repo: %REPO_ROOT%
echo [INFO] Expected frontend: %FRONTEND_URL%
echo [INFO] Expected backend: %BACKEND_URL%
echo.

if not exist "%BACKEND_DIR%\main.py" (
    echo [ERROR] Backend entrypoint not found.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
    echo [ERROR] Frontend entrypoint not found.
    pause
    exit /b 1
)

call :set_python "%REPO_ROOT%\venv\Scripts\python.exe"
if defined PYTHON_EXE goto :python_found
call :set_python "%REPO_ROOT%\.venv\Scripts\python.exe"
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

echo [ERROR] No usable Python environment was found.
pause
exit /b 1

:python_found
echo [INFO] Using Python: %PYTHON_EXE%

call :stop_port 8000 Backend
call :stop_port 3000 Frontend

if not exist "%BACKEND_ENV_FILE%" (
    echo [ERROR] Missing backend env file: %BACKEND_ENV_FILE%
    echo [INFO] The backend and worker need backend\.env plus a reachable Redis instance.
    pause
    exit /b 1
)

echo [INFO] Checking Redis connectivity...
"%PYTHON_EXE%" -c "import os, sys; sys.path.insert(0, os.environ['BACKEND_DIR']); from services.redis_service import ping_redis; raise SystemExit(0 if ping_redis() else 1)"
if errorlevel 1 (
    echo [WARN] Redis is not reachable. Background jobs will not run correctly until Redis is available.
)

echo [INFO] Starting backend API window...
start "Alchemy Backend" cmd /k "set APP_ROLE=api&& set BACKEND_DIR=%BACKEND_DIR%&& set PYTHON_EXE=%PYTHON_EXE%&& cd /d ""%BACKEND_DIR%"" && ""%PYTHON_EXE%"" -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo [INFO] Starting worker window...
start "Alchemy Worker" "%REPO_ROOT%\launch_worker_console.cmd"

echo [INFO] Starting frontend window...
start "Alchemy Frontend" cmd /k "cd /d ""%FRONTEND_DIR%"" && ""%PYTHON_EXE%"" -m http.server 3000 --bind 127.0.0.1"

call :wait_for_port 8000 30 Backend
call :wait_for_port 3000 20 Frontend

echo [INFO] Startup diagnostics:
powershell -NoProfile -Command "try { $response = Invoke-RestMethod -Uri '%BACKEND_URL%/health/detailed' -Method Get -TimeoutSec 10; $response | ConvertTo-Json -Depth 6 } catch { Write-Host '[WARN] Detailed health endpoint is not ready yet.' }"

echo [INFO] Opening Chrome...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" %FRONTEND_URL%
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" %FRONTEND_URL%
) else (
    start "" %FRONTEND_URL%
)

echo.
echo [INFO] Backend, worker, and frontend logs are running in their own windows.
echo [INFO] Close those windows to stop the local stack.
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
exit /b 0

:wait_for_port
set "TARGET_PORT=%~1"
set "MAX_ATTEMPTS=%~2"
set "TARGET_NAME=%~3"
set /a ATTEMPT=0

:wait_for_port_loop
set /a ATTEMPT+=1
for /f %%P in ('powershell -NoProfile -Command "$connection = Get-NetTCPConnection -LocalPort %TARGET_PORT% -State Listen -ErrorAction SilentlyContinue ^| Select-Object -First 1; if ($connection) { Write-Output ready }"') do (
    if /I "%%P"=="ready" (
        echo [INFO] %TARGET_NAME% is listening on port %TARGET_PORT%.
        exit /b 0
    )
)

if %ATTEMPT% GEQ %MAX_ATTEMPTS% (
    echo [WARN] %TARGET_NAME% did not open port %TARGET_PORT% within the expected time.
    exit /b 0
)

timeout /t 1 >nul
goto :wait_for_port_loop
