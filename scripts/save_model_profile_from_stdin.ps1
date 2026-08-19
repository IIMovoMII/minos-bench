[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ModulePath
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

Import-Module $ModulePath -Force -DisableNameChecking

$rawPayload = $null
$payload = $null
$apiKeyPlain = $null
$baseUrlPlain = $null

try {
    $rawPayload = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($rawPayload)) {
        throw "No model configuration was submitted."
    }
    $payload = $rawPayload | ConvertFrom-Json
    if ($null -eq $payload.PSObject.Properties["slots"]) {
        throw "Model configuration is missing the slots object."
    }

    $existingProfile = $null
    if (Test-LlmEvalProfileExists) {
        $existingProfile = Get-LlmEvalProfile
    }

    $records = [ordered]@{}
    foreach ($definition in Get-LlmEvalSlotDefinitions) {
        $inputProperty = $payload.slots.PSObject.Properties[$definition.Key]
        if ($null -eq $inputProperty) {
            throw "Model configuration is missing slot $($definition.Key)."
        }
        $inputSlot = $inputProperty.Value
        $adapter = ([string]$inputSlot.adapter).Trim()
        $apiMode = Normalize-LlmEvalApiMode ([string]$inputSlot.api_mode)
        $modelId = ([string]$inputSlot.model_id).Trim()
        $reasoningEffort = ([string]$inputSlot.reasoning_effort).Trim()
        if ([string]::IsNullOrWhiteSpace($modelId)) {
            throw "Actual model ID cannot be blank."
        }
        if ([string]::IsNullOrWhiteSpace($reasoningEffort)) {
            $reasoningEffort = "default"
        }

        $existingSlot = $null
        if ($null -ne $existingProfile) {
            $existingSlot = Get-LlmEvalSlot $existingProfile $definition.Key
        }

        $apiKeyPlain = [string]$inputSlot.api_key
        if (-not [string]::IsNullOrWhiteSpace($apiKeyPlain)) {
            $apiKeySecure = ConvertTo-SecureString `
                -String $apiKeyPlain `
                -AsPlainText `
                -Force
            try {
                $apiKeyProtected = Protect-LlmEvalSecureValue $apiKeySecure
            }
            finally {
                $apiKeySecure.Dispose()
            }
        }
        elseif ($null -ne $existingSlot) {
            $apiKeyProtected = [string]$existingSlot.api_key_protected
        }
        else {
            throw "API key is required when a slot is configured for the first time."
        }

        $clearBaseUrl = [bool]$inputSlot.clear_base_url
        $baseUrlPlain = [string]$inputSlot.base_url
        if ($clearBaseUrl) {
            $baseUrlProtected = ""
        }
        elseif (-not [string]::IsNullOrWhiteSpace($baseUrlPlain)) {
            $baseUrlSecure = ConvertTo-SecureString `
                -String $baseUrlPlain `
                -AsPlainText `
                -Force
            try {
                Assert-LlmEvalBaseUrlPrefix $baseUrlSecure
                $baseUrlProtected = Protect-LlmEvalSecureValue `
                    $baseUrlSecure `
                    -AllowEmpty
            }
            finally {
                $baseUrlSecure.Dispose()
            }
        }
        elseif ($null -ne $existingSlot) {
            $baseUrlProtected = [string]$existingSlot.base_url_protected
        }
        else {
            $baseUrlProtected = ""
        }

        $records[$definition.Key] = [PSCustomObject][ordered]@{
            prefix = $definition.Prefix
            label = $definition.Label
            adapter = $adapter
            api_mode = $apiMode
            model_id = $modelId
            reasoning_effort = $reasoningEffort
            base_url_protected = $baseUrlProtected
            api_key_protected = $apiKeyProtected
        }
        $apiKeyPlain = $null
        $baseUrlPlain = $null
    }

    $profile = New-LlmEvalProfile -SlotRecords $records
    if ($null -ne $existingProfile) {
        $profile.created_at = $existingProfile.created_at
    }
    $null = Save-LlmEvalProfile $profile
    $summary = @(Get-LlmEvalSafeProfileSummary $profile)
    [PSCustomObject][ordered]@{
        saved = $true
        protection = "windows_dpapi_current_user"
        safe_summary = $summary
    } | ConvertTo-Json -Depth 8 -Compress
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    $apiKeyPlain = $null
    $baseUrlPlain = $null
    $rawPayload = $null
    $payload = $null
}
