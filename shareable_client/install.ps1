if (-not (Get-Variable -Name BootstrapUrl -ErrorAction SilentlyContinue)) {
    $BootstrapUrl = 'SET_BOOTSTRAP_URL'
}
if (-not (Get-Variable -Name BundleUrl -ErrorAction SilentlyContinue)) {
    $BundleUrl = 'SET_BUNDLE_URL'
}
if (-not (Get-Variable -Name EnvUrl -ErrorAction SilentlyContinue)) {
    $EnvUrl = 'SET_ENV_URL'
}
if (-not (Get-Variable -Name EnvBearerToken -ErrorAction SilentlyContinue)) {
    $EnvBearerToken = 'SET_ENV_BEARER_TOKEN'
}
if (-not (Get-Variable -Name ExpectedSha256 -ErrorAction SilentlyContinue)) {
    $ExpectedSha256 = 'SET_EXPECTED_SHA256'
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-ForSingleQuotedPowerShell {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-TempInstallRoot {
    $root = Join-Path $env:TEMP ("alchemy-release-install-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    return $root
}

function Start-CleanupProcess {
    param([Parameter(Mandatory = $true)][string]$Path)

    $cleanupCommand = "Start-Sleep -Seconds 3; Remove-Item -LiteralPath {0} -Recurse -Force -ErrorAction SilentlyContinue" -f (Quote-ForSingleQuotedPowerShell $Path)
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cleanupCommand) -WindowStyle Hidden | Out-Null
}

function Invoke-ReleaseBootstrap {
    if ($BootstrapUrl -like "SET_*" -or $BundleUrl -like "SET_*") {
        throw "This hosted install.ps1 is not configured yet. Populate BootstrapUrl and BundleUrl before uploading it."
    }

    if ($EnvUrl -like "SET_*") {
        $EnvUrl = ""
    }
    if ($EnvBearerToken -like "SET_*") {
        $EnvBearerToken = ""
    }
    if ($ExpectedSha256 -like "SET_*") {
        $ExpectedSha256 = ""
    }

    $tempRoot = New-TempInstallRoot
    $bootstrapPath = Join-Path $tempRoot "bootstrap_install.ps1"

    try {
        Write-Host ""
        Write-Host "Downloading installer bootstrap..."
        Invoke-WebRequest -Uri $BootstrapUrl -OutFile $bootstrapPath

        if (-not (Test-Path -LiteralPath $bootstrapPath)) {
            throw "Bootstrap download did not produce a local script."
        }

        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $bootstrapPath,
            "-BundleUrl", $BundleUrl
        )

        if ($EnvUrl) {
            $arguments += @("-EnvUrl", $EnvUrl)
        }

        if ($EnvBearerToken) {
            $arguments += @("-EnvBearerToken", $EnvBearerToken)
        }

        if ($ExpectedSha256) {
            $arguments += @("-ExpectedSha256", $ExpectedSha256)
        }

        & powershell.exe @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Bootstrap installer exited with code $LASTEXITCODE."
        }
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Start-ElevatedHostedInstaller {
    $tempRoot = New-TempInstallRoot
    $elevatedScriptPath = Join-Path $tempRoot "install.ps1"
    $scriptSource = $MyInvocation.MyCommand.ScriptBlock.ToString()

    if (-not $scriptSource) {
        throw "Unable to capture the hosted installer source for elevation."
    }

    $scriptContent = @"
`$BootstrapUrl = $(Quote-ForSingleQuotedPowerShell $BootstrapUrl)
`$BundleUrl = $(Quote-ForSingleQuotedPowerShell $BundleUrl)
`$EnvUrl = $(Quote-ForSingleQuotedPowerShell $EnvUrl)
`$EnvBearerToken = $(Quote-ForSingleQuotedPowerShell $EnvBearerToken)
`$ExpectedSha256 = $(Quote-ForSingleQuotedPowerShell $ExpectedSha256)

$scriptSource
"@

    Set-Content -LiteralPath $elevatedScriptPath -Value $scriptContent -Encoding ASCII

    Write-Host ""
    Write-Host "Requesting administrator permission..."

    try {
        $null = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $elevatedScriptPath
        ) -PassThru
    } catch {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw "Administrator permission was not granted. Installation cancelled."
    }

    Start-CleanupProcess -Path $tempRoot
}

if (-not (Test-IsAdministrator)) {
    Start-ElevatedHostedInstaller
    return
}

Invoke-ReleaseBootstrap
