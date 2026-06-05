#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import contextlib
import io
import json
import os
import re
import sys
from typing import Any, Dict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ORIGINAL_STDOUT = sys.stdout

from modules.backend_api.commands.data_processing import (
    handle_data_processing_command,
    is_data_processing_command,
)
from modules.AI_Testing.backend_commands import (
    handle_ai_testing_command,
    is_ai_testing_command,
)
from modules.backend_api.commands.document_processing import (
    handle_document_processing_command,
    is_document_processing_command,
)
from modules.backend_api.commands.filesystem import (
    handle_filesystem_command,
    is_filesystem_command,
)
from modules.backend_api.commands.information_gathering import (
    handle_information_gathering_command,
    is_information_gathering_command,
)
from modules.config.config_manager import ConfigManager
from modules.Emergency_help.weekly_report.weekly_report_generator import WeeklyReportGenerator

try:
    from modules.utils.resource_path import ensure_resources_extracted

    ensure_resources_extracted()
except Exception:
    # Backend stdout must stay pure JSON; resource extraction failures are reported
    # by the actual command that needs the missing resource.
    pass


def _response(ok: bool, data: Any = None, error: str | None = None) -> Dict[str, Any]:
    return {"ok": ok, "data": data, "error": error}


def _json_safe(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {_json_safe(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _load_config() -> Dict[str, Any]:
    return ConfigManager().load_config()


def _read_app_version() -> str:
    env_version = os.environ.get("KOI_APP_VERSION", "").strip()
    if env_version:
        return env_version.lstrip("v")

    candidates = [
        os.path.join(ROOT_DIR, "tauri-ui", "src-tauri", "Cargo.toml"),
        os.path.join(ROOT_DIR, "src-tauri", "Cargo.toml"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', content)
            if match:
                return match.group(1).lstrip("v")
        except Exception:
            continue
    return "0.0.0"


def _set_dark_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    dark_mode = bool(payload.get("dark_mode", False))
    manager = ConfigManager()
    config = manager.load_config()
    config.setdefault("ui_settings", {})["dark_mode"] = dark_mode
    config.setdefault("ui", {})["dark_mode"] = dark_mode
    if not manager.save_config(config):
        raise RuntimeError("保存配置失败")
    return {"dark_mode": dark_mode}


def _weekly_report_days(range_text: str) -> int | None:
    text = str(range_text or "")
    for days in (30, 14, 7, 3):
        if str(days) in text:
            return days
    return None


def _generate_weekly_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    range_text = str(payload.get("range") or "")
    detail_text = str(payload.get("detail") or "")
    detailed = bool(payload.get("detailed", "详" in detail_text or "detail" in detail_text.lower()))

    progress_buffer = io.StringIO()
    with contextlib.redirect_stdout(progress_buffer):
        report = WeeklyReportGenerator().generate_report(_weekly_report_days(range_text), detailed)

    progress = [line for line in progress_buffer.getvalue().splitlines() if line.strip()]
    status = "failed" if report.startswith("生成报告时出错") else "success"
    return {
        "report": report,
        "status": status,
        "range": range_text,
        "detail": detail_text,
        "progress": progress,
    }



def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    command = request.get("command")
    payload = request.get("payload") or {}

    if command == "config.load":
        return _response(True, _load_config())
    if command == "config.set_dark_mode":
        return _response(True, _set_dark_mode(payload))
    if command == "app.version":
        return _response(True, {"version": _read_app_version()})
    if command == "weekly_report.generate":
        return _response(True, _generate_weekly_report(payload))
    if is_data_processing_command(command):
        return _response(True, handle_data_processing_command(command, payload))
    if is_ai_testing_command(command):
        return _response(True, handle_ai_testing_command(command, payload))
    if is_document_processing_command(command):
        return _response(True, handle_document_processing_command(command, payload))
    if is_information_gathering_command(command):
        return _response(True, handle_information_gathering_command(command, payload))
    if is_filesystem_command(command):
        return _response(True, handle_filesystem_command(command, payload))

    return _response(False, None, f"未知命令: {command}")


def _process_one(raw: str) -> str:
    try:
        request = json.loads(raw)
        response = handle_request(request)
    except Exception as exc:
        response = _response(False, None, str(exc))
    return json.dumps(_json_safe(response), ensure_ascii=True)


def main() -> int:
    """
    持续运行 JSON-RPC 循环（sidecar / daemon 模式）。
    stdin 每行是一个 JSON 请求，stdout 每行是一个 JSON 响应。
    EOF 或空行退出。
    """
    try:
        for line in sys.stdin:
            stripped = line.strip()
            if not stripped:
                continue
            result = _process_one(stripped)
            ORIGINAL_STDOUT.write(result + "\n")
            ORIGINAL_STDOUT.flush()
    except Exception as exc:
        response = _response(False, None, str(exc))
        ORIGINAL_STDOUT.write(json.dumps(_json_safe(response), ensure_ascii=True) + "\n")
        ORIGINAL_STDOUT.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
