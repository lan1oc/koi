#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天眼查企业信息查询脚本
功能：通过企业名称查询企业的详细信息，包括基本信息、ICP备案等
"""

import requests
import json
import time
import random
import re
import os
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, no_type_check
try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    HAS_DRISSIONPAGE = True
except ImportError:
    HAS_DRISSIONPAGE = False

try:
    from .cookie_manager import ChromeCookieManager
    HAS_COOKIE_MANAGER = True
except ImportError:
    try:
        from cookie_manager import ChromeCookieManager
        HAS_COOKIE_MANAGER = True
    except ImportError:
        HAS_COOKIE_MANAGER = False

class MockResponse:
    """模拟HTTP响应对象，用于调试保存HTML内容"""
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.headers = {'content-type': 'text/html; charset=utf-8'}
    
    def raise_for_status(self):
        """模拟requests.Response的raise_for_status方法"""
        pass

class TianyanchaQuery:
    def __init__(self, config_path=None):
        self.session = requests.Session()
        
        # 静态 User-Agent 列表（作为备用）
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
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
        
        # 请求间隔配置（秒）- 优化为更保守的真实请求间隔
        self.min_delay = 1.5  # 最小延迟1.5秒
        self.max_delay = 3.0  # 最大延迟3秒
        self.last_request_time = 0
        
        # 增加请求失败重试配置
        self.max_retries = 3
        self.retry_delay = 5.0
        
        # 自动登录配置
        self.auto_login_enabled = True  # 启用自动登录
        self.max_login_attempts = 3     # 最大登录尝试次数
        self.login_wait_timeout = 300   # 登录等待超时时间（秒）
        self.cookie_check_interval = 0.1  # Cookie检查间隔（秒） - 真正的实时检测
        
        # 设置通用请求头（完全按照原始请求包）
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        })
        
        # 天眼查Cookie配置（从config.json读取）
        self.tianyancha_cookies = {}
        if config_path:
            self.config_path = config_path
        else:
            try:
                from modules.config.config_manager import ConfigManager
                self.config_path = ConfigManager().config_file
            except Exception:
                self.config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config.json')
        
        # 调试输出配置
        self.debug_output_enabled = False  # 默认关闭调试输出
        # 终端控制台日志（请求与调试信息）开关，默认关闭
        self.console_log_enabled = False
        # 是否显示详细请求信息（URL/Method/Headers/Cookies），默认关闭
        self.show_request_details = False
        
        # 登录/验证成功后是否立即关闭用于验证的浏览器
        # 若为True，保存cookies并验证通过后立刻关闭挂起的浏览器
        self.auto_close_after_login = True
        self.debug_output_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_output')
        if not os.path.exists(self.debug_output_dir):
            os.makedirs(self.debug_output_dir)
        
        # 验证浏览器挂起关闭回调（在成功获取数据后触发）
        self._pending_browser_close = None
        # 验证浏览器页面引用（用于重复从浏览器抓取页面而不重发HTTP请求）
        self._verification_page_ref = None
        # 验证过程状态与实时检测配置
        self._verification_in_progress = False
        self.verification_poll_interval = 0.1  # 验证未完成时的轮询间隔（秒）
        self.verification_poll_timeout = 90    # 验证未完成时的最大等待时间（秒）
        # 验证浏览器页面捕获（在验证完成后直接使用浏览器获取到的页面响应）
        self._verification_page_capture = None
        self._verification_user_closed = False
        self._verification_auto_close_requested = False

        self._load_config()
    

    def _load_config(self):
        """从config.json加载配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                # 加载天眼查cookies
                tyc_config = config.get('tyc', {})
                cookie_str = tyc_config.get('cookie', '')
                
                # 将cookie字符串解析为字典
                if cookie_str:
                    self.tianyancha_cookies = {}
                    for item in cookie_str.split(';'):
                        if '=' in item:
                            key, value = item.strip().split('=', 1)
                            self.tianyancha_cookies[key] = value
                else:
                    self.tianyancha_cookies = {}
                
                # 加载调试输出配置
                debug_config = config.get('debug', {})
                self.debug_output_enabled = debug_config.get('tianyancha_debug_output', False)
                # 控制台日志打印（请求/DEBUG信息）开关
                self.console_log_enabled = debug_config.get('tianyancha_console_log', False)
                
                # 保持简短的初始化提示，不受console_log_enabled控制
                print(f"已加载配置文件: {self.config_path}")
                if self.tianyancha_cookies:
                    print("已加载天眼查Cookie配置")
                else:
                    print("警告：未找到天眼查Cookie配置，可能影响查询功能")
            else:
                self.tianyancha_cookies = {}
                print(f"配置文件不存在: {self.config_path}")
                print("将使用默认配置")
        except Exception as e:
            self.tianyancha_cookies = {}
            print(f"加载配置文件失败: {str(e)}")
            print("将使用默认配置")
    
    def _clear_cookies(self):
        """清除所有cookies"""
        try:
            # 清除内存中的cookies
            self.tianyancha_cookies = {}
            
            # 清除session中的cookies
            self.session.cookies.clear()
            
            print("已清除所有cookies")
        except Exception as e:
            print(f"清除cookies失败: {str(e)}")
    
    def _save_debug_response(self, url: str, response, request_info: Optional[dict] = None, force_save: bool = False):
        """保存调试响应到HTML文件（仅保存HTML，不保存JSON元数据）"""
        if not self.debug_output_enabled and not force_save:
            return
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 精确到毫秒
            
            # 从URL中提取有意义的文件名部分
            if 'nsearch' in url:
                filename_prefix = "tianyancha_search"
            elif 'company' in url:
                filename_prefix = "tianyancha_company"
            elif 'icp' in url.lower():
                filename_prefix = "tianyancha_icp"
            elif 'app' in url.lower():
                filename_prefix = "tianyancha_app"
            elif 'wechat' in url.lower():
                filename_prefix = "tianyancha_wechat"
            else:
                filename_prefix = "tianyancha_response"
            
            if response is not None:
                try:
                    # 获取响应文本
                    response_text = response.text
                    
                    # 检查响应内容类型
                    content_type = response.headers.get('content-type', '').lower()
                    
                    # 对于JSON响应，保存为格式化的JSON文件
                    if 'application/json' in content_type:
                        try:
                            json_data = response.json()
                            json_filename = f"{filename_prefix}_{timestamp}_response.json"
                            json_filepath = os.path.join(self.debug_output_dir, json_filename)
                            with open(json_filepath, 'w', encoding='utf-8') as f:
                                json.dump(json_data, f, ensure_ascii=False, indent=2)
                            print(f"🐛 调试JSON响应已保存到: {json_filepath}")
                            return
                        except:
                            # JSON解析失败，按HTML处理
                            pass
                    
                    # 对于HTML或其他文本内容，保存为格式化的HTML文件
                    if HAS_BS4 and response_text.strip():
                        try:
                            # 首先格式化JSON数据在script标签中
                            formatted_text = response_text
                            
                            # 使用正则表达式查找并格式化JSON数据
                            import re
                            script_pattern = r'(<script[^>]*type=["\']application/json["\'][^>]*>)(.*?)(</script>)'
                            
                            def format_json_content(match):
                                opening_tag = match.group(1)
                                json_content = match.group(2)
                                closing_tag = match.group(3)
                                
                                try:
                                    # 尝试解析和格式化JSON
                                    json_data = json.loads(json_content.strip())
                                    formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
                                    return f"{opening_tag}\n{formatted_json}\n{closing_tag}"
                                except:
                                    # 如果JSON解析失败，保持原样
                                    return match.group(0)
                            
                            formatted_text = re.sub(script_pattern, format_json_content, formatted_text, flags=re.DOTALL)
                            
                            # 使用BeautifulSoup格式化HTML
                            soup = BeautifulSoup(formatted_text, 'html.parser')
                            formatted_html = soup.prettify()
                        except Exception as e:
                            # 如果BeautifulSoup解析失败，使用原始文本
                            formatted_html = response_text
                    else:
                        # 如果没有BeautifulSoup或内容为空，使用原始文本
                        formatted_html = response_text
                    
                    # 保存格式化的HTML到文件
                    html_filename = f"{filename_prefix}_{timestamp}_response.html"
                    html_filepath = os.path.join(self.debug_output_dir, html_filename)
                    with open(html_filepath, 'w', encoding='utf-8') as f:
                        # 确保写入的内容是字符串类型
                        if isinstance(formatted_html, bytes):
                            f.write(formatted_html.decode('utf-8', errors='ignore'))
                        else:
                            f.write(str(formatted_html))
                    
                    print(f"🐛 调试HTML响应已保存到: {html_filepath}")
                    
                except Exception as e:
                    print(f"❌ 读取响应内容失败: {str(e)}")
            else:
                print(f"❌ 未收到响应，无法保存调试文件")
            
        except Exception as e:
            print(f"❌ 保存调试响应失败: {str(e)}")
    
    def _anti_crawl_delay(self, status_callback=None):
        """反爬延时控制 - 天眼查专用加强版"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # 计算需要等待的时间 - 天眼查需要更长延时
        min_interval = random.uniform(self.min_delay, self.max_delay)
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            message = f"天眼查反爬延时: {sleep_time:.2f}秒"
            print(message)
            if status_callback:
                status_callback(message)
            
            # 尝试使用异步延时
            try:
                # 检查是否在QThread环境中
                from PySide6.QtCore import QThread, QTimer
                from PySide6.QtWidgets import QApplication
                
                if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) and isinstance(getattr(self, 'parent', None), QThread)):
                    # 在QThread环境中，使用异步延时
                    try:
                        # 尝试导入并使用AsyncDelay工具类
                        from ...utils.async_delay import AsyncDelay
                        AsyncDelay.delay(
                            milliseconds=int(sleep_time * 1000),
                            progress_callback=status_callback
                        )
                    except (ImportError, ModuleNotFoundError):
                        # 如果导入失败，使用QTimer进行异步延时
                        timer = QTimer()
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: None)
                        timer.start(int(sleep_time * 1000))
                        
                        # 等待定时器完成
                        loop = QTimer()
                        loop.setSingleShot(True)
                        loop.start(int(sleep_time * 1000))
                        while loop.isActive():
                            QApplication.processEvents()
                            # 增加休眠时间，减少CPU占用
                            time.sleep(0.05)
                else:
                    # 不在QThread环境中，使用传统的time.sleep
                    time.sleep(sleep_time)
            except (ImportError, NameError):
                # 如果导入失败，使用传统的time.sleep
                time.sleep(sleep_time)
        
        self.last_request_time = int(time.time())
    
    def _get_random_ua(self):
        """获取随机User-Agent"""
        if self.use_fake_ua:
            try:
                if self.ua:
                    return self.ua.random
                return random.choice(self.user_agents)
            except Exception:
                return random.choice(self.user_agents)
        else:
            return random.choice(self.user_agents)
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        new_ua = self._get_random_ua()
        self.session.headers.update({'User-Agent': new_ua})
        return new_ua
    
    def _detect_login_required(self, response_text):
        """检测响应是否需要登录"""
        if not response_text:
            return False
        
        response_lower = response_text.lower()
        
        # 首先独立检测验证码页面（优先级最高，不依赖其他条件）
        captcha_keywords = [
            '请进行身份验证以继续使用',
            '行为验证',
            'captcha',
            '人机验证',
            '验证码',
            '安全验证'
        ]
        
        # 检测是否是验证码页面
        for keyword in captcha_keywords:
            if keyword in response_text:
                return "captcha_required"  # 新增状态：需要验证码

        try:
            has_user_mobile = re.search(r'"userIdentity"\s*:\s*\{[^}]*"mobile"\s*:\s*"(?!")', response_text, re.IGNORECASE)
            has_user_id = re.search(r'"userIdentity"\s*:\s*\{[^}]*"userId"\s*:\s*"(?!")', response_text, re.IGNORECASE)
            if has_user_mobile or has_user_id:
                return False
        except Exception:
            pass
        
        # 检查JSON数据中的mustlogin状态
        if 'mustlogin' in response_lower:
            return True
        
        # 首先检查是否已经登录（isLogin:1表示已登录，isLogin:0表示未登录）
        if '"islogin":1' in response_lower or '"islogin": 1' in response_lower or 'islogin:1' in response_lower:
            return False
        
        # 如果检测到isLogin:0，说明未登录，需要进一步检查
        if '"islogin":0' in response_lower or '"islogin": 0' in response_lower or 'islogin:0' in response_lower:
            # 兼容API接口：很多JSON接口在未登录(isLogin:0)时仍返回有效数据
            # 若接口返回成功标识（state=ok 或 errorCode=0）且包含data字段，则视为无需登录
            json_success_markers = (
                ('"state":"ok"' in response_lower),
                ('"errorcode":0' in response_lower or '"errorCode":0' in response_lower),
            )
            has_data_block = '"data":' in response_lower or '"item":' in response_lower or '"itemTotal":' in response_lower
            if any(json_success_markers) and has_data_block:
                return False
            # 仍然可能需要登录以获取更完整数据
            return True
        
        # 检查是否包含公司数据（如果有companyList说明请求成功）
        if 'companylist' in response_lower:
            return False
        
        # 检测真正需要登录的关键词 - 扩展检测范围
        login_keywords = [
            '登录查看',
            '登录后查看',
            '登录后查看更多信息',
            '请先登录',
            '需要登录',
            '扫码登录',
            '微信登录',
            'class="login',
            'id="login',
            '请登录后查看',
            '登录后可查看',
            'span class="_c7f86">登录查看',
            'button class="login',
            '登录后查看完整信息',
            '立即登录',
            '免费注册',
            '登录/注册',
            'window.location.href="/login"',
            'location.href="/login"',
            'href="/login"',
            '>登录<',
            '登录</a>',
            '登录</button>'
        ]
        
        # 先检查是否真的需要登录
        needs_login = False
        for keyword in login_keywords:
            if keyword.lower() in response_lower:
                needs_login = True
                break
        
        # 检查HTTP状态码相关的登录需求
        if '401' in response_text or '403' in response_text:
            needs_login = True
        
        # 如果确实需要登录，再检查具体的登录类型
        if needs_login:
            # 检测真正的账号被暂停（明确表示账号问题）
            suspended_keywords = [
                '被暂停了',
                '系统检测到您当前帐号的操作存在异常',
                '已暂停您的访问请求',
                '账号异常',
                '操作异常'
            ]
            
            # 如果检测到账号被暂停，返回特殊标识
            for keyword in suspended_keywords:
                if keyword in response_text:
                    return "account_suspended"  # 返回特殊标识
            
            return True  # 普通的需要登录
        
        # 新增：检查是否是已登录但账号被限制的情况
        # 这种情况下，用户已经登录（URL已变化），但是看到限制页面
        account_restricted_keywords = [
            '系统检测到您当前帐号的操作存在异常',
            '已暂停您的访问请求',
            '账号异常',
            '操作异常',
            '访问频率过高',
            '请稍后再试',
            '系统繁忙'
        ]
        
        # 如果检测到账号被限制但不需要重新登录，返回特殊状态
        for keyword in account_restricted_keywords:
            if keyword in response_text:
                return "account_restricted"  # 新增状态：账号被限制但已登录
        
        # 新增：检查账号被停用的情况（扫码后显示账号被停用）
        account_disabled_keywords = [
            '账号被停用',
            '账户被停用',
            '账号已停用',
            '账户已停用',
            '账号被禁用',
            '账户被禁用',
            '账号已被停用',
            '账户已被停用',
            '该账号已被停用',
            '该账户已被停用',
            '账号状态异常',
            '账户状态异常',
            '账号不可用',
            '账户不可用',
            '系统检测到您当前账号的操作存在异常',
            '已暂停您的访问请求',
            '操作存在异常',
            '暂停您的访问',
            '账号的操作存在异常',
            '当前账号的操作存在异常'
        ]
        
        # 如果检测到账号被停用，返回特殊状态
        for keyword in account_disabled_keywords:
            if keyword in response_text:
                return "account_disabled"  # 新增状态：账号被停用
        
        # 新增：检查是否返回了天眼查主页HTML而不是API数据
        # 如果请求的是API接口但返回了HTML页面，通常意味着需要登录
        if ('<!DOCTYPE html>' in response_text or '<html' in response_text) and '天眼查' in response_text:
            # 这是天眼查的HTML页面，不是API响应，需要登录
            print("🔍 [DEBUG] 检测到返回HTML页面而非API数据，判断需要登录")
            return True
        
        return False
    
    def _is_cookie_valid(self, cookies_dict):
        """检查cookie是否有效"""
        if not cookies_dict:
            return False
        
        # 检查关键cookie是否存在
        required_cookies = ['HWWAFSESTIME', 'HWWAFSESID']
        for cookie_name in required_cookies:
            if cookie_name not in cookies_dict or not cookies_dict[cookie_name]:
                return False
        
        # 检查cookie是否过期（简单检查）
        try:
            # 如果有时间戳相关的cookie，可以检查是否过期
            if 'HWWAFSESTIME' in cookies_dict:
                # 这里可以添加更复杂的过期检查逻辑
                pass
        except:
            pass
        
        return True
    
    def _validate_cookies(self, cookies_list):
        """验证从浏览器获取的cookies是否有效 - 改进版本，避免验证页面cookie被误判为有效"""
        if not cookies_list:
            return False
        
        # 将cookies列表转换为字典
        cookies_dict = {}
        for cookie in cookies_list:
            name = cookie.get('name', '')
            value = cookie.get('value', '')
            if name and value:
                cookies_dict[name] = value
        
        # 检查是否包含关键的天眼查cookies
        key_cookies = ['HWWAFSESTIME', 'HWWAFSESID', 'tyc-user-info', 'auth_token', 'sessionid']
        found_key_cookies = 0
        
        for key_cookie in key_cookies:
            if key_cookie in cookies_dict and cookies_dict[key_cookie]:
                found_key_cookies += 1
        
        # 检查是否有tyc-user-info这个最重要的登录标识cookie
        has_user_info = 'tyc-user-info' in cookies_dict and cookies_dict['tyc-user-info']
        
        # 更严格的验证：必须有tyc-user-info或者至少3个关键cookie
        if has_user_info or found_key_cookies >= 3:
            # 额外检查：确保不是验证页面的cookie
            # 验证页面通常只有基础的session cookie，没有用户信息
            if has_user_info:
                return True
            elif found_key_cookies >= 3:
                return True
        
        # 如果没有足够的关键cookie，检查是否有其他有效的天眼查相关cookie
        tyc_cookies = [name for name in cookies_dict.keys() if 'tyc' in name.lower() or 'tianyancha' in name.lower()]
        
        # 更严格的条件：需要有用户相关的cookie且总数超过8个
        if len(tyc_cookies) > 2 and len(cookies_dict) > 8:
            # 检查是否包含用户相关的cookie名称
            user_related_cookies = [name for name in cookies_dict.keys() 
                                  if any(keyword in name.lower() for keyword in ['user', 'auth', 'login', 'token'])]
            if len(user_related_cookies) > 0:
                return True
        
        return False
    
    def _verify_login_status(self, status_callback=None):
        """验证当前登录状态"""
        try:
            if status_callback:
                status_callback("🔍 验证登录状态...")
            
            # 访问用户中心页面来验证登录状态
            test_url = "https://www.tianyancha.com/usercenter/"
            response = self.session.get(test_url, timeout=10)
            
            if response.status_code == 200:
                # 检查是否包含登录用户信息
                if any(keyword in response.text for keyword in ['用户中心', 'userCenter', 'user-info']):
                    if status_callback:
                        status_callback("✅ 登录状态验证成功")
                    return True
                else:
                    if status_callback:
                        status_callback("❌ 登录状态验证失败 - 未找到用户信息")
                    return False
            else:
                if status_callback:
                    status_callback(f"❌ 登录状态验证失败 - 状态码: {response.status_code}")
                return False
                
        except Exception as e:
            if status_callback:
                status_callback(f"❌ 登录状态验证异常: {str(e)}")
            return False
    
    def _test_cookie_validity(self, status_callback=None):
        """测试当前Cookie是否有效"""
        try:
            if status_callback:
                status_callback("🧪 正在测试Cookie有效性...")
            
            # 使用一个简单的API来测试Cookie是否有效
            test_url = "https://www.tianyancha.com/next/web/getUserInfo"
            
            response = self.session.get(test_url, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    # 如果返回用户信息，说明Cookie有效
                    if data.get('state') == 'ok' or 'data' in data:
                        if status_callback:
                            status_callback("✅ Cookie测试成功 - 用户信息获取正常")
                        return True
                except:
                    pass
            
            # 如果上面的测试失败，尝试访问首页看是否需要登录
            home_url = "https://www.tianyancha.com/"
            response = self.session.get(home_url, timeout=10)
            
            if response.status_code == 200:
                # 检查是否需要登录
                login_required = self._detect_login_required(response.text)
                if not login_required:
                    if status_callback:
                        status_callback("✅ Cookie测试成功 - 首页访问正常")
                    return True
                else:
                    if status_callback:
                        status_callback("❌ Cookie测试失败 - 仍需要登录")
                    return False
            
            if status_callback:
                status_callback("❌ Cookie测试失败 - 网络请求异常")
            return False
            
        except Exception as e:
            if status_callback:
                status_callback(f"❌ Cookie测试异常: {str(e)}")
            return False
    
    def _handle_captcha_verification(self, url, response_text=None, status_callback=None, use_temp_dir=False):
        """处理验证码验证的情况 - 默认带cookie，只有账户被暂停时才不带cookie"""
        if status_callback:
            status_callback("🔐 启动验证码验证流程...")
            status_callback("🔧 _handle_captcha_verification方法已被调用")
            status_callback("🌐 正在启动浏览器...")
        
        try:
            self._verification_user_closed = False
            self._verification_auto_close_requested = False
            # 检查DrissionPage是否可用
            if not HAS_DRISSIONPAGE:
                if status_callback:
                    status_callback("DrissionPage未安装，请先安装: pip install DrissionPage")
                return False
                
            if status_callback:
                status_callback("✅ 浏览器控制模块导入成功")
            
            if status_callback:
                status_callback("⚙️ 正在配置浏览器选项...")
            # 创建浏览器实例 - 使用现有cookie
            options = ChromiumOptions()
            if status_callback:
                status_callback("🔧 创建浏览器选项对象成功")
            
            # 使用cookie管理器创建独立的用户数据目录
            if HAS_COOKIE_MANAGER:
                cookie_manager = ChromeCookieManager()
                if use_temp_dir:
                    user_data_dir = cookie_manager.create_user_data_dir(with_cookies=False)
                    if status_callback:
                        status_callback("🗂️ 使用独立用户数据目录，无cookie干扰（账户被暂停模式）")
                else:
                    user_data_dir = cookie_manager.create_user_data_dir(with_cookies=True)
                    cookies = cookie_manager.load_cookies_from_config()
                    if cookies:
                        cookie_manager.setup_cookies_in_chrome_profile(user_data_dir, cookies)
                    if status_callback:
                        status_callback("🍪 使用独立用户数据目录，已从配置文件复制cookie（正常模式）")
                
                options.set_user_data_path(user_data_dir)
            else:
                # 回退到原来的逻辑（如果cookie管理器不可用）
                if use_temp_dir:
                    import tempfile
                    temp_dir = tempfile.mkdtemp(prefix="tianyancha_captcha_")
                    options.set_user_data_path(temp_dir)
                    if status_callback:
                        status_callback("🗂️ 使用临时用户数据目录（回退模式）")
                else:
                    if status_callback:
                        status_callback("🍪 使用默认用户数据目录（回退模式）")
            
            # 设置浏览器启动参数 - 强力解决混合内容阻止问题
            browser_args = [
                '--window-size=1200,800',
                '--disable-popup-blocking',
                '--enable-javascript',
                # 核心混合内容处理参数 - 基于最新Chrome版本
                '--allow-running-insecure-content',  # 允许不安全内容运行
                '--disable-web-security',  # 完全禁用网络安全限制
                '--disable-features=VizDisplayCompositor,MixedContentAutoupgrade,InsecureDownloadWarnings',  # 禁用混合内容自动升级
                '--disable-mixed-content-autoupgrade',  # 禁用混合内容自动升级（备用参数）
                '--allow-insecure-localhost',  # 允许不安全的本地主机
                '--disable-extensions',  # 禁用扩展，避免干扰
                '--no-sandbox',  # 禁用沙盒模式
                '--disable-dev-shm-usage',  # 禁用/dev/shm使用
                # 图片和资源加载强制参数
                '--blink-settings=imagesEnabled=true',  # 强制启用图片加载
                '--disable-features=BlockInsecurePrivateNetworkRequests',  # 禁用阻止不安全私有网络请求
                '--ignore-certificate-errors',  # 忽略证书错误
                '--ignore-ssl-errors',  # 忽略SSL错误
                '--ignore-certificate-errors-spki-list',  # 忽略证书错误列表
                '--ignore-certificate-errors-skip-list',  # 跳过证书错误列表
                '--disable-site-isolation-trials',  # 禁用站点隔离试验
                # 强制信任不安全来源 - 关键参数
                '--unsafely-treat-insecure-origin-as-secure=http://captcha.tianyancha.com,http://static.tianyancha.com,http://img.tianyancha.com,http://antirobot.tianyancha.com',
                # 禁用安全检查
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI,BlinkGenPropertyTrees',
            ]
            
            for arg in browser_args:
                options.set_argument(arg)
            
            if status_callback:
                status_callback("⚙️ 浏览器选项配置完成")
                status_callback("🚀 正在启动Chrome浏览器...")
            
            # 启动浏览器 - 完全按照测试文件
            page = ChromiumPage(addr_or_opts=options)
            # 记录页面引用用于后续重复抓取HTML
            self._verification_page_ref = page
            # 记录页面引用用于后续重复抓取HTML
            self._verification_page_ref = page
            
            # 记录浏览器挂起关闭回调，待成功获取企业数据后自动关闭
            self._pending_browser_close = (lambda p=page: p.quit())
            if status_callback:
                status_callback("🧹 已记录浏览器关闭回调，将在数据获取成功后自动关闭")

            if status_callback:
                status_callback("✅ 浏览器启动成功")
                status_callback("🌐 浏览器已打开")
            
            # 最大化窗口并获取焦点
            page.set.window.max()
            page.run_js("window.focus();")
            if status_callback:
                status_callback("🎯 已获取窗口焦点")
            
            # Windows API处理
            try:
                import platform
                if platform.system() == "Windows":
                    import win32gui
                    import win32con
                    
                    def enum_windows_callback(hwnd, windows):
                        if win32gui.IsWindowVisible(hwnd):
                            window_text = win32gui.GetWindowText(hwnd)
                            if "Chrome" in window_text:
                                windows.append((hwnd, window_text))
                        return True
                    
                    windows = []
                    win32gui.EnumWindows(enum_windows_callback, windows)
                    
                    if windows:
                        hwnd, title = windows[0]
                        win32gui.SetForegroundWindow(hwnd)
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        if status_callback:
                            status_callback("🎯 已使用Windows API将窗口置于前台")
            except Exception as e:
                if status_callback:
                    status_callback(f"⚠️ Windows API处理失败: {e}")
            
            # 访问搜索页面（优先使用当前请求的URL），避免固定跳转验证页
            if status_callback:
                status_callback("📄 访问搜索页面...")
                status_callback("⚠️  请注意：浏览器窗口已打开，请在浏览器中完成验证操作")

            try:
                target_url = url if (isinstance(url, str) and url.startswith("http")) else "https://www.tianyancha.com/"
                if isinstance(target_url, str) and ('capi.tianyancha.com' in target_url or target_url.startswith('https://capi.') or target_url.startswith('http://capi.')):
                    target_url = "https://www.tianyancha.com/"
            except Exception:
                target_url = "https://www.tianyancha.com/"

            # 打开目标URL（可能会被站点重定向到登录/验证页，属正常）
            page.get(target_url)
            
            # 等待页面加载 - 与测试文件一致
            time.sleep(3)
            
            # Cookie状态说明（现在通过Chrome数据库预设）
            if not use_temp_dir and HAS_COOKIE_MANAGER:
                if status_callback:
                    status_callback("🍪 Cookie已通过Chrome数据库预设，无需手动设置")
            elif use_temp_dir:
                if status_callback:
                    status_callback("🆕 使用全新的浏览器环境，无任何旧cookie（账户被暂停模式）")
            else:
                if status_callback:
                    status_callback("ℹ️ 使用回退模式，可能需要手动登录")
            
            # 检测验证弹窗状态
            if status_callback:
                status_callback("🔍 正在检测验证弹窗状态...")
            
            def detect_verification_popup():
                """检测验证弹窗的详细状态"""
                try:
                    verification_info = page.run_js("""
                        var result = {
                            // 基本信息
                            pageTitle: document.title,
                            currentUrl: window.location.href,
                            
                            // 图像点击验证
                            imageClickVerification: {
                                found: false,
                                instructionTexts: [],
                                images: [],
                                confirmButtons: []
                            },
                            
                            // 滑动验证
                            slideVerification: {
                                found: false,
                                sliders: []
                            },
                            
                            // 拼图验证
                            puzzleVerification: {
                                found: false,
                                puzzles: []
                            },
                            
                            // 通用验证元素
                            generalElements: {
                                modals: [],
                                iframes: [],
                                canvases: []
                            }
                        };
                        
                        // 1. 检测图像点击验证
                        var clickTexts = [
                            '请在下图依次点击', '请依次点击', '点击验证', '请点击',
                            '按顺序点击', '依次点击', '请按顺序点击', '点击图片',
                            '请选择', '选择正确', '点击正确'
                        ];
                        
                        clickTexts.forEach(function(text) {
                            var elements = Array.from(document.querySelectorAll('*')).filter(el => 
                                el.textContent && el.textContent.includes(text) && 
                                window.getComputedStyle(el).display !== 'none'
                            );
                            if (elements.length > 0) {
                                result.imageClickVerification.found = true;
                                result.imageClickVerification.instructionTexts.push({
                                    text: text,
                                    fullText: elements[0].textContent.trim()
                                });
                            }
                        });
                        
                        // 检测验证图片
                        var verifyImages = document.querySelectorAll(
                            'img[src*="captcha"], img[src*="verify"], img[src*="geetest"], ' +
                            '[class*="captcha"] img, [class*="verify"] img, [class*="geetest"] img, ' +
                            'canvas[class*="captcha"], canvas[class*="verify"], canvas[class*="geetest"]'
                        );
                        
                        for (var i = 0; i < verifyImages.length; i++) {
                            var img = verifyImages[i];
                            var style = window.getComputedStyle(img);
                            if (style.display !== 'none' && style.visibility !== 'hidden') {
                                result.imageClickVerification.images.push({
                                    tag: img.tagName,
                                    width: img.offsetWidth,
                                    height: img.offsetHeight
                                });
                            }
                        }
                        
                        // 检测确定按钮
                        var buttonTexts = ['确定', '确认', '提交', '完成', '验证', '下一步'];
                        buttonTexts.forEach(function(text) {
                            var buttons = Array.from(document.querySelectorAll(
                                'button, div[role="button"], [class*="btn"], [class*="button"], input[type="button"], input[type="submit"]'
                            )).filter(el => 
                                el.textContent && el.textContent.trim().includes(text) &&
                                window.getComputedStyle(el).display !== 'none'
                            );
                            
                            buttons.forEach(function(btn) {
                                result.imageClickVerification.confirmButtons.push({
                                    text: btn.textContent.trim(),
                                    tag: btn.tagName
                                });
                            });
                        });
                        
                        // 2. 检测滑动验证
                        var sliders = document.querySelectorAll(
                            '[class*="slider"], [class*="slide"], [id*="slider"], [id*="slide"]'
                        );
                        for (var i = 0; i < sliders.length; i++) {
                            var slider = sliders[i];
                            var style = window.getComputedStyle(slider);
                            if (style.display !== 'none') {
                                result.slideVerification.found = true;
                                result.slideVerification.sliders.push({
                                    className: slider.className
                                });
                            }
                        }
                        
                        // 3. 检测拼图验证
                        var puzzles = document.querySelectorAll(
                            '[class*="puzzle"], [class*="jigsaw"], [id*="puzzle"], [id*="jigsaw"]'
                        );
                        for (var i = 0; i < puzzles.length; i++) {
                            var puzzle = puzzles[i];
                            var style = window.getComputedStyle(puzzle);
                            if (style.display !== 'none') {
                                result.puzzleVerification.found = true;
                                result.puzzleVerification.puzzles.push({
                                    className: puzzle.className
                                });
                            }
                        }
                        
                        // 4. 检测通用验证元素
                        // 模态框
                        var modals = document.querySelectorAll(
                            '[class*="modal"], [class*="dialog"], [class*="popup"], [class*="overlay"], [class*="mask"]'
                        );
                        for (var i = 0; i < modals.length; i++) {
                            var modal = modals[i];
                            var style = window.getComputedStyle(modal);
                            if (style.display !== 'none' && style.visibility !== 'hidden') {
                                result.generalElements.modals.push({
                                    className: modal.className,
                                    zIndex: style.zIndex
                                });
                            }
                        }
                        
                        // iframe
                        var iframes = document.querySelectorAll('iframe');
                        for (var i = 0; i < iframes.length; i++) {
                            var iframe = iframes[i];
                            var style = window.getComputedStyle(iframe);
                            if (style.display !== 'none') {
                                result.generalElements.iframes.push({
                                    src: iframe.src
                                });
                            }
                        }
                        
                        // canvas
                        var canvases = document.querySelectorAll('canvas');
                        for (var i = 0; i < canvases.length; i++) {
                            var canvas = canvases[i];
                            var style = window.getComputedStyle(canvas);
                            if (style.display !== 'none') {
                                result.generalElements.canvases.push({
                                    width: canvas.width,
                                    height: canvas.height
                                });
                            }
                        }
                        
                        return result;
                    """)
                    
                    return verification_info
                    
                except Exception as e:
                    if status_callback:
                        status_callback(f"❌ 检测验证弹窗失败: {e}")
                    return None
            
            # 连续检测验证弹窗状态，确保完全加载
            if status_callback:
                status_callback("🔍 开始连续检测验证弹窗状态...")
            
            verification_detected = False
            detection_attempts = 0
            max_detection_attempts = 20  # 最多检测10秒（每0.5秒一次）
            
            while not verification_detected and detection_attempts < max_detection_attempts:
                detection_attempts += 1
                
                if status_callback and detection_attempts % 4 == 1:  # 每2秒显示一次进度
                    status_callback(f"🔄 第{detection_attempts}次检测验证弹窗...")
                
                verification_info = detect_verification_popup()
                
                if verification_info:
                    # 分析验证状态
                    img_verify = verification_info['imageClickVerification']
                    slide_verify = verification_info['slideVerification']
                    puzzle_verify = verification_info['puzzleVerification']
                    general = verification_info['generalElements']
                    
                    # 综合判断验证状态
                    has_image_verification = (img_verify['found'] or 
                                            len(img_verify['images']) > 0 or 
                                            len(img_verify['confirmButtons']) > 0)
                    
                    has_any_verification = (has_image_verification or 
                                          slide_verify['found'] or 
                                          puzzle_verify['found'])
                    
                    has_modal_container = len(general['modals']) > 0 or len(general['canvases']) > 0
                    
                    # 检查是否检测到完整的验证弹窗
                    if has_any_verification and has_modal_container:
                        verification_detected = True
                        
                        if status_callback:
                            status_callback("📊 验证弹窗检测结果:")
                            status_callback(f"   🖼️ 图像验证: {has_image_verification}")
                            status_callback(f"   🎚️ 滑动验证: {slide_verify['found']}")
                            status_callback(f"   🧩 拼图验证: {puzzle_verify['found']}")
                            status_callback(f"   📦 容器元素: {len(general['modals'])}个模态框, {len(general['canvases'])}个canvas")
                            status_callback("🎉 验证弹窗检测成功！验证界面已完全加载")
                            
                            # 提供具体的操作指导
                            if has_image_verification:
                                if img_verify['instructionTexts']:
                                    for inst in img_verify['instructionTexts']:
                                        status_callback(f"📝 验证指令: {inst['fullText']}")
                                status_callback("🖼️ 请根据提示点击图片中的指定位置")
                            
                            if slide_verify['found']:
                                status_callback("🎚️ 请拖动滑块完成验证")
                            
                            if puzzle_verify['found']:
                                status_callback("🧩 请拖动拼图块到正确位置")
                            
                            if img_verify['confirmButtons']:
                                button_texts = [btn['text'] for btn in img_verify['confirmButtons']]
                                status_callback(f"🔘 完成后请点击: {', '.join(button_texts[:3])}")
                        break
                    else:
                        # 检测到部分元素但不完整，继续等待
                        if status_callback and detection_attempts % 4 == 0:  # 每2秒显示一次详细信息
                            status_callback(f"⏳ 检测到部分验证元素，等待完全加载... (尝试{detection_attempts}/{max_detection_attempts})")
                            if has_any_verification:
                                status_callback(f"   ✓ 验证元素已检测到")
                            if has_modal_container:
                                status_callback(f"   ✓ 容器元素已检测到")
                
                # 等待0.5秒后继续检测
                time.sleep(0.5)
            
            if not verification_detected:
                if status_callback:
                    status_callback("⚠️ 验证弹窗检测超时，可能页面加载较慢或验证类型不支持")
                    status_callback("💡 请手动检查浏览器中是否有验证弹窗出现")
            
            # 获取初始URL用于检测变化
            initial_url = page.url
            
            # 启动URL检测线程，监控登录状态变化
            import threading
            login_success = threading.Event()
            detection_result = {"success": False, "cookies": None, "user_closed": False}
            
            def url_detection_thread():
                """优化的URL检测线程 - 基于成功测试脚本的经验"""
                last_url = initial_url
                check_count = 0
                
                try:
                    if status_callback:
                        status_callback("🔄 URL检测线程已启动")
                        status_callback(f"📍 初始URL: {last_url}")
                        status_callback(f"🔧 检测间隔: {self.cookie_check_interval}秒")
                        status_callback(f"⏰ 超时时间: {self.login_wait_timeout}秒")
                        status_callback("🎯 开始监控URL变化...")
                    
                    while not login_success.is_set():
                        try:
                            # 检查浏览器是否被用户关闭
                            try:
                                current_url = page.url
                                browser_alive = True
                            except Exception as e:
                                if self._verification_auto_close_requested:
                                    self._verification_auto_close_requested = False
                                    if status_callback:
                                        status_callback("🧹 检测到自动关闭浏览器")
                                    self._pending_browser_close = None
                                    self._verification_page_ref = None
                                    login_success.set()
                                    break
                                if status_callback:
                                    status_callback("🚪 检测到用户手动关闭浏览器")
                                self._pending_browser_close = None
                                self._verification_page_ref = None
                                detection_result["user_closed"] = True
                                login_success.set()
                                break
                            
                            # 精确的检测间隔
                            time.sleep(self.cookie_check_interval)
                            check_count += 1
                            
                            # 获取当前URL
                            current_url = page.url
                            
                            # 检测URL变化
                            if current_url != last_url:
                                if status_callback:
                                    status_callback(f"🔄 检测到URL变化 (第{check_count}次检查)")
                                    status_callback(f"📍 从: {last_url}")
                                    status_callback(f"📍 到: {current_url}")
                                
                                # 检查是否还在验证页面
                                is_verification_page = any(keyword in current_url.lower() for keyword in [
                                    'verify', 'captcha', 'challenge', 'security', 'robot', 'human',
                                    'verification', 'check', 'validate', 'confirm'
                                ])
                                
                                if is_verification_page:
                                    if status_callback:
                                        status_callback("⚠️ 检测到仍在验证页面，继续等待...")
                                    last_url = current_url
                                    continue
                                
                                # URL变化后等待页面稳定
                                if status_callback:
                                    status_callback("⏳ 等待页面稳定...")
                                time.sleep(2)  # 等待页面稳定

                                # 若已进入搜索结果页，提前捕获页面HTML供后续解析使用
                                try:
                                    if ("/nsearch?key=" in current_url) or ("/search?key=" in current_url):
                                        try:
                                            captured_html = page.html
                                        except Exception:
                                            captured_html = None
                                        if captured_html:
                                            self._verification_page_capture = {
                                                'url': current_url,
                                                'html': captured_html,
                                                'timestamp': time.time()
                                            }
                                            if status_callback:
                                                status_callback("📄 已捕获搜索结果页HTML（等待Cookie验证）")
                                except Exception as e:
                                    if status_callback:
                                        status_callback(f"⚠️ 捕获搜索页HTML失败: {str(e)}")
                                
                                # 获取cookies
                                try:
                                    current_cookies = page.cookies()
                                    if status_callback:
                                        status_callback(f"🍪 获取到 {len(current_cookies)} 个cookies")
                                    
                                    # 验证cookies
                                    if self._validate_cookies(current_cookies):
                                        # 再次确认不在验证页面
                                        final_url = page.url
                                        final_is_verification = any(keyword in final_url.lower() for keyword in [
                                            'verify', 'captcha', 'challenge', 'security', 'robot', 'human',
                                            'verification', 'check', 'validate', 'confirm'
                                        ])
                                        
                                        if not final_is_verification:
                                            if status_callback:
                                                status_callback("✅ Cookies验证成功！")
                                            
                                            # 保存有效cookies
                                            temp_cookies = {}
                                            for cookie in current_cookies:
                                                name = cookie.get('name', '')
                                                value = cookie.get('value', '')
                                                if name and value:
                                                    temp_cookies[name] = value
                                            
                                            detection_result["success"] = True
                                            detection_result["cookies"] = temp_cookies
                                            login_success.set()
                                            break
                                        else:
                                            if status_callback:
                                                status_callback("⚠️ 最终检查发现仍在验证页面，继续等待...")
                                    else:
                                        if status_callback:
                                            status_callback("⚠️ Cookies验证失败，继续监控...")
                                
                                except Exception as e:
                                    if status_callback:
                                        status_callback(f"⚠️ 获取cookies失败: {str(e)}")
                                
                                last_url = current_url
                            
                            # 每10秒显示一次状态
                            if check_count % 100 == 0:  # 每10秒显示一次
                                if status_callback:
                                    elapsed = check_count * self.cookie_check_interval
                                    status_callback(f"⏰ 已监控 {elapsed:.1f} 秒，等待验证完成...")
                        
                        except Exception as e:
                            if status_callback:
                                status_callback(f"⚠️ URL检测异常: {str(e)}")
                            time.sleep(1)
                
                except Exception as e:
                    if status_callback:
                        status_callback(f"❌ URL检测线程异常: {str(e)}")
            
            # 启动URL检测线程
            detection_thread = threading.Thread(target=url_detection_thread, daemon=True)
            detection_thread.start()
            
            # 等待用户完成验证
            if status_callback:
                status_callback("⏰ 请在浏览器中完成验证...")
                status_callback("🔐 请完成人机验证或其他安全验证")
                status_callback("⚠️  重要：浏览器将保持开启，请手动完成验证")
                status_callback("💡 验证完成后，系统会自动检测并保存cookies")
                status_callback("🔄 或者您可以手动关闭浏览器继续使用现有cookies")
            
            # 等待登录完成或超时，期间支持取消并定时心跳
            total_wait = 0.0
            step = max(self.cookie_check_interval, 0.2)
            if status_callback:
                status_callback(f"⏳ 正在等待登录/验证完成，最长 {self.login_wait_timeout} 秒…")
            while not login_success.is_set() and total_wait < self.login_wait_timeout:
                time.sleep(step)
                total_wait += step
                # 每隔约5秒输出一次心跳，提升UI感知
                if status_callback and int(total_wait) % 5 == 0:
                    try:
                        status_callback(f"⌛ 已等待 {int(total_wait)} 秒…")
                    except Exception:
                        pass
            login_completed = login_success.is_set()
            
            if login_completed:
                if detection_result.get("user_closed"):
                    if status_callback:
                        status_callback("🚪 检测到您手动关闭了浏览器")
                        status_callback("⚠️ 尚未保存新的Cookies，继续使用旧Cookies可能无法查询数据")
                        status_callback("💡 请在验证完成并提示‘已保存Cookies’之前不要关闭浏览器")
                    # 清理挂起关闭回调
                    self._pending_browser_close = None
                    self._verification_user_closed = True
                    # 优化：尝试检测当前会话Cookies是否已有效，若有效则直接保存并继续查询
                    try:
                        if self._verify_login_status(status_callback):
                            # 从requests会话提取cookies并持久化
                            try:
                                cookie_items = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                                cookie_dict = {it['name']: it['value'] for it in cookie_items if it.get('name') and it.get('value')}
                                if cookie_dict:
                                    # 更新到内存与会话
                                    self.tianyancha_cookies.update(cookie_dict)
                                    for n, v in cookie_dict.items():
                                        try:
                                            self.session.cookies.set(n, v)
                                        except Exception:
                                            pass
                                    # 持久化到配置
                                    self._update_cookies_to_config(self.tianyancha_cookies)
                                    if status_callback:
                                        status_callback("✅ 检测到会话Cookies有效，已保存并继续查询")
                                    return True
                            except Exception as e:
                                if status_callback:
                                    status_callback(f"⚠️ 自动保存Cookies异常: {str(e)}")
                        else:
                            # 进一步尝试：从配置文件加载历史Cookies并写入会话，然后再验证一次
                            try:
                                if os.path.exists(self.config_path):
                                    with open(self.config_path, 'r', encoding='utf-8') as f:
                                        cfg = json.load(f)
                                    tyc_cfg = (cfg.get('tyc') or {})
                                    # 从tyc配置拼装cookie字典（兼容字符串或字典）
                                    loaded_cookies = {}
                                    if isinstance(tyc_cfg, dict):
                                        # config可能保存为"cookie": "a=b; c=d" 或键值对
                                        cookie_str = tyc_cfg.get('cookie') or tyc_cfg.get('cookies')
                                        if isinstance(cookie_str, str):
                                            for part in cookie_str.split(';'):
                                                part = part.strip()
                                                if '=' in part:
                                                    name, value = part.split('=', 1)
                                                    loaded_cookies[name.strip()] = value.strip()
                                        else:
                                            for name, value in tyc_cfg.items():
                                                if isinstance(value, str):
                                                    loaded_cookies[name] = value
                                    # 将加载的cookies写入会话并验证
                                    if loaded_cookies:
                                        self.tianyancha_cookies.update(loaded_cookies)
                                        for n, v in loaded_cookies.items():
                                            try:
                                                self.session.cookies.set(n, v)
                                            except Exception:
                                                pass
                                        if self._verify_login_status(status_callback):
                                            self._update_cookies_to_config(self.tianyancha_cookies)
                                            if status_callback:
                                                status_callback("✅ 已从配置加载Cookies并验证通过，继续查询")
                                            return True
                            except Exception as e:
                                if status_callback:
                                    status_callback(f"⚠️ 尝试从配置加载Cookies失败: {str(e)}")
                    except Exception:
                        # 忽略回退检测中的异常，保持原有提示
                        pass
                    return False
                elif detection_result.get("success"):
                    # 在保存前先验证Cookie是否真正可用，避免未完成验证时误保存
                    if status_callback:
                        status_callback("🔎 正在验证Cookies是否可用于正常访问...")

                    # 使用检测到的临时cookies进行一次主页访问，确认不再需要登录/验证
                    try:
                        home_url = "https://www.tianyancha.com/"
                        response = self.session.get(home_url, cookies=detection_result["cookies"], timeout=10)
                        # 仅当检测为不需要登录/验证码时，认为验证通过
                        test_success = not self._detect_login_required(response.text)
                    except Exception:
                        test_success = False

                    if test_success:
                        # 仅在验证通过后再保存cookies到配置
                        self.tianyancha_cookies.update(detection_result["cookies"])
                        self._update_cookies_to_config(self.tianyancha_cookies)
                        # 同步到requests会话，确保后续请求实时生效
                        try:
                            for n, v in self.tianyancha_cookies.items():
                                try:
                                    self.session.cookies.set(n, v)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        if status_callback:
                            status_callback(f"✅ 验证完成！已保存 {len(detection_result['cookies'])} 个有效cookies")
                            status_callback("🌙 浏览器将保持开启，稍后根据查询结果自动关闭")
                        return True
                    else:
                        # 验证未通过，可能仍在验证过程，不保存cookies，保持浏览器打开
                        if status_callback:
                            status_callback("⚠️ Cookies验证未通过，可能仍在验证过程；暂不保存Cookies")
                            status_callback("💡 请在浏览器中继续完成验证，完成后程序会自动检测")
                        # 不将未通过的cookies写入配置，返回失败让上层逻辑不要继续误用
                        return False
                else:
                    if status_callback:
                        status_callback("⚠️ 未检测到成功验证")
                    return False
            else:
                if status_callback:
                    status_callback(f"⏰ 验证超时 ({self.login_wait_timeout}秒)，请重试")
                return False
            
        except Exception as e:
            if status_callback:
                status_callback(f"❌ 验证码处理异常: {str(e)}")
            return False

    def _handle_login_required(self, url, response_text=None, status_callback=None, incognito=False, attempt=1):
        """处理需要登录的情况 - 改进版本"""
        if status_callback:
            if incognito:
                status_callback(f"🚨 检测到账号被暂停，正在启动无痕浏览器... (尝试 {attempt}/{self.max_login_attempts})")
                status_callback("🔧 _handle_login_required方法已被调用 (无痕模式)")
            else:
                status_callback(f"🔑 检测到需要登录，启动半自动登录流程... (尝试 {attempt}/{self.max_login_attempts})")
                status_callback("🔧 _handle_login_required方法已被调用 (普通模式)")
                status_callback("🌐 正在启动浏览器...")
        
        try:
            # 检查DrissionPage是否可用
            if not HAS_DRISSIONPAGE:
                if status_callback:
                    status_callback("DrissionPage未安装，请先安装: pip install DrissionPage")
                return False
                
            if status_callback:
                status_callback("✅ 浏览器控制模块导入成功")
            
            if status_callback:
                status_callback("⚙️ 正在配置浏览器选项...")
            # 创建浏览器实例 - 默认使用无痕模式以获取真实页面状态
            options = ChromiumOptions()
            if status_callback:
                status_callback("🔧 创建浏览器选项对象成功")
            
            # 使用临时用户数据目录，既不带旧cookie又能正常加载验证页面
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="tianyancha_login_")
            options.set_user_data_path(temp_dir)
            if status_callback:
                status_callback("🗂️ 使用临时用户数据目录，确保无旧cookie干扰")
            
            # 设置浏览器启动参数 - 强力解决混合内容阻止问题
            browser_args = [
                '--window-size=1200,800',
                '--window-position=100,100',
                '--disable-popup-blocking',
                '--enable-javascript',
                # 核心混合内容处理参数 - 基于最新Chrome版本
                '--allow-running-insecure-content',  # 允许不安全内容运行
                '--disable-web-security',  # 完全禁用网络安全限制
                '--disable-features=VizDisplayCompositor,MixedContentAutoupgrade,InsecureDownloadWarnings',  # 禁用混合内容自动升级
                '--disable-mixed-content-autoupgrade',  # 禁用混合内容自动升级（备用参数）
                '--allow-insecure-localhost',  # 允许不安全的本地主机
                '--disable-extensions',  # 禁用扩展，避免干扰
                '--no-sandbox',  # 禁用沙盒模式
                '--disable-dev-shm-usage',  # 禁用/dev/shm使用
                # 图片和资源加载强制参数
                '--blink-settings=imagesEnabled=true',  # 强制启用图片加载
                '--disable-features=BlockInsecurePrivateNetworkRequests',  # 禁用阻止不安全私有网络请求
                '--ignore-certificate-errors',  # 忽略证书错误
                '--ignore-ssl-errors',  # 忽略SSL错误
                '--ignore-certificate-errors-spki-list',  # 忽略证书错误列表
                '--ignore-certificate-errors-skip-list',  # 跳过证书错误列表
                '--disable-site-isolation-trials',  # 禁用站点隔离试验
                # 强制信任不安全来源 - 关键参数
                '--unsafely-treat-insecure-origin-as-secure=http://captcha.tianyancha.com,http://static.tianyancha.com,http://img.tianyancha.com,http://antirobot.tianyancha.com',
                # 禁用安全检查
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI,BlinkGenPropertyTrees',
            ]
            
            for arg in browser_args:
                options.set_argument(arg)
            
            if status_callback:
                status_callback("⚙️ 浏览器选项配置完成")
                status_callback("🚀 正在启动Chrome浏览器...")
            
            page = ChromiumPage(addr_or_opts=options)
            
            # 记录浏览器挂起关闭回调，待成功获取企业数据后自动关闭
            self._pending_browser_close = (lambda p=page: p.quit())
            if status_callback:
                status_callback("🧹 已记录浏览器关闭回调，将在数据获取成功后自动关闭")

            if status_callback:
                status_callback("✅ 浏览器启动成功")
                status_callback("🌐 浏览器已打开")
            
            # 确保浏览器窗口在前台显示
            try:
                page.set.window.max()
                if status_callback:
                    status_callback("🔍 浏览器窗口已最大化")
                
                try:
                    page.run_js("window.focus();")
                    if status_callback:
                        status_callback("🎯 已执行 window.focus()")
                except Exception as e:
                    if status_callback:
                        status_callback(f"window.focus() 失败: {str(e)}")
                
                try:
                    import platform
                    if platform.system() == "Windows":
                        import win32gui
                        import win32con
                        
                        def enum_windows_callback(hwnd, windows):
                            if win32gui.IsWindowVisible(hwnd):
                                window_text = win32gui.GetWindowText(hwnd)
                                if "Chrome" in window_text or "天眼查" in window_text:
                                    windows.append((hwnd, window_text))
                            return True
                        
                        windows = []
                        win32gui.EnumWindows(enum_windows_callback, windows)
                        
                        if windows:
                            hwnd, title = windows[0]
                            win32gui.SetForegroundWindow(hwnd)
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            if status_callback:
                                status_callback("🎯 已使用Windows API将窗口置于前台")
                        else:
                            if status_callback:
                                status_callback("⚠️ 未找到Chrome窗口")
                except ImportError:
                    if status_callback:
                        status_callback("⚠️ Windows API扩展未安装，无法使用窗口置前增强")
                except Exception as e:
                    if status_callback:
                        status_callback(f"Windows API方法失败: {str(e)}")
                
                import time
                time.sleep(1)
                
            except Exception as e:
                if status_callback:
                    status_callback(f"窗口最大化失败: {str(e)}")
            
            if status_callback:
                status_callback(f"🔗 正在访问页面: {url[:50]}...")
                status_callback("⚠️  请注意：浏览器窗口已打开，请在浏览器中完成登录操作")
            
            # 访问当前URL（如果是API接口，改为访问主页以进行登录）
            if status_callback:
                status_callback("📄 开始加载页面...")
            nav_url = url
            try:
                if isinstance(nav_url, str) and ('capi.tianyancha.com' in nav_url or nav_url.startswith('https://capi.') or nav_url.startswith('http://capi.')):
                    nav_url = 'https://www.tianyancha.com/'
            except Exception:
                nav_url = 'https://www.tianyancha.com/'
            page.get(nav_url)
            
            # 实时检测页面加载状态
            loading_start_time = time.time()
            loading_timeout = 5  # 最大等待5秒
            last_status = None
            check_count = 0
            page_loaded = False
            
            if status_callback:
                status_callback("🔍 开始检测页面加载状态...")
            
            while time.time() - loading_start_time < loading_timeout:
                try:
                    check_count += 1
                    
                    # 尝试多种方法检测页面状态
                    try:
                        # 使用getattr安全获取页面状态，避免属性不存在的问题
                        current_status = getattr(page, 'ready_state', None)
                        if current_status is not None:
                            ready_state_available = True
                        else:
                            # 使用页面URL和标题作为加载完成的指标
                            current_status = 'complete' if page.url and page.title else 'loading'
                            ready_state_available = True
                    except:
                        current_status = None
                        ready_state_available = False
                    
                    # 尝试获取页面URL作为加载完成的指标
                    try:
                        current_url = page.url
                        url_available = True
                    except:
                        current_url = None
                        url_available = False
                    
                    # 如果ready_state可用，使用它
                    if ready_state_available and current_status:
                        if current_status != last_status:
                            if current_status == 'loading':
                                if status_callback:
                                    status_callback("⏳ 正在加载")
                            elif current_status == 'interactive':
                                if status_callback:
                                    status_callback("🔄 页面交互就绪")
                            elif current_status == 'complete':
                                if status_callback:
                                    elapsed = time.time() - loading_start_time
                                    status_callback(f"✅ 页面加载完成 ({elapsed:.2f}秒)")
                                page_loaded = True
                                break
                            last_status = current_status
                    
                    # 如果ready_state不可用但URL可用，认为页面基本加载完成
                    elif url_available and current_url and check_count > 5:  # 等待至少0.5秒
                        if status_callback:
                            elapsed = time.time() - loading_start_time
                            status_callback(f"✅ 页面加载完成 ({elapsed:.2f}秒)")
                        page_loaded = True
                        break
                    
                    # 快速检测，每100毫秒检查一次
                    time.sleep(0.1)
                    
                except Exception as e:
                    # 如果检测出错，短暂等待后重试
                    time.sleep(0.1)
                    continue
            
            # 如果超时或其他情况
            if not page_loaded:
                if time.time() - loading_start_time >= loading_timeout:
                    if status_callback:
                        status_callback("⏰ 页面加载检测超时，继续执行")
                else:
                    if status_callback:
                        status_callback("✅ 页面加载完成（检测完成）")
            
            # 获取并输出当前登录页面的URL
            if status_callback:
                try:
                    current_url = page.url
                    status_callback(f"🌐 当前页面URL: {current_url}")
                except Exception as e:
                    status_callback(f"🌐 当前页面URL: {url} (获取实时URL失败: {str(e)})")
            
            # 给用户提示和等待时间 - 参考测试文件的成功做法
            if status_callback:
                status_callback("\n" + "="*60)
                status_callback("📱 请按以下步骤操作：")
                status_callback("1️⃣ 使用手机天眼查APP扫描页面上的二维码")
                status_callback("2️⃣ 在手机上确认登录")
                status_callback("3️⃣ 等待页面自动跳转到主页面")
                status_callback("4️⃣ 如果出现行为验证弹窗，请手动完成验证")
                status_callback("5️⃣ 程序会自动检测登录状态和验证完成情况")
                status_callback("💡 提示：程序现在会等待您扫码登录，然后自动检测后续的验证步骤")
                status_callback("="*60 + "\n")
            
            # 等待3秒，给用户时间看到浏览器和进行操作 - 参考测试文件
            time.sleep(3)
            
            # 注意：调试文件将在Cookie变化后保存，而不是在这里
            
            # 等待用户登录完成
            if status_callback:
                status_callback("⏰ 等待登录完成，请在浏览器中扫码登录...")
                status_callback("📱 请使用天眼查APP扫描二维码完成登录")
                status_callback(f"⏳ 系统将等待最多{self.login_wait_timeout//60}分钟，登录完成后会自动继续...")
            
            # 记录初始cookie状态
            try:
                initial_cookies = page.cookies()
                initial_cookie_count = len(initial_cookies) if initial_cookies else 0
                if status_callback:
                    status_callback(f"📊 成功获取初始cookies，数量: {initial_cookie_count}")
            except Exception as e:
                initial_cookies = []
                initial_cookie_count = 0
                if status_callback:
                    status_callback(f"⚠️ 获取初始cookies失败: {str(e)}，使用空列表继续")
                    status_callback("🔄 这不会影响URL检测功能，继续执行...")
            
            # 提取关键cookie的初始值 - 改进版本
            def get_key_cookies(cookies):
                key_cookies = {}
                all_cookies = {}  # 记录所有cookie用于全面检测
                for cookie in cookies:
                    name = cookie.get('name', '')
                    value = cookie.get('value', '')
                    all_cookies[name] = value
                    
                    # 扩展关键cookie列表，包括更多重要的天眼查cookie
                    if name in ['HWWAFSESTIME', 'tyc-user-info', 'tyc-user-phone', 'auth_token', 'sessionid', 
                               'TYCID', 'csrfToken', 'ssuid', 'HWWAFSESID', 'loginway', 'token', 'user_id',
                               'aliyungf_tc', 'sensorsdata2015jssdkcross', 'tyc-user-info-save-time']:
                        key_cookies[name] = value
                return key_cookies, all_cookies
            
            initial_key_cookies, initial_all_cookies = get_key_cookies(initial_cookies)
            
            # 记录初始页面状态
            try:
                initial_url = page.url
                initial_title = page.title
                initial_html_length = len(page.html)
                if status_callback:
                    status_callback(f"📋 成功记录初始页面状态")
            except Exception as e:
                initial_url = url
                initial_title = ""
                initial_html_length = 0
                if status_callback:
                    status_callback(f"⚠️ 记录初始状态时出错: {str(e)}，使用默认值继续")
            
            if status_callback:
                status_callback(f"📊 初始Cookie数量: {initial_cookie_count}, 关键Cookie数量: {len(initial_key_cookies)}")
                status_callback(f"🌐 初始URL: {initial_url}")
                status_callback(f"📄 初始标题: {initial_title}")
                if self.debug_output_enabled:
                    status_callback(f"🔑 关键Cookie: {list(initial_key_cookies.keys())}")
                status_callback("🚀 准备启动URL检测线程...")
            
            # 🚀 重写的实时检测逻辑 - 基于成功测试脚本的经验
            # 核心思路：纯粹的URL检测循环，没有复杂的干扰逻辑
            import threading
            
            # 设置检测标志
            login_success = threading.Event()
            detection_result = {"success": False, "cookies": None}
            
            def url_detection_thread():
                """分阶段检测线程 - 先等待登录，再检测行为验证"""
                last_url = initial_url
                check_count = 0
                login_detected = False  # 标记是否已检测到登录成功
                
                try:
                    if status_callback:
                        status_callback("🔄 URL检测线程已启动")
                        status_callback(f"📍 初始URL: {last_url}")
                        status_callback("🎯 第一阶段：等待用户扫码登录...")
                    
                    while not login_success.is_set():
                        try:
                            # 精确的0.1秒检测间隔
                            time.sleep(self.cookie_check_interval)
                            check_count += 1
                            
                            # 检测浏览器是否被用户关闭
                            try:
                                current_url = page.url
                                page_title = page.title
                            except Exception as e:
                                error_msg = str(e).lower()
                                if any(keyword in error_msg for keyword in ['closed', 'disconnected', 'target', 'session', 'connection']):
                                    if status_callback:
                                        status_callback(f"🚪 检测到浏览器已被用户关闭")
                                        status_callback(f"🎯 智能查询时机触发：用户主动关闭浏览器，立即继续查询")
                                    # 清理页面引用
                                    self._verification_page_ref = None
                                    detection_result["success"] = True
                                    detection_result["cookies"] = None
                                    detection_result["user_closed"] = True
                                    login_success.set()
                                    return
                                else:
                                    if status_callback:
                                        status_callback(f"❌ 获取URL失败: {str(e)}")
                                    continue
                            
                            # 第一阶段：检测登录成功（URL变化或Cookie变化）
                            if not login_detected:
                                if current_url != last_url:
                                    if status_callback:
                                        status_callback(f"🎉 第{check_count}次检测发现URL变化！")
                                        status_callback(f"   从: {last_url}")
                                        status_callback(f"   到: {current_url}")
                                    
                                    # 检查是否还在登录/验证页面
                                    is_login_page = any(keyword in current_url.lower() for keyword in [
                                        'login', 'verify', 'captcha', 'challenge', 'security', 'robot', 'human',
                                        'verification', 'check', 'validate', 'confirm', 'auth'
                                    ])
                                    
                                    if is_login_page:
                                        if status_callback:
                                            status_callback("⚠️ 检测到仍在登录/验证页面，继续等待...")
                                        last_url = current_url
                                        continue
                                    
                                    # URL变化且不在登录页面，说明登录成功
                                    if status_callback:
                                        status_callback("✅ 检测到登录成功！URL已跳转到主页面")
                                        status_callback("⏳ 等待页面稳定...")
                                    
                                    time.sleep(2.0)  # 等待页面稳定
                                    
                                    # 获取登录后的cookies
                                    try:
                                        cookies = page.cookies()
                                        if status_callback:
                                            status_callback(f"🍪 获取到{len(cookies) if cookies else 0}个cookies")
                                        
                                        if cookies and len(cookies) > 0:
                                            # 验证Cookie的有效性
                                            valid_cookies = self._validate_cookies(cookies)
                                            if valid_cookies:
                                                login_detected = True
                                                if status_callback:
                                                    status_callback("🎯 第二阶段：开始检测行为验证弹窗...")
                                                    status_callback("💡 现在程序会检测是否出现行为验证，如果出现请手动完成")
                                                last_url = current_url
                                                continue
                                            else:
                                                if status_callback:
                                                    status_callback("⚠️ 获取到cookies但验证无效，继续等待...")
                                        else:
                                            if status_callback:
                                                status_callback("⚠️ URL变化但cookies为空，继续检测...")
                                    except Exception as e:
                                        if status_callback:
                                            status_callback(f"❌ 获取cookies失败: {str(e)}")
                                    
                                    last_url = current_url
                                else:
                                    # URL未变化时，增加基于Cookie的登录检测
                                    try:
                                        cookies = page.cookies()
                                        if cookies and len(cookies) > 0:
                                            valid_cookies = self._validate_cookies(cookies)
                                            # 当前URL不是登录/验证页且Cookie有效，也视为登录成功
                                            is_login_page = any(keyword in current_url.lower() for keyword in [
                                                'login', 'verify', 'captcha', 'challenge', 'security', 'robot', 'human',
                                                'verification', 'check', 'validate', 'confirm', 'auth'
                                            ])
                                            if valid_cookies and not is_login_page:
                                                login_detected = True
                                                if status_callback:
                                                    status_callback("✅ 检测到Cookie已更新且页面非登录/验证页，判定为登录成功")
                                                    status_callback("⏳ 等待页面稳定...")
                                                time.sleep(2.0)
                                                last_url = current_url
                                            else:
                                                # 仅提示进度，避免刷屏
                                                if check_count % 50 == 0:
                                                    elapsed_time = check_count * self.cookie_check_interval
                                                    if status_callback:
                                                        status_callback(f"⏰ 等待用户扫码登录... ({elapsed_time:.1f}秒)")
                                        else:
                                            if check_count % 50 == 0:
                                                elapsed_time = check_count * self.cookie_check_interval
                                                if status_callback:
                                                    status_callback(f"⏰ 等待用户扫码登录... ({elapsed_time:.1f}秒)")
                                    except Exception as e:
                                        # 获取Cookie失败不影响主流程，仅记录并继续
                                        if status_callback and check_count % 100 == 0:
                                            status_callback(f"⚠️ Cookie检测异常: {str(e)}")
                            
                            # 第二阶段：检测行为验证弹窗
                            else:
                                # 检测是否出现了行为验证弹窗
                                verification_detected = False
                                try:
                                    # 使用JavaScript检测验证弹窗
                                    verification_info = page.run_js("""
                                        // 检测常见的验证弹窗元素
                                        var hasVerification = false;
                                        var verificationTypes = [];
                                        
                                        // 检测极验验证
                                        if (document.querySelector('.geetest_holder, .geetest_widget, .geetest_panel')) {
                                            hasVerification = true;
                                            verificationTypes.push('极验验证');
                                        }
                                        
                                        // 检测滑动验证
                                        if (document.querySelector('[class*="slider"], [class*="slide"]')) {
                                            hasVerification = true;
                                            verificationTypes.push('滑动验证');
                                        }
                                        
                                        // 检测图片验证
                                        if (document.querySelector('[class*="captcha"], [class*="verify"]')) {
                                            hasVerification = true;
                                            verificationTypes.push('图片验证');
                                        }
                                        
                                        return {
                                            hasVerification: hasVerification,
                                            types: verificationTypes,
                                            url: window.location.href,
                                            title: document.title
                                        };
                                    """)
                                    
                                    if verification_info and verification_info.get('hasVerification'):
                                        verification_detected = True
                                        types = verification_info.get('types', [])
                                        if status_callback:
                                            status_callback(f"🚨 检测到行为验证弹窗: {', '.join(types)}")
                                            status_callback("👆 请手动完成验证，程序将等待验证完成...")
                                    
                                except Exception as e:
                                    if status_callback and check_count % 100 == 0:  # 每10秒报告一次错误
                                        status_callback(f"⚠️ 验证检测异常: {str(e)}")
                                
                                # 如果没有检测到验证弹窗，检查是否可以正常访问
                                if not verification_detected:
                                    # 检测页面是否正常（没有被重定向到验证页面）
                                    current_url_check = page.url
                                    is_normal_page = not any(keyword in current_url_check.lower() for keyword in [
                                        'verify', 'captcha', 'challenge', 'security', 'robot', 'human',
                                        'verification', 'check', 'validate', 'confirm'
                                    ])
                                    
                                    if is_normal_page:
                                        # 页面正常，没有验证弹窗，登录完成
                                        try:
                                            final_cookies = page.cookies()
                                            if final_cookies:
                                                detection_result["success"] = True
                                                detection_result["cookies"] = final_cookies
                                                login_success.set()
                                                if status_callback:
                                                    status_callback(f"✅ 登录完成！未检测到行为验证，获取到{len(final_cookies)}个有效cookies")
                                                return
                                        except Exception as e:
                                            if status_callback:
                                                status_callback(f"❌ 获取最终cookies失败: {str(e)}")
                                
                                # 显示检测进度
                                if check_count % 50 == 0:  # 每5秒显示一次
                                    elapsed_time = check_count * self.cookie_check_interval
                                    if status_callback:
                                        status_callback(f"🔍 第{check_count}次行为验证检测 ({elapsed_time:.1f}秒)")
                        
                        except Exception as e:
                            if status_callback:
                                status_callback(f"❌ 检测循环异常: {str(e)}")
                            time.sleep(1)
                
                except Exception as e:
                    if status_callback:
                        status_callback(f"❌ 检测线程异常: {str(e)}")
                    import traceback
                    if status_callback:
                        status_callback(f"详细错误: {traceback.format_exc()}")
            
            # 启动URL检测线程
            if status_callback:
                status_callback("🔄 启动URL检测线程...")
            
            detection_thread = threading.Thread(target=url_detection_thread, daemon=True)
            detection_thread.start()
            
            # 给线程一点时间启动并输出初始状态
            time.sleep(0.2)
            
            # 主线程等待检测结果或超时
            if status_callback:
                status_callback(f"⏰ 等待登录完成，最多等待{self.login_wait_timeout//60}分钟...")
            
            # 等待登录成功或超时
            if login_success.wait(timeout=self.login_wait_timeout):
                # 检查是否是用户关闭浏览器触发的
                if detection_result.get("user_closed", False):
                    if status_callback:
                        status_callback("🎯 智能查询时机：用户主动关闭浏览器，立即继续查询")
                        status_callback("✅ 使用现有Cookie继续查询，无需等待行为检测")
                    return True
                
                # 登录成功并获取到新cookies
                if detection_result["success"] and detection_result["cookies"]:
                    try:
                        # 保存cookies
                        self._update_cookies_to_config(detection_result["cookies"])
                        if status_callback:
                            status_callback("✅ Cookie已保存到配置文件")
                        
                        # 调试输出
                        if self.debug_output_enabled:
                            debug_info = {
                                "timestamp": time.time(),
                                "login_success": True,
                                "cookies_count": len(detection_result["cookies"]),
                                "cookies": detection_result["cookies"],
                                "url": page.url
                            }
                            
                            debug_file = os.path.join(
                                self.debug_output_dir,
                                f"login_success_cookies_{int(time.time())}.json"
                            )
                            
                            try:
                                import json
                                with open(debug_file, 'w', encoding='utf-8') as f:
                                    json.dump(debug_info, f, ensure_ascii=False, indent=2)
                                if status_callback:
                                    status_callback(f"调试信息已保存: {debug_file}")
                            except Exception as e:
                                if status_callback:
                                    status_callback(f"保存调试信息失败: {str(e)}")
                        
                        # 自动关闭浏览器
                        if status_callback:
                            status_callback("✅ 登录成功！正在验证Cookie有效性...")
                        
                        # 立即测试Cookie是否有效
                        test_success = self._test_cookie_validity(status_callback)
                        
                        if test_success:
                            if status_callback:
                                status_callback("🎉 Cookie验证成功！")
                                status_callback("🌙 浏览器将保持开启，稍后根据查询结果自动关闭")
                            # 直接在验证浏览器中访问目标URL并捕获页面内容，避免重复发起原始请求
                            try:
                                if status_callback:
                                    status_callback("📥 正在通过验证浏览器访问目标页面以捕获响应...")
                                page.get(url)
                                # 等待页面加载稳定
                                time.sleep(2.0)
                                captured_html = None
                                try:
                                    captured_html = page.html
                                except Exception:
                                    captured_html = None
                                if captured_html:
                                    self._verification_page_capture = {
                                        'url': url,
                                        'html': captured_html,
                                        'timestamp': time.time()
                                    }
                                    if status_callback:
                                        status_callback("📄 已从验证浏览器捕获目标页面响应内容")
                                else:
                                    if status_callback:
                                        status_callback("⚠️ 未能直接获取页面HTML，但Cookies已验证，可继续服务端请求")
                            except Exception as e:
                                if status_callback:
                                    status_callback(f"⚠️ 捕获浏览器页面内容失败: {str(e)}")
                            return True
                        else:
                            if status_callback:
                                status_callback("❌ Cookie验证失败，请重新登录")
                            return False
                    except Exception as e:
                        if status_callback:
                            status_callback(f"保存cookies失败: {str(e)}")
                        return False
                else:
                    if status_callback:
                        status_callback("❌ 检测结果异常")
                    return False
            else:
                # 超时
                if status_callback:
                    status_callback("❌ 登录等待超时，但浏览器将保持打开状态供您手动操作")
                    status_callback("💡 您可以在浏览器中手动完成登录，然后重新尝试查询")
                # 不自动关闭浏览器，让用户有机会手动完成登录
                return False
                
                # 改进的cookie检测逻辑：检测页面状态变化和cookie变化
                try:
                    current_html = page.html
                    current_url = page.url
                    current_title = page.title
                    
                    # 多维度检测页面状态变化
                    is_current_login_page = self._detect_login_required(current_html)
                    
                    # 检测页面URL变化（登录后通常URL会变化）
                    url_changed = current_url != initial_url
                    
                    # 检测页面标题变化
                    title_changed = current_title != initial_title
                    
                    # 检测页面内容长度变化（页面刷新后内容通常会变化）
                    current_html_length = len(current_html)
                    content_length_changed = abs(current_html_length - initial_html_length) > 1000  # 内容变化超过1000字符
                    
                    # 检测cookie数量变化（登录后cookie通常会增加）
                    cookie_count_changed = current_cookie_count != initial_cookie_count
                    
                    # 检测关键cookie变化
                    key_cookie_changed = len(current_key_cookies) != len(initial_key_cookies)
                    
                    # 检测是否有新的重要cookie
                    has_new_important_cookies = any(
                        key in current_key_cookies and key not in initial_key_cookies
                        for key in current_key_cookies.keys()
                    )
                    
                    # 多条件判断页面状态变化
                    state_changed = (
                        not is_current_login_page or  # 不再是登录页面
                        url_changed or               # URL发生变化
                        title_changed or             # 标题发生变化
                        content_length_changed or    # 页面内容长度显著变化
                        cookie_count_changed or      # Cookie数量变化
                        key_cookie_changed or        # 关键cookie数量变化
                        has_new_important_cookies    # 有新的重要cookie
                    )
                    
                    if state_changed:
                        if status_callback:
                            status_callback("🔄 检测到页面状态变化！")
                            status_callback(f"  - 登录页面状态: {is_current_login_page}")
                            status_callback(f"  - URL变化: {url_changed}")
                            if url_changed:
                                status_callback(f"    🔗 初始URL: {initial_url}")
                                status_callback(f"    🔗 当前URL: {current_url}")
                                status_callback("    ✅ URL变化表明可能已成功登录！")
                            status_callback(f"  - 标题变化: {title_changed}")
                            if title_changed:
                                status_callback(f"    初始: {initial_title}")
                                status_callback(f"    当前: {current_title}")
                            status_callback(f"  - 内容长度变化: {content_length_changed} ({initial_html_length} -> {current_html_length})")
                            status_callback(f"  - Cookie数量变化: {cookie_count_changed} ({initial_cookie_count} -> {current_cookie_count})")
                            status_callback(f"  - 关键Cookie变化: {key_cookie_changed}")
                            status_callback(f"  - 新重要Cookie: {has_new_important_cookies}")
                        
                        # 等待页面完全加载
                        page.wait(3)
                        
                        # 重新获取最新状态
                        current_html = page.html
                        current_cookies = page.cookies()
                        current_key_cookies, _ = get_key_cookies(current_cookies)
                        
                        # 检测cookie变化
                        if status_callback:
                            status_callback("🍪 检测cookie变化：")
                            status_callback(f"  - Cookie数量: {len(current_cookies)} (初始: {len(initial_cookies)})")
                            status_callback(f"  - 关键Cookie数量: {len(current_key_cookies)} (初始: {len(initial_key_cookies)})")
                            
                            # 显示新增或变化的关键cookie
                            for key, value in current_key_cookies.items():
                                if key not in initial_key_cookies:
                                    short_value = value[:20] + "..." if len(value) > 20 else value
                                    status_callback(f"  - 新增: {key} = {short_value}")
                                elif initial_key_cookies.get(key) != value:
                                    short_value = value[:20] + "..." if len(value) > 20 else value
                                    status_callback(f"  - 变化: {key} = {short_value}")
                        
                        # 保存新的cookie
                        self._update_cookies_to_config(current_cookies)
                        
                        if status_callback:
                            status_callback("✅ Cookie已更新并保存")
                        
                        # 保存调试信息
                        if self.debug_output_enabled:
                            debug_info = {
                                "timestamp": datetime.now().isoformat(),
                                "event": "login_success_cookie_detected",
                                "initial_cookies": len(initial_cookies),
                                "new_cookies": len(current_cookies),
                                "initial_key_cookies": initial_key_cookies,
                                "new_key_cookies": current_key_cookies,
                                "url": current_url
                            }
                            
                            debug_file = os.path.join(
                                self.debug_output_dir,
                                f"login_success_cookies_{int(time.time())}.json"
                            )
                            
                            try:
                                with open(debug_file, 'w', encoding='utf-8') as f:
                                    json.dump(debug_info, f, ensure_ascii=False, indent=2)
                                if status_callback:
                                    status_callback(f"调试信息已保存: {debug_file}")
                            except Exception as e:
                                if status_callback:
                                    status_callback(f"保存调试信息失败: {str(e)}")
                        
                        # 返回成功，但不自动关闭浏览器，避免打断行为验证
                        if status_callback:
                            status_callback("✅ 已保存Cookies，浏览器保持打开以便继续操作")
                        return True
                    
                except Exception as e:
                    if status_callback:
                        status_callback(f"检查页面状态时出错: {str(e)}")
                
            # 循环结束 - 超时或连接断开，但不自动关闭浏览器
            if status_callback:
                if wait_time >= self.login_wait_timeout:
                    status_callback("❌ 登录等待超时，但浏览器将保持打开状态供您手动操作")
                    status_callback("💡 您可以在浏览器中手动完成登录，然后重新尝试查询")
                else:
                    status_callback("❌ 浏览器连接断开，但浏览器窗口可能仍然打开")
            
            return False
            
        except ImportError:
            if status_callback:
                status_callback("DrissionPage未安装，请先安装: pip install DrissionPage")
            return False
        except Exception as e:
            if status_callback:
                status_callback(f"浏览器登录失败: {str(e)}")
                status_callback("💡 浏览器可能仍然打开，您可以手动完成登录后重新尝试")
            # 不自动关闭浏览器，让用户有机会手动操作
            return False
    
    def _update_cookies_to_config(self, cookies):
        """更新cookie到配置文件"""
        try:
            # 使用实例的配置文件路径，而不是硬编码的config.json
            config_path = self.config_path
            
            # 读取现有配置
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}
            
            # 确保tyc配置存在（注意：配置文件中使用的是tyc，不是tianyancha）
            if 'tyc' not in config:
                config['tyc'] = {}
            
            # 转换cookie格式为字符串（与配置文件格式一致）
            cookie_parts = []
            # 支持 dict、list[dict]、list[str]、RequestsCookieJar
            if isinstance(cookies, dict):
                for name, value in cookies.items():
                    if name and value:
                        cookie_parts.append(f"{name}={value}")
            elif hasattr(cookies, 'items') and not isinstance(cookies, list):
                # 兼容 RequestsCookieJar 或类似对象
                try:
                    for name, morsel in cookies.items():
                        value = getattr(morsel, 'value', None) or morsel
                        if name and value:
                            cookie_parts.append(f"{name}={value}")
                except Exception:
                    pass
            else:
                for cookie in cookies or []:
                    if isinstance(cookie, dict):
                        name = cookie.get('name', '')
                        value = cookie.get('value', '')
                        if name and value:
                            cookie_parts.append(f"{name}={value}")
                    else:
                        cookie_str = str(cookie)
                        if '=' in cookie_str:
                            cookie_parts.append(cookie_str)
            
            # 更新cookie字符串和时间戳
            cookie_string = '; '.join(cookie_parts)
            config['tyc']['cookie'] = cookie_string
            config['tyc']['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 使用统一配置管理器进行原子更新，避免覆盖其他模块写入
            try:
                from modules.config.config_manager import ConfigManager
                cm = ConfigManager()
                cm.update_section('tyc', {
                    'cookie': cookie_string
                })
            except Exception:
                # 回退到原始方式（不推荐），仅在管理器不可用时使用
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            
            # 更新当前实例的cookie
            self.tianyancha_cookies = {}
            for part in cookie_parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    self.tianyancha_cookies[key] = value
            # 同步到requests会话，确保新Cookie立即生效
            try:
                for name, value in self.tianyancha_cookies.items():
                    try:
                        self.session.cookies.set(name, value)
                    except Exception:
                        pass
            except Exception:
                pass
            
            print("Cookie已更新并保存到统一配置")
            
        except Exception as e:
            print(f"更新cookie失败: {e}")

    def _emit_status(self, status_callback, msg: str):
        if self.console_log_enabled:
            try:
                print(msg)
            except Exception:
                pass
        if status_callback:
            try:
                status_callback(msg)
            except Exception:
                pass

    def _build_full_url_for_log(self, url, params):
        try:
            from urllib.parse import urlencode
            return url if not params else (url + ("?" + urlencode(params)))
        except Exception:
            return url

    def _log_request_details(self, method, url, kwargs, status_callback, retry_info):
        if not self.show_request_details:
            return
        full_url_log = self._build_full_url_for_log(url, kwargs.get('params', None))
        self._emit_status(status_callback, f"➡️ 正在发送请求{retry_info}")
        self._emit_status(status_callback, f"🔗 URL: {full_url_log}")
        self._emit_status(status_callback, f"🔖 Method: {method.upper()}")
        try:
            headers = kwargs.get('headers', {}) or {}
            display_order = [
                'Host',
                'Connection',
                'Cache-Control',
                'Upgrade-Insecure-Requests',
                'X-AUTH-TOKEN',
                'User-Agent',
                'sec-ch-ua-platform',
                'sec-ch-ua',
                'sec-ch-ua-mobile',
                'Accept',
                'Sec-Fetch-Site',
                'Sec-Fetch-Mode',
                'Sec-Fetch-User',
                'Sec-Fetch-Dest',
                'Referer',
                'Accept-Encoding',
                'Accept-Language',
                'Content-Type',
                'version',
                'Origin'
            ]
            self._emit_status(status_callback, "🧾 请求头:")
            for key in display_order:
                if key in headers and headers.get(key):
                    self._emit_status(status_callback, f"  {key}: {headers.get(key)}")
        except Exception:
            pass
        try:
            cookies = kwargs.get('cookies', {}) or {}
            if cookies:
                cookie_lines = []
                for name, value in cookies.items():
                    cookie_lines.append(f"{name}={value}")
                self._emit_status(status_callback, "🍪 Cookies:")
                self._emit_status(status_callback, "  " + "; ".join(cookie_lines))
        except Exception:
            pass

    def _send_request(self, method, url, kwargs):
        if method.upper() == 'GET':
            return self.session.get(url, **kwargs)
        if method.upper() == 'POST':
            return self.session.post(url, **kwargs)
        raise ValueError(f"不支持的请求方法: {method}")

    def _should_defer_login_detection(self, defer_login_detection, force_login_detection):
        return defer_login_detection or (bool(self.tianyancha_cookies) and not force_login_detection)

    def _log_login_debug(self, status_callback):
        if self.console_log_enabled:
            print(f"🔧 [DEBUG] _make_request被调用: 有cookie={bool(self.tianyancha_cookies)}")
        if status_callback:
            status_callback(f"🔧 调试信息: 有cookie={bool(self.tianyancha_cookies)}")

    def _normalize_login_status_for_json(self, login_status, response, status_callback):
        if login_status is True and response is not None and response.text:
            rl = response.text.lower()
            json_ok = ('"state":"ok"' in rl) or ('"errorcode":0' in rl) or ('"errorcode": 0' in rl) or ('"errorcode":0' in rl)
            has_data = ('"data":' in rl) or ('"item":' in rl) or ('"itemtotal":' in rl)
            if json_ok and has_data:
                login_status = False
                if status_callback:
                    status_callback("✅ 检测到接口已返回有效数据，跳过登录流程")
        return login_status


    def _handle_no_browser_flow(self, login_status, url, status_callback, response):
        if login_status in (True, "captcha_required", "account_suspended", "account_restricted", "account_disabled"):
            if status_callback:
                status_callback("🚫 当前查询步骤禁止打开浏览器，跳过登录/验证流程")
            if self._verification_page_capture:
                captured = self._verification_page_capture
                cap_url = captured.get('url', '')
                if cap_url and (cap_url == url or ("/nsearch?key=" in cap_url and "/nsearch?key=" in url) or ("/search?key=" in cap_url and "/search?key=" in url)):
                    if status_callback:
                        status_callback("📩 使用已捕获的页面HTML返回")
                    self._verification_page_capture = None
                    return MockResponse(captured.get('html', ''))
            return response
        return None

    def _handle_captcha_required(self, response, url, status_callback, allow_open_browser, kwargs):
        if status_callback:
            status_callback("🔐 检测到验证码页面，需要手动验证")
            if allow_open_browser:
                status_callback("🌐 正在启动浏览器，请完成验证后继续...")
                status_callback("⚠️  浏览器将保持打开状态，请手动完成验证")
                status_callback("💡 验证完成后，请手动关闭浏览器")
            else:
                status_callback("🚫 策略禁止自动打开浏览器（仅在Cookie无效时打开），返回当前响应供上层处理")
        if not allow_open_browser:
            return "return", response

        self._verification_in_progress = True
        verification_url = url
        try:
            if isinstance(url, str) and 'capi.tianyancha.com' in url:
                params = kwargs.get('params') or {}
                company_id = params.get('id') or params.get('company_id')
                if company_id:
                    verification_url = f"https://www.tianyancha.com/company/{company_id}"
                    if status_callback:
                        status_callback(f"🌐 将打开企业详情页进行验证: {verification_url}")
        except Exception:
            verification_url = url

        captcha_success = self._handle_captcha_verification(
            verification_url, response.text, status_callback
        )

        if captcha_success:
            if status_callback:
                status_callback("✅ 验证完成，正在更新cookies并重新发送请求...")
            self._verification_in_progress = False
            for name, value in self.tianyancha_cookies.items():
                self.session.cookies.set(name, value)
            if 'cookies' in kwargs:
                kwargs['cookies'].update(self.tianyancha_cookies)
            else:
                kwargs['cookies'] = self.tianyancha_cookies.copy()
            try:
                self._update_cookies_to_config(self.tianyancha_cookies)
                if status_callback:
                    status_callback("📝 已将更新后的Cookies保存到配置文件")
            except Exception as e:
                if status_callback:
                    status_callback(f"⚠️ 保存Cookies到配置失败：{str(e)}")
            if self._verification_page_capture and self._verification_page_capture.get('url') == url:
                if status_callback:
                    status_callback("📩 使用验证浏览器中捕获的响应内容返回")
                captured = self._verification_page_capture
                self._verification_page_capture = None
                return "return", MockResponse(captured.get('html', ''))
            if status_callback:
                status_callback("🔄 使用新cookies重新发送请求...")
            return "continue", None

        if status_callback:
            status_callback("⌛ 验证尚未完成或Cookies未生效，浏览器保持开启，请在浏览器完成验证后重试")
        if self._verification_page_capture:
            captured = self._verification_page_capture
            cap_url = captured.get('url', '')
            if cap_url and (cap_url == url or ("/nsearch?key=" in cap_url and "/nsearch?key=" in url) or ("/search?key=" in cap_url and "/search?key=" in url)):
                if status_callback:
                    status_callback("📩 验证未完成但已捕获页面HTML，直接返回解析")
                self._verification_page_capture = None
                return "return", MockResponse(captured.get('html', ''))
        return "return", None

    def _handle_account_suspended(self, response, url, status_callback, login_attempts):
        login_attempts += 1
        if login_attempts > self.max_login_attempts:
            if status_callback:
                status_callback(f"❌ 已达到最大登录尝试次数 ({self.max_login_attempts})，停止尝试")
            return "return", None, login_attempts
        if status_callback:
            status_callback(f"🚨 检测到账号被暂停，清除cookie并启动无痕浏览器重新登录... (尝试 {login_attempts}/{self.max_login_attempts})")
        self._clear_cookies()
        if status_callback:
            status_callback("🧹 已清除现有cookies")
            status_callback("🌐 正在启动无痕浏览器进行重新登录...")
        self._handle_login_required(url, response.text, status_callback, incognito=True, attempt=login_attempts)
        return "return", response, login_attempts

    def _handle_account_restricted_or_disabled(self, response, url, status_callback, method, kwargs, login_status):
        if login_status == "account_restricted":
            if status_callback:
                status_callback("⚠️  检测到账号已登录但访问受限")
                status_callback("🔄 当前账号查询频率过高，需要更换账户")
        else:
            if status_callback:
                status_callback("⚠️  检测到账号被停用")
                status_callback("🔄 当前账号已被停用，需要更换账户")

        max_account_switch_attempts = 3
        account_switch_attempt = 1

        while account_switch_attempt <= max_account_switch_attempts:
            if status_callback:
                status_callback(f"🔄 尝试更换账户 (第 {account_switch_attempt}/{max_account_switch_attempts} 次)")
                status_callback("🧹 正在清除当前账号的cookies...")
            self._clear_cookies()
            if status_callback:
                status_callback("✅ 已清除当前账号cookies")
                status_callback("🌐 正在启动无痕浏览器，请使用其他账户登录...")
            login_success = self._handle_login_required(url, response.text, status_callback, incognito=True, attempt=account_switch_attempt)

            if login_success:
                if status_callback:
                    status_callback("✅ 账户更换成功，验证新账户状态...")
                for name, value in self.tianyancha_cookies.items():
                    self.session.cookies.set(name, value)
                if 'cookies' in kwargs:
                    kwargs['cookies'].update(self.tianyancha_cookies)
                else:
                    kwargs['cookies'] = self.tianyancha_cookies
                if status_callback:
                    status_callback("⏳ 等待服务器识别新的登录状态...")
                time.sleep(3)
                try:
                    test_response = self.session.request(method, url, **kwargs)
                    test_login_status = self._detect_login_required(test_response.text)

                    if test_login_status == "account_restricted" or test_login_status == "account_disabled":
                        if status_callback:
                            if test_login_status == "account_restricted":
                                status_callback("❌ 新账户也访问受限，尝试更换其他账户...")
                            else:
                                status_callback("❌ 新账户也被停用，尝试更换其他账户...")
                        account_switch_attempt += 1
                        continue
                    if test_login_status is True:
                        if status_callback:
                            status_callback("❌ 新账户需要重新登录，尝试更换其他账户...")
                        account_switch_attempt += 1
                        continue
                    if status_callback:
                        status_callback("✅ 新账户状态正常，继续查询...")
                    return "return", test_response

                except Exception as e:
                    if status_callback:
                        status_callback(f"❌ 验证新账户状态时出错: {str(e)}")
                    account_switch_attempt += 1
                    continue
            else:
                if status_callback:
                    status_callback(f"❌ 第 {account_switch_attempt} 次账户更换失败")
                account_switch_attempt += 1

        if status_callback:
            status_callback("❌ 已尝试多次更换账户，均未成功，无法继续查询")
        return "return", None

    def _handle_login_required_flow(self, response, url, status_callback, method, kwargs, login_attempts, request_info):
        login_attempts += 1
        if login_attempts > self.max_login_attempts:
            if status_callback:
                status_callback(f"❌ 已达到最大登录尝试次数 ({self.max_login_attempts})，停止尝试")
            return "return", None, login_attempts
        if status_callback:
            status_callback(f"🔑 检测到需要登录，启动半自动登录流程... (尝试 {login_attempts}/{self.max_login_attempts})")
        login_success = self._handle_login_required(url, response.text, status_callback, attempt=login_attempts)

        if login_success:
            if status_callback:
                status_callback("登录成功，准备重新请求...")
            for name, value in self.tianyancha_cookies.items():
                self.session.cookies.set(name, value)
            if 'cookies' in kwargs:
                kwargs['cookies'].update(self.tianyancha_cookies)
            else:
                kwargs['cookies'] = self.tianyancha_cookies
            if status_callback:
                status_callback("等待服务器识别新的登录状态...")
            time.sleep(3)
            try:
                if status_callback:
                    status_callback("访问主页激活登录状态...")
                home_response = self.session.get("https://www.tianyancha.com/", **kwargs)
                if home_response.status_code == 200:
                    if status_callback:
                        status_callback("主页访问成功，登录状态已激活")
                else:
                    if status_callback:
                        status_callback(f"主页访问状态码: {home_response.status_code}")
            except Exception as e:
                if status_callback:
                    status_callback(f"访问主页失败: {str(e)}")

            max_retries = 3
            for retry in range(max_retries):
                try:
                    if status_callback:
                        status_callback(f"重新发送请求 (尝试 {retry + 1}/{max_retries})...")

                    if method.upper() == 'GET':
                        response = self.session.get(url, **kwargs)
                    elif method.upper() == 'POST':
                        response = self.session.post(url, **kwargs)

                    request_info["after_login"] = True
                    request_info["retry_count"] = retry + 1
                    self._save_debug_response(url, response, request_info)

                    if response and response.text:
                        login_check = self._detect_login_required(response.text)
                        if login_check:
                            if status_callback:
                                status_callback(f"第{retry + 1}次请求仍需登录: {login_check}")
                            if retry < max_retries - 1:
                                if status_callback:
                                    status_callback("等待后重试...")
                                time.sleep(2)
                                continue
                        else:
                            if status_callback:
                                status_callback("重新请求成功，无需登录")
                            break
                    else:
                        if status_callback:
                            status_callback("响应为空，重试...")
                        if retry < max_retries - 1:
                            time.sleep(2)
                            continue

                except Exception as e:
                    if status_callback:
                        status_callback(f"第{retry + 1}次请求失败: {str(e)}")
                    if retry < max_retries - 1:
                        time.sleep(2)
                        continue
                    return "return", None, login_attempts
        else:
            if status_callback:
                status_callback("登录失败或超时，返回原始响应")
        return "return", response, login_attempts

    def _process_login_flow(
        self,
        response,
        status_callback,
        request_info,
        url,
        method,
        kwargs,
        allow_open_browser,
        defer_login_detection,
        force_login_detection,
        login_attempts
    ):
        if response is None or not response.text:
            return "fallthrough", response, login_attempts

        self._log_login_debug(status_callback)
        auto_defer = self._should_defer_login_detection(defer_login_detection, force_login_detection)
        if auto_defer:
            if status_callback:
                status_callback("🧪 数据优先：先尝试解析数据，必要时再做登录/验证码检测")
            self._save_debug_response(url, response, request_info)
            return "return", response, login_attempts

        if self.console_log_enabled:
            print("🔍 [DEBUG] 开始检测登录状态...")
        if status_callback:
            status_callback("🔍 开始检测登录状态...")
        login_status = self._detect_login_required(response.text)
        print(f"🔍 [DEBUG] 登录状态检测结果: {login_status}")
        print(f"🔍 [DEBUG] 响应内容前500字符: {response.text[:500]}")
        if status_callback:
            status_callback(f"🔍 登录状态检测结果: {login_status}")

        login_status = self._normalize_login_status_for_json(login_status, response, status_callback)

        if not allow_open_browser:
            handled_response = self._handle_no_browser_flow(login_status, url, status_callback, response)
            if handled_response is not None:
                return "return", handled_response, login_attempts

        self._save_debug_response(url, response, request_info)

        if login_status == "captcha_required":
            action, value = self._handle_captcha_required(response, url, status_callback, allow_open_browser, kwargs)
            return action, value, login_attempts
        if login_status == "account_suspended":
            return self._handle_account_suspended(response, url, status_callback, login_attempts)
        if login_status == "account_restricted" or login_status == "account_disabled":
            action, value = self._handle_account_restricted_or_disabled(response, url, status_callback, method, kwargs, login_status)
            return action, value, login_attempts
        if login_status:
            return self._handle_login_required_flow(response, url, status_callback, method, kwargs, login_attempts, request_info)

        return "fallthrough", response, login_attempts

    # pylint: disable=too-many-branches, too-many-statements, too-many-locals, too-many-return-statements, too-complex
    @no_type_check
    def _make_request(self, method, url, status_callback=None, allow_open_browser=True, defer_login_detection=False, force_login_detection=False, **kwargs):  # noqa: C901, PLR0912, PLR0913, PLR0915
        """统一的请求方法，包含反爬措施和重试机制 - 改进版本"""
        # 设置请求超时，防止请求卡死
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 30  # 增加超时时间到30秒
        
        # 登录尝试计数器
        login_attempts = 0
        
        # 准备请求信息用于调试
        request_info = {
            "method": method.upper(),
            "headers": kwargs.get('headers', {}),
            "cookies": kwargs.get('cookies', {}),
            "timeout": kwargs.get('timeout', 30)
        }
        
        # 重试机制
        for attempt in range(self.max_retries):
            try:
                # 反爬延时（每次重试都要延时）
                self._anti_crawl_delay(status_callback=status_callback)
                
                # 轮换User-Agent（增加随机性）
                self._rotate_user_agent()
                
                retry_info = f" (重试 {attempt + 1}/{self.max_retries})" if attempt > 0 else ""
                self._log_request_details(method, url, kwargs, status_callback, retry_info)
                
                # 发送请求
                response = None
                response = self._send_request(method, url, kwargs)
                
                if status_callback:
                    status_callback(f"请求成功，状态码: {response.status_code}")
                
                decision, value, login_attempts = self._process_login_flow(
                    response,
                    status_callback,
                    request_info,
                    url,
                    method,
                    kwargs,
                    allow_open_browser,
                    defer_login_detection,
                    force_login_detection,
                    login_attempts
                )
                if decision == "continue":
                    continue
                if decision == "return":
                    return value

                return response
                
            except requests.exceptions.Timeout as e:
                if status_callback:
                    status_callback(f"请求超时 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    # 最后一次重试失败
                    request_info["timeout_error"] = str(e)
                    self._save_debug_response(url, None, request_info)
                    return None
                # 等待后重试
                time.sleep(self.retry_delay)
                continue
                
            except requests.exceptions.ConnectionError as e:
                if status_callback:
                    status_callback(f"网络连接错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    # 最后一次重试失败
                    request_info["connection_error"] = str(e)
                    self._save_debug_response(url, None, request_info)
                    return None
                # 等待后重试
                time.sleep(self.retry_delay)
                continue
                
            except requests.exceptions.RequestException as e:
                if status_callback:
                    status_callback(f"请求异常 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    # 最后一次重试失败
                    request_info["request_error"] = str(e)
                    self._save_debug_response(url, None, request_info)
                    return None
                # 等待后重试
                time.sleep(self.retry_delay)
                continue
                
            except Exception as e:
                if status_callback:
                    status_callback(f"未知错误 (尝试 {attempt + 1}/{self.max_retries}): {str(e)}")
                if attempt == self.max_retries - 1:
                    # 最后一次重试失败
                    request_info["general_error"] = str(e)
                    self._save_debug_response(url, None, request_info)
                    return None
                # 等待后重试
                time.sleep(self.retry_delay)
                continue
        
        # 如果所有重试都失败了
        if status_callback:
            status_callback(f"所有重试都失败，放弃请求")
        return None
    
    def _parse_html_fallback(self, html_content: str, company_name: str, update_status) -> Dict:
        """
        备用HTML解析方法，用于无cookie模式下的页面解析
        """
        try:
            update_status("🔄 使用备用HTML解析方法")
            
            # 检查是否有BeautifulSoup库
            if not HAS_BS4:
                update_status("⚠️ 缺少BeautifulSoup库，无法使用备用解析方法")
                return {
                    'success': False,
                    'error': '缺少BeautifulSoup库，无法解析HTML',
                    'query': company_name
                }
            
            soup = BeautifulSoup(html_content, 'html.parser')
            companies = []
            
            # 方法1：查找企业卡片或列表项
            def has_company_class(class_attr):
                if not class_attr:
                    return False
                class_str = ' '.join(class_attr) if isinstance(class_attr, list) else str(class_attr)
                return any(keyword in class_str.lower() for keyword in ['company', 'enterprise', 'item', 'card', 'result'])
            
            company_cards = soup.find_all(['div', 'li'], class_=has_company_class)
            
            if company_cards:
                update_status(f"🔍 找到 {len(company_cards)} 个可能的企业元素")
                
                for card in company_cards[:10]:  # 限制处理前10个
                    # 提取企业名称
                    def contains_company_name(text):
                        return text and company_name in str(text)
                    
                    name_elem = None
                    try:
                        # 使用getattr来避免类型检查错误
                        find_method = getattr(card, 'find', None)
                        if find_method:
                            name_elem = find_method(['a', 'span', 'h1', 'h2', 'h3'], string=contains_company_name)
                    except Exception:
                        pass
                    
                    if not name_elem:
                        # 尝试查找包含链接的元素
                        def has_company_href(href_attr):
                            return href_attr and 'company' in str(href_attr)
                        
                        try:
                            find_method = getattr(card, 'find', None)
                            if find_method:
                                name_elem = find_method('a', href=has_company_href)
                        except Exception:
                            pass
                    
                    if name_elem:
                        company_info = {
                            'id': None,  # 无cookie模式下可能无法获取ID
                            'name': self._clean_html_tags(name_elem.get_text(strip=True)),
                            'legalPersonName': '',
                            'regCapital': '',
                            'creditCode': '',
                            'regLocation': '',
                            'phoneList': [],
                            'emailList': [],
                            'websites': '',
                            'categoryNameLv1': '',
                            'categoryNameLv2': '',
                            'categoryNameLv3': '',
                            'categoryNameLv4': ''
                        }
                        
                        # 尝试提取更多信息
                        text_content = card.get_text()
                        
                        # 提取统一社会信用代码
                        credit_match = re.search(r'[0-9A-Z]{18}', text_content)
                        if credit_match:
                            company_info['creditCode'] = credit_match.group()
                        
                        # 提取注册资本
                        capital_match = re.search(r'注册资本[：:]\s*([^\s]+)', text_content)
                        if capital_match:
                            company_info['regCapital'] = capital_match.group(1)
                        
                        # 提取法定代表人
                        legal_match = re.search(r'法定代表人[：:]\s*([^\s]+)', text_content)
                        if legal_match:
                            company_info['legalPersonName'] = legal_match.group(1)
                        
                        companies.append(company_info)
            
            # 方法2：如果方法1没找到，尝试查找包含企业名称的文本
            if not companies:
                update_status("🔍 尝试文本匹配方法")
                
                def contains_company_name_text(text):
                    return text and company_name in str(text)
                
                text_elements = soup.find_all(string=contains_company_name_text)
                
                if text_elements:
                    # 创建一个基本的企业信息
                    company_info = {
                        'id': None,
                        'name': company_name,
                        'legalPersonName': '',
                        'regCapital': '',
                        'creditCode': '',
                        'regLocation': '',
                        'phoneList': [],
                        'emailList': [],
                        'websites': '',
                        'categoryNameLv1': '',
                        'categoryNameLv2': '',
                        'categoryNameLv3': '',
                        'categoryNameLv4': ''
                    }
                    companies.append(company_info)
                    update_status("🔍 使用基本匹配创建企业信息")
            
            if companies:
                update_status(f"✅ 备用解析方法找到 {len(companies)} 家企业")
                return {
                    'success': True,
                    'companies': companies,
                    'query': company_name,
                    'note': '使用备用解析方法，信息可能不完整'
                }
            else:
                update_status("❌ 备用解析方法未找到企业信息")
                return {
                    'success': False,
                    'error': '备用解析方法未找到企业信息',
                    'query': company_name
                }
                
        except Exception as e:
            update_status(f"❌ 备用解析方法出错: {str(e)}")
            return {
                'success': False,
                'error': f'备用解析方法出错: {str(e)}',
                'query': company_name
            }

    def search_company(self, company_name: str, status_callback=None) -> Dict:
        """
        第一步：搜索企业基本信息
        """
        # 关闭请求包详细输出（终端与UI）
        quiet_requests = True
        quiet_prefixes = (
            "➡️", "🔗", "🔖", "🧾", "🍪",
            "  Host:", "  Connection:", "  X-AUTH-TOKEN:", "  User-Agent:",
            "  sec-ch-ua-platform:", "  sec-ch-ua:", "  sec-ch-ua-mobile:",
            "  Accept:", "  Content-Type:", "  version:", "  Origin:",
            "  Sec-Fetch-Site:", "  Sec-Fetch-Mode:", "  Sec-Fetch-Dest:",
            "  Referer:", "  Accept-Encoding:", "  Accept-Language:"
        )
        def update_status(message):
            try:
                if quiet_requests and isinstance(message, str):
                    for p in quiet_prefixes:
                        if message.startswith(p):
                            return
            except Exception:
                pass
            print(message)
            if status_callback:
                try:
                    status_callback(message)
                except Exception:
                    pass
        
        update_status(f"正在搜索企业: {company_name}")
        update_status("🧪 按数据可得性判定：先尝试拿数据，暂不自动开浏览器")
        
        # 用于标记是否已尝试过浏览器验证（避免重复打开）
        verification_attempted_for_no_data = False
        
        # URL编码企业名称
        encoded_name = urllib.parse.quote(company_name)
        url = f"https://www.tianyancha.com/nsearch?key={encoded_name}"
        
        headers = {
            'Host': 'www.tianyancha.com',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'Upgrade-Insecure-Requests': '1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'Referer': f'https://www.tianyancha.com/nsearch?key={encoded_name}',
            'X-AUTH-TOKEN': (self.tianyancha_cookies.get('auth_token') if hasattr(self, 'tianyancha_cookies') and self.tianyancha_cookies else '')
        }
        
        try:
            try:
                # 首次搜索请求禁止自动打开浏览器；仅在确认拿不到数据后再触发验证
                response = self._make_request(
                    'GET',
                    url,
                    headers=headers,
                    cookies=self.tianyancha_cookies,
                    status_callback=status_callback,
                    allow_open_browser=False,
                    defer_login_detection=True
                )
                if response:
                    response.raise_for_status()
                else:
                    update_status("请求返回为空，尝试触发人工验证以恢复Cookie…")
                    # 一次性触发验证，避免循环
                    search_captcha_attempted = False
                    if not search_captcha_attempted:
                        try:
                            self._verification_in_progress = True
                            captcha_ok = self._handle_captcha_verification(
                                url,
                                None,
                                status_callback
                            )
                        except Exception as e:
                            captcha_ok = False
                            update_status(f"❌ 验证流程异常: {str(e)}")
                        finally:
                            self._verification_in_progress = False
                        search_captcha_attempted = True

                        # 若验证浏览器已捕获到页面HTML，使用其作为解析来源
                        if captcha_ok and self._verification_page_capture:
                            captured = self._verification_page_capture
                            cap_html = captured.get('html', '')
                            if cap_html:
                                html_content = cap_html
                                update_status("📄 使用验证浏览器捕获的页面HTML进行解析")
                                # 清理一次以避免后续误用旧内容
                                self._verification_page_capture = None
                                # 跳转到后续解析逻辑
                                pass
                            else:
                                # 验证成功但未捕获HTML，重试一次请求
                                response = self._make_request(
                                    'GET',
                                    url,
                                    headers=headers,
                                    cookies=self.tianyancha_cookies,
                                    status_callback=status_callback,
                                    allow_open_browser=False,
                                    defer_login_detection=True
                                )
                                if not response:
                                    # 兜底：直接从已打开的浏览器读取当前页面HTML
                                    page_ref = getattr(self, '_verification_page_ref', None)
                                    if page_ref is not None:
                                        try:
                                            html_content = page_ref.html
                                            update_status("📄 使用浏览器当前页HTML进行解析（请求为空兜底）")
                                        except Exception as e:
                                            update_status(f"⚠️ 读取浏览器页面失败: {str(e)}")
                                    else:
                                        return {
                                            'success': False,
                                            'error': '验证未完成或请求返回为空',
                                            'query': company_name,
                                            'companies': []
                                        }
                        else:
                            if self._verification_user_closed:
                                update_status("🚪 检测到手动关闭浏览器，终止本次查询")
                                return {
                                    'success': False,
                                    'error': '用户关闭浏览器，已终止查询',
                                    'query': company_name,
                                    'companies': []
                                }
                            return {
                                'success': False,
                                'error': '验证未完成或请求返回为空',
                                'query': company_name,
                                'companies': []
                            }
            except requests.exceptions.RequestException as e:
                update_status(f"请求失败: {str(e)}，正在重试...")
                # 网络异常时重试一次
                time.sleep(2)
                response = self._make_request(
                    'GET',
                    url,
                    headers=headers,
                    cookies=self.tianyancha_cookies,
                    status_callback=status_callback,
                    allow_open_browser=False,
                    defer_login_detection=True
                )
                if response:
                    response.raise_for_status()
                else:
                    update_status("重试请求返回为空，尝试触发人工验证以恢复Cookie…")
                    try:
                        self._verification_in_progress = True
                        captcha_ok = self._handle_captcha_verification(
                            url,
                            None,
                            status_callback
                        )
                    except Exception as e2:
                        captcha_ok = False
                        update_status(f"❌ 验证流程异常: {str(e2)}")
                    finally:
                        self._verification_in_progress = False
                    if captcha_ok:
                        # 验证后再次请求
                        response = self._make_request(
                            'GET',
                            url,
                            headers=headers,
                            cookies=self.tianyancha_cookies,
                            status_callback=status_callback,
                            allow_open_browser=False,
                            defer_login_detection=True
                        )
                        if response:
                            response.raise_for_status()
                        else:
                            return {
                                'success': False,
                                'error': '验证未完成或重试请求返回为空',
                                'query': company_name,
                                'companies': []
                            }
                    else:
                        if self._verification_user_closed:
                            update_status("🚪 检测到手动关闭浏览器，终止本次查询")
                            return {
                                'success': False,
                                'error': '用户关闭浏览器，已终止查询',
                                'query': company_name,
                                'companies': []
                            }
                        return {
                            'success': False,
                            'error': '验证未完成或重试请求返回为空',
                            'query': company_name,
                            'companies': []
                        }
            
            # 从HTML中提取JSON数据
            if response and hasattr(response, 'text'):
                html_content = response.text
            else:
                # 如果前面通过验证浏览器已捕获到页面HTML，此处直接使用
                if 'html_content' in locals() and html_content:
                    pass
                else:
                    update_status("响应对象无text属性")
                    return {
                        'success': False,
                        'error': '响应对象无text属性',
                        'query': company_name
                    }
            
            # 调试：输出页面基本信息
            update_status(f"🔍 页面长度: {len(html_content)} 字符")
            
            # 检查页面是否包含常见的反爬或登录提示
            if "请完成安全验证" in html_content or "安全验证" in html_content:
                update_status("⚠️ 检测到安全验证页面")
            if "登录" in html_content and "密码" in html_content:
                update_status("⚠️ 检测到登录页面")
            if "验证码" in html_content:
                update_status("⚠️ 检测到验证码页面")
            
            # 查找包含企业数据的JSON（在__NEXT_DATA__脚本标签中）
            pattern = r'<script id="__NEXT_DATA__" type="application/json">\s*({.*?})\s*</script>'
            match = re.search(pattern, html_content, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                try:
                    next_data = json.loads(json_str)
                    update_status("📄 检测到 __NEXT_DATA__ JSON 标签")
                    
                    # 确保next_data是字典类型
                    if not isinstance(next_data, dict):
                        update_status(f"解析的JSON数据类型错误: {type(next_data).__name__}")
                        return {
                            'success': False,
                            'error': f'解析的JSON数据类型错误: {type(next_data).__name__}',
                            'query': company_name
                        }
                    
                    # 导航到企业列表数据
                    company_list = None
                    if ('props' in next_data and 
                        'pageProps' in next_data['props'] and 
                        'dehydratedState' in next_data['props']['pageProps'] and
                        'queries' in next_data['props']['pageProps']['dehydratedState']):
                        
                        for query in next_data['props']['pageProps']['dehydratedState']['queries']:
                            if ('state' in query and 
                                'data' in query['state'] and 
                                'data' in query['state']['data'] and
                                'companyList' in query['state']['data']['data']):
                                company_list = query['state']['data']['data']['companyList']
                                break
                    
                    if company_list:
                        update_status("✅ 检测到公司列表数据，准备构建结果")
                        companies = []
                        for company in company_list:
                            # 确保company是字典类型
                            if not isinstance(company, dict):
                                update_status(f"公司数据类型错误: {type(company).__name__}，跳过此条记录")
                                continue
                            
                            category_levels = self._extract_category_levels(company)
                            print(f"DEBUG: Extracted category levels: {category_levels}") # 添加调试信息
                            company_info = {
                                'id': company.get('id'),
                                'name': self._clean_html_tags(company.get('name', '')),
                                'legalPersonName': company.get('legalPersonName', ''),
                                'regCapital': company.get('regCapital', ''),
                                'creditCode': company.get('creditCode', ''),
                                'regLocation': company.get('regLocation', ''),
                                'phoneList': company.get('phoneList', []),
                                'emailList': company.get('emailList', []),
                                'websites': company.get('websites', ''),
                                **category_levels
                            }
                            companies.append(company_info)
                        
                        update_status(f"找到 {len(companies)} 家企业")
                        # 搜索获取到数据后，持久化当前cookies
                        try:
                            current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                            if current_cookies:
                                self._update_cookies_to_config(current_cookies)
                                update_status(f"🍪 已保存天眼查cookies（搜索成功后持久化），数量: {len(current_cookies)}")
                        except Exception as e:
                            update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")

                        # 成功获取企业数据后，自动关闭验证用浏览器（若存在挂起关闭回调）
                        close_cb = getattr(self, '_pending_browser_close', None)
                        if callable(close_cb):
                            try:
                                self._verification_auto_close_requested = True
                                close_cb()
                                update_status("🧹 已自动关闭验证用浏览器（数据获取成功后）")
                            except Exception as e:
                                self._verification_auto_close_requested = False
                                update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                            finally:
                                self._pending_browser_close = None
                                self._verification_page_ref = None
                        return {
                            'success': True,
                            'companies': companies,
                            'query': company_name
                        }
                    else:
                        # 未找到企业信息，可能是Cookie失效或被风控，尝试打开浏览器验证
                        if not verification_attempted_for_no_data:
                            update_status("⚠️ 未找到企业信息，可能是Cookie失效或需要验证，尝试打开浏览器...")
                            verification_attempted_for_no_data = True
                            try:
                                self._verification_in_progress = True
                                captcha_ok = self._handle_captcha_verification(
                                    url,
                                    html_content,
                                    status_callback
                                )
                                if captcha_ok and self._verification_page_capture:
                                    captured = self._verification_page_capture
                                    cap_html = captured.get('html', '')
                                    if cap_html:
                                        update_status("📄 使用验证浏览器捕获的页面HTML重新解析")
                                        # 重新解析验证后的页面
                                        html_content = cap_html
                                        self._verification_page_capture = None
                                        # 重新尝试解析
                                        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">\s*({.*?})\s*</script>', html_content, re.DOTALL)
                                        if match:
                                            try:
                                                next_data = json.loads(match.group(1))
                                            except json.JSONDecodeError:
                                                next_data = None
                                            
                                            if next_data:
                                                company_list = None
                                                # 尝试从多个可能的路径获取公司列表
                                                if 'props' in next_data and 'pageProps' in next_data['props']:
                                                    page_props = next_data['props']['pageProps']
                                                    if 'query' in page_props and 'state' in page_props['query']:
                                                        if 'data' in page_props['query']['state'] and 'data' in page_props['query']['state']['data']:
                                                            company_list = page_props['query']['state']['data']['data'].get('companyList')
                                                
                                                if company_list and len(company_list) > 0:
                                                    companies = []
                                                    for company in company_list:
                                                        if not isinstance(company, dict):
                                                            continue
                                                        category_levels = self._extract_category_levels(company)
                                                        company_info = {
                                                            'id': company.get('id'),
                                                            'name': self._clean_html_tags(company.get('name', '')),
                                                            'legalPersonName': company.get('legalPersonName', ''),
                                                            'regCapital': company.get('regCapital', ''),
                                                            'creditCode': company.get('creditCode', ''),
                                                            'regLocation': company.get('regLocation', ''),
                                                            'phoneList': company.get('phoneList', []),
                                                            'emailList': company.get('emailList', []),
                                                            'websites': company.get('websites', ''),
                                                            **category_levels
                                                        }
                                                        companies.append(company_info)
                                                    
                                                    if companies:
                                                        update_status(f"✅ 验证后找到 {len(companies)} 家企业")
                                                        # 保存cookies
                                                        try:
                                                            current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                                                            if current_cookies:
                                                                self._update_cookies_to_config(current_cookies)
                                                                update_status(f"🍪 已保存天眼查cookies（验证成功后持久化）")
                                                        except Exception as e:
                                                            update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")
                                                        
                                                        # 关闭验证浏览器
                                                        close_cb = getattr(self, '_pending_browser_close', None)
                                                        if callable(close_cb):
                                                            try:
                                                                self._verification_auto_close_requested = True
                                                                close_cb()
                                                                update_status("🧹 已自动关闭验证用浏览器")
                                                            except Exception:
                                                                self._verification_auto_close_requested = False
                                                                pass
                                                            finally:
                                                                self._pending_browser_close = None
                                                                self._verification_page_ref = None
                                                        
                                                        return {
                                                            'success': True,
                                                            'companies': companies,
                                                            'query': company_name
                                                        }
                            except Exception as e:
                                update_status(f"❌ 验证流程异常: {str(e)}")
                            finally:
                                self._verification_in_progress = False
                            
                            # 如果第一次解析失败，但浏览器仍在运行，则持续检测浏览器页面
                            page_ref = getattr(self, '_verification_page_ref', None)
                            if page_ref is not None:
                                update_status("🔁 浏览器内重复提取页面数据，直到解析成功（未找到企业信息时的持续检测）")
                                max_retry = 15
                                for i in range(max_retry):
                                    try:
                                        # 重新抓取当前页面HTML
                                        latest_html = page_ref.html
                                        update_status(f"🔁 第{i+1}/{max_retry}次抓取，页面长度: {len(latest_html)}")
                                        
                                        # 尝试主解析流程：提取 __NEXT_DATA__
                                        match2 = re.search(r'<script id="__NEXT_DATA__" type="application/json">\s*({.*?})\s*</script>', latest_html, re.DOTALL)
                                        if match2:
                                            try:
                                                next_data2 = json.loads(match2.group(1))
                                                company_list2 = None
                                                # 尝试从多个可能的路径获取公司列表
                                                if 'props' in next_data2 and 'pageProps' in next_data2['props']:
                                                    page_props2 = next_data2['props']['pageProps']
                                                    # 路径1: pageProps.query.state.data.data.companyList
                                                    if 'query' in page_props2 and 'state' in page_props2['query']:
                                                        if 'data' in page_props2['query']['state'] and 'data' in page_props2['query']['state']['data']:
                                                            company_list2 = page_props2['query']['state']['data']['data'].get('companyList')
                                                    # 路径2: dehydratedState.queries[].state.data.data.companyList
                                                    if not company_list2 and ('dehydratedState' in page_props2 and
                                                                              'queries' in page_props2['dehydratedState']):
                                                        for query in page_props2['dehydratedState']['queries']:
                                                            if ('state' in query and 
                                                                'data' in query['state'] and 
                                                                'data' in query['state']['data'] and
                                                                'companyList' in query['state']['data']['data']):
                                                                company_list2 = query['state']['data']['data']['companyList']
                                                                break
                                                
                                                if company_list2 and len(company_list2) > 0:
                                                    companies2 = []
                                                    for company in company_list2:
                                                        if not isinstance(company, dict):
                                                            continue
                                                        category_levels = self._extract_category_levels(company)
                                                        companies2.append({
                                                            'id': company.get('id'),
                                                            'name': self._clean_html_tags(company.get('name', '')),
                                                            'legalPersonName': company.get('legalPersonName', ''),
                                                            'regCapital': company.get('regCapital', ''),
                                                            'creditCode': company.get('creditCode', ''),
                                                            'regLocation': company.get('regLocation', ''),
                                                            'phoneList': company.get('phoneList', []),
                                                            'emailList': company.get('emailList', []),
                                                            'websites': company.get('websites', ''),
                                                            **category_levels
                                                        })
                                                    
                                                    if companies2:
                                                        update_status(f"✅ 持续检测后成功解析到 {len(companies2)} 家企业")
                                                        # 保存cookies（从浏览器获取）
                                                        try:
                                                            browser_cookies = page_ref.cookies()
                                                            if browser_cookies:
                                                                conv = []
                                                                for c in browser_cookies:
                                                                    name = c.get('name') if isinstance(c, dict) else getattr(c, 'name', None)
                                                                    value = c.get('value') if isinstance(c, dict) else getattr(c, 'value', None)
                                                                    if name is not None and value is not None:
                                                                        conv.append({'name': name, 'value': value})
                                                                if conv:
                                                                    self._update_cookies_to_config(conv)
                                                                    update_status("🍪 已保存天眼查cookies（持续检测成功后持久化）")
                                                        except Exception as e:
                                                            update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")
                                                        
                                                        # 自动关闭验证浏览器
                                                        close_cb = getattr(self, '_pending_browser_close', None)
                                                        if callable(close_cb):
                                                            try:
                                                                self._verification_auto_close_requested = True
                                                                close_cb()
                                                                update_status("🧹 已自动关闭验证用浏览器（持续检测成功后）")
                                                            except Exception as e:
                                                                self._verification_auto_close_requested = False
                                                                update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                                                            finally:
                                                                self._pending_browser_close = None
                                                                self._verification_page_ref = None
                                                        
                                                        return {
                                                            'success': True,
                                                            'companies': companies2,
                                                            'query': company_name
                                                        }
                                            except Exception as e:
                                                update_status(f"⚠️ 重新抓取的JSON解析失败: {str(e)}")
                                        
                                        # 主流程仍失败，尝试备用解析
                                        backup2 = self._parse_html_fallback(latest_html, company_name, update_status)
                                        if backup2.get('success'):
                                            try:
                                                browser_cookies = page_ref.cookies()
                                                if browser_cookies:
                                                    conv = []
                                                    for c in browser_cookies:
                                                        name = c.get('name') if isinstance(c, dict) else getattr(c, 'name', None)
                                                        value = c.get('value') if isinstance(c, dict) else getattr(c, 'value', None)
                                                        if name is not None and value is not None:
                                                            conv.append({'name': name, 'value': value})
                                                    if conv:
                                                        self._update_cookies_to_config(conv)
                                                        update_status("🍪 已保存天眼查cookies（持续检测备用解析后持久化）")
                                            except Exception as e:
                                                update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")
                                            
                                            close_cb = getattr(self, '_pending_browser_close', None)
                                            if callable(close_cb):
                                                try:
                                                    self._verification_auto_close_requested = True
                                                    close_cb()
                                                    update_status("🧹 已自动关闭验证用浏览器（持续检测备用解析成功后）")
                                                except Exception as e:
                                                    self._verification_auto_close_requested = False
                                                    update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                                                finally:
                                                    self._pending_browser_close = None
                                                    self._verification_page_ref = None
                                            return backup2
                                        
                                        # 暂未成功，稍等后重试
                                        time.sleep(1.0)
                                    except Exception as e:
                                        update_status(f"⚠️ 浏览器抓取循环异常: {str(e)}")
                                        time.sleep(1.0)
                                
                                # 持续检测超时，关闭浏览器
                                update_status("⏰ 持续检测超时，未能在浏览器中找到企业信息")
                                close_cb = getattr(self, '_pending_browser_close', None)
                                if callable(close_cb):
                                    try:
                                        self._verification_auto_close_requested = True
                                        close_cb()
                                        update_status("🧹 已关闭验证用浏览器（超时后）")
                                    except Exception:
                                        self._verification_auto_close_requested = False
                                        pass
                                    finally:
                                        self._pending_browser_close = None
                                        self._verification_page_ref = None
                        
                        # 如果验证后仍然未找到，返回错误
                        return {
                            'success': False,
                            'error': '未找到企业信息',
                            'query': company_name
                        }
                except json.JSONDecodeError as e:
                    return {
                        'success': False,
                        'error': f'JSON解析错误: {str(e)}',
                        'query': company_name
                    }
            else:
                update_status("⚠️ 未找到 __NEXT_DATA__ 标签，尝试备用解析方法")

                # 若检测到登录/验证码提示，且当前步骤未自动开浏览器，则在确认数据不可得后再触发验证
                try:
                    login_status = self._detect_login_required(html_content)
                except Exception:
                    login_status = False
                if login_status in (True, "captcha_required", "account_suspended", "account_restricted", "account_disabled"):
                    update_status("🔐 检测到登录/验证码提示，但尚未拿到数据，准备打开验证页面…")
                    try:
                        self._verification_in_progress = True
                        captcha_ok = self._handle_captcha_verification(
                            url,
                            html_content,
                            status_callback
                        )
                    except Exception as e:
                        captcha_ok = False
                        update_status(f"❌ 验证流程异常: {str(e)}")
                    finally:
                        self._verification_in_progress = False

                    # 若验证浏览器已捕获到页面HTML，优先使用捕获内容作为解析来源
                    if captcha_ok and self._verification_page_capture:
                        captured = self._verification_page_capture
                        cap_html = captured.get('html', '')
                        if cap_html:
                            html_content = cap_html
                            update_status("📄 使用验证浏览器捕获的页面HTML进行解析")
                        # 清理一次以避免后续误用旧内容
                        self._verification_page_capture = None
                
                # 备用解析方法：尝试从HTML中直接提取企业信息（不再仅限无cookie模式）
                backup_result = self._parse_html_fallback(html_content, company_name, update_status)
                if backup_result.get('success'):
                    # 备用解析成功后，持久化当前cookies
                    try:
                        current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                        if current_cookies:
                            self._update_cookies_to_config(current_cookies)
                            update_status("🍪 已保存天眼查cookies（备用解析成功后持久化）")
                    except Exception as e:
                        update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")

                    # 自动关闭验证用浏览器（若存在挂起关闭回调）
                    close_cb = getattr(self, '_pending_browser_close', None)
                    if callable(close_cb):
                        try:
                            self._verification_auto_close_requested = True
                            close_cb()
                            update_status("🧹 已自动关闭验证用浏览器（备用解析成功后）")
                        except Exception as e:
                            self._verification_auto_close_requested = False
                            update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                        finally:
                            self._pending_browser_close = None
                    return backup_result
                
                # 如果备用解析失败，但浏览器仍在运行，则在不重新发送HTTP请求的前提下，
                # 直接从已打开的浏览器页面重复抓取HTML并重试解析，直到成功或超时
                page_ref = getattr(self, '_verification_page_ref', None)
                if page_ref is not None:
                    update_status("🔁 浏览器内重复提取页面数据，直到解析成功（不重发请求）")
                    max_retry = 15
                    for i in range(max_retry):
                        try:
                            # 重新抓取当前页面HTML
                            latest_html = page_ref.html
                            update_status(f"🔁 第{i+1}/{max_retry}次抓取，页面长度: {len(latest_html)}")

                            # 尝试主解析流程：提取 __NEXT_DATA__
                            match2 = re.search(r'<script id="__NEXT_DATA__" type="application/json">\s*({.*?})\s*</script>', latest_html, re.DOTALL)
                            if match2:
                                try:
                                    next_data2 = json.loads(match2.group(1))
                                    company_list2 = None
                                    if ('props' in next_data2 and 
                                        'pageProps' in next_data2['props'] and 
                                        'dehydratedState' in next_data2['props']['pageProps'] and
                                        'queries' in next_data2['props']['pageProps']['dehydratedState']):
                                        for query in next_data2['props']['pageProps']['dehydratedState']['queries']:
                                            if ('state' in query and 
                                                'data' in query['state'] and 
                                                'data' in query['state']['data'] and
                                                'companyList' in query['state']['data']['data']):
                                                company_list2 = query['state']['data']['data']['companyList']
                                                break
                                    if company_list2:
                                        companies2 = []
                                        for company in company_list2:
                                            if not isinstance(company, dict):
                                                continue
                                            companies2.append({
                                                'id': company.get('id'),
                                                'name': self._clean_html_tags(company.get('name', '')),
                                                'legalPersonName': company.get('legalPersonName', ''),
                                                'regCapital': company.get('regCapital', ''),
                                                'creditCode': company.get('creditCode', ''),
                                                'regLocation': company.get('regLocation', ''),
                                                'phoneList': company.get('phoneList', []),
                                                'emailList': company.get('emailList', []),
                                                'websites': company.get('websites', ''),
                                                'categoryNameLv1': company.get('categoryNameLv1', ''),
                                                'categoryNameLv2': company.get('categoryNameLv2', ''),
                                                'categoryNameLv3': company.get('categoryNameLv3', ''),
                                                'categoryNameLv4': company.get('categoryNameLv4', '')
                                            })
                                        update_status(f"✅ 重新抓取后成功解析到 {len(companies2)} 家企业")
                                        # 保存cookies（从浏览器获取）
                                        try:
                                            browser_cookies = page_ref.cookies()
                                            if browser_cookies:
                                                # 统一转换为{name,value}
                                                conv = []
                                                for c in browser_cookies:
                                                    name = c.get('name') if isinstance(c, dict) else getattr(c, 'name', None)
                                                    value = c.get('value') if isinstance(c, dict) else getattr(c, 'value', None)
                                                    if name is not None and value is not None:
                                                        conv.append({'name': name, 'value': value})
                                                if conv:
                                                    self._update_cookies_to_config(conv)
                                                    update_status("🍪 已保存天眼查cookies（浏览器抓取成功后持久化）")
                                        except Exception as e:
                                            update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")

                                        # 自动关闭验证浏览器
                                        close_cb = getattr(self, '_pending_browser_close', None)
                                        if callable(close_cb):
                                            try:
                                                self._verification_auto_close_requested = True
                                                close_cb()
                                                update_status("🧹 已自动关闭验证用浏览器（抓取成功后）")
                                            except Exception as e:
                                                self._verification_auto_close_requested = False
                                                update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                                            finally:
                                                self._pending_browser_close = None
                                                self._verification_page_ref = None
                                        return {
                                            'success': True,
                                            'companies': companies2,
                                            'query': company_name
                                        }
                                except Exception as e:
                                    update_status(f"⚠️ 重新抓取的JSON解析失败: {str(e)}")

                            # 主流程仍失败，尝试备用解析
                            backup2 = self._parse_html_fallback(latest_html, company_name, update_status)
                            if backup2.get('success'):
                                try:
                                    browser_cookies = page_ref.cookies()
                                    if browser_cookies:
                                        conv = []
                                        for c in browser_cookies:
                                            name = c.get('name') if isinstance(c, dict) else getattr(c, 'name', None)
                                            value = c.get('value') if isinstance(c, dict) else getattr(c, 'value', None)
                                            if name is not None and value is not None:
                                                conv.append({'name': name, 'value': value})
                                        if conv:
                                            self._update_cookies_to_config(conv)
                                            update_status("🍪 已保存天眼查cookies（浏览器备用解析后持久化）")
                                except Exception as e:
                                    update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")

                                close_cb = getattr(self, '_pending_browser_close', None)
                                if callable(close_cb):
                                    try:
                                        self._verification_auto_close_requested = True
                                        close_cb()
                                        update_status("🧹 已自动关闭验证用浏览器（备用解析成功后）")
                                    except Exception as e:
                                        self._verification_auto_close_requested = False
                                        update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                                    finally:
                                        self._pending_browser_close = None
                                        self._verification_page_ref = None
                                return backup2

                            # 暂未成功，稍等后重试
                            time.sleep(1.0)
                        except Exception as e:
                            update_status(f"⚠️ 浏览器抓取循环异常: {str(e)}")
                            time.sleep(1.0)
                
                # 保存调试页面（仅在调试模式下）
                if hasattr(self, 'debug_output') and getattr(self, 'debug_output', False):
                    debug_file = f"debug_page_{int(time.time())}.html"
                    try:
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(html_content)
                        update_status(f"🔧 调试页面已保存到: {debug_file}")
                    except Exception as e:
                        update_status(f"🔧 保存调试页面失败: {str(e)}")
                
                return {
                    'success': False,
                    'error': '无法解析页面数据',
                    'query': company_name
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'搜索失败: {str(e)}',
                'query': company_name
            }
    
    def query_icp_info(self, company_id: str, status_callback=None, partial_callback=None) -> Dict:
        """
        查询企业ICP备案信息
        
        Args:
            company_id (str): 企业ID
            status_callback (callable): 状态更新回调函数
            
        Returns:
            dict: ICP备案信息
        """
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
            
        update_status(f"正在查询企业ID {company_id} 的ICP备案信息")
        
        all_icp_records = []
        page_num = 1
        # 尽量减少分页次数，降低触发风控的概率
        page_size = 10

        # 改为按“数据可得性”判定：先尝试请求，不预检Cookie。
        update_status("🧪 按数据可得性判定cookie：先请求，失败再验证")
        
        try:
            # 防止重复打开验证浏览器造成死循环：每个公司仅尝试一次人工验证
            captcha_attempted = False
            while True:
                # 构建ICP查询URL
                icp_url = "https://capi.tianyancha.com/cloud-intellectual-property/intellectualProperty/icpRecordList"
                
                # 请求参数
                params = {
                    'id': company_id,
                    'pageSize': page_size,
                    'pageNum': page_num,
                    '_': str(int(time.time() * 1000))
                }
                
                headers = {
                    'Host': 'capi.tianyancha.com',
                    'Connection': 'keep-alive',
                    'X-AUTH-TOKEN': self.tianyancha_cookies.get('auth_token', ''),
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
                    'sec-ch-ua-mobile': '?0',
                    # 不带X-TYCID头，仅在Cookie中保留TYCID以对齐成功发包
                    # 统一使用与sec-ch-ua一致的Chrome 139 UA，避免随机UA触发风控
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Content-Type': 'application/json',
                    'version': 'TYC-Web',
                    'Origin': 'https://www.tianyancha.com',
                    'Sec-Fetch-Site': 'same-site',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Dest': 'empty',
                    'Referer': 'https://www.tianyancha.com/',
                    'Accept-Encoding': 'gzip, deflate, br, zstd',
                    'Accept-Language': 'zh-CN,zh;q=0.9'
                }
                
                # 发送请求（首轮不自动开浏览器，人机验证仅在数据不可得时触发）
                # 调试输出：打印完整请求信息，便于对比你手动发包
                try:
                    from urllib.parse import urlencode
                    full_url = icp_url + ("?" + urlencode(params))
                except Exception:
                    full_url = icp_url
                if self.show_request_details:
                    update_status("➡️ 即将发送ICP请求")
                    update_status(f"🔗 URL: {full_url}")
                    update_status(f"🔖 Method: GET")
                # 打印关键请求头
                try:
                    header_lines = [
                        f"Host: {headers.get('Host','')}",
                        f"Connection: {headers.get('Connection','keep-alive')}",
                        f"X-AUTH-TOKEN: {headers.get('X-AUTH-TOKEN','')}",
                        f"User-Agent: {headers.get('User-Agent','')}",
                        f"sec-ch-ua-platform: {headers.get('sec-ch-ua-platform','')}",
                        f"sec-ch-ua: {headers.get('sec-ch-ua','')}",
                        f"sec-ch-ua-mobile: {headers.get('sec-ch-ua-mobile','')}",
                        f"Accept: {headers.get('Accept','')}",
                        f"Content-Type: {headers.get('Content-Type','')}",
                        f"version: {headers.get('version','')}",
                        f"Origin: {headers.get('Origin','')}",
                        f"Sec-Fetch-Site: {headers.get('Sec-Fetch-Site','')}",
                        f"Sec-Fetch-Mode: {headers.get('Sec-Fetch-Mode','')}",
                        f"Sec-Fetch-Dest: {headers.get('Sec-Fetch-Dest','')}",
                        f"Referer: {headers.get('Referer','')}",
                        f"Accept-Encoding: {headers.get('Accept-Encoding','')}",
                        f"Accept-Language: {headers.get('Accept-Language','')}"
                    ]
                    if self.show_request_details:
                        update_status("🧾 请求头:")
                        for line in header_lines:
                            update_status("  " + line)
                except Exception:
                    pass
                # 打印Cookies（按name=value）
                try:
                    if self.show_request_details and self.tianyancha_cookies:
                        cookie_lines = []
                        for name, value in self.tianyancha_cookies.items():
                            cookie_lines.append(f"{name}={value}")
                        update_status("🍪 Cookies:")
                        update_status("  " + "; ".join(cookie_lines))
                except Exception:
                    pass

                response = self._make_request(
                    'GET',
                    icp_url,
                    headers=headers,
                    params=params,
                    cookies=self.tianyancha_cookies,
                    status_callback=status_callback,
                    # 首次不打开浏览器；若检测到风控/验证码且拿不到数据，再在下方显式打开
                    allow_open_browser=False,
                    defer_login_detection=True
                )
                if response:
                    response.raise_for_status()
                    try:
                        data = response.json() if hasattr(response, 'json') else {}
                    except Exception:
                        # 处理HTML验证码/登录页面：视为数据不可得，触发人工验证
                        resp_text = getattr(response, 'text', '')
                        login_status = self._detect_login_required(resp_text)
                        if login_status in ('captcha_required', True, 'account_suspended', 'account_restricted', 'account_disabled'):
                            if captcha_attempted:
                                # 已尝试过一次验证，避免重复打开导致循环
                                return {
                                    'success': False,
                                    'error': '需要人机验证但未完成，已保持浏览器开启，请重试',
                                    'company_id': company_id,
                                    'icp_records': all_icp_records
                                }
                            update_status("🔐 检测到人机验证/登录要求，准备打开企业详情页进行人工验证...")
                            try:
                                self._verification_in_progress = True
                                company_url = f"https://www.tianyancha.com/company/{company_id}"
                                update_status(f"🌐 正在打开验证页面: {company_url}")
                                captcha_ok = self._handle_captcha_verification(
                                    company_url,
                                    resp_text,
                                    status_callback
                                )
                            except Exception as e:
                                captcha_ok = False
                                update_status(f"验证码流程异常: {e}")
                            finally:
                                self._verification_in_progress = False
                            captcha_attempted = True
                            if captcha_ok:
                                # 验证成功后：优先使用验证流程中已更新的 self.tianyancha_cookies
                                try:
                                    if self.tianyancha_cookies:
                                        # 同步到requests会话
                                        for name, value in self.tianyancha_cookies.items():
                                            try:
                                                self.session.cookies.set(name, value)
                                            except Exception:
                                                pass
                                        # 持久化到配置
                                        self._update_cookies_to_config(self.tianyancha_cookies)
                                        update_status("🍪 已保存并同步天眼查Cookies（验证成功后持久化）")
                                    else:
                                        # 兜底：从会话读取并保存
                                        current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                                        cookie_dict = {it['name']: it['value'] for it in current_cookies if it.get('name') and it.get('value')}
                                        if cookie_dict:
                                            self.tianyancha_cookies.update(cookie_dict)
                                            self._update_cookies_to_config(self.tianyancha_cookies)
                                            update_status("🍪 已从会话兜底保存Cookies")
                                except Exception as e:
                                    update_status(f"⚠️ 保存/同步Cookies时出现异常: {str(e)}")

                                # 验证成功后重试当前页请求
                                update_status("验证完成，重试当前页的ICP请求...")
                                continue
                            else:
                                return {
                                    'success': False,
                                    'error': '需要人机验证但未完成，已保持浏览器开启，请重试',
                                    'company_id': company_id,
                                    'icp_records': all_icp_records
                                }
                        else:
                            data = {}
                else:
                    update_status("ICP请求返回为空")
                    return {
                        'success': False,
                        'message': 'ICP请求返回为空',
                        'data': [],
                        'icp_records': all_icp_records
                    }
                
                # 确保data是字典类型
                if not isinstance(data, dict):
                    update_status(f"返回数据类型错误: {type(data).__name__}")
                    return {
                        'success': False,
                        'error': f'返回数据类型错误: {type(data).__name__}',
                        'company_id': company_id,
                        'icp_records': all_icp_records
                    }
                
                if data.get('state') != 'ok':
                    # 仅当返回JSON明确表示风控/验证码/风险时才打开浏览器
                    msg = str(data.get('message', '未知错误'))
                    risk_keywords = ['人机验证', '验证码', '风控', '账号存在风险', 'captcha', '登录', 'login', '请登录', '需要登录']
                    if any(k in msg for k in risk_keywords):
                        if captcha_attempted:
                            return {
                                'success': False,
                                'error': '需要人机验证但未完成，已保持浏览器开启，请重试',
                                'company_id': company_id,
                                'icp_records': all_icp_records
                            }
                        update_status(f"检测到风控: {msg}，尝试打开企业详情页进行人工验证...")
                        
                        # 输出响应内容用于调试
                        if hasattr(response, 'text') and response.text:
                            truncated_text = response.text[:500] + "..." if len(response.text) > 500 else response.text
                            update_status(f"🔍 风控响应内容: {truncated_text}")
                        if hasattr(response, 'status_code'):
                            update_status(f"🔍 响应状态码: {response.status_code}")
                        
                        try:
                            self._verification_in_progress = True
                            company_url = f"https://www.tianyancha.com/company/{company_id}"
                            update_status(f"🌐 正在打开验证页面: {company_url}")
                            captcha_ok = self._handle_captcha_verification(
                                company_url,
                                response.text if hasattr(response, 'text') else None,
                                status_callback
                            )
                        except Exception as e:
                            captcha_ok = False
                            update_status(f"验证码流程异常: {e}")
                        finally:
                            self._verification_in_progress = False
                        captcha_attempted = True
                        # 根据验证码完成情况处理
                        if captcha_ok:
                            # 验证成功后持久化最新cookies
                            try:
                                current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                                if current_cookies:
                                    self._update_cookies_to_config(current_cookies)
                                    update_status("🍪 已保存天眼查cookies（验证成功后持久化）")
                            except Exception as e:
                                update_status(f"⚠️ 保存cookies时出现异常: {str(e)}")
                            # 验证完成后重试当前页
                            update_status("验证完成，重试当前页的ICP请求...")
                            continue
                        else:
                            return {
                                'success': False,
                                'error': '需要人机验证但未完成，已保持浏览器开启，请重试',
                                'company_id': company_id,
                                'icp_records': all_icp_records
                            }
                    else:
                        return {
                            'success': False,
                            'error': f'ICP查询失败: {msg}',
                            'company_id': company_id,
                            'icp_records': all_icp_records
                        }
                
                # 检查是否有数据
                if 'data' not in data or not data['data']:
                    break
                    
                # 检查是否到达最后一页
                if 'item' not in data['data'] or not data['data']['item']:
                    break
                    
                # 提取ICP记录
                page_records = []
                for item in data['data']['item']:
                    icp_record = {
                        'ym': item.get('ym', ''),  # 域名
                        'webSite': item.get('webSite', []),  # URL列表
                        'webName': item.get('webName', ''),  # 网站名称
                        'liscense': item.get('liscense', '')  # 备案号
                    }
                    all_icp_records.append(icp_record)
                    page_records.append(icp_record)
                
                update_status(f"已获取第 {page_num} 页，共 {len(data['data']['item'])} 条记录")

                # 流式输出当前页结果到UI
                try:
                    if callable(partial_callback) and page_records:
                        partial_callback({
                            'type': 'icp_page',
                            'page_num': page_num,
                            'records': page_records
                        })
                except Exception:
                    pass
                
                # 检查是否还有更多页
                if len(data['data']['item']) < page_size:
                    break
                    
                page_num += 1
                
                # 防止无限循环
                if page_num > 10:
                    break
            
            update_status(f"ICP查询完成，共获取 {len(all_icp_records)} 条备案记录")

            # ICP查询成功后检测并保存cookie更新
            try:
                # 获取当前会话中的cookies
                current_cookies = [{'name': c.name, 'value': c.value} for c in self.session.cookies]
                cookie_dict = {it['name']: it['value'] for it in current_cookies if it.get('name') and it.get('value')}
                
                if cookie_dict:
                    # 检测cookie变化
                    old_cookie_count = len(self.tianyancha_cookies)
                    old_key_cookies = {k: v for k, v in self.tianyancha_cookies.items() 
                                     if k in ['TYCID', 'auth_token', 'tyc-user-info', 'tyc-user-phone']}
                    
                    # 更新cookies
                    self.tianyancha_cookies.update(cookie_dict)
                    new_cookie_count = len(self.tianyancha_cookies)
                    new_key_cookies = {k: v for k, v in self.tianyancha_cookies.items() 
                                     if k in ['TYCID', 'auth_token', 'tyc-user-info', 'tyc-user-phone']}
                    
                    # 检测变化并记录
                    cookie_changed = False
                    if new_cookie_count != old_cookie_count:
                        update_status(f"🍪 Cookie数量变化: {old_cookie_count} -> {new_cookie_count}")
                        cookie_changed = True
                    
                    # 检测关键cookie变化
                    for key in ['TYCID', 'auth_token', 'tyc-user-info', 'tyc-user-phone']:
                        old_val = old_key_cookies.get(key, '')
                        new_val = new_key_cookies.get(key, '')
                        if old_val != new_val:
                            if old_val and new_val:
                                update_status(f"🔄 关键Cookie已更新: {key}")
                            elif new_val:
                                update_status(f"🆕 新增关键Cookie: {key}")
                            cookie_changed = True
                    
                    # 如果有变化，保存到配置
                    if cookie_changed:
                        self._update_cookies_to_config(self.tianyancha_cookies)
                        update_status("🍪 已检测并保存Cookie更新（ICP查询后）")
                    else:
                        update_status("🍪 Cookie无变化，无需更新")
                else:
                    update_status("⚠️ 未检测到有效的Cookie")
            except Exception as e:
                update_status(f"⚠️ Cookie检测过程中出现异常: {str(e)}")

            # 若之前开启了验证浏览器，成功后自动关闭以清理资源
            close_cb = getattr(self, '_pending_browser_close', None)
            if callable(close_cb):
                try:
                    self._verification_auto_close_requested = True
                    close_cb()
                    update_status("🧹 已自动关闭验证用浏览器（ICP成功后）")
                except Exception as e:
                    self._verification_auto_close_requested = False
                    update_status(f"⚠️ 自动关闭浏览器失败：{str(e)}")
                finally:
                    self._pending_browser_close = None
                    self._verification_page_ref = None

            return {
                'success': True,
                'icp_records': all_icp_records,
                'company_id': company_id
            }
            
        except Exception as e:
            # 打印异常响应信息用于调试
            error_msg = f'ICP查询失败: {str(e)}'
            update_status(f"❌ {error_msg}")
            
            # 尝试获取响应内容进行调试
            try:
                # 安全地检查异常是否有response属性（通常是requests.HTTPError等）
                response_obj = getattr(e, 'response', None)
                if response_obj is not None:
                    response_text = getattr(response_obj, 'text', '')
                    status_code = getattr(response_obj, 'status_code', 'Unknown')
                    update_status(f"🔍 异常响应状态码: {status_code}")
                    if response_text:
                        # 截取前500字符避免输出过长
                        truncated_text = response_text[:500] + "..." if len(response_text) > 500 else response_text
                        update_status(f"🔍 异常响应内容: {truncated_text}")
                        
                        # 检查是否为账户被暂停的响应
                        login_status = self._detect_login_required(response_text)
                        if login_status == "account_suspended":
                            update_status("⚠️ 检测到账户被暂停状态")
                        elif login_status == "account_restricted":
                            update_status("⚠️ 检测到账户受限状态")
                        elif login_status == "account_disabled":
                            update_status("⚠️ 检测到账户被禁用状态")
                        elif login_status == "captcha_required":
                            update_status("⚠️ 检测到需要验证码")
                        elif login_status is True:
                            update_status("⚠️ 检测到需要登录")
                    else:
                        update_status("🔍 异常响应内容为空")
                else:
                    update_status("🔍 无法获取异常响应信息")
            except Exception as debug_e:
                update_status(f"🔍 获取异常响应信息时出错: {str(debug_e)}")
            
            return {
                'success': False,
                'error': error_msg,
                'icp_records': all_icp_records,
                'company_id': company_id
            }
    
    def query_app_info(self, company_id: str, status_callback=None) -> Dict:
        """查询企业APP信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        update_status(f"正在查询APP信息: {company_id}")
        
        try:
            url = f"https://capi.tianyancha.com/cloud-business-state/v3/ar/appbkinfo"
            
            params = {
                'id': company_id,
                'pageSize': 10,
                'pageNum': 1
            }
            
            headers = {
                'Host': 'capi.tianyancha.com',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'version': 'TYC-Web',
                'Origin': 'https://www.tianyancha.com',
                'Referer': 'https://www.tianyancha.com/',
                'User-Agent': self._get_random_ua()
            }
            
            # 添加认证头
            if hasattr(self, 'tianyancha_cookies') and self.tianyancha_cookies:
                auth_token = self.tianyancha_cookies.get('auth_token')
                tycid = self.tianyancha_cookies.get('tycid')
                if auth_token:
                    headers['X-AUTH-TOKEN'] = auth_token
                if tycid:
                    headers['X-TYCID'] = tycid
            
            response = self._make_request('GET', url, params=params, headers=headers, 
                                        cookies=self.tianyancha_cookies, status_callback=status_callback, allow_open_browser=False)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
            else:
                return {
                    'success': False,
                    'message': 'APP信息请求返回为空',
                    'data': []
                }
            
            if data.get('state') != 'ok':
                return {
                    'success': False,
                    'error': f'APP信息查询失败: {data.get("message", "未知错误")}',
                    'company_id': company_id
                }
            
            app_list = []
            if 'data' in data and 'items' in data['data']:
                for item in data['data']['items']:
                    app_info = {
                        'name': item.get('name', ''),  # 产品名称
                        'type': item.get('type', ''),  # 产品分类
                        'classes': item.get('classes', '')  # 领域
                    }
                    app_list.append(app_info)
            
            update_status(f"成功获取 {len(app_list)} 个APP信息")
            return {
                'success': True,
                'message': f'成功获取 {len(app_list)} 个APP信息',
                'company_id': company_id,
                'data': app_list
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'APP信息查询异常: {str(e)}',
                'company_id': company_id
            }
    
    def query_wechat_info(self, company_id: str, status_callback=None) -> Dict:
        """查询企业微信公众号信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        update_status(f"正在查询微信公众号信息: {company_id}")
        
        try:
            url = f"https://capi.tianyancha.com/cloud-business-state/wechat/list"
            
            params = {
                'graphId': company_id,
                'pageSize': 10,
                'pageNum': 1
            }
            
            headers = {
                'Host': 'capi.tianyancha.com',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'version': 'TYC-Web',
                'Origin': 'https://www.tianyancha.com',
                'Referer': 'https://www.tianyancha.com/',
                'User-Agent': self._get_random_ua()
            }
            
            # 添加认证头
            if hasattr(self, 'tianyancha_cookies') and self.tianyancha_cookies:
                auth_token = self.tianyancha_cookies.get('auth_token')
                tycid = self.tianyancha_cookies.get('tycid')
                if auth_token:
                    headers['X-AUTH-TOKEN'] = auth_token
                if tycid:
                    headers['X-TYCID'] = tycid
            
            response = self._make_request('GET', url, params=params, headers=headers, 
                                        cookies=self.tianyancha_cookies, status_callback=status_callback, allow_open_browser=False)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
            else:
                return {
                    'success': False,
                    'message': '微信公众号信息请求返回为空',
                    'data': []
                }
            
            if data.get('state') != 'ok':
                return {
                    'success': False,
                    'error': f'微信公众号信息查询失败: {data.get("message", "未知错误")}',
                    'company_id': company_id
                }
            
            wechat_list = []
            if 'data' in data and 'resultList' in data['data']:
                for item in data['data']['resultList']:
                    wechat_info = {
                        'title': item.get('title', ''),  # 微信公众号名称
                        'publicNum': item.get('publicNum', '')  # 微信号
                    }
                    wechat_list.append(wechat_info)
            
            update_status(f"成功获取 {len(wechat_list)} 个微信公众号信息")
            return {
                'success': True,
                'message': f'成功获取 {len(wechat_list)} 个微信公众号信息',
                'company_id': company_id,
                'data': wechat_list
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'微信公众号信息查询异常: {str(e)}',
                'company_id': company_id
            }
    
    def query_company_complete(self, company_name: str, status_callback=None, partial_callback=None) -> Dict:
        """
        完整查询企业信息（包括基本信息、ICP备案、APP信息、微信公众号）
        
        Args:
            company_name (str): 企业名称
            status_callback (callable): 状态更新回调函数
            
        Returns:
            dict: 完整查询结果
        """
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        # 第一步：搜索企业基本信息
        update_status("第一步：搜索企业基本信息")
        company_result = self.search_company(company_name, status_callback)
        
        if not company_result['success']:
            return company_result
            
        companies = company_result['companies']
        if not companies:
            return {
                'success': False,
                'error': '未找到企业信息',
                'query': company_name
            }
        
        # 第一步完成
        update_status(f"第一步完成：找到 {len(companies)} 家企业")

        # 流式输出搜索结果
        try:
            if callable(partial_callback):
                partial_callback({
                    'type': 'search_results',
                    'companies': companies
                })
        except Exception:
            pass
        
        # 只查询第一家企业的详细信息
        first_company = companies[0]
        company_id = first_company['id']
        
        # 第二步：查询ICP备案信息
        update_status(f"第二步：查询 {first_company['name']} 的ICP备案信息")
        icp_result = self.query_icp_info(company_id, status_callback, partial_callback)
        # 如果ICP触发了人工验证且尚未完成，暂停后续步骤
        if icp_result and not icp_result.get('success', False):
            err_msg = icp_result.get('error', '')
            pause_keywords = ['人机验证', '验证码', '请重试', '验证', '登录', 'login', '请登录', '需要登录']
            if any(k in err_msg for k in pause_keywords):
                update_status(f"⏸ 检测到人工验证进行中：{err_msg}")
                update_status("➡️ 不再重复打开浏览器，将继续APP与微信公众号查询；稍后可重试ICP")
        
        # 第三步：查询APP信息
        update_status(f"第三步：查询 {first_company['name']} 的APP信息")
        app_result = self.query_app_info(company_id, status_callback)
        # 流式输出APP信息
        try:
            if callable(partial_callback) and app_result and app_result.get('success'):
                partial_callback({
                    'type': 'app_info',
                    'data': app_result.get('data', [])
                })
        except Exception:
            pass
        
        # 第四步：查询微信公众号信息
        update_status(f"第四步：查询 {first_company['name']} 的微信公众号信息")
        wechat_result = self.query_wechat_info(company_id, status_callback)
        # 流式输出微信公众号信息
        try:
            if callable(partial_callback) and wechat_result and wechat_result.get('success'):
                partial_callback({
                    'type': 'wechat_info',
                    'data': wechat_result.get('data', [])
                })
        except Exception:
            pass
        
        # 将所有信息添加到第一家企业信息中
        first_company_complete = first_company.copy()
        
        # 添加ICP信息
        if icp_result and icp_result.get('success', False):
            first_company_complete['icp_records'] = icp_result.get('icp_records', [])
            update_status(f"第二步完成：ICP查询完成，共获取 {len(icp_result.get('icp_records', []))} 条备案记录")
        else:
            # 如果有部分记录，保留并提示为部分成功
            partial_icp = icp_result.get('icp_records', []) if icp_result else []
            if partial_icp:
                first_company_complete['icp_records'] = partial_icp
                update_status(f"第二步部分完成：ICP已获取 {len(partial_icp)} 条记录（后续查询失败或需登录）")
            else:
                first_company_complete['icp_records'] = []
                error_msg = icp_result.get('error', '未知错误') if icp_result else '请求返回为空'
                update_status(f"ICP查询失败: {error_msg}")
        
        # 添加APP信息
        if app_result and app_result.get('success', False):
            first_company_complete['app_records'] = app_result.get('data', [])
            update_status(f"第三步完成：APP查询完成，共获取 {len(app_result.get('data', []))} 条APP记录")
        else:
            first_company_complete['app_records'] = []
            error_msg = app_result.get('error', '未知错误') if app_result else '请求返回为空'
            update_status(f"APP查询失败: {error_msg}")
        
        # 添加微信公众号信息
        if wechat_result and wechat_result.get('success', False):
            first_company_complete['wechat_records'] = wechat_result.get('data', [])
            update_status(f"第四步完成：微信公众号查询完成，共获取 {len(wechat_result.get('data', []))} 条公众号记录")
        else:
            first_company_complete['wechat_records'] = []
            error_msg = wechat_result.get('error', '未知错误') if wechat_result else '请求返回为空'
            update_status(f"微信公众号查询失败: {error_msg}")
        
        # 返回所有企业信息，但只有第一家包含完整信息
        companies[0] = first_company_complete
        
        return {
            'success': True,
            'companies': companies,
            'query': company_name
        }
    
    def _extract_category_levels(self, company: Dict) -> Dict:
        print(f"DEBUG: _extract_category_levels received company: {json.dumps(company, ensure_ascii=False, indent=2)}")
        # 1. 优先检查 industryInfo 字段 (用户反馈的新字段结构)
        industry_info = company.get('industryInfo')
        
        # 处理可能的数据嵌套
        if not industry_info and isinstance(company.get('baseInfo'), dict):
            industry_info = company.get('baseInfo', {}).get('industryInfo')

        if industry_info:
            # 如果是字符串，尝试解析
            if isinstance(industry_info, str):
                try:
                    industry_info = json.loads(industry_info)
                except:
                    pass
            
            if isinstance(industry_info, dict):
                levels = []
                # 尝试多种键名模式
                for i in range(1, 5):
                    val = (industry_info.get(f'nameLevel{i}') or 
                           industry_info.get(f'level{i}Name') or 
                           industry_info.get(f'categoryNameLv{i}') or
                           industry_info.get(f'industryNameLv{i}'))
                    levels.append(val or '')
                
                if any(levels):
                    extracted_levels = {
                        'categoryNameLv1': levels[0],
                        'categoryNameLv2': levels[1],
                        'categoryNameLv3': levels[2],
                        'categoryNameLv4': levels[3]
                    }
                    print(f"DEBUG: Extracted from industryInfo: {extracted_levels}")
                    return extracted_levels

        # 2. 检查 industry 字段 (有时直接是行业名称字符串)
        industry = company.get('industry')
        if industry and isinstance(industry, str):
             extracted_levels = {
                'categoryNameLv1': industry,
                'categoryNameLv2': '',
                'categoryNameLv3': '',
                'categoryNameLv4': ''
             }
             print(f"DEBUG: Extracted from industry (string): {extracted_levels}")
             return extracted_levels

        # 3. 检查其他常见字段 (industryCategory, industryName 等)
        # 这些字段可能是字符串，也可能是包含层级信息的对象
        for key in (
            'industryCategory', 'industryName', 'categoryName',
            'category', 'industryType', 'industryCategoryName'
        ):
            val = company.get(key)
            if val:
                # 如果是字符串，作为一级分类返回
                if isinstance(val, str):
                    extracted_levels = {
                        'categoryNameLv1': val,
                        'categoryNameLv2': '',
                        'categoryNameLv3': '',
                        'categoryNameLv4': ''
                    }
                    print(f"DEBUG: Extracted from {key} (string): {extracted_levels}")
                    return extracted_levels
                # 如果是字典，尝试提取层级信息
                elif isinstance(val, dict):
                    levels = []
                    for i in range(1, 5):
                        sub_val = (val.get(f'industryNameLv{i}') or 
                                   val.get(f'industryCategoryLv{i}') or 
                                   val.get(f'categoryNameLv{i}') or
                                   val.get(f'nameLevel{i}') or
                                   val.get(f'level{i}Name'))
                        levels.append(sub_val or '')
                    
                    if any(levels):
                        extracted_levels = {
                            'categoryNameLv1': levels[0],
                            'categoryNameLv2': levels[1],
                            'categoryNameLv3': levels[2],
                            'categoryNameLv4': levels[3]
                        }
                        print(f"DEBUG: Extracted from {key} (dict): {extracted_levels}")
                        return extracted_levels

        # 4. 原有的兜底逻辑 (直接在 company 对象上查找层级字段)
        levels = [company.get(f'categoryNameLv{i}', '') for i in range(1, 5)]
        if any(levels):
            extracted_levels = {
                'categoryNameLv1': levels[0] or '',
                'categoryNameLv2': levels[1] or '',
                'categoryNameLv3': levels[2] or '',
                'categoryNameLv4': levels[3] or ''
            }
            print(f"DEBUG: Extracted from categoryNameLvX: {extracted_levels}")
            return extracted_levels
        
        print("DEBUG: No industry information extracted, returning empty.")
        
        # 5. 尝试从 abstractsBaseInfo 中提取 (兜底方案)
        abstracts_base_info = company.get('abstractsBaseInfo')
        if abstracts_base_info and isinstance(abstracts_base_info, str):
            match = re.search(r'以从事(.+?)为主的企业', abstracts_base_info)
            if match:
                extracted_industry = match.group(1).strip()
                print(f"DEBUG: Extracted from abstractsBaseInfo: {extracted_industry}")
                return {
                    'categoryNameLv1': extracted_industry,
                    'categoryNameLv2': '',
                    'categoryNameLv3': '',
                    'categoryNameLv4': ''
                }

        return {
            'categoryNameLv1': '',
            'categoryNameLv2': '',
            'categoryNameLv3': '',
            'categoryNameLv4': ''
        }


    def _clean_html_tags(self, text: str) -> str:
        """清理HTML标签"""
        if not text:
            return ''
        # 移除HTML标签
        clean_text = re.sub(r'<[^>]+>', '', text)
        return clean_text.strip()
    
    def query_company_info(self, company_name: str, status_callback=None) -> Dict:
        """
        查询企业信息的主函数
        
        Args:
            company_name (str): 企业名称
            status_callback (callable): 状态更新回调函数
            
        Returns:
            dict: 查询结果
        """
        return self.query_company_complete(company_name, status_callback)
    
    def format_result(self, result: Dict) -> str:
        """格式化查询结果"""
        # 确保result是字典类型
        if not isinstance(result, dict):
            return f"查询结果类型错误: {type(result).__name__}"
            
        if not result.get('success', False):
            return f"查询失败: {result.get('error', '未知错误')}"
        
        output = []
        
        # 确保companies字段存在且为列表
        companies = result.get('companies', [])
        if not isinstance(companies, list):
            return f"企业列表类型错误: {type(companies).__name__}"
            
        # 直接从企业详细信息开始，不显示搜索结果列表
        output.append("=" * 50)
        
        # 只显示第一家企业的详细信息
        if companies:
            company = companies[0]
            
            # 确保company是字典类型
            if not isinstance(company, dict):
                return f"企业信息类型错误: {type(company).__name__}"
            
            print(f"DEBUG: format_result received company for display: {json.dumps(company, ensure_ascii=False, indent=2)}")
                
            output.append(f"企业名称: {company.get('name', '未知')}")
            output.append(f"法定代表人: {company.get('legalPersonName', '未知')}")
            output.append(f"注册资本: {company.get('regCapital', '未知')}")
            output.append(f"统一社会信用代码: {company.get('creditCode', '未知')}")
            output.append(f"注册地址: {company.get('regLocation', '未知')}")
            
            # 联系方式
            phone_list = company.get('phoneList', [])
            if phone_list and isinstance(phone_list, list):
                output.append(f"联系电话: {', '.join(phone_list)}")
                
            email_list = company.get('emailList', [])
            if email_list and isinstance(email_list, list):
                output.append(f"邮箱: {', '.join(email_list)}")
                
            websites = company.get('websites', '')
            if websites:
                output.append(f"网站: {websites}")
            
            # 行业分类
            categories = []
            for i in range(1, 5):
                cat = company.get(f'categoryNameLv{i}')
                if cat:
                    categories.append(cat)
            if categories:
                output.append(f"行业分类: {' > '.join(categories)}")
            
            # ICP备案信息
            icp_records = company.get('icp_records', [])
            if icp_records and isinstance(icp_records, list):
                output.append("\nICP备案信息:")
                for i, icp in enumerate(icp_records, 1):
                    # 确保icp是字典类型
                    if not isinstance(icp, dict):
                        output.append(f"  备案{i}: 数据类型错误 {type(icp).__name__}")
                        continue
                        
                    output.append(f"  备案{i}:")
                    output.append(f"    域名: {icp.get('ym', '未知')}")
                    output.append(f"    网站名称: {icp.get('webName', '未知')}")
                    output.append(f"    备案号: {icp.get('liscense', '未知')}")
                    
                    website = icp.get('webSite', [])
                    if website and isinstance(website, list):
                        output.append(f"    网站URL: {', '.join(website)}")
            else:
                output.append("\n暂无ICP备案信息")
            
            # APP信息
            app_records = company.get('app_records', [])
            if app_records and isinstance(app_records, list):
                output.append("\nAPP信息:")
                for i, app in enumerate(app_records, 1):
                    # 确保app是字典类型
                    if not isinstance(app, dict):
                        output.append(f"  APP{i}: 数据类型错误 {type(app).__name__}")
                        continue
                        
                    output.append(f"  APP{i}:")
                    output.append(f"    产品名称: {app.get('name', '未知')}")
                    output.append(f"    产品分类: {app.get('type', '未知')}")
                    output.append(f"    领域: {app.get('classes', '未知')}")
            else:
                output.append("\n暂无APP信息")
            
            # 微信公众号信息
            wechat_records = company.get('wechat_records', [])
            if wechat_records and isinstance(wechat_records, list):
                output.append("\n微信公众号信息:")
                for i, wechat in enumerate(wechat_records, 1):
                    # 确保wechat是字典类型
                    if not isinstance(wechat, dict):
                        output.append(f"  公众号{i}: 数据类型错误 {type(wechat).__name__}")
                        continue
                        
                    output.append(f"  公众号{i}:")
                    output.append(f"    公众号名称: {wechat.get('title', '未知')}")
                    output.append(f"    微信号: {wechat.get('publicNum', '未知')}")
            else:
                output.append("\n暂无微信公众号信息")
        
        return "\n".join(output)
    
    def _print_single_result(self, result: Dict, company_name: str, index: int, total: int):
        """立即输出单个企业的查询结果"""
        print(f"\n{'='*80}")
        print(f"📊 第 {index}/{total} 家企业查询结果: {company_name}")
        print(f"{'='*80}")
        
        if result.get('success', False):
            companies = result.get('companies', [])
            if companies:
                for i, company in enumerate(companies, 1):
                    print(f"\n🏢 企业 {i}:")
                    print(f"   ID: {company.get('id', 'N/A')}")
                    print(f"   名称: {company.get('name', 'N/A')}")
                    print(f"   法人: {company.get('legalPersonName', 'N/A')}")
                    print(f"   注册资本: {company.get('regCapital', 'N/A')}")
                    print(f"   统一社会信用代码: {company.get('creditCode', 'N/A')}")
                    print(f"   注册地址: {company.get('regLocation', 'N/A')}")
                    
                    # 联系方式
                    phone_list = company.get('phoneList', [])
                    if phone_list:
                        print(f"   电话: {', '.join(phone_list)}")
                    
                    email_list = company.get('emailList', [])
                    if email_list:
                        print(f"   邮箱: {', '.join(email_list)}")
                    
                    websites = company.get('websites', [])
                    if websites:
                        print(f"   网站: {', '.join(websites)}")
                    
                    # 行业分类
                    for level in range(1, 5):
                        category = company.get(f'categoryNameLv{level}')
                        if category:
                            print(f"   行业分类Lv{level}: {category}")
                    
                    if i < len(companies):
                        print(f"   {'-'*40}")
            else:
                print("   ❌ 未找到企业信息")
        else:
            error_msg = result.get('error', '查询失败')
            print(f"   ❌ 查询失败: {error_msg}")
        
        print(f"{'='*80}")

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
                
                # 最多重试2次（包括首次查询）
                max_retries = 2
                retry_count = 0
                query_success = False
                
                while retry_count < max_retries and not query_success:
                    try:
                        # 创建状态回调函数，包含公司信息
                        def company_status_callback(message):
                            if progress_callback:
                                progress_callback(f"第 {i}/{total_companies} 家公司: {company} - {message}")
                        
                        result = self.query_company_complete(company, company_status_callback)
                        
                        # 确保result是字典类型
                        if not isinstance(result, dict):
                            error_msg = f"查询结果类型错误: {type(result).__name__}"
                            if retry_count == max_retries - 1:  # 最后一次重试
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
                            retry_count += 1
                            continue
                        
                        if result.get('success', False):
                            results.append({
                                'company': company,
                                'data': result,
                                'success': True,
                                'index': i
                            })
                            success_count += 1
                            query_success = True
                            
                            # 立即输出详细查询结果
                            companies_found = len(result.get('companies', []))
                            if progress_callback:
                                progress_callback(f"✅ 查询 {company} 成功 - 找到 {companies_found} 家企业")
                            
                            # 立即格式化并输出当前企业的详细信息
                            self._print_single_result(result, company, i, total_companies)
                        else:
                            error_msg = result.get('error', '查询失败')
                            
                            # 检查是否是需要重试的错误（登录相关或请求返回为空）
                            should_retry = any(keyword in error_msg for keyword in [
                                '需要登录', '登录', 'login', '请求返回为空', '重试请求返回为空'
                            ])
                            
                            if should_retry:
                                if progress_callback:
                                    if '请求返回为空' in error_msg:
                                        progress_callback(f"⚠️ 查询 {company} 请求返回为空，可能需要重新登录，正在重试...")
                                    else:
                                        progress_callback(f"⚠️ 查询 {company} 需要重新登录，正在重试...")
                                retry_count += 1
                                if retry_count < max_retries:
                                    time.sleep(2)  # 等待2秒后重试
                                    continue
                            
                            if retry_count == max_retries - 1:  # 最后一次重试
                                results.append({
                                    'company': company,
                                    'error': error_msg,
                                    'success': False,
                                    'index': i
                                })
                                
                                if error_callback:
                                    error_callback(f"❌ 查询 {company} 失败: {error_msg}")
                                elif progress_callback:
                                    progress_callback(f"❌ 查询 {company} 失败: {error_msg}")
                            
                            retry_count += 1
                        
                    except Exception as e:
                        error_msg = str(e)
                        
                        # 检查是否是网络或登录相关异常
                        if any(keyword in error_msg.lower() for keyword in ['timeout', 'connection', 'login', '登录']):
                            if progress_callback:
                                progress_callback(f"⚠️ 查询 {company} 遇到网络问题，正在重试...")
                            retry_count += 1
                            if retry_count < max_retries:
                                time.sleep(3)  # 网络问题等待更长时间
                                continue
                        
                        if retry_count == max_retries - 1:  # 最后一次重试
                            results.append({
                                'company': company,
                                'error': error_msg,
                                'success': False,
                                'index': i
                            })
                            
                            if error_callback:
                                error_callback(f"❌ 查询 {company} 异常: {error_msg}")
                            elif progress_callback:
                                progress_callback(f"❌ 查询 {company} 异常: {error_msg}")
                        
                        retry_count += 1
                
                # 批量查询间的延时（公司与公司之间的查询间隔）
                if i < total_companies:
                    batch_delay = random.uniform(2.0, 4.0)  # 2-4秒随机延时
                    if progress_callback:
                        progress_callback(f"等待 {batch_delay:.1f} 秒后查询下一家公司...")
                    time.sleep(batch_delay)
            
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
        
        formatted_text = f"""📊 天眼查批量查询结果报告
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
                companies = data.get('companies', [])
                
                if companies:
                    company_info = companies[0]
                    formatted_text += f"\n{i}. ✅ {company}"
                    formatted_text += f"\n   统一社会信用代码: {company_info.get('creditCode', 'N/A')}"
                    formatted_text += f"\n   法定代表人: {company_info.get('legalPersonName', 'N/A')}"
                    formatted_text += f"\n   注册资本: {company_info.get('regCapital', 'N/A')}"
                    
                    # ICP备案信息
                    if 'icp_records' in company_info and company_info['icp_records']:
                        formatted_text += f"\n   ICP备案: {len(company_info['icp_records'])}个"
                    else:
                        formatted_text += f"\n   ICP备案: 无"
                else:
                    formatted_text += f"\n{i}. ✅ {company} (无详细信息)"
                
            else:
                error_msg = result.get('error', '未知错误')
                formatted_text += f"\n{i}. ❌ {company}"
                formatted_text += f"\n   错误: {error_msg}"
            
            formatted_text += "\n" + "-"*30
        
        return formatted_text

def main():
    """测试函数"""
    print("天眼查企业信息查询工具")
    print("注意：使用前需要先登录天眼查，并更新Cookie信息")
    
    # 创建查询实例
    query = TianyanchaQuery()
    
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
            company_name = "西藏国玉"  # 默认示例
        
        # 执行查询
        result = query.query_company_complete(company_name)
        
        # 输出结果
        print("\n" + "=" * 60)
        print(query.format_result(result))

if __name__ == "__main__":
    main()
