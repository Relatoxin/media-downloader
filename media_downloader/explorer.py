from __future__ import annotations

import ctypes
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ExplorerStatus(str, Enum):
    SELECTED = "selected"
    FOLDER_OPENED = "folder_opened"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExplorerResult:
    status: ExplorerStatus
    path: Path
    folder: Path
    error: str = ""


Launcher = Callable[[Sequence[str]], object]
Selector = Callable[[Path], object]


def _select_with_windows_shell(path: Path) -> None:
    if os.name != "nt":
        raise OSError("Выделение файла поддерживается только в Windows")
    ole32 = ctypes.OleDLL("ole32")
    shell32 = ctypes.OleDLL("shell32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    shell32.SHParseDisplayName.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    shell32.SHParseDisplayName.restype = ctypes.c_long
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long

    co_result = ole32.CoInitializeEx(None, 0x2)
    should_uninitialize = co_result in {0, 1}
    pidl = ctypes.c_void_p()
    try:
        parse_result = shell32.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
        if parse_result < 0 or not pidl.value:
            raise OSError(f"SHParseDisplayName failed: 0x{parse_result & 0xFFFFFFFF:08X}")
        open_result = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        if open_result < 0:
            raise OSError(f"SHOpenFolderAndSelectItems failed: 0x{open_result & 0xFFFFFFFF:08X}")
    finally:
        if pidl.value:
            ole32.CoTaskMemFree(pidl)
        if should_uninitialize:
            ole32.CoUninitialize()


def show_in_explorer(path: Path, *, selector: Selector = _select_with_windows_shell) -> ExplorerResult:
    resolved = path.expanduser().resolve()
    folder = resolved.parent
    if not resolved.is_file():
        return ExplorerResult(ExplorerStatus.MISSING, resolved, folder)
    try:
        selector(resolved)
        return ExplorerResult(ExplorerStatus.SELECTED, resolved, folder)
    except OSError as exc:
        return ExplorerResult(ExplorerStatus.FAILED, resolved, folder, str(exc))


def open_folder(path: Path, *, launcher: Launcher = subprocess.Popen) -> ExplorerResult:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        return ExplorerResult(ExplorerStatus.MISSING, resolved, resolved)
    try:
        launcher(["explorer.exe", str(resolved)])
        return ExplorerResult(ExplorerStatus.FOLDER_OPENED, resolved, resolved)
    except OSError as exc:
        return ExplorerResult(ExplorerStatus.FAILED, resolved, resolved, str(exc))
