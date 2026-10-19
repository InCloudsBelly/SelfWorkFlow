// Copyright KuaiShou Games, Inc. All Rights Reserved.
// Author: zhaoxiaohan06@kuaishou.com

using System.Buffers;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

internal static class Program
{
    internal const int ProtocolVersion = 1;
    internal const int MaxFrameBytes = 16 * 1024 * 1024;
    internal const int MaxFileBytes = 10 * 1024 * 1024;
    internal const int MaxPathBytes = 4096;
    internal const int MaxComponentBytes = 255;
    internal const uint GenericRead = 0x80000000;
    internal const uint GenericWrite = 0x40000000;
    internal const uint FileShareRead = 0x00000001;
    internal const uint FileShareWrite = 0x00000002;
    internal const uint OpenExisting = 3;
    internal const uint FileFlagBackupSemantics = 0x02000000;
    internal const uint FileFlagOpenReparsePoint = 0x00200000;
    internal const uint FileAttributeReparsePoint = 0x00000400;
    internal const uint MoveFileReplaceExisting = 0x00000001;

    public static int Main(string[] args)
    {
        try
        {
            var root = ReadRequiredOption(args, "--root");
            var attemptId = ReadOptionalOption(args, "--attempt-id") ?? "development";
            var manifestHash = ReadOptionalOption(args, "--manifest-sha256") ?? "unbound-development";
            var toolchainId = ReadOptionalOption(args, "--toolchain-id") ?? "dotnet-9.0.304-win-x64";
            if (!string.Equals(ReadOptionalOption(args, "--stdio") ?? "", "", StringComparison.Ordinal) &&
                !args.Contains("--stdio", StringComparer.Ordinal))
                throw new ProtocolException("invalid startup mode");

            using var backend = SecureBackend.Open(root);
            using var input = Console.OpenStandardInput();
            using var output = Console.OpenStandardOutput();
            var identity = ImageIdentity.Read();
            while (ReadFrame(input, out var frame))
            {
                var response = Handle(frame, backend, attemptId, manifestHash, toolchainId, identity);
                WriteFrame(output, response);
            }
            return 0;
        }
        catch (Exception ex) when (ex is ProtocolException or IOException or UnauthorizedAccessException)
        {
            // Protocol and filesystem failures are fail-closed. Do not expose paths or data.
            return 2;
        }
    }

    private static byte[] Handle(byte[] frame, SecureBackend backend, string attemptId, string manifestHash, string toolchainId, ImageIdentity identity)
    {
        using var document = ParseStrictObject(frame);
        var root = document.RootElement;
        var id = RequiredString(root, "id", 128);
        var op = RequiredString(root, "op", 64);
        var allowed = op switch
        {
            "handshake" => new[] { "id", "op", "protocolVersion", "mountId" },
            "ping" => new[] { "id", "op" },
            "read" => new[] { "id", "op", "mountId", "path" },
            "write" => new[] { "id", "op", "mountId", "path", "dataBase64" },
            "list" or "mkdir" or "remove" => new[] { "id", "op", "mountId", "path" },
            "rename" => new[] { "id", "op", "mountId", "from", "to" },
            _ => throw new ProtocolException("unknown operation")
        };
        RejectUnknown(root, allowed);
        try
        {
            return op switch
            {
                "handshake" => Handshake(root, id, attemptId, manifestHash, toolchainId, identity, backend.RootIdentity),
                "ping" => Ok(id, new { ready = true, protocolVersion = ProtocolVersion }),
                "read" => backend.Read(id, Mount(root), RequiredString(root, "path", MaxPathBytes)),
                "write" => backend.Write(id, Mount(root), RequiredString(root, "path", MaxPathBytes), RequiredBase64(root, "dataBase64")),
                "list" => backend.List(id, Mount(root), RequiredString(root, "path", MaxPathBytes)),
                "mkdir" => backend.Mkdir(id, Mount(root), RequiredString(root, "path", MaxPathBytes)),
                "remove" => backend.Remove(id, Mount(root), RequiredString(root, "path", MaxPathBytes)),
                "rename" => backend.Rename(id, Mount(root), RequiredString(root, "from", MaxPathBytes), RequiredString(root, "to", MaxPathBytes)),
                _ => throw new ProtocolException("unknown operation")
            };
        }
        catch (PathRejectedException ex)
        {
            return Error(id, "path-rejected", ex.Message);
        }
        catch (ProtocolException ex)
        {
            return Error(id, "protocol-rejected", ex.Message);
        }
        catch (FileNotFoundException)
        {
            return Error(id, "not-found", "requested entry is unavailable");
        }
        catch (IOException)
        {
            return Error(id, "io-failed", "operation failed closed");
        }
    }

    private static byte[] Handshake(JsonElement root, string id, string attemptId, string manifestHash, string toolchainId, ImageIdentity identity, Native.ByHandleFileInformation mountIdentity)
    {
        if (!root.TryGetProperty("protocolVersion", out var version) || version.ValueKind != JsonValueKind.Number || version.GetInt32() != ProtocolVersion)
            throw new ProtocolException("protocol version mismatch");
        if (root.TryGetProperty("mountId", out var mount) && (mount.ValueKind != JsonValueKind.String || mount.GetString() != "root"))
            throw new ProtocolException("mount mismatch");
        return Ok(id, new
        {
            ready = true,
            protocolVersion = ProtocolVersion,
            runtimeVersion = Environment.Version.ToString(),
            toolchainId,
            artifactManifestSha256 = manifestHash,
            attemptId,
            mount = new { volumeSerial = mountIdentity.VolumeSerialNumber, fileIndexHigh = mountIdentity.FileIndexHigh, fileIndexLow = mountIdentity.FileIndexLow, numberOfLinks = mountIdentity.NumberOfLinks },
            image = new { volumeSerial = identity.VolumeSerial, fileIndexHigh = identity.FileIndexHigh, fileIndexLow = identity.FileIndexLow, sha256 = identity.Sha256 }
        });
    }

    private static string Mount(JsonElement root)
    {
        if (root.TryGetProperty("mountId", out var mount) && (mount.ValueKind != JsonValueKind.String || mount.GetString() != "root"))
            throw new ProtocolException("mount mismatch");
        return "root";
    }

    private static JsonDocument ParseStrictObject(byte[] frame)
    {
        if (frame.Length > MaxFrameBytes) throw new ProtocolException("frame too large");
        var options = new JsonDocumentOptions { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow, MaxDepth = 64 };
        var document = JsonDocument.Parse(frame, options);
        if (document.RootElement.ValueKind != JsonValueKind.Object) { document.Dispose(); throw new ProtocolException("request must be an object"); }
        return document;
    }

    private static void RejectUnknown(JsonElement objectValue, IReadOnlyCollection<string> allowed)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in objectValue.EnumerateObject())
            if (!seen.Add(property.Name) || !allowed.Contains(property.Name, StringComparer.Ordinal)) throw new ProtocolException("unknown or duplicate field");
    }

    private static string RequiredString(JsonElement objectValue, string name, int maxBytes)
    {
        if (!objectValue.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String) throw new ProtocolException($"missing {name}");
        var text = value.GetString() ?? throw new ProtocolException($"missing {name}");
        if (text.Length == 0 || Encoding.UTF8.GetByteCount(text) > maxBytes) throw new ProtocolException($"invalid {name}");
        return text.Normalize(NormalizationForm.FormC);
    }

    private static byte[] RequiredBase64(JsonElement objectValue, string name)
    {
        var text = RequiredString(objectValue, name, MaxFileBytes * 2);
        byte[] bytes;
        try { bytes = Convert.FromBase64String(text); } catch (FormatException) { throw new ProtocolException("invalid payload"); }
        if (bytes.Length > MaxFileBytes) throw new ProtocolException("payload too large");
        return bytes;
    }

    private static byte[] Ok(string id, object result) => JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result });
    private static byte[] Error(string id, string code, string message) => JsonSerializer.SerializeToUtf8Bytes(new { id, status = "error", error = new { code, message } });

    private static string? ReadOptionalOption(string[] args, string name)
    {
        var index = Array.IndexOf(args, name);
        if (index < 0) return null;
        if (index + 1 >= args.Length || args[index + 1].StartsWith("--", StringComparison.Ordinal)) return "";
        return args[index + 1];
    }

    private static string ReadRequiredOption(string[] args, string name) => ReadOptionalOption(args, name) switch
    {
        null or "" => throw new ProtocolException($"missing startup option {name}"),
        var value => value
    };

    private static bool ReadFrame(Stream input, out byte[] frame)
    {
        Span<byte> length = stackalloc byte[4];
        var count = ReadExactly(input, length);
        if (count == 0) { frame = []; return false; }
        if (count != 4) throw new ProtocolException("truncated frame header");
        var size = BitConverter.ToInt32(length);
        if (size <= 0 || size > MaxFrameBytes) throw new ProtocolException("frame bound exceeded");
        frame = GC.AllocateUninitializedArray<byte>(size);
        if (ReadExactly(input, frame) != size) throw new ProtocolException("truncated frame");
        return true;
    }

    private static int ReadExactly(Stream stream, Span<byte> buffer)
    {
        var total = 0;
        while (total < buffer.Length)
        {
            var read = stream.Read(buffer[total..]);
            if (read == 0) break;
            total += read;
        }
        return total;
    }

    private static void WriteFrame(Stream output, byte[] payload)
    {
        if (payload.Length <= 0 || payload.Length > MaxFrameBytes) throw new ProtocolException("response bound exceeded");
        Span<byte> length = stackalloc byte[4];
        BitConverter.TryWriteBytes(length, payload.Length);
        output.Write(length);
        output.Write(payload);
        output.Flush();
    }
}

internal sealed class SecureBackend : IDisposable
{
    private readonly string root;
    private readonly SafeFileHandle rootHandle;
    private readonly Native.ByHandleFileInformation rootIdentity;

    private SecureBackend(string root, SafeFileHandle rootHandle, Native.ByHandleFileInformation rootIdentity)
    {
        this.root = root;
        this.rootHandle = rootHandle;
        this.rootIdentity = rootIdentity;
    }

    internal Native.ByHandleFileInformation RootIdentity => rootIdentity;

    public static SecureBackend Open(string root)
    {
        var full = Path.GetFullPath(root);
        if (!Path.IsPathFullyQualified(full) || !Directory.Exists(full)) throw new IOException("backend root unavailable");
        var handle = Native.CreateFile(full, Program.GenericRead, Program.FileShareRead | Program.FileShareWrite, Program.OpenExisting, Program.FileFlagBackupSemantics | Program.FileFlagOpenReparsePoint);
        if (handle.IsInvalid) throw new IOException("backend root unavailable");
        if (!Native.GetFileInformationByHandle(handle, out var info) || (info.FileAttributes & Program.FileAttributeReparsePoint) != 0)
        { handle.Dispose(); throw new IOException("backend root is reparse"); }
        return new SecureBackend(full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar), handle, info);
    }

    public byte[] Read(string id, string mount, string relative)
    {
        EnsureRootStable();
        using var file = OpenRegular(relative, Program.GenericRead);
        using var stream = new FileStream(file, FileAccess.Read, 64 * 1024, false);
        if (stream.Length > 10 * 1024 * 1024) throw new ProtocolException("file too large");
        var bytes = new byte[stream.Length];
        var offset = 0;
        while (offset < bytes.Length)
        {
            var read = stream.Read(bytes, offset, bytes.Length - offset);
            if (read == 0) throw new IOException("short read");
            offset += read;
        }
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { dataBase64 = Convert.ToBase64String(bytes) } });
    }

    public byte[] Write(string id, string mount, string relative, byte[] bytes)
    {
        EnsureRootStable();
        var target = Resolve(relative, false, allowMissingFinal: true);
        ValidateExistingIfPresent(target);
        var temp = target + ".selfopenwiki-" + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 64 * 1024, FileOptions.WriteThrough))
        {
            stream.Write(bytes);
            stream.Flush(true);
        }
        try
        {
            using (var tempHandle = OpenRegularPath(temp, Program.GenericRead)) { }
            if (!Native.MoveFileEx(temp, target, Program.MoveFileReplaceExisting)) throw new IOException("atomic replace failed");
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
        ValidateExistingIfPresent(target);
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { writtenBytes = bytes.Length } });
    }

    public byte[] List(string id, string mount, string relative)
    {
        EnsureRootStable();
        var directory = Resolve(relative, true, allowMissingFinal: true);
        using var handle = OpenDirectoryPath(directory);
        var names = Directory.EnumerateFileSystemEntries(directory).Select(Path.GetFileName).Where(n => n is not null).Cast<string>().Order(StringComparer.Ordinal).ToArray();
        if (names.Length > 100_000) throw new ProtocolException("entry bound exceeded");
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { entries = names } });
    }

    public byte[] Mkdir(string id, string mount, string relative)
    {
        EnsureRootStable();
        var directory = Resolve(relative, true, allowMissingFinal: true);
        if (!Directory.Exists(directory))
        {
            var parent = Path.GetDirectoryName(directory) ?? throw new PathRejectedException("invalid directory");
            ValidateDirectory(parent);
            Directory.CreateDirectory(directory);
        }
        ValidateDirectory(directory);
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { created = true } });
    }

    public byte[] Remove(string id, string mount, string relative)
    {
        EnsureRootStable();
        var path = Resolve(relative, false);
        ValidateExistingIfPresent(path);
        if (Directory.Exists(path)) Directory.Delete(path, false); else File.Delete(path);
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { removed = true } });
    }

    public byte[] Rename(string id, string mount, string from, string to)
    {
        EnsureRootStable();
        var source = Resolve(from, false);
        var target = Resolve(to, false, allowMissingFinal: true);
        ValidateExistingIfPresent(source);
        ValidateExistingIfPresent(target);
        if (Directory.Exists(source)) Directory.Move(source, target); else File.Move(source, target, true);
        ValidateExistingIfPresent(target);
        EnsureRootStable();
        return JsonSerializer.SerializeToUtf8Bytes(new { id, status = "ok", result = new { renamed = true } });
    }

    private string Resolve(string relative, bool directory, bool allowMissingFinal = false)
    {
        PathValidator.Validate(relative, directory);
        var combined = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!combined.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new PathRejectedException("outside mount");
        var parts = relative.Split(['/', '\\'], StringSplitOptions.None);
        var current = root;
        foreach (var part in parts)
        {
            current = Path.Combine(current, part);
            if (allowMissingFinal && current == combined && !File.Exists(current) && !Directory.Exists(current)) break;
            using var handle = directory && current == combined ? OpenDirectoryPath(current) : OpenAnyPath(current);
            if (!Native.GetFileInformationByHandle(handle, out var info) || (info.FileAttributes & Program.FileAttributeReparsePoint) != 0) throw new PathRejectedException("reparse path");
        }
        return combined;
    }

    private SafeFileHandle OpenRegular(string relative, uint access) { var path = Resolve(relative, false); return OpenRegularPath(path, access); }

    private void EnsureRootStable()
    {
        if (rootHandle.IsInvalid || !Native.GetFileInformationByHandle(rootHandle, out var info) ||
            (info.FileAttributes & Program.FileAttributeReparsePoint) != 0 ||
            info.VolumeSerialNumber != rootIdentity.VolumeSerialNumber ||
            info.FileIndexHigh != rootIdentity.FileIndexHigh ||
            info.FileIndexLow != rootIdentity.FileIndexLow ||
            info.NumberOfLinks != rootIdentity.NumberOfLinks)
            throw new PathRejectedException("root identity changed");
    }
    private SafeFileHandle OpenRegularPath(string path, uint access)
    {
        var handle = OpenAnyPath(path, access);
        if (!Native.GetFileInformationByHandle(handle, out var info) || (info.FileAttributes & Program.FileAttributeReparsePoint) != 0 || (info.NumberOfLinks != 1)) { handle.Dispose(); throw new PathRejectedException("non-regular file"); }
        return handle;
    }
    private SafeFileHandle OpenAnyPath(string path, uint access = Program.GenericRead) => Native.CreateFile(path, access, Program.FileShareRead | Program.FileShareWrite, Program.OpenExisting, Program.FileFlagBackupSemantics | Program.FileFlagOpenReparsePoint);
    private SafeFileHandle OpenDirectoryPath(string path) => Native.CreateFile(path, Program.GenericRead, Program.FileShareRead | Program.FileShareWrite, Program.OpenExisting, Program.FileFlagBackupSemantics | Program.FileFlagOpenReparsePoint);
    private void ValidateDirectory(string path) { using var handle = OpenDirectoryPath(path); if (!Native.GetFileInformationByHandle(handle, out var info) || (info.FileAttributes & Program.FileAttributeReparsePoint) != 0) throw new PathRejectedException($"invalid directory attributes {info.FileAttributes:x}"); }
    private void ValidateExistingIfPresent(string path) { if (!File.Exists(path) && !Directory.Exists(path)) return; using var handle = OpenAnyPath(path); if (handle.IsInvalid || !Native.GetFileInformationByHandle(handle, out var info) || (info.FileAttributes & Program.FileAttributeReparsePoint) != 0 || info.NumberOfLinks != 1) throw new PathRejectedException("invalid target"); }
    public void Dispose() => rootHandle.Dispose();
}

internal static class PathValidator
{
    public static void Validate(string value, bool directory)
    {
        if (string.IsNullOrEmpty(value) || value.Length > 4096 || value.Contains('\\') || value.Contains(':') || value.Contains('*') || value.Contains('?') || value.Any(char.IsControl) || value.EndsWith('.') || value.EndsWith(' ') || value.Contains('~')) throw new PathRejectedException("invalid relative path");
        foreach (var component in value.Split('/', StringSplitOptions.None))
        {
            if (component is "" or "." or ".." || Encoding.UTF8.GetByteCount(component) > 255) throw new PathRejectedException("invalid component");
            var stem = component.Split('.')[0];
            if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem, StringComparer.OrdinalIgnoreCase)) throw new PathRejectedException("reserved component");
        }
    }
}

internal sealed class PathRejectedException : Exception { public PathRejectedException(string message) : base(message) { } }
internal sealed class ProtocolException : Exception { public ProtocolException(string message) : base(message) { } }

internal sealed record ImageIdentity(uint VolumeSerial, uint FileIndexHigh, uint FileIndexLow, string Sha256)
{
    public static ImageIdentity Read()
    {
        var path = Environment.ProcessPath ?? throw new IOException("process image unavailable");
        using var handle = Native.CreateFile(path, Program.GenericRead, Program.FileShareRead | Program.FileShareWrite, Program.OpenExisting, Program.FileFlagOpenReparsePoint);
        if (handle.IsInvalid || !Native.GetFileInformationByHandle(handle, out var info) || info.NumberOfLinks != 1) throw new IOException("process image identity unavailable");
        using var stream = new FileStream(handle, FileAccess.Read, 64 * 1024, false);
        return new ImageIdentity(info.VolumeSerialNumber, info.FileIndexHigh, info.FileIndexLow, Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant());
    }
}

internal static class Native
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFile(string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes, uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);
    public static SafeFileHandle CreateFile(string path, uint access, uint share, uint disposition, uint flags) => CreateFile(path, access, share, IntPtr.Zero, disposition, flags, IntPtr.Zero);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetFileInformationByHandle(SafeFileHandle file, out ByHandleFileInformation info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern bool MoveFileEx(string existing, string destination, uint flags);
    [StructLayout(LayoutKind.Sequential)] public struct ByHandleFileInformation
    {
        public uint FileAttributes, CreationTimeLow, CreationTimeHigh, LastAccessTimeLow, LastAccessTimeHigh, LastWriteTimeLow, LastWriteTimeHigh, VolumeSerialNumber, FileSizeHigh, FileSizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow;
    }
}
