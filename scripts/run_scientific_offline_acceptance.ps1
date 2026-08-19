[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing. Run scripts/setup.ps1 first."
}

Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"

& $python "scripts\build_scientific_v1.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m llm_eval_workbench.cli scientific-validate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m compileall -q src app.py scripts tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m ruff check src tests "scripts\build_scientific_v1.py" app.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

[ordered]@{
    status = "passed"
    provider_requests = 0
    scientific_dataset = "sealed"
    real_provider_stage_entered = $false
} | ConvertTo-Json
