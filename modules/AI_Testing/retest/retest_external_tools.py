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
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List


TOOLS = ("nmap", "sqlmap", "ffuf")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROJECT_TOOL_ROOT = PROJECT_ROOT / "retest_external_tools"
LOCAL_TOOL_ROOT = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Koi" / "retest-tools"


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


def install_tools(tool_names: Iterable[str] | None = None) -> Dict[str, Any]:
    selected = [str(item).strip().lower() for item in (tool_names or TOOLS) if str(item).strip()]
    selected = [item for item in dict.fromkeys(selected) if item in TOOLS]
    if not selected:
        selected = list(TOOLS)
    logs: List[str] = []
    installed: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    root = preferred_tool_root()
    for tool in selected:
        try:
            logs.append(f"Installing {tool} into {root / tool}")
            if tool == "ffuf":
                _install_ffuf(root / tool, logs)
            elif tool == "sqlmap":
                _install_sqlmap(root / tool, logs)
            elif tool == "nmap":
                _install_nmap(root / tool, logs)
            command = find_tool_command(tool)
            installed.append({"id": tool, "installed": bool(command), "command": command})
            if not command:
                failures.append({"tool": tool, "reason": "download finished but executable was not found"})
        except Exception as exc:
            failures.append({"tool": tool, "reason": str(exc)})
            logs.append(f"{tool} install failed: {exc}")
    return {
        "success": not failures,
        "message": "Tool installation completed." if not failures else "Some tools failed to install.",
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


def _download(url: str, output: Path, logs: List[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Koi-Retest-Agent/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response, open(output, "wb") as handle:
        shutil.copyfileobj(response, handle)
    logs.append(f"Downloaded {url} -> {output} ({output.stat().st_size} bytes)")


def _extract_zip(zip_path: Path, destination: Path, logs: List[str]) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
    logs.append(f"Extracted {zip_path.name} -> {destination}")


def _install_ffuf(destination: Path, logs: List[str]) -> None:
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
        _download(asset_url, zip_path, logs)
        _extract_zip(zip_path, destination, logs)


def _install_sqlmap(destination: Path, logs: List[str]) -> None:
    url = "https://github.com/sqlmapproject/sqlmap/archive/refs/heads/master.zip"
    with tempfile.TemporaryDirectory(prefix="koi-sqlmap-") as tmp:
        zip_path = Path(tmp) / "sqlmap.zip"
        _download(url, zip_path, logs)
        extract_dir = Path(tmp) / "extract"
        _extract_zip(zip_path, extract_dir, logs)
        roots = [item for item in extract_dir.iterdir() if item.is_dir()]
        source = roots[0] if roots else extract_dir
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        logs.append(f"Installed sqlmap source -> {destination}")


def _install_nmap(destination: Path, logs: List[str]) -> None:
    archive_url = "https://nmap.org/dist/"
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
        _download(url, zip_path, logs)
        _extract_zip(zip_path, destination, logs)
