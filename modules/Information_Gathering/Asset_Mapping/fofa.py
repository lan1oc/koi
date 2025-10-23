#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FOFA API 搜索引擎模块
网络空间测绘搜索引擎
"""

import requests
import json
import base64
import time
from typing import Dict, List, Optional


class FOFASearcher:
    """FOFA API 搜索类"""
    
    def __init__(self, api_key: str = "", email: str = ""):
        self.api_key = api_key
        self.email = email
        self.base_url = "https://fofa.info/api/v1"
        
    def search(self, query: str, size: int = 10, page: int = 1, fields: str = "host,ip,port,title,country", full: bool = False) -> Dict:
        """搜索资产
        
        Args:
            query: 搜索语句
            size: 返回数量
            page: 页码
            fields: 返回字段
            
        Returns:
            搜索结果字典
        """
        try:
            # Base64编码查询语句
            query_encoded = base64.b64encode(query.encode()).decode()
            
            url = f"{self.base_url}/search/all"
            params = {
                "email": self.email,
                "key": self.api_key,
                "qbase64": query_encoded,
                "size": size,
                "page": page,
                "fields": fields
            }
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('error'):
                    return {
                        'success': False,
                        'error': result.get('errmsg', '未知错误'),
                        'query': query
                    }
                
                # 处理结果数据
                results = []
                if 'results' in result and result['results']:
                    field_list = fields.split(',')
                    for item in result['results']:
                        if isinstance(item, list) and len(item) >= len(field_list):
                            result_dict = {}
                            for i, field in enumerate(field_list):
                                if i < len(item):
                                    result_dict[field] = item[i]
                            results.append(result_dict)
                
                return {
                    'success': True,
                    'results': results,
                    'size': result.get('size', 0),
                    'total': result.get('size', 0),
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
    
    def search_all_pages(self, query: str, max_pages: int = 10, size: int = 100):
        """搜索所有页面
        
        Args:
            query: 搜索语句
            max_pages: 最大页数
            size: 每页数量
            
        Yields:
            每页的搜索结果
        """
        for page in range(1, max_pages + 1):
            result = self.search(query, size=size, page=page)
            if result.get('success'):
                yield result
                # 如果返回结果少于请求数量，说明已经是最后一页
                if len(result.get('results', [])) < size:
                    break
            else:
                break
            
            # 添加延时避免请求过快
            try:
                # 检查是否在QThread环境中
                from PySide6.QtCore import QThread, QTimer
                from PySide6.QtWidgets import QApplication
                
                if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) and isinstance(getattr(self, 'parent', None), QThread)):
                    # 在QThread环境中，使用异步延时
                    try:
                        # 尝试导入并使用AsyncDelay工具类
                        from PySide6.QtCore import QTimer
                        from PySide6.QtWidgets import QApplication
                        from modules.utils.async_delay import AsyncDelay
                        AsyncDelay.delay(milliseconds=1000)
                    except (ImportError, ModuleNotFoundError):
                        # 如果导入失败，使用QTimer进行异步延时
                        timer = QTimer()
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: None)
                        timer.start(1000)
                        
                        # 等待定时器完成
                        loop = QTimer()
                        loop.setSingleShot(True)
                        loop.start(1000)
                        while loop.isActive():
                            QApplication.processEvents()
                            # 增加休眠时间，减少CPU占用
                            time.sleep(0.05)
                else:
                    # 不在QThread环境中，使用传统的time.sleep
                    time.sleep(1)
            except (ImportError, NameError):
                # 如果导入失败，使用传统的time.sleep
                time.sleep(1)
    
    def search_stats(self, query: str) -> Dict:
        """获取搜索统计信息"""
        try:
            # Base64编码查询语句
            query_encoded = base64.b64encode(query.encode()).decode()
            
            url = f"{self.base_url}/search/stats"
            params = {
                "email": self.api_key.split(',')[0] if ',' in self.api_key else '',
                "key": self.api_key.split(',')[1] if ',' in self.api_key else self.api_key,
                "qbase64": query_encoded
            }
            
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('error'):
                    return {
                        'success': False,
                        'error': result.get('errmsg', '未知错误'),
                        'query': query
                    }
                
                return {
                    'success': True,
                    'distinct': result.get('distinct', {}),
                    'lastupdatetime': result.get('lastupdatetime', ''),
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


    def batch_search(self, queries: List[str], max_pages: int = 10, size: int = 100,
                    fields: str = "host,ip,port,title,country", delay: float = 1.0,
                    progress_callback=None) -> Dict:
        """批量搜索资产
        
        Args:
            queries: 查询语句列表
            max_pages: 每个查询的最大页数
            size: 每页数量
            fields: 返回字段
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
                
                # 获取该查询的所有页面
                query_results = []
                for page_result in self.search_all_pages(query, max_pages, size):
                    if page_result.get('success', False):
                        results = page_result.get('results', [])
                        for result in results:
                            if isinstance(result, dict):
                                result['source_query'] = query  # 添加来源查询标记
                        query_results.extend(results)
                    else:
                        break  # 查询失败，停止该查询
                
                all_results.extend(query_results)
                
                if progress_callback:
                    progress_callback(f"查询 {i} 完成，获得 {len(query_results)} 个结果")
                
                # 查询间延时
                if i < total_queries and delay > 0:
                    try:
                        # 检查是否在QThread环境中
                        from PySide6.QtCore import QThread, QTimer
                        from PySide6.QtWidgets import QApplication
                        
                        if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) and isinstance(getattr(self, 'parent', None), QThread)):
                            # 在QThread环境中，使用异步延时
                            try:
                                # 尝试导入并使用AsyncDelay工具类
                                from modules.utils.async_delay import AsyncDelay
                                AsyncDelay.delay(
                                    milliseconds=int(delay * 1000),
                                    progress_callback=progress_callback
                                )
                            except (ImportError, ModuleNotFoundError):
                                # 如果导入失败，使用QTimer进行异步延时
                                if progress_callback:
                                    progress_callback(f"等待请求间隔 {delay} 秒...")
                                
                                timer = QTimer()
                                timer.setSingleShot(True)
                                timer.timeout.connect(lambda: None)
                                timer.start(int(delay * 1000))
                                
                                # 等待定时器完成
                                loop = QTimer()
                                loop.setSingleShot(True)
                                loop.start(int(delay * 1000))
                                while loop.isActive():
                                    QApplication.processEvents()
                                    # 增加休眠时间，减少CPU占用
                                    time.sleep(0.05)
                        else:
                            # 不在QThread环境中，使用传统的time.sleep
                            time.sleep(delay)
                    except (ImportError, NameError):
                        # 如果导入失败，使用传统的time.sleep
                        time.sleep(delay)
            
            # 构造最终结果
            final_result = {
                'success': True,
                'results': all_results,
                'total': len(all_results),
                'queries_processed': total_queries,
                'message': 'Batch search completed successfully'
            }
            
            return final_result
            
        except Exception as e:
            return {
                'success': False,
                'error': f'批量查询异常: {str(e)}',
                'results': [],
                'total': 0
            }


def get_common_fields():
    """获取常用字段列表"""
    return [
        "host", "ip", "port", "title", "country", "city", "server", 
        "protocol", "banner", "cert", "domain", "icp", "fid", "structinfo"
    ]
    
    def search_with_callback(self, query: str, max_pages: int = 10, size: int = 100,
                           fields: str = "host,ip,port,title,country", delay: float = 1.0,
                           progress_callback=None):
        """搜索资产（带进度回调）
        
        Args:
            query: 搜索语句
            max_pages: 最大页数
            size: 每页数量
            fields: 返回字段
            delay: 页面间延时
            progress_callback: 进度回调函数
            
        Yields:
            每页的搜索结果
        """
        for page in range(1, max_pages + 1):
            if progress_callback:
                progress_callback(f"正在获取第 {page}/{max_pages} 页...")
            
            result = self.search(
                query=query,
                size=size,
                page=page,
                fields=fields
            )
            
            if result.get('success', False):
                yield result
                
                # 检查是否还有更多数据
                results = result.get('results', [])
                if len(results) < size:
                    break  # 没有更多数据了
            else:
                break  # 查询失败，停止
            
            # 添加延时避免请求过快
            if page < max_pages and delay > 0:
                time.sleep(delay)


def main():
    """测试函数"""
    print("FOFA API 模块加载成功")
    print("常用字段:", get_common_fields())
    
    # 测试批量搜索功能
    api = FOFASearcher()
    test_queries = ["port=80", "title=\"管理\""]
    
    def progress_callback(msg):
        print(f"进度: {msg}")
    
    print("测试批量搜索功能...")
    # 注意：需要有效的API Key才能实际测试
    # result = api.batch_search(test_queries, progress_callback=progress_callback)
    # print(f"批量搜索结果: {result}")


if __name__ == "__main__":
    main()