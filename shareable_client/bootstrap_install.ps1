param(
    [Parameter(Mandatory = $true)][string]$BundleUrl,
    [string]$EnvUrl = "",
    [string]$EnvBearerToken = "",
    [string]$ExpectedSha256 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "installer_common.ps1")

function Get-TempPath {
    $root = Join-Path $env:TEMP ("alchemy-bootstrap-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    return $root
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$tempRoot = Get-TempPath
$zipPath = Join-Path $tempRoot "bundle.zip"
$extractRoot = Join-Path $tempRoot "bundle"

try {
    $pythonInfo = Ensure-PythonInterpreter

    Write-InstallerStage "Downloading application bundle..."
    Invoke-WebRequest -Uri $BundleUrl -OutFile $zipPath

    if ($ExpectedSha256) {
        Write-InstallerStage "Verifying SHA256..."
        $actualHash = Get-FileSha256 -Path $zipPath
        if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
            throw "Bundle hash mismatch. Expected $ExpectedSha256 but got $actualHash."
        }
    }

    Write-InstallerStage "Extracting bundle..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force

    if ($EnvUrl) {
        Write-InstallerStage "Retrieving environment configuration..."
        $headers = @{}
        if ($EnvBearerToken) {
            $headers["Authorization"] = "Bearer $EnvBearerToken"
        }
        $envContent = Invoke-WebRequest -Uri $EnvUrl -Headers $headers -UseBasicParsing
        $envTarget = Join-Path $extractRoot "payload\app\backend\.env"
        Set-Content -LiteralPath $envTarget -Value $envContent.Content -Encoding UTF8
    }

    $installerPath = Join-Path $extractRoot "install_client.ps1"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Installer script not found in extracted bundle."
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File $installerPath -ResolvedPythonPath $pythonInfo.Path
    if ($LASTEXITCODE -ne 0) {
        throw "Client installation failed with exit code $LASTEXITCODE."
    }
} catch {
    throw "Bootstrap stage failed: $($_.Exception.Message)"
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
