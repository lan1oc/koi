#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微步威胁情报API

提供IP信誉查询、DNS查询、文件报告等威胁情报功能
"""

import requests
import json
import time
from typing import Dict, List, Optional, Any
import logging


class ThreatBookAPI:
    """微步威胁情报API类"""
    
    def __init__(self, api_key: str = ""):
        """
        初始化微步威胁情报API
        
        Args:
            api_key: 微步API密钥
        """
        self.api_key = api_key
        self.base_url = "https://api.threatbook.cn"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ThreatBook-API-Client/1.0',
            'Content-Type': 'application/json'
        })
        
        # 设置日志
        self.logger = logging.getLogger(__name__)
    
    def set_api_key(self, api_key: str):
        """设置API密钥"""
        self.api_key = api_key
    
    def _make_request(self, endpoint: str, params: Dict[str, Any], method: str = 'GET') -> Dict[str, Any]:
        """
        发送API请求
        
        Args:
            endpoint: API端点
            params: 请求参数
            method: 请求方法
            
        Returns:
            API响应数据
        """
        if not self.api_key:
            return {'error': 'API密钥未设置'}
        
        # 添加API密钥到参数
        params['apikey'] = self.api_key
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params, timeout=30)
            else:
                response = self.session.post(url, json=params, timeout=30)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API请求失败: {str(e)}")
            return {'error': f'请求失败: {str(e)}'}
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {str(e)}")
            return {'error': f'响应解析失败: {str(e)}'}
    
    def query_ip_reputation(self, ip: str, lang: str = 'zh', 
                           include_malware_family: bool = True,
                           include_campaign: bool = True,
                           include_actor: bool = True,
                           include_ttp: bool = True,
                           include_cve: bool = True) -> Dict[str, Any]:
        """
        查询IP信誉 (使用v3 API，保留v5参数以备将来使用)
        
        Args:
            ip: IP地址
            lang: 语言 (zh/en)
            include_malware_family: 包含恶意软件家族信息 (v5功能，暂时保留)
            include_campaign: 包含攻击活动信息 (v5功能，暂时保留)
            include_actor: 包含威胁行为者信息 (v5功能，暂时保留)
            include_ttp: 包含战术、技术和程序信息 (v5功能，暂时保留)
            include_cve: 包含CVE漏洞信息 (v5功能，暂时保留)
            
        Returns:
            IP信誉查询结果
        """
        # 使用v3端点，因为v5端点暂时不可用
        endpoint = "/v3/scene/ip_reputation"
        params = {
            'resource': ip,
            'lang': lang
            # v5参数暂时不使用，保留接口以备将来升级
            # 'include_malware_family': str(include_malware_family).lower(),
            # 'include_campaign': str(include_campaign).lower(),
            # 'include_actor': str(include_actor).lower(),
            # 'include_ttp': str(include_ttp).lower(),
            # 'include_cve': str(include_cve).lower()
        }
        
        result = self._make_request(endpoint, params)
        
        if 'error' in result:
            return result
        
        # 格式化返回结果
        data = result.get('data', {})
        ip_data = data.get(ip, {}) if ip in data else {}
        
        # 提取威胁等级 (v3 API格式)
        severity = ip_data.get('severity', '无威胁')
        is_malicious = ip_data.get('is_malicious', False)
        
        # 根据威胁等级和恶意状态确定信誉等级
        if is_malicious:
            reputation_level = '恶意'
        elif severity == '无威胁' or severity == 'none':
            reputation_level = '良好'
        elif severity == 'low':
            reputation_level = '低危'
        elif severity == 'medium':
            reputation_level = '中危'
        elif severity == 'high':
            reputation_level = '高危'
        else:
            reputation_level = '未知'
        
        # 提取v5 API的丰富数据结构
        malware_families = ip_data.get('malware_families', [])
        campaigns = ip_data.get('campaigns', [])
        actors = ip_data.get('actors', [])
        ttps = ip_data.get('ttps', [])
        cves = ip_data.get('cves', [])
        iocs = ip_data.get('iocs', [])
        
        formatted_result = {
            'ip': ip,
            'query_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'reputation_level': reputation_level,
            'confidence': ip_data.get('confidence_level', '未知'),
            'threat_types': ip_data.get('tags_classes', []),
            'judgments': ip_data.get('judgments', []),
            'basic': ip_data.get('basic', {}),
            'location': ip_data.get('basic', {}).get('location', {}),
            'asn': ip_data.get('asn', {}),
            'severity': severity,
            'is_malicious': is_malicious,
            'update_time': ip_data.get('update_time', ''),
            'permalink': ip_data.get('permalink', ''),
            # v5 API新增字段
            'malware_families': malware_families,
            'campaigns': campaigns,
            'actors': actors,
            'ttps': ttps,
            'cves': cves,
            'iocs': iocs,
            'intelligence_tags': ip_data.get('intelligence_tags', []),
            'threat_score': ip_data.get('threat_score', 0),
            'first_seen': ip_data.get('first_seen', ''),
            'last_seen': ip_data.get('last_seen', ''),
            'raw_data': result
        }
        
        return formatted_result
    
    def query_dns_compromise(self, domain: str) -> Dict[str, Any]:
        """
        查询域名失陷检测 (使用v5 API)
        
        Args:
            domain: 域名
            
        Returns:
            域名失陷检测结果
        """
        endpoint = "/v3/scene/dns"
        params = {
            'resource': domain
        }
        
        result = self._make_request(endpoint, params)
        
        # 添加调试日志
        print(f"[DEBUG] DNS API调用结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        if 'error' in result:
            return result
        
        # 格式化返回结果 - 适配v3 scene/dns API响应格式
        data = result.get('data', {})
        
        print(f"[DEBUG] v3 API返回的data数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # v3 scene/dns API的数据结构: data.domains.{domain_name}
        domains_data = data.get('domains', {})
        domain_info = domains_data.get(domain, {})
        
        print(f"[DEBUG] 域名 {domain} 的信息: {json.dumps(domain_info, indent=2, ensure_ascii=False)}")
        
        # 提取威胁信息 - v3 scene/dns API格式
        severity = domain_info.get('severity', '无威胁')
        judgments = domain_info.get('judgments', [])
        tags_classes = domain_info.get('tags_classes', [])
        confidence_level = domain_info.get('confidence_level', '未知')
        is_malicious = domain_info.get('is_malicious', False)
        permalink = domain_info.get('permalink', '')
        
        # 提取恶意软件家族信息
        malware_families = []
        for tag_class in tags_classes:
            if tag_class.get('tags_type') == 'virus_family':
                malware_families.extend(tag_class.get('tags', []))
        
        # 提取排名信息
        rank_info = domain_info.get('rank', {})
        alexa_rank = rank_info.get('alexa_rank', {}).get('global_rank', -1) if isinstance(rank_info.get('alexa_rank'), dict) else -1
        umbrella_rank = rank_info.get('umbrella_rank', {}).get('global_rank', -1) if isinstance(rank_info.get('umbrella_rank'), dict) else -1
        
        # 提取分类信息
        categories = domain_info.get('categories', {})
        second_cats = categories.get('second_cats', '') if isinstance(categories, dict) else ''
        
        formatted_result = {
            'domain': domain,
            'query_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'is_malicious': is_malicious,
            'severity': severity,
            'confidence_level': confidence_level,
            'judgments': judgments,
            'tags_classes': tags_classes,
            'malware_families': malware_families,
            'permalink': permalink,
            'alexa_rank': alexa_rank,
            'umbrella_rank': umbrella_rank,
            'categories': second_cats,
            'raw_data': result
        }
        
        return formatted_result
    
    def upload_file(self, file_path: str, sandbox_type: str = 'win7_sp1_enx86_office2013', run_time: int = 60) -> Dict[str, Any]:
        """
        上传文件进行分析 (使用v3 API，按照官方示例)
        
        Args:
            file_path: 文件路径
            sandbox_type: 沙箱类型，默认为 win7_sp1_enx86_office2013
            run_time: 运行时间（秒），默认为60秒
            
        Returns:
            文件上传结果
        """
        endpoint = "/v3/file/upload"
        
        if not self.api_key:
            return {'error': 'API密钥未设置'}
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            import os
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # 检查文件大小限制 (100MB)
            if file_size > 100 * 1024 * 1024:
                return {'error': f'文件过大: {file_size / (1024*1024):.1f}MB，超过100MB限制'}
            
            print(f"[DEBUG] 上传文件: {file_path}, 大小: {file_size / (1024*1024):.2f}MB")
            print(f"[DEBUG] 沙箱类型: {sandbox_type}, 运行时间: {run_time}秒")
            
            # 按照官方示例格式构建请求
            with open(file_path, 'rb') as f:
                files = {'file': (file_name, f)}
                data = {
                    'apikey': self.api_key,
                    'sandbox_type': sandbox_type,
                    'run_time': run_time
                }
                
                print(f"[DEBUG] 请求URL: {url}")
                print(f"[DEBUG] 请求参数: {data}")
                
                response = requests.post(url, data=data, files=files, timeout=120)
                response.raise_for_status()
                
                result = response.json()
                
                print(f"[DEBUG] 文件上传API响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
                
                # 检查响应状态
                if result.get('response_code') != 0:
                    error_msg = result.get('verbose_msg', '上传失败')
                    return {'error': f'API错误: {error_msg}'}
                
                data_info = result.get('data', {})
                
                # 格式化返回结果
                formatted_result = {
                    'file_name': file_name,
                    'file_path': file_path,
                    'file_size': file_size,
                    'sandbox_type': sandbox_type,
                    'run_time': run_time,
                    'upload_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'sha256': data_info.get('sha256', ''),
                    'md5': data_info.get('md5', ''),
                    'sha1': data_info.get('sha1', ''),
                    'permalink': data_info.get('permalink', ''),
                    'raw_data': result
                }
                
                return formatted_result
                
        except FileNotFoundError:
            return {'error': f'文件不存在: {file_path}'}
        except requests.exceptions.RequestException as e:
            self.logger.error(f"文件上传失败: {str(e)}")
            return {'error': f'上传失败: {str(e)}'}
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {str(e)}")
            return {'error': f'响应解析失败: {str(e)}'}
        except Exception as e:
            self.logger.error(f"文件上传异常: {str(e)}")
            return {'error': f'上传异常: {str(e)}'}
    
    def query_file_report(self, resource: str, resource_type: str = 'sha256') -> Dict[str, Any]:
        """
        查询文件报告 - 使用v5 API
        
        Args:
            resource: 文件哈希值(MD5/SHA1/SHA256)或scan_id
            resource_type: 资源类型 (sha256, md5, sha1, scan_id)
            
        Returns:
            文件分析报告
        """
        endpoint = "/v3/file/report"
        params = {
            'resource': resource,
            'resource_type': resource_type
        }
        
        result = self._make_request(endpoint, params)
        
        if 'error' in result:
            return result
        
        # 格式化返回结果
        data = result.get('data', {})
        formatted_result = {
            'resource': resource,
            'resource_type': resource_type,
            'query_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'sha256': data.get('sha256', ''),
            'md5': data.get('md5', ''),
            'sha1': data.get('sha1', ''),
            'file_name': data.get('file_name', ''),
            'file_size': data.get('file_size', 0),
            'file_type': data.get('file_type', ''),
            'reputation_level': data.get('reputation_level', 'unknown'),
            'confidence': data.get('confidence', 0),
            'threat_types': data.get('threat_types', []),
            'engines': data.get('engines', {}),
            'scan_date': data.get('scan_date', ''),
            'permalink': data.get('permalink', ''),  # 添加permalink字段提取
            'raw_data': result
        }
        
        return formatted_result
    
    def query_file_multiengines(self, resource: str, resource_type: str = 'sha256') -> Dict[str, Any]:
        """
        查询文件多引擎检测结果 - 使用v5 API
        
        Args:
            resource: 文件哈希值(MD5/SHA1/SHA256)
            resource_type: 资源类型 (sha256, md5, sha1)
            
        Returns:
            多引擎检测结果
        """
        endpoint = "/v3/file/report/multiengines"
        params = {
            'resource': resource,
            'resource_type': resource_type
        }
        
        result = self._make_request(endpoint, params)
        
        if 'error' in result:
            return result
        
        # 格式化返回结果 - 根据官方API文档结构
        data = result.get('data', {})
        multiengines = data.get('multiengines', {})
        
        formatted_result = {
            'resource': resource,
            'resource_type': resource_type,
            'query_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'threat_level': multiengines.get('threat_level', 'unknown'),
            'total_engines': multiengines.get('total', 0),
            'total2_engines': multiengines.get('total2', 0),
            'positive_engines': multiengines.get('positives', 0),
            'scan_date': multiengines.get('scan_date', ''),
            'malware_type': multiengines.get('malware_type', ''),
            'malware_family': multiengines.get('malware_family', ''),
            'is_white': multiengines.get('is_white', False),
            'engines_detail': multiengines.get('scans', {}),
            'raw_data': result
        }
        
        return formatted_result
    
    def batch_query_ip(self, ip_list: List[str], progress_callback=None) -> List[Dict[str, Any]]:
        """
        批量查询IP信誉
        
        Args:
            ip_list: IP地址列表
            progress_callback: 进度回调函数
            
        Returns:
            批量查询结果列表
        """
        results = []
        total = len(ip_list)
        
        for i, ip in enumerate(ip_list, 1):
            if progress_callback:
                progress_callback(f"正在查询第 {i}/{total} 个IP: {ip}")
            
            result = self.query_ip_reputation(ip)
            results.append(result)
            
            # 添加请求间隔，避免频率限制
            if i < total:
                time.sleep(1)
        
        return results
    
    def test_connection(self) -> Dict[str, Any]:
        """
        测试API连接
        
        Returns:
            连接测试结果
        """
        if not self.api_key:
            return {'success': False, 'message': 'API密钥未设置'}
        
        # 使用一个简单的IP查询来测试连接
        test_result = self.query_ip_reputation('8.8.8.8')
        
        if 'error' in test_result:
            return {'success': False, 'message': test_result['error']}
        else:
            return {'success': True, 'message': 'API连接正常'}


def main():
    """测试函数"""
    # 示例用法
    api = ThreatBookAPI()
    
    # 测试连接
    test_result = api.test_connection()
    print(f"连接测试: {test_result}")
    
    if test_result['success']:
        # 测试IP查询
        ip_result = api.query_ip_reputation('1.1.1.1')
        print(f"IP查询结果: {json.dumps(ip_result, indent=2, ensure_ascii=False)}")
        
        # 测试域名失陷检测
        dns_result = api.query_dns_compromise('example.com')
        print(f"域名失陷检测结果: {json.dumps(dns_result, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    main()