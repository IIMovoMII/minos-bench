[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$')]
    [string]$ExecutionId,

    [int]$MaxRecoveryRounds = 5
)

$runner = Join-Path $PSScriptRoot "run_scientific_v2.ps1"
& $runner `
    -ExecutionId $ExecutionId `
    -MaxRecoveryRounds $MaxRecoveryRounds `
    -ScientificVersion v3
exit $LASTEXITCODE
