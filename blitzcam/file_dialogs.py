"""Windows Common Item Dialogs, shared by file and folder selection.

Uses the system IFileDialog implementation without optional Python packages.
Each HTTP worker initializes and releases its own STA COM apartment.
https://learn.microsoft.com/windows/win32/shell/common-file-dialog
"""
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from .profile import CameraError


class GUID(C.Structure):
    _fields_ = [('data1', C.c_uint32), ('data2', C.c_uint16),
                ('data3', C.c_uint16), ('data4', C.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(str(value)).bytes_le)


class FilterSpec(C.Structure):
    _fields_ = [('name', W.LPCWSTR), ('pattern', W.LPCWSTR)]


FILE_OPEN = GUID.parse('dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7')
FILE_SAVE = GUID.parse('c0b4e2f3-ba21-4773-8dba-335ec946eb8b')
I_FILE_DIALOG = GUID.parse('42f85136-db7e-439c-85f1-e4075d135fc8')
I_SHELL_ITEM = GUID.parse('43826d1e-e718-42ee-bc55-a1e261c37bfe')
CANCELLED = 0x800704C7
FOS_OVERWRITEPROMPT = 0x2
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
FOS_FILEMUSTEXIST = 0x1000
FOS_DONTADDTORECENT = 0x2000000
FOS_DEFAULTNOMINIMODE = 0x20000000


def _method(pointer, slot, *argtypes):
    """Bind a method from an IUnknown-derived COM vtable (HRESULT ABI)."""
    address = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents[slot]
    return C.WINFUNCTYPE(C.c_long, C.c_void_p, *argtypes)(address)


def _check(result):
    if result < 0:
        raise OSError(f'无法打开文件选择窗口（0x{result & 0xffffffff:08X}）。')


def _release(pointer):
    if pointer:
        _method(pointer, 2)(pointer)


@contextmanager
def _above_overlay(user):
    """Raise only dialogs on this worker above the app's topmost panels."""
    callback_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
    user.SetWindowsHookExW.argtypes = [C.c_int, callback_type, W.HINSTANCE, W.DWORD]
    user.SetWindowsHookExW.restype = W.HHOOK
    user.CallNextHookEx.argtypes = [W.HHOOK, C.c_int, W.WPARAM, W.LPARAM]
    user.CallNextHookEx.restype = C.c_ssize_t
    user.UnhookWindowsHookEx.argtypes = [W.HHOOK]
    user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentThreadId.restype = W.DWORD

    @callback_type
    def callback(code, window, param):
        if code == 5:  # HCBT_ACTIVATE; never change other application windows.
            name = C.create_unicode_buffer(64)
            user.GetClassNameW(window, name, len(name))
            if name.value == '#32770':
                user.SetWindowPos(window, W.HWND(-1), 0, 0, 0, 0, 0x13)
        return user.CallNextHookEx(None, code, window, param)

    hook = user.SetWindowsHookExW(5, callback, None, kernel.GetCurrentThreadId())
    try:
        yield
    finally:
        if hook:
            user.UnhookWindowsHookEx(hook)


def _owner(user):
    user.GetForegroundWindow.restype = W.HWND
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    window = user.GetForegroundWindow()
    title = C.create_unicode_buffer(512)
    user.GetWindowTextW(window, title, len(title))
    # Opening a picker through the local API must never disable an unrelated app.
    return window if 'blitz camera' in title.value.lower() else None


def show_dialog(*, title, filters=(), initial=None, save=False, folder=False,
                default_ext=None, default_name='', remember_location=False):
    """Return one filesystem Path, or None on Cancel/Escape/window close."""
    if os.name != 'nt':
        raise CameraError('本地文件选择需要 Windows。')
    ole = C.WinDLL('ole32', use_last_error=True)
    ole.CoInitializeEx.argtypes, ole.CoInitializeEx.restype = [C.c_void_p, W.DWORD], C.c_long
    ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, W.DWORD,
                                    C.POINTER(GUID), C.POINTER(C.c_void_p)]
    ole.CoCreateInstance.restype = C.c_long
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    ole.CoUninitialize.argtypes = []
    _check(ole.CoInitializeEx(None, 2 | 4))  # STA, COINIT_DISABLE_OLE1DDE
    dialog, selected, location, path = (C.c_void_p() for _ in range(4))
    try:
        _check(ole.CoCreateInstance(C.byref(FILE_SAVE if save else FILE_OPEN), None, 1,
                                    C.byref(I_FILE_DIALOG), C.byref(dialog)))
        # Separate persisted dimensions and replay location from other Python apps.
        client = GUID.parse(uuid5(NAMESPACE_URL, 'blitzcamera/dialog/' + title))
        _check(_method(dialog, 24, C.POINTER(GUID))(dialog, C.byref(client)))
        options = W.DWORD()
        _check(_method(dialog, 10, C.POINTER(W.DWORD))(dialog, C.byref(options)))
        flags = options.value | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_DONTADDTORECENT
        if folder:
            flags |= FOS_PICKFOLDERS
        elif save:
            flags |= FOS_OVERWRITEPROMPT | FOS_DEFAULTNOMINIMODE
        else:
            flags |= FOS_FILEMUSTEXIST
        _check(_method(dialog, 9, W.DWORD)(dialog, flags))
        _check(_method(dialog, 17, W.LPCWSTR)(dialog, title))
        if folder:
            _check(_method(dialog, 18, W.LPCWSTR)(dialog, '选择文件夹'))
        if filters and not folder:
            specs = (FilterSpec * len(filters))(*(FilterSpec(*spec) for spec in filters))
            _check(_method(dialog, 4, W.UINT, C.POINTER(FilterSpec))(dialog, len(specs), specs))
            _check(_method(dialog, 5, W.UINT)(dialog, 1))
        if default_ext:
            _check(_method(dialog, 22, W.LPCWSTR)(dialog, default_ext))
        if default_name:
            _check(_method(dialog, 15, W.LPCWSTR)(dialog, default_name))
        if initial and Path(initial).is_dir():
            shell = C.WinDLL('shell32', use_last_error=True)
            shell.SHCreateItemFromParsingName.argtypes = [W.LPCWSTR, C.c_void_p, C.POINTER(GUID),
                                                        C.POINTER(C.c_void_p)]
            shell.SHCreateItemFromParsingName.restype = C.c_long
            _check(shell.SHCreateItemFromParsingName(str(Path(initial).resolve()), None,
                                                    C.byref(I_SHELL_ITEM), C.byref(location)))
            # Replay browsing remembers its last folder; project settings take priority.
            _check(_method(dialog, 11 if remember_location else 12, C.c_void_p)(dialog, location))
        user = C.WinDLL('user32', use_last_error=True)
        owner = _owner(user)
        with _above_overlay(user):
            result = _method(dialog, 3, W.HWND)(dialog, owner)
        if result & 0xffffffff == CANCELLED:
            return None
        _check(result)
        _check(_method(dialog, 20, C.POINTER(C.c_void_p))(dialog, C.byref(selected)))
        # SIGDN_FILESYSPATH returns an allocated UTF-16 string, with no MAX_PATH buffer.
        _check(_method(selected, 5, W.DWORD, C.POINTER(C.c_void_p))(
            selected, 0x80058000, C.byref(path)))
        return Path(C.wstring_at(path))
    finally:
        if path:
            ole.CoTaskMemFree(path)
        _release(selected)
        _release(location)
        _release(dialog)
        ole.CoUninitialize()
