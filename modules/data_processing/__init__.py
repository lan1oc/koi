#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理模块

提供Excel文件处理、字段提取、数据填充、模板管理等功能
"""

from .excel_processor import ExcelProcessor
from .field_extractor import FieldExtractor
from .data_filler import DataFiller
from .template_manager import TemplateManager
from .data_processor_ui import DataProcessorUI

__all__ = [
    'ExcelProcessor',
    'FieldExtractor', 
    'DataFiller',
    'TemplateManager',
    'DataProcessorUI'
]

__version__ = '1.0.0'
__author__ = 'DataProcessor Team'
__description__ = '数据处理模块 - 提供Excel文件处理、字段提取、数据填充等功能'