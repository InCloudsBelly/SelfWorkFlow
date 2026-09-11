[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Discover", "Apply")]
    [string]$Mode,
    [string]$BootstrapRoot,
    [string]$Registry = "https://registry.npmjs.org/",
    [ValidateSet("@openai/codex")]
    [string]$PackageName = "@openai/codex",
    [string]$PackageVersion = "latest",
    [string]$ToolchainRoot,
    [string]$ConfirmedPlanPath,
    [string]$ConfirmPlanHash
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Bootstrap security checks must use the OS-provided Windows PowerShell
# security cmdlets.  Codex hosts may inject another PowerShell module tree via
# PSModulePath; Windows PowerShell 5.1 can then load duplicate ObjectSecurity
# type data and make Get-Acl/Set-Acl unavailable.  Restricting this process to
# the system module tree also prevents user/module-path shadowing of the ACL
# implementation used by this security boundary.
try {
    $SystemPowerShellModules = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\Modules"
    if (-not [IO.Directory]::Exists($SystemPowerShellModules)) {
        throw "System PowerShell module directory is unavailable."
    }
    $env:PSModulePath = $SystemPowerShellModules
    Import-Module Microsoft.PowerShell.Security -ErrorAction Stop
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: PowerShell security module unavailable.")
    exit 58
}

function ConvertFrom-SelfWorkflowStrictJsonObject {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Trimmed = $Text.Trim()
    if (-not $Trimmed.StartsWith("{", [StringComparison]::Ordinal)) {
        throw "JSON value is not a single object."
    }
    $Value = ConvertFrom-Json -InputObject $Trimmed -ErrorAction Stop
    if ($null -eq $Value -or $Value -isnot [Management.Automation.PSCustomObject]) {
        throw "JSON value is not a single object."
    }
    return $Value
}

function Assert-SelfWorkflowExactProperties {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Collections.IDictionary]$Types
    )

    if ($Value -isnot [Management.Automation.PSCustomObject]) {
        throw "Object shape is invalid."
    }
    if (
        (@($Value.PSObject.Properties.Name | Sort-Object) -join ",") -cne
        (@($Names | Sort-Object) -join ",")
    ) {
        throw "Object properties are invalid."
    }
    if ($null -ne $Types) {
        foreach ($Name in $Types.Keys) {
            $PropertyValue = $Value.PSObject.Properties[[string]$Name].Value
            if ($null -eq $PropertyValue -or -not ($Types[$Name]).IsAssignableFrom($PropertyValue.GetType())) {
                throw "Object property type is invalid."
            }
        }
    }
}

function Assert-SelfWorkflowPlanV2Shape {
    param([Parameter(Mandatory = $true)]$Plan)

    $EnvironmentNames = @(
        "SystemRoot", "WINDIR", "TEMP", "TMP", "NPM_CONFIG_REGISTRY",
        "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG", "NPM_CONFIG_CACHE",
        "NPM_CONFIG_IGNORE_SCRIPTS", "NPM_CONFIG_AUDIT", "NPM_CONFIG_FUND",
        "NPM_CONFIG_UPDATE_NOTIFIER"
    )
    $Shapes = @(
        @{ Value = $Plan; Names = @("planSchemaVersion", "bootstrapRoot", "package", "execution", "security", "sideEffects", "unverified", "planHash") },
        @{ Value = $Plan.package; Names = @("name", "requestedVersion", "version", "integrity") },
        @{ Value = $Plan.execution; Names = @("registry", "trustedCwd", "node", "npmCli", "toolchain", "metadataArguments", "installArguments", "metadataEnvironment", "installEnvironment") },
        @{ Value = $Plan.execution.node; Names = @("path", "sha256") },
        @{ Value = $Plan.execution.npmCli; Names = @("path", "sha256") },
        @{ Value = $Plan.execution.toolchain; Names = @("root", "treeHash", "inventory") },
        @{ Value = $Plan.execution.metadataEnvironment; Names = $EnvironmentNames },
        @{ Value = $Plan.execution.installEnvironment; Names = $EnvironmentNames },
        @{ Value = $Plan.security; Names = @("toolchainAnchor", "expectedBootstrapDacl") },
        @{ Value = $Plan.security.expectedBootstrapDacl; Names = @("protected", "principals", "rights") },
        @{ Value = $Plan.sideEffects; Names = @("bootstrapRoot", "cachePath", "manifestPath", "uninstallBoundary") }
    )
    foreach ($Shape in $Shapes) {
        Assert-SelfWorkflowExactProperties $Shape.Value $Shape.Names
    }
    foreach ($Entry in @($Plan.execution.toolchain.inventory)) {
        Assert-SelfWorkflowExactProperties $Entry @("path", "type", "ownerSid", "daclSddl", "sha256")
    }
    $Strings = @(
        $Plan.bootstrapRoot, $Plan.package.name, $Plan.package.requestedVersion,
        $Plan.package.version, $Plan.package.integrity, $Plan.execution.registry,
        $Plan.execution.trustedCwd, $Plan.execution.node.path,
        $Plan.execution.node.sha256, $Plan.execution.npmCli.path,
        $Plan.execution.npmCli.sha256, $Plan.execution.toolchain.root,
        $Plan.execution.toolchain.treeHash, $Plan.security.toolchainAnchor,
        $Plan.security.expectedBootstrapDacl.rights,
        $Plan.sideEffects.bootstrapRoot, $Plan.sideEffects.cachePath,
        $Plan.sideEffects.manifestPath, $Plan.sideEffects.uninstallBoundary,
        $Plan.planHash
    )
    if (
        $Plan.planSchemaVersion -ne 2 -or
        @($Strings | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
        @($Plan.execution.metadataArguments | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
        @($Plan.execution.installArguments | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
        $Plan.execution.metadataArguments -isnot [object[]] -or
        $Plan.execution.installArguments -isnot [object[]] -or
        $Plan.execution.toolchain.inventory -isnot [object[]] -or
        $Plan.security.expectedBootstrapDacl.principals -isnot [object[]] -or
        $Plan.unverified -isnot [object[]] -or
        @($Plan.unverified | Where-Object { $_ -isnot [string] }).Count -ne 0 -or
        $Plan.security.expectedBootstrapDacl.protected -isnot [bool]
    ) {
        throw "Plan value type is invalid."
    }
}

function ConvertTo-SelfWorkflowCanonicalValue {
    param($Value)

    if ($null -eq $Value -or $Value -is [string] -or $Value -is [ValueType]) {
        return $Value
    }
    if ($Value -is [Collections.IDictionary]) {
        $Result = [ordered]@{}
        foreach ($Key in @($Value.Keys | Sort-Object)) {
            $Result[[string]$Key] = ConvertTo-SelfWorkflowCanonicalValue $Value[$Key]
        }
        return $Result
    }
    if ($Value -is [Management.Automation.PSCustomObject]) {
        $Result = [ordered]@{}
        foreach ($Property in @($Value.PSObject.Properties | Sort-Object Name)) {
            $Result[$Property.Name] = ConvertTo-SelfWorkflowCanonicalValue $Property.Value
        }
        return $Result
    }
    if ($Value -is [Collections.IEnumerable]) {
        return @($Value | ForEach-Object { ConvertTo-SelfWorkflowCanonicalValue $_ })
    }
    throw "Unsupported canonical JSON value."
}

function ConvertTo-SelfWorkflowCanonicalJson {
    param($Value, [int]$Depth = 20)
    return (ConvertTo-SelfWorkflowCanonicalValue $Value) | ConvertTo-Json -Depth $Depth -Compress
}

function Get-SelfWorkflowSha256Text {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $Hash = $Hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))
        return ([BitConverter]::ToString($Hash)).Replace("-", "").ToLowerInvariant()
    }
    finally { $Hasher.Dispose() }
}

function Get-SelfWorkflowPlanHash {
    param([Parameter(Mandatory = $true)]$Plan)

    $WithoutHash = [ordered]@{}
    foreach ($Property in $Plan.PSObject.Properties) {
        if ($Property.Name -ne "planHash") {
            $WithoutHash[$Property.Name] = $Property.Value
        }
    }
    return Get-SelfWorkflowSha256Text (ConvertTo-SelfWorkflowCanonicalJson $WithoutHash)
}

function Read-SelfWorkflowConfirmedPlan {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ConfirmedHash
    )

    $CanonicalPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.File]::Exists($CanonicalPath)) {
        throw "Confirmed plan does not exist."
    }
    $Current = [IO.FileInfo]::new($CanonicalPath)
    while ($null -ne $Current) {
        if (($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Confirmed plan path contains a reparse point."
        }
        $Current = if ($Current -is [IO.DirectoryInfo]) {
            $Current.Parent
        } else {
            $Current.Directory
        }
    }
    $Stream = [IO.FileStream]::new(
        $CanonicalPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        if ($Stream.Length -gt 1048576) {
            throw "Confirmed plan is too large."
        }
        $Reader = [IO.StreamReader]::new(
            $Stream, [Text.UTF8Encoding]::new($false, $true), $true, 4096, $true)
        try {
            $Plan = ConvertFrom-SelfWorkflowStrictJsonObject $Reader.ReadToEnd()
        }
        finally {
            $Reader.Dispose()
        }
        Assert-SelfWorkflowPlanV2Shape $Plan
        $CalculatedHash = Get-SelfWorkflowPlanHash $Plan
        if (
            $ConfirmedHash -cnotmatch "^[0-9a-f]{64}$" -or
            $Plan.planHash -isnot [string] -or
            $Plan.planHash -cne $CalculatedHash -or
            $ConfirmedHash -cne $CalculatedHash
        ) {
            throw "Confirmed plan hash is invalid."
        }
        return [pscustomobject]@{ Plan = $Plan; Lock = $Stream }
    }
    catch {
        $Stream.Dispose()
        throw
    }
}

if ($Mode -eq "Apply" -and (-not $ConfirmedPlanPath -or -not $ConfirmPlanHash)) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: ConfirmedPlanPath and ConfirmPlanHash are required for Apply mode."
    )
    exit 45
}
if ($Mode -eq "Apply" -and -not [System.IO.Path]::IsPathRooted($ConfirmedPlanPath)) {
    [Console]::Error.WriteLine("SelfWorkFlow: confirmed plan validation failed.")
    exit 60
}
if ($Mode -eq "Apply") {
    try {
        $ConfirmedPlanContext = Read-SelfWorkflowConfirmedPlan `
            -Path $ConfirmedPlanPath -ConfirmedHash $ConfirmPlanHash
    }
    catch {
        [Console]::Error.WriteLine("SelfWorkFlow: confirmed plan validation failed.")
        exit 60
    }
}

try {
    . (Join-Path $PSScriptRoot "lib\bootstrap-manifest.ps1")
    . (Join-Path $PSScriptRoot "lib\bootstrap-execution.ps1")
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: bootstrap library loading failed.")
    exit 58
}
function Initialize-SelfWorkflowPathLockType {
    if ("SelfWorkflowPathLockSet" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public sealed class SelfWorkflowPathLockSet : IDisposable {
    private const uint FileReadAttributes = 0x80;
    private const uint DeleteAccess = 0x00010000;
    private const uint FileShareRead = 0x1;
    private const uint FileShareWrite = 0x2;
    private const uint FileShareDelete = 0x4;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string fileName, uint desiredAccess,
        uint shareMode, IntPtr securityAttributes, uint creationDisposition,
        uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file,
        out ByHandleFileInformation information);

    private sealed class Lock : IDisposable {
        public readonly string Path;
        public readonly SafeFileHandle Handle;
        public readonly ByHandleFileInformation Identity;

        public Lock(string path, SafeFileHandle handle, ByHandleFileInformation identity) {
            Path = path;
            Handle = handle;
            Identity = identity;
        }

        public void Dispose() {
            Handle.Dispose();
        }
    }

    private readonly string anchorPath;
    private readonly Dictionary<string, Lock> locks =
        new Dictionary<string, Lock>(StringComparer.OrdinalIgnoreCase);

    public SelfWorkflowPathLockSet(string anchorPath) {
        this.anchorPath = Canonicalize(anchorPath);
    }

    private static string Canonicalize(string path) {
        return System.IO.Path.GetFullPath(path).TrimEnd('\\');
    }

    private static SafeFileHandle OpenDirectory(string path, bool holdAgainstDelete) {
        SafeFileHandle result = CreateFileW(
            path,
            FileReadAttributes | (holdAgainstDelete ? DeleteAccess : 0),
            FileShareRead | FileShareWrite | (holdAgainstDelete ? 0 : FileShareDelete),
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (result.IsInvalid) {
            int error = Marshal.GetLastWin32Error();
            result.Dispose();
            throw new Win32Exception(error, "Unable to lock a bootstrap path ancestor.");
        }
        return result;
    }

    private static ByHandleFileInformation ReadIdentity(SafeFileHandle directoryHandle) {
        ByHandleFileInformation information;
        if (!GetFileInformationByHandle(directoryHandle, out information)) {
            throw new Win32Exception(Marshal.GetLastWin32Error(),
                "Unable to read a bootstrap path ancestor identity.");
        }
        return information;
    }

    private static bool HasSameIdentity(ByHandleFileInformation expected,
        ByHandleFileInformation actual) {
        return actual.VolumeSerialNumber == expected.VolumeSerialNumber
            && actual.FileIndexHigh == expected.FileIndexHigh
            && actual.FileIndexLow == expected.FileIndexLow;
    }

    private static void RejectReparsePoint(ByHandleFileInformation information) {
        if ((information.FileAttributes & (uint)FileAttributes.ReparsePoint) != 0) {
            throw new InvalidOperationException("A bootstrap path ancestor is a reparse point.");
        }
    }

    private static Lock Acquire(string path) {
        SafeFileHandle handle = OpenDirectory(path, true);
        try {
            ByHandleFileInformation identity = ReadIdentity(handle);
            RejectReparsePoint(identity);
            return new Lock(path, handle, identity);
        } catch {
            handle.Dispose();
            throw;
        }
    }

    private List<string> GetExistingChain(string targetPath) {
        List<string> chain = new List<string>();
        DirectoryInfo current = new DirectoryInfo(targetPath);
        bool reachedAnchor = false;
        bool isTarget = true;
        while (current != null) {
            string currentPath = Canonicalize(current.FullName);
            if (File.Exists(currentPath) && !isTarget) {
                throw new InvalidOperationException("A bootstrap path ancestor is not a directory.");
            }
            if (!File.Exists(currentPath) && Directory.Exists(currentPath)) {
                if ((File.GetAttributes(currentPath) & FileAttributes.ReparsePoint) != 0) {
                    throw new InvalidOperationException("A bootstrap path ancestor is a reparse point.");
                }
                chain.Add(currentPath);
            }
            if (currentPath.Equals(anchorPath, StringComparison.OrdinalIgnoreCase)) {
                reachedAnchor = true;
                break;
            }
            current = current.Parent;
            isTarget = false;
        }
        if (!reachedAnchor) {
            throw new InvalidOperationException(
                "The bootstrap path does not descend from its security anchor.");
        }
        return chain;
    }

    public void Refresh(string targetPath) {
        List<string> chain = GetExistingChain(targetPath);
        List<string> addedPaths = new List<string>();
        try {
            for (int index = chain.Count - 1; index >= 0; index--) {
                string path = chain[index];
                if (!locks.ContainsKey(path)) {
                    locks.Add(path, Acquire(path));
                    addedPaths.Add(path);
                }
            }
            Verify(targetPath);
        } catch {
            foreach (string path in addedPaths) {
                locks[path].Dispose();
                locks.Remove(path);
            }
            throw;
        }
    }

    public void Verify(string targetPath) {
        GetExistingChain(targetPath);
        foreach (Lock item in locks.Values) {
            ByHandleFileInformation heldIdentity = ReadIdentity(item.Handle);
            RejectReparsePoint(heldIdentity);
            if (!HasSameIdentity(item.Identity, heldIdentity)) {
                throw new InvalidOperationException("A locked bootstrap path identity changed.");
            }
            using (SafeFileHandle currentHandle = OpenDirectory(item.Path, false)) {
                ByHandleFileInformation currentIdentity = ReadIdentity(currentHandle);
                RejectReparsePoint(currentIdentity);
                if (!HasSameIdentity(item.Identity, currentIdentity)) {
                    throw new InvalidOperationException(
                        "A bootstrap path ancestor identity changed.");
                }
            }
        }
    }

    public void Dispose() {
        foreach (Lock item in locks.Values) {
            item.Dispose();
        }
        locks.Clear();
    }
}
"@
}

function Set-StrictBootstrapAcl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $CurrentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $SystemSid = [System.Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $InheritanceFlags = (
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $Security = [System.Security.AccessControl.DirectorySecurity]::new()
    $Security.SetOwner($CurrentUserSid)
    $Security.SetAccessRuleProtection($true, $false)
    foreach ($Sid in @($CurrentUserSid, $SystemSid)) {
        [void]$Security.AddAccessRule(
            [System.Security.AccessControl.FileSystemAccessRule]::new(
                $Sid,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $InheritanceFlags,
                [System.Security.AccessControl.PropagationFlags]::None,
                [System.Security.AccessControl.AccessControlType]::Allow
            )
        )
    }
    [System.IO.Directory]::SetAccessControl($Path, $Security)
}

function Get-VerifiedBootstrapSddl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Acl = [System.IO.Directory]::GetAccessControl(
        $Path,
        [System.Security.AccessControl.AccessControlSections]::Access
    )
    $Sddl = $Acl.GetSecurityDescriptorSddlForm(
        [Security.AccessControl.AccessControlSections]::Access
    )
    Assert-SelfWorkflowExactBootstrapSddl $Sddl
    return $Sddl
}

if ($Mode -eq "Discover") {
    if (-not $ToolchainRoot) {
        [Console]::Error.WriteLine("SelfWorkFlow: toolchain security verification failed.")
        exit 59
    }
    if (-not $BootstrapRoot) {
        $BootstrapRoot = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli"
    }
    Invoke-SelfWorkflowDiscoverV2 `
        -BootstrapRoot $BootstrapRoot `
        -ToolchainRoot $ToolchainRoot `
        -Registry $Registry `
        -PackageName $PackageName `
        -PackageVersion $PackageVersion
    exit 0
}

$ToolchainContext = $null
$ExitCode = 0
$Stage = @{ code = 60; message = "SelfWorkFlow: confirmed plan validation failed." }
try {
    Assert-SelfWorkflowStaticPlan $ConfirmedPlanContext.Plan

    $Stage = @{ code = 59; message = "SelfWorkFlow: toolchain security verification failed." }
    $ToolchainContext = Open-SelfWorkflowToolchainContext -Plan $ConfirmedPlanContext.Plan

    $Root = $ConfirmedPlanContext.Plan.bootstrapRoot
    $Stage = @{ code = 43; message = "SelfWorkFlow: bootstrap path security verification failed." }
    $ToolchainContext.directories.Refresh($Root)
    $Stage = @{ code = 44; message = "SelfWorkFlow: existing BootstrapRoot does not satisfy safe recovery conditions; only an empty directory is accepted." }
    $RootIsUnsafe = [IO.File]::Exists($Root)
    if (-not $RootIsUnsafe -and [IO.Directory]::Exists($Root)) {
        $RootIsUnsafe = [IO.Directory]::GetFileSystemEntries($Root).Count -ne 0
        if (-not $RootIsUnsafe) {
            $null = Assert-SelfWorkflowSafeAcl -Path $Root -AllowInheritance
        }
    }
    if ($RootIsUnsafe) {
        throw "Unsafe bootstrap root."
    }
    [IO.Directory]::CreateDirectory($Root) | Out-Null
    $ToolchainContext.directories.Refresh($Root)

    $Stage = @{ code = 48; message = "SelfWorkFlow: ACL security verification failed." }
    Set-StrictBootstrapAcl $Root
    $VerifiedSddl = Get-VerifiedBootstrapSddl $Root
    $Stage = @{ code = 44; message = "SelfWorkFlow: existing BootstrapRoot does not satisfy safe recovery conditions; only an empty directory is accepted." }
    if ([IO.Directory]::GetFileSystemEntries($Root).Count -ne 0) { throw "Bootstrap root changed before install." }

    $Stage = @{ code = 49; message = "SelfWorkFlow: npm install failed to start." }
    $InstallResult = Invoke-SelfWorkflowNodeProcess `
        -NodePath $ToolchainContext.node.path `
        -Arguments $ConfirmedPlanContext.Plan.execution.installArguments `
        -WorkingDirectory $ConfirmedPlanContext.Plan.execution.trustedCwd `
        -Environment (ConvertTo-SelfWorkflowCanonicalValue `
            $ConfirmedPlanContext.Plan.execution.installEnvironment)
    if ($InstallResult.exitCode -ne 0) {
        $Stage.message = "SelfWorkFlow: npm install failed with exit code $($InstallResult.exitCode)."
        throw "npm install failed."
    }

    $Stage = @{ code = 50; message = "SelfWorkFlow: installed package verification failed." }
    $InstalledPackageRoot = Join-Path $Root "node_modules\@openai\codex"
    if (-not [IO.File]::Exists((Join-Path $InstalledPackageRoot "package.json")) -or -not [IO.File]::Exists((Join-Path $ConfirmedPlanContext.Plan.bootstrapRoot "package-lock.json"))) { throw "Missing metadata." }
    $InitialPackageTreeHash = Get-SelfWorkflowPackageTreeHash $InstalledPackageRoot
    $InstalledPackage = ConvertFrom-SelfWorkflowStrictJsonObject ([IO.File]::ReadAllText((Join-Path $InstalledPackageRoot "package.json")))
    $PackageLock = ConvertFrom-SelfWorkflowStrictJsonObject ([IO.File]::ReadAllText((Join-Path $ConfirmedPlanContext.Plan.bootstrapRoot "package-lock.json")))
    if ($InstalledPackage.name -isnot [string] -or $InstalledPackage.version -isnot [string]) { throw "Invalid package fields." }
    if ($PackageLock.lockfileVersion -isnot [int] -or $PackageLock.packages -isnot [Management.Automation.PSCustomObject]) { throw "Invalid lock shape." }
    $LockedPackage = $PackageLock.packages.PSObject.Properties["node_modules/@openai/codex"].Value
    if ($LockedPackage -isnot [Management.Automation.PSCustomObject]) { throw "Missing lock entry." }
    if ($LockedPackage.name -isnot [string] -or $LockedPackage.version -isnot [string] -or $LockedPackage.integrity -isnot [string]) { throw "Invalid lock fields." }
    if ($InstalledPackage.name -cne $ConfirmedPlanContext.Plan.package.name -or $InstalledPackage.version -cne $ConfirmedPlanContext.Plan.package.version) { throw "Installed package identity changed." }
    if ($LockedPackage.name -cne $ConfirmedPlanContext.Plan.package.name -or $LockedPackage.version -cne $ConfirmedPlanContext.Plan.package.version) { throw "Locked package identity changed." }
    if ($LockedPackage.integrity -cne $ConfirmedPlanContext.Plan.package.integrity) { throw "Locked package integrity changed." }
    $VerifiedPackageTreeHash = Get-SelfWorkflowPackageTreeHash $InstalledPackageRoot
    if ($InitialPackageTreeHash -cne $VerifiedPackageTreeHash) { throw "Package tree changed." }

    $Stage = @{ code = 48; message = "SelfWorkFlow: ACL security verification failed." }
    if ((Get-VerifiedBootstrapSddl $Root) -cne $VerifiedSddl) { throw "BootstrapRoot ACL changed." }

    $Stage = @{ code = 58; message = "SelfWorkFlow: manifest validation or publication failed." }
    $ManifestPath = $ConfirmedPlanContext.Plan.sideEffects.manifestPath
    $Manifest = [pscustomobject][ordered]@{
        schemaVersion = 2; bootstrapRoot = $ConfirmedPlanContext.Plan.bootstrapRoot
        package = [pscustomobject][ordered]@{ name = $ConfirmedPlanContext.Plan.package.name; version = $ConfirmedPlanContext.Plan.package.version; integrity = $ConfirmedPlanContext.Plan.package.integrity }
        packageTreeHash = $VerifiedPackageTreeHash
        daclSddl = $VerifiedSddl; expectedCliVersion = $ConfirmedPlanContext.Plan.package.version
        cliVersionVerification = "not-run"; planHash = Get-SelfWorkflowPlanHash $ConfirmedPlanContext.Plan
    }
    $WrittenManifest = Publish-SelfWorkflowManifestAtomic $Manifest $ManifestPath $ConfirmedPlanContext.Plan (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli") $InstalledPackageRoot $VerifiedSddl
    $Output = [ordered]@{ manifestPath = $ManifestPath; manifest = $WrittenManifest } | ConvertTo-Json -Depth 5 -Compress
}
catch {
    $ExitCode = $Stage.code
    $Output = $Stage.message
}
finally {
    if ($ExitCode -ne 0) { [Console]::Error.WriteLine($Output) } else { $Output }
    [Environment]::Exit($ExitCode)
}
