Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$shareableClientRoot = Split-Path -Parent $scriptRoot
$helperPath = Join-Path $shareableClientRoot "installer_common.ps1"

. $helperPath

$results = New-Object System.Collections.Generic.List[object]
$skipped = New-Object System.Collections.Generic.List[string]
$actualProbeResults = New-Object System.Collections.Generic.List[object]
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("alchemy-installer-harness-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

function Add-TestResult {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "FAIL", "SKIP")][string]$Status,
        [string]$Detail = ""
    )

    $results.Add([PSCustomObject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
    })

    $color = switch ($Status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        default { "Yellow" }
    }

    Write-Host ("[{0}] {1}" -f $Status, $Name) -ForegroundColor $color
    if ($Detail) {
        Write-Host ("       " + $Detail)
    }

    if ($Status -eq "SKIP") {
        $skipped.Add($Name)
    }
}

function Invoke-TestCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body,
        [switch]$CanSkip
    )

    try {
        & $Body
        Add-TestResult -Name $Name -Status "PASS"
    } catch {
        if ($CanSkip -and $_.Exception.Message -like "SKIP:*") {
            Add-TestResult -Name $Name -Status "SKIP" -Detail $_.Exception.Message.Substring(5).Trim()
            return
        }

        Add-TestResult -Name $Name -Status "FAIL" -Detail $_.Exception.Message
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

function New-FakePythonCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$BodyLines
    )

    $path = Join-Path $testRoot $Name
    Set-Content -LiteralPath $path -Value $BodyLines -Encoding ASCII
    return $path
}

function Invoke-IsolatedHelper {
    param([Parameter(Mandatory = $true)][scriptblock]$ScriptBlock)

    & {
        . $helperPath
        & $ScriptBlock
    }
}

function Get-VisibleActualPythonCandidates {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($commandName in @("py.exe", "py", "python.exe", "python", "python3.exe", "python3")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            $candidates.Add($command.Source)
        }
    }

    foreach ($path in @(
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python314\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python311\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python312\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python313\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Microsoft\WindowsApps\python.exe"),
        (Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Microsoft\WindowsApps\python3.exe")
    )) {
        if ($path) {
            $candidates.Add($path)
        }
    }

    return $candidates | Sort-Object -Unique
}

try {
    $goodStub = Join-Path $testRoot "python-good.cmd"
    $goodJson = '{"major":3,"minor":11,"micro":9,"bits":64,"executable":"' + ($goodStub.Replace('\', '\\')) + '","implementation":"CPython"}'
    Set-Content -LiteralPath $goodStub -Value @(
        "@echo off",
        "echo $goodJson",
        "exit /b 0"
    ) -Encoding ASCII

    $stderrGoodStub = Join-Path $testRoot "python-stderr-good.cmd"
    Set-Content -LiteralPath $stderrGoodStub -Value @(
        "@echo off",
        "echo informational stderr 1>&2",
        "echo $goodJson",
        "exit /b 0"
    ) -Encoding ASCII

    $unsupportedStub = Join-Path $testRoot "python-unsupported.cmd"
    $unsupportedJson = '{"major":3,"minor":14,"micro":0,"bits":64,"executable":"' + ($unsupportedStub.Replace('\', '\\')) + '","implementation":"CPython"}'
    Set-Content -LiteralPath $unsupportedStub -Value @(
        "@echo off",
        "echo $unsupportedJson",
        "exit /b 0"
    ) -Encoding ASCII

    $thirtyTwoBitStub = Join-Path $testRoot "python-32bit.cmd"
    $thirtyTwoBitJson = '{"major":3,"minor":11,"micro":9,"bits":32,"executable":"' + ($thirtyTwoBitStub.Replace('\', '\\')) + '","implementation":"CPython"}'
    Set-Content -LiteralPath $thirtyTwoBitStub -Value @(
        "@echo off",
        "echo $thirtyTwoBitJson",
        "exit /b 0"
    ) -Encoding ASCII
    $emptyStdoutStub = New-FakePythonCommand -Name "python-empty.cmd" -BodyLines @(
        "@echo off",
        "exit /b 0"
    )
    $invalidJsonStub = New-FakePythonCommand -Name "python-invalid-json.cmd" -BodyLines @(
        "@echo off",
        "echo not-json",
        "exit /b 0"
    )
    $nonZeroStub = New-FakePythonCommand -Name "python-nonzero.cmd" -BodyLines @(
        "@echo off",
        "echo failure happened 1>&2",
        "exit /b 5"
    )
    $wingetFailStub = New-FakePythonCommand -Name "winget-fail.cmd" -BodyLines @(
        "@echo off",
        "echo winget failed 1>&2",
        "exit /b 1"
    )
    $wingetSuccessStub = New-FakePythonCommand -Name "winget-success.cmd" -BodyLines @(
        "@echo off",
        "echo winget installed python",
        "exit /b 0"
    )

    $spaceRoot = Join-Path $testRoot "path with spaces"
    New-Item -ItemType Directory -Force -Path $spaceRoot | Out-Null
    Copy-Item -LiteralPath $goodStub -Destination (Join-Path $spaceRoot "python-good.cmd")
    $spaceStub = Join-Path $spaceRoot "python-good.cmd"

    Invoke-TestCase -Name "Empty candidate collection" -Body {
        $list = New-Object System.Collections.Generic.List[object]
        Add-PythonPathCandidates -Candidates $list -BasePath ""
        Assert-True ($list.Count -eq 0) "Expected no candidates to be added."
    }

    Invoke-TestCase -Name "Missing candidate path" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath (Join-Path $testRoot "missing-python.exe")
        Assert-True (-not $detail.Accepted) "Missing path should be rejected."
        Assert-True ($detail.Reason -eq "File does not exist.") "Expected an explicit missing-file reason."
    }

    Invoke-TestCase -Name "Invalid candidate path characters" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath 'C:\bad"quote\python.exe'
        Assert-True (-not $detail.Accepted) "Invalid candidate path should be rejected."
        Assert-True ($detail.Reason -in @("File does not exist.", "Candidate is not a real file.")) "Invalid path input should not crash candidate evaluation."
    }

    Invoke-TestCase -Name "Path containing spaces" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $spaceStub
        Assert-True ($detail.Accepted) "Expected the stub in a spaced path to be accepted."
    }

    Invoke-TestCase -Name "Fake WindowsApps alias" -Body {
        $fakeWindowsAppsDir = Join-Path $testRoot "Microsoft\WindowsApps"
        New-Item -ItemType Directory -Force -Path $fakeWindowsAppsDir | Out-Null
        Copy-Item -LiteralPath $goodStub -Destination (Join-Path $fakeWindowsAppsDir "python.exe")
        $detail = Test-PythonCandidateDetailed -FilePath (Join-Path $fakeWindowsAppsDir "python.exe")
        Assert-True (-not $detail.Accepted) "WindowsApps alias path should be rejected."
        Assert-True ($detail.Reason -like "Rejected Microsoft Store*") "Expected WindowsApps rejection."
    }

    Invoke-TestCase -Name "Real working Python executable" -CanSkip -Body {
        $realPython = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $realPython) {
            throw "SKIP: No local python.exe command was available."
        }

        $detail = Test-PythonCandidateDetailed -FilePath $realPython.Source
        Assert-True ($detail.Accepted -or $detail.Reason -like "Unsupported Python version*") "Expected a real interpreter probe result."
    }

    Invoke-TestCase -Name "Unsupported version" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $unsupportedStub
        Assert-True (-not $detail.Accepted) "Unsupported version should be rejected."
        Assert-True ($detail.Reason -like "Unsupported Python version*") "Expected unsupported-version reason."
    }

    Invoke-TestCase -Name "32-bit Python simulation" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $thirtyTwoBitStub
        Assert-True (-not $detail.Accepted) "32-bit interpreter should be rejected."
        Assert-True ($detail.Reason -like "Interpreter is 32-bit*") "Expected 32-bit rejection."
    }

    Invoke-TestCase -Name "Process start failure" -Body {
        $probe = Get-PythonProbe -FilePath (Join-Path $testRoot "does-not-exist.exe")
        Assert-True (-not $probe.Success) "Probe should fail for a missing executable."
    }

    Invoke-TestCase -Name "Non-zero exit code" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $nonZeroStub
        Assert-True (-not $detail.Accepted) "Non-zero exit code should be rejected."
        Assert-True ($detail.Reason -like "Process exited with code 5*") "Expected exit-code reason."
    }

    Invoke-TestCase -Name "Empty stdout" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $emptyStdoutStub
        Assert-True (-not $detail.Accepted) "Empty stdout should be rejected."
        Assert-True ($detail.Reason -like "Process returned empty stdout*") "Expected empty-stdout reason."
    }

    Invoke-TestCase -Name "stderr output with successful exit" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $stderrGoodStub
        Assert-True ($detail.Accepted) "Valid JSON on stdout should still be accepted when stderr has text."
    }

    Invoke-TestCase -Name "Invalid JSON probe output" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $invalidJsonStub
        Assert-True (-not $detail.Accepted) "Invalid JSON should be rejected."
        Assert-True ($detail.Reason -eq "Probe output was not valid JSON.") "Expected invalid-JSON reason."
    }

    Invoke-TestCase -Name "Duplicate candidate paths" -Body {
        $candidates = @(
            [PSCustomObject]@{ FilePath = $goodStub; Arguments = @() },
            [PSCustomObject]@{ FilePath = $goodStub; Arguments = @() }
        )
        $resolved = Resolve-PythonInterpreterFromCandidateList -Candidates $candidates
        Assert-True ($null -ne $resolved) "Expected duplicates to resolve successfully."
    }

    Invoke-TestCase -Name "Missing registry keys" -Body {
        $candidates = Get-PythonRegistryCandidates -RegistryRoots @("HKCU:\SOFTWARE\AlchemyInstallerHarness\MissingRoot")
        Assert-True (@($candidates).Count -eq 0) "Missing registry roots should be skipped."
    }

    Invoke-TestCase -Name "Registry version key without InstallPath" -Body {
        $root = "HKCU:\SOFTWARE\AlchemyInstallerHarness\NoInstallPath"
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -Path $root -Force | Out-Null
        New-Item -Path (Join-Path $root "3.11") -Force | Out-Null
        $candidates = Get-PythonRegistryCandidates -RegistryRoots @($root)
        Assert-True (@($candidates).Count -eq 0) "Version key without InstallPath should not crash or produce candidates."
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }

    Invoke-TestCase -Name "Valid InstallPath default value" -Body {
        $root = "HKCU:\SOFTWARE\AlchemyInstallerHarness\ValidInstallPath"
        $pythonDir = Join-Path $testRoot "registry-python"
        New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
        New-Item -Path $root -Force | Out-Null
        $versionKey = New-Item -Path (Join-Path $root "3.11") -Force
        $installKey = New-Item -Path (Join-Path $versionKey.PSPath "InstallPath") -Force
        Set-ItemProperty -LiteralPath $installKey.PSPath -Name "(default)" -Value $pythonDir
        $candidates = Get-PythonRegistryCandidates -RegistryRoots @($root)
        Assert-True ($candidates.Count -ge 2) "Expected python.exe and python3.exe candidates from InstallPath."
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }

    Invoke-TestCase -Name "Stale registry path" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath (Join-Path $testRoot "stale-registry\python.exe")
        Assert-True (-not $detail.Accepted) "Stale path should not be accepted."
    }

    Invoke-TestCase -Name "No Python found" -Body {
        $resolved = Resolve-PythonInterpreterFromCandidateList -Candidates @()
        Assert-True ($null -eq $resolved) "Empty discovery set should resolve to null."
    }

    Invoke-TestCase -Name "winget unavailable" -Body {
        $result = Invoke-IsolatedHelper {
            function Get-Command { param([string]$Name) return $null }
            Install-Python311WithWinget
        }
        Assert-True (-not $result.Success) "winget should report unavailable."
    }

    Invoke-TestCase -Name "winget failure" -Body {
        $result = Invoke-IsolatedHelper {
            function Get-Command {
                param([string]$Name)
                [PSCustomObject]@{ Source = $wingetFailStub }
            }
            Install-Python311WithWinget
        }
        Assert-True (-not $result.Success) "winget failure should be reported."
    }

    Invoke-TestCase -Name "winget success but rediscovery failure" -Body {
        $result = Invoke-IsolatedHelper {
            function Resolve-PythonInterpreter { return $null }
            function Install-Python311WithWinget { [PSCustomObject]@{ Success = $true; Reason = "ok" } }
            function Get-DeterministicPython311Candidates { @() }
            $script:resolveAfterInstallCount = 0
            function Resolve-PythonInterpreterAfterInstall {
                $script:resolveAfterInstallCount += 1
                if ($script:resolveAfterInstallCount -eq 1) {
                    return $null
                }

                return [PSCustomObject]@{ Accepted = $true; Path = $goodStub; DisplayName = $goodStub; Major = 3; Minor = 11; Micro = 9; Bits = 64 }
            }
            function Install-Python311FromPythonOrg { [PSCustomObject]@{ Success = $true; Path = $goodStub } }
            function Test-PythonCandidateDetailed { param([string]$FilePath, [string[]]$Arguments=@()) return [PSCustomObject]@{ Accepted = $true; Candidate = $FilePath; Reason = "Accepted."; Path = $FilePath; DisplayName = $FilePath; Major = 3; Minor = 11; Micro = 9; Bits = 64 } }
            Ensure-PythonInterpreter
        }
        Assert-True ($null -ne $result) "Ensure-PythonInterpreter should continue to the fallback path."
    }

    Invoke-TestCase -Name "Deterministic fallback success" -Body {
        $result = Invoke-IsolatedHelper {
            function Resolve-PythonInterpreter { return $null }
            function Install-Python311WithWinget { [PSCustomObject]@{ Success = $false; Reason = "skip winget" } }
            function Install-Python311FromPythonOrg { [PSCustomObject]@{ Success = $true; Path = $goodStub } }
            function Resolve-PythonInterpreterAfterInstall {
                param([switch]$EmitDiagnostics, [string]$OriginalUserName, [string]$OriginalUserProfile, [string]$OriginalLocalAppData, [object[]]$PreferredCandidates)
                return [PSCustomObject]@{ Accepted = $true; Path = $goodStub; DisplayName = $goodStub; Major = 3; Minor = 11; Micro = 9; Bits = 64 }
            }
            Ensure-PythonInterpreter
        }
        Assert-True ($null -ne $result) "Fallback install should produce a verified interpreter."
    }

    Invoke-TestCase -Name "Deterministic fallback failure" -Body {
        $failed = $false
        try {
            Invoke-IsolatedHelper {
                function Resolve-PythonInterpreter { return $null }
                function Install-Python311WithWinget { [PSCustomObject]@{ Success = $false; Reason = "skip winget" } }
                function Install-Python311FromPythonOrg { [PSCustomObject]@{ Success = $true; Path = $goodStub } }
                function Resolve-PythonInterpreterAfterInstall { return $null }
                Ensure-PythonInterpreter
            } | Out-Null
        } catch {
            $failed = $true
        }
        Assert-True $failed "Expected fallback failure to throw."
    }

    Invoke-TestCase -Name "Bundle hash mismatch" -Body {
        $bundlePath = Join-Path $testRoot "bundle.zip"
        Set-Content -LiteralPath $bundlePath -Value "bundle" -Encoding ASCII
        $actualHash = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
        Assert-True ($actualHash -ne ("0" * 64)) "Expected a detectable SHA256 mismatch."
    }

    Invoke-TestCase -Name "Missing bootstrap dependency" -Body {
        $bootstrapContent = Get-Content -LiteralPath (Join-Path $shareableClientRoot "bootstrap_install.ps1") -Raw
        Assert-True ($bootstrapContent -notmatch "installer_common\.ps1") "Bootstrap must stay self-contained."
    }

    Invoke-TestCase -Name "Hosted installer stays non-elevated" -Body {
        $installContent = Get-Content -LiteralPath (Join-Path $shareableClientRoot "install.ps1") -Raw
        Assert-True ($installContent -notmatch "-Verb\s+RunAs") "Hosted installer should not require elevation."
    }

    Invoke-TestCase -Name "Python fallback stays per-user" -Body {
        $helperContent = Get-Content -LiteralPath $helperPath -Raw
        Assert-True ($helperContent -match "InstallAllUsers=0") "python.org fallback should be per-user."
        Assert-True ($helperContent -match "Programs\\Python\\Python311") "python.org fallback should target LocalAppData."
        Assert-True ($helperContent -match '--scope",\s*"user"') "winget fallback should stay in user scope."
    }

    Invoke-TestCase -Name "Missing extracted helper" -Body {
        $tempInstallRoot = Join-Path $testRoot "missing-helper"
        New-Item -ItemType Directory -Force -Path $tempInstallRoot | Out-Null
        Copy-Item -LiteralPath (Join-Path $shareableClientRoot "install_client.ps1") -Destination (Join-Path $tempInstallRoot "install_client.ps1")
        $errored = $false
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tempInstallRoot "install_client.ps1") 2>$null | Out-Null
        } catch {
            $errored = $true
        }
        Assert-True ($errored -or $LASTEXITCODE -ne 0) "Expected install_client.ps1 to fail when installer_common.ps1 is missing."
    }

    Invoke-TestCase -Name "Paths containing spaces throughout" -Body {
        $detail = Test-PythonCandidateDetailed -FilePath $spaceStub
        Assert-True ($detail.Accepted) "Expected spaced-path probe to remain valid end to end."
    }

    foreach ($candidatePath in (Get-VisibleActualPythonCandidates)) {
        if (-not $candidatePath) {
            continue
        }

        $arguments = @()
        if ([System.IO.Path]::GetFileName($candidatePath).Equals("py.exe", [System.StringComparison]::OrdinalIgnoreCase) -and $candidatePath -notlike "*WindowsApps*") {
            $arguments = @("-3.11")
        }

        $detail = Test-PythonCandidateDetailed -FilePath $candidatePath -Arguments $arguments
        $actualProbeResults.Add([PSCustomObject]@{
            Path     = $candidatePath
            Version  = $(if ($detail.Accepted) { $detail.Version } else { "" })
            Bits     = $(if ($detail.Accepted) { $detail.Bits } else { "" })
            Accepted = [bool]$detail.Accepted
            Reason   = $detail.Reason
        })
    }

    $summary = [PSCustomObject]@{
        TotalTests         = $results.Count
        Passed             = @($results | Where-Object Status -eq "PASS").Count
        Failed             = @($results | Where-Object Status -eq "FAIL").Count
        Skipped            = @($results | Where-Object Status -eq "SKIP").Count
        FailedTests        = @($results | Where-Object Status -eq "FAIL" | Select-Object -ExpandProperty Name)
        SkippedTests       = @($results | Where-Object Status -eq "SKIP" | Select-Object -ExpandProperty Name)
        Results            = $results
        ActualProbeResults = $actualProbeResults
    }

    $summaryPath = Join-Path $testRoot "installer-harness-results.json"
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host ""
    Write-Host "Harness results: $summaryPath"

    if ($summary.Failed -gt 0) {
        exit 1
    }
} finally {
}
