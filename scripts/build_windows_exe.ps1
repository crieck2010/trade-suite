# PowerShell script to build the Windows standalone desktop application
[CmdletBinding()]
param (
    [switch]$SkipTests,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceRoot = Split-Path -Parent $ScriptDir

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🦅 Building Trade Dashboard App Native Windows Executable" -ForegroundColor Cyan
Write-Host "Workspace: $WorkspaceRoot" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan

$buildArgs = @("scripts/build_windows_exe.py")
if ($SkipTests) { $buildArgs += "--skip-tests" }
if ($Clean) { $buildArgs += "--clean" }

python @buildArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build script failed with exit code $LASTEXITCODE"
}
