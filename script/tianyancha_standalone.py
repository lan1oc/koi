#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天眼查企业信息查询脚本（独立版本）
功能：通过企业名称查询企业的详细信息，包括基本信息、ICP备案等
使用前请先登录天眼查网站获取Cookie
"""

import requests
import json
import time
import random
import re
import urllib.parse
import csv
import os
import argparse
from datetime import datetime
from typing import Dict, List, Optional
try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

class TianyanchaQuery:
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
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'
            ]
        
        # 请求间隔配置（秒）
        self.min_delay = 1.0
        self.max_delay = 2.0
        self.last_request_time = 0
        
        # 响应输出配置
        self.output_dir = os.path.join(os.path.dirname(__file__), 'output', 'tianyancha')
        os.makedirs(self.output_dir, exist_ok=True)
        self.request_counter = 0
        
        # 设置通用请求头
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
        
        # 初始化Cookie（从用户输入获取）
        self.tianyancha_cookies = {}
    
    def setup_cookies(self):
        """设置Cookie（从config.json文件读取）"""
        print("="*60)
        print("🔧 天眼查企业信息查询工具（独立版本）")
        print("="*60)
        
        # 从config.json读取cookie
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 获取天眼查Cookie
            tianyancha_cookie_str = config.get('tyc', {}).get('cookie', '')
            if tianyancha_cookie_str:
                self.tianyancha_cookies = {}
                for item in tianyancha_cookie_str.split(';'):
                    if '=' in item:
                        key, value = item.strip().split('=', 1)
                        self.tianyancha_cookies[key] = value
                print(f"✅ 从config.json读取天眼查Cookie成功，包含{len(self.tianyancha_cookies)}个字段")
            else:
                print("⚠️  config.json中未找到天眼查Cookie，可能影响查询功能")
                
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
    
    def _anti_crawl_delay(self, status_callback=None):
        """反爬延时控制"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        min_interval = random.uniform(self.min_delay, self.max_delay)
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            message = f"天眼查反爬延时: {sleep_time:.2f}秒"
            print(message)
            if status_callback:
                status_callback(message)
            time.sleep(sleep_time)
        
        self.last_request_time = int(time.time())
    
    def _get_random_ua(self):
        """获取随机User-Agent"""
        if self.use_fake_ua:
            try:
                return self.ua.random
            except Exception:
                return random.choice(self.user_agents)
        else:
            return random.choice(self.user_agents)
    
    def _rotate_user_agent(self):
        """轮换User-Agent"""
        new_ua = self._get_random_ua()
        self.session.headers.update({'User-Agent': new_ua})
        return new_ua
    
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
            if 'key' in query_params:
                filename_parts.append(f"key_{query_params['key'][0][:20]}")  # 限制长度
            elif 'id' in query_params:
                filename_parts.append(f"id_{query_params['id'][0]}")
            elif 'name' in query_params:
                filename_parts.append(f"name_{query_params['name'][0][:20]}")
            
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
        
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 15
        
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
            kwargs['timeout'] = 30
            try:
                if method.upper() == 'GET':
                    response = self.session.get(url, **kwargs)
                elif method.upper() == 'POST':
                    response = self.session.post(url, **kwargs)
                else:
                    return None
                
                # 保存重试后的响应
                self._save_response(response, url, method)
                return response
                
            except Exception as e:
                if status_callback:
                    status_callback(f"重试请求失败: {str(e)}")
                return None
    
    def search_company(self, company_name: str, status_callback=None) -> Dict:
        """搜索企业基本信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
        
        update_status(f"正在搜索企业: {company_name}")
        
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
                response = self._make_request('GET', url, headers=headers, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                    # 额外延迟，确保JavaScript完全加载
                    update_status("等待页面完全加载...")
                    time.sleep(3)
                else:
                    update_status("请求返回为空")
                    return {}
            except requests.exceptions.RequestException as e:
                update_status(f"请求失败: {str(e)}，正在重试...")
                time.sleep(2)
                response = self._make_request('GET', url, headers=headers, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                else:
                    update_status("重试请求返回为空")
                    return {}
            
            if response and hasattr(response, 'text'):
                html_content = response.text
            else:
                update_status("响应对象无text属性")
                return {
                    'success': False,
                    'error': '响应对象无text属性',
                    'query': company_name
                }
            
            # 查找包含企业数据的JSON（增强版）
            def extract_next_data(content):
                patterns = [
                    r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>',
                    r'<script[^>]*id="__NEXT_DATA__"[^>]*>({.*?})</script>',
                    r'__NEXT_DATA__[^>]*>({.*?})</script>',
                    r'window\.__NEXT_DATA__\s*=\s*({.*?});',
                ]
                
                for pattern in patterns:
                    try:
                        match = re.search(pattern, content, re.DOTALL)
                        if match:
                            json_str = match.group(1)
                            
                            # 清理JSON字符串
                            json_str = json_str.strip()
                            
                            # 修复常见的JSON问题
                            json_str = re.sub(r'[\r\n\t]+', ' ', json_str)
                            json_str = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', json_str)
                            
                            try:
                                data = json.loads(json_str)
                                print(f"成功提取__NEXT_DATA__ (使用模式: {pattern[:50]}...)")
                                return data
                            except json.JSONDecodeError as e:
                                print(f"JSON解析失败 (模式 {pattern[:30]}...): {e}")
                                continue
                    except Exception as e:
                        print(f"提取失败 (模式 {pattern[:30]}...): {e}")
                        continue
                
                return None
            
            next_data = extract_next_data(html_content)
            
            if next_data:
                try:
                    
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
                        companies = []
                        for company in company_list:
                            if not isinstance(company, dict):
                                update_status(f"公司数据类型错误: {type(company).__name__}，跳过此条记录")
                                continue
                                
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
                                'categoryNameLv1': company.get('categoryNameLv1', ''),
                                'categoryNameLv2': company.get('categoryNameLv2', ''),
                                'categoryNameLv3': company.get('categoryNameLv3', ''),
                                'categoryNameLv4': company.get('categoryNameLv4', '')
                            }
                            companies.append(company_info)
                        
                        update_status(f"找到 {len(companies)} 家企业")
                        return {
                            'success': True,
                            'companies': companies,
                            'query': company_name
                        }
                    else:
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
                # 尝试备用数据提取方案
                update_status("尝试备用数据提取方案...")
                
                # 查找任何包含企业信息的JSON数据
                backup_patterns = [
                    r'window\.[a-zA-Z_$][a-zA-Z0-9_$]*\s*=\s*({[^;]*"name"[^;]*})\s*;',
                    r'({[^}]*"creditCode"[^}]*})',
                    r'<script[^>]*>.*?({[^<]*"companyList"[^<]*})[^<]*</script>',
                    r'data-reactroot[^>]*>.*?({[^}]*"name"[^}]*})',
                ]
                
                for pattern in backup_patterns:
                    try:
                        matches = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                        for match in matches:
                            try:
                                data = json.loads(match)
                                if isinstance(data, dict) and ('name' in str(data) or 'creditCode' in str(data)):
                                    update_status("找到备用数据源")
                                    # 尝试构造标准格式的返回数据
                                    companies = []
                                    if 'companyList' in data:
                                        companies = data['companyList']
                                    elif isinstance(data, dict) and 'name' in data:
                                        companies = [data]
                                    
                                    if companies:
                                        return {
                                            'success': True,
                                            'companies': companies,
                                            'query': company_name
                                        }
                            except:
                                continue
                    except:
                        continue
                
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
    
    def query_icp_info(self, company_id: str, status_callback=None) -> Dict:
        """查询企业ICP备案信息"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
            
        update_status(f"正在查询企业ID {company_id} 的ICP备案信息")
        
        all_icp_records = []
        page_num = 1
        page_size = 10
        
        try:
            while True:
                icp_url = "https://capi.tianyancha.com/cloud-intellectual-property/intellectualProperty/icpRecordList"
                
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
                    'X-TYCID': self.tianyancha_cookies.get('TYCID', ''),
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
                
                response = self._make_request('GET', icp_url, headers=headers, params=params, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                    data = response.json()
                else:
                    update_status("ICP请求返回为空")
                    return {
                        'success': False,
                        'message': 'ICP请求返回为空',
                        'data': []
                    }
                
                if not isinstance(data, dict):
                    update_status(f"返回数据类型错误: {type(data).__name__}")
                    return {
                        'success': False,
                        'error': f'返回数据类型错误: {type(data).__name__}',
                        'company_id': company_id
                    }
                
                if data.get('state') != 'ok':
                    return {
                        'success': False,
                        'error': f'ICP查询失败: {data.get("message", "未知错误")}',
                        'company_id': company_id
                    }
                
                if 'data' not in data or not data['data']:
                    break
                    
                if 'item' not in data['data'] or not data['data']['item']:
                    break
                    
                for item in data['data']['item']:
                    icp_record = {
                        'ym': item.get('ym', ''),
                        'webSite': item.get('webSite', []),
                        'webName': item.get('webName', ''),
                        'liscense': item.get('liscense', '')
                    }
                    all_icp_records.append(icp_record)
                
                update_status(f"已获取第 {page_num} 页，共 {len(data['data']['item'])} 条记录")
                
                if len(data['data']['item']) < page_size:
                    break
                    
                page_num += 1
                
                if page_num > 10:
                    break
            
            update_status(f"ICP查询完成，共获取 {len(all_icp_records)} 条备案记录")
            
            return {
                'success': True,
                'icp_records': all_icp_records,
                'company_id': company_id
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'ICP查询异常: {str(e)}',
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
            
            response = self._make_request('GET', url, params=params, headers=headers, 
                                        cookies=self.tianyancha_cookies, status_callback=status_callback)
            
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
                        'name': item.get('name', ''),
                        'type': item.get('type', ''),
                        'classes': item.get('classes', '')
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
            
            response = self._make_request('GET', url, params=params, headers=headers, 
                                        cookies=self.tianyancha_cookies, status_callback=status_callback)
            
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
                        'title': item.get('title', ''),
                        'publicNum': item.get('publicNum', '')
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
    
    def query_company_complete(self, company_name: str, status_callback=None) -> Dict:
        """完整查询企业信息（包括基本信息和ICP备案）"""
        def update_status(message):
            print(message)
            if status_callback:
                status_callback(message)
            
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
        
        update_status(f"第一步完成：找到 {len(companies)} 家企业")
        
        first_company = companies[0]
        company_id = first_company['id']
        
        # 第二步：查询ICP备案信息
        update_status(f"第二步：查询 {first_company['name']} 的ICP备案信息")
        icp_result = self.query_icp_info(company_id, status_callback)
        
        # 第三步：查询APP信息
        update_status(f"第三步：查询 {first_company['name']} 的APP信息")
        app_result = self.query_app_info(company_id, status_callback)
        
        # 第四步：查询微信公众号信息
        update_status(f"第四步：查询 {first_company['name']} 的微信公众号信息")
        wechat_result = self.query_wechat_info(company_id, status_callback)
        
        # 合并所有查询结果
        first_company_complete = first_company.copy()
        
        # 添加ICP信息
        if icp_result and icp_result.get('success', False):
            first_company_complete['icp_records'] = icp_result.get('icp_records', [])
            update_status(f"第二步完成：ICP查询完成，共获取 {len(icp_result.get('icp_records', []))} 条备案记录")
        else:
            first_company_complete['icp_records'] = []
            error_msg = icp_result.get('error', '未知错误') if icp_result else '请求返回为空'
            update_status(f"ICP查询失败: {error_msg}")
        
        # 添加APP信息
        if app_result and app_result.get('success', False):
            first_company_complete['app_records'] = app_result.get('data', [])
            update_status(f"第三步完成：APP查询完成，共获取 {len(app_result.get('data', []))} 个APP")
        else:
            first_company_complete['app_records'] = []
            error_msg = app_result.get('error', '未知错误') if app_result else '请求返回为空'
            update_status(f"APP查询失败: {error_msg}")
        
        # 添加微信公众号信息
        if wechat_result and wechat_result.get('success', False):
            first_company_complete['wechat_records'] = wechat_result.get('data', [])
            update_status(f"第四步完成：微信公众号查询完成，共获取 {len(wechat_result.get('data', []))} 个公众号")
        else:
            first_company_complete['wechat_records'] = []
            error_msg = wechat_result.get('error', '未知错误') if wechat_result else '请求返回为空'
            update_status(f"微信公众号查询失败: {error_msg}")
        
        companies[0] = first_company_complete
        
        return {
            'success': True,
            'companies': companies,
            'query': company_name
        }
    
    def _clean_html_tags(self, text: str) -> str:
        """清理HTML标签"""
        if not text:
            return ''
        clean_text = re.sub(r'<[^>]+>', '', text)
        return clean_text.strip()
    
    def query_company_info(self, company_name: str, status_callback=None) -> Dict:
        """查询企业信息的主函数"""
        return self.query_company_complete(company_name, status_callback)
    
    def format_result(self, result: Dict) -> str:
        """格式化查询结果"""
        if not isinstance(result, dict):
            return f"查询结果类型错误: {type(result).__name__}"
            
        if not result.get('success', False):
            return f"查询失败: {result.get('error', '未知错误')}"
        
        output = []
        output.append(f"查询关键词: {result.get('query', '未知')}")
        
        companies = result.get('companies', [])
        if not isinstance(companies, list):
            return f"企业列表类型错误: {type(companies).__name__}"
            
        output.append(f"找到企业数量: {len(companies)}")
        output.append("\n" + "=" * 50)
        
        if companies:
            company = companies[0]
            
            if not isinstance(company, dict):
                return f"企业信息类型错误: {type(company).__name__}"
                
            output.append(f"企业名称: {company.get('name', '未知')}")
            output.append(f"法定代表人: {company.get('legalPersonName', '未知')}")
            output.append(f"注册资本: {company.get('regCapital', '未知')}")
            output.append(f"统一社会信用代码: {company.get('creditCode', '未知')}")
            output.append(f"注册地址: {company.get('regLocation', '未知')}")
            
            phone_list = company.get('phoneList', [])
            if phone_list and isinstance(phone_list, list):
                output.append(f"联系电话: {', '.join(phone_list)}")
                
            email_list = company.get('emailList', [])
            if email_list and isinstance(email_list, list):
                output.append(f"邮箱: {', '.join(email_list)}")
                
            websites = company.get('websites', '')
            if websites:
                output.append(f"网站: {websites}")
            
            categories = []
            for i in range(1, 5):
                cat = company.get(f'categoryNameLv{i}')
                if cat:
                    categories.append(cat)
            if categories:
                output.append(f"行业分类: {' > '.join(categories)}")
            
            icp_records = company.get('icp_records', [])
            if icp_records and isinstance(icp_records, list):
                output.append("\nICP备案信息:")
                for i, icp in enumerate(icp_records, 1):
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
                    if not isinstance(wechat, dict):
                        output.append(f"  公众号{i}: 数据类型错误 {type(wechat).__name__}")
                        continue
                        
                    output.append(f"  公众号{i}:")
                    output.append(f"    公众号名称: {wechat.get('title', '未知')}")
                    output.append(f"    微信号: {wechat.get('publicNum', '未知')}")
            else:
                output.append("\n暂无微信公众号信息")
        
        return "\n".join(output)
    
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
        base_filename = f"tianyancha_batch_results_{timestamp}"
        
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
                '企业名称', '法定代表人', '注册资本', '统一社会信用代码', '注册地址',
                '联系电话', '邮箱', '网站', '行业分类1', '行业分类2', 
                '行业分类3', '行业分类4', 'ICP备案数量', 'ICP域名列表', 
                'ICP网站名称列表', 'APP数量', 'APP名称', '微信公众号数量', '微信公众号名称', '查询状态'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in batch_results:
                if result.get('success', False):
                    data = result['data']
                    companies = data.get('companies', [])
                    
                    if companies:
                        company = companies[0]  # 取第一家企业
                        
                        # 处理ICP信息
                        icp_records = company.get('icp_records', [])
                        icp_domains = []
                        icp_names = []
                        for icp in icp_records:
                            if icp.get('ym'):
                                icp_domains.append(icp['ym'])
                            if icp.get('webName'):
                                icp_names.append(icp['webName'])
                        
                        # 处理行业分类
                        categories = []
                        for i in range(1, 5):
                            cat = company.get(f'categoryNameLv{i}', '')
                            categories.append(cat)
                        
                        # 处理APP信息
                        app_records = company.get('app_records', [])
                        
                        # 处理微信公众号信息
                        wechat_records = company.get('wechat_records', [])
                        
                        # 处理APP名称列表
                        app_names = [app.get('name', '') for app in app_records if isinstance(app, dict) and app.get('name')]
                        
                        # 处理微信公众号名称列表
                        wechat_names = [wechat.get('title', '') for wechat in wechat_records if isinstance(wechat, dict) and wechat.get('title')]
                        
                        # 计算最大行数（以最多值的字段为准）
                        max_items = max(len(icp_domains), len(icp_names), len(app_names), len(wechat_names), 1)
                        
                        # 基础企业信息（只在第一行显示）
                        base_info = {
                            '法定代表人': company.get('legalPersonName', ''),
                            '注册资本': company.get('regCapital', ''),
                            '统一社会信用代码': company.get('creditCode', ''),
                            '注册地址': company.get('regLocation', ''),
                            '联系电话': '; '.join(company.get('phoneList', [])),
                            '邮箱': '; '.join(company.get('emailList', [])),
                            '网站': company.get('websites', ''),
                            '行业分类1': categories[0],
                            '行业分类2': categories[1],
                            '行业分类3': categories[2],
                            '行业分类4': categories[3],
                            'ICP备案数量': len(icp_records),
                            'APP数量': len(app_records),
                            '微信公众号数量': len(wechat_records),
                            '查询状态': '成功'
                        }
                        
                        # 为每个值创建单独行
                        for i in range(max_items):
                            row = {'企业名称': company.get('name', '')}
                            
                            # 只在第一行填充基础信息
                            if i == 0:
                                row.update(base_info)
                            else:
                                # 其他行的基础信息留空
                                for key in base_info.keys():
                                    row[key] = ''
                            
                            # 填充多值字段
                            row['ICP域名列表'] = icp_domains[i] if i < len(icp_domains) else ''
                            row['ICP网站名称列表'] = icp_names[i] if i < len(icp_names) else ''
                            row['APP名称'] = app_names[i] if i < len(app_names) else ''
                            row['微信公众号名称'] = wechat_names[i] if i < len(wechat_names) else ''
                            
                            writer.writerow(row)
                    else:
                        row = {
                            '企业名称': result.get('company_name', ''),
                            '法定代表人': '', '注册资本': '', '统一社会信用代码': '', '注册地址': '',
                            '联系电话': '', '邮箱': '', '网站': '', '行业分类1': '',
                            '行业分类2': '', '行业分类3': '', '行业分类4': '',
                            'ICP备案数量': '', 'ICP域名列表': '', 'ICP网站名称列表': '',
                            'APP数量': '', 'APP名称': '', '微信公众号数量': '', '微信公众号名称': '',
                            '查询状态': '成功但无企业信息'
                        }
                        writer.writerow(row)
                else:
                    row = {
                        '企业名称': result.get('company_name', ''),
                        '法定代表人': '', '注册资本': '', '统一社会信用代码': '', '注册地址': '',
                        '联系电话': '', '邮箱': '', '网站': '', '行业分类1': '',
                        '行业分类2': '', '行业分类3': '', '行业分类4': '',
                        'ICP备案数量': '', 'ICP域名列表': '', 'ICP网站名称列表': '',
                        'APP数量': '', 'APP名称': '', '微信公众号数量': '', '微信公众号名称': '',
                        '查询状态': f"失败: {result.get('error', '未知错误')}"
                    }
                    writer.writerow(row)
    
    def _export_to_txt(self, batch_results: List[Dict], filename: str):
        """导出为表格格式的TXT文件"""
        with open(filename, 'w', encoding='utf-8') as txtfile:
            # 使用制表符分隔，避免数据截断
            headers = ['序号', '企业名称', '法定代表人', '注册资本', '统一社会信用代码', '注册地址',
                      '联系电话', '邮箱', '网站', '行业分类1', '行业分类2', 'ICP备案数',
                      'APP数量', 'APP名称', '微信公众号数', '微信公众号', '查询状态']
            
            # 写入表头（使用制表符分隔）
            txtfile.write('\t'.join(headers) + '\n')
            
            # 写入数据行
            for i, result in enumerate(batch_results, 1):
                if result.get('success', False):
                    data = result['data']
                    companies = data.get('companies', [])
                    
                    if companies:
                        company = companies[0]
                        icp_records = company.get('icp_records', [])
                        
                        # 移除截断逻辑，保留完整数据
                        
                        # 处理行业分类
                        categories = []
                        for j in range(1, 5):
                            cat = company.get(f'categoryNameLv{j}', '')
                            if cat:
                                categories.append(cat)
                        
                        # 安全处理列表字段
                        phone_list = company.get('phoneList', [])
                        if not isinstance(phone_list, list):
                            phone_list = []
                        
                        email_list = company.get('emailList', [])
                        if not isinstance(email_list, list):
                            email_list = []
                        
                        # 处理APP信息
                        app_records = company.get('app_records', [])
                        if not isinstance(app_records, list):
                            app_records = []
                        app_names = [app.get('name', '') for app in app_records if isinstance(app, dict)]
                        
                        # 处理微信公众号信息
                        wechat_records = company.get('wechat_records', [])
                        if not isinstance(wechat_records, list):
                            wechat_records = []
                        wechat_names = [wechat.get('title', '') for wechat in wechat_records if isinstance(wechat, dict)]
                        
                        row_data = [
                            str(i),  # 序号
                            company.get('name', ''),  # 企业名称
                            company.get('legalPersonName', ''),  # 法定代表人
                            company.get('regCapital', ''),  # 注册资本
                            company.get('creditCode', ''),  # 统一社会信用代码
                            company.get('regLocation', ''),  # 注册地址
                            '; '.join(phone_list),  # 联系电话
                            '; '.join(email_list),  # 邮箱
                            company.get('websites', ''),  # 网站
                            categories[0] if len(categories) > 0 else '',  # 行业分类1
                            categories[1] if len(categories) > 1 else '',  # 行业分类2
                            str(len(icp_records)),  # ICP备案数
                            str(len(app_records)),  # APP数量
                            '; '.join(app_names),  # APP名称
                            str(len(wechat_records)),  # 微信公众号数
                            '; '.join(wechat_names),  # 微信公众号
                            '成功'  # 查询状态
                        ]
                    else:
                        row_data = [
                            str(i),  # 序号
                            result.get('company_name', ''),  # 企业名称
                            '', '', '', '',  # 法定代表人, 注册资本, 统一社会信用代码, 注册地址
                            '', '', '',  # 联系电话, 邮箱, 网站
                            '', '',  # 行业分类1, 行业分类2
                            '', '', '', '', '',  # ICP备案数, APP数量, APP名称, 微信公众号数, 微信公众号
                            '无信息'  # 查询状态
                        ]
                else:
                    row_data = [
                        str(i),  # 序号
                        result.get('company_name', ''),  # 企业名称
                        '', '', '', '',  # 法定代表人, 注册资本, 统一社会信用代码, 注册地址
                        '', '', '',  # 联系电话, 邮箱, 网站
                        '', '',  # 行业分类1, 行业分类2
                        '', '', '', '', '',  # ICP备案数, APP数量, APP名称, 微信公众号数, 微信公众号
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

def batch_query(query: TianyanchaQuery, companies: List[str], export_format: Optional[str] = None) -> List[Dict]:
    """执行批量查询"""
    print(f"\n🚀 开始批量查询 {len(companies)} 家企业...")
    
    # 收集批量查询结果
    batch_results = []
    
    for i, company in enumerate(companies, 1):
        print(f"\n{'='*60}")
        print(f"📊 正在查询第 {i}/{len(companies)} 家企业: {company}")
        print(f"{'='*60}")
        
        result = query.query_company_complete(company)
        
        print("\n" + "=" * 60)
        print(query.format_result(result))
        
        # 收集结果
        if result.get('success', False):
            batch_results.append({
                'success': True,
                'company_name': company,
                'data': result
            })
        else:
            batch_results.append({
                'success': False,
                'company_name': company,
                'error': result.get('error', '查询失败')
            })
        
        # 批量查询间的延时
        if i < len(companies):
            print(f"\n⏳ 等待 3 秒后查询下一家企业...")
            time.sleep(3)
    
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
        description='天眼查企业信息查询工具（独立版本）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  python tianyancha_standalone.py                    # 交互式查询
  python tianyancha_standalone.py -c "西藏国玉"       # 单个企业查询
  python tianyancha_standalone.py -f companies.txt   # 从文件批量查询
  python tianyancha_standalone.py -f companies.txt -o csv  # 批量查询并导出CSV
  
文件格式:
  每行一个企业名称，支持#开头的注释行
  示例:
    # 这是注释
    西藏国玉投资有限公司
    杭州安恒信息技术股份有限公司
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
    query = TianyanchaQuery()
    
    # 设置Cookie
    query.setup_cookies()
    
    # 根据参数执行不同的查询模式
    if args.company:
        # 单个企业查询
        print(f"\n📝 查询企业: {args.company}")
        result = query.query_company_complete(args.company)
        
        print("\n" + "=" * 60)
        print(query.format_result(result))
            
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
                company_name = "西藏国玉"  # 默认示例
                print(f"使用默认示例: {company_name}")
            
            # 执行查询
            result = query.query_company_complete(company_name)
            
            # 输出结果
            print("\n" + "=" * 60)
            print(query.format_result(result))
    
    print("\n🎉 查询完成，感谢使用！")

if __name__ == "__main__":
    main()