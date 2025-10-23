#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字段提取器

提供从Excel文件中提取指定字段的功能
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging
import csv
from .excel_processor import ExcelProcessor

class FieldExtractor:
    """字段提取器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.excel_processor = ExcelProcessor()
        self.supported_formats = ['.xlsx', '.xls', '.csv', '.txt']
    
    def _read_file(self, file_path: Union[str, Path], sheet_name: Optional[str] = None, custom_separator: Optional[str] = None) -> tuple[pd.DataFrame, str]:
        """        读取文件，支持Excel、CSV、TXT格式
        
        Args:
            file_path: 文件路径
            sheet_name: 工作表名称（仅对Excel文件有效）
            custom_separator: 自定义分隔符
            
        Returns:
            tuple: (pandas DataFrame对象, 检测到的分隔符)
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
            Exception: 读取失败
        """
        file_path = Path(file_path)
        
        # 检查文件是否存在
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 检查文件格式
        file_suffix = file_path.suffix.lower()
        if file_suffix not in self.supported_formats:
            raise ValueError(f"不支持的文件格式: {file_suffix}。支持的格式: {', '.join(self.supported_formats)}")
        
        try:
            if file_suffix in ['.xlsx', '.xls']:
                # Excel文件
                df = self.excel_processor.read_excel(file_path, sheet_name)
                return df, 'Excel格式'
            elif file_suffix == '.csv':
                # CSV文件
                if custom_separator:
                    # 使用自定义分隔符
                    encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']
                    for encoding in encodings:
                        try:
                            df = pd.read_csv(file_path, sep=custom_separator, encoding=encoding)
                            return df, f'自定义分隔符: "{custom_separator}"'
                        except UnicodeDecodeError:
                            continue
                    df = pd.read_csv(file_path, sep=custom_separator, encoding='utf-8', on_bad_lines='skip')
                    return df, f'自定义分隔符: "{custom_separator}"'
                else:
                    # 尝试不同的编码
                    encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']
                    for encoding in encodings:
                        try:
                            df = pd.read_csv(file_path, encoding=encoding)
                            return df, '逗号分隔符 (",")'
                        except UnicodeDecodeError:
                            continue
                    # 如果所有编码都失败，使用默认编码并忽略错误
                    df = pd.read_csv(file_path, encoding='utf-8', on_bad_lines='skip')
                    return df, '逗号分隔符 (",")'
            elif file_suffix == '.txt':
                # TXT文件，尝试不同的分隔符
                encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']
                
                if custom_separator:
                    # 使用自定义分隔符
                    for encoding in encodings:
                        try:
                            if custom_separator == r'\s+':
                                df = pd.read_csv(file_path, sep=r'\s+', encoding=encoding, engine='python')
                            else:
                                df = pd.read_csv(file_path, sep=custom_separator, encoding=encoding)
                            return df, f'自定义分隔符: "{custom_separator}"'
                        except (UnicodeDecodeError, pd.errors.ParserError):
                            continue
                    # 如果失败，尝试按行读取
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        return pd.DataFrame({'content': [line.strip() for line in lines]}), '按行读取'
                    except UnicodeDecodeError:
                        with open(file_path, 'r', encoding='gbk') as f:
                            lines = f.readlines()
                        return pd.DataFrame({'content': [line.strip() for line in lines]}), '按行读取'
                else:
                    # 自动检测分隔符
                    separators = [
                        ('\t', r'制表符 ("\t")'),
                        (',', '逗号 (",")'),
                        ('|', '竖线 ("|")'),
                        (';', r'分号 (";")')
                    ]
                    
                    for encoding in encodings:
                        for sep, sep_name in separators:
                            try:
                                df = pd.read_csv(file_path, sep=sep, encoding=encoding)
                                # 如果成功读取且有多列，则认为找到了正确的分隔符
                                if len(df.columns) > 1:
                                    return df, sep_name
                            except (UnicodeDecodeError, pd.errors.ParserError):
                                continue
                    
                    # 尝试处理空格分隔的表格格式（如url.txt这种格式）
                    for encoding in encodings:
                        try:
                            # 使用正则表达式分隔多个空格
                            df = pd.read_csv(file_path, sep=r'\s+', encoding=encoding, engine='python')
                            # 如果成功读取且有合理的列数（2-20列），则认为找到了正确的格式
                            if 2 <= len(df.columns) <= 20:
                                return df, r'多空格分隔符 ("\s+")'
                        except (UnicodeDecodeError, pd.errors.ParserError):
                            continue
                    
                    # 如果都失败，尝试按行读取
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        return pd.DataFrame({'content': [line.strip() for line in lines]}), '按行读取'
                    except UnicodeDecodeError:
                        with open(file_path, 'r', encoding='gbk') as f:
                            lines = f.readlines()
                        return pd.DataFrame({'content': [line.strip() for line in lines]}), '按行读取'
            else:
                # 不支持的文件格式，返回空DataFrame
                return pd.DataFrame(), '未知格式'
            
        except Exception as e:
            raise Exception(f"读取文件失败: {e}")
    
    def _save_file(self, df: pd.DataFrame, file_path: Union[str, Path]) -> bool:
        """
        保存文件，支持Excel、CSV格式
        
        Args:
            df: 要保存的DataFrame
            file_path: 输出文件路径
            
        Returns:
            bool: 保存是否成功
        """
        try:
            file_path = Path(file_path)
            file_suffix = file_path.suffix.lower()
            
            if file_suffix in ['.xlsx', '.xls']:
                # Excel文件
                return self.excel_processor.write_excel(df, file_path)
            elif file_suffix == '.csv':
                # CSV文件
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                return True
            elif file_suffix == '.txt':
                # TXT文件，使用制表符分隔
                df.to_csv(file_path, index=False, sep='\t', encoding='utf-8-sig')
                return True
            else:
                # 默认保存为CSV
                df.to_csv(file_path.with_suffix('.csv'), index=False, encoding='utf-8-sig')
                return True
                
        except Exception as e:
            self.logger.error(f"保存文件失败: {e}")
            return False
    
    def extract_fields(self, source_file: Union[str, Path], 
                      selected_fields: List[str],
                      output_file: Optional[Union[str, Path]] = None,
                      sheet_name: Optional[str] = None,
                      custom_separator: Optional[str] = None) -> Dict[str, Any]:
        """
        从Excel文件中提取指定字段
        
        Args:
            source_file: 源Excel文件路径
            selected_fields: 要提取的字段列表
            output_file: 输出文件路径，None表示不保存
            sheet_name: 工作表名称
            
        Returns:
            提取结果字典
        """
        result = {
            'success': False,
            'message': '',
            'extracted_data': None,
            'output_file': None,
            'statistics': {}
        }
        
        try:
            # 读取源文件
            df, detected_separator = self._read_file(source_file, sheet_name, custom_separator)
            result['detected_separator'] = detected_separator
            
            # 验证字段是否存在
            available_fields = df.columns.tolist()
            missing_fields = [field for field in selected_fields if field not in available_fields]
            
            if missing_fields:
                result['message'] = f"以下字段不存在: {', '.join(missing_fields)}"
                return result
            
            # 提取指定字段
            extracted_df = df[selected_fields].copy()
            # 确保返回DataFrame类型
            if not isinstance(extracted_df, pd.DataFrame):
                extracted_df = pd.DataFrame(extracted_df)
            
            # 生成统计信息
            statistics = self._generate_statistics(extracted_df, df)
            
            # 保存到文件
            if output_file:
                output_path = Path(output_file)
                if not output_path.suffix:
                    output_path = output_path.with_suffix('.csv')
                
                success = self._save_file(extracted_df, output_path)
                if success:
                    result['output_file'] = str(output_path)
                else:
                    result['message'] = "保存文件失败"
                    return result
            
            result['success'] = True
            result['message'] = f"成功提取 {len(selected_fields)} 个字段，共 {len(extracted_df)} 行数据"
            # 将DataFrame转换为列表格式，便于UI显示
            result['extracted_data'] = extracted_df.values.tolist()
            result['selected_fields'] = selected_fields
            result['statistics'] = statistics
            
            self.logger.info(f"字段提取完成: {source_file} -> {output_file}")
            
        except Exception as e:
            result['message'] = f"提取失败: {str(e)}"
            self.logger.error(f"字段提取失败: {e}")
        
        return result
    
    def preview_extraction(self, source_file: Union[str, Path],
                          selected_fields: List[str],
                          sheet_name: Optional[str] = None,
                          preview_rows: int = 10,
                          custom_separator: Optional[str] = None) -> Dict[str, Any]:
        """
        预览字段提取结果
        
        Args:
            source_file: 源Excel文件路径
            selected_fields: 要提取的字段列表
            sheet_name: 工作表名称
            preview_rows: 预览行数
            
        Returns:
            预览结果字典
        """
        result = {
            'success': False,
            'message': '',
            'preview_data': None,
            'field_info': {},
            'statistics': {}
        }
        
        try:
            # 读取源文件
            df, detected_separator = self._read_file(source_file, sheet_name, custom_separator)
            result['detected_separator'] = detected_separator
            
            # 验证字段是否存在
            available_fields = df.columns.tolist()
            missing_fields = [field for field in selected_fields if field not in available_fields]
            
            if missing_fields:
                result['message'] = f"以下字段不存在: {', '.join(missing_fields)}"
                return result
            
            # 提取指定字段
            extracted_df = df[selected_fields].copy()
            # 确保返回DataFrame类型
            if not isinstance(extracted_df, pd.DataFrame):
                extracted_df = pd.DataFrame(extracted_df)
            
            # 生成预览数据
            preview_data = extracted_df.head(preview_rows).to_dict(orient='records')
            
            # 生成字段信息
            field_info = {}
            for field in selected_fields:
                field_info[field] = {
                    'data_type': str(df[field].dtype),
                    'null_count': int(df[field].isnull().sum()),
                    'unique_count': int(df[field].nunique()),
                    'sample_values': df[field].dropna().head(3).tolist()
                }
            
            # 生成统计信息
            statistics = self._generate_statistics(extracted_df, df)
            
            result['success'] = True
            result['message'] = f"预览 {len(selected_fields)} 个字段的前 {min(preview_rows, len(extracted_df))} 行数据"
            result['preview_data'] = preview_data
            result['field_info'] = field_info
            result['statistics'] = statistics
            
        except Exception as e:
            result['message'] = f"预览失败: {str(e)}"
            self.logger.error(f"预览失败: {e}")
        
        return result
    
    def get_available_fields(self, source_file: Union[str, Path],
                           sheet_name: Optional[str] = None,
                           custom_separator: Optional[str] = None) -> Dict[str, Any]:
        """
        获取文件中所有可用字段
        
        Args:
            source_file: 源Excel文件路径
            sheet_name: 工作表名称
            
        Returns:
            字段信息字典
        """
        result = {
            'success': False,
            'message': '',
            'fields': [],
            'field_details': {}
        }
        
        try:
            # 读取源文件
            df, detected_separator = self._read_file(source_file, sheet_name, custom_separator)
            result['detected_separator'] = detected_separator
            
            # 获取字段列表
            fields = df.columns.tolist()
            
            # 生成字段详细信息
            field_details = {}
            for field in fields:
                try:
                    field_series = df[field]
                    if isinstance(field_series, pd.Series):
                        field_details[field] = {
                            'data_type': str(field_series.dtype),
                            'null_count': int(field_series.isnull().sum()),
                            'null_percentage': round(field_series.isnull().sum() / len(df) * 100, 2),
                            'unique_count': int(field_series.nunique()),
                            'sample_values': field_series.dropna().head(5).tolist(),
                            'description': self._generate_field_description(field_series)
                        }
                    else:
                        field_details[field] = {
                            'data_type': 'unknown',
                            'null_count': 0,
                            'null_percentage': 0.0,
                            'unique_count': 0,
                            'sample_values': [],
                            'description': 'Unknown field type'
                        }
                except Exception as e:
                    field_details[field] = {
                        'data_type': 'error',
                        'null_count': 0,
                        'null_percentage': 0.0,
                        'unique_count': 0,
                        'sample_values': [],
                        'description': f'Error processing field: {str(e)}'
                    }
            
            result['success'] = True
            result['message'] = f"找到 {len(fields)} 个字段"
            result['fields'] = fields
            result['field_details'] = field_details
            
        except Exception as e:
            result['message'] = f"获取字段失败: {str(e)}"
            self.logger.error(f"获取字段失败: {e}")
        
        return result
    
    def extract_by_pattern(self, source_file: Union[str, Path],
                          field_patterns: List[str],
                          output_file: Optional[Union[str, Path]] = None,
                          sheet_name: Optional[str] = None,
                          case_sensitive: bool = False,
                          custom_separator: Optional[str] = None) -> Dict[str, Any]:
        """
        根据字段名模式提取字段
        
        Args:
            source_file: 源Excel文件路径
            field_patterns: 字段名模式列表（支持通配符）
            output_file: 输出文件路径
            sheet_name: 工作表名称
            case_sensitive: 是否区分大小写
            
        Returns:
            提取结果字典
        """
        result = {
            'success': False,
            'message': '',
            'matched_fields': [],
            'extracted_data': None,
            'output_file': None
        }
        
        try:
            # 读取源文件
            df, detected_separator = self._read_file(source_file, sheet_name, custom_separator)
            result['detected_separator'] = detected_separator
            
            # 获取所有字段
            all_fields = df.columns.tolist()
            
            # 匹配字段模式
            matched_fields = []
            for pattern in field_patterns:
                matched = self._match_fields_by_pattern(all_fields, pattern, case_sensitive)
                matched_fields.extend(matched)
            
            # 去重
            matched_fields = list(set(matched_fields))
            
            if not matched_fields:
                result['message'] = "没有找到匹配的字段"
                return result
            
            # 提取匹配的字段
            extraction_result = self.extract_fields(source_file, matched_fields, output_file, sheet_name)
            
            result['success'] = extraction_result['success']
            result['message'] = extraction_result['message']
            result['matched_fields'] = matched_fields
            result['extracted_data'] = extraction_result['extracted_data']
            result['output_file'] = extraction_result['output_file']
            
        except Exception as e:
            result['message'] = f"模式匹配提取失败: {str(e)}"
            self.logger.error(f"模式匹配提取失败: {e}")
        
        return result
    
    def _generate_statistics(self, extracted_df: pd.DataFrame, original_df: pd.DataFrame) -> Dict[str, Any]:
        """
        生成提取统计信息
        
        Args:
            extracted_df: 提取后的数据
            original_df: 原始数据
            
        Returns:
            统计信息字典
        """
        try:
            statistics = {
                'original_rows': len(original_df),
                'original_columns': len(original_df.columns),
                'extracted_rows': len(extracted_df),
                'extracted_columns': len(extracted_df.columns),
                'extraction_ratio': round(len(extracted_df.columns) / len(original_df.columns) * 100, 2),
                'memory_usage': {
                    'original_mb': round(original_df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
                    'extracted_mb': round(extracted_df.memory_usage(deep=True).sum() / 1024 / 1024, 2)
                },
                'data_quality': {
                    'total_null_values': int(extracted_df.isnull().sum().sum()),
                    'null_percentage': round(extracted_df.isnull().sum().sum() / (len(extracted_df) * len(extracted_df.columns)) * 100, 2)
                }
            }
            
            return statistics
            
        except Exception as e:
            self.logger.error(f"生成统计信息失败: {e}")
            return {}
    
    def _generate_field_description(self, series: pd.Series) -> str:
        """
        生成字段描述
        
        Args:
            series: 字段数据
            
        Returns:
            字段描述
        """
        try:
            dtype = str(series.dtype)
            null_count = series.isnull().sum()
            unique_count = series.nunique()
            total_count = len(series)
            
            if dtype in ['int64', 'float64']:
                desc = f"数值型字段，范围: {series.min():.2f} - {series.max():.2f}"
            elif dtype == 'object':
                if unique_count < total_count * 0.1:
                    desc = f"分类型字段，{unique_count} 个不同值"
                else:
                    desc = f"文本型字段，{unique_count} 个不同值"
            elif 'datetime' in dtype:
                desc = f"日期型字段，范围: {series.min()} - {series.max()}"
            else:
                desc = f"{dtype} 类型字段"
            
            if null_count > 0:
                desc += f"，包含 {null_count} 个空值"
            
            return desc
            
        except Exception:
            return "未知类型字段"
    
    def _match_fields_by_pattern(self, fields: List[str], pattern: str, case_sensitive: bool = False) -> List[str]:
        """
        根据模式匹配字段
        
        Args:
            fields: 字段列表
            pattern: 匹配模式
            case_sensitive: 是否区分大小写
            
        Returns:
            匹配的字段列表
        """
        import fnmatch
        
        matched = []
        
        for field in fields:
            field_to_match = field if case_sensitive else field.lower()
            pattern_to_match = pattern if case_sensitive else pattern.lower()
            
            if fnmatch.fnmatch(field_to_match, pattern_to_match):
                matched.append(field)
        
        return matched
    
    def batch_extract(self, extraction_configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量提取字段
        
        Args:
            extraction_configs: 提取配置列表，每个配置包含:
                - source_file: 源文件路径
                - selected_fields: 选择的字段
                - output_file: 输出文件路径
                - sheet_name: 工作表名称（可选）
                
        Returns:
            批量提取结果列表
        """
        results = []
        
        for i, config in enumerate(extraction_configs):
            try:
                self.logger.info(f"开始处理第 {i+1}/{len(extraction_configs)} 个文件")
                
                result = self.extract_fields(
                    source_file=config['source_file'],
                    selected_fields=config['selected_fields'],
                    output_file=config.get('output_file'),
                    sheet_name=config.get('sheet_name')
                )
                
                result['config_index'] = i
                result['source_file'] = str(config['source_file'])
                results.append(result)
                
            except Exception as e:
                error_result = {
                    'success': False,
                    'message': f"处理失败: {str(e)}",
                    'config_index': i,
                    'source_file': str(config['source_file'])
                }
                results.append(error_result)
                self.logger.error(f"批量提取第 {i+1} 个文件失败: {e}")
        
        return results