#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一查询模块
整合多个网络空间测绘平台的查询功能
"""

from PySide6.QtCore import QThread, Signal
from typing import Dict, List, Optional, Any
import logging
import time
import re
from datetime import datetime

from .Asset_Mapping.fofa import FOFASearcher
from .Asset_Mapping.hunter import HunterAPI
from .Asset_Mapping.quake import QuakeAPI


class UnifiedSearchEngine:
    """统一查询引擎"""
    
    def __init__(self, api_configs: Optional[Dict[str, Dict]] = None):
        """
        初始化统一查询引擎
        
        Args:
            api_configs: API配置字典，格式为 {'platform': {'api_key': 'key', ...}}
        """
        self.logger = logging.getLogger(__name__)
        self.api_configs = api_configs or {}
        
        # 初始化API实例
        self.fofa_api = None
        self.hunter_api = None
        self.quake_api = None
        
        self._init_apis()
    
    def _init_apis(self):
        """初始化API实例"""
        try:
            # 初始化FOFA API
            if 'fofa' in self.api_configs and self.api_configs['fofa'].get('api_key'):
                self.fofa_api = FOFASearcher(
                    api_key=self.api_configs['fofa']['api_key'],
                    email=self.api_configs['fofa'].get('email', '')
                )
            
            # 初始化Hunter API
            if 'hunter' in self.api_configs and self.api_configs['hunter'].get('api_key'):
                self.hunter_api = HunterAPI(self.api_configs['hunter']['api_key'])
            
            # 初始化Quake API
            if 'quake' in self.api_configs and self.api_configs['quake'].get('api_key'):
                self.quake_api = QuakeAPI(self.api_configs['quake']['api_key'])
                
        except Exception as e:
            self.logger.error(f"初始化API实例失败: {e}")
    
    def update_api_configs(self, api_configs: Dict[str, Dict]):
        """更新API配置"""
        self.api_configs = api_configs
        self._init_apis()
    
    def convert_query_syntax(self, query: str) -> Dict[str, str]:
        """转换查询语法为各平台支持的格式"""
        converted = {
            'fofa': query,
            'hunter': query,
            'quake': query
        }
        
        try:
            # 基础语法转换规则
            query_lower = query.strip().lower()
            
            # 检测平台特定语法，需要进行转换
            is_hunter_syntax = 'web.' in query_lower or 'ip.port' in query_lower
            is_fofa_syntax = ('body=' in query_lower or 'header=' in query_lower) and 'web.' not in query_lower
            is_quake_syntax = 'response:' in query_lower or 'service.' in query_lower
            
            # 如果是平台特定的复杂语法，进行转换
            if is_hunter_syntax:
                # Hunter特定语法转换
                converted['fofa'] = self._convert_hunter_to_fofa(query)
                converted['hunter'] = query  # Hunter保持原样
                converted['quake'] = self._convert_hunter_to_quake(query)
            elif is_fofa_syntax:
                # FOFA特定语法转换
                converted['fofa'] = query  # FOFA保持原样
                converted['hunter'] = self._convert_fofa_to_hunter(query)
                converted['quake'] = self._convert_fofa_to_quake(query)
            elif is_quake_syntax:
                # Quake特定语法转换
                converted['fofa'] = self._convert_quake_to_fofa(query)
                converted['hunter'] = self._convert_quake_to_hunter(query)
                converted['quake'] = query  # Quake保持原样
            # IP地址查询
            elif re.match(r'^\d+\.\d+\.\d+\.\d+$', query.strip()):
                ip = query.strip()
                converted['fofa'] = f'ip="{ip}"'
                converted['hunter'] = f'ip="{ip}"'
                converted['quake'] = f'ip:"{ip}"'
            
            # 域名查询 - 处理domain:"xxx"格式
            elif re.match(r'^domain[=:]\s*["\']?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["\']?$', query_lower):
                domain_match = re.search(r'domain[=:]\s*["\']?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["\']?', query, re.IGNORECASE)
                if domain_match:
                    domain = domain_match.group(1)
                    converted['fofa'] = f'domain="{domain}"'
                    converted['hunter'] = f'domain="{domain}"'
                    converted['quake'] = f'domain:"{domain}"'
            
            # 纯域名查询
            elif re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', query.strip()):
                domain = query.strip()
                converted['fofa'] = f'domain="{domain}"'
                converted['hunter'] = f'domain="{domain}"'
                converted['quake'] = f'domain:"{domain}"'
            
            # 端口查询
            elif re.match(r'^port[=:]?\s*\d+$', query_lower):
                port_match = re.search(r'\d+', query)
                if port_match:
                    port = port_match.group()
                    converted['fofa'] = f'port="{port}"'
                    converted['hunter'] = f'ip.port="{port}"'
                    converted['quake'] = f'port:{port}'
            
            # 标题查询 - 处理title:"xxx"格式
            elif re.match(r'^title[=:]', query_lower):
                title_match = re.search(r'title[=:]\s*["\']?(.+?)["\']?$', query, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip('"\'')
                    converted['fofa'] = f'title="{title}"'
                    converted['hunter'] = f'web.title="{title}"'
                    converted['quake'] = f'title:"{title}"'
            
            # 主机名查询 - 处理hostname:"xxx"格式
            elif re.match(r'^hostname[=:]', query_lower):
                hostname_match = re.search(r'hostname[=:]\s*["\']?(.+?)["\']?$', query, re.IGNORECASE)
                if hostname_match:
                    hostname = hostname_match.group(1).strip('"\'')
                    converted['fofa'] = f'host="{hostname}"'
                    converted['hunter'] = f'domain="{hostname}"'
                    converted['quake'] = f'hostname:"{hostname}"'
            
            # 如果没有匹配到特定模式，保持原查询语句
            
        except Exception as e:
            self.logger.error(f"转换查询语法失败: {e}")
        
        return converted
    
    def _convert_hunter_to_fofa(self, query: str) -> str:
        """将Hunter语法转换为FOFA语法"""
        try:
            # Hunter -> FOFA 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'web\.body=', 'body=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'web\.title=', 'title=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'web\.server=', 'server=', converted, flags=re.IGNORECASE)
            # Header相关
            converted = re.sub(r'header\.server=', 'server=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'header\.status_code=', 'status_code=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'header=', 'header=', converted, flags=re.IGNORECASE)
            # IP相关
            converted = re.sub(r'ip\.port=', 'port=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.country=', 'country=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.province=', 'region=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.city=', 'city=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.os=', 'os=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.isp=', 'org=', converted, flags=re.IGNORECASE)
            # 域名相关
            converted = re.sub(r'domain\.suffix=', 'domain=', converted, flags=re.IGNORECASE)
            # ICP相关
            converted = re.sub(r'icp\.name=', 'icp=', converted, flags=re.IGNORECASE)
            # 证书相关
            converted = re.sub(r'cert\.is_trust=', 'cert=', converted, flags=re.IGNORECASE)
            # 逻辑运算符保持不变
            converted = re.sub(r'\s+&&\s+', ' && ', converted)
            converted = re.sub(r'\s+\|\|\s+', ' || ', converted)
            return converted
        except Exception as e:
            self.logger.error(f"Hunter转FOFA失败: {e}")
            return query
    
    def _convert_hunter_to_quake(self, query: str) -> str:
        """将Hunter语法转换为Quake语法"""
        try:
            # Hunter -> Quake 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'web\.body=', 'response:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'web\.title=', 'title:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'web\.server=', 'server:', converted, flags=re.IGNORECASE)
            # Header相关
            converted = re.sub(r'header\.server=', 'server:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'header=', 'header:', converted, flags=re.IGNORECASE)
            # IP相关
            converted = re.sub(r'ip\.port=', 'port:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.country=', 'country:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.province=', 'province:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.city=', 'city:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.os=', 'os:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip\.isp=', 'isp:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'ip=', 'ip:', converted, flags=re.IGNORECASE)
            # 域名相关
            converted = re.sub(r'domain\.suffix=', 'domain:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'domain=', 'domain:', converted, flags=re.IGNORECASE)
            # 应用相关
            converted = re.sub(r'app=', 'app:', converted, flags=re.IGNORECASE)
            # 证书相关
            converted = re.sub(r'cert\.is_trust=', 'cert:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'cert=', 'cert:', converted, flags=re.IGNORECASE)
            # Banner相关
            converted = re.sub(r'banner=', 'banner:', converted, flags=re.IGNORECASE)
            # 协议相关
            converted = re.sub(r'protocol=', 'service:', converted, flags=re.IGNORECASE)
            # 逻辑运算符
            converted = re.sub(r'\s+&&\s+', ' AND ', converted)
            converted = re.sub(r'\s+\|\|\s+', ' OR ', converted)
            # 其他等号转冒号
            converted = re.sub(r'=', ':', converted)
            return converted
        except Exception as e:
            self.logger.error(f"Hunter转Quake失败: {e}")
            return query
    
    def _convert_fofa_to_hunter(self, query: str) -> str:
        """将FOFA语法转换为Hunter语法"""
        try:
            # FOFA -> Hunter 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'\bbody=', 'web.body=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\btitle=', 'web.title=', converted, flags=re.IGNORECASE)
            # Header和Server
            converted = re.sub(r'\bheader=', 'header=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bserver=', 'header.server=', converted, flags=re.IGNORECASE)
            # IP和位置
            converted = re.sub(r'\bport=', 'ip.port=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcountry=', 'ip.country=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bregion=', 'ip.province=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcity=', 'ip.city=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bos=', 'ip.os=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\borg=', 'ip.isp=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bip=', 'ip=', converted, flags=re.IGNORECASE)
            # 域名
            converted = re.sub(r'\bdomain=', 'domain.suffix=', converted, flags=re.IGNORECASE)
            # 应用
            converted = re.sub(r'\bapp=', 'app=', converted, flags=re.IGNORECASE)
            # 证书
            converted = re.sub(r'\bcert=', 'cert.is_trust=', converted, flags=re.IGNORECASE)
            # Banner
            converted = re.sub(r'\bbanner=', 'banner=', converted, flags=re.IGNORECASE)
            # 协议
            converted = re.sub(r'\bprotocol=', 'protocol=', converted, flags=re.IGNORECASE)
            return converted
        except Exception as e:
            self.logger.error(f"FOFA转Hunter失败: {e}")
            return query
    
    def _convert_fofa_to_quake(self, query: str) -> str:
        """将FOFA语法转换为Quake语法"""
        try:
            # FOFA -> Quake 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'\bbody=', 'response:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\btitle=', 'title:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bserver=', 'server:', converted, flags=re.IGNORECASE)
            # Header
            converted = re.sub(r'\bheader=', 'header:', converted, flags=re.IGNORECASE)
            # IP和位置
            converted = re.sub(r'\bport=', 'port:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bip=', 'ip:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcountry=', 'country:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bregion=', 'province:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcity=', 'city:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bos=', 'os:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\borg=', 'org:', converted, flags=re.IGNORECASE)
            # 域名和主机
            converted = re.sub(r'\bdomain=', 'domain:', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bhost=', 'hostname:', converted, flags=re.IGNORECASE)
            # 应用
            converted = re.sub(r'\bapp=', 'app:', converted, flags=re.IGNORECASE)
            # ASN
            converted = re.sub(r'\basn=', 'asn:', converted, flags=re.IGNORECASE)
            # 证书
            converted = re.sub(r'\bcert=', 'cert:', converted, flags=re.IGNORECASE)
            # Banner
            converted = re.sub(r'\bbanner=', 'banner:', converted, flags=re.IGNORECASE)
            # 协议
            converted = re.sub(r'\bprotocol=', 'service:', converted, flags=re.IGNORECASE)
            # 逻辑运算符
            converted = re.sub(r'\s+&&\s+', ' AND ', converted)
            converted = re.sub(r'\s+\|\|\s+', ' OR ', converted)
            # 其他等号转冒号
            converted = re.sub(r'=', ':', converted)
            return converted
        except Exception as e:
            self.logger.error(f"FOFA转Quake失败: {e}")
            return query
    
    def _convert_quake_to_fofa(self, query: str) -> str:
        """将Quake语法转换为FOFA语法"""
        try:
            # Quake -> FOFA 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'\bresponse:', 'body=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\btitle:', 'title=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bserver:', 'server=', converted, flags=re.IGNORECASE)
            # Header
            converted = re.sub(r'\bheader:', 'header=', converted, flags=re.IGNORECASE)
            # IP和位置
            converted = re.sub(r'\bport:', 'port=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bip:', 'ip=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcountry:', 'country=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bprovince:', 'region=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcity:', 'city=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bos:', 'os=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\borg:', 'org=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bisp:', 'org=', converted, flags=re.IGNORECASE)
            # 域名和主机
            converted = re.sub(r'\bdomain:', 'domain=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bhostname:', 'host=', converted, flags=re.IGNORECASE)
            # 应用
            converted = re.sub(r'\bapp:', 'app=', converted, flags=re.IGNORECASE)
            # ASN
            converted = re.sub(r'\basn:', 'asn=', converted, flags=re.IGNORECASE)
            # 证书
            converted = re.sub(r'\bcert:', 'cert=', converted, flags=re.IGNORECASE)
            # Banner
            converted = re.sub(r'\bbanner:', 'banner=', converted, flags=re.IGNORECASE)
            # 协议/服务
            converted = re.sub(r'\bservice:', 'protocol=', converted, flags=re.IGNORECASE)
            # 逻辑运算符
            converted = re.sub(r'\s+AND\s+', ' && ', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\s+OR\s+', ' || ', converted, flags=re.IGNORECASE)
            # 其他冒号转等号
            converted = re.sub(r':', '=', converted)
            return converted
        except Exception as e:
            self.logger.error(f"Quake转FOFA失败: {e}")
            return query
    
    def _convert_quake_to_hunter(self, query: str) -> str:
        """将Quake语法转换为Hunter语法"""
        try:
            # Quake -> Hunter 转换规则
            converted = query
            # Web相关
            converted = re.sub(r'\bresponse:', 'web.body=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\btitle:', 'web.title=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bserver:', 'header.server=', converted, flags=re.IGNORECASE)
            # Header
            converted = re.sub(r'\bheader:', 'header=', converted, flags=re.IGNORECASE)
            # IP和位置
            converted = re.sub(r'\bport:', 'ip.port=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bip:', 'ip=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcountry:', 'ip.country=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bprovince:', 'ip.province=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bcity:', 'ip.city=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bos:', 'ip.os=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bisp:', 'ip.isp=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\borg:', 'ip.isp=', converted, flags=re.IGNORECASE)
            # 域名和主机
            converted = re.sub(r'\bdomain:', 'domain.suffix=', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\bhostname:', 'domain=', converted, flags=re.IGNORECASE)
            # 应用
            converted = re.sub(r'\bapp:', 'app=', converted, flags=re.IGNORECASE)
            # 证书
            converted = re.sub(r'\bcert:', 'cert.is_trust=', converted, flags=re.IGNORECASE)
            # Banner（Hunter也有banner，保持不变）
            converted = re.sub(r'\bbanner:', 'banner=', converted, flags=re.IGNORECASE)
            # 协议/服务
            converted = re.sub(r'\bservice:', 'protocol=', converted, flags=re.IGNORECASE)
            # 逻辑运算符
            converted = re.sub(r'\s+AND\s+', ' && ', converted, flags=re.IGNORECASE)
            converted = re.sub(r'\s+OR\s+', ' || ', converted, flags=re.IGNORECASE)
            # 其他冒号转等号
            converted = re.sub(r':', '=', converted)
            return converted
        except Exception as e:
            self.logger.error(f"Quake转Hunter失败: {e}")
            return query
    
    def search_single_platform(self, platform: str, query: str, limit: int = 100, fetch_all: bool = True, **kwargs) -> Dict:
        """在单个平台上执行查询"""
        try:
            if platform == 'fofa' and self.fofa_api:
                return self._query_fofa(query, limit, fetch_all=fetch_all, **kwargs)
            elif platform == 'hunter' and self.hunter_api:
                return self._query_hunter(query, limit, fetch_all=fetch_all, **kwargs)
            elif platform == 'quake' and self.quake_api:
                return self._query_quake(query, limit, fetch_all=fetch_all, **kwargs)
            else:
                return {
                    'success': False,
                    'error': f'平台 {platform} 不可用或API未配置',
                    'query': query,
                    'platform': platform
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'platform': platform
            }
    
    def _query_fofa(self, query: str, limit: int = 100, fetch_all: bool = True, **kwargs) -> Dict:
        """查询FOFA"""
        try:
            page_size = min(limit, 100)
            if not fetch_all:
                if not self.fofa_api:
                    return {
                        'success': False,
                        'error': 'FOFA API未初始化',
                        'results': [],
                        'total': 0
                    }
                result = self.fofa_api.search(
                    query=query,
                    size=page_size,
                    page=1,
                    fields="host,ip,port,title,country,city,server"
                )
                if result.get('success', False):
                    results = result.get('results', [])
                    return {
                        'success': True,
                        'results': results[:limit],
                        'total': result.get('total', len(results)),
                        'query': query,
                        'platform': 'fofa'
                    }
                return result
            
            pages_needed = (limit + page_size - 1) // page_size
            all_results = []
            total_count = 0
            
            for page in range(1, pages_needed + 1):
                if self.fofa_api:
                    result = self.fofa_api.search(
                        query=query,
                        size=page_size,
                        page=page,
                        fields="host,ip,port,title,country,city,server"
                    )
                else:
                    return {
                        'success': False,
                        'error': 'FOFA API未初始化',
                        'results': [],
                        'total': 0
                    }
                
                if result.get('success', False):
                    results = result.get('results', [])
                    all_results.extend(results)
                    total_count = result.get('total', len(all_results))
                    if len(results) < page_size:
                        break
                else:
                    return result
                
                if page < pages_needed:
                    try:
                        from PySide6.QtCore import QThread, QTimer
                        from PySide6.QtWidgets import QApplication
                        
                        if isinstance(self, QThread) or (hasattr(self, 'parent') and getattr(self, 'parent', None) and isinstance(getattr(self, 'parent', None), QThread)):
                            try:
                                from ..utils.async_delay import AsyncDelay
                                AsyncDelay.delay(milliseconds=1000)
                            except (ImportError, ModuleNotFoundError):
                                timer = QTimer()
                                timer.setSingleShot(True)
                                timer.timeout.connect(lambda: None)
                                timer.start(1000)
                                
                                loop = QTimer()
                                loop.setSingleShot(True)
                                loop.start(1000)
                                while loop.isActive():
                                    QApplication.processEvents()
                                    time.sleep(0.05)
                        else:
                            time.sleep(1)
                    except (ImportError, NameError):
                        time.sleep(1)
            
            return {
                'success': True,
                'results': all_results[:limit],
                'total': total_count,
                'query': query,
                'platform': 'fofa'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'platform': 'fofa'
            }
    
    def _query_hunter(self, query: str, limit: int = 100, fetch_all: bool = True, **kwargs) -> Dict:
        """查询Hunter"""
        try:
            page_size = min(limit, 100)
            if not fetch_all:
                if not self.hunter_api:
                    return {
                        'success': False,
                        'error': 'Hunter API未初始化',
                        'results': [],
                        'total': 0
                    }
                result = self.hunter_api.search(
                    query=query,
                    page=1,
                    page_size=page_size,
                    is_web=3,
                    port_filter=False
                )
                if result.get('code') == 200:
                    data = result.get('data', {})
                    results = data.get('arr', [])
                    if results is None:
                        results = []
                    return {
                        'success': True,
                        'results': results[:limit],
                        'total': data.get('total', len(results)),
                        'query': query,
                        'platform': 'hunter'
                    }
                return {
                    'success': False,
                    'error': result.get('message', '查询失败'),
                    'query': query,
                    'platform': 'hunter'
                }
            
            pages_needed = (limit + page_size - 1) // page_size
            all_results = []
            total_count = 0
            
            for page in range(1, pages_needed + 1):
                if self.hunter_api:
                    result = self.hunter_api.search(
                        query=query,
                        page=page,
                        page_size=page_size,
                        is_web=3,
                        port_filter=False
                    )
                else:
                    return {
                        'success': False,
                        'error': 'Hunter API未初始化',
                        'results': [],
                        'total': 0
                    }
                
                if result.get('code') == 200:
                    data = result.get('data', {})
                    results = data.get('arr', [])
                    if results is None:
                        results = []
                    all_results.extend(results)
                    total_count = data.get('total', len(all_results))
                    if len(results) < page_size:
                        break
                else:
                    return {
                        'success': False,
                        'error': result.get('message', '查询失败'),
                        'query': query,
                        'platform': 'hunter'
                    }
                
                if page < pages_needed:
                    time.sleep(1)
            
            return {
                'success': True,
                'results': all_results[:limit],
                'total': total_count,
                'query': query,
                'platform': 'hunter'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'platform': 'hunter'
            }
    
    def _query_quake(self, query: str, limit: int = 100, fetch_all: bool = True, **kwargs) -> Dict:
        """查询Quake"""
        try:
            if not self.quake_api:
                return {
                    'success': False,
                    'error': 'Quake API未初始化',
                    'results': [],
                    'total': 0,
                    'query': query,
                    'platform': 'quake'
                }
            
            page_size = min(limit, 500)
            if not fetch_all:
                result = self.quake_api.search(
                    query=query,
                    size=page_size,
                    start=0
                )
                if result.get('success', False):
                    return {
                        'success': True,
                        'results': result.get('data', [])[:limit],
                        'total': result.get('total', 0),
                        'query': query,
                        'platform': 'quake'
                    }
                return result
            
            all_results = []
            total_count = 0
            start = 0
            
            while len(all_results) < limit:
                size = min(500, limit - len(all_results))
                result = self.quake_api.search(
                    query=query,
                    size=size,
                    start=start
                )
                
                if result.get('success', False):
                    results = result.get('data', [])
                    all_results.extend(results)
                    total_count = result.get('total', len(all_results))
                    if len(results) < size:
                        break
                    start += len(results)
                    time.sleep(1)
                else:
                    return result
            
            return {
                'success': True,
                'results': all_results[:limit],
                'total': total_count,
                'query': query,
                'platform': 'quake'
            }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'platform': 'quake'
            }
    
    def unified_search(self, queries: List[str], platforms: List[str], 
                      limit: int = 100, debug: bool = False) -> Dict:
        """执行统一查询"""
        try:
            all_results = {}
            debug_info = []
            
            if debug:
                debug_info.append(f"[DEBUG] 开始统一查询，共 {len(queries)} 个查询语句")
                debug_info.append(f"[DEBUG] 选择的平台: {platforms}")
                debug_info.append(f"[DEBUG] 查询参数 - 限制: {limit}")
            
            # 循环处理每个查询语句
            for i, query in enumerate(queries, 1):
                if debug:
                    debug_info.append(f"[DEBUG] 处理第 {i}/{len(queries)} 个查询: {query}")
                
                # 转换查询语句
                converted_queries = self.convert_query_syntax(query)
                if debug:
                    debug_info.append(f"[DEBUG] 查询语句转换结果: {converted_queries}")
                
                query_results = {}
                
                # 执行各平台查询
                for platform in platforms:
                    if debug:
                        debug_info.append(f"[DEBUG] 开始查询平台: {platform}")
                        debug_info.append(f"[DEBUG] {platform} 查询语句: {converted_queries.get(platform, 'N/A')}")
                    
                    try:
                        platform_query = converted_queries.get(platform, query)
                        result = self.search_single_platform(platform, platform_query, limit)
                        
                        if debug:
                            if result.get('success', False):
                                result_count = len(result.get('results', []))
                                debug_info.append(f"[DEBUG] {platform} 查询成功，获得 {result_count} 条结果")
                            else:
                                debug_info.append(f"[DEBUG] {platform} 查询失败: {result.get('error', '未知错误')}")
                        
                        query_results[platform] = result
                        
                    except Exception as e:
                        error_msg = str(e)
                        if debug:
                            debug_info.append(f"[DEBUG] {platform} 查询异常: {error_msg}")
                        
                        query_results[platform] = {
                            'success': False,
                            'error': error_msg,
                            'query': query,
                            'platform': platform
                        }
                    
                    # 添加延时避免请求过快
                    time.sleep(1)
                
                all_results[query] = query_results
            
            # 统计结果
            total_results = 0
            successful_queries = 0
            
            for query, platforms_results in all_results.items():
                query_has_success = False
                for platform, result in platforms_results.items():
                    if result.get('success', False):
                        total_results += len(result.get('results', []))
                        query_has_success = True
                
                if query_has_success:
                    successful_queries += 1
            
            if debug:
                debug_info.append(f"[DEBUG] 统一查询完成")
                debug_info.append(f"[DEBUG] 成功查询: {successful_queries}/{len(queries)}")
                debug_info.append(f"[DEBUG] 总结果数: {total_results}")
            
            return {
                'success': True,
                'results': all_results,
                'total_queries': len(queries),
                'successful_queries': successful_queries,
                'total_results': total_results,
                'debug_info': debug_info if debug else []
            }
            
        except Exception as e:
            error_msg = str(e)
            if debug:
                debug_info.append(f"[DEBUG] 统一查询主异常: {error_msg}")
            
            return {
                'success': False,
                'error': error_msg,
                'debug_info': debug_info if debug else []
            }
    
    def merge_and_deduplicate_results(self, results: Dict) -> List[Dict]:
        """合并和去重查询结果"""
        try:
            all_items = []
            seen_items = set()
            
            for query, platforms_results in results.items():
                for platform, platform_result in platforms_results.items():
                    if platform_result.get('success', False):
                        items = platform_result.get('results', [])
                        
                        for item in items:
                            if isinstance(item, dict):
                                # 创建去重键
                                dedup_key = self._create_dedup_key(item, platform)
                                
                                if dedup_key not in seen_items:
                                    seen_items.add(dedup_key)
                                    
                                    # 添加元数据
                                    item_copy = item.copy()
                                    item_copy['source_query'] = query
                                    item_copy['source_platform'] = platform
                                    item_copy['unified_search'] = True
                                    
                                    all_items.append(item_copy)
            
            return all_items
            
        except Exception as e:
            self.logger.error(f"合并和去重结果失败: {e}")
            return []
    
    def _create_dedup_key(self, item: Dict, platform: str) -> str:
        """创建去重键"""
        try:
            # 根据不同平台的数据结构创建去重键
            if platform == 'fofa':
                host = item.get('host', '')
                ip = item.get('ip', '')
                port = item.get('port', '')
                return f"fofa_{host}_{ip}_{port}"
            
            elif platform == 'hunter':
                url = item.get('url', '')
                ip = item.get('ip', '')
                port = item.get('port', '')
                return f"hunter_{url}_{ip}_{port}"
            
            elif platform == 'quake':
                ip = item.get('ip', '')
                port = item.get('port', '')
                service = item.get('service', {}).get('name', '')
                return f"quake_{ip}_{port}_{service}"
            
            else:
                # 通用去重键
                ip = item.get('ip', '')
                port = item.get('port', '')
                return f"{platform}_{ip}_{port}"
                
        except Exception as e:
            self.logger.error(f"创建去重键失败: {e}")
            return f"{platform}_{hash(str(item))}"
    
    def format_results_as_table(self, results: List[Dict]) -> str:
        """将结果格式化为表格形式"""
        try:
            if not results:
                return "没有查询结果"
            
            # 表格标题
            table_lines = []
            table_lines.append("📊 统一查询结果表格")
            table_lines.append("=" * 80)
            table_lines.append("")
            
            # 表头
            header = f"{'序号':<4} {'IP地址':<15} {'端口':<6} {'域名/URL':<30} {'标题':<20} {'平台':<8}"
            table_lines.append(header)
            table_lines.append("-" * 80)
            
            # 数据行
            for i, item in enumerate(results[:100], 1):  # 限制显示前100条
                ip = item.get('ip', 'N/A')[:15]
                port = str(item.get('port', 'N/A'))[:6]
                
                # 获取域名或URL
                domain_url = item.get('host', item.get('url', item.get('domain', 'N/A')))[:30]
                
                # 获取标题
                title = item.get('title', item.get('service', {}).get('name', 'N/A'))[:20]
                
                # 获取平台
                platform = item.get('source_platform', 'N/A')[:8]
                
                row = f"{i:<4} {ip:<15} {port:<6} {domain_url:<30} {title:<20} {platform:<8}"
                table_lines.append(row)
            
            if len(results) > 100:
                table_lines.append(f"... 还有 {len(results) - 100} 条结果未显示")
            
            table_lines.append("")
            table_lines.append(f"总计: {len(results)} 条去重结果")
            
            return "\n".join(table_lines)
            
        except Exception as e:
            self.logger.error(f"格式化表格失败: {e}")
            return f"格式化表格失败: {str(e)}"


class UnifiedSearchThread(QThread):
    """统一查询线程"""
    progress_updated = Signal(str)
    search_completed = Signal(dict)
    
    def __init__(self, search_engine: UnifiedSearchEngine, queries: List[str], 
                 platforms: List[str], limit: int = 100, debug: bool = False):
        super().__init__()
        self.search_engine = search_engine
        self.queries = queries
        self.platforms = platforms
        self.limit = limit
        self.debug = debug
    
    def run(self):
        try:
            # 执行统一查询
            result = self.search_engine.unified_search(
                queries=self.queries,
                platforms=self.platforms,
                limit=self.limit,
                debug=self.debug
            )
            
            self.search_completed.emit(result)
            
        except Exception as e:
            self.search_completed.emit({
                'success': False,
                'error': str(e)
            })


def main():
    """测试函数"""
    print("统一查询模块加载成功")
    
    # 测试查询语法转换
    engine = UnifiedSearchEngine()
    
    test_queries = [
        "1.1.1.1",
        "baidu.com",
        "port:80",
        "title:管理后台"
    ]
    
    for query in test_queries:
        converted = engine.convert_query_syntax(query)
        print(f"原查询: {query}")
        print(f"转换结果: {converted}")
        print("-" * 40)


if __name__ == "__main__":
    main()
