Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$releaseRoot = Join-Path $scriptRoot "dist\release-ready"
$releaseBundleRoot = Join-Path $releaseRoot "alchemy-shareable-client-build"
$releaseBundleZip = "$releaseBundleRoot.zip"
$finalBundlePath = Join-Path $workspaceRoot "alchemy-shareable-client-build.zip"
$generatedInstallPath = Join-Path $releaseRoot "install.ps1"
$harnessPath = Join-Path $scriptRoot "tests\Invoke-InstallerHarness.ps1"
$bootstrapUrl = "https://github.com/AlchemyKoushik/OSINT-Tool-for-Alchemy-Research-Analyst-Focused-/releases/download/v1.0.0/bootstrap_install.ps1"
$bundleUrl = "https://github.com/AlchemyKoushik/OSINT-Tool-for-Alchemy-Research-Analyst-Focused-/releases/download/v1.0.0/alchemy-shareable-client-build.zip"
$envUrl = "https://alchemy-client-env.koushik-bhandary.workers.dev/"
$installScriptUrl = "https://github.com/AlchemyKoushik/OSINT-Tool-for-Alchemy-Research-Analyst-Focused-/releases/download/v1.0.0/install.ps1"
$checkResults = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "FAIL")][string]$Status,
        [string]$Detail = ""
    )

    $checkResults.Add([PSCustomObject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
    })

    $color = if ($Status -eq "PASS") { "Green" } else { "Red" }
    Write-Host ("[{0}] {1}" -f $Status, $Name) -ForegroundColor $color
    if ($Detail) {
        Write-Host ("       " + $Detail)
    }
}

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )

    try {
        & $Body
        Add-Check -Name $Name -Status "PASS"
    } catch {
        Add-Check -Name $Name -Status "FAIL" -Detail $_.Exception.Message
    }
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-ExistingEnvBearerToken {
    foreach ($candidatePath in @(
        (Join-Path $releaseRoot "install.ps1"),
        (Join-Path $scriptRoot "dist\install.ps1")
    )) {
        if (-not (Test-Path -LiteralPath $candidatePath)) {
            continue
        }

        $content = Get-Content -LiteralPath $candidatePath -Raw
        $match = [regex]::Match($content, "EnvBearerToken\s*=\s*'([^']+)'")
        if ($match.Success) {
            return $match.Groups[1].Value
        }
    }

    throw "Could not recover the existing EnvBearerToken from a generated install.ps1."
}

function Parse-PowerShellFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $Path), [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw ($errors | ForEach-Object Message | Select-Object -First 1)
    }
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$envBearerToken = Get-ExistingEnvBearerToken

Invoke-Check -Name "PowerShell parser validation" -Body {
    foreach ($path in (rg --files shareable_client -g '*.ps1')) {
        Parse-PowerShellFile -Path (Join-Path $repoRoot $path)
    }
}

Invoke-Check -Name "Python helper harness" -Body {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $harnessPath
    if ($LASTEXITCODE -ne 0) {
        throw "Installer harness failed with exit code $LASTEXITCODE."
    }
}

Invoke-Check -Name "Bundle build" -Body {
    if (Test-Path -LiteralPath $releaseBundleRoot) {
        Remove-Item -LiteralPath $releaseBundleRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $releaseBundleZip) {
        Remove-Item -LiteralPath $releaseBundleZip -Force
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "build_bundle.ps1") -OutputRoot $releaseBundleRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Bundle build failed."
    }

    Copy-Item -LiteralPath $releaseBundleZip -Destination $finalBundlePath -Force
}

$bundleHash = (Get-FileHash -LiteralPath $finalBundlePath -Algorithm SHA256).Hash.ToLowerInvariant()

Invoke-Check -Name "Generate release-ready install.ps1" -Body {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "new_client_install_command.ps1") `
        -BootstrapUrl $bootstrapUrl `
        -BundleUrl $bundleUrl `
        -EnvUrl $envUrl `
        -EnvBearerToken $envBearerToken `
        -ExpectedSha256 $bundleHash `
        -InstallScriptUrl $installScriptUrl `
        -OutputInstallScriptPath $generatedInstallPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Release-ready install generation failed."
    }
}

Invoke-Check -Name "Generated install.ps1 parse validation" -Body {
    Parse-PowerShellFile -Path $generatedInstallPath
}

Invoke-Check -Name "Bundle filename is exact" -Body {
    Assert-True ([System.IO.Path]::GetFileName($finalBundlePath) -eq "alchemy-shareable-client-build.zip") "Final bundle filename is not alchemy-shareable-client-build.zip."
}

Invoke-Check -Name "Generated install.ps1 has exact SHA256" -Body {
    $content = Get-Content -LiteralPath $generatedInstallPath -Raw
    Assert-True ($content -match [regex]::Escape($bundleHash)) "Generated install.ps1 did not contain the bundle SHA256."
}

Invoke-Check -Name "Bootstrap URL is correct" -Body {
    $content = Get-Content -LiteralPath $generatedInstallPath -Raw
    Assert-True ($content -match [regex]::Escape($bootstrapUrl)) "Generated install.ps1 did not contain the expected bootstrap URL."
}

Invoke-Check -Name "Bundle URL is correct" -Body {
    $content = Get-Content -LiteralPath $generatedInstallPath -Raw
    Assert-True ($content -match [regex]::Escape($bundleUrl)) "Generated install.ps1 did not contain the expected bundle URL."
}

Invoke-Check -Name "Hosted install is IEX-ready" -Body {
    $content = Get-Content -LiteralPath $generatedInstallPath -Raw
    Assert-True ($content -match "Invoke-ReleaseBootstrap") "Hosted install.ps1 is missing bootstrap invocation logic."
    Assert-True ($content -notmatch "-Verb\s+RunAs") "Hosted install.ps1 should not require elevation."
}

Invoke-Check -Name "Bootstrap is self-contained before extraction" -Body {
    $content = Get-Content -LiteralPath (Join-Path $scriptRoot "bootstrap_install.ps1") -Raw
    Assert-True ($content -notmatch "installer_common\.ps1") "bootstrap_install.ps1 must not depend on installer_common.ps1 before extraction."
}

Invoke-Check -Name "Bundle contents inspection" -Body {
    $tempInspectRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("alchemy-bundle-inspect-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempInspectRoot | Out-Null
    try {
        Expand-Archive -LiteralPath $finalBundlePath -DestinationPath $tempInspectRoot -Force
        $files = Get-ChildItem -LiteralPath $tempInspectRoot -Recurse -File
        Assert-True (-not ($files | Where-Object Name -eq ".env")) "Bundle contains a .env file."
        Assert-True ($files.FullName -contains (Join-Path $tempInspectRoot "installer_common.ps1")) "installer_common.ps1 is missing from the bundle."
        Assert-True ($files.FullName -contains (Join-Path $tempInspectRoot "bootstrap_install.ps1")) "bootstrap_install.ps1 is missing from the bundle."
        Assert-True (-not ($files | Where-Object FullName -match "\\dist\\|\\build\\")) "Bundle contains recursive dist/build leakage."
        Assert-True (-not ($files | Where-Object Name -match "\.tmp$|\.temp$")) "Bundle contains temporary files."
        $suspiciousFiles = $files | Where-Object { $_.FullName -match "token|secret" -and $_.Extension -ne ".ps1" }
        Assert-True (-not $suspiciousFiles) "Bundle contains suspicious token/secret files."
    } finally {
        Remove-Item -LiteralPath $tempInspectRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Invoke-Check -Name "No pre-bundle missing dependency" -Body {
    $content = Get-Content -LiteralPath (Join-Path $scriptRoot "install.ps1") -Raw
    Assert-True ($content -match "bootstrap_install\.ps1") "Hosted installer does not download bootstrap_install.ps1."
}

$summary = [PSCustomObject]@{
    Checks               = $checkResults
    BundlePath           = $finalBundlePath
    GeneratedInstallPath = $generatedInstallPath
    BundleSha256         = $bundleHash
}

$summaryPath = Join-Path $releaseRoot "preflight-summary.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Preflight summary: $summaryPath"

if (@($checkResults | Where-Object Status -eq "FAIL").Count -gt 0) {
    exit 1
}
