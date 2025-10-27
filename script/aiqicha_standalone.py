#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爱企查企业信息查询脚本（独立版本）
功能：通过企业名称查询企业的详细信息，包括基本信息、行业分类、ICP备案、员工联系方式等
使用前请先登录爱企查和寻客宝网站获取Cookie
"""

import requests
import json
import time
import urllib.parse
import random
import csv
import os
import argparse
import re
from datetime import datetime
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
        
        # 请求间隔配置（秒）
        self.min_delay = 0.3
        self.max_delay = 0.8
        self.last_request_time = 0
        
        # 响应输出配置
        self.output_dir = os.path.join(os.path.dirname(__file__), 'output', 'aiqicha')
        os.makedirs(self.output_dir, exist_ok=True)
        self.request_counter = 0
        
        # 设置通用请求头
        initial_ua = self._get_random_ua()
        self.session.headers.update({
            'User-Agent': initial_ua,
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
        })
        
        # 初始化Cookie（从用户输入获取）
        self.aiqicha_cookies = {}
        self.xunkebao_cookies = {}
    
    def setup_cookies(self):
        """设置Cookie（从config.json文件读取）"""
        print("="*60)
        print("🔧 爱企查企业信息查询工具（独立版本）")
        print("="*60)
        
        # 从config.json读取cookie
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 获取爱企查Cookie
            aiqicha_cookie_str = config.get('aiqicha', {}).get('cookie', '')
            if aiqicha_cookie_str:
                self.aiqicha_cookies = {}
                for item in aiqicha_cookie_str.split(';'):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        self.aiqicha_cookies[key] = value
                print(f"✅ 从config.json读取爱企查Cookie成功，包含{len(self.aiqicha_cookies)}个字段")
            else:
                print("⚠️  config.json中未找到爱企查Cookie，可能影响查询功能")
            
            # 获取寻客宝Cookie
            xunkebao_cookie_str = config.get('aiqicha', {}).get('xunkebao_cookie', '')
            if xunkebao_cookie_str:
                self.xunkebao_cookies = {}
                for item in xunkebao_cookie_str.split(';'):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        self.xunkebao_cookies[key] = value
                print(f"✅ 从config.json读取寻客宝Cookie成功，包含{len(self.xunkebao_cookies)}个字段")
            else:
                print("ℹ️  config.json中未找到寻客宝Cookie，将跳过联系方式查询")
                
        except FileNotFoundError:
            print(f"❌ 未找到配置文件: {config_path}")
            print("请确保config.json文件存在并包含正确的cookie配置")
            return False
        except json.JSONDecodeError:
            print(f"❌ 配置文件格式错误: {config_path}")
            return False
        except Exception as e:
            print(f"❌ 读取配置文件时出错: {e}")
            return False
        
        print("\n🚀 Cookie设置完成，开始查询...")
        print("="*60)
        return True
    
    def _get_random_ua(self):
        """获取随机PC端User-Agent（避免移动端）"""
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
        if self.use_fake_ua:
            try:
                # 尝试多次获取，过滤掉移动端UA
                for _ in range(10):
                    ua = self.ua.random
                    # 检查是否为移动端UA
                    mobile_keywords = ['Mobile', 'Android', 'iPhone', 'iPad', 'BlackBerry', 'Windows Phone']
                    if not any(keyword in ua for keyword in mobile_keywords):
                        return ua
            except Exception:
                pass
        
        # 备用：从PC端UA列表中随机选择
        return random.choice(pc_user_agents)
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        new_ua = self._get_random_ua()
        self.session.headers.update({'User-Agent': new_ua})
        return new_ua
    
    def _anti_crawl_delay(self, status_callback=None):
        """反爬延时控制"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        min_interval = random.uniform(self.min_delay, self.max_delay)
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            message = f"爱企查反爬延时: {sleep_time:.2f}秒"
            print(message)
            if status_callback:
                status_callback(message)
            time.sleep(sleep_time)
        
        self.last_request_time = int(time.time())
    
    def _save_response(self, response, url, method):
        """保存响应到文件"""
        try:
            self.request_counter += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 从URL中提取有意义的文件名部分
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(url)
            path_parts = parsed_url.path.strip('/').split('/')
            query_params = parse_qs(parsed_url.query)
            
            # 构建文件名
            filename_parts = []
            if path_parts and path_parts[0]:
                filename_parts.append(path_parts[-1])  # 使用路径的最后一部分
            
            # 添加查询参数中的关键信息
            if 'q' in query_params:
                filename_parts.append(f"q_{query_params['q'][0][:20]}")  # 限制长度
            elif 'pid' in query_params:
                filename_parts.append(f"pid_{query_params['pid'][0]}")
            
            if not filename_parts:
                filename_parts.append("request")
            
            filename = f"{self.request_counter:03d}_{timestamp}_{method.lower()}_{'-'.join(filename_parts)}"
            # 清理文件名中的非法字符
            filename = "".join(c for c in filename if c.isalnum() or c in ('-', '_', '.'))[:100]
            
            # 保存响应头信息
            headers_file = os.path.join(self.output_dir, f"{filename}_headers.json")
            headers_data = {
                'url': url,
                'method': method,
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'timestamp': timestamp
            }
            with open(headers_file, 'w', encoding='utf-8') as f:
                json.dump(headers_data, f, ensure_ascii=False, indent=2)
            
            # 保存响应内容
            content_file = os.path.join(self.output_dir, f"{filename}_content.txt")
            with open(content_file, 'w', encoding='utf-8') as f:
                f.write(response.text)
                
        except Exception as e:
            print(f"保存响应失败: {e}")
    
    def _make_request(self, method, url, status_callback=None, **kwargs):
        """统一的请求方法，包含反爬措施"""
        self._anti_crawl_delay(status_callback=status_callback)
        
        if random.random() < 0.3:
            self._rotate_user_agent()
        
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 10
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = self.session.post(url, **kwargs)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            # 保存响应到文件
            self._save_response(response, url, method)
            return response
            
        except requests.exceptions.Timeout:
            if status_callback:
                status_callback("请求超时，正在重试...")
            kwargs['timeout'] = 20
            if method.upper() == 'GET':
                response = self.session.get(url, **kwargs)
            elif method.upper() == 'POST':
                response = self.session.post(url, **kwargs)
            
            # 保存重试后的响应
            self._save_response(response, url, method)
            return response
    
    def search_company(self, company_name: str, max_retries: int = 3, status_callback=None) -> Optional[Dict]:
        """搜索企业（简化版）"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
                
        update_status(f"正在搜索企业: {company_name}")
        
        encoded_name = urllib.parse.quote(company_name)
        url = f"https://aiqicha.baidu.com/s?q={encoded_name}&t=0"
        
        headers = {
            'Host': 'aiqicha.baidu.com',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self._get_random_ua(),
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
                
                # 额外延迟，确保JavaScript完全加载
                update_status("等待页面完全加载...")
                time.sleep(3)
                
                response.raise_for_status()
                html_content = response.text
                
                # 检查反爬限制
                if self._check_anti_crawler(html_content):
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # 指数退避
                        print(f"检测到反爬限制，等待{wait_time}秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print("多次遇到反爬限制，查询失败")
                        return None
                
                # 提取数据
                data = self._extract_page_data(html_content)
                if data:
                    return data
                
                # 尝试备用数据提取方案
                update_status("尝试备用数据提取方案...")
                backup_data = self._extract_backup_data(html_content)
                if backup_data:
                    return backup_data
                
                if attempt < max_retries - 1:
                    print(f"数据提取失败，1秒后重试...")
                    time.sleep(1)
                else:
                    print("多次尝试后仍无法提取数据")
                    return {}
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"请求异常: {e}，2秒后重试...")
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
            "验证码", "captcha", "人机验证", "安全验证",
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
        """从HTML中提取页面数据（增强版）"""
        import re
        
        # 方法1: 寻找 window.pageData 的完整JSON
        def extract_complete_json(pattern, content):
            match = re.search(pattern, content)
            if not match:
                return None
                
            start_pos = match.start(1)
            json_start = content[start_pos:]
            
            # 手动解析JSON，处理嵌套的大括号
            brace_count = 0
            json_end = 0
            in_string = False
            escape_next = False
            
            for i, char in enumerate(json_start):
                if escape_next:
                    escape_next = False
                    continue
                    
                if char == '\\':
                    escape_next = True
                    continue
                    
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                    
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
            
            if json_end > 0:
                return json_start[:json_end]
            return None
        
        # 尝试多种模式提取数据
        patterns = [
            r'window\.pageData\s*=\s*({)',  # 匹配开始的大括号
            r'window\.pageData\s*=\s*(\{.*?\})\s*;',  # 简单模式
            r'pageData\s*=\s*({)',  # 备用模式
        ]
        
        for pattern in patterns:
            try:
                if pattern.endswith('({)'):
                    # 使用完整JSON提取
                    json_str = extract_complete_json(pattern, html_content)
                else:
                    # 使用正则表达式
                    match = re.search(pattern, html_content, re.DOTALL)
                    json_str = match.group(1) if match else None
                
                if json_str:
                    # 清理和修复JSON字符串
                    json_str = json_str.strip()
                    
                    # 修复常见的JSON问题
                    json_str = re.sub(r'[\r\n\t]+', ' ', json_str)  # 替换换行符和制表符
                    json_str = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', json_str)  # 修复转义字符
                    
                    try:
                        data = json.loads(json_str)
                        
                        # 检查数据结构
                        if (data and isinstance(data, dict) and 'result' in data and 
                            isinstance(data['result'], dict) and 'resultList' in data['result'] and 
                            data['result']['resultList']):
                            
                            first_result = data['result']['resultList'][0]
                            company_name = first_result.get('entName', '未知')
                            
                            # 处理Unicode编码
                            if '\\u' in company_name:
                                try:
                                    company_name = company_name.encode().decode('unicode_escape')
                                except:
                                    pass
                            
                            print(f"找到企业: {company_name}")
                            print(f"使用模式: {pattern}")
                            return data
                            
                    except json.JSONDecodeError as e:
                        print(f"JSON解析失败 (模式 {pattern}): {e}")
                        continue
                        
            except Exception as e:
                print(f"提取失败 (模式 {pattern}): {e}")
                continue
        
        # 如果所有方法都失败，尝试查找任何包含企业数据的JSON
        print("尝试查找页面中的其他JSON数据...")
        json_patterns = [
            r'<script[^>]*>.*?({[^<]*"entName"[^<]*})[^<]*</script>',
            r'({[^}]*"entName"[^}]*})',
            r'window\.[a-zA-Z_$][a-zA-Z0-9_$]*\s*=\s*({[^;]*})\s*;'
        ]
        
        for pattern in json_patterns:
            try:
                matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, dict) and ('entName' in str(data) or 'result' in data):
                            print(f"找到备用数据源")
                            return data
                    except:
                        continue
            except:
                continue
        
        print("无法提取数据")
        return None
    
    def _extract_backup_data(self, html_content: str) -> Optional[Dict]:
        """备用数据提取方法，尝试从各种可能的位置提取企业数据"""
        print("执行备用数据提取...")
        
        # 备用提取模式
        backup_patterns = [
            # 查找任何包含regNo（统一信用代码）的JSON
            r'({[^}]*"regNo"[^}]*})',
            # 查找包含企业基本信息的JSON
            r'window\.[a-zA-Z_$][a-zA-Z0-9_$]*\s*=\s*({[^;]*"entName"[^;]*})\s*;',
            # 查找script标签中的JSON数据
            r'<script[^>]*>.*?({[^<]*"entName"[^<]*})[^<]*</script>',
            # 查找data属性中的JSON
            r'data-[a-zA-Z-]*\s*=\s*["\']({[^"\']*})["\']',
            # 查找任何包含企业列表的JSON
            r'({[^}]*"resultList"[^}]*})',
            # 查找React组件的props
            r'<div[^>]*data-reactroot[^>]*>.*?({[^}]*"entName"[^}]*})',
        ]
        
        for i, pattern in enumerate(backup_patterns):
            try:
                print(f"尝试备用模式 {i+1}: {pattern[:50]}...")
                matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                
                for match in matches:
                    try:
                        # 尝试解析JSON
                        if isinstance(match, str) and match.strip().startswith('{'):
                            data = json.loads(match)
                            
                            # 检查是否包含有效的企业数据
                            if isinstance(data, dict):
                                # 检查是否包含企业名称或统一信用代码
                                data_str = str(data).lower()
                                if any(key in data_str for key in ['entname', 'regno', 'resultlist', 'companyname']):
                                    print(f"备用模式 {i+1} 找到有效数据")
                                    return data
                                    
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        print(f"备用模式 {i+1} 处理异常: {e}")
                        continue
                        
            except Exception as e:
                print(f"备用模式 {i+1} 匹配异常: {e}")
                continue
        
        # 最后尝试：查找页面中所有可能的JSON数据
        print("尝试提取页面中所有JSON数据...")
        try:
            # 查找所有可能的JSON对象
            all_json_pattern = r'({[^{}]*(?:{[^{}]*}[^{}]*)*})'
            matches = re.findall(all_json_pattern, html_content)
            
            for match in matches:
                try:
                    if len(match) > 50 and len(match) < 10000:  # 合理的JSON长度
                        data = json.loads(match)
                        if isinstance(data, dict):
                            data_str = str(data).lower()
                            # 更宽松的检查条件
                            if any(keyword in data_str for keyword in ['name', 'company', 'ent', 'reg', 'credit']):
                                print("找到可能的企业数据")
                                return data
                except:
                    continue
                    
        except Exception as e:
            print(f"全局JSON提取异常: {e}")
        
        print("备用数据提取失败")
        return None
    
    def get_company_detail(self, pid: str) -> Optional[Dict]:
        """获取企业详情页信息"""
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
                html_content = response.text
                
                import re
                
                # 使用增强的数据提取方法
                def extract_detail_json(content):
                    patterns = [
                        r'window\.pageData\s*=\s*({)',  # 完整JSON提取
                        r'window\.pageData\s*=\s*(\{.*?\})\s*;',  # 简单模式
                        r'pageData\s*=\s*({)',  # 备用模式
                    ]
                    
                    for pattern in patterns:
                        try:
                            if pattern.endswith('({)'):
                                # 手动解析完整JSON
                                match = re.search(pattern, content)
                                if not match:
                                    continue
                                    
                                start_pos = match.start(1)
                                json_start = content[start_pos:]
                                
                                brace_count = 0
                                json_end = 0
                                in_string = False
                                escape_next = False
                                
                                for i, char in enumerate(json_start):
                                    if escape_next:
                                        escape_next = False
                                        continue
                                        
                                    if char == '\\':
                                        escape_next = True
                                        continue
                                        
                                    if char == '"' and not escape_next:
                                        in_string = not in_string
                                        continue
                                        
                                    if not in_string:
                                        if char == '{':
                                            brace_count += 1
                                        elif char == '}':
                                            brace_count -= 1
                                            if brace_count == 0:
                                                json_end = i + 1
                                                break
                                
                                if json_end > 0:
                                    json_str = json_start[:json_end]
                                else:
                                    continue
                            else:
                                match = re.search(pattern, content, re.DOTALL)
                                if not match:
                                    continue
                                json_str = match.group(1)
                            
                            # 清理JSON字符串
                            json_str = json_str.strip()
                            json_str = re.sub(r'[\r\n\t]+', ' ', json_str)
                            json_str = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', json_str)
                            
                            data = json.loads(json_str)
                            if 'result' in data:
                                print(f"获取到企业详情数据 (使用模式: {pattern})")
                                return data
                                
                        except Exception as e:
                            print(f"详情页提取失败 (模式 {pattern}): {e}")
                            continue
                    
                    return None
                
                data = extract_detail_json(html_content)
                if data:
                    return data
                else:
                    print("无法从详情页中提取数据")
                    return None
            else:
                return None
                
        except Exception as e:
            print(f"获取企业详情失败: {e}")
            return None
    
    def get_icp_info(self, pid: str) -> List[Dict]:
        """获取ICP备案信息"""
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
                    data = response.json()
                else:
                    print("ICP请求返回为空")
                    break
                
                if data.get('status') == 0 and 'data' in data:
                    if 'list' in data['data'] and isinstance(data['data']['list'], list):
                        icp_list = data['data']['list']
                        all_icp_data.extend(icp_list)
                        print(f"获取到第{page}页ICP备案信息，共{len(icp_list)}条")
                        
                        if len(icp_list) < 10 or page >= data['data'].get('pageCount', 1):
                            break
                    elif isinstance(data['data'], list):
                        icp_list = data['data']
                        all_icp_data.extend(icp_list)
                        print(f"获取到第{page}页ICP备案信息，共{len(icp_list)}条")
                        
                        if len(icp_list) < 10:
                            break
                    else:
                        print("ICP备案信息数据结构异常")
                        break
                    
                    page += 1
                else:
                    if data.get('status') != 0:
                        print(f"获取ICP备案信息失败: {data.get('message', '未知错误')}")
                    else:
                        print("未获取到ICP备案信息")
                    break
                
            except Exception as e:
                print(f"获取ICP备案信息失败: {e}")
                break
            
            if page > 10:
                print("已达到最大页数限制")
                break
        
        print(f"ICP备案信息获取完成，共{len(all_icp_data)}条")
        return all_icp_data
    
    def get_enterprise_id(self, pid: str) -> Optional[str]:
        """获取企业ID"""
        if not self.xunkebao_cookies:
            print("未设置寻客宝Cookie，跳过企业ID获取")
            return None
            
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
                data = response.json()
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
        """解锁资源"""
        if not self.xunkebao_cookies:
            return False
            
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
                data = response.json()
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
        """解锁股东信息"""
        if not self.xunkebao_cookies:
            return False
            
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
                data = response.json()
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
        """获取员工联系方式"""
        if not self.xunkebao_cookies:
            print("未设置寻客宝Cookie，跳过联系方式查询")
            return []
            
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
                data = response.json()
            else:
                print("请求返回为空")
                return []
            
            phone_numbers = []
            
            if not isinstance(data, dict):
                print(f"返回数据类型错误: {type(data).__name__}")
                return []
                
            data_field = data.get('data')
            
            if data_field is None:
                print("返回数据中没有data字段")
                return []
                
            if isinstance(data_field, list) and len(data_field) > 0:
                first_data = data_field[0]
                if isinstance(first_data, dict):
                    phone_numbers = first_data.get('allCellPhoneNOs', [])
                else:
                    print(f"data列表中的元素类型错误: {type(first_data).__name__}")
            elif isinstance(data_field, dict):
                phone_numbers = data_field.get('allCellPhoneNOs', [])
            else:
                print(f"未知的data字段类型: {type(data_field).__name__}")
                return []
            
            if phone_numbers:
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
                            'name': item.get('name', '')
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
                            'wechatName': item.get('wechatName', ''),
                            'wechatId': item.get('wechatId', '')
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
        """完整查询企业信息的主函数"""
        def update_status(message, step=None, completed=False):
            print(message)
            if status_callback:
                if completed and step is not None:
                    status_callback(message, step)
                else:
                    status_callback(message, step - 1 if step and step > 0 else 0)
        
        result = {
            'company_name': company_name,
            'basic_info': {},
            'industry_info': {},
            'icp_info': [],
            'contact_info': []
        }
        
        if not pid:
            update_status("第一步：搜索企业信息", 1)
            search_result = self.search_company(company_name)
            if not search_result:
                print("搜索失败，无法继续")
                return None
            
            if 'result' in search_result and 'resultList' in search_result['result']:
                first_result = search_result['result']['resultList'][0]
                pid = first_result.get('pid')
                
                result['basic_info'] = {
                    'legalPerson': first_result.get('legalPerson', ''),
                    'titleDomicile': first_result.get('titleDomicile', ''),
                    'regCap': first_result.get('regCap', ''),
                    'regNo': first_result.get('regNo', ''),
                    'email': first_result.get('email', ''),
                    'website': first_result.get('website', ''),
                    'telephone': first_result.get('telephone', '')
                }
                
                result['pid'] = pid
                
                print(f"提取到企业PID: {pid}")
                update_status("第一步完成：已获取企业基本信息", 1, completed=True)
            else:
                print("搜索结果格式异常")
                return result
        
        if pid:
            print(f"\n=== 使用PID: {pid} ===")
            
            update_status("第二步：获取企业详情", 2)
            detail_result = self.get_company_detail(pid)
            
            if detail_result and 'result' in detail_result:
                detail_data = detail_result['result']
                
                industry_more = detail_data.get('industryMore', {})
                result['industry_info'] = {
                    'industryCode1': industry_more.get('industryCode1', ''),
                    'industryCode2': industry_more.get('industryCode2', ''),
                    'industryCode3': industry_more.get('industryCode3', ''),
                    'industryCode4': industry_more.get('industryCode4', ''),
                    'industryNum': industry_more.get('industryNum', '')
                }
                
                email_info = detail_data.get('emailinfo', [])
                result['industry_info']['employee_emails'] = [item.get('email', '') for item in email_info]
                
                print(f"提取到行业信息和{len(email_info)}个员工邮箱")
                update_status("第二步完成：已获取企业详情", 2, completed=True)
            
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
            
            update_status("第六步：获取企业ID", 6)
            enterprise_id = self.get_enterprise_id(pid)
            update_status("第六步完成：已获取企业ID", 6, completed=True)
            
            if enterprise_id:
                update_status("第七步：解锁资源", 7)
                unlock1_success = self.unlock_resource(enterprise_id)
                update_status("第七步完成：资源解锁成功", 7, completed=True)
                
                if unlock1_success:
                    update_status("第八步：解锁股东信息", 8)
                    unlock2_success = self.unlock_stock_info()
                    
                    if unlock2_success:
                        update_status("第八步完成：股东信息解锁成功", 8, completed=True)
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
        """格式化输出查询结果"""
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
    
    def export_batch_results(self, batch_results: List[Dict], export_format: str = 'both') -> str:
        """导出批量查询结果
        
        Args:
            batch_results: 批量查询结果列表
            export_format: 导出格式 ('csv', 'txt', 'both')
            
        Returns:
            导出文件路径信息
        """
        if not batch_results:
            print("❌ 没有查询结果可导出")
            return ""
        
        # 生成文件名（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"aiqicha_batch_results_{timestamp}"
        
        exported_files = []
        
        # 导出CSV格式
        if export_format in ['csv', 'both']:
            csv_filename = f"{base_filename}.csv"
            self._export_to_csv(batch_results, csv_filename)
            exported_files.append(csv_filename)
            print(f"✅ CSV文件已导出: {csv_filename}")
        
        # 导出TXT格式
        if export_format in ['txt', 'both']:
            txt_filename = f"{base_filename}.txt"
            self._export_to_txt(batch_results, txt_filename)
            exported_files.append(txt_filename)
            print(f"✅ TXT文件已导出: {txt_filename}")
        
        return f"导出完成，文件: {', '.join(exported_files)}"
    
    def _export_to_csv(self, batch_results: List[Dict], filename: str):
        """导出为CSV格式"""
        with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
            fieldnames = [
                '企业名称', '法人代表', '注册资本', '统一社会信用代码', '企业地址',
                '企业邮箱', '企业网站', '企业电话', '行业大类', '行业中类', 
                '行业小类', '具体分类', '行业编号', '员工企业邮箱', 'ICP备案数量',
                'ICP域名列表', 'APP数量', 'APP名称', '微信公众号数量', '微信公众号名称',
                '员工手机数量', '员工手机列表', '查询状态'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in batch_results:
                if result.get('success', False):
                    data = result['data']
                    basic_info = data.get('basic_info', {})
                    industry_info = data.get('industry_info', {})
                    icp_info = data.get('icp_info', [])
                    contact_info = data.get('contact_info', [])
                    
                    # 处理ICP信息
                    icp_domains = []
                    for icp in icp_info:
                        domains = icp.get('domain', [])
                        if isinstance(domains, list):
                            icp_domains.extend(domains)
                        else:
                            icp_domains.append(str(domains))
                    
                    # 处理员工邮箱
                    employee_emails = industry_info.get('employee_emails', [])
                    if not isinstance(employee_emails, list):
                        employee_emails = []
                    
                    # 处理员工联系方式
                    if not isinstance(contact_info, list):
                        contact_info = []
                    
                    # 处理APP信息
                    app_info = data.get('app_info', [])
                    if not isinstance(app_info, list):
                        app_info = []
                    
                    # 处理微信公众号信息
                    wechat_info = data.get('wechat_info', [])
                    if not isinstance(wechat_info, list):
                        wechat_info = []
                    
                    # 处理APP名称列表
                    app_names = [app.get('name', '') for app in app_info if isinstance(app, dict) and app.get('name')]
                    
                    # 处理微信公众号名称列表
                    wechat_names = [wechat.get('wechatName', '') for wechat in wechat_info if isinstance(wechat, dict) and wechat.get('wechatName')]
                    
                    # 处理员工手机列表
                    contact_list = [phone for phone in contact_info if phone]
                    
                    # 计算最大行数（以最多值的字段为准）
                    max_items = max(len(icp_domains), len(app_names), len(wechat_names), len(contact_list), 1)
                    
                    # 基础企业信息（只在第一行显示）
                    base_info = {
                        '法人代表': basic_info.get('legalPerson', ''),
                        '注册资本': basic_info.get('regCap', ''),
                        '统一社会信用代码': basic_info.get('regNo', ''),
                        '企业地址': basic_info.get('titleDomicile', ''),
                        '企业邮箱': basic_info.get('email', ''),
                        '企业网站': basic_info.get('website', ''),
                        '企业电话': basic_info.get('telephone', ''),
                        '行业大类': industry_info.get('industryCode1', ''),
                        '行业中类': industry_info.get('industryCode2', ''),
                        '行业小类': industry_info.get('industryCode3', ''),
                        '具体分类': industry_info.get('industryCode4', ''),
                        '行业编号': industry_info.get('industryNum', ''),
                        '员工企业邮箱': '; '.join(employee_emails),
                        'ICP备案数量': len(icp_info),
                        'APP数量': len(app_info),
                        '微信公众号数量': len(wechat_info),
                        '员工手机数量': len(contact_info),
                        '查询状态': '成功'
                    }
                    
                    # 为每个值创建单独行
                    for i in range(max_items):
                        row = {'企业名称': data.get('company_name', '')}
                        
                        # 只在第一行填充基础信息
                        if i == 0:
                            row.update(base_info)
                        else:
                            # 其他行的基础信息留空
                            for key in base_info.keys():
                                row[key] = ''
                        
                        # 填充多值字段
                        row['ICP域名列表'] = icp_domains[i] if i < len(icp_domains) else ''
                        row['APP名称'] = app_names[i] if i < len(app_names) else ''
                        row['微信公众号名称'] = wechat_names[i] if i < len(wechat_names) else ''
                        row['员工手机列表'] = contact_list[i] if i < len(contact_list) else ''
                        
                        writer.writerow(row)
                else:
                    row = {
                        '企业名称': result.get('company_name', ''),
                        '法人代表': '', '注册资本': '', '统一社会信用代码': '', '企业地址': '',
                        '企业邮箱': '', '企业网站': '', '企业电话': '', '行业大类': '',
                        '行业中类': '', '行业小类': '', '具体分类': '', '行业编号': '',
                        '员工企业邮箱': '', 'ICP备案数量': '', 'ICP域名列表': '',
                        'APP数量': '', 'APP名称': '', '微信公众号数量': '', '微信公众号名称': '',
                        '员工手机数量': '', '员工手机列表': '',
                        '查询状态': f"失败: {result.get('error', '未知错误')}"
                    }
                    writer.writerow(row)
    
    def _export_to_txt(self, batch_results: List[Dict], filename: str):
        """导出为表格格式的TXT文件"""
        with open(filename, 'w', encoding='utf-8') as txtfile:
            # 使用制表符分隔，避免数据截断
            headers = ['序号', '企业名称', '法人代表', '注册资本', '统一社会信用代码', '企业地址',
                      '企业邮箱', '企业网站', '企业电话', '行业大类', '行业中类', 'ICP备案数',
                      '员工手机数', '查询状态']
            
            # 写入表头（使用制表符分隔）
            txtfile.write('\t'.join(headers) + '\n')
            
            # 写入数据行
            for i, result in enumerate(batch_results, 1):
                if result.get('success', False):
                    data = result['data']
                    basic_info = data.get('basic_info', {})
                    industry_info = data.get('industry_info', {})
                    icp_info = data.get('icp_info', [])
                    contact_info = data.get('contact_info', [])
                    
                    row_data = [
                        str(i),  # 序号
                        data.get('company_name', ''),  # 企业名称
                        basic_info.get('legalPerson', ''),  # 法人代表
                        basic_info.get('regCap', ''),  # 注册资本
                        basic_info.get('regNo', ''),  # 统一社会信用代码
                        basic_info.get('titleDomicile', ''),  # 企业地址
                        basic_info.get('email', ''),  # 企业邮箱
                        basic_info.get('website', ''),  # 企业网站
                        basic_info.get('telephone', ''),  # 企业电话
                        industry_info.get('industryCode1', ''),  # 行业大类
                        industry_info.get('industryCode2', ''),  # 行业中类
                        str(len(icp_info)),  # ICP备案数
                        str(len(contact_info)),  # 员工手机数
                        '成功'  # 查询状态
                    ]
                else:
                    row_data = [
                        str(i),  # 序号
                        result.get('company_name', ''),  # 企业名称
                        '', '', '', '',  # 法人代表, 注册资本, 统一社会信用代码, 企业地址
                        '', '', '',  # 企业邮箱, 企业网站, 企业电话
                        '', '',  # 行业大类, 行业中类
                        '', '',  # ICP备案数, 员工手机数
                        '失败'  # 查询状态
                    ]
                
                # 写入行数据（使用制表符分隔）
                txtfile.write('\t'.join(str(item) for item in row_data) + '\n')

def load_companies_from_file(file_path: str) -> List[str]:
    """从文件加载企业名单"""
    companies = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                company = line.strip()
                if company and not company.startswith('#'):  # 忽略空行和注释行
                    companies.append(company)
        print(f"📁 从文件 {file_path} 加载了 {len(companies)} 家企业")
        return companies
    except FileNotFoundError:
        print(f"❌ 文件 {file_path} 不存在")
        return []
    except Exception as e:
        print(f"❌ 读取文件 {file_path} 失败: {e}")
        return []

def batch_query(query: AiqichaQuery, companies: List[str], export_format: Optional[str] = None) -> List[Dict]:
    """执行批量查询"""
    print(f"\n🚀 开始批量查询 {len(companies)} 家企业...")
    
    # 收集批量查询结果
    batch_results = []
    
    for i, company in enumerate(companies, 1):
        print(f"\n{'='*60}")
        print(f"📊 正在查询第 {i}/{len(companies)} 家企业: {company}")
        print(f"{'='*60}")
        
        result = query.query_company_info(company)
        
        if result:
            query.print_result(result)
            batch_results.append({
                'success': True,
                'company_name': company,
                'data': result
            })
        else:
            print(f"❌ 查询企业 '{company}' 失败")
            batch_results.append({
                'success': False,
                'company_name': company,
                'error': '查询失败'
            })
        
        # 批量查询间的延时
        if i < len(companies):
            print(f"\n⏳ 等待 2 秒后查询下一家企业...")
            time.sleep(2)
    
    print(f"\n✅ 批量查询完成！共查询 {len(companies)} 家企业")
    
    # 自动导出或询问导出
    if export_format:
        query.export_batch_results(batch_results, export_format)
    else:
        # 询问是否导出结果
        print("\n📤 是否导出查询结果？")
        print("1. 导出为CSV格式")
        print("2. 导出为TXT格式")
        print("3. 同时导出CSV和TXT格式")
        print("4. 不导出")
        export_choice = input("> ").strip()
        
        if export_choice == "1":
            query.export_batch_results(batch_results, 'csv')
        elif export_choice == "2":
            query.export_batch_results(batch_results, 'txt')
        elif export_choice == "3":
            query.export_batch_results(batch_results, 'both')
        else:
            print("📋 跳过导出")
    
    return batch_results

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='爱企查企业信息查询工具（独立版本）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  python aiqicha_standalone.py                    # 交互式查询
  python aiqicha_standalone.py -c "杭州安恒信息"    # 单个企业查询
  python aiqicha_standalone.py -f companies.txt   # 从文件批量查询
  python aiqicha_standalone.py -f companies.txt -o csv  # 批量查询并导出CSV
  
文件格式:
  每行一个企业名称，支持#开头的注释行
  示例:
    # 这是注释
    杭州安恒信息技术股份有限公司
    阿里巴巴集团控股有限公司
    '''
    )
    
    parser.add_argument('-c', '--company', 
                       help='查询单个企业（企业名称）')
    parser.add_argument('-f', '--file', 
                       help='从文件批量查询（文件路径，每行一个企业名称）')
    parser.add_argument('-o', '--output', 
                       choices=['csv', 'txt', 'both'],
                       help='导出格式（仅批量查询时有效）')
    
    args = parser.parse_args()
    
    # 创建查询实例
    query = AiqichaQuery()
    
    # 设置Cookie
    query.setup_cookies()
    
    # 根据参数执行不同的查询模式
    if args.company:
        # 单个企业查询
        print(f"\n📝 查询企业: {args.company}")
        result = query.query_company_info(args.company)
        
        if result:
            query.print_result(result)
        else:
            print(f"❌ 查询企业 '{args.company}' 失败")
            
    elif args.file:
        # 从文件批量查询
        companies = load_companies_from_file(args.file)
        if companies:
            batch_query(query, companies, args.output)
        else:
            print("❌ 没有有效的企业名称可查询")
            return
            
    else:
        # 交互式模式
        print("\n📋 请选择查询模式:")
        print("1. 单个企业查询")
        print("2. 批量企业查询")
        mode = input("> ").strip()
        
        if mode == "2":
            # 批量查询模式
            print("\n📝 批量查询模式")
            print("请输入企业名称，每行一个，输入空行结束:")
            
            companies = []
            while True:
                company = input("> ").strip()
                if not company:
                    break
                companies.append(company)
            
            if not companies:
                print("❌ 未输入任何企业名称")
                return
            
            batch_query(query, companies)
            
        else:
            # 单个查询模式
            print("\n📝 单个企业查询模式")
            company_name = input("请输入要查询的企业名称: ").strip()
            if not company_name:
                company_name = "杭州安恒信息技术股份有限公司"  # 默认示例
                print(f"使用默认示例: {company_name}")
            
            # 执行查询
            result = query.query_company_info(company_name)
            
            # 输出结果
            if result:
                query.print_result(result)
            else:
                print(f"❌ 查询企业 '{company_name}' 失败")
    
    print("\n🎉 查询完成，感谢使用！")

if __name__ == "__main__":
    main()