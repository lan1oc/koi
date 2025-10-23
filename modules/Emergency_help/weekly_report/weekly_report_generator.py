#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报生成器模块
自动分析工作文件生成周报
"""

import os
import winreg
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional


class WeeklyReportGenerator:
    """周报生成器"""
    
    def __init__(self):
        self.work_keywords = [
            '漏洞', '扫描', '渗透', '测试', '安全', '评估', '报告', '检测',
            '修复', '加固', '防护', '监控', '审计', '合规', '风险',
            'vulnerability', 'scan', 'penetration', 'test', 'security',
            'assessment', 'report', 'detection', 'fix', 'hardening'
        ]
        
        self.company_patterns = [
            r'([\u4e00-\u9fa5]+(?:公司|集团|企业|科技|网络|信息|系统|软件|技术))',
            r'([A-Za-z]+(?:\s+(?:Inc|Corp|Ltd|Co|Company|Group|Tech|Technology)))',
        ]
    
    def generate_report(self, days: Optional[int] = None, detailed: bool = False) -> str:
        """生成工作周报
        
        Args:
            days: 统计天数，None表示本周工作日
            detailed: 是否生成详细报告
            
        Returns:
            生成的周报内容
        """
        try:
            # 确定时间范围
            end_date = datetime.now()
            if days is None:
                # 本周工作日（周一到今天）
                days_since_monday = end_date.weekday()
                start_date = end_date - timedelta(days=days_since_monday)
                date_range = f"本周工作日（{start_date.strftime('%m月%d日')}至{end_date.strftime('%m月%d日')}）"
            else:
                start_date = end_date - timedelta(days=days)
                date_range = f"最近{days}天（{start_date.strftime('%m月%d日')}至{end_date.strftime('%m月%d日')}）"
            
            # 收集文件活动记录
            print(f"正在收集{date_range}的文件活动记录...")
            file_records = self._collect_file_activities(start_date, end_date)
            
            # 分析工作内容
            work_analysis = self._analyze_work_content(file_records)
            
            # 生成报告
            report = self._generate_report_content(
                date_range, work_analysis, detailed, file_records
            )
            
            return report
            
        except Exception as e:
            return f"生成报告时出错: {str(e)}"
    
    def _collect_file_activities(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """收集文件活动记录"""
        file_records = []
        
        try:
            # 从注册表获取最近文件记录
            registry_files = self._get_recent_files_from_registry()
            print(f"从注册表获取到 {len(registry_files)} 个文件记录")
            file_records.extend(registry_files)
            
            # 从最近文件夹获取记录
            recent_folder_files = self._get_recent_files_from_folder()
            print(f"从最近文件夹获取到 {len(recent_folder_files)} 个文件记录")
            file_records.extend(recent_folder_files)
            
            # 去重
            unique_files = {}
            for record in file_records:
                file_path = record.get('path', '')
                if file_path and file_path not in unique_files:
                    unique_files[file_path] = record
            
            file_records = list(unique_files.values())
            print(f"去重后共 {len(file_records)} 个唯一文件")
            
            # 过滤时间范围
            filtered_records = []
            for record in file_records:
                file_time = record.get('modified_time')
                if file_time and start_date <= file_time <= end_date:
                    filtered_records.append(record)
            
            print(f"时间范围内的文件: {len(filtered_records)} 个")
            return filtered_records
            
        except Exception as e:
            print(f"收集文件活动记录时出错: {e}")
            return []
    
    def _get_recent_files_from_registry(self) -> List[Dict]:
        """从注册表获取最近文件"""
        files = []
        
        try:
            # Office最近文件
            office_keys = [
                r"Software\Microsoft\Office\16.0\Word\File MRU",
                r"Software\Microsoft\Office\16.0\Excel\File MRU",
                r"Software\Microsoft\Office\16.0\PowerPoint\File MRU",
            ]
            
            for key_path in office_keys:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        i = 0
                        while True:
                            try:
                                value_name, value_data, _ = winreg.EnumValue(key, i)
                                if isinstance(value_data, str) and value_data.startswith('[F00000000]'):
                                    # 解析Office MRU格式
                                    file_path = value_data.split('*')[1] if '*' in value_data else value_data
                                    if os.path.exists(file_path):
                                        stat = os.stat(file_path)
                                        files.append({
                                            'path': file_path,
                                            'name': os.path.basename(file_path),
                                            'modified_time': datetime.fromtimestamp(stat.st_mtime),
                                            'source': 'registry_office'
                                        })
                                i += 1
                            except OSError:
                                break
                except (OSError, FileNotFoundError):
                    continue
                    
        except Exception as e:
            print(f"从注册表获取文件时出错: {e}")
        
        return files
    
    def _get_recent_files_from_folder(self) -> List[Dict]:
        """从最近文件夹获取文件"""
        files = []
        
        try:
            # Windows最近文件夹
            recent_folder = os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Recent")
            
            if os.path.exists(recent_folder):
                for file_name in os.listdir(recent_folder):
                    if file_name.endswith('.lnk'):
                        link_path = os.path.join(recent_folder, file_name)
                        try:
                            # 获取快捷方式的目标路径
            
                            stat = os.stat(link_path)
                            files.append({
                                'path': link_path,
                                'name': file_name.replace('.lnk', ''),
                                'modified_time': datetime.fromtimestamp(stat.st_mtime),
                                'source': 'recent_folder'
                            })
                        except (OSError, FileNotFoundError):
                            continue
                            
        except Exception as e:
            print(f"从最近文件夹获取文件时出错: {e}")
        
        return files
    
    def _analyze_work_content(self, file_records: List[Dict]) -> Dict:
        """分析工作内容"""
        analysis = {
            'total_files': len(file_records),
            'work_files': [],
            'companies': set(),
            'work_types': {
                '漏洞扫描': 0,
                '渗透测试': 0,
                '安全评估': 0,
                '通报处置': 0,
                '通报下发': 0,
                '报告编写': 0,
                '其他': 0
            },
            'file_types': {},
            'work_details': {
                '漏洞扫描': [],
                '渗透测试': [],
                '安全评估': [],
                '通报处置': [],
                '通报下发': [],
                '报告编写': [],
                '其他': []
            }
        }
        
        for record in file_records:
            file_name = record.get('name', '')
            file_path = record.get('path', '')
            file_name_lower = file_name.lower()
            file_path_lower = file_path.lower()
            
            # 检查是否为工作相关文件
            is_work_file = any(keyword in file_name_lower or keyword in file_path_lower 
                             for keyword in self.work_keywords)
            
            if is_work_file:
                analysis['work_files'].append(record)
                
                # 根据文件夹路径和文件名进行分类
                work_type = self._classify_work_type(file_name, file_path)
                analysis['work_types'][work_type] += 1
                analysis['work_details'][work_type].append(file_name)
                
                # 提取企业名称
                import re
                for pattern in self.company_patterns:
                    matches = re.findall(pattern, file_name + ' ' + file_path)
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]
                        if len(match) > 2:  # 过滤太短的匹配
                            analysis['companies'].add(match)
            
            # 统计文件类型
            file_ext = os.path.splitext(record.get('name', ''))[1].lower()
            if file_ext:
                analysis['file_types'][file_ext] = analysis['file_types'].get(file_ext, 0) + 1
        
        analysis['companies'] = list(analysis['companies'])
        return analysis
    
    def _classify_work_type(self, file_name: str, file_path: str) -> str:
        """根据文件路径和名称分类工作类型"""
        file_name_lower = file_name.lower()
        file_path_lower = file_path.lower()
        
        # 第一优先级：通报文件夹和处置文件夹的区分
        # 检查路径中是否包含通报文件夹
        if any(folder in file_path_lower for folder in ['通报文件夹', '通报\\', '通报/', 'notification']):
            return '通报下发'
        # 检查路径中是否包含处置文件夹
        if any(folder in file_path_lower for folder in ['处置文件夹', '处置\\', '处置/', 'disposal']):
            return '通报处置'
            
        # 第二优先级：通报相关的文件名
        if '通报下发' in file_name_lower:
            return '通报下发'
        if '通报' in file_name_lower and not any(word in file_name_lower for word in ['处置', '整改']):
            return '通报下发'
        if any(pattern in file_name_lower for pattern in ['处置报告', '整改报告']):
            return '通报处置'
        if any(word in file_name_lower for word in ['处置', '整改', 'disposal']):
            return '通报处置'
        
        # 第二优先级：根据文件夹路径判断
        if '漏扫' in file_path_lower or 'scan' in file_path_lower:
            return '漏洞扫描'
        elif '渗透' in file_path_lower or 'pentest' in file_path_lower:
            return '渗透测试'
        elif '处置' in file_path_lower or 'disposal' in file_path_lower:
            return '通报处置'
        elif '评估' in file_path_lower or 'assessment' in file_path_lower:
            return '安全评估'
        
        # 第三优先级：漏洞通报相关文件判断
        # 检查是否为漏洞通报类文件
        if '漏洞' in file_name_lower or '存在' in file_name_lower or '附件' in file_name_lower:
            # 如果文件名包含企业名称和漏洞描述，归类为通报下发
            if any(pattern in file_name_lower for pattern in ['公司', '集团', '有限', '股份', '企业']) and \
               any(pattern in file_name_lower for pattern in ['存在', '漏洞', '附件']):
                return '通报下发'
        
        # 第四优先级：根据文件名特定模式判断
        if any(pattern in file_name_lower for pattern in ['综述报告', '漏洞报告', '扫描报告']):
            # 如果文件名同时包含通报关键词，优先归类为通报处置
            if '通报' in file_name_lower or '处置' in file_name_lower:
                return '通报处置'
            # 如果文件名包含数字编号和系统名称，可能是通报下发
            if any(digit in file_name_lower for digit in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']) and \
               any(pattern in file_name_lower for pattern in ['系统', '平台', '网站']):
                return '通报下发'
            return '漏洞扫描'
        elif any(pattern in file_name_lower for pattern in ['渗透报告', '测试报告']):
            return '渗透测试'
        elif any(pattern in file_name_lower for pattern in ['评估报告']):
            return '安全评估'
        
        # 第五优先级：根据文件名关键词判断
        if any(word in file_name_lower for word in ['漏洞', '扫描', 'vulnerability', 'scan']):
            # 如果文件名包含企业名称，可能是通报下发
            if any(pattern in file_name_lower for pattern in ['公司', '集团', '有限', '股份', '企业']):
                return '通报下发'
            return '漏洞扫描'
        elif any(word in file_name_lower for word in ['渗透', 'penetration']):
            return '渗透测试'
        elif any(word in file_name_lower for word in ['评估', 'assessment']):
            return '安全评估'
        
        # 通用关键词判断（优先级低）
        if any(word in file_name_lower for word in ['测试', 'test']) and 'penetration' not in file_name_lower:
            return '渗透测试'
        elif any(word in file_name_lower for word in ['报告', 'report']):
            return '报告编写'
        else:
            return '其他'
    
    def _extract_key_info(self, file_name: str, work_type: str) -> str:
        """从文件名中提取关键信息，并以更自然的语言描述
        
        Args:
            file_name: 文件名
            work_type: 工作类型
            
        Returns:
            提取的关键信息，格式化为自然语言描述
        """
        import re
        
        # 移除时间戳和常见前缀
        clean_name = re.sub(r'^\d+', '', file_name)
        clean_name = re.sub(r'^关于', '', clean_name)
        # 移除特殊前缀
        clean_name = re.sub(r'所属门户网站存在信息', '', clean_name)
        
        # 提取企业名称
        company_match = None
        for pattern in self.company_patterns:
            matches = re.findall(pattern, clean_name)
            if matches:
                company_match = matches[0]
                if isinstance(company_match, tuple):
                    company_match = company_match[0]
                break
        
        # 根据工作类型提取关键信息并格式化为自然语言描述
        if work_type == '漏洞扫描':
            # 提取系统名称和漏洞级别
            system_match = re.search(r'([\u4e00-\u9fa5]+(?:系统|平台|网站|管理系统|门户))', clean_name)
            level_match = re.search(r'(高危|中危|低危)', clean_name)
            
            system = system_match.group(1) if system_match else ''
            level = level_match.group(1) if level_match else ''
            
            if system:
                if level:
                    return f"对{system}进行{level}漏洞扫描"
                else:
                    return f"对{system}进行漏洞扫描"
            elif company_match:
                return f"对{company_match}进行漏洞扫描"
            else:
                return "进行了一次漏洞扫描"
                
        elif work_type == '渗透测试':
            # 提取系统名称
            system_match = re.search(r'([\u4e00-\u9fa5]+(?:系统|平台|网站|管理系统|门户))', clean_name)
            system = system_match.group(1) if system_match else ''
            
            if system:
                return f"对{system}进行渗透测试"
            elif company_match:
                return f"对{company_match}进行渗透测试"
            else:
                return "进行了一次渗透测试"
                
        elif work_type in ['通报下发', '通报处置']:
            # 提取漏洞类型和系统名称
            vuln_match = re.search(r'存在([\u4e00-\u9fa5a-zA-Z]+(?:漏洞|风险|问题|隐患))', clean_name)
            system_match = re.search(r'([\u4e00-\u9fa5]+(?:系统|平台|网站|管理系统|门户|Spring|WordPress))', clean_name)
            
            vuln_type = vuln_match.group(1) if vuln_match else '安全漏洞'
            system = system_match.group(1) if system_match else ''
            
            if work_type == '通报下发':
                if company_match and system:
                    return f"向{company_match}下发{system}{vuln_type}通报"
                elif company_match:
                    return f"向{company_match}下发安全漏洞通报"
                elif system:
                    return f"下发{system}安全漏洞通报"
                else:
                    return "下发了一份安全漏洞通报"
            else:  # 通报处置
                if company_match and system:
                    return f"处置{company_match}的{system}{vuln_type}问题"
                elif company_match:
                    return f"处置{company_match}的安全漏洞问题"
                elif system:
                    return f"处置{system}的安全漏洞问题"
                else:
                    return "处置了一起安全漏洞事件"
                
        elif work_type == '报告编写':
            # 提取报告类型
            report_type_match = re.search(r'([\u4e00-\u9fa5]+(?:报告|总结|分析))', clean_name)
            report_type = report_type_match.group(1) if report_type_match else '安全报告'
            
            if company_match:
                return f"编写{company_match}的{report_type}"
            elif '模板' in clean_name.lower():
                return f"编写{report_type}模板"
            else:
                return f"编写了一份{report_type}"
        
        # 默认返回更自然的描述
        if company_match:
            return f"处理{company_match}相关工作"
        else:
            # 尝试提取任何有意义的名称
            name_match = re.search(r'([\u4e00-\u9fa5]{2,})', clean_name)
            if name_match:
                return f"处理{name_match.group(1)}相关工作"
            else:
                return "处理了一项工作"
    
    def _generate_report_content(self, date_range: str, analysis: Dict, 
                               detailed: bool, file_records: List[Dict]) -> str:
        """生成报告内容"""
        report_lines = [
            "工作周报",
            f"统计时间: {date_range}",
            "",
            "工作统计:",
            f"总文件数量: {analysis['total_files']}个",
            f"工作相关文件: {len(analysis['work_files'])}个",
            f"涉及企业数量: {len(analysis['companies'])}家",
            ""
        ]
        
        # 工作类型统计 - 按数量排序
        if any(count > 0 for count in analysis['work_types'].values()):
            report_lines.append("工作类型分布:")
            sorted_work_types = sorted(
                [(work_type, count) for work_type, count in analysis['work_types'].items() if count > 0],
                key=lambda x: x[1],
                reverse=True
            )
            for work_type, count in sorted_work_types:
                report_lines.append(f"{work_type}: {count}个")
            report_lines.append("")
        
        # 涉及企业 - 按字母排序
        if analysis['companies']:
            report_lines.append("涉及企业:")
            sorted_companies = sorted(analysis['companies'])
            for i, company in enumerate(sorted_companies[:10], 1):  # 最多显示10个
                report_lines.append(f"{i}. {company}")
            if len(sorted_companies) > 10:
                report_lines.append(f"... 等共{len(sorted_companies)}家企业")
            report_lines.append("")
        
        # 主要工作内容 - 提取关键信息而不是直接显示文件名
        if analysis['work_files']:
            report_lines.append("主要工作内容:")
            
            # 按工作类型分组显示，并按数量排序
            sorted_work_types = sorted(
                [(work_type, files) for work_type, files in analysis['work_details'].items() if files],
                key=lambda x: len(x[1]),
                reverse=True
            )
            
            for work_type, files in sorted_work_types:
                if files:
                    report_lines.append(f"\n【{work_type}】")
                    
                    # 提取每个文件的关键信息
                    info_dict = {}
                    for file_name in files:
                        key_info = self._extract_key_info(file_name, work_type)
                        info_dict[key_info] = info_dict.get(key_info, 0) + 1
                    
                    # 按关键信息排序并显示
                    sorted_info = sorted(info_dict.items())
                    for key_info, count in sorted_info:
                        if count > 1:
                            report_lines.append(f"{key_info} (共{count}个)")
                        else:
                            report_lines.append(f"{key_info}")
                    
                    if len(files) > 10 and len(sorted_info) < len(files):
                        report_lines.append(f"... 等共{len(files)}个文件")
            report_lines.append("")
        
        # 详细文件列表 - 按修改时间排序
        if detailed and analysis['work_files']:
            report_lines.append("详细文件列表:")
            # 按修改时间排序，最近的文件排在前面
            sorted_records = sorted(analysis['work_files'], 
                                   key=lambda x: x.get('modified_time', datetime.min), 
                                   reverse=True)
            for i, file_record in enumerate(sorted_records, 1):
                file_name = file_record.get('name', '')
                work_type = self._classify_work_type(file_name, file_record.get('path', ''))
                key_info = self._extract_key_info(file_name, work_type)
                
                modified_time = file_record.get('modified_time')
                time_str = modified_time.strftime('%m-%d %H:%M') if modified_time else '未知'
                report_lines.append(f"{i}. [{work_type}] {key_info} ({time_str})")
            report_lines.append("")
        
        # 工作总结
        report_lines.extend([
            "工作总结:",
            f"本{date_range.split('（')[0]}共处理{analysis['total_files']}个文件，"
            f"其中工作相关文件{len(analysis['work_files'])}个，"
            f"涉及{len(analysis['companies'])}家企业的安全工作。",
            "",
            f"主要完成了{', '.join([k for k, v in analysis['work_types'].items() if v > 0])}等工作，"
            "为企业网络安全提供了有力保障。",
            "",
            f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ])
        
        return "\n".join(report_lines)


def main():
    """测试函数"""
    print("周报生成器模块加载成功")
    generator = WeeklyReportGenerator()
    print("周报生成器初始化完成")


if __name__ == "__main__":
    main()