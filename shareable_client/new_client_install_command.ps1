param(
    [Parameter(Mandatory = $true)][string]$BootstrapUrl,
    [Parameter(Mandatory = $true)][string]$BundleUrl,
    [string]$EnvUrl = "",
    [string]$EnvBearerToken = "",
    [string]$ExpectedSha256 = "",
    [string]$InstallScriptUrl = "",
    [string]$OutputInstallScriptPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-ForSingleQuotedPowerShell {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function New-HostedInstallScriptContent {
    $template = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install.ps1') -Raw
    $content = $template.Replace('SET_BOOTSTRAP_URL', $BootstrapUrl)
    $content = $content.Replace('SET_BUNDLE_URL', $BundleUrl)
    $content = $content.Replace('SET_ENV_URL', $EnvUrl)
    $content = $content.Replace('SET_ENV_BEARER_TOKEN', $EnvBearerToken)
    $content = $content.Replace('SET_EXPECTED_SHA256', $ExpectedSha256)
    return $content
}

$installScriptContent = New-HostedInstallScriptContent

if ($OutputInstallScriptPath) {
    Set-Content -LiteralPath $OutputInstallScriptPath -Value $installScriptContent -Encoding ASCII
}

Write-Host ""
Write-Host "Hosted install.ps1 content:"
Write-Host $installScriptContent

Write-Host ""
Write-Host "Client install command:"
if ($InstallScriptUrl) {
    Write-Host ("irm " + (Quote-ForSingleQuotedPowerShell $InstallScriptUrl) + " | iex")
} else {
    Write-Host "Upload the generated install.ps1 to your release, then run:"
    Write-Host "irm '<GitHub Release URL>/install.ps1' | iex"
}
