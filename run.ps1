<#
.SYNOPSIS
    FreeCompute PowerShell Launcher
.DESCRIPTION
    Launches FreeCompute in the active PowerShell console with proper UTF-8 output.
#>

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
}

python -m harness.cli.main $args
