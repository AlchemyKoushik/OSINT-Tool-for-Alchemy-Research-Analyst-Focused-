Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-RobocopyCopy {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /R:1 /W:1 /NFL /NDL /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed with exit code $LASTEXITCODE."
    }
}

function Get-PythonCommand {
    $candidates = @(
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3") },
        [PSCustomObject]@{ FilePath = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        try {
            $null = & $candidate.FilePath @($candidate.Arguments + @("--version")) 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
        }
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Python was not found. Installing Python 3.11 with winget..."
        # Do not let winget success output become part of this function's return value.
        & winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements | Out-Host
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3.11") }
        }
    }

    throw "Python 3.11+ is required for installation."
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $shortcut.Save()
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$payloadAppRoot = Join-Path $scriptRoot "payload\app"
$payloadSupportRoot = Join-Path $scriptRoot "payload\support"

if (-not (Test-Path -LiteralPath $payloadAppRoot)) {
    throw "Missing payload app folder: $payloadAppRoot"
}

if (-not (Test-Path -LiteralPath $payloadSupportRoot)) {
    throw "Missing payload support folder: $payloadSupportRoot"
}

$installRoot = Join-Path $env:LOCALAPPDATA "AlchemyIndustryResearchTool"
$appRoot = Join-Path $installRoot "app"
$runRoot = Join-Path $installRoot "run"
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Alchemy Industry Research Tool.lnk"
$pythonInfo = Get-PythonCommand

New-Item -ItemType Directory -Force -Path $installRoot, $runRoot | Out-Null

Write-Host ""
Write-Host "Installing Alchemy Industry Research Tool..."
Write-Host "Install path: $installRoot"

Invoke-RobocopyCopy -Source $payloadSupportRoot -Destination $installRoot
Invoke-RobocopyCopy -Source $payloadAppRoot -Destination $appRoot

attrib +h $installRoot | Out-Null

$venvPath = Join-Path $installRoot ".venv"
if (-not (Test-Path -LiteralPath $venvPath)) {
    Write-Host "Creating local virtual environment..."
    & $pythonInfo.FilePath @($pythonInfo.Arguments + @("-m", "venv", $venvPath))
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed."
    }
}

$pythonExe = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Installed Python environment is missing: $pythonExe"
}

$requirementsFile = Join-Path $appRoot "backend\requirements.txt"
if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw "Package payload is incomplete. Missing requirements file: $requirementsFile"
}

Write-Host "Installing Python requirements..."
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}
& $pythonExe -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Host "Installing Playwright Chromium runtime..."
& $pythonExe -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw "Playwright Chromium installation failed."
}

New-DesktopShortcut -ShortcutPath $desktopShortcut -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") -WorkingDirectory $installRoot

Write-Host ""
Write-Host "Installation complete."
Write-Host "Desktop launcher created:"
Write-Host "  $desktopShortcut"
Write-Host ""
Write-Host "If backend\.env is not present in the hidden install, the Start option will fail until secrets are provided."
