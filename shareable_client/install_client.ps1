param(
    [string]$ResolvedPythonPath = "",
    [string]$OriginalUserName = "",
    [string]$OriginalUserProfile = "",
    [string]$OriginalLocalAppData = "",
    [string]$OriginalOneDriveCommercial = "",
    [string]$OriginalOneDriveConsumer = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "installer_common.ps1")

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

function Ensure-ElevatedInstaller {
    if (Test-IsAdministrator) {
        return
    }

    Write-InstallerStage "Requesting administrator permission..."

    $argumentList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath
    )

    if ($ResolvedPythonPath) {
        $argumentList += @("-ResolvedPythonPath", $ResolvedPythonPath)
    }

    foreach ($pair in @(
        @("-OriginalUserName", $OriginalUserName),
        @("-OriginalUserProfile", $OriginalUserProfile),
        @("-OriginalLocalAppData", $OriginalLocalAppData),
        @("-OriginalOneDriveCommercial", $OriginalOneDriveCommercial),
        @("-OriginalOneDriveConsumer", $OriginalOneDriveConsumer)
    )) {
        if ($pair[1]) {
            $argumentList += $pair
        }
    }

    try {
        $null = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argumentList -PassThru
    } catch {
        throw "Administrator permission was not granted. Installation cancelled."
    }

    exit 0
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

function Reset-BrokenVirtualEnvironment {
    param([Parameter(Mandatory = $true)][string]$VenvPath)

    $venvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPath)) {
        return
    }

    if (Test-Path -LiteralPath $venvPython) {
        return
    }

    Write-InstallerStage "Removing incomplete virtual environment from a previous install attempt..."
    Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
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

$userContext = Get-InstallerUserContext `
    -OriginalUserName $OriginalUserName `
    -OriginalUserProfile $OriginalUserProfile `
    -OriginalLocalAppData $OriginalLocalAppData `
    -OriginalOneDriveCommercial $OriginalOneDriveCommercial `
    -OriginalOneDriveConsumer $OriginalOneDriveConsumer

$installRoot = Join-Path $userContext.LocalAppData "AlchemyIndustryResearchTool"
$appRoot = Join-Path $installRoot "app"
$runRoot = Join-Path $installRoot "run"

Ensure-ElevatedInstaller

if ($ResolvedPythonPath) {
    $pythonInfo = Test-PythonCandidate -FilePath $ResolvedPythonPath
    if (-not $pythonInfo) {
        Write-Host "The provided Python path is not usable anymore. Resolving Python again..."
        $pythonInfo = Ensure-PythonInterpreter
    }
} else {
    $pythonInfo = Ensure-PythonInterpreter
}

New-Item -ItemType Directory -Force -Path $installRoot, $runRoot | Out-Null
Set-InstallerLogPath -Path (Join-Path $runRoot "install.last.log")

Write-InstallerStage "Installing Alchemy Industry Research Tool..."
Write-Host "Install path: $installRoot"

Invoke-RobocopyCopy -Source $payloadSupportRoot -Destination $installRoot
Invoke-RobocopyCopy -Source $payloadAppRoot -Destination $appRoot

attrib +h $installRoot | Out-Null

$venvPath = Join-Path $installRoot ".venv"
Reset-BrokenVirtualEnvironment -VenvPath $venvPath
if (-not (Test-Path -LiteralPath $venvPath)) {
    Write-InstallerStage "Creating local virtual environment..."
    & $pythonInfo.Path -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed."
    }
}

$pythonExe = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Installed Python environment is missing: $pythonExe"
}

& $pythonExe -m ensurepip --upgrade | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "ensurepip failed for the virtual environment."
}

$requirementsFile = Join-Path $appRoot "backend\requirements.txt"
if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw "Package payload is incomplete. Missing requirements file: $requirementsFile"
}

Write-InstallerStage "Installing application dependencies..."
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}
& $pythonExe -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-InstallerStage "Installing Playwright Chromium runtime..."
& $pythonExe -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw "Playwright Chromium installation failed."
}

foreach ($desktopPath in $userContext.DesktopCandidates) {
    if (-not (Test-Path -LiteralPath $desktopPath)) {
        continue
    }

    $desktopShortcut = Join-Path $desktopPath "Alchemy Industry Research Tool.lnk"
    New-DesktopShortcut -ShortcutPath $desktopShortcut -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") -WorkingDirectory $installRoot
    Write-Host "Desktop launcher created:"
    Write-Host "  $desktopShortcut"
    break
}

Write-InstallerStage "Installation complete."
Write-Host ""
Write-Host "If backend\.env is not present in the hidden install, the Start option will fail until secrets are provided."
