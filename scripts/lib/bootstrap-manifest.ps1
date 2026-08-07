Set-StrictMode -Version Latest

function Get-SelfWorkflowSha256Text {
    param([Parameter(Mandatory = $true)][string]$Text)

    $Algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Hash = $Algorithm.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
        return ([System.BitConverter]::ToString($Hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Algorithm.Dispose()
    }
}

function Get-SelfWorkflowPackageTreeHash {
    param([Parameter(Mandatory = $true)][string]$PackageRoot)

    $Entries = @(Get-ChildItem -LiteralPath $PackageRoot -File -Recurse -Force |
        ForEach-Object {
            [pscustomobject]@{
                File = $_
                RelativePath = $_.FullName.Substring($PackageRoot.Length).
                    TrimStart("\").Replace("\", "/")
            }
        } | Sort-Object RelativePath)
    $Hasher = [System.Security.Cryptography.IncrementalHash]::CreateHash(
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $Buffer = New-Object byte[] 65536
    try {
        foreach ($Entry in $Entries) {
            $Hasher.AppendData([System.Text.Encoding]::UTF8.GetBytes($Entry.RelativePath))
            $Hasher.AppendData([byte[]]@(0))
            $Stream = [System.IO.File]::OpenRead($Entry.File.FullName)
            try {
                while (($Count = $Stream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                    $Hasher.AppendData($Buffer, 0, $Count)
                }
            }
            finally {
                $Stream.Dispose()
            }
            $Hasher.AppendData([byte[]]@(0))
        }
        $Hash = $Hasher.GetHashAndReset()
        return "sha256:$(([BitConverter]::ToString($Hash)).Replace('-', '').ToLowerInvariant())"
    }
    finally {
        $Hasher.Dispose()
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

    $RootProperty = $Manifest.PSObject.Properties["bootstrapRoot"]
    if ($null -eq $RootProperty -or $RootProperty.Value -isnot [string]) {
        throw "Manifest bootstrapRoot is invalid."
    }
    $CanonicalRoot = [System.IO.Path]::GetFullPath($RootProperty.Value).TrimEnd("\")
    $CanonicalBoundary = [System.IO.Path]::GetFullPath($AllowedBoundary).TrimEnd("\")
    $PlannedRoot = [System.IO.Path]::GetFullPath([string]$Plan.bootstrapRoot).TrimEnd("\")
    $BoundaryPrefix = $CanonicalBoundary + [System.IO.Path]::DirectorySeparatorChar
    if (
        $RootProperty.Value -cne $CanonicalRoot -or
        $CanonicalRoot -cne $PlannedRoot -or
        -not (
            $CanonicalRoot.Equals(
                $CanonicalBoundary,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            $CanonicalRoot.StartsWith(
                $BoundaryPrefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
    ) {
        throw "Manifest bootstrapRoot is outside its canonical boundary."
    }

    $SddlProperty = $Manifest.PSObject.Properties["daclSddl"]
    if ($null -eq $SddlProperty -or $SddlProperty.Value -isnot [string]) {
        throw "Manifest DACL is invalid."
    }
    $Descriptor = [System.Security.AccessControl.RawSecurityDescriptor]::new(
        $SddlProperty.Value
    )
    $ProtectedFlag = [System.Security.AccessControl.ControlFlags]::DiscretionaryAclProtected
    $ExpectedAceFlags = (
        [int][System.Security.AccessControl.AceFlags]::ContainerInherit -bor
        [int][System.Security.AccessControl.AceFlags]::ObjectInherit
    )
    $ExpectedSids = @(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        "S-1-5-18"
    )
    if (
        ($Descriptor.ControlFlags -band $ProtectedFlag) -eq 0 -or
        $Descriptor.DiscretionaryAcl.Count -ne 2
    ) {
        throw "Manifest DACL is not protected and exact."
    }
    $ObservedSids = @()
    foreach ($Ace in $Descriptor.DiscretionaryAcl) {
        if (
            $Ace -isnot [System.Security.AccessControl.CommonAce] -or
            $Ace.AceQualifier -ne [System.Security.AccessControl.AceQualifier]::AccessAllowed -or
            $Ace.AccessMask -ne [int][System.Security.AccessControl.FileSystemRights]::FullControl -or
            [int]$Ace.AceFlags -ne $ExpectedAceFlags
        ) {
            throw "Manifest DACL contains an unexpected access rule."
        }
        $ObservedSids += $Ace.SecurityIdentifier.Value
    }
    if (
        @($ObservedSids | Where-Object { $_ -notin $ExpectedSids }).Count -ne 0 -or
        @($ExpectedSids | Where-Object { $_ -notin $ObservedSids }).Count -ne 0 -or
        $SddlProperty.Value -cne $ExpectedSddl
    ) {
        throw "Manifest DACL does not match the bootstrap root."
    }

    $PackageProperty = $Manifest.PSObject.Properties["package"]
    $CliVersionProperty = $Manifest.PSObject.Properties["cliVersion"]
    if (
        $null -eq $PackageProperty -or
        $PackageProperty.Value -isnot [System.Management.Automation.PSCustomObject] -or
        $null -eq $CliVersionProperty -or
        $CliVersionProperty.Value -isnot [string]
    ) {
        throw "Manifest package version binding is invalid."
    }
    $Package = $PackageProperty.Value
    $NameProperty = $Package.PSObject.Properties["name"]
    $VersionProperty = $Package.PSObject.Properties["version"]
    $IntegrityProperty = $Package.PSObject.Properties["integrity"]
    $SemVer = "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
    if (
        $null -eq $NameProperty -or $NameProperty.Value -isnot [string] -or
        $null -eq $VersionProperty -or $VersionProperty.Value -isnot [string] -or
        $null -eq $IntegrityProperty -or $IntegrityProperty.Value -isnot [string] -or
        $NameProperty.Value -cne "@openai/codex" -or
        $NameProperty.Value -cne $Plan.package.name -or
        $VersionProperty.Value -cne $Plan.package.version -or
        $IntegrityProperty.Value -cne $Plan.package.integrity -or
        $CliVersionProperty.Value -cne $VersionProperty.Value -or
        $CliVersionProperty.Value -notmatch $SemVer
    ) {
        throw "Manifest package or CLI version does not match the plan."
    }

    $TreeHashProperty = $Manifest.PSObject.Properties["packageTreeHash"]
    $PlanHashProperty = $Manifest.PSObject.Properties["planHash"]
    $PlanData = [ordered]@{
        schemaVersion = $Plan.schemaVersion
        bootstrapRoot = $Plan.bootstrapRoot
        package = $Plan.package
        execution = $Plan.execution
        security = $Plan.security
        sideEffects = $Plan.sideEffects
    }
    $ExpectedPlanHash = Get-SelfWorkflowSha256Text -Text (
        $PlanData | ConvertTo-Json -Depth 8 -Compress
    )
    if (
        $null -eq $TreeHashProperty -or $TreeHashProperty.Value -isnot [string] -or
        $null -eq $PlanHashProperty -or $PlanHashProperty.Value -isnot [string] -or
        $TreeHashProperty.Value -cne (
            Get-SelfWorkflowPackageTreeHash -PackageRoot $PackageRoot
        ) -or
        $PlanHashProperty.Value -cne $ExpectedPlanHash
    ) {
        throw "Manifest package tree or plan hash is invalid."
    }
}
