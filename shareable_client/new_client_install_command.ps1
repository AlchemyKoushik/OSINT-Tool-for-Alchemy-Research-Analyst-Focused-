param(
    [Parameter(Mandatory = $true)][string]$BootstrapUrl,
    [Parameter(Mandatory = $true)][string]$BundleUrl,
    [string]$EnvUrl = "",
    [string]$EnvBearerToken = "",
    [string]$ExpectedSha256 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-ForSingleQuotedPowerShell {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

$commandParts = @(
    "powershell -NoProfile -ExecutionPolicy Bypass -Command",
    '"& {',
    '`$tmp = Join-Path `$env:TEMP (''alchemy-bootstrap-'' + [guid]::NewGuid().ToString(''N'') + ''.ps1'');',
    "Invoke-WebRequest -Uri $(Quote-ForSingleQuotedPowerShell $BootstrapUrl) -OutFile ``$tmp;",
    "& powershell -NoProfile -ExecutionPolicy Bypass -File ``$tmp -BundleUrl $(Quote-ForSingleQuotedPowerShell $BundleUrl)"
)

if ($EnvUrl) {
    $commandParts += "-EnvUrl $(Quote-ForSingleQuotedPowerShell $EnvUrl)"
}

if ($EnvBearerToken) {
    $commandParts += "-EnvBearerToken $(Quote-ForSingleQuotedPowerShell $EnvBearerToken)"
}

if ($ExpectedSha256) {
    $commandParts += "-ExpectedSha256 $(Quote-ForSingleQuotedPowerShell $ExpectedSha256)"
}

$commandParts += '}"'

$command = $commandParts -join " "

Write-Host ""
Write-Host "Client install command:"
Write-Host $command
