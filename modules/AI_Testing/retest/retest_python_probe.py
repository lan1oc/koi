#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Restricted Python HTTP probe for AI-planned black-box retest steps."""

from __future__ import annotations

import ast
import base64
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
    """Run an AI-provided HTTP probe bounded to the reported target scope.

    The script must define:

        def run(targets, context):
            ...

    The runner deliberately does not decide whether a vulnerability is
    reproduced. It only executes the model's HTTP test plan, records request /
    response evidence, and enforces the retest target boundary.
    """

    MAX_SCRIPT_CHARS = 24000
    MAX_RECORDS = 60
    MAX_REQUESTS = 80
    MAX_UPLOAD_BYTES = 2 * 1024 * 1024

    # 唯一保留的边界：不让脚本碰【本机】OS / 文件 / 进程 / 任意网络栈。
    # 这对测任何 web 漏洞零损失（web 漏洞都是对目标发 HTTP + 看响应），
    # 只防大模型幻觉脚本误删本地文件、执行本地命令、连内网。
    _BLOCKED_NAMES = {
        "open", "eval", "exec", "compile", "input", "breakpoint", "help",
        "os", "sys", "subprocess", "socket", "pathlib", "shutil", "importlib",
        "builtins", "__builtins__", "__import__", "globals", "locals",
        "ctypes", "multiprocessing", "threading", "asyncio", "signal",
        "fileinput", "tempfile", "glob", "io", "pickle", "marshal", "shelve",
        "platform", "pty", "fcntl", "resource", "gc", "inspect",
    }
    # 危险 dunder：经由属性链做沙箱逃逸的常见跳板，仍然拦死。
    # 普通的单下划线 / 业务 dunder（如 __init__ 调用）不再一刀切禁。
    _BLOCKED_ATTRS = {
        "__class__", "__bases__", "__base__", "__mro__", "__subclasses__",
        "__globals__", "__code__", "__closure__", "__func__", "__self__",
        "__dict__", "__builtins__", "__import__", "__loader__", "__spec__",
        "__getattribute__", "__reduce__", "__reduce_ex__", "__subclasshook__",
        "__init_subclass__", "__class_getitem__", "__module__",
    }
    # 纯计算 / 编码 / 计时 / 解析类模块全部放开——渗透脚本需要它们。
    # 没有一个能逃逸到本机 OS。
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

    def __init__(self, session: Any, timeout: int, meta_builder: Callable[[Any, float], Dict[str, Any]]):
        self.session = session
        self.timeout = timeout
        self.meta_builder = meta_builder

    def run_probe(self, script: str, context: Dict[str, Any], targets: Iterable[str]) -> List[Dict[str, Any]]:
        code = str(script or "").strip()
        if not code:
            return []
        if len(code) > self.MAX_SCRIPT_CHARS:
            return self._attach_script([self._info("Python 探针脚本过长，已跳过", f"{len(code)} chars")], code)

        validation_error = self._validate(code)
        if validation_error:
            return self._attach_script([self._info("Python 探针脚本未通过安全校验", validation_error, tool_failed=True)], code)

        allowed_targets = [target for target in self._dedupe(targets) if target.startswith(("http://", "https://"))][:8]
        allowed_origins = {self._origin_key(target) for target in allowed_targets if self._origin_key(target)}
        if not allowed_targets or not allowed_origins:
            return self._attach_script([self._info("Python 探针缺少通报目标", "没有可用于受限脚本的 HTTP/HTTPS 通报 URL。")], code)

        records: List[Dict[str, Any]] = []
        exchanges: List[Dict[str, Any]] = []
        request_count = 0

        def resolve_target(raw_url: str) -> str:
            target = str(raw_url or "").strip()
            if target.startswith("/"):
                target = urljoin(allowed_targets[0], target)
            parsed = urlparse(target)
            if not parsed.scheme and not parsed.netloc:
                target = urljoin(allowed_targets[0], target)
            parsed = urlparse(target)
            origin = self._origin_key(target)
            if parsed.scheme not in {"http", "https"} or origin not in allowed_origins:
                raise RuntimeError(f"Python 探针目标不在通报范围: {target}")
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
            if request_count > self.MAX_REQUESTS:
                raise RuntimeError(f"Python 探针请求数超过限制 {self.MAX_REQUESTS}")
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
            if len(records) >= self.MAX_RECORDS:
                return
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
            values = [int(item) for item in args]
            # 放宽到 5000：盲注逐字符提取、字典循环都需要更多迭代。
            if len(values) == 1:
                values = [0, min(values[0], 5000)]
            elif len(values) >= 2:
                values[1] = min(values[1], values[0] + 5000)
            return range(*values)

        bounded_requests = BoundedRequests()
        urllib_safe = types.SimpleNamespace(parse=urllib_parse)
        safe_modules = {
            **self._ALLOWED_IMPORTS,
            "urllib": urllib_safe,
            "urllib.parse": urllib_parse,
            "requests": bounded_requests,
        }

        def safe_import(name: str, globals_value: Any = None, locals_value: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            if level:
                raise ImportError("relative import is not allowed")
            module_name = str(name or "")
            if module_name not in safe_modules:
                raise ImportError(f"module is not allowed: {module_name}")
            module_value = safe_modules[module_name]
            if module_name == "urllib.parse" and not fromlist:
                return urllib_safe
            return module_value

        helpers = {
            "__builtins__": {
                # 基础类型与转换
                "len": len, "str": str, "bytes": bytes, "bytearray": bytearray,
                "int": int, "float": float, "bool": bool, "complex": complex,
                "list": list, "dict": dict, "set": set, "frozenset": frozenset,
                "tuple": tuple, "type": type, "object": object,
                # 数值/进制/字符
                "min": min, "max": max, "sum": sum, "round": round, "abs": abs,
                "pow": pow, "divmod": divmod, "hex": hex, "oct": oct, "bin": bin,
                "chr": chr, "ord": ord, "format": format, "repr": repr, "ascii": ascii,
                # 迭代/序列
                "range": safe_range, "enumerate": enumerate, "zip": zip,
                "map": map, "filter": filter, "reversed": reversed, "sorted": sorted,
                "any": any, "all": all, "iter": iter, "next": next, "slice": slice,
                # 反射/属性（测越权、动态取字段常用，不再禁）
                "getattr": getattr, "setattr": setattr, "hasattr": hasattr,
                "isinstance": isinstance, "issubclass": issubclass, "callable": callable,
                "id": id, "hash": hash,
                # 异常体系（脚本要自己 try/except 分支判断）
                "Exception": Exception, "BaseException": BaseException,
                "ValueError": ValueError, "RuntimeError": RuntimeError,
                "KeyError": KeyError, "IndexError": IndexError, "TypeError": TypeError,
                "AttributeError": AttributeError, "StopIteration": StopIteration,
                "ZeroDivisionError": ZeroDivisionError, "ArithmeticError": ArithmeticError,
                "UnicodeDecodeError": UnicodeDecodeError, "AssertionError": AssertionError,
                # 常量
                "True": True, "False": False, "None": None,
                # 受控副作用
                "print": lambda *args, **kwargs: None,
                "__import__": safe_import,
            },
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

    def _validate(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return f"语法错误: {exc}"

        local_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local_names.add(node.name)
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    local_names.add(arg.arg)
                if node.args.vararg:
                    local_names.add(node.args.vararg.arg)
                if node.args.kwarg:
                    local_names.add(node.args.kwarg.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local_names.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local_names.add(str(node.name))

        has_run = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "run":
                    has_run = True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # 允许 import 顶层包后用点访问子模块（如 import urllib 再用 urllib.parse），
                    # 也允许直接 import 已登记的子模块（如 import xml.etree.ElementTree）。
                    top = alias.name.split(".")[0]
                    if (
                        alias.name not in self._ALLOWED_IMPORTS
                        and top not in self._ALLOWED_IMPORTS
                        and alias.name != "requests"
                    ):
                        return f"不允许 import 模块: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                module = str(node.module or "")
                top = module.split(".")[0]
                if node.level or (
                    module not in self._ALLOWED_IMPORTS
                    and top not in self._ALLOWED_IMPORTS
                    and module != "requests"
                ):
                    return f"不允许 from import 模块: {module}"
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in self._BLOCKED_NAMES
                and node.id not in local_names
            ):
                return f"不允许使用名称: {node.id}"
            # 只拦截可用于沙箱逃逸的危险 dunder 属性链，不再一刀切禁所有下划线属性。
            if isinstance(node, ast.Attribute) and node.attr in self._BLOCKED_ATTRS:
                return f"不允许访问属性: {node.attr}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 20000:
                return "字符串常量过长"
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
                item["python_probe_script"] = script[: self.MAX_SCRIPT_CHARS]
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
