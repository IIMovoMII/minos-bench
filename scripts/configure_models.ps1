[CmdletBinding()]
param(
    [switch]$SkipStatus
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$modulePath = Join-Path $PSScriptRoot "ModelProfile.psm1"
$managerPath = Join-Path $PSScriptRoot "manage_model_profile.ps1"
Import-Module $modulePath -Force

Write-Host ""
Write-Host "Minos Bench - persistent local configuration"
Write-Host "API keys and full Base URLs are protected with Windows DPAPI."
Write-Host "The saved profile is loaded only into this evaluation process."
Write-Host ""

if (-not (Test-LlmEvalProfileExists)) {
    Write-Host "No persistent model profile exists. Complete the one-time setup."
    & $managerPath -Initialize
    if (-not (Test-LlmEvalProfileExists)) {
        throw "Persistent model profile setup did not complete."
    }
}

$profile = Get-LlmEvalProfile
Import-LlmEvalProfileToProcess $profile

Write-Host "Saved profile loaded:"
Get-LlmEvalSafeProfileSummary $profile | Format-Table -AutoSize
Write-Host "API keys and full Base URLs were not displayed."
Write-Host "Run 管理模型配置.cmd whenever you need to change one field."

if (-not $SkipStatus) {
    & (Join-Path $PSScriptRoot "run_cli.ps1") env-status `
        --config configs\run_model_a_prompt_v1.yaml
    & (Join-Path $PSScriptRoot "run_cli.ps1") env-status `
        --config configs\run_model_b_prompt_v1.yaml
    & (Join-Path $PSScriptRoot "run_cli.ps1") env-status `
        --config configs\run_weak_prompt_v2.yaml
}
