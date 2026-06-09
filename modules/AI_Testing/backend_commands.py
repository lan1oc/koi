#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI testing backend commands and retest agent runtime."""

import base64
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

import requests

WORD_SUFFIXES = {".doc", ".docx"}
RETEST_AI_PROVIDERS = {"openai", "anthropic", "openrouter"}
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_FREE_MODEL = "openrouter/free"
OPENROUTER_FREE_LIMITS = {
    "requests_per_minute": 20,
    "daily_without_credits": 50,
    "daily_with_credits": 1000,
    "credits_threshold_usd": 10,
}

AI_TESTING_COMMANDS = {
    "doc.retest.run",
    "doc.retest.list_files",
    "doc.retest.run_one",
    "doc.retest.run_one.start",
    "doc.retest.run_one.status",
    "doc.retest.run_one.stop",
    "doc.retest.confirmation.respond",
    "doc.retest.event_stream.info",
    "doc.retest.agent.start",
    "doc.retest.agent.message",
    "doc.retest.agent.status",
    "doc.retest.agent.stop",
    "doc.retest.agent_chat",
    "doc.retest.ai_config.get",
    "doc.retest.ai_config.set",
    "doc.retest.ai_config.test",
    "doc.retest.ai_config.key_status",
    "doc.retest.tools.list",
    "doc.retest.tools.status",
    "doc.retest.tools.install",
    "doc.retest.generate_reports_with_screenshot",
    "doc.retest.open_output",
}

class _ProgressTee(io.TextIOBase):
    def __init__(self, original: Any, progress: "NoticeProgress"):
        self.original = original
        self.progress = progress
        self._buffer = ""

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8")

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        value = str(text)
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.progress.log(line.rstrip())
        if self.original is not None and self.original is not sys.stdout:
            try:
                self.original.write(value)
            except Exception:
                pass
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            self.progress.log(self._buffer.rstrip())
        self._buffer = ""
        if self.original is not None and self.original is not sys.stdout:
            try:
                self.original.flush()
            except Exception:
                pass


class NoticeProgress:
    def __init__(self, total: int = 0):
        self.lock = threading.RLock()
        self.logs: List[str] = []
        self.progress = 0
        self.message = "等待开始..."
        self.processed = 0
        self.total = max(0, int(total or 0))

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "progress": self.progress,
                "message": self.message,
                "logs": list(self.logs),
                "processed": self.processed,
                "total_reports": self.total,
            }

    def log(self, message: Any) -> None:
        text = str(message or "").strip("\r\n")
        if not text:
            return
        with self.lock:
            self.logs.append(text)
            self.message = text

    def extend(self, messages: Iterable[Any]) -> None:
        for message in messages:
            self.log(message)

    def set(self, progress: int | float | None = None, message: Any | None = None) -> None:
        with self.lock:
            if progress is not None:
                self.progress = max(0, min(100, int(round(float(progress)))))
            if message is not None:
                self.message = str(message)

    def set_total(self, total: int) -> None:
        with self.lock:
            self.total = max(0, int(total or 0))

    def set_processed(self, processed: int, total: int | None = None, message: Any | None = None) -> None:
        with self.lock:
            self.processed = max(0, int(processed or 0))
            if total is not None:
                self.total = max(0, int(total or 0))
            total_value = self.total
            if total_value > 0:
                self.progress = max(self.progress, min(98, 20 + int(self.processed / total_value * 75)))
            if message is not None:
                self.message = str(message)


class ProgressLogList(list):
    def __init__(self, progress: NoticeProgress | None = None):
        super().__init__()
        self.progress = progress

    def append(self, item: Any) -> None:
        super().append(str(item))
        if self.progress:
            self.progress.log(item)

    def extend(self, items: Iterable[Any]) -> None:
        for item in items:
            self.append(item)

    def extend_silent(self, items: Iterable[Any]) -> None:
        for item in items:
            super().append(str(item))


class RetestTaskProgress(NoticeProgress):
    def __init__(self, total: int = 0):
        super().__init__(total)
        self.trace_events: List[Dict[str, Any]] = []
        self.session_id = ""
        self.task_id = ""
        self.stop_requested = False

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "progress": self.progress,
                "message": self.message,
                "logs": list(self.logs),
                "processed": self.processed,
                "total_reports": self.total,
                "trace_events": list(self.trace_events),
                "stop_requested": self.stop_requested,
            }

    def request_stop(self, message: str = "复测已停止，可继续") -> None:
        with self.lock:
            self.stop_requested = True
            self.message = message
            self.logs.append(message)

    def should_stop(self) -> bool:
        with self.lock:
            return bool(self.stop_requested)

    def event(self, event: Dict[str, Any] | None) -> None:
        if not isinstance(event, dict):
            return
        with self.lock:
            self.trace_events.append(dict(event))
            title = str(event.get("title") or "").strip()
            if title:
                self.message = title
        try:
            from modules.backend_api.retest_event_stream import publish_retest_event

            publish_retest_event({
                "type": "retest_trace_event",
                "session_id": self.session_id,
                "task_id": self.task_id,
                "event": event,
            })
        except Exception:
            pass

_RETEST_TASKS: Dict[str, Dict[str, Any]] = {}
_RETEST_TASK_LOCK = threading.RLock()
_RETEST_AGENT_RUNNERS: Dict[str, "RetestAgentRunner"] = {}
_RETEST_AGENT_LOCK = threading.RLock()

# ---- 人在回路确认（probe 含本机破坏性操作时，暂停等用户批准）----
# confirmation_id -> {"event": threading.Event, "decision": "approve"|"reject"|"", "note": str}
_RETEST_CONFIRMATIONS: Dict[str, Dict[str, Any]] = {}
_RETEST_CONFIRM_LOCK = threading.RLock()


def _register_confirmation(confirmation_id: str) -> threading.Event:
    evt = threading.Event()
    with _RETEST_CONFIRM_LOCK:
        _RETEST_CONFIRMATIONS[confirmation_id] = {"event": evt, "decision": "", "note": ""}
    return evt


def _resolve_confirmation(confirmation_id: str, decision: str, note: str = "") -> bool:
    with _RETEST_CONFIRM_LOCK:
        entry = _RETEST_CONFIRMATIONS.get(confirmation_id)
        if not entry:
            return False
        entry["decision"] = "approve" if str(decision).lower() in {"approve", "yes", "allow", "true", "1"} else "reject"
        entry["note"] = str(note or "")
        entry["event"].set()
    return True


def _read_confirmation(confirmation_id: str) -> Dict[str, Any]:
    with _RETEST_CONFIRM_LOCK:
        entry = _RETEST_CONFIRMATIONS.get(confirmation_id) or {}
        return {"decision": entry.get("decision") or "", "note": entry.get("note") or ""}


def _discard_confirmation(confirmation_id: str) -> None:
    with _RETEST_CONFIRM_LOCK:
        _RETEST_CONFIRMATIONS.pop(confirmation_id, None)


def _retest_request_confirmation(progress: "RetestTaskProgress | None", request: Dict[str, Any]) -> Dict[str, Any]:
    """暂停并向 UI 推送确认卡片，阻塞等待用户批准/拒绝本机破坏性操作。

    request: {"operation": str, "detail": str, "script": str, "matched": str}
    返回:    {"decision": "approve"|"reject", "note": str}
    用户点停止 / 超时（默认 300s）均按拒绝处理，且原因回传给模型促其改写脚本。
    """
    confirmation_id = uuid.uuid4().hex
    evt = _register_confirmation(confirmation_id)
    operation = str(request.get("operation") or "本机敏感操作")
    matched = str(request.get("matched") or "")
    detail = str(request.get("detail") or "")
    script = str(request.get("script") or "")
    try:
        if progress is not None:
            progress.event(_retest_trace_event(
                "confirmation_request",
                f"需要你确认：{operation}",
                f"复测脚本包含可能影响本机电脑的操作（{matched}）。\n{detail}\n\n"
                f"批准则按原脚本执行；拒绝则不在你本机执行该操作，并让模型改写脚本。",
                "warn",
                metadata={
                    "confirmationId": confirmation_id,
                    "operation": operation,
                    "matched": matched,
                    "script": script[:4000],
                    "requiresUserDecision": True,
                },
            ))
        # 阻塞等待用户决定；期间若用户点了停止，立即按拒绝放行循环。
        waited = 0.0
        while not evt.wait(timeout=1.0):
            waited += 1.0
            if progress is not None and progress.should_stop():
                _discard_confirmation(confirmation_id)
                return {"decision": "reject", "note": "用户已停止复测"}
            if waited >= 300:
                _discard_confirmation(confirmation_id)
                return {"decision": "reject", "note": "确认超时（300s），默认拒绝"}
        outcome = _read_confirmation(confirmation_id)
        _discard_confirmation(confirmation_id)
        return {"decision": outcome.get("decision") or "reject", "note": outcome.get("note") or ""}
    except Exception:
        _discard_confirmation(confirmation_id)
        return {"decision": "reject", "note": "确认流程异常，默认拒绝"}




def is_ai_testing_command(command: str | None) -> bool:
    return str(command or "") in AI_TESTING_COMMANDS


def handle_ai_testing_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if command == "doc.retest.run":
        return _doc_retest_run(payload)
    if command == "doc.retest.list_files":
        return _doc_retest_list_files(payload)
    if command == "doc.retest.run_one":
        return _doc_retest_run_one(payload)
    if command == "doc.retest.run_one.start":
        return _doc_retest_run_one_start(payload)
    if command == "doc.retest.run_one.status":
        return _doc_retest_run_one_status(payload)
    if command == "doc.retest.run_one.stop":
        return _doc_retest_run_one_stop(payload)
    if command == "doc.retest.confirmation.respond":
        return _doc_retest_confirmation_respond(payload)
    if command == "doc.retest.event_stream.info":
        return _doc_retest_event_stream_info(payload)
    if command == "doc.retest.agent.start":
        return _doc_retest_agent_start(payload)
    if command == "doc.retest.agent.message":
        return _doc_retest_agent_message(payload)
    if command == "doc.retest.agent.status":
        return _doc_retest_agent_status(payload)
    if command == "doc.retest.agent.stop":
        return _doc_retest_agent_stop(payload)
    if command == "doc.retest.agent_chat":
        return _doc_retest_agent_chat(payload)
    if command == "doc.retest.ai_config.get":
        return _doc_retest_ai_config_get(payload)
    if command == "doc.retest.ai_config.set":
        return _doc_retest_ai_config_set(payload)
    if command == "doc.retest.ai_config.test":
        return _doc_retest_ai_config_test(payload)
    if command == "doc.retest.ai_config.key_status":
        return _doc_retest_ai_key_status(payload)
    if command == "doc.retest.tools.list":
        return _doc_retest_tools_list(payload)
    if command == "doc.retest.tools.status":
        return _doc_retest_tools_status(payload)
    if command == "doc.retest.tools.install":
        return _doc_retest_tools_install(payload)
    if command == "doc.retest.generate_reports_with_screenshot":
        return _doc_retest_generate_reports_with_screenshot(payload)
    if command == "doc.retest.open_output":
        return _doc_retest_open_output(payload)
    raise ValueError(f"未知 AI 测试命令: {command}")

def _required_text(payload: Dict[str, Any], key: str, message: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(message)
    return value

def _path_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]

_MODEL_REPRODUCED_VALUES = {"reproduced", "reproducible", "unfixed", "not_fixed", "risk", "vulnerable", "可复现", "未修复"}
_MODEL_CLEAN_VALUES = {"not_reproduced", "not reproducible", "fixed", "clean", "pass", "passed", "已修复", "复测通过", "不可复现"}


def _model_verdict_from_judgement(judgement: Dict[str, Any] | None, fallback: Any = "") -> str:
    """Return only the model's explicit verdict; never infer from tool counts."""
    source = judgement if isinstance(judgement, dict) else {}
    raw = str(
        source.get("verdict")
        or source.get("reproduction_status")
        or source.get("fix_status")
        or fallback
        or ""
    ).strip().lower()
    if raw in _MODEL_REPRODUCED_VALUES:
        return "reproduced"
    if raw in _MODEL_CLEAN_VALUES:
        return "not_reproduced"
    if isinstance(source.get("reproduced"), bool):
        return "reproduced" if source.get("reproduced") else "not_reproduced"
    return ""


def _model_verdict_from_result_data(data: Dict[str, Any] | None) -> str:
    source = data if isinstance(data, dict) else {}
    judgement = source.get("ai_judgement") if isinstance(source.get("ai_judgement"), dict) else {}
    return _model_verdict_from_judgement(judgement, source.get("final_verdict"))


def _model_reproduced_from_result_data(data: Dict[str, Any] | None) -> bool | None:
    verdict = _model_verdict_from_result_data(data)
    if verdict == "reproduced":
        return True
    if verdict == "not_reproduced":
        return False
    return None


def _failure_dicts(failures: Iterable[tuple[Path, str]]) -> List[Dict[str, str]]:
    return [{"file": str(src), "name": src.name, "reason": str(reason)} for src, reason in failures]


def _captured_lines(buffer: io.StringIO) -> List[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


def _store_captured_lines(logs: List[str], lines: Iterable[Any]) -> None:
    if isinstance(logs, ProgressLogList):
        logs.extend_silent(lines)
    else:
        logs.extend(str(line) for line in lines)


def _append_log(logs: List[str], message: Any, progress: NoticeProgress | None = None) -> None:
    text = str(message or "")
    logs.append(text)
    if progress:
        progress.log(text)


def _extend_logs(logs: List[str], messages: Iterable[Any], progress: NoticeProgress | None = None) -> None:
    for message in messages:
        _append_log(logs, message, progress)


def _run_with_progress_capture(func: Any, progress: NoticeProgress | None = None) -> tuple[Any, List[str]]:
    buffer = io.StringIO()
    stream: Any = _ProgressTee(buffer, progress) if progress else buffer
    with contextlib.redirect_stdout(stream):
        result = func()
    try:
        stream.flush()
    except Exception:
        pass
    return result, _captured_lines(buffer)


def _call_with_progress_capture(func: Any, progress: NoticeProgress | None = None) -> tuple[Any, List[str], BaseException | None]:
    buffer = io.StringIO()
    stream: Any = _ProgressTee(buffer, progress) if progress else buffer
    result = None
    error: BaseException | None = None
    with contextlib.redirect_stdout(stream):
        try:
            result = func()
        except BaseException as exc:
            error = exc
    try:
        stream.flush()
    except Exception:
        pass
    return result, _captured_lines(buffer), error

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

def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _template_dir() -> Path:
    try:
        from modules.utils.resource_path import get_report_template_dir

        return get_report_template_dir()
    except Exception:
        return _project_root() / "Report_Template"


def _find_template(keyword: str) -> Path | None:
    template_root = _template_dir()
    if not template_root.exists():
        return None
    candidates = sorted(
        item
        for item in template_root.iterdir()
        if item.is_file() and item.suffix.lower() in {".doc", ".docx"}
    )
    return next((item for item in candidates if keyword in item.name), None)


def _retest_template_path() -> Path:
    template_root = _template_dir()
    for filename in ("复测模板.docx", "复测模板.doc", "澶嶆祴妯℃澘.docx"):
        candidate = template_root / filename
        if candidate.exists():
            return candidate
    found = _find_template("复测")
    return found or (template_root / "复测模板.docx")

def _normalize_retest_ai_provider(value: Any) -> str:
    provider = str(value or "openai").strip().lower()
    return provider if provider in RETEST_AI_PROVIDERS else "openai"


def _retest_ai_provider_default_name(provider: str) -> str:
    provider = _normalize_retest_ai_provider(provider)
    if provider == "openrouter":
        return "OpenRouter 免费路由"
    if provider == "anthropic":
        return "Anthropic"
    return "默认 OpenAI"


def _retest_ai_provider_label(provider: str) -> str:
    provider = _normalize_retest_ai_provider(provider)
    if provider == "openrouter":
        return "OpenRouter"
    if provider == "anthropic":
        return "Anthropic"
    return "OpenAI"


def _retest_ai_provider_defaults(provider: str) -> Dict[str, Any]:
    provider = _normalize_retest_ai_provider(provider)
    if provider == "openrouter":
        return {
            "base_url": OPENROUTER_DEFAULT_BASE_URL,
            "model": OPENROUTER_FREE_MODEL,
            "max_tokens": 1600,
            "context_window": 128000,
        }
    return {
        "base_url": "",
        "model": "",
        "max_tokens": 1600,
        "context_window": 128000,
    }


def _default_retest_ai_profile(profile_id: str = "default", name: str | None = None, provider: str = "openai") -> Dict[str, Any]:
    provider = _normalize_retest_ai_provider(provider)
    defaults = _retest_ai_provider_defaults(provider)
    return {
        "id": profile_id,
        "name": name or _retest_ai_provider_default_name(provider),
        "provider": provider,
        "base_url": defaults["base_url"],
        "api_key": "",
        "model": defaults["model"],
        "temperature": 0.1,
        "max_tokens": defaults["max_tokens"],
        "context_window": defaults["context_window"],
        "last_updated": "",
    }


def _default_retest_ai_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "active_profile_id": "default",
        "profiles": [
            _default_retest_ai_profile(),
            _default_retest_ai_profile("openrouter-free", "OpenRouter 免费路由", "openrouter"),
        ],
        "last_updated": "",
    }


def _retest_ai_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_retest_ai_profile_id(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    return text[:64] or f"profile-{uuid.uuid4().hex[:8]}"


def _retest_ai_float(value: Any, default: float = 0.1) -> float:
    try:
        return max(0.0, min(2.0, float(value)))
    except Exception:
        return default


def _retest_ai_int(value: Any, default: int = 1600) -> int:
    try:
        return max(128, min(65536, int(value)))
    except Exception:
        return default


def _retest_ai_context_int(value: Any, default: int = 128000) -> int:
    try:
        return max(4096, min(2000000, int(value)))
    except Exception:
        return default


def _normalize_retest_ai_profile(raw: Dict[str, Any] | None, fallback_id: str = "default", fallback_name: str = "默认 OpenAI") -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    profile_id = _sanitize_retest_ai_profile_id(source.get("id") or fallback_id)
    provider = _normalize_retest_ai_provider(source.get("provider") or "openai")
    profile = _default_retest_ai_profile(fallback_id, fallback_name, provider)
    defaults = _retest_ai_provider_defaults(provider)
    profile.update({
        "id": profile_id,
        "name": str(source.get("name") or fallback_name or profile_id).strip()[:80] or profile_id,
        "provider": provider,
        "base_url": str(source.get("base_url") or defaults["base_url"]).strip(),
        "api_key": str(source.get("api_key") or "").strip(),
        "model": str(source.get("model") or defaults["model"]).strip(),
        "temperature": _retest_ai_float(source.get("temperature"), 0.1),
        "max_tokens": _retest_ai_int(source.get("max_tokens"), defaults["max_tokens"]),
        "context_window": _retest_ai_context_int(source.get("context_window"), defaults["context_window"]),
        "last_updated": str(source.get("last_updated") or ""),
    })
    return profile


def _normalize_retest_ai_config(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    store = _default_retest_ai_config()
    store["enabled"] = _payload_bool(source.get("enabled"), False)
    store["last_updated"] = str(source.get("last_updated") or "")

    raw_profiles = source.get("profiles") if isinstance(source.get("profiles"), list) else None
    if raw_profiles is None:
        # 兼容旧版单配置：provider/base_url/api_key/model 直接挂在 retest_ai_agent 下。
        migrated = _normalize_retest_ai_profile(source, "default", str(source.get("name") or "默认 OpenAI"))
        store["profiles"] = [migrated]
        if migrated.get("provider") != "openrouter":
            store["profiles"].append(_default_retest_ai_profile("openrouter-free", "OpenRouter 免费路由", "openrouter"))
        store["active_profile_id"] = migrated["id"]
        return store

    profiles: List[Dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, item in enumerate(raw_profiles):
        if not isinstance(item, dict):
            continue
        fallback_id = "default" if index == 0 else f"profile-{index + 1}"
        profile = _normalize_retest_ai_profile(item, fallback_id, str(item.get("name") or f"配置 {index + 1}"))
        base_id = profile["id"]
        if base_id in used_ids:
            suffix = 2
            while f"{base_id}-{suffix}" in used_ids:
                suffix += 1
            profile["id"] = f"{base_id}-{suffix}"
        used_ids.add(profile["id"])
        profiles.append(profile)

    if not profiles:
        profiles = [_default_retest_ai_profile()]
        used_ids = {"default"}
    if not any(profile.get("provider") == "openrouter" for profile in profiles):
        profile_id = "openrouter-free"
        suffix = 2
        while profile_id in used_ids:
            profile_id = f"openrouter-free-{suffix}"
            suffix += 1
        profiles.append(_default_retest_ai_profile(profile_id, "OpenRouter 免费路由", "openrouter"))
        used_ids.add(profile_id)
    active_id = _sanitize_retest_ai_profile_id(source.get("active_profile_id") or profiles[0]["id"])
    if active_id not in used_ids:
        active_id = profiles[0]["id"]
    store["profiles"] = profiles
    store["active_profile_id"] = active_id
    return store


def _load_retest_ai_store() -> Dict[str, Any]:
    from modules.config.config_manager import ConfigManager

    manager = ConfigManager()
    config = manager.load_config()
    raw = config.get("retest_ai_agent") if isinstance(config.get("retest_ai_agent"), dict) else {}
    return _normalize_retest_ai_config(raw)


def _active_retest_ai_profile(store: Dict[str, Any]) -> Dict[str, Any]:
    active_id = str(store.get("active_profile_id") or "")
    for profile in store.get("profiles") or []:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            return profile
    profiles = store.get("profiles") or []
    return profiles[0] if profiles and isinstance(profiles[0], dict) else _default_retest_ai_profile()


def _load_retest_ai_config() -> Dict[str, Any]:
    store = _load_retest_ai_store()
    active_profile = _active_retest_ai_profile(store)
    runtime = dict(active_profile)
    runtime["enabled"] = bool(store.get("enabled"))
    runtime["active_profile_id"] = active_profile.get("id")
    return runtime


class RetestAIBlockedError(RuntimeError):
    def __init__(self, message: str, stage: str = "config"):
        super().__init__(message)
        self.stage = stage


def _ai_blocked_title(exc: RetestAIBlockedError) -> str:
    message = str(exc)
    if "超时" in message:
        return "模型响应超时"
    if "HTTP 429" in message or "限流" in message or "并发" in message:
        return "模型并发/限流"
    if exc.stage == "config" or "配置" in message or "未启用" in message:
        return "AI 配置阻塞"
    return "AI 测试暂停"


def _ensure_retest_ai_ready(stage: str = "config") -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_ai_agent import RetestLLMClient, load_retest_prompt

        ai_config = _load_retest_ai_config()
        client = RetestLLMClient(ai_config)
    except RetestAIBlockedError:
        raise
    except Exception as exc:
        raise RetestAIBlockedError(f"读取 AI 测试配置失败: {exc}", stage) from exc

    if not ai_config.get("enabled"):
        raise RetestAIBlockedError(
            "AI 测试未启用。请先在「模型与工具」配置并启用 AI，然后回到测试工作台点击「继续测试」。",
            stage,
        )
    if not client.is_ready():
        missing = "、".join(client.missing_items() or ["必要配置"])
        raise RetestAIBlockedError(
            f"AI 测试配置不完整，缺少 {missing}。请先在「模型与工具」补全配置，然后回到测试工作台点击「继续测试」。",
            stage,
        )
    return ai_config


def _ai_blocked_payload(
    exc: RetestAIBlockedError,
    source_file: str = "",
    logs: List[str] | None = None,
    trace_events: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "success": False,
        "blocked_by_ai": True,
        "blocked_by_ai_config": True,
        "blocked_stage": exc.stage,
        "blocked_title": _ai_blocked_title(exc),
        "message": str(exc),
        "source_file": source_file,
        "manual_test_required": False,
        "logs": list(logs or []),
        "trace_events": list(trace_events or []),
    }


def _safe_retest_ai_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    safe = _normalize_retest_ai_profile(profile, str(profile.get("id") or "default"), str(profile.get("name") or "默认 OpenAI"))
    api_key = str(safe.get("api_key") or "")
    safe.pop("api_key", None)
    safe["api_key_configured"] = bool(api_key)
    safe["api_key_masked"] = (api_key[:3] + "***" + api_key[-3:]) if len(api_key) >= 8 else ("***" if api_key else "")
    return safe


def _safe_retest_ai_config(config: Dict[str, Any]) -> Dict[str, Any]:
    store = _normalize_retest_ai_config(config)
    safe_profiles = [_safe_retest_ai_profile(profile) for profile in store.get("profiles") or [] if isinstance(profile, dict)]
    active_profile = next(
        (profile for profile in safe_profiles if profile.get("id") == store.get("active_profile_id")),
        safe_profiles[0] if safe_profiles else _safe_retest_ai_profile(_default_retest_ai_profile()),
    )
    return {
        "enabled": bool(store.get("enabled")),
        "active_profile_id": active_profile.get("id"),
        "active_profile": active_profile,
        "profiles": safe_profiles,
        "last_updated": str(store.get("last_updated") or ""),
        # 兼容旧前端字段，指向当前 active profile。
        "provider": active_profile.get("provider"),
        "base_url": active_profile.get("base_url"),
        "model": active_profile.get("model"),
        "temperature": active_profile.get("temperature"),
        "max_tokens": active_profile.get("max_tokens"),
        "context_window": active_profile.get("context_window"),
        "api_key_configured": active_profile.get("api_key_configured"),
        "api_key_masked": active_profile.get("api_key_masked"),
    }


def _doc_retest_ai_config_get(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = _load_retest_ai_store()
    return {"success": True, "message": "复测 AI Agent 配置已读取", "config": _safe_retest_ai_config(store)}


def _doc_retest_ai_config_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    from modules.config.config_manager import ConfigManager

    manager = ConfigManager()
    config = manager.load_config()
    current = config.get("retest_ai_agent") if isinstance(config.get("retest_ai_agent"), dict) else {}
    store = _normalize_retest_ai_config(current)
    action = str(payload.get("action") or "save_profile").strip().lower()

    if "enabled" in payload:
        store["enabled"] = _payload_bool(payload.get("enabled"), False)

    profiles = [profile for profile in (store.get("profiles") or []) if isinstance(profile, dict)]
    active_id = str(store.get("active_profile_id") or (profiles[0].get("id") if profiles else "default"))

    if action == "set_enabled":
        message = "复测 AI Agent 已启用" if store.get("enabled") else "复测 AI Agent 已关闭"
    elif action == "create_profile":
        provider = _normalize_retest_ai_provider(payload.get("provider") or "openai")
        requested_id = _sanitize_retest_ai_profile_id(payload.get("profile_id") or payload.get("name") or provider)
        used_ids = {str(profile.get("id")) for profile in profiles}
        profile_id = requested_id
        suffix = 2
        while profile_id in used_ids:
            profile_id = f"{requested_id}-{suffix}"
            suffix += 1
        name = str(payload.get("name") or _retest_ai_provider_default_name(provider)).strip()[:80]
        new_profile = _default_retest_ai_profile(profile_id, name or profile_id, provider)
        new_profile["last_updated"] = _retest_ai_now()
        profiles.append(new_profile)
        store["active_profile_id"] = profile_id
        message = "复测 AI 配置档已创建"
    elif action == "switch_profile":
        profile_id = _sanitize_retest_ai_profile_id(payload.get("profile_id") or active_id)
        if not any(profile.get("id") == profile_id for profile in profiles):
            raise ValueError("要切换的 AI 配置档不存在")
        store["active_profile_id"] = profile_id
        message = "已切换复测 AI 配置档"
    elif action == "delete_profile":
        profile_id = _sanitize_retest_ai_profile_id(payload.get("profile_id") or active_id)
        if len(profiles) <= 1:
            raise ValueError("至少需要保留一个 AI 配置档")
        original_count = len(profiles)
        profiles = [profile for profile in profiles if profile.get("id") != profile_id]
        if len(profiles) == original_count:
            raise ValueError("要删除的 AI 配置档不存在")
        if store.get("active_profile_id") == profile_id:
            store["active_profile_id"] = profiles[0].get("id")
        message = "复测 AI 配置档已删除"
    else:
        profile_id = _sanitize_retest_ai_profile_id(payload.get("profile_id") or active_id)
        target = next((profile for profile in profiles if profile.get("id") == profile_id), None)
        provider = _normalize_retest_ai_provider(payload.get("provider") or (target.get("provider") if isinstance(target, dict) else "openai"))
        if target is None:
            target = _default_retest_ai_profile(profile_id, str(payload.get("name") or _retest_ai_provider_default_name(provider)), provider)
            profiles.append(target)
        previous_provider = _normalize_retest_ai_provider(target.get("provider") or "openai")
        defaults = _retest_ai_provider_defaults(provider)
        target["provider"] = provider
        if "name" in payload:
            target["name"] = str(payload.get("name") or target.get("name") or profile_id).strip()[:80] or profile_id
        for key in ("base_url", "model"):
            incoming_value = str(payload.get(key) or "").strip() if key in payload else ""
            if key in payload:
                target[key] = incoming_value or str(defaults.get(key) or "")
            elif provider != previous_provider and not str(target.get(key) or "").strip():
                target[key] = str(defaults.get(key) or "")
        if "api_key" in payload:
            incoming_key = str(payload.get("api_key") or "")
            if incoming_key.strip():
                target["api_key"] = incoming_key.strip()
            elif _payload_bool(payload.get("clear_api_key"), False):
                target["api_key"] = ""
        if "temperature" in payload:
            target["temperature"] = _retest_ai_float(payload.get("temperature"), 0.1)
        if "max_tokens" in payload:
            target["max_tokens"] = _retest_ai_int(payload.get("max_tokens"), 800)
        if "context_window" in payload:
            target["context_window"] = _retest_ai_context_int(payload.get("context_window"), 128000)
        target["last_updated"] = _retest_ai_now()
        store["active_profile_id"] = profile_id
        message = "复测 AI 配置档已保存"

    store["profiles"] = profiles or [_default_retest_ai_profile()]
    if not any(profile.get("id") == store.get("active_profile_id") for profile in store["profiles"]):
        store["active_profile_id"] = store["profiles"][0].get("id")
    store["last_updated"] = _retest_ai_now()
    config["retest_ai_agent"] = store
    if not manager.save_config(config):
        return {"success": False, "message": "保存复测 AI Agent 配置失败", "config": _safe_retest_ai_config(store)}
    return {"success": True, "message": message, "config": _safe_retest_ai_config(store)}


def _runtime_retest_ai_profile_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = _load_retest_ai_store()
    profiles = [profile for profile in (store.get("profiles") or []) if isinstance(profile, dict)]
    requested_id = _sanitize_retest_ai_profile_id(payload.get("profile_id") or store.get("active_profile_id") or "")
    saved_profile = next((profile for profile in profiles if profile.get("id") == requested_id), None) or _active_retest_ai_profile(store)
    runtime_profile = dict(saved_profile)

    for key in ("provider", "base_url", "model"):
        if key in payload:
            runtime_profile[key] = str(payload.get(key) or "").strip()
    if "temperature" in payload:
        runtime_profile["temperature"] = _retest_ai_float(payload.get("temperature"), 0.1)
    if "max_tokens" in payload:
        runtime_profile["max_tokens"] = _retest_ai_int(payload.get("max_tokens"), 800)
    if "context_window" in payload:
        runtime_profile["context_window"] = _retest_ai_context_int(payload.get("context_window"), 128000)
    incoming_key = str(payload.get("api_key") or "").strip()
    if incoming_key:
        runtime_profile["api_key"] = incoming_key
    elif _payload_bool(payload.get("clear_api_key"), False):
        runtime_profile["api_key"] = ""

    return _normalize_retest_ai_profile(runtime_profile, str(saved_profile.get("id") or "default"), str(saved_profile.get("name") or "AI 配置"))


def _sanitize_openrouter_key_status(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return str(value)[:500]
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"api_key", "apikey", "key", "token", "authorization", "password", "secret"}:
                continue
            clean[key_text] = _sanitize_openrouter_key_status(item, depth + 1)
        return clean
    if isinstance(value, list):
        return [_sanitize_openrouter_key_status(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:2000]
    return value


def _openrouter_key_status_summary(data: Any) -> Dict[str, Any]:
    source = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(source, dict):
        return {}
    keys = (
        "label",
        "usage",
        "limit",
        "limit_remaining",
        "limit_reset",
        "is_free_tier",
        "rate_limit",
        "rate_limit_remaining",
        "requests",
        "requests_remaining",
        "credits",
        "credit_balance",
    )
    return {key: source.get(key) for key in keys if key in source}


def _doc_retest_ai_key_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    profile = _runtime_retest_ai_profile_from_payload(payload)
    provider = _normalize_retest_ai_provider(profile.get("provider"))
    if provider != "openrouter":
        return {
            "success": False,
            "message": "当前 Key 状态查询仅支持 OpenRouter。请切换到 OpenRouter 免费路由配置后再查询。",
            "provider": provider,
            "model": profile.get("model") or "",
            "free_model_limits": OPENROUTER_FREE_LIMITS,
        }
    api_key = str(profile.get("api_key") or "").strip()
    if not api_key:
        return {
            "success": False,
            "message": "请先填写或保存 OpenRouter API Key，再查询当前限制和剩余额度。",
            "provider": provider,
            "model": profile.get("model") or "",
            "free_model_limits": OPENROUTER_FREE_LIMITS,
        }

    base_url = str(profile.get("base_url") or OPENROUTER_DEFAULT_BASE_URL).strip().rstrip("/") or OPENROUTER_DEFAULT_BASE_URL
    endpoint = f"{base_url}/key"
    started = time.time()
    try:
        response = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(10, 30),
        )
        elapsed_ms = int((time.time() - started) * 1000)
        if response.status_code == 429:
            return {
                "success": False,
                "message": "OpenRouter Key 状态查询被限流（HTTP 429），请稍后再试。",
                "provider": provider,
                "model": profile.get("model") or "",
                "endpoint": endpoint,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "free_model_limits": OPENROUTER_FREE_LIMITS,
            }
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            return {
                "success": False,
                "message": f"OpenRouter Key 状态查询失败（HTTP {response.status_code}）: {response.text[:500]}",
                "provider": provider,
                "model": profile.get("model") or "",
                "endpoint": endpoint,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
                "free_model_limits": OPENROUTER_FREE_LIMITS,
            }
        try:
            data = response.json()
        except Exception as exc:
            return {
                "success": False,
                "message": f"OpenRouter Key 状态返回内容不是 JSON: {exc}",
                "provider": provider,
                "model": profile.get("model") or "",
                "endpoint": endpoint,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
                "free_model_limits": OPENROUTER_FREE_LIMITS,
            }
        safe_data = _sanitize_openrouter_key_status(data)
        return {
            "success": True,
            "message": "OpenRouter Key 状态已读取。免费路由在本应用内会串行并按 20 次/分钟保护；每日额度以 OpenRouter 当前账号状态为准。",
            "provider": provider,
            "model": profile.get("model") or "",
            "endpoint": endpoint,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "summary": _openrouter_key_status_summary(safe_data),
            "data": safe_data,
            "free_model_limits": OPENROUTER_FREE_LIMITS,
        }
    except requests.exceptions.Timeout as exc:
        return {
            "success": False,
            "message": f"OpenRouter Key 状态查询超时: {exc}",
            "provider": provider,
            "model": profile.get("model") or "",
            "endpoint": endpoint,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": str(exc),
            "free_model_limits": OPENROUTER_FREE_LIMITS,
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"OpenRouter Key 状态查询异常: {exc}",
            "provider": provider,
            "model": profile.get("model") or "",
            "endpoint": endpoint,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": str(exc),
            "free_model_limits": OPENROUTER_FREE_LIMITS,
        }


def _doc_retest_ai_config_test(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_ai_agent import RetestLLMClient, load_retest_prompt
    except Exception as exc:
        return {"success": False, "message": f"导入 AI Agent 客户端失败: {exc}", "error": str(exc)}

    profile = _runtime_retest_ai_profile_from_payload(payload)
    client = RetestLLMClient({**profile, "enabled": True})
    provider = client.provider
    model = client.model
    started = time.time()
    if not client.is_ready():
        missing = []
        if not client.api_key:
            missing.append("API Key")
        if not client.model:
            missing.append("Model")
        if provider not in RETEST_AI_PROVIDERS:
            missing.append("Provider")
        return {
            "success": False,
            "message": "模型测试失败：缺少 " + "、".join(missing or ["必要配置"]),
            "provider": provider,
            "model": model,
            "elapsed_ms": 0,
        }

    try:
        response = client.complete_json(
            load_retest_prompt("connectivity_test_system"),
            json.dumps({
                "task": "请确认当前模型 API 是否可通信。",
                "schema": {"ok": True, "message": "一句中文测试结果"},
            }, ensure_ascii=False),
        )
        elapsed_ms = int((time.time() - started) * 1000)
        reply = json.dumps(response, ensure_ascii=False)
        ok = bool(response.get("ok", True))
        message = str(response.get("message") or response.get("reply") or "模型已返回 JSON，通信正常").strip()
        return {
            "success": ok,
            "message": f"模型测试{'成功' if ok else '失败'}：{message}",
            "provider": provider,
            "model": model,
            "reply": reply,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "success": False,
            "message": f"模型测试失败：{exc}",
            "provider": provider,
            "model": model,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }


def _doc_retest_tools_list(payload: Dict[str, Any]) -> Dict[str, Any]:
    from modules.AI_Testing.retest.retest_tool_registry import RetestToolRegistry

    tools = RetestToolRegistry().catalog()
    categories: Dict[str, int] = {}
    for tool in tools:
        category = str(tool.get("category") or "other")
        categories[category] = categories.get(category, 0) + 1
    return {"success": True, "message": f"已加载 {len(tools)} 个复测工具", "tools": tools, "categories": categories}


def _doc_retest_tools_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_external_tools import tool_status

        return tool_status()
    except Exception as exc:
        return {"success": False, "message": f"读取外部工具状态失败: {exc}", "logs": [traceback.format_exc()]}


def _doc_retest_tools_install(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_external_tools import install_tools

        tool_names = payload.get("tools")
        if isinstance(tool_names, str):
            tool_names = [item.strip() for item in tool_names.split(",") if item.strip()]
        return install_tools(tool_names if isinstance(tool_names, list) else None)
    except Exception as exc:
        return {
            "success": False,
            "message": f"一键下载外部工具失败: {exc}",
            "logs": [traceback.format_exc()],
            "failures": [{"tool": "all", "reason": str(exc)}],
        }


def _valid_http_target(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://")) and not text.startswith((
        "http://schemas.microsoft.com",
        "https://schemas.microsoft.com",
        "http://schemas.openxmlformats.org",
        "https://schemas.openxmlformats.org",
        "http://purl.oclc.org",
        "https://purl.oclc.org",
        "http://www.w3.org",
        "https://www.w3.org",
        "http://www.wps.cn",
        "https://www.wps.cn",
    ))


_RETEST_CONTEXT_TAG_LABELS = {
    "unauthorized": "未授权/越权",
    "directory_listing": "目录列表",
    "path_traversal": "路径遍历",
    "file_read": "任意文件读取",
    "sensitive_file": "敏感文件",
    "config_leak": "配置泄露",
    "source_leak": "源码泄露",
    "backup_file": "备份/压缩文件",
    "swagger_api": "Swagger/API",
    "phpinfo": "PHPInfo/探针",
    "js_library": "前端库版本",
    "response_header": "响应头泄露",
    "tls": "TLS/证书",
    "cors": "CORS",
    "clickjacking": "点击劫持",
    "http_methods": "HTTP方法",
    "weak_password": "弱口令",
    "sql_injection": "SQL注入",
    "xss": "XSS",
    "ssrf": "SSRF",
    "rce": "命令/代码执行",
    "file_upload": "文件上传",
}


def _format_retest_context_tags(tags: Iterable[Any]) -> str:
    labels = [_RETEST_CONTEXT_TAG_LABELS.get(str(tag), str(tag)) for tag in tags]
    return "；".join(dict.fromkeys(label for label in labels if label))


def _redact_retest_context_value(value: Any, replacements: Dict[str, str]) -> Any:
    if isinstance(value, str):
        text = value
        for secret, masked in replacements.items():
            if secret:
                text = text.replace(secret, masked)
        return text
    if isinstance(value, list):
        return [_redact_retest_context_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_retest_context_value(item, replacements)
            for key, item in value.items()
            if str(key).lower() not in {"password", "passwd", "pwd", "cookie", "authorization", "x-api-key", "token"}
        }
    return value


def _sanitize_http_request_candidates(value: Any, replacements: Dict[str, str]) -> List[Dict[str, Any]]:
    sanitized_requests: List[Dict[str, Any]] = []
    if not isinstance(value, list):
        return sanitized_requests

    for item in value:
        if not isinstance(item, dict):
            continue
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        body = str(item.get("body") or "")
        safe_item = {
            "method": item.get("method"),
            "target": item.get("target"),
            "url": item.get("url"),
            "header_names": sorted(str(key) for key in headers.keys()),
            "has_body": bool(body),
            "body_line_count": item.get("body_line_count"),
            "body_size": len(body),
            "evidence_lines": item.get("evidence_lines") or [],
            "source_line": item.get("source_line"),
        }
        sanitized_requests.append(_redact_retest_context_value(safe_item, replacements))
    return sanitized_requests


def _sanitize_retest_context(context: Any) -> Any:
    if not isinstance(context, dict):
        return context

    replacements: Dict[str, str] = {}
    for item in context.get("credential_candidates") or []:
        if isinstance(item, dict):
            password = str(item.get("password") or "")
            masked = str(item.get("password_masked") or "***")
            if password:
                replacements[password] = masked

    sanitized: Dict[str, Any] = {}
    for key, value in context.items():
        if key == "http_request_candidates":
            sanitized[key] = _sanitize_http_request_candidates(value, replacements)
            continue

        if key == "credential_candidates" and isinstance(value, list):
            sanitized_credentials: List[Dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                cleaned = {k: v for k, v in item.items() if k != "password"}
                sanitized_credentials.append(_redact_retest_context_value(cleaned, replacements))
            sanitized[key] = sanitized_credentials
            continue

        if key.lower() in {"password", "passwd", "pwd", "cookie", "authorization", "x-api-key", "token"}:
            continue
        sanitized[key] = _redact_retest_context_value(value, replacements)
    return sanitized


def _sanitize_retest_scan_result(scan_result: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(scan_result)
    sanitized.pop("raw_text", None)
    sanitized["retest_context"] = _sanitize_retest_context(sanitized.get("retest_context") or {})
    return sanitized


def _truncate_retest_agent_text(value: Any, limit: int = 6000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _sanitize_retest_agent_payload(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "..."
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"password", "passwd", "pwd", "cookie", "authorization", "x-api-key", "token", "api_key"}:
                continue
            sanitized[key_text] = _sanitize_retest_agent_payload(item, depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_retest_agent_payload(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return _truncate_retest_agent_text(value, 1000)
    return value


def _doc_retest_agent_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        return {"success": False, "message": "请输入要追问 Agent 的内容", "reply": ""}

    summary = _truncate_retest_agent_text(payload.get("summary"), 8000)
    logs = payload.get("logs") if isinstance(payload.get("logs"), list) else []
    logs = [_truncate_retest_agent_text(item, 800) for item in logs[-60:]]
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    history = [_sanitize_retest_agent_payload(item) for item in history[-20:] if isinstance(item, dict)]
    result_data = payload.get("result_data") if isinstance(payload.get("result_data"), dict) else {}
    safe_result_data = _sanitize_retest_agent_payload(result_data)
    session_id = str(payload.get("session_id") or "").strip()
    stream_key = f"agent-chat:{session_id or 'adhoc'}:{uuid.uuid4().hex[:10]}"

    def publish_chat_event(content: str, tone: str = "info", complete: bool = False) -> None:
        if not session_id:
            return
        event = _retest_trace_event(
            "chat",
            "Agent",
            _truncate_retest_agent_text(content, 6000),
            tone,
            metadata={
                "role": "agent",
                "phase": "agent_chat",
                "modelOutput": True,
                "dialogueOutput": True,
                "streaming": not complete,
                "completeModelOutput": complete,
                "streamKey": stream_key,
            },
        )
        try:
            from modules.backend_api.retest_event_stream import publish_retest_event

            publish_retest_event({
                "type": "retest_trace_event",
                "session_id": session_id,
                "task_id": "agent-chat",
                "event": event,
            })
        except Exception:
            pass

    def visible_dialogue(raw: str) -> str:
        text = str(raw or "")
        cut_points = []
        for marker in ("```json", "```JSON", "JSON_RESULT:", "\nJSON:", "\n{"):
            index = text.find(marker)
            if index >= 0:
                cut_points.append(index)
        if text.lstrip().startswith("{"):
            return "我正在理解你的意图，并准备调度当前复测会话。"
        if cut_points:
            text = text[:min(cut_points)]
        text = re.sub(r"^\s*AGENT_MESSAGE\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
        return text

    stream_state = {"buffer": "", "visible": "", "last_emit": 0.0, "last_emit_count": 0, "count": 0}

    def stream_callback(chunk: str) -> None:
        text = str(chunk or "")
        if not text:
            return
        stream_state["buffer"] = (str(stream_state["buffer"]) + text)[-12000:]
        stream_state["visible"] = visible_dialogue(str(stream_state["buffer"]))
        stream_state["count"] = int(stream_state["count"]) + len(text)
        now = time.time()
        if now - float(stream_state["last_emit"] or 0.0) < 0.2 and int(stream_state["count"]) - int(stream_state["last_emit_count"]) < 80:
            return
        preview = str(stream_state["visible"] or "").strip()
        if not preview:
            return
        stream_state["last_emit"] = now
        stream_state["last_emit_count"] = stream_state["count"]
        publish_chat_event(preview)

    try:
        from modules.AI_Testing.retest.retest_ai_agent import RetestLLMClient, load_retest_prompt

        ai_config = _load_retest_ai_config()
        client = RetestLLMClient({**ai_config, "_stream_callback": stream_callback, "_dialogue_stream": True})
        provider = client.provider
        model = client.model
        if not ai_config.get("enabled") or not client.is_ready():
            missing = "、".join(client.missing_items() or ["必要配置"])
            reply = f"AI Agent 未启用或配置不完整，缺少 {missing}。当前对话不会回退成本地规则判断，请先在「模型与工具」补全配置后继续。"
            return {
                "success": False,
                "message": reply,
                "reply": reply,
                "action": "none",
                "action_reason": "AI Agent 未配置完成，无法由模型判断会话动作。",
                "provider": provider,
                "model": model,
                "blocked_by_ai_config": True,
                "blocked_stage": "chat",
                "blocked_title": "AI 会话配置阻塞",
                "stream_key": stream_key,
            }

        system_prompt = load_retest_prompt("agent_chat_system")
        user_payload = {
            "schema": {
                "reply": "中文回答",
                "action": "none|continue_retest|rerun_retest",
                "generate_reports": "boolean，默认 false，只有用户明确要求报告时为 true",
                "action_reason": "为什么选择该动作",
            },
            "user_question": message,
            "session_state": {
                "can_continue": bool(payload.get("can_continue")),
                "is_running": bool(payload.get("is_running")),
                "target_dir": str(payload.get("target_dir") or ""),
            },
            "session_summary": summary,
            "recent_logs": logs,
            "chat_history": history,
            "result_data": safe_result_data,
        }
        response = client.complete_json(system_prompt, json.dumps(user_payload, ensure_ascii=False))
        reply = str(response.get("reply") or response.get("answer") or "").strip()
        if not reply:
            if response.get("action") == "continue_retest":
                reply = "我会从当前暂停断点继续复测。"
            elif response.get("action") == "rerun_retest":
                reply = "我会基于当前通报目录重新创建一轮完整复测。"
            else:
                reply = "我已读取当前复测上下文。"
        action = str(response.get("action") or "none").strip()
        if action not in {"none", "continue_retest", "rerun_retest"}:
            action = "none"
        generate_reports = bool(response.get("generate_reports")) and action in {"continue_retest", "rerun_retest"}
        publish_chat_event(reply, "ok", True)
        return {
            "success": True,
            "message": "AI Agent 已回答",
            "reply": _truncate_retest_agent_text(reply, 6000),
            "action": action,
            "generate_reports": generate_reports,
            "action_reason": _truncate_retest_agent_text(response.get("action_reason") or "", 1000),
            "provider": provider,
            "model": model,
            "stream_key": stream_key,
        }
    except Exception as exc:
        message_text = str(exc)
        if "HTTP 429" in message_text or "限流" in message_text or "并发" in message_text:
            title = "模型并发/限流，待继续"
        elif "超时" in message_text or "timeout" in message_text.lower():
            title = "模型响应超时，待继续"
        else:
            title = "AI 会话暂停"
        reply = f"{title}: {message_text}。当前不会回退成本地规则判断，网络或模型恢复后请继续。"
        publish_chat_event(reply, "warn", True)
        return {
            "success": False,
            "message": reply,
            "reply": reply,
            "action": "none",
            "action_reason": "AI Agent 会话调用失败，未使用本地规则兜底。",
            "provider": "",
            "model": "",
            "blocked_by_ai_config": True,
            "blocked_stage": "chat",
            "blocked_title": title,
            "stream_key": stream_key,
        }

def _apply_retest_ai_agent(scan_result: Dict[str, Any], logs: List[str], stream_callback: Callable[[str], None] | None = None) -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_ai_agent import RetestAIAgent
        from modules.AI_Testing.retest.retest_tool_registry import RetestToolRegistry

        ai_config = _ensure_retest_ai_ready("planning")
        if stream_callback:
            ai_config = {**ai_config, "_stream_callback": stream_callback, "_dialogue_stream": True}
        agent = RetestAIAgent(ai_config, RetestToolRegistry())
        advice = agent.advise(scan_result)
        updated = agent.apply_advice(scan_result, advice)
        context = updated.get("retest_context") if isinstance(updated.get("retest_context"), dict) else {}
        agent_advice = context.get("agent_advice") if isinstance(context, dict) else {}
        if isinstance(agent_advice, dict):
            provider = agent_advice.get("provider") or ai_config.get("provider") or "openai"
            model = agent_advice.get("model") or ai_config.get("model") or ""
            prefix = f"AI Agent({provider}{('/' + model) if model else ''})"
            if agent_advice.get("used"):
                recommended = agent_advice.get("recommended_checks") or []
                logs.append(f"{prefix} 已参与复测规划，推荐工具: {', '.join(recommended) if recommended else '无'}")
        return updated
    except RetestAIBlockedError:
        raise
    except Exception as exc:
        message = str(exc)
        if "模型响应超时/网络超时" in message or "HTTP 429" in message:
            raise RetestAIBlockedError(f"AI Agent 规划阶段暂停: {message}", "planning") from exc
        raise RetestAIBlockedError(f"AI Agent 规划阶段调用异常，已暂停，可继续: {message}", "planning") from exc


def _apply_retest_ai_judgement(
    scan_result: Dict[str, Any],
    result_data: Dict[str, Any],
    logs: List[str],
    stream_callback: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    try:
        from modules.AI_Testing.retest.retest_ai_agent import RetestAIAgent
        from modules.AI_Testing.retest.retest_tool_registry import RetestToolRegistry

        ai_config = _ensure_retest_ai_ready("judgement")
        if stream_callback:
            ai_config = {**ai_config, "_stream_callback": stream_callback, "_dialogue_stream": True}
        agent = RetestAIAgent(ai_config, RetestToolRegistry())
        judgement = agent.judge_retest(scan_result, result_data)
        verdict = _model_verdict_from_judgement(judgement)
        if not verdict:
            raise RuntimeError("模型没有给出明确 verdict，不能由工具结果或代码兜底判定。")
        reproduced = verdict == "reproduced"
        judgement["verdict"] = verdict
        judgement["reproduced"] = reproduced
        judgement["fix_status"] = "risk" if reproduced else "clean"
        judgement["conclusion"] = judgement.get("conclusion") or ("漏洞未修复/可复现" if reproduced else "漏洞已修复/复测通过")
        result_data["ai_judgement"] = judgement
        result_data["final_verdict"] = verdict
        result_data["ai_reproduced"] = reproduced
        # Compatibility fields only mirror the model verdict.
        result_data["risk_count"] = 1 if reproduced else 0
        result_data["manual_count"] = 0
        result_data["manual_test_required"] = False
        result_data["reason"] = judgement.get("reason") or result_data.get("reason") or ""
        logs.append(
            "AI Agent 已完成最终判定: "
            + ("漏洞未修复/可复现" if reproduced else "漏洞已修复/复测通过")
        )
        return result_data
    except RetestAIBlockedError:
        raise
    except Exception as exc:
        message = str(exc)
        if "模型响应超时/网络超时" in message or "HTTP 429" in message:
            raise RetestAIBlockedError(f"AI Agent 判定阶段暂停: {message}", "judgement") from exc
        raise RetestAIBlockedError(f"AI Agent 判定阶段调用异常，已暂停，可继续: {message}", "judgement") from exc


def _format_retest_summary(file_path: Path, result_data: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"文件: {file_path.name}")
    scan_result = result_data.get("scan_result") or {}
    vuln_types = scan_result.get("vulnerability_types") or []
    if vuln_types:
        lines.append("通报漏洞类型: " + "；".join(vuln_types))
    context = scan_result.get("retest_context") or {}
    context_tags = context.get("issue_tags") or []
    if context_tags:
        lines.append("正文识别标签: " + _format_retest_context_tags(context_tags))
    agent_advice = context.get("agent_advice") if isinstance(context, dict) else {}
    if isinstance(agent_advice, dict) and agent_advice.get("enabled"):
        provider = agent_advice.get("provider") or ""
        model = agent_advice.get("model") or ""
        ai_state = "已完成通报阅读与复测规划" if agent_advice.get("used") else "规划未完成（已暂停等待继续）"
        lines.append(f"AI Agent: {provider}{('/' + model) if model else ''}，{ai_state}")
        recommended = agent_advice.get("recommended_checks") or []
        if recommended:
            lines.append("AI推荐工具: " + "；".join(str(item) for item in recommended[:10]))
        plan_steps = agent_advice.get("plan_steps") or []
        if plan_steps:
            lines.append("AI复测计划: " + "；".join(str(item) for item in plan_steps[:5]))
        notes = str(agent_advice.get("notes") or agent_advice.get("reason") or agent_advice.get("error") or "").strip()
        if notes:
            lines.append("AI说明: " + notes[:220])
        warnings = agent_advice.get("warnings") or []
        if warnings:
            lines.append("AI提醒: " + "；".join(str(item) for item in warnings[:4]))
    http_requests = context.get("http_request_candidates") or []
    payloads = context.get("payload_candidates") or []
    if http_requests or payloads:
        lines.append(f"正文复测线索: HTTP请求块 {len(http_requests)} 个，参数载荷 {len(payloads)} 个")
    path_candidates = context.get("path_candidates") or []
    if path_candidates:
        lines.append("正文证据路径: " + "；".join(str(item) for item in path_candidates[:6]))
    expected_markers = context.get("expected_markers") or []
    if expected_markers:
        lines.append("正文证据特征: " + "；".join(str(item) for item in expected_markers[:6]))
    credentials = context.get("credential_candidates") or []
    if credentials:
        cred_text = []
        for item in credentials[:3]:
            username = item.get("username", "")
            password = item.get("password_masked", "")
            if username or password:
                cred_text.append(f"{username}/{password}")
        if cred_text:
            lines.append("正文账号线索: " + "；".join(cred_text))
    urls = result_data.get("urls") or []
    lines.append(f"复测URL数量: {len(urls)}")
    if result_data.get("context_supported"):
        lines.append("复测策略: 已启用通报正文上下文复测")
    ai_judgement = result_data.get("ai_judgement") if isinstance(result_data.get("ai_judgement"), dict) else {}
    if ai_judgement:
        lines.append("AI最终判定: " + str(ai_judgement.get("conclusion") or ""))
        if ai_judgement.get("reason"):
            lines.append("AI判定理由: " + str(ai_judgement.get("reason"))[:260])
        evidence = ai_judgement.get("evidence") or []
        if evidence:
            lines.append("AI关键证据: " + "；".join(str(item) for item in evidence[:6]))

    results = result_data.get("retest_results") or []
    observation_records = [
        vuln
        for item in results
        for vuln in (item.get("vulnerabilities") or [])
        if isinstance(vuln, dict)
        and not vuln.get("tool_unavailable")
    ]
    observation_count = result_data.get("observation_count")
    try:
        observation_count = int(observation_count)
    except Exception:
        observation_count = sum(_retest_observation_count(item) for item in results if isinstance(item, dict))
    if observation_count < len(observation_records):
        observation_count = len(observation_records)
    lines.append(f"工具观察记录总数: {max(0, observation_count)}")
    final_verdict = _model_verdict_from_result_data(result_data)
    _judgement = result_data.get("ai_judgement") if isinstance(result_data.get("ai_judgement"), dict) else {}
    _unreachable = bool(_judgement.get("unverified_unreachable") or result_data.get("target_unreachable"))
    if final_verdict == "reproduced":
        lines.append("复测结论: 漏洞未修复/可复现")
    elif final_verdict == "not_reproduced":
        lines.append("复测结论: 未复现：目标不可达，未能验证（建议复查）" if _unreachable else "复测结论: 漏洞已修复/复测通过")
    else:
        lines.append("复测结论: 等待AI判定")
    for index, item in enumerate(results, 1):
        lines.append("")
        lines.append(f"[{index}] {item.get('url', '')}")
        if item.get("error"):
            if item.get("target_unreachable"):
                lines.append(f"    目标不可达: {item.get('error')}（当前未见可利用入口）")
            else:
                lines.append(f"    复测错误: {item.get('error')}")
            continue
        meta = item.get("request_meta") or {}
        if meta:
            if meta.get("status_code") is not None:
                lines.append(f"    响应: HTTP {meta.get('status_code')}，长度 {meta.get('content_length', '-')}, 耗时 {meta.get('elapsed_ms', '-')}ms")
            elif meta.get("error"):
                lines.append(f"    响应错误: {meta.get('error')}")
        vulnerabilities = item.get("vulnerabilities") or []
        if not vulnerabilities:
            lines.append("    未记录额外工具观察")
            if item.get("note"):
                lines.append(f"    说明: {item.get('note')}")
            continue
        for vuln in vulnerabilities:
            detail = vuln.get("detail") or ""
            evidence = vuln.get("evidence")
            lines.append(f"    [{vuln.get('severity', 'info')}] {vuln.get('type', '未知类型')} - {detail}")
            if evidence:
                lines.append(f"        证据: {evidence}")
    return "\n".join(lines)


def _report_value(data: Any, *keys: str, limit: int = 0) -> str:
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = str(value)
        text = text.strip()
        if text:
            return text[:limit] if limit and len(text) > limit else text
    return ""


def _report_dict(data: Any, *keys: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _append_report_block(lines: List[str], label: str, text: Any, max_chars: int = 1600, max_lines: int = 18) -> None:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", value)
    truncated = len(value) > max_chars
    if truncated:
        value = value[:max_chars].rstrip()
    block_lines = value.splitlines() or [value]
    lines.append(f"{label}:")
    for line in block_lines[:max_lines]:
        lines.append(f"  {line[:220]}")
    if truncated or len(block_lines) > max_lines:
        lines.append("  ...(已截断)")


def _format_report_meta(data: Dict[str, Any]) -> str:
    meta = _report_dict(data, "response_meta", "responseMeta", "request_meta", "requestMeta")
    if not meta:
        return ""
    parts: List[str] = []
    status = _report_value(meta, "status_code", "statusCode", "status")
    if status:
        parts.append(f"HTTP {status}")
    final_url = _report_value(meta, "final_url", "finalUrl", "url", limit=220)
    if final_url:
        parts.append(f"final_url={final_url}")
    content_type = _report_value(meta, "content_type", "contentType", "mime_type", "mimeType", limit=120)
    if content_type:
        parts.append(f"content-type={content_type}")
    content_length = _report_value(meta, "content_length", "contentLength", "length", "bytes")
    if content_length:
        parts.append(f"length={content_length}")
    elapsed = _report_value(meta, "elapsed_ms", "elapsedMs", "duration_ms", "durationMs")
    if elapsed:
        parts.append(f"elapsed={elapsed}ms")
    error = _report_value(meta, "error", limit=260)
    if error:
        parts.append(f"error={error}")
    return "，".join(parts)


def _append_report_headers(lines: List[str], headers: Dict[str, Any]) -> None:
    if not isinstance(headers, dict) or not headers:
        return
    lines.append("响应头(脱敏):")
    for index, (key, value) in enumerate(headers.items()):
        if index >= 8:
            lines.append("  ...(已截断)")
            break
        lines.append(f"  {key}: {str(value)[:180]}")


def _format_report_evidence_snapshot(summary: str, result_data: Dict[str, Any]) -> str:
    data = result_data if isinstance(result_data, dict) else {}
    ai_judgement = data.get("ai_judgement") if isinstance(data.get("ai_judgement"), dict) else {}
    final_verdict = _model_verdict_from_result_data(data)
    conclusion = ai_judgement.get("conclusion") or (
        "漏洞未修复/可复现"
        if final_verdict == "reproduced"
        else "漏洞已修复/复测通过"
        if final_verdict == "not_reproduced"
        else "模型未给出判定"
    )
    lines: List[str] = [
        "复测结果与响应证据",
        f"复测结论: {conclusion}",
    ]
    reason = str(ai_judgement.get("reason") or data.get("reason") or "").strip()
    if reason:
        lines.append(f"AI判定理由: {reason[:600]}")
    urls = [str(item).strip() for item in (data.get("urls") or []) if str(item).strip()]
    if urls:
        lines.append("通报目标: " + "；".join(urls[:6]))
    evidence = ai_judgement.get("evidence") if isinstance(ai_judgement.get("evidence"), list) else []
    if evidence:
        lines.append("AI引用证据:")
        for item in evidence[:6]:
            if str(item).strip():
                lines.append(f"  - {str(item)[:260]}")

    lines.append("")
    lines.append("HTTP请求/响应证据")
    results = [item for item in (data.get("retest_results") or []) if isinstance(item, dict)]
    if not results:
        lines.append("未记录结构化 HTTP 响应；以下保留 Agent 复测摘要。")
    for index, item in enumerate(results[:5], 1):
        if len(lines) >= 108:
            lines.append("...(更多证据已截断)")
            break
        url = _report_value(item, "url", limit=240)
        lines.append("")
        lines.append(f"[{index}] 目标: {url or '-'}")
        if item.get("target_unreachable"):
            lines.append(f"目标状态: 不可达/未见可利用入口。{_report_value(item, 'error', limit=300)}")
        elif item.get("error"):
            lines.append(f"执行错误: {_report_value(item, 'error', limit=300)}")
        meta_line = _format_report_meta(item)
        if meta_line:
            lines.append(f"响应信息: {meta_line}")
        request_text = _report_value(item, "request_safe", "requestSafe", "request_raw", "requestRaw", limit=1400)
        _append_report_block(lines, "重放请求包", request_text, max_chars=1400, max_lines=12)
        _append_report_headers(lines, _report_dict(item, "response_headers_safe", "responseHeadersSafe"))
        response_text = _report_value(
            item,
            "response_raw_excerpt",
            "responseRawExcerpt",
            "response_body_preview",
            "responseBodyPreview",
            limit=1800,
        )
        _append_report_block(lines, "响应数据片段", response_text, max_chars=1800, max_lines=18)

        vulnerabilities = [v for v in (item.get("vulnerabilities") or []) if isinstance(v, dict)]
        if vulnerabilities:
            lines.append("工具/探针证据:")
        for vuln_index, vuln in enumerate(vulnerabilities[:4], 1):
            detail = _report_value(vuln, "detail", "evidence", limit=360)
            severity = _report_value(vuln, "severity") or "info"
            vuln_type = _report_value(vuln, "type") or "复测证据"
            lines.append(f"  {vuln_index}. [{severity}] {vuln_type}: {detail or '-'}")
            markers = vuln.get("matched_markers") or vuln.get("matchedMarkers") or []
            if isinstance(markers, list) and markers:
                lines.append("     命中特征: " + "；".join(str(marker) for marker in markers[:8]))
            vuln_meta = _format_report_meta(vuln)
            if vuln_meta and vuln_meta != meta_line:
                lines.append(f"     响应信息: {vuln_meta}")
            vuln_request = _report_value(vuln, "request_safe", "requestSafe", "request_raw", "requestRaw", limit=900)
            if vuln_request and vuln_request != request_text:
                _append_report_block(lines, "     证据请求包", vuln_request, max_chars=900, max_lines=7)
            vuln_response = _report_value(
                vuln,
                "response_raw_excerpt",
                "responseRawExcerpt",
                "response_body_preview",
                "responseBodyPreview",
                limit=1200,
            )
            if vuln_response and vuln_response != response_text:
                _append_report_block(lines, "     证据响应片段", vuln_response, max_chars=1200, max_lines=10)
        if item.get("note"):
            lines.append(f"说明: {_report_value(item, 'note', limit=300)}")

    lines.append("")
    _append_report_block(lines, "复测摘要", summary, max_chars=2600, max_lines=24)
    return "\n".join(lines[:118])


def _payload_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(value)


def _save_retest_screenshot_data(target_dir: Path, screenshot_data_url: str) -> Path:
    text = str(screenshot_data_url or "").strip()
    match = re.match(r"^data:image/(png|jpeg|jpg);base64,(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("复测截图数据格式不正确")

    image_type = match.group(1).lower()
    extension = "jpg" if image_type in {"jpeg", "jpg"} else "png"
    try:
        image_bytes = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:
        raise ValueError("复测截图 base64 解码失败") from exc
    if not image_bytes:
        raise ValueError("复测截图数据为空")

    output_dir = _retest_screenshot_dir(target_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"ui_result_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{extension}"
    with open(output_path, "wb") as screenshot_file:
        screenshot_file.write(image_bytes)
    return output_path


def _save_retest_text_screenshot(target_dir: Path, text: str, title: str = "复测结果") -> Path:
    from PIL import Image, ImageDraw, ImageFont

    output_dir = _retest_screenshot_dir(target_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"agent_result_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    width = 1280
    padding = 36
    line_height = 28
    max_chars = 88

    def load_font(size: int):
        candidates = [
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc",
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simhei.ttf",
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        ]
        for candidate in candidates:
            try:
                if candidate.exists():
                    return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue
        return ImageFont.load_default()

    title_font = load_font(28)
    body_font = load_font(20)
    raw_lines = [str(title or "复测结果").strip(), ""]
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            raw_lines.append("")
            continue
        while len(line) > max_chars:
            raw_lines.append(line[:max_chars])
            line = line[max_chars:]
        raw_lines.append(line)
    raw_lines = raw_lines[:120]
    height = max(360, padding * 2 + 44 + len(raw_lines) * line_height)
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 86), fill="#f2f6ff")
    draw.text((padding, 24), str(title or "复测结果"), fill="#1f2a44", font=title_font)
    y = 104
    for line in raw_lines[2:]:
        draw.text((padding, y), line, fill="#243044", font=body_font)
        y += line_height
    image.save(output_path)
    return output_path


def _retest_screenshot_dir(target_dir: Path) -> Path:
    return target_dir / ".koi_retest_screenshots"


def _cleanup_retest_screenshot_dir(target_dir: Path, logs: List[str]) -> None:
    screenshot_dir = _retest_screenshot_dir(target_dir)
    if not screenshot_dir.exists():
        return

    try:
        resolved_dir = screenshot_dir.resolve()
        resolved_target = target_dir.resolve()
        if resolved_dir.name != ".koi_retest_screenshots" or resolved_dir.parent != resolved_target:
            logs.append(f"跳过异常复测截图目录清理: {resolved_dir}")
            return
        shutil.rmtree(resolved_dir)
        logs.append(f"临时复测截图目录已删除: {resolved_dir}")
    except Exception as exc:
        logs.append(f"临时复测截图目录删除失败: {screenshot_dir} -> {exc}")


def _doc_retest_list_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = Path(_required_text(payload, "target_dir", "请选择通报目录")).expanduser()
    if not target_dir.exists() or not target_dir.is_dir():
        return {"success": False, "message": f"通报目录不存在: {target_dir}", "logs": []}

    try:
        from modules.AI_Testing.retest.word_vulnerability_scanner import WordVulnerabilityScanner
    except Exception as exc:
        return {"success": False, "message": f"导入通报扫描器失败: {exc}", "logs": [traceback.format_exc()]}

    logs: List[str] = []
    scanner = WordVulnerabilityScanner(str(target_dir))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        word_files = scanner.find_word_files()
    logs.extend(_captured_lines(buffer))
    logs.append(f"扫描完成，发现 {len(word_files)} 份通报文档")
    return {
        "success": True,
        "message": f"发现 {len(word_files)} 份通报文档",
        "target_dir": str(target_dir),
        "total": len(word_files),
        "source_files": [str(file_path) for file_path in word_files],
        "logs": logs,
    }


def _retest_trace_event(
    event_type: str,
    title: str,
    content: str = "",
    tone: str = "info",
    tool: Dict[str, Any] | None = None,
    source_file: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "id": f"trace-{uuid.uuid4().hex[:10]}",
        "type": event_type,
        "title": title,
        "content": content,
        "tone": tone,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    if tool:
        event["tool"] = tool
    if source_file:
        event["sourceFile"] = source_file
    if metadata:
        event["metadata"] = metadata
    return event


def _retest_observation_count(result_item: Dict[str, Any]) -> int:
    if not isinstance(result_item, dict):
        return 0
    if result_item.get("observation_count") is not None:
        try:
            return max(0, int(result_item.get("observation_count") or 0))
        except Exception:
            return 0
    return len([item for item in (result_item.get("vulnerabilities") or []) if isinstance(item, dict)])


def _retest_ai_advice_trace(scan_result: Dict[str, Any], source_file: Path) -> Dict[str, Any] | None:
    context = scan_result.get("retest_context") if isinstance(scan_result.get("retest_context"), dict) else {}
    advice = context.get("agent_advice") if isinstance(context, dict) else {}
    if not isinstance(advice, dict) or not advice.get("enabled"):
        return None
    provider = str(advice.get("provider") or "")
    model = str(advice.get("model") or "")
    plan_steps = [str(item) for item in (advice.get("plan_steps") or []) if str(item).strip()]
    recommended = [str(item) for item in (advice.get("recommended_checks") or []) if str(item).strip()]
    warnings = [str(item) for item in (advice.get("warnings") or []) if str(item).strip()]
    lines = [
        f"模型: {provider}{('/' + model) if model else ''}".strip(),
        f"状态: {'已完成通报阅读与复测规划' if advice.get('used') else '规划未完成（已暂停等待继续）'}",
    ]
    if plan_steps:
        lines.append("计划:\n" + "\n".join(f"- {item}" for item in plan_steps[:8]))
    if recommended:
        lines.append("推荐工具: " + "、".join(recommended))
    python_probe = advice.get("python_probe") if isinstance(advice.get("python_probe"), dict) else {}
    if python_probe and python_probe.get("script"):
        lines.append("Python 探针: 已生成受限 HTTP 探针脚本")
        if python_probe.get("reason"):
            lines.append("脚本目的: " + str(python_probe.get("reason")))
    if advice.get("notes"):
        lines.append("说明: " + str(advice.get("notes")))
    if warnings:
        lines.append("提醒:\n" + "\n".join(f"- {item}" for item in warnings[:6]))
    if advice.get("reason") and not advice.get("used"):
        lines.append("原因: " + str(advice.get("reason")))
    if advice.get("error"):
        lines.append("错误: " + str(advice.get("error")))
    return _retest_trace_event(
        "thought_summary",
        "AI 规划摘要",
        "\n".join(line for line in lines if line),
        "ok" if advice.get("used") else "warn",
        source_file=str(source_file),
        metadata={"provider": provider, "model": model, "recommended_checks": recommended, "pythonProbe": bool(python_probe and python_probe.get("script")), "phase": "planning"},
    )


def _run_retest_for_source_file(
    file_path: Path,
    payload: Dict[str, Any],
    logs: List[str],
    event_callback: Callable[[Dict[str, Any]], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    confirm_callback: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
) -> tuple[str, Dict[str, Any], bool, List[Dict[str, Any]]]:
    from modules.AI_Testing.retest.vulnerability_batch_scanner import VulnerabilityRetestScanner
    from modules.AI_Testing.retest.word_vulnerability_scanner import WordVulnerabilityScanner

    trace_events: List[Dict[str, Any]] = []
    round_id = str(payload.get("round_id") or f"file:{file_path.name}")
    turn_id = str(payload.get("turn_id") or "")
    source_file_name = str(payload.get("source_file_name") or file_path.name)

    def emit(event: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(event, dict):
            event.setdefault("sourceFile", str(file_path))
            metadata = event.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                event["metadata"] = metadata
            metadata.setdefault("roundId", round_id)
            if turn_id:
                metadata.setdefault("turnId", turn_id)
            metadata.setdefault("sourceFileName", source_file_name)
            metadata.setdefault("phase", "tool" if str(event.get("type") or "").startswith("tool_") else "status")
            trace_events.append(event)
            if event_callback:
                event_callback(event)
        return event

    def make_model_stream_callback(title: str, phase: str) -> tuple[Callable[[str], None], Callable[[], None]]:
        state = {"buffer": "", "visible": "", "last_emit": 0.0, "last_emit_count": 0, "count": 0}
        stream_key = f"model-output:{round_id}:{phase}"

        def visible_dialogue(raw: str) -> str:
            text = str(raw or "")
            cut_points = []
            for marker in ("```json", "```JSON", "JSON_RESULT:", "\nJSON:", "\n{"):
                index = text.find(marker)
                if index >= 0:
                    cut_points.append(index)
            if text.lstrip().startswith("{"):
                return "Agent 正在生成结构化复测数据，稍后会继续执行工具。"
            if cut_points:
                text = text[:min(cut_points)]
            text = re.sub(r"^\s*AGENT_MESSAGE\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
            return text

        def callback(chunk: str) -> None:
            text = str(chunk or "")
            if not text:
                return
            state["buffer"] = (state["buffer"] + text)[-12000:]
            state["visible"] = visible_dialogue(str(state["buffer"]))
            state["count"] = int(state["count"]) + len(text)
            now = time.time()
            if now - float(state["last_emit"] or 0.0) < 0.25 and int(state["count"]) - int(state["last_emit_count"]) < 120:
                return
            preview = str(state["visible"] or "").strip()
            if not preview:
                return
            state["last_emit"] = now
            state["last_emit_count"] = state["count"]
            emit(_retest_trace_event(
                "thought_summary",
                title,
                preview,
                "info",
                source_file=str(file_path),
                metadata={"phase": phase, "streaming": True, "modelOutput": True, "dialogueOutput": True, "streamKey": stream_key},
            ))

        def flush() -> None:
            if not state["buffer"]:
                return
            final_text = str(state["visible"] or "").strip() or "Agent 已完成本阶段模型输出，正在进入下一步。"
            emit(_retest_trace_event(
                "thought_summary",
                title.replace("对话 /", "对话完成 /"),
                final_text,
                "ok",
                source_file=str(file_path),
                metadata={"phase": phase, "streaming": False, "modelOutput": True, "dialogueOutput": True, "completeModelOutput": True, "streamKey": stream_key},
            ))

        return callback, flush

    scanner = WordVulnerabilityScanner(str(file_path.parent))
    ai_config_for_trace: Dict[str, Any] = {}
    try:
        ai_config_for_trace = _load_retest_ai_config()
    except Exception:
        ai_config_for_trace = {}
    retest_scanner = VulnerabilityRetestScanner(
        timeout=int(payload.get("timeout") or 15),
        max_workers=int(payload.get("max_workers") or 5),
        trace_callback=emit,
        ai_config=ai_config_for_trace,
        stop_check=stop_check,
        confirm_callback=confirm_callback,
    )
    emit(_retest_trace_event("status", "文档解析", f"开始解析通报文档: {file_path.name}", "info", source_file=str(file_path), metadata={"phase": "parse"}))

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        scan_result = scanner.scan_document(file_path)
    logs.extend(_captured_lines(buffer))
    emit(_retest_trace_event(
        "status",
        "文档解析完成",
        "\n".join([
            f"漏洞类型: {'、'.join(scan_result.get('vulnerability_types') or []) or '未识别'}",
            f"URL: {'、'.join(scan_result.get('urls') or []) or '未提取'}",
        ]),
        "ok",
        source_file=str(file_path),
        metadata={"phase": "parse"},
    ))
    ai_provider = str(ai_config_for_trace.get("provider") or "")
    ai_model = str(ai_config_for_trace.get("model") or "")
    ai_enabled = bool(ai_config_for_trace.get("enabled"))
    ai_started = time.time()
    emit(_retest_trace_event(
        "tool_call",
        "AI 规划模型",
        "调用模型分析通报上下文、纠正识别结果并推荐复测工具。" if ai_enabled else "AI 未就绪，本次会话将中断并等待配置后继续。",
        "info" if ai_enabled else "warn",
        tool={
            "toolId": "llm_plan",
            "label": "AI 规划模型",
            "status": "running" if ai_enabled else "blocked",
            "target": file_path.name,
            "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
        },
        source_file=str(file_path),
        metadata={"provider": ai_provider, "model": ai_model, "enabled": ai_enabled, "phase": "planning"},
    ))
    plan_stream_callback, flush_plan_stream = make_model_stream_callback("AI Agent 对话 / 规划", "planning")
    try:
        scan_result = _apply_retest_ai_agent(
            scan_result,
            logs,
            stream_callback=plan_stream_callback,
        )
        flush_plan_stream()
    except RetestAIBlockedError as exc:
        flush_plan_stream()
        blocked_preview = f"blocked_stage: {exc.stage}\nreason: {exc}"
        emit(_retest_trace_event(
            "tool_result",
            "AI 规划模型",
            blocked_preview,
            "error",
            tool={
                "toolId": "llm_plan",
                "label": "AI 规划模型",
                "status": "blocked",
                "target": file_path.name,
                "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
                "resultPreview": blocked_preview,
                "durationMs": int((time.time() - ai_started) * 1000),
                "failureReason": str(exc),
            },
            source_file=str(file_path),
            metadata={"provider": ai_provider, "model": ai_model, "phase": exc.stage, "blockedByAiConfig": True},
        ))
        raise
    ai_trace = _retest_ai_advice_trace(scan_result, file_path)
    ai_advice = (scan_result.get("retest_context") or {}).get("agent_advice") if isinstance(scan_result.get("retest_context"), dict) else {}
    ai_used = bool(isinstance(ai_advice, dict) and ai_advice.get("used"))
    ai_error = str(ai_advice.get("error") or "") if isinstance(ai_advice, dict) else ""
    ai_reason = str(ai_advice.get("reason") or ai_advice.get("notes") or "") if isinstance(ai_advice, dict) else ""
    ai_recommended = ai_advice.get("recommended_checks") if isinstance(ai_advice, dict) else []
    ai_result_preview = "\n".join([
        f"used: {ai_used}",
        f"recommended: {', '.join(str(item) for item in (ai_recommended or [])[:12]) or '-'}",
        f"reason: {ai_error or ai_reason or '-'}",
    ])
    emit(_retest_trace_event(
        "tool_result",
        "AI 规划模型",
        ai_result_preview,
        "ok" if ai_used else ("error" if ai_error else "warn"),
        tool={
            "toolId": "llm_plan",
            "label": "AI 规划模型",
            "status": "completed" if ai_used else ("failed" if ai_error else "skipped"),
            "target": file_path.name,
            "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
            "resultPreview": ai_result_preview,
            "durationMs": int((time.time() - ai_started) * 1000),
        },
        source_file=str(file_path),
        metadata={"provider": ai_provider, "model": ai_model, "used": ai_used, "phase": "planning", "evidenceLevel": "ai_used" if ai_used else "ai_required"},
    ))
    if ai_trace:
        emit(ai_trace)

    vuln_types = scan_result.get("vulnerability_types") or []
    retest_context = scan_result.get("retest_context") or {}
    url_candidates = scan_result.get("urls") or retest_context.get("target_urls") or []
    valid_urls = [url for url in url_candidates if _valid_http_target(url)]
    context_supported = retest_scanner.context_has_retestable_signals(retest_context)
    scan_result["context_supported"] = context_supported
    sanitized_scan_result = _sanitize_retest_scan_result(scan_result)

    if not valid_urls:
        reason_parts = []
        if not vuln_types:
            reason_parts.append("未识别到漏洞类型")
        reason_parts.append("未提取到可用URL")
        result_data: Dict[str, Any] = {
            "file": str(file_path),
            "urls": valid_urls,
            "retest_results": [],
            "risk_count": 0,
            "manual_count": 0,
            "failed_count": 0,
            "scan_result": sanitized_scan_result,
            "manual_test_required": False,
            "reason": "；".join(reason_parts) + "；未见可复现证据",
            "context_supported": context_supported,
        }
        logs.append(f"{file_path.name} 未定位到可复测目标，按未见复现证据处理: {result_data['reason']}")
        emit(_retest_trace_event("status", "未见可复测目标", result_data["reason"], "ok", source_file=str(file_path), metadata={"phase": "result", "evidenceLevel": "empty"}))
    else:
        retest_results = []
        try:
            for url in valid_urls:
                result = retest_scanner.scan_url_for_context(url, vuln_types, retest_context)
                retest_results.append(result)
        except Exception as exc:
            message = str(exc)
            if "模型响应超时/网络超时" in message or "HTTP 429" in message or "AI Agent" in message or "LLM" in message:
                raise RetestAIBlockedError(f"AI Agent 执行决策阶段暂停: {message}", "execution") from exc
            raise
        observation_count = sum(_retest_observation_count(item) for item in retest_results)
        logs.append(f"{file_path.name} 工具观察完成，观察记录 {observation_count} 条；最终结论由 AI 判定")
        emit(_retest_trace_event(
            "status",
            "工具观察完成",
            f"工具记录到 {observation_count} 条观察，正在交由 AI 根据完整请求/响应证据判定。",
            "info" if observation_count else "ok",
            source_file=str(file_path),
            metadata={"observation_count": observation_count, "phase": "result", "evidenceLevel": "observation" if observation_count else "empty"},
        ))
        all_targets_unreachable = bool(retest_results) and all(
            bool(item.get("target_unreachable") or (isinstance(item.get("request_meta"), dict) and item.get("request_meta", {}).get("error")))
            for item in retest_results
            if isinstance(item, dict)
        )
        result_data = {
            "file": str(file_path),
            "urls": valid_urls,
            "retest_results": retest_results,
            "observation_count": observation_count,
            "risk_count": 0,
            "manual_count": 0,
            "failed_count": sum(int(item.get("failed_count") or 0) for item in retest_results if isinstance(item, dict)),
            "scan_result": sanitized_scan_result,
            "manual_test_required": False,
            "target_unreachable": all_targets_unreachable,
            "reason": "",
            "context_supported": context_supported,
        }

    judge_started = time.time()
    emit(_retest_trace_event(
        "tool_call",
        "AI 结论判定",
        "调用模型读取工具输出并给出最终复测结论。",
        "info",
        tool={
            "toolId": "llm_judge",
            "label": "AI 结论判定",
            "status": "running",
            "target": file_path.name,
            "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
        },
        source_file=str(file_path),
        metadata={"provider": ai_provider, "model": ai_model, "phase": "judgement"},
    ))
    judge_stream_callback, flush_judge_stream = make_model_stream_callback("AI Agent 对话 / 判定", "judgement")
    try:
        result_data = _apply_retest_ai_judgement(
            scan_result,
            result_data,
            logs,
            stream_callback=judge_stream_callback,
        )
        flush_judge_stream()
    except RetestAIBlockedError as exc:
        flush_judge_stream()
        blocked_preview = f"blocked_stage: {exc.stage}\nreason: {exc}"
        emit(_retest_trace_event(
            "tool_result",
            "AI 结论判定",
            blocked_preview,
            "error",
            tool={
                "toolId": "llm_judge",
                "label": "AI 结论判定",
                "status": "blocked",
                "target": file_path.name,
                "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
                "resultPreview": blocked_preview,
                "durationMs": int((time.time() - judge_started) * 1000),
                "failureReason": str(exc),
            },
            source_file=str(file_path),
            metadata={"provider": ai_provider, "model": ai_model, "phase": exc.stage, "blockedByAiConfig": True},
        ))
        raise
    ai_judgement = result_data.get("ai_judgement") if isinstance(result_data.get("ai_judgement"), dict) else {}
    model_verdict = _model_verdict_from_result_data(result_data)
    reproduced = model_verdict == "reproduced"
    trace_tone = "warn" if reproduced else ("ok" if model_verdict == "not_reproduced" else "error")
    fix_status = "risk" if reproduced else ("clean" if model_verdict == "not_reproduced" else "unknown")
    evidence_level = "confirmed" if reproduced else ("not_reproduced" if model_verdict == "not_reproduced" else "unknown")
    judgement_preview = "\n".join([
        f"verdict: {model_verdict or '-'}",
        f"conclusion: {ai_judgement.get('conclusion') or '-'}",
        f"reason: {ai_judgement.get('reason') or result_data.get('reason') or '-'}",
    ])
    emit(_retest_trace_event(
        "tool_result",
        "AI 结论判定",
        judgement_preview,
        trace_tone,
        tool={
            "toolId": "llm_judge",
            "label": "AI 结论判定",
            "status": "completed",
            "target": file_path.name,
            "argsPreview": f"provider: {ai_provider or '-'}\nmodel: {ai_model or '-'}",
            "resultPreview": judgement_preview,
            "durationMs": int((time.time() - judge_started) * 1000),
        },
        source_file=str(file_path),
        metadata={
            "provider": ai_provider,
            "model": ai_model,
            "phase": "judgement",
            "evidenceLevel": evidence_level,
            "fixStatus": fix_status,
        },
    ))
    judgement_lines = [
        f"结论: {ai_judgement.get('conclusion') or ('漏洞未修复/可复现' if reproduced else '漏洞已修复/复测通过' if model_verdict == 'not_reproduced' else '模型未给出判定')}",
        f"理由: {ai_judgement.get('reason') or result_data.get('reason') or 'AI 未提供额外理由'}",
    ]
    evidence = ai_judgement.get("evidence") if isinstance(ai_judgement.get("evidence"), list) else []
    if evidence:
        judgement_lines.append("证据:\n" + "\n".join(f"- {item}" for item in evidence[:8]))
    emit(_retest_trace_event(
        "thought_summary",
        "AI 判定摘要",
        "\n".join(judgement_lines),
        trace_tone,
        source_file=str(file_path),
        metadata={
            "provider": ai_provider,
            "model": ai_model,
            "phase": "judgement",
            "fixStatus": fix_status,
            "evidenceLevel": evidence_level,
        },
    ))

    summary = _format_retest_summary(file_path, result_data)
    return summary, result_data, False, trace_events


def _doc_retest_run_one(payload: Dict[str, Any], progress: RetestTaskProgress | None = None) -> Dict[str, Any]:
    source_file = Path(_required_text(payload, "source_file", "请选择通报文件")).expanduser()
    if not source_file.exists() or source_file.suffix.lower() not in WORD_SUFFIXES:
        return {"success": False, "message": f"通报文件不存在或不是 Word 文档: {source_file}", "logs": []}

    logs: List[str] = ProgressLogList(progress) if progress else []
    logs.append(f"开始复测: {source_file.name}")
    try:
        if progress:
            progress.set(8, f"开始复测: {source_file.name}")
        summary, result_data, _manual_required, trace_events = _run_retest_for_source_file(
            source_file,
            payload,
            logs,
            event_callback=progress.event if progress else None,
            stop_check=progress.should_stop if progress else None,
            confirm_callback=(lambda req: _retest_request_confirmation(progress, req)) if progress else None,
        )
        if progress:
            progress.set(92, f"复测完成: {source_file.name}")
    except RetestAIBlockedError as exc:
        blocked_title = _ai_blocked_title(exc)
        if progress:
            progress.set(progress.snapshot().get("progress", 0), str(exc))
            progress.event(_retest_trace_event(
                "status",
                blocked_title,
                str(exc),
                "warn",
                source_file=str(source_file),
                metadata={"phase": exc.stage, "blockedByAiConfig": True},
            ))
            snapshot = progress.snapshot()
            trace_events = snapshot.get("trace_events") or []
        else:
            trace_events = [_retest_trace_event(
                "status",
                blocked_title,
                str(exc),
                "warn",
                source_file=str(source_file),
                metadata={"phase": exc.stage, "blockedByAiConfig": True},
            )]
        logs.append(str(exc))
        return _ai_blocked_payload(exc, str(source_file), logs, trace_events)
    except Exception as exc:
        logs.append(traceback.format_exc())
        return {"success": False, "message": f"复测失败: {exc}", "source_file": str(source_file), "logs": logs}

    return {
        "success": True,
        "message": f"复测完成: {source_file.name}",
        "source_file": str(source_file),
        "manual_test_required": False,
        "summary": summary,
        "result_data": result_data,
        "trace_events": trace_events,
        "logs": logs,
    }


def _retest_task_worker(task_id: str, payload: Dict[str, Any]) -> None:
    with _RETEST_TASK_LOCK:
        task = _RETEST_TASKS.get(task_id)
    if not task:
        return

    progress = task["progress"]
    try:
        result = _doc_retest_run_one(payload, progress=progress)
        with _RETEST_TASK_LOCK:
            if task.get("stopped"):
                task.update({
                    "running": False,
                    "done": True,
                    "success": False,
                    "message": "复测已停止，可继续",
                    "result": task.get("result") or {
                        "success": False,
                        "stopped": True,
                        "message": "复测已停止，可继续",
                        "logs": progress.snapshot().get("logs", []),
                        "trace_events": progress.snapshot().get("trace_events", []),
                        "source_file": str(payload.get("source_file") or ""),
                    },
                    "finished_at": time.time(),
                })
                return
            task.update({
                "running": False,
                "done": True,
                "success": bool(result.get("success")),
                "message": result.get("message") or ("复测完成" if result.get("success") else "复测失败"),
                "result": result,
                "finished_at": time.time(),
            })
        progress.set(100 if result.get("success") else progress.snapshot().get("progress", 0), result.get("message") or "")
    except Exception as exc:
        progress.log(_format_exception(exc))
        with _RETEST_TASK_LOCK:
            stopped = bool(task.get("stopped"))
        progress.set(progress.snapshot().get("progress", 0) if stopped else 0, "复测已停止，可继续" if stopped else f"复测失败: {exc}")
        result = {
            "success": False,
            "stopped": stopped,
            "message": "复测已停止，可继续" if stopped else f"复测失败: {exc}",
            "logs": progress.snapshot().get("logs", []),
            "trace_events": progress.snapshot().get("trace_events", []),
            "source_file": str(payload.get("source_file") or ""),
        }
        with _RETEST_TASK_LOCK:
            task.update({
                "running": False,
                "done": True,
                "success": False,
                "message": result["message"],
                "result": result,
                "error": "" if stopped else str(exc),
                "finished_at": time.time(),
            })


def _doc_retest_event_stream_info(payload: Dict[str, Any]) -> Dict[str, Any]:
    from modules.backend_api.retest_event_stream import ensure_retest_event_stream

    return ensure_retest_event_stream()


def _doc_retest_run_one_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_file = Path(_required_text(payload, "source_file", "请选择通报文件")).expanduser()
    if not source_file.exists() or source_file.suffix.lower() not in WORD_SUFFIXES:
        return {"success": False, "message": f"通报文件不存在或不是 Word 文档: {source_file}", "logs": [], "trace_events": []}

    try:
        _ensure_retest_ai_ready("config")
    except RetestAIBlockedError as exc:
        blocked_title = _ai_blocked_title(exc)
        logs = [str(exc)]
        trace_events = [_retest_trace_event(
            "status",
            blocked_title,
            str(exc),
            "warn",
            source_file=str(source_file),
            metadata={
                "roundId": str(payload.get("round_id") or f"file:{source_file.name}"),
                "sourceFileName": str(payload.get("source_file_name") or source_file.name),
                "phase": "config",
                "blockedByAiConfig": True,
            },
        )]
        return _ai_blocked_payload(exc, str(source_file), logs, trace_events)

    task_id = uuid.uuid4().hex
    progress = RetestTaskProgress(total=1)
    progress.session_id = str(payload.get("session_id") or "")
    progress.task_id = task_id
    progress.set(1, f"任务已创建: {source_file.name}")
    progress.event(_retest_trace_event(
        "status",
        "复测任务启动",
        f"后台任务已创建，准备复测: {source_file.name}",
        "info",
        source_file=str(source_file),
        metadata={"roundId": str(payload.get("round_id") or f"file:{source_file.name}"), "sourceFileName": str(payload.get("source_file_name") or source_file.name), "phase": "start"},
    ))
    task = {
        "task_id": task_id,
        "running": True,
        "done": False,
        "success": False,
        "message": f"任务已创建: {source_file.name}",
        "progress": progress,
        "result": None,
        "created_at": time.time(),
        "finished_at": None,
        "error": None,
        "stopped": False,
        "source_file": str(source_file),
    }
    with _RETEST_TASK_LOCK:
        _RETEST_TASKS[task_id] = task

    worker = threading.Thread(target=_retest_task_worker, args=(task_id, dict(payload)), daemon=True)
    task["thread"] = worker
    worker.start()
    snapshot = progress.snapshot()
    return {
        "success": True,
        "task_id": task_id,
        "running": True,
        "done": False,
        "message": snapshot["message"],
        "progress": snapshot["progress"],
        "logs": snapshot["logs"],
        "trace_events": snapshot["trace_events"],
        "source_file": str(source_file),
    }


def _doc_retest_run_one_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_id = _required_text(payload, "task_id", "缺少任务ID")
    with _RETEST_TASK_LOCK:
        task = _RETEST_TASKS.get(task_id)
        if not task:
            return {"success": False, "task_id": task_id, "done": True, "running": False, "message": "复测任务不存在或已过期", "logs": [], "trace_events": []}
        progress = task["progress"]
        snapshot = progress.snapshot()
        result = task.get("result") or {}
        done = bool(task.get("done"))
        running = bool(task.get("running"))
        success = bool(task.get("success")) if done else True
        message = str(task.get("message") or snapshot.get("message") or "")
        stopped = bool(task.get("stopped") or snapshot.get("stop_requested") or result.get("stopped"))

    response = {
        "success": success,
        "task_id": task_id,
        "running": running,
        "done": done,
        "stopped": stopped,
        "message": message,
        "progress": 100 if done and success else snapshot["progress"],
        "logs": snapshot["logs"],
        "trace_events": snapshot["trace_events"],
        "source_file": result.get("source_file"),
        "manual_test_required": result.get("manual_test_required"),
        "blocked_by_ai_config": result.get("blocked_by_ai_config"),
        "blocked_stage": result.get("blocked_stage"),
        "summary": result.get("summary"),
        "result_data": result.get("result_data"),
        "error": task.get("error"),
    }
    if done:
        response["result"] = result
    return response


def _doc_retest_confirmation_respond(payload: Dict[str, Any]) -> Dict[str, Any]:
    confirmation_id = _required_text(payload, "confirmation_id", "缺少确认ID")
    decision = str(payload.get("decision") or "").strip().lower()
    note = str(payload.get("note") or "")
    if decision not in {"approve", "reject", "yes", "no", "allow", "deny"}:
        return {"success": False, "message": "decision 必须是 approve 或 reject", "confirmation_id": confirmation_id}
    ok = _resolve_confirmation(confirmation_id, decision, note)
    if not ok:
        return {"success": False, "message": "确认请求不存在或已超时", "confirmation_id": confirmation_id}
    return {"success": True, "confirmation_id": confirmation_id, "decision": decision}


def _doc_retest_run_one_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_id = _required_text(payload, "task_id", "缺少任务ID")
    with _RETEST_TASK_LOCK:
        task = _RETEST_TASKS.get(task_id)
        if not task:
            return {"success": False, "task_id": task_id, "stopped": True, "done": True, "running": False, "message": "复测任务不存在或已过期", "logs": [], "trace_events": []}
        progress = task["progress"]
        progress.request_stop("复测已停止，可继续")
        progress.event(_retest_trace_event(
            "status",
            "复测已停止",
            "当前单份通报任务已收到停止指令，已保留会话断点。",
            "warn",
            source_file=str(task.get("source_file") or ""),
            metadata={"phase": "stop", "stopped": True},
        ))
        task.update({
            "running": False,
            "done": True,
            "success": False,
            "stopped": True,
            "message": "复测已停止，可继续",
            "result": {
                "success": False,
                "stopped": True,
                "message": "复测已停止，可继续",
                "logs": progress.snapshot().get("logs", []),
                "trace_events": progress.snapshot().get("trace_events", []),
                "source_file": str(task.get("source_file") or ""),
            },
            "finished_at": time.time(),
            "error": None,
        })
        snapshot = progress.snapshot()
    return {
        "success": True,
        "task_id": task_id,
        "stopped": True,
        "done": True,
        "running": False,
        "message": "复测已停止，可继续",
        "progress": snapshot["progress"],
        "logs": snapshot["logs"],
        "trace_events": snapshot["trace_events"],
    }


def _completion_item_from_result(source_file: str, run_result: Dict[str, Any] | None = None, report_paths: List[str] | None = None, failure_reason: str = "") -> Dict[str, Any]:
    result_data = run_result.get("result_data") if isinstance(run_result, dict) else {}
    if not isinstance(result_data, dict):
        result_data = {}
    ai_judgement = result_data.get("ai_judgement") if isinstance(result_data.get("ai_judgement"), dict) else {}
    final_verdict = _model_verdict_from_result_data(result_data)
    reproduced = final_verdict == "reproduced"
    failed = bool(failure_reason or (isinstance(run_result, dict) and not run_result.get("success", True)))
    missing_model_verdict = not failed and final_verdict not in {"reproduced", "not_reproduced"}
    status = "failed" if failed or missing_model_verdict else ("risk" if reproduced else "clean")
    # 目标不可达属于"未能验证"，不能展示成"已修复/复测通过"。
    unreachable = bool(ai_judgement.get("unverified_unreachable") or result_data.get("target_unreachable"))
    if status == "risk":
        status_label = "漏洞未修复/可复现"
    elif status == "failed":
        status_label = "模型未给出判定" if missing_model_verdict else "执行失败"
    elif unreachable:
        status_label = "未复现：目标不可达，未能验证（建议复查）"
    else:
        status_label = "漏洞已修复/复测通过"
    tools: List[str] = []
    evidence_lines: List[str] = []
    for item in result_data.get("retest_results") or []:
        if not isinstance(item, dict):
            continue
        for tool in item.get("context_checks") or []:
            if str(tool).strip():
                tools.append(str(tool))
        for vuln in item.get("vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            detail = str(vuln.get("detail") or vuln.get("evidence") or "").strip()
            if detail:
                evidence_lines.append(detail)
    for item in ai_judgement.get("evidence") or []:
        if str(item).strip():
            evidence_lines.append(str(item))
    reason = failure_reason or str(ai_judgement.get("reason") or result_data.get("reason") or "")
    if missing_model_verdict and not reason:
        reason = "模型未给出 reproduced/not_reproduced 判定，未由工具结果兜底。"
    return {
        "sourceFile": source_file,
        "sourceFileName": Path(source_file).name,
        "status": status,
        "statusLabel": status_label,
        "evidence": "\n".join(evidence_lines[:6]) or reason or "暂无证据摘要",
        "reason": reason,
        "reportPaths": list(report_paths or []),
        "tools": list(dict.fromkeys(tools))[:20],
        "riskCount": 1 if reproduced else 0,
        "manualCount": 0,
        "failedCount": 1 if failed or missing_model_verdict else int(result_data.get("failed_count") or 0),
    }


def _format_agent_result_message(file_path: str, result: Dict[str, Any], completion_item: Dict[str, Any], report_paths: List[str] | None = None) -> str:
    result_data = result.get("result_data") if isinstance(result.get("result_data"), dict) else {}
    ai_judgement = result_data.get("ai_judgement") if isinstance(result_data.get("ai_judgement"), dict) else {}
    final_verdict = _model_verdict_from_result_data(result_data)
    conclusion = str(ai_judgement.get("conclusion") or completion_item.get("statusLabel") or "").strip()
    urls = [str(item) for item in (result_data.get("urls") or []) if str(item).strip()]
    lines = [
        f"文件: {Path(file_path).name}",
        f"复测结果: {completion_item.get('statusLabel') or '模型未给出判定'}",
        f"模型判定: {final_verdict or '模型未给出判定'}{(' / ' + conclusion) if conclusion else ''}",
    ]
    reason = str(ai_judgement.get("reason") or completion_item.get("reason") or result_data.get("reason") or "").strip()
    if reason:
        lines.append(f"理由: {reason}")
    if urls:
        lines.append("目标: " + "；".join(urls[:4]))
    tools = completion_item.get("tools") or []
    if tools:
        lines.append("工具: " + ", ".join(str(item) for item in tools[:10]))
    evidence = str(completion_item.get("evidence") or "").strip()
    if evidence:
        lines.append("关键证据:\n" + "\n".join(evidence.splitlines()[:6]))
    reports = list(report_paths or completion_item.get("reportPaths") or [])
    if reports:
        lines.append("报告:\n" + "\n".join(f"{index + 1}. {path}" for index, path in enumerate(reports)))
    return "\n".join(lines)


def _format_agent_completion_overview(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "复测结论总览\n暂无文件级结论。"
    labels = {
        "risk": "漏洞未修复/可复现",
        "clean": "漏洞已修复/复测通过",
        "failed": "执行失败",
    }
    lines = ["复测结论总览"]
    for status in ("risk", "clean", "failed"):
        group = [item for item in items if item.get("status") == status]
        lines.append("")
        lines.append(f"【{labels[status]}】{len(group)} 项")
        if not group:
            lines.append("- 无")
            continue
        for item in group:
            lines.append(f"- {item.get('sourceFileName') or Path(str(item.get('sourceFile') or '')).name}")
            evidence = str(item.get("evidence") or "").replace("\n", " / ")
            if evidence:
                lines.append(f"  证据: {evidence[:500]}")
            reason = str(item.get("reason") or "")
            if reason:
                lines.append(f"  原因: {reason[:500]}")
            reports = item.get("reportPaths") or []
            if reports:
                lines.append("  报告: " + "；".join(str(path) for path in reports))
    return "\n".join(lines)


def _format_report_artifact_content(message: str, reports: List[str]) -> str:
    lines = [str(message or ("报告生成完成" if reports else "未生成报告")).strip()]
    clean_reports = [str(path) for path in reports if str(path).strip()]
    if clean_reports:
        lines.append("报告路径:")
        lines.extend(f"{index + 1}. {path}" for index, path in enumerate(clean_reports))
    return "\n".join(line for line in lines if line)


def _existing_report_path(output_path: Any) -> str:
    if not output_path:
        return ""
    path = Path(str(output_path)).expanduser()
    if path.exists() and path.is_file():
        return str(path)
    return ""


def _generate_retest_reports_from_agent_summary(target_dir: Path, source_files: List[str], summary_text: str, logs: List[str]) -> Dict[str, Any]:
    template_path = _retest_template_path()
    if not template_path.exists():
        return {"success": False, "message": f"未找到复测模板文件: {template_path}", "reports": [], "failures": [], "logs": logs}
    screenshot_path: Path | None = None
    reports: List[str] = []
    failures: List[tuple[Path, str]] = []
    try:
        screenshot_path = _save_retest_text_screenshot(target_dir, summary_text, "AI 复测结果")
        logs.append(f"AI Agent 复测结果证据图已生成: {screenshot_path}")
        from modules.AI_Testing.retest.retest_report_generator import RetestReportGenerator

        for source_file in source_files:
            file_path = Path(source_file).expanduser()
            if not file_path.exists() or file_path.suffix.lower() not in WORD_SUFFIXES:
                failures.append((file_path, "通报文件不存在或不是 Word 文档"))
                continue
            generator = RetestReportGenerator(
                target_dir=str(file_path.parent),
                template_path=str(template_path),
                output_dir=None,
                screenshot_path=str(screenshot_path),
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                generator_scan = generator.scan_document(file_path)
                output_path = generator.generate_report(generator_scan)
            logs.extend(_captured_lines(buffer))
            report_path = _existing_report_path(output_path)
            if report_path:
                reports.append(report_path)
                logs.append(f"报告已生成: {report_path}")
            else:
                failures.append((file_path, f"报告生成失败或文件未落盘: {output_path or '无输出路径'}"))
    except Exception as exc:
        logs.append(traceback.format_exc())
        return {"success": False, "message": f"报告生成失败: {exc}", "reports": reports, "failures": _failure_dicts(failures), "logs": logs}
    finally:
        _cleanup_retest_screenshot_dir(target_dir, logs)
    success = bool(reports) and not failures
    return {
        "success": success,
        "message": (
            f"报告生成完成: {len(reports)} 份，失败 {len(failures)} 份"
            if success
            else f"报告未生成或生成失败: 成功 {len(reports)} 份，失败 {len(failures)} 份"
        ),
        "reports": reports,
        "failures": _failure_dicts(failures),
        "logs": logs,
    }


class RetestAgentRunner:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.lock = threading.RLock()
        self.target_dir = ""
        self.source_files: List[str] = []
        self.next_index = 0
        self.summaries: List[str] = []
        self.reports: List[str] = []
        self.report_evidence_summaries: Dict[str, str] = {}
        self.completion_items: List[Dict[str, Any]] = []
        self.logs: List[str] = []
        self.latest_result_data: Dict[str, Any] | None = None
        self.generate_reports = False
        self.running = False
        self.blocked = False
        self.blocked_reason = ""
        self.blocked_stage = ""
        self.blocked_title = ""
        self.stopped = False
        self.thread: threading.Thread | None = None
        self.pending_messages: List[str] = []
        # 会话级 ReAct 完整消息历史（不含 system；含 user/assistant/tool 及 tool_calls 结构），
        # 跨轮持久化，让对话框记得"上一轮发过什么请求、拿到什么响应、调过什么工具"。
        self.conversation: List[Dict[str, Any]] = []
        self.turn_counter = 0
        self.current_turn_id = ""
        self.created_at = time.time()
        self.updated_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "success": True,
                "session_id": self.session_id,
                "target_dir": self.target_dir,
                "source_files": list(self.source_files),
                "next_index": self.next_index,
                "running": self.running,
                "blocked": self.blocked,
                "blocked_reason": self.blocked_reason,
                "blocked_stage": self.blocked_stage,
                "blocked_title": self.blocked_title,
                "generate_reports": self.generate_reports,
                "summaries": list(self.summaries),
                "reports": list(self.reports),
                "completion_items": list(self.completion_items),
                "logs": list(self.logs),
                "latest_result_data": self.latest_result_data,
                "progress": self._progress_locked(),
                "status": self._status_locked(),
            }

    def _progress_locked(self) -> int:
        total = max(1, len(self.source_files))
        if not self.source_files:
            return 100 if self.completion_items else 0
        return max(0, min(100, int(round(self.next_index / total * 100))))

    def _status_locked(self) -> str:
        if self.running:
            return "Agent 正在执行..."
        if self.blocked:
            return self.blocked_title or "AI 测试暂停"
        if self.source_files and self.next_index >= len(self.source_files):
            return "复测完成"
        if self.completion_items and not self.source_files:
            return "复测完成"
        return "等待 Agent 指令"

    def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = str(payload.get("message") or "一键复测并生成报告").strip()
        with self.lock:
            target_dir = str(payload.get("target_dir") or self.target_dir or "").strip()
            if target_dir:
                self.target_dir = target_dir
            self.generate_reports = _payload_bool(payload.get("generate_reports"), self.generate_reports or _message_requests_report(message))
            self.blocked = False
            self.blocked_reason = ""
            self.blocked_stage = ""
            self.blocked_title = ""
        return self._launch(message, reset_queue=not bool(self.source_files))

    def message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        if not message:
            return {"success": False, "message": "请输入 Agent 指令", **self.snapshot()}
        target_dir = str(payload.get("target_dir") or "").strip()
        with self.lock:
            if target_dir:
                self.target_dir = target_dir
            if self.running:
                self.pending_messages.append(message)
                self._publish("chat", "Agent", "我收到你的新指令了，当前工具执行结束后会继续处理。", "info", metadata={"role": "agent", "turnId": self.current_turn_id})
                return {"success": True, "message": "Agent 正在运行，已记录指令。", **self.snapshot()}
        return self._launch(message, reset_queue=_message_requests_rerun(message))

    def stop(self) -> Dict[str, Any]:
        with self.lock:
            self.stopped = True
            self.running = False
            self.blocked = False
        self._publish("status", "Agent 已停止", "当前会话已收到停止指令。", "warn", metadata={"sessionPatch": self._session_patch()})
        return {"success": True, "message": "Agent 已停止", **self.snapshot()}

    def _launch(self, message: str, reset_queue: bool = False) -> Dict[str, Any]:
        with self.lock:
            if self.running:
                return {"success": True, "message": "Agent 已在运行中", **self.snapshot()}
            self.running = True
            self.stopped = False
            self.blocked = False
            self.blocked_reason = ""
            self.blocked_stage = ""
            self.blocked_title = ""
            self.updated_at = time.time()
            self.turn_counter += 1
            turn_id = f"agent:{self.session_id}:turn:{self.turn_counter}:{uuid.uuid4().hex[:6]}"
            self.current_turn_id = turn_id
            if reset_queue:
                self.next_index = 0
                self.summaries = []
                self.reports = []
                self.report_evidence_summaries = {}
                self.completion_items = []
                self.latest_result_data = None
            thread = threading.Thread(target=self._worker, args=(message, reset_queue, turn_id), name=f"koi-retest-agent-{self.session_id[:8]}", daemon=True)
            self.thread = thread
            thread.start()
        return {"success": True, "message": "Agent 已开始执行", **self.snapshot()}

    def _new_turn_id_locked(self) -> str:
        self.turn_counter += 1
        self.current_turn_id = f"agent:{self.session_id}:turn:{self.turn_counter}:{uuid.uuid4().hex[:6]}"
        return self.current_turn_id

    def _worker(self, message: str, reset_queue: bool, turn_id: str) -> None:
        try:
            self._publish("chat", "Agent", f"我会在当前会话处理你的指令：{message}", "info", metadata={"role": "agent", "turnId": turn_id, "sessionPatch": self._session_patch({"isRunning": True, "resumeState": None})})
            self._handle_instruction(message, reset_queue, turn_id)
            while True:
                with self.lock:
                    if not self.pending_messages or self.stopped or self.blocked:
                        break
                    next_message = self.pending_messages.pop(0)
                    turn_id = self._new_turn_id_locked()
                self._publish("chat", "Agent", f"继续处理排队指令：{next_message}", "info", metadata={"role": "agent", "turnId": turn_id, "sessionPatch": self._session_patch({"isRunning": True, "resumeState": None})})
                self._handle_instruction(next_message, _message_requests_rerun(next_message), turn_id)
        except RetestAIBlockedError as exc:
            self._block(exc, turn_id)
        except Exception as exc:
            self.logs.append(traceback.format_exc())
            self._publish("error", "Agent 执行失败", str(exc), "error", metadata={"turnId": turn_id, "sessionPatch": self._session_patch({"isRunning": False, "status": f"Agent 执行失败: {exc}", "resumeState": None})})
        finally:
            with self.lock:
                self.running = False
                self.updated_at = time.time()
                final_blocked = self.blocked
            self._publish("status", "Agent 空闲", self._status_locked(), "info", metadata={"turnId": turn_id, "sessionPatch": self._session_patch({"isRunning": False, "resumeState": self._resume_state_locked(True) if final_blocked else None})})

    def _handle_instruction(self, message: str, reset_queue: bool, turn_id: str) -> None:
        """会话级 ReAct 入口：用户消息先经过模型理解，由模型自主调用会话工具。

        旧的关键词路由（if "报告"/"重测"/"工具" in message）已被完整 ReAct 循环取代；
        模型通过 list_reports / retest_report / retest_all_reports / retest_url /
        generate_reports / install_tools / tool_status 等工具完成动作。
        """
        ai_config = _ensure_retest_ai_ready("config")
        # 用户明确表达"重测/再跑一遍"时，先清空既有队列进度，让模型可以从头复测
        if reset_queue:
            with self.lock:
                self.next_index = 0
                self.summaries = []
                self.reports = []
                self.report_evidence_summaries = {}
                self.completion_items = []
                self.latest_result_data = None
                self.blocked = False
        from modules.AI_Testing.retest.retest_session_agent import RetestSessionAgent

        with self.lock:
            prior_messages = list(self.conversation)

        agent = RetestSessionAgent(self, ai_config)
        _reply, persisted_messages = agent.run_turn(message, turn_id, prior_messages=prior_messages)

        # 回存本轮结束后的完整消息历史（不含 system），供下一轮继续对话。
        with self.lock:
            self.conversation = persisted_messages

    # ============================ 会话级 ReAct 工具适配层 ============================
    # 下列 tool_* 方法是 RetestSessionAgent 的副作用出口：模型决定调用哪个工具，
    # 这里负责真正执行（跑流水线 / 改会话状态 / 推 WebSocket 事件），并返回一段
    # 文本结果回灌给模型。所有状态变更仍在 self.lock 内完成。

    def tool_session_state(self) -> Dict[str, Any]:
        with self.lock:
            completed = [
                str(item.get("sourceFileName") or Path(str(item.get("sourceFile") or "")).name)
                for item in self.completion_items
                if item.get("sourceFile")
            ]
            return {
                "target_dir": self.target_dir,
                "has_target_dir": bool(self.target_dir),
                "source_files": [Path(item).name for item in self.source_files],
                "total_reports": len(self.source_files),
                "next_index": self.next_index,
                "completed_reports": completed,
                "completed_count": len(self.completion_items),
                "generate_reports_default": self.generate_reports,
            }

    def _ensure_source_files_loaded(self, turn_id: str) -> None:
        with self.lock:
            loaded = bool(self.source_files)
        if not loaded:
            self._load_source_files(turn_id)

    def tool_list_reports(self, turn_id: str) -> str:
        with self.lock:
            if not self.target_dir:
                return "当前会话还没有通报目录。请用户从一键复测入口选择目录，或在对话里提供 target_dir，再列通报。"
        self._ensure_source_files_loaded(turn_id)
        with self.lock:
            files = list(self.source_files)
            next_index = self.next_index
        if not files:
            return "通报目录下没有发现可复测的通报文档（Word 报告）。"
        lines = [f"通报目录: {self.target_dir}", f"共 {len(files)} 份通报，断点在第 {next_index + 1} 份："]
        for idx, item in enumerate(files, 1):
            done = "✓已复测" if idx - 1 < next_index else "待复测"
            lines.append(f"{idx}. [{done}] {Path(item).name}")
        return "\n".join(lines)

    def _resolve_report_index(self, file_index: Any, file_name: str) -> int:
        with self.lock:
            files = list(self.source_files)
            next_index = self.next_index
        if file_name:
            target = str(file_name).strip().lower()
            for idx, item in enumerate(files):
                if Path(item).name.lower() == target or target in Path(item).name.lower():
                    return idx
            return -1
        if file_index is not None:
            try:
                idx = int(file_index) - 1
            except Exception:
                return -1
            return idx if 0 <= idx < len(files) else -1
        # 未指定则取下一份未完成的通报
        return next_index if next_index < len(files) else -1

    def tool_retest_report(
        self,
        file_index: Any = None,
        file_name: str = "",
        generate_report: bool = False,
        turn_id: str = "",
    ) -> str:
        with self.lock:
            if self.stopped:
                return "会话已停止，不再执行复测。"
            if not self.target_dir:
                return "当前会话没有通报目录，无法复测通报文档。可改用 retest_url 对具体 URL 现场取证。"
        self._ensure_source_files_loaded(turn_id)
        index = self._resolve_report_index(file_index, file_name)
        if index < 0:
            return f"没找到要复测的通报（file_index={file_index}, file_name={file_name}）。可先调用 list_reports 查看清单。"
        outcome = self._retest_single_file(index, bool(generate_report), turn_id)
        return outcome.get("message") or "复测完成。"

    def tool_retest_all_reports(self, generate_reports: bool = False, turn_id: str = "") -> str:
        with self.lock:
            if not self.target_dir:
                return "当前会话没有通报目录，无法批量复测。可改用 retest_url 对具体 URL 现场取证。"
        self._ensure_source_files_loaded(turn_id)
        with self.lock:
            total = len(self.source_files)
            start = self.next_index
        if total <= 0:
            return "通报目录下没有可复测的通报文档。"
        if start >= total:
            return f"全部 {total} 份通报都已复测完成。如需重测，请告诉用户说『重新复测』。"
        self._publish(
            "thought_summary", "Agent 计划",
            f"按队列从第 {start + 1} 份开始，依次复测剩余 {total - start} 份通报。",
            "info", metadata={"turnId": turn_id, "roundId": turn_id, "phase": "planning"},
        )
        done = 0
        while True:
            with self.lock:
                if self.stopped:
                    break
                index = self.next_index
                if index >= len(self.source_files):
                    break
            self._retest_single_file(index, bool(generate_reports), turn_id)
            done += 1
        overview = _format_agent_completion_overview(self.completion_items)
        self._publish(
            "artifact", "复测结论总览", overview,
            "warn" if any(item.get("status") == "risk" for item in self.completion_items) else "ok",
            metadata={"turnId": turn_id, "roundId": turn_id, "phase": "completion_summary",
                      "completionItems": list(self.completion_items),
                      "sessionPatch": self._session_patch({"status": "复测完成", "progress": 100, "resumeState": None})},
        )
        return f"已复测 {done} 份通报。\n{overview}"

    def tool_retest_url(self, url: str, vuln_types: List[str], note: str = "", turn_id: str = "") -> str:
        target = str(url or "").strip()
        if not _valid_http_target(target):
            return f"URL 无效或不是 http/https 目标: {url}"
        return self._retest_adhoc_url(target, vuln_types or [], note, turn_id)

    def tool_generate_reports(self, file_name: str = "", turn_id: str = "") -> str:
        with self.lock:
            completed = [str(item.get("sourceFile") or "") for item in self.completion_items if item.get("sourceFile")]
        if not completed:
            return "当前会话还没有已完成的复测结果，无法生成报告。请先复测。"
        if file_name:
            target = str(file_name).strip().lower()
            match = next((item for item in completed if target in Path(item).name.lower()), "")
            if not match:
                return f"没找到已复测的通报 {file_name}，无法单独生成报告。"
            summary = self.report_evidence_summaries.get(match) or ""
            reports = self._generate_report_for_file(match, summary, turn_id)
            return f"已为 {Path(match).name} 生成 {len(reports)} 份报告。" if reports else "报告生成失败或无输出。"
        self._generate_reports_for_completed(turn_id)
        with self.lock:
            count = len(self.reports)
        return f"已为本会话已完成的通报生成报告，共 {count} 份。"

    def tool_install_tools(self, tools: List[str], turn_id: str = "") -> str:
        selected = [t for t in (tools or []) if t in ("nmap", "sqlmap", "ffuf")] or ["nmap", "sqlmap", "ffuf"]
        message = "下载工具 " + " ".join(selected)
        self._install_external_tools(message, turn_id)
        result = _doc_retest_tools_status({})
        lines = []
        for item in result.get("tools") or []:
            lines.append(f"{item.get('name')}: {'已配置' if item.get('installed') else '未配置'}")
        return "外部工具安装流程已执行。当前状态:\n" + ("\n".join(lines) or "未知")

    def tool_tool_status(self, turn_id: str = "") -> str:
        self._show_external_tool_status(turn_id)
        result = _doc_retest_tools_status({})
        lines = []
        for item in result.get("tools") or []:
            command = " ".join(str(part) for part in item.get("command") or [])
            lines.append(f"{item.get('name')}: {'已配置' if item.get('installed') else '未配置'} {command}".rstrip())
        return "\n".join(lines) or (result.get("message") or "未获取到工具状态。")

    def _retest_single_file(self, index: int, generate_report: bool, turn_id: str) -> Dict[str, Any]:
        """复测单份通报（从队列循环抽取），事件/状态行为与批量队列保持一致。

        返回 {"status": ..., "message": ...}，message 会回灌给会话模型。
        """
        with self.lock:
            if index < 0 or index >= len(self.source_files):
                return {"status": "failed", "message": f"通报序号越界: {index + 1}"}
            source_file = self.source_files[index]
            total = len(self.source_files)
        file_path = Path(source_file)
        round_id = f"{turn_id}:file:{index + 1}"
        self._publish(
            "chat", f"通报 {index + 1}/{total}", f"开始复测: {file_path.name}", "info",
            metadata={"role": "agent", "turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name,
                      "sessionPatch": self._session_patch({"status": f"Agent 正在复测 ({index + 1}/{total}): {file_path.name}", "progress": int(index / max(1, total) * 100), "isRunning": True, "resumeState": None})},
        )
        file_logs: List[str] = []

        def on_event(event: Dict[str, Any]) -> None:
            try:
                from modules.backend_api.retest_event_stream import publish_retest_event

                # 内层复测产生的 tool_call/tool_result/status 默认只带 phase，缺 turnId/roundId。
                # 这里统一补全，保证前端能把这些事件归属到本轮、并让 tool_call↔tool_result 稳定配对。
                meta = event.get("metadata")
                if not isinstance(meta, dict):
                    meta = {}
                    event["metadata"] = meta
                meta.setdefault("turnId", turn_id)
                meta.setdefault("roundId", round_id)
                if not event.get("sourceFile"):
                    event["sourceFile"] = str(file_path)
                meta.setdefault("sourceFileName", file_path.name)

                publish_retest_event({"type": "retest_trace_event", "session_id": self.session_id, "task_id": "agent", "event": event})
            except Exception:
                pass

        try:
            summary, result_data, _manual, _events = _run_retest_for_source_file(
                file_path,
                {"round_id": round_id, "turn_id": turn_id, "source_file_name": file_path.name, "session_id": self.session_id},
                file_logs,
                event_callback=on_event,
            )
            self.logs.extend(file_logs)
            result = {"success": True, "message": f"复测完成: {file_path.name}", "summary": summary, "result_data": result_data, "logs": file_logs}
            report_summary = _format_report_evidence_snapshot(summary, result_data)
            report_paths: List[str] = []
            if generate_report:
                report_paths = self._generate_report_for_file(source_file, report_summary, turn_id, round_id)
            completion_item = _completion_item_from_result(source_file, result, report_paths)
            with self.lock:
                self.summaries.append(summary)
                self.reports.extend(report_paths)
                self.report_evidence_summaries[source_file] = report_summary
                self.completion_items.append(completion_item)
                self.latest_result_data = result_data
                self.next_index = max(self.next_index, index + 1)
            status = "risk" if completion_item.get("status") == "risk" else completion_item.get("status") or "clean"
            self._publish(
                "chat", "复测结果", _format_agent_result_message(source_file, result, completion_item, report_paths),
                "warn" if status == "risk" else "ok",
                metadata={"role": "agent", "turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name,
                          "fixStatus": "risk" if status == "risk" else "clean",
                          "sessionPatch": self._session_patch({"resultText": summary, "latestResultData": result_data, "progress": int((index + 1) / max(1, total) * 100), "resumeState": None})},
            )
            verdict = "漏洞可复现/未修复" if status == "risk" else "未见复现/复测通过"
            return {"status": status, "message": f"{file_path.name} 复测完成：{verdict}。" + (f" 已生成 {len(report_paths)} 份报告。" if report_paths else "")}
        except RetestAIBlockedError:
            raise
        except Exception as exc:
            self.logs.append(traceback.format_exc())
            completion_item = _completion_item_from_result(source_file, None, [], str(exc))
            with self.lock:
                self.completion_items.append(completion_item)
                self.next_index = max(self.next_index, index + 1)
            self._publish(
                "error", "复测错误", f"{file_path.name} 处理失败: {exc}", "error",
                metadata={"turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name, "sessionPatch": self._session_patch()},
            )
            return {"status": "failed", "message": f"{file_path.name} 复测失败: {exc}"}

    def _retest_adhoc_url(self, url: str, vuln_types: List[str], note: str, turn_id: str) -> str:
        """对用户在对话里直接给出的 URL 现场取证（无需通报文档）。

        复用 VulnerabilityRetestScanner 的 ReAct 取证引擎 + judge 判定，事件推到当前会话流。
        """
        ai_config = _ensure_retest_ai_ready("config")
        from modules.AI_Testing.retest.vulnerability_batch_scanner import VulnerabilityRetestScanner

        round_id = f"{turn_id}:url:{uuid.uuid4().hex[:6]}"

        def on_event(event: Dict[str, Any]) -> None:
            if isinstance(event, dict):
                metadata = event.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    event["metadata"] = metadata
                metadata.setdefault("turnId", turn_id)
                metadata.setdefault("roundId", round_id)
            try:
                from modules.backend_api.retest_event_stream import publish_retest_event

                publish_retest_event({"type": "retest_trace_event", "session_id": self.session_id, "task_id": "agent", "event": event})
            except Exception:
                pass

        self._publish(
            "chat", "现场取证", f"对用户指定 URL 启动黑盒取证: {url}", "info",
            metadata={"role": "agent", "turnId": turn_id, "roundId": round_id,
                      "sessionPatch": self._session_patch({"status": f"正在现场取证: {url}", "isRunning": True, "resumeState": None})},
        )

        context: Dict[str, Any] = {
            "target_urls": [url],
            "issue_tags": [],
            "raw_text": note or "",
        }
        scanner = VulnerabilityRetestScanner(timeout=15, max_workers=3, trace_callback=on_event, ai_config=ai_config)
        try:
            result = scanner.scan_url_for_context(url, vuln_types or [], context)
        except RetestAIBlockedError:
            raise
        except Exception as exc:
            self.logs.append(traceback.format_exc())
            self._publish(
                "error", "现场取证失败", f"{url} 取证失败: {exc}", "error",
                metadata={"turnId": turn_id, "roundId": round_id, "sessionPatch": self._session_patch()},
            )
            return f"对 {url} 现场取证失败: {exc}"

        observations = [item for item in (result.get("vulnerabilities") or []) if isinstance(item, dict)]
        obs_count = len(observations)
        executed = result.get("context_checks") or []
        react_summary = ""
        advice = context.get("agent_advice") if isinstance(context.get("agent_advice"), dict) else {}
        if isinstance(advice, dict):
            react_summary = str(advice.get("react_summary") or "")
        lines = [f"对 {url} 的现场取证完成。", f"调用工具 {len(executed)} 次，记录 {obs_count} 条观察。"]
        if react_summary:
            lines.append(f"取证总结: {react_summary}")
        for item in observations[:8]:
            lines.append(f"- [{item.get('severity') or 'info'}] {item.get('type') or '观察'}: {str(item.get('detail') or item.get('evidence') or '')[:200]}")
        if result.get("target_unreachable"):
            lines.append("目标当前不可达。")
        summary_text = "\n".join(lines)
        self._publish(
            "chat", "现场取证结果", summary_text, "ok",
            metadata={"role": "agent", "turnId": turn_id, "roundId": round_id,
                      "sessionPatch": self._session_patch({"status": "现场取证完成", "resumeState": None})},
        )
        return (
            summary_text
            + "\n\n注意：这是现场取证的原始观察，不是对通报漏洞的最终二元判定。"
            "如需对某份通报给出 reproduced/not_reproduced 结论，请用 retest_report。"
        )

    def _load_source_files(self, turn_id: str) -> None:
        with self.lock:
            target_dir = self.target_dir
        if not target_dir:
            raise ValueError("当前会话没有通报目录。请先从一键复测入口启动，或在会话里提供 target_dir。")
        tool_call_id = f"list:{turn_id}"
        self._publish("tool_call", "列通报", f"扫描通报目录: {target_dir}", "info", tool={"toolId": "list_reports", "label": "列通报", "status": "running", "target": target_dir, "argsPreview": target_dir}, metadata={"toolCallId": tool_call_id, "turnId": turn_id, "roundId": turn_id, "phase": "tool"})
        result = _doc_retest_list_files({"target_dir": target_dir})
        self.logs.extend(result.get("logs") or [])
        source_files = result.get("source_files") or []
        with self.lock:
            self.source_files = [str(item) for item in source_files]
            self.next_index = min(self.next_index, len(self.source_files))
        self._publish("tool_result", "列通报", result.get("message") or f"发现 {len(source_files)} 份通报", "ok" if source_files else "warn", tool={"toolId": "list_reports", "label": "列通报", "status": "completed", "target": target_dir, "resultPreview": result.get("message") or "", "rawCount": len(source_files), "rawOutput": "\n".join(str(item) for item in source_files)}, metadata={"toolCallId": tool_call_id, "turnId": turn_id, "roundId": turn_id, "phase": "tool", "sessionPatch": self._session_patch({"targetDir": target_dir, "progress": self._progress_locked(), "resumeState": None})})
        if not source_files:
            raise ValueError(result.get("message") or "未找到通报文档。")

    def _run_retest_queue(self, turn_id: str) -> None:
        _ensure_retest_ai_ready("config")
        with self.lock:
            if not self.source_files:
                self._load_source_files(turn_id)
            total = len(self.source_files)
        if total <= 0:
            return
        self._publish("thought_summary", "Agent 计划", f"我会按当前队列逐份读取通报、调用工具复测，再由 AI 给出二元结论。队列共 {total} 份，断点位置 {self.next_index + 1}。", "info", metadata={"turnId": turn_id, "roundId": turn_id, "phase": "planning", "sessionPatch": self._session_patch({"isRunning": True, "resumeState": None})})
        while True:
            with self.lock:
                if self.stopped:
                    return
                index = self.next_index
                if index >= len(self.source_files):
                    break
                source_file = self.source_files[index]
                generate_reports = self.generate_reports
            file_path = Path(source_file)
            round_id = f"{turn_id}:file:{index + 1}"
            self._publish("chat", f"通报 {index + 1}/{total}", f"开始复测: {file_path.name}", "info", metadata={"role": "agent", "turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name, "sessionPatch": self._session_patch({"status": f"Agent 正在复测 ({index + 1}/{total}): {file_path.name}", "progress": int(index / max(1, total) * 100), "isRunning": True, "resumeState": None})})
            file_logs: List[str] = []

            def on_event(event: Dict[str, Any]) -> None:
                try:
                    from modules.backend_api.retest_event_stream import publish_retest_event

                    publish_retest_event({"type": "retest_trace_event", "session_id": self.session_id, "task_id": "agent", "event": event})
                except Exception:
                    pass

            try:
                summary, result_data, _manual, _events = _run_retest_for_source_file(
                    file_path,
                    {"round_id": round_id, "turn_id": turn_id, "source_file_name": file_path.name, "session_id": self.session_id},
                    file_logs,
                    event_callback=on_event,
                )
                self.logs.extend(file_logs)
                result = {"success": True, "message": f"复测完成: {file_path.name}", "summary": summary, "result_data": result_data, "logs": file_logs}
                report_summary = _format_report_evidence_snapshot(summary, result_data)
                report_paths: List[str] = []
                if generate_reports:
                    report_paths = self._generate_report_for_file(source_file, report_summary, turn_id, round_id)
                completion_item = _completion_item_from_result(source_file, result, report_paths)
                with self.lock:
                    self.summaries.append(summary)
                    self.reports.extend(report_paths)
                    self.report_evidence_summaries[source_file] = report_summary
                    self.completion_items.append(completion_item)
                    self.latest_result_data = result_data
                    self.next_index = index + 1
                self._publish("chat", "复测结果", _format_agent_result_message(source_file, result, completion_item, report_paths), "warn" if completion_item.get("status") == "risk" else "ok", metadata={"role": "agent", "turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name, "fixStatus": "risk" if completion_item.get("status") == "risk" else "clean", "sessionPatch": self._session_patch({"resultText": summary, "latestResultData": result_data, "progress": int((index + 1) / max(1, total) * 100), "resumeState": None})})
            except RetestAIBlockedError:
                raise
            except Exception as exc:
                self.logs.append(traceback.format_exc())
                completion_item = _completion_item_from_result(source_file, None, [], str(exc))
                with self.lock:
                    self.completion_items.append(completion_item)
                    self.next_index = index + 1
                self._publish("error", "复测错误", f"{file_path.name} 处理失败: {exc}", "error", metadata={"turnId": turn_id, "roundId": round_id, "sourceFileName": file_path.name, "sessionPatch": self._session_patch()})
        overview = _format_agent_completion_overview(self.completion_items)
        final_result = "\n\n".join([overview] + self.summaries + (["生成报告:\n" + "\n".join(self.reports)] if self.reports else []))
        with self.lock:
            self.blocked = False
            self.blocked_reason = ""
            self.blocked_stage = ""
            self.blocked_title = ""
        self._publish("artifact", "复测结论总览", overview, "warn" if any(item.get("status") == "risk" for item in self.completion_items) else "ok", metadata={"turnId": turn_id, "roundId": turn_id, "phase": "completion_summary", "completionItems": list(self.completion_items), "sessionPatch": self._session_patch({"status": "复测完成", "progress": 100, "resultText": final_result, "lastReportPath": self.reports[0] if self.reports else self.target_dir, "resumeState": None})})

    def _generate_report_for_file(self, source_file: str, summary: str, turn_id: str = "", round_id: str = "") -> List[str]:
        tool_id = f"report:{self.session_id}:{Path(source_file).name}:{time.time()}"
        metadata = {"toolCallId": tool_id, "turnId": turn_id or self.current_turn_id, "roundId": round_id or turn_id or self.current_turn_id, "phase": "tool"}
        self._publish("tool_call", "生成报告", f"按用户明确要求为 {Path(source_file).name} 生成报告。", "info", tool={"toolId": "generate_report", "label": "生成报告", "status": "running", "target": source_file, "argsPreview": source_file}, metadata=metadata)
        logs: List[str] = []
        result: Dict[str, Any]
        try:
            result = _generate_retest_reports_from_agent_summary(Path(self.target_dir), [source_file], summary, logs)
        except Exception as exc:
            logs.append(traceback.format_exc())
            result = {
                "success": False,
                "message": f"报告生成异常: {exc}",
                "reports": [],
                "failures": [{"file": source_file, "name": Path(source_file).name, "reason": str(exc)}],
                "logs": logs,
            }
        self.logs.extend(result.get("logs") or logs)
        reports = [str(item) for item in result.get("reports") or []]
        artifact_content = _format_report_artifact_content(str(result.get("message") or ""), reports)
        self._publish("tool_result", "生成报告", artifact_content, "ok" if result.get("success") else "error", tool={"toolId": "generate_report", "label": "生成报告", "status": "completed" if result.get("success") else "failed", "target": source_file, "resultPreview": artifact_content, "rawOutput": "\n".join(result.get("logs") or []), "rawCount": len(reports), "failureReason": "" if result.get("success") else result.get("message")}, metadata={**metadata, "reports": reports, "sessionPatch": self._session_patch({"lastReportPath": reports[0] if reports else self.target_dir, "resumeState": None})})
        if result.get("success") or reports:
            self._publish(
                "artifact",
                "报告生成完成" if result.get("success") else "报告生成部分完成",
                artifact_content,
                "ok" if result.get("success") else "warn",
                metadata={
                    "turnId": metadata.get("turnId"),
                    "roundId": metadata.get("roundId"),
                    "phase": "artifact",
                    "reports": reports,
                    "sessionPatch": self._session_patch({"lastReportPath": reports[0] if reports else self.target_dir, "resumeState": None}),
                },
            )
        return reports

    def _generate_reports_for_completed(self, turn_id: str) -> None:
        with self.lock:
            source_files = [str(item.get("sourceFile") or "") for item in self.completion_items if item.get("sourceFile")]
            summary = "\n\n".join(self.summaries) or _format_agent_completion_overview(self.completion_items)
        if not source_files:
            self._publish("chat", "Agent", "当前会话还没有已完成的复测结果，无法直接生成报告。", "warn", metadata={"role": "agent", "turnId": turn_id})
            return
        summary_parts: List[str] = []
        for source_file in source_files:
            evidence_summary = self.report_evidence_summaries.get(source_file)
            if evidence_summary:
                summary_parts.append(evidence_summary)
        if not summary_parts:
            summary_parts.append(summary)
        logs: List[str] = []
        result = _generate_retest_reports_from_agent_summary(Path(self.target_dir), source_files, "\n\n".join(summary_parts), logs)
        self.logs.extend(result.get("logs") or [])
        reports = [str(item) for item in result.get("reports") or []]
        with self.lock:
            self.reports.extend(reports)
        artifact_content = _format_report_artifact_content(str(result.get("message") or ""), reports)
        self._publish("artifact", "报告生成完成" if result.get("success") else "报告生成失败", artifact_content, "ok" if result.get("success") else "error", metadata={"turnId": turn_id, "roundId": turn_id, "phase": "artifact", "reports": reports, "sessionPatch": self._session_patch({"lastReportPath": reports[0] if reports else self.target_dir, "resumeState": None})})

    def _install_external_tools(self, message: str, turn_id: str) -> None:
        selected = []
        for name in ("nmap", "sqlmap", "ffuf"):
            if name in message.lower():
                selected.append(name)
        selected = selected or ["nmap", "sqlmap", "ffuf"]
        tool_call_id = f"install-tools:{self.session_id}:{uuid.uuid4().hex[:8]}"
        self._publish("tool_call", "一键下载外部工具", "下载并配置 nmap/sqlmap/ffuf 项目工具目录。", "info", tool={"toolId": "install_external_tools", "label": "一键下载外部工具", "status": "running", "target": ",".join(selected), "argsPreview": ",".join(selected)}, metadata={"toolCallId": tool_call_id, "turnId": turn_id, "roundId": turn_id, "phase": "tool", "sessionPatch": self._session_patch({"status": "正在下载外部工具", "isRunning": True, "resumeState": None})})
        result = _doc_retest_tools_install({"tools": selected})
        raw_output = "\n".join(result.get("logs") or []) or json.dumps(result, ensure_ascii=False, default=str, indent=2)
        self._publish("tool_result", "一键下载外部工具", result.get("message") or "", "ok" if result.get("success") else "error", tool={"toolId": "install_external_tools", "label": "一键下载外部工具", "status": "completed" if result.get("success") else "failed", "target": ",".join(selected), "resultPreview": result.get("message") or "", "rawOutput": raw_output, "failureReason": "" if result.get("success") else json.dumps(result.get("failures") or [], ensure_ascii=False)}, metadata={"toolCallId": tool_call_id, "turnId": turn_id, "roundId": turn_id, "phase": "tool", "sessionPatch": self._session_patch({"status": result.get("message") or "工具下载完成", "resumeState": None})})

    def _show_external_tool_status(self, turn_id: str) -> None:
        result = _doc_retest_tools_status({})
        lines = []
        for item in result.get("tools") or []:
            command = " ".join(str(part) for part in item.get("command") or [])
            lines.append(f"{item.get('name')}: {'已配置' if item.get('installed') else '未配置'} {command}")
        self._publish("chat", "外部工具状态", "\n".join(lines) or result.get("message") or "", "ok" if result.get("success") else "warn", metadata={"role": "agent", "turnId": turn_id})

    def _block(self, exc: RetestAIBlockedError, turn_id: str = "") -> None:
        with self.lock:
            self.running = False
            self.blocked = True
            self.blocked_reason = str(exc)
            self.blocked_stage = exc.stage
            self.blocked_title = _ai_blocked_title(exc)
        self._publish("error", self.blocked_title, str(exc), "warn", metadata={"blockedByAiConfig": True, "turnId": turn_id or self.current_turn_id, "roundId": turn_id or self.current_turn_id, "phase": exc.stage, "sessionPatch": self._session_patch({"isRunning": False, "status": self.blocked_title, "resumeState": self._resume_state_locked(True)})})

    def _resume_state_locked(self, can_continue: bool) -> Dict[str, Any]:
        return {
            "canContinue": can_continue,
            "targetDir": self.target_dir,
            "sourceFiles": list(self.source_files),
            "nextIndex": self.next_index,
            "summaries": list(self.summaries),
            "reports": list(self.reports),
            "completionItems": list(self.completion_items),
            "allLogs": list(self.logs),
            "failedCount": len([item for item in self.completion_items if item.get("status") == "failed"]),
            "generateReports": self.generate_reports,
            "blockedReason": self.blocked_reason,
            "blockedStage": self.blocked_stage,
            "blockedTitle": self.blocked_title,
        }

    def _session_patch(self, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
        with self.lock:
            patch = {
                "targetDir": self.target_dir,
                "status": self._status_locked(),
                "progress": self._progress_locked(),
                "isRunning": self.running,
                "log": "\n".join(self.logs[-3000:]),
                "lastReportPath": self.reports[0] if self.reports else self.target_dir,
                "latestResultData": self.latest_result_data,
                "resumeState": self._resume_state_locked(self.blocked) if self.blocked else None,
            }
        if extra:
            patch.update(extra)
        return patch

    def _publish(self, event_type: str, title: str, content: str = "", tone: str = "info", tool: Dict[str, Any] | None = None, metadata: Dict[str, Any] | None = None) -> None:
        event = _retest_trace_event(event_type, title, content, tone, tool=tool, metadata=metadata or {})
        try:
            from modules.backend_api.retest_event_stream import publish_retest_event

            publish_retest_event({"type": "retest_trace_event", "session_id": self.session_id, "task_id": "agent", "event": event})
        except Exception:
            pass


def _message_requests_report(message: str) -> bool:
    text = str(message or "")
    return any(word in text for word in ("生成报告", "写报告", "出报告", "导出报告", "报告"))


def _message_requests_rerun(message: str) -> bool:
    text = str(message or "")
    return any(word in text for word in ("重新", "再测", "重测", "重新测", "重新复测", "再跑", "重新跑", "测一遍"))


def _get_retest_agent_runner(session_id: str) -> RetestAgentRunner:
    if not session_id:
        session_id = f"agent-{uuid.uuid4().hex[:10]}"
    with _RETEST_AGENT_LOCK:
        runner = _RETEST_AGENT_RUNNERS.get(session_id)
        if runner is None:
            runner = RetestAgentRunner(session_id)
            _RETEST_AGENT_RUNNERS[session_id] = runner
        return runner


def _doc_retest_agent_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip() or f"session-{uuid.uuid4().hex[:10]}"
    runner = _get_retest_agent_runner(session_id)
    return runner.start(payload)


def _doc_retest_agent_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return {"success": False, "message": "缺少 session_id"}
    runner = _get_retest_agent_runner(session_id)
    return runner.message(payload)


def _doc_retest_agent_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return {"success": False, "message": "缺少 session_id"}
    runner = _get_retest_agent_runner(session_id)
    return runner.snapshot()


def _doc_retest_agent_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return {"success": False, "message": "缺少 session_id"}
    runner = _get_retest_agent_runner(session_id)
    return runner.stop()


def _doc_retest_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = Path(_required_text(payload, "target_dir", "请选择通报目录")).expanduser()
    if not target_dir.exists() or not target_dir.is_dir():
        return {"success": False, "message": f"通报目录不存在: {target_dir}", "logs": []}

    logs: List[str] = []
    reports: List[str] = []
    source_files: List[str] = []
    summaries: List[str] = []
    risk_count = 0
    pass_count = 0
    failed_count = 0
    generate_reports = _payload_bool(payload.get("generate_reports"), True)

    try:
        _ensure_retest_ai_ready("config")
    except RetestAIBlockedError as exc:
        logs.append(str(exc))
        return _ai_blocked_payload(exc, "", logs, [])

    try:
        from modules.AI_Testing.retest.vulnerability_batch_scanner import VulnerabilityRetestScanner
        from modules.AI_Testing.retest.word_vulnerability_scanner import WordVulnerabilityScanner
        from modules.AI_Testing.retest.retest_report_generator import RetestReportGenerator
    except Exception as exc:
        return {"success": False, "message": f"导入复测模块失败: {exc}", "logs": [traceback.format_exc()]}

    template_path = _retest_template_path()
    if generate_reports and not template_path.exists():
        return {"success": False, "message": f"未找到复测模板文件: {template_path}", "logs": logs}

    scanner = WordVulnerabilityScanner(str(target_dir))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        word_files = scanner.find_word_files()
    logs.extend(_captured_lines(buffer))
    logs.append(f"扫描完成，发现 {len(word_files)} 份通报文档")

    for index, file_path in enumerate(word_files, 1):
        source_files.append(str(file_path))
        logs.append(f"处理 ({index}/{len(word_files)}): {file_path.name}")
        try:
            summary, result_data, _manual_required, trace_events = _run_retest_for_source_file(file_path, payload, logs)
        except RetestAIBlockedError as exc:
            logs.append(str(exc))
            payload_blocked = _ai_blocked_payload(exc, str(file_path), logs, [])
            payload_blocked.update({
                "target_dir": str(target_dir),
                "source_files": source_files,
                "processed": max(0, index - 1),
                "reports": reports,
                "summary": "\n\n".join(summaries),
                "risk_count": risk_count,
                "pass_count": pass_count,
                "failed_count": failed_count,
                "manual_count": 0,
            })
            return payload_blocked
        final_verdict = _model_verdict_from_result_data(result_data)
        if final_verdict == "reproduced":
            risk_count += 1
        elif final_verdict == "not_reproduced":
            pass_count += 1
        else:
            failed_count += 1
            result_data["failed_count"] = max(1, int(result_data.get("failed_count") or 0))
            logs.append(f"{file_path.name} 模型未给出 reproduced/not_reproduced 判定，未按工具结果兜底。")
        summaries.append(summary)
        if trace_events:
            logs.append(f"{file_path.name} 记录 {len(trace_events)} 条 Agent 执行事件")

        if generate_reports:
            generator = RetestReportGenerator(
                target_dir=str(file_path.parent),
                template_path=str(template_path),
                output_dir=None,
                screenshot_path=None,
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                generator_scan = generator.scan_document(file_path)
                output_path = generator.generate_report(generator_scan)
            logs.extend(_captured_lines(buffer))
            report_path = _existing_report_path(output_path)
            if report_path:
                reports.append(report_path)
                logs.append(f"报告已生成: {report_path}")
            else:
                failed_count += 1
                logs.append(f"报告生成失败或文件未落盘: {file_path.name} ({output_path or '无输出路径'})")

    message = (
        f"复测完成：处理 {len(word_files)} 份文档，生成 {len(reports)} 份报告，漏洞未修复/可复现 {risk_count} 份，复测通过 {pass_count} 份，执行失败 {failed_count} 份"
        if generate_reports
        else f"复测完成：处理 {len(word_files)} 份文档，等待截图写入报告，漏洞未修复/可复现 {risk_count} 份，复测通过 {pass_count} 份，执行失败 {failed_count} 份"
    )
    return {
        "success": True,
        "message": message,
        "target_dir": str(target_dir),
        "processed": len(word_files),
        "manual_count": 0,
        "risk_count": risk_count,
        "pass_count": pass_count,
        "failed_count": failed_count,
        "source_files": source_files,
        "reports": reports,
        "summary": "\n\n".join(summaries),
        "logs": logs,
    }


def _doc_retest_generate_reports_with_screenshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = Path(_required_text(payload, "target_dir", "请选择通报目录")).expanduser()
    if not target_dir.exists() or not target_dir.is_dir():
        return {"success": False, "message": f"通报目录不存在: {target_dir}", "logs": []}

    source_files = _path_list(payload.get("source_files"))
    if not source_files:
        return {"success": False, "message": "缺少待生成报告的通报文件列表", "logs": []}

    template_path = _retest_template_path()
    if not template_path.exists():
        return {"success": False, "message": f"未找到复测模板文件: {template_path}", "logs": []}

    logs: List[str] = []
    reports: List[str] = []
    failures: List[tuple[Path, str]] = []
    screenshot_path: Path | None = None

    try:
        try:
            screenshot_path = _save_retest_screenshot_data(
                target_dir,
                _required_text(payload, "screenshot_data_url", "缺少复测截图数据"),
            )
            logs.append(f"复测结果区域截图已保存: {screenshot_path}")
        except Exception as exc:
            logs.append(traceback.format_exc())
            return {"success": False, "message": f"保存复测截图失败: {exc}", "logs": logs}

        try:
            from modules.AI_Testing.retest.retest_report_generator import RetestReportGenerator
        except Exception as exc:
            logs.append(traceback.format_exc())
            return {"success": False, "message": f"导入复测报告生成器失败: {exc}", "logs": logs}

        for source_file in source_files:
            file_path = Path(source_file).expanduser()
            if not file_path.exists() or file_path.suffix.lower() not in WORD_SUFFIXES:
                failures.append((file_path, "通报文件不存在或不是 Word 文档"))
                continue

            generator = RetestReportGenerator(
                target_dir=str(file_path.parent),
                template_path=str(template_path),
                output_dir=None,
                screenshot_path=str(screenshot_path),
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                generator_scan = generator.scan_document(file_path)
                output_path = generator.generate_report(generator_scan)
            logs.extend(_captured_lines(buffer))
            report_path = _existing_report_path(output_path)
            if report_path:
                reports.append(report_path)
                logs.append(f"报告已写入截图: {report_path}")
            else:
                failures.append((file_path, f"报告生成失败或文件未落盘: {output_path or '无输出路径'}"))

        success = bool(reports) and not failures
        message = (
            f"复测报告截图写入完成：生成 {len(reports)} 份，失败 {len(failures)} 份"
            if success
            else f"复测报告未生成或写入失败：生成 {len(reports)} 份，失败 {len(failures)} 份"
        )
        return {
            "success": success,
            "message": message,
            "target_dir": str(target_dir),
            "reports": reports,
            "screenshot_path": str(screenshot_path),
            "failures": _failure_dicts(failures),
            "logs": logs,
        }
    finally:
        _cleanup_retest_screenshot_dir(target_dir, logs)


def _doc_retest_open_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = Path(_required_text(payload, "target_dir", "请选择通报目录")).expanduser()
    if not target_dir.exists() or not target_dir.is_dir():
        return {"success": False, "message": f"目录不存在: {target_dir}"}
    opened, error = _open_path_in_system(target_dir)
    return {
        "success": opened,
        "message": "已打开报告目录" if opened else f"无法打开报告目录: {error}",
        "path": str(target_dir),
    }

