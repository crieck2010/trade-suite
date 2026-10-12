<#
.SYNOPSIS
    Launches Moomoo OpenD on Windows workstation (port 11111).
.DESCRIPTION
    Checks if OpenD is already running on 127.0.0.1:11111.
    If not, executes scripts/setup_moomoo_opend.py to download, configure, and launch OpenD.
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       Moomoo OpenD Gateway Launcher (Port 11111)         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$scriptPath = Join-Path $PSScriptRoot "setup_moomoo_opend.py"

python $scriptPath --launch --gui
