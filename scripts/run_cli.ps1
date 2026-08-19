param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:DEEPEVAL_TELEMETRY_OPT_OUT = "YES"
uv run --no-sync python -m llm_eval_workbench.cli @CliArgs
