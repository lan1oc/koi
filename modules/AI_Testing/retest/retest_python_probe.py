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
import traceback
import types
import uuid as _uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
import urllib as urllib_package
import urllib.parse as urllib_parse
from urllib.parse import parse_qs, quote, urlencode, unquote, urljoin, urlparse

import requests

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

    # 复测只需要最小充分验证，不允许把探针退化成扫描器或绕过脚本。
    MAX_UPLOAD_BYTES = 64 * 1024 * 1024
    MAX_REQUESTS = 20
    MAX_RANGE_ITEMS = 200

    _WAF_BYPASS_PATTERNS = (
        r"\bbypass\s+(?:the\s+)?waf\b",
        r"\bwaf\s+bypass\b",
        r"\bevade\s+(?:the\s+)?waf\b",
        r"绕过\s*waf",
        r"规避\s*waf",
        r"绕开\s*waf",
        r"--tamper(?:=|\s)",
        r"\b(?:space2comment|randomcase|charencode)\.py\b",
    )
    _DIRECT_NETWORK_IMPORTS = {
        "socket", "urllib3", "urllib.request", "http", "http.client", "aiohttp", "httpx", "ftplib",
        "smtplib", "websocket", "websockets", "requests.sessions",
    }

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

        waf_hit = next(
            (pattern for pattern in self._WAF_BYPASS_PATTERNS if re.search(pattern, code, flags=re.IGNORECASE)),
            "",
        )
        if waf_hit:
            return self._attach_script([self._info(
                "Python 探针包含 WAF 绕过意图，已拒绝执行",
                "复测只能重放通报原始请求/载荷或最小无害等价验证；被 WAF 拦截时应记录当前未能验证，不得尝试混淆或绕过。",
                tool_failed=True,
            )], code)

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

        allowed_targets = [target for target in self._dedupe(targets) if target.startswith(("http://", "https://"))]
        base_target = allowed_targets[0] if allowed_targets else ""
        allowed_origins = {
            f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            for parsed in (urlparse(target) for target in allowed_targets)
            if parsed.scheme.lower() in {"http", "https"} and parsed.netloc
        }

        records: List[Dict[str, Any]] = []
        exchanges: List[Dict[str, Any]] = []
        request_count = 0

        def resolve_target(raw_url: str) -> str:
            target = str(raw_url or "").strip()
            if base_target and (target.startswith("/") or not urlparse(target).netloc):
                target = urljoin(base_target, target)
            parsed = urlparse(target)
            origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" if parsed.scheme and parsed.netloc else ""
            if not origin or origin not in allowed_origins:
                allowed = ", ".join(sorted(allowed_origins)) or "无有效目标"
                raise RuntimeError(f"目标超出通报授权同源范围: {target}；允许范围: {allowed}")
            return target

        class ProbeResponse(dict):
            """忠实模拟 requests.Response 的响应壳。

            模型是在真实 requests 上训练的，会写 resp.raise_for_status() /
            resp.cookies / resp.elapsed / resp.reason 等。这里把这些常用属性/方法
            都补齐，避免脚本一写就撞 AttributeError。
            """

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
                    return int(self.get("status_code") or 0) < 400
                except Exception:
                    return False

            @property
            def is_redirect(self) -> bool:
                try:
                    return int(self.get("status_code") or 0) in (301, 302, 303, 307, 308)
                except Exception:
                    return False

            @property
            def elapsed(self) -> _datetime.timedelta:
                try:
                    return _datetime.timedelta(milliseconds=float(self.get("elapsed_ms") or 0))
                except Exception:
                    return _datetime.timedelta(0)

            def json(self, **kwargs: Any) -> Any:
                return json.loads(str(self.get("text") or "{}"))

            def raise_for_status(self) -> "ProbeResponse":
                code = int(self.get("status_code") or 0)
                if 400 <= code:
                    raise requests.exceptions.HTTPError(
                        f"{code} Error for url: {self.get('final_url') or ''}", response=None,
                    )
                return self

            def iter_lines(self, *args: Any, **kwargs: Any) -> Any:
                return iter(str(self.get("text") or "").splitlines())

            def iter_content(self, *args: Any, **kwargs: Any) -> Any:
                return iter([str(self.get("text") or "").encode("utf-8", errors="ignore")])

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
            if request_count >= self.MAX_REQUESTS:
                raise RuntimeError(f"Python 探针 HTTP 请求数已达上限 {self.MAX_REQUESTS}，请用已有证据结束复测")
            request_count += 1
            target = resolve_target(url)

            started = time.time()
            method_name = str(method or "GET").upper()
            request_headers = {str(k): str(v) for k, v in (headers or {}).items() if str(k).lower() not in {"host", "content-length"}}
            kwargs: Dict[str, Any] = {
                "headers": request_headers,
                "timeout": min(self.timeout, 12),
                # 禁止底层自动跟随重定向，避免下一跳在校验前越出同源范围。
                "allow_redirects": False,
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
            # 本次响应的 Set-Cookie 与底层 session 累计的 cookie（同一真实 session
            # 跨请求自动保持，越权/IDOR 复测的“先登录再访问”链路据此成立）。
            try:
                response_cookies = dict(response.cookies)
            except Exception:
                response_cookies = {}
            try:
                session_cookies = self.session.cookies.get_dict()
            except Exception:
                session_cookies = {}
            return ProbeResponse({
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": (response.text or "")[:20000],
                "text_preview": (response.text or "")[:1000],
                "response_body_preview": exchange.get("response_body_preview") or "",
                "final_url": response.url,
                "content_length": meta.get("content_length"),
                "elapsed_ms": meta.get("elapsed_ms"),
                "reason": str(getattr(response, "reason", "") or ""),
                "encoding": str(getattr(response, "encoding", "") or ""),
                "apparent_encoding": str(getattr(response, "apparent_encoding", "") or ""),
                "cookies": response_cookies,
                "session_cookies": session_cookies,
            })

        session_ref = self.session

        class BoundedRequests:
            # 暴露真实 requests 的异常/工具，让脚本的 try/except requests.exceptions.X
            # 能真正捕获到底层 self.session 抛出的异常（假异常类是 catch 不住真异常的）。
            exceptions = requests.exceptions
            utils = requests.utils
            RequestException = requests.exceptions.RequestException
            Timeout = requests.exceptions.Timeout
            ConnectionError = requests.exceptions.ConnectionError
            HTTPError = requests.exceptions.HTTPError
            TooManyRedirects = requests.exceptions.TooManyRedirects

            def __init__(self, default_headers: Optional[Dict[str, Any]] = None):
                self.headers: Dict[str, Any] = {str(k): str(v) for k, v in (default_headers or {}).items()}

            @property
            def cookies(self) -> Any:
                # 读底层真实 session 的 cookie jar：登录后 Set-Cookie 已自动保持，
                # 越权/IDOR 脚本可据此确认会话态。
                return getattr(session_ref, "cookies", {})

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

            def head(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                kwargs.setdefault("allow_redirects", False)
                return http_request("HEAD", url, **self._kwargs(kwargs))

            def options(self, url: str, **kwargs: Any) -> Dict[str, Any]:
                return http_request("OPTIONS", url, **self._kwargs(kwargs))

            def close(self) -> None:
                return None

            def __enter__(self) -> "BoundedRequests":
                return self

            def __exit__(self, *args: Any) -> bool:
                return False

            def Session(self) -> "BoundedRequests":
                return BoundedRequests(dict(self.headers))

        def record(
            title: str,
            severity: str = "info",
            detail: str = "",
            evidence: str = "",
            manual_required: bool = False,
            relation: str = "",
            verdict_support: str = "",
        ) -> None:
            normalized = str(severity or "info").lower()
            if normalized not in {"info", "low", "medium", "high"}:
                normalized = "info"
            normalized_relation = str(relation or "").strip().lower()
            if normalized_relation not in {"reported_vulnerability", "side_observation"}:
                normalized_relation = ""
            normalized_support = str(verdict_support or "").strip().lower()
            if normalized_support not in {"reproduced", "not_reproduced", "inconclusive"}:
                normalized_support = ""
            item = {
                "type": str(title or "Python 探针结果"),
                "severity": normalized,
                "detail": str(detail or ""),
                "evidence": str(evidence or "")[:2000],
                "relation": normalized_relation,
                "verdict_support": normalized_support,
                "source": "context",
                "manual_required": False,
                "python_probe": True,
            }
            if exchanges:
                item.update(exchanges[-1])
            records.append(item)

        def safe_range(*args: int) -> range:
            result = range(*[int(item) for item in args])
            if len(result) > self.MAX_RANGE_ITEMS:
                raise RuntimeError(
                    f"Python 探针单个 range 超过 {self.MAX_RANGE_ITEMS} 次；复测禁止大字典、逐字符提取或探索性扫描"
                )
            return result

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
            if any(
                module_name == blocked or module_name.startswith(blocked + ".")
                for blocked in self._DIRECT_NETWORK_IMPORTS
            ):
                raise ImportError(
                    f"禁止直接导入网络模块 {module_name}；请使用受同源限制的 requests/http_request"
                )
            return _real_import(name, globals_value, locals_value, fromlist, level)

        # 保留常规 Python 能力，但所有 HTTP 都必须经过上面的同源请求壳。
        full_builtins = dict(vars(_builtins))
        full_builtins["print"] = lambda *args, **kwargs: None
        full_builtins["__import__"] = safe_import
        full_builtins["range"] = safe_range
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
            # 回传带脚本行号的精简 traceback，让模型能定位并一次改对，而不是盲改。
            detail = self._format_probe_error(exc, code)
            return self._attach_script([self._info("Python 探针执行失败", detail, tool_failed=True)], code)

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

    def _format_probe_error(self, exc: Exception, code: str) -> str:
        """把脚本运行异常整理成带行号的精简报错，供模型定位并一次改对。

        只保留脚本自身（<koi-python-probe>）的帧，并把出错行原文附上；
        runner 内部帧不暴露，避免噪声。
        """
        script_lines = str(code or "").splitlines()
        try:
            frames = traceback.extract_tb(exc.__traceback__)
        except Exception:
            frames = []
        located: List[str] = []
        for frame in frames:
            if frame.filename != "<koi-python-probe>":
                continue
            lineno = frame.lineno or 0
            src = ""
            if 1 <= lineno <= len(script_lines):
                src = script_lines[lineno - 1].strip()
            func = frame.name or "?"
            located.append(f"  第 {lineno} 行 (in {func}): {src}" if src else f"  第 {lineno} 行 (in {func})")
        header = f"{exc.__class__.__name__}: {exc}"
        if located:
            return header + "\n出错位置（脚本内）:\n" + "\n".join(located[-5:])
        return header

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
