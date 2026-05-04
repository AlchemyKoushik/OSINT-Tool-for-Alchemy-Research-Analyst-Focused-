@echo off
setlocal

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "BACKEND_DIR=%REPO_ROOT%\backend"
set "FRONTEND_DIR=%REPO_ROOT%\frontend"
set "BACKEND_ENV_FILE=%BACKEND_DIR%\.env"
set "BACKEND_ENV_EXAMPLE=%BACKEND_DIR%\.env.example"
set "PYTHON_EXE="
set "FRONTEND_URL=http://127.0.0.1:3000"
set "BACKEND_URL=http://127.0.0.1:8000"

echo =================================
echo Starting Full Stack Application...
echo =================================

cd /d "%REPO_ROOT%"

call :stop_port 8000 "Backend"
call :stop_port 3000 "Frontend"

if not exist "%BACKEND_DIR%\main.py" (
    echo [ERROR] Backend entrypoint not found: %BACKEND_DIR%\main.py
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
    echo [ERROR] Frontend entrypoint not found: %FRONTEND_DIR%\index.html
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
echo [INFO] Checked local venv, local .venv, sibling ..\venv, C:\Python314\python.exe, Python 3.11, and PATH.
pause
exit /b 1

:python_found
echo [INFO] Using Python: %PYTHON_EXE%

if not exist "%BACKEND_ENV_FILE%" (
    echo [WARN] Backend env file not found: %BACKEND_ENV_FILE%
    if exist "%BACKEND_ENV_EXAMPLE%" (
        echo [INFO] Fill in backend\.env using backend\.env.example before expecting backend startup.
    ) else (
        echo [INFO] Create backend\.env with the required keys before expecting backend startup.
    )
    echo [INFO] Skipping backend startup for now.
) else (
    echo [INFO] Starting Backend...
    start "OSINT Backend" /b cmd /d /c "cd /d ""%BACKEND_DIR%"" && ""%PYTHON_EXE%"" -m uvicorn main:app --host 127.0.0.1 --port 8000"
)

echo [INFO] Starting Frontend server...
start "OSINT Frontend" /b cmd /d /c "cd /d ""%FRONTEND_DIR%"" && ""%PYTHON_EXE%"" -m http.server 3000 --bind 127.0.0.1"

call :wait_for_port 3000 20 "Frontend"
if exist "%BACKEND_ENV_FILE%" (
    call :wait_for_port 8000 30 "Backend"
)

echo [INFO] Opening Chrome on frontend...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" %FRONTEND_URL%
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" %FRONTEND_URL%
) else (
    start "" %FRONTEND_URL%
)

echo [INFO] Frontend URL: %FRONTEND_URL%
if exist "%BACKEND_ENV_FILE%" echo [INFO] Backend URL: %BACKEND_URL%
echo =================================
echo Backend and frontend logs will print below.
echo =================================
echo Leave this CMD window open while the app is running.
echo.
pause >nul
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

call :wait_for_port_clear %TARGET_PORT% 10 "%TARGET_NAME%"
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

:wait_for_port_clear
set "TARGET_PORT=%~1"
set "MAX_ATTEMPTS=%~2"
set "TARGET_NAME=%~3"
set /a ATTEMPT=0

:wait_for_port_clear_loop
set /a ATTEMPT+=1
netstat -ano | findstr /C:":%TARGET_PORT%" | findstr /C:"LISTENING" >nul
if errorlevel 1 (
    echo [INFO] %TARGET_NAME% port %TARGET_PORT% is clear.
    exit /b 0
)

if %ATTEMPT% GEQ %MAX_ATTEMPTS% (
    echo [WARN] %TARGET_NAME% port %TARGET_PORT% is still busy.
    exit /b 0
)

timeout /t 1 >nul
goto :wait_for_port_clear_loop
