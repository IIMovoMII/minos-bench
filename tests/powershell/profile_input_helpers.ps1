[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ManagerPath
)

$ErrorActionPreference = "Stop"
. $ManagerPath -TestHelpersOnly

function Assert-Equal {
    param(
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)][string]$Message
    )
    if ($Actual -ne $Expected) {
        throw $Message
    }
}

$script:FakeHostValues = [Collections.Queue]::new()
function Read-Host {
    param(
        [string]$Prompt,
        [switch]$AsSecureString
    )
    if ($script:FakeHostValues.Count -eq 0) {
        throw "The fake Read-Host queue is empty."
    }
    $value = [string]$script:FakeHostValues.Dequeue()
    if ($AsSecureString) {
        return ConvertTo-SecureString -String $value -AsPlainText -Force
    }
    return $value
}

$script:FakeHostValues.Enqueue("")
Assert-Equal `
    (Read-TextWithDefault "Adapter" "openai") `
    "openai" `
    "A blank optional field did not resolve to its default."

$script:FakeHostValues.Enqueue("  custom-model  ")
Assert-Equal `
    (Read-RequiredText "Actual model ID") `
    "custom-model" `
    "A required model ID was not trimmed and returned."

$script:FakeHostValues.Enqueue("")
$script:FakeHostValues.Enqueue("model-after-retry")
Assert-Equal `
    (Read-RequiredText "Actual model ID") `
    "model-after-retry" `
    "A blank model ID did not trigger a retry."

foreach ($definition in Get-LlmEvalSlotDefinitions) {
    if ($null -ne $definition.PSObject.Properties["DefaultModelId"]) {
        throw "A model slot still exposes a hard-coded default model ID."
    }
}

Write-Output "profile_input_helpers_ok"
