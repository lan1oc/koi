#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quake API 搜索引擎模块
360网络空间测绘搜索引擎
"""

import requests
import json
import time
from typing import Dict, List, Optional


class QuakeAPI:
    """Quake API 搜索类"""
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = "https://quake.360.cn/api/v3"
        self.headers = {
            "X-QuakeToken": self.api_key,
            "Content-Type": "application/json"
        }
    
    def search(self, query: str, size: int = 10, start: int = 0) -> Dict:
        """搜索资产
        
        Args:
            query: 搜索语句
            size: 返回数量
            start: 起始位置
            
        Returns:
            搜索结果字典
        """
        try:
            url = f"{self.base_url}/search/quake_service"
            data = {
                "query": query,
                "start": start,
                "size": size
            }
            
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'data': result.get('data', []),
                    'total': result.get('meta', {}).get('total', 0),
                    'query': query
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'query': query
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'请求异常: {str(e)}',
                'query': query
            }
    
    def get_user_info(self) -> Dict:
        """获取用户信息"""
        try:
            url = f"{self.base_url}/user/info"
            response = requests.get(url, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'data': response.json()
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
    
    @property
    def user_info(self) -> Dict:
        """用户信息属性"""
        return self.get_user_info()
    
    def domain_search(self, domain: str, size: int = 10, start: int = 0) -> Dict:
        """域名搜索"""
        query = f'hostname:"{domain}"'
        return self.search(query, size, start)
    
    def get_filterable_fields(self) -> Dict:
        """获取可过滤字段"""
        return {
            'success': True,
            'fields': [
                'ip', 'port', 'hostname', 'domain', 'title', 'country',
                'province', 'city', 'service', 'app', 'components', 'vulns'
            ]
        }
    
    def aggregation_search(self, query: str, field: str, size: int = 10) -> Dict:
        """聚合搜索"""
        try:
            url = f"{self.base_url}/search/quake_service"
            data = {
                "query": query,
                "start": 0,
                "size": size,
                "aggs": {
                    "field_agg": {
                        "terms": {
                            "field": field,
                            "size": size
                        }
                    }
                }
            }
            
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'aggregations': result.get('aggregations', {}),
                    'query': query
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'query': query
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'请求异常: {str(e)}',
                'query': query
            }
    
    def scroll_search(self, query: str, scroll_id: Optional[str] = None, size: int = 100) -> Dict:
        """滚动搜索"""
        try:
            if scroll_id:
                # 继续滚动
                url = f"{self.base_url}/search/scroll"
                data = {
                    "scroll_id": scroll_id,
                    "size": size
                }
            else:
                # 开始滚动搜索
                url = f"{self.base_url}/search/quake_service"
                data = {
                    "query": query,
                    "start": 0,
                    "size": size,
                    "scroll": "1m"
                }
            
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'data': result.get('data', []),
                    'scroll_id': result.get('scroll_id'),
                    'total': result.get('meta', {}).get('total', 0),
                    'query': query
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'query': query
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'请求异常: {str(e)}',
                'query': query
            }


    def batch_search(self, queries: List[str], size: int = 100, start: int = 0,
                    delay: float = 1.0, progress_callback=None) -> Dict:
        """批量搜索资产
        
        Args:
            queries: 查询语句列表
            size: 每个查询返回数量
            start: 起始位置
            delay: 查询间延时(秒)
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
                
                result = self.search(query=query, size=size, start=start)
                
                if result.get('success', False):
                    data = result.get('data', [])
                    for item in data:
                        if isinstance(item, dict):
                            item['source_query'] = query  # 添加来源查询标记
                    all_results.extend(data)
                    
                    if progress_callback:
                        progress_callback(f"查询 {i} 完成，获得 {len(data)} 个结果")
                else:
                    if progress_callback:
                        progress_callback(f"查询 {i} 失败: {result.get('error', '未知错误')}")
                
                # 查询间延时 - 使用异步方式避免线程阻塞
                if i < total_queries and delay > 0:
                    try:
                        # 尝试导入并使用AsyncDelay工具类
                        from modules.utils.async_delay import AsyncDelay
                        AsyncDelay.delay(
                            milliseconds=int(delay * 1000),
                            progress_callback=progress_callback
                        )
                    except (ImportError, ModuleNotFoundError):
                        # 如果导入失败，回退到传统方式
                        try:
                            from PySide6.QtCore import QThread, QTimer
                            from PySide6.QtWidgets import QApplication
                            
                            if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) and isinstance(getattr(self, 'parent', None), QThread)):
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
                'success': True,
                'data': all_results,
                'total': len(all_results),
                'queries_processed': total_queries,
                'message': 'Batch search completed successfully'
            }
            
            return final_result
            
        except Exception as e:
            return {
                'success': False,
                'error': f'批量查询异常: {str(e)}',
                'data': [],
                'total': 0
            }
    
    def search_with_pagination(self, query: str, total_size: int = 1000, page_size: int = 100,
                              delay: float = 1.0, progress_callback=None) -> Dict:
        """分页搜索资产
        
        Args:
            query: 搜索语句
            total_size: 总共需要获取的数量
            page_size: 每页数量
            delay: 页面间延时
            progress_callback: 进度回调函数
            
        Returns:
            搜索结果字典
        """
        try:
            all_results = []
            pages_needed = (total_size + page_size - 1) // page_size
            
            for page in range(pages_needed):
                start = page * page_size
                current_size = min(page_size, total_size - len(all_results))
                
                if progress_callback:
                    progress_callback(f"正在获取第 {page + 1}/{pages_needed} 页...")
                
                result = self.search(query=query, size=current_size, start=start)
                
                if result.get('success', False):
                    data = result.get('data', [])
                    all_results.extend(data)
                    
                    # 如果返回数据少于请求数量，说明没有更多数据了
                    if len(data) < current_size:
                        break
                else:
                    break  # 查询失败，停止
                
                # 检查是否已获取足够数据
                if len(all_results) >= total_size:
                    break
                
                # 添加延时避免请求过快 - 使用异步方式避免线程阻塞
                if page < pages_needed - 1 and delay > 0:
                    try:
                        # 尝试导入并使用AsyncDelay工具类
                        from ...utils.async_delay import AsyncDelay
                        AsyncDelay.delay(
                            milliseconds=int(delay * 1000),
                            progress_callback=progress_callback
                        )
                    except (ImportError, ModuleNotFoundError):
                        # 如果导入失败，回退到传统方式
                        try:
                            from PySide6.QtCore import QThread, QTimer
                            from PySide6.QtWidgets import QApplication
                            
                            if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) is not None and isinstance(getattr(self, 'parent', None), QThread)):
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
            
            return {
                'success': True,
                'data': all_results[:total_size],  # 限制返回数量
                'total': len(all_results),
                'query': query
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'data': [],
                'query': query
            }


def main():
    """测试函数"""
    print("Quake API 模块加载成功")
    
    # 测试批量搜索功能
    api = QuakeAPI()
    test_queries = ['port:80', 'service:"http"']
    
    def progress_callback(msg):
        print(f"进度: {msg}")
    
    print("测试批量搜索功能...")
    # 注意：需要有效的API Key才能实际测试
    # result = api.batch_search(test_queries, progress_callback=progress_callback)
    # print(f"批量搜索结果: {result}")
    
    print("测试分页搜索功能...")
    # result = api.search_with_pagination('port:80', total_size=500, progress_callback=progress_callback)
    # print(f"分页搜索结果: {result}")


if __name__ == "__main__":
    main()
