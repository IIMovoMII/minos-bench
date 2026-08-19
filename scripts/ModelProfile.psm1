Set-StrictMode -Version Latest

$script:ProfileVersion = 1
$script:ProfileFileName = "default-profile.json"

function Get-LlmEvalSlotDefinitions {
    return @(
        [PSCustomObject]@{
            Key = "model_a"
            Prefix = "MODEL_A"
            Label = "Model A"
        },
        [PSCustomObject]@{
            Key = "model_b"
            Prefix = "MODEL_B"
            Label = "Model B"
        },
        [PSCustomObject]@{
            Key = "weak_model"
            Prefix = "WEAK_MODEL"
            Label = "Weaker model"
        },
        [PSCustomObject]@{
            Key = "judge"
            Prefix = "JUDGE_MODEL"
            Label = "Judge"
        }
    )
}

function Get-LlmEvalProfileDirectory {
    $override = [Environment]::GetEnvironmentVariable(
        "LLM_EVAL_PROFILE_DIR",
        "Process"
    )
    if (-not [string]::IsNullOrWhiteSpace($override)) {
        return [IO.Path]::GetFullPath($override)
    }
    $localAppData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        throw "Cannot resolve the current user's LocalAppData directory."
    }
    return Join-Path $localAppData "LLMEvalWorkbench\profiles"
}

function Get-LlmEvalProfilePath {
    return Join-Path (Get-LlmEvalProfileDirectory) $script:ProfileFileName
}

function Test-LlmEvalProfileExists {
    return Test-Path -LiteralPath (Get-LlmEvalProfilePath) -PathType Leaf
}

function ConvertTo-LlmEvalPlainText {
    param(
        [Parameter(Mandatory)]
        [Security.SecureString]$SecureValue
    )
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Test-LlmEvalSecureValueEmpty {
    param(
        [Parameter(Mandatory)]
        [Security.SecureString]$SecureValue
    )
    $plainValue = ConvertTo-LlmEvalPlainText $SecureValue
    try {
        return [string]::IsNullOrWhiteSpace($plainValue)
    }
    finally {
        $plainValue = $null
    }
}

function Assert-LlmEvalBaseUrlPrefix {
    param(
        [Parameter(Mandatory)]
        [Security.SecureString]$SecureValue
    )
    if (Test-LlmEvalSecureValueEmpty $SecureValue) {
        return
    }
    $plainValue = ConvertTo-LlmEvalPlainText $SecureValue
    try {
        $uri = $null
        if (
            -not [Uri]::TryCreate(
                $plainValue,
                [UriKind]::Absolute,
                [ref]$uri
            ) -or
            $uri.Scheme -notin @("http", "https")
        ) {
            throw "Base URL must be an absolute HTTP(S) URL."
        }
        $path = $uri.AbsolutePath.TrimEnd("/").ToLowerInvariant()
        if (
            $path.EndsWith("/responses") -or
            $path.EndsWith("/chat/completions")
        ) {
            throw (
                "Base URL must be the API prefix, normally ending in /v1. " +
                "Do not include /responses or /chat/completions."
            )
        }
    }
    finally {
        $plainValue = $null
    }
}

function Protect-LlmEvalSecureValue {
    param(
        [Parameter(Mandatory)]
        [Security.SecureString]$SecureValue,
        [switch]$AllowEmpty
    )
    if (Test-LlmEvalSecureValueEmpty $SecureValue) {
        if ($AllowEmpty) {
            return ""
        }
        throw "A required protected value was left blank."
    }
    # On Windows this uses DPAPI scoped to the current Windows user.
    return ConvertFrom-SecureString -SecureString $SecureValue
}

function Unprotect-LlmEvalSecureValue {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$ProtectedValue,
        [switch]$AllowEmpty
    )
    if ([string]::IsNullOrWhiteSpace($ProtectedValue)) {
        if ($AllowEmpty) {
            return (New-Object Security.SecureString)
        }
        throw "A required protected value is missing."
    }
    try {
        return ConvertTo-SecureString -String $ProtectedValue
    }
    catch {
        throw (
            "A saved credential cannot be decrypted by the current Windows " +
            "user. Edit or replace the local model profile."
        )
    }
}

function Assert-LlmEvalAdapter {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9_.-]+$') {
        throw "API adapter must be a LiteLLM provider prefix without '/' or spaces."
    }
}

function Normalize-LlmEvalApiMode {
    param([Parameter(Mandatory)][string]$Value)
    $normalized = $Value.Trim().TrimStart("/").ToLowerInvariant()
    if ($normalized -ne "responses") {
        throw (
            "API endpoint mode must be responses. Chat Completions is " +
            "disabled for this project."
        )
    }
    return $normalized
}

function Get-LlmEvalSlotApiMode {
    param([Parameter(Mandatory)]$Slot)
    if ($null -eq $Slot.PSObject.Properties["api_mode"]) {
        return "responses"
    }
    return Normalize-LlmEvalApiMode ([string]$Slot.api_mode)
}

function Assert-LlmEvalReasoningEffort {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9_.-]+$') {
        throw "Reasoning effort must be a single provider value such as max or high."
    }
}

function New-LlmEvalSlotRecord {
    param(
        [Parameter(Mandatory)][string]$Prefix,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$Adapter,
        [string]$ApiMode = "responses",
        [Parameter(Mandatory)][string]$ModelId,
        [Parameter(Mandatory)][string]$ReasoningEffort,
        [Parameter(Mandatory)][Security.SecureString]$ApiKey,
        [Parameter(Mandatory)][Security.SecureString]$BaseUrl
    )
    $adapterValue = $Adapter.Trim()
    $apiModeValue = Normalize-LlmEvalApiMode $ApiMode
    $modelIdValue = $ModelId.Trim()
    $reasoningValue = $ReasoningEffort.Trim()
    Assert-LlmEvalAdapter $adapterValue
    Assert-LlmEvalReasoningEffort $reasoningValue
    Assert-LlmEvalBaseUrlPrefix $BaseUrl
    if ([string]::IsNullOrWhiteSpace($modelIdValue)) {
        throw "Actual model ID cannot be blank."
    }
    return [PSCustomObject][ordered]@{
        prefix = $Prefix
        label = $Label
        adapter = $adapterValue
        api_mode = $apiModeValue
        model_id = $modelIdValue
        reasoning_effort = $reasoningValue
        base_url_protected = Protect-LlmEvalSecureValue $BaseUrl -AllowEmpty
        api_key_protected = Protect-LlmEvalSecureValue $ApiKey
    }
}

function New-LlmEvalProfile {
    param(
        [Parameter(Mandatory)]
        [Collections.IDictionary]$SlotRecords
    )
    $slots = [ordered]@{}
    foreach ($definition in Get-LlmEvalSlotDefinitions) {
        if (-not $SlotRecords.Contains($definition.Key)) {
            throw "Profile is missing slot $($definition.Key)."
        }
        $slots[$definition.Key] = $SlotRecords[$definition.Key]
    }
    $timestamp = [DateTime]::UtcNow.ToString("o")
    return [PSCustomObject][ordered]@{
        version = $script:ProfileVersion
        profile_name = "default"
        created_at = $timestamp
        updated_at = $timestamp
        protection = "windows_dpapi_current_user"
        slots = [PSCustomObject]$slots
    }
}

function Get-LlmEvalSlot {
    param(
        [Parameter(Mandatory)]$Profile,
        [Parameter(Mandatory)][string]$Key
    )
    $property = $Profile.slots.PSObject.Properties[$Key]
    if ($null -eq $property) {
        throw "Profile is missing slot $Key."
    }
    return $property.Value
}

function Assert-LlmEvalProfile {
    param([Parameter(Mandatory)]$Profile)
    if ([int]$Profile.version -ne $script:ProfileVersion) {
        throw "Unsupported local model profile version."
    }
    foreach ($definition in Get-LlmEvalSlotDefinitions) {
        $slot = Get-LlmEvalSlot $Profile $definition.Key
        if ($slot.prefix -ne $definition.Prefix) {
            throw "Profile slot prefix mismatch for $($definition.Key)."
        }
        Assert-LlmEvalAdapter ([string]$slot.adapter)
        $null = Get-LlmEvalSlotApiMode $slot
        Assert-LlmEvalReasoningEffort ([string]$slot.reasoning_effort)
        if ([string]::IsNullOrWhiteSpace([string]$slot.model_id)) {
            throw "Profile model ID is missing for $($definition.Key)."
        }
        if ([string]::IsNullOrWhiteSpace([string]$slot.api_key_protected)) {
            throw "Profile API key is missing for $($definition.Key)."
        }
    }
}

function Save-LlmEvalProfile {
    param([Parameter(Mandatory)]$Profile)
    Assert-LlmEvalProfile $Profile
    $Profile.updated_at = [DateTime]::UtcNow.ToString("o")
    $directory = Get-LlmEvalProfileDirectory
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $path = Get-LlmEvalProfilePath
    $temporaryPath = "$path.tmp"
    $backupPath = "$path.bak"
    $json = $Profile | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText(
        $temporaryPath,
        $json,
        [Text.UTF8Encoding]::new($false)
    )
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        [IO.File]::Replace($temporaryPath, $path, $backupPath, $true)
    }
    else {
        [IO.File]::Move($temporaryPath, $path)
    }
    return $path
}

function Get-LlmEvalProfile {
    $path = Get-LlmEvalProfilePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "No saved local model profile exists."
    }
    try {
        $profile = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    }
    catch {
        throw "The saved local model profile is not valid JSON."
    }
    Assert-LlmEvalProfile $profile
    return $profile
}

function Get-LlmEvalSafeProfileSummary {
    param([Parameter(Mandatory)]$Profile)
    Assert-LlmEvalProfile $Profile
    return @(
        foreach ($definition in Get-LlmEvalSlotDefinitions) {
            $slot = Get-LlmEvalSlot $Profile $definition.Key
            $apiMode = Get-LlmEvalSlotApiMode $slot
            [PSCustomObject]@{
                Slot = $definition.Label
                Adapter = [string]$slot.adapter
                ApiMode = "/$apiMode"
                ModelId = [string]$slot.model_id
                ReasoningEffort = [string]$slot.reasoning_effort
                BaseUrlConfigured = -not [string]::IsNullOrWhiteSpace(
                    [string]$slot.base_url_protected
                )
                ApiKeyConfigured = -not [string]::IsNullOrWhiteSpace(
                    [string]$slot.api_key_protected
                )
            }
        }
    )
}

function Join-LlmEvalAdapterAndModel {
    param(
        [Parameter(Mandatory)][string]$Adapter,
        [Parameter(Mandatory)][string]$ModelId
    )
    if ($ModelId.StartsWith(
        "$Adapter/",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        return $ModelId
    }
    return "$Adapter/$ModelId"
}

function Import-LlmEvalProfileToProcess {
    param([Parameter(Mandatory)]$Profile)
    Assert-LlmEvalProfile $Profile
    foreach ($definition in Get-LlmEvalSlotDefinitions) {
        $slot = Get-LlmEvalSlot $Profile $definition.Key
        $apiMode = Get-LlmEvalSlotApiMode $slot
        $apiKeySecure = Unprotect-LlmEvalSecureValue (
            [string]$slot.api_key_protected
        )
        $baseUrlSecure = Unprotect-LlmEvalSecureValue (
            [string]$slot.base_url_protected
        ) -AllowEmpty
        $apiKeyPlain = $null
        $baseUrlPlain = $null
        try {
            Assert-LlmEvalBaseUrlPrefix $baseUrlSecure
            $apiKeyPlain = ConvertTo-LlmEvalPlainText $apiKeySecure
            $baseUrlPlain = ConvertTo-LlmEvalPlainText $baseUrlSecure
            [Environment]::SetEnvironmentVariable(
                "$($definition.Prefix)_NAME",
                (Join-LlmEvalAdapterAndModel `
                    ([string]$slot.adapter) `
                    ([string]$slot.model_id)),
                "Process"
            )
            [Environment]::SetEnvironmentVariable(
                "$($definition.Prefix)_API_KEY",
                $apiKeyPlain,
                "Process"
            )
            [Environment]::SetEnvironmentVariable(
                "$($definition.Prefix)_BASE_URL",
                $baseUrlPlain,
                "Process"
            )
            [Environment]::SetEnvironmentVariable(
                "$($definition.Prefix)_API_MODE",
                $apiMode,
                "Process"
            )
            [Environment]::SetEnvironmentVariable(
                "$($definition.Prefix)_REASONING_EFFORT",
                [string]$slot.reasoning_effort,
                "Process"
            )
        }
        finally {
            $apiKeyPlain = $null
            $baseUrlPlain = $null
            if ($null -ne $apiKeySecure) {
                $apiKeySecure.Dispose()
            }
            if ($null -ne $baseUrlSecure) {
                $baseUrlSecure.Dispose()
            }
        }
    }
}

function Restore-LlmEvalProfileBackup {
    $path = Get-LlmEvalProfilePath
    $backupPath = "$path.bak"
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "No saved profile backup exists."
    }
    [IO.File]::Copy($backupPath, $path, $true)
    return Get-LlmEvalProfile
}

function Remove-LlmEvalProfile {
    $path = Get-LlmEvalProfilePath
    $backupPath = "$path.bak"
    foreach ($target in @($path, $backupPath)) {
        if (Test-Path -LiteralPath $target -PathType Leaf) {
            Remove-Item -LiteralPath $target
        }
    }
}

Export-ModuleMember -Function @(
    "Get-LlmEvalSlotDefinitions",
    "Get-LlmEvalProfileDirectory",
    "Get-LlmEvalProfilePath",
    "Test-LlmEvalProfileExists",
    "Protect-LlmEvalSecureValue",
    "Unprotect-LlmEvalSecureValue",
    "Assert-LlmEvalBaseUrlPrefix",
    "Normalize-LlmEvalApiMode",
    "New-LlmEvalSlotRecord",
    "New-LlmEvalProfile",
    "Get-LlmEvalSlot",
    "Save-LlmEvalProfile",
    "Get-LlmEvalProfile",
    "Get-LlmEvalSafeProfileSummary",
    "Import-LlmEvalProfileToProcess",
    "Restore-LlmEvalProfileBackup",
    "Remove-LlmEvalProfile"
)
