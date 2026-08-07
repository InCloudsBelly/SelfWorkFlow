[CmdletBinding()]
param(
    [ValidateSet("unit", "conformance", "installer", "behavioral", "automated", "native", "all")]
    [string]$Suite = "all",
    [string]$Test
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Suite -eq "unit") {
    $TestScript = Join-Path $PSScriptRoot "test.ps1"
    if ($Test) {
        & $TestScript -Test $Test
    }
    else {
        & $TestScript
    }
    exit $LASTEXITCODE
}

$UnimplementedSuites = @("conformance", "installer", "behavioral", "automated")
if ($UnimplementedSuites -contains $Suite) {
    [ordered]@{
        suite = $Suite
        status = "not-implemented"
        exitCode = 20
        message = "The '$Suite' verification suite is not implemented in Task 1."
    } | ConvertTo-Json -Compress
    exit 20
}

if ($Suite -eq "native") {
    [ordered]@{
        suite = "native"
        status = "requires-user-action"
        exitCode = 30
        message = "Native verification requires a user-operated Windows agent environment."
    } | ConvertTo-Json -Compress
    exit 30
}

if ($Suite -eq "all") {
    $TestScript = Join-Path $PSScriptRoot "test.ps1"
    $PowerShellExecutable = Join-Path $PSHOME "powershell.exe"
    $UnitArguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $TestScript)
    if ($Test) {
        $UnitArguments += @("-Test", $Test)
    }

    & $PowerShellExecutable @UnitArguments
    $UnitExitCode = $LASTEXITCODE
    if ($UnitExitCode -ne 0) {
        [ordered]@{
            suite = "all"
            status = "failed"
            exitCode = $UnitExitCode
            failedSuite = "unit"
        } | ConvertTo-Json -Compress
        exit $UnitExitCode
    }

    [ordered]@{
        suite = "all"
        status = "incomplete"
        exitCode = 20
        results = @(
            [ordered]@{ suite = "unit"; status = "passed"; exitCode = 0 }
            [ordered]@{ suite = "conformance"; status = "not-implemented"; exitCode = 20 }
            [ordered]@{ suite = "installer"; status = "not-implemented"; exitCode = 20 }
            [ordered]@{ suite = "behavioral"; status = "not-implemented"; exitCode = 20 }
            [ordered]@{ suite = "automated"; status = "not-implemented"; exitCode = 20 }
            [ordered]@{ suite = "native"; status = "requires-user-action"; exitCode = 30 }
        )
    } | ConvertTo-Json -Depth 4 -Compress
    exit 20
}
