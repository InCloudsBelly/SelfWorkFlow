[CmdletBinding()]
param(
    [ValidateSet("unit", "conformance", "installer", "behavioral", "automated", "native", "all")]
    [string]$Suite = "all",
    [string]$Test
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Suite -in @("unit", "conformance", "installer", "behavioral", "automated")) {
    $TestScript = Join-Path $PSScriptRoot "test.ps1"
    if ($Test) {
        & $TestScript -Test $Test
    }
    elseif ($Suite -eq "unit") {
        & $TestScript -Test "tests.unit"
    }
    elseif ($Suite -eq "conformance") {
        & $TestScript -Test "tests.conformance"
    }
    elseif ($Suite -eq "installer") {
        & $TestScript -Test "tests.installer"
    }
    elseif ($Suite -eq "behavioral") {
        & $TestScript -Test "tests.behavioral"
    }
    else {
        & $TestScript
    }
    $SuiteExitCode = $LASTEXITCODE
    [ordered]@{
        suite = $Suite
        status = if ($SuiteExitCode -eq 0) { "passed" } else { "failed" }
        exitCode = $SuiteExitCode
    } | ConvertTo-Json -Compress
    exit $SuiteExitCode
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
            [ordered]@{ suite = "automated"; status = "passed"; exitCode = 0 }
            [ordered]@{ suite = "native"; status = "requires-user-action"; exitCode = 30 }
        )
    } | ConvertTo-Json -Depth 4 -Compress
    exit 20
}
