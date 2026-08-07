Set-StrictMode -Version Latest

function Get-SelfWorkflowStreamSha256 {
    param([Parameter(Mandatory = $true)][IO.Stream]$Stream)

    $Stream.Position = 0
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $Hash = $Hasher.ComputeHash($Stream)
    }
    finally {
        $Hasher.Dispose()
    }
    $Stream.Position = 0
    return "sha256:$(([BitConverter]::ToString($Hash)).Replace('-', '').ToLowerInvariant())"
}

function Open-SelfWorkflowFileIdentity {
    param([Parameter(Mandatory = $true)][string]$Path)

    $CanonicalPath = [IO.Path]::GetFullPath($Path)
    $Stream = [IO.FileStream]::new(
        $CanonicalPath,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        return [pscustomobject]@{
            path = $CanonicalPath
            sha256 = Get-SelfWorkflowStreamSha256 $Stream
            lock = $Stream
        }
    }
    catch {
        $Stream.Dispose()
        throw
    }
}

function Get-SelfWorkflowTreeSnapshot {
    param([Parameter(Mandatory = $true)][string]$Root)

    $Root = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    $Items = @((Get-Item -LiteralPath $Root -Force)) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse)
    $Inventory = @($Items | ForEach-Object {
        $FullName = [IO.Path]::GetFullPath($_.FullName)
        if (
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not ($FullName.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
                $FullName.StartsWith($Root + "\", [StringComparison]::OrdinalIgnoreCase))
        ) { throw "Tree inventory escaped or contains a reparse point." }
        $Hash = $null
        if (-not $_.PSIsContainer) {
            $Identity = Open-SelfWorkflowFileIdentity $FullName
            try { $Hash = $Identity.sha256 } finally { $Identity.lock.Dispose() }
        }
        [ordered]@{
            path = if ($FullName -eq $Root) { "." } else { $FullName.Substring($Root.Length + 1).Replace("\", "/") }
            type = if ($_.PSIsContainer) { "directory" } else { "file" }
            sha256 = $Hash
        }
    } | Sort-Object { $_["path"] })
    if (@($Items | Where-Object {
        $Current = [IO.FileInfo]::new($_.FullName); -not $_.PSIsContainer -and (-not $Current.Exists -or $Current.Length -ne $_.Length -or $Current.LastWriteTimeUtc -ne $_.LastWriteTimeUtc)
    }).Count) { throw "Tree changed while hashing." }
    return [pscustomobject]@{
        root = $Root; inventory = $Inventory
        treeHash = "sha256:$(Get-SelfWorkflowSha256Text (ConvertTo-SelfWorkflowCanonicalJson $Inventory 8))"
    }
}

function Test-SelfWorkflowPathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $LeftPath = [IO.Path]::GetFullPath($Left).TrimEnd("\")
    $RightPath = [IO.Path]::GetFullPath($Right).TrimEnd("\")
    return (
        $LeftPath.Equals($RightPath, [StringComparison]::OrdinalIgnoreCase) -or
        $LeftPath.StartsWith($RightPath + "\", [StringComparison]::OrdinalIgnoreCase) -or
        $RightPath.StartsWith($LeftPath + "\", [StringComparison]::OrdinalIgnoreCase)
    )
}

function Open-SelfWorkflowToolchainContext {
    param([string]$Root, $Plan)

    if ($null -ne $Plan) {
        $Root = [string]$Plan.execution.toolchain.root
    }
    $Root = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    $ExpectedNode = Join-Path $Root "node.exe"
    $ExpectedNpmCli = Join-Path $Root "node_modules\npm\bin\npm-cli.js"
    if ($null -ne $Plan) {
        $BootstrapRoot = [IO.Path]::GetFullPath([string]$Plan.bootstrapRoot).TrimEnd("\")
        $AllowedRoot = [IO.Path]::GetFullPath(
            (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli")
        ).TrimEnd("\")
        if (
            $Root -cne [string]$Plan.execution.toolchain.root -or
            $Plan.execution.node.path -cne $ExpectedNode -or
            $Plan.execution.npmCli.path -cne $ExpectedNpmCli -or
            $BootstrapRoot -cne [string]$Plan.bootstrapRoot -or
            -not ($BootstrapRoot.Equals($AllowedRoot, [StringComparison]::OrdinalIgnoreCase) -or
                $BootstrapRoot.StartsWith($AllowedRoot + "\", [StringComparison]::OrdinalIgnoreCase)) -or
            (Test-SelfWorkflowPathsOverlap $Root $BootstrapRoot) -or
            (Test-SelfWorkflowPathsOverlap $Root $Plan.sideEffects.cachePath) -or
            (Test-SelfWorkflowPathsOverlap $Root $Plan.execution.trustedCwd)
        ) {
            throw "Planned paths are unsafe."
        }
    }

    $DirectoryLocks = $null
    $NodeIdentity = $null
    $NpmIdentity = $null
    try {
        $Initial = Get-SelfWorkflowToolchainInventory `
            -LocalAppData $env:LOCALAPPDATA -ToolchainRoot $Root
        Initialize-SelfWorkflowPathLockType
        $DirectoryLocks = [SelfWorkflowPathLockSet]::new($env:LOCALAPPDATA)
        $DirectoryLocks.Refresh($Root)
        $Current = Get-SelfWorkflowToolchainInventory `
            -LocalAppData $env:LOCALAPPDATA -ToolchainRoot $Root
        $NodeIdentity = Open-SelfWorkflowFileIdentity $ExpectedNode
        $NpmIdentity = Open-SelfWorkflowFileIdentity $ExpectedNpmCli
        if ($Initial.treeHash -cne $Current.treeHash) {
            throw "Toolchain identity changed."
        }
        if ($null -ne $Plan) {
            $ExpectedInventory = ConvertTo-SelfWorkflowCanonicalJson $Plan.execution.toolchain.inventory 10
            $CurrentInventory = ConvertTo-SelfWorkflowCanonicalJson $Current.inventory 10
            if (
                $Current.treeHash -cne $Plan.execution.toolchain.treeHash -or
                $CurrentInventory -cne $ExpectedInventory -or
                $NodeIdentity.sha256 -cne $Plan.execution.node.sha256 -or
                $NpmIdentity.sha256 -cne $Plan.execution.npmCli.sha256 -or
                $Current.anchor -cne $Plan.security.toolchainAnchor
            ) {
                throw "Toolchain identity changed."
            }
        }
        $Context = [pscustomobject]@{
            directories = $DirectoryLocks
            node = $NodeIdentity
            npmCli = $NpmIdentity
            root = $Current.root
            anchor = $Current.anchor
            inventory = $Current.inventory
            treeHash = $Current.treeHash
        }
        $Context | Add-Member ScriptMethod Dispose {
            $this.npmCli.lock.Dispose()
            $this.node.lock.Dispose()
            $this.directories.Dispose()
        }
        return $Context
    }
    catch {
        if ($null -ne $NpmIdentity) { $NpmIdentity.lock.Dispose() }
        if ($null -ne $NodeIdentity) { $NodeIdentity.lock.Dispose() }
        if ($null -ne $DirectoryLocks) { $DirectoryLocks.Dispose() }
        throw
    }
}

function Resolve-SelfWorkflowRegistry {
    param([Parameter(Mandatory = $true)][string]$Registry)

    $Uri = [System.Uri]::new($Registry, [System.UriKind]::Absolute)
    if (
        $Uri.Scheme -cne "https" -or -not $Uri.Host -or $Uri.UserInfo -or
        $Uri.Query -or $Uri.Fragment
    ) {
        throw "Registry is unsafe."
    }
    $Builder = [System.UriBuilder]::new($Uri)
    if (-not $Builder.Path.EndsWith("/", [StringComparison]::Ordinal)) {
        $Builder.Path += "/"
    }
    return $Builder.Uri.AbsoluteUri
}

function Assert-SelfWorkflowSafeAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Acl = Get-Acl -LiteralPath $Path
    $CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $SystemSid = "S-1-5-18"
    $OwnerSid = $Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($OwnerSid -notin @($CurrentSid, $SystemSid)) {
        throw "Unsafe owner."
    }
    $DangerousRights = [int](
        [Security.AccessControl.FileSystemRights]::WriteData -bor
        [Security.AccessControl.FileSystemRights]::AppendData -bor
        [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
        [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [Security.AccessControl.FileSystemRights]::TakeOwnership
    )
    $Rules = @($Acl.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ))
    foreach ($Rule in $Rules) {
        if ($Rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            throw "Unverifiable deny rule."
        }
        if (
            $Rule.IdentityReference.Value -notin @($CurrentSid, $SystemSid) -and
            (([int]$Rule.FileSystemRights -band $DangerousRights) -ne 0)
        ) {
            throw "Unsafe access rule."
        }
    }
    return [pscustomobject]@{
        ownerSid = $OwnerSid
        daclSddl = $Acl.GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Access
        )
    }
}

function Get-SelfWorkflowToolchainInventory {
    param(
        [Parameter(Mandatory = $true)][string]$LocalAppData,
        [Parameter(Mandatory = $true)][string]$ToolchainRoot
    )

    $CanonicalLocalAppData = [IO.Path]::GetFullPath($LocalAppData).TrimEnd("\")
    $Anchor = [IO.Path]::GetFullPath(
        (Join-Path $CanonicalLocalAppData "SelfWorkFlow\bootstrap\toolchains")
    ).TrimEnd("\")
    $Root = [IO.Path]::GetFullPath($ToolchainRoot).TrimEnd("\")
    $Prefix = $Anchor + [IO.Path]::DirectorySeparatorChar
    if (
        -not [IO.Path]::IsPathRooted($ToolchainRoot) -or
        -not [IO.Directory]::Exists($Anchor) -or
        -not [IO.Directory]::Exists($Root) -or
        -not $Root.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Toolchain path is outside the anchor."
    }

    $Current = [IO.DirectoryInfo]::new($Root)
    $ReachedLocalAppData = $false
    while ($null -ne $Current) {
        if (($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Toolchain chain contains a reparse point."
        }
        $null = Assert-SelfWorkflowSafeAcl -Path $Current.FullName
        if ($Current.FullName.TrimEnd("\").Equals(
            $CanonicalLocalAppData,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $ReachedLocalAppData = $true
            break
        }
        $Current = $Current.Parent
    }
    if (-not $ReachedLocalAppData) {
        throw "Toolchain chain escaped LocalAppData."
    }

    $Inventory = @((Get-SelfWorkflowTreeSnapshot $Root).inventory | ForEach-Object {
        $Security = Assert-SelfWorkflowSafeAcl -Path $(if ($_.path -eq ".") { $Root } else { Join-Path $Root $_.path })
        [ordered]@{
            path = $_.path; type = $_.type; sha256 = $_.sha256
            ownerSid = $Security.ownerSid; daclSddl = $Security.daclSddl
        }
    })
    return [pscustomobject]@{
        root = $Root
        anchor = $Anchor
        inventory = $Inventory
        treeHash = "sha256:$(Get-SelfWorkflowSha256Text (ConvertTo-SelfWorkflowCanonicalJson $Inventory 8))"
    }
}

function ConvertTo-SelfWorkflowProcessArguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return (($Arguments | ForEach-Object {
        if ($_ -notmatch '[\s"]') { $_ } else {
            '"' + ([regex]::Replace($_, '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
        }
    }) -join " ")
}

function Invoke-SelfWorkflowNodeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][Collections.IDictionary]$Environment
    )

    $StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $NodePath
    $StartInfo.Arguments = ConvertTo-SelfWorkflowProcessArguments $Arguments
    $StartInfo.WorkingDirectory = $WorkingDirectory
    $StartInfo.UseShellExecute = $false
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.CreateNoWindow = $true
    $StartInfo.EnvironmentVariables.Clear()
    foreach ($Name in $Environment.Keys) {
        $StartInfo.EnvironmentVariables[[string]$Name] = [string]$Environment[$Name]
    }
    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    try {
        if (-not $Process.Start()) { throw "Process did not start." }
        $Stdout = $Process.StandardOutput.ReadToEndAsync()
        $Stderr = $Process.StandardError.ReadToEndAsync()
        $Process.WaitForExit()
        return [pscustomobject]@{
            exitCode = $Process.ExitCode
            stdout = $Stdout.GetAwaiter().GetResult()
            stderr = $Stderr.GetAwaiter().GetResult()
        }
    }
    finally {
        $Process.Dispose()
    }
}

function New-SelfWorkflowNpmStageDescriptor {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("metadata", "install")]
        [string]$Stage,
        [Parameter(Mandatory = $true)][string]$NpmCliPath,
        [Parameter(Mandatory = $true)][string]$Registry,
        [Parameter(Mandatory = $true)][string]$PackageSpecification,
        [Parameter(Mandatory = $true)][string]$BootstrapRoot
    )

    $Cache = if ($Stage -eq "metadata") { "NUL" } else {
        Join-Path $BootstrapRoot "npm-cache"
    }
    $Arguments = if ($Stage -eq "metadata") {
        @(
            $NpmCliPath, "view", $PackageSpecification, "version",
            "dist.integrity", "--json", "--registry", $Registry
        )
    } else {
        @(
            $NpmCliPath, "install", "--prefix", $BootstrapRoot,
            "--package-lock=true", "--save-exact", "--registry", $Registry
        )
    }
    $Arguments += @(
        "--userconfig", "NUL", "--globalconfig", "NUL", "--cache", $Cache,
        "--ignore-scripts", "--no-audit", "--no-fund"
    )
    if ($Stage -eq "install") { $Arguments += $PackageSpecification }
    return [pscustomobject][ordered]@{
        arguments = $Arguments
        environment = [ordered]@{
            SystemRoot = $env:SystemRoot; WINDIR = $env:WINDIR
            TEMP = $env:TEMP; TMP = $env:TMP
            NPM_CONFIG_REGISTRY = $Registry
            NPM_CONFIG_USERCONFIG = "NUL"; NPM_CONFIG_GLOBALCONFIG = "NUL"
            NPM_CONFIG_CACHE = $Cache; NPM_CONFIG_IGNORE_SCRIPTS = "true"
            NPM_CONFIG_AUDIT = "false"; NPM_CONFIG_FUND = "false"
            NPM_CONFIG_UPDATE_NOTIFIER = "false"
        }
        trustedCwd = [IO.Path]::GetFullPath((Join-Path $env:SystemRoot "System32"))
        cachePath = $Cache
    }
}

function Assert-SelfWorkflowStaticPlan {
    param([Parameter(Mandatory = $true)]$Plan)

    $Root = [IO.Path]::GetFullPath([string]$Plan.bootstrapRoot).TrimEnd("\")
    $Registry = Resolve-SelfWorkflowRegistry $Plan.execution.registry
    $Metadata = New-SelfWorkflowNpmStageDescriptor -Stage metadata -NpmCliPath $Plan.execution.npmCli.path -Registry $Registry -PackageSpecification "$($Plan.package.name)@$($Plan.package.requestedVersion)" -BootstrapRoot $Root
    $Install = New-SelfWorkflowNpmStageDescriptor -Stage install -NpmCliPath $Plan.execution.npmCli.path -Registry $Registry -PackageSpecification "$($Plan.package.name)@$($Plan.package.version)" -BootstrapRoot $Root
    $ExpectedSecurity = [ordered]@{
        protected = $true
        principals = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, "S-1-5-18")
        rights = "FullControl"
    }
    $ExpectedEffects = [ordered]@{
        bootstrapRoot = $Root; cachePath = $Install.cachePath
        manifestPath = Join-Path $Root "bootstrap-tool-manifest.json"; uninstallBoundary = $Root
    }
    $Comparisons = @(
        @($Plan.execution.registry, $Registry),
        @($Plan.execution.trustedCwd, $Metadata.trustedCwd),
        @($Plan.execution.metadataArguments, $Metadata.arguments),
        @($Plan.execution.installArguments, $Install.arguments),
        @($Plan.execution.metadataEnvironment, $Metadata.environment),
        @($Plan.execution.installEnvironment, $Install.environment),
        @($Plan.security.expectedBootstrapDacl, $ExpectedSecurity),
        @($Plan.sideEffects, $ExpectedEffects)
    )
    $Changed = @($Comparisons | Where-Object {
        (ConvertTo-SelfWorkflowCanonicalJson $_[0] 10) -cne
        (ConvertTo-SelfWorkflowCanonicalJson $_[1] 10)
    }).Count -ne 0
    if (
        $Plan.package.name -cne "@openai/codex" -or
        -not (Test-SelfWorkflowCanonicalSemVer $Plan.package.version) -or
        $Plan.package.integrity -notmatch '^sha(256|384|512)-[A-Za-z0-9+/_=-]+$' -or
        $Changed
    ) {
        throw "Static plan semantics changed."
    }
}

function Invoke-SelfWorkflowDiscoverV2 {
    param(
        [Parameter(Mandatory = $true)][string]$BootstrapRoot,
        [Parameter(Mandatory = $true)][string]$ToolchainRoot,
        [Parameter(Mandatory = $true)][string]$Registry,
        [Parameter(Mandatory = $true)][string]$PackageName,
        [Parameter(Mandatory = $true)][string]$PackageVersion
    )

    try {
        $CanonicalBootstrapRoot = [IO.Path]::GetFullPath($BootstrapRoot).TrimEnd("\")
        $AllowedRoot = [IO.Path]::GetFullPath(
            (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli")
        ).TrimEnd("\")
        if (-not ($CanonicalBootstrapRoot.Equals($AllowedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            $CanonicalBootstrapRoot.StartsWith($AllowedRoot + "\", [StringComparison]::OrdinalIgnoreCase))) {
            throw "BootstrapRoot is outside the allowed boundary."
        }
    }
    catch {
        [Console]::Error.WriteLine("SelfWorkFlow: bootstrap path security verification failed.")
        exit 43
    }
    try {
        $CanonicalRegistry = Resolve-SelfWorkflowRegistry $Registry
        $Toolchain = Open-SelfWorkflowToolchainContext -Root $ToolchainRoot
        $NodePath = $Toolchain.node.path
        $NpmCliPath = $Toolchain.npmCli.path
    }
    catch {
        [Console]::Error.WriteLine("SelfWorkFlow: toolchain security verification failed.")
        exit 59
    }

    $MetadataStage = New-SelfWorkflowNpmStageDescriptor `
        -Stage metadata -NpmCliPath $NpmCliPath -Registry $CanonicalRegistry `
        -PackageSpecification "$PackageName@$PackageVersion" `
        -BootstrapRoot $BootstrapRoot
    try {
        $Result = Invoke-SelfWorkflowNodeProcess -NodePath $NodePath `
            -Arguments $MetadataStage.arguments `
            -WorkingDirectory $MetadataStage.trustedCwd `
            -Environment $MetadataStage.environment
    }
    catch {
        [Console]::Error.WriteLine("SelfWorkFlow: npm metadata query failed to start.")
        exit 40
    }
    if ($Result.exitCode -ne 0) {
        [Console]::Error.WriteLine(
            "SelfWorkFlow: npm metadata query failed with exit code $($Result.exitCode)."
        )
        exit 40
    }
    try {
        $Metadata = ConvertFrom-SelfWorkflowStrictJsonObject $Result.stdout
        if (
            $Metadata.version -isnot [string] -or
            $Metadata.'dist.integrity' -isnot [string] -or
            -not (Test-SelfWorkflowCanonicalSemVer $Metadata.version) -or
            $Metadata.'dist.integrity' -notmatch '^sha(256|384|512)-[A-Za-z0-9+/_=-]+$'
        ) { throw "Invalid metadata." }
    }
    catch {
        [Console]::Error.WriteLine("SelfWorkFlow: npm metadata response is invalid.")
        exit 47
    }

    $InstallStage = New-SelfWorkflowNpmStageDescriptor `
        -Stage install -NpmCliPath $NpmCliPath -Registry $CanonicalRegistry `
        -PackageSpecification "$PackageName@$($Metadata.version)" `
        -BootstrapRoot $CanonicalBootstrapRoot
    $Plan = [pscustomobject][ordered]@{
        planSchemaVersion = 2
        bootstrapRoot = $CanonicalBootstrapRoot
        package = [ordered]@{
            name = $PackageName
            requestedVersion = $PackageVersion
            version = $Metadata.version
            integrity = $Metadata.'dist.integrity'
        }
        execution = [ordered]@{
            registry = $CanonicalRegistry
            trustedCwd = $MetadataStage.trustedCwd
            node = [ordered]@{ path = $NodePath; sha256 = $Toolchain.node.sha256 }
            npmCli = [ordered]@{ path = $NpmCliPath; sha256 = $Toolchain.npmCli.sha256 }
            toolchain = [ordered]@{
                root = $Toolchain.root
                treeHash = $Toolchain.treeHash
                inventory = $Toolchain.inventory
            }
            metadataArguments = $MetadataStage.arguments
            installArguments = $InstallStage.arguments
            metadataEnvironment = $MetadataStage.environment
            installEnvironment = $InstallStage.environment
        }
        security = [ordered]@{
            toolchainAnchor = $Toolchain.anchor
            expectedBootstrapDacl = [ordered]@{
                protected = $true
                principals = @(
                    [Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
                    "S-1-5-18"
                )
                rights = "FullControl"
            }
        }
        sideEffects = [ordered]@{
            bootstrapRoot = $CanonicalBootstrapRoot
            cachePath = $InstallStage.cachePath
            manifestPath = Join-Path $CanonicalBootstrapRoot "bootstrap-tool-manifest.json"
            uninstallBoundary = $CanonicalBootstrapRoot
        }
        unverified = @(
            "same-SID, SYSTEM, or OS-privileged mutation after final verification",
            "real npm, network, and Codex execution"
        )
        planHash = ""
    }
    $Plan.planHash = Get-SelfWorkflowPlanHash $Plan
    $Plan | ConvertTo-Json -Depth 20 -Compress
    $Toolchain.Dispose()
}
