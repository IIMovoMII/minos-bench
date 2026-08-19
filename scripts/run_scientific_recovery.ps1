[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$')]
    [string]$SourceExecutionId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$')]
    [string]$RecoveryExecutionId
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & (Join-Path $PSScriptRoot "setup.ps1")
}

Import-Module (Join-Path $PSScriptRoot "ModelProfile.psm1") -Force
if (-not (Test-LlmEvalProfileExists)) {
    throw "No encrypted local model profile exists. Use the profile manager first."
}

# The profile is decrypted only into this process and is never printed.
$profile = Get-LlmEvalProfile
Import-LlmEvalProfileToProcess $profile
$profile = $null

$cli = Join-Path $PSScriptRoot "run_cli.ps1"
$executionPlan = Join-Path $projectRoot (
    "artifacts\scientific_v2\executions\{0}\execution_plan.json" -f `
        $RecoveryExecutionId
)

& $cli scientific-validate
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $executionPlan)) {
    & $cli scientific-prepare-recovery `
        --source-execution-id $SourceExecutionId `
        --execution-id $RecoveryExecutionId
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

& $cli scientific-run `
    --execution-id $RecoveryExecutionId `
    --allow-runtime-recovery `
    --judge-contract-retries 1
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $cli scientific-machine-final-report --execution-id $RecoveryExecutionId
exit $LASTEXITCODE
