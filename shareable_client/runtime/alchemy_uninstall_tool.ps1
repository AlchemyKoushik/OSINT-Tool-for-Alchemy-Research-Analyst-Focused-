Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Stop-TrackedProcess {
    param([Parameter(Mandatory = $true)][string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }

    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($raw) {
        $pidValue = [int]$raw
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $pidValue -Force
        }
    }

    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

$confirmation = Read-Host "Type REMOVE to uninstall the tool"
$normalizedConfirmation = [string]$confirmation
if ($normalizedConfirmation.Trim().ToUpperInvariant() -ne "REMOVE") {
    Write-Host "Uninstall cancelled."
    Start-Sleep -Seconds 2
    exit 0
}

$installRoot = $PSScriptRoot
$resolvedInstallRoot = (Resolve-Path $installRoot).Path
$expectedPrefix = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "AlchemyIndustryResearchTool"))
if (-not $resolvedInstallRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove an unexpected install path: $resolvedInstallRoot"
}

$runRoot = Join-Path $installRoot "run"
Stop-TrackedProcess -PidFile (Join-Path $runRoot "backend.pid")
Stop-TrackedProcess -PidFile (Join-Path $runRoot "worker.pid")
Stop-TrackedProcess -PidFile (Join-Path $runRoot "frontend.pid")

$desktopCandidates = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "Desktop"),
    $(if ($env:OneDriveCommercial) { Join-Path $env:OneDriveCommercial "Desktop" }),
    $(if ($env:OneDriveConsumer) { Join-Path $env:OneDriveConsumer "Desktop" }),
    (Join-Path $env:USERPROFILE "OneDrive - Alchemy Research and Analytics\Desktop")
) | Where-Object { $_ } | Select-Object -Unique

foreach ($desktopPath in $desktopCandidates) {
    Remove-Item -LiteralPath (Join-Path $desktopPath "Alchemy Industry Research Tool.lnk") -Force -ErrorAction SilentlyContinue
}

$startMenuPrograms = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
Remove-Item -LiteralPath (Join-Path $startMenuPrograms "Alchemy Industry Research Tool.lnk") -Force -ErrorAction SilentlyContinue

$cleanupScript = Join-Path $env:TEMP ("alchemy-uninstall-" + [guid]::NewGuid().ToString("N") + ".cmd")
$cleanupBody = @"
@echo off
setlocal EnableExtensions
cd /d "%TEMP%"
for /l %%I in (1,1,15) do (
    if exist "$resolvedInstallRoot" rd /s /q "$resolvedInstallRoot" >nul 2>nul
    if not exist "$resolvedInstallRoot" goto done
    ping 127.0.0.1 -n 2 >nul
)
:done
del "%~f0" >nul 2>nul
"@
Set-Content -LiteralPath $cleanupScript -Value $cleanupBody -Encoding ASCII

Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $cleanupScript) -WorkingDirectory $env:TEMP -WindowStyle Hidden | Out-Null

Write-Host "The tool is being removed from this device."
Start-Sleep -Seconds 2
