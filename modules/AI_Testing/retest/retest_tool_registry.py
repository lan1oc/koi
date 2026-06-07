#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""复测工具注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Set


@dataclass(frozen=True)
class RetestToolSpec:
    """一个可由复测器或 AI Agent 选择的固定工具。"""

    tool_id: str
    label: str
    category: str
    risk: str
    tags: tuple[str, ...]
    requires: tuple[str, ...]
    description: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class RetestToolRegistry:
    """维护可用复测工具及其按通报上下文的选择规则。"""

    def __init__(self) -> None:
        specs = [
            RetestToolSpec(
                "collect_page_context", "页面/JS 上下文采集", "agent", "low",
                ("unauthorized", "directory_listing", "path_traversal", "file_read", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library", "sql_injection", "xss", "ssrf", "rce", "file_upload", "weak_password", "service_exposure", "open_redirect"),
                ("target_urls",),
                "采集当前页面 HTML、同源 JS bundle、表单和候选接口，供 Agent 生成动态 Python HTTP 探针。",
            ),
            RetestToolSpec(
                "check_reported_url_access", "通报 URL 访问复核", "access", "low",
                ("unauthorized", "directory_listing", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library", "sql_injection", "xss", "ssrf", "rce", "file_upload", "weak_password"),
                ("target_urls",), "访问通报明确给出的 URL，核对状态码和是否仍可达。",
            ),
            RetestToolSpec(
                "check_contextual_evidence", "正文证据特征复核", "evidence", "low",
                ("unauthorized", "directory_listing", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library", "sql_injection", "xss", "ssrf", "rce", "file_upload"),
                ("target_urls", "expected_markers"), "核对响应中是否仍出现通报提到的状态码、响应头或正文特征。",
            ),
            RetestToolSpec(
                "check_context_paths", "通报路径访问复核", "access", "low",
                ("unauthorized", "directory_listing", "path_traversal", "file_read", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library", "xss", "file_upload"),
                ("path_candidates",), "只请求通报正文出现过的路径，避免目录爆破。",
            ),
            RetestToolSpec(
                "check_editor_endpoint_config", "编辑器上传接口复核", "upload", "low",
                ("file_upload", "xss"), ("target_urls", "path_candidates"),
                "针对通报中的 UEditor/KindEditor 上传接口做只读配置/接口可达性复核；仅接口可达不作为漏洞证据。",
            ),
            RetestToolSpec(
                "check_api_schema_exposure", "API/Swagger 暴露复核", "api", "low",
                ("swagger_api", "unauthorized"), ("target_urls", "path_candidates"),
                "对通报给出的 Swagger/OpenAPI/API 文档路径做可达性和 schema 特征核对。",
            ),
            RetestToolSpec(
                "check_auth_boundary", "未授权访问边界复核", "auth", "low",
                ("unauthorized", "directory_listing"), ("target_urls",),
                "判断通报目标当前是否仍可直接访问业务内容，而不是登录页或拒绝页。",
            ),
            RetestToolSpec(
                "check_http_request_replay", "通报 HTTP 请求块重放", "replay", "medium",
                ("file_upload", "xss", "rce", "ssrf", "sql_injection"), ("http_request_candidates",),
                "按通报正文给出的完整 HTTP 请求块重放一次，并核对当前响应成功特征。",
            ),
            RetestToolSpec(
                "check_payload_replay", "通报参数载荷重放", "replay", "medium",
                ("sql_injection", "xss", "path_traversal", "file_read"), ("payload_candidates",),
                "仅重放通报正文中的参数载荷，核对 SQL 延迟/错误回显或反射特征。",
            ),
            RetestToolSpec(
                "check_weak_password_login", "弱口令表单登录复核", "auth", "medium",
                ("weak_password",), ("credential_candidates",),
                "只使用通报正文给出的账号密码提交标准登录表单，不做字典爆破。",
            ),
            RetestToolSpec(
                "check_directory_listing_signature", "目录列表特征复核", "access", "low",
                ("directory_listing", "unauthorized", "sensitive_file"), ("target_urls", "path_candidates"),
                "核对通报 URL 或通报路径当前是否仍呈现 Index of/Parent Directory 等目录列表特征。",
            ),
            RetestToolSpec(
                "check_sensitive_artifact_access", "敏感资产短名单复核", "content", "medium",
                ("sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo"), ("target_urls",),
                "按通报标签选择少量固定敏感资产路径做真实访问复核，如 .env、.git/config、Swagger、phpinfo、备份包。",
            ),
            RetestToolSpec(
                "check_source_map_exposure", "SourceMap 暴露复核", "content", "low",
                ("source_leak", "js_library", "sensitive_file", "config_leak"), ("target_urls", "path_candidates"),
                "解析通报页面或通报 JS 路径，核对同源 source map 是否仍可访问。",
            ),
            RetestToolSpec(
                "check_xss_reflection_replay", "XSS 载荷反射复核", "replay", "medium",
                ("xss",), ("payload_candidates",),
                "仅重放通报正文给出的 XSS 参数载荷，核对当前响应是否原样反射或已编码。",
            ),
            RetestToolSpec(
                "check_file_read_signature_replay", "文件读取载荷特征复核", "file_read", "medium",
                ("path_traversal", "file_read"), ("payload_candidates",),
                "仅重放通报正文给出的文件读取/路径遍历参数载荷，核对 /etc/passwd、win.ini 等文件特征。",
            ),
            RetestToolSpec(
                "check_open_redirect_replay", "开放重定向参数复核", "replay", "medium",
                ("open_redirect",), ("target_urls", "payload_candidates"),
                "仅对通报 URL 或正文参数中的跳转类参数重放外部目标，核对 Location 是否仍指向外部域。",
            ),
            RetestToolSpec(
                "check_endpoint_fingerprint", "端点指纹证据复核", "fingerprint", "low",
                ("response_header", "phpinfo", "js_library", "swagger_api", "sensitive_file"), ("target_urls",),
                "提取当前响应中的 Server、X-Powered-By、phpinfo、Swagger、JS 库等指纹，用于辅助核验通报证据。",
            ),
            RetestToolSpec(
                "check_nmap_service_probe", "Nmap 服务探测（可选）", "external", "medium",
                ("service_exposure", "unauthorized", "weak_password", "rce", "ssrf", "tls", "response_header"), ("target_urls",),
                "借鉴 AICTF 黑盒工具模型；如本机存在 nmap，则对通报目标主机做短端口集服务指纹探测。",
            ),
            RetestToolSpec(
                "check_sqlmap_context_probe", "Sqlmap SQL 注入验证（可选）", "external", "medium",
                ("sql_injection",), ("target_urls", "payload_candidates", "http_request_candidates"),
                "如本机存在 sqlmap，则使用低 risk/level、batch、无导出参数对通报 URL 或正文载荷做 SQL 注入验证。",
            ),
            RetestToolSpec(
                "check_ffuf_short_discovery", "Ffuf 短名单路径发现（可选）", "external", "medium",
                ("service_exposure", "unauthorized", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "weak_password"), ("target_urls", "path_candidates"),
                "如本机存在 ffuf，则用通报路径和少量固定敏感路径做短名单发现，不执行大字典爆破。",
            ),
            RetestToolSpec(
                "tool_external_status", "外部工具状态检测", "agent_tools", "low",
                ("service_exposure", "sql_injection", "weak_password", "unauthorized"), (),
                "Agent 会话可调用的工具管理能力：检测项目工具目录、本机用户目录和 PATH 中的 nmap/sqlmap/ffuf。",
            ),
            RetestToolSpec(
                "tool_install_external_tools", "一键下载外部工具", "agent_tools", "medium",
                ("service_exposure", "sql_injection", "weak_password", "unauthorized"), (),
                "Agent 会话可调用的工具管理能力：从官方来源下载并配置 nmap/sqlmap/ffuf；用户在会话里说下载工具即可执行。",
            ),
            RetestToolSpec(
                "check_ai_python_probe", "AI Python HTTP 探针", "agent", "medium",
                ("sql_injection", "xss", "ssrf", "rce", "file_upload", "open_redirect", "weak_password", "unauthorized", "service_exposure"), ("target_urls", "agent_advice"),
                "AI 可在固定工具不适合时生成受限 Python HTTP 探针脚本；脚本只能请求通报目标并记录证据。",
            ),
            RetestToolSpec(
                "check_header_disclosure", "响应头泄露复核", "baseline", "low",
                ("response_header",), ("target_urls",), "核对 Server/X-Powered-By 等响应头泄露。",
            ),
            RetestToolSpec(
                "check_security_headers", "安全响应头复核", "baseline", "low",
                ("cors", "clickjacking"), ("target_urls",), "核对 CORS、X-Frame-Options、CSP 等安全策略。",
            ),
            RetestToolSpec(
                "check_http_methods", "HTTP 方法复核", "baseline", "low",
                ("http_methods",), ("target_urls",), "核对 OPTIONS/TRACE 等 HTTP 方法暴露。",
            ),
            RetestToolSpec(
                "check_tls_config", "TLS/证书复核", "baseline", "low",
                ("tls",), ("target_urls",), "核对 HTTPS 证书和协议配置。",
            ),
            RetestToolSpec(
                "check_url_content", "敏感内容特征复核", "content", "low",
                ("sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library"),
                ("target_urls",), "核对 phpinfo、package.json、.git/config、source map 等敏感内容特征。",
            ),
            RetestToolSpec(
                "check_common_path_file_read", "少量系统文件读取复核", "file_read", "medium",
                ("path_traversal", "file_read"), ("target_urls",),
                "仅针对任意文件读取/路径遍历通报，少量请求典型系统文件路径。",
            ),
        ]
        self._tools = {spec.tool_id: spec for spec in specs}

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def get(self, tool_id: str) -> RetestToolSpec | None:
        return self._tools.get(tool_id)

    def catalog(self) -> List[Dict[str, object]]:
        return [self._tools[key].to_dict() for key in sorted(self._tools)]

    def checks_for_context(self, context: Dict) -> Set[str]:
        checks: Set[str] = set()

        advice = context.get("agent_advice") if isinstance(context, dict) else {}
        python_probe = advice.get("python_probe") if isinstance(advice, dict) else {}
        has_python_probe = isinstance(python_probe, dict) and bool(str(python_probe.get("script") or "").strip())
        if has_python_probe:
            checks.add("check_ai_python_probe")
        else:
            checks.discard("check_ai_python_probe")

        if context.get("http_request_candidates"):
            checks.add("check_http_request_replay")
        if context.get("payload_candidates"):
            checks.add("check_payload_replay")

        for tool_id in context.get("agent_recommended_checks") or []:
            if self.has_tool(str(tool_id)):
                spec = self.get(str(tool_id))
                if spec and spec.category == "agent_tools":
                    continue
                if str(tool_id) == "check_ai_python_probe" and not has_python_probe:
                    continue
                checks.add(str(tool_id))

        return checks

    def context_has_signals(self, context: Dict | None) -> bool:
        if not context:
            return False
        if any(context.get(key) for key in (
            "http_request_candidates", "payload_candidates", "path_candidates",
            "expected_markers", "expected_status_codes", "credential_candidates",
            "agent_recommended_checks",
        )):
            return True
        tags = set(context.get("issue_tags") or [])
        return any(tags & set(spec.tags) for spec in self._tools.values())

    def filter_known(self, tool_ids: Iterable[str]) -> List[str]:
        return [tool_id for tool_id in dict.fromkeys(str(item) for item in tool_ids) if self.has_tool(tool_id)]
