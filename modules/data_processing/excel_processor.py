#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel文件处理器

提供Excel文件的读取、解析、写入等基础功能
"""

import pandas as pd
import openpyxl
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import logging

class ExcelProcessor:
    """Excel文件处理器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.supported_formats = ['.xlsx', '.xls']
    
    def read_excel(self, file_path: Union[str, Path], sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        读取Excel文件
        
        Args:
            file_path: Excel文件路径
            sheet_name: 工作表名称，None表示读取第一个工作表
            
        Returns:
            pandas DataFrame对象
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
            Exception: 读取失败
        """
        try:
            file_path = Path(file_path)
            
            # 检查文件是否存在
            if not file_path.exists():
                raise FileNotFoundError(f"文件不存在: {file_path}")
            
            # 检查文件格式
            if file_path.suffix.lower() not in self.supported_formats:
                raise ValueError(f"不支持的文件格式: {file_path.suffix}")
            
            # 读取Excel文件
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
            
            self.logger.info(f"成功读取Excel文件: {file_path}, 数据形状: {df.shape}")
            return df
            
        except Exception as e:
            self.logger.error(f"读取Excel文件失败: {e}")
            raise
    
    def get_sheet_names(self, file_path: Union[str, Path]) -> List[str]:
        """
        获取Excel文件中所有工作表名称
        
        Args:
            file_path: Excel文件路径
            
        Returns:
            工作表名称列表
        """
        try:
            file_path = Path(file_path)
            
            if not file_path.exists():
                raise FileNotFoundError(f"文件不存在: {file_path}")
            
            # 使用openpyxl获取工作表名称
            workbook = openpyxl.load_workbook(file_path, read_only=True)
            sheet_names = workbook.sheetnames
            workbook.close()
            
            return sheet_names
            
        except Exception as e:
            self.logger.error(f"获取工作表名称失败: {e}")
            return []
    
    def get_headers(self, file_path: Union[str, Path], sheet_name: Optional[str] = None) -> List[str]:
        """
        获取Excel文件的表头信息
        
        Args:
            file_path: Excel文件路径
            sheet_name: 工作表名称
            
        Returns:
            表头列表
        """
        try:
            df = self.read_excel(file_path, sheet_name)
            headers = df.columns.tolist()
            
            # 处理空列名
            processed_headers = []
            for i, header in enumerate(headers):
                if pd.isna(header) or str(header).strip() == '':
                    processed_headers.append(f"列{i+1}")
                else:
                    processed_headers.append(str(header).strip())
            
            return processed_headers
            
        except Exception as e:
            self.logger.error(f"获取表头失败: {e}")
            return []
    
    def get_data_preview(self, file_path: Union[str, Path], sheet_name: Optional[str] = None, 
                        rows: int = 5) -> Dict[str, Any]:
        """
        获取Excel文件数据预览
        
        Args:
            file_path: Excel文件路径
            sheet_name: 工作表名称
            rows: 预览行数
            
        Returns:
            包含预览信息的字典
        """
        try:
            df = self.read_excel(file_path, sheet_name)
            
            preview_data = {
                'total_rows': len(df),
                'total_columns': len(df.columns),
                'headers': self.get_headers(file_path, sheet_name),
                'preview_rows': df.head(rows).to_dict('records'),
                'data_types': df.dtypes.to_dict(),
                'null_counts': df.isnull().sum().to_dict()
            }
            
            return preview_data
            
        except Exception as e:
            self.logger.error(f"获取数据预览失败: {e}")
            return {}
    
    def write_excel(self, data: pd.DataFrame, file_path: Union[str, Path], 
                   sheet_name: str = 'Sheet1', index: bool = False) -> bool:
        """
        写入Excel文件
        
        Args:
            data: 要写入的数据
            file_path: 输出文件路径
            sheet_name: 工作表名称
            index: 是否写入索引
            
        Returns:
            是否写入成功
        """
        try:
            file_path = Path(file_path)
            
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入Excel文件
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                data.to_excel(writer, sheet_name=sheet_name, index=index)
            
            self.logger.info(f"成功写入Excel文件: {file_path}, 数据形状: {data.shape}")
            return True
            
        except Exception as e:
            self.logger.error(f"写入Excel文件失败: {e}")
            return False
    
    def validate_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        验证Excel文件
        
        Args:
            file_path: Excel文件路径
            
        Returns:
            验证结果字典
        """
        result = {
            'is_valid': False,
            'file_exists': False,
            'format_supported': False,
            'readable': False,
            'error_message': None,
            'file_info': {}
        }
        
        try:
            file_path = Path(file_path)
            
            # 检查文件是否存在
            if not file_path.exists():
                result['error_message'] = f"文件不存在: {file_path}"
                return result
            
            result['file_exists'] = True
            
            # 检查文件格式
            if file_path.suffix.lower() not in self.supported_formats:
                result['error_message'] = f"不支持的文件格式: {file_path.suffix}"
                return result
            
            result['format_supported'] = True
            
            # 尝试读取文件
            df = self.read_excel(file_path)
            result['readable'] = True
            
            # 获取文件信息
            result['file_info'] = {
                'file_size': file_path.stat().st_size,
                'sheet_names': self.get_sheet_names(file_path),
                'total_rows': len(df),
                'total_columns': len(df.columns),
                'headers': self.get_headers(file_path)
            }
            
            result['is_valid'] = True
            
        except Exception as e:
            result['error_message'] = str(e)
            
        return result
    
    def convert_data_types(self, df: pd.DataFrame, type_mapping: Dict[str, str]) -> pd.DataFrame:
        """
        转换数据类型
        
        Args:
            df: 原始数据
            type_mapping: 类型映射字典 {列名: 目标类型}
            
        Returns:
            转换后的数据
        """
        try:
            df_copy = df.copy()
            
            for column, target_type in type_mapping.items():
                if column in df_copy.columns:
                    try:
                        if target_type == 'string':
                            df_copy[column] = df_copy[column].astype(str)
                        elif target_type == 'int':
                            try:
                                numeric_series = pd.to_numeric(df_copy[column], errors='coerce')
                                if isinstance(numeric_series, pd.Series):
                                    df_copy[column] = numeric_series.astype('Int64')
                                else:
                                    df_copy[column] = pd.Series(numeric_series).astype('Int64')
                            except (AttributeError, TypeError):
                                numeric_data = pd.to_numeric(df_copy[column], errors='coerce')
                                df_copy[column] = pd.Series(numeric_data).fillna(0).astype(int)
                        elif target_type == 'float':
                            df_copy[column] = pd.to_numeric(df_copy[column], errors='coerce')
                        elif target_type == 'datetime':
                            df_copy[column] = pd.to_datetime(df_copy[column], errors='coerce')
                        elif target_type == 'bool':
                            df_copy[column] = df_copy[column].astype(bool)
                    except Exception as e:
                        self.logger.warning(f"转换列 {column} 到 {target_type} 失败: {e}")
            
            return df_copy
            
        except Exception as e:
            self.logger.error(f"数据类型转换失败: {e}")
            return df
    
    def clean_data(self, df: pd.DataFrame, 
                  remove_duplicates: bool = False,
                  fill_na_value: Any = None,
                  drop_na_columns: Optional[List[str]] = None) -> pd.DataFrame:
        """
        清洗数据
        
        Args:
            df: 原始数据
            remove_duplicates: 是否移除重复行
            fill_na_value: 填充空值的值
            drop_na_columns: 删除包含空值的列
            
        Returns:
            清洗后的数据
        """
        try:
            df_copy = df.copy()
            
            # 移除重复行
            if remove_duplicates:
                df_copy = df_copy.drop_duplicates()
                self.logger.info(f"移除重复行后，数据形状: {df_copy.shape}")
            
            # 填充空值
            if fill_na_value is not None:
                df_copy = df_copy.fillna(fill_na_value)
                self.logger.info(f"填充空值: {fill_na_value}")
            
            # 删除包含空值的列
            if drop_na_columns:
                for column in drop_na_columns:
                    if column in df_copy.columns:
                        df_copy = df_copy.dropna(subset=[column])
                self.logger.info(f"删除包含空值的列: {drop_na_columns}")
            
            return df_copy
            
        except Exception as e:
            self.logger.error(f"数据清洗失败: {e}")
            return df