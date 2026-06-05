#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""围绕通报上下文的专用复测工具。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


class RetestContextTools:
    """只使用通报正文中出现过的 URL、路径和证据线索做复测。"""

    def __init__(self, session: Any, timeout: int, meta_builder: Callable[[Any, float], Dict[str, Any]]):
        self.session = session
        self.timeout = timeout
        self.meta_builder = meta_builder

    def check_upload_artifact_access(self, url: str, context: Dict) -> List[Dict]:
        """历史上传产物只作为线索，不单独记为风险。

        有效上传证据必须来自本次复测重放上传请求，并验证新返回的产物 URL 可访问。
        """
        return []

    def check_editor_endpoint_config(self, url: str, context: Dict) -> List[Dict]:
        """对 UEditor/KindEditor 等上传接口做只读复核。"""
        out: List[Dict] = []
        for endpoint in self._editor_endpoint_urls(url, context):
            try:
                started = time.time()
                response = self.session.get(endpoint, timeout=min(self.timeout, 10), allow_redirects=True)
                meta = self.meta_builder(response, started)
                body = (response.text or "").lower()
                marker = self._editor_endpoint_marker(endpoint, body)
                if response.status_code == 200 and marker:
                    out.append({
                        "type": "编辑器上传接口可达（信息）",
                        "severity": "info",
                        "detail": f"通报中的编辑器接口当前可访问，响应符合 {marker} 特征；仅接口可达不作为上传漏洞有效证据。",
                        "evidence": f"{endpoint} | status={meta.get('status_code')}, len={meta.get('content_length')}",
                        "source": "context",
                    })
                elif response.status_code in (401, 403, 404):
                    out.append({
                        "type": "编辑器上传接口访问受限（复测）",
                        "severity": "info",
                        "detail": f"通报中的编辑器接口当前返回 HTTP {response.status_code}。",
                        "evidence": endpoint,
                        "source": "context",
                    })
            except Exception as e:
                logging.debug(f"check_editor_endpoint_config {endpoint}: {e}")
        return out

    def check_api_schema_exposure(self, url: str, context: Dict) -> List[Dict]:
        """核对通报中的 Swagger/OpenAPI/API 文档是否仍暴露。"""
        out: List[Dict] = []
        for schema_url in self._schema_urls(url, context):
            try:
                started = time.time()
                response = self.session.get(schema_url, timeout=min(self.timeout, 10), allow_redirects=True)
                meta = self.meta_builder(response, started)
                marker = self._api_schema_marker(response.text or "")
                if response.status_code == 200 and marker:
                    out.append({
                        "type": "API文档仍暴露（复测）",
                        "severity": "medium",
                        "detail": f"通报中的 API/Swagger 路径当前仍可访问，匹配特征: {marker}。",
                        "evidence": f"{schema_url} | status={meta.get('status_code')}, len={meta.get('content_length')}",
                        "source": "context",
                    })
                elif response.status_code in (401, 403, 404):
                    out.append({
                        "type": "API文档访问受限（复测）",
                        "severity": "info",
                        "detail": f"通报中的 API/Swagger 路径当前返回 HTTP {response.status_code}。",
                        "evidence": schema_url,
                        "source": "context",
                    })
            except Exception as e:
                logging.debug(f"check_api_schema_exposure {schema_url}: {e}")
        return out

    def check_auth_boundary(self, url: str, response: Any, context: Dict) -> List[Dict]:
        """判断未授权类通报目标当前是否仍直接返回业务内容。"""
        tags = set(context.get("issue_tags") or [])
        if not tags & {"unauthorized", "directory_listing"}:
            return []

        body = response.text or ""
        low = body.lower()
        content_length = len(response.content or b"")
        block_markers = (
            "login", "signin", "password", "验证码", "captcha", "403 forbidden",
            "401 unauthorized", "access denied", "无权限", "禁止访问", "请登录",
        )
        if response.status_code in (401, 403):
            return [{
                "type": "未授权访问已受限（复测）",
                "severity": "info",
                "detail": f"通报目标当前返回 HTTP {response.status_code}，访问边界可能已收紧。",
                "evidence": f"status={response.status_code}, len={content_length}",
                "source": "context",
            }]
        if response.status_code == 200 and content_length >= 128 and not any(marker in low for marker in block_markers):
            expected_markers = [str(marker).strip() for marker in (context.get("expected_markers") or []) if str(marker).strip()]
            matched_markers = [marker for marker in expected_markers if marker.lower() in low]
            if not matched_markers:
                return [{
                    "type": "未授权目标可达（信息）",
                    "severity": "info",
                    "detail": "通报目标当前 HTTP 200 且未见登录/拒绝提示，但未命中通报证据特征；不单独作为未授权漏洞复现证据。",
                    "evidence": f"{url} | len={content_length}",
                    "source": "context",
                    "manual_required": False,
                }]
            return [{
                "type": "未授权目标疑似仍可直接访问（复测）",
                "severity": "medium",
                "detail": "通报目标当前 HTTP 200 且未见登录/拒绝提示，并命中通报证据特征，按未授权访问可复现证据记录。",
                "evidence": f"{url} | len={content_length}; markers={'；'.join(matched_markers[:5])}",
                "source": "context",
                "manual_required": False,
            }]
        return []

    def _absolute_context_urls(self, base_url: str, context: Dict) -> List[str]:
        urls: List[str] = []
        for value in (context.get("target_urls") or []) + (context.get("all_urls") or []):
            text = str(value or "").strip()
            if text.startswith(("http://", "https://")):
                urls.append(text)

        parsed = urlparse(base_url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            for path in context.get("path_candidates") or []:
                text = str(path or "").strip()
                if not text:
                    continue
                if text.startswith(("http://", "https://")):
                    urls.append(text)
                else:
                    urls.append(urljoin(origin, text if text.startswith("/") else f"/{text}"))
        return self._dedupe(urls)

    def _artifact_urls(self, base_url: str, context: Dict) -> List[str]:
        artifact_extensions = (".html", ".htm", ".svg", ".xml", ".jsp", ".jspx", ".php", ".aspx", ".asp")
        candidates = []
        for item in self._absolute_context_urls(base_url, context):
            parsed = urlparse(item)
            path = parsed.path.lower()
            if "/upload" in path or "/uploads" in path or path.endswith(artifact_extensions):
                candidates.append(item)
        return candidates[:8]

    def _editor_endpoint_urls(self, base_url: str, context: Dict) -> List[str]:
        endpoints: List[str] = []
        for item in self._absolute_context_urls(base_url, context):
            low = item.lower()
            if any(marker in low for marker in ("ueditor", "kindeditor", "upload_json", "controller.php")):
                endpoints.append(item)
                config_url = self._ueditor_config_url(item)
                if config_url:
                    endpoints.append(config_url)
        return self._dedupe(endpoints)[:8]

    def _schema_urls(self, base_url: str, context: Dict) -> List[str]:
        schema_urls = []
        for item in self._absolute_context_urls(base_url, context):
            low = item.lower()
            if any(marker in low for marker in ("swagger", "openapi", "api-doc", "v2/api-docs", "v3/api-docs")):
                schema_urls.append(item)
        return self._dedupe(schema_urls)[:8]

    def _ueditor_config_url(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        if "ueditor" not in parsed.path.lower() or "controller.php" not in parsed.path.lower():
            return None
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["action"] = "config"
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _upload_artifact_marker(self, url: str, body: str, headers: Any) -> Optional[str]:
        low = (body or "").lower()
        content_type = ""
        try:
            content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
        except Exception:
            pass
        path = urlparse(url).path.lower()
        if path.endswith((".svg", ".xml")) and ("<svg" in low or "<script" in low or "image/svg" in content_type):
            return "SVG/XML 可展示内容"
        if path.endswith((".html", ".htm")) and ("<html" in low or "<script" in low or "text/html" in content_type):
            return "HTML 可展示内容"
        if path.endswith((".jsp", ".jspx", ".php", ".aspx", ".asp")) and len(body or "") > 0:
            return "服务端脚本扩展名"
        return None

    def _editor_endpoint_marker(self, url: str, body_lower: str) -> Optional[str]:
        low_url = url.lower()
        if "ueditor" in low_url and any(marker in body_lower for marker in ("imageactionname", "fileactionname", "catcherlocaldomain", "uploadimage")):
            return "UEditor 配置"
        if "kindeditor" in low_url and any(marker in body_lower for marker in ("invalid", "upload", "json", "dir")):
            return "KindEditor 上传接口"
        if "upload_json" in low_url or "controller.php" in low_url:
            return "上传接口响应"
        return None

    def _api_schema_marker(self, body: str) -> Optional[str]:
        low = (body or "").lower()
        for marker in ("swagger", "openapi", '"paths"', '"definitions"', '"components"', "api documentation"):
            if marker in low:
                return marker
        return None

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
