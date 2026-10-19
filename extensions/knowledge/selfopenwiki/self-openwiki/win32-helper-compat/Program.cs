// Copyright KuaiShou Games, Inc. All Rights Reserved.
// Author: zhaoxiaohan06@kuaishou.com

using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Win32.SafeHandles;

[assembly: SupportedOSPlatform("windows")]

internal static class Program
{
    private const uint GenericRead = 0x80000000;
    private const uint ShareReadWriteDelete = 0x00000007;
    private const uint OpenExisting = 3;
    private const uint FileAttributeNormal = 0x00000080;
    private const uint FileFlagSequentialScan = 0x08000000;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const uint DriveFixed = 3;
    private const uint FileTypeDisk = 0x0001;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static int Main()
    {
        if (!OperatingSystem.IsWindows())
        {
            WriteFailure("platform_unsupported");
            return 2;
        }

        try
        {
            string inputText = Console.In.ReadToEnd();
            HelperRequest? request = JsonSerializer.Deserialize<HelperRequest>(inputText, JsonOptions);
            if (request is null || request.Version != 1)
            {
                WriteFailure("invalid_request");
                return 2;
            }
            object result = request.Operation switch
            {
                "inspect-copy" when request.SourcePath is not null &&
                    request.DestinationPath is not null &&
                    request.MaxBytes is not null &&
                    request.TargetPath is null &&
                    request.Directory is null => InspectAndCopy(
                        new CopyRequest(
                            request.SourcePath,
                            request.DestinationPath,
                             request.MaxBytes.Value)),
                "inspect-path" when request.SourcePath is not null &&
                    request.DestinationPath is null &&
                    request.MaxBytes is null &&
                    request.TargetPath is null &&
                    request.Directory is null => InspectPath(request.SourcePath),
                "secure-path" when request.TargetPath is not null &&
                    request.Directory is not null &&
                    request.SourcePath is null &&
                    request.DestinationPath is null &&
                    request.MaxBytes is null => SecurePrivatePath(
                        request.TargetPath,
                        request.Directory.Value),
                _ => throw new SourceRejectedException(),
            };
            Console.Out.Write(JsonSerializer.Serialize(result, JsonOptions));
            return 0;
        }
        catch (SourceChangedException)
        {
            WriteFailure("source_changed");
            return 3;
        }
        catch (SourceRejectedException)
        {
            WriteFailure("source_rejected");
            return 4;
        }
        catch (SourceTooLargeException)
        {
            WriteFailure("source_too_large");
            return 5;
        }
        catch
        {
            WriteFailure("helper_failure");
            return 6;
        }
    }

    private static CopyResult InspectAndCopy(CopyRequest request)
    {
        if (request.MaxBytes <= 0 || request.MaxBytes > 1_073_741_824)
        {
            throw new SourceRejectedException();
        }

        string sourcePath = ValidateFixedLocalPath(request.SourcePath);
        string destinationPath = ValidateFixedLocalPath(request.DestinationPath);
        string? destinationDirectory = Path.GetDirectoryName(destinationPath);
        if (destinationDirectory is null)
        {
            throw new SourceRejectedException();
        }

        InspectAncestors(sourcePath);
        InspectAncestors(destinationDirectory);
        if (!Directory.Exists(destinationDirectory))
        {
            throw new SourceChangedException();
        }
        if (File.Exists(destinationPath) || Directory.Exists(destinationPath))
        {
            throw new SourceRejectedException();
        }

        using SafeFileHandle sourceHandle = OpenSource(sourcePath);
        if (GetFileType(sourceHandle) != FileTypeDisk)
        {
            throw new SourceRejectedException();
        }
        FileAttributeTagInformation sourceTag = ReadAttributeTag(sourceHandle);
        if ((sourceTag.FileAttributes & (FileAttributeReparsePoint | FileAttributeDirectory)) != 0)
        {
            throw new SourceRejectedException();
        }
        FileIdentity before = ReadIdentity(sourceHandle);
        string finalPath = NormalizeFinalPath(ReadFinalPath(sourceHandle));
        if (!PathEquals(sourcePath, finalPath))
        {
            throw new SourceRejectedException();
        }
        if (before.Size > request.MaxBytes)
        {
            throw new SourceTooLargeException();
        }
        WaitForTestBarrier("opened");

        long copied = 0;
        string hash;
        try
        {
            using FileStream source = new(sourceHandle, FileAccess.Read, 64 * 1024, isAsync: false);
            using FileStream destination = new(
                destinationPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                64 * 1024,
                FileOptions.WriteThrough);
            using IncrementalHash hasher = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            byte[] buffer = new byte[64 * 1024];
            while (true)
            {
                int read = source.Read(buffer, 0, buffer.Length);
                if (read == 0)
                {
                    break;
                }
                copied += read;
                if (copied > request.MaxBytes)
                {
                    throw new SourceTooLargeException();
                }
                hasher.AppendData(buffer, 0, read);
                destination.Write(buffer, 0, read);
                if (copied == read)
                {
                    WaitForTestBarrier("copying");
                }
            }
            destination.Flush(flushToDisk: true);
            hash = Convert.ToHexString(hasher.GetHashAndReset()).ToLowerInvariant();
        }
        catch
        {
            TryDelete(destinationPath);
            throw;
        }

        if (copied != before.Size)
        {
            TryDelete(destinationPath);
            throw new SourceChangedException();
        }

        using SafeFileHandle currentHandle = OpenSource(sourcePath);
        FileAttributeTagInformation currentTag = ReadAttributeTag(currentHandle);
        if ((currentTag.FileAttributes & (FileAttributeReparsePoint | FileAttributeDirectory)) != 0)
        {
            TryDelete(destinationPath);
            throw new SourceChangedException();
        }
        FileIdentity after = ReadIdentity(currentHandle);
        string currentFinalPath = NormalizeFinalPath(ReadFinalPath(currentHandle));
        if (!before.Equals(after) || !PathEquals(finalPath, currentFinalPath))
        {
            TryDelete(destinationPath);
            throw new SourceChangedException();
        }
        InspectAncestors(sourcePath);

        return new CopyResult(
            Version: 1,
            Ok: true,
            CanonicalPath: finalPath,
            Size: copied,
            Hash: $"sha256:{hash}",
            ReparseTagChecked: true,
            VolumeSerial: before.VolumeSerial,
            FileIndex: before.FileIndex.ToString("x16"),
            LastWriteFileTime: before.LastWriteFileTime.ToString());
    }

    private static PathInspectionResult InspectPath(string requestedPath)
    {
        string sourcePath = ValidateFixedLocalPath(requestedPath);
        InspectAncestors(sourcePath);
        using SafeFileHandle sourceHandle = OpenPath(sourcePath);
        if (GetFileType(sourceHandle) != FileTypeDisk)
        {
            throw new SourceRejectedException();
        }
        FileAttributeTagInformation tag = ReadAttributeTag(sourceHandle);
        if ((tag.FileAttributes & FileAttributeReparsePoint) != 0)
        {
            throw new SourceRejectedException();
        }
        FileIdentity identity = ReadIdentity(sourceHandle);
        string finalPath = NormalizeFinalPath(ReadFinalPath(sourceHandle));
        if (!PathEquals(sourcePath, finalPath))
        {
            throw new SourceRejectedException();
        }
        InspectAncestors(sourcePath);
        return new PathInspectionResult(
            Version: 1,
            Ok: true,
            CanonicalPath: finalPath,
            Directory: (tag.FileAttributes & FileAttributeDirectory) != 0,
            Size: identity.Size,
            VolumeSerial: identity.VolumeSerial,
            FileIndex: identity.FileIndex.ToString("x16"),
            LastWriteFileTime: identity.LastWriteFileTime.ToString(),
            ReparseTagChecked: true);
    }

    private static SecurePathResult SecurePrivatePath(string requestedPath, bool directory)
    {
        string targetPath = ValidateFixedLocalPath(requestedPath);
        InspectAncestors(targetPath);
        using (SafeFileHandle targetHandle = OpenPath(targetPath))
        {
            FileAttributeTagInformation targetTag = ReadAttributeTag(targetHandle);
            bool actualDirectory = (targetTag.FileAttributes & FileAttributeDirectory) != 0;
            if ((targetTag.FileAttributes & FileAttributeReparsePoint) != 0 ||
                actualDirectory != directory)
            {
                throw new SourceRejectedException();
            }
        }

        SecurityIdentifier currentUser = WindowsIdentity.GetCurrent().User
            ?? throw new SourceRejectedException();
        SecurityIdentifier localSystem = new(WellKnownSidType.LocalSystemSid, null);
        InheritanceFlags inheritance = directory
            ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit
            : InheritanceFlags.None;

        FileSystemSecurity security = directory
            ? new DirectorySecurity()
            : new FileSecurity();
        security.SetOwner(currentUser);
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.AddAccessRule(new FileSystemAccessRule(
            currentUser,
            FileSystemRights.FullControl,
            inheritance,
            PropagationFlags.None,
            AccessControlType.Allow));
        security.AddAccessRule(new FileSystemAccessRule(
            localSystem,
            FileSystemRights.FullControl,
            inheritance,
            PropagationFlags.None,
            AccessControlType.Allow));

        if (directory)
        {
            FileSystemAclExtensions.SetAccessControl(
                new DirectoryInfo(targetPath),
                (DirectorySecurity)security);
        }
        else
        {
            FileSystemAclExtensions.SetAccessControl(
                new FileInfo(targetPath),
                (FileSecurity)security);
        }

        FileSystemSecurity verified = directory
            ? FileSystemAclExtensions.GetAccessControl(
                new DirectoryInfo(targetPath),
                AccessControlSections.Owner | AccessControlSections.Access)
            : FileSystemAclExtensions.GetAccessControl(
                new FileInfo(targetPath),
                AccessControlSections.Owner | AccessControlSections.Access);
        if (verified.GetOwner(typeof(SecurityIdentifier)) is not SecurityIdentifier owner)
        {
            throw new SourceRejectedException();
        }
        AuthorizationRuleCollection rules = verified.GetAccessRules(
            includeExplicit: true,
            includeInherited: true,
            targetType: typeof(SecurityIdentifier));
        if (!owner.Equals(currentUser) || !verified.AreAccessRulesProtected || rules.Count != 2)
        {
            throw new SourceRejectedException();
        }

        HashSet<string> expectedSids = new(StringComparer.OrdinalIgnoreCase)
        {
            currentUser.Value,
            localSystem.Value,
        };
        foreach (AuthorizationRule rule in rules)
        {
            if (rule is not FileSystemAccessRule accessRule ||
                accessRule.IdentityReference is not SecurityIdentifier sid ||
                !expectedSids.Remove(sid.Value) ||
                accessRule.IsInherited ||
                accessRule.AccessControlType != AccessControlType.Allow ||
                (accessRule.FileSystemRights & FileSystemRights.FullControl) != FileSystemRights.FullControl ||
                accessRule.InheritanceFlags != inheritance ||
                accessRule.PropagationFlags != PropagationFlags.None)
            {
                throw new SourceRejectedException();
            }
        }
        if (expectedSids.Count != 0)
        {
            throw new SourceRejectedException();
        }
        VerifyRestrictedTokenCannotAccess(targetPath, directory, currentUser);

        return new SecurePathResult(
            Version: 1,
            Ok: true,
            OwnerSid: currentUser.Value,
            DaclProtected: true,
            ExplicitFullControlSids: [currentUser.Value, localSystem.Value]);
    }

    private static string ValidateFixedLocalPath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value.IndexOf('\0') >= 0)
        {
            throw new SourceRejectedException();
        }
        if (value.StartsWith("\\\\", StringComparison.Ordinal) ||
            value.StartsWith("\\?\\", StringComparison.Ordinal) ||
            value.StartsWith("\\.\\", StringComparison.Ordinal))
        {
            throw new SourceRejectedException();
        }
        if (!Path.IsPathFullyQualified(value) || value.Length < 3 || value[1] != ':')
        {
            throw new SourceRejectedException();
        }
        string fullPath = Path.GetFullPath(value);
        if (fullPath.IndexOf(':', 2) >= 0)
        {
            throw new SourceRejectedException();
        }
        string? root = Path.GetPathRoot(fullPath);
        if (root is null || GetDriveTypeW(root) != DriveFixed)
        {
            throw new SourceRejectedException();
        }
        return fullPath;
    }

    private static void InspectAncestors(string path)
    {
        string? root = Path.GetPathRoot(path);
        if (root is null)
        {
            throw new SourceRejectedException();
        }
        string relative = Path.GetRelativePath(root, path);
        string current = root;
        foreach (string segment in relative.Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, segment);
            FileAttributes attributes;
            try
            {
                attributes = File.GetAttributes(current);
            }
            catch (FileNotFoundException)
            {
                throw new SourceChangedException();
            }
            catch (DirectoryNotFoundException)
            {
                throw new SourceChangedException();
            }
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new SourceRejectedException();
            }
        }
    }

    private static SafeFileHandle OpenSource(string path)
    {
        return OpenPath(path, FileFlagSequentialScan);
    }

    private static SafeFileHandle OpenPath(string path, uint additionalFlags = 0)
    {
        SafeFileHandle handle = CreateFileW(
            path,
            GenericRead,
            ShareReadWriteDelete,
            IntPtr.Zero,
            OpenExisting,
            FileAttributeNormal | FileFlagBackupSemantics | FileFlagOpenReparsePoint | additionalFlags,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            handle.Dispose();
            throw new SourceChangedException();
        }
        return handle;
    }

    private static FileAttributeTagInformation ReadAttributeTag(SafeFileHandle handle)
    {
        if (!GetFileInformationByHandleEx(
                handle,
                FileInfoByHandleClass.FileAttributeTagInfo,
                out FileAttributeTagInformation information,
                (uint)Marshal.SizeOf<FileAttributeTagInformation>()))
        {
            throw new SourceRejectedException();
        }
        return information;
    }

    private static FileIdentity ReadIdentity(SafeFileHandle handle)
    {
        if (!GetFileInformationByHandle(handle, out ByHandleFileInformation info))
        {
            throw new SourceRejectedException();
        }
        long size = ((long)info.FileSizeHigh << 32) | info.FileSizeLow;
        ulong fileIndex = ((ulong)info.FileIndexHigh << 32) | info.FileIndexLow;
        long lastWrite = ((long)info.LastWriteTime.High << 32) | info.LastWriteTime.Low;
        return new FileIdentity(info.VolumeSerialNumber, fileIndex, size, lastWrite);
    }

    private static string ReadFinalPath(SafeFileHandle handle)
    {
        char[] buffer = new char[32_768];
        uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Length, 0);
        if (length == 0 || length >= buffer.Length)
        {
            throw new SourceRejectedException();
        }
        return new string(buffer, 0, (int)length);
    }

    private static string NormalizeFinalPath(string value)
    {
        const string extendedPrefix = "\\\\?\\";
        return value.StartsWith(extendedPrefix, StringComparison.Ordinal)
            ? value[extendedPrefix.Length..]
            : value;
    }

    private static bool PathEquals(string left, string right) =>
        string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
            StringComparison.OrdinalIgnoreCase);

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch
        {
            // The caller treats a retained quarantine file as cleanup failure.
        }
    }

    private static void WaitForTestBarrier(string stage)
    {
        string? barrierDirectory = Environment.GetEnvironmentVariable("KG_C7_TEST_BARRIER_DIR");
        string? requestedStage = Environment.GetEnvironmentVariable("KG_C7_TEST_BARRIER_STAGE");
        if (string.IsNullOrEmpty(barrierDirectory) || requestedStage != stage)
        {
            return;
        }
        string canonicalDirectory = Path.GetFullPath(barrierDirectory);
        File.WriteAllText(Path.Combine(canonicalDirectory, $"{stage}.ready"), "ready");
        string continuation = Path.Combine(canonicalDirectory, $"{stage}.continue");
        DateTime deadline = DateTime.UtcNow.AddSeconds(10);
        while (!File.Exists(continuation))
        {
            if (DateTime.UtcNow >= deadline)
            {
                throw new SourceChangedException();
            }
            Thread.Sleep(10);
        }
    }

    private static void VerifyRestrictedTokenCannotAccess(
        string targetPath,
        bool directory,
        SecurityIdentifier currentUser)
    {
        if (!OpenProcessToken(
            GetCurrentProcess(),
            TokenDuplicate | TokenQuery | TokenImpersonate,
            out SafeAccessTokenHandle processToken))
        {
            throw new SourceRejectedException();
        }
        using (processToken)
        {
            byte[] sidBytes = new byte[currentUser.BinaryLength];
            currentUser.GetBinaryForm(sidBytes, 0);
            GCHandle pinnedSid = GCHandle.Alloc(sidBytes, GCHandleType.Pinned);
            try
            {
                SidAndAttributes[] disabled =
                [
                    new SidAndAttributes
                    {
                        Sid = pinnedSid.AddrOfPinnedObject(),
                        Attributes = 0,
                    },
                ];
                if (!CreateRestrictedToken(
                    processToken,
                    DisableMaxPrivilege,
                    1,
                    disabled,
                    0,
                    IntPtr.Zero,
                    0,
                    IntPtr.Zero,
                    out SafeAccessTokenHandle restrictedToken))
                {
                    throw new SourceRejectedException();
                }
                using (restrictedToken)
                {
                    bool denied = WindowsIdentity.RunImpersonated(
                        restrictedToken,
                        () => IsAccessDenied(targetPath, directory));
                    if (!denied)
                    {
                        throw new SourceRejectedException();
                    }
                }
            }
            finally
            {
                pinnedSid.Free();
            }
        }
    }

    private static bool IsAccessDenied(string targetPath, bool directory)
    {
        try
        {
            if (directory)
            {
                using IEnumerator<string> entries = Directory
                    .EnumerateFileSystemEntries(targetPath)
                    .GetEnumerator();
                _ = entries.MoveNext();
            }
            else
            {
                using FileStream stream = new(
                    targetPath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete);
                _ = stream.ReadByte();
            }
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return true;
        }
    }

    private static void WriteFailure(string code) =>
        Console.Out.Write(JsonSerializer.Serialize(new FailureResult(1, false, code), JsonOptions));

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation information);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(
        SafeFileHandle file,
        FileInfoByHandleClass informationClass,
        out FileAttributeTagInformation information,
        uint bufferSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint GetFileType(SafeFileHandle file);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle file,
        [Out] char[] filePath,
        uint filePathLength,
        uint flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern uint GetDriveTypeW(string rootPathName);

    private const uint TokenDuplicate = 0x0002;
    private const uint TokenImpersonate = 0x0004;
    private const uint TokenQuery = 0x0008;
    private const uint DisableMaxPrivilege = 0x00000001;

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(
        IntPtr processHandle,
        uint desiredAccess,
        out SafeAccessTokenHandle tokenHandle);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateRestrictedToken(
        SafeAccessTokenHandle existingTokenHandle,
        uint flags,
        uint disableSidCount,
        [In] SidAndAttributes[] sidsToDisable,
        uint deletePrivilegeCount,
        IntPtr privilegesToDelete,
        uint restrictedSidCount,
        IntPtr sidsToRestrict,
        out SafeAccessTokenHandle newTokenHandle);

    private sealed record HelperRequest(
        int Version,
        string Operation,
        string? SourcePath,
        string? DestinationPath,
        long? MaxBytes,
        string? TargetPath,
        bool? Directory);

    private sealed record CopyRequest(
        string SourcePath,
        string DestinationPath,
        long MaxBytes);

    private sealed record CopyResult(
        int Version,
        bool Ok,
        string CanonicalPath,
        long Size,
        string Hash,
        bool ReparseTagChecked,
        uint VolumeSerial,
        string FileIndex,
        string LastWriteFileTime);

    private sealed record PathInspectionResult(
        int Version,
        bool Ok,
        string CanonicalPath,
        bool Directory,
        long Size,
        uint VolumeSerial,
        string FileIndex,
        string LastWriteFileTime,
        bool ReparseTagChecked);

    private sealed record FailureResult(int Version, bool Ok, string Code);

    private sealed record SecurePathResult(
        int Version,
        bool Ok,
        string OwnerSid,
        bool DaclProtected,
        string[] ExplicitFullControlSids);

    private readonly record struct FileIdentity(
        uint VolumeSerial,
        ulong FileIndex,
        long Size,
        long LastWriteFileTime);

    private enum FileInfoByHandleClass
    {
        FileAttributeTagInfo = 9,
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileAttributeTagInformation
    {
        public uint FileAttributes;
        public uint ReparseTag;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint Low;
        public uint High;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public FileTime CreationTime;
        public FileTime LastAccessTime;
        public FileTime LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes
    {
        public IntPtr Sid;
        public uint Attributes;
    }

    private sealed class SourceRejectedException : Exception;
    private sealed class SourceChangedException : Exception;
    private sealed class SourceTooLargeException : Exception;
}
