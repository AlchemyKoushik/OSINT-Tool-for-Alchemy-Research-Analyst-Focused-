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
        [Parameter(Mandatory = $true)][string]$ShortcutName,
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string[]]$LegacyPrefixes = @()
    )

    if (-not (Test-Path -LiteralPath $ProgramsPath)) {
        return $null
    }

    $shortcutPath = Join-Path $ProgramsPath $ShortcutName
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
        supported_sections  = @("trends", "competitive_landscape")
        follow_up_enabled   = $false
        launcher_mode       = "shareable_client"
        installed_at_utc    = (Get-Date).ToUniversalTime().ToString("o")
    }

    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$StageName,
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [int]$MaxAttempts = 3,
        [int]$DelaySeconds = 3
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $ScriptBlock
            return
        } catch {
            $lastError = $_
            if ($attempt -ge $MaxAttempts) {
                break
            }

            Write-Host "$StageName failed on attempt $attempt of $MaxAttempts. Retrying in $DelaySeconds second(s)..."
            Start-Sleep -Seconds $DelaySeconds
        }
    }

    throw $lastError
}

function Set-DotEnvKey {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }

    $updated = $false
    $outputLines = @(
        foreach ($line in $lines) {
        if ([string]$line -match "^\s*$([regex]::Escape($Key))\s*=") {
            $updated = $true
            "{0}={1}" -f $Key, $Value
        } else {
            $line
        }
        }
    )

    if (-not $updated) {
        $outputLines += "{0}={1}" -f $Key, $Value
    }

    Set-Content -LiteralPath $Path -Value $outputLines -Encoding UTF8
}

function Write-ClientBackendOverrides {
    param([Parameter(Mandatory = $true)][string]$BackendEnvPath)

    if (-not (Test-Path -LiteralPath $BackendEnvPath)) {
        return
    }

    Set-DotEnvKey -Path $BackendEnvPath -Key "ALLOWED_RESEARCH_SECTIONS" -Value "trends,competitive_landscape"
    Set-DotEnvKey -Path $BackendEnvPath -Key "FOLLOW_UP_ENABLED" -Value "false"
}

function Get-DotEnvMap {
    param([Parameter(Mandatory = $true)][string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }

    foreach ($rawLine in (Get-Content -LiteralPath $Path)) {
        $line = [string]$rawLine
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("#")) {
            continue
        }

        $separatorIndex = $trimmed.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $trimmed.Substring(0, $separatorIndex).Trim()
        $value = $trimmed.Substring($separatorIndex + 1).Trim()
        if (-not $key) {
            continue
        }

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $values[$key] = $value
    }

    return $values
}

function Test-RequiredBackendEnvironment {
    param([Parameter(Mandatory = $true)][string]$BackendEnvPath)

    if (-not (Test-Path -LiteralPath $BackendEnvPath)) {
        throw "Missing backend environment file in the installed payload: $BackendEnvPath"
    }

    $envValues = Get-DotEnvMap -Path $BackendEnvPath
    $requiredKeys = @(
        "OPENAI_API_KEY",
        "SCRAPEDO_KEY",
        "REDIS_URL",
        "CLOUDFLARE_R2_ACCOUNT_ID",
        "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "CLOUDFLARE_R2_BUCKET_NAME"
    )

    $missingKeys = @(
        foreach ($key in $requiredKeys) {
            if (-not $envValues.ContainsKey($key) -or [string]::IsNullOrWhiteSpace([string]$envValues[$key])) {
                $key
            }
        }
    )

    if ($missingKeys.Count -gt 0) {
        throw ("backend\\.env is missing required values: " + ($missingKeys -join ", "))
    }
}

function Test-BackendPythonConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$BackendDir
    )

    $probeCode = @'
from config.settings import settings

settings.validate_required(
    (
        "OPENAI_API_KEY",
        "SCRAPEDO_KEY",
        "REDIS_URL",
        "CLOUDFLARE_R2_ACCOUNT_ID",
        "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "CLOUDFLARE_R2_BUCKET_NAME",
    )
)
print("backend-env-ok")
'@

    $probePath = Join-Path $BackendDir "__installer_env_probe__.py"
    try {
        Set-Content -LiteralPath $probePath -Value $probeCode -Encoding ASCII
        & $PythonExe $probePath
        if ($LASTEXITCODE -ne 0) {
            throw "Python backend environment validation failed."
        }
    } finally {
        Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
    }
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
$backendEnvPath = Join-Path $appRoot "backend\.env"
Write-ClientBackendOverrides -BackendEnvPath $backendEnvPath
Test-RequiredBackendEnvironment -BackendEnvPath $backendEnvPath

if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw "Package payload is incomplete. Missing requirements file: $requirementsFile"
}

Write-InstallerStage "Installing application dependencies..."
Invoke-WithRetry -StageName "pip upgrade" -ScriptBlock {
    & $pythonExe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed."
    }
}
Invoke-WithRetry -StageName "Dependency installation" -ScriptBlock {
    & $pythonExe -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

Write-InstallerStage "Installing Playwright Chromium runtime..."
Invoke-WithRetry -StageName "Playwright Chromium installation" -ScriptBlock {
    & $pythonExe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright Chromium installation failed."
    }
} -MaxAttempts 2 -DelaySeconds 5

Write-InstallerStage "Validating backend configuration..."
Test-BackendPythonConfiguration -PythonExe $pythonExe -BackendDir (Join-Path $appRoot "backend")

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
    -ShortcutName "Alchemy Industry Research Tool.lnk" `
    -TargetPath (Join-Path $installRoot "Alchemy Industry Research Tool.bat") `
    -WorkingDirectory $installRoot `
    -LegacyPrefixes $legacyPrefixes
if ($startMenuShortcut) {
    Write-Host "Start menu launcher created:"
    Write-Host "  $startMenuShortcut"
}

$startMenuUninstallShortcut = New-StartMenuShortcut `
    -ProgramsPath $userContext.StartMenuPrograms `
    -ShortcutName "Uninstall Alchemy Industry Research Tool.lnk" `
    -TargetPath (Join-Path $installRoot "Uninstall Alchemy Industry Research Tool.bat") `
    -WorkingDirectory $installRoot `
    -LegacyPrefixes $legacyPrefixes
if ($startMenuUninstallShortcut) {
    Write-Host "Start menu uninstall shortcut created:"
    Write-Host "  $startMenuUninstallShortcut"
}

Write-InstallManifest -InstallRoot $installRoot -AppRoot $appRoot -PythonPath $pythonExe

Write-InstallerStage "Installation complete."
Write-Host ""
Write-Host "The application files are stored in the hidden folder:"
Write-Host "  $installRoot"
Write-Host "Use the desktop or Start menu shortcut to open the launcher TUI."
Write-Host "Direct uninstall command:"
Write-Host "  $(Join-Path $installRoot 'Uninstall Alchemy Industry Research Tool.bat')"
if (Test-Path -LiteralPath $legacyProgramFilesRoot) {
    Write-Host ""
    Write-Host "Legacy desktop install detected at:"
    Write-Host "  $legacyProgramFilesRoot"
    Write-Host "If this machine still opens the old UI, remove that old install and use the new desktop or Start menu shortcut."
}
Write-Host "If backend\.env is not present in the hidden install, the Start option will fail until secrets are provided."
