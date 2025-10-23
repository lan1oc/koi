#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模板管理器

提供数据映射模板的管理功能，包括创建、编辑、删除、导入导出模板
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging
from datetime import datetime

class TemplateManager:
    """模板管理器"""
    
    def __init__(self, templates_dir: Optional[Union[str, Path]] = None):
        self.logger = logging.getLogger(__name__)
        
        # 设置模板存储目录
        if templates_dir:
            self.templates_dir = Path(templates_dir)
        else:
            # 默认使用数据处理模块内的templates目录
            self.templates_dir = Path(__file__).parent / 'templates'
        
        # 确保模板目录存在
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # 模板文件路径
        self.templates_file = self.templates_dir / 'templates.json'
        
        # 加载模板
        self.templates = self._load_templates()
    
    def create_template(self, name: str, description: str,
                       field_mapping: Dict[str, str],
                       source_format: str = 'excel',
                       template_format: str = 'excel',
                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        创建新模板
        
        Args:
            name: 模板名称
            description: 模板描述
            field_mapping: 字段映射关系 {模板字段: 源字段}
            source_format: 源文件格式
            template_format: 模板文件格式
            metadata: 额外元数据
            
        Returns:
            创建结果字典
        """
        result = {
            'success': False,
            'message': '',
            'template_id': None
        }
        
        try:
            # 检查模板名称是否已存在
            if self.template_exists(name):
                result['message'] = f"模板名称 '{name}' 已存在"
                return result
            
            # 生成模板ID
            template_id = self._generate_template_id(name)
            
            # 创建模板对象
            template = {
                'id': template_id,
                'name': name,
                'description': description,
                'field_mapping': field_mapping,
                'source_format': source_format,
                'template_format': template_format,
                'metadata': metadata or {},
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'version': '1.0.0',
                'usage_count': 0
            }
            
            # 添加到模板列表
            self.templates[template_id] = template
            
            # 保存模板
            if self._save_templates():
                result['success'] = True
                result['message'] = f"成功创建模板 '{name}'"
                result['template_id'] = template_id
                self.logger.info(f"创建模板: {name} (ID: {template_id})")
            else:
                result['message'] = "保存模板失败"
                # 回滚
                del self.templates[template_id]
            
        except Exception as e:
            result['message'] = f"创建模板失败: {str(e)}"
            self.logger.error(f"创建模板失败: {e}")
        
        return result
    
    def update_template(self, template_id: str, **kwargs) -> Dict[str, Any]:
        """
        更新模板
        
        Args:
            template_id: 模板ID
            **kwargs: 要更新的字段
            
        Returns:
            更新结果字典
        """
        result = {
            'success': False,
            'message': ''
        }
        
        try:
            if template_id not in self.templates:
                result['message'] = f"模板 '{template_id}' 不存在"
                return result
            
            # 更新字段
            template = self.templates[template_id]
            
            updatable_fields = ['name', 'description', 'field_mapping', 'source_format', 
                              'template_format', 'metadata']
            
            for field, value in kwargs.items():
                if field in updatable_fields:
                    template[field] = value
            
            # 更新时间戳
            template['updated_at'] = datetime.now().isoformat()
            
            # 保存模板
            if self._save_templates():
                result['success'] = True
                result['message'] = f"成功更新模板 '{template['name']}'"
                self.logger.info(f"更新模板: {template_id}")
            else:
                result['message'] = "保存模板失败"
            
        except Exception as e:
            result['message'] = f"更新模板失败: {str(e)}"
            self.logger.error(f"更新模板失败: {e}")
        
        return result
    
    def delete_template(self, template_id: str) -> Dict[str, Any]:
        """
        删除模板
        
        Args:
            template_id: 模板ID
            
        Returns:
            删除结果字典
        """
        result = {
            'success': False,
            'message': ''
        }
        
        try:
            if template_id not in self.templates:
                result['message'] = f"模板 '{template_id}' 不存在"
                return result
            
            template_name = self.templates[template_id]['name']
            
            # 删除模板
            del self.templates[template_id]
            
            # 保存模板
            if self._save_templates():
                result['success'] = True
                result['message'] = f"成功删除模板 '{template_name}'"
                self.logger.info(f"删除模板: {template_id}")
            else:
                result['message'] = "保存模板失败"
            
        except Exception as e:
            result['message'] = f"删除模板失败: {str(e)}"
            self.logger.error(f"删除模板失败: {e}")
        
        return result
    
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        获取模板
        
        Args:
            template_id: 模板ID
            
        Returns:
            模板字典或None
        """
        return self.templates.get(template_id)
    
    def get_template_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        根据名称获取模板
        
        Args:
            name: 模板名称
            
        Returns:
            模板字典或None
        """
        for template in self.templates.values():
            if template['name'] == name:
                return template
        return None
    
    def list_templates(self, filter_format: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出所有模板
        
        Args:
            filter_format: 过滤格式
            
        Returns:
            模板列表
        """
        templates = list(self.templates.values())
        
        if filter_format:
            templates = [t for t in templates if t.get('source_format') == filter_format]
        
        # 按创建时间排序
        templates.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return templates
    
    def template_exists(self, name: str) -> bool:
        """
        检查模板是否存在
        
        Args:
            name: 模板名称
            
        Returns:
            是否存在
        """
        return any(template['name'] == name for template in self.templates.values())
    
    def use_template(self, template_id: str) -> Dict[str, Any]:
        """
        使用模板（增加使用计数）
        
        Args:
            template_id: 模板ID
            
        Returns:
            模板字典
        """
        if template_id in self.templates:
            self.templates[template_id]['usage_count'] += 1
            self.templates[template_id]['last_used'] = datetime.now().isoformat()
            self._save_templates()
            return self.templates[template_id]
        return {}
    
    def export_template(self, template_id: str, export_path: Union[str, Path]) -> Dict[str, Any]:
        """
        导出模板
        
        Args:
            template_id: 模板ID
            export_path: 导出路径
            
        Returns:
            导出结果字典
        """
        result = {
            'success': False,
            'message': '',
            'export_file': None
        }
        
        try:
            if template_id not in self.templates:
                result['message'] = f"模板 '{template_id}' 不存在"
                return result
            
            template = self.templates[template_id]
            export_path = Path(export_path)
            
            # 确保文件扩展名
            if not export_path.suffix:
                export_path = export_path.with_suffix('.json')
            
            # 导出模板
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
            
            result['success'] = True
            result['message'] = f"成功导出模板 '{template['name']}'"
            result['export_file'] = str(export_path)
            
            self.logger.info(f"导出模板: {template_id} -> {export_path}")
            
        except Exception as e:
            result['message'] = f"导出模板失败: {str(e)}"
            self.logger.error(f"导出模板失败: {e}")
        
        return result
    
    def import_template(self, import_path: Union[str, Path], 
                       overwrite: bool = False) -> Dict[str, Any]:
        """
        导入模板
        
        Args:
            import_path: 导入路径
            overwrite: 是否覆盖同名模板
            
        Returns:
            导入结果字典
        """
        result = {
            'success': False,
            'message': '',
            'template_id': None
        }
        
        try:
            import_path = Path(import_path)
            
            if not import_path.exists():
                result['message'] = f"文件不存在: {import_path}"
                return result
            
            # 读取模板文件
            with open(import_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
            
            # 验证模板格式
            required_fields = ['name', 'description', 'field_mapping']
            for field in required_fields:
                if field not in template_data:
                    result['message'] = f"模板文件缺少必需字段: {field}"
                    return result
            
            # 检查是否已存在同名模板
            if self.template_exists(template_data['name']) and not overwrite:
                result['message'] = f"模板 '{template_data['name']}' 已存在，使用overwrite=True覆盖"
                return result
            
            # 生成新的模板ID
            template_id = self._generate_template_id(template_data['name'])
            template_data['id'] = template_id
            
            # 更新时间戳
            template_data['imported_at'] = datetime.now().isoformat()
            if 'created_at' not in template_data:
                template_data['created_at'] = datetime.now().isoformat()
            template_data['updated_at'] = datetime.now().isoformat()
            
            # 重置使用计数
            template_data['usage_count'] = 0
            
            # 添加到模板列表
            self.templates[template_id] = template_data
            
            # 保存模板
            if self._save_templates():
                result['success'] = True
                result['message'] = f"成功导入模板 '{template_data['name']}'"
                result['template_id'] = template_id
                self.logger.info(f"导入模板: {import_path} -> {template_id}")
            else:
                result['message'] = "保存模板失败"
                # 回滚
                del self.templates[template_id]
            
        except Exception as e:
            result['message'] = f"导入模板失败: {str(e)}"
            self.logger.error(f"导入模板失败: {e}")
        
        return result
    
    def search_templates(self, keyword: str) -> List[Dict[str, Any]]:
        """
        搜索模板
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的模板列表
        """
        keyword = keyword.lower()
        matched_templates = []
        
        for template in self.templates.values():
            # 在名称、描述中搜索
            if (keyword in template['name'].lower() or 
                keyword in template['description'].lower()):
                matched_templates.append(template)
        
        # 按相关性排序（简单的匹配度计算）
        def relevance_score(template):
            score = 0
            if keyword in template['name'].lower():
                score += 10
            if keyword in template['description'].lower():
                score += 5
            return score
        
        matched_templates.sort(key=relevance_score, reverse=True)
        
        return matched_templates
    
    def get_template_statistics(self) -> Dict[str, Any]:
        """
        获取模板统计信息
        
        Returns:
            统计信息字典
        """
        if not self.templates:
            return {
                'total_templates': 0,
                'most_used': None,
                'recently_created': None,
                'format_distribution': {}
            }
        
        templates = list(self.templates.values())
        
        # 最常用的模板
        most_used = max(templates, key=lambda x: x.get('usage_count', 0))
        
        # 最近创建的模板
        recently_created = max(templates, key=lambda x: x.get('created_at', ''))
        
        # 格式分布
        format_distribution = {}
        for template in templates:
            fmt = template.get('source_format', 'unknown')
            format_distribution[fmt] = format_distribution.get(fmt, 0) + 1
        
        return {
            'total_templates': len(templates),
            'most_used': {
                'name': most_used['name'],
                'usage_count': most_used.get('usage_count', 0)
            },
            'recently_created': {
                'name': recently_created['name'],
                'created_at': recently_created.get('created_at', '')
            },
            'format_distribution': format_distribution
        }
    
    def _load_templates(self) -> Dict[str, Dict[str, Any]]:
        """
        加载模板文件
        
        Returns:
            模板字典
        """
        try:
            if self.templates_file.exists():
                with open(self.templates_file, 'r', encoding='utf-8') as f:
                    templates = json.load(f)
                self.logger.info(f"加载了 {len(templates)} 个模板")
                return templates
            else:
                # 创建默认模板
                default_templates = self._create_default_templates()
                self._save_templates_to_file(default_templates)
                return default_templates
        except Exception as e:
            self.logger.error(f"加载模板失败: {e}")
            return {}
    
    def _save_templates(self) -> bool:
        """
        保存模板到文件
        
        Returns:
            是否保存成功
        """
        return self._save_templates_to_file(self.templates)
    
    def _save_templates_to_file(self, templates: Dict[str, Dict[str, Any]]) -> bool:
        """
        保存模板到指定文件
        
        Args:
            templates: 模板字典
            
        Returns:
            是否保存成功
        """
        try:
            with open(self.templates_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"保存模板失败: {e}")
            return False
    
    def _generate_template_id(self, name: str) -> str:
        """
        生成模板ID
        
        Args:
            name: 模板名称
            
        Returns:
            模板ID
        """
        import hashlib
        import time
        
        # 使用名称和时间戳生成唯一ID
        unique_string = f"{name}_{time.time()}"
        return hashlib.md5(unique_string.encode()).hexdigest()[:12]
    
    def _create_default_templates(self) -> Dict[str, Dict[str, Any]]:
        """
        创建默认模板
        
        Returns:
            默认模板字典
        """
        default_templates = {}
        
        # 暴露面收集模板
        exposure_template = {
            'id': 'exposure_template_001',
            'name': '暴露面收集模板',
            'description': '用于暴露面收集数据的标准模板',
            'field_mapping': {
                'IP地址': 'ip',
                '端口': 'port',
                '协议': 'protocol',
                '服务': 'service',
                '标题': 'title',
                '状态码': 'status',
                '国家': 'country',
                '城市': 'city',
                '组织': 'org'
            },
            'source_format': 'excel',
            'template_format': 'excel',
            'metadata': {
                'category': 'security',
                'tags': ['暴露面', '网络安全', 'IP扫描']
            },
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'version': '1.0.0',
            'usage_count': 0
        }
        
        default_templates['exposure_template_001'] = exposure_template
        
        return default_templates