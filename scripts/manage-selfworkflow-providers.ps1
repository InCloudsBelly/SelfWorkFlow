[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ProviderArguments,
    [string]$LogRoot = (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\logs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PythonExecutable = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$stamp = [DateTimeOffset]::Now.ToString("yyyyMMdd-HHmmss-fff")
$LogDirectory = Join-Path $LogRoot ("provider-" + $stamp)
$LogFile = Join-Path $LogDirectory "provider.log"
$exitCode = 10

try {
    [IO.Directory]::CreateDirectory($LogDirectory) | Out-Null
    [IO.File]::WriteAllText(
        $LogFile,
        (("{0} provider-manager-start" -f [DateTimeOffset]::Now.ToString("o")) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        throw "repository-environment-missing"
    }
    if (-not $ProviderArguments -or $ProviderArguments.Count -eq 0) {
        $ProviderArguments = @("list")
    }
    $sourceRoot = Join-Path $RepositoryRoot "src"
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $originalPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $sourceRoot
        & $PythonExecutable -m selfworkflow.cli provider @ProviderArguments 2>&1 |
            Tee-Object -FilePath $LogFile -Append
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadPythonPath) {
            $env:PYTHONPATH = $originalPythonPath
        }
        else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value (
        "{0} provider-manager-exit code={1}" -f [DateTimeOffset]::Now.ToString("o"), $exitCode
    )
}
catch {
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value (
        "{0} provider-manager-failed code={1}" -f [DateTimeOffset]::Now.ToString("o"), $exitCode
    )
    [Console]::Error.WriteLine("SelfWorkFlow: provider-manager-failed. Log: {0}", $LogFile)
}

exit $exitCode
