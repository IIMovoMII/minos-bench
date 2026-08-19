[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("model_a", "model_b", "weak_model", "judge")]
    [string]$Slot
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "Project virtual environment is missing. Run scripts/setup.ps1 first."
}

Import-Module (Join-Path $PSScriptRoot "ModelProfile.psm1") -Force -DisableNameChecking
if (-not (Test-LlmEvalProfileExists)) {
    throw "No encrypted local model profile exists. Use the profile manager first."
}

# Values exist only in this process and are never printed by the safe probe.
$profile = Get-LlmEvalProfile
Import-LlmEvalProfileToProcess $profile
$profile = $null

$cli = Join-Path $PSScriptRoot "run_cli.ps1"
& $cli scientific-slot-probe --slot $Slot
exit $LASTEXITCODE
