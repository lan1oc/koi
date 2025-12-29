#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源路径工具模块

提供统一的资源路径解析，支持开发环境和 PyInstaller 打包环境
"""

import sys
import os
from pathlib import Path


def get_base_path() -> Path:
    """
    获取应用程序的基础路径
    
    - 在开发环境中：返回项目根目录（koi.py 所在目录）
    - 在打包环境中：返回 PyInstaller 解压的临时目录 (sys._MEIPASS)
    
    Returns:
        Path: 基础路径
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的环境
        return Path(sys._MEIPASS)
    else:
        # 开发环境 - 返回项目根目录
        # 从当前文件向上找到项目根目录 (modules/utils/resource_path.py -> 项目根目录)
        return Path(__file__).parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件的绝对路径（支持开发和打包环境）
    
    Args:
        relative_path: 相对于项目根目录的路径，如 'Report_Template/复测模板.docx'
    
    Returns:
        Path: 资源文件的绝对路径
    """
    base_path = get_base_path()
    return base_path / relative_path


def get_report_template_dir() -> Path:
    """
    获取 Report_Template 目录的绝对路径
    
    Returns:
        Path: Report_Template 目录的绝对路径
    """
    return get_resource_path('Report_Template')


def get_data_processing_templates_dir() -> Path:
    """
    获取数据处理模板目录的绝对路径
    
    Returns:
        Path: modules/data_processing/templates 目录的绝对路径
    """
    return get_resource_path('modules/data_processing/templates')


def is_frozen() -> bool:
    """
    检测是否在打包环境中运行
    
    Returns:
        bool: True 表示在打包环境中运行
    """
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


# 便捷导出
__all__ = [
    'get_base_path',
    'get_resource_path', 
    'get_report_template_dir',
    'get_data_processing_templates_dir',
    'is_frozen'
]
