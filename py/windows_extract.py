"""Windows memory access for the veteran data extractor.

Same scan as linux_extract.py, but lists and reads the game's memory with the
Win32 API (VirtualQueryEx / ReadProcessMemory) instead of /proc. Read-only:
nothing is injected into or written to the game.
"""
import ctypes
import os
import sys
from ctypes import wintypes

from veteran_scan import filter_regions, scan_regions

TARGET_PROCESS = "umamusumeprettyderby.exe"

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_ACCESS_DENIED = 5

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
# Writable protections, the same as "rw" in /proc/<pid>/maps
PAGE_RW = {
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
    ] + ([("PartitionId", wintypes.WORD)] if ctypes.sizeof(ctypes.c_void_p) == 8 else []) + [
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


_kernel32 = None


def kernel32():
    """Load kernel32 on first use, so this module can be imported anywhere."""
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.VirtualQueryEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(MEMORY_BASIC_INFORMATION),
            ctypes.c_size_t,
        ]
        k.VirtualQueryEx.restype = ctypes.c_size_t
        k.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k.ReadProcessMemory.restype = wintypes.BOOL
        _kernel32 = k
    return _kernel32


def find_game_processes():
    """Return a list of (pid, exe_name) for running game processes."""
    k = kernel32()
    snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE or snapshot is None:
        raise ctypes.WinError(ctypes.get_last_error())

    candidates = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == TARGET_PROCESS:
                candidates.append((entry.th32ProcessID, entry.szExeFile))
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)

    candidates.sort()
    return candidates


def open_process(pid):
    """Open the process for reading. Raises PermissionError on access denied."""
    handle = kernel32().OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            raise PermissionError(f"Access denied opening process {pid}")
        raise ctypes.WinError(err)
    return handle


def read_memory_regions(handle):
    """Return read-write memory regions of the process, largest first.

    Adjacent regions are merged, like Frida's enumerateRanges(coalesce: true)
    that the original Windows scanner used.
    """
    k = kernel32()
    all_regions = []
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    while k.VirtualQueryEx(handle, address, ctypes.byref(mbi), ctypes.sizeof(mbi)):
        start = mbi.BaseAddress or 0
        size = mbi.RegionSize
        if size == 0:
            break

        if mbi.State == MEM_COMMIT and mbi.Protect in PAGE_RW and not mbi.Protect & PAGE_GUARD:
            if all_regions and all_regions[-1]["end"] == start:
                all_regions[-1]["end"] = start + size
                all_regions[-1]["size"] += size
            else:
                all_regions.append({"start": start, "end": start + size, "size": size})

        address = start + size
        if address >= sys.maxsize * 2:
            break

    return filter_regions(all_regions), len(all_regions)


def read_region(handle, region):
    """Read a whole region, or return None if it can't be read."""
    buf = bytearray(region["size"])
    c_buf = (ctypes.c_char * len(buf)).from_buffer(buf)
    read = ctypes.c_size_t(0)
    ok = kernel32().ReadProcessMemory(handle, region["start"], c_buf, len(buf), ctypes.byref(read))
    del c_buf
    if not ok or read.value != len(buf):
        return None
    return buf


def scan_for_veteran_data(pid, log=print, progress=None):
    """Scan process memory for the trained_chara_array msgpack blob.

    Returns the raw bytes starting at the array marker, or None if not found.
    Raises PermissionError if the process can't be opened for reading.
    progress(scanned, total) is called after each region.
    """
    handle = open_process(pid)
    try:
        log("Reading process memory map...")
        memory_regions, total = read_memory_regions(handle)
        log(f"Scanning {len(memory_regions)} memory regions (filtered from {total})...")
        return scan_regions(memory_regions, lambda r: read_region(handle, r), log, progress)
    finally:
        kernel32().CloseHandle(handle)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Start this program again with a UAC prompt. Returns True if it started."""
    if getattr(sys, "frozen", False):
        args = sys.argv[1:]
    else:
        args = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    params = " ".join(f'"{a}"' for a in args)
    # ShellExecuteW returns a value > 32 on success
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32
