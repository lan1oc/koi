#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爱企查企业信息查询脚本
功能：通过企业名称查询企业的详细信息，包括基本信息、行业分类、ICP备案、员工联系方式等
"""

import requests
import json
import time
import urllib.parse
import random
from typing import Dict, List, Optional
try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

class AiqichaQuery:
    def __init__(self):
        self.session = requests.Session()
        
        # 反爬配置
        if HAS_FAKE_UA:
            self.ua = UserAgent()
            self.use_fake_ua = True
        else:
            self.use_fake_ua = False
            self.user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'
            ]
        
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
        
        # 初始化Cookie
        self._load_config()
    
    def _load_config(self):
        """从配置文件加载Cookie"""
        try:
            import os
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 加载爱企查Cookie
                aiqicha_config = config.get('aiqicha', {})
                cookie_str = aiqicha_config.get('cookie', '')
                
                if cookie_str:
                    # 解析Cookie字符串
                    self.aiqicha_cookies = {}
                    for item in cookie_str.split(';'):
                        if '=' in item:
                            key, value = item.strip().split('=', 1)
                            self.aiqicha_cookies[key] = value
                else:
                    self.aiqicha_cookies = {}
                
                # 加载寻客宝Cookie
                xunkebao_config = config.get('xunkebao', {})
                xunkebao_cookie_str = xunkebao_config.get('cookie', '')
                
                if xunkebao_cookie_str:
                    # 解析Cookie字符串
                    self.xunkebao_cookies = {}
                    for item in xunkebao_cookie_str.split(';'):
                        if '=' in item:
                            key, value = item.strip().split('=', 1)
                            self.xunkebao_cookies[key] = value
                else:
                    self.xunkebao_cookies = {}
                    
            else:
                # 配置文件不存在，初始化为空字典
                self.aiqicha_cookies = {}
                self.xunkebao_cookies = {}
                    
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            self.aiqicha_cookies = {}
            self.xunkebao_cookies = {}
    
    @property
    def cookie(self):
        """获取Cookie字符串"""
        if not self.aiqicha_cookies:
            return ''
        return '; '.join([f'{k}={v}' for k, v in self.aiqicha_cookies.items()])
    
    @cookie.setter
    def cookie(self, cookie_str: str):
        """设置Cookie字符串"""
        if not cookie_str:
            self.aiqicha_cookies = {}
            return
            
        self.aiqicha_cookies = {}
        for item in cookie_str.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                self.aiqicha_cookies[key] = value
    
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
        
        # 随机轮换User-Agent
        if random.random() < 0.3:  # 30%概率轮换UA
            self._rotate_user_agent()
        
        # 设置请求超时，防止请求卡死
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 10  # 设置10秒超时
        
        # 发送请求
        try:
            if method.upper() == 'GET':
                return self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                return self.session.post(url, **kwargs)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
        except requests.exceptions.Timeout:
            if status_callback:
                status_callback("请求超时，正在重试...")
            # 超时后重试一次，增加超时时间
            kwargs['timeout'] = 20
            if method.upper() == 'GET':
                return self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                return self.session.post(url, **kwargs)
    
    def search_company(self, company_name: str, max_retries: int = 3, status_callback=None) -> Optional[Dict]:
        """
        第一步：搜索企业（简化版，参考天眼查的直接调用方式）
        """
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
                
        update_status(f"正在搜索企业: {company_name}")
        
        # URL编码企业名称
        encoded_name = urllib.parse.quote(company_name)
        url = f"https://aiqicha.baidu.com/s?q={encoded_name}&t=0"
        
        headers = {
            'Host': 'aiqicha.baidu.com',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self._get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': 'https://aiqicha.baidu.com/',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        }
        
        for attempt in range(max_retries):
            try:
                response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
                if not response:
                    update_status("请求返回为空")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None
                
                response.raise_for_status()
                
                # 从HTML中提取JSON数据
                html_content = response.text
                
                # 显示响应基本信息
                print(f"响应长度: {len(html_content)} 字符")
                
                # 检查是否遇到反爬限制（简化检查）
                if self._check_anti_crawler(html_content):
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # 指数退避
                        print(f"检测到反爬限制，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print("多次遇到反爬限制，查询失败")
                        return None
                
                # 尝试提取数据
                data = self._extract_page_data(html_content)
                if data:
                    return data
                
                # 如果提取失败且还有重试机会
                if attempt < max_retries - 1:
                    print(f"数据提取失败，1秒后重试...")
                    time.sleep(1)
                else:
                    print("多次尝试后仍无法提取数据")
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
            "<title>403", "<title>404", "<title>500",
            "403 Forbidden", "404 Not Found", "500 Internal Server Error",
            "Access Denied", "Permission Denied"
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
    
    def _extract_page_data(self, html_content: str) -> Optional[Dict]:
        """
        从HTML中提取页面数据（简化版）
        """
        import re
        
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
                    # 尝试修复常见的JSON问题
                    json_str_fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    data = json.loads(json_str_fixed)
                
                # 检查数据结构并返回
                if (data and isinstance(data, dict) and 'result' in data and 
                    isinstance(data['result'], dict) and 'resultList' in data['result'] and 
                    data['result']['resultList']):
                    
                    result_list = data['result']['resultList']
                    first_result = result_list[0]
                    company_name = first_result.get('entName', '未知')
                    
                    # 处理Unicode编码
                    if '\\u' in company_name:
                        try:
                            company_name = company_name.encode().decode('unicode_escape')
                        except:
                            pass
                    
                    print(f"找到企业: {company_name}")
                    return data
                else:
                    print("数据结构不符合预期")
            except Exception as e:
                print(f"JSON解析失败: {e}")
        else:
            print("未找到window.pageData")
            
            # 调试：保存失败情况下的响应以供分析
            if len(html_content) > 1000000:  # 只保存大文件（可能有问题的响应）
                try:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    debug_filename = f"aiqicha_failed_debug_{timestamp}.html"
                    with open(debug_filename, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print(f"大响应文件已保存到: {debug_filename} ({len(html_content)} 字符)")
                except Exception as e:
                    print(f"保存调试文件失败: {e}")
        
        print("数据提取失败")
        return None
    
    def _extract_json_from_position(self, html_content: str, start_pos: int) -> Optional[str]:
        """
        从指定位置开始提取完整的JSON对象
        """
        if start_pos >= len(html_content):
            return None
        
        # 跳过空白字符
        while start_pos < len(html_content) and html_content[start_pos].isspace():
            start_pos += 1
        
        if start_pos >= len(html_content) or html_content[start_pos] != '{':
            return None
        
        # 手动计算括号匹配
        brace_count = 0
        in_string = False
        escape_next = False
        current_pos = start_pos
        
        while current_pos < len(html_content):
            char = html_content[current_pos]
            
            if escape_next:
                escape_next = False
            elif char == '\\':
                escape_next = True
            elif char == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # 找到匹配的结束括号
                        return html_content[start_pos:current_pos + 1]
                elif char == ';' and brace_count == 0:
                    # 遇到分号但没有匹配的括号，说明JSON结束了
                    break
            
            current_pos += 1
        
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
        if self.use_fake_ua and hasattr(self, 'ua'):
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
    
    def get_company_detail(self, pid: str) -> Optional[Dict]:
        """
        第二步：获取企业详情页信息
        """
        print(f"正在获取企业详情: {pid}")
        
        url = f"https://aiqicha.baidu.com/company_detail_{pid}"
        
        headers = {
            'Host': 'aiqicha.baidu.com',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://aiqicha.baidu.com/s?q={urllib.parse.quote("企业名称")}&t=0',
        }
        
        try:
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies)
            if response:
                response.raise_for_status()
            else:
                return None
            
            # 解析JSON响应
            data = response.text if hasattr(response, 'text') else ""
            html_content = data
            
            # 查找 window.pageData 的JSON数据
            import re
            pattern = r'window\.pageData\s*=\s*({.*?});'
            match = re.search(pattern, html_content, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                
                if 'result' in data:
                    print(f"获取到企业详情数据")
                    return data
                else:
                    print("详情页数据格式异常")
                    return None
            else:
                print("无法从详情页中提取数据")
                return None
            
        except Exception as e:
            print(f"获取企业详情失败: {e}")
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
                'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
                'sec-ch-ua-mobile': '?0',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/plain, */*',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=certRecord',
            }
            
            try:
                response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies)
                if response:
                    response.raise_for_status()
                    # 解析JSON响应
                    data = response.json() if hasattr(response, 'json') else {}
                else:
                    print("ICP请求返回为空")
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
                        break
                    
                    # 继续获取下一页
                    page += 1
                else:
                    # API返回错误或无数据
                    if data.get('status') != 0:
                        print(f"获取ICP备案信息失败: {data.get('message', '未知错误')}")
                    else:
                        print("未获取到ICP备案信息")
                    break
                
            except Exception as e:
                print(f"获取ICP备案信息失败: {e}")
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
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
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
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
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
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
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
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
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
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': self._get_random_ua(),
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=operatingCondition'
            }
            
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
            else:
                return {
                    'success': False,
                    'message': 'APP信息请求返回为空',
                    'data': []
                }
            
            if data.get('status') != 0:
                return {
                    'success': False,
                    'error': f'APP信息查询失败: {data.get("msg", "未知错误")}',
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
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': self._get_random_ua(),
                'Referer': f'https://aiqicha.baidu.com/company_detail_{pid}?tab=operatingCondition'
            }
            
            response = self._make_request('GET', url, headers=headers, cookies=self.aiqicha_cookies, status_callback=status_callback)
            
            if response:
                data = response.json() if hasattr(response, 'json') else {}
            else:
                return {
                    'success': False,
                    'message': '微信公众号信息请求返回为空',
                    'data': []
                }
            
            if data.get('status') != 0:
                return {
                    'success': False,
                    'error': f'微信公众号信息查询失败: {data.get("msg", "未知错误")}',
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
        
        return result
    
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