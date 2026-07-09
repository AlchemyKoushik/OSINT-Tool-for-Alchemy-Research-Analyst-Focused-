Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:PythonProbeCode = @'
import json
import platform
import struct
import sys

print(json.dumps({
    "major": sys.version_info[0],
    "minor": sys.version_info[1],
    "micro": sys.version_info[2],
    "bits": struct.calcsize("P") * 8,
    "executable": sys.executable,
    "implementation": platform.python_implementation(),
}))
'@

$script:PythonVersionPolicyDescription = "Python 3.11-3.13 x64"
$script:Python311FallbackVersion = "3.11.9"
$script:Python311FallbackUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$script:Python311FallbackSha256 = ""
$script:InstallerLogPath = $null

function Set-InstallerLogPath {
    param([string]$Path)

    $script:InstallerLogPath = $Path
    if ($Path) {
        $logDirectory = Split-Path -Parent $Path
        if ($logDirectory) {
            New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        }
    }
}

function Write-InstallerLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    if (-not $script:InstallerLogPath) {
        return
    }

    $line = "{0} {1}" -f (Get-Date -Format o), $Message
    Add-Content -LiteralPath $script:InstallerLogPath -Value $line -Encoding UTF8
}

function Write-InstallerStage {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host ""
    Write-Host $Message
    Write-InstallerLog -Message $Message
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-InstallerUserContext {
    param(
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = "",
        [string]$OriginalOneDriveCommercial = "",
        [string]$OriginalOneDriveConsumer = ""
    )

    $localAppData = if ($OriginalLocalAppData) { $OriginalLocalAppData } else { [Environment]::GetFolderPath("LocalApplicationData") }
    $userProfile = if ($OriginalUserProfile) { $OriginalUserProfile } else { $env:USERPROFILE }
    $userName = if ($OriginalUserName) { $OriginalUserName } else { $env:USERNAME }
    $oneDriveCommercial = if ($OriginalOneDriveCommercial) { $OriginalOneDriveCommercial } else { $env:OneDriveCommercial }
    $oneDriveConsumer = if ($OriginalOneDriveConsumer) { $OriginalOneDriveConsumer } else { $env:OneDriveConsumer }

    return [PSCustomObject]@{
        UserName           = $userName
        UserProfile        = $userProfile
        LocalAppData       = $localAppData
        OneDriveCommercial = $oneDriveCommercial
        OneDriveConsumer   = $oneDriveConsumer
        DesktopCandidates  = @(
            (Join-Path $userProfile "Desktop"),
            $(if ($oneDriveCommercial) { Join-Path $oneDriveCommercial "Desktop" }),
            $(if ($oneDriveConsumer) { Join-Path $oneDriveConsumer "Desktop" }),
            (Join-Path $userProfile "OneDrive - Alchemy Research and Analytics\Desktop")
        ) | Where-Object { $_ } | Select-Object -Unique
    }
}

function Remove-StaleInstallerTempRoots {
    param([int]$MaxAgeHours = 12)

    $tempRoot = [System.IO.Path]::GetTempPath()
    $cutoff = (Get-Date).AddHours(-1 * $MaxAgeHours)
    $prefixes = @(
        "alchemy-release-install-",
        "alchemy-bootstrap-",
        "alchemy-python-installer-"
    )

    foreach ($prefix in $prefixes) {
        foreach ($entry in (Get-ChildItem -LiteralPath $tempRoot -Directory -ErrorAction SilentlyContinue)) {
            if (-not $entry.Name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }

            if ($entry.LastWriteTime -gt $cutoff) {
                continue
            }

            Remove-Item -LiteralPath $entry.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-SupportedPythonVersion {
    param(
        [Parameter(Mandatory = $true)][int]$Major,
        [Parameter(Mandatory = $true)][int]$Minor
    )

    return $Major -eq 3 -and $Minor -ge 11 -and $Minor -le 13
}

function Get-ProcessArgumentText {
    param([string[]]$Arguments = @())

    $encoded = foreach ($argument in $Arguments) {
        if ($null -eq $argument) {
            '""'
            continue
        }

        $text = [string]$argument
        if ($text -notmatch '[\s"]') {
            $text
            continue
        }

        '"' + (($text -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
    }

    return ($encoded -join ' ')
}

function Invoke-ExternalProcessCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 15
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $argumentText = Get-ProcessArgumentText -Arguments $Arguments
    if ($startInfo.PSObject.Properties.Name -contains "ArgumentList" -and $startInfo.ArgumentList) {
        foreach ($argument in $Arguments) {
            [void]$startInfo.ArgumentList.Add([string]$argument)
        }
    } else {
        $startInfo.Arguments = $argumentText
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    try {
        $started = $process.Start()
    } catch {
        return [PSCustomObject]@{
            Started         = $false
            TimedOut        = $false
            ExitCode        = $null
            StdOut          = ""
            StdErr          = ""
            FilePath        = $FilePath
            Arguments       = @($Arguments)
            ArgumentText    = $argumentText
            UseShellExecute = $startInfo.UseShellExecute
            StartException  = $_.Exception.Message
        }
    }

    if (-not $started) {
        return [PSCustomObject]@{
            Started         = $false
            TimedOut        = $false
            ExitCode        = $null
            StdOut          = ""
            StdErr          = ""
            FilePath        = $FilePath
            Arguments       = @($Arguments)
            ArgumentText    = $argumentText
            UseShellExecute = $startInfo.UseShellExecute
            StartException  = "Process failed to start."
        }
    }

    $timedOut = -not $process.WaitForExit($TimeoutSeconds * 1000)
    if ($timedOut) {
        try {
            $process.Kill()
        } catch {
        }
    } else {
        $process.WaitForExit()
    }

    $stdOut = $process.StandardOutput.ReadToEnd()
    $stdErr = $process.StandardError.ReadToEnd()

    return [PSCustomObject]@{
        Started         = $true
        TimedOut        = $timedOut
        ExitCode        = $(if ($timedOut) { $null } else { $process.ExitCode })
        StdOut          = $stdOut
        StdErr          = $stdErr
        FilePath        = $FilePath
        Arguments       = @($Arguments)
        ArgumentText    = $argumentText
        UseShellExecute = $startInfo.UseShellExecute
        StartException  = ""
    }
}

function Test-WindowsAppsAliasPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $expanded = [System.IO.Path]::GetFullPath($Path)
    return $expanded -like "*\Microsoft\WindowsApps\*"
}

function Get-PythonProbe {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $probeArguments = @($Arguments + @("-c", $script:PythonProbeCode))
    $result = Invoke-ExternalProcessCapture -FilePath $FilePath -Arguments $probeArguments
    $stdoutText = [string]$result.StdOut
    $stderrText = [string]$result.StdErr

    if (-not $result.Started) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "Process failed to start: $($result.StartException)"
            Detail  = $result
        }
    }

    if ($result.TimedOut) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "Process timed out after 15 seconds."
            Detail  = $result
        }
    }

    if ($result.ExitCode -ne 0) {
        $message = "Process exited with code $($result.ExitCode)."
        if ($stderrText.Trim()) {
            $message += " stderr: $($stderrText.Trim())"
        }
        return [PSCustomObject]@{
            Success = $false
            Reason  = $message
            Detail  = $result
        }
    }

    if (-not $stdoutText.Trim()) {
        $message = "Process returned empty stdout."
        if ($stderrText.Trim()) {
            $message += " stderr: $($stderrText.Trim())"
        }
        return [PSCustomObject]@{
            Success = $false
            Reason  = $message
            Detail  = $result
        }
    }

    try {
        $probe = $stdoutText | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "Probe output was not valid JSON."
            Detail  = $result
        }
    }

    $propertyNames = @($probe.PSObject.Properties.Name)
    foreach ($requiredProperty in @("major", "minor", "micro", "bits", "executable")) {
        if ($propertyNames -notcontains $requiredProperty) {
            return [PSCustomObject]@{
                Success = $false
                Reason  = "Probe JSON did not include '$requiredProperty'."
                Detail  = $result
            }
        }
    }

    return [PSCustomObject]@{
        Success = $true
        Reason  = "Probe succeeded."
        Detail  = $result
        Probe   = [PSCustomObject]@{
            ExecutablePath = [string]$probe.executable
            Major          = [int]$probe.major
            Minor          = [int]$probe.minor
            Micro          = [int]$probe.micro
            Bits           = [int]$probe.bits
            Implementation = [string]$probe.implementation
        }
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

    if (-not $FilePath) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Candidate path was empty."
        }
    }

    if (Test-WindowsAppsAliasPath -Path $FilePath) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Rejected Microsoft Store WindowsApps alias path."
        }
    }

    if (-not (Test-Path -LiteralPath $FilePath)) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "File does not exist."
        }
    }

    $fileInfo = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
    if (-not $fileInfo -or $fileInfo.PSIsContainer) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Candidate is not a real file."
        }
    }

    $probe = Get-PythonProbe -FilePath $FilePath -Arguments $Arguments
    if (-not $probe.Success) {
        return [PSCustomObject]@{
            Accepted       = $false
            Candidate      = $candidateLabel
            Reason         = $probe.Reason
            FileLength     = $fileInfo.Length
            InvocationPath = $FilePath
            ArgumentText   = $probe.Detail.ArgumentText
            ExitCode       = $probe.Detail.ExitCode
            StdOut         = $probe.Detail.StdOut
            StdErr         = $probe.Detail.StdErr
        }
    }

    $resolvedPath = [string]$probe.Probe.ExecutablePath
    if (-not $resolvedPath) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Probe returned an empty executable path."
        }
    }

    $resolvedPath = [System.IO.Path]::GetFullPath($resolvedPath)
    if (-not (Test-Path -LiteralPath $resolvedPath)) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Resolved executable path does not exist: $resolvedPath"
        }
    }

    if (Test-WindowsAppsAliasPath -Path $resolvedPath) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Probe resolved to a Microsoft Store WindowsApps alias."
        }
    }

    if (-not (Test-SupportedPythonVersion -Major $probe.Probe.Major -Minor $probe.Probe.Minor)) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Unsupported Python version $($probe.Probe.Major).$($probe.Probe.Minor).$($probe.Probe.Micro). $script:PythonVersionPolicyDescription is supported."
        }
    }

    if ($probe.Probe.Bits -ne 64) {
        return [PSCustomObject]@{
            Accepted = $false
            Candidate = $candidateLabel
            Reason = "Interpreter is $($probe.Probe.Bits)-bit. 64-bit Python is required."
        }
    }

    return [PSCustomObject]@{
        Accepted       = $true
        Candidate      = $candidateLabel
        Reason         = "Accepted."
        Path           = $resolvedPath
        Version        = "{0}.{1}.{2}" -f $probe.Probe.Major, $probe.Probe.Minor, $probe.Probe.Micro
        Major          = $probe.Probe.Major
        Minor          = $probe.Probe.Minor
        Micro          = $probe.Probe.Micro
        Bits           = $probe.Probe.Bits
        DisplayName    = "$resolvedPath ($($probe.Probe.Major).$($probe.Probe.Minor).$($probe.Probe.Micro), $($probe.Probe.Bits)-bit)"
        FileLength     = $fileInfo.Length
        InvocationPath = $FilePath
        ArgumentText   = $probe.Detail.ArgumentText
        ExitCode       = $probe.Detail.ExitCode
        StdOut         = $probe.Detail.StdOut
        StdErr         = $probe.Detail.StdErr
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
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$Candidates,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$FilePath,
        [string[]]$Arguments = @()
    )

    if (-not $FilePath) {
        return
    }

    $Candidates.Add([PSCustomObject]@{
        FilePath  = [string]$FilePath
        Arguments = @($Arguments)
    })
}

function Add-PythonPathCandidates {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$Candidates,
        [AllowEmptyString()][string]$BasePath
    )

    if (-not $BasePath) {
        return
    }

    Add-PythonCandidate -Candidates $Candidates -FilePath (Join-Path $BasePath "python.exe")
    Add-PythonCandidate -Candidates $Candidates -FilePath (Join-Path $BasePath "python3.exe")
}

function Get-PythonCommandCandidates {
    $candidates = New-Object System.Collections.Generic.List[object]

    Add-PythonCandidate -Candidates $candidates -FilePath "py.exe" -Arguments @("-3.11")
    Add-PythonCandidate -Candidates $candidates -FilePath "py.exe" -Arguments @("-3")
    Add-PythonCandidate -Candidates $candidates -FilePath "python.exe"
    Add-PythonCandidate -Candidates $candidates -FilePath "python3.exe"
    Add-PythonCandidate -Candidates $candidates -FilePath "python"
    Add-PythonCandidate -Candidates $candidates -FilePath "python3"

    foreach ($commandName in @("py.exe", "py", "python.exe", "python", "python3.exe", "python3")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            Add-PythonCandidate -Candidates $candidates -FilePath $command.Source
        }
    }

    return $candidates
}

function Get-PythonLauncherPaths {
    $paths = New-Object System.Collections.Generic.List[string]

    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $pyCommand) {
        $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    }

    if (-not $pyCommand) {
        return $paths
    }

    $launcherProbe = Invoke-ExternalProcessCapture -FilePath $pyCommand.Source -Arguments @("-0p")
    if (-not $launcherProbe.Started -or $launcherProbe.TimedOut -or $launcherProbe.ExitCode -ne 0) {
        return $paths
    }

    foreach ($line in (($launcherProbe.StdOut -split "`r?`n") | ForEach-Object { $_.Trim() })) {
        if (-not $line) {
            continue
        }

        $segments = $line -split "\s+", 2
        $candidatePath = if ($segments.Count -gt 1) { $segments[1].Trim() } else { $segments[0] }
        if ($candidatePath) {
            $paths.Add($candidatePath)
        }
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
        if ($null -eq $value) {
            return $null
        }

        $text = [string]$value
        if ([string]::IsNullOrWhiteSpace($text)) {
            return $null
        }

        return $text.Trim()
    } catch {
        return $null
    }
}

function Get-RegistryDefaultStringValue {
    param([Parameter(Mandatory = $true)][string]$Path)

    return Get-RegistryStringValue -Path $Path -Name "(default)"
}

function Get-PythonRegistryCandidates {
    param([string[]]$RegistryRoots = @(
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore",
        "HKCU:\SOFTWARE\Python\PythonCore"
    ))

    $candidates = New-Object System.Collections.Generic.List[object]

    foreach ($registryRoot in $RegistryRoots) {
        foreach ($key in (Get-ChildItem -Path $registryRoot -ErrorAction SilentlyContinue)) {
            $versionInstallPath = Get-RegistryStringValue -Path $key.PSPath -Name "InstallPath"
            if ($versionInstallPath) {
                Add-PythonPathCandidates -Candidates $candidates -BasePath $versionInstallPath
            }

            $installPathSubkey = Join-Path $key.PSPath "InstallPath"
            if (-not (Test-Path -LiteralPath $installPathSubkey)) {
                continue
            }

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

    return $candidates
}

function Get-DeterministicPython311Candidates {
    param([string]$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData"))

    $candidates = New-Object System.Collections.Generic.List[object]

    foreach ($basePath in @(
        (Join-Path $env:ProgramFiles "Python311"),
        $(if ($LocalAppData) { Join-Path $LocalAppData "Programs\Python\Python311" })
    )) {
        if ($basePath) {
            Add-PythonPathCandidates -Candidates $candidates -BasePath $basePath
        }
    }

    return $candidates
}

function Get-KnownPythonInstallPaths {
    param([string]$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData"))

    $candidates = New-Object System.Collections.Generic.List[object]

    foreach ($pathRoot in @(
        (Join-Path $env:ProgramFiles "Python311"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python313"),
        $(if ($LocalAppData) { Join-Path $LocalAppData "Programs\Python\Python311" }),
        $(if ($LocalAppData) { Join-Path $LocalAppData "Programs\Python\Python312" }),
        $(if ($LocalAppData) { Join-Path $LocalAppData "Programs\Python\Python313" })
    )) {
        if ($pathRoot) {
            Add-PythonPathCandidates -Candidates $candidates -BasePath $pathRoot
        }
    }

    foreach ($pattern in @(
        (Join-Path $env:ProgramFiles "Python*"),
        $(if ($LocalAppData) { Join-Path $LocalAppData "Programs\Python\Python*" })
    )) {
        if (-not $pattern) {
            continue
        }

        foreach ($match in (Get-ChildItem -Path $pattern -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)) {
            Add-PythonPathCandidates -Candidates $candidates -BasePath $match
        }
    }

    foreach ($candidate in (Get-PythonRegistryCandidates)) {
        $candidates.Add($candidate)
    }

    foreach ($path in (Get-PythonLauncherPaths)) {
        Add-PythonCandidate -Candidates $candidates -FilePath $path
    }

    return $candidates
}

function Write-PythonDiscoveryDiagnostics {
    param(
        [Parameter(Mandatory = $true)][string]$Context,
        [Parameter(Mandatory = $true)][object[]]$Attempts,
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = ""
    )

    Write-Host ""
    Write-Host "$Context diagnostics:"
    Write-Host "  Current user: $env:USERNAME"
    Write-Host "  Current userprofile: $env:USERPROFILE"
    Write-Host "  Current LocalAppData: $([Environment]::GetFolderPath('LocalApplicationData'))"
    if ($OriginalUserName) {
        Write-Host "  Original user: $OriginalUserName"
    }
    if ($OriginalUserProfile) {
        Write-Host "  Original userprofile: $OriginalUserProfile"
    }
    if ($OriginalLocalAppData) {
        Write-Host "  Original LocalAppData: $OriginalLocalAppData"
    }

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

function Resolve-PythonInterpreterFromCandidateList {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Candidates,
        [switch]$EmitDiagnostics,
        [string]$DiagnosticContext = "Python discovery",
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = ""
    )

    $verifiedCandidates = New-Object System.Collections.Generic.List[object]
    $attempts = New-Object System.Collections.Generic.List[object]
    $seen = @{}

    foreach ($candidate in $Candidates) {
        if (-not $candidate) {
            continue
        }

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
        Write-PythonDiscoveryDiagnostics `
            -Context $DiagnosticContext `
            -Attempts $attempts `
            -OriginalUserName $OriginalUserName `
            -OriginalUserProfile $OriginalUserProfile `
            -OriginalLocalAppData $OriginalLocalAppData
    }

    $uniqueCandidates = $verifiedCandidates |
        Group-Object Path |
        ForEach-Object { $_.Group | Select-Object -First 1 }

    if (-not $uniqueCandidates) {
        return $null
    }

    return Select-BestPythonCandidate -Candidates $uniqueCandidates
}

function Resolve-PythonInterpreter {
    param(
        [switch]$EmitDiagnostics,
        [string]$DiagnosticContext = "Python discovery",
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = ""
    )

    $allCandidates = New-Object System.Collections.Generic.List[object]

    foreach ($candidate in (Get-PythonCommandCandidates)) {
        $allCandidates.Add($candidate)
    }

    foreach ($candidate in (Get-KnownPythonInstallPaths -LocalAppData $OriginalLocalAppData)) {
        $allCandidates.Add($candidate)
    }

    return Resolve-PythonInterpreterFromCandidateList `
        -Candidates $allCandidates `
        -EmitDiagnostics:$EmitDiagnostics `
        -DiagnosticContext $DiagnosticContext `
        -OriginalUserName $OriginalUserName `
        -OriginalUserProfile $OriginalUserProfile `
        -OriginalLocalAppData $OriginalLocalAppData
}

function Resolve-PythonInterpreterAfterInstall {
    param(
        [switch]$EmitDiagnostics,
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = "",
        [object[]]$PreferredCandidates = @()
    )

    if ($PreferredCandidates -and $PreferredCandidates.Count -gt 0) {
        $preferredPython = Resolve-PythonInterpreterFromCandidateList `
            -Candidates $PreferredCandidates `
            -EmitDiagnostics:$EmitDiagnostics `
            -DiagnosticContext "Deterministic post-install Python discovery" `
            -OriginalUserName $OriginalUserName `
            -OriginalUserProfile $OriginalUserProfile `
            -OriginalLocalAppData $OriginalLocalAppData

        if ($preferredPython) {
            return $preferredPython
        }
    }

    return Resolve-PythonInterpreter `
        -EmitDiagnostics:$EmitDiagnostics `
        -DiagnosticContext "Post-install Python discovery" `
        -OriginalUserName $OriginalUserName `
        -OriginalUserProfile $OriginalUserProfile `
        -OriginalLocalAppData $OriginalLocalAppData
}

function Install-Python311WithWinget {
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wingetCommand) {
        $wingetCommand = Get-Command winget -ErrorAction SilentlyContinue
    }

    if (-not $wingetCommand) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "winget not found."
        }
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

    $result = Invoke-ExternalProcessCapture -FilePath $wingetCommand.Source -Arguments $arguments -TimeoutSeconds 1800
    if (-not $result.Started) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "winget failed to start: $($result.StartException)"
            Result  = $result
        }
    }

    if ($result.TimedOut) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "winget timed out."
            Result  = $result
        }
    }

    if ($result.StdOut.Trim()) {
        Write-Host $result.StdOut.Trim()
    }
    if ($result.StdErr.Trim()) {
        Write-Host $result.StdErr.Trim()
    }

    if ($result.ExitCode -ne 0) {
        return [PSCustomObject]@{
            Success = $false
            Reason  = "winget exited with code $($result.ExitCode)."
            Result  = $result
        }
    }

    return [PSCustomObject]@{
        Success = $true
        Reason  = "winget install completed."
        Result  = $result
    }
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

        if ($script:Python311FallbackSha256) {
            $downloadedHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($downloadedHash -ne $script:Python311FallbackSha256.ToLowerInvariant()) {
                throw "Downloaded Python installer SHA256 mismatch."
            }
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

    return [PSCustomObject]@{
        Success = $true
        Reason  = "python.org install completed."
        Path    = (Join-Path $targetDir "python.exe")
    }
}

function Ensure-PythonInterpreter {
    param(
        [string]$OriginalUserName = "",
        [string]$OriginalUserProfile = "",
        [string]$OriginalLocalAppData = ""
    )

    Write-InstallerStage "Checking Python 3.11..."

    $python = Resolve-PythonInterpreter `
        -OriginalUserName $OriginalUserName `
        -OriginalUserProfile $OriginalUserProfile `
        -OriginalLocalAppData $OriginalLocalAppData
    if ($python) {
        Write-Host "Verified Python: $($python.DisplayName)"
        return $python
    }

    $wingetInstall = Install-Python311WithWinget
    if ($wingetInstall.Success) {
        $preferredCandidates = Get-DeterministicPython311Candidates -LocalAppData $OriginalLocalAppData
        $python = Resolve-PythonInterpreterAfterInstall `
            -EmitDiagnostics `
            -OriginalUserName $OriginalUserName `
            -OriginalUserProfile $OriginalUserProfile `
            -OriginalLocalAppData $OriginalLocalAppData `
            -PreferredCandidates $preferredCandidates
        if ($python) {
            Write-Host "Python installed successfully."
            Write-Host "Verified Python: $($python.DisplayName)"
            return $python
        }

        Write-Host ""
        Write-Host "Python was installed by winget, but no supported interpreter could be verified yet. Falling back to the official python.org installer..."
    }

    $pythonOrgInstall = Install-Python311FromPythonOrg

    $python = Resolve-PythonInterpreterAfterInstall `
        -EmitDiagnostics `
        -OriginalUserName $OriginalUserName `
        -OriginalUserProfile $OriginalUserProfile `
        -OriginalLocalAppData $OriginalLocalAppData `
        -PreferredCandidates @([PSCustomObject]@{ FilePath = $pythonOrgInstall.Path; Arguments = @() })
    if (-not $python) {
        throw "Python installation completed, but no supported 64-bit Python interpreter could be verified."
    }

    Write-Host "Python installed successfully."
    Write-Host "Verified Python: $($python.DisplayName)"
    return $python
}
