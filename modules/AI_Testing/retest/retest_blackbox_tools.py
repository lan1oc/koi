#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Black-box retest tools constrained by report context."""

from __future__ import annotations

import html
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from modules.AI_Testing.retest.retest_external_tools import find_tool_command
from modules.AI_Testing.retest.retest_python_probe import RetestPythonProbeRunner


class RetestBlackboxTools:
    """Small real probes inspired by AICTF's tool model.

    These checks stay bounded to report-provided targets, paths and payloads,
    plus a short fixed artifact list selected by issue tags. They do not brute
    force directories or credentials.
    """

    def __init__(
        self,
        session: Any,
        timeout: int,
        meta_builder: Callable[[Any, float], Dict[str, Any]],
        ai_config: Optional[Dict[str, Any]] = None,
    ):
        self.session = session
        self.timeout = timeout
        self.meta_builder = meta_builder
        self.ai_config = ai_config or {}

    def check_directory_listing_signature(self, url: str, response: Any, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        if not tags & {"directory_listing", "unauthorized", "sensitive_file"}:
            return []

        out: List[Dict] = []
        for target_url, target_response in self._responses_for_reported_paths(url, response, context, limit=6):
            try:
                marker = self._directory_listing_marker(target_response.text or "")
                content_length = len(target_response.content or b"")
                if target_response.status_code == 200 and marker:
                    out.append({
                        "type": "目录列表仍可访问（复测）",
                        "severity": "medium",
                        "detail": f"目标当前返回目录列表特征: {marker}。",
                        "evidence": f"{target_url} | status=200, len={content_length}",
                        "source": "context",
                    })
                elif "directory_listing" in tags and target_response.status_code in (401, 403, 404):
                    out.append({
                        "type": "目录列表访问受限（复测）",
                        "severity": "info",
                        "detail": f"通报目录路径当前返回 HTTP {target_response.status_code}，目录列表可能已关闭或加访问控制。",
                        "evidence": target_url,
                        "source": "context",
                    })
            except Exception as exc:
                logging.debug(f"check_directory_listing_signature {target_url}: {exc}")
        return out

    def check_sensitive_artifact_access(self, url: str, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        candidates = self._sensitive_artifact_urls(url, context, tags)
        if not candidates:
            return []

        out: List[Dict] = []
        for target_url in candidates[:14]:
            try:
                marker, severity, method, meta = self._probe_sensitive_artifact(target_url)
                if not marker:
                    continue
                out.append({
                    "type": "敏感资产仍可访问（复测）",
                    "severity": severity,
                    "detail": f"{method} {target_url} 命中敏感资产特征: {marker}。",
                    "evidence": f"status={meta.get('status_code')}, len={meta.get('content_length')}, elapsed={meta.get('elapsed_ms')}ms",
                    "source": "context",
                })
            except Exception as exc:
                logging.debug(f"check_sensitive_artifact_access {target_url}: {exc}")
        return out

    def check_source_map_exposure(self, url: str, response: Any, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        if not tags & {"source_leak", "js_library", "sensitive_file", "config_leak"}:
            return []

        out: List[Dict] = []
        for map_url in self._source_map_urls(url, response, context)[:10]:
            try:
                started = time.time()
                probe = self.session.get(map_url, timeout=min(self.timeout, 10), allow_redirects=True)
                meta = self.meta_builder(probe, started)
                marker = self._source_map_marker(map_url, probe)
                if probe.status_code == 200 and marker:
                    out.append({
                        "type": "SourceMap 仍暴露（复测）",
                        "severity": "medium",
                        "detail": f"当前可访问 source map，并匹配 {marker} 特征。",
                        "evidence": f"{map_url} | status={meta.get('status_code')}, len={meta.get('content_length')}",
                        "source": "context",
                    })
            except Exception as exc:
                logging.debug(f"check_source_map_exposure {map_url}: {exc}")
        return out

    def check_xss_reflection_replay(self, url: str, context: Dict) -> List[Dict]:
        if "xss" not in set(context.get("issue_tags") or []):
            return []

        out: List[Dict] = []
        for payload_item in (context.get("payload_candidates") or [])[:5]:
            if not isinstance(payload_item, dict):
                continue
            raw = str(payload_item.get("raw") or "").strip()
            if not self._looks_like_xss_payload(raw):
                continue
            split = self._split_parameter(raw)
            target_url = str(payload_item.get("url") or url or "").strip()
            if split is None or not target_url.startswith(("http://", "https://")):
                continue
            parameter, value = split

            try:
                started = time.time()
                probe = self.session.get(target_url, params={parameter: value}, timeout=self.timeout, allow_redirects=True)
                meta = self.meta_builder(probe, started)
                reflection = self._xss_reflection_marker(value, probe.text or "")
                if reflection == "raw":
                    out.append({
                        "type": "XSS载荷反射命中（复测）",
                        "severity": "high",
                        "detail": f"已重放通报正文参数 {parameter}，当前响应原样反射 XSS 关键片段。",
                        "evidence": f"status={probe.status_code}, len={meta.get('content_length')}",
                        "source": "context",
                    })
                    continue
                if reflection == "escaped":
                    out.append({
                        "type": "XSS载荷已编码反射（复测）",
                        "severity": "info",
                        "detail": f"已重放通报正文参数 {parameter}，当前响应可见编码后的输入，未观察到原样脚本反射。",
                        "evidence": f"status={probe.status_code}, len={meta.get('content_length')}",
                        "source": "context",
                    })
                    continue
                out.append({
                    "type": "XSS载荷未复现（复测）",
                    "severity": "info",
                    "detail": f"已重放通报正文参数 {parameter}，当前响应未观察到通报载荷反射。",
                    "evidence": f"status={probe.status_code}, len={meta.get('content_length')}",
                    "source": "context",
                })
            except Exception as exc:
                logging.debug(f"check_xss_reflection_replay {target_url}: {exc}")
        return out

    def check_file_read_signature_replay(self, url: str, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        if not tags & {"file_read", "path_traversal"}:
            return []

        out: List[Dict] = []
        for payload_item in (context.get("payload_candidates") or [])[:5]:
            if not isinstance(payload_item, dict):
                continue
            raw = str(payload_item.get("raw") or "").strip()
            if not self._looks_like_file_read_payload(raw):
                continue
            split = self._split_parameter(raw)
            target_url = str(payload_item.get("url") or url or "").strip()
            if split is None or not target_url.startswith(("http://", "https://")):
                continue
            parameter, value = split

            try:
                started = time.time()
                probe = self.session.get(target_url, params={parameter: value}, timeout=self.timeout, allow_redirects=True)
                meta = self.meta_builder(probe, started)
                marker = self._file_read_marker(probe.text or "")
                if marker:
                    out.append({
                        "type": "任意文件读取载荷重放命中（复测）",
                        "severity": "high",
                        "detail": f"已重放通报正文参数 {parameter}，当前响应匹配系统文件特征: {marker}。",
                        "evidence": f"status={probe.status_code}, len={meta.get('content_length')}",
                        "source": "context",
                    })
                    continue
                out.append({
                    "type": "任意文件读取载荷未复现（复测）",
                    "severity": "info",
                    "detail": f"已重放通报正文参数 {parameter}，当前响应未匹配系统文件特征。",
                    "evidence": f"status={probe.status_code}, len={meta.get('content_length')}",
                    "source": "context",
                })
            except Exception as exc:
                logging.debug(f"check_file_read_signature_replay {target_url}: {exc}")
        return out

    def check_open_redirect_replay(self, url: str, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        if "open_redirect" not in tags:
            return []

        out: List[Dict] = []
        for target_url in self._open_redirect_candidates(url, context)[:6]:
            try:
                started = time.time()
                probe = self.session.get(target_url, timeout=min(self.timeout, 10), allow_redirects=False)
                meta = self.meta_builder(probe, started)
                location = str(probe.headers.get("Location") or probe.headers.get("location") or "")
                if probe.status_code in (301, 302, 303, 307, 308) and "example.com" in location.lower():
                    out.append({
                        "type": "开放重定向仍可复现（复测）",
                        "severity": "medium",
                        "detail": "按通报参数重放跳转目标后，响应 Location 指向外部域名。",
                        "evidence": f"{target_url} | status={probe.status_code}, location={location}, elapsed={meta.get('elapsed_ms')}ms",
                        "source": "context",
                    })
                    continue
                out.append({
                    "type": "开放重定向未见复现证据（复测）",
                    "severity": "info",
                    "detail": "已按通报跳转参数重放外部跳转目标，未观察到外部 Location。",
                    "evidence": f"{target_url} | status={probe.status_code}, location={location or '-'}",
                    "source": "context",
                })
            except Exception as exc:
                logging.debug(f"check_open_redirect_replay {target_url}: {exc}")
        return out

    def check_endpoint_fingerprint(self, url: str, response: Any, context: Dict) -> List[Dict]:
        tags = set(context.get("issue_tags") or [])
        if not tags & {"response_header", "phpinfo", "js_library", "swagger_api", "sensitive_file"}:
            return []
        markers = self._fingerprint_markers(response)
        if not markers:
            return []
        return [{
            "type": "端点指纹证据（复测）",
            "severity": "info",
            "detail": "当前响应仍暴露可用于核验通报的技术指纹: " + "；".join(markers[:6]),
            "evidence": url,
            "source": "context",
        }]

    def check_nmap_service_probe(self, url: str, context: Dict) -> List[Dict]:
        """Optional nmap service probe, bounded to the reported host and a short port set."""
        command = find_tool_command("nmap")
        if not command:
            return [self._external_tool_unavailable("nmap", "nmap 未安装或不在 PATH，已跳过服务指纹探测。")]

        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return []

        ports = self._context_ports(url, context)
        args = [
            *command,
            "-sV",
            "--version-light",
            "-Pn",
            "-T3",
            "-p",
            ",".join(str(port) for port in ports),
            host,
        ]
        completed = self._run_external(args, timeout=90)
        output = completed.get("output") or ""
        if completed.get("error"):
            return [{
                "type": "Nmap 服务探测执行失败（复测）",
                "severity": "info",
                "detail": str(completed.get("error")),
                "evidence": output[:800],
                "source": "context",
                "tool_failed": True,
            }]

        open_lines = [
            line.strip()
            for line in output.splitlines()
            if re.search(r"\bopen\b", line, flags=re.IGNORECASE)
        ][:12]
        if not open_lines:
            return [{
                "type": "Nmap 服务探测未见开放端口（复测）",
                "severity": "info",
                "detail": f"已对 {host} 的 {','.join(str(port) for port in ports)} 端口执行 nmap 轻量服务探测，未见开放端口输出。",
                "evidence": output[:800] or host,
                "source": "context",
            }]

        tags = set(context.get("issue_tags") or [])
        severity = "medium" if tags & {"service_exposure", "weak_password", "rce", "unauthorized"} else "info"
        return [{
            "type": "Nmap 服务指纹证据（复测）",
            "severity": severity,
            "detail": "nmap 轻量服务探测返回开放服务: " + "；".join(open_lines[:6]),
            "evidence": "\n".join(open_lines),
            "source": "context",
        }]

    def check_sqlmap_context_probe(self, url: str, context: Dict) -> List[Dict]:
        """Optional sqlmap verification with low risk settings and no dumping."""
        if "sql_injection" not in set(context.get("issue_tags") or []):
            return []
        command = find_tool_command("sqlmap")
        if not command:
            return [self._external_tool_unavailable("sqlmap", "sqlmap 未安装或不在 PATH，已跳过 SQL 注入外部验证。")]

        candidate = self._sqlmap_candidate(url, context)
        if not candidate:
            return [{
                "type": "Sqlmap 验证缺少注入点（复测）",
                "severity": "info",
                "detail": "通报正文未提取到可交给 sqlmap 的 URL 查询参数或 HTTP 请求体。",
                "evidence": url,
                "source": "context",
            }]

        with tempfile.TemporaryDirectory(prefix="koi-sqlmap-") as output_dir:
            args = [
                *command,
                "-u",
                candidate["url"],
                "--batch",
                "--smart",
                "--level=1",
                "--risk=1",
                "--random-agent",
                "--flush-session",
                "--timeout=10",
                "--retries=0",
                "--output-dir",
                output_dir,
            ]
            if candidate.get("data"):
                args.extend(["--data", str(candidate["data"])[:12000]])
            completed = self._run_external(args, timeout=180)

        output = completed.get("output") or ""
        low = output.lower()
        if completed.get("error") and not output:
            return [{
                "type": "Sqlmap 验证执行失败（复测）",
                "severity": "info",
                "detail": str(completed.get("error")),
                "evidence": "",
                "source": "context",
                "tool_failed": True,
            }]

        vulnerable_markers = (
            "is vulnerable",
            "parameter",
            "appears to be injectable",
            "back-end dbms",
            "payload:",
        )
        clean_markers = (
            "all tested parameters do not appear to be injectable",
            "does not seem to be injectable",
            "no parameter(s) found for testing",
        )
        if any(marker in low for marker in vulnerable_markers) and not any(marker in low for marker in clean_markers[:1]):
            evidence = self._important_external_lines(output, ("is vulnerable", "appears", "back-end DBMS", "payload", "Parameter"))
            return [{
                "type": "Sqlmap 命中 SQL 注入证据（复测）",
                "severity": "high",
                "detail": "sqlmap 低风险验证输出显示存在可注入参数；未执行数据导出。",
                "evidence": evidence or output[:1200],
                "source": "context",
            }]

        if any(marker in low for marker in clean_markers):
            return [{
                "type": "Sqlmap 未见注入证据（复测）",
                "severity": "info",
                "detail": "sqlmap 低风险验证未发现可注入参数。",
                "evidence": self._important_external_lines(output, clean_markers) or output[:800],
                "source": "context",
            }]

        return [{
            "type": "Sqlmap 未形成复现证据（复测）",
            "severity": "info",
            "detail": "sqlmap 已执行，但输出未形成明确命中结论；按当前结果未复现处理。",
            "evidence": output[:1200],
            "source": "context",
        }]

    def check_ffuf_short_discovery(self, url: str, context: Dict) -> List[Dict]:
        """Optional ffuf check with a generated short wordlist, not a broad brute force."""
        tags = set(context.get("issue_tags") or [])
        if not tags & {"unauthorized", "sensitive_file", "config_leak", "source_leak", "backup_file", "swagger_api", "weak_password", "service_exposure"}:
            return []
        command = find_tool_command("ffuf")
        if not command:
            return [self._external_tool_unavailable("ffuf", "ffuf 未安装或不在 PATH，已跳过短名单路径发现。")]

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return []
        origin = f"{parsed.scheme}://{parsed.netloc}"
        words = self._ffuf_words(context, tags)
        if not words:
            return []

        with tempfile.TemporaryDirectory(prefix="koi-ffuf-") as tmp_dir:
            wordlist = f"{tmp_dir}/words.txt"
            output_json = f"{tmp_dir}/ffuf.json"
            with open(wordlist, "w", encoding="utf-8") as handle:
                handle.write("\n".join(words))
            args = [
                *command,
                "-u",
                f"{origin}/FUZZ",
                "-w",
                wordlist,
                "-of",
                "json",
                "-o",
                output_json,
                "-t",
                "5",
                "-timeout",
                "8",
                "-ac",
            ]
            completed = self._run_external(args, timeout=90)
            parsed_results = self._read_ffuf_results(output_json)

        if completed.get("error") and not parsed_results:
            return [{
                "type": "Ffuf 短名单发现执行失败（复测）",
                "severity": "info",
                "detail": str(completed.get("error")),
                "evidence": str(completed.get("output") or "")[:800],
                "source": "context",
                "tool_failed": True,
            }]

        hits = [
            item for item in parsed_results
            if int(item.get("status") or 0) in {200, 204, 301, 302, 307, 308, 401, 403}
        ][:12]
        if not hits:
            return [{
                "type": "Ffuf 短名单未发现有效路径（复测）",
                "severity": "info",
                "detail": f"已对 {origin} 执行 {len(words)} 个通报相关/固定短名单路径探测，未见有效返回。",
                "evidence": str(completed.get("output") or "")[:800],
                "source": "context",
            }]

        risky_paths = (".git", ".env", "swagger", "api-doc", "backup", "phpinfo", "login", "admin")
        evidence_lines = []
        severity = "info"
        for item in hits:
            input_value = item.get("input")
            if isinstance(input_value, dict):
                path = str(next(iter(input_value.values()), ""))
            else:
                path = str(input_value or item.get("url") or "")
            status = int(item.get("status") or 0)
            length = int(item.get("length") or 0)
            evidence_lines.append(f"{path} | status={status}, len={length}")
            if any(marker in path.lower() for marker in risky_paths) and status in {200, 401, 403}:
                severity = "medium"

        return [{
            "type": "Ffuf 短名单路径发现证据（复测）",
            "severity": severity,
            "detail": "ffuf 返回了通报相关或安全敏感路径，需要结合内容确认是否仍暴露。",
            "evidence": "\n".join(evidence_lines[:10]),
            "source": "context",
        }]

    def check_ai_python_probe(self, url: str, context: Dict) -> List[Dict]:
        advice = context.get("agent_advice") if isinstance(context, dict) else {}
        probe = advice.get("python_probe") if isinstance(advice, dict) else {}
        script = str((probe or {}).get("script") or "").strip() if isinstance(probe, dict) else ""
        if not script:
            return []
        targets = (context.get("target_urls") or []) + (context.get("all_urls") or []) + [url]
        runner = RetestPythonProbeRunner(self.session, self.timeout, self.meta_builder)
        reason = str(probe.get("reason") or "") if isinstance(probe, dict) else ""
        last_results: List[Dict[str, Any]] = []
        current_script = script
        current_reason = reason

        for attempt in range(1, 4):
            results = runner.run_probe(current_script, context, targets)
            last_results = self._decorate_python_probe_results(results, current_reason, attempt)
            failure = self._python_probe_failure(last_results)
            if not failure:
                return last_results
            repaired = self._repair_python_probe(url, context, targets, current_script, failure, attempt)
            if not repaired.get("script") or repaired.get("script") == current_script:
                break
            current_script = repaired["script"]
            current_reason = repaired.get("reason") or current_reason
            if isinstance(advice, dict):
                advice["python_probe"] = {"reason": current_reason, "script": current_script}
            if isinstance(context, dict):
                context.setdefault("agent_advice", {})
                if isinstance(context["agent_advice"], dict):
                    context["agent_advice"]["python_probe"] = {"reason": current_reason, "script": current_script}

        return last_results

    def _decorate_python_probe_results(self, results: List[Dict[str, Any]], reason: str, attempt: int) -> List[Dict[str, Any]]:
        for item in results:
            if not isinstance(item, dict):
                continue
            if reason and item.get("detail") and "脚本目的:" not in str(item.get("detail") or ""):
                item["detail"] = f"{item.get('detail')}\n脚本目的: {reason}"
            item["source"] = "context"
            item["probe_attempt"] = attempt
        return results

    def _python_probe_failure(self, results: List[Dict[str, Any]]) -> str:
        failures = []
        for item in results:
            if not isinstance(item, dict) or not item.get("tool_failed"):
                continue
            detail = str(item.get("detail") or item.get("type") or "Python 探针失败")
            evidence = str(item.get("evidence") or "")
            failures.append(f"{detail}: {evidence}".strip(": "))
        return "\n".join(failures[:3])

    def _repair_python_probe(
        self,
        url: str,
        context: Dict[str, Any],
        targets: List[str],
        previous_script: str,
        failure: str,
        attempt: int,
    ) -> Dict[str, str]:
        if not self.ai_config or not self.ai_config.get("enabled"):
            return {}
        try:
            from modules.AI_Testing.retest.retest_ai_agent import RetestAIAgent

            agent = RetestAIAgent(dict(self.ai_config))
            observations = context.get("tool_observations") if isinstance(context, dict) else []
            scan_result = {
                "vulnerability_types": context.get("vulnerability_types") or [],
                "urls": targets,
                "retest_context": context,
                "raw_text": context.get("raw_text") or "",
            }
            result_data = {
                "urls": targets,
                "observation_count": len(observations or []),
                "failed_count": 1,
                "retest_results": [
                    {
                        "url": url,
                        "observation_count": len(observations or []),
                        "failed_count": 1,
                        "vulnerabilities": observations or [],
                    }
                ],
            }
            tool_context = {
                "target_url": url,
                "vulnerability_types": context.get("vulnerability_types") or [],
                "issue_tags": context.get("issue_tags") or [],
                "page_observations": context.get("page_observations") or {},
                "tool_observations": observations or [],
            }
            return agent.repair_python_probe(scan_result, result_data, tool_context, previous_script, failure, attempt)
        except Exception as exc:
            logging.debug("repair python probe failed: %s", exc, exc_info=True)
            return {}

    def _responses_for_reported_paths(self, url: str, response: Any, context: Dict, limit: int) -> List[Tuple[str, Any]]:
        items: List[Tuple[str, Any]] = [(url, response)]
        for target_url in self._absolute_context_urls(url, context):
            if target_url.lower() == str(url).lower():
                continue
            try:
                probe = self.session.get(target_url, timeout=min(self.timeout, 10), allow_redirects=True)
                items.append((target_url, probe))
                if len(items) >= limit:
                    break
            except Exception as exc:
                logging.debug(f"reported path probe {target_url}: {exc}")
        return items

    def _sensitive_artifact_urls(self, base_url: str, context: Dict, tags: Set[str]) -> List[str]:
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            return []
        origin = f"{parsed.scheme}://{parsed.netloc}"
        urls = self._absolute_context_urls(base_url, context)
        paths_by_tag: Dict[str, Tuple[str, ...]] = {
            "sensitive_file": ("/robots.txt", "/sitemap.xml", "/package.json"),
            "config_leak": ("/.env", "/config.json", "/config.yml", "/application.yml", "/WEB-INF/web.xml"),
            "source_leak": ("/.git/config", "/.svn/entries", "/.DS_Store"),
            "backup_file": ("/backup.zip", "/www.zip", "/web.zip", "/site.zip", "/backup.rar", "/backup.tar.gz"),
            "swagger_api": ("/swagger-ui.html", "/swagger/index.html", "/swagger-ui/", "/v2/api-docs", "/v3/api-docs", "/openapi.json", "/api-docs"),
            "phpinfo": ("/phpinfo.php", "/info.php", "/test.php"),
        }
        for tag, paths in paths_by_tag.items():
            if tag in tags:
                urls.extend(urljoin(origin, path) for path in paths)
        return self._dedupe(urls)

    def _probe_sensitive_artifact(self, target_url: str) -> Tuple[Optional[str], str, str, Dict[str, Any]]:
        path = urlparse(target_url).path.lower()
        if self._is_archive_path(path):
            started = time.time()
            response = self.session.head(target_url, timeout=min(self.timeout, 10), allow_redirects=True)
            meta = self.meta_builder(response, started)
            content_length = self._content_length(response)
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if response.status_code == 200 and (content_length >= 1024 or any(key in content_type for key in ("zip", "rar", "octet-stream", "x-7z"))):
                return "备份/压缩文件可下载", "high", "HEAD", meta
            return None, "info", "HEAD", meta

        started = time.time()
        response = self.session.get(target_url, timeout=min(self.timeout, 10), allow_redirects=True)
        meta = self.meta_builder(response, started)
        if response.status_code != 200:
            return None, "info", "GET", meta
        marker = self._sensitive_marker(target_url, response)
        if not marker:
            return None, "info", "GET", meta
        return marker[0], marker[1], "GET", meta

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

    def _source_map_urls(self, base_url: str, response: Any, context: Dict) -> List[str]:
        urls: List[str] = []
        for target_url in self._absolute_context_urls(base_url, context):
            path = urlparse(target_url).path.lower()
            if path.endswith(".map"):
                urls.append(target_url)
            elif path.endswith(".js"):
                urls.append(f"{target_url}.map")
        body = response.text or ""
        for script_src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", body, flags=re.IGNORECASE):
            script_url = urljoin(base_url, html.unescape(script_src))
            if self._same_origin(base_url, script_url) and urlparse(script_url).path.lower().endswith(".js"):
                urls.append(f"{script_url}.map")
        for source_map in re.findall(r"sourceMappingURL\s*=\s*([^\s'\"<>]+)", body, flags=re.IGNORECASE):
            urls.append(urljoin(getattr(response, "url", base_url) or base_url, html.unescape(source_map.strip())))
        return self._dedupe(urls)

    def _directory_listing_marker(self, body: str) -> Optional[str]:
        low = (body or "").lower()
        markers = ("<title>index of", "index of /", "parent directory", "directory listing for", "<pre><a href=", "name last modified size", "目录列表", "目录浏览")
        for marker in markers:
            if marker in low:
                return marker
        if len(re.findall(r"<a\s+href=[\"'][^\"']+/[\"']", low)) >= 4:
            return "multiple directory links"
        return None

    def _sensitive_marker(self, target_url: str, response: Any) -> Optional[Tuple[str, str]]:
        path = urlparse(target_url).path.lower()
        body = (response.text or "")[:60000]
        low = body.lower()
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if path.endswith("/robots.txt") and "user-agent" in low:
            return "robots.txt", "info"
        if path.endswith("package.json") and '"dependencies"' in low:
            return "package.json dependencies", "low"
        if "/.git/config" in path and "[core]" in low and "repositoryformatversion" in low:
            return ".git/config", "high"
        if "/.svn/entries" in path and ("dir" in low or "svn" in low):
            return ".svn/entries", "high"
        if path.endswith("/.env") and re.search(r"\b(APP_KEY|DB_PASSWORD|DB_USERNAME|SECRET|ACCESS_KEY|PASSWORD)\s*=", body):
            return ".env secrets", "high"
        if path.endswith((".yml", ".yaml", ".json")) and re.search(r"(password|secret|token|access[_-]?key|jdbc|datasource)", low):
            return "配置文件关键字", "medium"
        if path.endswith("web.xml") and "<web-app" in low:
            return "WEB-INF/web.xml", "medium"
        if any(key in path for key in ("swagger", "api-doc", "openapi")) and self._api_schema_marker(body):
            return "Swagger/OpenAPI schema", "medium"
        if path.endswith(("phpinfo.php", "info.php", "test.php")) and ("phpinfo()" in low or "php version" in low):
            return "phpinfo", "medium"
        if path.endswith(".map") and self._source_map_marker(target_url, response):
            return "source map", "medium"
        if "application/json" in content_type and self._api_schema_marker(body):
            return "API schema", "medium"
        return None

    def _source_map_marker(self, target_url: str, response: Any) -> Optional[str]:
        body = (response.text or "")[:80000]
        low = body.lower()
        if urlparse(target_url).path.lower().endswith(".map") and '"sources"' in low and '"mappings"' in low:
            return "sources/mappings"
        if "webpack://" in low or "sourcescontent" in low:
            return "webpack sources"
        return None

    def _api_schema_marker(self, body: str) -> Optional[str]:
        low = (body or "").lower()
        for marker in ("swagger", "openapi", '"paths"', '"definitions"', '"components"', "api documentation"):
            if marker in low:
                return marker
        return None

    def _fingerprint_markers(self, response: Any) -> List[str]:
        markers: List[str] = []
        try:
            headers = getattr(response, "headers", {}) or {}
            for name in (
                "Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version",
                "X-Generator", "X-Runtime", "X-Drupal-Cache", "X-Varnish",
                "Via", "X-Backend-Server", "X-Application-Context", "X-Jenkins",
                "X-Jenkins-Session", "X-Kubernetes-Pf-Flowschema-Uid",
            ):
                value = headers.get(name)
                if value:
                    markers.append(f"{name}: {value}")
        except Exception:
            pass
        body = (getattr(response, "text", "") or "")[:60000].lower()
        for marker in (
            # 语言/框架运行时
            "phpinfo()", "php version", "thinkphp", "laravel", "yii", "symfony",
            "django", "flask", "werkzeug", "express", "spring", "struts",
            "asp.net", "tomcat", "jetty", "nginx", "apache", "iis",
            # API/文档
            "swagger", "openapi", "graphql", "wsdl", "soap",
            # 前端框架/库
            "jquery", "bootstrap", "vue", "angular", "react", "webpack",
            # CMS/中间件
            "wordpress", "wp-content", "drupal", "joomla", "shiro", "weblogic",
            "websphere", "jboss", "fastjson",
            # 调试/报错指纹
            "stack trace", "traceback (most recent call last)", "fatal error",
            "exception in thread", "debug = true", "whoops",
        ):
            if marker in body:
                markers.append(marker)
        return self._dedupe(markers)

    def _looks_like_xss_payload(self, raw: str) -> bool:
        low = (raw or "").lower()
        return "=" in raw and any(marker in low for marker in ("<script", "alert(", "onerror", "onload", "javascript:", "<svg"))

    def _looks_like_file_read_payload(self, raw: str) -> bool:
        low = (raw or "").lower()
        return "=" in raw and any(marker in low for marker in ("../", "..\\", "/etc/passwd", "win.ini", "boot.ini", "windows/system32"))

    def _split_parameter(self, raw: str) -> Optional[Tuple[str, str]]:
        text = str(raw or "").strip()
        if "=" not in text:
            return None
        name, value = text.split("=", 1)
        name = name.strip().lstrip("?&")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]{0,60}$", name):
            return None
        return name, value

    def _xss_reflection_marker(self, value: str, body: str) -> Optional[str]:
        if not value:
            return None
        if value in (body or ""):
            return "raw"
        escaped = html.escape(value, quote=True)
        if escaped and escaped in (body or ""):
            return "escaped"
        return None

    def _file_read_marker(self, body: str) -> Optional[str]:
        text = (body or "")[:120000]
        low = text.lower()
        markers = (
            ("root:", "passwd/root"),
            ("daemon:", "passwd/daemon"),
            ("for 16-bit app support", "win.ini"),
            ("[fonts]", "win.ini"),
            ("127.0.0.1", "hosts"),
            ("localhost", "hosts"),
        )
        for needle, label in markers:
            if needle in low:
                return label
        return None

    def _same_origin(self, left: str, right: str) -> bool:
        l_parsed = urlparse(left)
        r_parsed = urlparse(right)
        return (l_parsed.scheme, l_parsed.netloc.lower()) == (r_parsed.scheme, r_parsed.netloc.lower())

    def _is_archive_path(self, path: str) -> bool:
        return path.lower().endswith((".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz", ".gz", ".bak", ".backup"))

    def _content_length(self, response: Any) -> int:
        try:
            header_value = response.headers.get("Content-Length")
            if header_value is not None and str(header_value).isdigit():
                return int(header_value)
        except Exception:
            pass
        try:
            return len(response.content or b"")
        except Exception:
            return 0

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

    def _external_tool_unavailable(self, tool_name: str, message: str) -> Dict[str, Any]:
        detail = (
            f"{message} 可在「AI测试 / 模型与工具」点击一键下载，"
            f"也可以在当前测试工作台直接对 Agent 说“下载 {tool_name}”。"
        )
        return {
            "type": f"{tool_name} 不可用（复测）",
            "severity": "info",
            "detail": detail,
            "evidence": tool_name,
            "source": "context",
            "tool_unavailable": True,
            "manual_required": False,
            "install_hint": f"下载 {tool_name}",
        }

    def _run_external(self, args: List[str], timeout: int) -> Dict[str, Any]:
        started = time.time()
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
            return {
                "returncode": completed.returncode,
                "output": output[:20000],
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": "" if completed.returncode == 0 else f"exit={completed.returncode}",
            }
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(part for part in (exc.stdout or "", exc.stderr or "") if part).strip()
            return {"returncode": -1, "output": output[:12000], "elapsed_ms": int((time.time() - started) * 1000), "error": f"timeout>{timeout}s"}
        except Exception as exc:
            return {"returncode": -1, "output": "", "elapsed_ms": int((time.time() - started) * 1000), "error": str(exc)}

    def _context_ports(self, url: str, context: Dict) -> List[int]:
        ports: List[int] = []
        parsed = urlparse(url)
        if parsed.port:
            ports.append(parsed.port)
        elif parsed.scheme == "https":
            ports.append(443)
        elif parsed.scheme == "http":
            ports.append(80)
        for value in (context.get("evidence_lines") or []) + (context.get("path_candidates") or []):
            for port_text in re.findall(r"(?<!\d)(\d{2,5})(?!\d)", str(value or "")):
                port = int(port_text)
                if 1 <= port <= 65535 and port not in ports:
                    ports.append(port)
        for port in (21, 22, 80, 443, 445, 8080, 8443):
            if port not in ports:
                ports.append(port)
        return ports[:12]

    def _sqlmap_candidate(self, url: str, context: Dict) -> Optional[Dict[str, str]]:
        for request_item in (context.get("http_request_candidates") or [])[:5]:
            if not isinstance(request_item, dict):
                continue
            method = str(request_item.get("method") or "GET").upper()
            target_url = str(request_item.get("url") or "").strip()
            body = str(request_item.get("body") or "")
            if target_url.startswith(("http://", "https://")) and (urlparse(target_url).query or body):
                return {"url": target_url, "data": body if method in {"POST", "PUT", "PATCH"} else ""}

        for payload_item in (context.get("payload_candidates") or [])[:5]:
            if not isinstance(payload_item, dict):
                continue
            target_url = str(payload_item.get("url") or url or "").strip()
            split = self._split_parameter(str(payload_item.get("raw") or ""))
            if target_url.startswith(("http://", "https://")) and split:
                parameter, value = split
                parsed = urlparse(target_url)
                query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                query[parameter] = value
                return {"url": urlunparse(parsed._replace(query=urlencode(query))), "data": ""}

        if url.startswith(("http://", "https://")) and urlparse(url).query:
            return {"url": url, "data": ""}
        return None

    def _open_redirect_candidates(self, url: str, context: Dict) -> List[str]:
        candidates: List[str] = []
        param_names = ("url", "redirect", "redirect_url", "return", "return_url", "next", "target", "to", "go", "callback")
        replacement = "https://example.com/"

        for payload_item in context.get("payload_candidates") or []:
            if not isinstance(payload_item, dict):
                continue
            target_url = str(payload_item.get("url") or url or "").strip()
            split = self._split_parameter(str(payload_item.get("raw") or ""))
            if target_url.startswith(("http://", "https://")) and split:
                parameter, _value = split
                if any(name in parameter.lower() for name in param_names):
                    parsed = urlparse(target_url)
                    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
                    query[parameter] = replacement
                    candidates.append(urlunparse(parsed._replace(query=urlencode(query))))

        for target_url in (context.get("target_urls") or []) + [url]:
            text = str(target_url or "").strip()
            if not text.startswith(("http://", "https://")):
                continue
            parsed = urlparse(text)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            for name in list(query):
                if any(marker in name.lower() for marker in param_names):
                    query[name] = replacement
                    candidates.append(urlunparse(parsed._replace(query=urlencode(query))))
        return self._dedupe(candidates)

    def _important_external_lines(self, output: str, markers: Iterable[str]) -> str:
        marker_values = [str(marker).lower() for marker in markers]
        lines = []
        for line in (output or "").splitlines():
            low = line.lower()
            if any(marker in low for marker in marker_values):
                lines.append(line.strip())
        return "\n".join(lines[:12])

    def _ffuf_words(self, context: Dict, tags: Set[str]) -> List[str]:
        words: List[str] = []
        for raw_path in context.get("path_candidates") or []:
            path = str(raw_path or "").strip().lstrip("/")
            if path and "FUZZ" not in path and len(path) <= 120:
                words.append(path)

        by_tag: Dict[str, Tuple[str, ...]] = {
            "weak_password": ("login", "admin", "admin/login", "user/login", "manager", "console"),
            "unauthorized": ("admin", "manage", "console", "api", "internal", "dashboard"),
            "sensitive_file": ("robots.txt", "sitemap.xml", "package.json"),
            "config_leak": (".env", "config.json", "config.yml", "application.yml"),
            "source_leak": (".git/config", ".svn/entries", ".DS_Store"),
            "backup_file": ("backup.zip", "www.zip", "web.zip", "site.zip", "backup.rar"),
            "swagger_api": ("swagger-ui.html", "swagger/index.html", "v2/api-docs", "v3/api-docs", "openapi.json"),
            "service_exposure": ("actuator", "actuator/env", "metrics", "server-status"),
        }
        for tag, candidates in by_tag.items():
            if tag in tags:
                words.extend(candidates)
        return self._dedupe(words)[:40]

    def _read_ffuf_results(self, output_json: str) -> List[Dict[str, Any]]:
        try:
            with open(output_json, "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            results = parsed.get("results") if isinstance(parsed, dict) else []
            return [item for item in results if isinstance(item, dict)]
        except Exception:
            return []
