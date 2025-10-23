#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hunter API 搜索引擎模块
鹰图平台网络资产搜索
"""

import requests
import json
import time
import base64
from typing import Dict, List, Optional
from PySide6.QtCore import QThread, Signal


class HunterAPI:
    """Hunter API 搜索类"""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = "https://hunter.qianxin.com/openApi"
        self.headers = {
            "Content-Type": "application/json"
        }
    
    def search(self, query: str, page: int = 1, page_size: int = 10, is_web: int = 3, port_filter: bool = False, full: bool = False, delay: int = 1) -> Dict:
        """搜索资产
        
        Args:
            query: 搜索语句
            page: 页码
            page_size: 每页数量
            is_web: 是否为web资产 (1:是, 2:不是, 3:全部)
            port_filter: 是否过滤端口
            full: 是否返回完整结果
            delay: 请求延迟时间(秒)
            
        Returns:
            搜索结果字典
        """
        try:
            url = f"{self.base_url}/search"
            
            # 使用URLSafe Base64编码查询语句，避免URLBase64转码错误
            query_encoded = base64.urlsafe_b64encode(query.encode('utf-8')).decode('ascii')
            
            params = {
                "api-key": self.api_key,
                "search": query_encoded,
                "page": page,
                "page_size": page_size,
                "is_web": is_web,
                "port_filter": port_filter
            }
            
            # 设置请求超时和重试机制
            max_retries = 2
            retry_count = 0
            
            while retry_count <= max_retries:
                try:
                    response = requests.get(url, params=params, headers=self.headers, timeout=20)
                    
                    if response.status_code == 200:
                        result = response.json()
                        # 直接返回Hunter API的原始格式
                        return result
                    else:
                        return {
                            'code': response.status_code,
                            'message': f'HTTP {response.status_code}: {response.text}',
                            'data': None
                        }
                except requests.exceptions.Timeout:
                    retry_count += 1
                    if retry_count <= max_retries:
                        # 增加超时时间并重试
                        timeout = 30 if retry_count == 1 else 45
                        print(f"请求超时，正在进行第{retry_count}次重试，超时设置为{timeout}秒...")
                    else:
                        # 超过最大重试次数，返回错误信息
                        return {
                            'code': 408,
                            'message': '请求超时，已达到最大重试次数',
                            'data': None
                        }
                except requests.exceptions.ConnectionError:
                    retry_count += 1
                    if retry_count <= max_retries:
                        print(f"连接错误，正在进行第{retry_count}次重试...")
                        time.sleep(2)  # 连接错误时等待2秒再重试
                    else:
                        # 超过最大重试次数，返回错误信息
                        return {
                            'code': 503,
                            'message': '连接错误，已达到最大重试次数',
                            'data': None
                        }
                
        except Exception as e:
            return {
                'code': 500,
                'message': f'请求异常: {str(e)}',
                'data': None
            }
            
        # 确保所有路径都有返回值
        return {
            'code': 500,
            'message': '未知错误',
            'data': None
        }
    
    def search_all_pages(self, query: str, max_pages: int = 10, page_size: int = 100):
        """搜索所有页面
        
        Args:
            query: 搜索语句
            max_pages: 最大页数
            page_size: 每页数量
            
        Yields:
            每页的搜索结果
        """
        for page in range(1, max_pages + 1):
            result = self.search(query, page=page, page_size=page_size)
            if result.get('success'):
                yield result
                # 如果返回结果少于请求数量，说明已经是最后一页
                if len(result.get('results', [])) < page_size:
                    break
            else:
                break
            
            # 添加延时避免请求过快
            time.sleep(1)
    
    def get_user_info(self) -> Dict:
        """获取用户信息"""
        try:
            url = f"{self.base_url}/userInfo"
            params = {
                "api-key": self.api_key
            }
            
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('code') == 200:
                    return {
                        'success': True,
                        'data': result.get('data', {})
                    }
                else:
                    return {
                        'success': False,
                        'error': result.get('message', '未知错误'),
                        'code': result.get('code')
                    }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'请求异常: {str(e)}'
            }
    
    def domain_search(self, domain: str, page: int = 1, page_size: int = 10) -> Dict:
        """域名搜索
        
        Args:
            domain: 域名
            page: 页码
            page_size: 每页数量
            
        Returns:
            搜索结果字典
        """
        try:
            url = f"{self.base_url}/subDomains"
            params = {
                "api-key": self.api_key,
                "domain": domain,
                "page": page,
                "page_size": page_size
            }
            
            response = requests.get(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('code') == 200:
                    data = result.get('data', {})
                    return {
                        'success': True,
                        'results': data.get('arr', []),
                        'total': data.get('total', 0),
                        'domain': domain
                    }
                else:
                    return {
                        'success': False,
                        'error': result.get('message', '未知错误'),
                        'code': result.get('code'),
                        'domain': domain
                    }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'domain': domain
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'请求异常: {str(e)}',
                'domain': domain
            }
    
    def search_assets(self, query: str, page: int = 1, page_size: int = 10, debug: bool = False, **kwargs) -> Dict:
        """搜索资产（别名方法）"""
        return self.search(query, page, page_size, **kwargs)
    
    def batch_search(self, queries: List[str], page_size: int = 100, is_web: int = 1, 
                    port_filter: bool = False, start_time: str = "", end_time: str = "", 
                    debug: bool = False, delay: float = 1.0, all_pages: bool = False,
                    progress_callback=None) -> Dict:
        """批量搜索资产
        
        Args:
            queries: 查询语句列表
            page_size: 每页数量
            is_web: 是否为Web资产 (1:是, 2:否, 3:全部)
            port_filter: 是否过滤端口
            start_time: 开始时间
            end_time: 结束时间
            debug: 调试模式
            delay: 查询间延时(秒)
            all_pages: 是否获取所有页面
            progress_callback: 进度回调函数
            
        Returns:
            批量查询结果字典
        """
        try:
            all_results = []
            total_queries = len(queries)
            
            for i, query in enumerate(queries, 1):
                query = query.strip()
                if not query:
                    continue
                
                if progress_callback:
                    progress_callback(f"正在处理第 {i}/{total_queries} 个查询: {query[:50]}...")
                
                if all_pages:
                    # 获取所有页面
                    results = self.search_all_pages_with_callback(
                        query=query,
                        page_size=page_size,
                        is_web=is_web,
                        port_filter=port_filter,
                        start_time=start_time,
                        end_time=end_time,
                        debug=debug,
                        delay=delay,
                        progress_callback=progress_callback
                    )
                    
                    if results:
                        for result in results:
                            if result and result.get('code') == 200:
                                data = result.get('data', {}) if result else {}
                                assets = data.get('arr', []) if data else []
                                for asset in assets:
                                    asset['source_query'] = query  # 添加来源查询标记
                                all_results.extend(assets)
                else:
                    # 单页查询
                    result = self.search_assets(
                        query=query,
                        page=1,
                        page_size=page_size,
                        is_web=is_web,
                        port_filter=port_filter,
                        start_time=start_time,
                        end_time=end_time,
                        debug=debug
                    )
                    
                    if result and result.get('code') == 200:
                        data = result.get('data', {})
                        assets = data.get('arr', [])
                        for asset in assets:
                            asset['source_query'] = query  # 添加来源查询标记
                        all_results.extend(assets)
                        
                        if progress_callback:
                            progress_callback(f"查询 {i} 完成，获得 {len(assets)} 个结果")
                    else:
                        if progress_callback:
                            progress_callback(f"查询 {i} 失败: {result.get('message', '未知错误')}")
                
                # 查询间延时 - 使用异步方式避免线程阻塞（减少延时以提高用户体验）
                if i < total_queries and delay > 0:
                    # 减少延时时间，提高用户体验
                    optimized_delay = min(delay, 1.0)  # 最大延时1秒
                    try:
                        # 尝试导入并使用AsyncDelay工具类
                        from modules.utils.async_delay import AsyncDelay
                        AsyncDelay.delay(
                            milliseconds=int(optimized_delay * 1000),
                            progress_callback=progress_callback
                        )
                    except (ImportError, ModuleNotFoundError):
                        # 如果导入失败，回退到传统方式
                        try:
                            from PySide6.QtCore import QThread, QTimer
                            from PySide6.QtWidgets import QApplication
                            # 确保QTimer和QApplication已定义
                            
                            if isinstance(self, QThread):
                                # 如果是QThread实例，使用QTimer进行异步延时
                                timer = QTimer()
                                timer.setSingleShot(True)
                                timer.timeout.connect(lambda: None)
                                timer.start(int(delay * 1000))  # 转换为毫秒
                        
                                if progress_callback:
                                    progress_callback(f"等待请求间隔 {delay} 秒...")
                                
                                # 等待定时器完成
                                loop = QTimer()
                                loop.setSingleShot(True)
                                loop.start(int(delay * 1000))
                                while loop.isActive():
                                    QApplication.processEvents()
                                    # 增加休眠时间，减少CPU占用
                                    time.sleep(0.05)
                            else:
                                # 如果不是QThread实例，使用传统的time.sleep
                                time.sleep(delay)
                        except (ImportError, NameError):
                            # 如果PySide6导入失败，使用传统的time.sleep
                            time.sleep(delay)
            
            # 构造最终结果
            final_result = {
                'code': 200,
                'data': {
                    'total': len(all_results),
                    'queries_processed': total_queries,
                    'arr': all_results,
                    'account_type': ''
                },
                'message': 'success'
            }
            
            return final_result
            
        except Exception as e:
            return {
                'code': 500,
                'message': f'批量查询异常: {str(e)}',
                'data': {'arr': [], 'total': 0}
            }
    
    def search_all_pages_with_callback(self, query: str, max_pages: int = 10, page_size: int = 100,
                                      is_web: int = 1, port_filter: bool = False, 
                                      start_time: str = "", end_time: str = "",
                                      debug: bool = False, delay: float = 1.0,
                                      progress_callback=None, max_retries: int = 2):
        """搜索所有页面（带进度回调）
        
        Args:
            query: 搜索语句
            max_pages: 最大页数
            page_size: 每页数量
            is_web: 是否为Web资产
            port_filter: 是否过滤端口
            start_time: 开始时间
            end_time: 结束时间
            debug: 调试模式
            delay: 页面间延时
            progress_callback: 进度回调函数
            
        Yields:
            每页的搜索结果
        """
        for page in range(1, max_pages + 1):
            if progress_callback:
                progress_callback(f"正在获取第 {page}/{max_pages} 页...")
            
            # 添加重试机制
            retry_count = 0
            max_retries = 2
            result = None
            
            while retry_count <= max_retries and not result:
                try:
                    result = self.search_assets(
                        query=query,
                        page=page,
                        page_size=page_size,
                        is_web=is_web,
                        port_filter=port_filter,
                        start_time=start_time,
                        end_time=end_time,
                        debug=debug
                    )
                except Exception as e:
                    retry_count += 1
                    if retry_count <= max_retries:
                        if progress_callback:
                            progress_callback(f"查询失败，正在进行第{retry_count}次重试...")
                        time.sleep(2)  # 失败后等待2秒再重试
                    else:
                        if progress_callback:
                            progress_callback(f"查询失败，已达到最大重试次数: {str(e)}")
                        result = {
                            'code': 500,
                            'message': f'请求异常: {str(e)}',
                            'data': None
                        }
            
            if result and result.get('code') == 200:
                yield result
                
                # 检查是否还有更多数据
                data = result.get('data', {}) if result else {}
                assets = data.get('arr', []) if data else []
                if len(assets) < page_size:
                    break  # 没有更多数据了
            else:
                break  # 查询失败，停止
            
            # 添加延时避免请求过快 - 使用异步方式避免线程阻塞（减少延时以提高用户体验）
            if page < max_pages and delay > 0:
                # 减少延时时间，提高用户体验
                optimized_delay = min(delay, 1.0)  # 最大延时1秒
                try:
                    # 尝试导入并使用AsyncDelay工具类
                    from ...utils.async_delay import AsyncDelay
                    AsyncDelay.delay(
                        milliseconds=int(optimized_delay * 1000),
                        progress_callback=progress_callback
                    )
                except (ImportError, ModuleNotFoundError):
                    # 如果导入失败，回退到传统方式
                    try:
                        from PySide6.QtCore import QThread, QTimer
                        from PySide6.QtWidgets import QApplication
                    except ImportError:
                        pass
                    
                    if isinstance(self, QThread):
                        # 如果是QThread实例，使用QTimer进行异步延时
                        timer = QTimer()
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: None)
                        timer.start(int(delay * 1000))  # 转换为毫秒
                        
                        if progress_callback:
                            progress_callback(f"等待请求间隔 {delay} 秒...")
                        
                        # 等待定时器完成
                        loop = QTimer()
                        loop.setSingleShot(True)
                        loop.start(int(delay * 1000))
                        while loop.isActive():
                            QApplication.processEvents()
                            # 增加休眠时间，减少CPU占用
                            time.sleep(0.05)
                    else:
                        # 如果不是QThread实例，使用传统的time.sleep
                        time.sleep(delay)


class HunterSearchThread(QThread):
    """Hunter搜索线程"""
    progress_updated = Signal(str)
    search_completed = Signal(dict)
    
    def __init__(self, hunter_api, search_query, page_size, is_web, port_filter, 
                 start_time, end_time, debug, delay, all_pages=False, page=1):
        super().__init__()
        self.hunter_api = hunter_api
        self.search_query = search_query
        self.page_size = page_size
        self.is_web = is_web
        self.port_filter = port_filter
        self.start_time = start_time
        self.end_time = end_time
        self.debug = debug
        self.delay = delay
        self.all_pages = all_pages
        self.page = page
    
    def run(self):
        try:
            if self.all_pages:
                results = []
                for page_result in self.hunter_api.search_all_pages_with_callback(
                    query=self.search_query,
                    page_size=self.page_size,
                    is_web=self.is_web,
                    port_filter=self.port_filter,
                    start_time=self.start_time,
                    end_time=self.end_time,
                    debug=self.debug,
                    delay=self.delay,
                    progress_callback=self.progress_updated.emit
                ):
                    if page_result and page_result.get('code') == 200:
                        data = page_result.get('data', {})
                        assets = data.get('arr', [])
                        results.extend(assets)
                
                final_result = {
                    'code': 200,
                    'data': {
                        'total': len(results),
                        'arr': results
                    }
                }
                self.search_completed.emit(final_result)
            else:
                self.progress_updated.emit(f"正在搜索第{self.page}页...")
                results = self.hunter_api.search_assets(
                    query=self.search_query,
                    page=self.page,
                    page_size=self.page_size,
                    is_web=self.is_web,
                    port_filter=self.port_filter,
                    start_time=self.start_time,
                    end_time=self.end_time,
                    debug=self.debug
                )
                self.search_completed.emit(results)
        except Exception as e:
            self.search_completed.emit({'error': str(e)})


class HunterBatchSearchThread(QThread):
    """Hunter批量搜索线程"""
    progress_updated = Signal(str)
    search_completed = Signal(dict)
    
    def __init__(self, hunter_api, queries, page_size, is_web, port_filter, 
                 start_time, end_time, debug, delay, all_pages=False):
        super().__init__()
        self.hunter_api = hunter_api
        self.queries = queries
        self.page_size = page_size
        self.is_web = is_web
        self.port_filter = port_filter
        self.start_time = start_time
        self.end_time = end_time
        self.debug = debug
        self.delay = delay
        self.all_pages = all_pages
    
    def run(self):
        try:
            result = self.hunter_api.batch_search(
                queries=self.queries,
                page_size=self.page_size,
                is_web=self.is_web,
                port_filter=self.port_filter,
                start_time=self.start_time,
                end_time=self.end_time,
                debug=self.debug,
                delay=self.delay,
                all_pages=self.all_pages,
                progress_callback=self.progress_updated.emit
            )
            self.search_completed.emit(result)
        except Exception as e:
            self.search_completed.emit({'error': str(e)})


def main():
    """测试函数"""
    print("Hunter API 模块加载成功")
    
    # 测试批量搜索功能
    api = HunterAPI()
    test_queries = ["port:80", "title:管理"]
    
    def progress_callback(msg):
        print(f"进度: {msg}")
    
    print("测试批量搜索功能...")
    # 注意：需要有效的API Key才能实际测试
    # result = api.batch_search(test_queries, progress_callback=progress_callback)
    # print(f"批量搜索结果: {result}")


if __name__ == "__main__":
    main()