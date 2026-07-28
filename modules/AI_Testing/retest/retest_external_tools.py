#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""External retest tool discovery and one-click installer.

The AICTF sandbox installs nmap/sqlmap/ffuf inside Kali. This module provides
the Windows/local equivalent for Koi: prefer project-downloaded portable tools,
then PATH, and expose a small installer that downloads from official upstreams.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List


TOOLS = ("nmap", "sqlmap", "ffuf")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROJECT_TOOL_ROOT = PROJECT_ROOT / "retest_external_tools"
LOCAL_TOOL_ROOT = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Koi" / "retest-tools"
ProgressCallback = Callable[[Dict[str, Any]], None]


def app_tool_root() -> Path:
    """Return the tool directory beside the project/app executable."""
    try:
        from modules.utils.resource_path import get_install_dir

        return get_install_dir() / "retest_external_tools"
    except Exception:
        return PROJECT_TOOL_ROOT


def tool_roots() -> List[Path]:
    env_root = os.environ.get("KOI_RETEST_TOOLS_DIR")
    roots = []
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.append(app_tool_root())
    if PROJECT_TOOL_ROOT not in roots:
        roots.append(PROJECT_TOOL_ROOT)
    roots.append(LOCAL_TOOL_ROOT)
    return roots


def preferred_tool_root() -> Path:
    for root in tool_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            test_file = root / ".write-test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return root
        except Exception:
            continue
    LOCAL_TOOL_ROOT.mkdir(parents=True, exist_ok=True)
    return LOCAL_TOOL_ROOT


def _exe_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _candidate_paths(tool: str) -> List[Path]:
    candidates: List[Path] = []
    for root in tool_roots():
        candidates.extend([
            root / tool / _exe_name(tool),
            root / tool / "bin" / _exe_name(tool),
            root / tool / "nmap" / _exe_name(tool),
            root / tool / "ffuf.exe",
            root / tool / "ffuf",
            root / tool / "sqlmap.py",
        ])
        if root.exists():
            candidates.extend(root.glob(f"{tool}/**/{_exe_name(tool)}"))
            if tool == "sqlmap":
                candidates.extend(root.glob("sqlmap/**/sqlmap.py"))
    return candidates


def find_tool_command(tool: str) -> List[str]:
    name = str(tool or "").strip().lower()
    if name not in TOOLS:
        return []
    for candidate in _candidate_paths(name):
        if not candidate.exists():
            continue
        if name == "sqlmap" and candidate.name.lower() == "sqlmap.py":
            return [sys.executable, str(candidate)]
        return [str(candidate)]
    path_binary = shutil.which(name)
    if path_binary:
        return [path_binary]
    return []


def _command_source(tool: str, command: List[str]) -> str:
    if not command:
        return ""
    try:
        executable = Path(command[-1] if tool == "sqlmap" and command[-1].endswith(".py") else command[0]).resolve()
    except Exception:
        return "detected"
    for root in tool_roots():
        try:
            if executable.is_relative_to(root.resolve()):
                if root == PROJECT_TOOL_ROOT:
                    return "project"
                if root == app_tool_root():
                    return "app"
                if root == LOCAL_TOOL_ROOT:
                    return "local"
                return "env"
        except Exception:
            continue
    path_binary = shutil.which(tool)
    if path_binary:
        try:
            if executable == Path(path_binary).resolve():
                return "path"
        except Exception:
            return "path"
    return "detected"


def tool_status() -> Dict[str, Any]:
    tools = []
    for name in TOOLS:
        command = find_tool_command(name)
        tools.append({
            "id": name,
            "name": name,
            "installed": bool(command),
            "command": command,
            "source": _command_source(name, command),
            "installable": True,
            "root": str(preferred_tool_root() / name),
        })
    return {
        "success": True,
        "message": "External retest tool status loaded.",
        "tool_root": str(preferred_tool_root()),
        "tools": tools,
    }


def _emit_progress(progress: ProgressCallback | None, **event: Any) -> None:
    if progress is None:
        return
    try:
        progress({key: value for key, value in event.items() if value is not None})
    except Exception:
        pass


def _overall_percent(tool_index: int, tool_count: int, tool_percent: Any) -> int:
    total = max(1, int(tool_count or 1))
    try:
        local = float(tool_percent)
    except Exception:
        local = 0.0
    local = max(0.0, min(100.0, local))
    return max(0, min(100, int(round(((tool_index + local / 100.0) / total) * 100))))


def _download_message(tool: str, output: Path, percent: int | None, bytes_read: int, total_bytes: int | None) -> str:
    if total_bytes:
        return f"{tool}: 下载 {output.name} {percent or 0}% ({bytes_read}/{total_bytes} bytes)"
    return f"{tool}: 下载 {output.name} ({bytes_read} bytes)"


def install_tools(tool_names: Iterable[str] | None = None, progress: ProgressCallback | None = None) -> Dict[str, Any]:
    selected = [str(item).strip().lower() for item in (tool_names or TOOLS) if str(item).strip()]
    selected = [item for item in dict.fromkeys(selected) if item in TOOLS]
    if not selected:
        selected = list(TOOLS)
    logs: List[str] = []
    installed: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    root = preferred_tool_root()
    tool_count = len(selected)
    _emit_progress(
        progress,
        phase="start",
        percent=0,
        overall_percent=0,
        tool_index=0,
        tool_count=tool_count,
        message=f"开始下载外部工具: {', '.join(selected)}",
    )
    for tool_index, tool in enumerate(selected):
        def tool_progress(event: Dict[str, Any], _index: int = tool_index, _tool: str = tool) -> None:
            _emit_progress(
                progress,
                **event,
                tool=_tool,
                tool_index=_index + 1,
                tool_count=tool_count,
                overall_percent=_overall_percent(_index, tool_count, event.get("percent", 0)),
            )

        try:
            logs.append(f"Installing {tool} into {root / tool}")
            tool_progress({"phase": "tool_start", "percent": 0, "message": f"开始安装 {tool}"})
            if tool == "ffuf":
                _install_ffuf(root / tool, logs, tool_progress)
            elif tool == "sqlmap":
                _install_sqlmap(root / tool, logs, tool_progress)
            elif tool == "nmap":
                _install_nmap(root / tool, logs, tool_progress)
            tool_progress({"phase": "verify", "percent": 96, "message": f"正在验证 {tool}"})
            command = find_tool_command(tool)
            installed.append({"id": tool, "installed": bool(command), "command": command})
            if not command:
                reason = "download finished but executable was not found"
                failures.append({"tool": tool, "reason": reason})
                tool_progress({"phase": "failed", "percent": 100, "message": f"{tool} 下载完成但未找到可执行文件", "error": reason})
            else:
                tool_progress({"phase": "done", "percent": 100, "message": f"{tool} 安装完成"})
        except Exception as exc:
            failures.append({"tool": tool, "reason": str(exc)})
            logs.append(f"{tool} install failed: {exc}")
            tool_progress({"phase": "failed", "percent": 100, "message": f"{tool} 安装失败: {exc}", "error": str(exc)})
    _emit_progress(
        progress,
        phase="all_done" if not failures else "all_failed",
        percent=100,
        overall_percent=100,
        tool_index=tool_count,
        tool_count=tool_count,
        message="外部工具下载完成" if not failures else "部分外部工具下载失败",
        done=True,
        success=not failures,
        failures=failures,
    )
    return {
        "success": not failures,
        "message": "外部工具下载完成" if not failures else "部分外部工具下载失败",
        "tool_root": str(root),
        "installed": installed,
        "failures": failures,
        "logs": logs,
        "status": tool_status(),
    }


def _urlopen_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Koi-Retest-Agent/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _download(
    url: str,
    output: Path,
    logs: List[str],
    progress: ProgressCallback | None = None,
    tool: str = "",
    percent_start: int = 0,
    percent_end: int = 100,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Koi-Retest-Agent/1.0"})
    label = tool or "tool"
    _emit_progress(
        progress,
        phase="download",
        percent=percent_start,
        url=url,
        output=str(output),
        message=f"{label}: 开始下载 {output.name}",
    )
    with urllib.request.urlopen(request, timeout=180) as response, open(output, "wb") as handle:
        total_bytes = None
        try:
            length_header = response.headers.get("Content-Length") if response.headers else None
            total_bytes = int(length_header) if length_header else None
        except Exception:
            total_bytes = None
        bytes_read = 0
        last_emit_at = 0.0
        last_percent = -1
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            bytes_read += len(chunk)
            percent = percent_start
            if total_bytes and total_bytes > 0:
                span = max(1, int(percent_end) - int(percent_start))
                percent = int(percent_start + min(1.0, bytes_read / total_bytes) * span)
            now = time.monotonic()
            if percent != last_percent or now - last_emit_at >= 0.75:
                _emit_progress(
                    progress,
                    phase="download",
                    percent=percent,
                    url=url,
                    output=str(output),
                    bytes_read=bytes_read,
                    total_bytes=total_bytes,
                    message=_download_message(label, output, percent, bytes_read, total_bytes),
                )
                last_emit_at = now
                last_percent = percent
        handle.flush()
    output_size = output.stat().st_size if output.exists() else 0
    _emit_progress(
        progress,
        phase="download_done",
        percent=percent_end,
        url=url,
        output=str(output),
        bytes_read=output_size,
        total_bytes=output_size or None,
        message=f"{label}: 下载完成 {output.name}",
    )
    logs.append(f"Downloaded {url} -> {output} ({output.stat().st_size} bytes)")


def _extract_zip(
    zip_path: Path,
    destination: Path,
    logs: List[str],
    progress: ProgressCallback | None = None,
    tool: str = "",
    percent: int = 90,
) -> None:
    label = tool or "tool"
    _emit_progress(progress, phase="extract", percent=percent, message=f"{label}: 正在解压 {zip_path.name}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
    logs.append(f"Extracted {zip_path.name} -> {destination}")
    _emit_progress(progress, phase="extract_done", percent=min(95, percent + 5), message=f"{label}: 解压完成")


def _install_ffuf(destination: Path, logs: List[str], progress: ProgressCallback | None = None) -> None:
    _emit_progress(progress, phase="metadata", percent=3, message="ffuf: 查询最新版本")
    data = _urlopen_json("https://api.github.com/repos/ffuf/ffuf/releases/latest")
    assets = data.get("assets") if isinstance(data, dict) else []
    asset_url = ""
    for asset in assets or []:
        name = str(asset.get("name") or "").lower()
        if "windows" in name and "amd64" in name and name.endswith(".zip"):
            asset_url = str(asset.get("browser_download_url") or "")
            break
    if not asset_url:
        raise RuntimeError("No ffuf Windows amd64 zip asset found in latest GitHub release.")
    with tempfile.TemporaryDirectory(prefix="koi-ffuf-") as tmp:
        zip_path = Path(tmp) / "ffuf.zip"
        _download(asset_url, zip_path, logs, progress, "ffuf", 8, 82)
        _extract_zip(zip_path, destination, logs, progress, "ffuf", 86)


def _install_sqlmap(destination: Path, logs: List[str], progress: ProgressCallback | None = None) -> None:
    url = "https://github.com/sqlmapproject/sqlmap/archive/refs/heads/master.zip"
    with tempfile.TemporaryDirectory(prefix="koi-sqlmap-") as tmp:
        zip_path = Path(tmp) / "sqlmap.zip"
        _download(url, zip_path, logs, progress, "sqlmap", 5, 78)
        extract_dir = Path(tmp) / "extract"
        _extract_zip(zip_path, extract_dir, logs, progress, "sqlmap", 82)
        roots = [item for item in extract_dir.iterdir() if item.is_dir()]
        source = roots[0] if roots else extract_dir
        _emit_progress(progress, phase="copy", percent=90, message="sqlmap: 正在写入工具目录")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        logs.append(f"Installed sqlmap source -> {destination}")
        _emit_progress(progress, phase="copy_done", percent=95, message="sqlmap: 工具目录写入完成")


def _install_nmap(destination: Path, logs: List[str], progress: ProgressCallback | None = None) -> None:
    archive_url = "https://nmap.org/dist/"
    _emit_progress(progress, phase="metadata", percent=3, message="nmap: 查询可下载版本")
    request = urllib.request.Request(archive_url, headers={"User-Agent": "Koi-Retest-Agent/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        index = response.read().decode("utf-8", errors="replace")
    versions = []
    for name in re.findall(r"nmap-([0-9.]+)-win32\.zip", index, flags=re.IGNORECASE):
        versions.append(name)
    if not versions:
        raise RuntimeError("No public nmap win32 zip found at nmap.org/dist; install the official Windows setup manually.")
    version = sorted(versions, key=lambda item: tuple(int(part) for part in item.split(".") if part.isdigit()))[-1]
    url = f"https://nmap.org/dist/nmap-{version}-win32.zip"
    with tempfile.TemporaryDirectory(prefix="koi-nmap-") as tmp:
        zip_path = Path(tmp) / "nmap.zip"
        _download(url, zip_path, logs, progress, "nmap", 10, 82)
        _extract_zip(zip_path, destination, logs, progress, "nmap", 86)
