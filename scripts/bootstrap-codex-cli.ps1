[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Discover", "Apply")]
    [string]$Mode,
    [string]$BootstrapRoot,
    [string]$NpmCommand = "npm.cmd",
    [ValidateSet("@openai/codex")]
    [string]$PackageName = "@openai/codex",
    [string]$PackageVersion = "latest",
    [string]$ConfirmedPlanHash,
    [string]$IcaclsCommand = "icacls.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $Hash = $Algorithm.ComputeHash($Bytes)
        return ([System.BitConverter]::ToString($Hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Algorithm.Dispose()
    }
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

function Get-PackageTreeHash {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $Files = @(Get-ChildItem -LiteralPath $PackageRoot -File -Recurse -Force | ForEach-Object {
        [pscustomobject]@{
            File = $_
            RelativePath = $_.FullName.Substring($PackageRoot.Length).TrimStart("\").Replace("\", "/")
        }
    } | Sort-Object RelativePath)
    $Hasher = [System.Security.Cryptography.IncrementalHash]::CreateHash(
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $Separator = [byte[]]@(0)
    $Buffer = New-Object byte[] 65536
    try {
        foreach ($Entry in $Files) {
            $RelativePathBytes = [System.Text.Encoding]::UTF8.GetBytes($Entry.RelativePath)
            $Hasher.AppendData($RelativePathBytes)
            $Hasher.AppendData($Separator)
            $Stream = [System.IO.File]::OpenRead($Entry.File.FullName)
            try {
                while (($BytesRead = $Stream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                    $Hasher.AppendData($Buffer, 0, $BytesRead)
                }
            }
            finally {
                $Stream.Dispose()
            }
            $Hasher.AppendData($Separator)
        }
        $Hash = $Hasher.GetHashAndReset()
        $HashHex = ([System.BitConverter]::ToString($Hash)).Replace("-", "").ToLowerInvariant()
        return "sha256:$HashHex"
    }
    finally {
        $Hasher.Dispose()
    }
}

if (-not $BootstrapRoot) {
    $BootstrapRoot = Join-Path $env:LOCALAPPDATA "SelfWorkFlow\bootstrap\codex-cli"
}
$CanonicalBootstrapRoot = [System.IO.Path]::GetFullPath($BootstrapRoot).TrimEnd("\")
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
if ($Mode -eq "Apply" -and -not $ConfirmedPlanHash) {
    [Console]::Error.WriteLine("SelfWorkFlow: ConfirmedPlanHash is required for Apply mode.")
    exit 45
}

$MetadataOutput = & $NpmCommand view "$PackageName@$PackageVersion" version dist.integrity --json 2>&1
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("SelfWorkFlow: npm metadata query failed with exit code $LASTEXITCODE.")
    exit 40
}
$Metadata = ($MetadataOutput -join [Environment]::NewLine) | ConvertFrom-Json
$Integrity = $Metadata."dist.integrity"

$PlanData = [ordered]@{
    schemaVersion = 1
    bootstrapRoot = $CanonicalBootstrapRoot
    package = [ordered]@{
        name = $PackageName
        requestedVersion = $PackageVersion
        version = $Metadata.version
        integrity = $Integrity
    }
}
$PlanJson = $PlanData | ConvertTo-Json -Depth 4 -Compress
$PlanHash = Get-Sha256Hex -Text $PlanJson

if ($Mode -eq "Discover") {
    [ordered]@{
        mode = "Discover"
        schemaVersion = $PlanData.schemaVersion
        bootstrapRoot = $PlanData.bootstrapRoot
        package = $PlanData.package
        planHash = $PlanHash
    } | ConvertTo-Json -Depth 4 -Compress
    exit 0
}

if (-not [System.String]::Equals(
    $ConfirmedPlanHash,
    $PlanHash,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: ConfirmedPlanHash does not match the regenerated plan hash."
    )
    exit 46
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

[System.IO.Directory]::CreateDirectory($CanonicalBootstrapRoot) | Out-Null
Set-StrictBootstrapAcl -Path $CanonicalBootstrapRoot
$IcaclsOutput = & $IcaclsCommand $CanonicalBootstrapRoot 2>&1
if ($LASTEXITCODE -ne 0 -or -not $IcaclsOutput) {
    [Console]::Error.WriteLine("SelfWorkFlow: icacls verification failed.")
    exit 48
}
$VerifiedSddl = Get-VerifiedBootstrapSddl -Path $CanonicalBootstrapRoot

$InstallSpec = "$PackageName@$($Metadata.version)"
$InstallOutput = & $NpmCommand install `
    --prefix $CanonicalBootstrapRoot `
    --ignore-scripts `
    --no-audit `
    --no-fund `
    --package-lock=true `
    --save-exact `
    $InstallSpec 2>&1
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("SelfWorkFlow: npm install failed with exit code $LASTEXITCODE.")
    exit 49
}

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

$InstalledPackage = Get-Content -Raw -LiteralPath $InstalledPackageJsonPath | ConvertFrom-Json
$PackageLock = Get-Content -Raw -LiteralPath $PackageLockPath | ConvertFrom-Json
$LockPackageKey = "node_modules/$PackageName"
$LockedPackage = $PackageLock.packages.PSObject.Properties[$LockPackageKey].Value
if (
    $InstalledPackage.version -ne $Metadata.version -or
    $LockedPackage.version -ne $Metadata.version
) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package version does not match the regenerated plan.")
    exit 51
}
if ($LockedPackage.integrity -ne $Integrity) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed package integrity does not match the regenerated plan.")
    exit 52
}

$CodexCliPath = Join-Path $CanonicalBootstrapRoot "node_modules\.bin\codex.cmd"
if (-not [System.IO.File]::Exists($CodexCliPath)) {
    [Console]::Error.WriteLine("SelfWorkFlow: installed Codex CLI shim is missing.")
    exit 53
}

$CliVersionOutput = & $CodexCliPath --version 2>&1
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine(
        "SelfWorkFlow: Codex CLI version command failed with exit code $LASTEXITCODE."
    )
    exit 54
}
$CliVersion = ($CliVersionOutput -join [Environment]::NewLine).Trim()

$PackageTreeHash = Get-PackageTreeHash -PackageRoot $InstalledPackageRoot
$FinalSddl = Get-VerifiedBootstrapSddl -Path $CanonicalBootstrapRoot
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
$ManifestPath = Join-Path $CanonicalBootstrapRoot "bootstrap-tool-manifest.json"
[System.IO.File]::WriteAllText(
    $ManifestPath,
    $ManifestJson,
    [System.Text.UTF8Encoding]::new($false)
)
