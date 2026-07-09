Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:PythonProbeCode = @'
import json
import struct
import sys

print(json.dumps({
    "major": sys.version_info[0],
    "minor": sys.version_info[1],
    "micro": sys.version_info[2],
    "bits": struct.calcsize("P") * 8,
    "executable": sys.executable,
}))
'@

$script:Python311FallbackVersion = "3.11.9"
$script:Python311FallbackUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

function Write-InstallerStage {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host ""
    Write-Host $Message
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-SupportedPythonVersion {
    param(
        [Parameter(Mandatory = $true)][int]$Major,
        [Parameter(Mandatory = $true)][int]$Minor
    )

    return $Major -eq 3 -and $Minor -ge 11 -and $Minor -le 13
}

function Get-PythonProbe {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    try {
        $rawOutput = & $FilePath @($Arguments + @("-c", $script:PythonProbeCode)) 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }

        $text = ($rawOutput | Out-String).Trim()
        if (-not $text) {
            return $null
        }

        $probe = $text | ConvertFrom-Json
        $resolvedPath = [string]$probe.executable
        if (-not $resolvedPath) {
            return $null
        }

        return [PSCustomObject]@{
            ExecutablePath = $resolvedPath
            Major          = [int]$probe.major
            Minor          = [int]$probe.minor
            Micro          = [int]$probe.micro
            Bits           = [int]$probe.bits
        }
    } catch {
        return $null
    }
}

function Test-PythonCandidateDetailed {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $candidateLabel = if ($Arguments.Count -gt 0) {
        "$FilePath $($Arguments -join ' ')"
    } else {
        $FilePath
    }

    $probe = Get-PythonProbe -FilePath $FilePath -Arguments $Arguments
    if (-not $probe) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Could not execute a real Python interpreter."
        }
    }

    if (-not (Test-SupportedPythonVersion -Major $probe.Major -Minor $probe.Minor)) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Unsupported Python version $($probe.Major).$($probe.Minor).$($probe.Micro)."
        }
    }

    if ($probe.Bits -ne 64) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Interpreter is $($probe.Bits)-bit."
        }
    }

    $resolvedPath = [System.IO.Path]::GetFullPath($probe.ExecutablePath)
    if (-not (Test-Path -LiteralPath $resolvedPath)) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Resolved executable path does not exist: $resolvedPath"
        }
    }

    return [PSCustomObject]@{
        Accepted    = $true
        Candidate   = $candidateLabel
        Reason      = "Accepted."
        Path        = $resolvedPath
        Version     = "{0}.{1}.{2}" -f $probe.Major, $probe.Minor, $probe.Micro
        Major       = $probe.Major
        Minor       = $probe.Minor
        Micro       = $probe.Micro
        Bits        = $probe.Bits
        DisplayName = "$resolvedPath ($($probe.Major).$($probe.Minor).$($probe.Micro), $($probe.Bits)-bit)"
    }
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $detail = Test-PythonCandidateDetailed -FilePath $FilePath -Arguments $Arguments
    if ($detail.Accepted) {
        return $detail
    }

    return $null
}

function Add-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][System.Collections.Generic.List[object]]$Candidates,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    if ([string]::IsNullOrWhiteSpace($FilePath)) {
        return
    }

    $Candidates.Add([PSCustomObject]@{
        FilePath  = $FilePath
        Arguments = $Arguments
    })
}

function Add-PythonPathCandidates {
    param(
        [Parameter(Mandatory = $true)][System.Collections.Generic.List[object]]$Candidates,
        [Parameter(Mandatory = $true)][string]$BasePath
    )

    if ([string]::IsNullOrWhiteSpace($BasePath)) {
        return
    }

    Add-PythonCandidate -Candidates $Candidates -FilePath (Join-Path $BasePath "python.exe")
    Add-PythonCandidate -Candidates $Candidates -FilePath (Join-Path $BasePath "python3.exe")
}

function Get-PythonCommandCandidates {
    return @(
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3") },
        [PSCustomObject]@{ FilePath = "python"; Arguments = @() },
        [PSCustomObject]@{ FilePath = "python.exe"; Arguments = @() },
        [PSCustomObject]@{ FilePath = "python3"; Arguments = @() },
        [PSCustomObject]@{ FilePath = "python3.exe"; Arguments = @() }
    )
}

function Get-PythonLauncherPaths {
    $paths = @()

    try {
        $launcherOutput = & py -0p 2>$null
        if ($LASTEXITCODE -eq 0) {
            foreach ($line in $launcherOutput) {
                if ($line -match '([A-Za-z]:\\[^"]*python\.exe)') {
                    $paths += $matches[1]
                }
            }
        }
    } catch {
    }

    return $paths
}

function Get-RegistryStringValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    try {
        $value = Get-ItemPropertyValue -LiteralPath $Path -Name $Name -ErrorAction Stop
        if ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    } catch {
    }

    return $null
}

function Get-RegistryDefaultStringValue {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if ($item -is [Microsoft.Win32.RegistryKey]) {
            $value = $item.GetValue("", $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) {
                return $value
            }
        }
    } catch {
    }

    return $null
}

function Get-KnownPythonInstallPaths {
    $candidates = New-Object System.Collections.Generic.List[object]
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $directCandidateRoots = @(
        (Join-Path $env:ProgramFiles "Python311"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python313"),
        (Join-Path $localAppData "Programs\Python\Python311"),
        (Join-Path $localAppData "Programs\Python\Python312"),
        (Join-Path $localAppData "Programs\Python\Python313")
    )

    foreach ($pathRoot in $directCandidateRoots) {
        if ($pathRoot) {
            Add-PythonPathCandidates -Candidates $candidates -BasePath $pathRoot
        }
    }

    $globRoots = @(
        (Join-Path $env:ProgramFiles "Python*"),
        (Join-Path $localAppData "Programs\Python\Python*")
    )

    foreach ($pattern in $globRoots) {
        if (-not $pattern) {
            continue
        }

        foreach ($match in (Get-ChildItem -Path $pattern -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)) {
            Add-PythonPathCandidates -Candidates $candidates -BasePath $match
        }
    }

    $registryRoots = @(
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore",
        "HKCU:\SOFTWARE\Python\PythonCore"
    )

    foreach ($registryRoot in $registryRoots) {
        foreach ($key in (Get-ChildItem -Path $registryRoot -ErrorAction SilentlyContinue)) {
            $versionInstallPath = Get-RegistryStringValue -Path $key.PSPath -Name "InstallPath"
            if ($versionInstallPath) {
                Add-PythonPathCandidates -Candidates $candidates -BasePath $versionInstallPath
            }

            $installPathSubkey = Join-Path $key.PSPath "InstallPath"
            if (Test-Path -LiteralPath $installPathSubkey) {
                $subkeyInstallPath = Get-RegistryDefaultStringValue -Path $installPathSubkey
                if ($subkeyInstallPath) {
                    Add-PythonPathCandidates -Candidates $candidates -BasePath $subkeyInstallPath
                }

                $executablePath = Get-RegistryStringValue -Path $installPathSubkey -Name "ExecutablePath"
                if ($executablePath) {
                    Add-PythonCandidate -Candidates $candidates -FilePath $executablePath
                }
            }
        }
    }

    foreach ($path in (Get-PythonLauncherPaths)) {
        Add-PythonCandidate -Candidates $candidates -FilePath $path
    }

    return $candidates
}

function Write-PythonDiscoveryDiagnostics {
    param(
        [Parameter(Mandatory = $true)][string]$Context,
        [Parameter(Mandatory = $true)][object[]]$Attempts
    )

    Write-Host ""
    Write-Host "$Context diagnostics:"
    Write-Host "  User: $env:USERNAME"
    Write-Host "  LocalAppData: $([Environment]::GetFolderPath('LocalApplicationData'))"

    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $pyCommand) {
        $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    }

    if ($pyCommand) {
        Write-Host "  py launcher: $($pyCommand.Source)"
    } else {
        Write-Host "  py launcher: not found"
    }

    foreach ($attempt in $Attempts) {
        $status = if ($attempt.Accepted) { "accepted" } else { "rejected" }
        Write-Host "  [$status] $($attempt.Candidate)"
        Write-Host "           $($attempt.Reason)"
    }
}

function Select-BestPythonCandidate {
    param([Parameter(Mandatory = $true)][object[]]$Candidates)

    return $Candidates |
        Sort-Object @{ Expression = { if ($_.Minor -eq 11) { 0 } else { $_.Minor } } }, @{ Expression = { $_.Path } } |
        Select-Object -First 1
}

function Resolve-PythonInterpreter {
    param(
        [switch]$EmitDiagnostics,
        [string]$DiagnosticContext = "Python discovery"
    )

    $verifiedCandidates = New-Object System.Collections.Generic.List[object]
    $attempts = New-Object System.Collections.Generic.List[object]
    $allCandidates = New-Object System.Collections.Generic.List[object]

    foreach ($candidate in (Get-PythonCommandCandidates)) {
        $allCandidates.Add($candidate)
    }

    foreach ($candidate in (Get-KnownPythonInstallPaths)) {
        $allCandidates.Add($candidate)
    }

    $seen = @{}
    foreach ($candidate in $allCandidates) {
        $arguments = @($candidate.Arguments)
        $key = "$($candidate.FilePath)|$($arguments -join ' ')"
        if ($seen.ContainsKey($key)) {
            continue
        }
        $seen[$key] = $true

        $detail = Test-PythonCandidateDetailed -FilePath $candidate.FilePath -Arguments $arguments
        $attempts.Add($detail)
        if ($detail.Accepted) {
            $verifiedCandidates.Add($detail)
        }
    }

    if ($EmitDiagnostics) {
        Write-PythonDiscoveryDiagnostics -Context $DiagnosticContext -Attempts $attempts
    }

    $uniqueCandidates = $verifiedCandidates |
        Group-Object Path |
        ForEach-Object { $_.Group | Select-Object -First 1 }

    if (-not $uniqueCandidates) {
        return $null
    }

    return Select-BestPythonCandidate -Candidates $uniqueCandidates
}

function Resolve-PythonInterpreterAfterInstall {
    param([switch]$EmitDiagnostics)

    return Resolve-PythonInterpreter -EmitDiagnostics:$EmitDiagnostics -DiagnosticContext "Post-install Python discovery"
}

function Install-Python311WithWinget {
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wingetCommand) {
        $wingetCommand = Get-Command winget -ErrorAction SilentlyContinue
    }

    if (-not $wingetCommand) {
        return $false
    }

    Write-InstallerStage "Python 3.11 not found. Installing with winget..."

    $arguments = @(
        "install",
        "-e",
        "--id", "Python.Python.3.11",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
        "--silent"
    )

    if (Test-IsAdministrator) {
        $arguments += @("--scope", "machine")
    }

    & $wingetCommand.Source @arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    return $true
}

function Install-Python311FromPythonOrg {
    $pythonVersion = $script:Python311FallbackVersion
    $installerUrl = $script:Python311FallbackUrl
    $targetDir = Join-Path $env:ProgramFiles "Python311"
    $tempRoot = Join-Path $env:TEMP ("alchemy-python-installer-" + [guid]::NewGuid().ToString("N"))
    $installerPath = Join-Path $tempRoot "python-$pythonVersion-amd64.exe"

    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

    try {
        $installerUri = [Uri]$installerUrl
        if ($installerUri.Host -ne "www.python.org") {
            throw "Python fallback installer host must be www.python.org."
        }
        if ($installerUri.AbsolutePath -ne "/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe") {
            throw "Python fallback installer path must target python-$pythonVersion-amd64.exe."
        }

        Write-InstallerStage "winget is unavailable or failed. Downloading Python 3.11 installer from python.org..."
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

        if (-not (Test-Path -LiteralPath $installerPath)) {
            throw "Python installer download did not produce a file."
        }

        $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
            throw "Downloaded Python installer signature is not valid."
        }
        if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            throw "Downloaded Python installer is not signed by the Python Software Foundation."
        }

        Write-InstallerStage "Running Python installer..."
        $arguments = @(
            "/quiet",
            "InstallAllUsers=1",
            "PrependPath=1",
            "Include_pip=1",
            "Include_test=0",
            "Shortcuts=0",
            "SimpleInstall=1",
            "Include_launcher=1",
            "TargetDir=$targetDir"
        )

        $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Python installer exited with code $($process.ExitCode)."
        }
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-PythonInterpreter {
    Write-InstallerStage "Checking Python 3.11..."

    $python = Resolve-PythonInterpreter
    if ($python) {
        Write-Host "Verified Python: $($python.DisplayName)"
        return $python
    }

    $installedWithWinget = Install-Python311WithWinget
    if ($installedWithWinget) {
        $python = Resolve-PythonInterpreterAfterInstall -EmitDiagnostics
        if ($python) {
            Write-Host "Python installed successfully."
            Write-Host "Verified Python: $($python.DisplayName)"
            return $python
        }

        Write-Host ""
        Write-Host "Python was installed by winget, but no supported interpreter could be verified yet. Falling back to the official python.org installer..."
    }

    Install-Python311FromPythonOrg

    $python = Resolve-PythonInterpreterAfterInstall -EmitDiagnostics
    if (-not $python) {
        throw "Python installation completed, but no supported 64-bit Python interpreter could be verified."
    }

    Write-Host "Python installed successfully."
    Write-Host "Verified Python: $($python.DisplayName)"
    return $python
}
