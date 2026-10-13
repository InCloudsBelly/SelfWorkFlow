[CmdletBinding()]
param(
    [switch]$Help,
    [ValidateSet("core", "knowledge", "maintainer")]
    [string]$Profile = "core",
    [ValidateSet("Ask", "Existing", "InstallOfficial", "Skip")]
    [string]$SuperpowersChoice = "Skip",
    [switch]$ConfirmApply,
    [switch]$NonInteractive,
    [switch]$CodeGraphMcpLauncherOnly,
    [switch]$ReplaceCodeGraphOverride,
    [string]$CodeGraphPath,
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
  Install_SelfWorkFlow.bat [-Profile core|knowledge|maintainer]
  Install_SelfWorkFlow.bat -CodeGraphMcpLauncherOnly -ConfirmApply
  Install_SelfWorkFlow.bat -CodeGraphPath <local-codegraph-root> -ConfirmApply

The pinned Matt Pocock Skills foundation and the path-limited TEA, Ponytail and
other workflow submodules are prepared from the repository locks. Superpowers is external-only
and is never installed or enabled by this script.

The default CodeGraph runtime is @colbymchenry/codegraph v1.6.2. Its official
serve --mcp entry is registered with Codex. CodeGraph owns its watcher, daemon,
graph storage and process lifecycle; SelfWorkFlow owns project routing and
post-write synchronization only.

The installer shows the generated plan and requires the exact confirmation
APPLY before publishing workflow files. It writes diagnostic artifacts below
%LOCALAPPDATA%\SelfWorkFlow\logs and rolls back the workflow publication or
provider configuration if a later step fails.

An explicit -CodeGraphPath binds a local checkout or managed runtime for
testing/override. Full mode uses strength-routed grilling for design and plan;
Deep mode adds the frontier review path. No legacy topic graph or deep model is
installed or activated.
"@
    exit 0
}

$RepositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Version = "0.1.0.dev0"
$CodeGraphVersion = "v1.6.2"
$MattSkillsLockPath = Join-Path $RepositoryRoot "dependencies\locks\matt-pocock-skills.lock.yaml"
$PonytailLockPath = Join-Path $RepositoryRoot "dependencies\locks\ponytail.lock.yaml"
$CodeGraphLockPath = Join-Path $RepositoryRoot "dependencies\locks\codegraph.lock.yaml"

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 30) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
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
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "path-invalid" }
    return [IO.Path]::GetFullPath($Path)
}

function Get-Sha256Hex {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $sha256.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Invoke-NativeLogged {
    param([string]$Executable, [string[]]$Arguments = @(), [string]$WorkingDirectory)
    $previousPreference = $ErrorActionPreference
    $locationPushed = $false
    try {
        if ($WorkingDirectory) { Push-Location -LiteralPath $WorkingDirectory; $locationPushed = $true }
        $ErrorActionPreference = "Continue"
        $nativeOutput = (& $Executable @Arguments 2>&1 | Out-String).Trim()
        $nativeExitCode = $LASTEXITCODE
    }
    catch {
        $nativeOutput = $_.Exception.Message
        $nativeExitCode = 9009
    }
    finally {
        if ($locationPushed) { Pop-Location }
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeOutput) { Add-Content -LiteralPath $script:InstallLog -Value $nativeOutput -Encoding UTF8 }
    return $nativeExitCode
}

function Test-VenvReady {
    param([string]$Python)
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { return $false }
    return (Invoke-NativeLogged $Python @("-c", "import jsonschema, yaml, selfworkflow")) -eq 0
}

function Find-SystemPython {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($launcher) {
        if ((Invoke-NativeLogged $launcher.Source @("-3", "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) -eq 0) {
            return [pscustomobject]@{ Executable = $launcher.Source; Prefix = @("-3") }
        }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python) {
        if ((Invoke-NativeLogged $python.Source @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")) -eq 0) {
            return [pscustomobject]@{ Executable = $python.Source; Prefix = @() }
        }
    }
    return $null
}

function Ensure-RepositoryEnvironment {
    $venvPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
    if (Test-VenvReady $venvPython) { return $venvPython }
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) { Stop-Install "environment" 20 "python-3.11-required" }
    Write-InstallLog "Creating repository virtual environment."
    $venvExit = Invoke-NativeLogged $systemPython.Executable (@($systemPython.Prefix) + @("-m", "venv", (Join-Path $RepositoryRoot ".venv")))
    if ($venvExit -ne 0) { Stop-Install "environment" 20 "venv-create-failed" }
    $pipExit = Invoke-NativeLogged $venvPython @(
        "-m", "pip", "install", "--disable-pip-version-check",
        "-r", (Join-Path $RepositoryRoot "requirements-dev.lock.txt"), "-e", $RepositoryRoot
    )
    if ($pipExit -ne 0 -or -not (Test-VenvReady $venvPython)) { Stop-Install "environment" 20 "dependency-install-failed" }
    return $venvPython
}

function Invoke-SelfWorkflow {
    param([string[]]$Arguments, [string]$OutputPath)
    $sourceRoot = Join-Path $RepositoryRoot "src"
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $originalPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $sourceRoot
        $output = (& $script:PythonExecutable -m selfworkflow.cli @Arguments 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadPythonPath) { $env:PYTHONPATH = $originalPythonPath }
        else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    }
    if ($output) { Add-Content -LiteralPath $script:InstallLog -Value $output -Encoding UTF8 }
    if ($OutputPath) { [IO.File]::WriteAllText($OutputPath, $output + [Environment]::NewLine, [Text.UTF8Encoding]::new($false)) }
    if ($exitCode -ne 0) { throw "selfworkflow-command-failed:$($Arguments -join ' ')" }
    if ([string]::IsNullOrWhiteSpace($output)) { throw "selfworkflow-command-empty" }
    return ($output | ConvertFrom-Json)
}

function Test-CodeGraphCommand {
    param([string]$Root)
    $command = Join-Path $Root "bin\codegraph.cmd"
    return (Test-Path -LiteralPath $command -PathType Leaf) -and -not ((Get-Item -LiteralPath $command).Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Ensure-CodeGraphRuntime {
    if ($CodeGraphPath) {
        $explicit = Resolve-FullPath $CodeGraphPath
        if (-not (Test-Path -LiteralPath $explicit -PathType Container)) { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-path-invalid" }
        if ((Test-CodeGraphCommand $explicit) -or (Test-Path -LiteralPath (Join-Path $explicit "dist\bin\codegraph.js") -PathType Leaf)) {
            return $explicit
        }
        Stop-Install "codegraph-runtime" 27 "codegraph-runtime-entry-missing"
    }

    $installBase = Join-Path $DependencyRoot "codegraph\1.6.2"
    $current = Join-Path $installBase "current"
    if (-not (Test-CodeGraphCommand $current)) {
        $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
        $officialScript = Join-Path $script:LogDirectory "codegraph-install.ps1"
        try {
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1" -OutFile $officialScript -UseBasicParsing
        }
        catch { Stop-Install "codegraph-runtime" 27 "codegraph-download-failed" }
        $oldVersion = $env:CODEGRAPH_VERSION
        $oldInstall = $env:CODEGRAPH_INSTALL_DIR
        try {
            $env:CODEGRAPH_VERSION = $CodeGraphVersion
            $env:CODEGRAPH_INSTALL_DIR = $installBase
            $exit = Invoke-NativeLogged "powershell.exe" @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $officialScript
            )
        }
        finally {
            if ($null -eq $oldVersion) { Remove-Item Env:CODEGRAPH_VERSION -ErrorAction SilentlyContinue } else { $env:CODEGRAPH_VERSION = $oldVersion }
            if ($null -eq $oldInstall) { Remove-Item Env:CODEGRAPH_INSTALL_DIR -ErrorAction SilentlyContinue } else { $env:CODEGRAPH_INSTALL_DIR = $oldInstall }
        }
        if ($exit -ne 0 -or -not (Test-CodeGraphCommand $current)) { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-install-failed" }
    }
    return (Resolve-FullPath $current)
}

function Ensure-HostLauncher {
    param([string]$TargetPath)
    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) { Stop-Install "host-cli" 28 "host-cli-missing" }
    $output = (& $TargetPath --host-info 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Install "host-cli" 28 "host-cli-verify-failed" }
    $identity = $output | ConvertFrom-Json
    return [ordered]@{ status = "installed"; path = $TargetPath; artifactHash = $identity.artifactHash; snapshot = $identity.snapshot }
}

function Ensure-CodeGraphMcpLauncher {
    param([string]$RuntimeRoot, [string]$TargetPath)
    $command = Join-Path $RuntimeRoot "bin\codegraph.cmd"
    $script = Join-Path $RuntimeRoot "dist\bin\codegraph.js"
    $node = $null
    if (-not (Test-Path -LiteralPath $command -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { Stop-Install "codegraph-mcp" 28 "codegraph-mcp-entry-missing" }
        $nodeCommand = Get-Command "node.exe" -ErrorAction SilentlyContinue
        if ($null -eq $nodeCommand) { Stop-Install "codegraph-mcp" 28 "node-runtime-missing" }
        $node = $nodeCommand.Source
    }
    $parent = Split-Path -Parent $TargetPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    if ($node) {
        $quotedNode = $node.Replace('"', '""')
        $quotedScript = $script.Replace('"', '""')
        $content = @"
@echo off
setlocal
set "SELFWORKFLOW_CODEGRAPH_NODE=$quotedNode"
set "SELFWORKFLOW_CODEGRAPH_SCRIPT=$quotedScript"
if not exist "%SELFWORKFLOW_CODEGRAPH_NODE%" (
  >&2 echo SelfWorkFlow: Node runtime missing; rerun the installer.
  exit /b 20
)
if not exist "%SELFWORKFLOW_CODEGRAPH_SCRIPT%" (
  >&2 echo SelfWorkFlow: CodeGraph checkout missing; rerun the installer.
  exit /b 20
)
"%SELFWORKFLOW_CODEGRAPH_NODE%" "%SELFWORKFLOW_CODEGRAPH_SCRIPT%" %*
exit /b %ERRORLEVEL%
"@.TrimStart("`r", "`n") + "`r`n"
    }
    else {
        $quoted = $command.Replace('"', '""')
        $content = @"
@echo off
setlocal
set "SELFWORKFLOW_CODEGRAPH_CLI=$quoted"
if not exist "%SELFWORKFLOW_CODEGRAPH_CLI%" (
  >&2 echo SelfWorkFlow: CodeGraph runtime missing; rerun the installer.
  exit /b 20
)
"%SELFWORKFLOW_CODEGRAPH_CLI%" %*
exit /b %ERRORLEVEL%
"@.TrimStart("`r", "`n") + "`r`n"
    }
    try { [IO.File]::WriteAllText($TargetPath, $content, [Text.UTF8Encoding]::new($false)) }
    catch { Stop-Install "codegraph-mcp" 28 "codegraph-mcp-write-failed" }
    return [ordered]@{ status = "installed"; path = $TargetPath; runtimeRoot = $RuntimeRoot }
}

function Ensure-CodexCodeGraphMcp {
    param([string]$CodexConfigPath, [string]$LauncherPath)
    $parent = Split-Path -Parent $CodexConfigPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $begin = "# selfworkflow:codegraph-mcp:begin"
    $end = "# selfworkflow:codegraph-mcp:end"
    $section = @"
$begin
[mcp_servers.codegraph]
command = "$($LauncherPath.Replace('\', '\\').Replace('"', '\"'))"
# official command: codegraph serve --mcp
args = ["serve", "--mcp"]
$end
"@.Trim("`r", "`n")
    $existing = if (Test-Path -LiteralPath $CodexConfigPath) { [IO.File]::ReadAllText($CodexConfigPath) } else { "" }
    $oldBegin = "# selfworkflow:graft-mcp:begin"
    $oldEnd = "# selfworkflow:graft-mcp:end"
    if ($existing.Contains($oldBegin) -and $existing.Contains($oldEnd)) {
        $oldPattern = '(?ms)^' + [regex]::Escape($oldBegin) + '\r?\n.*?^' + [regex]::Escape($oldEnd) + '\r?\n?'
        $existing = [regex]::Replace($existing, $oldPattern, "")
    }
    $hasBegin = $existing.Contains($begin)
    $hasEnd = $existing.Contains($end)
    $foreign = [regex]::IsMatch($existing, '(?m)^\[mcp_servers\.codegraph\]\s*$') -and -not $hasBegin
    if (($hasBegin -xor $hasEnd) -or $foreign) { Stop-Install "codegraph-mcp" 28 "codex-codegraph-mcp-conflict" }
    if ($hasBegin -and $hasEnd) {
        $pattern = '(?ms)^' + [regex]::Escape($begin) + '\r?\n.*?^' + [regex]::Escape($end) + '\r?\n?'
        $updated = [regex]::Replace($existing, $pattern, $section + "`r`n")
    }
    elseif ([string]::IsNullOrWhiteSpace($existing)) { $updated = $section + "`r`n" }
    else { $updated = $existing.TrimEnd("`r", "`n") + "`r`n`r`n" + $section + "`r`n" }
    if ($updated -ne $existing) {
        try { [IO.File]::WriteAllText($CodexConfigPath, $updated, [Text.UTF8Encoding]::new($false)) }
        catch { Stop-Install "codegraph-mcp" 28 "codex-codegraph-mcp-write-failed" }
    }
    return [ordered]@{ status = "installed"; configPath = $CodexConfigPath; launcherPath = $LauncherPath; toolSource = "official-codegraph-mcp" }
}

function Remove-LegacyState {
    param([string]$ProviderConfigPath)
    $legacyCache = Join-Path $RepositoryRoot "graft"
    if (Test-Path -LiteralPath $legacyCache) {
        $resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot).ProviderPath.TrimEnd('\')
        $resolvedCache = (Resolve-Path -LiteralPath $legacyCache).ProviderPath.TrimEnd('\')
        if (-not $resolvedCache.StartsWith($resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $resolvedCache -ne ($resolvedRoot + '\graft')) {
            Stop-Install "cleanup" 79 "legacy-cache-path-invalid"
        }
        Remove-Item -LiteralPath $legacyCache -Recurse -Force
        Write-InstallLog "Removed legacy project CodeMap cache: <repo>\graft\"
    }
    $legacyModel = Join-Path (Split-Path -Parent $ProviderConfigPath) "graft-model.local.yaml"
    if (Test-Path -LiteralPath $legacyModel -PathType Leaf) { Remove-Item -LiteralPath $legacyModel -Force }
    $legacyLauncher = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bin\graft-mcp.cmd"
    if (Test-Path -LiteralPath $legacyLauncher -PathType Leaf) {
        $text = [IO.File]::ReadAllText($legacyLauncher)
        if ($text -match "(?i)selfworkflow.*graft|graft_no_refresh") { Remove-Item -LiteralPath $legacyLauncher -Force }
    }
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
$HostLauncherPath = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bin\selfworkflow.cmd"
$CodeGraphMcpLauncherPath = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bin\codegraph-mcp.cmd"
$CodexCodeGraphMcpConfigPath = Join-Path $CodexRoot "config.toml"
$script:PythonExecutable = $null
$applyResult = $null
$cleanupPending = @()
$codeGraphRollbackToken = $null

try {
    Write-InstallLog ("SelfWorkFlow repository: " + $RepositoryRoot)
    if ($env:OS -ne "Windows_NT") { Stop-Install "preflight" 20 "windows-required" }
    if (-not (Get-Command "git.exe" -ErrorAction SilentlyContinue)) { Stop-Install "preflight" 20 "git-required" }
    if ($SuperpowersChoice -ne "Skip") { Stop-Install "preflight" 20 "superpowers-external-only" }
    $script:PythonExecutable = Ensure-RepositoryEnvironment

    Set-InstallStage "codegraph-runtime" 27
    $runtimeRoot = Ensure-CodeGraphRuntime
    $runtimeReport = Invoke-SelfWorkflow @("provider", "inspect", "--codegraph-path", $runtimeRoot) (Join-Path $script:LogDirectory "codegraph-source.json")
    if (-not $runtimeReport.sourceHash) { Stop-Install "codegraph-runtime" 27 "codegraph-source-unverified" }

    if ($CodeGraphMcpLauncherOnly) {
        if (-not $ConfirmApply) { Stop-Install "confirmation" 50 "explicit-apply-confirmation-required" }
        Set-InstallStage "codegraph-mcp-launcher-only" 75
        $launcherReport = Ensure-CodeGraphMcpLauncher $runtimeRoot $CodeGraphMcpLauncherPath
        $codexReport = Ensure-CodexCodeGraphMcp $CodexCodeGraphMcpConfigPath $CodeGraphMcpLauncherPath
        Write-JsonFile (Join-Path $script:LogDirectory "summary.json") ([ordered]@{
            schemaVersion = 1; status = "launcher-only"; codegraphMcpLauncher = $launcherReport
            codexCodeGraphMcp = $codexReport; logDirectory = $script:LogDirectory
        })
        Write-Host "CodeGraph MCP launcher updated."
        exit 0
    }

    Set-InstallStage "submodules" 25
    $submoduleExit = Invoke-NativeLogged $script:PythonExecutable @(
        "-m", "selfworkflow.v3.submodule_profiles", "--repository", $RepositoryRoot, "--profile", "normal"
    )
    if ($submoduleExit -ne 0) { Stop-Install "submodules" 25 "normal-submodule-profile-failed" }
    if (-not (Test-Path -LiteralPath $MattSkillsLockPath -PathType Leaf)) { Stop-Install "submodules" 25 "matt-skills-lock-missing" }
    if (-not (Test-Path -LiteralPath $PonytailLockPath -PathType Leaf)) { Stop-Install "submodules" 25 "ponytail-lock-missing" }
    if (-not (Test-Path -LiteralPath $CodeGraphLockPath -PathType Leaf)) { Stop-Install "submodules" 25 "codegraph-lock-missing" }
    $mattSkillsLockText = [IO.File]::ReadAllText($MattSkillsLockPath)
    $mattSkillsCommitMatch = [regex]::Match($mattSkillsLockText, '(?m)^gitlinkCommit:\s*(\S+)\s*$')
    if (-not $mattSkillsCommitMatch.Success) { Stop-Install "submodules" 25 "matt-skills-lock-invalid" }
    $mattSkillsReport = [ordered]@{
        commit = $mattSkillsCommitMatch.Groups[1].Value
        lockHash = Get-Sha256Hex $MattSkillsLockPath
    }
    $ponytailReport = Invoke-SelfWorkflow @("source", "ponytail-verify", "--repository", $RepositoryRoot) (Join-Path $script:LogDirectory "ponytail-source.json")

    Set-InstallStage "plan" 40
    $doctorBefore = Join-Path $script:LogDirectory "doctor-before.json"
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) $doctorBefore | Out-Null
    $runtime = Join-Path $script:LogDirectory "runtime"
    $runtimeManifest = Join-Path $script:LogDirectory "runtime-manifest.json"
    Invoke-SelfWorkflow @("build", "--repository", $RepositoryRoot, "--output", $runtime, "--version", $Version, "--profile", $Profile) $runtimeManifest | Out-Null
    $planPath = Join-Path $script:LogDirectory "install-plan.json"
    Invoke-SelfWorkflow @("install", "plan", "--artifact", $runtime, "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot, "--version", $Version, "--host-launcher", $HostLauncherPath, "--host-python", $script:PythonExecutable, "--output", $planPath) $null | Out-Null
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
    if ($plan.status -eq "paused") { Stop-Install "plan" 40 ("install-plan-paused:" + ($plan.issues -join ",")) }
    Write-InstallLog ("Plan status: {0}; planHash: {1}" -f $plan.status, $plan.planHash)
    Write-InstallLog ("CodeGraph source: {0}; version: {1}" -f $runtimeReport.sourceHash, $runtimeReport.version)
    Write-InstallLog ("Ponytail commit: {0}; lock: {1}" -f $ponytailReport.gitlinkCommit, $ponytailReport.lockHash)
    Write-JsonFile (Join-Path $script:LogDirectory "confirmation-summary.json") ([ordered]@{
        planHash = $plan.planHash; profile = $plan.profile; artifactFiles = $plan.artifactFiles
        agentsRoot = $AgentsRoot; codexRoot = $CodexRoot; stateRoot = $StateRoot
        codegraph = $runtimeReport; ponytail = $ponytailReport; superpowers = "external-only"
    })

    Set-InstallStage "confirmation" 50
    if (-not $ConfirmApply) {
        if ($NonInteractive) { Stop-Install "confirmation" 50 "explicit-apply-confirmation-required" }
        if ((Read-Host "Type APPLY to publish this exact plan and dependency hashes") -cne "APPLY") { Stop-Install "confirmation" 50 "installation-cancelled" }
    }

    Set-InstallStage "apply" 60
    $applyPath = Join-Path $script:LogDirectory "apply-result.json"
    $applyResult = Invoke-SelfWorkflow @("install", "apply", "--plan", $planPath, "--confirm-plan-hash", $plan.planHash) $applyPath
    if ($applyResult.PSObject.Properties.Name -contains "cleanupPending") {
        $cleanupPending = @($applyResult.cleanupPending)
        Write-Host "Workflow files were committed; installer lock cleanup is pending. Do not delete a lock owned by another process."
    }
    Set-InstallStage "verify" 70
    Invoke-SelfWorkflow @("install", "verify", "--manifest", $applyResult.manifestPath) (Join-Path $script:LogDirectory "verify-result.json") | Out-Null

    Set-InstallStage "host-cli" 74
    $hostReport = Ensure-HostLauncher $HostLauncherPath
    Set-InstallStage "codegraph-mcp" 75
    $launcherReport = Ensure-CodeGraphMcpLauncher $runtimeRoot $CodeGraphMcpLauncherPath
    $codexReport = Ensure-CodexCodeGraphMcp $CodexCodeGraphMcpConfigPath $CodeGraphMcpLauncherPath
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) (Join-Path $script:LogDirectory "doctor-after.json") | Out-Null

    Set-InstallStage "codegraph-provider-configure" 76
    $existing = Invoke-SelfWorkflow @("provider", "list", "--config-file", $ProviderConfigFile) (Join-Path $script:LogDirectory "provider-list.json")
    $existingCodeGraph = @($existing.providers | Where-Object { $_.providerId -eq "codegraph" })
    $existingUserLocal = @($existingCodeGraph | Where-Object { $_.ownership -eq "user-local" })
    if ($existingUserLocal.Count -gt 0 -and -not $ReplaceCodeGraphOverride) {
        $providerReport = [ordered]@{ status = "preserved-user-local-override"; existing = $existingUserLocal[0] }
    }
    else {
        $codeGraphRollbackToken = [Guid]::NewGuid().ToString("N")
        $configureArgs = @(
            "provider", "configure", "--config-file", $ProviderConfigFile,
            "--codegraph-path", $runtimeRoot, "--expected-source-hash", $runtimeReport.sourceHash,
            "--rollback-token", $codeGraphRollbackToken, "--replace-existing"
        )
        $providerReport = Invoke-SelfWorkflow $configureArgs (Join-Path $script:LogDirectory "codegraph-provider-configure.json")
    }
    Invoke-SelfWorkflow @("provider", "retire", "--config-file", $ProviderConfigFile, "--provider-id", "graft") (Join-Path $script:LogDirectory "legacy-provider-retire.json") | Out-Null
    Remove-LegacyState $ProviderConfigFile

    $summary = [ordered]@{
        schemaVersion = 1; status = "installed"; profile = $Profile
        cleanupPending = $cleanupPending
        codegraph = $runtimeReport; codegraphProvider = $providerReport
        hostLauncher = $hostReport; codegraphMcpLauncher = $launcherReport
        codexCodeGraphMcp = $codexReport; ponytail = $ponytailReport
        mattSkills = $mattSkillsReport
        superpowers = "external-only"; writeCapability = "enabled"
        manifestPath = $applyResult.manifestPath; logDirectory = $script:LogDirectory
        nativeAgentVerification = "unverified-restart-required"
    }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") $summary
    if ($codeGraphRollbackToken) {
        try {
            Invoke-SelfWorkflow @("provider", "commit-config", "--config-file", $ProviderConfigFile, "--rollback-token", $codeGraphRollbackToken) (Join-Path $script:LogDirectory "codegraph-provider-commit.json") | Out-Null
            $codeGraphRollbackToken = $null
        }
        catch { Write-Host "CodeGraph provider rollback-record cleanup is pending; see the install log." }
    }
    Write-Host "Installation verified. Restart Codex before relying on the new workflow."
    exit 0
}
catch {
    $failure = $_.Exception.Message
    Write-InstallLog ("FAILED [{0}]: {1}" -f $script:CurrentStage, $failure)
    $rollbackStatus = "not-required"
    try {
        if ($codeGraphRollbackToken) {
            $rollback = Invoke-SelfWorkflow @("provider", "rollback-config", "--config-file", $ProviderConfigFile, "--rollback-token", $codeGraphRollbackToken, "--if-issued") (Join-Path $script:LogDirectory "codegraph-provider-rollback.json")
            if ($rollback.status -eq "rolled-back") { $rollbackStatus = "rolled-back" }
        }
        if ($applyResult -and $applyResult.status -eq "applied") {
            $rollbackPlanPath = Join-Path $script:LogDirectory "rollback-plan.json"
            Invoke-SelfWorkflow @("install", "rollback-plan", "--transaction", $applyResult.transactionPath, "--output", $rollbackPlanPath) $null | Out-Null
            $rollbackPlan = Get-Content -Raw -LiteralPath $rollbackPlanPath | ConvertFrom-Json
            Invoke-SelfWorkflow @("install", "rollback", "--plan", $rollbackPlanPath, "--confirm-plan-hash", $rollbackPlan.planHash) (Join-Path $script:LogDirectory "rollback-result.json") | Out-Null
            $rollbackStatus = "rolled-back"
        }
    }
    catch {
        $rollbackStatus = "failed"
        $script:FailureExitCode = 80
        Write-InstallLog ("ROLLBACK FAILED: " + $_.Exception.Message)
    }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") ([ordered]@{
        schemaVersion = 1; status = "failed"; stage = $script:CurrentStage
        cleanupPending = $cleanupPending
        reason = $failure; rollback = $rollbackStatus; logDirectory = $script:LogDirectory
    })
    Write-Host ("Installation failed. Diagnostic log: " + $script:LogDirectory)
    exit $script:FailureExitCode
}
