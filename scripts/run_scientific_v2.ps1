[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$')]
    [string]$ExecutionId,

    [int]$MaxRecoveryRounds = 5
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

# The profile is decrypted only into this PowerShell process and never printed.
$profile = Get-LlmEvalProfile
Import-LlmEvalProfileToProcess $profile
$profile = $null

$cli = Join-Path $PSScriptRoot "run_cli.ps1"
$executionRoot = Join-Path $projectRoot "artifacts\scientific_v2\executions"

& $cli scientific-validate
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

function Invoke-ScientificRun {
    param([string]$Id)
    $raw = & $cli scientific-run --execution-id $Id --allow-runtime-recovery | Out-String
    $exitCode = $LASTEXITCODE
    try {
        $value = $raw | ConvertFrom-Json
    }
    catch {
        throw "scientific-run returned an unreadable safe status (exit $exitCode)"
    }
    if ($exitCode -ne 0 -and $value.status -ne "completed") {
        Write-Output ($value | ConvertTo-Json -Depth 8)
        return $null
    }
    return $value
}

function Get-RuntimeErrorNodeCount {
    param(
        [string]$Id,
        [string]$Stage = ""
    )
    $nodesPath = Join-Path (Join-Path $executionRoot $Id) "nodes"
    if (-not (Test-Path -LiteralPath $nodesPath)) {
        return 0
    }
    $count = 0
    foreach ($nodePath in (Get-ChildItem -LiteralPath $nodesPath -Filter "*.json" -File)) {
        $node = $null
        for ($attempt = 0; $attempt -lt 8; $attempt++) {
            try {
                $node = Get-Content -LiteralPath $nodePath.FullName -Raw | ConvertFrom-Json
                break
            }
            catch {
                if ($attempt -ge 7) {
                    throw "Unable to read node status safely: $($nodePath.Name)"
                }
                Start-Sleep -Milliseconds (25 * ($attempt + 1))
            }
        }
        if (
            $node.status -eq "runtime_error" -and
            ([string]::IsNullOrWhiteSpace($Stage) -or $node.stage -eq $Stage)
        ) {
            $count++
        }
    }
    return $count
}

$currentId = $ExecutionId
for ($round = 0; $round -le $MaxRecoveryRounds; $round++) {
    if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $executionRoot $currentId) "execution_plan.json"))) {
        & $cli scientific-plan --execution-id $currentId
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    $run = Invoke-ScientificRun -Id $currentId
    if ($null -eq $run) {
        exit 2
    }

    $runtimeErrors = Get-RuntimeErrorNodeCount -Id $currentId
    if ($runtimeErrors -eq 0) {
        & $cli scientific-machine-final-report --execution-id $currentId
        exit $LASTEXITCODE
    }

    if ($round -ge $MaxRecoveryRounds) {
        Write-Output "V2 execution still has $runtimeErrors runtime-error nodes; successful nodes were not replayed."
        exit 2
    }

    $judgeRuntimeErrors = Get-RuntimeErrorNodeCount `
        -Id $currentId `
        -Stage "judge_evaluation"
    if ($judgeRuntimeErrors -gt 0) {
        # A completed initial Judge probe can go offline later. Check the route
        # once before creating a large derived recovery; a failed preflight must
        # not turn 95 known route errors into another paid batch of failures.
        & (Join-Path $PSScriptRoot "run_scientific_slot_probe.ps1") -Slot judge | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Output "Judge route preflight failed; no derived recovery was started."
            exit 2
        }
    }

    $nextId = "$ExecutionId-recovery-$($round + 1)"
    & $cli scientific-prepare-recovery `
        --source-execution-id $currentId `
        --execution-id $nextId
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    $currentId = $nextId
}

exit 2
