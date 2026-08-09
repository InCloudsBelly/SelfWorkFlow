[CmdletBinding()]
param(
    [switch]$Help,
    [ValidateSet("Ask", "Install", "Skip")]
    [string]$GrillMeChoice = "Ask",
    [ValidateSet("Ask", "Existing", "InstallOfficial", "Skip")]
    [string]$SuperpowersChoice = "Ask",
    [string]$SuperpowersSource,
    [ValidateSet("Ask", "Configure", "Skip")]
    [string]$CodeGraphOverrideChoice = "Ask",
    [string]$CodeGraphPath,
    [switch]$ReplaceCodeGraphOverride,
    [switch]$AllowDirtySuperpowers,
    [switch]$ConfirmApply,
    [switch]$NonInteractive,
    [string]$AgentsRoot = (Join-Path $env:USERPROFILE ".agents"),
    [string]$CodexRoot = (Join-Path $env:USERPROFILE ".codex"),
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\state"),
    [string]$ProviderConfigFile = (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\config\providers.local.yaml"),
    [string]$DependencyRoot = (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\dependencies"),
    [string]$LogRoot = (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\logs")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Help) {
    @"
SelfWorkFlow Windows one-click installer

Usage:
  Install_SelfWorkFlow.bat [-GrillMeChoice Ask|Install|Skip]
    [-SuperpowersChoice Ask|Existing|InstallOfficial|Skip]
    [-SuperpowersSource <local-git-path>] [-AllowDirtySuperpowers]
    [-CodeGraphOverrideChoice Ask|Configure|Skip]
    [-CodeGraphPath <explicit-local-path>]
    [-ReplaceCodeGraphOverride]

GrillMeChoice:
  Ask      Prompt when Grill-me is missing.
  Install  Install the bundled Grill-me Skill.
  Skip     Continue without Grill-me.

CodeGraphOverrideChoice:
  Ask        Prompt once during interactive first installation; blank means Skip.
  Configure  Bind the explicit CodeGraphPath as a user-owned local Provider.
  Skip       Do not configure a local CodeGraph override.

The installer writes a timestamped diagnostic log, shows the generated plan,
and requires an explicit APPLY confirmation before publishing files.
"@
    exit 0
}

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Version = "0.1.0.dev0"
$OfficialSuperpowers = "https://github.com/obra/superpowers.git"
$RequiredSuperpowersSkills = @(
    "brainstorming",
    "writing-plans",
    "test-driven-development",
    "systematic-debugging",
    "requesting-code-review",
    "receiving-code-review",
    "verification-before-completion"
)

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) {
        [IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function Write-InstallLog {
    param([string]$Message)
    $line = "{0} {1}" -f [DateTimeOffset]::Now.ToString("o"), $Message
    Add-Content -LiteralPath $script:InstallLog -Value $line -Encoding UTF8
    Write-Host $Message
}

function Stop-Install {
    param([string]$Stage, [int]$Code, [string]$Reason)
    $script:CurrentStage = $Stage
    $script:FailureExitCode = $Code
    throw $Reason
}

function Set-InstallStage {
    param([string]$Stage, [int]$Code)
    $script:CurrentStage = $Stage
    $script:FailureExitCode = $Code
}

function Resolve-FullPath {
    param([string]$Path)
    return [IO.Path]::GetFullPath($Path)
}

function Invoke-NativeLogged {
    param([string]$Executable, [string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $nativeOutput = (& $Executable @Arguments 2>&1 | Out-String).Trim()
        $nativeExitCode = $LASTEXITCODE
    }
    catch {
        $nativeOutput = $_.Exception.Message
        $nativeExitCode = 9009
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeOutput) {
        Add-Content -LiteralPath $script:InstallLog -Value $nativeOutput -Encoding UTF8
    }
    return $nativeExitCode
}

function Test-VenvReady {
    param([string]$Python)
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        return $false
    }
    return (Invoke-NativeLogged $Python @("-c", "import jsonschema, yaml, selfworkflow")) -eq 0
}

function Find-SystemPython {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        $launcherExit = Invoke-NativeLogged $launcher.Source @("-3", "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        if ($launcherExit -eq 0) {
            return [pscustomobject]@{ Executable = $launcher.Source; Prefix = @("-3") }
        }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python) {
        $pythonExit = Invoke-NativeLogged $python.Source @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        if ($pythonExit -eq 0) {
            return [pscustomobject]@{ Executable = $python.Source; Prefix = @() }
        }
    }
    return $null
}

function Ensure-RepositoryEnvironment {
    $venvPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
    if (Test-VenvReady $venvPython) {
        return $venvPython
    }
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) {
        if ($NonInteractive) {
            Stop-Install "environment" 20 "python-3.11-required"
        }
        Write-Host "Python 3.11+ is required to create the repository virtual environment."
        Write-Host "With approval, winget will install Python.Python.3.12 for the current machine."
        $answer = Read-Host "Install Python with winget? [Y/N]"
        if ($answer -notmatch "^(y|yes)$") {
            Stop-Install "environment" 20 "python-install-declined"
        }
        $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
        if (-not $winget) {
            Stop-Install "environment" 20 "winget-unavailable"
        }
        Write-InstallLog "Installing Python 3.12 through winget after user approval."
        $wingetExit = Invoke-NativeLogged $winget.Source @("install", "--id", "Python.Python.3.12", "-e", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements")
        if ($wingetExit -ne 0) {
            Stop-Install "environment" 20 "python-install-failed"
        }
        $systemPython = Find-SystemPython
        if ($null -eq $systemPython) {
            Stop-Install "environment" 20 "python-not-discoverable-after-install"
        }
    }
    Write-InstallLog "Creating repository virtual environment."
    $pythonPrefix = @($systemPython.Prefix)
    $venvArguments = @($pythonPrefix) + @("-m", "venv", (Join-Path $RepositoryRoot ".venv"))
    $venvExit = Invoke-NativeLogged $systemPython.Executable $venvArguments
    if ($venvExit -ne 0) {
        Stop-Install "environment" 20 "venv-create-failed"
    }
    $pipExit = Invoke-NativeLogged $venvPython @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $RepositoryRoot "requirements-dev.lock.txt"), "-e", $RepositoryRoot)
    if ($pipExit -ne 0 -or -not (Test-VenvReady $venvPython)) {
        Stop-Install "environment" 20 "dependency-install-failed"
    }
    return $venvPython
}

function Invoke-SelfWorkflow {
    param([string[]]$Arguments, [string]$CapturePath)
    $operation = @($Arguments | Select-Object -First 2) -join " "
    Write-InstallLog ("Running selfworkflow " + $operation)
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $RepositoryRoot "src"
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = (& $script:PythonExecutable -m selfworkflow.cli @Arguments 2>&1 | Out-String).Trim()
            $childExit = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
    }
    finally {
        if ($hadPythonPath) {
            $env:PYTHONPATH = $oldPythonPath
        }
        else {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
    }
    if ($output) {
        Add-Content -LiteralPath $script:InstallLog -Value $output -Encoding UTF8
    }
    if ($childExit -ne 0) {
        throw "selfworkflow-command-failed:$childExit"
    }
    if ($CapturePath) {
        [IO.File]::WriteAllText($CapturePath, $output + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    }
    if (-not $output) {
        return $null
    }
    return $output | ConvertFrom-Json
}

function Inspect-Superpowers {
    param([string]$Source)
    $report = Invoke-SelfWorkflow @("source", "inspect", "--path", $Source) (Join-Path $script:LogDirectory "superpowers-source.json")
    if ($report.supportStatus -ne "supported") {
        Stop-Install "superpowers-selection" 30 "superpowers-source-unsupported"
    }
    foreach ($skill in $RequiredSuperpowersSkills) {
        if (@($report.trackedSkillIds) -notcontains $skill) {
            Stop-Install "superpowers-selection" 30 ("superpowers-skill-untracked:{0}" -f $skill)
        }
    }
    if ($report.dirty -and -not $AllowDirtySuperpowers) {
        if ($NonInteractive) {
            Stop-Install "superpowers-selection" 30 "dirty-superpowers-requires-authorization"
        }
        Write-Host ("The selected Superpowers source is dirty: {0}" -f $report.sourceLocator)
        $answer = Read-Host "Use this dirty source for this installation? [Y/N]"
        if ($answer -notmatch "^(y|yes)$") {
            Stop-Install "superpowers-selection" 30 "dirty-superpowers-declined"
        }
    }
    return $report
}

$AgentsRoot = Resolve-FullPath $AgentsRoot
$CodexRoot = Resolve-FullPath $CodexRoot
$StateRoot = Resolve-FullPath $StateRoot
$ProviderConfigFile = Resolve-FullPath $ProviderConfigFile
$DependencyRoot = Resolve-FullPath $DependencyRoot
$LogRoot = Resolve-FullPath $LogRoot
[IO.Directory]::CreateDirectory($LogRoot) | Out-Null
$script:LogDirectory = Join-Path $LogRoot ("install-" + [DateTime]::Now.ToString("yyyyMMdd-HHmmss-fff"))
[IO.Directory]::CreateDirectory($script:LogDirectory) | Out-Null
$script:InstallLog = Join-Path $script:LogDirectory "install.log"
[IO.File]::WriteAllText($script:InstallLog, "", [Text.UTF8Encoding]::new($false))
$script:CurrentStage = "preflight"
$script:FailureExitCode = 20
$script:PythonExecutable = $null
$applyResult = $null
$stagedSuperpowers = $null
$createdOfficialClone = $false
$superpowersReport = [ordered]@{
    supportStatus = "unsupported"
    reason = "unavailable-or-declined"
}
$providerReport = [ordered]@{ status = "skipped" }
$providerSourceReport = $null
$providerConfigSnapshotTaken = $false
$providerConfigExisted = $false
$providerConfigPreimage = $null

try {
    Write-InstallLog ("SelfWorkFlow repository: " + $RepositoryRoot)
    if ($env:OS -ne "Windows_NT") {
        Stop-Install "preflight" 20 "windows-required"
    }
    if (-not (Get-Command "git.exe" -ErrorAction SilentlyContinue)) {
        Stop-Install "preflight" 20 "git-required"
    }
    $script:PythonExecutable = Ensure-RepositoryEnvironment

    Set-InstallStage "submodules" 25
    Write-InstallLog "Preparing the path-limited normal submodule profile."
    $submoduleExit = Invoke-NativeLogged $script:PythonExecutable @(
        "-m", "selfworkflow.v3.submodule_profiles",
        "--repository", $RepositoryRoot,
        "--profile", "normal"
    )
    if ($submoduleExit -ne 0) {
        Stop-Install "submodules" 25 "normal-submodule-profile-failed"
    }

    Set-InstallStage "grill-selection" 30
    $grillTarget = Join-Path $AgentsRoot "skills\grill-me\SKILL.md"
    if ($GrillMeChoice -eq "Ask") {
        if (Test-Path -LiteralPath $grillTarget -PathType Leaf) {
            $GrillMeChoice = "Install"
            Write-InstallLog "Existing Grill-me detected; compatibility will be checked by the install plan."
        }
        elseif ($NonInteractive) {
            Stop-Install "grill-selection" 30 "grill-me-choice-required"
        }
        else {
            Write-Host "Grill-me is not installed. SelfWorkFlow contains a bundled, explicit-only version."
            $answer = Read-Host "Install bundled Grill-me? [Y/N] (recommended: Y)"
            $GrillMeChoice = if ($answer -match "^(y|yes)$") { "Install" } else { "Skip" }
        }
    }

    Set-InstallStage "superpowers-selection" 30
    if (-not $SuperpowersSource) {
        $sourceCandidates = @(
            (Join-Path $CodexRoot "superpowers"),
            (Join-Path $DependencyRoot "superpowers")
        )
        foreach ($defaultSource in $sourceCandidates) {
            if (Test-Path -LiteralPath $defaultSource -PathType Container) {
                $SuperpowersSource = $defaultSource
                break
            }
        }
    }
    if ($SuperpowersChoice -eq "Ask") {
        if ($NonInteractive) {
            Stop-Install "superpowers-selection" 30 "superpowers-choice-required"
        }
        if ($SuperpowersSource) {
            $answer = Read-Host ("Use Superpowers source '{0}'? [Y/N]" -f $SuperpowersSource)
            $SuperpowersChoice = if ($answer -match "^(y|yes)$") { "Existing" } else { "Skip" }
        }
        else {
            Write-Host "Superpowers is required for Brainstorming, Plan, TDD, Review, and completion verification."
            $answer = Read-Host "Install the official obra/superpowers repository? [Y/N]"
            $SuperpowersChoice = if ($answer -match "^(y|yes)$") { "InstallOfficial" } else { "Skip" }
        }
    }
    if ($SuperpowersChoice -eq "Existing") {
        if (-not $SuperpowersSource) {
            Stop-Install "superpowers-selection" 30 "superpowers-source-required"
        }
        $SuperpowersSource = (Resolve-Path -LiteralPath $SuperpowersSource -ErrorAction Stop).Path
        $superpowersReport = Inspect-Superpowers $SuperpowersSource
    }
    elseif ($SuperpowersChoice -eq "InstallOfficial") {
        $SuperpowersSource = Join-Path $DependencyRoot "superpowers"
        if (Test-Path -LiteralPath $SuperpowersSource) {
            Stop-Install "superpowers-selection" 30 "official-superpowers-target-exists"
        }
        [IO.Directory]::CreateDirectory($DependencyRoot) | Out-Null
        $createdOfficialClone = $true
        Write-InstallLog "Cloning the approved official Superpowers source."
        $cloneExit = Invoke-NativeLogged "git.exe" @("clone", "--depth", "1", $OfficialSuperpowers, $SuperpowersSource)
        if ($cloneExit -ne 0) {
            Stop-Install "superpowers-selection" 30 "official-superpowers-clone-failed"
        }
        $superpowersReport = Inspect-Superpowers $SuperpowersSource
    }

    Set-InstallStage "provider-selection" 30
    if ($CodeGraphOverrideChoice -eq "Ask") {
        if ($NonInteractive) {
            $CodeGraphOverrideChoice = "Skip"
        }
        else {
            $answer = Read-Host "Configure an explicit local CodeGraph override? [y/N]"
            if ($answer -match "^(y|yes)$") {
                $CodeGraphOverrideChoice = "Configure"
                if (-not $CodeGraphPath) {
                    $CodeGraphPath = Read-Host "Absolute CodeGraph path"
                }
            }
            else {
                $CodeGraphOverrideChoice = "Skip"
            }
        }
    }
    if ($CodeGraphOverrideChoice -eq "Configure") {
        if (-not $CodeGraphPath) {
            Stop-Install "provider-selection" 30 "codegraph-path-required"
        }
        $CodeGraphPath = (Resolve-Path -LiteralPath $CodeGraphPath -ErrorAction Stop).Path
        $providerSourceReport = Invoke-SelfWorkflow @(
            "provider", "inspect", "--codegraph-path", $CodeGraphPath
        ) (Join-Path $script:LogDirectory "provider-source.json")
    }

    Set-InstallStage "plan" 40
    $doctorBefore = Join-Path $script:LogDirectory "doctor-before.json"
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) $doctorBefore | Out-Null
    $runtime = Join-Path $script:LogDirectory "runtime"
    $runtimeManifest = Join-Path $script:LogDirectory "runtime-manifest.json"
    $buildArguments = @("build", "--repository", $RepositoryRoot, "--output", $runtime, "--version", $Version, "--profile", "core")
    if ($GrillMeChoice -eq "Skip") {
        $buildArguments += "--without-grill-me"
    }
    Invoke-SelfWorkflow $buildArguments $runtimeManifest | Out-Null
    $planPath = Join-Path $script:LogDirectory "install-plan.json"
    Invoke-SelfWorkflow @("install", "plan", "--artifact", $runtime, "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot, "--version", $Version, "--output", $planPath) $null | Out-Null
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
    if ($plan.status -eq "paused") {
        Stop-Install "plan" 40 ("install-plan-paused:" + ($plan.issues -join ","))
    }
    Write-InstallLog ("Plan status: {0}; planHash: {1}" -f $plan.status, $plan.planHash)
    Write-InstallLog ("Grill-me: {0}; Superpowers: {1}" -f $GrillMeChoice, $SuperpowersChoice)
    Write-InstallLog ("Agents root: " + $AgentsRoot)
    Write-InstallLog ("Codex root: " + $CodexRoot)
    Write-InstallLog ("State root: " + $StateRoot)
    Write-InstallLog ("Profile: {0}; Artifact files: {1}" -f $plan.profile, @($plan.artifactFiles).Count)
    if ($SuperpowersChoice -ne "Skip") {
        Write-InstallLog ("Superpowers commit: " + $superpowersReport.commit)
        Write-InstallLog ("Superpowers inventoryHash: " + $superpowersReport.inventoryHash)
        Write-InstallLog ("Superpowers dirty: " + $superpowersReport.dirty)
    }
    if ($providerSourceReport) {
        Write-InstallLog ("CodeGraph commit: " + $providerSourceReport.commit)
        Write-InstallLog ("CodeGraph sourceHash: " + $providerSourceReport.sourceHash)
        Write-InstallLog ("CodeGraph dirty: " + $providerSourceReport.dirty)
        Write-InstallLog ("CodeGraph version: " + $providerSourceReport.version)
    }
    Write-JsonFile (Join-Path $script:LogDirectory "confirmation-summary.json") ([ordered]@{
        planHash = $plan.planHash
        profile = $plan.profile
        artifactFiles = $plan.artifactFiles
        agentsRoot = $AgentsRoot
        codexRoot = $CodexRoot
        stateRoot = $StateRoot
        grillMeChoice = $GrillMeChoice
        superpowersChoice = $SuperpowersChoice
        codeGraphOverrideChoice = $CodeGraphOverrideChoice
        codeGraphSource = $providerSourceReport
        superpowers = $superpowersReport
    })

    Set-InstallStage "confirmation" 50
    if (-not $ConfirmApply) {
        if ($NonInteractive) {
            Stop-Install "confirmation" 50 "explicit-apply-confirmation-required"
        }
        $answer = Read-Host "Type APPLY to publish this exact plan and displayed dependency/provider hashes"
        if ($answer -cne "APPLY") {
            Stop-Install "confirmation" 50 "installation-cancelled"
        }
    }

    Set-InstallStage "apply" 60
    $applyPath = Join-Path $script:LogDirectory "apply-result.json"
    $applyResult = Invoke-SelfWorkflow @("install", "apply", "--plan", $planPath, "--confirm-plan-hash", $plan.planHash) $applyPath
    Set-InstallStage "verify" 70
    $verifyPath = Join-Path $script:LogDirectory "verify-result.json"
    Invoke-SelfWorkflow @("install", "verify", "--manifest", $applyResult.manifestPath) $verifyPath | Out-Null

    if ($SuperpowersChoice -ne "Skip") {
        $superpowersTarget = Join-Path $AgentsRoot "skills\superpowers"
        $stagedSuperpowers = Invoke-SelfWorkflow @(
            "source", "stage",
            "--path", $SuperpowersSource,
            "--target", $superpowersTarget,
            "--expected-inventory-hash", $superpowersReport.inventoryHash
        ) (Join-Path $script:LogDirectory "superpowers-stage.json")
        foreach ($skill in $RequiredSuperpowersSkills) {
            $entry = Join-Path $superpowersTarget ("{0}\SKILL.md" -f $skill)
            if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
                Stop-Install "verify" 70 ("staged-superpowers-skill-missing:{0}" -f $skill)
            }
        }
    }
    $doctorAfter = Join-Path $script:LogDirectory "doctor-after.json"
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) $doctorAfter | Out-Null

    if ($CodeGraphOverrideChoice -eq "Configure") {
        Set-InstallStage "provider-configure" 75
        $providerConfigSnapshotTaken = $true
        $providerConfigExisted = Test-Path -LiteralPath $ProviderConfigFile -PathType Leaf
        if ($providerConfigExisted) {
            $providerConfigPreimage = [IO.File]::ReadAllBytes($ProviderConfigFile)
        }
        $providerArguments = @(
            "provider", "configure",
            "--config-file", $ProviderConfigFile,
            "--codegraph-path", $CodeGraphPath,
            "--expected-source-hash", $providerSourceReport.sourceHash
        )
        if ($ReplaceCodeGraphOverride) {
            $providerArguments += "--replace-existing"
        }
        $providerReport = Invoke-SelfWorkflow $providerArguments (Join-Path $script:LogDirectory "provider-configure.json")
        if ($env:SELFWORKFLOW_TEST_FAIL_AFTER_PROVIDER_CONFIG -eq "1") {
            throw "injected-failure-after-provider-config"
        }
    }

    $summary = [ordered]@{
        schemaVersion = 1
        status = "installed"
        profile = "core"
        grillMe = if ($GrillMeChoice -eq "Install") { "installed" } else { "skipped" }
        superpowers = $superpowersReport
        codeGraphOverride = $providerReport.status
        writeCapability = if ($SuperpowersChoice -eq "Skip") { "paused-superpowers-unavailable" } else { "enabled" }
        manifestPath = $applyResult.manifestPath
        logDirectory = $script:LogDirectory
        nativeAgentVerification = "unverified-restart-required"
    }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") $summary
    Write-InstallLog ("Installation verified. Logs: " + $script:LogDirectory)
    Write-Host "Restart Codex before relying on newly discovered Skills."
    exit 0
}
catch {
    $failure = $_.Exception.Message
    Write-InstallLog ("FAILED [{0}]: {1}" -f $script:CurrentStage, $failure)
    $rollbackStatus = "not-required"
    try {
        if ($providerConfigSnapshotTaken) {
            $providerParent = Split-Path -Parent $ProviderConfigFile
            [IO.Directory]::CreateDirectory($providerParent) | Out-Null
            $providerLockPath = $ProviderConfigFile + ".lock"
            $providerLock = [IO.File]::Open(
                $providerLockPath,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            try {
                if ($providerConfigExisted) {
                    $providerRestore = $ProviderConfigFile + ".rollback-" + [Guid]::NewGuid().ToString("N")
                    [IO.File]::WriteAllBytes($providerRestore, $providerConfigPreimage)
                    if (Test-Path -LiteralPath $ProviderConfigFile) {
                        [IO.File]::Replace($providerRestore, $ProviderConfigFile, $null)
                    }
                    else {
                        [IO.File]::Move($providerRestore, $ProviderConfigFile)
                    }
                }
                elseif (Test-Path -LiteralPath $ProviderConfigFile) {
                    Remove-Item -LiteralPath $ProviderConfigFile -Force
                }
            }
            finally {
                $providerLock.Dispose()
            }
            $rollbackStatus = "rolled-back"
        }
        if ($stagedSuperpowers -and $stagedSuperpowers.status -eq "staged") {
            $superpowersTarget = Resolve-FullPath (Join-Path $AgentsRoot "skills\superpowers")
            $expectedTarget = Resolve-FullPath $stagedSuperpowers.target
            if ($superpowersTarget -eq $expectedTarget -and (Test-Path -LiteralPath $superpowersTarget)) {
                Remove-Item -LiteralPath $superpowersTarget -Recurse -Force
            }
        }
        if ($applyResult -and $applyResult.status -eq "applied") {
            $rollbackPlanPath = Join-Path $script:LogDirectory "rollback-plan.json"
            Invoke-SelfWorkflow @("install", "rollback-plan", "--transaction", $applyResult.transactionPath, "--output", $rollbackPlanPath) $null | Out-Null
            $rollbackPlan = Get-Content -Raw -LiteralPath $rollbackPlanPath | ConvertFrom-Json
            Invoke-SelfWorkflow @("install", "rollback", "--plan", $rollbackPlanPath, "--confirm-plan-hash", $rollbackPlan.planHash) (Join-Path $script:LogDirectory "rollback-result.json") | Out-Null
            $rollbackStatus = "rolled-back"
        }
        if ($createdOfficialClone -and (Test-Path -LiteralPath $SuperpowersSource)) {
            $expectedClone = Resolve-FullPath (Join-Path $DependencyRoot "superpowers")
            if ((Resolve-FullPath $SuperpowersSource) -eq $expectedClone) {
                Remove-Item -LiteralPath $SuperpowersSource -Recurse -Force
            }
        }
    }
    catch {
        $rollbackStatus = "failed"
        $script:FailureExitCode = 80
        Write-InstallLog ("ROLLBACK FAILED: " + $_.Exception.Message)
    }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") ([ordered]@{
        schemaVersion = 1
        status = "failed"
        stage = $script:CurrentStage
        reason = $failure
        rollback = $rollbackStatus
        logDirectory = $script:LogDirectory
    })
    Write-Host ("Installation failed. Diagnostic log: " + $script:LogDirectory)
    exit $script:FailureExitCode
}
