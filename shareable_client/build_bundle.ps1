param(
    [string]$OutputRoot = "",
    [switch]$IncludeSecrets
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-RobocopyCopy {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExcludeDirectories = @(),
        [string[]]$ExcludeFiles = @()
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $arguments = @($Source, $Destination, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NP")
    if ($ExcludeDirectories.Count -gt 0) {
        $arguments += "/XD"
        $arguments += $ExcludeDirectories
    }
    if ($ExcludeFiles.Count -gt 0) {
        $arguments += "/XF"
        $arguments += $ExcludeFiles
    }

    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed with exit code $LASTEXITCODE."
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$resolvedRepoRoot = (Resolve-Path $repoRoot).Path

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $scriptRoot "dist\alchemy-shareable-client"
}

$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$payloadRoot = Join-Path $resolvedOutputRoot "payload"
$payloadAppRoot = Join-Path $payloadRoot "app"
$payloadSupportRoot = Join-Path $payloadRoot "support"
$resolvedDistRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot "dist"))

if (Test-Path -LiteralPath $resolvedOutputRoot) {
    Remove-Item -LiteralPath $resolvedOutputRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $resolvedOutputRoot, $payloadRoot, $payloadAppRoot, $payloadSupportRoot | Out-Null

$excludeDirectories = @(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "research_artifacts",
    "shareable_client\dist",
    $resolvedOutputRoot,
    $resolvedDistRoot
)
$excludeFiles = @(
    "*.pyc",
    "*.pyo",
    "*.log"
)

if (-not $IncludeSecrets) {
    $excludeFiles += ".env"
}

Invoke-RobocopyCopy -Source $resolvedRepoRoot -Destination $payloadAppRoot -ExcludeDirectories $excludeDirectories -ExcludeFiles $excludeFiles
Invoke-RobocopyCopy -Source (Join-Path $scriptRoot "runtime") -Destination $payloadSupportRoot

Copy-Item -LiteralPath (Join-Path $scriptRoot "install_client.ps1") -Destination (Join-Path $resolvedOutputRoot "install_client.ps1")
Copy-Item -LiteralPath (Join-Path $scriptRoot "Run Alchemy Installer.bat") -Destination (Join-Path $resolvedOutputRoot "Run Alchemy Installer.bat")
Copy-Item -LiteralPath (Join-Path $scriptRoot "bootstrap_install.ps1") -Destination (Join-Path $resolvedOutputRoot "bootstrap_install.ps1")

$zipPath = "$resolvedOutputRoot.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $resolvedOutputRoot "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Alchemy shareable bundle created at:"
Write-Host "  $resolvedOutputRoot"
Write-Host "Zip:"
Write-Host "  $zipPath"
if (-not $IncludeSecrets) {
    Write-Host ""
    Write-Host "Secrets were excluded from this bundle."
    Write-Host "Use bootstrap_install.ps1 with -EnvUrl, or rebuild with -IncludeSecrets."
}
