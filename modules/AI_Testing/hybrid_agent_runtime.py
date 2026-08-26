#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared hybrid agent runtime primitives.

This module is intentionally small and conservative.  It gives the retest
agent a structured, persisted session model and a safe set of workspace tools,
without turning the first rollout into a full coding-agent rewrite.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


AGENT_SESSION_DIRNAME = ".koi_agent_sessions"
AGENT_SESSION_SCHEMA_VERSION = 2
MAX_EVENT_MEMORY = 800
MAX_STEP_MEMORY = 400
MAX_TOOL_TEXT = 20000
MAX_OPERATION_OUTPUT = 60000
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
DEFAULT_BUILD_TIMEOUT_SECONDS = 600
DEFAULT_TEST_TIMEOUT_SECONDS = 300
COMMAND_DENY_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\brmdir\b",
    r"\bdel\s+",
    r"\berase\s+",
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\breg\s+",
    r"\bgit\s+reset\b",
    r"\bgit\s+clean\b",
    r"\bgit\s+checkout\s+--\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\binvoke-webrequest\b",
    r"\biwr\b",
    r"\binvoke-restmethod\b",
    r"\bnpm\s+install\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bpip\s+install\b",
    r"\bpython\s+-c\b",
    r"\bpython(?:\.exe)?\s+-c\b",
    r"\bpy\s+-c\b",
    r"\bpy(?:\.exe)?\s+-c\b",
    r"\bpowershell(?:\.exe)?\s+-command\b",
    r"\bpwsh(?:\.exe)?\s+-command\b",
    r"\bcmd(?:\.exe)?\s+/c\b",
    r"\bstart-process\b",
)
TERMINAL_OPERATION_STATUSES = {"completed", "failed", "rejected", "cancelled", "stale"}
APPROVED_OPERATION_STATUSES = {"approved", "running"}


@dataclass
class AgentToolCall:
    id: str
    name: str
    status: str = "running"
    args_preview: str = ""
    result_preview: str = ""
    raw_output: str = ""
    duration_ms: int = 0
    risk: str = "read"
    requires_approval: bool = False
    approval_id: str = ""
    operation_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentArtifact:
    id: str
    title: str
    content: str = ""
    path: str = ""
    kind: str = "text"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentApprovalRequest:
    id: str
    tool_name: str
    operation: str
    detail: str
    args_preview: str = ""
    args_json: str = ""
    cwd: str = ""
    risk: str = "write"
    operation_id: str = ""
    tool_call_id: str = ""
    run_id: str = ""
    status: str = "pending"
    decision: str = ""
    note: str = ""
    preview_artifact_id: str = ""
    sandbox_summary: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentOperation:
    id: str
    approval_id: str
    tool_name: str
    args: Dict[str, Any] = field(default_factory=dict)
    cwd: str = ""
    risk: str = "write"
    detail: str = ""
    status: str = "pending"
    session_id: str = ""
    run_id: str = ""
    tool_call_id: str = ""
    result_preview: str = ""
    raw_output: str = ""
    exit_code: Optional[int] = None
    error: str = ""
    artifact_ids: List[str] = field(default_factory=list)
    preview_artifact_id: str = ""
    sandbox_summary: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0


@dataclass
class AgentStep:
    id: str
    kind: str
    title: str
    content: str = ""
    status: str = "completed"
    tool_call: Optional[AgentToolCall] = None
    artifact: Optional[AgentArtifact] = None
    approval: Optional[AgentApprovalRequest] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentRun:
    id: str
    user_message: str
    mode: str = "hybrid"
    status: str = "running"
    plan: str = ""
    observations: List[Dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""
    steps: List[AgentStep] = field(default_factory=list)


@dataclass
class AgentSession:
    id: str
    schema_version: int = AGENT_SESSION_SCHEMA_VERSION
    mode: str = "hybrid"
    auto_approve: bool = True
    workspace_root: str = ""
    status: str = "idle"
    memory_markdown: str = ""
    compact_memory: str = ""
    conversation: List[Dict[str, Any]] = field(default_factory=list)
    runs: List[AgentRun] = field(default_factory=list)
    steps: List[AgentStep] = field(default_factory=list)
    approvals: Dict[str, AgentApprovalRequest] = field(default_factory=dict)
    operations: Dict[str, AgentOperation] = field(default_factory=dict)
    artifacts: List[AgentArtifact] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


def agent_session_to_dict(session: AgentSession) -> Dict[str, Any]:
    return asdict(session)


def _agent_tool_call_from_dict(value: Dict[str, Any] | None) -> AgentToolCall | None:
    if not isinstance(value, dict):
        return None
    allowed = {field.name for field in AgentToolCall.__dataclass_fields__.values()}
    return AgentToolCall(**{key: value.get(key) for key in allowed if key in value})


def _agent_artifact_from_dict(value: Dict[str, Any] | None) -> AgentArtifact | None:
    if not isinstance(value, dict):
        return None
    allowed = {field.name for field in AgentArtifact.__dataclass_fields__.values()}
    return AgentArtifact(**{key: value.get(key) for key in allowed if key in value})


def _agent_approval_from_dict(value: Dict[str, Any] | None) -> AgentApprovalRequest | None:
    if not isinstance(value, dict):
        return None
    allowed = {field.name for field in AgentApprovalRequest.__dataclass_fields__.values()}
    return AgentApprovalRequest(**{key: value.get(key) for key in allowed if key in value})


def _agent_operation_from_dict(value: Dict[str, Any] | None) -> AgentOperation | None:
    if not isinstance(value, dict):
        return None
    allowed = {field.name for field in AgentOperation.__dataclass_fields__.values()}
    data = {key: value.get(key) for key in allowed if key in value}
    if not isinstance(data.get("args"), dict):
        data["args"] = {}
    if not isinstance(data.get("artifact_ids"), list):
        data["artifact_ids"] = []
    return AgentOperation(**data)


def _agent_step_from_dict(value: Dict[str, Any] | None) -> AgentStep | None:
    if not isinstance(value, dict):
        return None
    return AgentStep(
        id=str(value.get("id") or f"step-{uuid.uuid4().hex[:8]}"),
        kind=str(value.get("kind") or "status"),
        title=str(value.get("title") or ""),
        content=str(value.get("content") or ""),
        status=str(value.get("status") or "completed"),
        tool_call=_agent_tool_call_from_dict(value.get("tool_call")),
        artifact=_agent_artifact_from_dict(value.get("artifact")),
        approval=_agent_approval_from_dict(value.get("approval")),
        created_at=str(value.get("created_at") or datetime.now().isoformat()),
    )


def _agent_run_from_dict(value: Dict[str, Any] | None) -> AgentRun | None:
    if not isinstance(value, dict):
        return None
    run = AgentRun(
        id=str(value.get("id") or f"run-{uuid.uuid4().hex[:8]}"),
        user_message=str(value.get("user_message") or ""),
        mode=str(value.get("mode") or "hybrid"),
        status=str(value.get("status") or "running"),
        plan=str(value.get("plan") or ""),
        started_at=str(value.get("started_at") or datetime.now().isoformat()),
        finished_at=str(value.get("finished_at") or ""),
    )
    run.observations = [dict(item) for item in (value.get("observations") or []) if isinstance(item, dict)]
    run.steps = [step for step in (_agent_step_from_dict(item) for item in value.get("steps") or []) if step]
    return run


def _agent_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return bool(value)


def agent_session_from_dict(value: Dict[str, Any], fallback_id: str = "") -> AgentSession:
    if "auto_approve" in value:
        auto_approve = _agent_bool(value.get("auto_approve"), True)
    elif "autoApprove" in value:
        auto_approve = _agent_bool(value.get("autoApprove"), True)
    else:
        auto_approve = True
    session = AgentSession(
        id=str(value.get("id") or fallback_id or f"agent-{uuid.uuid4().hex[:10]}"),
        schema_version=int(value.get("schema_version") or 1),
        mode=str(value.get("mode") or "hybrid"),
        auto_approve=auto_approve,
        workspace_root=str(value.get("workspace_root") or ""),
        status=str(value.get("status") or "idle"),
        memory_markdown=str(value.get("memory_markdown") or ""),
        compact_memory=str(value.get("compact_memory") or ""),
        created_at=str(value.get("created_at") or datetime.now().isoformat()),
        updated_at=str(value.get("updated_at") or datetime.now().isoformat()),
    )
    session.conversation = [dict(item) for item in (value.get("conversation") or []) if isinstance(item, dict)]
    session.runs = [run for run in (_agent_run_from_dict(item) for item in value.get("runs") or []) if run]
    session.steps = [step for step in (_agent_step_from_dict(item) for item in value.get("steps") or []) if step]
    session.artifacts = [
        artifact for artifact in (_agent_artifact_from_dict(item) for item in value.get("artifacts") or []) if artifact
    ]
    session.approvals = {
        str(key): approval
        for key, approval in (
            (key, _agent_approval_from_dict(item)) for key, item in (value.get("approvals") or {}).items()
        )
        if approval
    }
    session.operations = {
        str(key): operation
        for key, operation in (
            (key, _agent_operation_from_dict(item)) for key, item in (value.get("operations") or {}).items()
        )
        if operation
    }
    session.events = [dict(item) for item in (value.get("events") or []) if isinstance(item, dict)]
    _migrate_agent_session(session)
    return session


def _migrate_agent_session(session: AgentSession) -> None:
    if not isinstance(session.schema_version, int) or session.schema_version < 1:
        session.schema_version = 1
    now = datetime.now().isoformat()
    for operation in session.operations.values():
        if operation.status == "resolved":
            operation.status = "approved"
    for approval in session.approvals.values():
        operation = session.operations.get(approval.operation_id)
        if operation and operation.status == "stale" and approval.status == "running":
            approval.status = "stale"
            approval.updated_at = now
    session.schema_version = AGENT_SESSION_SCHEMA_VERSION


class AgentSessionStore:
    """Persist agent sessions under the project data directory."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        self.session_dir = self.root_dir / AGENT_SESSION_DIRNAME
        self.lock = threading.RLock()

    def path_for(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "agent")).strip("._")
        return self.session_dir / f"{safe or 'agent'}.json"

    def load(self, session_id: str, *, mode: str = "hybrid", workspace_root: str = "") -> AgentSession:
        path = self.path_for(session_id)
        with self.lock:
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    session = agent_session_from_dict(raw, session_id)
                    if workspace_root and not session.workspace_root:
                        session.workspace_root = str(Path(workspace_root).resolve())
                    return session
                except Exception:
                    pass
            return AgentSession(id=session_id, mode=mode, workspace_root=str(Path(workspace_root or self.root_dir).resolve()))

    def save(self, session: AgentSession) -> None:
        with self.lock:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            session.updated_at = datetime.now().isoformat()
            path = self.path_for(session.id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(agent_session_to_dict(session), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)


@dataclass
class AgentExecutionResult:
    status: str
    summary: str
    raw_output: str = ""
    exit_code: Optional[int] = None
    artifact_ids: List[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str = ""


@dataclass
class CommandSpec:
    label: str
    cwd: str = "."
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    argv: List[str] = field(default_factory=list)
    command: str = ""
    shell: bool = False

    def display(self) -> str:
        if self.argv:
            return " ".join(_quote_command_part(item) for item in self.argv)
        return self.command


_RUNNING_OPERATION_LOCK = threading.RLock()
_RUNNING_OPERATIONS: Dict[str, Dict[str, Any]] = {}


def running_agent_operations_snapshot(session_id: str = "") -> List[Dict[str, Any]]:
    wanted = str(session_id or "").strip()
    with _RUNNING_OPERATION_LOCK:
        rows = []
        for operation_id, entry in _RUNNING_OPERATIONS.items():
            if wanted and entry.get("session_id") != wanted:
                continue
            rows.append({
                "operation_id": operation_id,
                "session_id": entry.get("session_id", ""),
                "tool_name": entry.get("tool_name", ""),
                "status": entry.get("status", "running"),
                "started_at": entry.get("started_at", ""),
                "cwd": entry.get("cwd", ""),
                "command": entry.get("command", ""),
            })
        return rows


def cancel_agent_operations(session_id: str = "", operation_id: str = "") -> int:
    wanted_session = str(session_id or "").strip()
    wanted_operation = str(operation_id or "").strip()
    cancelled = 0
    with _RUNNING_OPERATION_LOCK:
        entries = list(_RUNNING_OPERATIONS.items())
    for op_id, entry in entries:
        if wanted_operation and op_id != wanted_operation:
            continue
        if wanted_session and entry.get("session_id") != wanted_session:
            continue
        stop_event = entry.get("stop_event")
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        process = entry.get("process")
        if process is not None:
            _terminate_process_tree(process)
        cancelled += 1
    return cancelled


def _clip_operation_output(text: Any, limit: int = MAX_OPERATION_OUTPUT) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    head = max(1000, limit // 2)
    tail = max(1000, limit - head - 80)
    return value[:head] + f"\n...[truncated {len(value) - head - tail} chars]...\n" + value[-tail:]


def traceback_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _command_path_tokens(command: str) -> List[str]:
    tokens = re.findall(r'"[^"]+"|\'[^\']+\'|\S+', str(command or ""))
    cleaned: List[str] = []
    for token in tokens:
        value = token.strip().rstrip(",;")
        if not value:
            continue
        if value in {"|", "&&", "||", ">", ">>", "<"}:
            cleaned.append(value)
            continue
        if value.startswith((">", ">>", "<")) and len(value) > 1:
            cleaned.append(value.lstrip("><"))
            continue
        cleaned.append(value)
    return cleaned


def _canonical_agent_args(args: Dict[str, Any]) -> str:
    try:
        return json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(args or {})


def _canonical_agent_cwd(value: Any) -> str:
    return str(value or "").strip() or "."


def _quote_command_part(value: Any) -> str:
    text = str(value or "")
    if not text:
        return '""'
    if re.search(r"\s", text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _running_operation_ids() -> set[str]:
    with _RUNNING_OPERATION_LOCK:
        return set(_RUNNING_OPERATIONS)


def _terminate_process_tree(process: Any) -> None:
    if process is None:
        return
    pid = getattr(process, "pid", None)
    if os.name == "nt" and pid:
        try:
            completed = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if completed.returncode == 0:
                return
        except Exception:
            pass
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass


class AgentSandboxPolicy:
    """Workspace-only safety policy for approved side-effect tools."""

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()

    def summary_for_tool(self, tool_name: str) -> str:
        if tool_name == "apply_patch":
            return "workspace unified text diff only; create/modify allowed; delete/rename/binary/path escape rejected"
        if tool_name in {"run_command", "run_tests", "build_project"}:
            return "workspace cwd only; clean env; timeout; output capture; network/install/destructive/path escape rejected"
        return "workspace-only sandbox"

    def validate_tool_request(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "apply_patch":
            self.parse_patch(str(args.get("patch") or ""))
        elif tool_name in {"run_command", "run_tests", "build_project"}:
            command = str(args.get("command") or "").strip()
            if command:
                cwd = self.resolve_workspace_dir(args.get("cwd") or ".")
                self.validate_command(command, cwd)
        else:
            raise RuntimeError(f"unknown side-effect tool: {tool_name}")
        return self.summary_for_tool(tool_name)

    def resolve_workspace_dir(self, value: Any) -> Path:
        raw = str(value or ".").strip() or "."
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except Exception as exc:
            raise RuntimeError("cwd escapes workspace root") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise RuntimeError(f"cwd is not a directory: {raw}")
        return resolved

    def validate_command(self, command: str, cwd: Path) -> None:
        text = str(command or "").strip()
        if not text:
            raise RuntimeError("command is required")
        lowered = text.lower()
        for pattern in COMMAND_DENY_PATTERNS:
            if re.search(pattern, lowered):
                raise RuntimeError(f"command rejected by sandbox policy: {pattern}")
        for token in _command_path_tokens(text)[1:]:
            self.validate_command_path_token(token, cwd)

    def validate_command_argv(self, argv: List[str], cwd: Path) -> None:
        if not argv:
            raise RuntimeError("command argv is required")
        text = " ".join(str(item or "") for item in argv).lower()
        for pattern in COMMAND_DENY_PATTERNS:
            if re.search(pattern, text):
                raise RuntimeError(f"command rejected by sandbox policy: {pattern}")
        for token in argv[1:]:
            self.validate_command_path_token(str(token), cwd)

    def validate_command_path_token(self, token: str, cwd: Path) -> None:
        raw = token.strip().strip('"').strip("'")
        if not raw or raw.startswith("-"):
            return
        if raw in {">", ">>", "<", "|", "&&", "||"}:
            return
        if raw.startswith(("http://", "https://")):
            raise RuntimeError("network URLs are not allowed in approved command arguments")
        looks_like_path = (
            "/" in raw
            or "\\" in raw
            or raw.startswith(".")
            or bool(re.match(r"^[A-Za-z]:", raw))
        )
        if not looks_like_path:
            return
        if raw in {".", "./", ".\\"}:
            return
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        try:
            candidate.resolve().relative_to(self.root)
        except Exception as exc:
            raise RuntimeError(f"command path escapes workspace root: {raw}") from exc

    def parse_patch(self, patch_text: str) -> List[Dict[str, Any]]:
        text = str(patch_text or "")
        if "\0" in text or "GIT binary patch" in text or "Binary files " in text:
            raise RuntimeError("binary patches are not allowed")
        if not text.strip() or "@@" not in text:
            raise RuntimeError("only unified diffs with hunks are supported")
        forbidden_headers = ("deleted file mode", "rename from ", "rename to ", "similarity index ", "dissimilarity index ")
        for line in text.splitlines():
            if line.startswith(forbidden_headers):
                raise RuntimeError("delete/rename patches are not allowed")

        lines = text.splitlines()
        index = 0
        patches: List[Dict[str, Any]] = []
        while index < len(lines):
            line = lines[index]
            if not line.startswith("--- "):
                index += 1
                continue
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise RuntimeError("invalid unified diff header")
            old_path = self.patch_path_to_workspace(lines[index][4:].strip())
            new_path = self.patch_path_to_workspace(lines[index + 1][4:].strip())
            if new_path is None:
                raise RuntimeError("file deletion patches are not allowed")
            if old_path is not None and old_path != new_path:
                raise RuntimeError("rename patches are not allowed")
            if old_path is None and new_path.exists():
                raise RuntimeError(f"create patch target already exists: {new_path.relative_to(self.root)}")
            if old_path is not None and not old_path.exists():
                raise RuntimeError(f"patch target does not exist: {old_path.relative_to(self.root)}")
            self.validate_text_target(new_path)
            index += 2
            hunks: List[Dict[str, Any]] = []
            while index < len(lines) and not lines[index].startswith("--- "):
                if lines[index].startswith("diff --git "):
                    break
                if not lines[index].startswith("@@ "):
                    index += 1
                    continue
                match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
                if not match:
                    raise RuntimeError("invalid unified diff hunk header")
                old_start, old_count, new_start, new_count = match.groups()
                index += 1
                hunk_lines: List[str] = []
                while index < len(lines):
                    current = lines[index]
                    if current.startswith("@@ ") or current.startswith("--- ") or current.startswith("diff --git "):
                        break
                    if current.startswith("\\ No newline"):
                        index += 1
                        continue
                    if not current or current[0] not in {" ", "-", "+"}:
                        raise RuntimeError("invalid unified diff hunk line")
                    hunk_lines.append(current)
                    index += 1
                hunks.append({
                    "old_start": int(old_start),
                    "old_count": int(old_count or "1"),
                    "new_start": int(new_start),
                    "new_count": int(new_count or "1"),
                    "lines": hunk_lines,
                })
                if index < len(lines) and lines[index].startswith("diff --git "):
                    break
            if not hunks:
                raise RuntimeError("patch file entry has no hunks")
            patches.append({"old_path": old_path, "new_path": new_path, "hunks": hunks})
        if not patches:
            raise RuntimeError("patch does not contain workspace file paths")
        return patches

    def patch_path_to_workspace(self, token: str) -> Optional[Path]:
        raw = str(token or "").strip().strip('"')
        raw = raw.split("\t", 1)[0].split(" ", 1)[0]
        if not raw or raw in {"/dev/null", "NUL", "nul"}:
            return None
        if raw.startswith("a/") or raw.startswith("b/"):
            raw = raw[2:]
        raw = raw.replace("\\", "/")
        candidate = Path(raw)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise RuntimeError("patch path escapes workspace root")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except Exception as exc:
            raise RuntimeError("patch path escapes workspace root") from exc
        return resolved

    def validate_text_target(self, path: Path) -> None:
        rel_parts = path.relative_to(self.root).parts
        if rel_parts and rel_parts[0] in {".git", ".koi_agent_sessions", "node_modules"}:
            raise RuntimeError(f"patch target is not allowed: {rel_parts[0]}")
        if path.exists() and self.looks_binary_file(path):
            raise RuntimeError(f"patch target is binary: {path.relative_to(self.root)}")

    def looks_binary_file(self, path: Path) -> bool:
        binary_suffixes = {
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".exe", ".dll", ".db", ".zip",
            ".rar", ".7z", ".pdf", ".pyc", ".pyd", ".so", ".dylib",
        }
        if path.suffix.lower() in binary_suffixes:
            return True
        try:
            sample = path.read_bytes()[:4096]
        except Exception:
            return False
        return b"\0" in sample


class HybridAgentRuntime:
    """Small structured runtime used by the retest adapter and generic tools."""

    def __init__(
        self,
        session_id: str,
        workspace_root: str | Path,
        publish: Callable[[Dict[str, Any]], None] | None = None,
        mode: str = "hybrid",
        store_root: str | Path | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.store = AgentSessionStore(store_root or self.workspace_root)
        self.session = self.store.load(session_id, mode=mode, workspace_root=str(self.workspace_root))
        loaded_workspace = Path(self.session.workspace_root).resolve() if self.session.workspace_root else None
        if loaded_workspace != self.workspace_root:
            self.session.workspace_root = str(self.workspace_root)
            self.store.save(self.session)
        self.sandbox = AgentSandboxPolicy(self.workspace_root)
        self.publish = publish
        self.lock = threading.RLock()
        self.mark_stale_operations()

    def begin_run(self, user_message: str, *, mode: str = "hybrid", emit_plan: bool = True) -> AgentRun:
        run = AgentRun(id=f"run-{uuid.uuid4().hex[:10]}", user_message=str(user_message or ""), mode=mode)
        with self.lock:
            self.session.status = "running"
            self.session.runs.append(run)
            self.session.runs = self.session.runs[-80:]
            self._save_locked()
        if emit_plan:
            self.record_plan(run, self._plan_for(user_message, mode))
        return run

    def finish_run(self, run: AgentRun | None, status: str = "completed") -> None:
        with self.lock:
            if run:
                run.status = status
                run.finished_at = datetime.now().isoformat()
            self.session.status = "idle" if status == "completed" else status
            self._save_locked()

    def finish_latest_run(self, status: str = "completed") -> None:
        with self.lock:
            run = self.session.runs[-1] if self.session.runs else None
        self.finish_run(run, status)

    def mark_stale_operations(self) -> int:
        live = _running_operation_ids()
        now = datetime.now().isoformat()
        changed = 0
        with self.lock:
            for operation in self.session.operations.values():
                if operation.status == "running" and operation.id not in live:
                    operation.status = "stale"
                    operation.error = operation.error or "Operation was running when the backend session was restored."
                    operation.finished_at = operation.finished_at or now
                    operation.updated_at = now
                    approval = self.session.approvals.get(operation.approval_id)
                    if approval and approval.status == "running":
                        approval.status = "stale"
                        approval.updated_at = now
                    changed += 1
            if changed:
                self._save_locked()
        return changed

    def record_event(self, event: Dict[str, Any]) -> None:
        with self.lock:
            self.session.events.append(dict(event))
            self.session.events = self.session.events[-MAX_EVENT_MEMORY:]
            self._save_locked()

    def record_status(self, title: str, content: str = "", tone: str = "info", metadata: Optional[Dict[str, Any]] = None) -> None:
        step = AgentStep(id=f"step-{uuid.uuid4().hex[:10]}", kind="status", title=title, content=content)
        self._append_step(step)
        self._emit("status", title, content, tone, metadata=metadata or {})

    def record_plan(self, run: AgentRun | None, content: str) -> None:
        plan = str(content or "").strip() or "先理解请求，再读取必要上下文，最后基于真实工具观察回复。"
        if run:
            with self.lock:
                run.plan = plan
                self._save_locked()
        self.record_status("Agent 计划", plan, "info", metadata={"phase": "planning", "runId": getattr(run, "id", "")})

    def record_thought(self, title: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        step = AgentStep(id=f"step-{uuid.uuid4().hex[:10]}", kind="thought_summary", title=title, content=str(content or ""))
        self._append_step(step)
        meta = {"phase": "reflection", "role": "agent"}
        meta.update(metadata or {})
        self._emit("thought_summary", title, str(content or ""), "info", metadata=meta)

    def record_chat(self, title: str, content: str = "", tone: str = "ok", metadata: Optional[Dict[str, Any]] = None) -> None:
        step = AgentStep(id=f"step-{uuid.uuid4().hex[:10]}", kind="chat", title=title, content=content)
        self._append_step(step)
        meta = {"role": "agent", "phase": "final"}
        meta.update(metadata or {})
        self._emit("chat", title, content, tone, metadata=meta)

    def append_conversation(self, message: Dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        with self.lock:
            self.session.conversation.append(dict(message))
            self.session.conversation = self.session.conversation[-120:]
            self._save_locked()

    def conversation_messages(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(item) for item in self.session.conversation[-max(1, int(limit or 40)):]]

    def set_compact_memory(self, content: str) -> None:
        with self.lock:
            self.session.compact_memory = str(content or "")[:24000]
            self.session.memory_markdown = self.session.compact_memory
            self._save_locked()

    def set_auto_approve(self, enabled: bool, note: str = "") -> bool:
        enabled_bool = bool(enabled)
        with self.lock:
            changed = self.session.auto_approve != enabled_bool
            self.session.auto_approve = enabled_bool
            self._save_locked()
        self.record_status(
            "Auto approval updated",
            f"Auto approval is now {'enabled' if enabled_bool else 'disabled'}. Sandbox policy still applies."
            + (f" {note}" if note else ""),
            "warn" if enabled_bool else "info",
            metadata={"phase": "auto_approval", "autoApprove": enabled_bool, "changed": changed, "agentRuntime": True},
        )
        return enabled_bool

    def record_artifact(self, title: str, content: str = "", path: str = "", kind: str = "text") -> AgentArtifact:
        artifact = AgentArtifact(id=f"artifact-{uuid.uuid4().hex[:10]}", title=title, content=content, path=path, kind=kind)
        step = AgentStep(id=f"step-{uuid.uuid4().hex[:10]}", kind="artifact", title=title, content=content, artifact=artifact)
        with self.lock:
            self.session.artifacts.append(artifact)
            self.session.artifacts = self.session.artifacts[-120:]
        self._append_step(step)
        self._emit("artifact", title, content or path, "ok", metadata={"artifactId": artifact.id, "artifactKind": kind, "path": path})
        return artifact

    def record_tool_call(
        self,
        name: str,
        args_preview: str,
        *,
        label: str = "",
        risk: str = "read",
        approval_id: str = "",
        operation_id: str = "",
        requires_approval: bool = False,
    ) -> AgentToolCall:
        call = AgentToolCall(
            id=f"tool-{uuid.uuid4().hex[:10]}",
            name=name,
            args_preview=args_preview[:4000],
            risk=risk,
            approval_id=approval_id,
            operation_id=operation_id,
            requires_approval=requires_approval,
        )
        step = AgentStep(
            id=f"step-{uuid.uuid4().hex[:10]}",
            kind="tool_call",
            title=label or name,
            content=args_preview[:4000],
            status="running",
            tool_call=call,
        )
        self._append_step(step)
        self._emit(
            "tool_call",
            label or name,
            f"开始执行 {label or name}",
            "info",
            tool={"toolId": name, "label": label or name, "status": "running", "argsPreview": args_preview[:4000]},
            metadata={
                "toolCallId": call.id,
                "phase": "tool",
                "agentRuntime": True,
                "approvalId": approval_id or None,
                "operationId": operation_id or None,
                "requiresApproval": requires_approval or None,
            },
        )
        return call

    def record_tool_result(
        self,
        call: AgentToolCall,
        result_preview: str,
        *,
        raw_output: str = "",
        status: str = "completed",
        tone: str = "info",
        duration_ms: int = 0,
    ) -> None:
        call.status = status
        call.result_preview = result_preview[:4000]
        call.raw_output = raw_output[:MAX_TOOL_TEXT]
        call.duration_ms = int(duration_ms or 0)
        step = AgentStep(
            id=f"step-{uuid.uuid4().hex[:10]}",
            kind="tool_result",
            title=call.name,
            content=call.result_preview,
            status=status,
            tool_call=call,
        )
        with self.lock:
            if self.session.runs:
                self.session.runs[-1].observations.append({
                    "tool": call.name,
                    "status": status,
                    "preview": call.result_preview,
                    "duration_ms": call.duration_ms,
                    "created_at": datetime.now().isoformat(),
                })
                self.session.runs[-1].observations = self.session.runs[-1].observations[-120:]
        self._append_step(step)
        self._emit(
            "tool_result",
            call.name,
            call.result_preview,
            tone,
            tool={
                "toolId": call.name,
                "label": call.name,
                "status": status,
                "argsPreview": call.args_preview,
                "resultPreview": call.result_preview,
                "rawOutput": call.raw_output,
                "durationMs": call.duration_ms,
            },
            metadata={
                "toolCallId": call.id,
                "phase": "tool",
                "agentRuntime": True,
                "approvalId": call.approval_id or None,
                "operationId": call.operation_id or None,
                "requiresApproval": call.requires_approval or None,
            },
        )

    def _legacy_request_approval(self, tool_name: str, operation: str, detail: str, args_preview: str = "") -> AgentApprovalRequest:
        approval = AgentApprovalRequest(
            id=f"approval-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            operation=operation,
            detail=detail,
            args_preview=args_preview[:4000],
        )
        step = AgentStep(
            id=f"step-{uuid.uuid4().hex[:10]}",
            kind="approval",
            title=f"需要确认: {operation}",
            content=detail,
            status="blocked",
            approval=approval,
        )
        with self.lock:
            self.session.approvals[approval.id] = approval
        self._append_step(step)
        self._emit(
            "approval_request",
            f"需要确认: {operation}",
            detail,
            "warn",
            metadata={
                "approvalId": approval.id,
                "confirmationId": approval.id,
                "operation": operation,
                "matched": tool_name,
                "script": args_preview[:4000],
                "requiresUserDecision": True,
                "agentRuntime": True,
            },
        )
        return approval

    def _legacy_resolve_approval(self, approval_id: str, decision: str, note: str = "") -> bool:
        with self.lock:
            approval = self.session.approvals.get(str(approval_id or ""))
            if not approval:
                return False
            approval.status = "resolved"
            approval.decision = "approve" if str(decision).lower() in {"approve", "yes", "allow", "true", "1"} else "reject"
            approval.note = str(note or "")
            self._save_locked()
        self.record_status(
            "审批已处理",
            f"{approval.operation}: {approval.decision}{(' - ' + approval.note) if approval.note else ''}",
            "ok" if approval.decision == "approve" else "warn",
            metadata={"phase": "approval", "approvalId": approval.id},
        )
        return True

    def request_approval(
        self,
        tool_name: str,
        operation: str,
        detail: str,
        args_preview: str = "",
        *,
        args: Optional[Dict[str, Any]] = None,
        cwd: str = "",
        risk: str = "write",
        run_id: str = "",
        tool_call_id: str = "",
        preview_artifact_id: str = "",
        sandbox_summary: str = "",
    ) -> AgentApprovalRequest:
        args_dict = args if isinstance(args, dict) else {}
        args_json = json.dumps(args_dict, ensure_ascii=False, default=str)
        auto_approved = bool(self.session.auto_approve)
        with self.lock:
            active_run_id = run_id or (self.session.runs[-1].id if self.session.runs else "")
            operation_id = f"operation-{uuid.uuid4().hex[:12]}"
            approval = AgentApprovalRequest(
                id=f"approval-{uuid.uuid4().hex[:12]}",
                tool_name=tool_name,
                operation=operation,
                detail=detail,
                args_preview=args_preview[:4000],
                args_json=args_json[:24000],
                cwd=str(cwd or ""),
                risk=str(risk or "write"),
                operation_id=operation_id,
                tool_call_id=str(tool_call_id or ""),
                run_id=active_run_id,
                preview_artifact_id=str(preview_artifact_id or ""),
                sandbox_summary=str(sandbox_summary or ""),
            )
            agent_operation = AgentOperation(
                id=operation_id,
                approval_id=approval.id,
                tool_name=tool_name,
                args=dict(args_dict),
                cwd=str(cwd or ""),
                risk=str(risk or "write"),
                detail=detail,
                session_id=self.session.id,
                run_id=active_run_id,
                tool_call_id=str(tool_call_id or ""),
                preview_artifact_id=str(preview_artifact_id or ""),
                sandbox_summary=str(sandbox_summary or ""),
            )
            self.session.approvals[approval.id] = approval
            self.session.operations[operation_id] = agent_operation

        step = AgentStep(
            id=f"step-{uuid.uuid4().hex[:10]}",
            kind="approval",
            title=f"Approval required: {operation}",
            content=detail,
            status="blocked",
            approval=approval,
        )
        self._append_step(step)
        self._emit(
            "approval_request",
            f"Approval required: {operation}",
            detail,
            "warn",
            metadata={
                "approvalId": approval.id,
                "confirmationId": approval.id,
                "operationId": operation_id,
                "operation": operation,
                "matched": tool_name,
                "script": args_preview[:4000],
                "cwd": str(cwd or ""),
                "risk": str(risk or "write"),
                "sandboxPolicySummary": str(sandbox_summary or ""),
                "previewArtifactId": str(preview_artifact_id or ""),
                "runId": active_run_id,
                "toolCallId": str(tool_call_id or ""),
                "requiresUserDecision": not auto_approved,
                "autoApproved": auto_approved,
                "autoApprove": auto_approved,
                "agentRuntime": True,
            },
        )
        return approval

    def resolve_approval(self, approval_id: str, decision: str, note: str = "") -> bool:
        approved = str(decision).lower() in {"approve", "yes", "allow", "true", "1"}
        with self.lock:
            approval = self.session.approvals.get(str(approval_id or ""))
            if not approval:
                return False
            now = datetime.now().isoformat()
            approval.status = "approved" if approved else "rejected"
            approval.decision = "approve" if approved else "reject"
            approval.note = str(note or "")
            approval.updated_at = now
            operation = self.session.operations.get(approval.operation_id)
            if operation:
                operation.status = "approved" if approved else "rejected"
                operation.updated_at = now
                if not approved:
                    operation.error = approval.note or "Rejected by user"
                    operation.finished_at = now
            self._save_locked()
        self.record_status(
            "Approval handled",
            f"{approval.operation}: {approval.decision}{(' - ' + approval.note) if approval.note else ''}",
            "ok" if approved else "warn",
            metadata={
                "phase": "approval",
                "approvalId": approval.id,
                "operationId": approval.operation_id,
                "status": approval.status,
                "agentRuntime": True,
            },
        )
        if not approved:
            self.record_chat(
                "Agent",
                f"{approval.tool_name} was rejected by the user. No side effects were executed.",
                "warn",
                metadata={"phase": "approval", "approvalId": approval.id, "operationId": approval.operation_id},
            )
        return True

    def approval_request(self, approval_id: str) -> Optional[AgentApprovalRequest]:
        with self.lock:
            approval = self.session.approvals.get(str(approval_id or ""))
            return AgentApprovalRequest(**asdict(approval)) if approval else None

    def operation_for_approval(self, approval_id: str) -> Optional[AgentOperation]:
        with self.lock:
            approval = self.session.approvals.get(str(approval_id or ""))
            if not approval:
                return None
            operation = self.session.operations.get(approval.operation_id)
            return AgentOperation(**asdict(operation)) if operation else None

    def operation_by_id(self, operation_id: str) -> Optional[AgentOperation]:
        with self.lock:
            operation = self.session.operations.get(str(operation_id or ""))
            return AgentOperation(**asdict(operation)) if operation else None

    def rejected_matching_operation(self, tool_name: str, args: Dict[str, Any], cwd: str = "") -> Optional[AgentOperation]:
        wanted_tool = str(tool_name or "")
        wanted_args = _canonical_agent_args(args)
        wanted_cwd = _canonical_agent_cwd(cwd)
        with self.lock:
            operations = sorted(
                self.session.operations.values(),
                key=lambda item: item.updated_at or item.created_at,
                reverse=True,
            )
            for operation in operations:
                if operation.tool_name != wanted_tool or operation.status != "rejected":
                    continue
                if _canonical_agent_args(operation.args) != wanted_args:
                    continue
                if _canonical_agent_cwd(operation.cwd) != wanted_cwd:
                    continue
                return AgentOperation(**asdict(operation))
        return None

    def operation_snapshot(self, operation_id: str) -> Dict[str, Any]:
        self.mark_stale_operations()
        with self.lock:
            operation = self.session.operations.get(str(operation_id or ""))
            if not operation:
                return {}
            return asdict(operation)

    def mark_operation_cancel_requested(self, operation_id: str, message: str = "Operation cancellation requested.") -> bool:
        now = datetime.now().isoformat()
        with self.lock:
            operation = self.session.operations.get(str(operation_id or ""))
            if not operation:
                return False
            if operation.status not in TERMINAL_OPERATION_STATUSES:
                operation.status = "cancelled"
                operation.error = message
                operation.finished_at = operation.finished_at or now
                operation.updated_at = now
                approval = self.session.approvals.get(operation.approval_id)
                if approval and approval.status not in TERMINAL_OPERATION_STATUSES:
                    approval.status = "cancelled"
                    approval.updated_at = now
                self._save_locked()
            return True

    def execute_approved_operation(
        self,
        approval_id: str,
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        stop_event = stop_event or threading.Event()
        with self.lock:
            approval = self.session.approvals.get(str(approval_id or ""))
            if not approval:
                raise RuntimeError("approval not found")
            operation = self.session.operations.get(approval.operation_id)
            if not operation:
                raise RuntimeError("operation not found")
            if approval.status not in APPROVED_OPERATION_STATUSES and operation.status not in APPROVED_OPERATION_STATUSES:
                raise RuntimeError(f"approval is not approved: {approval.status}")
            now = datetime.now().isoformat()
            approval.status = "running"
            approval.updated_at = now
            operation.status = "running"
            operation.started_at = operation.started_at or now
            operation.updated_at = now
            self.session.status = "running"
            self._save_locked()
            operation_snapshot = AgentOperation(**asdict(operation))

        with _RUNNING_OPERATION_LOCK:
            _RUNNING_OPERATIONS[operation_snapshot.id] = {
                "operation_id": operation_snapshot.id,
                "session_id": self.session.id,
                "tool_name": operation_snapshot.tool_name,
                "status": "running",
                "started_at": operation_snapshot.started_at,
                "cwd": operation_snapshot.cwd,
                "command": str(operation_snapshot.args.get("command") or ""),
                "stop_event": stop_event,
                "process": None,
            }

        args_preview = json.dumps(operation_snapshot.args, ensure_ascii=False, default=str)[:4000]
        call = self.record_tool_call(
            operation_snapshot.tool_name,
            args_preview,
            label=operation_snapshot.tool_name,
            risk=operation_snapshot.risk,
            approval_id=approval_id,
            operation_id=operation_snapshot.id,
            requires_approval=True,
        )
        with self.lock:
            live_operation = self.session.operations.get(operation_snapshot.id)
            if live_operation:
                live_operation.tool_call_id = call.id
                live_operation.updated_at = datetime.now().isoformat()
                self._save_locked()
        started = time.time()
        try:
            result = self._dispatch_approved_operation(operation_snapshot, stop_event)
        except Exception as exc:
            result = AgentExecutionResult(
                status="failed",
                summary=f"{operation_snapshot.tool_name} failed: {exc}",
                raw_output=traceback_text(exc),
                error=str(exc),
            )
        finally:
            with _RUNNING_OPERATION_LOCK:
                _RUNNING_OPERATIONS.pop(operation_snapshot.id, None)

        if not result.duration_ms:
            result.duration_ms = int((time.time() - started) * 1000)
        tone = "ok" if result.status == "completed" else ("warn" if result.status == "cancelled" else "error")
        self.record_tool_result(
            call,
            result.summary,
            raw_output=result.raw_output,
            status=result.status,
            tone=tone,
            duration_ms=result.duration_ms,
        )
        self.append_conversation({
            "role": "tool",
            "tool_call_id": call.id,
            "name": operation_snapshot.tool_name,
            "content": (result.raw_output or result.summary)[:16000],
        })
        self._complete_operation(operation_snapshot.id, approval_id, result)
        return {
            "success": result.status == "completed",
            "status": result.status,
            "operation_id": operation_snapshot.id,
            "approval_id": approval_id,
            "tool_name": operation_snapshot.tool_name,
            "message": result.summary,
            "summary": result.summary,
            "raw_output": result.raw_output,
            "exit_code": result.exit_code,
            "artifact_ids": result.artifact_ids,
            "duration_ms": result.duration_ms,
            "agent_session": self.snapshot(),
        }

    def _dispatch_approved_operation(self, operation: AgentOperation, stop_event: threading.Event) -> AgentExecutionResult:
        if operation.tool_name == "run_command":
            return self._execute_command_tool(operation, stop_event, DEFAULT_COMMAND_TIMEOUT_SECONDS)
        if operation.tool_name == "run_tests":
            return self._execute_tests_tool(operation, stop_event)
        if operation.tool_name == "build_project":
            return self._execute_build_tool(operation, stop_event)
        if operation.tool_name == "apply_patch":
            return self._execute_patch_tool(operation)
        raise RuntimeError(f"unknown approved operation tool: {operation.tool_name}")

    def _complete_operation(self, operation_id: str, approval_id: str, result: AgentExecutionResult) -> None:
        now = datetime.now().isoformat()
        with self.lock:
            operation = self.session.operations.get(operation_id)
            approval = self.session.approvals.get(approval_id)
            if operation:
                operation.status = result.status
                operation.result_preview = result.summary[:4000]
                operation.raw_output = result.raw_output[:MAX_OPERATION_OUTPUT]
                operation.exit_code = result.exit_code
                operation.error = result.error
                operation.artifact_ids = list(result.artifact_ids or [])
                operation.duration_ms = int(result.duration_ms or 0)
                operation.finished_at = now
                operation.updated_at = now
            if approval:
                approval.status = result.status
                approval.updated_at = now
            self.session.status = "idle" if result.status in {"completed", "failed", "cancelled"} else result.status
            self._save_locked()

    def _execute_tests_tool(self, operation: AgentOperation, stop_event: threading.Event) -> AgentExecutionResult:
        args = dict(operation.args or {})
        if str(args.get("command") or "").strip():
            return self._execute_command_tool(operation, stop_event, DEFAULT_TEST_TIMEOUT_SECONDS)
        test_operation = AgentOperation(**asdict(operation))
        return self._execute_command_sequence(
            test_operation,
            [CommandSpec(
                label="hybrid agent loop test",
                argv=[sys.executable, "modules/AI_Testing/hybrid_agent_loop_test.py"],
                cwd=".",
                timeout_seconds=DEFAULT_TEST_TIMEOUT_SECONDS,
            )],
            stop_event,
        )

    def _execute_build_tool(self, operation: AgentOperation, stop_event: threading.Event) -> AgentExecutionResult:
        args = dict(operation.args or {})
        custom_command = str(args.get("command") or "").strip()
        if custom_command:
            return self._execute_command_tool(operation, stop_event, DEFAULT_BUILD_TIMEOUT_SECONDS)
        commands = [
            CommandSpec(
                label="frontend build",
                argv=["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
                cwd="tauri-ui",
                timeout_seconds=DEFAULT_BUILD_TIMEOUT_SECONDS,
            ),
            CommandSpec(
                label="rust check",
                argv=["cargo", "check", "--manifest-path", "tauri-ui/src-tauri/Cargo.toml"],
                cwd=".",
                timeout_seconds=DEFAULT_BUILD_TIMEOUT_SECONDS,
            ),
        ]
        return self._execute_command_sequence(operation, commands, stop_event)

    def _execute_command_tool(
        self,
        operation: AgentOperation,
        stop_event: threading.Event,
        default_timeout: int,
    ) -> AgentExecutionResult:
        args = dict(operation.args or {})
        command = str(args.get("command") or "").strip()
        if not command:
            raise RuntimeError("command is required")
        cwd = self._resolve_workspace_dir(args.get("cwd") or operation.cwd or ".")
        timeout = self._timeout_seconds(args.get("timeout_seconds") or args.get("timeout") or default_timeout, default_timeout)
        argv = self._command_argv_if_safe(command)
        return self._execute_command_sequence(
            operation,
            [
                CommandSpec(
                    label=operation.tool_name,
                    command="" if argv else command,
                    argv=argv,
                    cwd=str(cwd),
                    timeout_seconds=int(timeout),
                    shell=not bool(argv),
                )
            ],
            stop_event,
        )

    def _execute_command_sequence(
        self,
        operation: AgentOperation,
        commands: List[CommandSpec | Dict[str, Any]],
        stop_event: threading.Event,
    ) -> AgentExecutionResult:
        outputs: List[str] = []
        started = time.time()
        last_exit_code: Optional[int] = None
        for index, raw_spec in enumerate(commands, 1):
            spec = self._coerce_command_spec(raw_spec)
            if stop_event.is_set():
                return AgentExecutionResult(
                    status="cancelled",
                    summary=f"{operation.tool_name} cancelled before command {index}.",
                    raw_output=_clip_operation_output("\n\n".join(outputs)),
                    exit_code=last_exit_code,
                    duration_ms=int((time.time() - started) * 1000),
                )
            command_display = spec.display().strip()
            if not command_display:
                raise RuntimeError("command is required")
            cwd = self._resolve_workspace_dir(spec.cwd or operation.cwd or ".")
            timeout = self._timeout_seconds(spec.timeout_seconds, DEFAULT_COMMAND_TIMEOUT_SECONDS)
            if spec.argv:
                self.sandbox.validate_command_argv(spec.argv, cwd)
            else:
                self.sandbox.validate_command(spec.command, cwd)
            heading = f"$ {command_display}\n# cwd: {cwd}"
            output, exit_code, status = self._run_shell_command(
                operation.id,
                spec,
                cwd,
                timeout,
                stop_event,
            )
            last_exit_code = exit_code
            outputs.append(f"{heading}\n{output}".rstrip())
            if status == "cancelled":
                raw = _clip_operation_output("\n\n".join(outputs))
                return AgentExecutionResult(
                    status="cancelled",
                    summary=f"{operation.tool_name} cancelled.",
                    raw_output=raw,
                    exit_code=exit_code,
                    duration_ms=int((time.time() - started) * 1000),
                )
            if status == "failed":
                raw = _clip_operation_output("\n\n".join(outputs))
                return AgentExecutionResult(
                    status="failed",
                    summary=f"{operation.tool_name} failed with exit code {exit_code}.",
                    raw_output=raw,
                    exit_code=exit_code,
                    duration_ms=int((time.time() - started) * 1000),
                    error=f"exit code {exit_code}",
                )
        raw = _clip_operation_output("\n\n".join(outputs))
        return AgentExecutionResult(
            status="completed",
            summary=f"{operation.tool_name} completed successfully.",
            raw_output=raw,
            exit_code=last_exit_code,
            duration_ms=int((time.time() - started) * 1000),
        )

    def _run_shell_command(
        self,
        operation_id: str,
        spec: CommandSpec,
        cwd: Path,
        timeout_seconds: float,
        stop_event: threading.Event,
    ) -> tuple[str, Optional[int], str]:
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            spec.command if spec.shell else spec.argv,
            cwd=str(cwd),
            shell=bool(spec.shell),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            env=self._command_env(),
        )
        with _RUNNING_OPERATION_LOCK:
            entry = _RUNNING_OPERATIONS.get(operation_id)
            if entry is not None:
                entry["process"] = proc
                entry["command"] = spec.display()
                entry["cwd"] = str(cwd)
        try:
            output, _ = proc.communicate(timeout=max(0.1, float(timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS)))
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            try:
                output, _ = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(proc)
                output = ""
            return f"{output or ''}\n[command timed out after {timeout_seconds:g}s]", proc.returncode, "failed"
        finally:
            with _RUNNING_OPERATION_LOCK:
                entry = _RUNNING_OPERATIONS.get(operation_id)
                if entry is not None:
                    entry["process"] = None
        if stop_event.is_set():
            return f"{output or ''}\n[command cancelled]", proc.returncode, "cancelled"
        status = "completed" if proc.returncode == 0 else "failed"
        return output or "", proc.returncode, status

    def _coerce_command_spec(self, value: CommandSpec | Dict[str, Any]) -> CommandSpec:
        if isinstance(value, CommandSpec):
            return value
        data = value if isinstance(value, dict) else {}
        argv = data.get("argv") if isinstance(data.get("argv"), list) else []
        return CommandSpec(
            label=str(data.get("label") or data.get("command") or "command"),
            cwd=str(data.get("cwd") or "."),
            timeout_seconds=int(data.get("timeout_seconds") or DEFAULT_COMMAND_TIMEOUT_SECONDS),
            argv=[str(item) for item in argv],
            command=str(data.get("command") or ""),
            shell=bool(data.get("shell", not argv)),
        )

    def _command_argv_if_safe(self, command: str) -> List[str]:
        text = str(command or "").strip()
        if not text:
            return []
        if re.search(r"[|&<>^]", text):
            return []
        try:
            parts = shlex.split(text, posix=(os.name != "nt"))
        except Exception:
            return []
        if not parts:
            return []
        executable = parts[0].strip().lower()
        if executable in {"echo", "dir", "copy", "type", "set", "cd"}:
            return []
        return [str(item) for item in parts]

    def _command_env(self) -> Dict[str, str]:
        temp_root = self.workspace_root / AGENT_SESSION_DIRNAME / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        env: Dict[str, str] = {}
        for key in ("PATH", "PATHEXT", "SystemRoot", "ComSpec", "WINDIR", "ProgramFiles", "ProgramFiles(x86)"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["TMP"] = str(temp_root)
        env["TEMP"] = str(temp_root)
        env["HOME"] = str(temp_root)
        env["USERPROFILE"] = str(temp_root)
        env["NO_COLOR"] = "1"
        return env

    def _execute_patch_tool(self, operation: AgentOperation) -> AgentExecutionResult:
        args = dict(operation.args or {})
        patch_text = str(args.get("patch") or "")
        if not patch_text.strip():
            raise RuntimeError("patch is required")
        started = time.time()
        parsed = self.sandbox.parse_patch(patch_text)
        touched, applied_diff = self._apply_workspace_unified_patch(parsed)
        artifact = self.record_artifact(
            "Agent patch applied diff",
            _clip_operation_output(applied_diff or patch_text),
            kind="diff",
        )
        touched_text = "\n".join(str(path.relative_to(self.workspace_root)).replace("\\", "/") for path in touched)
        raw = "\n".join(part for part in [f"touched files:\n{touched_text}", applied_diff or patch_text] if part).strip()
        return AgentExecutionResult(
            status="completed",
            summary=f"apply_patch completed for {len(touched)} file(s).",
            raw_output=_clip_operation_output(raw),
            exit_code=0,
            artifact_ids=[artifact.id],
            duration_ms=int((time.time() - started) * 1000),
        )

    def _apply_workspace_unified_patch(self, parsed: List[Dict[str, Any]]) -> tuple[List[Path], str]:
        touched: List[Path] = []
        diff_parts: List[str] = []
        pending_writes: List[tuple[Path, str]] = []
        for entry in parsed:
            target = entry["new_path"]
            original_lines = target.read_text(encoding="utf-8", errors="replace").splitlines() if target.exists() else []
            new_lines = self._apply_patch_hunks(original_lines, entry["hunks"], target)
            before_text = self._lines_to_text(original_lines)
            after_text = self._lines_to_text(new_lines)
            if before_text == after_text:
                raise RuntimeError(f"patch makes no changes: {target.relative_to(self.workspace_root)}")
            rel = str(target.relative_to(self.workspace_root)).replace("\\", "/")
            diff_parts.extend(difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=f"a/{rel}" if entry.get("old_path") else "/dev/null",
                tofile=f"b/{rel}",
                lineterm="",
            ))
            pending_writes.append((target, after_text))
            touched.append(target)
        for target, content in pending_writes:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        return touched, "\n".join(diff_parts).strip() + ("\n" if diff_parts else "")

    def _apply_patch_hunks(self, original_lines: List[str], hunks: List[Dict[str, Any]], target: Path) -> List[str]:
        result: List[str] = []
        cursor = 0
        for hunk in hunks:
            old_start = int(hunk.get("old_start") or 0)
            target_index = max(old_start - 1, 0)
            if target_index < cursor:
                raise RuntimeError(f"overlapping patch hunks for {target.relative_to(self.workspace_root)}")
            result.extend(original_lines[cursor:target_index])
            local_cursor = target_index
            for raw_line in hunk.get("lines") or []:
                marker = raw_line[:1]
                text = raw_line[1:]
                if marker == " ":
                    if local_cursor >= len(original_lines) or original_lines[local_cursor] != text:
                        raise RuntimeError(f"patch context mismatch for {target.relative_to(self.workspace_root)}")
                    result.append(original_lines[local_cursor])
                    local_cursor += 1
                elif marker == "-":
                    if local_cursor >= len(original_lines) or original_lines[local_cursor] != text:
                        raise RuntimeError(f"patch removal mismatch for {target.relative_to(self.workspace_root)}")
                    local_cursor += 1
                elif marker == "+":
                    result.append(text)
                else:
                    raise RuntimeError("invalid unified diff hunk line")
            cursor = local_cursor
        result.extend(original_lines[cursor:])
        return result

    def _lines_to_text(self, lines: List[str]) -> str:
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def _resolve_workspace_dir(self, value: Any) -> Path:
        return self.sandbox.resolve_workspace_dir(value)

    def _timeout_seconds(self, value: Any, default: int) -> float:
        try:
            timeout = float(value)
        except Exception:
            timeout = float(default)
        return max(1.0, min(timeout, 1800.0))

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return agent_session_to_dict(self.session)

    def _append_step(self, step: AgentStep) -> None:
        with self.lock:
            self.session.steps.append(step)
            self.session.steps = self.session.steps[-MAX_STEP_MEMORY:]
            if self.session.runs:
                self.session.runs[-1].steps.append(step)
                self.session.runs[-1].steps = self.session.runs[-1].steps[-MAX_STEP_MEMORY:]
            self._save_locked()

    def _emit(
        self,
        event_type: str,
        title: str,
        content: str,
        tone: str,
        tool: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = {
            "id": f"agent-runtime-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
            "type": event_type,
            "title": title,
            "content": content,
            "tone": tone,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "metadata": metadata or {},
        }
        if tool:
            event["tool"] = tool
        self.record_event(event)
        if self.publish:
            try:
                self.publish(event)
            except Exception:
                pass

    def _save_locked(self) -> None:
        self.store.save(self.session)

    def _plan_for(self, user_message: str, mode: str) -> str:
        text = str(user_message or "").strip()
        if mode == "retest":
            return (
                "1. 读取当前会话/断点状态。\n"
                "2. 选择复测工具或通报队列动作。\n"
                "3. 将每个工具调用、观察和产物写入统一 Agent 会话。"
            )
        if _looks_like_workspace_request(text):
            return (
                "1. 先用只读工程工具理解仓库状态。\n"
                "2. 如需写文件或执行命令，先发出审批请求。\n"
                "3. 汇总发现、风险和下一步建议。"
            )
        return (
            "1. 判断用户意图是复测、工程分析还是普通问答。\n"
            "2. 优先调用安全的只读工具获取事实。\n"
            "3. 需要副作用时先请求确认，再执行。"
        )


def _looks_like_workspace_request(message: str) -> bool:
    text = str(message or "").lower()
    keywords = (
        "代码", "仓库", "文件", "目录", "实现", "bug", "报错", "build", "test", "diff", "git",
        "read", "search", "workspace", "repo", "file", "command",
    )
    return any(keyword in text for keyword in keywords)


class HybridWorkspaceTools:
    """Read-only workspace tools plus approval stubs for mutating actions."""

    READ_TOOL_NAMES = {"workspace_tree", "read_file", "search_code", "inspect_git_diff", "summarize_file"}
    MUTATING_TOOL_NAMES = {"run_command", "apply_patch", "run_tests", "build_project"}

    def __init__(self, runtime: HybridAgentRuntime):
        self.runtime = runtime
        self.root = runtime.workspace_root

    def _spec_sandbox_summary(self, tool_name: str) -> str:
        return self.runtime.sandbox.summary_for_tool(tool_name)

    def tool_specs(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "workspace_tree",
                "description": "List files and directories under the current workspace root. Read-only.",
                "risk": "read",
                "requiresApproval": False,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("workspace_tree"),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative workspace path. Defaults to root."},
                        "max_entries": {"type": "integer", "description": "Maximum entries, default 120."},
                    },
                },
            },
            {
                "name": "read_file",
                "description": "Read a UTF-8 text file inside the workspace. Read-only.",
                "risk": "read",
                "requiresApproval": False,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("read_file"),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_chars": {"type": "integer", "description": "Maximum characters, default 12000."},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "search_code",
                "description": "Search text in workspace files. Read-only.",
                "risk": "read",
                "requiresApproval": False,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("search_code"),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                        "max_matches": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "inspect_git_diff",
                "description": "Inspect current git diff/stat for the workspace. Read-only.",
                "risk": "read",
                "requiresApproval": False,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("inspect_git_diff"),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "summarize_file",
                "description": "Read and summarize the shape of a source file. Read-only.",
                "risk": "read",
                "requiresApproval": False,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("summarize_file"),
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "run_command",
                "description": "Run a shell command inside the current workspace after user approval and command sandbox checks.",
                "risk": "command",
                "requiresApproval": True,
                "autoApprovalSupported": True,
                "defaultTimeoutSeconds": DEFAULT_COMMAND_TIMEOUT_SECONDS,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("run_command"),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {"type": "string", "description": "Workspace-relative directory. Defaults to root."},
                        "timeout_seconds": {"type": "integer"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "apply_patch",
                "description": "Apply a unified text diff inside the workspace after user approval.",
                "risk": "write",
                "requiresApproval": True,
                "autoApprovalSupported": True,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("apply_patch"),
                "parameters": {"type": "object", "properties": {"patch": {"type": "string"}}, "required": ["patch"]},
            },
            {
                "name": "run_tests",
                "description": "Run project tests after user approval. Defaults to the Hybrid Agent loop test.",
                "risk": "test",
                "requiresApproval": True,
                "autoApprovalSupported": True,
                "defaultTimeoutSeconds": DEFAULT_TEST_TIMEOUT_SECONDS,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("run_tests"),
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}}},
            },
            {
                "name": "build_project",
                "description": "Run project build checks after user approval. Defaults to npm.cmd run build and cargo check.",
                "risk": "build",
                "requiresApproval": True,
                "autoApprovalSupported": True,
                "defaultTimeoutSeconds": DEFAULT_BUILD_TIMEOUT_SECONDS,
                "workspaceOnly": True,
                "sandboxPolicySummary": self._spec_sandbox_summary("build_project"),
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}}},
            },
        ]

    def execute(self, name: str, args: Dict[str, Any], *, tool_call_id: str = "") -> str:
        args = args if isinstance(args, dict) else {}
        if name in self.MUTATING_TOOL_NAMES:
            preview = json.dumps(args, ensure_ascii=False, default=str)[:4000]
            risk = "command" if name == "run_command" else name.replace("_project", "").replace("run_", "")
            cwd = str(args.get("cwd") or "")
            call = self.runtime.record_tool_call(
                name,
                preview,
                label=name,
                risk=risk,
                requires_approval=True,
            )
            started = time.time()
            try:
                rejected = self.runtime.rejected_matching_operation(name, args, cwd)
                if rejected:
                    text = (
                        f"blocked_by_previous_rejection: {name} with the same arguments was already rejected by the user "
                        f"as {rejected.approval_id or rejected.id}. Do not request the identical approval again; "
                        "choose a read-only or narrower alternative and explain the limitation."
                    )
                    self.runtime.record_tool_result(
                        call,
                        text,
                        raw_output=text,
                        status="blocked",
                        tone="warn",
                        duration_ms=int((time.time() - started) * 1000),
                    )
                    return text
                sandbox_summary = self.runtime.sandbox.validate_tool_request(name, args)
                preview_artifact_id = ""
                if name == "apply_patch":
                    artifact = self.runtime.record_artifact(
                        "Agent patch preview",
                        _clip_operation_output(str(args.get("patch") or "")),
                        kind="diff",
                    )
                    preview_artifact_id = artifact.id
                detail = self._approval_detail(name, args, sandbox_summary)
            except Exception as exc:
                text = f"Sandbox rejected {name}: {exc}"
                self.runtime.record_tool_result(
                    call,
                    text,
                    raw_output=text,
                    status="failed",
                    tone="error",
                    duration_ms=int((time.time() - started) * 1000),
                )
                return text
            approval = self.runtime.request_approval(
                name,
                f"{name} requires approval",
                detail,
                preview,
                args=args,
                cwd=cwd,
                risk=risk,
                tool_call_id=call.id or tool_call_id,
                preview_artifact_id=preview_artifact_id,
                sandbox_summary=sandbox_summary,
            )
            call.approval_id = approval.id
            call.operation_id = approval.operation_id
            auto_approve = bool(self.runtime.session.auto_approve)
            result_marker = "auto_approved" if auto_approve else "approval_required"
            result_status = "approved" if auto_approve else "blocked"
            result_tone = "warn" if auto_approve else "warn"
            result_content = f"{result_marker}: {approval.id}"
            self.runtime.record_tool_result(
                call,
                result_content,
                raw_output=detail,
                status=result_status,
                tone=result_tone,
                duration_ms=int((time.time() - started) * 1000),
            )
            return result_content
        call = self.runtime.record_tool_call(name, json.dumps(args, ensure_ascii=False, default=str), label=name, risk="read")
        started = time.time()
        try:
            if name == "workspace_tree":
                text = self.workspace_tree(args.get("path") or "", int(args.get("max_entries") or 120))
            elif name == "read_file":
                text = self.read_file(str(args.get("path") or ""), int(args.get("max_chars") or 12000))
            elif name == "search_code":
                text = self.search_code(str(args.get("query") or ""), str(args.get("path") or ""), int(args.get("max_matches") or 80))
            elif name == "inspect_git_diff":
                text = self.inspect_git_diff()
            elif name == "summarize_file":
                text = self.summarize_file(str(args.get("path") or ""))
            else:
                text = f"Unknown workspace tool: {name}"
            self.runtime.record_tool_result(call, text[:4000], raw_output=text, duration_ms=int((time.time() - started) * 1000))
            return text
        except Exception as exc:
            text = f"Tool failed: {exc}"
            self.runtime.record_tool_result(call, text, raw_output=text, status="failed", tone="error", duration_ms=int((time.time() - started) * 1000))
            return text

    def _approval_detail(self, name: str, args: Dict[str, Any], sandbox_summary: str = "") -> str:
        policy_line = f" Sandbox: {sandbox_summary}" if sandbox_summary else ""
        if name == "run_command":
            command = str(args.get("command") or "").strip()
            cwd = str(args.get("cwd") or ".").strip() or "."
            return (
                "Run a workspace-scoped shell command after approval. "
                f"cwd={cwd}; command={command[:1000]}. "
                "The backend will still enforce command sandbox checks, timeout, output capture, and stop support."
                f"{policy_line}"
            )
        if name == "apply_patch":
            return (
                "Apply a unified text diff inside the workspace after approval. "
                "The backend rejects path escape, binary patches, and invalid diffs before writing."
                f"{policy_line}"
            )
        if name == "run_tests":
            command = str(args.get("command") or "").strip() or "default Hybrid Agent test command"
            return f"Run tests after approval: {command[:1000]}. Output will be captured in the Agent timeline.{policy_line}"
        if name == "build_project":
            command = str(args.get("command") or "").strip() or "default build checks: npm.cmd run build + cargo check"
            return f"Run build checks after approval: {command[:1000]}. Output will be captured in the Agent timeline.{policy_line}"
        return f"{name} requires approval before side effects are executed.{policy_line}"

    def workspace_tree(self, rel_path: str = "", max_entries: int = 120) -> str:
        base = self._resolve_path(rel_path or ".")
        if not base.exists():
            raise RuntimeError(f"path not found: {rel_path}")
        entries: List[str] = []
        count = 0
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            dirs[:] = [d for d in sorted(dirs) if d not in {".git", "node_modules", "__pycache__", ".koi_agent_sessions"}]
            for name in sorted(dirs) + sorted(files):
                item = root_path / name
                rel = item.relative_to(self.root)
                suffix = "/" if item.is_dir() else ""
                entries.append(str(rel).replace("\\", "/") + suffix)
                count += 1
                if count >= max(1, min(max_entries, 1000)):
                    return "\n".join(entries) + "\n...[truncated]"
        return "\n".join(entries) or "."

    def read_file(self, rel_path: str, max_chars: int = 12000) -> str:
        path = self._resolve_path(rel_path)
        if not path.is_file():
            raise RuntimeError(f"not a file: {rel_path}")
        data = path.read_text(encoding="utf-8", errors="replace")
        limit = max(1000, min(int(max_chars or 12000), 80000))
        if len(data) > limit:
            return data[:limit] + f"\n...[truncated {len(data) - limit} chars]"
        return data

    def search_code(self, query: str, rel_path: str = "", max_matches: int = 80) -> str:
        needle = str(query or "")
        if not needle:
            raise RuntimeError("query is required")
        base = self._resolve_path(rel_path or ".")
        matches: List[str] = []
        limit = max(1, min(int(max_matches or 80), 500))
        for path in self._iter_text_files(base):
            try:
                for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if needle.lower() in line.lower():
                        rel = path.relative_to(self.root)
                        rel_text = str(rel).replace("\\", "/")
                        matches.append(f"{rel_text}:{lineno}: {line[:300]}")
                        if len(matches) >= limit:
                            return "\n".join(matches) + "\n...[truncated]"
            except Exception:
                continue
        return "\n".join(matches) or "No matches."

    def inspect_git_diff(self) -> str:
        commands = [
            ["git", "status", "--short"],
            ["git", "diff", "--stat"],
            ["git", "diff", "--", ":!*.lock"],
        ]
        parts: List[str] = []
        for command in commands:
            try:
                proc = subprocess.run(command, cwd=str(self.root), capture_output=True, text=True, timeout=10)
                output = (proc.stdout or proc.stderr or "").strip()
                parts.append(f"$ {' '.join(command)}\n{output[:12000]}")
            except Exception as exc:
                parts.append(f"$ {' '.join(command)}\nfailed: {exc}")
        return "\n\n".join(parts)

    def summarize_file(self, rel_path: str) -> str:
        text = self.read_file(rel_path, 30000)
        lines = text.splitlines()
        defs = []
        for idx, line in enumerate(lines, 1):
            if re.match(r"\s*(class|def|function|export function|const|interface|type)\s+[\w$]+", line):
                defs.append(f"{idx}: {line.strip()}")
        return "\n".join([
            f"file: {rel_path}",
            f"lines: {len(lines)}",
            "symbols:",
            "\n".join(defs[:80]) or "(no obvious symbols found)",
            "preview:",
            "\n".join(lines[:80]),
        ])

    def _resolve_path(self, rel_path: str) -> Path:
        raw = str(rel_path or ".").strip()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except Exception as exc:
            raise RuntimeError("path escapes workspace root") from exc
        return resolved

    def _iter_text_files(self, base: Path) -> Iterable[Path]:
        if base.is_file():
            yield base
            return
        skip_dirs = {".git", "node_modules", "__pycache__", ".koi_agent_sessions", "dist", "build"}
        skip_suffix = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".exe", ".dll", ".db", ".zip", ".rar", ".7z", ".pdf"}
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() in skip_suffix:
                    continue
                yield path


HYBRID_AGENT_FALLBACK_SYSTEM = """你是 KOI Hybrid Agent，一个保守的工程分析助手。

工作方式：
1. 每轮先用简短计划说明你要验证什么。
2. 必须基于真实工具观察回答；不要编造文件、命令输出或测试结果。
3. 第一版工程能力默认只读。可以使用 workspace_tree/read_file/search_code/inspect_git_diff/summarize_file。
4. run_command/apply_patch/run_tests/build_project 会发起审批，不会直接执行；需要副作用时先解释原因并调用对应工具触发审批。
5. 工具返回后，先反思观察是否足够，再给出简洁最终回复。
"""


HYBRID_AGENT_FALLBACK_SYSTEM = """You are KOI Hybrid Agent, a conservative coding and analysis agent for the current workspace.
Start each turn with a short plan, gather real observations through tools, reflect briefly after tool results, and finish with a concise grounded answer.
Read-only tools may be used directly. Side-effect tools (run_command, apply_patch, run_tests, build_project) require user approval first.
After approval, the backend still enforces workspace-only sandbox checks, patch validation, command policy, timeouts, output capture, and stop/cancel support.
Do not invent file contents, command output, diffs, test results, or repository state."""


class HybridAgentLoop:
    """Model-driven plan -> tool -> observation -> reflection -> final loop."""

    DEFAULT_MAX_ROUNDS = 8
    MAX_NO_TOOL_NUDGES = 2
    MAX_CONTEXT_MESSAGES = 40

    def __init__(
        self,
        runtime: HybridAgentRuntime,
        client: Any,
        system_prompt: str = "",
        *,
        max_rounds: int | None = None,
        stop_check: Callable[[], bool] | None = None,
    ):
        self.runtime = runtime
        self.client = client
        self.system_prompt = str(system_prompt or "").strip() or HYBRID_AGENT_FALLBACK_SYSTEM
        self.tools = HybridWorkspaceTools(runtime)
        self.max_rounds = max(3, min(int(max_rounds or self.DEFAULT_MAX_ROUNDS), 20))
        self.stop_check = stop_check

    def _should_stop(self) -> bool:
        if not callable(self.stop_check):
            return False
        try:
            return bool(self.stop_check())
        except Exception:
            return False

    def run(self, message: str) -> Dict[str, Any]:
        if hasattr(self.client, "is_ready") and not self.client.is_ready():
            raise RuntimeError("AI Agent 未配置 provider/api_key/model")

        run = self.runtime.begin_run(message, mode="hybrid", emit_plan=False)
        messages = self._initial_messages(message)
        self.runtime.append_conversation({"role": "user", "content": str(message or "")})

        no_tool_calls = 0
        saw_tool_result = False
        final_message = ""
        status = "completed"
        approval_id = ""
        operation_id = ""

        try:
            for round_index in range(self.max_rounds):
                if self._should_stop():
                    final_message = "Agent 已按用户指令停止，未继续调用工具。"
                    status = "stopped"
                    self.runtime.record_status("Agent 已停止", final_message, "warn", metadata={"runId": run.id, "phase": "stop"})
                    break
                reply = self.client.chat(messages, self.tools.tool_specs())
                if self._should_stop():
                    final_message = "Agent 已按用户指令停止，模型晚到结果已丢弃。"
                    status = "stopped"
                    self.runtime.record_status("Agent 已停止", final_message, "warn", metadata={"runId": run.id, "phase": "stop"})
                    break
                content = str(reply.get("content") or "").strip()
                thinking = str(reply.get("thinking") or "").strip()
                tool_calls = [dict(item) for item in (reply.get("tool_calls") or []) if isinstance(item, dict)]

                if thinking:
                    self.runtime.record_thought("Agent 反思", thinking[:3000], metadata={"round": round_index, "runId": run.id})

                if round_index == 0:
                    self.runtime.record_plan(run, content or "读取必要上下文，调用只读工具验证事实，再基于观察回复。")
                elif content:
                    self.runtime.record_thought("Agent 反思", content[:3000], metadata={"round": round_index, "runId": run.id})

                assistant_message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
                messages.append(assistant_message)
                self.runtime.append_conversation(assistant_message)

                if not tool_calls:
                    if saw_tool_result:
                        final_message = content or "已根据工具观察完成分析。"
                        self.runtime.record_chat("Agent", final_message[:6000], "ok", metadata={"runId": run.id})
                        break
                    no_tool_calls += 1
                    if no_tool_calls <= self.MAX_NO_TOOL_NUDGES:
                        nudge = (
                            "请先调用至少一个只读工具获取真实上下文；如果确实需要写文件或执行命令，"
                            "请调用对应工具发起审批。"
                        )
                        messages.append({"role": "user", "content": nudge})
                        continue
                    final_message = content or "模型没有调用工具，已停止本轮以避免空转。"
                    self.runtime.record_chat("Agent", final_message[:6000], "warn", metadata={"runId": run.id, "noToolCalls": True})
                    break

                no_tool_calls = 0
                for raw_call in tool_calls:
                    if self._should_stop():
                        final_message = "Agent 已按用户指令停止，未执行新的工具调用。"
                        status = "stopped"
                        break
                    name = str(raw_call.get("name") or "")
                    args = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
                    call_id = str(raw_call.get("id") or f"call_{round_index}_{len(messages)}")
                    result_text = self.tools.execute(name, args, tool_call_id=call_id)
                    saw_tool_result = True
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": str(result_text)[:16000],
                    })
                    self.runtime.append_conversation({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": str(result_text)[:16000],
                    })
                    result_text_value = str(result_text)
                    if result_text_value.startswith("approval_required:") or result_text_value.startswith("auto_approved:"):
                        marker, raw_approval_id = result_text_value.split(":", 1)
                        approval_id = raw_approval_id.strip()
                        approval = self.runtime.approval_request(approval_id)
                        operation_id = approval.operation_id if approval else ""
                        if marker == "auto_approved":
                            final_message = (
                                f"{name} 已通过 sandbox 检查，且自动审批已开启；"
                                f"后端将启动 operation：{operation_id or approval_id}"
                            )
                            self.runtime.record_chat(
                                "Agent",
                                final_message,
                                "warn",
                                metadata={"runId": run.id, "approvalId": approval_id, "operationId": operation_id, "autoApproved": True},
                            )
                            status = "running"
                            self.runtime.finish_run(run, status)
                            return self._result(run, final_message, status, approval_id, operation_id, auto_approved=True)
                        final_message = f"{name} 需要用户审批，已创建审批请求：{approval_id}"
                        self.runtime.record_chat(
                            "Agent",
                            final_message,
                            "warn",
                            metadata={"runId": run.id, "approvalId": approval_id, "operationId": operation_id},
                        )
                        status = "blocked"
                        self.runtime.finish_run(run, status)
                        return self._result(run, final_message, status, approval_id, operation_id)

                if status == "stopped":
                    break

                messages.append({
                    "role": "user",
                    "content": "请根据刚才的工具观察做简短反思；如果信息足够，直接给最终回复；如果不足，再调用下一个最小必要工具。",
                })

            if not final_message and status != "stopped":
                final_message = "本轮已达到 Agent 最大循环次数，已停止以避免空转。请缩小问题或继续发下一条指令。"
                status = "incomplete"
                self.runtime.record_chat("Agent", final_message, "warn", metadata={"runId": run.id, "maxRounds": self.max_rounds})
            self.runtime.finish_run(run, status)
            return self._result(run, final_message, status, approval_id, operation_id)
        except Exception:
            self.runtime.finish_run(run, "failed")
            raise

    def _initial_messages(self, message: str) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        memory = str(self.runtime.session.compact_memory or self.runtime.session.memory_markdown or "").strip()
        if memory:
            messages.append({"role": "user", "content": f"[持久化记忆]\n{memory[:12000]}"})
        messages.extend(self.runtime.conversation_messages(self.MAX_CONTEXT_MESSAGES))
        messages.append({"role": "user", "content": str(message or "")})
        return messages

    def _result(
        self,
        run: AgentRun,
        final_message: str,
        status: str,
        approval_id: str = "",
        operation_id: str = "",
        *,
        auto_approved: bool = False,
    ) -> Dict[str, Any]:
        return {
            "success": status not in {"failed"},
            "run_id": run.id,
            "final_message": final_message,
            "message": final_message,
            "blocked": status == "blocked",
            "running": status == "running",
            "status": status,
            "approval_id": approval_id,
            "operation_id": operation_id,
            "auto_approved": auto_approved,
            "agent_session": self.runtime.snapshot(),
        }
