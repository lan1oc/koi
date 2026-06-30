#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HTTP evidence formatting helpers for retest tools."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping
from urllib.parse import urlparse


SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "token",
    "proxy-authorization",
}
SENSITIVE_BODY_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "apikey",
}
BODY_PREVIEW_LIMIT = 4000
REQUEST_BODY_LIMIT = 8000
_CHARSET_RE = re.compile(r"charset\s*=\s*['\"]?([^;,'\"\s]+)", re.IGNORECASE)
_MOJIBAKE_RE = re.compile(
    r"[ÃÂâ][\x80-\xff\u0152\u0153\u0160\u0161\u0178\u017d\u017e]?"
    r"|[æåèéç][\x80-\xff\u0152\u0153\u0160\u0161\u0178\u017d\u017e]"
    r"|�"
)
_MOJIBAKE_FRAGMENT_RE = re.compile(
    r"[\x80-\xff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192"
    r"\u02c6\u02dc\u2013-\u201e\u2020-\u2026\u2030\u2039\u203a"
    r"\u20ac\u2122]{2,}"
)
_MOJIBAKE_RUN_RE = re.compile(
    r"[\x80-\xff\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192"
    r"\u02c6\u02dc\u2013-\u201e\u2020-\u2026\u2030\u2039\u203a"
    r"\u20ac\u2122A-Za-z0-9_\-/%?&=:.#]{2,}"
)


def repair_utf8_mojibake(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    original_score = _decode_score(text)

    def decode_fragment(fragment: str) -> str:
        best = fragment
        best_score = _decode_score(fragment)
        for encoding in ("latin-1", "cp1252"):
            try:
                candidate = fragment.encode(encoding).decode("utf-8")
            except Exception:
                continue
            score = _decode_score(candidate)
            if candidate != fragment and score > best_score:
                best = candidate
                best_score = score
        return best

    repaired = decode_fragment(text)
    if repaired != text and _decode_score(repaired) > original_score:
        return repaired

    if not _MOJIBAKE_RE.search(text):
        return text

    def replace_match(match: re.Match[str]) -> str:
        return decode_fragment(match.group(0))

    best_text = text
    best_score = original_score
    for pattern in (_MOJIBAKE_FRAGMENT_RE, _MOJIBAKE_RUN_RE):
        try:
            repaired = pattern.sub(replace_match, text)
        except Exception:
            continue
        score = _decode_score(repaired)
        if repaired != text and score > best_score:
            best_text = repaired
            best_score = score
    if best_text != text:
        return best_text

    # Some mixed strings contain ASCII punctuation between mojibake bytes. Repair
    # the obvious fragments even when the whole-line score is only a small gain.
    return text


def _decode_score(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    mojibake = len(_MOJIBAKE_RE.findall(text))
    replacement = text.count("\ufffd")
    controls = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text))
    return cjk * 3 - mojibake * 8 - replacement * 12 - controls * 5


def _candidate_encodings(response: Any, headers: Mapping[str, Any]) -> Iterable[str]:
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    match = _CHARSET_RE.search(content_type)
    if match:
        yield match.group(1).strip()
    for attr in ("encoding", "apparent_encoding"):
        encoding = str(getattr(response, attr, "") or "").strip()
        if encoding:
            yield encoding
    yield "utf-8"
    yield "gb18030"
    yield "latin-1"


def decode_response_text(response: Any) -> str:
    content = getattr(response, "content", b"") or b""
    headers = getattr(response, "headers", {}) or {}
    if not content:
        try:
            return repair_utf8_mojibake(str(getattr(response, "text", "") or ""))
        except Exception:
            return ""

    best_text = ""
    best_score = -10**9
    seen: set[str] = set()
    for raw_encoding in _candidate_encodings(response, headers):
        encoding = str(raw_encoding or "").strip().lower()
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            decoded = content.decode(encoding, errors="replace")
        except Exception:
            continue
        decoded = repair_utf8_mojibake(decoded)
        score = _decode_score(decoded)
        if encoding in {"utf-8", "utf8"}:
            score += 2
        if score > best_score:
            best_score = score
            best_text = decoded
    if best_text:
        return best_text
    try:
        return repair_utf8_mojibake(str(getattr(response, "text", "") or ""))
    except Exception:
        return content.decode("utf-8", errors="replace")


def safe_headers(headers: Mapping[str, Any] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in (headers or {}).items():
        name = str(key)
        text = str(value)
        if name.lower() in SENSITIVE_HEADER_NAMES:
            out[name] = "<redacted>"
        else:
            out[name] = text[:1000]
    return out


def redact_text(value: Any, limit: int = REQUEST_BODY_LIMIT) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = text[:limit]
    for key in SENSITIVE_BODY_KEYS:
        text = re.sub(
            rf"(?i)({re.escape(key)}[\"'\s:=]+)([^&\s,\"'}}]+)",
            rf"\1<redacted>",
            text,
        )
        text = re.sub(
            rf"(?i)({re.escape(key)}[^=&\s]{{0,24}}=)([^&\s]+)",
            rf"\1<redacted>",
            text,
        )
    return text


def format_http_request(method: str, url: str, headers: Mapping[str, Any] | None = None, body: Any = "") -> str:
    parsed = urlparse(str(url or ""))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    path = redact_text(path, limit=4000)
    lines = [f"{str(method or 'GET').upper()} {path} HTTP/1.1"]
    host = parsed.netloc
    if host:
        lines.append(f"Host: {host}")
    for key, value in safe_headers(headers).items():
        if str(key).lower() in {"host", "content-length"}:
            continue
        lines.append(f"{key}: {value}")
    safe_body = redact_text(body)
    if safe_body:
        lines.append("")
        lines.append(safe_body)
    return "\n".join(lines)


def response_body_preview(response: Any, limit: int = BODY_PREVIEW_LIMIT) -> str:
    content = getattr(response, "content", b"") or b""
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type") or "").lower()
    is_text = any(
        marker in content_type
        for marker in ("text/", "json", "xml", "javascript", "html", "x-www-form-urlencoded")
    )
    if not is_text and content:
        prefix = content[:512]
        if b"\x00" in prefix:
            digest = hashlib.sha256(content).hexdigest()[:16]
            return f"<binary response: {len(content)} bytes, sha256={digest}, content-type={content_type or '-'}>"
    text = decode_response_text(response)
    if len(text) > limit:
        return text[:limit] + "\n... <truncated>"
    return text


def response_meta(response: Any, meta: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    base = dict(meta or {})
    headers = getattr(response, "headers", {}) or {}
    base.setdefault("status_code", getattr(response, "status_code", None))
    base.setdefault("final_url", getattr(response, "url", ""))
    base.setdefault("content_length", len(getattr(response, "content", b"") or b""))
    base["content_type"] = str(headers.get("Content-Type") or "")
    return base


def format_http_response(response: Any, meta: Mapping[str, Any] | None = None) -> str:
    data = response_meta(response, meta)
    status_code = data.get("status_code") or "-"
    lines = [f"HTTP {status_code}"]
    for key, value in safe_headers(getattr(response, "headers", {}) or {}).items():
        lines.append(f"{key}: {value}")
    body = response_body_preview(response)
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines)


def build_http_exchange(method: str, url: str, headers: Mapping[str, Any] | None, body: Any, response: Any, meta: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    req = format_http_request(method, url, headers, body)
    res_meta = response_meta(response, meta)
    headers_safe = safe_headers(getattr(response, "headers", {}) or {})
    body_preview = response_body_preview(response)
    return {
        "request_raw": req,
        "request_safe": req,
        "response_meta": res_meta,
        "response_headers_safe": headers_safe,
        "response_body_preview": body_preview,
        "response_raw_excerpt": format_http_response(response, res_meta),
    }


def compact_exchange_text(exchange: Mapping[str, Any]) -> str:
    request_text = str(exchange.get("request_safe") or exchange.get("request_raw") or "")
    response_text = str(exchange.get("response_raw_excerpt") or exchange.get("response_body_preview") or "")
    return "\n\n".join(
        part for part in (
            "=== 重放请求包 ===\n" + request_text if request_text else "",
            "=== 响应数据 ===\n" + response_text if response_text else "",
        )
        if part
    )


def exchange_to_json_preview(exchange: Mapping[str, Any], limit: int = 12000) -> str:
    text = json.dumps(dict(exchange), ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "\n... <truncated>"
