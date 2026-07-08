Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-LauncherErrorSummary {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$RunRoot,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
    $errorLogPath = Join-Path $RunRoot "launcher.last_error.log"
    $lines = @(
        "timestamp=$(Get-Date -Format o)",
        "message=$($ErrorRecord.Exception.Message)",
        "install_root=$InstallRoot",
        "python_exe=$(Join-Path $InstallRoot '.venv\Scripts\python.exe')",
        "env_file=$(Join-Path $InstallRoot 'app\backend\.env')",
        "backend_stderr=$(Join-Path $RunRoot 'backend.stderr.log')",
        "worker_stderr=$(Join-Path $RunRoot 'worker.stderr.log')",
        "frontend_stderr=$(Join-Path $RunRoot 'frontend.stderr.log')"
    )
    Set-Content -LiteralPath $errorLogPath -Value $lines -Encoding ASCII
    return $errorLogPath
}

function Wait-BeforeExit {
    Write-Host ""
    [void](Read-Host "Press Enter to close this launcher")
}

function Test-PortReady {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$Attempts = 30
    )

    for ($index = 0; $index -lt $Attempts; $index++) {
        $client = $null
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $asyncResult = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($asyncResult.AsyncWaitHandle.WaitOne(1000) -and $client.Connected) {
                $client.EndConnect($asyncResult)
                return $true
            }
        } catch {
        } finally {
            if ($client) {
                $client.Dispose()
            }
        }
        if ($index -lt ($Attempts - 1)) {
            Start-Sleep -Seconds 1
        }
    }

    return $false
}

function Get-PidFromFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $raw = (Get-Content -LiteralPath $Path -Raw).Trim()
    if (-not $raw) {
        return $null
    }

    return [int]$raw
}

function Save-Pid {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    Set-Content -LiteralPath $Path -Value $ProcessId -Encoding ASCII
}

function Ensure-BackgroundProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$ReadyPort,
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StdOutLog,
        [Parameter(Mandatory = $true)][string]$StdErrLog,
        [int]$Attempts = 30
    )

    if (Test-PortReady -Port $ReadyPort -Attempts 2) {
        return
    }

    $existingPid = Get-PidFromFile -Path $PidFile
    if ($existingPid) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Stop-Process -Id $existingPid -Force
            Start-Sleep -Seconds 1
        }
    }

    if (Test-PortReady -Port $ReadyPort -Attempts 2) {
        return
    }

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog -PassThru
    Save-Pid -Path $PidFile -ProcessId $process.Id

    if (-not (Test-PortReady -Port $ReadyPort -Attempts $Attempts)) {
        throw "$Name failed to become ready. Check logs in $WorkingDirectory."
    }
}

function Ensure-WorkerProcess {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StdOutLog,
        [Parameter(Mandatory = $true)][string]$StdErrLog
    )

    $existingPid = Get-PidFromFile -Path $PidFile
    if ($existingPid) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            return
        }
    }

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog -PassThru
    Save-Pid -Path $PidFile -ProcessId $process.Id
    Start-Sleep -Seconds 2

    $workerProcess = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
    if (-not $workerProcess) {
        throw "Worker failed to remain running. Check logs in $WorkingDirectory."
    }
}

$installRoot = $PSScriptRoot
$appRoot = Join-Path $installRoot "app"
$backendDir = Join-Path $appRoot "backend"
$frontendDir = Join-Path $appRoot "frontend"
$runRoot = Join-Path $installRoot "run"
$pythonExe = Join-Path $installRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $backendDir ".env"
$frontendUrl = "http://127.0.0.1:3000"
$backendPort = 8000
$frontendPort = 3000

New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Installed Python environment not found at $pythonExe"
    }

    if (-not (Test-Path -LiteralPath $envFile)) {
        throw "Missing backend environment file: $envFile"
    }

    Write-Host ""
    Write-Host "Starting Alchemy Industry Research Tool..."

    Ensure-BackgroundProcess `
        -Name "Backend" `
        -ReadyPort $backendPort `
        -PidFile (Join-Path $runRoot "backend.pid") `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backendDir `
        -StdOutLog (Join-Path $runRoot "backend.stdout.log") `
        -StdErrLog (Join-Path $runRoot "backend.stderr.log") `
        -Attempts 45

    Ensure-WorkerProcess `
        -PidFile (Join-Path $runRoot "worker.pid") `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "workers.worker") `
        -WorkingDirectory $backendDir `
        -StdOutLog (Join-Path $runRoot "worker.stdout.log") `
        -StdErrLog (Join-Path $runRoot "worker.stderr.log")

    Ensure-BackgroundProcess `
        -Name "Frontend" `
        -ReadyPort $frontendPort `
        -PidFile (Join-Path $runRoot "frontend.pid") `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "http.server", "3000", "--bind", "127.0.0.1") `
        -WorkingDirectory $frontendDir `
        -StdOutLog (Join-Path $runRoot "frontend.stdout.log") `
        -StdErrLog (Join-Path $runRoot "frontend.stderr.log") `
        -Attempts 20

    $chromeCandidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )

    $chromePath = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($chromePath) {
        Start-Process -FilePath $chromePath -ArgumentList $frontendUrl | Out-Null
    } else {
        Start-Process $frontendUrl | Out-Null
    }

    Write-Host ""
    Write-Host "The tool is running on $frontendUrl"
    Wait-BeforeExit
} catch {
    $errorLogPath = Write-LauncherErrorSummary -InstallRoot $installRoot -RunRoot $runRoot -ErrorRecord $_
    Write-Host ""
    Write-Host "The tool could not be started." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Error summary: $errorLogPath" -ForegroundColor Yellow
    Wait-BeforeExit
    exit 1
}
