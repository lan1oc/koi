#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""High-privilege Python HTTP probe for AI-planned black-box retest steps.

This is not a security sandbox. The runner is intended for authorized retest
HTTP probes and asks for user confirmation before local destructive operations.
"""

from __future__ import annotations

import ast
import base64
import builtins as _builtins
import binascii
import codecs
import collections
import datetime as _datetime
import difflib
import hashlib
import hmac
import html
import itertools
import json
import math
import random
import re
import string as _string
import struct
import textwrap
import time
import types
import uuid as _uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
import urllib as urllib_package
import urllib.parse as urllib_parse
from urllib.parse import parse_qs, quote, urlencode, unquote, urljoin, urlparse

import xml.etree.ElementTree as _ElementTree

from modules.AI_Testing.retest.retest_http_evidence import build_http_exchange


class RetestPythonProbeRunner:
    """Run an AI-provided HTTP probe for the reported target scope.

    The script must define:

        def run(targets, context):
            ...

    The runner deliberately does not decide whether a vulnerability is
    reproduced. It only executes the model's HTTP test plan, records request /
    response evidence. It is a high-privilege helper, not a sandbox; local
    destructive operations are intercepted and routed through user approval.
    """

    # 无限制：脚本长度 / 记录数 / 请求数 / 循环次数均不再设上限。
    # 仅保留上传体大小（避免单次构造超大 body 把内存撑爆，非安全限制）。
    MAX_UPLOAD_BYTES = 64 * 1024 * 1024

    # 唯一红线：会破坏【本机电脑】的操作（删/改本机文件、起本机进程、关机等）。
    # 命中时默认拒绝执行并把原因回传给模型，促使其改写脚本去掉该操作——
    # 网络/计算/渗透能力完全不受影响。
    _LOCAL_DESTRUCTIVE_PATTERNS = (
        # 进程/命令执行（在本机起进程）
        r"\bos\.(system|popen|exec[lv]?[pe]*|spawn\w*|startfile|remove|unlink|rmdir|removedirs|rename|replace|truncate|chmod|chown|kill|killpg|abort)\b",
        r"\bsubprocess\.(run|call|check_call|check_output|Popen|getoutput|getstatusoutput)\b",
        r"\bshutil\.(rmtree|move|copy\w*|rmtree|chown|disk_usage)\b",
        r"\bpathlib\b.*\.(unlink|rmdir|write_text|write_bytes|rename|replace|chmod)\b",
        # 写/删本机文件（open 以写/追加模式）
        r"\bopen\s*\([^)]*['\"][^'\"]*['\"]\s*,\s*['\"][rwa+xb]*[wax+][rwa+xb]*['\"]",
        r"\bos\.remove\b|\bos\.unlink\b|\bos\.rmdir\b",
        # 关机/重启/系统级
        r"\bos\.(_exit|abort)\b|shutdown|reboot|poweroff",
        # 通过 ctypes 直接调系统 API
        r"\bctypes\.(CDLL|WinDLL|windll|cdll|memmove|memset)\b",
    )
    # 预置模块对象（import 这些名字时优先返回这些对象；其余模块走真实 __import__ 全放行）。
    _ALLOWED_IMPORTS = {
        "json": json,
        "re": re,
        "html": html,
        "base64": base64,
        "binascii": binascii,
        "codecs": codecs,
        "collections": collections,
        "datetime": _datetime,
        "difflib": difflib,
        "hashlib": hashlib,
        "hmac": hmac,
        "itertools": itertools,
        "math": math,
        "random": random,
        "string": _string,
        "struct": struct,
        "textwrap": textwrap,
        "time": time,
        "uuid": _uuid,
        "urllib": urllib_package,
        "urllib.parse": urllib_parse,
        "xml.etree.ElementTree": _ElementTree,
    }

    def __init__(self, session: Any, timeout: int, meta_builder: Callable[[Any, float], Dict[str, Any]], confirm_callback: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None):
        self.session = session
        self.timeout = timeout
        self.meta_builder = meta_builder
        # 本机破坏性操作的人工确认回调：返回 {"decision": "approve"|"reject", "note": str}
        self.confirm_callback = confirm_callback

    def run_probe(self, script: str, context: Dict[str, Any], targets: Iterable[str]) -> List[Dict[str, Any]]:
        code = str(script or "").strip()
        if not code:
            return []

        # 红线检查：脚本含会破坏本机的操作时，暂停并请用户确认（人在回路）。
        # - 有确认回调：批准则按原脚本执行；拒绝则回传原因促模型改写。
        # - 无确认回调：默认拒绝并回传原因（安全兜底）。
        local_hit = self._detect_local_destructive(code)
        if local_hit:
            decision = "reject"
            note = ""
            if callable(self.confirm_callback):
                try:
                    outcome = self.confirm_callback({
                        "operation": "本机敏感/破坏性操作",
                        "matched": local_hit,
                        "detail": "复测只需对目标发 HTTP。该脚本含可能删改本机文件 / 起本机进程的代码。",
                        "script": code,
                    }) or {}
                    decision = str(outcome.get("decision") or "reject").lower()
                    note = str(outcome.get("note") or "")
                except Exception as exc:
                    decision = "reject"
                    note = f"确认流程异常：{exc}"
            if decision != "approve":
                return self._attach_script([self._info(
                    "Python 探针含本机破坏性操作，已按用户决定跳过",
                    f"检测到可能删改本机文件/起本机进程的操作：{local_hit}。"
                    f"{('用户拒绝执行：' + note) if note else '未获批准。'} "
                    f"请删除该本机操作后重试——复测目标只需对远端发 HTTP，无需碰本机文件/进程。",
                    tool_failed=True,
                )], code)
            # 已获用户批准：放行，按原脚本执行（含本机操作）。

        validation_error = self._validate(code)
        if validation_error:
            return self._attach_script([self._info("Python 探针脚本未通过安全校验", validation_error, tool_failed=True)], code)

        # 无同源限制：允许脚本请求任意目标。仍保留通报 URL 作为相对路径的拼接基准。
        allowed_targets = [target for target in self._dedupe(targets) if target.startswith(("http://", "https://"))]
        base_target = allowed_targets[0] if allowed_targets else ""

        records: List[Dict[str, Any]] = []
        exchanges: List[Dict[str, Any]] = []
        request_count = 0

        def resolve_target(raw_url: str) -> str:
            target = str(raw_url or "").strip()
            # 相对路径基于通报目标拼接；绝对地址原样放行，不做同源/端口校验。
            if base_target and (target.startswith("/") or not urlparse(target).netloc):
                target = urljoin(base_target, target)
            return target

        class ProbeResponse(dict):
            def __getattr__(self, name: str) -> Any:
                if name == "url":
                    return self.get("final_url")
                if name == "content":
                    return str(self.get("text") or "").encode("utf-8", errors="ignore")
                try:
                    return self[name]
                except KeyError as exc:
                    raise AttributeError(name) from exc

            @property
            def ok(self) -> bool:
                try:
                    return 200 <= int(self.get("status_code") or 0) < 400
                except Exception:
                    return False

            def json(self) -> Any:
                return json.loads(str(self.get("text") or "{}"))

        def http_request(
            method: str,
            url: str,
            headers: Optional[Dict[str, Any]] = None,
            body: Any = "",
            allow_redirects: bool = True,
            params: Optional[Dict[str, Any]] = None,
            data: Any = None,
            json_body: Any = None,
            files: Any = None,
            content_type: str = "",
        ) -> Dict[str, Any]:
            nonlocal request_count
            request_count += 1
            target = resolve_target(url)

            started = time.time()
            method_name = str(method or "GET").upper()
            request_headers = {str(k): str(v) for k, v in (headers or {}).items() if str(k).lower() not in {"host", "content-length"}}
            kwargs: Dict[str, Any] = {
                "headers": request_headers,
                "timeout": min(self.timeout, 12),
                "allow_redirects": bool(allow_redirects),
            }
            if isinstance(params, dict):
                kwargs["params"] = {str(key): str(value) for key, value in params.items()}
            request_body_preview = ""
            normalized_files = self._normalize_files(files)
            if normalized_files:
                kwargs["files"] = normalized_files
                if isinstance(data, dict):
                    kwargs["data"] = {str(key): str(value) for key, value in data.items()}
                request_body_preview = self._preview_upload_body(data, normalized_files)
            elif json_body is not None:
                kwargs["json"] = json_body
                request_body_preview = json.dumps(json_body, ensure_ascii=False, default=str)
            elif isinstance(data, dict):
                kwargs["data"] = {str(key): str(value) for key, value in data.items()}
                request_body_preview = urlencode({str(key): str(value) for key, value in data.items()})
            elif data is not None:
                request_body_preview = str(data)
                kwargs["data"] = request_body_preview.encode("utf-8")
            elif method_name in {"POST", "PUT", "PATCH", "DELETE"} and body:
                if isinstance(body, dict):
                    request_body_preview = urlencode({str(key): str(value) for key, value in body.items()})
                else:
                    request_body_preview = str(body)
                kwargs["data"] = request_body_preview.encode("utf-8")
            if content_type and not normalized_files:
                request_headers.setdefault("Content-Type", str(content_type))
                kwargs["headers"] = request_headers
            response = self.session.request(method_name, target, **kwargs)
            meta = self.meta_builder(response, started)
            exchange = build_http_exchange(method_name, response.url or target, request_headers, request_body_preview[:12000], response, meta)
            exchanges.append(exchange)
            return ProbeResponse({
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": (response.text or "")[:20000],
                "text_preview": (response.text or "")[:1000],
                "response_body_preview": exchange.get("response_body_preview") or "",
                "final_url": response.url,
                "content_length": meta.get("content_length"),
                "elapsed_ms": meta.get("elapsed_ms"),
            })

        class BoundedRequests:
            def __init__(self, default_headers: Optional[Dict[str, Any]] = None):
                self.headers: Dict[str, Any] = {str(k): str(v) for k, v in (default_headers or {}).items()}

            def _kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
                allowed = dict(kwargs)
                if "json" in allowed and "json_body" not in allowed:
                    allowed["json_body"] = allowed.pop("json")
                headers = {str(k): str(v) for k, v in self.headers.items()}
                if isinstance(allowed.get("headers"), dict):
                    headers.update({str(k): str(v) for k, v in (allowed.get("headers") or {}).items()})
                if headers:
                    allowed["headers"] = headers
                for ignored in ("timeout", "verify", "cookies", "auth", "proxies", "stream", "cert"):
                    allowed.pop(ignored, None)
                return allowed

            def request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request(method, url, **self._kwargs(kwargs))

            def get(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("GET", url, **self._kwargs(kwargs))

            def post(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("POST", url, **self._kwargs(kwargs))

            def put(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("PUT", url, **self._kwargs(kwargs))

            def patch(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("PATCH", url, **self._kwargs(kwargs))

            def delete(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("DELETE", url, **self._kwargs(kwargs))

            def Session(self) -> "BoundedRequests":
                return BoundedRequests(dict(self.headers))

        def record(title: str, severity: str = "info", detail: str = "", evidence: str = "", manual_required: bool = False) -> None:
            normalized = str(severity or "info").lower()
            if normalized not in {"info", "low", "medium", "high"}:
                normalized = "info"
            item = {
                "type": str(title or "Python 探针结果"),
                "severity": normalized,
                "detail": str(detail or ""),
                "evidence": str(evidence or "")[:2000],
                "source": "context",
                "manual_required": False,
                "python_probe": True,
            }
            if exchanges:
                item.update(exchanges[-1])
            records.append(item)

        def safe_range(*args: int) -> range:
            # 无限制：迭代次数不再裁剪（盲注逐字符提取、大字典循环按需进行）。
            return range(*[int(item) for item in args])

        bounded_requests = BoundedRequests()
        urllib_safe = types.SimpleNamespace(parse=urllib_parse)
        _real_import = _builtins.__import__
        safe_modules = {
            **self._ALLOWED_IMPORTS,
            "urllib": urllib_safe,
            "urllib.parse": urllib_parse,
            "requests": bounded_requests,
        }

        def safe_import(name: str, globals_value: Any = None, locals_value: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            module_name = str(name or "")
            # 预置对象优先（requests→受限会话壳，urllib→命名空间），其余任意模块全部放行。
            if module_name in safe_modules:
                module_value = safe_modules[module_name]
                if module_name == "urllib.parse" and not fromlist:
                    return urllib_safe
                return module_value
            # 无白名单限制：直接用真实 __import__ 导入任意模块（含 urllib3、ssl、socket 等）。
            return _real_import(name, globals_value, locals_value, fromlist, level)

        # 无限制：直接暴露完整真实 builtins（含 open/eval/exec/getattr/__import__ 等），
        # 脚本可写任意 Python。下面只覆盖少量便捷项（print 静默、range 不再裁剪）。
        full_builtins = dict(vars(_builtins))
        full_builtins["print"] = lambda *args, **kwargs: None
        full_builtins["__import__"] = safe_import
        helpers = {
            "__builtins__": full_builtins,
            "__name__": "koi_python_probe",
            "__package__": "",
            "requests": bounded_requests,
            "http": bounded_requests,
            "http_request": http_request,
            "record": record,
            "contains": lambda text, needle: str(needle).lower() in str(text).lower(),
            "lower": lambda text: str(text or "").lower(),
            "regex_search": lambda pattern, text: bool(re.search(str(pattern), str(text or ""), flags=re.IGNORECASE)),
            "join_url": lambda base, path: urljoin(str(base or ""), str(path or "")),
            "json_dumps": lambda value: json.dumps(value, ensure_ascii=False),
            "json_loads": lambda value: json.loads(str(value or "{}")),
            "form_encode": self._form_encode,
            "get_value": self._get_value,
            "parse_qs": parse_qs,
            "urlencode": urlencode,
            "quote": quote,
            "unquote": unquote,
            # 计时助手：时间盲注 / 命令注入延迟判断。
            # 注意：每次 http_request 返回的响应里已带 elapsed_ms，
            # 时间盲注优先直接读 resp["elapsed_ms"]，无需自己掐表。
            "now_ms": lambda: int(time.time() * 1000),
            "elapsed_since": lambda start_ms: int(time.time() * 1000) - int(start_ms),
            # 受控等待：上限 5s，防脚本卡死整个复测。
            "sleep": lambda seconds=0: time.sleep(min(max(float(seconds or 0), 0), 5)),
            # 编码助手：payload 构造常用。
            "b64encode": lambda value: base64.b64encode(str(value).encode("utf-8")).decode("ascii"),
            "b64decode": lambda value: base64.b64decode(str(value)).decode("utf-8", errors="ignore"),
            "url_encode": lambda value: quote(str(value or ""), safe=""),
            "url_decode": lambda value: unquote(str(value or "")),
            "html_escape": lambda value: html.escape(str(value or "")),
            "md5": lambda value: hashlib.md5(str(value).encode("utf-8")).hexdigest(),
            "sha1": lambda value: hashlib.sha1(str(value).encode("utf-8")).hexdigest(),
            "sha256": lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest(),
            "regex_findall": lambda pattern, text: re.findall(str(pattern), str(text or "")),
        }
        try:
            exec(compile(code, "<koi-python-probe>", "exec"), helpers, helpers)
            run_func = helpers.get("run")
            if not callable(run_func):
                return self._attach_script([self._info("Python 探针缺少 run 函数", "脚本必须定义 def run(targets, context)。", tool_failed=True)], code)
            run_func(allowed_targets, self._safe_context(context))
        except Exception as exc:
            return self._attach_script([self._info("Python 探针执行失败", str(exc), tool_failed=True)], code)

        if records:
            return self._attach_script(records, code)
        item = self._info("Python 探针未记录命中项", f"执行完成，请求 {request_count} 次。")
        if exchanges:
            item.update(exchanges[-1])
        return self._attach_script([item], code)

    def _detect_local_destructive(self, code: str) -> str:
        """检测脚本是否含会破坏【本机电脑】的操作（删改本机文件 / 起本机进程 / 关机等）。

        命中返回命中的代码片段描述，未命中返回空串。
        这是唯一红线：网络 / 计算 / 渗透能力完全不受影响，只拦本机破坏。
        """
        text = str(code or "")
        for pattern in self._LOCAL_DESTRUCTIVE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return ""

    def _validate(self, code: str) -> str:
        # 无限制：只做语法解析与 run 函数存在性检查，不再拦截任何 import / 名称 / 属性。
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return f"语法错误: {exc}"
        has_run = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
            for node in ast.walk(tree)
        )
        if not has_run:
            return "脚本必须定义 def run(targets, context)"
        return ""

    def _safe_import(self, name: str, globals_value: Any = None, locals_value: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if level:
            raise ImportError("relative import is not allowed")
        module_name = str(name or "")
        if module_name == "requests":
            return globals_value.get("requests") if isinstance(globals_value, dict) else None
        if module_name not in self._ALLOWED_IMPORTS:
            raise ImportError(f"module is not allowed: {module_name}")
        return self._ALLOWED_IMPORTS[module_name]

    def _origin_key(self, url: str) -> str:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").lower()
        if not parsed.scheme or not host:
            return ""
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        return f"{parsed.scheme.lower()}://{host}:{port}"

    def _normalize_files(self, value: Any) -> Dict[str, Any]:
        if not value:
            return {}
        if not isinstance(value, dict):
            raise RuntimeError("files 必须是 dict")
        files: Dict[str, Any] = {}
        for field, item in value.items():
            field_name = str(field)
            filename = f"{field_name}.txt"
            content: Any = ""
            content_type = "application/octet-stream"
            if isinstance(item, dict):
                filename = str(item.get("filename") or filename)
                content = item.get("content") if item.get("content") is not None else ""
                content_type = str(item.get("content_type") or item.get("mime") or content_type)
            elif isinstance(item, (list, tuple)):
                parts = list(item)
                if parts:
                    filename = str(parts[0])
                if len(parts) >= 2:
                    content = parts[1]
                if len(parts) >= 3:
                    content_type = str(parts[2])
            else:
                content = item
            if isinstance(content, str):
                data = content.encode("utf-8")
            elif isinstance(content, bytes):
                data = content
            else:
                data = str(content).encode("utf-8")
            if len(data) > self.MAX_UPLOAD_BYTES:
                raise RuntimeError(f"上传内容超过限制 {self.MAX_UPLOAD_BYTES} bytes: {filename}")
            files[field_name] = (filename, data, content_type)
        return files

    def _preview_upload_body(self, data: Any, files: Dict[str, Any]) -> str:
        lines = []
        if isinstance(data, dict) and data:
            lines.append("form_fields=" + json.dumps({str(k): str(v) for k, v in data.items()}, ensure_ascii=False)[:2000])
        for field, item in files.items():
            filename = item[0] if isinstance(item, tuple) and item else ""
            content = item[1] if isinstance(item, tuple) and len(item) > 1 else b""
            content_type = item[2] if isinstance(item, tuple) and len(item) > 2 else ""
            size = len(content or b"")
            digest = hashlib.sha256(content or b"").hexdigest()[:16]
            lines.append(f"file {field}: filename={filename}, content_type={content_type}, bytes={size}, sha256={digest}")
        return "\n".join(lines)

    def _attach_script(self, items: List[Dict[str, Any]], script: str) -> List[Dict[str, Any]]:
        for item in items:
            if isinstance(item, dict):
                item["python_probe_script"] = script
        return items

    def _safe_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "issue_tags": [str(item) for item in (context.get("issue_tags") or [])],
            "target_urls": [str(item) for item in (context.get("target_urls") or [])[:20]],
            "all_urls": [str(item) for item in (context.get("all_urls") or [])[:40]],
            "raw_text": str(context.get("raw_text") or "")[:20000],
            "path_candidates": [str(item) for item in (context.get("path_candidates") or [])[:20]],
            "parameter_names": [str(item) for item in (context.get("parameter_names") or [])[:20]],
            "expected_markers": [str(item) for item in (context.get("expected_markers") or [])[:20]],
            "expected_status_codes": [int(item) for item in (context.get("expected_status_codes") or []) if str(item).isdigit()],
            "credential_candidates": self._safe_credentials(context.get("credential_candidates") or []),
            "http_request_candidates": self._safe_http_requests(context.get("http_request_candidates") or []),
            "payload_candidates": self._safe_payloads(context.get("payload_candidates") or []),
            "page_observations": context.get("page_observations") or {},
            "tool_observations": context.get("tool_observations") or [],
        }

    def _info(self, detail: str, evidence: str = "", tool_failed: bool = False) -> Dict[str, Any]:
        return {
            "type": detail,
            "severity": "info",
            "detail": detail,
            "evidence": evidence,
            "source": "context",
            "manual_required": False,
            "tool_failed": bool(tool_failed),
            "python_probe": True,
        }

    def _dedupe(self, values: Iterable[str]) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for value in values:
            text = str(value or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
        return out

    def _form_encode(self, value: Any) -> str:
        try:
            from urllib.parse import urlencode

            if isinstance(value, dict):
                return urlencode({str(key): str(item) for key, item in value.items()})
        except Exception:
            return ""
        return str(value or "")

    def _get_value(self, source: Any, key: Any, default: Any = "") -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        if isinstance(source, list):
            try:
                return source[int(key)]
            except Exception:
                return default
        return default

    def _safe_credentials(self, values: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(values, list):
            return out
        for item in values[:8]:
            if not isinstance(item, dict):
                continue
            out.append({
                "username": str(item.get("username") or ""),
                "password": str(item.get("password") or ""),
                "password_masked": str(item.get("password_masked") or "***"),
                "evidence": str(item.get("evidence") or "")[:800],
            })
        return out

    def _safe_http_requests(self, values: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(values, list):
            return out
        for item in values[:12]:
            if not isinstance(item, dict):
                continue
            out.append({
                "method": str(item.get("method") or "GET")[:12],
                "url": str(item.get("url") or item.get("target") or "")[:1200],
                "headers": {str(k): str(v)[:1000] for k, v in (item.get("headers") or {}).items()} if isinstance(item.get("headers"), dict) else {},
                "body": str(item.get("body") or "")[:4000],
                "evidence_lines": [str(line)[:1000] for line in (item.get("evidence_lines") or [])[:12]],
            })
        return out

    def _safe_payloads(self, values: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(values, list):
            return out
        for item in values[:20]:
            if not isinstance(item, dict):
                continue
            out.append({
                "parameter": str(item.get("parameter") or "")[:200],
                "url": str(item.get("url") or "")[:1200],
                "raw": str(item.get("raw") or "")[:2000],
                "evidence": str(item.get("evidence") or "")[:1000],
            })
        return out
