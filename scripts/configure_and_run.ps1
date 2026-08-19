[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & (Join-Path $PSScriptRoot "setup.ps1")
}

. (Join-Path $PSScriptRoot "configure_models.ps1") -SkipStatus
& (Join-Path $PSScriptRoot "run_full_pipeline.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$latestPipelinePath = Join-Path `
    $projectRoot `
    "artifacts\pipelines\latest.json"
if (Test-Path -LiteralPath $latestPipelinePath -PathType Leaf) {
    $latestPipeline = Get-Content -Raw -LiteralPath $latestPipelinePath |
        ConvertFrom-Json
    if ([string]$latestPipeline.status -eq "awaiting_evaluation_model_design") {
        Write-Host ""
        Write-Host "No online call was made."
        Write-Host (
            "Formal evaluation is paused until the candidate confirms the " +
            "scientific evaluation-model freeze."
        )
        return
    }
    if ([string]$latestPipeline.status -eq "awaiting_staged_pipeline_rewrite") {
        Write-Host ""
        Write-Host "No online call was made."
        Write-Host (
            "The withdrawn all-in-one matrix remains disabled until the " +
            "staged runner is implemented and tested."
        )
        return
    }
    if ([string]$latestPipeline.status -eq "awaiting_execution_authorization") {
        Write-Host ""
        Write-Host "No online call was made."
        Write-Host (
            "Formal evaluation is paused until the candidate approves the " +
            "versioned call plan and safety limits."
        )
        return
    }
}

Write-Host ""
Write-Host "You can now start the review UI with:"
Write-Host "  .\scripts\start_ui.ps1"
