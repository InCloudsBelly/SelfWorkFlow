param(
    [Parameter(Mandatory = $true)][string]$Evidence,
    [Parameter(Mandatory = $true)][string]$Output
)
$ErrorActionPreference = "Stop"
$value = Get-Content -LiteralPath $Evidence -Raw -Encoding UTF8 | ConvertFrom-Json
$record = [ordered]@{
    schemaVersion = 1
    runId = $value.runId
    mode = $value.mode
    model = $value.model
    reasoningEffort = $value.reasoningEffort
    scenarioHash = $value.scenarioHash
    skillHash = $value.skillHash
    inputRunHash = $value.inputRunHash
    resultHash = $value.resultHash
}
$json = $record | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Output), $json + "`n", [System.Text.UTF8Encoding]::new($false))
