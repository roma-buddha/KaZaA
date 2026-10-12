"""Verified logical overwriting of explicitly selected local Windows files.

This is not device sanitization: SSD remapping, filesystem metadata, snapshots
and external copies remain outside the guarantee. No filenames are persisted.
"""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import secrets
import stat
import struct
from threading import Event


@dataclass(frozen=True)
class Algorithm:
    key: str
    label: str
    patterns: tuple


# None means fresh cryptographic random bytes for every block.
GUTMANN = ((None,) * 4 + (b"\x55", b"\xaa", b"\x92\x49\x24",
    b"\x49\x24\x92", b"\x24\x92\x49") +
    tuple(bytes([value]) for value in range(0, 256, 17)) +
    (b"\x92\x49\x24", b"\x49\x24\x92", b"\x24\x92\x49",
     b"\x6d\xb6\xdb", b"\xb6\xdb\x6d", b"\xdb\x6d\xb6") + (None,) * 4)
ALGORITHMS = (
    Algorithm("single", "Single pass · 1 pass", (b"\x00",)),
    Algorithm("two", "Two passes · 2 passes", (b"\x00", b"\xff")),
    Algorithm("dod", "DoD-style · 3 passes", (b"\x00", b"\xff", None)),
    Algorithm("seven", "Seven passes · 7 passes", tuple(bytes([n]) for n in (0, 255, 85, 170, 255, 85, 170))),
    Algorithm("gutmann", "Gutmann · 35 passes", GUTMANN),
)
ALGORITHM_BY_KEY = {algorithm.key: algorithm for algorithm in ALGORITHMS}
BLOCK_SIZE = 1024 * 1024
LIMITATION = "Overwriting cannot guarantee erasure on SSDs or remove backups, snapshots or filesystem metadata."


class ShredError(Exception):
    pass


class ShredCancelled(ShredError):
    pass


@dataclass(frozen=True)
class FileTarget:
    path: str
    size: int
    device: int
    inode: int
    modified: int


def inspect_file(path):
    """Snapshot identity without following a supplied link or device path."""
    path = Path(os.path.abspath(os.fspath(path)))
    if os.name != "nt":
        raise ShredError("Shredding is supported on Windows only.")
    drive, tail = os.path.splitdrive(str(path))
    if not drive or drive.startswith("\\\\") or ":" in tail:
        raise ShredError("Choose a local file, not a network, device or stream path.")
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ShredError("Links, junctions and cloud placeholders are not supported.")
    info = path.lstat()
    _validate_info(info)
    return FileTarget(str(path), info.st_size, info.st_dev, info.st_ino, info.st_mtime_ns)


def _validate_info(info):
    if not stat.S_ISREG(info.st_mode):
        raise ShredError("Choose individual files; folders are not shredded.")
    if info.st_nlink != 1:
        raise ShredError("Files with multiple hard links are not supported.")
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & (0x1 | 0x4 | 0x200 | 0x400 | 0x800 | 0x1000 | 0x4000):
        raise ShredError("Read-only, system, sparse, compressed, encrypted or offline files are not supported.")


def _check_cancel(cancel):
    if cancel.is_set():
        raise ShredCancelled("Cancelled; file kept. Any completed overwrites cannot be undone.")


def _write_all(fd, data, cancel):
    view = memoryview(data)
    while view:
        _check_cancel(cancel)
        written = os.write(fd, view)
        if written <= 0 or written > len(view):
            raise ShredError("Incomplete write; file kept.")
        view = view[written:]


def _overwrite_stream(fd, size, algorithm, cancel, progress):
    """Flush and digest-verify every pass. Never truncate, even on cancellation."""
    for index, pattern in enumerate(algorithm.patterns, 1):
        _check_cancel(cancel)
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        offset = 0
        while offset < size:
            _check_cancel(cancel)
            length = min(BLOCK_SIZE, size - offset)
            if pattern is None:
                data = secrets.token_bytes(length)
            else:
                # Preserve the pattern across block boundaries (including triples).
                shift = offset % len(pattern)
                data = (pattern * ((length + shift + len(pattern) - 1) // len(pattern)))[shift:shift + length]
            _write_all(fd, data, cancel)
            digest.update(data)
            offset += length
            progress(length, f"Overwriting · pass {index}/{len(algorithm.patterns)}")
        os.fsync(fd)
        _check_cancel(cancel)
        os.lseek(fd, 0, os.SEEK_SET)
        actual = hashlib.sha256()
        remaining = size
        while remaining:
            _check_cancel(cancel)
            data = os.read(fd, min(BLOCK_SIZE, remaining))
            if not data:
                raise ShredError("Verification read was incomplete; file kept.")
            actual.update(data)
            remaining -= len(data)
            progress(len(data), f"Verifying · pass {index}/{len(algorithm.patterns)}")
        if actual.digest() != digest.digest():
            raise ShredError("Verification failed; file kept.")
        if os.fstat(fd).st_size != size:
            raise ShredError("File size changed during shredding; file kept.")


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME), ("modified", wintypes.FILETIME),
        ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


def _kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    for name in ("GetFileInformationByHandleEx", "SetFileInformationByHandle"):
        fn = getattr(api, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        fn.restype = wintypes.BOOL
    api.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.LPWSTR, wintypes.DWORD]
    api.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    return api


def _require(success):
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())


class _WindowsFile:
    """Own exclusive stream handles and delete the verified object by handle."""
    def __init__(self, target):
        import msvcrt
        self.api = _kernel()
        self.handles = []
        self.streams = []
        current = inspect_file(target.path)
        if current != target:
            raise ShredError("File changed since it was added. Remove it and add it again.")
        root = Path(target.path).anchor
        if self.api.GetDriveTypeW(root) not in (2, 3):
            raise ShredError("Choose a file on a local writable drive.")
        self.native_path = "\\\\?\\" + target.path
        try:
            main = self._open(self.native_path, delete=True)
            self.main = main
            fs = ctypes.create_unicode_buffer(32)
            _require(self.api.GetVolumeInformationByHandleW(main, None, 0, None, None, None, fs, len(fs)))
            if fs.value != "NTFS":
                raise ShredError("Verified shredding currently supports NTFS drives only.")
            for name, size in sorted(self._stream_info(), key=lambda item: item[0] != "::$DATA"):
                handle = main if name == "::$DATA" else self._open(self.native_path + name)
                info = _FileInfo()
                _require(self.api.GetFileInformationByHandle(handle, ctypes.byref(info)))
                if info.links != 1 or info.attributes & (0x1 | 0x4 | 0x200 | 0x400 | 0x800 | 0x1000 | 0x4000):
                    raise ShredError("File attributes changed; file kept.")
                fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
                # The CRT descriptor now owns this native handle.
                self.handles.remove(handle)
                self.streams.append((name, fd, size))
                if os.fstat(fd).st_size != size:
                    raise ShredError("Stream changed while opening; file kept.")
            main_fd = next(fd for name, fd, _ in self.streams if name == "::$DATA")
            info = os.fstat(main_fd)
            _validate_info(info)
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                    target.device, target.inode, target.size, target.modified):
                raise ShredError("File identity changed; file kept.")
        except BaseException:
            self.close()
            raise

    def _open(self, path, delete=False):
        # Delete access is checked across streams. ADS share deletion with the
        # main handle; the main handle blocks outside rename/delete operations.
        access = 0xC0000000 | (0x10000 if delete else 0)
        handle = self.api.CreateFileW(path, access, 0 if delete else 4, None,
            3, 0x80000000 | 0x00200000, None)  # OPEN_EXISTING, write-through, no reparse
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append(handle)
        return handle

    def _stream_info(self):
        capacity = 4096
        while capacity <= 4 * 1024 * 1024:
            buffer = ctypes.create_string_buffer(capacity)
            if self.api.GetFileInformationByHandleEx(self.main, 7, buffer, capacity):
                break
            if ctypes.get_last_error() not in (24, 122, 234):
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        else:
            raise ShredError("Could not enumerate all file streams; file kept.")
        raw, offset, streams = buffer.raw, 0, []
        while True:
            next_offset, length, size, _ = struct.unpack_from("<IIqq", raw, offset)
            if length % 2 or length > len(raw) - offset - 24 or size < 0:
                raise ShredError("Invalid stream inventory; file kept.")
            name = raw[offset + 24:offset + 24 + length].decode("utf-16-le")
            if not name.endswith(":$DATA") or "/" in name or "\\" in name:
                raise ShredError("Unsupported stream; file kept.")
            streams.append((name, size))
            if not next_offset:
                break
            if next_offset < 24 + length or offset + next_offset + 24 > len(raw):
                raise ShredError("Invalid stream inventory; file kept.")
            offset += next_offset
        if len({name for name, _ in streams}) != len(streams) or not any(name == "::$DATA" for name, _ in streams):
            raise ShredError("Could not enumerate the main file stream; file kept.")
        return streams

    def delete_verified(self):
        info = _FileInfo()
        _require(self.api.GetFileInformationByHandle(self.main, ctypes.byref(info)))
        if info.links != 1:
            raise ShredError("Hard links changed during shredding; file kept.")
        expected = sorted((name, size) for name, _, size in self.streams)
        if sorted(self._stream_info()) != expected:
            raise ShredError("File streams changed during shredding; file kept.")
        disposition = wintypes.BOOL(True)
        _require(self.api.SetFileInformationByHandle(self.main, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)))

    def close(self):
        # Close alternate streams before the main handle completes deletion.
        for _, fd, _ in reversed(self.streams):
            os.close(fd)
        self.streams.clear()
        for handle in self.handles:
            self.api.CloseHandle(handle)
        self.handles.clear()


def shred_file(target, algorithm_key, cancel=None, progress=None):
    """Overwrite and verify all data streams before requesting deletion.

    progress(percent, description) reports this file, including ADS. Errors and
    cancellation keep the file at its existing size, but written bytes are lost.
    """
    cancel = cancel if cancel is not None else Event()
    progress = progress or (lambda percent, description: None)
    algorithm = ALGORITHM_BY_KEY.get(algorithm_key)
    if algorithm is None:
        raise ShredError("Unknown overwrite algorithm.")
    _check_cancel(cancel)
    opened = _WindowsFile(target)
    try:
        total = sum(size for _, _, size in opened.streams) * len(algorithm.patterns) * 2
        done = 0

        def advanced(count, description):
            nonlocal done
            done += count
            progress(min(99, int(done * 100 / total)) if total else 0, description)

        for name, fd, size in opened.streams:
            _overwrite_stream(fd, size, algorithm, cancel, advanced)
        _check_cancel(cancel)
        opened.delete_verified()
    finally:
        opened.close()
    progress(100, "Shredded · verified")
