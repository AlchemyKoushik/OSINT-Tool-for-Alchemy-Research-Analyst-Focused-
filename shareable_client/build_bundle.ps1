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

function Remove-PathIfPresent {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Remove-PathsByPattern {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        Get-ChildItem -LiteralPath $Root -Filter $pattern -Force -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$resolvedRepoRoot = (Resolve-Path $repoRoot).Path

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $scriptRoot "dist\alchemy-shareable-client-build"
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
    (Join-Path $resolvedRepoRoot ".git"),
    (Join-Path $resolvedRepoRoot ".venv"),
    (Join-Path $resolvedRepoRoot "venv"),
    (Join-Path $resolvedRepoRoot "__pycache__"),
    (Join-Path $resolvedRepoRoot "node_modules"),
    (Join-Path $resolvedRepoRoot "research_artifacts"),
    (Join-Path $resolvedRepoRoot ".pytest_cache"),
    (Join-Path $resolvedRepoRoot "runtime_logs"),
    (Join-Path $resolvedRepoRoot "shareable_client\dist"),
    $resolvedOutputRoot,
    $resolvedDistRoot
)
$excludeFiles = @(
    "*.pyc",
    "*.pyo",
    "*.log",
    "uvicorn-ma.stderr.log",
    "uvicorn-ma.stdout.log"
)

if (-not $IncludeSecrets) {
    $excludeFiles += ".env"
}

Invoke-RobocopyCopy -Source $resolvedRepoRoot -Destination $payloadAppRoot -ExcludeDirectories $excludeDirectories -ExcludeFiles $excludeFiles
Invoke-RobocopyCopy -Source (Join-Path $scriptRoot "runtime") -Destination $payloadSupportRoot

$frontendConfigOverride = Join-Path $scriptRoot "client-config.shareable.json"
if (Test-Path -LiteralPath $frontendConfigOverride) {
    Copy-Item -LiteralPath $frontendConfigOverride -Destination (Join-Path $payloadAppRoot "frontend\client-config.json") -Force
}

foreach ($path in @(
    (Join-Path $payloadAppRoot "test_pipeline.py"),
    (Join-Path $payloadAppRoot "generate_trends_arch_doc.py"),
    (Join-Path $payloadAppRoot "OSINT_Tool_Alpha_Trends_Technical_Architecture.docx"),
    (Join-Path $payloadAppRoot "launch_alchemy.bat"),
    (Join-Path $payloadAppRoot "launch_backend_console.cmd"),
    (Join-Path $payloadAppRoot "launch_frontend_console.cmd"),
    (Join-Path $payloadAppRoot "launch_worker_console.cmd"),
    (Join-Path $payloadAppRoot "run_backend.bat"),
    (Join-Path $payloadAppRoot "run_fullstack.bat"),
    (Join-Path $payloadAppRoot "backend\docs"),
    (Join-Path $payloadAppRoot "backend\render.yaml"),
    (Join-Path $payloadAppRoot "backend\Procfile"),
    (Join-Path $payloadAppRoot "backend\scripts"),
    (Join-Path $payloadAppRoot "frontend\vercel.json"),
    (Join-Path $payloadAppRoot "shareable_client\dist"),
    (Join-Path $payloadAppRoot "shareable_client\tests")
)) {
    Remove-PathIfPresent -Path $path
}

Remove-PathsByPattern -Root (Join-Path $payloadAppRoot "backend") -Patterns @(
    "tmp_*.json",
    "test*.py"
)

Copy-Item -LiteralPath (Join-Path $scriptRoot "install_client.ps1") -Destination (Join-Path $resolvedOutputRoot "install_client.ps1")
Copy-Item -LiteralPath (Join-Path $scriptRoot "installer_common.ps1") -Destination (Join-Path $resolvedOutputRoot "installer_common.ps1")
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
