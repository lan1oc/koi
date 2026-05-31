"""Helpers for preserving browser-like Cookie headers.

The enterprise query modules store Cookie headers in config.json.  A plain
dict loses same-name cookies from different domains, so these helpers keep the
ordered header string as the durable representation and only build dicts for
places that need quick lookup, such as auth_token headers.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Iterable, List, Optional


def cookie_domain_matches_host(domain: str, host: str) -> bool:
    domain = (domain or "").lower().lstrip(".")
    host = (host or "").lower()
    return bool(domain and host and (host == domain or host.endswith("." + domain)))


def cookie_header_to_map(cookie_header: str) -> Dict[str, str]:
    cookie_map: Dict[str, str] = {}
    for item in str(cookie_header or "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookie_map[name] = value
    return cookie_map


def cookie_map_to_header(cookie_map: Dict[str, str]) -> str:
    if not cookie_map:
        return ""
    return "; ".join(f"{name}={value}" for name, value in cookie_map.items() if name and value is not None)


def cookie_input_to_header(cookies: Any, url: str = "") -> str:
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return "; ".join(item.strip() for item in cookies.split(";") if item.strip())
    if isinstance(cookies, dict):
        return cookie_map_to_header({str(k): str(v) for k, v in cookies.items() if k and v is not None})
    if hasattr(cookies, "__iter__"):
        return browser_cookie_data_to_header_for_url(cookies, url)
    return ""


def _cookie_iterable(cookie_data: Any, url: str) -> Iterable[Dict[str, Any]]:
    try:
        parsed = urllib.parse.urlparse(url or "https://www.tianyancha.com/")
        host = parsed.hostname or "www.tianyancha.com"
    except Exception:
        host = "www.tianyancha.com"

    if isinstance(cookie_data, dict):
        for name, value in cookie_data.items():
            yield {"name": name, "value": value, "domain": host, "path": "/"}
        return

    if isinstance(cookie_data, list):
        iterable = cookie_data
    else:
        iterable = list(cookie_data) if hasattr(cookie_data, "__iter__") else []

    for item in iterable:
        if isinstance(item, dict):
            yield item
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, value = item
            yield {"name": name, "value": value, "domain": host, "path": "/"}
        elif hasattr(item, "name") and hasattr(item, "value"):
            yield {
                "name": getattr(item, "name", ""),
                "value": getattr(item, "value", ""),
                "domain": getattr(item, "domain", "") or host,
                "path": getattr(item, "path", "") or "/",
            }


def browser_cookie_data_to_header_for_url(cookie_data: Any, url: str) -> str:
    if not cookie_data:
        return ""
    try:
        parsed = urllib.parse.urlparse(url or "https://www.tianyancha.com/")
        host = parsed.hostname or "www.tianyancha.com"
        req_path = parsed.path or "/"
    except Exception:
        host = "www.tianyancha.com"
        req_path = "/"

    parts: List[str] = []
    for item in _cookie_iterable(cookie_data, url):
        name = item.get("name") or item.get("key")
        value = item.get("value")
        domain = str(item.get("domain", "") or host)
        path = str(item.get("path", "") or "/")
        if not name or value is None:
            continue
        if domain and not cookie_domain_matches_host(domain, host):
            continue
        if path and not req_path.startswith(path.rstrip("/") or "/"):
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def get_page_cookie_data(page: Any, all_domains: bool = False) -> Optional[Any]:
    try:
        cookies = getattr(page, "cookies", None)
        if callable(cookies):
            try:
                cookies = cookies(all_domains=all_domains)
            except TypeError:
                cookies = cookies()
            except Exception:
                cookies = None
        if cookies:
            return cookies
    except Exception:
        pass

    for attr in ("get_cookies", "cookies"):
        try:
            method = getattr(page, attr, None)
            if callable(method):
                cookies = method()
                if cookies:
                    return cookies
        except Exception:
            pass
    return None


def get_browser_cookie_header_for_url(page: Any, url: str) -> str:
    try:
        runner = getattr(page, "run_cdp", None)
        if callable(runner):
            raw = runner("Network.getCookies", urls=[url])
            cookies = raw.get("cookies") if isinstance(raw, dict) else None
            header = browser_cookie_data_to_header_for_url(cookies, url)
            if header:
                return header
    except Exception:
        pass
    return browser_cookie_data_to_header_for_url(get_page_cookie_data(page, all_domains=True), url)
