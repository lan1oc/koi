#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通报正文复测上下文提取。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from docx import Document


class RetestContextExtractor:
    """从通报正文中提取可重放的复测线索。"""

    def __init__(self) -> None:
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
        self.path_pattern = re.compile(
            r'(?<![A-Za-z0-9])/(?:[A-Za-z0-9._~!$&()*+,;=:@%-]+/?)+(?:\?[^\s，。；;、<>《》]*)?'
        )
        self.request_line_pattern = re.compile(
            r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s+HTTP/\d(?:\.\d)?$',
            re.IGNORECASE,
        )

        self.context_tag_keywords: Dict[str, Tuple[str, ...]] = {
            'unauthorized': ('未授权', '未登录', '无需登录', '无需认证', '匿名访问', '直接访问', '越权', '权限绕过', 'Unauthorized Access'),
            'directory_listing': ('目录列表', '目录浏览', 'Index of', 'directory listing'),
            'path_traversal': ('目录遍历', '路径遍历', 'Path Traversal', 'Directory Traversal'),
            'file_read': ('任意文件读取', '任意文件下载', 'Arbitrary File Read', 'Arbitrary File Download', '/etc/passwd', 'win.ini'),
            'sensitive_file': ('敏感文件', '站点文件', '文档文件', '访问控制文件', 'robots.txt', 'package.json'),
            'config_leak': ('配置文件', '配置信息', '.env', 'config', 'yaml', 'yml'),
            'source_leak': ('源代码泄露', '源码泄露', '.git', 'git泄露', 'source map', '.map'),
            'backup_file': ('备份文件', '压缩文件', '.zip', '.rar', '.tar.gz', '.7z'),
            'swagger_api': ('swagger', 'openapi', 'api-docs', '接口文档', 'api接口'),
            'phpinfo': ('phpinfo', 'php探针', '探针泄露'),
            'js_library': ('JavaScript库', 'js库', 'jquery', 'bootstrap', 'angular', 'vue'),
            'response_header': ('响应头', 'Server泄露', 'X-Powered-By', 'ASP.NET版本', '框架信息'),
            'tls': ('TLS', 'SSL', '证书', '弱密码套件', 'Sweet32', 'LOGJAM', 'FREAK'),
            'cors': ('跨域', 'CORS', '资源共享'),
            'clickjacking': ('点击劫持', 'X-Frame-Options', 'frame-ancestors'),
            'http_methods': ('OPTIONS方法', 'TRACE方法', 'HTTP方法'),
            'service_exposure': ('端口开放', '开放端口', '端口暴露', '服务暴露', '服务探测', 'nmap', '端口扫描', '高危端口'),
            'open_redirect': ('开放重定向', '任意跳转', 'URL跳转', 'redirect', '重定向漏洞'),
            'weak_password': ('弱口令', '弱密码', '默认口令', '默认密码'),
            'sql_injection': ('SQL注入', 'SQL Injection', 'sqli'),
            'xss': ('XSS', '跨站脚本'),
            'ssrf': ('SSRF', '服务端请求伪造'),
            'rce': ('RCE', '远程代码执行', '远程命令执行', '命令执行', '代码执行'),
            'file_upload': ('文件上传', 'File Upload'),
        }

        self.evidence_markers = [
            'swagger', 'openapi', 'api documentation', 'phpinfo()', 'php version',
            '__VIEWSTATE', 'root:', 'bin/bash', 'nobody:', 'daemon:', 'for 16-bit app support',
            'Index of', 'Directory Listing', 'Access-Control-Allow-Origin', 'X-Powered-By',
            'Server:', 'jquery', 'bootstrap', 'angular', 'vue', 'telescope', 'ThinkPHP',
            'package.json', '.env', '.git/config', 'robots.txt', 'stack trace', 'debug mode',
        ]

        self.section_aliases: Dict[str, Tuple[str, ...]] = {
            '漏洞信息': ('漏洞名称', '漏洞类型', '漏洞详情', '漏洞描述', '问题描述', '漏洞情况'),
            '验证情况': ('验证情况', '验证过程', '验证结果', '检测结果', '核查情况', '证明材料', '漏洞证明'),
            '影响范围': ('影响范围', '影响资产', '涉及资产', '风险地址', '目标地址'),
            '处置建议': ('处置建议', '整改建议', '修复建议', '处置措施'),
        }

    def extract(self, text: str, file_path: Optional[Path] = None, vulnerability_types: Optional[List[str]] = None) -> Dict[str, object]:
        raw_lines = [line.strip() for line in text.split('\n') if line.strip()]
        sections = self._extract_sections(raw_lines)

        priority_lines: List[str] = []
        for name in ('验证情况', '漏洞信息', '影响范围'):
            priority_lines.extend(sections.get(name, []))

        all_urls = self._extract_all_urls_from_text(text, file_path)
        target_urls: List[str] = []
        for line in priority_lines:
            target_urls.extend(self._extract_urls_from_line(line))

        if not target_urls:
            for line in raw_lines:
                if any(marker in line for marker in ('URL', 'Url', 'url', 'URl', '网址', '地址', '域名', 'domain', 'Domain')):
                    target_urls.extend(self._extract_urls_from_line(line))

        if not target_urls:
            target_urls.extend(all_urls[:5])

        target_urls = self._dedupe_keep_order(target_urls)[:8]
        return {
            'target_urls': target_urls,
            'all_urls': all_urls[:30],
            'path_candidates': self._dedupe_keep_order(self._paths_from_urls(all_urls) + self._extract_path_candidates(priority_lines or raw_lines))[:20],
            'http_request_candidates': self._extract_http_request_candidates(raw_lines, target_urls),
            'payload_candidates': self._extract_payload_candidates(priority_lines or raw_lines, target_urls),
            'expected_status_codes': self._extract_expected_status_codes(priority_lines or raw_lines),
            'expected_markers': self._extract_expected_markers('\n'.join(priority_lines or raw_lines)),
            'parameter_names': self._extract_parameter_names(all_urls, priority_lines or raw_lines),
            'credential_candidates': self._extract_credentials(raw_lines),
            'issue_tags': self._extract_issue_tags('\n'.join(priority_lines) if priority_lines else text, vulnerability_types),
            'evidence_lines': self._dedupe_keep_order([line[:220] for line in raw_lines if self._line_has_context_signal(line)])[:14],
            'sections': {key: value[:8] for key, value in sections.items()},
        }

    def _dedupe_keep_order(self, values: List[str]) -> List[str]:
        deduped: List[str] = []
        seen: Set[str] = set()
        for value in values:
            item = str(value or '').strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    def _clean_endpoint(self, value: str) -> str:
        text = str(value or '').strip()
        text = text.split('<', 1)[0].split('>', 1)[0]
        text = text.strip('\'"“”‘’<>《》()（）[]【】{}')
        return text.rstrip('.,;，。；、！!?)）】》]')

    def _is_ignored_url(self, value: str) -> bool:
        text = self._clean_endpoint(value).lower()
        return text.startswith((
            'http://schemas.microsoft.com', 'https://schemas.microsoft.com',
            'http://schemas.openxmlformats.org', 'https://schemas.openxmlformats.org',
            'http://purl.oclc.org', 'https://purl.oclc.org',
            'http://www.w3.org', 'https://www.w3.org',
            'http://www.wps.cn', 'https://www.wps.cn',
        ))

    def _is_ignored_path(self, value: str) -> bool:
        text = self._clean_endpoint(value).lower()
        return text.startswith(('/markup-compatibility/', '/officedocument/', '/drawingml/', '/wordprocessingml/', '/vml/'))

    def _extract_urls_from_line(self, line: str) -> List[str]:
        urls = [self._clean_endpoint(url) for url in self.url_pattern.findall(line) if not self._is_ignored_url(url)]
        marker_match = re.search(r'(?:URL|Url|url|URl|网址|地址|域名|domain|Domain|DOMAIN)\s*[:：]\s*([^\s，,；;。]+)', line)
        if marker_match and not urls:
            urls.extend(self._endpoint_candidates_from_value(marker_match.group(1)))
        return self._dedupe_keep_order(urls)

    def _extract_all_urls_from_text(self, text: str, file_path: Optional[Path]) -> List[str]:
        urls = [self._clean_endpoint(url) for url in self.url_pattern.findall(text) if not self._is_ignored_url(url)]
        for line in text.split('\n'):
            urls.extend(self._extract_urls_from_line(line))
        if file_path is not None:
            try:
                raw_doc = Document(str(file_path))
                raw_xml = raw_doc._element.xml  # type: ignore[attr-defined]
                urls.extend(self._clean_endpoint(url) for url in self.url_pattern.findall(raw_xml) if not self._is_ignored_url(url))
            except Exception:
                pass
        return self._dedupe_keep_order(urls)

    def _endpoint_candidates_from_value(self, value: str) -> List[str]:
        text = self._clean_endpoint(value)
        if not text:
            return []
        if text.startswith(('http://', 'https://')):
            return [] if self._is_ignored_url(text) else [text]
        parsed = urlparse(f'//{text}')
        host = parsed.hostname or ''
        if host and '.' in host and re.match(r'^[A-Za-z0-9.-]+$', host):
            return [f'https://{text}', f'http://{text}']
        return []

    def _paths_from_urls(self, urls: List[str]) -> List[str]:
        paths: List[str] = []
        for url in urls:
            parsed = urlparse(url)
            if not parsed.path or parsed.path == '/':
                continue
            path = parsed.path + (f'?{parsed.query}' if parsed.query else '')
            if not self._is_ignored_path(path):
                paths.append(path)
        return self._dedupe_keep_order(paths)

    def _extract_path_candidates(self, lines: List[str]) -> List[str]:
        paths: List[str] = []
        for line in lines:
            line_without_urls = self.url_pattern.sub(' ', line)
            for match in self.path_pattern.findall(line_without_urls):
                path = self._clean_endpoint(match)
                if not path or path.startswith('//') or self._is_ignored_path(path) or '/**/' in path or path.startswith('/*') or len(path) < 3:
                    continue
                paths.append(path)
        return self._dedupe_keep_order(paths)[:20]

    def _mask_secret(self, value: str) -> str:
        text = str(value or '')
        if len(text) <= 2:
            return '*' * len(text)
        if len(text) <= 6:
            return text[0] + '*' * (len(text) - 1)
        return text[:2] + '*' * (len(text) - 4) + text[-2:]

    def _extract_credentials(self, lines: List[str]) -> List[Dict[str, str]]:
        credentials: List[Dict[str, str]] = []
        patterns = [
            re.compile(r'(?:账号密码|账户密码|用户名密码|用户密码)\s*[:：]\s*([^\s/：:，,;；]+)\s*/\s*([^\s，,;；。]+)', re.IGNORECASE),
            re.compile(r'(?:用户(?:名)?|账号|账户|账号密码|登录名)\s*/?\s*(?:密码|口令)?\s*[:：]\s*([^\s/：:，,;；]+)\s*/\s*([^\s，,;；。]+)', re.IGNORECASE),
            re.compile(r'(?:用户(?:名)?|账号|账户|登录名)\s*[:：]\s*([^\s，,;；]+).*?(?:密码|口令)\s*[:：]\s*([^\s，,;；。]+)', re.IGNORECASE),
            re.compile(r'(?:user(?:name)?|account)\s*[:：]\s*([^\s，,;；]+).*?(?:pass(?:word)?|pwd)\s*[:：]\s*([^\s，,;；。]+)', re.IGNORECASE),
        ]
        for line in lines:
            for pattern in patterns:
                match = pattern.search(line)
                if not match:
                    continue
                username = self._clean_endpoint(match.group(1))
                password = self._clean_endpoint(match.group(2))
                if username and password:
                    credentials.append({'username': username, 'password': password, 'password_masked': self._mask_secret(password), 'evidence': line.replace(password, self._mask_secret(password))})
                    break
        return credentials[:8]

    def _extract_sections(self, lines: List[str]) -> Dict[str, List[str]]:
        sections: Dict[str, List[str]] = {}
        all_headings = tuple(alias for aliases in self.section_aliases.values() for alias in aliases)
        for section_name, aliases in self.section_aliases.items():
            for index, line in enumerate(lines):
                if not any(alias in line for alias in aliases):
                    continue
                collected: List[str] = [line]
                for follow in lines[index + 1:index + 13]:
                    if any(heading in follow for heading in all_headings) and len(collected) > 1:
                        break
                    collected.append(follow)
                sections[section_name] = collected[:12]
                break
        return sections

    def _extract_issue_tags(self, text: str, vulnerability_types: Optional[List[str]]) -> List[str]:
        source = '\n'.join([text, ' '.join(vulnerability_types or [])]).lower()
        tags: List[str] = []
        for tag, keywords in self.context_tag_keywords.items():
            if any(keyword.lower() in source for keyword in keywords):
                tags.append(tag)
        return self._dedupe_keep_order(tags)

    def _extract_expected_status_codes(self, lines: List[str]) -> List[int]:
        status_codes: List[int] = []
        for line in lines:
            if not any(key in line for key in ('状态码', '响应码', 'HTTP', 'http', '返回', '响应')):
                continue
            status_codes.extend(int(code) for code in re.findall(r'\b(20\d|30\d|40\d|50\d)\b', line))
        return list(dict.fromkeys(status_codes))[:8]

    def _extract_expected_markers(self, text: str) -> List[str]:
        normalized = text.lower()
        return self._dedupe_keep_order([marker for marker in self.evidence_markers if marker.lower() in normalized])[:16]

    def _extract_parameter_names(self, urls: List[str], lines: List[str]) -> List[str]:
        params: List[str] = []
        for url in urls:
            parsed = urlparse(url)
            if parsed.query:
                params.extend(re.findall(r'([A-Za-z_][A-Za-z0-9_-]{0,40})=', parsed.query))
        for line in lines:
            params.extend(re.findall(r'(?:参数|字段|param|parameter)\s*[:：]?\s*([A-Za-z_][A-Za-z0-9_-]{1,40})', line, flags=re.IGNORECASE))
        return self._dedupe_keep_order(params)[:20]

    def _looks_like_retest_stop_line(self, line: str) -> bool:
        text = str(line or '').strip()
        return bool(
            self.request_line_pattern.match(text)
            or re.match(r'^\d+[\.．、]\s*(?:处置|整改|修复|建议|影响|附件)', text)
            or any(marker in text for marker in ('处置措施', '整改建议', '修复建议', '三、整改', '整改要求'))
        )

    def _request_url_from_parts(self, target: str, headers: Dict[str, str], target_urls: List[str]) -> str:
        target = self._clean_endpoint(target)
        if target.startswith(('http://', 'https://')):
            return target
        host = headers.get('Host') or headers.get('host') or ''
        scheme = 'http'
        for url in target_urls:
            parsed = urlparse(url)
            if parsed.scheme:
                scheme = parsed.scheme
            if parsed.hostname and host and parsed.netloc.lower() == host.lower():
                break
        if host:
            path = target if target.startswith('/') else f'/{target}'
            return f'{scheme}://{host}{path}'
        return urljoin(target_urls[0], target) if target_urls else target

    def _extract_http_request_candidates(self, lines: List[str], target_urls: List[str]) -> List[Dict[str, object]]:
        requests: List[Dict[str, object]] = []
        for index, line in enumerate(lines):
            match = self.request_line_pattern.match(line)
            if not match:
                continue
            method = match.group(1).upper()
            target = self._clean_endpoint(match.group(2))
            headers: Dict[str, str] = {}
            body_lines: List[str] = []
            evidence_lines: List[str] = []
            phase = 'headers'
            for follow in lines[index + 1:index + 90]:
                if self._looks_like_retest_stop_line(follow):
                    break
                if any(marker in follow for marker in ('返回', '响应', '拼接路径', '访问路径', '文件路径', '成功', '失败')):
                    evidence_lines.append(follow[:220])
                    if phase == 'body' and follow.startswith(('返回', '响应', '拼接路径')):
                        continue
                header_match = re.match(r'^([A-Za-z][A-Za-z0-9_.-]{1,60})\s*:\s*(.*)$', follow)
                if phase == 'headers' and header_match:
                    headers[header_match.group(1)] = header_match.group(2).strip()
                    continue
                phase = 'body'
                body_lines.append(follow)
            url = self._request_url_from_parts(target, headers, target_urls)
            if url.startswith(('http://', 'https://')):
                requests.append({'method': method, 'target': target, 'url': url, 'headers': headers, 'body': '\r\n'.join(body_lines).strip()[:120000], 'body_line_count': len(body_lines), 'evidence_lines': evidence_lines[:8], 'source_line': line})
        return requests[:8]

    def _extract_payload_candidates(self, lines: List[str], target_urls: List[str]) -> List[Dict[str, str]]:
        payloads: List[Dict[str, str]] = []
        payload_keywords = ('sleep(', 'union', 'select', 'or ', 'and ', '<script', '%3c', 'alert(', '../', '..\\')
        for line in lines:
            text = line.strip()
            if not text or self.request_line_pattern.match(text) or '=' not in text:
                continue
            if ':' in text[:40] and not text.lower().startswith(('http://', 'https://')):
                continue
            if not any(keyword in text.lower() for keyword in payload_keywords):
                continue
            raw_payload = re.split(r'(第[一二三四五六七八九十]+个|当前数据库名|ascii码|返回|响应|验证截图)', text, 1)[0].strip()
            parameter_match = re.match(r'([A-Za-z_][A-Za-z0-9_-]{0,60})\s*=', raw_payload)
            if parameter_match:
                payloads.append({'raw': raw_payload[:6000], 'parameter': parameter_match.group(1), 'url': target_urls[0] if target_urls else '', 'evidence': text[:220]})
        return payloads[:8]

    def _line_has_context_signal(self, line: str) -> bool:
        if self.url_pattern.search(line) or self.path_pattern.search(line):
            return True
        if re.search(r'\b(20\d|30\d|40\d|50\d)\b', line) and any(key in line for key in ('状态', '响应', 'HTTP', '返回')):
            return True
        line_lower = line.lower()
        return any(marker.lower() in line_lower for marker in self.evidence_markers) or any(
            keyword.lower() in line_lower for keywords in self.context_tag_keywords.values() for keyword in keywords
        )
