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

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $probe = Get-PythonProbe -FilePath $FilePath -Arguments $Arguments
    if (-not $probe) {
        return $null
    }

    if (-not (Test-SupportedPythonVersion -Major $probe.Major -Minor $probe.Minor)) {
        return $null
    }

    if ($probe.Bits -ne 64) {
        return $null
    }

    $resolvedPath = [System.IO.Path]::GetFullPath($probe.ExecutablePath)
    if (-not (Test-Path -LiteralPath $resolvedPath)) {
        return $null
    }

    return [PSCustomObject]@{
        Path        = $resolvedPath
        Version     = "{0}.{1}.{2}" -f $probe.Major, $probe.Minor, $probe.Micro
        Major       = $probe.Major
        Minor       = $probe.Minor
        Micro       = $probe.Micro
        Bits        = $probe.Bits
        DisplayName = "$resolvedPath ($($probe.Major).$($probe.Minor).$($probe.Micro), $($probe.Bits)-bit)"
    }
}

function Get-PythonCommandCandidates {
    return @(
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ FilePath = "py"; Arguments = @("-3") },
        [PSCustomObject]@{ FilePath = "python"; Arguments = @() },
        [PSCustomObject]@{ FilePath = "python.exe"; Arguments = @() }
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

function Get-KnownPythonInstallPaths {
    $candidates = New-Object System.Collections.Generic.List[string]
    $directCandidates = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python313\python.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    )

    foreach ($path in $directCandidates) {
        if ($path) {
            $candidates.Add($path)
        }
    }

    $globRoots = @(
        (Join-Path $env:ProgramFiles "Python3*\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe")
    )

    foreach ($pattern in $globRoots) {
        if (-not $pattern) {
            continue
        }
        foreach ($match in (Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)) {
            $candidates.Add($match)
        }
    }

    $registryRoots = @(
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKCU:\SOFTWARE\Python\PythonCore"
    )

    foreach ($registryRoot in $registryRoots) {
        foreach ($key in (Get-ChildItem -Path $registryRoot -ErrorAction SilentlyContinue)) {
            $installPath = (Get-ItemProperty -LiteralPath $key.PSPath -Name InstallPath -ErrorAction SilentlyContinue).InstallPath
            if ($installPath) {
                $candidates.Add((Join-Path $installPath "python.exe"))
            }
        }
    }

    foreach ($path in (Get-PythonLauncherPaths)) {
        $candidates.Add($path)
    }

    return $candidates
}

function Select-BestPythonCandidate {
    param([Parameter(Mandatory = $true)][object[]]$Candidates)

    return $Candidates |
        Sort-Object @{ Expression = { if ($_.Minor -eq 11) { 0 } else { $_.Minor } } }, @{ Expression = { $_.Path } } |
        Select-Object -First 1
}

function Resolve-PythonInterpreter {
    $verifiedCandidates = New-Object System.Collections.Generic.List[object]

    foreach ($candidate in (Get-PythonCommandCandidates)) {
        $verified = Test-PythonCandidate -FilePath $candidate.FilePath -Arguments $candidate.Arguments
        if ($verified) {
            $verifiedCandidates.Add($verified)
        }
    }

    foreach ($candidatePath in (Get-KnownPythonInstallPaths)) {
        if (-not $candidatePath) {
            continue
        }
        $verified = Test-PythonCandidate -FilePath $candidatePath
        if ($verified) {
            $verifiedCandidates.Add($verified)
        }
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
    $verifiedCandidates = New-Object System.Collections.Generic.List[object]

    foreach ($candidatePath in (Get-KnownPythonInstallPaths)) {
        if (-not $candidatePath) {
            continue
        }
        $verified = Test-PythonCandidate -FilePath $candidatePath
        if ($verified) {
            $verifiedCandidates.Add($verified)
        }
    }

    $uniqueCandidates = $verifiedCandidates |
        Group-Object Path |
        ForEach-Object { $_.Group | Select-Object -First 1 }

    if (-not $uniqueCandidates) {
        return $null
    }

    return Select-BestPythonCandidate -Candidates $uniqueCandidates
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
            "Include_launcher=1"
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
    if (-not $installedWithWinget) {
        Install-Python311FromPythonOrg
    }

    $python = Resolve-PythonInterpreterAfterInstall
    if (-not $python) {
        throw "Python installation completed, but no supported 64-bit Python interpreter could be verified."
    }

    Write-Host "Python installed successfully."
    Write-Host "Verified Python: $($python.DisplayName)"
    return $python
}
