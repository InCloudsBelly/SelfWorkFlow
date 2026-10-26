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
    [ValidateSet("ue", "official")]
    [string]$CodeGraphBackend = "ue",
    [string]$AgentsRoot = (Join-Path $env:USERPROFILE ".agents"),
    [string]$CodexRoot = (Join-Path $env:USERPROFILE ".codex"),
    [string]$DshRoot = "",
    [string]$DocumentRoot = "",
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
  Install_SelfWorkFlow.bat [-Profile core|knowledge|maintainer] [-DshRoot <dsh-home>]
  Install_SelfWorkFlow.bat -CodeGraphMcpLauncherOnly -ConfirmApply
  Install_SelfWorkFlow.bat -CodeGraphPath <local-codegraph-root> -ConfirmApply
  Install_SelfWorkFlow.bat -CodeGraphBackend ue|official -ReplaceCodeGraphOverride -ConfirmApply

An explicit -DshRoot writes the same managed bootstrap plus the DSH adapter
 section to <DshRoot>\AGENTS.md for DeepSeek Harness. Without it, the DSH
 instruction root is left untouched; after a DSH install, repeat it on upgrades.

Optional -DocumentRoot <public-root> performs a one-time migration to the stable
 public document entry and retires owned native Skill copies with drift checks.
 Ordinary document consumers do not need to run this installer.

The pinned Matt Pocock Skills foundation and the path-limited TEA, Ponytail and
other workflow submodules are prepared from the repository locks. Superpowers is external-only
and is never installed or enabled by this script.

The default CodeGraph backend is the pinned personal UE-enhanced submodule.
It is built with npm ci and npm run build; build or identity failures stop installation.
-CodeGraphBackend official explicitly selects @colbymchenry/codegraph v1.6.2.
The CodeGraph serve --mcp entry is registered with Codex. CodeGraph owns its watcher, daemon,
graph storage and process lifecycle; SelfWorkFlow owns project routing and
post-write synchronization only.

The installer shows the generated plan and requires the exact confirmation
APPLY before publishing workflow files. It writes diagnostic artifacts below
%LOCALAPPDATA%\SelfWorkFlow\logs and rolls back the workflow publication or
provider configuration if a later step fails.

An explicit -CodeGraphPath binds a local checkout or managed runtime for
testing/override. Grilling and TEA are explicit-only; Full/Deep use one combined
independent reviewer inheriting the parent model. No legacy topic graph or deep model is
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

function Read-CodeGraphLock {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Stop-Install "codegraph-runtime" 27 "codegraph-lock-missing" }
    $text = [IO.File]::ReadAllText($Path)
    $versionMatch = [regex]::Match($text, '(?m)^\s+version:\s*([^\s#]+)\s*$')
    $tagMatch = [regex]::Match($text, '(?m)^\s+releaseTag:\s*([^\s#]+)\s*$')
    $packageJsonHashMatch = [regex]::Match($text, '(?m)^\s+packageJsonHash:\s*(sha256:[0-9a-fA-F]{64})\s*$')
    $packageLockHashMatch = [regex]::Match($text, '(?m)^\s+packageLockHash:\s*(sha256:[0-9a-fA-F]{64})\s*$')
    $packageJsonUrlMatch = [regex]::Match($text, '(?m)^\s+packageJsonUrl:\s*(\S+)\s*$')
    $packageLockUrlMatch = [regex]::Match($text, '(?m)^\s+packageLockUrl:\s*(\S+)\s*$')
    $entryHashMatch = [regex]::Match($text, '(?m)^\s+entrySha256:\s*(sha256:[0-9a-fA-F]{64})\s*$')
    $assetUrlMatch = [regex]::Match($text, '(?m)^\s+windowsAssetUrl:\s*(\S+)\s*$')
    $assetHashMatch = [regex]::Match($text, '(?m)^\s+windowsAssetSha256:\s*(sha256:[0-9a-fA-F]{64})\s*$')
    if (-not ($versionMatch.Success -and $tagMatch.Success -and $packageJsonHashMatch.Success -and
            $packageLockHashMatch.Success -and $packageJsonUrlMatch.Success -and $entryHashMatch.Success -and
            $packageLockUrlMatch.Success -and $assetUrlMatch.Success -and $assetHashMatch.Success)) {
        Stop-Install "codegraph-runtime" 27 "codegraph-lock-invalid"
    }
    $lock = [ordered]@{
        version = $versionMatch.Groups[1].Value
        releaseTag = $tagMatch.Groups[1].Value
        packageJsonHash = $packageJsonHashMatch.Groups[1].Value.ToLowerInvariant()
        packageLockHash = $packageLockHashMatch.Groups[1].Value.ToLowerInvariant()
        packageJsonUrl = $packageJsonUrlMatch.Groups[1].Value
        packageLockUrl = $packageLockUrlMatch.Groups[1].Value
        entrySha256 = $entryHashMatch.Groups[1].Value.ToLowerInvariant()
        windowsAssetUrl = $assetUrlMatch.Groups[1].Value
        windowsAssetSha256 = $assetHashMatch.Groups[1].Value.ToLowerInvariant()
    }
    if ($lock.version -ne $CodeGraphVersion.TrimStart("v") -or $lock.releaseTag -ne $CodeGraphVersion) {
        Stop-Install "codegraph-runtime" 27 "codegraph-lock-version-mismatch"
    }
    $tagRoot = "https://raw.githubusercontent.com/colbymchenry/codegraph/$($lock.releaseTag)/"
    if ($lock.packageJsonUrl -ne ($tagRoot + "package.json") -or
        $lock.packageLockUrl -ne ($tagRoot + "package-lock.json") -or
        $lock.windowsAssetUrl -ne "https://github.com/colbymchenry/codegraph/releases/download/$($lock.releaseTag)/codegraph-win32-x64.zip" -or
        $lock.windowsAssetUrl -match "/main/|/latest/|/master/") {
        Stop-Install "codegraph-runtime" 27 "codegraph-lock-source-unpinned"
    }
    return $lock
}

function Download-AndVerifyFile {
    param(
        [string]$Uri,
        [string]$Destination,
        [string]$ExpectedHash,
        [string]$FailurePrefix
    )
    try { Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing }
    catch { Stop-Install "codegraph-runtime" 27 ($FailurePrefix + "-download-failed") }
    $actualHash = "sha256:" + (Get-Sha256Hex $Destination)
    if ($actualHash -ine $ExpectedHash) {
        Stop-Install "codegraph-runtime" 27 ($FailurePrefix + "-hash-mismatch")
    }
    return $actualHash
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
    param([object]$Lock)
    if ($CodeGraphPath) {
        $explicit = Resolve-FullPath $CodeGraphPath
        if (-not (Test-Path -LiteralPath $explicit -PathType Container)) { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-path-invalid" }
        if ((Test-CodeGraphCommand $explicit) -or (Test-Path -LiteralPath (Join-Path $explicit "dist\bin\codegraph.js") -PathType Leaf)) {
            return $explicit
        }
        Stop-Install "codegraph-runtime" 27 "codegraph-runtime-entry-missing"
    }

    if ($CodeGraphBackend -eq "ue") {
        $build = Invoke-SelfWorkflow @("source", "codegraph-ue-prepare", "--repository", $RepositoryRoot) (Join-Path $script:LogDirectory "codegraph-ue-build.json")
        if ($build.status -ne "built-and-verified" -or -not $build.sourcePath) {
            Stop-Install "codegraph-runtime" 27 "codegraph-ue-build-unverified"
        }
        return (Resolve-FullPath $build.sourcePath)
    }

    $installBase = Join-Path $DependencyRoot "codegraph\1.6.2"
    $current = Join-Path $installBase "current"
    if (-not (Test-CodeGraphCommand $current)) {
        $metadataRoot = Join-Path $script:LogDirectory "codegraph-lock"
        [IO.Directory]::CreateDirectory($metadataRoot) | Out-Null
        Download-AndVerifyFile $Lock.packageJsonUrl (Join-Path $metadataRoot "package.json") $Lock.packageJsonHash "codegraph-package-json" | Out-Null
        Download-AndVerifyFile $Lock.packageLockUrl (Join-Path $metadataRoot "package-lock.json") $Lock.packageLockHash "codegraph-package-lock" | Out-Null
        $archivePath = Join-Path $script:LogDirectory "codegraph-win32-x64.zip"
        Download-AndVerifyFile $Lock.windowsAssetUrl $archivePath $Lock.windowsAssetSha256 "codegraph-asset" | Out-Null
        $stageRoot = Join-Path $script:LogDirectory "codegraph-stage"
        try { Expand-Archive -LiteralPath $archivePath -DestinationPath $stageRoot -Force }
        catch { Stop-Install "codegraph-runtime" 27 "codegraph-asset-extract-failed" }
        $candidates = @([IO.DirectoryInfo]$stageRoot)
        $candidates += @(Get-ChildItem -LiteralPath $stageRoot -Directory -Recurse -Force)
        $runtimeCandidate = $candidates |
            Where-Object {
                (Test-CodeGraphCommand $_.FullName) -and
                (Test-Path -LiteralPath (Join-Path $_.FullName "node.exe") -PathType Leaf)
            } |
            Select-Object -First 1
        if ($null -eq $runtimeCandidate) { Stop-Install "codegraph-runtime" 27 "codegraph-asset-entry-missing" }
        if (Test-Path -LiteralPath $current) { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-invalid-existing" }
        [IO.Directory]::CreateDirectory($installBase) | Out-Null
        try { Move-Item -LiteralPath $runtimeCandidate.FullName -Destination $current }
        catch { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-install-failed" }
        if (-not (Test-CodeGraphCommand $current)) { Stop-Install "codegraph-runtime" 27 "codegraph-runtime-install-failed" }
    }
    return (Resolve-FullPath $current)
}

function Assert-CodeGraphRuntime {
    param([string]$Root, [object]$Lock)
    $packageCandidates = @(
        (Join-Path $Root "lib\package.json"),
        (Join-Path $Root "package.json")
    )
    $packagePath = $packageCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ($null -eq $packagePath) { Stop-Install "codegraph-runtime" 27 "codegraph-package-json-missing" }
    try { $packageValue = Get-Content -Raw -LiteralPath $packagePath | ConvertFrom-Json }
    catch { Stop-Install "codegraph-runtime" 27 "codegraph-package-json-invalid" }
    if ($packageValue.name -ne "@colbymchenry/codegraph" -or $packageValue.version -ne $Lock.version) {
        Stop-Install "codegraph-runtime" 27 "codegraph-package-identity-mismatch"
    }
    $packageHash = "sha256:" + (Get-Sha256Hex $packagePath)
    if ($packageHash -ine $Lock.packageJsonHash) { Stop-Install "codegraph-runtime" 27 "codegraph-package-json-hash-mismatch" }
    $entryCandidates = @(
        (Join-Path $Root "lib\dist\bin\codegraph.js"),
        (Join-Path $Root "dist\bin\codegraph.js")
    )
    $entryPath = $entryCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ($null -eq $entryPath) { Stop-Install "codegraph-runtime" 27 "codegraph-entry-missing" }
    $entryHash = "sha256:" + (Get-Sha256Hex $entryPath)
    if ($entryHash -ine $Lock.entrySha256) { Stop-Install "codegraph-runtime" 27 "codegraph-entry-hash-mismatch" }
    return [ordered]@{
        status = "verified"
        packageJsonHash = $packageHash
        entrySha256 = $entryHash
        version = $packageValue.version
    }
}

function Ensure-HostLauncher {
    param([string]$TargetPath)
    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) { Stop-Install "host-cli" 28 "host-cli-missing" }
    $output = (& $TargetPath --host-info 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Stop-Install "host-cli" 28 "host-cli-verify-failed" }
    $identity = $output | ConvertFrom-Json
    return [ordered]@{ status = "installed"; path = $TargetPath; artifactHash = $identity.artifactHash; snapshot = $identity.snapshot }
}

function Get-McpBytesHash {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Assert-McpFilePath {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -Force -LiteralPath $current
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "mcp-file-reparse-path" }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
    if (Test-Path -LiteralPath $Path -PathType Container) { throw "mcp-file-path-conflict" }
}

function Get-McpFileHash {
    param([string]$Path)
    Assert-McpFilePath $Path
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return Get-Sha256Hex $Path }
    return "missing"
}

function Get-McpFileState {
    param([string]$Path)
    $Path = [IO.Path]::GetFullPath($Path)
    if ($script:McpFileStates.ContainsKey($Path)) { return $script:McpFileStates[$Path] }
    Assert-McpFilePath $Path
    $exists = [IO.File]::Exists($Path)
    $bytes = [byte[]]@()
    if ($exists) { $bytes = [IO.File]::ReadAllBytes($Path) }
    $beforeHash = if ($exists) { Get-McpBytesHash $bytes } else { "missing" }
    $backup = Join-Path $script:LogDirectory ("mcp-before-" + [Guid]::NewGuid().ToString("N") + ".bin")
    if ($exists) { [IO.File]::WriteAllBytes($backup, $bytes) }
    $state = @{ Path = $Path; BeforeExists = $exists; BeforeBytes = $bytes; BeforeHash = $beforeHash;
        BackupPath = $backup; AfterHash = $null; Written = $false; Unverified = $false }
    $script:McpFileStates[$Path] = $state
    Save-McpFileJournal
    return $state
}

function Save-McpFileJournal {
    $records = @($script:McpFileStates.Values | ForEach-Object {
        [ordered]@{ path = $_.Path; beforeHash = $_.BeforeHash; backupPath = $_.BackupPath;
            afterHash = $_.AfterHash; written = $_.Written; unverified = $_.Unverified }
    })
    Write-JsonFile (Join-Path $script:LogDirectory "mcp-file-state.json") $records
}

function Write-McpStage {
    param([string]$Path, [byte[]]$Bytes)
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}

function Set-McpFileBytes {
    param([hashtable]$State, [byte[]]$Bytes, [int]$RecoveryBudget = 1)
    $path = $State.Path
    $expected = if ($State.Written) { $State.AfterHash } else { $State.BeforeHash }
    $desired = Get-McpBytesHash $Bytes
    $lockId = Get-McpBytesHash ([Text.Encoding]::UTF8.GetBytes($path.ToLowerInvariant()))
    $mutex = [Threading.Mutex]::new($false, "Local\SelfWorkFlow-Mcp-" + $lockId)
    $held = $false
    $temporary = $null
    $captured = $null
    $discardCaptured = $false
    $commitAttempted = $false
    try {
        try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw "mcp-file-busy" }
        if ((Get-McpFileHash $path) -ne $expected) { throw "mcp-file-precondition-conflict" }
        if ($desired -eq $expected) { return }
        $parent = [IO.Path]::GetDirectoryName($path)
        [IO.Directory]::CreateDirectory($parent) | Out-Null
        $temporary = Join-Path $parent (".selfworkflow-mcp-" + [Guid]::NewGuid().ToString("N") + ".tmp")
        $captured = Join-Path $parent (".selfworkflow-mcp-" + [Guid]::NewGuid().ToString("N") + ".before")
        Write-McpStage $temporary $Bytes
        if ((Get-McpFileHash $path) -ne $expected) { throw "mcp-file-precondition-conflict" }
        $commitAttempted = $true
        if ($expected -eq "missing") { [IO.File]::Move($temporary, $path) }
        else { [IO.File]::Replace($temporary, $path, $captured) }
        $State.AfterHash = $desired
        $State.Written = $true
        if ([IO.File]::Exists($captured) -and (Get-Sha256Hex $captured) -ne $expected) {
            $State.BeforeBytes = [IO.File]::ReadAllBytes($captured)
            $State.BeforeHash = Get-McpBytesHash $State.BeforeBytes
            $State.BeforeExists = $true
            $State.BackupPath = Join-Path $script:LogDirectory ("mcp-conflict-" + [Guid]::NewGuid().ToString("N") + ".bin")
            [IO.File]::Copy($captured, $State.BackupPath)
            $discardCaptured = $true
            Save-McpFileJournal
            if ($RecoveryBudget -gt 0) { Set-McpFileBytes $State $State.BeforeBytes ($RecoveryBudget - 1) }
            throw "mcp-file-precondition-conflict"
        }
        $discardCaptured = $true
        Save-McpFileJournal
    }
    catch {
        if ($commitAttempted -and -not $State.Written -and (Get-McpFileHash $path) -ne $expected) {
            $State.Unverified = $true
        }
        throw
    }
    finally {
        if ($temporary -and [IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
        if ($discardCaptured -and $captured -and [IO.File]::Exists($captured)) { [IO.File]::Delete($captured) }
        if ($held) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Restore-McpFiles {
    $failed = $false
    $restored = $false
    foreach ($state in @($script:McpFileStates.Values)) {
        if ($state.Unverified) { $failed = $true; continue }
        if (-not $state.Written) { continue }
        try {
            if ($state.BeforeExists) { Set-McpFileBytes $state $state.BeforeBytes }
            else {
                if ((Get-McpFileHash $state.Path) -ne $state.AfterHash) { throw "mcp-file-rollback-conflict" }
                $holding = $state.Path + ".rollback-" + [Guid]::NewGuid().ToString("N")
                [IO.File]::Move($state.Path, $holding)
                if ((Get-Sha256Hex $holding) -ne $state.AfterHash) {
                    if (-not [IO.File]::Exists($state.Path)) { [IO.File]::Move($holding, $state.Path) }
                    throw "mcp-file-rollback-conflict"
                }
                [IO.File]::Delete($holding)
            }
            $state.Written = $false
            $restored = $true
        }
        catch { $failed = $true; Write-InstallLog ("MCP ROLLBACK FAILED: " + $_.Exception.Message) }
    }
    Save-McpFileJournal
    if ($failed) { throw "mcp-file-rollback-failed" }
    if ($restored) { return "rolled-back" }
    return "not-required"
}

function Ensure-CodeGraphMcpLauncher {
    param([string]$RuntimeRoot, [string]$TargetPath, [string[]]$CommandPrefix)
    if ($CommandPrefix.Count -lt 2 -or -not (Test-Path -LiteralPath $CommandPrefix[0] -PathType Leaf) -or
        -not (Test-Path -LiteralPath $CommandPrefix[-1] -PathType Leaf)) {
        Stop-Install "codegraph-mcp" 28 "codegraph-mcp-entry-missing"
    }
    $prefix = (@($CommandPrefix | ForEach-Object { '"' + $_.Replace('%', '%%').Replace('"', '""') + '"' }) -join " ")
    $directMode = ""
    if ($RuntimeRoot.Replace('/', '\').TrimEnd('\').EndsWith('\extensions\codegraph\codegraph_ue', [StringComparison]::OrdinalIgnoreCase)) {
        # shortcut: shared package versions cannot identify fork daemons; retire when the daemon handshake binds builds.
        $directMode = 'set "CODEGRAPH_NO_DAEMON=1"' + "`r`n" +
            'if not defined CODEGRAPH_WATCHDOG_TIMEOUT_MS set "CODEGRAPH_WATCHDOG_TIMEOUT_MS=600000"'
    }
    $parent = Split-Path -Parent $TargetPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $content = @"
@echo off
setlocal DisableDelayedExpansion
for /f "tokens=2 delims=:" %%p in ('chcp') do set "SELFWORKFLOW_CODEGRAPH_CODEPAGE=%%p"
chcp 65001 >nul
$directMode
$prefix %*
set "SELFWORKFLOW_CODEGRAPH_EXIT=%ERRORLEVEL%"
if defined SELFWORKFLOW_CODEGRAPH_CODEPAGE chcp %SELFWORKFLOW_CODEGRAPH_CODEPAGE% >nul
exit /b %SELFWORKFLOW_CODEGRAPH_EXIT%
"@.TrimStart("`r", "`n") + "`r`n"
    try { Set-McpFileBytes (Get-McpFileState $TargetPath) ([Text.UTF8Encoding]::new($false).GetBytes($content)) }
    catch { Stop-Install "codegraph-mcp" 28 "codegraph-mcp-write-failed" }
    return [ordered]@{ status = "installed"; path = $TargetPath; runtimeRoot = $RuntimeRoot }
}

function Ensure-CodexCodeGraphMcp {
    param([string]$CodexConfigPath, [string]$LauncherPath, [string]$RuntimeRoot = "")
    $parent = Split-Path -Parent $CodexConfigPath
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $begin = "# selfworkflow:codegraph-mcp:begin"
    $end = "# selfworkflow:codegraph-mcp:end"
    $timeoutSettings = ""
    if ($RuntimeRoot.Replace('/', '\').TrimEnd('\').EndsWith('\extensions\codegraph\codegraph_ue', [StringComparison]::OrdinalIgnoreCase)) {
        # Large UE graphs legitimately spend over a minute checking their inputs.
        $timeoutSettings = "`r`nstartup_timeout_sec = 600`r`ntool_timeout_sec = 1200"
    }
    $section = @"
$begin
[mcp_servers.codegraph]
command = "$($LauncherPath.Replace('\', '\\').Replace('"', '\"'))"
# official command: codegraph serve --mcp
args = ["serve", "--mcp"]$timeoutSettings
$end
"@.Trim("`r", "`n")
    $state = Get-McpFileState $CodexConfigPath
    $existing = if ($state.BeforeExists) { [Text.Encoding]::UTF8.GetString($state.BeforeBytes).TrimStart([char]0xFEFF) } else { "" }
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
    $bytes = $state.BeforeBytes
    if ($updated -ne $existing) { $bytes = [Text.UTF8Encoding]::new($false).GetBytes($updated) }
    try { Set-McpFileBytes $state $bytes }
    catch { Stop-Install "codegraph-mcp" 28 "codex-codegraph-mcp-write-failed" }
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
$DshRoot = if ([string]::IsNullOrWhiteSpace($DshRoot)) { "" } else { Resolve-FullPath $DshRoot }
$DshArguments = if ($DshRoot) { @("--dsh-root", $DshRoot) } else { @() }
$DocumentArguments = if ([string]::IsNullOrWhiteSpace($DocumentRoot)) { @() } else { @("--document-root", (Resolve-FullPath $DocumentRoot)) }
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
$script:McpFileStates = @{}

try {
    Write-InstallLog ("SelfWorkFlow repository: " + $RepositoryRoot)
    if ($env:OS -ne "Windows_NT") { Stop-Install "preflight" 20 "windows-required" }
    if (-not (Get-Command "git.exe" -ErrorAction SilentlyContinue)) { Stop-Install "preflight" 20 "git-required" }
    if ($SuperpowersChoice -ne "Skip") { Stop-Install "preflight" 20 "superpowers-external-only" }
    $codeGraphLock = Read-CodeGraphLock $CodeGraphLockPath
    $script:PythonExecutable = Ensure-RepositoryEnvironment

    Set-InstallStage "codegraph-runtime" 27
    $providerBeforeHash = if (Test-Path -LiteralPath $ProviderConfigFile -PathType Leaf) { Get-Sha256Hex $ProviderConfigFile } else { "missing" }
    $existing = Invoke-SelfWorkflow @("provider", "list", "--config-file", $ProviderConfigFile) (Join-Path $script:LogDirectory "provider-list-before.json")
    $existingCodeGraph = @($existing.providers | Where-Object { $_.providerId -eq "codegraph" -and $_.managementStatus -eq "managed-metadata-available" })
    $existingUserLocal = @($existingCodeGraph | Where-Object { $_.ownership -eq "user-local" })
    $preserveSource = ($existingUserLocal.Count -gt 0 -and -not $ReplaceCodeGraphOverride) -or ($CodeGraphMcpLauncherOnly -and $existingCodeGraph.Count -gt 0)
    if ($preserveSource) {
        $providerDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $ProviderConfigFile | ConvertFrom-Json
        $sourceEntry = @($providerDocument.providers | Where-Object { $_.providerId -eq "codegraph" })[0]
        if ($sourceEntry.bindingHash -ne $existingCodeGraph[0].bindingHash -or (Get-Sha256Hex $ProviderConfigFile) -ne $providerBeforeHash) {
            Stop-Install "codegraph-runtime" 27 "provider-config-precondition-conflict"
        }
        $runtimeRoot = $sourceEntry.sourcePath
        $codeGraphVerification = [ordered]@{ status = "preserved-user-local-override"; path = $runtimeRoot; lock = "not-applied-to-preserved-source" }
    }
    else { $runtimeRoot = Ensure-CodeGraphRuntime $codeGraphLock }
    if (-not $preserveSource -and $CodeGraphPath) {
        $codeGraphVerification = [ordered]@{
            status = "explicit-local-override"
            path = $runtimeRoot
            lock = "not-applied-to-user-override"
        }
    }
    elseif (-not $preserveSource -and $CodeGraphBackend -eq "ue") {
        $codeGraphVerification = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $script:LogDirectory "codegraph-ue-build.json") | ConvertFrom-Json
    }
    elseif (-not $preserveSource) {
        $codeGraphVerification = Assert-CodeGraphRuntime $runtimeRoot $codeGraphLock
    }
    $runtimeReport = Invoke-SelfWorkflow @("provider", "inspect", "--codegraph-path", $runtimeRoot) (Join-Path $script:LogDirectory "codegraph-source.json")
    if (-not $runtimeReport.sourceHash) { Stop-Install "codegraph-runtime" 27 "codegraph-source-unverified" }

    if ($CodeGraphMcpLauncherOnly) {
        if (-not $ConfirmApply) { Stop-Install "confirmation" 50 "explicit-apply-confirmation-required" }
        Get-McpFileState $CodeGraphMcpLauncherPath | Out-Null
        Get-McpFileState $CodexCodeGraphMcpConfigPath | Out-Null
        Set-InstallStage "codegraph-mcp-launcher-only" 75
        $launcherReport = Ensure-CodeGraphMcpLauncher $runtimeRoot $CodeGraphMcpLauncherPath $runtimeReport.commandPrefix
        $codexReport = Ensure-CodexCodeGraphMcp $CodexCodeGraphMcpConfigPath $CodeGraphMcpLauncherPath $runtimeRoot
        if ($preserveSource -and (Get-McpFileHash $ProviderConfigFile) -ne $providerBeforeHash) {
            Stop-Install "codegraph-mcp" 75 "provider-config-precondition-conflict"
        }
        Write-JsonFile (Join-Path $script:LogDirectory "summary.json") ([ordered]@{
            schemaVersion = 1; status = "launcher-only"; codegraphMcpLauncher = $launcherReport
            codexCodeGraphMcp = $codexReport; logDirectory = $script:LogDirectory
        })
        Write-Host "CodeGraph MCP launcher updated."
        exit 0
    }

    Set-InstallStage "submodules" 25
    $submoduleExit = Invoke-NativeLogged $script:PythonExecutable @(
        "-m", "selfworkflow.v3.submodule_profiles", "--repository", $RepositoryRoot, "--profile", "normal", "--runtime-profile", $Profile
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
    $doctorBeforeArguments = @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) + $DshArguments
    Invoke-SelfWorkflow $doctorBeforeArguments $doctorBefore | Out-Null
    $runtime = Join-Path $script:LogDirectory "runtime"
    $runtimeManifest = Join-Path $script:LogDirectory "runtime-manifest.json"
    Invoke-SelfWorkflow @("build", "--repository", $RepositoryRoot, "--output", $runtime, "--version", $Version, "--profile", $Profile) $runtimeManifest | Out-Null
    $planPath = Join-Path $script:LogDirectory "install-plan.json"
    $planArguments = @("install", "plan", "--artifact", $runtime, "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot, "--version", $Version, "--host-launcher", $HostLauncherPath, "--host-python", $script:PythonExecutable, "--output", $planPath) + $DshArguments
    Invoke-SelfWorkflow ($planArguments + $DocumentArguments) $null | Out-Null
    $plan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
    if ($plan.status -eq "paused") { Stop-Install "plan" 40 ("install-plan-paused:" + ($plan.issues -join ",")) }
    Write-InstallLog ("Plan status: {0}; planHash: {1}" -f $plan.status, $plan.planHash)
    Write-InstallLog ("CodeGraph source: {0}; version: {1}" -f $runtimeReport.sourceHash, $runtimeReport.version)
    Write-InstallLog ("Ponytail commit: {0}; lock: {1}" -f $ponytailReport.gitlinkCommit, $ponytailReport.lockHash)
    Write-JsonFile (Join-Path $script:LogDirectory "confirmation-summary.json") ([ordered]@{
        planHash = $plan.planHash; profile = $plan.profile; artifactFiles = $plan.artifactFiles
        agentsRoot = $AgentsRoot; codexRoot = $CodexRoot; dshRoot = $DshRoot; stateRoot = $StateRoot
        codegraph = $runtimeReport; codegraphLock = $codeGraphVerification
        ponytail = $ponytailReport; superpowers = "external-only"
    })

    Set-InstallStage "confirmation" 50
    if (-not $ConfirmApply) {
        if ($NonInteractive) { Stop-Install "confirmation" 50 "explicit-apply-confirmation-required" }
        if ((Read-Host "Type APPLY to publish this exact plan and dependency hashes") -cne "APPLY") { Stop-Install "confirmation" 50 "installation-cancelled" }
    }

    Get-McpFileState $CodeGraphMcpLauncherPath | Out-Null
    Get-McpFileState $CodexCodeGraphMcpConfigPath | Out-Null
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
    $launcherReport = Ensure-CodeGraphMcpLauncher $runtimeRoot $CodeGraphMcpLauncherPath $runtimeReport.commandPrefix
    $codexReport = Ensure-CodexCodeGraphMcp $CodexCodeGraphMcpConfigPath $CodeGraphMcpLauncherPath $runtimeRoot
    $doctorAfterArguments = @("doctor", "--agents-root", $AgentsRoot, "--codex-root", $CodexRoot, "--state-root", $StateRoot) + $DshArguments
    Invoke-SelfWorkflow $doctorAfterArguments (Join-Path $script:LogDirectory "doctor-after.json") | Out-Null

    $wikiReport = [ordered]@{ status = "not-selected" }
    if ($Profile -eq "knowledge") {
        Set-InstallStage "wiki-mcp" 76
        $wikiSource = Invoke-SelfWorkflow @("wiki", "inspect", "--repository", $RepositoryRoot) (Join-Path $script:LogDirectory "wiki-source.json")
        $wikiStorage = Join-Path $env:LOCALAPPDATA "SelfOpenWiki\config.json"
        if ($wikiSource.status -eq "source-ready" -and (Test-Path -LiteralPath $wikiStorage -PathType Leaf)) {
            $wikiPlan = Invoke-SelfWorkflow @("wiki", "register", "--repository", $RepositoryRoot, "--config", $CodexCodeGraphMcpConfigPath) (Join-Path $script:LogDirectory "wiki-registration-plan.json")
            $wikiState = Get-McpFileState $CodexCodeGraphMcpConfigPath
            $expectedBefore = if ($wikiState.Written) { $wikiState.AfterHash } else { $wikiState.BeforeHash }
            $expectedPlanBefore = if ($expectedBefore -eq "missing") { Get-McpBytesHash ([byte[]]@()) } else { $expectedBefore }
            if ($wikiPlan.beforeConfigHash -ne ("sha256:" + $expectedPlanBefore)) { throw "wiki-host-config-precondition-conflict" }
            try {
                $wikiReport = Invoke-SelfWorkflow @("wiki", "register", "--repository", $RepositoryRoot, "--config", $CodexCodeGraphMcpConfigPath, "--confirm-plan-hash", $wikiPlan.planHash) (Join-Path $script:LogDirectory "wiki-registration-result.json")
            }
            finally {
                $currentHash = Get-McpFileHash $CodexCodeGraphMcpConfigPath
                if (("sha256:" + $currentHash) -eq $wikiPlan.afterConfigHash) {
                    if ($currentHash -ne $expectedBefore) {
                        $wikiState.AfterHash = $currentHash
                        $wikiState.Written = $true
                    }
                }
                elseif ($currentHash -ne $expectedBefore) { $wikiState.Unverified = $true }
                Save-McpFileJournal
            }
        } else {
            $wikiReport = [ordered]@{ status = "setup-or-binding-required"; sourceStatus = $wikiSource.status; nextStep = "Manage_SelfWorkFlow_Wiki.bat install, then selfworkflow wiki register and wiki doctor" }
        }
    }

    Set-InstallStage "codegraph-provider-configure" 76
    $providerCurrentHash = if (Test-Path -LiteralPath $ProviderConfigFile -PathType Leaf) { Get-Sha256Hex $ProviderConfigFile } else { "missing" }
    if ($providerCurrentHash -ne $providerBeforeHash) { Stop-Install "codegraph-provider-configure" 76 "provider-config-precondition-conflict" }
    $existing = Invoke-SelfWorkflow @("provider", "list", "--config-file", $ProviderConfigFile) (Join-Path $script:LogDirectory "provider-list.json")
    $existingCodeGraph = @($existing.providers | Where-Object { $_.providerId -eq "codegraph" -and $_.managementStatus -eq "managed-metadata-available" })
    $existingUserLocal = @($existingCodeGraph | Where-Object { $_.ownership -eq "user-local" })
    if ($preserveSource) {
        if ($existingUserLocal.Count -ne 1 -or $existingUserLocal[0].bindingHash -ne $sourceEntry.bindingHash) {
            Stop-Install "codegraph-provider-configure" 76 "provider-config-precondition-conflict"
        }
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
        $receiptPath = Join-Path (Split-Path -Parent $ProviderConfigFile) (".provider-transactions/" + $codeGraphRollbackToken + ".json")
        Assert-McpFilePath $receiptPath
        $receipt = Get-Content -Raw -Encoding UTF8 -LiteralPath $receiptPath | ConvertFrom-Json
        $expectedPreimage = if ($providerBeforeHash -eq "missing") { "missing" } else { "sha256:" + $providerBeforeHash }
        if ($receipt.rollbackToken -ne $codeGraphRollbackToken -or $receipt.state -ne "applied" -or
            $receipt.preimageHash -ne $expectedPreimage) {
            Stop-Install "codegraph-provider-configure" 76 "provider-config-precondition-conflict"
        }
    }
    Invoke-SelfWorkflow @("provider", "retire", "--config-file", $ProviderConfigFile, "--provider-id", "graft") (Join-Path $script:LogDirectory "legacy-provider-retire.json") | Out-Null
    Remove-LegacyState $ProviderConfigFile

    $summary = [ordered]@{
        schemaVersion = 1; status = "installed"; profile = $Profile
        cleanupPending = $cleanupPending
        codegraph = $runtimeReport; codegraphLock = $codeGraphVerification; codegraphProvider = $providerReport
        hostLauncher = $hostReport; codegraphMcpLauncher = $launcherReport
        codexCodeGraphMcp = $codexReport; wikiModule = $wikiReport; ponytail = $ponytailReport
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
    $rollbackFailed = $false
    try {
        $mcpRollback = Restore-McpFiles
        if ($mcpRollback -eq "rolled-back") { $rollbackStatus = "rolled-back" }
    }
    catch { $rollbackFailed = $true; Write-InstallLog ("MCP ROLLBACK FAILED: " + $_.Exception.Message) }
    try {
        if ($codeGraphRollbackToken) {
            $rollback = Invoke-SelfWorkflow @("provider", "rollback-config", "--config-file", $ProviderConfigFile, "--rollback-token", $codeGraphRollbackToken, "--if-issued") (Join-Path $script:LogDirectory "codegraph-provider-rollback.json")
            if ($rollback.status -eq "rolled-back") { $rollbackStatus = "rolled-back" }
        }
    }
    catch { $rollbackFailed = $true; Write-InstallLog ("PROVIDER ROLLBACK FAILED: " + $_.Exception.Message) }
    try {
        if ($applyResult -and $applyResult.status -eq "applied") {
            $rollbackPlanPath = Join-Path $script:LogDirectory "rollback-plan.json"
            Invoke-SelfWorkflow @("install", "rollback-plan", "--transaction", $applyResult.transactionPath, "--output", $rollbackPlanPath) $null | Out-Null
            $rollbackPlan = Get-Content -Raw -LiteralPath $rollbackPlanPath | ConvertFrom-Json
            Invoke-SelfWorkflow @("install", "rollback", "--plan", $rollbackPlanPath, "--confirm-plan-hash", $rollbackPlan.planHash) (Join-Path $script:LogDirectory "rollback-result.json") | Out-Null
            $rollbackStatus = "rolled-back"
        }
    }
    catch {
        $rollbackFailed = $true
        Write-InstallLog ("ROLLBACK FAILED: " + $_.Exception.Message)
    }
    if ($rollbackFailed) { $rollbackStatus = "failed"; $script:FailureExitCode = 80 }
    Write-JsonFile (Join-Path $script:LogDirectory "summary.json") ([ordered]@{
        schemaVersion = 1; status = "failed"; stage = $script:CurrentStage
        cleanupPending = $cleanupPending
        reason = $failure; rollback = $rollbackStatus; logDirectory = $script:LogDirectory
    })
    Write-Host ("Installation failed. Diagnostic log: " + $script:LogDirectory)
    exit $script:FailureExitCode
}
