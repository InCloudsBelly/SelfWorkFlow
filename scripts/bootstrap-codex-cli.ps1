[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Discover", "Apply")]
    [string]$Mode,
    [string]$BootstrapRoot,
    [string]$NpmCommand = "npm.cmd",
    [string]$Registry = "https://registry.npmjs.org/",
    [ValidateSet("@openai/codex")]
    [string]$PackageName = "@openai/codex",
    [string]$PackageVersion = "latest",
    [string]$ConfirmPlanHash,
    [string]$IcaclsCommand = "icacls.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

try {
    . (Join-Path $PSScriptRoot "lib\bootstrap-manifest.ps1")
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: manifest semantic validation failed.")
    exit 58
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

function Resolve-ExecutableIdentity {
    param([Parameter(Mandatory = $true)][string]$Command)

    $ResolvedCommand = Get-Command `
        -Name $Command `
        -CommandType Application `
        -ErrorAction Stop | Select-Object -First 1
    $CanonicalPath = [System.IO.Path]::GetFullPath($ResolvedCommand.Source)
    if (-not [System.IO.File]::Exists($CanonicalPath)) {
        throw "The external command is not an executable file."
    }
    $Stream = [System.IO.FileStream]::new(
        $CanonicalPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $Algorithm = [System.Security.Cryptography.SHA256]::Create()
        try {
            $HashBytes = $Algorithm.ComputeHash($Stream)
            $Hash = ([System.BitConverter]::ToString($HashBytes)).Replace("-", "")
        }
        finally {
            $Algorithm.Dispose()
        }
        return [pscustomobject]@{
            Path = $CanonicalPath
            Sha256 = "sha256:$($Hash.ToLowerInvariant())"
            Lock = $Stream
        }
    }
    catch {
        $Stream.Dispose()
        throw
    }
}

function Resolve-NpmRegistry {
    param([Parameter(Mandatory = $true)][string]$Value)

    try {
        $Uri = [System.Uri]::new($Value, [System.UriKind]::Absolute)
    }
    catch {
        throw "Registry must be an absolute URI."
    }
    if (
        $Uri.Scheme -ne [System.Uri]::UriSchemeHttps -or
        -not $Uri.Host -or
        $Uri.UserInfo -or
        $Uri.Query -or
        $Uri.Fragment
    ) {
        throw "Registry URI components are not allowed."
    }
    $Builder = [System.UriBuilder]::new($Uri)
    if (-not $Builder.Path.EndsWith("/", [System.StringComparison]::Ordinal)) {
        $Builder.Path += "/"
    }
    return $Builder.Uri.AbsoluteUri
}

function Invoke-NpmStage {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Registry,
        [Parameter(Mandatory = $true)]
        [ValidateSet("metadata query", "install")]
        [string]$Stage,
        [Parameter(Mandatory = $true)][int]$FailureCode
    )

    $EnvironmentNames = @(
        Get-ChildItem Env: |
            Where-Object Name -Match '^(NPM_CONFIG_|NPM_TOKEN$|NODE_AUTH_TOKEN$)' |
            ForEach-Object Name
    ) + @(
        "NPM_CONFIG_REGISTRY",
        "NPM_CONFIG_USERCONFIG",
        "NPM_CONFIG_GLOBALCONFIG",
        "NPM_TOKEN",
        "NODE_AUTH_TOKEN"
    ) | Select-Object -Unique

    $SavedEnvironment = @{}
    foreach ($Name in $EnvironmentNames) {
        $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name)
        [Environment]::SetEnvironmentVariable($Name, $null)
    }

    try {
        $env:NPM_CONFIG_REGISTRY = $Registry
        $env:NPM_CONFIG_USERCONFIG = "NUL"
        $env:NPM_CONFIG_GLOBALCONFIG = "NUL"
        $ErrorActionPreference = "Continue"
        $Output = @(& $Path @Arguments 2>&1)
        $ExitCode = $LASTEXITCODE
        if ($ExitCode -ne 0) {
            [Console]::Error.WriteLine(
                "SelfWorkFlow: npm $Stage failed with exit code $ExitCode."
            )
            exit $FailureCode
        }
        return $Output
    }
    finally {
        foreach ($Name in $EnvironmentNames) {
            [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name])
        }
    }
}

function Get-CodexCliVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $Path
    $StartInfo.Arguments = "--version"
    $StartInfo.UseShellExecute = $false
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.CreateNoWindow = $true

    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    try {
        try {
            if (-not $Process.Start()) {
                throw "The external command did not start."
            }
        }
        catch {
            [Console]::Error.WriteLine(
                "SelfWorkFlow: Codex CLI version command failed to start."
            )
            exit 54
        }
        $StandardOutput = $Process.StandardOutput.ReadToEndAsync()
        $StandardError = $Process.StandardError.ReadToEndAsync()
        $Process.WaitForExit()
        if ($Process.ExitCode -ne 0) {
            [Console]::Error.WriteLine(
                "SelfWorkFlow: Codex CLI version command failed with exit code $($Process.ExitCode)."
            )
            exit 54
        }
        $Output = $StandardOutput.GetAwaiter().GetResult()
        $ErrorOutput = $StandardError.GetAwaiter().GetResult()
    }
    finally {
        $Process.Dispose()
    }

    $NormalizedOutput = $Output.Replace("`r`n", "`n").Replace("`r", "`n")
    if ($NormalizedOutput.EndsWith("`n", [System.StringComparison]::Ordinal)) {
        $NormalizedOutput = $NormalizedOutput.Substring(0, $NormalizedOutput.Length - 1)
    }
    $SemVer = Get-SelfWorkflowCanonicalSemVerPattern
    $Match = [regex]::Match($NormalizedOutput, "^codex-cli (?<version>$SemVer)$")
    if (
        $ErrorOutput.Length -ne 0 -or
        $NormalizedOutput.Contains("`n") -or
        -not $Match.Success -or
        $Match.Groups["version"].Value -ne $ExpectedVersion
    ) {
        [Console]::Error.WriteLine(
            "SelfWorkFlow: Codex CLI version verification failed."
        )
        exit 55
    }
    return $Match.Groups["version"].Value
}

function ConvertFrom-StrictJsonObject {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Trimmed = $Text.Trim()
    if (-not $Trimmed.StartsWith("{", [System.StringComparison]::Ordinal)) {
        throw "JSON value is not a single object."
    }
    try {
        $Value = ConvertFrom-Json -InputObject $Trimmed -ErrorAction Stop
    }
    catch {
        throw "JSON object cannot be parsed."
    }
    if (
        $null -eq $Value -or
        $Value -isnot [System.Management.Automation.PSCustomObject]
    ) {
        throw "JSON value is not a single object."
    }
    return $Value
}

function Get-ReparsePointAncestor {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Current = [System.IO.DirectoryInfo]::new($Path)
    while ($null -ne $Current) {
        if (
            [System.IO.Directory]::Exists($Current.FullName) -or
            [System.IO.File]::Exists($Current.FullName)
        ) {
            $Attributes = [System.IO.File]::GetAttributes($Current.FullName)
            if (($Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                return $Current.FullName
            }
        }
        $Current = $Current.Parent
    }
    return $null
}

function Stop-BootstrapPathSecurityFailure {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: bootstrap path security verification failed."
    )
    exit 43
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
    [void]$Security.AddAccessRule(
        [System.Security.AccessControl.FileSystemAccessRule]::new(
            $CurrentUserSid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $InheritanceFlags,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
    )
    [void]$Security.AddAccessRule(
        [System.Security.AccessControl.FileSystemAccessRule]::new(
            $SystemSid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $InheritanceFlags,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
    )
    [System.IO.Directory]::SetAccessControl($Path, $Security)
}

function Get-VerifiedBootstrapSddl {
    param([Parameter(Mandatory = $true)][string]$Path)

    $CurrentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $ExpectedSids = @($CurrentUserSid, "S-1-5-18")
    $ExpectedInheritance = (
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $Acl = Get-Acl -LiteralPath $Path
    if (-not $Acl.AreAccessRulesProtected) {
        throw "BootstrapRoot DACL inheritance is not protected."
    }
    $Rules = @($Acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ))
    if ($Rules.Count -ne 2) {
        throw "BootstrapRoot DACL must contain exactly two access rules."
    }
    foreach ($ExpectedSid in $ExpectedSids) {
        $MatchingRules = @($Rules | Where-Object {
            $_.IdentityReference.Value -eq $ExpectedSid
        })
        if ($MatchingRules.Count -ne 1) {
            throw "BootstrapRoot DACL is missing the exact rule for SID '$ExpectedSid'."
        }
        $Rule = $MatchingRules[0]
        if (
            $Rule.IsInherited -or
            $Rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $Rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
            $Rule.InheritanceFlags -ne $ExpectedInheritance -or
            $Rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None
        ) {
            throw "BootstrapRoot DACL rule for SID '$ExpectedSid' is not exact."
        }
    }

    $Sddl = $Acl.GetSecurityDescriptorSddlForm(
        [System.Security.AccessControl.AccessControlSections]::Access
    )
    $RawDescriptor = [System.Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
    if (
        ($RawDescriptor.ControlFlags -band
            [System.Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -eq 0 -or
        $RawDescriptor.DiscretionaryAcl.Count -ne 2
    ) {
        throw "BootstrapRoot SDDL does not contain the expected protected two-entry DACL."
    }
    return $Sddl
}

if (-not $BootstrapRoot) {
    $BootstrapRoot = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli"
}
$CanonicalBootstrapRoot = [System.IO.Path]::GetFullPath($BootstrapRoot).TrimEnd("\")
$CanonicalLocalAppData = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd("\")
$AllowedBoundary = [System.IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli")
).TrimEnd("\")
$AllowedBoundaryPrefix = $AllowedBoundary + [System.IO.Path]::DirectorySeparatorChar
$IsWithinAllowedBoundary = $CanonicalBootstrapRoot.Equals(
    $AllowedBoundary,
    [System.StringComparison]::OrdinalIgnoreCase
) -or $CanonicalBootstrapRoot.StartsWith(
    $AllowedBoundaryPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)
if (-not $IsWithinAllowedBoundary) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: BootstrapRoot '$CanonicalBootstrapRoot' is outside the allowed bootstrap boundary '$AllowedBoundary'."
    )
    exit 42
}
$ReparsePointAncestor = Get-ReparsePointAncestor -Path $CanonicalBootstrapRoot
if ($ReparsePointAncestor) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: reparse point ancestor '$ReparsePointAncestor' is not allowed for BootstrapRoot."
    )
    exit 43
}
if ($Mode -eq "Apply" -and -not $ConfirmPlanHash) {
    [Console]::Error.WriteLine("SelfWorkFlow: ConfirmPlanHash is required for Apply mode.")
    exit 45
}

try {
    $CanonicalRegistry = Resolve-NpmRegistry -Value $Registry
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: registry configuration is invalid.")
    exit 41
}

$PathLocks = $null
if ($Mode -eq "Apply") {
    try {
        $PathLocks = [SelfWorkflowPathLockSet]::new($env:LOCALAPPDATA)
        $PathLocks.Refresh($CanonicalBootstrapRoot)
    }
    catch {
        Stop-BootstrapPathSecurityFailure
    }
}

try {
    $NpmIdentity = Resolve-ExecutableIdentity -Command $NpmCommand
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: npm command validation failed.")
    exit 39
}
$NpmCommand = $NpmIdentity.Path
$MetadataArguments = @(
    "view",
    "$PackageName@$PackageVersion",
    "version",
    "dist.integrity",
    "--json",
    "--registry",
    $CanonicalRegistry
)

$MetadataOutput = Invoke-NpmStage `
    -Path $NpmCommand `
    -Arguments $MetadataArguments `
    -Registry $CanonicalRegistry `
    -Stage "metadata query" `
    -FailureCode 40
try {
    $MetadataText = $MetadataOutput -join [Environment]::NewLine
    $Metadata = ConvertFrom-StrictJsonObject -Text $MetadataText
    $VersionProperty = $Metadata.PSObject.Properties["version"]
    $IntegrityProperty = $Metadata.PSObject.Properties["dist.integrity"]
    if (
        $null -eq $VersionProperty -or
        $VersionProperty.Value -isnot [string] -or
        $null -eq $IntegrityProperty -or
        $IntegrityProperty.Value -isnot [string]
    ) {
        throw "Metadata fields are missing or have invalid types."
    }
    if (
        -not (Test-SelfWorkflowCanonicalSemVer -Value $VersionProperty.Value) -or
        $IntegrityProperty.Value -notmatch "^sha(256|384|512)-[A-Za-z0-9+/_=-]+$"
    ) {
        throw "Metadata field formats are invalid."
    }
    $Integrity = $IntegrityProperty.Value
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: npm metadata response is invalid.")
    exit 47
}
$InstallArguments = @(
    "install",
    "--prefix",
    $CanonicalBootstrapRoot,
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--package-lock=true",
    "--save-exact",
    "--registry",
    $CanonicalRegistry,
    "$PackageName@$($Metadata.version)"
)
$CurrentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$PlannedManifestPath = Join-Path $CanonicalBootstrapRoot "bootstrap-tool-manifest.json"

$PlanData = [ordered]@{
    schemaVersion = 1
    bootstrapRoot = $CanonicalBootstrapRoot
    package = [ordered]@{
        name = $PackageName
        requestedVersion = $PackageVersion
        version = $Metadata.version
        integrity = $Integrity
    }
    execution = [ordered]@{
        npm = [ordered]@{
            path = $NpmIdentity.Path
            sha256 = $NpmIdentity.Sha256
            registry = $CanonicalRegistry
        }
        metadataArguments = $MetadataArguments
        installArguments = $InstallArguments
        environment = [ordered]@{
            npmConfig = "cleared"
            authentication = "cleared"
            userConfig = "NUL"
            globalConfig = "NUL"
        }
    }
    security = [ordered]@{
        dacl = [ordered]@{
            protected = $true
            principals = @($CurrentUserSid, "S-1-5-18")
            rights = "FullControl"
            inheritance = @("ContainerInherit", "ObjectInherit")
        }
        path = [ordered]@{
            status = "constrained"
            lockAnchor = $CanonicalLocalAppData
            verified = @(
                "existing ancestors locked against delete and rename",
                "path identities and reparse attributes rechecked before side effects"
            )
            unverified = @(
                "atomic create-and-open of new directory components against a same-SID attacker",
                "same-SID mutation of unlocked ACL or package files after final verification"
            )
        }
    }
    sideEffects = [ordered]@{
        bootstrapRoot = $CanonicalBootstrapRoot
        manifestPath = $PlannedManifestPath
        uninstallBoundary = $CanonicalBootstrapRoot
    }
}
$PlanJson = $PlanData | ConvertTo-Json -Depth 8 -Compress
$PlanHash = Get-SelfWorkflowSha256Text -Text $PlanJson

if ($Mode -eq "Discover") {
    [ordered]@{
        mode = "Discover"
        schemaVersion = $PlanData.schemaVersion
        bootstrapRoot = $PlanData.bootstrapRoot
        package = $PlanData.package
        execution = $PlanData.execution
        security = $PlanData.security
        sideEffects = $PlanData.sideEffects
        planHash = $PlanHash
    } | ConvertTo-Json -Depth 8 -Compress
    exit 0
}

if (-not [System.String]::Equals(
    $ConfirmPlanHash,
    $PlanHash,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: ConfirmPlanHash does not match the regenerated plan hash."
    )
    exit 46
}

try {
    $PathLocks.Verify($CanonicalBootstrapRoot)
}
catch {
    Stop-BootstrapPathSecurityFailure
}

$TargetIsUnsafe = [System.IO.File]::Exists($CanonicalBootstrapRoot)
if (
    -not $TargetIsUnsafe -and
    [System.IO.Directory]::Exists($CanonicalBootstrapRoot)
) {
    $TargetIsUnsafe = (
        [System.IO.Directory]::GetFileSystemEntries($CanonicalBootstrapRoot).Count -ne 0
    )
}
if ($TargetIsUnsafe) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: existing BootstrapRoot does not satisfy safe recovery conditions; only an empty directory is accepted."
    )
    exit 44
}

try {
    [System.IO.Directory]::CreateDirectory($CanonicalBootstrapRoot) | Out-Null
    $PathLocks.Refresh($CanonicalBootstrapRoot)
}
catch {
    Stop-BootstrapPathSecurityFailure
}

try {
    Set-StrictBootstrapAcl -Path $CanonicalBootstrapRoot
    $IcaclsOutput = & $IcaclsCommand $CanonicalBootstrapRoot 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $IcaclsOutput) {
        throw "icacls verification failed."
    }
    $VerifiedSddl = Get-VerifiedBootstrapSddl -Path $CanonicalBootstrapRoot
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: ACL security verification failed.")
    exit 48
}

try {
    $PathLocks.Verify($CanonicalBootstrapRoot)
}
catch {
    Stop-BootstrapPathSecurityFailure
}
$null = Invoke-NpmStage `
    -Path $NpmCommand `
    -Arguments $InstallArguments `
    -Registry $CanonicalRegistry `
    -Stage "install" `
    -FailureCode 49

$PackageRelativePath = $PackageName.Replace("/", [System.IO.Path]::DirectorySeparatorChar)
$InstalledPackageRoot = Join-Path (
    (Join-Path $CanonicalBootstrapRoot "node_modules")
) $PackageRelativePath
$InstalledPackageJsonPath = Join-Path $InstalledPackageRoot "package.json"
$PackageLockPath = Join-Path $CanonicalBootstrapRoot "package-lock.json"
if (
    -not [System.IO.File]::Exists($InstalledPackageJsonPath) -or
    -not [System.IO.File]::Exists($PackageLockPath)
) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package metadata is missing.")
    exit 50
}

$LockPackageKey = "node_modules/$PackageName"
try {
    $InstalledPackage = ConvertFrom-StrictJsonObject -Text (
        Get-Content -Raw -LiteralPath $InstalledPackageJsonPath
    )
    $InstalledVersionProperty = $InstalledPackage.PSObject.Properties["version"]
    if (
        $null -eq $InstalledVersionProperty -or
        $InstalledVersionProperty.Value -isnot [string]
    ) {
        throw "Installed package version is invalid."
    }
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package metadata is invalid.")
    exit 56
}
try {
    $PackageLock = ConvertFrom-StrictJsonObject -Text (
        Get-Content -Raw -LiteralPath $PackageLockPath
    )
    $PackagesProperty = $PackageLock.PSObject.Properties["packages"]
    if (
        $null -eq $PackagesProperty -or
        $PackagesProperty.Value -isnot [System.Management.Automation.PSCustomObject]
    ) {
        throw "Package-lock packages map is invalid."
    }
    $LockedPackageProperty = $PackagesProperty.Value.PSObject.Properties[$LockPackageKey]
    if (
        $null -eq $LockedPackageProperty -or
        $LockedPackageProperty.Value -isnot [System.Management.Automation.PSCustomObject]
    ) {
        throw "Package-lock entry is invalid."
    }
    $LockedPackage = $LockedPackageProperty.Value
    $LockedVersionProperty = $LockedPackage.PSObject.Properties["version"]
    $LockedIntegrityProperty = $LockedPackage.PSObject.Properties["integrity"]
    if (
        $null -eq $LockedVersionProperty -or
        $LockedVersionProperty.Value -isnot [string] -or
        $null -eq $LockedIntegrityProperty -or
        $LockedIntegrityProperty.Value -isnot [string]
    ) {
        throw "Package-lock fields are invalid."
    }
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: package-lock metadata is invalid.")
    exit 57
}
if (
    $InstalledVersionProperty.Value -ne $Metadata.version -or
    $LockedVersionProperty.Value -ne $Metadata.version
) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package version does not match the regenerated plan.")
    exit 51
}
if ($LockedIntegrityProperty.Value -ne $Integrity) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package integrity does not match the regenerated plan.")
    exit 52
}

$CodexCliPath = Join-Path $CanonicalBootstrapRoot "node_modules\.bin\codex.cmd"
if (-not [System.IO.File]::Exists($CodexCliPath)) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed Codex CLI shim is missing.")
    exit 53
}

$CliVersion = Get-CodexCliVersion `
    -Path $CodexCliPath `
    -ExpectedVersion $Metadata.version

$PackageTreeHash = Get-SelfWorkflowPackageTreeHash -PackageRoot $InstalledPackageRoot
try {
    $FinalSddl = Get-VerifiedBootstrapSddl -Path $CanonicalBootstrapRoot
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: ACL security verification failed.")
    exit 48
}
$Manifest = [ordered]@{
    schemaVersion = 1
    bootstrapRoot = $CanonicalBootstrapRoot
    package = [ordered]@{
        name = $PackageName
        version = $Metadata.version
        integrity = $Integrity
    }
    packageTreeHash = $PackageTreeHash
    daclSddl = $FinalSddl
    cliVersion = $CliVersion
    planHash = $PlanHash
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 4
try {
    Assert-SelfWorkflowBootstrapManifest `
        -Manifest ($ManifestJson | ConvertFrom-Json) `
        -Plan ($PlanJson | ConvertFrom-Json) `
        -AllowedBoundary $AllowedBoundary `
        -PackageRoot $InstalledPackageRoot `
        -ExpectedSddl $FinalSddl
}
catch {
    [Console]::Error.WriteLine("SelfWorkFlow: manifest semantic validation failed.")
    exit 58
}
$ManifestPath = Join-Path $CanonicalBootstrapRoot "bootstrap-tool-manifest.json"
[System.IO.File]::WriteAllText(
    $ManifestPath,
    $ManifestJson,
    [System.Text.UTF8Encoding]::new($false)
)
$NpmIdentity.Lock.Dispose()
$PathLocks.Dispose()
