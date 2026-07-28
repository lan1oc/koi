#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import contextlib
import io
import json
import os
import re
import sys
from datetime import date, datetime
from typing import Any, Dict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ORIGINAL_STDOUT = sys.stdout
PROTOCOL_STDOUT = ORIGINAL_STDOUT
# Keep the sidecar stdout channel reserved for one JSON response per request.
# Ordinary print/log output must not pollute the line protocol that Tauri reads.
sys.stdout = sys.stderr

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

    version_files = []
    app_dir = os.environ.get("KOI_APP_DIR", "").strip()
    if app_dir:
        version_files.append(os.path.join(app_dir, "version.txt"))
    if getattr(sys, "frozen", False):
        version_files.append(os.path.join(os.path.dirname(sys.executable), "version.txt"))
    version_files.append(os.path.join(ROOT_DIR, "version.txt"))
    for path in version_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                version = f.read().strip()
            if version:
                return version.lstrip("v")
        except Exception:
            continue

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


def _get_weekly_report_config() -> Dict[str, Any]:
    config = ConfigManager().load_config()
    weekly = config.get("weekly_report") if isinstance(config.get("weekly_report"), dict) else {}
    return {
        "vulnerability_notice_dir": str(weekly.get("vulnerability_notice_dir") or ""),
        "event_notice_dir": str(weekly.get("event_notice_dir") or ""),
        "exclude_monday_next_notice": bool(weekly.get("exclude_monday_next_notice", False)),
        "last_updated": str(weekly.get("last_updated") or ""),
    }


def _set_weekly_report_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    vulnerability_notice_dir = str(
        payload.get("vulnerability_notice_dir")
        or payload.get("vulnerabilityNoticeDir")
        or ""
    ).strip()
    event_notice_dir = str(
        payload.get("event_notice_dir")
        or payload.get("eventNoticeDir")
        or ""
    ).strip()
    exclude_monday_next_notice = bool(
        payload.get("exclude_monday_next_notice")
        if "exclude_monday_next_notice" in payload
        else payload.get("excludeMondayNextNotice", False)
    )
    manager = ConfigManager()
    config = manager.load_config()
    config.setdefault("weekly_report", {})
    config["weekly_report"].update({
        "vulnerability_notice_dir": vulnerability_notice_dir,
        "event_notice_dir": event_notice_dir,
        "exclude_monday_next_notice": exclude_monday_next_notice,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    if not manager.save_config(config):
        raise RuntimeError("保存周报路径配置失败")
    return _get_weekly_report_config()


def _parse_weekly_report_date(payload: Dict[str, Any]) -> date:
    raw = str(
        payload.get("report_date")
        or payload.get("reportDate")
        or payload.get("today")
        or ""
    ).strip()
    if not raw:
        return datetime.now().date()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"周报基准日期格式错误，应为 YYYY-MM-DD: {raw}") from exc


def _generate_weekly_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    saved = _get_weekly_report_config()
    vulnerability_notice_dir = str(
        payload.get("vulnerability_notice_dir")
        or payload.get("vulnerabilityNoticeDir")
        or saved.get("vulnerability_notice_dir")
        or ""
    ).strip()
    event_notice_dir = str(
        payload.get("event_notice_dir")
        or payload.get("eventNoticeDir")
        or saved.get("event_notice_dir")
        or ""
    ).strip()
    exclude_monday_next_notice = bool(
        payload.get("exclude_monday_next_notice")
        if "exclude_monday_next_notice" in payload
        else payload.get(
            "excludeMondayNextNotice",
            saved.get("exclude_monday_next_notice", False),
        )
    )
    report_date = _parse_weekly_report_date(payload)

    progress_buffer = io.StringIO()
    with contextlib.redirect_stdout(progress_buffer):
        summary = WeeklyReportGenerator().generate_closure_summary(
            vulnerability_notice_dir=vulnerability_notice_dir,
            event_notice_dir=event_notice_dir,
            today=report_date,
            exclude_monday_next_notice=exclude_monday_next_notice,
        )
        report = summary["report"]
        if vulnerability_notice_dir or event_notice_dir:
            _set_weekly_report_config({
                "vulnerability_notice_dir": vulnerability_notice_dir,
                "event_notice_dir": event_notice_dir,
                "exclude_monday_next_notice": exclude_monday_next_notice,
            })

    progress = [line for line in progress_buffer.getvalue().splitlines() if line.strip()]
    status = "failed" if report.startswith("生成报告时出错") else "success"
    return {
        "report": report,
        "status": status,
        "vulnerability_notice_dir": vulnerability_notice_dir,
        "event_notice_dir": event_notice_dir,
        "exclude_monday_next_notice": exclude_monday_next_notice,
        "report_date": report_date.isoformat(),
        "progress": progress,
        "summary": summary if status == "success" else {},
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
    if command == "weekly_report.config.get":
        return _response(True, _get_weekly_report_config())
    if command == "weekly_report.config.set":
        return _response(True, _set_weekly_report_config(payload))
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
        with contextlib.redirect_stdout(sys.stderr):
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
            PROTOCOL_STDOUT.write(result + "\n")
            PROTOCOL_STDOUT.flush()
    except Exception as exc:
        response = _response(False, None, str(exc))
        PROTOCOL_STDOUT.write(json.dumps(_json_safe(response), ensure_ascii=True) + "\n")
        PROTOCOL_STDOUT.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
