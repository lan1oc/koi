#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爱企查企业信息查询脚本
功能：通过企业名称查询企业的详细信息，包括基本信息、行业分类、ICP备案、员工联系方式等
"""

import ast
import requests
from requests.cookies import create_cookie
import json
import time
import urllib.parse
import random
import os
import shutil
import sys
import tempfile
import re
import html
from datetime import datetime
from typing import Dict, List, Optional
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    HAS_CURL_CFFI = False

try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

try:
    from .cookie_manager import ChromeCookieManager
    HAS_CHROME_COOKIE_MANAGER = True
except ImportError:
    try:
        from cookie_manager import ChromeCookieManager
        HAS_CHROME_COOKIE_MANAGER = True
    except ImportError:
        HAS_CHROME_COOKIE_MANAGER = False


class AiqichaQuery:
    # 与用户浏览器抓包对齐（Chrome 147 + Client Hints），搜索 GET /s 等同款
    AIQICHA_CHROME_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    )
    AIQICHA_SEC_CH_UA = (
        '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"'
    )

    def __init__(self):
        self.session = requests.Session()
        
        # 静态 User-Agent 列表（作为备用）
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'
        ]
        
        # 反爬配置 - 在初始化时捕获 fake_useragent 的运行时异常
        self.use_fake_ua = False
        self.ua = None
        if HAS_FAKE_UA:
            try:
                self.ua = UserAgent()
                # 测试是否能正常获取 UA（打包后可能失败）
                _ = self.ua.random
                self.use_fake_ua = True
            except Exception:
                # fake_useragent 初始化或使用失败，降级到静态列表
                self.use_fake_ua = False
                self.ua = None
        
        # 请求间隔配置（秒）- 进一步减少延时以提高用户体验
        self.min_delay = 0.3
        self.max_delay = 0.8
        self.last_request_time = 0
        
        # 设置通用请求头
        initial_ua = self._get_random_ua()
        self.session.headers.update({
            'User-Agent': initial_ua,
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
        })
        
        # 初始化 Cookie 容器（固定 dict 身份，便于请求参数始终引用最新键值）
        self.aiqicha_cookies = {}
        self.xunkebao_cookies = {}
        self.aiqicha_cookie_raw = ""
        self.xunkebao_cookie_raw = ""
        self.debug_output_enabled = False
        self.debug_output_dir = None
        self._opened_browser_pages = []
        # 与 tianyancha_query 对齐：验证浏览器捕获的页面、挂起关闭回调、页面引用
        self._verification_page_capture = None
        self._pending_browser_close = None
        self._verification_page_ref = None
        self._last_inner_config_reload_ts = 0.0
        self._browser_profile_dir = None
        self._load_config()

    def reload_session_cookies_from_config(self) -> None:
        """
        不启动浏览器：从 config.json 读取爱企查/寻客宝 Cookie，
        写入 self.aiqicha_cookies / self.xunkebao_cookies，并灌入 requests.Session（与 DrissionPage 预置同源）。
        """
        self._load_config()
    
    def _load_config(self):
        """从配置文件加载 Cookie，并重建 Session 罐（不依赖浏览器）。"""
        try:
            from modules.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            config = config_manager.get_config()
            self.config_path = config_manager.config_file_path
            if self.config_path:
                debug_output_dir = os.path.join(os.path.dirname(self.config_path), 'debug_output')
            else:
                debug_output_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_output')
            self.debug_output_dir = os.path.abspath(debug_output_dir)
            os.makedirs(self.debug_output_dir, exist_ok=True)

            aiqicha_config = config.get('aiqicha', {})
            cookie_str = aiqicha_config.get('cookie', '')
            self.aiqicha_cookie_raw = str(cookie_str or "").strip()

            self.aiqicha_cookies.clear()
            if cookie_str:
                for item in cookie_str.split(';'):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        self.aiqicha_cookies[key] = value

            xunkebao_config = config.get('xunkebao', {})
            xunkebao_cookie_str = xunkebao_config.get('cookie', '')
            if not xunkebao_cookie_str:
                xunkebao_cookie_str = aiqicha_config.get('xunkebao_cookie', '')
            self.xunkebao_cookie_raw = str(xunkebao_cookie_str or "").strip()

            self.xunkebao_cookies.clear()
            if xunkebao_cookie_str:
                for item in xunkebao_cookie_str.split(';'):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        self.xunkebao_cookies[key] = value

            debug_config = config.get('debug', {})
            self.debug_output_enabled = debug_config.get('aiqicha_debug_output', False)
            self._rebuild_session_cookies_from_config()
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            self.aiqicha_cookies.clear()
            self.xunkebao_cookies.clear()
            self.aiqicha_cookie_raw = ""
            self.xunkebao_cookie_raw = ""
            self.debug_output_enabled = False
            self.debug_output_dir = None

    def _rebuild_session_cookies_from_config(self) -> None:
        """清空 Session Cookie 罐并按当前配置重建，避免历史 Set-Cookie 与配置混用。"""
        try:
            self.session.cookies.clear()
        except Exception:
            pass
        merged: Dict[str, str] = {}
        merged.update(self.xunkebao_cookies)
        merged.update(self.aiqicha_cookies)
        for name, value in merged.items():
            if not name:
                continue
            try:
                c = create_cookie(
                    str(name),
                    str(value) if value is not None else "",
                    domain=".baidu.com",
                    path="/",
                )
                self.session.cookies.set_cookie(c)
            except Exception:
                try:
                    self.session.cookies.set(name, value)
                except Exception:
                    pass

    def _stable_aiqicha_client_ua(self) -> str:
        """本会话固定 Chrome UA（与 AIQICHA_CHROME_UA 一致）；随机 UA 易被百度判为新设备。"""
        cached = getattr(self, "_cached_stable_aiqicha_ua", None)
        if not cached:
            self._cached_stable_aiqicha_ua = AiqichaQuery.AIQICHA_CHROME_UA
            cached = self._cached_stable_aiqicha_ua
        return cached

    def _aiqicha_browser_document_headers(self, referer: str) -> Dict[str, str]:
        """GET /s、company_detail 等文档导航：与用户提供的 Chrome 抓包头字段一致（Cookie 走 Session）。"""
        return {
            "Host": "aiqicha.baidu.com",
            "Connection": "keep-alive",
            "sec-ch-ua": AiqichaQuery.AIQICHA_SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self._stable_aiqicha_client_ua(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Referer": referer,
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    
    @property
    def cookie(self):
        """获取Cookie字符串"""
        if not self.aiqicha_cookies:
            return ''
        return '; '.join([f'{k}={v}' for k, v in self.aiqicha_cookies.items()])
    
    @cookie.setter
    def cookie(self, cookie_str: str):
        """设置爱企查 Cookie 字符串并立即同步到 Session（无需写回配置文件也会生效于 requests）。"""
        self.aiqicha_cookies.clear()
        self.aiqicha_cookie_raw = str(cookie_str or "").strip()
        if cookie_str:
            for item in cookie_str.split(';'):
                if '=' in item:
                    key, value = item.strip().split('=', 1)
                    self.aiqicha_cookies[key] = value
        self._rebuild_session_cookies_from_config()

    def _sync_session_from_aiqicha_cookies(self) -> None:
        """验证后写回 Session：与配置一致地重建整罐 Cookie（含寻客宝）。"""
        self._rebuild_session_cookies_from_config()

    def _raw_cookie_for_url(self, url: str) -> str:
        """返回配置中的原始 Cookie 字符串，避免 requests CookieJar 重排/改写风控 Cookie。"""
        u = (url or "").lower()
        if "xunkebao.baidu.com" in u:
            return (
                getattr(self, "xunkebao_cookie_raw", "")
                or getattr(self, "aiqicha_cookie_raw", "")
                or self._cookie_map_to_string(self.xunkebao_cookies or self.aiqicha_cookies)
            )
        if "aiqicha.baidu.com" in u:
            return getattr(self, "aiqicha_cookie_raw", "") or self._cookie_map_to_string(self.aiqicha_cookies)
        return ""

    def _merge_response_cookies_into_runtime_header(self, url: str, response) -> None:
        """合并响应 Set-Cookie 到本次运行时 Cookie header，避免重试继续发送旧配置 Cookie。"""
        u = (url or "").lower()
        if "aiqicha.baidu.com" not in u and "xunkebao.baidu.com" not in u:
            return

        fresh: Dict[str, str] = {}
        try:
            fresh.update(self._cookie_data_to_map(getattr(response, "cookies", None)))
        except Exception:
            pass
        try:
            fresh.update(self._cookie_data_to_map(getattr(self.session, "cookies", None)))
        except Exception:
            pass
        fresh = {k: v for k, v in fresh.items() if k and v is not None}
        if not fresh:
            return

        if "xunkebao.baidu.com" in u:
            current = self._cookie_data_to_map(
                getattr(self, "xunkebao_cookie_raw", "")
                or getattr(self, "aiqicha_cookie_raw", "")
                or self._cookie_map_to_string(self.xunkebao_cookies or self.aiqicha_cookies)
            )
            current.update(fresh)
            self.xunkebao_cookies.clear()
            self.xunkebao_cookies.update(current)
            self.xunkebao_cookie_raw = self._cookie_map_to_string(current)
        else:
            current = self._cookie_data_to_map(
                getattr(self, "aiqicha_cookie_raw", "")
                or self._cookie_map_to_string(self.aiqicha_cookies)
            )
            current.update(fresh)
            self.aiqicha_cookies.clear()
            self.aiqicha_cookies.update(current)
            self.aiqicha_cookie_raw = self._cookie_map_to_string(current)

        self._rebuild_session_cookies_from_config()

    def _has_aiqicha_login_cookie_signal(self) -> bool:
        cookies = getattr(self, "aiqicha_cookies", {}) or {}
        if cookies.get("BDUSS") and len(str(cookies.get("BDUSS") or "")) > 16:
            return True
        if cookies.get("BDUSS_BFESS") and len(str(cookies.get("BDUSS_BFESS") or "")) > 16:
            return True
        if cookies.get("STOKEN") or cookies.get("PTOKEN"):
            return True
        return any(
            any(marker in str(name).upper() for marker in ("BDUSS", "STOKEN", "PTOKEN", "LOGIN", "USER"))
            for name in cookies
        )

    def _validate_aiqicha_browser_cookies(self, cookies_list) -> bool:
        """
        校验 DrissionPage page.cookies() 列表是否像已登录百度系账号（对标 TianyanchaQuery._validate_cookies）。
        不依赖 requests 二次探测，避免浏览器与 requests 环境不一致导致永远失败。
        """
        if not cookies_list:
            return False
        cookies_dict: Dict[str, str] = {}
        for cookie in cookies_list:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            if name and value is not None:
                cookies_dict[str(name)] = str(value)
        if not cookies_dict:
            return False
        if cookies_dict.get("BDUSS") and len(cookies_dict["BDUSS"]) > 16:
            return True
        if cookies_dict.get("BDUSS_BFESS") and len(cookies_dict["BDUSS_BFESS"]) > 16:
            return True
        if cookies_dict.get("STOKEN") or cookies_dict.get("PTOKEN"):
            return True
        userish = [
            n
            for n in cookies_dict
            if any(
                k in n.upper()
                for k in ("BDUSS", "TOKEN", "PASS", "UID", "USER", "LOGIN", "BAIDU")
            )
        ]
        if len(userish) >= 2 and len(cookies_dict) >= 10:
            return True
        return False

    def _html_suggests_baidu_passport_scan_login(self, html_content: str) -> bool:
        """百度账号扫码/登录页（配置里预置的 BDUSS 仍会让 cookie 校验为真，必须单独拦住）。"""
        if not html_content or len(html_content) < 500:
            return False
        h = html_content.lower()
        structural = (
            "tang-pass-qrcode",
            "tang-pass-tab",
            "pass-login-wrapper",
            "pass-reglink",
            "pass-login-pop",
        )
        if any(x in h for x in structural):
            return True
        text_markers = (
            "请使用百度app扫一扫登录",
            "请使用百度app扫码登录",
            "请使用百度app扫码",
        )
        return any(m in h for m in text_markers)

    def _is_aiqicha_url_or_html_blocked_for_finish(self, cur_url: str, html_content: str) -> bool:
        """仍在人机/账号验证链上时不应判定为「验证完成」（以 URL 为主，减轻正文误伤）。"""
        u = (cur_url or "").lower()
        if "wappass.baidu.com" in u:
            return True
        if "passport.baidu.com" in u:
            return True
        if "verify.baidu.com" in u:
            return True
        if not html_content or len(html_content) < 400:
            return False
        h = html_content.lower()
        # 勿根据正文中的 wappass 域名拦截：爱企查正常搜索页脚本/JSON 常含该字符串，会误判为一直 blocked
        if "请点击开始验证" in html_content or "请完成验证" in html_content:
            return True
        if "人机验证" in html_content or "百度安全验证" in html_content:
            return True
        if self._html_suggests_baidu_passport_scan_login(html_content):
            return True
        return False

    def _verification_search_html_has_list_signal(self, html_content: str) -> bool:
        """搜索页已出现可解析的列表/结果结构（避免仅凭旧 Cookie 或 absorbed JSON 误判结束）。"""
        if not html_content or len(html_content) < 800:
            return False
        if 'data-log-title="item-' in html_content or 'class="company-list"' in html_content:
            return True
        # 非空 resultList；仅 absorbed 时常为 [] 或仅有 absorbed 块
        return bool(
            re.search(r'"resultList"\s*:\s*\[\s*\{', html_content, re.I)
        )

    def _cookie_data_to_map(self, cookie_data):
        cookie_map = {}
        if not cookie_data:
            return cookie_map
        if isinstance(cookie_data, dict):
            for key, value in cookie_data.items():
                if key and value:
                    cookie_map[str(key)] = str(value)
            return cookie_map
        if isinstance(cookie_data, list):
            for item in cookie_data:
                if isinstance(item, dict):
                    name = item.get('name') or item.get('key')
                    value = item.get('value')
                    domain = str(item.get('domain', '') or '')
                    if domain and 'baidu.com' not in domain:
                        continue
                    if name and value:
                        cookie_map[str(name)] = str(value)
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    name, value = item
                    if name and value:
                        cookie_map[str(name)] = str(value)
            return cookie_map
        if hasattr(cookie_data, 'get_dict'):
            try:
                return self._cookie_data_to_map(cookie_data.get_dict())
            except Exception:
                return cookie_map
        if hasattr(cookie_data, 'all'):
            try:
                return self._cookie_data_to_map(cookie_data.all())
            except Exception:
                return cookie_map
        return cookie_map

    def _cookie_map_to_string(self, cookie_map: Dict[str, str]) -> str:
        if not cookie_map:
            return ''
        return '; '.join([f'{k}={v}' for k, v in cookie_map.items() if k and v])

    def _cookie_string_to_browser_cookie_list(self, cookie_str: str) -> List[Dict[str, object]]:
        """把配置中的百度系 Cookie 转成浏览器运行时可注入的结构。"""
        cookies: List[Dict[str, object]] = []
        seen = set()
        expires = int(time.time()) + 180 * 24 * 60 * 60
        for item in str(cookie_str or "").split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name or not value or name in seen:
                continue
            seen.add(name)
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".baidu.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "expires": expires,
            })
        return cookies

    def _inject_aiqicha_cookies_into_browser(self, page, cookie_str: str) -> bool:
        """
        运行时注入 Cookie，而不是手写 Chrome Cookies SQLite。
        新版 Chrome 会校验/迁移 Cookie 库结构，直接写库容易被忽略或清空。
        """
        cookies = self._cookie_string_to_browser_cookie_list(cookie_str)
        if not cookies:
            return False
        try:
            page.get("https://aiqicha.baidu.com/", timeout=25)
        except Exception:
            pass

        errors = []
        try:
            browser = getattr(page, "browser", None)
            setter = getattr(getattr(browser, "set", None), "cookies", None)
            if callable(setter):
                setter(cookies)
                print(f"已通过浏览器运行时注入爱企查 Cookie：{len(cookies)} 条")
                return True
        except Exception as e:
            errors.append(str(e))

        try:
            setter = getattr(getattr(page, "set", None), "cookies", None)
            if callable(setter):
                setter(cookies)
                print(f"已通过页面运行时注入爱企查 Cookie：{len(cookies)} 条")
                return True
        except Exception as e:
            errors.append(str(e))

        try:
            runner = getattr(page, "run_cdp", None)
            if callable(runner):
                runner("Storage.setCookies", cookies=cookies)
                print(f"已通过 CDP 注入爱企查 Cookie：{len(cookies)} 条")
                return True
        except Exception as e:
            errors.append(str(e))

        if errors:
            print(f"浏览器运行时 Cookie 注入失败: {'; '.join(errors[-2:])}")
        return False

    def _get_browser_cookie_header_for_url(self, page, url: str) -> str:
        """返回浏览器对目标 URL 实际会发送的 Cookie 头，保留同名不同域 Cookie。"""
        try:
            runner = getattr(page, "run_cdp", None)
            if callable(runner):
                raw = runner("Network.getCookies", urls=[url])
                cookies = raw.get("cookies") if isinstance(raw, dict) else None
                if isinstance(cookies, list):
                    parts = []
                    for cookie in cookies:
                        if not isinstance(cookie, dict):
                            continue
                        name = cookie.get("name")
                        value = cookie.get("value")
                        if name and value is not None:
                            parts.append(f"{name}={value}")
                    if parts:
                        return "; ".join(parts)
        except Exception:
            pass
        return self._browser_cookie_data_to_header_for_url(
            self._get_page_cookie_data(page, all_domains=True),
            url,
        )

    def _cookie_domain_matches_host(self, domain: str, host: str) -> bool:
        domain = (domain or "").lower().lstrip(".")
        host = (host or "").lower()
        return bool(domain and host and (host == domain or host.endswith("." + domain)))

    def _browser_cookie_data_to_header_for_url(self, cookie_data, url: str) -> str:
        """从浏览器 Cookie 列表拼出目标 URL 可用的 Cookie header，保留同名项。"""
        if not cookie_data:
            return ""
        try:
            parsed = urllib.parse.urlparse(url or "https://aiqicha.baidu.com/")
            host = parsed.hostname or "aiqicha.baidu.com"
            req_path = parsed.path or "/"
        except Exception:
            host = "aiqicha.baidu.com"
            req_path = "/"

        parts = []
        if isinstance(cookie_data, dict):
            iterable = [{"name": k, "value": v, "domain": host, "path": "/"} for k, v in cookie_data.items()]
        else:
            iterable = cookie_data if isinstance(cookie_data, list) else []
        for item in iterable:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            value = item.get("value")
            domain = str(item.get("domain", "") or host)
            path = str(item.get("path", "") or "/")
            if not name or value is None:
                continue
            if domain and not self._cookie_domain_matches_host(domain, host):
                continue
            if path and not req_path.startswith(path.rstrip("/") or "/"):
                continue
            parts.append(f"{name}={value}")
        return "; ".join(parts)

    def _persist_browser_cookies_after_data_ready(
        self,
        page,
        target_url: str,
        fallback_cookie_map: Optional[Dict[str, str]] = None,
    ) -> bool:
        """数据页已经可解析后，保存此刻浏览器实际发送给目标 URL 的 Cookie。"""
        _ = fallback_cookie_map
        cookie_header = self._get_browser_cookie_header_for_url(page, target_url)
        if not cookie_header:
            print("⚠️ 未能读取浏览器实际发送的 Cookie header，暂不覆盖配置")
            return False
        self.cookie = cookie_header
        if self._save_aiqicha_cookie_to_config(cookie_header):
            print("✅ 已在数据页可解析后更新爱企查 Cookie 到配置文件")
            self._sync_session_from_aiqicha_cookies()
            try:
                self._load_config()
            except Exception:
                pass
            return True
        return False

    def _get_page_cookie_data(self, page, all_domains: bool = False):
        try:
            cookies = page.cookies
            if callable(cookies):
                try:
                    cookies = cookies(all_domains=all_domains)
                except TypeError:
                    cookies = cookies()
                except Exception:
                    pass
            if cookies:
                return cookies
        except Exception:
            pass
        for attr in ('get_cookies', 'cookies'):
            try:
                method = getattr(page, attr, None)
                if callable(method):
                    cookies = method()
                    if cookies:
                        return cookies
            except Exception:
                pass
        return None

    def _get_cookie_string_from_page(self, page) -> str:
        cookie_data = self._get_page_cookie_data(page)
        cookie_map = self._cookie_data_to_map(cookie_data)
        return self._cookie_map_to_string(cookie_map)

    def _cookie_dict_to_string(self, cookie_dict: Dict[str, str]) -> str:
        if not cookie_dict:
            return ""
        return "; ".join(f"{k}={v}" for k, v in sorted(cookie_dict.items()) if k and v)

    def _collect_cookies_from_drission_page(self, page) -> Dict[str, str]:
        """与天眼查一致：优先使用 page.cookies() 返回的列表，覆盖百度系域。"""
        out: Dict[str, str] = {}
        raw = None
        try:
            getter = getattr(page, "cookies", None)
            if callable(getter):
                try:
                    raw = getter(all_domains=True)
                except TypeError:
                    try:
                        raw = getter()
                    except Exception:
                        raw = None
        except Exception:
            raw = None
        if raw is None:
            try:
                raw = page.run_cdp("Network.getAllCookies") if hasattr(page, "run_cdp") else None
                if isinstance(raw, dict) and "cookies" in raw:
                    raw = raw["cookies"]
            except Exception:
                raw = None
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                val = item.get("value")
                dom = str(item.get("domain", "") or "").lower()
                if not name or val is None:
                    continue
                if "baidu.com" in dom or dom == "":
                    out[str(name)] = str(val)
            if out:
                return out
        return self._cookie_data_to_map(self._get_page_cookie_data(page))

    def _page_data_indicates_aiqicha_logged_in(self, html: str) -> bool:
        """未登录首页也有 window.pageData 且体积大，不能仅凭长度判断；需出现已登录标记。"""
        if not html:
            return False
        if re.search(r'"isLogin"\s*:\s*1\b', html):
            return True
        if re.search(r'"isLogin"\s*:\s*true\b', html, re.I):
            return True
        if re.search(r'"loginStatus"\s*:\s*1\b', html):
            return True
        if re.search(r'loginStatus["\']?\s*:\s*1', html):
            return True
        return False

    def _probe_aiqicha_search_usable(self, cookie_dict: Dict[str, str]) -> bool:
        """用搜索页二次探测：能出现企业列表结构则说明 Cookie 可用（比首页更可靠）。"""
        try:
            r = requests.get(
                "https://aiqicha.baidu.com/s?q=%E5%85%AC%E5%8F%B8&t=0",
                cookies=cookie_dict,
                headers={
                    "User-Agent": self._stable_aiqicha_client_ua(),
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://aiqicha.baidu.com/",
                },
                timeout=18,
                allow_redirects=True,
            )
            if r.status_code != 200:
                return False
            u = (getattr(r, "url", None) or "").lower()
            if "passport.baidu.com" in u or "wappass.baidu.com" in u:
                return False
            t = r.text or ""
            if "resultList" in t and '"pid"' in t:
                return True
            return False
        except Exception:
            return False

    def _probe_aiqicha_cookies_work(self, cookie_dict: Dict[str, str]) -> bool:
        """探测 Cookie 是否已能正常使用爱企查（已登录且可拉取页面数据，而非仅 HTTP 200）。"""
        if not cookie_dict:
            return False
        try:
            r = requests.get(
                "https://aiqicha.baidu.com/",
                cookies=cookie_dict,
                headers={
                    "User-Agent": self._stable_aiqicha_client_ua(),
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=18,
                allow_redirects=True,
            )
            if r.status_code != 200:
                return False
            u = (getattr(r, "url", None) or "").lower()
            if "passport.baidu.com" in u or "wappass.baidu.com" in u:
                return False
            t = r.text or ""
            if "window.pageData" not in t:
                return False
            # 未登录态首页也有 pageData，必须识别登录态或搜索页可用
            if self._page_data_indicates_aiqicha_logged_in(t):
                return len(t) > 800
            return self._probe_aiqicha_search_usable(cookie_dict)
        except Exception:
            return False

    def _save_aiqicha_cookie_to_config(self, cookie_str: str) -> bool:
        if not cookie_str:
            return False
        try:
            from modules.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            return config_manager.update_section('aiqicha', {
                'cookie': cookie_str
            })
        except Exception as e:
            print(f"保存爱企查Cookie失败: {e}")
            return False

    def _save_cookie_from_page(self, page, previous_cookie: str) -> bool:
        cookie_str = self._get_cookie_string_from_page(page)
        if not cookie_str:
            return False
        if previous_cookie:
            if cookie_str == previous_cookie:
                return False
            if self._normalize_cookie_string_for_compare(
                cookie_str
            ) == self._normalize_cookie_string_for_compare(previous_cookie):
                return False
        self.cookie = cookie_str
        self._save_aiqicha_cookie_to_config(cookie_str)
        return True

    def _normalize_cookie_string_for_compare(self, s: str) -> str:
        """排序后的 cookie 键值对，避免浏览器导出顺序不同导致误判为「已变化」。"""
        if not s:
            return ""
        parts = []
        for item in str(s).split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            parts.append(f"{k.strip()}={v.strip()}")
        parts.sort()
        return ";".join(parts)

    def _html_suggests_verification_gate(self, html_content: str) -> bool:
        """页面是否仍为人机/安全验证相关；排除极短页、404 等误报。"""
        if not html_content or len(html_content) < 800:
            return False
        h = html_content.lower()
        if any(x in h for x in ("nginx", "404 not found", "bad gateway", "error 404")):
            return False
        strong = (
            "人机验证",
            "请点击开始验证",
            "请完成验证",
            "百度安全验证",
        )
        if any(m in h for m in strong):
            return True
        if "passport.baidu.com/static" in h or "passport.baidu.com/v2" in h:
            return True
        if "verify.baidu.com" in h:
            return True
        return False

    def _html_requires_browser_verification(self, html_content: str) -> bool:
        """用于决定是否启动浏览器：只认明确验证文案/验证域名，避免正常页面里的登录脚本误伤。"""
        if not html_content:
            return False
        h = html_content.lower()
        strong_markers = (
            "人机验证",
            "请点击开始验证",
            "请完成验证",
            "百度安全验证",
            "请输入验证码",
            "滑动验证",
            "点击验证",
            "访问过于频繁",
            "访问异常",
            "访问受限",
            "security check",
        )
        if any(marker in h for marker in strong_markers):
            return True
        if self._html_suggests_baidu_passport_scan_login(html_content):
            return True
        if "verify.baidu.com" in h:
            return True
        return False

    def _wait_until_verification_done_then_save_cookies(
        self,
        page,
        previous_cookie_str: str,
        target_url: str,
        timeout_seconds: int = 600,
    ) -> bool:
        """
        对标 TianyanchaQuery._handle_captcha_verification 中 URL 检测线程逻辑：
        - 进入爱企查搜索页时捕获 HTML 到 _verification_page_capture；
        - 用 page.cookies() + _validate_aiqicha_browser_cookies 判断是否已具备登录态（不用 requests 误判）；
        - 持久化后 page.get(target_url) 再抓一页写入 capture，供 search_company 直接解析。
        previous_cookie_str 保留参数供将来扩展，当前以浏览器校验为准。
        """
        _ = previous_cookie_str
        self._verification_page_capture = None
        start = time.time()
        poll = 0.25
        stable_ok = 0
        tu0 = (target_url or "").lower()
        is_search_target = "aiqicha.baidu.com/s" in tu0 and "q=" in tu0
        # 搜索页须看到列表信号才结束；轮次略多，避免预置 Cookie 导致「未扫码就关浏览器」
        need_stable = 20 if is_search_target else 8
        last_url = ""
        consecutive_read_fail = 0
        max_read_fail = 40

        while time.time() - start < timeout_seconds:
            cur_url = ""
            html_content = ""
            url_ok = False
            html_ok = False
            try:
                cur_url = page.url or ""
                url_ok = True
            except Exception:
                pass
            try:
                html_content = page.html or ""
                html_ok = True
            except Exception:
                pass

            if not url_ok and not html_ok:
                consecutive_read_fail += 1
                if consecutive_read_fail >= max_read_fail:
                    print(
                        "长时间无法读取浏览器页面（可能已关闭窗口）。"
                        "请在验证完成并提示已保存 Cookie 前不要关闭浏览器。"
                    )
                    return False
                time.sleep(1)
                continue
            consecutive_read_fail = 0

            u = (cur_url or "").lower()
            hc = html_content or ""

            raw_list = None
            try:
                cg = getattr(page, "cookies", None)
                if callable(cg):
                    try:
                        raw_list = cg(all_domains=True)
                    except TypeError:
                        raw_list = cg()
            except Exception:
                raw_list = None

            blocked = self._is_aiqicha_url_or_html_blocked_for_finish(cur_url, html_content)
            cookie_login_ok = bool(raw_list and self._validate_aiqicha_browser_cookies(raw_list))
            search_list_ok = self._verification_search_html_has_list_signal(html_content)
            search_page_reached = (
                is_search_target
                and ("aiqicha.baidu.com/s" in u and "q=" in u)
                and html_ok
                and len(html_content) > 2000
            )
            search_ready = (
                search_page_reached
                and search_list_ok
            )

            if search_page_reached:
                try:
                    self._verification_page_capture = {
                        "url": cur_url,
                        "html": html_content,
                        "timestamp": time.time(),
                    }
                except Exception:
                    pass

            if blocked:
                stable_ok = 0
                time.sleep(poll)
                continue

            search_page_unblocked = search_page_reached and not self._html_suggests_baidu_passport_scan_login(html_content)
            if cookie_login_ok or search_page_unblocked:
                if is_search_target:
                    if search_ready or search_page_unblocked:
                        stable_ok += 1
                    else:
                        stable_ok = 0
                else:
                    stable_ok += 1
                if stable_ok >= need_stable:
                    cd = self._collect_cookies_from_drission_page(page)
                    tu = target_url if isinstance(target_url, str) and target_url.startswith("http") else ""
                    if not tu:
                        tu = cur_url if str(cur_url or "").startswith("http") else "https://aiqicha.baidu.com/"
                    if not cd and not self._get_browser_cookie_header_for_url(page, tu):
                        stable_ok = 0
                        time.sleep(poll)
                        continue

                    data_ready = False
                    try:
                        print("📥 验证完成，正在用浏览器重新打开目标页以确认数据并保存最新 Cookie…")
                        page.get(tu)
                        for _ in range(12):
                            time.sleep(0.5)
                            nh = getattr(page, "html", "") or ""
                            if not nh:
                                continue
                            if is_search_target:
                                data_ready = self._verification_search_html_has_list_signal(nh)
                            else:
                                data_ready = bool(
                                    "window.pageData" in nh
                                    and not self._html_suggests_verification_gate(nh)
                                    and not self._html_suggests_baidu_passport_scan_login(nh)
                                )
                            if data_ready:
                                self._verification_page_capture = {
                                    "url": getattr(page, "url", "") or tu,
                                    "html": nh,
                                    "timestamp": time.time(),
                                }
                                break
                        if data_ready:
                            self._persist_browser_cookies_after_data_ready(page, tu, cd)
                        else:
                            print("⚠️ 目标页尚未出现可解析数据，暂不覆盖配置中的爱企查 Cookie")
                    except Exception as e:
                        print(f"⚠️ 验证后重访目标页失败: {e}")
                    return True
            else:
                stable_ok = 0

            if cur_url != last_url:
                last_url = cur_url
                time.sleep(0.4)

            time.sleep(poll)

        return False

    def _anti_crawl_delay(self, status_callback=None):
        """反爬延时控制"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # 计算需要等待的时间 - 使用较小的随机延时范围
        min_interval = random.uniform(self.min_delay, self.max_delay)
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            message = f"爱企查反爬延时: {sleep_time:.2f}秒"
            print(message)
            if status_callback:
                status_callback(message)
            
            # 尝试使用异步延时
            try:
                from ...utils.async_delay import AsyncDelay
                AsyncDelay.delay(
                    milliseconds=int(sleep_time * 1000),
                    progress_callback=status_callback
                )
            except (ImportError, ModuleNotFoundError):
                time.sleep(sleep_time)
        
        self.last_request_time = int(time.time())
    
    def _get_random_ua(self):
        """获取随机User-Agent"""
        if self.use_fake_ua and self.ua:
            try:
                return self.ua.random
            except Exception:
                # 如果fake_useragent失败，回退到静态列表
                return random.choice(self.user_agents)
        else:
            return random.choice(self.user_agents)
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        new_ua = self._get_random_ua()
        self.session.headers.update({'User-Agent': new_ua})
        return new_ua
    
    def _make_request(self, method, url, status_callback=None, **kwargs):
        """统一的请求方法，包含反爬措施"""
        # 反爬延时
        self._anti_crawl_delay(status_callback=status_callback)
        
        u_req = url or ""
        if "aiqicha.baidu.com" in u_req or "xunkebao.baidu.com" in u_req:
            try:
                self.session.headers["User-Agent"] = self._stable_aiqicha_client_ua()
            except Exception:
                pass
        elif random.random() < 0.3:
            self._rotate_user_agent()
        
        # 设置请求超时，防止请求卡死
        if 'timeout' not in kwargs:
            if "aiqicha.baidu.com" in u_req and "/s?" in u_req:
                kwargs['timeout'] = 20
            else:
                kwargs['timeout'] = 10  # 设置10秒超时
        
        # 爱企查/寻客宝：Cookie 已在 _load_config→_rebuild_session_cookies_from_config 写入 Session；
        # 再传 cookies= 可能与 Jar 合并顺序不一致，且无 domain 的 set() 曾导致子域请求不带 Cookie。
        if "aiqicha.baidu.com" in u_req or "xunkebao.baidu.com" in u_req:
            headers = dict(kwargs.get("headers") or {})
            if not any(str(k).lower() == "cookie" for k in headers):
                raw_cookie = self._raw_cookie_for_url(u_req)
                if raw_cookie:
                    headers["Cookie"] = raw_cookie
                    kwargs["headers"] = headers
            kwargs.pop("cookies", None)
        
        # 发送请求
        try:
            if (
                HAS_CURL_CFFI
                and method.upper() == "GET"
                and "aiqicha.baidu.com" in u_req
                and "/s?" in u_req
            ):
                response = curl_requests.get(
                    url,
                    impersonate="chrome136",
                    http_version="v1",
                    default_headers=False,
                    **kwargs,
                )
                self._merge_response_cookies_into_runtime_header(u_req, response)
                self._save_debug_response(url, response)
                return response
            if method.upper() == 'GET':
                response = self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = self.session.post(url, **kwargs)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            self._merge_response_cookies_into_runtime_header(u_req, response)
            self._save_debug_response(url, response)
            return response
        except requests.exceptions.Timeout:
            if status_callback:
                status_callback("请求超时，正在重试...")
            # 超时后重试一次，增加超时时间
            kwargs['timeout'] = 20
            if method.upper() == 'GET':
                response = self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = self.session.post(url, **kwargs)
            self._merge_response_cookies_into_runtime_header(u_req, response)
            self._save_debug_response(url, response)
            return response
    
    def search_company(self, company_name: str, max_retries: int = 3, status_callback=None) -> Optional[Dict]:
        """
        第一步：搜索企业（简化版，参考天眼查的直接调用方式）
        """
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
                
        update_status(f"正在搜索企业: {company_name}")
        # 纯 requests 路径：先发制人从磁盘刷新 Cookie→Session（与 query_company_info 内 _load_config 双保险）
        self.reload_session_cookies_from_config()
        
        # URL编码企业名称（勿加 &_= 等非官方参数，易导致服务端 404）
        encoded_name = urllib.parse.quote(company_name)
        url = f"https://aiqicha.baidu.com/s?q={encoded_name}&t=0"
        
        headers = self._aiqicha_browser_document_headers("https://aiqicha.baidu.com/?from=pz")
        
        search_saw_absorbed_only = False
        search_saw_list_but_no_match = False
        search_saw_parseable_data = False
        for attempt in range(max_retries):
            try:
                response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
                if response is None:
                    update_status("请求返回为空")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None
                
                status_code = response.status_code
                if status_code >= 400:
                    update_status(f"请求失败: {status_code}")
                    html_content = response.text or ""
                    captcha_url = self._extract_captcha_url(response, html_content)
                    if captcha_url:
                        self._open_with_drissionpage(captcha_url, "aiqicha_search_drissionpage")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        return None
                    if html_content and self._check_anti_crawler(html_content):
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            print(f"检测到反爬限制，等待{wait_time}秒后重试...")
                            time.sleep(wait_time)
                            continue
                        print("多次遇到反爬限制，查询失败（未检测到验证页则不再自动打开浏览器，请更新 Cookie 后重试）")
                        if self._should_open_browser(url, response=response, html_content=html_content):
                            self._open_with_drissionpage(url, "aiqicha_search_drissionpage")
                        return None
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None
                
                # 从HTML中提取JSON数据
                html_content = response.text
                
                # 显示响应基本信息
                print(f"响应长度: {len(html_content)} 字符")
                captcha_url = self._extract_captcha_url(response, html_content)

                # 检查是否遇到反爬限制（简化检查）
                if captcha_url:
                    self._open_with_drissionpage(captcha_url, "aiqicha_search_drissionpage")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None
                if self._check_anti_crawler(html_content):
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"检测到反爬限制，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print("多次遇到反爬限制，查询失败（未检测到验证页则不再自动打开浏览器，请更新 Cookie 后重试）")
                        if self._should_open_browser(url, html_content=html_content):
                            self._open_with_drissionpage(url, "aiqicha_search_drissionpage")
                        return None
                
                # 尝试提取数据
                dom_data = None
                data = self._extract_page_data(html_content)
                if getattr(self, "_last_page_extract_was_absorbed_only", False):
                    search_saw_absorbed_only = True
                if data and not self._embedded_page_data_matches_intent(data, company_name):
                    print("内嵌 pageData 的 queryWord/queryStr 与当前搜索词不一致，已忽略（可能为缓存页）")
                    data = None

                matched_data = None
                if data:
                    matched_data = self._filter_search_result_by_company_name(data, company_name)

                if not matched_data:
                    dom_data = self._extract_search_results_from_dom(html_content)
                    if dom_data:
                        matched_data = self._filter_search_result_by_company_name(dom_data, company_name)

                if matched_data:
                    return matched_data

                if data is not None or dom_data is not None:
                    search_saw_parseable_data = True
                    search_saw_list_but_no_match = True
                    print("搜索结果与目标企业不匹配")

                if attempt < max_retries - 1:
                    print(f"1秒后重试...")
                    time.sleep(1)
                    continue

                print(
                    "多次尝试后仍无法得到与目标企业一致的结果；"
                    "未检测到验证/风控时不再自动打开浏览器。"
                )
                browser_html = None
                if self._should_open_browser(url, response=response, html_content=html_content):
                    browser_html = self._open_with_drissionpage(url, "aiqicha_search_verification")
                elif search_saw_absorbed_only:
                    print(
                        "搜索页仅返回 absorbed 候选但未匹配到当前企业，"
                        "作为查不到的最终兜底，打开浏览器重新拉取搜索页。"
                    )
                    browser_html = self._open_with_drissionpage(
                        url, "aiqicha_search_absorbed_fallback", silent_if_no_verify=True
                    )
                elif search_saw_list_but_no_match:
                    print(
                        "检测到响应中有企业列表但与当前查询不一致（常见为缓存/串词），"
                        "作为查不到的最终兜底，打开浏览器重新拉取搜索页。"
                    )
                    browser_html = self._open_with_drissionpage(
                        url, "aiqicha_search_mismatch_fallback", silent_if_no_verify=True
                    )
                elif not search_saw_parseable_data:
                    print(
                        "多次请求后未解析到可用搜索结果，作为最终兜底打开浏览器确认页面状态。"
                    )
                    browser_html = self._open_with_drissionpage(
                        url, "aiqicha_search_no_data_inspect", silent_if_no_verify=True
                    )
                cap = getattr(self, "_verification_page_capture", None)
                if isinstance(cap, dict) and cap.get("html"):
                    cu = cap.get("url") or ""
                    if url in cu or cu in url or (
                        "aiqicha.baidu.com/s" in cu and encoded_name in cu
                    ):
                        browser_html = cap["html"]
                if browser_html:
                    try:
                        browser_data = self._extract_page_data(browser_html)
                        if browser_data and not self._embedded_page_data_matches_intent(
                            browser_data, company_name
                        ):
                            browser_data = None
                        matched_data = (
                            self._filter_search_result_by_company_name(browser_data, company_name)
                            if browser_data
                            else None
                        )
                        if matched_data:
                            return matched_data
                        dom_from_browser = self._extract_search_results_from_dom(browser_html)
                        matched_data = (
                            self._filter_search_result_by_company_name(dom_from_browser, company_name)
                            if dom_from_browser
                            else None
                        )
                        if matched_data:
                            return matched_data
                    finally:
                        self._verification_page_capture = None
                return {}
                    
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    print(f"请求异常: {e}，{2}秒后重试...")
                    time.sleep(2)
                else:
                    print(f"搜索企业失败: {e}")
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"未知异常: {e}，{2}秒后重试...")
                    time.sleep(2)
                else:
                    print(f"搜索企业失败: {e}")
                    return None
        
        print(f"搜索失败，已达到最大重试次数")
        return None
    
    def _check_anti_crawler(self, html_content: str) -> bool:
        """
        检查是否遇到反爬限制（优化版，减少误判）
        """
        # 如果页面内容为空，不判断为反爬
        if not html_content or len(html_content.strip()) < 100:
            return False
            
        # 明确的反爬关键词检测
        anti_crawler_keywords = [
            "验证码", "人机验证", "安全验证",
            "访问过于频繁", "请稍后再试", "系统繁忙",
            "安全检查", "security check", "访问受限", "访问异常",
            "请求频率过高", "请求次数超限", "IP限制", "IP被封",
            "请输入验证码", "滑动验证", "点击验证"
        ]
        
        for keyword in anti_crawler_keywords:
            if keyword.lower() in html_content.lower():
                print(f"检测到反爬关键词: {keyword}")
                return True
        
        # 检查是否是明确的错误页面
        error_indicators = [
            "<title>403",
            "403 Forbidden",
            "Access Denied",
            "Permission Denied"
        ]
        
        for indicator in error_indicators:
            if indicator.lower() in html_content.lower():
                print(f"检测到错误页面: {indicator}")
                return True
        
        # 移除过于严格的JavaScript数据检查，改为更宽松的检查
        # 只有当页面明显异常时才判断为反爬
        if len(html_content) < 1000 and "<html" not in html_content.lower():
            print("页面内容异常短且不包含HTML标签")
            return True
        
        return False

    def _extract_captcha_url(self, response, html_content: str) -> str:
        try:
            if response is not None:
                response_url = getattr(response, "url", "") or ""
                if "wappass.baidu.com" in response_url:
                    return response_url
        except Exception:
            pass
        if html_content and self._html_requires_browser_verification(html_content):
            m = re.search(r"https://wappass\.baidu\.com[^\"'\s<>\\]+", html_content)
            if m:
                return m.group(0).rstrip("\\")
            m = re.search(r"https://verify\.baidu\.com[^\"'\s<>\\]+", html_content)
            if m:
                return m.group(0).rstrip("\\")
        return ""

    def _should_open_browser(self, url: str, response=None, html_content: Optional[str] = None) -> bool:
        """仅在明确进入百度登录/安全验证链时打开浏览器。"""
        u = (url or "").lower()
        if any(host in u for host in ("wappass.baidu.com", "verify.baidu.com", "passport.baidu.com")):
            return True
        if response is not None:
            response_url = (getattr(response, "url", "") or "").lower()
            if any(host in response_url for host in ("wappass.baidu.com", "verify.baidu.com", "passport.baidu.com")):
                return True
        if html_content:
            if self._html_requires_browser_verification(html_content):
                return True
        return False

    def _is_no_data_message(self, message: str) -> bool:
        text = str(message or "")
        keywords = [
            "暂无", "无数据", "未找到", "不存在", "无结果", "空数据",
            "not found", "no data", "empty"
        ]
        return any(keyword in text for keyword in keywords)

    def _normalize_company_name(self, name: str) -> str:
        if not name:
            return ""
        text = html.unescape(str(name)).strip().lower()
        text = re.sub(r"<[^>]+>", "", text)
        for char in [" ", "\t", "\n", "\r", "（", "）", "(", ")", "-", "_", "·", ".", ",", "，", "。", "、", "/"]:
            text = text.replace(char, "")
        return text

    def _normalize_company_name_core(self, name: str) -> str:
        text = self._normalize_company_name(name)
        if not text:
            return ""
        suffixes = (
            "有限责任公司",
            "股份有限公司",
            "股份公司",
            "有限公司",
            "责任公司",
            "分公司",
            "总公司",
            "公司",
        )
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                return text[: -len(suffix)]
        return text

    def _is_company_name_match(self, target_name: str, candidate_name: str) -> bool:
        target = self._normalize_company_name(target_name)
        candidate = self._normalize_company_name(candidate_name)
        if not target or not candidate:
            return False
        if target == candidate:
            return True
        target_core = self._normalize_company_name_core(target_name)
        candidate_core = self._normalize_company_name_core(candidate_name)
        if target_core and candidate_core:
            if len(target_core) >= 4 and target_core == candidate_core:
                return True
            if len(target_core) >= 6 and target_core in candidate_core:
                return True
            if len(candidate_core) >= 6 and candidate_core in target_core:
                return True
        if len(target) >= 8 and target in candidate:
            return True
        if len(candidate) >= 8 and candidate in target:
            return True
        return False

    def _filter_search_result_by_company_name(self, data: Dict, target_name: str) -> Optional[Dict]:
        if not isinstance(data, dict):
            return None
        result = data.get("result")
        if not isinstance(result, dict):
            return None
        result_list = result.get("resultList", [])
        if not isinstance(result_list, list):
            return None
        normalized_target = self._normalize_company_name(target_name)
        fallback_item = None
        for item in result_list:
            if not isinstance(item, dict):
                continue
            ent_name = self._get_result_company_name(item) or item.get("entName", "")
            if self._is_company_name_match(target_name, ent_name):
                result["resultList"] = [item]
                return data
            normalized_candidate = self._normalize_company_name(
                self._get_result_company_name(item) or item.get("entName", "")
            )
            if (
                not fallback_item
                and normalized_target
                and len(normalized_target) <= 4
                and normalized_target in normalized_candidate
            ):
                fallback_item = item
        if fallback_item:
            print(
                f"未找到精确企业名，使用短关键词最佳候选: "
                f"{self._get_result_company_name(fallback_item) or fallback_item.get('entName', '')}"
            )
            result["resultList"] = [fallback_item]
            return data
        return None

    def _absorbed_candidates_to_result_list(self, absorbed) -> List[Dict]:
        result_list: List[Dict] = []
        seen = set()

        def add_item(item):
            if not isinstance(item, dict):
                return
            ent_name = (
                item.get("entName")
                or item.get("titleName")
                or item.get("name")
                or item.get("title")
            )
            pid = item.get("pid") or item.get("pidStr") or item.get("id")
            if not ent_name and not pid:
                return
            normalized = dict(item)
            if ent_name:
                normalized.setdefault("entName", ent_name)
                normalized.setdefault("titleName", ent_name)
            if pid is not None:
                normalized.setdefault("pid", str(pid))
            key = (
                normalized.get("pid") or "",
                self._normalize_company_name(
                    normalized.get("entName") or normalized.get("titleName") or ""
                ),
            )
            if key in seen:
                return
            seen.add(key)
            result_list.append(normalized)

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            add_item(value)
            for key in ("resultList", "list", "items", "data", "records"):
                nested = value.get(key)
                if isinstance(nested, (list, dict)):
                    walk(nested)

        walk(absorbed)
        return result_list

    def _embedded_page_data_matches_intent(self, data: Dict, company_name: str) -> bool:
        """判断内嵌 pageData 是否对应当前搜索词，避免 CDN/SSR 返回与 URL 中 q= 不一致的旧数据。"""
        if not isinstance(data, dict) or not (company_name or "").strip():
            return True
        target = self._normalize_company_name(company_name)
        if not target:
            return True
        candidates = []
        qw = data.get("queryWord")
        if isinstance(qw, str) and qw.strip():
            candidates.append(qw)
        result = data.get("result")
        if isinstance(result, dict):
            qs = result.get("queryStr")
            if isinstance(qs, str) and qs.strip():
                candidates.append(qs)
        if not candidates:
            return True
        for c in candidates:
            nc = self._normalize_company_name(c)
            if not nc:
                continue
            if nc == target:
                return True
            if len(target) >= 6 and (target in nc or nc in target):
                return True
            if len(nc) >= 6 and (target in nc or nc in target):
                return True
        return False

    def _get_result_company_name(self, item: Dict) -> str:
        if not isinstance(item, dict):
            return ""
        for key in ("titleName", "entName", "name"):
            value = item.get(key, "")
            normalized = self._normalize_company_name(value)
            if normalized:
                cleaned = html.unescape(str(value))
                cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
                if cleaned:
                    return cleaned
        return ""

    def _extract_search_results_from_dom(self, html_content: str) -> Optional[Dict]:
        if not html_content:
            return None
        pattern = re.compile(
            r'data-log-title="item-(?P<pid>\d+)"[^>]*class="card".*?<h3[^>]*class="title"><a[^>]*\stitle="(?P<title>[^"]+)"',
            re.DOTALL
        )
        result_list = []
        seen_pids = set()
        for match in pattern.finditer(html_content):
            pid = match.group("pid")
            ent_name = html.unescape(match.group("title") or "").strip()
            if not pid or not ent_name or pid in seen_pids:
                continue
            seen_pids.add(pid)
            result_list.append({
                "pid": pid,
                "entName": ent_name,
                "titleName": ent_name,
            })
        if not result_list:
            return None
        return {
            "result": {
                "resultList": result_list
            }
        }
    
    def _parse_js_object_literal(self, js_text: str) -> Optional[Dict]:
        if not js_text:
            return None
        converted_parts = []
        length = len(js_text)
        index = 0
        while index < length:
            char = js_text[index]
            if char in ("'", '"'):
                quote = char
                start = index
                index += 1
                escaped = False
                while index < length:
                    current = js_text[index]
                    if escaped:
                        escaped = False
                    elif current == "\\":
                        escaped = True
                    elif current == quote:
                        index += 1
                        break
                    index += 1
                converted_parts.append(js_text[start:index])
                continue
            if char.isalpha() or char in ("_", "$"):
                token_end = index + 1
                while token_end < length and (js_text[token_end].isalnum() or js_text[token_end] in ("_", "$")):
                    token_end += 1
                token = js_text[index:token_end]
                next_index = token_end
                while next_index < length and js_text[next_index].isspace():
                    next_index += 1
                if next_index < length and js_text[next_index] == ":":
                    converted_parts.append(json.dumps(token))
                elif token == "true":
                    converted_parts.append("True")
                elif token == "false":
                    converted_parts.append("False")
                elif token in ("null", "undefined"):
                    converted_parts.append("None")
                else:
                    converted_parts.append(token)
                index = token_end
                continue
            converted_parts.append(char)
            index += 1
        python_literal = "".join(converted_parts)
        python_literal = python_literal.replace("\\/", "/")
        python_literal = re.sub(r",(?=\s*[}\]])", "", python_literal)
        try:
            data = ast.literal_eval(python_literal)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _extract_page_data(self, html_content: str) -> Optional[Dict]:
        """
        从HTML中提取页面数据（简化版）
        """
        self._last_page_extract_was_absorbed_only = False
        
        # 检查页面是否包含基本的JavaScript数据
        if 'window.' not in html_content and '<script' not in html_content.lower():
            print("页面不包含JavaScript数据，可能是纯HTML页面或错误页面")
            return None
        
        # 使用更精确的正则表达式来匹配完整的JSON对象
        # 这个模式会匹配从开始的 { 到对应的结束 }
        primary_pattern = r'window\.pageData\s*=\s*({(?:[^{}]|{[^{}]*})*})\s*;'
        match = re.search(primary_pattern, html_content)
        
        # 如果还是没找到，尝试更宽松的模式（处理嵌套的情况）
        if not match:
            # 找到 window.pageData = 的位置，然后手动解析JSON
            start_pattern = r'window\.pageData\s*=\s*'
            start_match = re.search(start_pattern, html_content)
            if start_match:
                start_pos = start_match.end()
                # 从这个位置开始查找完整的JSON对象
                json_str = self._extract_json_from_position(html_content, start_pos)
                if json_str:
                    # 创建一个伪匹配对象
                    class FakeMatch:
                        def __init__(self, json_str):
                            self._json_str = json_str
                        def group(self, n):
                            return self._json_str
                    match = FakeMatch(json_str)
        
        if match:
            try:
                json_str = match.group(1)
                
                # 尝试解析JSON
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    json_str_fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    try:
                        data = json.loads(json_str_fixed)
                    except json.JSONDecodeError:
                        data = self._parse_js_object_literal(json_str)
                        if data is None:
                            raise
                
                # 检查数据结构并返回
                if data and isinstance(data, dict) and 'result' in data and isinstance(data['result'], dict):
                    result_data = data['result']
                    result_list = result_data.get('resultList', [])
                    
                    if result_list:
                        first_result = result_list[0]
                        company_name = first_result.get('entName', '未知')
                        
                        # 处理Unicode编码
                        if '\\u' in company_name:
                            try:
                                company_name = company_name.encode().decode('unicode_escape')
                            except:
                                pass
                        
                        print(f"找到企业: {company_name}")
                        # 为了兼容后续逻辑，把提取出的列表放回 resultList
                        data['result']['resultList'] = result_list
                        return data
                    elif result_data.get('absorbed'):
                        absorbed_candidates = self._absorbed_candidates_to_result_list(
                            result_data.get('absorbed')
                        )
                        if absorbed_candidates:
                            print(
                                f"resultList为空，已从absorbed提取{len(absorbed_candidates)}条候选数据"
                            )
                            data['result']['resultList'] = absorbed_candidates
                            return data
                        print("resultList为空，仅存在absorbed候选数据（不视为有效命中）")
                        self._last_page_extract_was_absorbed_only = True
                        return None
                    else:
                        print("数据结构不符合预期 (未找到 resultList 或 absorbed 等列表数据)")
                else:
                    print("数据结构不符合预期 (缺少 result 字段)")
            except Exception as e:
                print(f"JSON解析失败: {e}")
        else:
            print("未找到window.pageData")
            
            # 调试：保存失败情况下的响应以供分析
            if self.debug_output_enabled and len(html_content) > 1000000:
                try:
                    self._save_debug_content("aiqicha_failed_parse", html_content, "html")
                except Exception as e:
                    print(f"保存调试文件失败: {e}")
        
        print("数据提取失败")
        return None
    
    def _extract_json_from_position(self, html_content: str, start_pos: int) -> Optional[str]:
        """
        从指定位置开始提取完整的 JavaScript 对象字面量（如 window.pageData）。
        同时识别双引号与单引号字符串，避免 appJumpUrl 等字段内未转义的 { } 破坏括号配对。
        """
        if start_pos >= len(html_content):
            return None

        while start_pos < len(html_content) and html_content[start_pos].isspace():
            start_pos += 1

        if start_pos >= len(html_content) or html_content[start_pos] != '{':
            return None

        brace_count = 0
        in_string = False
        string_quote = None
        escape_next = False
        current_pos = start_pos

        while current_pos < len(html_content):
            char = html_content[current_pos]

            if escape_next:
                escape_next = False
                current_pos += 1
                continue

            if in_string:
                if char == '\\':
                    escape_next = True
                elif char == string_quote:
                    in_string = False
                    string_quote = None
                current_pos += 1
                continue

            if char == '"':
                in_string = True
                string_quote = '"'
                current_pos += 1
                continue
            if char == "'":
                in_string = True
                string_quote = "'"
                current_pos += 1
                continue

            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return html_content[start_pos : current_pos + 1]
            elif char == ';' and brace_count == 0:
                break

            current_pos += 1

        return None

    def _save_debug_response(self, url: str, response):
        if not self.debug_output_enabled or response is None:
            return
        if not self.debug_output_dir:
            return
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            if 'company_detail' in url:
                prefix = "aiqicha_company_detail"
            elif 's?q=' in url:
                prefix = "aiqicha_search"
            elif 'xunkebao.baidu.com' in url:
                prefix = "aiqicha_xunkebao"
            else:
                prefix = "aiqicha_response"
            content_type = response.headers.get('content-type', '').lower()
            if 'application/json' in content_type:
                try:
                    data = response.json()
                    filename = f"{prefix}_{timestamp}.json"
                    filepath = os.path.join(self.debug_output_dir, filename)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return
                except Exception:
                    pass
            if response.content:
                try:
                    filename = f"{prefix}_{timestamp}.html"
                    filepath = os.path.join(self.debug_output_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    return
                except Exception:
                    pass
            text = response.text
            if not text:
                try:
                    if response.content:
                        encoding = response.apparent_encoding or response.encoding or 'utf-8'
                        text = response.content.decode(encoding, errors='replace')
                except Exception:
                    text = ""
            if not text:
                headers_json = json.dumps(dict(response.headers), ensure_ascii=False)
                content_length = len(response.content) if response.content else 0
                text = f"status_code: {response.status_code}\nurl: {response.url}\nheaders: {headers_json}\ncontent_length: {content_length}\n"
            self._save_debug_content(prefix, text, "html")
        except Exception:
            pass

    def _save_debug_content(self, prefix: str, content: str, ext: str):
        if not self.debug_output_enabled or not self.debug_output_dir:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{prefix}_{timestamp}.{ext}"
        filepath = os.path.join(self.debug_output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def _close_browser_page(self, page):
        if page is None:
            return
        try:
            page.close()
            return
        except Exception:
            pass
        try:
            page.quit()
        except Exception:
            pass

    def _remember_browser_page(self, page):
        if page is None:
            return
        if page not in self._opened_browser_pages:
            self._opened_browser_pages.append(page)

    def _close_opened_browser_pages(self):
        while self._opened_browser_pages:
            page = self._opened_browser_pages.pop()
            self._close_browser_page(page)

    def _get_browser_profile_dir(self) -> str:
        cached = getattr(self, "_browser_profile_dir", None)
        if cached:
            return cached
        candidates = []
        config_path = getattr(self, "config_path", None)
        if config_path:
            try:
                candidates.append(os.path.join(os.path.dirname(config_path), "aiqicha_browser_profile"))
            except Exception:
                pass
        candidates.append(os.path.join(tempfile.gettempdir(), "koi_aiqicha_browser_profile"))
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                self._browser_profile_dir = os.path.abspath(candidate)
                return self._browser_profile_dir
            except Exception:
                continue
        fallback = os.path.abspath(os.path.join(tempfile.gettempdir(), "koi_aiqicha_browser_profile_fallback"))
        os.makedirs(fallback, exist_ok=True)
        self._browser_profile_dir = fallback
        return fallback

    def _browser_profile_has_cookie_store(self, user_data_dir: str) -> bool:
        try:
            cookies_path = os.path.join(user_data_dir, "Default", "Network", "Cookies")
            return os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0
        except Exception:
            return False

    def _open_with_drissionpage(
        self,
        url: str,
        prefix: str,
        cookie_str: Optional[str] = None,
        silent_if_no_verify: bool = False,
    ):
        can_save = bool(self.debug_output_enabled and self.debug_output_dir)
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except Exception as e:
            print(f"DrissionPage加载失败: {e}")
            return
        try:
            browser_path = os.environ.get("CHROME_PATH") or os.environ.get("CHROMIUM_PATH") or os.environ.get("EDGE_PATH")
            if not browser_path:
                for name in ("chrome", "msedge", "chromium"):
                    browser_path = shutil.which(name)
                    if browser_path:
                        break
            if not browser_path:
                candidates = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Chromium\Application\chrome.exe",
                    r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
                ]
                for candidate in candidates:
                    if os.path.exists(candidate):
                        browser_path = candidate
                        break

            user_data_dir = self._get_browser_profile_dir()

            options = ChromiumOptions()
            if browser_path:
                try:
                    options.set_browser_path(browser_path)
                except Exception:
                    pass
            options.set_user_data_path(user_data_dir)
            try:
                options.set_argument("--disable-blink-features", "AutomationControlled")
            except Exception:
                pass
            if silent_if_no_verify:
                try:
                    options.headless(True)
                except Exception:
                    try:
                        options.set_argument("--headless=new")
                    except Exception:
                        pass
                try:
                    options.set_argument("--window-size", "1365,900")
                except Exception:
                    pass
            try:
                options.set_user_agent(self._stable_aiqicha_client_ua())
            except Exception:
                pass

            page = ChromiumPage(addr_or_opts=options)

            if cookie_str is None:
                self._load_config()
                cookie_str = self.cookie
            previous_cookie = cookie_str or ""

            if cookie_str:
                self._inject_aiqicha_cookies_into_browser(page, cookie_str)

            if not silent_if_no_verify:
                try:
                    page.set.window.max()
                except Exception:
                    pass
            page.get(url)
            current_url = getattr(page, "url", "") or url
            html_content = getattr(page, "html", "") or ""

            needs_verify_flow = (
                "wappass.baidu.com" in (current_url or "").lower()
                or self._html_suggests_verification_gate(html_content)
            )

            if not needs_verify_flow:
                for _ in range(8):
                    if 'data-log-title="item-' in html_content or 'class="company-list"' in html_content:
                        break
                    try:
                        page.wait(1)
                    except Exception:
                        time.sleep(1)
                    latest_html = getattr(page, "html", "") or ""
                    if latest_html:
                        html_content = latest_html

            current_url = getattr(page, "url", "") or current_url
            html_content = getattr(page, "html", "") or html_content
            needs_verify_flow = (
                "wappass.baidu.com" in (current_url or "").lower()
                or self._html_suggests_verification_gate(html_content)
            )

            if needs_verify_flow:
                if silent_if_no_verify:
                    print("静默浏览器检测到需人机/安全验证，切换为可见浏览器供手动处理。")
                    self._close_browser_page(page)
                    return self._open_with_drissionpage(
                        url,
                        prefix,
                        previous_cookie,
                        silent_if_no_verify=False,
                    )
                self._verification_page_ref = page
                self._pending_browser_close = (lambda p=page: p.quit())
                print(
                    "检测到需人机/安全验证：请在浏览器中完成验证或扫码登录；"
                    "流程对齐天眼查：保存 Cookie 后会用当前窗口重新打开本次搜索 URL 并抓取页面。"
                )
                if self._wait_until_verification_done_then_save_cookies(
                    page, previous_cookie, url
                ):
                    print("已保存最新 Cookie，并已尝试捕获目标搜索页 HTML")
                    cap = getattr(self, "_verification_page_capture", None)
                    if isinstance(cap, dict) and cap.get("html"):
                        html_content = cap["html"]
                    else:
                        latest_html = getattr(page, "html", "") or ""
                        if latest_html:
                            html_content = latest_html
                    self._close_browser_page(page)
                else:
                    print("未在超时时间内检测到验证完成，浏览器将保持打开，请手动处理。")
                    self._remember_browser_page(page)
                self._pending_browser_close = None
                self._verification_page_ref = None
            else:
                if (
                    "aiqicha.baidu.com/s" in (url or "").lower()
                    and self._verification_search_html_has_list_signal(html_content)
                ):
                    try:
                        self._verification_page_capture = {
                            "url": current_url or url,
                            "html": html_content,
                            "timestamp": time.time(),
                        }
                        self._persist_browser_cookies_after_data_ready(
                            page,
                            current_url or url,
                        )
                    except Exception as e:
                        print(f"⚠️ 浏览器兜底后保存爱企查 Cookie 失败: {e}")
                self._close_browser_page(page)
            if can_save and html_content:
                self._save_debug_content(prefix, html_content, "html")
            return html_content
        except Exception as e:
            print(f"DrissionPage打开URL失败: {e}")
            return None
    
    def _get_random_user_agent(self) -> str:
        """
        获取随机PC端User-Agent（避免移动端）
        """
        # PC端User-Agent列表
        pc_user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15'
        ]
        
        # 如果有fake_useragent库，尝试获取PC端UA
        if self.use_fake_ua and self.ua:
            try:
                # 尝试多次获取，过滤掉移动端UA
                for _ in range(10):
                    ua = self.ua.random
                    # 检查是否为移动端UA
                    mobile_keywords = ['Mobile', 'Android', 'iPhone', 'iPad', 'BlackBerry', 'Windows Phone']
                    if not any(keyword in ua for keyword in mobile_keywords):
                        return ua
            except:
                pass
        
        # 备用：从PC端UA列表中随机选择
        return random.choice(pc_user_agents)

    def _parse_page_data_dict_from_html(self, html_content: str) -> Optional[Dict]:
        """从 HTML 解析 window.pageData（与搜索页共用括号配对，避免详情页嵌套 JSON 被非贪婪正则截断）。"""
        if not html_content or "window.pageData" not in html_content:
            return None
        primary_pattern = r'window\.pageData\s*=\s*({(?:[^{}]|{[^{}]*})*})\s*;'
        match = re.search(primary_pattern, html_content)
        if not match:
            start_match = re.search(r"window\.pageData\s*=\s*", html_content)
            if start_match:
                json_str = self._extract_json_from_position(html_content, start_match.end())
                if json_str:
                    class _FakeMatch:
                        def __init__(self, js: str):
                            self._js = js

                        def group(self, n: int) -> str:
                            return self._js

                    match = _FakeMatch(json_str)
        if not match:
            return None
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            try:
                fixed = json_str.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
                data = json.loads(fixed)
            except json.JSONDecodeError:
                data = self._parse_js_object_literal(json_str)
        return data if isinstance(data, dict) else None

    def get_company_detail(self, pid: str) -> Optional[Dict]:
        """
        第二步：获取企业详情页信息
        """
        print(f"正在获取企业详情: {pid}")
        
        url = f"https://aiqicha.baidu.com/company_detail_{pid}"
        
        headers = self._aiqicha_browser_document_headers(
            f'https://aiqicha.baidu.com/s?q={urllib.parse.quote("企业名称")}&t=0'
        )
        
        response = None
        try:
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies)
            if response:
                response.raise_for_status()
            else:
                if self._should_open_browser(url):
                    self._open_with_drissionpage(url, "aiqicha_company_detail_drissionpage")
                return None
            
            html_content = response.text if hasattr(response, "text") else ""
            parsed = self._parse_page_data_dict_from_html(html_content)
            if parsed and "result" in parsed:
                print("获取到企业详情数据")
                return parsed
            if parsed:
                print("详情页数据格式异常（若无验证页提示请更新 Cookie 或稍后重试）")
            else:
                print("无法从详情页中提取 pageData（未检测到验证页则不弹浏览器）")
            if self._should_open_browser(url, response=response, html_content=html_content):
                self._open_with_drissionpage(url, "aiqicha_company_detail_drissionpage")
            return None
            
        except Exception as e:
            print(f"获取企业详情失败: {e}")
            try:
                rt = response.text if response is not None and hasattr(response, "text") else ""
            except Exception:
                rt = ""
            if self._should_open_browser(url, response=response, html_content=rt):
                self._open_with_drissionpage(url, "aiqicha_company_detail_drissionpage")
            return None
    
    def get_icp_info(self, pid: str) -> List[Dict]:
        """
        第三步：获取ICP备案信息（循环获取所有页面）
        """
        print(f"正在获取ICP备案信息: {pid}")
        
        all_icp_data = []
        page = 1
        
        while True:
            url = f"https://aiqicha.baidu.com/cs/icpInfoAjax?pid={pid}&p={page}"
            
            headers = {
                'Host': 'aiqicha.baidu.com',
                'sec-ch-ua-platform': '"Windows"',
                'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
                'sec-ch-ua-mobile': '?0',
                'User-Agent': self._stable_aiqicha_client_ua(),
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/plain, */*',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=certRecord',
            }
            
            try:
                response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies)
                if response:
                    response.raise_for_status()
                    # 解析JSON响应
                    data = response.json() if hasattr(response, 'json') else {}
                    html_content = response.text if hasattr(response, 'text') else ""
                else:
                    print("ICP请求返回为空")
                    if self._should_open_browser(url):
                        self._open_with_drissionpage(url, "aiqicha_icp_drissionpage")
                    break
                
                # 检查响应数据
                if data.get('status') == 0 and 'data' in data:
                    # 检查数据结构 - 爱企查API可能返回两种不同的数据结构
                    if 'list' in data['data'] and isinstance(data['data']['list'], list):
                        # 第一种结构: data['data']['list']
                        icp_list = data['data']['list']
                        all_icp_data.extend(icp_list)
                        print(f"获取到第{page}页ICP备案信息，共{len(icp_list)}条")
                        
                        # 检查是否还有更多页
                        if len(icp_list) < 10 or page >= data['data'].get('pageCount', 1):
                            break
                    elif isinstance(data['data'], list):
                        # 第二种结构: data['data']是直接的列表
                        icp_list = data['data']
                        all_icp_data.extend(icp_list)
                        print(f"获取到第{page}页ICP备案信息，共{len(icp_list)}条")
                        
                        # 如果当前页数据少于10条，可能是最后一页
                        if len(icp_list) < 10:
                            break
                    else:
                        # 数据结构不符合预期
                        print("ICP备案信息数据结构异常")
                        if self._should_open_browser(url, response=response, html_content=html_content):
                            self._open_with_drissionpage(url, "aiqicha_icp_drissionpage")
                        break
                    
                    # 继续获取下一页
                    page += 1
                else:
                    # API返回错误或无数据
                    if data.get('status') != 0:
                        message = data.get('message') or data.get('msg') or '未知错误'
                        print(f"获取ICP备案信息失败: {message}")
                        if not self._is_no_data_message(message):
                            if self._should_open_browser(url, response=response, html_content=html_content):
                                self._open_with_drissionpage(url, "aiqicha_icp_drissionpage")
                    else:
                        print("未获取到ICP备案信息")
                    break
                
            except Exception as e:
                print(f"获取ICP备案信息失败: {e}")
                if self._should_open_browser(url):
                    self._open_with_drissionpage(url, "aiqicha_icp_drissionpage")
                break
            
            # 防止无限循环
            if page > 10:
                print("已达到最大页数限制")
                break
        
        print(f"ICP备案信息获取完成，共{len(all_icp_data)}条")
        return all_icp_data
    
    def get_enterprise_id(self, pid: str) -> Optional[str]:
        """
        第四步：获取企业ID
        """
        print(f"正在获取企业ID: {pid}")
        
        url = "https://xunkebao.baidu.com/crm/web/aiqicha/bizcrm/enterprise/queryBaseInfoBySourceId"
        
        headers = {
            'Host': 'xunkebao.baidu.com',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Sourceid': '175e96cddbce8310d92021d2a8b6fe50',
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
            'Api-Version': '0',
            'sec-ch-ua-mobile': '?0',
            'Auth-Type': 'PAAS',
            'User-Info': 'uc_id=;uc_appid=585;acc_token=;acc_id=309412743;login_id=309412743;device_type=dgtsale-h5;paas_appid=18;version=12;login_type=passport',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/plain, */*',
            'Env': 'WEB',
            'Client-Version': '0',
            'Origin': 'https://xunkebao.baidu.com',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://xunkebao.baidu.com/index.html',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        payload = {
            "params": {
                "sourceId": pid,
                "isNeedLoadUnlockStatus": True
            }
        }
        
        try:
            response = self._make_request('POST', url, headers=headers, cookies=self.xunkebao_cookies, json=payload)
            if response:
                response.raise_for_status()
                data = response.json() if hasattr(response, 'json') else {}
            else:
                print("请求返回为空")
                return None
            enterprise_id = data.get('data', {}).get('id')
            
            if enterprise_id:
                print(f"获取到企业ID: {enterprise_id}")
                return enterprise_id
            else:
                print("未能获取到企业ID")
                return None
                
        except Exception as e:
            print(f"获取企业ID失败: {e}")
            return None
    
    def unlock_resource(self, enterprise_id: str) -> bool:
        """
        解锁资源 - 第一步解锁
        """
        print(f"正在解锁资源: {enterprise_id}")
        
        url = "https://xunkebao.baidu.com/crm/web/aiqicha/bizcrm/enterprise/resourceunlock/unlockresource"
        
        headers = {
            'Host': 'xunkebao.baidu.com',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Sourceid': '5bca522374db1e9fac4e7bf9b36f77e0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
            'Api-Version': '0',
            'sec-ch-ua-mobile': '?0',
            'Auth-Type': 'PAAS',
            'User-Info': 'uc_id=;uc_appid=585;acc_token=;acc_id=309412743;login_id=309412743;device_type=dgtsale-h5;paas_appid=18;version=12;login_type=passport',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/plain, */*',
            'Env': 'WEB',
            'Client-Version': '0',
            'Acs-Token': '1756443934915_1756451572223_VYa51dua/e6K4G7lfysE/4fyRRz0M6+NZIzasHyeGaYPEVyro4DZFeI6Nl8cHf1B4d+xyV+dLwrdWT6okc4geVTdyuujOohS20MXHZy6XHaewz+dKLhFwtjYerEk0PmpPgEIFODohbEnQhwfjxZ42DfFRHK3CHtI7FlRf/cY83NalEJ01dv6kcjEM2JYRq6g7DvXQVdU6Qx6bcAMSlolF6rWr/BtaL8uNrQNv3GpnNJphMXHjgZ6EX33a0BAX1Lds9g/Dp1mZI66zUC1+Bo0FXTfHcppA/A8Q9E41X4omTZQ515z6y9R26JA0wfrCiRgj1RIsYYbos3BgLpBjCmF60g96b6O/CGocuacm5u0LupZpDKL50PNqXuDvveAUDIBT3s/T0CDGZVe7mjO4Yi+aM7w/ZfEb/2oSnv+55Kvzw1rvGyxv5wCandoNKrWxwm0Rp/IhF5ONGZqXJKz72Piwe/dr56tHGSYsoVFGA3mXl8=',
            'Origin': 'https://xunkebao.baidu.com',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://xunkebao.baidu.com/index.html',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        payload = {
            "param": {
                "resourceType": 1,
                "resourceIds": [enterprise_id],
                "isNeedValidate": True,
                "platform": "pc"
            }
        }
        
        try:
            response = self._make_request('POST', url, headers=headers, cookies=self.xunkebao_cookies, json=payload)
            if response:
                response.raise_for_status()
                data = response.json() if hasattr(response, 'json') else {}
            else:
                print("请求返回为空")
                return False
            
            if data.get('msg') == 'success':
                print("资源解锁成功")
                return True
            else:
                print(f"资源解锁失败: {data.get('msg', '未知错误')}")
                return False
                
        except Exception as e:
            print(f"资源解锁请求失败: {e}")
            return False
    
    def unlock_stock_info(self) -> bool:
        """
        解锁股东信息 - 第二步解锁
        """
        print("正在解锁股东信息")
        
        url = "https://xunkebao.baidu.com/crm/web/aiqicha/bizcrm/enterprise/resourceunlock/unlockstockinfo"
        
        headers = {
            'Host': 'xunkebao.baidu.com',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Sourceid': 'c938675913262e5c474fe8c687377be6',
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
            'Api-Version': '0',
            'sec-ch-ua-mobile': '?0',
            'Auth-Type': 'PAAS',
            'User-Info': 'uc_id=;uc_appid=585;acc_token=;acc_id=309412743;login_id=309412743;device_type=dgtsale-h5;paas_appid=18;version=12;login_type=passport',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/plain, */*',
            'Env': 'WEB',
            'Client-Version': '0',
            'Origin': 'https://xunkebao.baidu.com',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://xunkebao.baidu.com/index.html',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        payload = {
            "param": {
                "resourceType": 1
            }
        }
        
        try:
            response = self._make_request('POST', url, headers=headers, cookies=self.xunkebao_cookies, json=payload)
            if response:
                response.raise_for_status()
                data = response.json() if hasattr(response, 'json') else {}
            else:
                print("请求返回为空")
                return False
            
            if data.get('msg') == 'success':
                print("股东信息解锁成功")
                return True
            else:
                print(f"股东信息解锁失败: {data.get('msg', '未知错误')}")
                return False
                
        except Exception as e:
            print(f"股东信息解锁请求失败: {e}")
            return False
    
    def get_contact_info(self, enterprise_id: str) -> List[str]:
        """
        第五步：获取员工联系方式
        """
        print(f"正在获取联系方式: {enterprise_id}")
        
        url = "https://xunkebao.baidu.com/crm/web/aiqicha/bizcrm/enterprise/enterpriseContact/queryContactDetail"
        
        headers = {
            'Host': 'xunkebao.baidu.com',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Sourceid': 'daad96ab0928e33cba984d732fa8cdce',
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
            'Api-Version': '0',
            'sec-ch-ua-mobile': '?0',
            'Auth-Type': 'PAAS',
            'User-Info': 'uc_id=;uc_appid=585;acc_token=;acc_id=309412743;login_id=309412743;device_type=dgtsale-h5;paas_appid=18;version=12;login_type=passport',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/plain, */*',
            'Env': 'WEB',
            'Client-Version': '0',
            'Acs-Token': '1756357560894_1756435432742_dbk68mIoTC8sQaI56pGHBhFPb1/zywkb8Tr5j1iQLy6oRnREQpweyM0f3a/BB33NbApVFDKxc53V1Z2witepN6CMvdsh9tcqkrF3vDqlyaZ6avNZlWyfDFbxg4UHXWxScxAOvco05/L87avNZQzOgec2F0qq+TK1Uu2G5BFyn/dexeD+gjx8A2W+62at7JaYvHF4+viIEGisnR8Pq1nmDcm/qi92SHb8glujimZ1S0Fxq5LZlSvC+nynzgUxnnSOQ4GAsTKKlSufrmSKJWQd1gg0JWatqA5hGAOuMp6BV6uIKln+PWTKA1Z8PJK3Jayx99Enqx2/uFddZs3AL1ifT62mCOJa5rIPJQu6OwadjZ9JZHlFyre1Zic0S1gU1iWAHcWy22fSRB+5jQegmV8U4lqHEbWolrl4kBUQY1ntWkXttWe0ntMZfU5rr4FRj/hSt0AnxSw0GY33oPAce/DHCDE3Ne0hNR3Ss9Q6Q4rq1ho=',
            'Origin': 'https://xunkebao.baidu.com',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://xunkebao.baidu.com/index.html',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        payload = {
            "param": {
                "enterpriseId": enterprise_id,
                "isNeedCrawlWeChat": True,
                "isNeedLoadEnterpriseTag": True
            }
        }
        
        try:
            response = self._make_request('POST', url, headers=headers, cookies=self.xunkebao_cookies, json=payload)
            if response:
                response.raise_for_status()
                data = response.json() if hasattr(response, 'json') else {}
            else:
                print("请求返回为空")
                return []
            
            # 修复数据结构解析，增加更严格的类型检查
            phone_numbers = []
            
            # 确保data是字典类型
            if not isinstance(data, dict):
                print(f"返回数据类型错误: {type(data).__name__}")
                return []
                
            # 获取data字段，确保它是字典或列表
            data_field = data.get('data')
            
            if data_field is None:
                print("返回数据中没有data字段")
                return []
                
            if isinstance(data_field, list) and len(data_field) > 0:
                # data是一个列表，取第一个元素
                first_data = data_field[0]
                if isinstance(first_data, dict):
                    phone_numbers = first_data.get('allCellPhoneNOs', [])
                else:
                    print(f"data列表中的元素类型错误: {type(first_data).__name__}")
            elif isinstance(data_field, dict):
                # 如果data是字典格式
                phone_numbers = data_field.get('allCellPhoneNOs', [])
            elif isinstance(data_field, str):
                # 如果data是字符串，可能是JSON字符串，尝试解析
                print(f"data字段是字符串类型，无法提取手机号码")
                return []
            else:
                print(f"未知的data字段类型: {type(data_field).__name__}")
                return []
            
            if phone_numbers:
                # 去重处理
                unique_phones = list(set(phone_numbers))
                print(f"获取到{len(unique_phones)}个手机号码（已去重）")
                return unique_phones
            else:
                print("未能获取到手机号码")
                return []
                
        except Exception as e:
            print(f"获取联系方式失败: {e}")
            return []
    
    def query_app_info(self, pid: str, status_callback=None) -> Dict:
        """查询企业APP信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        update_status(f"正在查询APP信息: {pid}")
        
        try:
            url = f"https://aiqicha.baidu.com/detail/compManageAjax?pid={pid}"
            
            headers = {
                'Host': 'aiqicha.baidu.com',
                'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': self._stable_aiqicha_client_ua(),
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=operatingCondition',
            }
            
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
                html_content = response.text if hasattr(response, 'text') else ""
            else:
                return {
                    'success': False,
                    'message': 'APP信息请求返回为空',
                    'data': []
                }
            
            if data.get('status') != 0:
                message = data.get('msg') or data.get('message') or '未知错误'
                if not self._is_no_data_message(message):
                    if self._should_open_browser(url, response=response, html_content=html_content):
                        self._open_with_drissionpage(url, "aiqicha_app_drissionpage")
                else:
                    return {
                        'success': True,
                        'message': f'APP信息为空: {message}',
                        'pid': pid,
                        'data': []
                    }
                return {
                    'success': False,
                    'error': f'APP信息查询失败: {message}',
                    'pid': pid
                }
            
            app_list = []
            if 'data' in data and 'appinfo' in data['data']:
                app_info = data['data']['appinfo']
                if 'list' in app_info:
                    for item in app_info['list']:
                        app_data = {
                            'name': item.get('name', '')  # APP名称
                        }
                        app_list.append(app_data)
            
            update_status(f"成功获取 {len(app_list)} 个APP信息")
            return {
                'success': True,
                'message': f'成功获取 {len(app_list)} 个APP信息',
                'pid': pid,
                'data': app_list
            }
            
        except Exception as e:
            if self._should_open_browser(url):
                self._open_with_drissionpage(url, "aiqicha_app_drissionpage")
            return {
                'success': False,
                'error': f'APP信息查询异常: {str(e)}',
                'pid': pid
            }
    
    def query_wechat_info(self, pid: str, status_callback=None) -> Dict:
        """查询企业微信公众号信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        update_status(f"正在查询微信公众号信息: {pid}")
        
        try:
            url = f"https://aiqicha.baidu.com/detail/compManageAjax?pid={pid}"
            
            headers = {
                'Host': 'aiqicha.baidu.com',
                'sec-ch-ua': AiqichaQuery.AIQICHA_SEC_CH_UA,
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': self._stable_aiqicha_client_ua(),
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=operatingCondition',
            }
            
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
                html_content = response.text if hasattr(response, 'text') else ""
            else:
                return {
                    'success': False,
                    'message': '微信公众号信息请求返回为空',
                    'data': []
                }
            
            if data.get('status') != 0:
                message = data.get('msg') or data.get('message') or '未知错误'
                if not self._is_no_data_message(message):
                    if self._should_open_browser(url, response=response, html_content=html_content):
                        self._open_with_drissionpage(url, "aiqicha_wechat_drissionpage")
                else:
                    return {
                        'success': True,
                        'message': f'微信公众号信息为空: {message}',
                        'pid': pid,
                        'data': []
                    }
                return {
                    'success': False,
                    'error': f'微信公众号信息查询失败: {message}',
                    'pid': pid
                }
            
            wechat_list = []
            if 'data' in data and 'wechatoa' in data['data']:
                wechat_info = data['data']['wechatoa']
                if 'list' in wechat_info:
                    for item in wechat_info['list']:
                        wechat_data = {
                            'wechatName': item.get('wechatName', ''),  # 微信公众号名称
                            'wechatId': item.get('wechatId', '')  # 微信公众号
                        }
                        wechat_list.append(wechat_data)
            
            update_status(f"成功获取 {len(wechat_list)} 个微信公众号信息")
            return {
                'success': True,
                'message': f'成功获取 {len(wechat_list)} 个微信公众号信息',
                'pid': pid,
                'data': wechat_list
            }
            
        except Exception as e:
            if self._should_open_browser(url):
                self._open_with_drissionpage(url, "aiqicha_wechat_drissionpage")
            return {
                'success': False,
                'error': f'微信公众号信息查询异常: {str(e)}',
                'pid': pid
            }
    
    def query_company_info(self, company_name: str, pid: Optional[str] = None, status_callback=None) -> Optional[Dict]:
        """
        完整查询企业信息的主函数
        """
        def update_status(message, step=None, completed=False):
            print(message)
            if status_callback:
                # 如果是步骤完成，则更新到下一个进度值
                if completed and step is not None:
                    status_callback(message, step)
                else:
                    # 步骤开始时，保持当前进度不变
                    status_callback(message, step - 1 if step and step > 0 else 0)
        
        result = {
            'company_name': company_name,
            'basic_info': {},
            'industry_info': {},
            'icp_info': [],
            'contact_info': []
        }
        success_to_close_browser = False
        try:
            # 每次完整查询前重新加载配置中的 Cookie（与 UI「更新 Cookie」及外部改配置文件保持一致）
            self.reload_session_cookies_from_config()

            # 如果没有提供pid，先搜索企业
            if not pid:
                update_status("第一步：搜索企业信息", 1)
                search_result = self.search_company(company_name)
                if not search_result:
                    print("搜索失败，无法继续")
                    return None  # 返回None而不是空的result字典
                
                # 从搜索结果中提取基本信息和pid
                if 'result' in search_result and 'resultList' in search_result['result']:
                    first_result = search_result['result']['resultList'][0]
                    pid = first_result.get('pid')
                    matched_company_name = self._get_result_company_name(first_result)
                    if matched_company_name:
                        result['company_name'] = matched_company_name
                    
                    # 提取基本信息
                    result['basic_info'] = {
                        'legalPerson': first_result.get('legalPerson', ''),
                        'titleDomicile': first_result.get('titleDomicile', ''),
                        'regCap': first_result.get('regCap', ''),
                        'regNo': first_result.get('regNo', ''),  # 统一社会信用代码
                        'email': first_result.get('email', ''),
                        'website': first_result.get('website', ''),
                        'telephone': first_result.get('telephone', '')
                    }
                    
                    # 存储PID到结果中
                    result['pid'] = pid
                    
                    print(f"提取到企业PID: {pid}")
                    update_status("第一步完成：已获取企业基本信息", 1, completed=True)
                else:
                    print("搜索结果格式异常")
                    success_to_close_browser = True
                    return result
            
            # 如果有pid，继续后续步骤
            if pid:
                print(f"\n=== 使用PID: {pid} ===")
                
                # 第二步：获取企业详情
                update_status("第二步：获取企业详情", 2)
                detail_result = self.get_company_detail(pid)
                
                if detail_result and 'result' in detail_result:
                    detail_data = detail_result['result']
                    
                    # 提取行业信息
                    industry_more = detail_data.get('industryMore', {})
                    result['industry_info'] = {
                        'industryCode1': industry_more.get('industryCode1', ''),
                        'industryCode2': industry_more.get('industryCode2', ''),
                        'industryCode3': industry_more.get('industryCode3', ''),
                        'industryCode4': industry_more.get('industryCode4', ''),
                        'industryNum': industry_more.get('industryNum', '')
                    }
                    try:
                        debug_raw = {
                            'industryMore': industry_more,
                            'industryName1': detail_data.get('industryName1', ''),
                            'industryName2': detail_data.get('industryName2', ''),
                            'industryName3': detail_data.get('industryName3', ''),
                            'industryName4': detail_data.get('industryName4', ''),
                            'industryCategory': detail_data.get('industryCategory', ''),
                            'industry': detail_data.get('industry', '')
                        }
                        print(f"🔎 行业分类调试[aiqicha:{pid}] raw={debug_raw} parsed={result['industry_info']}")
                    except Exception:
                        pass
                    
                    # 提取员工邮箱信息
                    email_info = detail_data.get('emailinfo', [])
                    result['industry_info']['employee_emails'] = [item.get('email', '') for item in email_info]
                    
                    print(f"提取到行业信息和{len(email_info)}个员工邮箱")
                    update_status("第二步完成：已获取企业详情", 2, completed=True)
                
                # 第三步：获取ICP信息
                update_status("第三步：获取ICP备案信息", 3)
                icp_info = self.get_icp_info(pid)
                result['icp_info'] = icp_info
                update_status("第三步完成：已获取ICP备案信息", 3, completed=True)
                
                # 第四步：获取APP信息
                update_status("第四步：获取APP信息", 4)
                app_result = self.query_app_info(pid, status_callback)
                result['app_info'] = app_result.get('data', []) if app_result.get('success') else []
                update_status("第四步完成：已获取APP信息", 4, completed=True)
                
                # 第五步：获取微信公众号信息
                update_status("第五步：获取微信公众号信息", 5)
                wechat_result = self.query_wechat_info(pid, status_callback)
                result['wechat_info'] = wechat_result.get('data', []) if wechat_result.get('success') else []
                update_status("第五步完成：已获取微信公众号信息", 5, completed=True)
                
                # 第六步：获取企业ID
                update_status("第六步：获取企业ID", 6)
                enterprise_id = self.get_enterprise_id(pid)
                update_status("第六步完成：已获取企业ID", 6, completed=True)
                
                # 第七步：解锁资源
                if enterprise_id:
                    update_status("第七步：解锁资源", 7)
                    unlock1_success = self.unlock_resource(enterprise_id)
                    update_status("第七步完成：资源解锁成功", 7, completed=True)
                    
                    if unlock1_success:
                        # 第八步：解锁股东信息
                        update_status("第八步：解锁股东信息", 8)
                        unlock2_success = self.unlock_stock_info()
                        
                        if unlock2_success:
                            update_status("第八步完成：股东信息解锁成功", 8, completed=True)
                            # 第九步：获取员工联系方式
                            update_status("第九步：获取员工联系方式", 9)
                            contact_info = self.get_contact_info(enterprise_id)
                            result['contact_info'] = contact_info
                            update_status("查询完成！", 9, completed=True)
                        else:
                            update_status("解锁失败，无法获取员工联系方式", 8)
                    else:
                        update_status("解锁失败，无法获取员工联系方式", 7)
                else:
                    update_status("未获取到企业ID，跳过联系方式查询", 6)
            
            success_to_close_browser = True
            return result
        finally:
            if success_to_close_browser:
                self._close_opened_browser_pages()
    
    def print_result(self, result: Dict):
        """
        格式化输出查询结果
        """
        print("\n" + "="*50)
        print(f"企业查询结果: {result['company_name']}")
        print("="*50)
        
        # 基本信息
        print("\n【基本信息】")
        basic = result.get('basic_info', {})
        print(f"法人代表: {basic.get('legalPerson', '未获取到')}")
        print(f"企业地址: {basic.get('titleDomicile', '未获取到')}")
        print(f"注册资本: {basic.get('regCap', '未获取到')}")
        print(f"统一社会信用代码: {basic.get('regNo', '未获取到')}")
        print(f"企业邮箱: {basic.get('email', '未获取到')}")
        print(f"企业网站: {basic.get('website', '未获取到')}")
        print(f"企业电话: {basic.get('telephone', '未获取到')}")
        
        # 行业信息
        print("\n【行业分类】")
        industry = result.get('industry_info', {})
        print(f"行业大类: {industry.get('industryCode1', '未获取到')}")
        print(f"行业中类: {industry.get('industryCode2', '未获取到')}")
        print(f"行业小类: {industry.get('industryCode3', '未获取到')}")
        print(f"具体分类: {industry.get('industryCode4', '未获取到')}")
        print(f"行业编号: {industry.get('industryNum', '未获取到')}")
        
        # 员工企业邮箱
        employee_emails = industry.get('employee_emails', [])
        if employee_emails:
            print("\n【员工企业邮箱】")
            for i, email in enumerate(employee_emails, 1):
                print(f"{i}. {email}")
        
        # ICP信息
        print("\n【ICP备案信息】")
        if result['icp_info']:
            for i, icp in enumerate(result['icp_info'], 1):
                domains = icp.get('domain', [])
                domain_str = ', '.join(domains) if isinstance(domains, list) else str(domains)
                print(f"{i}. 域名: {domain_str}")
                print(f"   网站名称: {icp.get('siteName', 'N/A')}")
                print(f"   备案号: {icp.get('icpNo', 'N/A')}")
        else:
            print("暂无ICP备案信息")
        
        # APP信息
        print("\n【APP信息】")
        app_info = result.get('app_info', [])
        if app_info:
            for i, app in enumerate(app_info, 1):
                print(f"{i}. APP名称: {app.get('name', 'N/A')}")
        else:
            print("暂无APP信息")
        
        # 微信公众号信息
        print("\n【微信公众号信息】")
        wechat_info = result.get('wechat_info', [])
        if wechat_info:
            for i, wechat in enumerate(wechat_info, 1):
                print(f"{i}. 公众号名称: {wechat.get('wechatName', 'N/A')}")
                print(f"   微信号: {wechat.get('wechatId', 'N/A')}")
        else:
            print("暂无微信公众号信息")
        
        # 联系方式
        print("\n【员工手机号码】")
        if result['contact_info']:
            for i, phone in enumerate(result['contact_info'], 1):
                print(f"{i:2d}. {phone}")
        else:
            print("暂无员工手机号码信息")
    
    def batch_search(self, companies: List[str], progress_callback=None, 
                    error_callback=None, delay_range: Optional[tuple] = None) -> Dict:
        """批量查询企业信息
        
        Args:
            companies: 企业名称列表
            progress_callback: 进度回调函数
            error_callback: 错误回调函数
            delay_range: 自定义延时范围 (min_delay, max_delay)
            
        Returns:
            批量查询结果字典
        """
        try:
            results = []
            total_companies = len(companies)
            success_count = 0
            
            # 设置自定义延时
            if delay_range:
                original_min_delay = self.min_delay
                original_max_delay = self.max_delay
                self.min_delay, self.max_delay = delay_range
            
            for i, company in enumerate(companies, 1):
                company = company.strip()
                if not company:
                    continue
                
                if progress_callback:
                    progress_callback(f"正在查询第 {i}/{total_companies} 家公司: {company}")
                
                try:
                    result = self.query_company_info(company)
                    
                    if result and result.get('success', False):
                        results.append({
                            'company': company,
                            'data': result,
                            'success': True,
                            'index': i
                        })
                        success_count += 1
                        
                        if progress_callback:
                            progress_callback(f"查询 {company} 成功")
                    else:
                        error_msg = result.get('error', '查询失败') if result else '查询失败'
                        results.append({
                            'company': company,
                            'error': error_msg,
                            'success': False,
                            'index': i
                        })
                        
                        if error_callback:
                            error_callback(f"查询 {company} 失败: {error_msg}")
                        elif progress_callback:
                            progress_callback(f"查询 {company} 失败: {error_msg}")
                    
                except Exception as e:
                    error_msg = str(e)
                    results.append({
                        'company': company,
                        'error': error_msg,
                        'success': False,
                        'index': i
                    })
                    
                    if error_callback:
                        error_callback(f"查询 {company} 异常: {error_msg}")
                    elif progress_callback:
                        progress_callback(f"查询 {company} 异常: {error_msg}")
                
                # 批量查询间的额外延时（减少延时以提高用户体验）
                if i < total_companies:
                    extra_delay = random.uniform(0.5, 1.0)  # 额外0.5-1秒延时
                    time.sleep(extra_delay)
            
            # 恢复原始延时设置
            if delay_range:
                self.min_delay = original_min_delay
                self.max_delay = original_max_delay
            
            return {
                'success': True,
                'results': results,
                'total': total_companies,
                'success_count': success_count,
                'failure_count': total_companies - success_count,
                'message': f'批量查询完成，成功: {success_count}/{total_companies}'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'批量查询异常: {str(e)}',
                'results': [],
                'total': 0,
                'success_count': 0,
                'failure_count': 0
            }
    
    def format_batch_results(self, batch_result: Dict) -> str:
        """格式化批量查询结果"""
        if not batch_result.get('success', False):
            return f"批量查询失败: {batch_result.get('error', '未知错误')}"
        
        results = batch_result.get('results', [])
        if not results:
            return "没有查询结果"
        
        formatted_text = f"""📊 爱企查批量查询结果报告
{'='*50}
总查询数量: {batch_result.get('total', 0)}
成功查询: {batch_result.get('success_count', 0)}
失败查询: {batch_result.get('failure_count', 0)}
成功率: {(batch_result.get('success_count', 0) / max(batch_result.get('total', 1), 1) * 100):.1f}%

详细结果:
{'='*50}
"""
        
        for i, result in enumerate(results, 1):
            company = result.get('company', 'N/A')
            
            if result.get('success', False):
                data = result.get('data', {})
                basic_info = data.get('basic_info', {})
                
                formatted_text += f"\n{i}. ✅ {company}"
                formatted_text += f"\n   统一社会信用代码: {basic_info.get('creditCode', 'N/A')}"
                formatted_text += f"\n   法定代表人: {basic_info.get('legalPersonName', 'N/A')}"
                formatted_text += f"\n   注册资本: {basic_info.get('regCapital', 'N/A')}"
                formatted_text += f"\n   成立日期: {basic_info.get('estiblishTime', 'N/A')}"
                formatted_text += f"\n   企业状态: {basic_info.get('regStatus', 'N/A')}"
                
                # ICP备案信息
                icp_info = data.get('icp_info', [])
                if icp_info:
                    formatted_text += f"\n   ICP备案: {len(icp_info)}个"
                else:
                    formatted_text += f"\n   ICP备案: 无"
                
                # 联系方式
                contact_info = data.get('contact_info', [])
                if contact_info:
                    formatted_text += f"\n   员工手机: {len(contact_info)}个"
                else:
                    formatted_text += f"\n   员工手机: 无"
                
            else:
                error_msg = result.get('error', '未知错误')
                formatted_text += f"\n{i}. ❌ {company}"
                formatted_text += f"\n   错误: {error_msg}"
            
            formatted_text += "\n" + "-"*30
        
        return formatted_text

def main():
    """
    主函数
    """
    print("爱企查企业信息查询工具")
    print("注意：使用前需要先登录爱企查和寻客宝，并更新Cookie信息")
    
    # 创建查询实例
    query = AiqichaQuery()
    
    # 选择查询模式
    mode = input("请选择查询模式 (1: 单个查询, 2: 批量查询): ").strip()
    
    if mode == "2":
        # 批量查询模式
        print("\n批量查询模式")
        print("请输入企业名称，每行一个，输入空行结束:")
        
        companies = []
        while True:
            company = input().strip()
            if not company:
                break
            companies.append(company)
        
        if not companies:
            print("未输入任何企业名称")
            return
        
        def progress_callback(msg):
            print(f"进度: {msg}")
        
        def error_callback(msg):
            print(f"错误: {msg}")
        
        print(f"\n开始批量查询 {len(companies)} 家企业...")
        batch_result = query.batch_search(
            companies, 
            progress_callback=progress_callback,
            error_callback=error_callback
        )
        
        # 输出批量查询结果
        print("\n" + "=" * 60)
        print(query.format_batch_results(batch_result))
        
    else:
        # 单个查询模式
        company_name = input("请输入要查询的企业名称: ").strip()
        if not company_name:
            company_name = "杭州安恒信息技术股份有限公司"  # 默认示例
        
        # 执行查询（自动通过企业名称搜索获取PID）
        result = query.query_company_info(company_name)
        
        # 输出结果
        if result:
            query.print_result(result)
        else:
            print(f"查询企业 '{company_name}' 失败")

if __name__ == "__main__":
    main()
