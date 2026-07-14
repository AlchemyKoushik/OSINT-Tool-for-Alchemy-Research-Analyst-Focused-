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

function Get-ShortcutTargetPath {
    param([Parameter(Mandatory = $true)][string]$ShortcutPath)

    if (-not (Test-Path -LiteralPath $ShortcutPath)) {
        return ""
    }

    try {
        $wshShell = New-Object -ComObject WScript.Shell
        $shortcut = $wshShell.CreateShortcut($ShortcutPath)
        return [string]$shortcut.TargetPath
    } catch {
        return ""
    }
}

function New-StartMenuShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ProgramsPath,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string[]]$LegacyPrefixes = @()
    )

    if (-not (Test-Path -LiteralPath $ProgramsPath)) {
        return $null
    }

    $shortcutPath = Join-Path $ProgramsPath "Alchemy Industry Research Tool.lnk"
    [void](Remove-LegacyShortcutIfPresent -ShortcutPath $shortcutPath -LegacyPrefixes $LegacyPrefixes)
    New-DesktopShortcut -ShortcutPath $shortcutPath -TargetPath $TargetPath -WorkingDirectory $WorkingDirectory
    return $shortcutPath
}

function Remove-LegacyShortcutIfPresent {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string[]]$LegacyPrefixes
    )

    if (-not (Test-Path -LiteralPath $ShortcutPath)) {
        return $false
    }

    $targetPath = Get-ShortcutTargetPath -ShortcutPath $ShortcutPath
    foreach ($legacyPrefix in $LegacyPrefixes) {
        if (-not $legacyPrefix) {
            continue
        }

        if ($targetPath.StartsWith($legacyPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
            return $true
        }
    }

    return $false
}

function Remove-LegacyUserRuntimeRoot {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)

    if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
        return $false
    }

    $resolvedRuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRoot).Path
    $expectedPrefix = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Alchemy"))
    if (-not $resolvedRuntimeRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove an unexpected legacy runtime path: $resolvedRuntimeRoot"
    }

    Remove-Item -LiteralPath $resolvedRuntimeRoot -Recurse -Force -ErrorAction SilentlyContinue
    return (-not (Test-Path -LiteralPath $resolvedRuntimeRoot))
}

function Write-InstallManifest {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$AppRoot,
        [Parameter(Mandatory = $true)][string]$PythonPath
    )

    $manifestPath = Join-Path $InstallRoot "install-manifest.json"
    $manifest = [PSCustomObject]@{
        install_root        = $InstallRoot
        app_root            = $AppRoot
        python_path         = $PythonPath
        supported_sections  = @("trends", "drivers", "competitive_landscape")
        launcher_mode       = "shareable_client"
        installed_at_utc    = (Get-Date).ToUniversalTime().ToString("o")
    }

    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
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
$legacyProgramFilesRoot = Join-Path ${env:ProgramFiles} "Alchemy OSINT Tool"
$legacyUserRuntimeRoot = Join-Path $userContext.LocalAppData "Alchemy\OSINTTool"
$legacyPrefixes = @(
    [System.IO.Path]::GetFullPath($legacyProgramFilesRoot),
    [System.IO.Path]::GetFullPath($legacyUserRuntimeRoot)
)

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

$legacyRuntimeRemoved = $false
try {
    $legacyRuntimeRemoved = Remove-LegacyUserRuntimeRoot -RuntimeRoot $legacyUserRuntimeRoot
} catch {
    Write-Host "Legacy runtime cleanup skipped: $($_.Exception.Message)"
}
if ($legacyRuntimeRemoved) {
    Write-Host "Removed legacy user runtime:"
    Write-Host "  $legacyUserRuntimeRoot"
}

foreach ($desktopPath in $userContext.DesktopCandidates) {
    if (-not (Test-Path -LiteralPath $desktopPath)) {
        continue
    }

    $desktopShortcut = Join-Path $desktopPath "Alchemy Industry Research Tool.lnk"
    [void](Remove-LegacyShortcutIfPresent -ShortcutPath $desktopShortcut -LegacyPrefixes $legacyPrefixes)
    New-DesktopShortcut -ShortcutPath $desktopShortcut -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") -WorkingDirectory $installRoot
    Write-Host "Desktop launcher created:"
    Write-Host "  $desktopShortcut"
    break
}

$startMenuShortcut = New-StartMenuShortcut `
    -ProgramsPath $userContext.StartMenuPrograms `
    -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") `
    -WorkingDirectory $installRoot `
    -LegacyPrefixes $legacyPrefixes
if ($startMenuShortcut) {
    Write-Host "Start menu launcher created:"
    Write-Host "  $startMenuShortcut"
}

Write-InstallManifest -InstallRoot $installRoot -AppRoot $appRoot -PythonPath $pythonExe

Write-InstallerStage "Installation complete."
Write-Host ""
Write-Host "The application files are stored in the hidden folder:"
Write-Host "  $installRoot"
Write-Host "Use the desktop or Start menu shortcut to open the launcher TUI."
if (Test-Path -LiteralPath $legacyProgramFilesRoot) {
    Write-Host ""
    Write-Host "Legacy desktop install detected at:"
    Write-Host "  $legacyProgramFilesRoot"
    Write-Host "If this machine still opens the old UI, remove that old install and use the new desktop or Start menu shortcut."
}
Write-Host "If backend\.env is not present in the hidden install, the Start option will fail until secrets are provided."
