#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理模块

提供Excel文件处理、字段提取、数据填充、模板管理等功能。

注意：不要在包初始化时导入 PySide6 UI 模块。Tauri 后端打包会导入
modules.data_processing.field_extractor；如果这里提前导入 data_processor_ui，
会把 PySide6 和大量旧 UI 依赖带进 koi-backend.exe，导致体积和启动耗时增加。
"""

__all__ = [
    'ExcelProcessor',
    'FieldExtractor',
    'DataFiller',
    'TemplateManager'
]

__version__ = '1.0.0'
__author__ = 'DataProcessor Team'
__description__ = '数据处理模块 - 提供Excel文件处理、字段提取、数据填充等功能'


def __getattr__(name):
    if name == 'ExcelProcessor':
        from .excel_processor import ExcelProcessor
        return ExcelProcessor
    if name == 'FieldExtractor':
        from .field_extractor import FieldExtractor
        return FieldExtractor
    if name == 'DataFiller':
        from .data_filler import DataFiller
        return DataFiller
    if name == 'TemplateManager':
        from .template_manager import TemplateManager
        return TemplateManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
