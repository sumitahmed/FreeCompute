@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python -m harness.cli.main %*
if errorlevel 1 (
    echo.
    echo [FreeCompute] Process exited with error code %errorlevel%.
)
