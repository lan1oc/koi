#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据填充器

提供将源文件数据按照模板格式进行填充和转换的功能
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging
import re
from .excel_processor import ExcelProcessor

class DataFiller:
    """数据填充器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.excel_processor = ExcelProcessor()
    
    def fill_template(self, source_file: Union[str, Path],
                     template_file: Union[str, Path],
                     field_mapping: Dict[str, str],
                     output_file: Union[str, Path],
                     source_sheet: Optional[str] = None,
                     template_sheet: Optional[str] = None) -> Dict[str, Any]:
        """
        使用模板填充数据（自动检测源文件格式）
        
        Args:
            source_file: 源数据文件路径
            template_file: 模板文件路径
            field_mapping: 字段映射关系 {模板字段: 源字段}
            output_file: 输出文件路径
            source_sheet: 源文件工作表名称
            template_sheet: 模板文件工作表名称
            
        Returns:
            填充结果字典
        """
        result = {
            'success': False,
            'message': '',
            'output_file': None,
            'statistics': {},
            'warnings': []
        }
        
        try:
            source_path = Path(source_file)
            source_suffix = source_path.suffix.lower()
            
            # 根据文件扩展名选择读取方式
            if source_suffix in ['.txt', '.csv', '.tsv']:
                # 文本文件，使用fill_from_text方法
                return self.fill_from_text(
                    source_file=source_file,
                    template_file=template_file,
                    field_mapping=field_mapping,
                    output_file=output_file,
                    delimiter='\t' if source_suffix == '.txt' or source_suffix == '.tsv' else ',',
                    encoding='utf-8'
                )
            elif source_suffix in ['.xlsx', '.xls']:
                # Excel文件，使用原有逻辑
                # 读取源数据
                source_df = self.excel_processor.read_excel(source_file, source_sheet)
                self.logger.info(f"读取源数据: {source_df.shape}")
                
                # 读取模板
                template_df = self.excel_processor.read_excel(template_file, template_sheet)
                self.logger.info(f"读取模板: {template_df.shape}")
                
                # 验证字段映射
                validation_result = self._validate_field_mapping(source_df, template_df, field_mapping)
                if not validation_result['valid']:
                    result['message'] = validation_result['message']
                    result['warnings'] = validation_result['warnings']
                    return result
                
                result['warnings'].extend(validation_result['warnings'])
                
                # 执行数据填充
                filled_df = self._perform_data_filling(source_df, template_df, field_mapping)
                
                # 保存结果
                output_path = Path(output_file)
                if not output_path.suffix:
                    output_path = output_path.with_suffix('.xlsx')
                
                success = self.excel_processor.write_excel(filled_df, output_path)
                if not success:
                    result['message'] = "保存文件失败"
                    return result
                
                # 生成统计信息
                statistics = self._generate_filling_statistics(source_df, template_df, filled_df)
                
                result['success'] = True
                result['message'] = f"成功填充 {len(filled_df)} 行数据到模板"
                result['output_file'] = str(output_path)
                result['statistics'] = statistics
                
                self.logger.info(f"数据填充完成: {source_file} -> {output_file}")
            else:
                result['message'] = f"不支持的源文件格式: {source_suffix}。支持的格式: .txt, .csv, .tsv, .xlsx, .xls"
                self.logger.error(result['message'])
            
        except Exception as e:
            result['message'] = f"填充失败: {str(e)}"
            self.logger.error(f"数据填充失败: {e}")
        
        return result
    
    def fill_from_text(self, source_file: Union[str, Path],
                      template_file: Union[str, Path],
                      field_mapping: Dict[str, str],
                      output_file: Union[str, Path],
                      delimiter: str = '\t',
                      encoding: str = 'utf-8') -> Dict[str, Any]:
        """
        从文本文件填充模板
        
        Args:
            source_file: 源文本文件路径
            template_file: 模板Excel文件路径
            field_mapping: 字段映射关系
            output_file: 输出文件路径
            delimiter: 分隔符
            encoding: 文件编码
            
        Returns:
            填充结果字典
        """
        result = {
            'success': False,
            'message': '',
            'output_file': None,
            'statistics': {},
            'warnings': []
        }
        
        try:
            # 读取文本文件
            source_df = pd.read_csv(source_file, delimiter=delimiter, encoding=encoding)
            self.logger.info(f"读取文本数据: {source_df.shape}")
            
            # 读取模板
            template_df = self.excel_processor.read_excel(template_file)
            self.logger.info(f"读取模板: {template_df.shape}")
            
            # 验证字段映射
            validation_result = self._validate_field_mapping(source_df, template_df, field_mapping)
            if not validation_result['valid']:
                result['message'] = validation_result['message']
                result['warnings'] = validation_result['warnings']
                return result
            
            result['warnings'].extend(validation_result['warnings'])
            
            # 执行数据填充
            filled_df = self._perform_data_filling(source_df, template_df, field_mapping)
            
            # 保存结果
            output_path = Path(output_file)
            if not output_path.suffix:
                output_path = output_path.with_suffix('.xlsx')
            
            success = self.excel_processor.write_excel(filled_df, output_path)
            if not success:
                result['message'] = "保存文件失败"
                return result
            
            # 生成统计信息
            statistics = self._generate_filling_statistics(source_df, template_df, filled_df)
            
            result['success'] = True
            result['message'] = f"成功从文本文件填充 {len(filled_df)} 行数据到模板"
            result['output_file'] = str(output_path)
            result['statistics'] = statistics
            
        except Exception as e:
            result['message'] = f"文本填充失败: {str(e)}"
            self.logger.error(f"文本填充失败: {e}")
        
        return result
    
    def preview_filling(self, source_file: Union[str, Path],
                       template_file: Union[str, Path],
                       field_mapping: Dict[str, str],
                       preview_rows: int = 10,
                       source_sheet: Optional[str] = None,
                       template_sheet: Optional[str] = None) -> Dict[str, Any]:
        """
        预览数据填充结果
        
        Args:
            source_file: 源数据文件路径
            template_file: 模板文件路径
            field_mapping: 字段映射关系
            preview_rows: 预览行数
            source_sheet: 源文件工作表名称
            template_sheet: 模板文件工作表名称
            
        Returns:
            预览结果字典
        """
        result = {
            'success': False,
            'message': '',
            'preview_data': None,
            'mapping_info': {},
            'warnings': []
        }
        
        try:
            # 读取源数据
            source_df = self.excel_processor.read_excel(source_file, source_sheet)
            
            # 读取模板
            template_df = self.excel_processor.read_excel(template_file, template_sheet)
            
            # 验证字段映射
            validation_result = self._validate_field_mapping(source_df, template_df, field_mapping)
            if not validation_result['valid']:
                result['message'] = validation_result['message']
                result['warnings'] = validation_result['warnings']
                return result
            
            result['warnings'].extend(validation_result['warnings'])
            
            # 执行数据填充（仅预览行数）
            preview_source = source_df.head(preview_rows)
            filled_df = self._perform_data_filling(preview_source, template_df, field_mapping)
            
            # 生成预览数据
            preview_data = filled_df.to_dict('records')
            
            # 生成映射信息
            mapping_info = self._generate_mapping_info(source_df, template_df, field_mapping)
            
            result['success'] = True
            result['message'] = f"预览前 {len(filled_df)} 行填充结果"
            result['preview_data'] = preview_data
            result['mapping_info'] = mapping_info
            
        except Exception as e:
            result['message'] = f"预览失败: {str(e)}"
            self.logger.error(f"预览失败: {e}")
        
        return result
    
    def auto_map_fields(self, source_file: Union[str, Path],
                       template_file: Union[str, Path],
                       source_sheet: Optional[str] = None,
                       template_sheet: Optional[str] = None,
                       similarity_threshold: float = 0.6) -> Dict[str, Any]:
        """
        自动映射字段
        
        Args:
            source_file: 源数据文件路径
            template_file: 模板文件路径
            source_sheet: 源文件工作表名称
            template_sheet: 模板文件工作表名称
            similarity_threshold: 相似度阈值
            
        Returns:
            自动映射结果字典
        """
        result = {
            'success': False,
            'message': '',
            'auto_mapping': {},
            'confidence_scores': {},
            'unmapped_fields': []
        }
        
        try:
            # 读取文件获取字段信息
            source_df = self.excel_processor.read_excel(source_file, source_sheet)
            template_df = self.excel_processor.read_excel(template_file, template_sheet)
            
            source_fields = source_df.columns.tolist()
            template_fields = template_df.columns.tolist()
            
            # 执行自动映射
            auto_mapping = {}
            confidence_scores = {}
            unmapped_fields = []
            
            for template_field in template_fields:
                best_match = None
                best_score = 0
                
                for source_field in source_fields:
                    score = self._calculate_field_similarity(template_field, source_field)
                    if score > best_score and score >= similarity_threshold:
                        best_score = score
                        best_match = source_field
                
                if best_match:
                    auto_mapping[template_field] = best_match
                    confidence_scores[template_field] = best_score
                else:
                    unmapped_fields.append(template_field)
            
            result['success'] = True
            result['message'] = f"自动映射了 {len(auto_mapping)} 个字段，{len(unmapped_fields)} 个字段未映射"
            result['auto_mapping'] = auto_mapping
            result['confidence_scores'] = confidence_scores
            result['unmapped_fields'] = unmapped_fields
            
        except Exception as e:
            result['message'] = f"自动映射失败: {str(e)}"
            self.logger.error(f"自动映射失败: {e}")
        
        return result
    
    def _validate_field_mapping(self, source_df: pd.DataFrame, 
                               template_df: pd.DataFrame,
                               field_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        验证字段映射
        
        Args:
            source_df: 源数据
            template_df: 模板数据
            field_mapping: 字段映射 (key: 模板字段名, value: 源文件字段名)
            
        Returns:
            验证结果
        """
        result = {
            'valid': True,
            'message': '',
            'warnings': []
        }
        
        source_fields = source_df.columns.tolist()
        template_fields = template_df.columns.tolist()
        
        # 检查模板字段是否存在 (field_mapping的key是模板字段)
        missing_template_fields = [field for field in field_mapping.keys() if field not in template_fields]
        if missing_template_fields:
            result['valid'] = False
            result['message'] = f"模板中不存在以下字段: {', '.join(missing_template_fields)}"
            return result
        
        # 检查源字段是否存在 (field_mapping的value是源文件字段)
        missing_source_fields = [field for field in field_mapping.values() if field not in source_fields]
        if missing_source_fields:
            result['valid'] = False
            result['message'] = f"源数据中不存在以下字段: {', '.join(missing_source_fields)}"
            return result
        
        # 检查未映射的模板字段
        unmapped_template_fields = [field for field in template_fields if field not in field_mapping]
        if unmapped_template_fields:
            result['warnings'].append(f"以下模板字段未映射，将保持为空: {', '.join(unmapped_template_fields)}")
        
        return result
    
    def _perform_data_filling(self, source_df: pd.DataFrame,
                             template_df: pd.DataFrame,
                             field_mapping: Dict[str, str]) -> pd.DataFrame:
        """
        执行数据填充
        
        Args:
            source_df: 源数据
            template_df: 模板数据
            field_mapping: 字段映射
            
        Returns:
            填充后的数据
        """
        # 创建结果DataFrame，使用模板的列结构
        result_df = pd.DataFrame(columns=template_df.columns)
        
        # 根据映射关系填充数据
        for template_field, source_field in field_mapping.items():
            if source_field in source_df.columns:
                result_df[template_field] = source_df[source_field].values
        
        # 确保数据长度一致
        if len(result_df) != len(source_df):
            # 重新设置索引以匹配源数据长度
            result_df = result_df.reindex(range(len(source_df)))
            
            # 重新填充数据
            for template_field, source_field in field_mapping.items():
                if source_field in source_df.columns:
                    result_df[template_field] = source_df[source_field].values
        
        return result_df
    
    def _generate_filling_statistics(self, source_df: pd.DataFrame,
                                   template_df: pd.DataFrame,
                                   filled_df: pd.DataFrame) -> Dict[str, Any]:
        """
        生成填充统计信息
        
        Args:
            source_df: 源数据
            template_df: 模板数据
            filled_df: 填充后数据
            
        Returns:
            统计信息字典
        """
        try:
            statistics = {
                'source_info': {
                    'rows': len(source_df),
                    'columns': len(source_df.columns)
                },
                'template_info': {
                    'rows': len(template_df),
                    'columns': len(template_df.columns)
                },
                'result_info': {
                    'rows': len(filled_df),
                    'columns': len(filled_df.columns)
                },
                'filling_ratio': {
                    'mapped_columns': sum(1 for col in filled_df.columns if bool(filled_df[col].notna().any())),
                    'total_columns': len(filled_df.columns)
                },
                'data_quality': {
                    'total_cells': len(filled_df) * len(filled_df.columns),
                    'filled_cells': len(filled_df) * len(filled_df.columns) - filled_df.isna().sum().sum(),
                    'empty_cells': filled_df.isna().sum().sum()
                }
            }
            
            # 计算填充率
            if statistics['filling_ratio']['total_columns'] > 0:
                statistics['filling_ratio']['percentage'] = round(
                    statistics['filling_ratio']['mapped_columns'] / statistics['filling_ratio']['total_columns'] * 100, 2
                )
            else:
                statistics['filling_ratio']['percentage'] = 0
            
            return statistics
            
        except Exception as e:
            self.logger.error(f"生成统计信息失败: {e}")
            return {}
    
    def _generate_mapping_info(self, source_df: pd.DataFrame,
                              template_df: pd.DataFrame,
                              field_mapping: Dict[str, str]) -> Dict[str, Any]:
        """
        生成映射信息
        
        Args:
            source_df: 源数据
            template_df: 模板数据
            field_mapping: 字段映射
            
        Returns:
            映射信息字典
        """
        mapping_info = {
            'mapped_fields': {},
            'unmapped_template_fields': [],
            'unused_source_fields': []
        }
        
        # 映射字段信息
        for template_field, source_field in field_mapping.items():
            mapping_info['mapped_fields'][template_field] = {
                'source_field': source_field,
                'source_type': str(source_df[source_field].dtype) if source_field in source_df.columns else 'unknown',
                'template_type': str(template_df[template_field].dtype) if template_field in template_df.columns else 'unknown',
                'source_sample': source_df[source_field].dropna().head(3).tolist() if source_field in source_df.columns else [],
                'null_count': int(source_df[source_field].isna().sum()) if source_field in source_df.columns else 0
            }
        
        # 未映射的模板字段
        mapping_info['unmapped_template_fields'] = [
            field for field in template_df.columns if field not in field_mapping
        ]
        
        # 未使用的源字段
        mapping_info['unused_source_fields'] = [
            field for field in source_df.columns if field not in field_mapping.values()
        ]
        
        return mapping_info
    
    def _calculate_field_similarity(self, field1: str, field2: str) -> float:
        """
        计算字段名相似度
        
        Args:
            field1: 字段1
            field2: 字段2
            
        Returns:
            相似度分数 (0-1)
        """
        try:
            from difflib import SequenceMatcher
            
            # 转换为小写并去除空格
            f1 = re.sub(r'\s+', '', field1.lower())
            f2 = re.sub(r'\s+', '', field2.lower())
            
            # 计算字符串相似度
            similarity = SequenceMatcher(None, f1, f2).ratio()
            
            # 检查是否包含相同的关键词
            keywords1 = set(re.findall(r'\w+', f1))
            keywords2 = set(re.findall(r'\w+', f2))
            
            if keywords1 and keywords2:
                keyword_similarity = len(keywords1 & keywords2) / len(keywords1 | keywords2)
                # 综合字符串相似度和关键词相似度
                similarity = (similarity + keyword_similarity) / 2
            
            return similarity
            
        except Exception:
            return 0.0
    
    def batch_fill(self, fill_configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量填充数据
        
        Args:
            fill_configs: 填充配置列表
            
        Returns:
            批量填充结果列表
        """
        results = []
        
        for i, config in enumerate(fill_configs):
            try:
                self.logger.info(f"开始处理第 {i+1}/{len(fill_configs)} 个填充任务")
                
                result = self.fill_template(
                    source_file=config['source_file'],
                    template_file=config['template_file'],
                    field_mapping=config['field_mapping'],
                    output_file=config['output_file'],
                    source_sheet=config.get('source_sheet'),
                    template_sheet=config.get('template_sheet')
                )
                
                result['config_index'] = i
                results.append(result)
                
            except Exception as e:
                error_result = {
                    'success': False,
                    'message': f"处理失败: {str(e)}",
                    'config_index': i
                }
                results.append(error_result)
                self.logger.error(f"批量填充第 {i+1} 个任务失败: {e}")
        
        return results