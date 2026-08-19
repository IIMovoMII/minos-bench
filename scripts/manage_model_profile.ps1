[CmdletBinding()]
param(
    [switch]$Initialize,
    [switch]$Show,
    [switch]$TestHelpersOnly
)

$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "ModelProfile.psm1"
Import-Module $modulePath -Force

function Read-TextWithDefault {
    param(
        [string]$Prompt,
        [string]$Default
    )
    $suffix = if ([string]::IsNullOrWhiteSpace($Default)) {
        ""
    }
    else {
        " [$Default]"
    }
    $value = (Read-Host "$Prompt$suffix").Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

function Read-RequiredText {
    param([string]$Prompt)
    while ($true) {
        $value = (Read-Host $Prompt).Trim()
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
        Write-Warning "The value cannot be blank."
    }
}

function Read-RequiredSecureValue {
    param([string]$Prompt)
    while ($true) {
        $secureValue = Read-Host $Prompt -AsSecureString
        try {
            $null = Protect-LlmEvalSecureValue $secureValue
            return $secureValue
        }
        catch {
            Write-Warning "The value cannot be blank."
            $secureValue.Dispose()
        }
    }
}

function Read-OptionalSecureValue {
    param([string]$Prompt)
    return Read-Host $Prompt -AsSecureString
}

if ($TestHelpersOnly) {
    return
}

function Show-SafeProfile {
    param($Profile)
    Write-Host ""
    Write-Host "Saved local model profile (secrets are never displayed):"
    Get-LlmEvalSafeProfileSummary $Profile | Format-Table -AutoSize
    Write-Host "Profile path: $(Get-LlmEvalProfilePath)"
}

function New-InteractiveProfile {
    $records = [ordered]@{}
    Write-Host ""
    Write-Host "Create a persistent local model profile."
    Write-Host "API keys and full Base URLs are encrypted with Windows DPAPI."
    Write-Host "Encryption is tied to this Windows user on this machine."
    Write-Host "Actual model IDs have no defaults and must be entered explicitly."
    Write-Host ""
    foreach ($definition in Get-LlmEvalSlotDefinitions) {
        Write-Host "[$($definition.Label)]"
        $modelId = Read-RequiredText "Actual model ID"
        $adapter = Read-TextWithDefault `
            "LiteLLM provider adapter" `
            "openai"
        $apiMode = Read-TextWithDefault `
            "API endpoint mode" `
            "responses"
        $reasoningEffort = Read-TextWithDefault `
            "Reasoning effort" `
            "max"
        $baseUrl = Read-OptionalSecureValue `
            "Base URL (hidden; blank for provider default)"
        $apiKey = Read-RequiredSecureValue "API key (hidden)"
        try {
            $records[$definition.Key] = New-LlmEvalSlotRecord `
                -Prefix $definition.Prefix `
                -Label $definition.Label `
                -Adapter $adapter `
                -ApiMode $apiMode `
                -ModelId $modelId `
                -ReasoningEffort $reasoningEffort `
                -ApiKey $apiKey `
                -BaseUrl $baseUrl
        }
        finally {
            $apiKey.Dispose()
            $baseUrl.Dispose()
        }
        Write-Host ""
    }
    $profile = New-LlmEvalProfile -SlotRecords $records
    $null = Save-LlmEvalProfile $profile
    Write-Host "Persistent profile saved."
    return Get-LlmEvalProfile
}

function Select-SlotDefinition {
    $definitions = @(Get-LlmEvalSlotDefinitions)
    Write-Host ""
    for ($index = 0; $index -lt $definitions.Count; $index++) {
        Write-Host "$($index + 1). $($definitions[$index].Label)"
    }
    $choice = (Read-Host "Select a slot [1-$($definitions.Count)]").Trim()
    $number = 0
    if (
        -not [int]::TryParse($choice, [ref]$number) -or
        $number -lt 1 -or
        $number -gt $definitions.Count
    ) {
        Write-Warning "Invalid slot selection."
        return $null
    }
    return $definitions[$number - 1]
}

function Edit-ProfileField {
    param($Profile)
    $definition = Select-SlotDefinition
    if ($null -eq $definition) {
        return $Profile
    }
    $slot = Get-LlmEvalSlot $Profile $definition.Key
    Write-Host ""
    Write-Host "Edit $($definition.Label):"
    Write-Host "1. Actual model ID"
    Write-Host "2. LiteLLM provider adapter"
    Write-Host "3. API endpoint mode (/responses only)"
    Write-Host "4. Reasoning effort"
    Write-Host "5. Base URL"
    Write-Host "6. API key"
    Write-Host "7. Clear Base URL (use provider default)"
    $field = (Read-Host "Select a field [1-7]").Trim()
    switch ($field) {
        "1" {
            $slot.model_id = Read-TextWithDefault `
                "Actual model ID" `
                ([string]$slot.model_id)
        }
        "2" {
            $slot.adapter = Read-TextWithDefault `
                "LiteLLM provider adapter" `
                ([string]$slot.adapter)
        }
        "3" {
            $currentApiMode = if (
                $null -eq $slot.PSObject.Properties["api_mode"]
            ) {
                "responses"
            }
            else {
                [string]$slot.api_mode
            }
            $candidate = Read-TextWithDefault `
                "API endpoint mode" `
                $currentApiMode
            try {
                $normalized = Normalize-LlmEvalApiMode $candidate
            }
            catch {
                Write-Warning (
                    "Only /responses is supported; the saved value is unchanged."
                )
                return $Profile
            }
            if ($null -eq $slot.PSObject.Properties["api_mode"]) {
                $slot | Add-Member -NotePropertyName "api_mode" `
                    -NotePropertyValue $normalized
            }
            else {
                $slot.api_mode = $normalized
            }
        }
        "4" {
            $slot.reasoning_effort = Read-TextWithDefault `
                "Reasoning effort" `
                ([string]$slot.reasoning_effort)
        }
        "5" {
            $value = Read-OptionalSecureValue `
                "New Base URL (hidden; blank cancels)"
            try {
                Assert-LlmEvalBaseUrlPrefix $value
                $protected = Protect-LlmEvalSecureValue $value -AllowEmpty
                if (-not [string]::IsNullOrWhiteSpace($protected)) {
                    $slot.base_url_protected = $protected
                }
                else {
                    Write-Host "Base URL unchanged."
                    return $Profile
                }
            }
            finally {
                $value.Dispose()
            }
        }
        "6" {
            $value = Read-Host "New API key (hidden; blank cancels)" -AsSecureString
            try {
                try {
                    $slot.api_key_protected = Protect-LlmEvalSecureValue $value
                }
                catch {
                    Write-Host "API key unchanged."
                    return $Profile
                }
            }
            finally {
                $value.Dispose()
            }
        }
        "7" {
            $confirmation = (Read-Host "Type CLEAR to remove the saved Base URL").Trim()
            if ($confirmation -ne "CLEAR") {
                Write-Host "Base URL unchanged."
                return $Profile
            }
            $slot.base_url_protected = ""
        }
        default {
            Write-Warning "Invalid field selection."
            return $Profile
        }
    }
    $null = Save-LlmEvalProfile $Profile
    Write-Host "Saved."
    return Get-LlmEvalProfile
}

function Open-ProfileWithRecovery {
    if (-not (Test-LlmEvalProfileExists)) {
        return (New-InteractiveProfile)
    }
    try {
        return (Get-LlmEvalProfile)
    }
    catch {
        Write-Warning (
            "The saved profile cannot be loaded. No protected value was " +
            "displayed or changed."
        )
    }

    while ($true) {
        Write-Host ""
        Write-Host "1. Restore the previous saved version"
        Write-Host "2. Replace the complete profile"
        Write-Host "3. Delete the unreadable profile and backup"
        Write-Host "4. Exit"
        $action = (Read-Host "Choose recovery action [1-4]").Trim()
        switch ($action) {
            "1" {
                try {
                    $profile = Restore-LlmEvalProfileBackup
                    Write-Host "Previous profile restored."
                    return $profile
                }
                catch {
                    Write-Warning "The previous saved version is unavailable."
                }
            }
            "2" {
                $confirmation = (Read-Host "Type REPLACE to continue").Trim()
                if ($confirmation -eq "REPLACE") {
                    return (New-InteractiveProfile)
                }
            }
            "3" {
                $confirmation = (
                    Read-Host "Type DELETE to remove profile and backup"
                ).Trim()
                if ($confirmation -eq "DELETE") {
                    Remove-LlmEvalProfile
                    Write-Host "Persistent profile removed."
                    return $null
                }
            }
            "4" {
                return $null
            }
            default {
                Write-Warning "Invalid selection."
            }
        }
    }
}

if ($Initialize) {
    if (Test-LlmEvalProfileExists) {
        Show-SafeProfile (Get-LlmEvalProfile)
        return
    }
    $null = New-InteractiveProfile
    return
}

if ($Show) {
    if (-not (Test-LlmEvalProfileExists)) {
        Write-Host "No persistent model profile exists."
        throw "No persistent model profile exists."
    }
    Show-SafeProfile (Get-LlmEvalProfile)
    return
}

$profile = Open-ProfileWithRecovery
if ($null -eq $profile) {
    return
}

while ($true) {
    Show-SafeProfile $profile
    Write-Host ""
    Write-Host "1. Edit one field"
    Write-Host "2. Replace the complete profile"
    Write-Host "3. Restore the previous saved version"
    Write-Host "4. Delete the persistent profile"
    Write-Host "5. Exit"
    $action = (Read-Host "Choose [1-5]").Trim()
    switch ($action) {
        "1" {
            $profile = Edit-ProfileField $profile
        }
        "2" {
            $confirmation = (Read-Host "Type REPLACE to continue").Trim()
            if ($confirmation -eq "REPLACE") {
                $profile = New-InteractiveProfile
            }
        }
        "3" {
            $confirmation = (Read-Host "Type RESTORE to continue").Trim()
            if ($confirmation -eq "RESTORE") {
                $profile = Restore-LlmEvalProfileBackup
                Write-Host "Previous profile restored."
            }
        }
        "4" {
            $confirmation = (Read-Host "Type DELETE to remove profile and backup").Trim()
            if ($confirmation -eq "DELETE") {
                Remove-LlmEvalProfile
                Write-Host "Persistent profile removed."
                return
            }
        }
        "5" {
            return
        }
        default {
            Write-Warning "Invalid selection."
        }
    }
}
