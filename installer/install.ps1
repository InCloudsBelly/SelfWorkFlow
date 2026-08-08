[CmdletBinding()]
param(
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

if ($Help) {
    @"
SelfWorkFlow transactional installer

Usage:
  install.ps1 doctor --agents-root <path> --codex-root <path> --state-root <path>
  install.ps1 install plan --artifact <path> --agents-root <path> --codex-root <path> --state-root <path> --version <version> --output <plan.json>
  install.ps1 install apply --plan <plan.json> --confirm-plan-hash <sha256>
  install.ps1 install verify --manifest <manifest.json>
  install.ps1 install rollback-plan --transaction <transaction.json> --output <plan.json>
  install.ps1 install rollback --plan <plan.json> --confirm-plan-hash <sha256>
"@
    exit 0
}

$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "SelfWorkFlow repository virtual environment is required."
}
& $Python -m selfworkflow.cli @RemainingArguments
exit $LASTEXITCODE
