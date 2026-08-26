#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ReAct agent tool layer for black-box retest.

Unlike the legacy "pick a preset tool_id" approach, this layer exposes
真正可执行、可自由传参的工具给大模型（原生 function calling）：

- http_request        自由构造 method/headers/body/params（限通报目标同源）
- collect_page_context 采集页面 HTML/JS/表单/候选端点
- run_python_probe    运行高权限 Python HTTP 探针（本机敏感操作触发用户确认）
- run_nmap/run_sqlmap/run_ffuf  调用本机外部工具（限通报主机，带超时）
- run_preset_check    复用既有 27 个只读复核工具（按 check_id 调度）
- record_finding      记录一条证据观察
- finish_investigation 结束取证，进入最终判定

所有工具仅作用于通报目标同源范围；执行结果通过 scanner._trace_event 推送 UI，
事件格式与既有保持一致，前端零改动。最终 verdict 仍由 judge_retest 决定，
本层只负责取证（产生 observations）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
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


def _contains_waf_bypass_intent(value: Any) -> bool:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value or "")
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _WAF_BYPASS_PATTERNS)


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
        self.auto_finished = False
        self.finish_summary = ""
        self._pending_evidence_classification = False
        self._has_real_observation = False
        self._unclassified_real_observations = 0
        self.requires_probe_repair = False
        self.probe_failure_count = 0
        self.prior_probe_failure_count = 0
        self.last_probe_failure = ""
        self._failed_probe_scripts: List[str] = []
        self._failed_probe_fingerprints: set[str] = set()
        resume = self.context.get("probe_repair_resume")
        if isinstance(resume, dict):
            resume_target = str(resume.get("target_url") or "").strip()
            if not resume_target or resume_target == self.url:
                self.requires_probe_repair = True
                self.prior_probe_failure_count = max(0, int(resume.get("failure_count") or 0))
                self.last_probe_failure = str(resume.get("last_failure") or "")[:3000]
                self._failed_probe_fingerprints.update(
                    str(item)
                    for item in (resume.get("failed_script_fingerprints") or [])
                    if re.fullmatch(r"[0-9a-fA-F]{64}", str(item))
                )
        self.allowed_origins = self._build_allowed_origins(url, self.context)
        self._http_count = 0
        self._max_http = 20
        self._probe_runner = RetestPythonProbeRunner(
            scanner.session, scanner.timeout, scanner._build_request_meta,
            confirm_callback=getattr(scanner, "confirm_callback", None),
            stop_check=getattr(scanner, "stop_check", None),
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
            allowed = ", ".join(sorted(self.allowed_origins)) or self.url
            raise RuntimeError(f"目标超出通报授权同源范围: {target}；允许范围: {allowed}")
        return target

    def _policy_rejection(self, name: str, args: Dict[str, Any]) -> str:
        investigative = {
            "http_request", "collect_page_context", "run_python_probe",
            "run_nmap", "run_sqlmap", "run_ffuf", "run_preset_check",
        }
        if name in investigative and self._pending_evidence_classification:
            return (
                "已有 medium/high 证据等待归类。请先用 record_finding 明确它与原通报漏洞的关系及"
                "结论方向；如果它已直接证明原漏洞可复现，应立即 finish_investigation，不再调用其它工具交叉核验。"
            )
        if self.requires_probe_repair and name != "run_python_probe":
            return (
                "上一份 Python 探针执行失败，当前必须先根据错误重写并重新调用 run_python_probe；"
                "不能跳到其它工具、记录结论或结束取证，也不能把脚本失败当作漏洞不存在。"
            )
        if name == "run_python_probe":
            script = str(args.get("script") or "").strip()
            if script and self._probe_script_fingerprint(script) in self._failed_probe_fingerprints:
                return "这份脚本与已经失败的版本逻辑等价。必须根据错误实质修改代码后再运行，禁止原样重试。"
        if name in investigative and _contains_waf_bypass_intent(args):
            return (
                "复测策略禁止绕过或规避 WAF。只能重放通报中的原始请求/载荷或最小无害等价验证；"
                "若请求被 WAF 拦截，应记录为当前防护下未能验证并结束，不得继续尝试混淆、tamper 或绕过。"
            )
        return ""

    def probe_repair_instruction(self) -> str:
        return (
            "【强制脚本修复】上一份 run_python_probe 执行失败。下一步只能根据错误重写一份不同的脚本并再次调用 "
            "run_python_probe；不要只解释、不要切换其它工具、不要原样重试。脚本修复失败不会作为漏洞已修复证据；"
            "必须持续生成实质不同的修复脚本，直到成功或用户停止。\n"
            f"失败摘要:\n{self.last_probe_failure[:3000]}"
        )

    def probe_repair_resume_state(self) -> Dict[str, Any]:
        return {
            "target_url": self.url,
            "failure_count": self.prior_probe_failure_count + self.probe_failure_count,
            "last_failure": self.last_probe_failure[:3000],
            # Do not persist generated scripts because they can contain report
            # payloads or credentials.  Fingerprints are enough to reject an
            # equivalent script after resume.
            "failed_script_fingerprints": sorted(self._failed_probe_fingerprints)[-64:],
        }

    @staticmethod
    def _probe_script_fingerprint(script: str) -> str:
        """Normalize equivalent scripts so whitespace-only retries are rejected."""
        text = str(script or "").strip()
        try:
            tree = ast.parse(text)
            normalized = ast.dump(tree, annotate_fields=True, include_attributes=False)
        except SyntaxError:
            normalized = re.sub(r"\s+", " ", text)
        return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _is_decisive_reproduction_record(item: Dict[str, Any]) -> bool:
        relation = str(item.get("relation") or "").strip().lower()
        support = str(item.get("verdict_support") or "").strip().lower()
        severity = str(item.get("severity") or "info").strip().lower()
        evidence = str(item.get("evidence") or "").strip()
        return (
            relation == "reported_vulnerability"
            and support == "reproduced"
            and severity in {"low", "medium", "high"}
            and bool(evidence)
            and item.get("observation_bound") is True
        )

    def has_decisive_reproduction_evidence(self) -> bool:
        return any(
            self._is_decisive_reproduction_record(item)
            for item in self.records
            if isinstance(item, dict)
        )

    def _update_evidence_checkpoint(self, start_index: int) -> None:
        new_records = [item for item in self.records[start_index:] if isinstance(item, dict)]
        if any(self._is_decisive_reproduction_record(item) for item in new_records):
            self.finished = True
            self.auto_finished = True
            decisive = next(item for item in new_records if self._is_decisive_reproduction_record(item))
            self.finish_summary = (
                "原通报漏洞已由直接请求/响应证据证明仍可复现，按最小充分取证原则停止额外核验："
                + str(decisive.get("type") or "复现证据")
            )
            self._pending_evidence_classification = False
            return
        self._pending_evidence_classification = any(
            str(item.get("severity") or "info").lower() in {"medium", "high"}
            and not str(item.get("relation") or "").strip()
            for item in new_records
        )

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
                    "运行一段高权限 Python HTTP 探针脚本（不是安全沙箱；本机敏感/破坏性操作会触发用户确认），"
                    "是复测【任意不依赖外部工具的 web 漏洞】的万能武器："
                    "SQLi（含时间盲注/布尔盲注/报错注入）、XSS、SSRF、XXE、命令注入、SSTI、路径穿越、"
                    "越权/IDOR、CSRF、文件上传、反序列化、信息泄露等都可以现写脚本测到位。\n"
                    "脚本必须定义 def run(targets, context):。脚本内可以 import 标准计算/编码/计时模块"
                    "（time、re、json、base64、hashlib、hmac、struct、itertools、string、random、"
                    "datetime、binascii、codecs、collections、math、textwrap、urllib、xml.etree.ElementTree 等），"
                    "用预置的 http_request(method,url,headers=,params=,body=,json_body=,data=,files=,content_type=) "
                    "或 requests 对象（requests.get/post/...）访问通报目标同源 URL。\n"
                    "时间盲注无需自己掐表：每个响应对象都带 elapsed_ms 字段（毫秒），直接比对注入与基线的 elapsed_ms 即可判定。\n"
                    "用 record(title, severity, detail, evidence) 记录证据（severity ∈ info/low/medium/high，"
                    "只有拿到明确风险证据才用 low/medium/high）。可用辅助：contains/regex_search/join_url/"
                    "json_dumps/json_loads/now_ms()/b64encode/b64decode/url_encode/url_decode 等。"
                    "支持 for 循环遍历多个 payload、先取 token 再带着发请求等多步逻辑。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string", "description": "Python 探针脚本，含 def run(targets, context):；可 import time 等标准模块，可循环多 payload"},
                        "reason": {"type": "string", "description": "为什么需要脚本、验证什么漏洞"},
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
                        "relation": {
                            "type": "string",
                            "enum": ["reported_vulnerability", "side_observation"],
                            "description": "该证据是否直接对应原通报漏洞；旁路发现必须选 side_observation",
                        },
                        "verdict_support": {
                            "type": "string",
                            "enum": ["reproduced", "not_reproduced", "inconclusive"],
                            "description": "该证据支持的原漏洞判定方向",
                        },
                    },
                    "required": ["title", "detail", "relation", "verdict_support"],
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
        rejection = self._policy_rejection(name, args)
        if rejection:
            self._trace_tool_error(name, str(args)[:200], rejection)
            return f"工具调用被复测策略拒绝: {rejection}"
        if name not in {"record_finding", "finish_investigation"}:
            self.executed_tools.append(name)
        start_index = len(self.records)
        observed_this_call = False
        try:
            if name == "http_request":
                result = self._do_http_request(args)
            elif name == "collect_page_context":
                result = self._do_collect_page_context(args)
            elif name == "run_python_probe":
                result = self._do_python_probe(args)
            elif name == "run_nmap":
                result = self._do_nmap(args)
            elif name == "run_sqlmap":
                result = self._do_sqlmap(args)
            elif name == "run_ffuf":
                result = self._do_ffuf(args)
            elif name == "run_preset_check":
                result = self._do_preset_check(args)
            elif name == "record_finding":
                result = self._do_record_finding(args)
            elif name == "finish_investigation":
                result = self._do_finish(args)
            else:
                result = f"未知工具: {name}"
            if name == "http_request" and not result.startswith("工具执行失败:"):
                observed_this_call = True
            elif name == "collect_page_context" and result.startswith("页面上下文采集完成:"):
                observed_this_call = True
            elif name in {"run_nmap", "run_sqlmap", "run_ffuf"} and "完成 (exit=" in result:
                observed_this_call = True
            elif name in {"run_python_probe", "run_preset_check"} and any(
                isinstance(item, dict) and not item.get("tool_failed")
                for item in self.records[start_index:]
            ):
                observed_this_call = True
            if observed_this_call:
                self._has_real_observation = True
                self._unclassified_real_observations += 1
            self._update_evidence_checkpoint(start_index)
            return result
        except Exception as exc:  # surface tool errors back to the model, don't crash the loop
            self._trace_tool_error(name, str(args)[:200], str(exc))
            if name == "run_python_probe":
                script = str(args.get("script") or "").strip()
                self.probe_failure_count += 1
                self.last_probe_failure = str(exc)[:3000]
                if script:
                    self._failed_probe_fingerprints.add(self._probe_script_fingerprint(script))
                self.requires_probe_repair = True
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
            # 自动重定向可能在发出下一跳请求前越出同源边界。模型如需跟随，
            # 应读取 Location 后再发一次请求，让 _resolve_target 重新校验。
            "allow_redirects": False,
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
        target_urls = [
            str(target)
            for target in (self.context.get("target_urls") or [self.url])
            if self._origin_key(str(target)) in self.allowed_origins
        ]
        if not target_urls:
            target_urls = [self.url]
        records = self._probe_runner.run_probe(script, self.context, target_urls)
        if any(isinstance(item, dict) and item.get("stopped") for item in (records or [])):
            self.finished = True
            self.finish_summary = "复测已停止，可继续"
            return "Python 探针已按用户停止指令中断，当前结果不会进入最终漏洞判定。"
        added = 0
        failures: List[str] = []
        for item in records or []:
            if not isinstance(item, dict):
                continue
            if item.get("tool_failed"):
                # 脚本报错：带行号的 traceback 在 evidence 字段（_format_probe_error 产出），
                # detail 只是通用标题。两者都带上、不截断，否则模型看不到出错行号只能盲改。
                title = str(item.get("detail") or item.get("type") or "脚本执行失败")
                evidence = str(item.get("evidence") or "")
                failures.append(f"{title}\n{evidence}".strip() if evidence else title)
                continue
            self.records.append(item)
            added += 1
        success_items = [
            item for item in (records or [])
            if isinstance(item, dict) and not item.get("tool_failed")
        ]
        preview = "\n".join(
            f"- [{item.get('severity')}] {item.get('type')}: {str(item.get('detail') or '')[:200]}"
            for item in success_items[:8]
        ) or "脚本未记录证据。"
        if failures:
            for item in records or []:
                if isinstance(item, dict) and item.get("tool_failed"):
                    self.records.append(item)
            self._trace_tool_error(
                "run_python_probe", reason[:200],
                ("Python 探针脚本执行失败：\n" + "\n".join(failures[:3]))[:2000],
            )
        else:
            self._trace_result(
                "run_python_probe", "Python HTTP 探针", reason[:200],
                preview, raw_output=json.dumps(records, ensure_ascii=False, default=str, indent=2)[:12000],
                python_probe_script=script,
            )
        if failures:
            # 关键：脚本报错时绝不说“执行完成”，否则模型误以为跑通没发现洞、继续下一步。
            # 明确告知失败 + 完整错误 + 要求修脚本重调，触发 ReAct 下一轮自我修正。
            detail = "\n".join(failures[:3])[:3000]
            self.probe_failure_count += 1
            self.last_probe_failure = detail
            self._failed_probe_scripts.append(script)
            self._failed_probe_fingerprints.add(self._probe_script_fingerprint(script))
            self.requires_probe_repair = True
            return (
                "Python 探针脚本执行失败，未产生有效漏洞证据。下一步必须重写不同脚本并重新调用 run_python_probe，"
                "不要切换其它工具，也不要把失败当作“无漏洞”；系统不会因固定次数自动结束修复。\n" + detail
            )
        self.requires_probe_repair = False
        self.last_probe_failure = ""
        return f"探针执行完成，记录 {added} 条证据。\n{preview}"

    def _do_nmap(self, args: Dict[str, Any]) -> str:
        command = find_tool_command("nmap")
        if not command:
            return "nmap 未安装或不在 PATH。可在「模型与工具」一键下载，或直接对我说“下载 nmap”。"
        hosts = sorted(self._allowed_hosts())
        if not hosts:
            return "无法确定通报主机，已跳过。"
        host = hosts[0]
        requested_flags = str(args.get("flags") or "-sV -Pn").split()
        # Only single-token, bounded scan options are accepted. This prevents
        # positional extra hosts, NSE scripts and output-file side effects.
        flags = []
        for flag in requested_flags:
            if flag in {"-sV", "-Pn", "-sT", "-sS", "--version-light"}:
                flags.append(flag)
            elif re.fullmatch(r"-T[2-4]", flag):
                flags.append(flag)
            elif re.fullmatch(r"-p(?:\d{1,5})(?:,\d{1,5}){0,20}", flag):
                flags.append(flag)
            elif re.fullmatch(r"--top-ports=(?:[1-9]\d{0,2}|1000)", flag):
                flags.append(flag)
        if not flags:
            flags = ["-sV", "-Pn"]
        cmd = command + flags + [host]
        self._trace_call("run_nmap", "nmap 服务探测", " ".join(cmd))
        out = self.scanner.blackbox_tools._run_external(cmd, timeout=60)
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
            safe_extra = []
            for flag in extra.split():
                if re.fullmatch(r"(?:-p|--parameter)=[A-Za-z0-9_.-]{1,80}", flag):
                    safe_extra.append(flag)
                elif re.fullmatch(r"--dbms=[A-Za-z0-9_.-]{1,40}", flag):
                    safe_extra.append(flag)
                elif re.fullmatch(r"--technique=[BEUSTQ]{1,6}", flag, flags=re.IGNORECASE):
                    safe_extra.append(flag.upper())
                elif re.fullmatch(r"--time-sec=[1-5]", flag):
                    safe_extra.append(flag)
            cmd += safe_extra
        self._trace_call("run_sqlmap", "sqlmap 注入验证", target)
        out = self.scanner.blackbox_tools._run_external(cmd, timeout=60)
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
            out = self.scanner.blackbox_tools._run_external(cmd, timeout=60)
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
            "relation": str(args.get("relation") or "side_observation").strip().lower(),
            "verdict_support": str(args.get("verdict_support") or "inconclusive").strip().lower(),
            "source": "agent",
            "manual_required": False,
        }
        if item["relation"] not in {"reported_vulnerability", "side_observation"}:
            item["relation"] = "side_observation"
        if item["verdict_support"] not in {"reproduced", "not_reproduced", "inconclusive"}:
            item["verdict_support"] = "inconclusive"
        is_decisive_claim = (
            item["relation"] == "reported_vulnerability"
            and item["verdict_support"] == "reproduced"
            and severity in {"low", "medium", "high"}
            and bool(item["evidence"].strip())
        )
        pending_observation = self._unclassified_real_observations > 0
        if is_decisive_claim and not pending_observation:
            return "无法记录决定性阳性证据：本轮没有尚未归类的真实工具观察。请先执行最小必要的取证工具。"
        if pending_observation:
            item["observation_bound"] = True
            self._unclassified_real_observations -= 1
        self._pending_evidence_classification = False
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
