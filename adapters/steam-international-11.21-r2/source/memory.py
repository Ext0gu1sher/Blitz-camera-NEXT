"""Windows process inspection. This module has no process-write/injection API."""

import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import struct

from .profile import CameraError, PROFILES


class ProcessInfo:
    def __init__(self, pid, path, base, image_size):
        self.pid, self.path, self.base, self.image_size = pid, Path(path), base, image_size


def _kernel():
    if os.name != "nt":
        raise CameraError("实机读取需要 Windows；离线轨迹功能可以在其他系统运行。")
    k = C.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    k.CloseHandle.argtypes, k.CloseHandle.restype = [W.HANDLE], W.BOOL
    return k


class PROCESSENTRY32W(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", C.c_long), ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]


class MODULEINFO(C.Structure):
    _fields_ = [("lpBaseOfDll", C.c_void_p), ("SizeOfImage", W.DWORD), ("EntryPoint", C.c_void_p)]


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("PartitionId", W.WORD),
                ("RegionSize", C.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD),
                ("Type", W.DWORD)]


def find_process(pid=None):
    """Find the real executable module, using fresh OS snapshots after every restart."""
    k = _kernel()
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
    invalid = C.c_void_p(-1).value
    h = k.CreateToolhelp32Snapshot(2, 0)
    if h == invalid:
        raise CameraError("无法枚举游戏进程。")
    candidates = []
    try:
        e = PROCESSENTRY32W(); e.dwSize = C.sizeof(e)
        ok = k.Process32FirstW(h, C.byref(e))
        while ok:
            if e.szExeFile.lower() == "wotblitz.exe" and (pid is None or e.th32ProcessID == pid):
                candidates.append(int(e.th32ProcessID))
            ok = k.Process32NextW(h, C.byref(e))
    finally:
        k.CloseHandle(h)
    if len(candidates) != 1:
        raise CameraError("未找到唯一的 wotblitz.exe 进程；请打开 Steam 客户端的本地回放。")
    process_id = candidates[0]
    # Toolhelp module snapshots require more access on this machine. PSAPI works with
    # exactly QUERY_INFORMATION|VM_READ; do not escalate permissions or debug privileges.
    k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
    k.K32EnumProcessModulesEx.argtypes = [W.HANDLE, C.POINTER(W.HMODULE), W.DWORD, C.POINTER(W.DWORD), W.DWORD]
    k.K32GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
    k.K32GetModuleInformation.argtypes = [W.HANDLE, W.HMODULE, C.POINTER(MODULEINFO), W.DWORD]
    h = k.OpenProcess(0x410, False, process_id)
    if not h:
        raise CameraError(f"无法以查询/读取权限打开进程（错误 {C.get_last_error()}）。")
    try:
        capacity = 256
        while capacity <= 16384:
            modules = (W.HMODULE * capacity)(); needed = W.DWORD()
            if not k.K32EnumProcessModulesEx(h, modules, C.sizeof(modules), C.byref(needed), 1):
                raise CameraError(f"只读模块枚举失败（错误 {C.get_last_error()}）。")
            if needed.value <= C.sizeof(modules):
                break
            capacity = needed.value // C.sizeof(W.HMODULE) + 64
        else:
            raise CameraError("模块列表异常。")
        for module in modules[:needed.value // C.sizeof(W.HMODULE)]:
            path = C.create_unicode_buffer(32768)
            if k.K32GetModuleFileNameExW(h, module, path, len(path)) and Path(path.value).name.lower() == "wotblitz.exe":
                info = MODULEINFO()
                if not k.K32GetModuleInformation(h, module, C.byref(info), C.sizeof(info)):
                    raise CameraError("无法读取主模块范围。")
                return ProcessInfo(process_id, path.value, int(info.lpBaseOfDll), int(info.SizeOfImage))
    finally:
        k.CloseHandle(h)
    raise CameraError("游戏主模块不可用；请待回放加载完成后重新连接。")


def verify_binary(info):
    data = info.path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    profile = PROFILES.get(digest)
    if profile is None:
        raise CameraError(f"当前可执行文件尚未适配（SHA-256 {digest}）；拒绝套用旧布局。")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    machine = struct.unpack_from("<H", data, pe + 4)[0]
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    if data[pe:pe + 4] != b"PE\0\0" or (machine, magic) != (profile.machine, profile.optional_magic):
        raise CameraError("可执行文件架构与已验证构建不符。")
    if info.image_size != profile.image_size:
        raise CameraError("运行模块大小与已验证构建不符。")
    if struct.unpack_from('<I', data, pe+24+28)[0] != profile.preferred_base:
        raise CameraError("可执行文件首选基址与适配配置不符。")
    return profile


class ReadOnlyMemory:
    ACCESS = 0x0400 | 0x0010  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ

    def __init__(self, info):
        if C.sizeof(C.c_void_p) != 8:
            raise CameraError("请使用 64 位 Python 读取这个 x86 客户端。")
        self.info, self.k, self.handle = info, _kernel(), None
        self.profile = verify_binary(info)
        k = self.k
        k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        k.ReadProcessMemory.restype = W.BOOL
        k.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(MEMORY_BASIC_INFORMATION), C.c_size_t]
        k.VirtualQueryEx.restype = C.c_size_t
        k.GetExitCodeProcess.argtypes, k.GetExitCodeProcess.restype = [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL
        self.handle = k.OpenProcess(self.ACCESS, False, info.pid)
        if not self.handle:
            raise CameraError(f"只读访问被拒绝（Windows 错误 {C.get_last_error()}）。")
        try:
            buf = C.create_unicode_buffer(32768); size = W.DWORD(len(buf))
            if not k.QueryFullProcessImageNameW(self.handle, 0, buf, C.byref(size)):
                raise CameraError("无法再次核实进程身份。")
            if Path(buf.value).resolve() != info.path.resolve():
                raise CameraError("进程身份变化，请重新连接。")
            if self.read(info.base, 2) != b"MZ":
                raise CameraError("主模块不可读。")
        except Exception:
            self.close(); raise

    def read(self, address, size):
        if not self.handle or not (0 < address < 0x100000000) or size < 0 or address + size > 0x100000000:
            raise CameraError("读取范围无效或连接已关闭。")
        buf, got = C.create_string_buffer(size), C.c_size_t()
        ok = self.k.ReadProcessMemory(self.handle, C.c_void_p(address), buf, size, C.byref(got))
        if not ok or got.value != size:
            raise CameraError(f"地址 0x{address:X} 不可完整读取；回放可能已关闭或重建。")
        return buf.raw

    def u32(self, address):
        return struct.unpack("<I", self.read(address, 4))[0]

    def exit_code(self):
        """Query this handle's process, never a potentially reused PID.

        None means alive OR unknown. Only a confirmed exit permits recovery.
        """
        code = W.DWORD()
        if self.handle and self.k.GetExitCodeProcess(self.handle, C.byref(code)) and code.value != 259:
            return int(code.value)
        return None

    def regions(self):
        address = 0
        while address < 0x100000000:
            m = MEMORY_BASIC_INFORMATION()
            n = self.k.VirtualQueryEx(self.handle, C.c_void_p(address), C.byref(m), C.sizeof(m))
            if not n:
                break
            start, length = int(m.BaseAddress or 0), int(m.RegionSize)
            if length <= 0:
                break
            address = start + length
            if m.State == 0x1000 and m.Type == 0x20000 and not (m.Protect & 0x101) and (m.Protect & 0xFF) in (2, 4, 8, 0x20, 0x40, 0x80):
                yield start, min(length, 0x100000000 - start)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle); self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def confirmed_exit_code(memory):
    try:
        value = memory.exit_code()
        return value if type(value) is int else None
    except (CameraError, OSError):
        return None
