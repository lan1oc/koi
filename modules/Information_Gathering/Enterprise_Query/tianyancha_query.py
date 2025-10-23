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
from typing import Dict, List, Optional
try:
    from fake_useragent import UserAgent
    HAS_FAKE_UA = True
except ImportError:
    HAS_FAKE_UA = False

class TianyanchaQuery:
    def __init__(self, config_path=None):
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
        
        # 请求间隔配置（秒）- 天眼查反爬严格，但进一步减少延时以提高用户体验
        self.min_delay = 1.0
        self.max_delay = 2.0
        self.last_request_time = 0
        
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
        self.config_path = config_path or os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config.json')
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
    
    def _make_request(self, method, url, status_callback=None, **kwargs):
        """统一的请求方法，包含反爬措施"""
        # 反爬延时
        self._anti_crawl_delay(status_callback=status_callback)
        
        # 不进行任何随机化，完全按照原始请求包
        
        # 设置请求超时，防止请求卡死
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 15  # 设置15秒超时
        
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
            kwargs['timeout'] = 30
            try:
                if method.upper() == 'GET':
                    return self.session.get(url, **kwargs)
                elif method.upper() == 'POST':
                    return self.session.post(url, **kwargs)
                else:
                    return None
            except Exception as e:
                if status_callback:
                    status_callback(f"重试请求失败: {str(e)}")
                return None
    
    def search_company(self, company_name: str, status_callback=None) -> Dict:
        """
        第一步：搜索企业基本信息
        """
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
            'Upgrade-Insecure-Requests': '1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        }
        
        try:
            try:
                response = self._make_request('GET', url, headers=headers, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                else:
                    update_status("请求返回为空")
                    return {}
            except requests.exceptions.RequestException as e:
                update_status(f"请求失败: {str(e)}，正在重试...")
                # 网络异常时重试一次
                time.sleep(2)
                response = self._make_request('GET', url, headers=headers, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                else:
                    update_status("重试请求返回为空")
                    return {}
            
            # 从HTML中提取JSON数据
            if response and hasattr(response, 'text'):
                html_content = response.text
            else:
                update_status("响应对象无text属性")
                return {
                    'success': False,
                    'error': '响应对象无text属性',
                    'query': company_name
                }
            
            # 查找包含企业数据的JSON（在__NEXT_DATA__脚本标签中）
            pattern = r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>'
            match = re.search(pattern, html_content, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                try:
                    next_data = json.loads(json_str)
                    
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
                        companies = []
                        for company in company_list:
                            # 确保company是字典类型
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
        page_size = 10
        
        try:
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
                
                # 发送请求
                response = self._make_request('GET', icp_url, headers=headers, params=params, cookies=self.tianyancha_cookies, status_callback=status_callback)
                if response:
                    response.raise_for_status()
                    data = response.json() if hasattr(response, 'json') else {}
                else:
                    update_status("ICP请求返回为空")
                    return {
                        'success': False,
                        'message': 'ICP请求返回为空',
                        'data': []
                    }
                
                # 确保data是字典类型
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
                
                # 检查是否有数据
                if 'data' not in data or not data['data']:
                    break
                    
                # 检查是否到达最后一页
                if 'item' not in data['data'] or not data['data']['item']:
                    break
                    
                # 提取ICP记录
                for item in data['data']['item']:
                    icp_record = {
                        'ym': item.get('ym', ''),  # 域名
                        'webSite': item.get('webSite', []),  # URL列表
                        'webName': item.get('webName', ''),  # 网站名称
                        'liscense': item.get('liscense', '')  # 备案号
                    }
                    all_icp_records.append(icp_record)
                
                update_status(f"已获取第 {page_num} 页，共 {len(data['data']['item'])} 条记录")
                
                # 检查是否还有更多页
                if len(data['data']['item']) < page_size:
                    break
                    
                page_num += 1
                
                # 防止无限循环
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
                'error': f'ICP查询失败: {str(e)}',
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
    
    def query_company_complete(self, company_name: str, status_callback=None) -> Dict:
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
        
        # 只查询第一家企业的详细信息
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
        
        # 将所有信息添加到第一家企业信息中
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
        output.append(f"查询关键词: {result.get('query', '未知')}")
        
        # 确保companies字段存在且为列表
        companies = result.get('companies', [])
        if not isinstance(companies, list):
            return f"企业列表类型错误: {type(companies).__name__}"
            
        output.append(f"找到企业数量: {len(companies)}")
        output.append("\n" + "=" * 50)
        
        # 只显示第一家企业的详细信息
        if companies:
            company = companies[0]
            
            # 确保company是字典类型
            if not isinstance(company, dict):
                return f"企业信息类型错误: {type(company).__name__}"
                
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
                    result = self.query_company_complete(company)
                    
                    # 确保result是字典类型
                    if not isinstance(result, dict):
                        error_msg = f"查询结果类型错误: {type(result).__name__}"
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
                        continue
                    
                    if result.get('success', False):
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
                        error_msg = result.get('error', '查询失败')
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
                
                # 批量查询间的额外延时（进一步减少延时以提高用户体验）
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