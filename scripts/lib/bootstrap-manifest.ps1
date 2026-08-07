Set-StrictMode -Version Latest

$script:SelfWorkflowCanonicalSemVerPattern = '(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'

function Get-SelfWorkflowCanonicalSemVerPattern {
    return $script:SelfWorkflowCanonicalSemVerPattern
}

function Test-SelfWorkflowCanonicalSemVer {
    param([Parameter(Mandatory = $true)][string]$Value)
    return $Value -cmatch ("^" + $script:SelfWorkflowCanonicalSemVerPattern + "$")
}

function Get-SelfWorkflowPackageTreeHash {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)
    return (Get-SelfWorkflowTreeSnapshot $PackageRoot).treeHash
}

function Assert-SelfWorkflowExactBootstrapSddl {
    param([Parameter(Mandatory = $true)][string]$Sddl)
    $Descriptor = [Security.AccessControl.RawSecurityDescriptor]::new($Sddl)
    $ExpectedFlags = [int][Security.AccessControl.AceFlags]::ContainerInherit -bor [int][Security.AccessControl.AceFlags]::ObjectInherit
    $ExpectedSids = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, "S-1-5-18")
    $Aces = $Descriptor.DiscretionaryAcl
    if (($Descriptor.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -eq 0 -or $Aces.Count -ne 2) {
        throw "BootstrapRoot SDDL is not protected and exact."
    }
    foreach ($Ace in $Aces) {
        if ($Ace -isnot [Security.AccessControl.CommonAce] -or
            $Ace.AceQualifier -ne [Security.AccessControl.AceQualifier]::AccessAllowed -or
            $Ace.AccessMask -ne [int][Security.AccessControl.FileSystemRights]::FullControl -or
            [int]$Ace.AceFlags -ne $ExpectedFlags -or
            $Ace.SecurityIdentifier.Value -notin $ExpectedSids) { throw "BootstrapRoot SDDL rule is invalid." }
    }
    foreach ($Sid in $ExpectedSids) {
        if (@($Aces | Where-Object { $_.SecurityIdentifier.Value -eq $Sid }).Count -ne 1) { throw "BootstrapRoot SDDL principals are invalid." }
    }
}

function Assert-SelfWorkflowBootstrapManifest {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string]$AllowedBoundary,
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedSddl
    )

    $ManifestTypes = @{
        schemaVersion = [int]; bootstrapRoot = [string]; package = [Management.Automation.PSCustomObject]
        packageTreeHash = [string]; daclSddl = [string]; expectedCliVersion = [string]
        cliVersionVerification = [string]; planHash = [string]
    }
    Assert-SelfWorkflowExactProperties $Manifest @($ManifestTypes.Keys) $ManifestTypes
    $Package = $Manifest.package
    $PackageTypes = @{ name = [string]; version = [string]; integrity = [string] }
    Assert-SelfWorkflowExactProperties $Package @($PackageTypes.Keys) $PackageTypes
    Assert-SelfWorkflowPlanV2Shape $Plan

    $CanonicalRoot = [IO.Path]::GetFullPath($Manifest.bootstrapRoot).TrimEnd("\")
    $Boundary = [IO.Path]::GetFullPath($AllowedBoundary).TrimEnd("\")
    $BoundaryPrefix = $Boundary + [IO.Path]::DirectorySeparatorChar
    if (
        $Manifest.schemaVersion -ne 2 -or $Manifest.cliVersionVerification -cne "not-run" -or
        $Manifest.bootstrapRoot -cne $CanonicalRoot -or $CanonicalRoot -cne $Plan.bootstrapRoot -or
        -not ($CanonicalRoot.Equals($Boundary, [StringComparison]::OrdinalIgnoreCase) -or
            $CanonicalRoot.StartsWith($BoundaryPrefix, [StringComparison]::OrdinalIgnoreCase))
    ) {
        throw "Manifest root, schema, or verification state is invalid."
    }

    Assert-SelfWorkflowExactBootstrapSddl $Manifest.daclSddl
    if ($Manifest.daclSddl -cne $ExpectedSddl) { throw "Manifest DACL does not match the bootstrap root." }
    if (
        $Package.name -cne "@openai/codex" -or $Package.name -cne $Plan.package.name -or
        $Package.version -cne $Plan.package.version -or $Package.integrity -cne $Plan.package.integrity -or
        $Manifest.expectedCliVersion -cne $Package.version -or
        -not (Test-SelfWorkflowCanonicalSemVer $Package.version) -or
        $Manifest.packageTreeHash -cne (Get-SelfWorkflowPackageTreeHash $PackageRoot) -or
        $Manifest.planHash -cne (Get-SelfWorkflowPlanHash $Plan)
    ) {
        throw "Manifest package, tree, or plan binding is invalid."
    }
}

function Publish-SelfWorkflowManifestAtomic {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string]$AllowedBoundary,
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedSddl
    )

    $TempPath = "$ManifestPath.$([Guid]::NewGuid().ToString('N')).tmp"
    $Published = $false
    try {
        if ([IO.File]::Exists($ManifestPath)) { throw "Manifest already exists." }
        Assert-SelfWorkflowBootstrapManifest $Manifest $Plan $AllowedBoundary $PackageRoot $ExpectedSddl
        $Bytes = [Text.UTF8Encoding]::new($false).GetBytes(($Manifest | ConvertTo-Json -Depth 4))
        $Stream = [IO.FileStream]::new($TempPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None, 4096, [IO.FileOptions]::WriteThrough)
        try { $Stream.Write($Bytes, 0, $Bytes.Length); $Stream.Flush($true) } finally { $Stream.Dispose() }
        [IO.File]::Move($TempPath, $ManifestPath); $Published = $true
        $WrittenManifest = [IO.File]::ReadAllText($ManifestPath) | ConvertFrom-Json -ErrorAction Stop
        Assert-SelfWorkflowBootstrapManifest $WrittenManifest $Plan $AllowedBoundary $PackageRoot $ExpectedSddl
        return $WrittenManifest
    }
    catch {
        if ($Published -and [IO.File]::Exists($ManifestPath)) { [IO.File]::Delete($ManifestPath) }
        if ([IO.File]::Exists($TempPath)) { [IO.File]::Delete($TempPath) }
        throw
    }
}
