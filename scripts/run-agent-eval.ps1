param(
    [Parameter(Mandatory = $true)][string]$AgentCommand,
    [Parameter(Mandatory = $true)][string]$Scenario,
    [Parameter(Mandatory = $true)][string]$Schema,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$ReasoningEffort,
    [Parameter(Mandatory = $true)][ValidateSet("baseline", "skilled", "blind", "review")][string]$Mode,
    [string]$Skill,
    [string]$InputRun
)
$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$arguments = @(
    "-m", "selfworkflow.agent_eval",
    "--agent-command", (Resolve-Path -LiteralPath $AgentCommand).Path,
    "--scenario", (Resolve-Path -LiteralPath $Scenario).Path,
    "--schema", (Resolve-Path -LiteralPath $Schema).Path,
    "--output-root", [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputRoot)),
    "--timeout-seconds", $TimeoutSeconds,
    "--model", $Model,
    "--reasoning-effort", $ReasoningEffort,
    "--mode", $Mode
)
if ($Skill) { $arguments += @("--skill", (Resolve-Path -LiteralPath $Skill).Path) }
if ($InputRun) { $arguments += @("--input-run", (Resolve-Path -LiteralPath $InputRun).Path) }
& $python @arguments
exit $LASTEXITCODE
