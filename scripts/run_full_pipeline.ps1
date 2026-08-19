[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$cli = Join-Path $PSScriptRoot "run_cli.ps1"
$pipelineDirectory = Join-Path $projectRoot "artifacts\pipelines"
New-Item -ItemType Directory -Path $pipelineDirectory -Force | Out-Null
$authorizationReceiptDirectory = Join-Path `
    $pipelineDirectory `
    "execution_authorizations"
New-Item `
    -ItemType Directory `
    -Path $authorizationReceiptDirectory `
    -Force | Out-Null
$pipelineTimestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$pipelinePath = Join-Path $pipelineDirectory "pipeline_$pipelineTimestamp.json"
$latestPath = Join-Path $pipelineDirectory "latest.json"
$evaluationModelFreezePath = Join-Path `
    $projectRoot `
    "configs\evaluation_model_freeze.json"
$executionAuthorizationPath = Join-Path `
    $projectRoot `
    "configs\evaluation_run_authorization.json"

$state = [ordered]@{
    pipeline_id = $pipelineTimestamp
    status = "running"
    stage = "preflight"
    started_at = [DateTime]::UtcNow.ToString("o")
    finished_at = $null
    probes = [ordered]@{}
    runs = [ordered]@{}
    comparisons = [ordered]@{}
    verification = [ordered]@{}
    failed_probes = @()
    evaluation_model_freeze = [ordered]@{
        required = $true
        artifact = "configs/evaluation_model_freeze.json"
        validated = $false
        version = $null
    }
    staged_execution_plan = [ordered]@{
        required = $true
        implemented = $false
        reason = "The legacy all-in-one online matrix was withdrawn."
    }
    execution_authorization = [ordered]@{
        required = $true
        artifact = "configs/evaluation_run_authorization.json"
        validated = $false
        version = $null
        max_consecutive_runtime_errors = $null
        max_target_requests_per_run = $null
        max_judge_requests_per_run = $null
        receipt = $null
    }
    error_type = $null
    next_action = $null
}

function Save-PipelineState {
    $json = $state | ConvertTo-Json -Depth 20
    $temporaryPath = "$pipelinePath.tmp"
    [IO.File]::WriteAllText($temporaryPath, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryPath -Destination $pipelinePath -Force
    [IO.File]::WriteAllText(
        "$latestPath.tmp",
        $json,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath "$latestPath.tmp" -Destination $latestPath -Force
}

function Invoke-EvalJson {
    param(
        [string[]]$Arguments,
        [switch]$AllowNonZero
    )
    $rawOutput = & $cli @Arguments
    $exitCode = $LASTEXITCODE
    $lines = [string[]]$rawOutput
    $jsonStart = -1
    $jsonEnd = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $trimmed = $lines[$index].Trim()
        if (
            $jsonStart -lt 0 -and
            ($trimmed.StartsWith("{") -or $trimmed.StartsWith("["))
        ) {
            $jsonStart = $index
        }
        if (
            $jsonStart -ge 0 -and
            ($trimmed -eq "}" -or $trimmed -eq "]")
        ) {
            $jsonEnd = $index
        }
    }
    if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
        throw [System.IO.InvalidDataException]::new(
            "Command did not emit a complete JSON payload during $($state.stage)."
        )
    }
    $text = [string]::Join(
        [Environment]::NewLine,
        $lines[$jsonStart..$jsonEnd]
    )
    try {
        $parsed = $text | ConvertFrom-Json
    }
    catch {
        throw [System.IO.InvalidDataException]::new(
            "Command output was not valid JSON during $($state.stage)."
        )
    }
    if ($exitCode -ne 0 -and -not $AllowNonZero) {
        throw [InvalidOperationException]::new(
            "Evaluation command failed during $($state.stage)."
        )
    }
    return $parsed
}

function Set-Stage {
    param([string]$Name)
    $state.stage = $Name
    Save-PipelineState
    Write-Host ""
    Write-Host "[$Name]"
}

function Assert-Configured {
    $required = @(
        "MODEL_A_NAME", "MODEL_A_API_KEY", "MODEL_A_API_MODE",
        "MODEL_A_REASONING_EFFORT",
        "MODEL_B_NAME", "MODEL_B_API_KEY", "MODEL_B_API_MODE",
        "MODEL_B_REASONING_EFFORT",
        "WEAK_MODEL_NAME", "WEAK_MODEL_API_KEY",
        "WEAK_MODEL_API_MODE", "WEAK_MODEL_REASONING_EFFORT",
        "JUDGE_MODEL_NAME", "JUDGE_MODEL_API_KEY",
        "JUDGE_MODEL_API_MODE", "JUDGE_MODEL_REASONING_EFFORT"
    )
    $missing = @(
        foreach ($name in $required) {
            if ([string]::IsNullOrWhiteSpace(
                [Environment]::GetEnvironmentVariable($name, "Process")
            )) {
                $name
            }
        }
    )
    if ($missing.Count -gt 0) {
        throw [InvalidOperationException]::new(
            "Required process configuration is missing. Run configure_models.ps1 first."
        )
    }
}

function Get-EvaluationModelFreeze {
    if (-not (
        Test-Path -LiteralPath $evaluationModelFreezePath -PathType Leaf
    )) {
        return $null
    }
    try {
        $freeze = Get-Content -Raw -LiteralPath $evaluationModelFreezePath |
            ConvertFrom-Json
    }
    catch {
        throw [System.IO.InvalidDataException]::new(
            "The evaluation-model freeze artifact is not valid JSON."
        )
    }
    if (
        [string]$freeze.status -ne "frozen" -or
        $freeze.candidate_confirmed -isnot [bool] -or
        $freeze.candidate_confirmed -ne $true -or
        [string]::IsNullOrWhiteSpace([string]$freeze.version)
    ) {
        throw [System.IO.InvalidDataException]::new(
            "The evaluation-model freeze artifact is not candidate-confirmed."
        )
    }
    return $freeze
}

function Get-ExecutionAuthorization {
    param([string]$FreezeVersion)
    if (-not (
        Test-Path -LiteralPath $executionAuthorizationPath -PathType Leaf
    )) {
        return $null
    }
    try {
        $authorization = Get-Content `
            -Raw `
            -LiteralPath $executionAuthorizationPath | ConvertFrom-Json
    }
    catch {
        throw [System.IO.InvalidDataException]::new(
            "The execution authorization artifact is not valid JSON."
        )
    }
    if (
        [string]$authorization.status -ne "authorized" -or
        $authorization.candidate_confirmed -isnot [bool] -or
        $authorization.candidate_confirmed -ne $true -or
        [string]::IsNullOrWhiteSpace([string]$authorization.version) -or
        [string]$authorization.evaluation_model_freeze_version -ne $FreezeVersion
    ) {
        throw [System.IO.InvalidDataException]::new(
            "The execution authorization is not candidate-confirmed or does " +
            "not match the evaluation-model freeze."
        )
    }
    $maxConsecutive = [int]$authorization.max_consecutive_runtime_errors
    $maxTarget = [int]$authorization.max_target_requests_per_run
    $maxJudge = [int]$authorization.max_judge_requests_per_run
    if (
        $maxConsecutive -lt 1 -or $maxConsecutive -gt 3 -or
        $maxTarget -lt 1 -or $maxTarget -gt 60 -or
        $maxJudge -lt 1 -or $maxJudge -gt 120
    ) {
        throw [System.IO.InvalidDataException]::new(
            "Execution safety limits are missing or outside the allowed range."
        )
    }
    return $authorization
}

function Get-RunSafetyArguments {
    return @(
        "--max-consecutive-runtime-errors",
        [string]$state.execution_authorization.max_consecutive_runtime_errors,
        "--max-target-requests",
        [string]$state.execution_authorization.max_target_requests_per_run,
        "--max-judge-requests",
        [string]$state.execution_authorization.max_judge_requests_per_run
    )
}

function Consume-ExecutionAuthorization {
    param(
        [object]$Authorization,
        [string]$FreezeVersion
    )
    $authorizationVersion = [string]$Authorization.version
    if ($authorizationVersion -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$') {
        throw [System.IO.InvalidDataException]::new(
            "Execution authorization version contains unsafe characters."
        )
    }
    $receiptPath = Join-Path `
        $authorizationReceiptDirectory `
        "authorization_$authorizationVersion.json"
    $receipt = [ordered]@{
        authorization_version = $authorizationVersion
        pipeline_id = $pipelineTimestamp
        consumed_at = [DateTime]::UtcNow.ToString("o")
        evaluation_model_freeze_version = $FreezeVersion
        max_consecutive_runtime_errors = (
            [int]$Authorization.max_consecutive_runtime_errors
        )
        max_target_requests_per_run = (
            [int]$Authorization.max_target_requests_per_run
        )
        max_judge_requests_per_run = (
            [int]$Authorization.max_judge_requests_per_run
        )
    }
    $json = $receipt | ConvertTo-Json -Depth 5
    try {
        $stream = [IO.File]::Open(
            $receiptPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $writer = [IO.StreamWriter]::new(
                $stream,
                [Text.UTF8Encoding]::new($false)
            )
            $writer.Write($json)
            $writer.Flush()
        }
        finally {
            if ($null -ne $writer) {
                $writer.Dispose()
            }
            else {
                $stream.Dispose()
            }
        }
    }
    catch [System.IO.IOException] {
        throw [InvalidOperationException]::new(
            "This execution authorization was already consumed. Inspect the " +
            "previous pipeline before creating a new authorization."
        )
    }
    return $receiptPath
}

function Invoke-Probe {
    param(
        [string]$Key,
        [string]$Config,
        [string]$Alias,
        [switch]$SemanticJudge
    )
    $arguments = @(
        "probe", "--config", $Config, "--model-alias", $Alias
    )
    if ($SemanticJudge) {
        $arguments += "--semantic-judge"
    }
    $result = Invoke-EvalJson -Arguments $arguments -AllowNonZero
    $state.probes[$Key] = $result
    Save-PipelineState
    return [bool]$result.success
}

function Invoke-LiveRun {
    param(
        [string]$Key,
        [string]$Config
    )
    $runArguments = @(
        "run", "--config", $Config, "--mode", "live", "--allow-holdout"
    )
    $runArguments += Get-RunSafetyArguments
    $manifest = Invoke-EvalJson -Arguments $runArguments
    $state.runs[$Key] = $manifest.run_id
    Save-PipelineState
    $status = Invoke-EvalJson -Arguments @(
        "status", "--config", $Config, "--run-id", $manifest.run_id
    )
    if ([int]$status.summary.runtime_error_count -gt 0) {
        throw [InvalidOperationException]::new(
            "Runtime errors were recorded in $Key; inspect its run artifact."
        )
    }
    return $manifest.run_id
}

function Verify-Run {
    param(
        [string]$Key,
        [string]$Config,
        [string]$RunId
    )
    $verification = Invoke-EvalJson -Arguments @(
        "verify", "--config", $Config, "--run-id", $RunId
    )
    $state.verification[$Key] = $verification.valid
    Save-PipelineState
    if (-not $verification.valid) {
        throw [InvalidOperationException]::new(
            "Artifact verification failed: $Key"
        )
    }
}

Save-PipelineState

try {
    Set-Stage "preflight"
    Assert-Configured
    Invoke-EvalJson -Arguments @(
        "validate",
        "--config", "configs\run_model_a_prompt_v1.yaml",
        "--frozen"
    ) | Out-Null

    Set-Stage "evaluation_model_gate"
    $evaluationModelFreeze = Get-EvaluationModelFreeze
    if ($null -eq $evaluationModelFreeze) {
        $state.status = "awaiting_evaluation_model_design"
        $state.finished_at = [DateTime]::UtcNow.ToString("o")
        $state.next_action = (
            "Freeze the candidate-approved evaluation design before any " +
            "online provider call."
        )
        Save-PipelineState
        Write-Host ""
        Write-Host (
            "Online calls are paused at the candidate evaluation-model gate."
        )
        Write-Host "Formal runs are paused at the candidate evaluation-model gate."
        Write-Host "Pipeline state: $pipelinePath"
        return
    }
    $state.evaluation_model_freeze.validated = $true
    $state.evaluation_model_freeze.version = (
        [string]$evaluationModelFreeze.version
    )
    Save-PipelineState

    Set-Stage "staged_execution_plan_gate"
    $state.status = "awaiting_staged_pipeline_rewrite"
    $state.finished_at = [DateTime]::UtcNow.ToString("o")
    $state.next_action = (
        "Implement and test the approved staged canary/development/holdout " +
        "runner before creating any execution authorization."
    )
    Save-PipelineState
    Write-Host ""
    Write-Host "No online call was made."
    Write-Host "The withdrawn full matrix remains disabled."
    Write-Host "Pipeline state: $pipelinePath"
    return

    Set-Stage "execution_budget_gate"
    $executionAuthorization = Get-ExecutionAuthorization (
        [string]$evaluationModelFreeze.version
    )
    if ($null -eq $executionAuthorization) {
        $state.status = "awaiting_execution_authorization"
        $state.finished_at = [DateTime]::UtcNow.ToString("o")
        $state.next_action = (
            "Review the canary/full-run call plan and safety limits, then " +
            "create a candidate-confirmed execution authorization."
        )
        Save-PipelineState
        Write-Host ""
        Write-Host "No online call was made."
        Write-Host "Execution is paused at the explicit budget gate."
        Write-Host "Pipeline state: $pipelinePath"
        return
    }
    $state.execution_authorization.validated = $true
    $state.execution_authorization.version = (
        [string]$executionAuthorization.version
    )
    $state.execution_authorization.max_consecutive_runtime_errors = (
        [int]$executionAuthorization.max_consecutive_runtime_errors
    )
    $state.execution_authorization.max_target_requests_per_run = (
        [int]$executionAuthorization.max_target_requests_per_run
    )
    $state.execution_authorization.max_judge_requests_per_run = (
        [int]$executionAuthorization.max_judge_requests_per_run
    )
    $authorizationReceipt = Consume-ExecutionAuthorization `
        $executionAuthorization `
        ([string]$evaluationModelFreeze.version)
    $state.execution_authorization.receipt = (
        Resolve-Path -Relative -LiteralPath $authorizationReceipt
    )
    Save-PipelineState

    Set-Stage "provider_probes"
    $probePlan = @(
        @{
            Key = "model_a"
            Config = "configs\run_model_a_prompt_v1.yaml"
            Alias = "model_a"
            SemanticJudge = $false
        },
        @{
            Key = "model_b"
            Config = "configs\run_model_b_prompt_v1.yaml"
            Alias = "model_b"
            SemanticJudge = $false
        },
        @{
            Key = "weak_model"
            Config = "configs\run_weak_prompt_v2.yaml"
            Alias = "weak_model"
            SemanticJudge = $false
        },
        @{
            Key = "judge"
            Config = "configs\run_model_a_prompt_v1.yaml"
            Alias = "judge"
            SemanticJudge = $true
        }
    )
    $failedProbes = @()
    foreach ($probeSpec in $probePlan) {
        $succeeded = Invoke-Probe `
            $probeSpec.Key `
            $probeSpec.Config `
            $probeSpec.Alias `
            -SemanticJudge:$probeSpec.SemanticJudge
        if (-not $succeeded) {
            $failedProbes += $probeSpec.Key
        }
    }
    $state.failed_probes = $failedProbes
    Save-PipelineState
    if ($failedProbes.Count -gt 0) {
        foreach ($failedProbe in $failedProbes) {
            $diagnostic = $state.probes[$failedProbe]
            Write-Host (
                "$failedProbe failed: " +
                "$($diagnostic.error_type) / $($diagnostic.error)"
            ) -ForegroundColor Yellow
        }
        throw [InvalidOperationException]::new(
            "One or more provider probes failed."
        )
    }

    Set-Stage "live_model_a_prompt_v1"
    $runA = Invoke-LiveRun "model_a_prompt_v1" "configs\run_model_a_prompt_v1.yaml"

    Set-Stage "live_model_b_prompt_v1"
    $runB = Invoke-LiveRun "model_b_prompt_v1" "configs\run_model_b_prompt_v1.yaml"

    Set-Stage "live_weak_model_prompt_v2"
    $runWeak = Invoke-LiveRun "weak_model_prompt_v2" "configs\run_weak_prompt_v2.yaml"

    Set-Stage "replay_model_a_with_judge"
    $replayArguments = @(
        "run",
        "--config", "configs\run_model_a_prompt_v1.yaml",
        "--mode", "replay",
        "--source-run", $runA,
        "--allow-holdout"
    )
    $replayArguments += Get-RunSafetyArguments
    $replayA = Invoke-EvalJson -Arguments $replayArguments
    $state.runs["model_a_replay"] = $replayA.run_id
    Save-PipelineState

    Set-Stage "deterministic_only_model_a"
    $deterministicArguments = @(
        "run",
        "--config", "configs\run_model_a_prompt_v1.yaml",
        "--mode", "deterministic-only",
        "--source-run", $runA,
        "--allow-holdout"
    )
    $deterministicArguments += Get-RunSafetyArguments
    $deterministicA = Invoke-EvalJson -Arguments $deterministicArguments
    $state.runs["model_a_deterministic_only"] = $deterministicA.run_id
    Save-PipelineState

    Set-Stage "judge_stability_replay"
    $stabilityArguments = @(
        "run",
        "--config", "configs\judge_stability_model_a.yaml",
        "--mode", "replay",
        "--source-run", $runA,
        "--allow-holdout"
    )
    foreach ($caseId in @(
        "IG-002", "IG-006", "GQ-002", "GQ-006",
        "MT-002", "MT-004", "ST-003", "ST-005"
    )) {
        $stabilityArguments += @("--case-id", $caseId)
    }
    $stabilityArguments += Get-RunSafetyArguments
    $stabilityA = Invoke-EvalJson -Arguments $stabilityArguments
    $state.runs["judge_stability_model_a"] = $stabilityA.run_id
    Save-PipelineState

    Set-Stage "comparisons"
    $comparisonAB = Invoke-EvalJson -Arguments @(
        "compare",
        "--config", "configs\run_model_a_prompt_v1.yaml",
        "--baseline", $runA,
        "--candidate", $runB,
        "--output", "artifacts\real_compare_model_a_vs_b.json"
    )
    $state.comparisons["model_a_vs_b"] = $comparisonAB.comparison
    $comparisonWeak = Invoke-EvalJson -Arguments @(
        "compare",
        "--config", "configs\run_model_a_prompt_v1.yaml",
        "--baseline", $runA,
        "--candidate", $runWeak,
        "--output", "artifacts\real_compare_model_a_vs_weak_prompt_v2.json"
    )
    $state.comparisons["model_a_vs_weak_prompt_v2"] = $comparisonWeak.comparison
    Save-PipelineState

    Set-Stage "artifact_verification"
    Verify-Run "model_a_prompt_v1" "configs\run_model_a_prompt_v1.yaml" $runA
    Verify-Run "model_b_prompt_v1" "configs\run_model_b_prompt_v1.yaml" $runB
    Verify-Run "weak_model_prompt_v2" "configs\run_weak_prompt_v2.yaml" $runWeak
    Verify-Run "model_a_replay" "configs\run_model_a_prompt_v1.yaml" $replayA.run_id
    Verify-Run "model_a_deterministic_only" "configs\run_model_a_prompt_v1.yaml" $deterministicA.run_id
    Verify-Run "judge_stability_model_a" "configs\judge_stability_model_a.yaml" $stabilityA.run_id

    $state.status = "awaiting_candidate_holdout_review"
    $state.stage = "candidate_holdout_review"
    $state.finished_at = [DateTime]::UtcNow.ToString("o")
    $state.next_action = (
        "Open Streamlit, select run_model_a_prompt_v1.yaml, and complete all 8 " +
        "holdout reviews for the Model A run. " +
        "Do not inspect holdout reference fields before submitting."
    )
    Save-PipelineState
    Write-Host ""
    Write-Host "Automated pipeline completed."
    Write-Host "Next human gate: 8 blind holdout reviews for run $runA"
    Write-Host "Pipeline state: $pipelinePath"
}
catch {
    $state.status = "failed"
    $state.finished_at = [DateTime]::UtcNow.ToString("o")
    $state.error_type = $_.Exception.GetType().Name
    $state.next_action = if ($state.failed_probes.Count -gt 0) {
        "Edit the saved model profile if needed, then rerun the provider probes."
    }
    else {
        "Inspect the retained run artifacts, then rerun with the saved profile."
    }
    Save-PipelineState
    Write-Host "Pipeline stopped during $($state.stage). Inspect $pipelinePath." `
        -ForegroundColor Red
    exit 2
}
