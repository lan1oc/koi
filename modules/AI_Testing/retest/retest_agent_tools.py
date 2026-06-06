#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ReAct agent tool layer for black-box retest.

Unlike the legacy "pick a preset tool_id" approach, this layer exposes
真正可执行、可自由传参的工具给大模型（原生 function calling）：

- http_request        自由构造 method/headers/body/params（限通报目标同源）
- collect_page_context 采集页面 HTML/JS/表单/候选端点
- run_python_probe    运行受限 Python HTTP 探针（沿用现有 AST 沙箱）
- run_nmap/run_sqlmap/run_ffuf  调用本机外部工具（限通报主机，带超时）
- run_preset_check    复用既有 27 个只读复核工具（按 check_id 调度）
- record_finding      记录一条证据观察
- finish_investigation 结束取证，进入最终判定

所有工具仅作用于通报目标同源范围；执行结果通过 scanner._trace_event 推送 UI，
事件格式与既有保持一致，前端零改动。最终 verdict 仍由 judge_retest 决定，
本层只负责取证（产生 observations）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from modules.AI_Testing.retest.retest_http_evidence import build_http_exchange
from modules.AI_Testing.retest.retest_python_probe import RetestPythonProbeRunner
from modules.AI_Testing.retest.retest_external_tools import find_tool_command


_PRESET_CHECK_IDS = [
    "check_reported_url_access",
    "check_contextual_evidence",
    "check_context_paths",
    "check_auth_boundary",
    "check_directory_listing_signature",
    "check_sensitive_artifact_access",
    "check_source_map_exposure",
    "check_endpoint_fingerprint",
    "check_api_schema_exposure",
    "check_upload_artifact_access",
    "check_editor_endpoint_config",
    "check_http_request_replay",
    "check_payload_replay",
    "check_xss_reflection_replay",
    "check_file_read_signature_replay",
    "check_open_redirect_replay",
    "check_weak_password_login",
    "check_common_path_file_read",
    "check_header_disclosure",
    "check_security_headers",
    "check_http_methods",
    "check_tls_config",
    "check_url_content",
]


class RetestToolExecutor:
    """Bridge between the ReAct loop and the scanner's real capabilities.

    The executor binds to one scanner instance plus the current target URL /
    report context / probe response, and exposes a stable tool catalog with
    free-form parameters. Every execution stays bounded to the reported
    same-origin scope.
    """

    MAX_HTTP_BODY_PREVIEW = 8000

    def __init__(
        self,
        scanner: Any,
        url: str,
        context: Dict[str, Any],
        probe: Any,
    ) -> None:
        self.scanner = scanner
        self.url = url
        self.context = context or {}
        self.probe = probe
        self.session = scanner.session
        self.timeout = scanner.timeout
        self.records: List[Dict[str, Any]] = []
        self.executed_tools: List[str] = []
        self.finished = False
        self.finish_summary = ""
        self.allowed_origins = self._build_allowed_origins(url, self.context)
        self._http_count = 0
        self._max_http = 40
        self._probe_runner = RetestPythonProbeRunner(
            scanner.session, scanner.timeout, scanner._build_request_meta
        )

    # ------------------------------------------------------------------ scope

    @staticmethod
    def _origin_key(target: str) -> str:
        parsed = urlparse(str(target or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc.lower()}"

    def _build_allowed_origins(self, url: str, context: Dict[str, Any]) -> set:
        origins = set()
        key = self._origin_key(url)
        if key:
            origins.add(key)
        for target in (context.get("target_urls") or context.get("all_urls") or []):
            ok = self._origin_key(str(target))
            if ok:
                origins.add(ok)
        return origins

    def _resolve_target(self, raw_url: str) -> str:
        target = str(raw_url or "").strip()
        if not target:
            raise RuntimeError("缺少目标 URL")
        if target.startswith("/"):
            target = urljoin(self.url, target)
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc:
            target = urljoin(self.url, target)
        origin = self._origin_key(target)
        if not origin or origin not in self.allowed_origins:
            raise RuntimeError(f"目标不在通报范围（同源限制）: {target}")
        return target

    def _allowed_hosts(self) -> set:
        return {urlparse(o).netloc.split(":")[0].lower() for o in self.allowed_origins}

    # ------------------------------------------------------------- tool specs

    def tool_specs(self) -> List[Dict[str, Any]]:
        """统一格式工具目录，喂给 LLMClient.chat(tools=...)。"""
        specs: List[Dict[str, Any]] = [
            {
                "name": "http_request",
                "description": (
                    "对通报目标发起一次自定义 HTTP 请求，可自由指定方法、请求头、查询参数、"
                    "请求体（表单或 JSON）。仅允许请求通报目标同源 URL。返回状态码、响应头与正文预览。"
                    "这是最核心的复测工具，用于构造 PoC、验证漏洞、观察响应差异。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "description": "HTTP 方法，如 GET/POST/PUT/DELETE，默认 GET"},
                        "url": {"type": "string", "description": "目标 URL，可为同源绝对地址或 / 开头的路径"},
                        "headers": {"type": "object", "description": "自定义请求头键值对"},
                        "params": {"type": "object", "description": "URL 查询参数键值对"},
                        "body": {"type": "string", "description": "原始请求体字符串"},
                        "json_body": {"type": "object", "description": "JSON 请求体（与 body 二选一）"},
                        "follow_redirects": {"type": "boolean", "description": "是否跟随重定向，默认 true"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "collect_page_context",
                "description": (
                    "采集指定页面的 HTML、同源 JS bundle、表单字段和候选接口端点，"
                    "用于发现新的攻击面、参数和接口。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要采集的同源页面 URL，默认当前目标"},
                    },
                },
            },
            {
                "name": "run_python_probe",
                "description": (
                    "运行一段受限 Python HTTP 探针脚本，用于固定工具难以表达的多步验证逻辑。"
                    "脚本必须定义 def run(targets, context):，只能通过 http_request(...) 或预置的 "
                    "requests 对象访问通报目标同源 URL，并用 record(title, severity, detail, evidence) 记录证据。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "Python 探针脚本，含 def run(targets, context):"},
                        "reason": {"type": "string", "description": "为什么需要脚本、验证什么"},
                    },
                    "required": ["script"],
                },
            },
            {
                "name": "run_nmap",
                "description": (
                    "对通报目标主机执行 nmap 服务/端口探测（限通报主机）。仅在本机已安装 nmap 时可用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "flags": {"type": "string", "description": "nmap 参数，如 '-sV -Pn -p 80,443,8080'，默认 '-sV -Pn'"},
                    },
                },
            },
            {
                "name": "run_sqlmap",
                "description": (
                    "对通报目标 URL 执行 sqlmap SQL 注入验证（低风险、batch、不导出数据，限同源）。"
                    "仅在本机已安装 sqlmap 时可用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "带注入点的同源 URL"},
                        "data": {"type": "string", "description": "POST 数据（可选）"},
                        "flags": {"type": "string", "description": "附加 sqlmap 参数，如 '--level 2 --risk 1'（可选）"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "run_ffuf",
                "description": (
                    "对通报目标执行 ffuf 短名单路径发现（限同源，非大字典爆破）。"
                    "仅在本机已安装 ffuf 时可用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "含 FUZZ 关键字的同源 URL，如 https://host/FUZZ"},
                        "words": {"type": "array", "items": {"type": "string"}, "description": "短名单候选词（可选）"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "run_preset_check",
                "description": (
                    "调用一个内置只读复核工具（按通报上下文执行，无需手动传参）。"
                    "当你想快速复用成熟的复核逻辑时使用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "check_id": {
                            "type": "string",
                            "enum": _PRESET_CHECK_IDS,
                            "description": "要执行的内置复核工具 ID",
                        },
                    },
                    "required": ["check_id"],
                },
            },
            {
                "name": "record_finding",
                "description": (
                    "记录一条复测证据观察。当你通过上述工具确认了某个现象（无论是否构成漏洞复现），"
                    "用本工具留痕，供最终判定参考。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "观察标题"},
                        "severity": {"type": "string", "enum": ["info", "low", "medium", "high"], "description": "严重级别"},
                        "detail": {"type": "string", "description": "详细说明"},
                        "evidence": {"type": "string", "description": "关键证据（响应特征、状态码、回显等）"},
                    },
                    "required": ["title", "detail"],
                },
            },
            {
                "name": "finish_investigation",
                "description": (
                    "当你已收集到足够证据、可以进入最终复测判定时调用。提供一句话取证总结。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "取证过程与关键发现的简要总结"},
                    },
                    "required": ["summary"],
                },
            },
        ]
        return specs

    # --------------------------------------------------------------- dispatch

    def execute(self, name: str, args: Dict[str, Any]) -> str:
        """执行一次工具调用，返回给模型的文本结果。证据写入 self.records。"""
        args = args if isinstance(args, dict) else {}
        if name not in {"record_finding", "finish_investigation"}:
            self.executed_tools.append(name)
        try:
            if name == "http_request":
                return self._do_http_request(args)
            if name == "collect_page_context":
                return self._do_collect_page_context(args)
            if name == "run_python_probe":
                return self._do_python_probe(args)
            if name == "run_nmap":
                return self._do_nmap(args)
            if name == "run_sqlmap":
                return self._do_sqlmap(args)
            if name == "run_ffuf":
                return self._do_ffuf(args)
            if name == "run_preset_check":
                return self._do_preset_check(args)
            if name == "record_finding":
                return self._do_record_finding(args)
            if name == "finish_investigation":
                return self._do_finish(args)
            return f"未知工具: {name}"
        except Exception as exc:  # surface tool errors back to the model, don't crash the loop
            self._trace_tool_error(name, str(args)[:200], str(exc))
            return f"工具执行失败: {exc}"

    # --------------------------------------------------------------- handlers

    def _do_http_request(self, args: Dict[str, Any]) -> str:
        method = str(args.get("method") or "GET").upper()
        target = self._resolve_target(args.get("url") or self.url)
        if self._http_count >= self._max_http:
            return f"HTTP 请求数已达上限 {self._max_http}，请收敛验证或结束取证。"
        self._http_count += 1

        headers = {str(k): str(v) for k, v in (args.get("headers") or {}).items()
                   if str(k).lower() not in {"host", "content-length"}}
        kwargs: Dict[str, Any] = {
            "headers": headers,
            "timeout": min(self.timeout, 15),
            "allow_redirects": bool(args.get("follow_redirects", True)),
        }
        params = args.get("params")
        if isinstance(params, dict):
            kwargs["params"] = {str(k): str(v) for k, v in params.items()}
        body_preview = ""
        json_body = args.get("json_body")
        body = args.get("body")
        if json_body is not None:
            kwargs["json"] = json_body
            body_preview = json.dumps(json_body, ensure_ascii=False, default=str)
        elif body:
            kwargs["data"] = str(body).encode("utf-8")
            body_preview = str(body)
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        args_preview = f"{method} {target}"
        self._trace_call("http_request", "自定义 HTTP 请求", args_preview)
        started = time.time()
        response = self.session.request(method, target, **kwargs)
        meta = self.scanner._build_request_meta(response, started)
        exchange = build_http_exchange(method, response.url or target, headers, body_preview[:12000], response, meta)

        result_text = (
            f"HTTP {response.status_code}  ({meta.get('elapsed_ms')}ms)\n"
            f"final_url: {response.url}\n"
            f"len: {meta.get('content_length')}\n"
            f"--- response headers ---\n"
            + json.dumps(exchange.get("response_headers_safe") or {}, ensure_ascii=False, indent=2)[:2000]
            + "\n--- response body ---\n"
            + str(exchange.get("response_body_preview") or "")[:self.MAX_HTTP_BODY_PREVIEW]
        )
        self._trace_result(
            "http_request", "自定义 HTTP 请求", args_preview,
            f"HTTP {response.status_code}, len={meta.get('content_length')}",
            exchange=exchange, status_code=response.status_code, final_url=response.url,
            duration_ms=meta.get("elapsed_ms"), raw_output=result_text,
        )
        return result_text

    def _do_collect_page_context(self, args: Dict[str, Any]) -> str:
        target = self._resolve_target(args.get("url") or self.url)
        outputs = self.scanner._execute_agent_tool("collect_page_context", target, self.probe, self.context)
        # collect_page_context records page_observations into context as a side effect
        page = self.context.get("page_observations") or {}
        summary = {
            "url": page.get("url") or target,
            "status_code": page.get("status_code"),
            "frameworks": page.get("frameworks") or [],
            "forms": page.get("forms") or [],
            "script_urls": page.get("script_urls") or [],
            "candidate_endpoints": page.get("candidate_endpoints") or [],
        }
        return "页面上下文采集完成:\n" + json.dumps(summary, ensure_ascii=False, indent=2)[:6000]

    def _do_python_probe(self, args: Dict[str, Any]) -> str:
        script = str(args.get("script") or "").strip()
        if not script:
            return "未提供脚本。"
        reason = str(args.get("reason") or "")
        self._trace_call("run_python_probe", "Python HTTP 探针", reason[:200] or "运行探针脚本")
        targets = list(self.allowed_origins) or [self.url]
        # provide reported target urls (full URLs) as probe targets
        target_urls = [t for t in (self.context.get("target_urls") or [self.url]) if str(t).startswith(("http://", "https://"))]
        if not target_urls:
            target_urls = [self.url]
        records = self._probe_runner.run_probe(script, self.context, target_urls)
        added = 0
        for item in records or []:
            if isinstance(item, dict) and not item.get("tool_failed"):
                self.records.append(item)
                added += 1
        preview = "\n".join(
            f"- [{item.get('severity')}] {item.get('type')}: {str(item.get('detail') or '')[:200]}"
            for item in (records or [])[:8]
        ) or "脚本未记录证据。"
        self._trace_result(
            "run_python_probe", "Python HTTP 探针", reason[:200],
            preview, raw_output=json.dumps(records, ensure_ascii=False, default=str, indent=2)[:12000],
            python_probe_script=script,
        )
        return f"探针执行完成，记录 {added} 条证据。\n{preview}"

    def _do_nmap(self, args: Dict[str, Any]) -> str:
        command = find_tool_command("nmap")
        if not command:
            return "nmap 未安装或不在 PATH。可在「模型与工具」一键下载，或直接对我说“下载 nmap”。"
        hosts = sorted(self._allowed_hosts())
        if not hosts:
            return "无法确定通报主机，已跳过。"
        host = hosts[0]
        flags = str(args.get("flags") or "-sV -Pn").split()
        # strip any user-supplied target/host args; we pin the host
        flags = [f for f in flags if not f.startswith("-oN") and "://" not in f]
        cmd = command + flags + [host]
        self._trace_call("run_nmap", "nmap 服务探测", " ".join(cmd))
        out = self.scanner.blackbox_tools._run_external(cmd, timeout=90)
        text = str(out.get("output") or "")[:8000]
        self._trace_result("run_nmap", "nmap 服务探测", host,
                           f"exit={out.get('returncode')}", raw_output=text)
        return f"nmap 完成 (exit={out.get('returncode')}, {out.get('elapsed_ms')}ms):\n{text}"

    def _do_sqlmap(self, args: Dict[str, Any]) -> str:
        command = find_tool_command("sqlmap")
        if not command:
            return "sqlmap 未安装或不在 PATH。可在「模型与工具」一键下载，或直接对我说“下载 sqlmap”。"
        target = self._resolve_target(args.get("url") or self.url)
        cmd = command + ["-u", target, "--batch", "--level", "2", "--risk", "1",
                         "--technique", "BEUST", "--threads", "2", "--disable-coloring"]
        data = str(args.get("data") or "")
        if data:
            cmd += ["--data", data]
        extra = str(args.get("flags") or "")
        if extra:
            cmd += [f for f in extra.split() if not f.startswith(("--dump", "--os", "--sql-shell", "--file"))]
        self._trace_call("run_sqlmap", "sqlmap 注入验证", target)
        out = self.scanner.blackbox_tools._run_external(cmd, timeout=180)
        text = str(out.get("output") or "")[:10000]
        self._trace_result("run_sqlmap", "sqlmap 注入验证", target,
                           f"exit={out.get('returncode')}", raw_output=text)
        return f"sqlmap 完成 (exit={out.get('returncode')}):\n{text}"

    def _do_ffuf(self, args: Dict[str, Any]) -> str:
        command = find_tool_command("ffuf")
        if not command:
            return "ffuf 未安装或不在 PATH。可在「模型与工具」一键下载，或直接对我说“下载 ffuf”。"
        target = self._resolve_target(args.get("url") or self.url)
        if "FUZZ" not in target:
            target = target.rstrip("/") + "/FUZZ"
        words = [str(w).strip() for w in (args.get("words") or []) if str(w).strip()][:80]
        if not words:
            words = ["admin", "api", "backup", "config", ".git/config", ".env",
                     "swagger-ui.html", "actuator", "phpinfo.php", "robots.txt"]
        import tempfile, os
        with tempfile.TemporaryDirectory(prefix="koi-ffuf-") as tmp:
            wl = os.path.join(tmp, "words.txt")
            with open(wl, "w", encoding="utf-8") as fh:
                fh.write("\n".join(words))
            out_json = os.path.join(tmp, "ffuf.json")
            cmd = command + ["-u", target, "-w", wl, "-of", "json", "-o", out_json,
                             "-mc", "200,201,204,301,302,401,403", "-t", "20", "-s"]
            self._trace_call("run_ffuf", "ffuf 路径发现", target)
            out = self.scanner.blackbox_tools._run_external(cmd, timeout=90)
            hits = ""
            try:
                with open(out_json, "r", encoding="utf-8", errors="replace") as fh:
                    data = json.load(fh)
                results = data.get("results") or []
                hits = "\n".join(f"- {r.get('url')} [{r.get('status')}]" for r in results[:30]) or "无命中"
            except Exception:
                hits = str(out.get("output") or "")[:4000]
        self._trace_result("run_ffuf", "ffuf 路径发现", target,
                           f"exit={out.get('returncode')}", raw_output=hits)
        return f"ffuf 完成 (exit={out.get('returncode')}):\n{hits}"

    def _do_preset_check(self, args: Dict[str, Any]) -> str:
        check_id = str(args.get("check_id") or "").strip()
        if check_id not in _PRESET_CHECK_IDS:
            return f"未知 check_id: {check_id}"
        outputs = self.scanner._execute_agent_tool(check_id, self.url, self.probe, self.context)
        added = 0
        for item in outputs or []:
            if isinstance(item, dict):
                self.records.append(item)
                added += 1
        preview = "\n".join(
            f"- [{item.get('severity')}] {item.get('type')}: {str(item.get('detail') or item.get('evidence') or '')[:200]}"
            for item in (outputs or [])[:8]
        ) or "该复核未记录观察输出。"
        return f"{check_id} 完成，记录 {added} 条观察。\n{preview}"

    def _do_record_finding(self, args: Dict[str, Any]) -> str:
        severity = str(args.get("severity") or "info").lower()
        if severity not in {"info", "low", "medium", "high"}:
            severity = "info"
        item = {
            "type": str(args.get("title") or "复测观察"),
            "severity": severity,
            "detail": str(args.get("detail") or ""),
            "evidence": str(args.get("evidence") or "")[:2000],
            "source": "agent",
            "manual_required": False,
        }
        self.records.append(item)
        return f"已记录证据: [{severity}] {item['type']}"

    def _do_finish(self, args: Dict[str, Any]) -> str:
        self.finished = True
        self.finish_summary = str(args.get("summary") or "")
        return "已进入最终判定阶段。"

    # ------------------------------------------------------------ trace utils

    def _trace_call(self, tool_id: str, label: str, args_preview: str) -> None:
        try:
            self.scanner._trace_event(
                "tool_call", label, f"开始执行 {label}", "info",
                {"toolId": tool_id, "label": label, "status": "running", "target": self.url, "argsPreview": args_preview},
                metadata={"phase": "tool", "evidenceLevel": "pending"},
            )
        except Exception:
            pass

    def _trace_result(
        self, tool_id: str, label: str, args_preview: str, result_preview: str,
        exchange: Optional[Dict[str, Any]] = None, status_code: Any = None,
        final_url: str = "", duration_ms: Any = None, raw_output: str = "",
        python_probe_script: str = "",
    ) -> None:
        exchange = exchange or {}
        try:
            self.scanner._trace_event(
                "tool_result", label, result_preview, "info",
                {
                    "toolId": tool_id, "label": label, "status": "completed",
                    "target": self.url, "argsPreview": args_preview,
                    "resultPreview": result_preview[:2000],
                    "rawOutput": raw_output[:20000] if raw_output else "",
                    "durationMs": duration_ms,
                    "statusCode": status_code,
                    "finalUrl": final_url,
                    "requestRaw": exchange.get("request_raw") or "",
                    "requestSafe": exchange.get("request_safe") or "",
                    "responseMeta": exchange.get("response_meta") or {},
                    "responseHeadersSafe": exchange.get("response_headers_safe") or {},
                    "responseBodyPreview": exchange.get("response_body_preview") or "",
                    "responseRawExcerpt": exchange.get("response_raw_excerpt") or "",
                    "pythonProbeScript": python_probe_script[:12000] if python_probe_script else "",
                },
                metadata={"phase": "tool", "evidenceLevel": "observation"},
            )
        except Exception:
            pass

    def _trace_tool_error(self, tool_id: str, args_preview: str, message: str) -> None:
        try:
            self.scanner._trace_event(
                "tool_result", tool_id, message, "error",
                {"toolId": tool_id, "label": tool_id, "status": "failed", "target": self.url,
                 "argsPreview": args_preview, "resultPreview": message, "failureReason": message},
                metadata={"phase": "tool", "evidenceLevel": "failed"},
            )
        except Exception:
            pass
