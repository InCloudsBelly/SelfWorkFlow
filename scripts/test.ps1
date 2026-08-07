[CmdletBinding()]
param(
    [string]$Test
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$PythonExecutable = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    [Console]::Error.WriteLine("SelfWorkFlow: repository .venv is required at '$PythonExecutable'.")
    exit 10
}

$SourceRoot = Join-Path $RepositoryRoot "src"
$HadPythonPath = Test-Path Env:PYTHONPATH
$OriginalPythonPath = $env:PYTHONPATH
$ChildExitCode = 0
$LocationPushed = $false

try {
    Push-Location -LiteralPath $RepositoryRoot
    $LocationPushed = $true
    $env:PYTHONPATH = $SourceRoot
    if ($Test) {
        & $PythonExecutable -m unittest $Test -v
        $ChildExitCode = $LASTEXITCODE
    }
    else {
        & $PythonExecutable -m unittest discover -s tests -t . -v
        $ChildExitCode = $LASTEXITCODE
    }
}
finally {
    if ($HadPythonPath) {
        $env:PYTHONPATH = $OriginalPythonPath
    }
    else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    if ($LocationPushed) {
        Pop-Location
    }
}

exit $ChildExitCode
