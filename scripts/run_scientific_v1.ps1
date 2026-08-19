[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$')]
    [string]$ExecutionId,

    [string]$ProviderProbeReceipt
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

# The profile is decrypted only into this PowerShell process. No value is printed.
$profile = Get-LlmEvalProfile
Import-LlmEvalProfileToProcess $profile
$profile = $null

$cli = Join-Path $PSScriptRoot "run_cli.ps1"
& $cli scientific-validate
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& $cli scientific-plan --execution-id $ExecutionId
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if ($ProviderProbeReceipt) {
    & $cli scientific-import-provider-probes `
        --execution-id $ExecutionId `
        --receipt $ProviderProbeReceipt
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
& $cli scientific-run --execution-id $ExecutionId
exit $LASTEXITCODE
