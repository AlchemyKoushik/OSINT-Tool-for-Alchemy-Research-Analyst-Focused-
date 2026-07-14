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

function New-StartMenuShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ProgramsPath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    if (-not (Test-Path -LiteralPath $ProgramsPath)) {
        return $null
    }

    $shortcutPath = Join-Path $ProgramsPath "Alchemy Industry Research Tool.lnk"
    New-DesktopShortcut -ShortcutPath $shortcutPath -TargetPath $TargetPath -WorkingDirectory $WorkingDirectory
    return $shortcutPath
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

function Remove-LocalVirtualEnvironment {
    param([Parameter(Mandatory = $true)][string]$VenvPath)

    if (Test-Path -LiteralPath $VenvPath) {
        Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-LocalVirtualEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$BasePythonPath,
        [Parameter(Mandatory = $true)][string]$VenvPath
    )

    Write-InstallerStage "Creating local virtual environment..."
    & $BasePythonPath -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed."
    }
}

function Initialize-LocalVirtualEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$BasePythonPath,
        [Parameter(Mandatory = $true)][string]$VenvPath
    )

    Reset-BrokenVirtualEnvironment -VenvPath $VenvPath

    $rebuilt = $false
    while ($true) {
        if (-not (Test-Path -LiteralPath $VenvPath)) {
            New-LocalVirtualEnvironment -BasePythonPath $BasePythonPath -VenvPath $VenvPath
        }

        $venvPython = Join-Path $VenvPath "Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            if ($rebuilt) {
                throw "Installed Python environment is missing: $venvPython"
            }

            Write-InstallerStage "Detected a broken local virtual environment. Rebuilding it..."
            Remove-LocalVirtualEnvironment -VenvPath $VenvPath
            $rebuilt = $true
            continue
        }

        & $venvPython -m ensurepip --upgrade | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return $venvPython
        }

        if ($rebuilt) {
            throw "ensurepip failed for the virtual environment."
        }

        Write-InstallerStage "Detected a broken local virtual environment. Rebuilding it..."
        Remove-LocalVirtualEnvironment -VenvPath $VenvPath
        $rebuilt = $true
    }
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
$pythonExe = Initialize-LocalVirtualEnvironment -BasePythonPath $pythonInfo.Path -VenvPath $venvPath

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

$startMenuShortcut = New-StartMenuShortcut `
    -ProgramsPath $userContext.StartMenuPrograms `
    -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") `
    -WorkingDirectory $installRoot
if ($startMenuShortcut) {
    Write-Host "Start menu launcher created:"
    Write-Host "  $startMenuShortcut"
}

Write-InstallerStage "Installation complete."
Write-Host ""
Write-Host "The application files are stored in the hidden folder:"
Write-Host "  $installRoot"
Write-Host "Use the desktop or Start menu shortcut to open the launcher TUI."
Write-Host "If backend\.env is not present in the hidden install, the Start option will fail until secrets are provided."
