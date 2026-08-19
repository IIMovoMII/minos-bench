[CmdletBinding()]
param(
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Resolve-ProjectUv {
    $installed = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $installed) {
        return $installed.Source
    }

    Write-Host "uv was not found. It can be installed inside this project."
    $answer = Read-Host "Install the local bootstrap now? Enter y to continue"
    if ($answer.Trim().ToLowerInvariant() -ne "y") {
        throw "uv is required. Startup was cancelled; see README for manual setup."
    }

    $bootstrapDirectory = Join-Path $projectRoot ".bootstrap"
    $bootstrapPython = Join-Path $bootstrapDirectory "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $bootstrapPython -PathType Leaf)) {
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $pyLauncher) {
            & $pyLauncher.Source -3 -m venv $bootstrapDirectory
        }
        elseif ($null -ne $python) {
            & $python.Source -m venv $bootstrapDirectory
        }
        else {
            throw "Python was not found. Install Python 3.11 through 3.13 first."
        }
        if ($LASTEXITCODE -ne 0) {
            throw "The project-local bootstrap environment could not be created."
        }
    }

    Write-Host "Installing the project-local uv bootstrap..."
    & $bootstrapPython -m pip install `
        --disable-pip-version-check `
        --quiet `
        "uv==0.11.19"
    if ($LASTEXITCODE -ne 0) {
        throw "uv installation failed."
    }
    $localUv = Join-Path $bootstrapDirectory "Scripts\uv.exe"
    if (-not (Test-Path -LiteralPath $localUv -PathType Leaf)) {
        throw "The uv executable was not found after installation."
    }
    return $localUv
}

foreach ($requiredFile in @("pyproject.toml", "uv.lock", "app.py")) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $requiredFile))) {
        throw "Required project file is missing: $requiredFile"
    }
}

$uvCommand = Resolve-ProjectUv
$environmentPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$environmentStreamlit = Join-Path $projectRoot ".venv\Scripts\streamlit.exe"
$lockHash = (Get-FileHash -LiteralPath (Join-Path $projectRoot "uv.lock") `
    -Algorithm SHA256).Hash
$lockMarker = Join-Path $projectRoot ".venv\.project3-uv-lock-sha256"
$savedHash = ""
if (Test-Path -LiteralPath $lockMarker -PathType Leaf) {
    $savedHash = [IO.File]::ReadAllText($lockMarker).Trim()
}
$needsSync = (
    -not $SkipDependencySync -and (
        -not (Test-Path -LiteralPath $environmentPython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $environmentStreamlit -PathType Leaf) -or
        $savedHash -ne $lockHash
    )
)
if ($needsSync) {
    Write-Host "Preparing the locked environment. First startup may take a few minutes..."
    & $uvCommand sync --frozen --no-editable --link-mode copy
    if ($LASTEXITCODE -ne 0) {
        throw "The locked dependency environment could not be prepared."
    }
    [IO.File]::WriteAllText(
        $lockMarker,
        $lockHash,
        [Text.UTF8Encoding]::new($false)
    )
}

$profileModule = Join-Path $PSScriptRoot "ModelProfile.psm1"
if (Test-Path -LiteralPath $profileModule -PathType Leaf) {
    Import-Module $profileModule -Force
    if (Test-LlmEvalProfileExists) {
        try {
            $profile = Get-LlmEvalProfile
            Import-LlmEvalProfileToProcess $profile
            Write-Host "Loaded the encrypted model profile stored outside the repository."
        }
        catch {
            Write-Warning (
                "The saved profile could not be loaded. Fix it on the model configuration page."
            )
        }
    }
    else {
        Write-Host "No saved profile was found. Complete setup in the workbench."
    }
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:DEEPEVAL_TELEMETRY_OPT_OUT = "YES"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

Write-Host "Opening the local evaluation workbench..."
& $uvCommand run --no-sync streamlit run app.py
if ($LASTEXITCODE -ne 0) {
    throw "The evaluation workbench exited with an error."
}
