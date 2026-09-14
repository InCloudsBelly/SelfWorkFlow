[CmdletBinding()]
param(
    [switch]$Help,
    [ValidateSet("core", "knowledge", "maintainer")]
    [string]$Profile = "core",
    [ValidateSet("Ask", "Existing", "InstallOfficial", "Skip")]
    [string]$SuperpowersChoice = "Skip",
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
  Install_SelfWorkFlow.bat [-Profile core|knowledge|maintainer]

The pinned Matt Pocock Skills foundation, including strength-routed grilling and
grill-me, is installed from the repository Submodule. Superpowers is external-only and is
never installed or enabled by this script.

The pinned Graft Submodule is verified and built with Node >=20 during installation.
Graft is the default code-reading Provider; its project graph is local and lazily
initialized on the first code task. The installer registers the official Graft MCP
for Codex through a managed launcher bound to the current working directory. The
SelfWorkFlow Host remains responsible only for lifecycle checks, explicit maintenance,
and recovery; it does not reimplement Graft's graph or query protocol.

The installer writes a timestamped diagnostic log, shows the generated plan,
and requires an explicit APPLY confirmation before publishing files. It also
installs a machine-local Host CLI at %LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd
so project conversations can invoke the verified Provider from any working directory.
"@
    exit 0
}

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Version = "0.1.0.dev0"
$MattSkillsLockPath = Join-Path $RepositoryRoot "dependencies\locks\matt-pocock-skills.lock.yaml"
$GraftLockPath = Join-Path $RepositoryRoot "dependencies\locks\graft.lock.yaml"
$GraftPath = Join-Path $RepositoryRoot "dependencies\upstream\graft"
$PonytailLockPath = Join-Path $RepositoryRoot "dependencies\locks\ponytail.lock.yaml"

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

function Get-Sha256Hex {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-NativeLogged {
    param([string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory)
    $previousPreference = $ErrorActionPreference
    $locationPushed = $false
    try {
        if ($WorkingDirectory) {
            Push-Location -LiteralPath $WorkingDirectory
            $locationPushed = $true
        }
        $ErrorActionPreference = "Continue"
        $nativeOutput = (& $Executable @Arguments 2>&1 | Out-String).Trim()
        $nativeExitCode = $LASTEXITCODE
    }
    catch {
        $nativeOutput = $_.Exception.Message
        $nativeExitCode = 9009
    }
    finally {
        if ($locationPushed) {
            Pop-Location
        }
        $ErrorActionPreference = $previousPreference
    }
    if ($nativeOutput) {
        Add-Content -LiteralPath $script:InstallLog -Value $nativeOutput -Encoding UTF8
    }
    return $nativeExitCode
}

function Invoke-GitSanitized {
    param([string[]]$Arguments)
    $saved = @{}
    $blockedNames = @(
        "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
        "GIT_ATTR_NOSYSTEM"
    )
    $dynamicNames = @(
        Get-ChildItem Env: | Where-Object {
            $_.Name -match '^GIT_CONFIG_(KEY|VALUE)_\d+$'
        } | ForEach-Object { $_.Name }
    )
    foreach ($name in @($blockedNames + $dynamicNames | Select-Object -Unique)) {
        if (Test-Path ("Env:" + $name)) {
            $saved[$name] = [Environment]::GetEnvironmentVariable($name)
            Remove-Item ("Env:" + $name) -ErrorAction SilentlyContinue
        }
    }
    try {
        $env:GIT_CONFIG_NOSYSTEM = "1"
        $env:GIT_CONFIG_GLOBAL = "NUL"
        $env:GIT_CONFIG_SYSTEM = "NUL"
        $env:GIT_ATTR_NOSYSTEM = "1"
        $gitArguments = @(
            "-c", "core.hooksPath=NUL",
            "-c", "core.fsmonitor=false"
        ) + @($Arguments)
        return Invoke-NativeLogged "git.exe" $gitArguments
    }
    finally {
        foreach ($name in @($blockedNames + $dynamicNames | Select-Object -Unique)) {
            Remove-Item ("Env:" + $name) -ErrorAction SilentlyContinue
        }
        foreach ($entry in $saved.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value)
        }
    }
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
    if ($CapturePath) {
        [IO.File]::WriteAllText($CapturePath, $output + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    }
    if ($childExit -ne 0) {
        throw "selfworkflow-command-failed:$childExit"
    }
    if (-not $output) {
        return $null
    }
    return $output | ConvertFrom-Json
}

function Ensure-GraftBuild {
    param([string]$ExpectedCommit, [string]$ExpectedTree)
    if (-not (Test-Path -LiteralPath $GraftPath -PathType Container)) {
        Stop-Install "graft-build" 27 "graft-source-missing"
    }
    $node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if (-not $npm) {
        $npm = Get-Command "npm.exe" -ErrorAction SilentlyContinue
    }
    if (-not $node -or -not $npm) {
        Stop-Install "graft-build" 27 "node-npm-required"
    }
    $nodeVersion = (& $node.Source "--version" 2>$null | Out-String).Trim()
    if ($nodeVersion -notmatch '^v(2[0-9]|[3-9][0-9])\.') {
        Stop-Install "graft-build" 27 "node-20-required"
    }
    $graftEntry = Join-Path $GraftPath "dist\cli.js"
    $graftStampPath = Join-Path $GraftPath "node_modules\.selfworkflow-build.json"
    $graftPackageJsonPath = Join-Path $GraftPath "package.json"
    $graftPackageLockPath = Join-Path $GraftPath "package-lock.json"
    if ((Test-Path -LiteralPath $graftEntry -PathType Leaf) -and
        (Test-Path -LiteralPath $graftStampPath -PathType Leaf)) {
        try {
            $stamp = Get-Content -Raw -LiteralPath $graftStampPath | ConvertFrom-Json
            $stampMatches =
                $stamp.commit -eq $ExpectedCommit -and
                $stamp.tree -eq $ExpectedTree -and
                $stamp.node -eq $nodeVersion -and
                $stamp.packageJsonHash -eq ("sha256:" + (Get-Sha256Hex $graftPackageJsonPath)) -and
                $stamp.packageLockHash -eq ("sha256:" + (Get-Sha256Hex $graftPackageLockPath)) -and
                $stamp.cliHash -eq ("sha256:" + (Get-Sha256Hex $graftEntry))
            if ($stampMatches) {
                $cachedRuntimeExit = Invoke-NativeLogged $node.Source @($graftEntry, "--version") $GraftPath
                if ($cachedRuntimeExit -eq 0) {
                    Write-InstallLog "Reusing verified local Graft build."
                    return
                }
                Write-InstallLog "Cached Graft runtime check failed; rebuilding."
            }
        }
        catch {
            Write-InstallLog "Cached Graft build stamp invalid; rebuilding."
        }
    }
    Write-InstallLog ("Building pinned Graft with Node " + $nodeVersion)
    $ciExit = Invoke-NativeLogged $npm.Source @("ci", "--ignore-scripts") $GraftPath
    if ($ciExit -ne 0) {
        Stop-Install "graft-build" 27 "graft-npm-ci-failed"
    }
    # Install dependencies without executing package scripts, then rebuild the
    # pinned native grammar packages after the full dependency tree exists.
    # This keeps the install order deterministic while still producing a
    # runnable Graft CLI on hosts where prebuilt grammars are unavailable.
    $rebuildExit = Invoke-NativeLogged $npm.Source @("rebuild", "--foreground-scripts") $GraftPath
    if ($rebuildExit -ne 0) {
        Stop-Install "graft-build" 27 "graft-native-build-failed"
    }
    $buildExit = Invoke-NativeLogged $npm.Source @("run", "build") $GraftPath
    if ($buildExit -ne 0) {
        Stop-Install "graft-build" 27 "graft-build-failed"
    }
    $runtimeExit = Invoke-NativeLogged $node.Source @($graftEntry, "--version") $GraftPath
    if ($runtimeExit -ne 0) {
        Stop-Install "graft-build" 27 "graft-runtime-check-failed"
    }
    Write-JsonFile $graftStampPath ([ordered]@{
        schemaVersion = 1
        commit = $ExpectedCommit
        tree = $ExpectedTree
        node = $nodeVersion
        packageJsonHash = "sha256:" + (Get-Sha256Hex $graftPackageJsonPath)
        packageLockHash = "sha256:" + (Get-Sha256Hex $graftPackageLockPath)
        cliHash = "sha256:" + (Get-Sha256Hex $graftEntry)
    })
}

function Ensure-HostLauncher {
    param([string]$RepositoryRoot, [string]$TargetPath)
    if ($RepositoryRoot -match '[%"\r\n]') {
        Stop-Install "host-cli" 28 "host-cli-repository-path-invalid"
    }
    $parent = Split-Path -Parent $TargetPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $marker = "SelfWorkFlow managed Host CLI"
    if (Test-Path -LiteralPath $TargetPath) {
        $item = Get-Item -LiteralPath $TargetPath -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Stop-Install "host-cli" 28 "host-cli-target-invalid"
        }
        $existing = [IO.File]::ReadAllText($TargetPath)
        if ($existing -notmatch [regex]::Escape($marker)) {
            Stop-Install "host-cli" 28 "host-cli-conflict"
        }
    }
    $content = @"
@echo off
setlocal
rem $marker
set "SELFWORKFLOW_REPOSITORY_ROOT=$RepositoryRoot"
set "SELFWORKFLOW_PYTHON=%SELFWORKFLOW_REPOSITORY_ROOT%\.venv\Scripts\python.exe"
if not exist "%SELFWORKFLOW_PYTHON%" (
  >&2 echo SelfWorkFlow: repository environment missing; rerun the installer.
  exit /b 20
)
set "PYTHONPATH=%SELFWORKFLOW_REPOSITORY_ROOT%\src;%PYTHONPATH%"
"%SELFWORKFLOW_PYTHON%" -m selfworkflow.cli %*
exit /b %ERRORLEVEL%
"@.TrimStart("`r", "`n") + "`r`n"
    $temporary = Join-Path $parent ("." + [IO.Path]::GetFileName($TargetPath) + ".tmp-" + [Guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent ("." + [IO.Path]::GetFileName($TargetPath) + ".bak-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText($temporary, $content, [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $TargetPath) {
            [IO.File]::Replace($temporary, $TargetPath, $backup, $true)
            [IO.File]::Delete($backup)
        }
        else {
            [IO.File]::Move($temporary, $TargetPath)
        }
    }
    catch {
        Stop-Install "host-cli" 28 "host-cli-write-failed"
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            [IO.File]::Delete($temporary)
        }
        if (Test-Path -LiteralPath $backup) {
            [IO.File]::Delete($backup)
        }
    }
    return [ordered]@{
        status = "installed"
        path = $TargetPath
        repositoryRoot = $RepositoryRoot
    }
}

function Ensure-GraftMcpLauncher {
    param([string]$RepositoryRoot, [string]$GraftPath, [string]$TargetPath)
    if ($RepositoryRoot -match '[%"\r\n]' -or $GraftPath -match '[%"\r\n]') {
        Stop-Install "graft-mcp" 28 "graft-mcp-path-invalid"
    }
    $node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    if (-not $node) {
        Stop-Install "graft-mcp" 28 "graft-mcp-node-missing"
    }
    $nodePath = [IO.Path]::GetFullPath($node.Source)
    if ($nodePath -match '[%"\r\n]') {
        Stop-Install "graft-mcp" 28 "graft-mcp-node-path-invalid"
    }
    $entry = Join-Path $GraftPath "dist\cli.js"
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
        Stop-Install "graft-mcp" 28 "graft-mcp-entry-missing"
    }
    $parent = Split-Path -Parent $TargetPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $marker = "SelfWorkFlow managed official Graft MCP launcher"
    if (Test-Path -LiteralPath $TargetPath) {
        $item = Get-Item -LiteralPath $TargetPath -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Stop-Install "graft-mcp" 28 "graft-mcp-target-invalid"
        }
        $existing = [IO.File]::ReadAllText($TargetPath)
        if ($existing -notmatch [regex]::Escape($marker)) {
            Stop-Install "graft-mcp" 28 "graft-mcp-conflict"
        }
    }
    $content = @"
@echo off
setlocal
rem $marker
set "SELFWORKFLOW_GRAFT_NODE=$nodePath"
set "SELFWORKFLOW_GRAFT_CLI=$GraftPath\dist\cli.js"
set "SELFWORKFLOW_GRAFT_PROJECT_ROOT=%CD%"
if not exist "%SELFWORKFLOW_GRAFT_NODE%" (
  >&2 echo SelfWorkFlow: Node runtime missing; rerun the installer.
  exit /b 20
)
if not exist "%SELFWORKFLOW_GRAFT_CLI%" (
  >&2 echo SelfWorkFlow: pinned Graft CLI missing; rerun the installer.
  exit /b 20
)
"%SELFWORKFLOW_GRAFT_NODE%" "%SELFWORKFLOW_GRAFT_CLI%" mcp "%SELFWORKFLOW_GRAFT_PROJECT_ROOT%"
exit /b %ERRORLEVEL%
"@.TrimStart("`r", "`n") + "`r`n"
    $temporary = Join-Path $parent ("." + [IO.Path]::GetFileName($TargetPath) + ".tmp-" + [Guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent ("." + [IO.Path]::GetFileName($TargetPath) + ".bak-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText($temporary, $content, [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $TargetPath) {
            [IO.File]::Replace($temporary, $TargetPath, $backup, $true)
            [IO.File]::Delete($backup)
        }
        else {
            [IO.File]::Move($temporary, $TargetPath)
        }
    }
    catch {
        Stop-Install "graft-mcp" 28 "graft-mcp-write-failed"
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
        if (Test-Path -LiteralPath $backup) { [IO.File]::Delete($backup) }
    }
    return [ordered]@{
        status = "installed"
        path = $TargetPath
        repositoryRoot = $RepositoryRoot
        projectRootMode = "current-working-directory"
    }
}

function Ensure-CodexGraftMcp {
    param([string]$CodexConfigPath, [string]$LauncherPath)
    $parent = Split-Path -Parent $CodexConfigPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $begin = "# selfworkflow:graft-mcp:begin"
    $end = "# selfworkflow:graft-mcp:end"
    $launcherToml = $LauncherPath.Replace("\", "\\").Replace('"', '\"')
    $section = @"
$begin
[mcp_servers.graft]
command = "$launcherToml"
args = []
$end
"@.Trim("`r", "`n")
    $existing = if (Test-Path -LiteralPath $CodexConfigPath) {
        [IO.File]::ReadAllText($CodexConfigPath)
    } else { "" }
    $hasBegin = $existing.Contains($begin)
    $hasEnd = $existing.Contains($end)
    $hasForeignSection = [regex]::IsMatch($existing, '(?m)^\[mcp_servers\.graft\]\s*$') -and -not $hasBegin
    if (($hasBegin -xor $hasEnd) -or $hasForeignSection) {
        Stop-Install "graft-mcp" 28 "codex-graft-mcp-conflict"
    }
    if ($hasBegin -and $hasEnd) {
        $pattern = '(?ms)^' + [regex]::Escape($begin) + '\r?\n.*?^' + [regex]::Escape($end) + '\r?\n?'
        $updated = [regex]::Replace($existing, $pattern, $section + "`r`n")
    }
    elseif ([string]::IsNullOrWhiteSpace($existing)) {
        $updated = $section + "`r`n"
    }
    else {
        $updated = $existing.TrimEnd("`r", "`n") + "`r`n`r`n" + $section + "`r`n"
    }
    if ($updated -ne $existing) {
        $temporary = Join-Path $parent ("." + [IO.Path]::GetFileName($CodexConfigPath) + ".tmp-" + [Guid]::NewGuid().ToString("N"))
        $backup = Join-Path $parent ("." + [IO.Path]::GetFileName($CodexConfigPath) + ".bak-" + [Guid]::NewGuid().ToString("N"))
        try {
            [IO.File]::WriteAllText($temporary, $updated, [Text.UTF8Encoding]::new($false))
            if (Test-Path -LiteralPath $CodexConfigPath) {
                [IO.File]::Replace($temporary, $CodexConfigPath, $backup, $true)
                [IO.File]::Delete($backup)
            }
            else { [IO.File]::Move($temporary, $CodexConfigPath) }
        }
        catch { Stop-Install "graft-mcp" 28 "codex-graft-mcp-write-failed" }
        finally {
            if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
            if (Test-Path -LiteralPath $backup) { [IO.File]::Delete($backup) }
        }
    }
    return [ordered]@{
        status = if ($updated -eq $existing) { "unchanged" } else { "installed" }
        configPath = $CodexConfigPath
        launcherPath = $LauncherPath
        toolSource = "official-graft-mcp"
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
$GraftMcpLauncherPath = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bin\graft-mcp.cmd"
$CodexGraftMcpConfigPath = Join-Path $CodexRoot "config.toml"
$script:PythonExecutable = $null
$applyResult = $null
$mattSkillsReport = $null
$graftReport = $null
$ponytailReport = $null
$graftProviderReport = [ordered]@{ status = "skipped" }
$graftSourceReport = $null
$graftRollbackToken = $null
$graftMcpLauncherReport = $null
$codexGraftMcpReport = $null

try {
    Write-InstallLog ("SelfWorkFlow repository: " + $RepositoryRoot)
    if ($env:OS -ne "Windows_NT") {
        Stop-Install "preflight" 20 "windows-required"
    }
    if (-not (Get-Command "git.exe" -ErrorAction SilentlyContinue)) {
        Stop-Install "preflight" 20 "git-required"
    }
    if ($SuperpowersChoice -ne "Skip") {
        Stop-Install "preflight" 20 "superpowers-external-only"
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
    if (-not (Test-Path -LiteralPath $MattSkillsLockPath -PathType Leaf)) {
        Stop-Install "submodules" 25 "matt-skills-lock-missing"
    }
    $mattLockText = Get-Content -Raw -LiteralPath $MattSkillsLockPath
    if ($mattLockText -notmatch '(?m)^gitlinkCommit:\s*([0-9a-f]{40})\s*$') {
        Stop-Install "submodules" 25 "matt-skills-lock-invalid"
    }
    $mattSkillsReport = [ordered]@{
        commit = $Matches[1]
        lockHash = "sha256:" + (Get-Sha256Hex $MattSkillsLockPath)
    }
    $gitlinkOutput = (& git.exe -C $RepositoryRoot ls-files --stage -- "dependencies/upstream/matt-pocock-skills" 2>&1 | Out-String).Trim()
    $gitlinkFields = @($gitlinkOutput -split '\s+')
    if (
        $LASTEXITCODE -ne 0 -or
        $gitlinkFields.Count -lt 2 -or
        $gitlinkFields[0] -ne "160000" -or
        $gitlinkFields[1] -ne $mattSkillsReport.commit
    ) {
        Stop-Install "submodules" 25 "matt-skills-gitlink-lock-mismatch"
    }

    if (-not (Test-Path -LiteralPath $GraftLockPath -PathType Leaf)) {
        Stop-Install "submodules" 25 "graft-lock-missing"
    }
    $graftLockText = Get-Content -Raw -LiteralPath $GraftLockPath
    if ($graftLockText -notmatch '(?m)^gitlinkCommit:\s*([0-9a-f]{40})\s*$') {
        Stop-Install "submodules" 25 "graft-lock-invalid"
    }
    $graftExpectedCommit = $Matches[1]
    $graftGitlinkOutput = (& git.exe -C $RepositoryRoot ls-files --stage -- "dependencies/upstream/graft" 2>&1 | Out-String).Trim()
    $graftGitlinkFields = @($graftGitlinkOutput -split '\s+')
    if (
        $LASTEXITCODE -ne 0 -or
        $graftGitlinkFields.Count -lt 2 -or
        $graftGitlinkFields[0] -ne "160000" -or
        $graftGitlinkFields[1] -ne $graftExpectedCommit
    ) {
        Stop-Install "submodules" 25 "graft-gitlink-lock-mismatch"
    }
    $graftHead = (& git.exe -C $GraftPath rev-parse HEAD 2>$null | Out-String).Trim()
    $graftTree = (& git.exe -C $GraftPath rev-parse "HEAD^{tree}" 2>$null | Out-String).Trim()
    $graftDirty = (& git.exe -C $GraftPath status --porcelain=v1 --untracked-files=all 2>$null | Out-String).Trim()
    if ($graftHead -ne $graftExpectedCommit -or $graftDirty) {
        Stop-Install "submodules" 25 "graft-source-drift"
    }

    Set-InstallStage "graft-build" 27
    Ensure-GraftBuild $graftHead $graftTree
    $graftPackage = Get-Content -Raw -LiteralPath (Join-Path $GraftPath "package.json") | ConvertFrom-Json
    if ($graftPackage.name -ne "@nanonets/graft" -or $graftPackage.version -ne "0.18.0" -or -not (Test-Path -LiteralPath (Join-Path $GraftPath "dist\cli.js") -PathType Leaf)) {
        Stop-Install "graft-build" 27 "graft-build-identity-invalid"
    }
    $graftReport = [ordered]@{
        commit = $graftHead
        tree = $graftTree
        version = $graftPackage.version
        lockHash = "sha256:" + (Get-Sha256Hex $GraftLockPath)
        runtime = "repository-submodule-built"
    }
    $graftSourceReport = Invoke-SelfWorkflow @(
        "provider", "inspect", "--graft-path", $GraftPath
    ) (Join-Path $script:LogDirectory "graft-source.json")

    if (-not (Test-Path -LiteralPath $PonytailLockPath -PathType Leaf)) {
        Stop-Install "submodules" 25 "ponytail-lock-missing"
    }
    $ponytailReport = Invoke-SelfWorkflow @(
        "source", "ponytail-verify", "--repository", $RepositoryRoot
    ) (Join-Path $script:LogDirectory "ponytail-source.json")

    Set-InstallStage "plan" 40
    $doctorBefore = Join-Path $script:LogDirectory "doctor-before.json"
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) $doctorBefore | Out-Null
    $runtime = Join-Path $script:LogDirectory "runtime"
    $runtimeManifest = Join-Path $script:LogDirectory "runtime-manifest.json"
    $buildArguments = @("build", "--repository", $RepositoryRoot, "--output", $runtime, "--version", $Version, "--profile", $Profile)
    Invoke-SelfWorkflow $buildArguments $runtimeManifest | Out-Null
    $planPath = Join-Path $script:LogDirectory "install-plan.json"
    Invoke-SelfWorkflow @("install", "plan", "--artifact", $runtime, "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot, "--version", $Version, "--output", $planPath) $null | Out-Null
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
    if ($plan.status -eq "paused") {
        Stop-Install "plan" 40 ("install-plan-paused:" + ($plan.issues -join ","))
    }
    Write-InstallLog ("Plan status: {0}; planHash: {1}" -f $plan.status, $plan.planHash)
    Write-InstallLog ("Matt Skills commit: {0}; lock: {1}" -f $mattSkillsReport.commit, $mattSkillsReport.lockHash)
    Write-InstallLog ("Graft commit: {0}; version: {1}; lock: {2}" -f $graftReport.commit, $graftReport.version, $graftReport.lockHash)
    Write-InstallLog ("Ponytail commit: {0}; lock: {1}" -f $ponytailReport.gitlinkCommit, $ponytailReport.lockHash)
    Write-InstallLog "Superpowers: external-only; not managed by SelfWorkflow."
    Write-InstallLog ("Agents root: " + $AgentsRoot)
    Write-InstallLog ("Codex root: " + $CodexRoot)
    Write-InstallLog ("State root: " + $StateRoot)
    Write-InstallLog ("Profile: {0}; Artifact files: {1}" -f $plan.profile, @($plan.artifactFiles).Count)
    Write-JsonFile (Join-Path $script:LogDirectory "confirmation-summary.json") ([ordered]@{
        planHash = $plan.planHash
        profile = $plan.profile
        artifactFiles = $plan.artifactFiles
        agentsRoot = $AgentsRoot
        codexRoot = $CodexRoot
        stateRoot = $StateRoot
        mattSkills = $mattSkillsReport
        graft = $graftReport
        graftSource = $graftSourceReport
        ponytail = $ponytailReport
        graftProvider = $graftProviderReport
        graftMcpLauncher = $graftMcpLauncherReport
        codexGraftMcp = $codexGraftMcpReport
        superpowers = "external-only"
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

    Set-InstallStage "host-cli" 74
    $hostLauncherReport = Ensure-HostLauncher $RepositoryRoot $HostLauncherPath

    Set-InstallStage "graft-mcp" 75
    $graftMcpLauncherReport = Ensure-GraftMcpLauncher $RepositoryRoot $GraftPath $GraftMcpLauncherPath
    $codexGraftMcpReport = Ensure-CodexGraftMcp $CodexGraftMcpConfigPath $GraftMcpLauncherPath

    $doctorAfter = Join-Path $script:LogDirectory "doctor-after.json"
    Invoke-SelfWorkflow @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) $doctorAfter | Out-Null

    Set-InstallStage "graft-provider-configure" 76
    $existingProviders = Invoke-SelfWorkflow @(
        "provider", "list", "--config-file", $ProviderConfigFile
    ) (Join-Path $script:LogDirectory "provider-list.json")
    $existingGraftProvider = @($existingProviders.providers | Where-Object { $_.providerId -eq "graft" })
    $verifiedGraftProvider = @($existingGraftProvider | Where-Object {
        $_.managementStatus -eq "managed-metadata-available" -and
        $_.enabled -eq $true -and
        $_.bindingHash
    })
    if ($existingGraftProvider.Count -gt 0 -and $verifiedGraftProvider.Count -eq 0) {
        Stop-Install "graft-provider-configure" 74 "graft-provider-binding-unverified"
    }
    elseif ($verifiedGraftProvider.Count -gt 0) {
        $graftProviderReport = [ordered]@{
            status = "preserved-existing-binding"
            reason = "existing-graft-binding-not-replaced"
            existing = $existingGraftProvider[0]
        }
        Write-InstallLog "Existing Graft binding preserved; explicit provider configuration is required to rebind it."
    }
    else {
        $graftRollbackToken = [Guid]::NewGuid().ToString("N")
        $graftProviderReport = Invoke-SelfWorkflow @(
            "provider", "configure",
            "--config-file", $ProviderConfigFile,
            "--graft-path", $GraftPath,
            "--expected-source-hash", $graftSourceReport.sourceHash,
            "--rollback-token", $graftRollbackToken
        ) (Join-Path $script:LogDirectory "graft-provider-configure.json")
    }

    $summary = [ordered]@{
        schemaVersion = 1
        status = "installed"
        profile = $Profile
        mattSkills = $mattSkillsReport
        graft = $graftReport
        graftSource = $graftSourceReport
        ponytail = $ponytailReport
        graftProvider = $graftProviderReport
        hostLauncher = $hostLauncherReport
        graftMcpLauncher = $graftMcpLauncherReport
        codexGraftMcp = $codexGraftMcpReport
        superpowers = "external-only"
        writeCapability = "enabled"
        manifestPath = $applyResult.manifestPath
        logDirectory = $script:LogDirectory
        nativeAgentVerification = "unverified-restart-required"
    }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") $summary
    Write-InstallLog ("Installation verification completed; finalizing transaction. Logs: " + $script:LogDirectory)
    if ($graftRollbackToken) {
        try {
            if ($env:SELFWORKFLOW_TEST_FAIL_PROVIDER_COMMIT -eq "1") {
                throw "injected-graft-provider-commit-cleanup-failure"
            }
            Invoke-SelfWorkflow @(
                "provider", "commit-config",
                "--config-file", $ProviderConfigFile,
                "--rollback-token", $graftRollbackToken
            ) (Join-Path $script:LogDirectory "graft-provider-config-commit.json") | Out-Null
            $graftRollbackToken = $null
        }
        catch {
            Write-Host "Graft provider configuration is verified; rollback-record cleanup is pending."
        }
    }
    Write-Host "Installation verified."
    Write-Host "Restart Codex before relying on newly discovered Skills."
    exit 0
}
catch {
    $failure = $_.Exception.Message
    Write-InstallLog ("FAILED [{0}]: {1}" -f $script:CurrentStage, $failure)
    $rollbackStatus = "not-required"
    try {
        if ($graftRollbackToken) {
            $graftRollback = Invoke-SelfWorkflow @(
                "provider", "rollback-config",
                "--config-file", $ProviderConfigFile,
                "--rollback-token", $graftRollbackToken,
                "--if-issued"
            ) (Join-Path $script:LogDirectory "graft-provider-config-rollback.json")
            if ($graftRollback.status -eq "rolled-back") {
                $rollbackStatus = "rolled-back"
            }
            elseif ($graftRollback.status -ne "not-issued") {
                throw "graft-provider-config-rollback-status-invalid"
            }
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
