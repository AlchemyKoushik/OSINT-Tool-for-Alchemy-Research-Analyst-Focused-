Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Menu {
    Clear-Host
    Write-Host "==============================================="
    Write-Host "        ALCHEMY INDUSTRY RESEARCH TOOL"
    Write-Host "==============================================="
    Write-Host ""
    Write-Host "1. Start the Industry Research Tool"
    Write-Host "2. Remove the Tool from Your Device"
    Write-Host ""
}

function Wait-BeforeExit {
    Write-Host ""
    [void](Read-Host "Press Enter to close this launcher")
}

try {
    Show-Menu
    $selection = Read-Host "Choose an option [1]"
    $normalized = [string]$selection
    $normalized = $normalized.Trim()

    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized -eq "1") {
        & (Join-Path $PSScriptRoot "alchemy_start_tool.ps1")
        exit 0
    }

    if ($normalized -eq "2") {
        & (Join-Path $PSScriptRoot "alchemy_uninstall_tool.ps1")
        exit 0
    }

    Write-Host ""
    Write-Host "That option is not valid. Please launch the menu again."
    Start-Sleep -Seconds 2
} catch {
    Write-Host ""
    Write-Host "The launcher hit an error:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Wait-BeforeExit
    exit 1
}
