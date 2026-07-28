#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ctypes
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

FILESYSTEM_COMMANDS = {
    "fs.roots",
    "fs.list_dir",
    "fs.path_info",
    "fs.open_path",
    "fs.open_url",
}


def is_filesystem_command(command: str | None) -> bool:
    return str(command or "") in FILESYSTEM_COMMANDS


def handle_filesystem_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if command == "fs.roots":
        return _fs_roots()
    if command == "fs.list_dir":
        return _fs_list_dir(payload)
    if command == "fs.path_info":
        return _fs_path_info(payload)
    if command == "fs.open_path":
        return _fs_open_path(payload)
    if command == "fs.open_url":
        return _fs_open_url(payload)

    raise ValueError(f"Unknown filesystem command: {command}")


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        value /= 1024
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{size} B"


def _clean_fs_text(value: Any) -> str:
    return str(value).encode("utf-8", "replace").decode("utf-8")


def _drive_label(drive: str) -> str:
    if os.name != "nt":
        return drive
    try:
        volume_name = ctypes.create_unicode_buffer(1024)
        file_system_name = ctypes.create_unicode_buffer(1024)
        serial_number = ctypes.c_ulong()
        max_component_length = ctypes.c_ulong()
        file_system_flags = ctypes.c_ulong()
        success = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive + "\\"),
            volume_name,
            ctypes.sizeof(volume_name),
            ctypes.byref(serial_number),
            ctypes.byref(max_component_length),
            ctypes.byref(file_system_flags),
            file_system_name,
            ctypes.sizeof(file_system_name),
        )
        if success and volume_name.value:
            return f"{volume_name.value} ({drive})"
    except Exception:
        pass
    return drive


def _fs_roots() -> Dict[str, Any]:
    roots = []
    if os.name == "nt":
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if bitmask & (1 << index):
                drive = f"{chr(65 + index)}:"
                roots.append({"path": drive + "\\", "name": _drive_label(drive), "type": "drive"})
    else:
        roots.append({"path": "/", "name": "/", "type": "root"})

    home = str(Path.home())
    shortcuts = [
        {"path": home, "name": "用户目录", "type": "home"},
        {"path": str(Path.home() / "Desktop"), "name": "桌面", "type": "shortcut"},
        {"path": str(Path.home() / "Documents"), "name": "文档", "type": "shortcut"},
        {"path": str(Path.home() / "Downloads"), "name": "下载", "type": "shortcut"},
    ]
    shortcuts = [item for item in shortcuts if os.path.exists(item["path"])]
    return {"cwd": os.getcwd(), "home": home, "roots": roots, "shortcuts": shortcuts}


def _normalize_fs_path(path_value: str | None) -> Path:
    if path_value and str(path_value).strip():
        return Path(str(path_value).strip()).expanduser()
    return Path.home()


def _nearest_existing_directory(path: Path) -> Path | None:
    candidate = path
    while True:
        if candidate.exists():
            return candidate.parent if candidate.is_file() else candidate
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent


def _fs_list_dir(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = _normalize_fs_path(payload.get("path"))
    requested = current
    recovered_from = None
    recover_missing_ancestor = bool(payload.get("recover_missing_ancestor", False))
    show_hidden = bool(payload.get("show_hidden", False))
    filter_extensions = payload.get("extensions") or []
    if not isinstance(filter_extensions, list):
        filter_extensions = []
    normalized_extensions = {
        str(ext).lower().lstrip(".")
        for ext in filter_extensions
        if str(ext).strip() and str(ext).strip() != "*"
    }

    if current.is_file():
        current = current.parent
    if not current.exists():
        if not recover_missing_ancestor:
            raise FileNotFoundError(f"Path does not exist: {current}")
        recovered = _nearest_existing_directory(current)
        if recovered is None:
            recovered = _nearest_existing_directory(Path.home())
        if recovered is None:
            raise FileNotFoundError(f"Path does not exist and no parent directory is available: {current}")
        recovered_from = str(requested)
        current = recovered
    if not current.is_dir():
        raise NotADirectoryError(f"Not a directory: {current}")

    entries = []
    try:
        iterator = list(current.iterdir())
    except PermissionError as exc:
        raise PermissionError(f"Permission denied: {current}") from exc

    for child in iterator:
        name = child.name
        if not show_hidden and name.startswith("."):
            continue

        stat = _safe_stat(child)
        is_dir = child.is_dir()
        suffix = child.suffix.lower().lstrip(".")
        matches_filter = is_dir or not normalized_extensions or suffix in normalized_extensions
        entries.append({
            "name": _clean_fs_text(name),
            "path": _clean_fs_text(child),
            "is_dir": is_dir,
            "extension": suffix,
            "size": None if is_dir or stat is None else stat.st_size,
            "size_text": "" if is_dir or stat is None else _format_size(stat.st_size),
            "modified": None if stat is None else int(stat.st_mtime),
            "hidden": name.startswith("."),
            "matches_filter": matches_filter,
        })

    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
    parent = str(current.parent) if current.parent != current else None
    return {
        "path": _clean_fs_text(current),
        "parent": None if parent is None else _clean_fs_text(parent),
        "entries": entries,
        "separator": os.sep,
        "recovered_from": None if recovered_from is None else _clean_fs_text(recovered_from),
    }


def _fs_path_info(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = _normalize_fs_path(payload.get("path"))
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": path.is_dir() if exists else False,
        "is_file": path.is_file() if exists else False,
        "parent": str(path.parent),
        "name": path.name,
    }


def _open_path_in_system(path: Path) -> tuple[bool, str | None]:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except Exception as exc:
        return False, str(exc)


def _fs_open_path(payload: Dict[str, Any]) -> Dict[str, Any]:
    target = _normalize_fs_path(payload.get("path"))
    if not target.exists():
        return {"success": False, "message": f"Path does not exist: {target}", "path": str(target)}
    open_target = target.parent if target.is_file() else target
    opened, error = _open_path_in_system(open_target)
    return {
        "success": opened,
        "message": f"Opened: {open_target}" if opened else f"Unable to open path: {error}",
        "path": str(open_target),
    }


def _fs_open_url(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"success": False, "message": "Invalid URL", "url": url}
    try:
        opened = webbrowser.open_new_tab(url)
    except Exception as exc:
        return {"success": False, "message": f"Unable to open URL: {exc}", "url": url}
    return {
        "success": bool(opened),
        "message": f"Opened URL: {url}" if opened else f"Unable to open URL: {url}",
        "url": url,
    }
