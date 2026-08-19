[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ModulePath,
    [Parameter(Mandatory)]
    [string]$TempDirectory
)

$ErrorActionPreference = "Stop"
$env:LLM_EVAL_PROFILE_DIR = $TempDirectory
Import-Module $ModulePath -Force

function Assert-True {
    param(
        [Parameter(Mandatory)]
        [bool]$Condition,
        [Parameter(Mandatory)]
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function New-TestSecureString {
    param([Parameter(Mandatory)][string]$Value)
    return ConvertTo-SecureString -String $Value -AsPlainText -Force
}

$fullEndpoint = New-TestSecureString "https://endpoint.invalid/v1/responses"
try {
    $fullEndpointRejected = $false
    try {
        Assert-LlmEvalBaseUrlPrefix $fullEndpoint
    }
    catch {
        $fullEndpointRejected = $true
    }
    Assert-True $fullEndpointRejected `
        "A full /responses endpoint was accepted as a Base URL prefix."
}
finally {
    $fullEndpoint.Dispose()
}

$records = [ordered]@{}
$index = 0
foreach ($definition in Get-LlmEvalSlotDefinitions) {
    $index += 1
    $apiKey = New-TestSecureString "unit-key-$index"
    $baseUrl = New-TestSecureString "https://slot-$index.example.invalid/v1"
    try {
        $records[$definition.Key] = New-LlmEvalSlotRecord `
            -Prefix $definition.Prefix `
            -Label $definition.Label `
            -Adapter "openai" `
            -ModelId "test-model-$index" `
            -ReasoningEffort "max" `
            -ApiKey $apiKey `
            -BaseUrl $baseUrl
    }
    finally {
        $apiKey.Dispose()
        $baseUrl.Dispose()
    }
}

try {
    $profile = New-LlmEvalProfile -SlotRecords $records
    $path = Save-LlmEvalProfile $profile
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) `
        "Profile file was not created."

    $rawProfile = [IO.File]::ReadAllText($path)
    Assert-True (-not $rawProfile.Contains("unit-key-")) `
        "A test API key was persisted as plaintext."
    Assert-True (-not $rawProfile.Contains("example.invalid")) `
        "A test Base URL was persisted as plaintext."

    $loaded = Get-LlmEvalProfile
    $summary = @(Get-LlmEvalSafeProfileSummary $loaded)
    Assert-True ($summary.Count -eq 4) "Safe summary is missing slots."
    Assert-True (
        @($summary | Where-Object { -not $_.ApiKeyConfigured }).Count -eq 0
    ) "Safe summary reported a missing API key."
    Assert-True (
        @($summary | Where-Object { -not $_.BaseUrlConfigured }).Count -eq 0
    ) "Safe summary reported a missing Base URL."
    Assert-True (
        @($summary | Where-Object { $_.ApiMode -ne "/responses" }).Count -eq 0
    ) "Safe summary reported the wrong API endpoint mode."

    Import-LlmEvalProfileToProcess $loaded
    Assert-True (
        $env:MODEL_A_NAME -eq "openai/test-model-1"
    ) "Model ID or adapter was not loaded."
    Assert-True (
        $env:MODEL_A_REASONING_EFFORT -eq "max"
    ) "Reasoning effort was not loaded."
    Assert-True (
        $env:MODEL_A_API_MODE -eq "responses"
    ) "Responses API endpoint mode was not loaded."
    Assert-True (
        $env:MODEL_A_API_KEY -eq "unit-key-1"
    ) "API key could not be decrypted in the current process."
    Assert-True (
        $env:MODEL_A_BASE_URL -eq "https://slot-1.example.invalid/v1"
    ) "Base URL could not be decrypted in the current process."

    $modelA = Get-LlmEvalSlot $loaded "model_a"
    $originalProtectedBaseUrl = $modelA.base_url_protected
    $legacyFullEndpoint = New-TestSecureString `
        "https://endpoint.invalid/v1/responses"
    try {
        $modelA.base_url_protected = Protect-LlmEvalSecureValue `
            $legacyFullEndpoint
        $legacyFullEndpointRejected = $false
        try {
            Import-LlmEvalProfileToProcess $loaded
        }
        catch {
            $legacyFullEndpointRejected = $true
        }
        Assert-True $legacyFullEndpointRejected `
            "A saved full /responses endpoint was imported as a Base URL prefix."
    }
    finally {
        $legacyFullEndpoint.Dispose()
        $modelA.base_url_protected = $originalProtectedBaseUrl
    }

    $modelA.model_id = "edited-model"
    $modelA.reasoning_effort = "high"
    $null = Save-LlmEvalProfile $loaded
    Assert-True (Test-Path -LiteralPath "$path.bak" -PathType Leaf) `
        "Previous profile backup was not created."

    $edited = Get-LlmEvalProfile
    $editedModelA = Get-LlmEvalSlot $edited "model_a"
    Assert-True (
        $editedModelA.model_id -eq "edited-model"
    ) "Edited model ID was not persisted."
    Assert-True (
        $editedModelA.reasoning_effort -eq "high"
    ) "Edited reasoning effort was not persisted."

    $restored = Restore-LlmEvalProfileBackup
    $restoredModelA = Get-LlmEvalSlot $restored "model_a"
    Assert-True (
        $restoredModelA.model_id -eq "test-model-1"
    ) "Profile backup could not be restored."
}
finally {
    Remove-LlmEvalProfile
}

Assert-True (-not (Test-LlmEvalProfileExists)) `
    "Profile was not deleted."
Assert-True (-not (Test-Path -LiteralPath "$path.bak")) `
    "Profile backup was not deleted."

Write-Output "profile_roundtrip_ok"
