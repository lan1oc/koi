#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通报正文 HTTP 请求和参数载荷重放。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from modules.AI_Testing.retest.retest_http_evidence import build_http_exchange


class RetestRequestReplayer:
    """按通报中给出的原始请求或参数载荷做有边界的真实复测。"""

    def __init__(self, session: Any, timeout: int, meta_builder: Callable[[Any, float], Dict[str, Any]]):
        self.session = session
        self.timeout = timeout
        self.meta_builder = meta_builder

    def check_http_request_replay(self, context: Dict) -> List[Dict]:
        """重放通报正文中的完整 HTTP 请求块。"""
        out: List[Dict] = []
        issue_tags = set(context.get("issue_tags") or [])
        for request_item in (context.get("http_request_candidates") or [])[:5]:
            if not isinstance(request_item, dict):
                continue
            method = str(request_item.get("method") or "GET").upper()
            url = str(request_item.get("url") or "").strip()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            if not url.startswith(("http://", "https://")):
                continue

            headers = self._headers_for_replay(request_item.get("headers") or {})
            body = str(request_item.get("body") or "")
            evidence_lines = [str(line) for line in (request_item.get("evidence_lines") or [])]
            expected_status = set(context.get("expected_status_codes") or []) | set(
                self._status_codes_from_context_lines(evidence_lines)
            )
            report_success_markers = self._evidence_success_markers(evidence_lines)

            try:
                started = time.time()
                request_kwargs: Dict[str, Any] = {
                    "headers": headers,
                    "timeout": self.timeout,
                    "allow_redirects": True,
                }
                if method in {"POST", "PUT", "PATCH", "DELETE"} and body:
                    request_kwargs["data"] = body.encode("utf-8")
                response = self.session.request(method, url, **request_kwargs)
                meta = self.meta_builder(response, started)
                exchange = build_http_exchange(method, url, headers, body, response, meta)
                code = int(response.status_code)
                content_length = int(meta.get("content_length") or 0)
                matched_status = code in expected_status if expected_status else False
                response_markers = self._response_success_markers(response.text or "", report_success_markers, issue_tags)

                if response_markers:
                    uploaded_artifacts: List[str] = []
                    if issue_tags & {"file_upload", "xss"}:
                        uploaded_artifacts = self._verify_uploaded_artifacts(url, response.text or "")
                        if not uploaded_artifacts:
                            out.append({
                                "type": "上传请求已重放但未验证新产物（复测）",
                                "severity": "info",
                                "detail": (
                                    f"已按通报正文重放 {method} {url}，返回 HTTP {code} 且出现成功特征，"
                                    "但未能从本次响应中验证新上传产物可访问，因此不作为有效上传漏洞证据。"
                                ),
                                "evidence": f"markers={'；'.join(response_markers)}, status={code}, len={content_length}",
                                "source": "context",
                                "manual_required": False,
                                **exchange,
                            })
                            continue
                    out.append({
                        "type": "通报HTTP请求重放命中（复测）",
                        "severity": "high" if issue_tags & {"file_upload", "xss", "rce", "ssrf"} else "medium",
                        "detail": (
                            f"已按通报正文重放 {method} {url}，返回 HTTP {code}。"
                            + f" 当前响应出现成功特征: {'；'.join(response_markers)}。"
                            + (f" 本次返回产物可访问: {'；'.join(uploaded_artifacts[:3])}。" if uploaded_artifacts else "")
                        ),
                        "evidence": f"status={code}, len={content_length}, elapsed={meta.get('elapsed_ms')}ms",
                        "source": "context",
                        **exchange,
                    })
                    continue

                if code in (401, 403, 404):
                    out.append({
                        "type": "通报HTTP请求重放未复现（复测）",
                        "severity": "info",
                        "detail": f"已按通报正文重放 {method} {url}，当前返回 HTTP {code}，原请求路径可能已限制或移除。",
                        "evidence": f"status={code}, len={content_length}",
                        "source": "context",
                        "manual_required": False,
                        **exchange,
                    })
                else:
                    note = ""
                    if matched_status:
                        note = "，状态码与通报证据一致，但当前响应未出现明确成功回显"
                    out.append({
                        "type": "通报HTTP请求已重放（复测）",
                        "severity": "info",
                        "detail": f"已按通报正文重放 {method} {url}，当前返回 HTTP {code}{note}。",
                        "evidence": f"status={code}, len={content_length}, elapsed={meta.get('elapsed_ms')}ms",
                        "source": "context",
                        "manual_required": False,
                        **exchange,
                    })
            except Exception as e:
                logging.debug(f"check_http_request_replay {method} {url}: {e}")

        return out

    def check_payload_replay(self, url: str, context: Dict) -> List[Dict]:
        """重放通报正文中的参数载荷，适用于未给出完整 HTTP 请求的 SQL/XSS 等通报。"""
        out: List[Dict] = []
        for payload_item in (context.get("payload_candidates") or [])[:5]:
            if not isinstance(payload_item, dict):
                continue
            target_url = str(payload_item.get("url") or url or "").strip()
            raw_payload = str(payload_item.get("raw") or "").strip()
            split = self._split_payload_parameter(raw_payload)
            if not target_url.startswith(("http://", "https://")) or split is None:
                continue
            parameter, value = split

            try:
                baseline_started = time.time()
                baseline = self.session.get(target_url, timeout=self.timeout, allow_redirects=True)
                baseline_meta = self.meta_builder(baseline, baseline_started)

                replay_started = time.time()
                response = self.session.get(target_url, params={parameter: value}, timeout=self.timeout, allow_redirects=True)
                replay_meta = self.meta_builder(response, replay_started)
                exchange = build_http_exchange("GET", response.url or target_url, {}, "", response, replay_meta)

                baseline_elapsed = int(baseline_meta.get("elapsed_ms") or 0)
                replay_elapsed = int(replay_meta.get("elapsed_ms") or 0)
                elapsed_delta = replay_elapsed - baseline_elapsed
                sleep_seconds = self._extract_sleep_seconds(value)
                sql_error = self._sql_error_marker(response.text or "")

                if sleep_seconds and elapsed_delta >= max(800, sleep_seconds * 550):
                    out.append({
                        "type": "SQL注入时间延迟载荷重放命中（复测）",
                        "severity": "high",
                        "detail": f"已重放通报正文参数 {parameter}=...sleep({sleep_seconds})...，响应耗时比基线增加约 {elapsed_delta}ms。",
                        "evidence": f"baseline={baseline_elapsed}ms, replay={replay_elapsed}ms, status={response.status_code}",
                        "source": "context",
                        **exchange,
                    })
                    continue

                if sql_error:
                    out.append({
                        "type": "SQL注入错误回显载荷重放命中（复测）",
                        "severity": "high",
                        "detail": f"已重放通报正文参数 {parameter}，响应中出现数据库错误特征: {sql_error}。",
                        "evidence": f"status={response.status_code}, marker={sql_error}",
                        "source": "context",
                        **exchange,
                    })
                    continue

                out.append({
                    "type": "通报参数载荷已重放（复测）",
                    "severity": "info",
                    "detail": f"已重放通报正文参数 {parameter}，当前未观察到时间延迟或数据库错误回显。",
                    "evidence": f"baseline={baseline_elapsed}ms, replay={replay_elapsed}ms, status={response.status_code}",
                    "source": "context",
                    "manual_required": False,
                    **exchange,
                })
            except Exception as e:
                logging.debug(f"check_payload_replay {target_url}: {e}")

        return out

    def _headers_for_replay(self, headers: Dict[str, Any]) -> Dict[str, str]:
        blocked = {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
        replay_headers: Dict[str, str] = {}
        for key, value in (headers or {}).items():
            name = str(key or "").strip()
            if not name or name.lower() in blocked:
                continue
            replay_headers[name] = str(value or "")
        return replay_headers

    def _status_codes_from_context_lines(self, lines: List[str]) -> List[int]:
        codes: List[int] = []
        for line in lines or []:
            if not any(key in line for key in ("状态", "响应", "返回", "HTTP", "http")):
                continue
            for code_text in re.findall(r"\b(20\d|30\d|40\d|50\d)\b", line):
                codes.append(int(code_text))
        return list(dict.fromkeys(codes))

    def _evidence_success_markers(self, lines: List[str]) -> List[str]:
        markers: List[str] = []
        for line in lines or []:
            for marker in ("上传成功", "返回文件路径", "文件上传成功", "成功进入", "漏洞情况属实"):
                if marker in line:
                    markers.append(marker)
        return list(dict.fromkeys(markers))

    def _response_success_markers(self, text: str, report_markers: List[str], issue_tags: set) -> List[str]:
        low = (text or "").lower()
        markers: List[str] = []
        for marker in report_markers or []:
            if marker and marker.lower() in low:
                markers.append(marker)

        if issue_tags & {"file_upload", "xss"}:
            upload_patterns = (
                r'"state"\s*:\s*"success"',
                r'"success"\s*:\s*true',
                r'"error"\s*:\s*0',
                r'"url"\s*:\s*"[^"]+"',
                r'"path"\s*:\s*"[^"]+"',
                r'/upload/',
                r'/uploads/',
            )
            for pattern in upload_patterns:
                if re.search(pattern, low, flags=re.IGNORECASE):
                    markers.append(pattern)

        if issue_tags & {"rce"}:
            for marker in ("uid=", "gid=", "windows", "linux", "command executed"):
                if marker in low:
                    markers.append(marker)

        return list(dict.fromkeys(markers))

    def _verify_uploaded_artifacts(self, request_url: str, response_text: str) -> List[str]:
        artifacts: List[str] = []
        for candidate in self._uploaded_artifact_candidates(request_url, response_text):
            try:
                started = time.time()
                response = self.session.get(candidate, timeout=min(self.timeout, 10), allow_redirects=True)
                meta = self.meta_builder(response, started)
                if response.status_code == 200 and int(meta.get("content_length") or 0) > 0:
                    artifacts.append(f"{candidate} | status=200, len={meta.get('content_length')}")
            except Exception as exc:
                logging.debug(f"verify_uploaded_artifact {candidate}: {exc}")
        return artifacts[:5]

    def _uploaded_artifact_candidates(self, request_url: str, response_text: str) -> List[str]:
        text = response_text or ""
        candidates: List[str] = []
        patterns = (
            r'"(?:url|path|file|filePath|src)"\s*:\s*"([^"]{2,300})"',
            r"'(?:url|path|file|filePath|src)'\s*:\s*'([^']{2,300})'",
            r'(?:/upload/|/uploads/|/ueditor/|/kindeditor/)[A-Za-z0-9._~!$&()*+,;=:@%/\-]{2,240}',
        )
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                value = str(match or "").strip().strip("\\")
                if not value or value.lower().startswith(("javascript:", "data:")):
                    continue
                absolute = urljoin(request_url, value)
                parsed = urlparse(absolute)
                request_host = urlparse(request_url).hostname
                if parsed.scheme in {"http", "https"} and parsed.hostname and request_host and parsed.hostname.lower() == request_host.lower():
                    candidates.append(absolute)
        return list(dict.fromkeys(candidates))[:8]

    def _split_payload_parameter(self, raw_payload: str) -> Optional[Tuple[str, str]]:
        text = str(raw_payload or "").strip()
        if "=" not in text:
            return None
        name, value = text.split("=", 1)
        name = name.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]{0,60}$", name):
            return None
        return name, value

    def _extract_sleep_seconds(self, payload: str) -> Optional[int]:
        text = payload or ""
        match = re.search(r"sleep\s*\(\s*(\d{1,2})\s*\)", text, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"sleep\s*\(\s*if\s*\(.+?,\s*(\d{1,2})\s*,\s*\d{1,2}\s*\)", text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            return max(1, min(30, int(match.group(1))))
        except ValueError:
            return None

    def _sql_error_marker(self, text: str) -> Optional[str]:
        low = (text or "").lower()
        markers = (
            "sql syntax", "mysql", "mariadb", "postgresql", "ora-", "sqlite",
            "odbc", "jdbc", "syntax error", "database error", "sqlstate",
        )
        for marker in markers:
            if marker in low:
                return marker
        return None
