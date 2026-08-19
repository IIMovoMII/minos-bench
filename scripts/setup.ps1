$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$env:UV_NO_EDITABLE = "1"
uv sync --all-groups --no-editable --link-mode copy `
    --reinstall-package minos-bench

Write-Host "Environment ready: $projectRoot\.venv"
