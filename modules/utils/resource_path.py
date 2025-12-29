#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源路径工具模块

提供统一的资源路径解析，支持开发环境和 PyInstaller 打包环境
"""

import sys
import shutil
import os
from pathlib import Path

def get_base_path() -> Path:
    """
    获取应用程序的基础路径
    
    - 在开发环境中：返回项目根目录（koi.py 所在目录）
    - 在打包环境中：返回 PyInstaller 解压的临时目录 (sys._MEIPASS)
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).parent.parent.parent


def get_app_dir() -> Path:
    """
    获取程序运行目录
    
    - 在开发环境中：返回项目根目录
    - 在打包环境中：返回可执行文件所在目录
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件的绝对路径
    
    优先级：
    1. 程序运行目录下的文件（用户可修改）
    2. 打包环境临时目录下的文件（默认资源）
    """
    # 优先检查程序运行目录（可执行文件同级）
    app_dir_path = get_app_dir() / relative_path
    if app_dir_path.exists():
        return app_dir_path
        
    # 如果本地不存在，则使用基础路径（开发环境根目录 或 打包环境_MEIPASS）
    base_path = get_base_path()
    return base_path / relative_path


def ensure_resources_extracted():
    """
    确保必要的资源文件已释放到程序运行目录
    
    仅在打包环境下执行。如果程序运行目录下没有相关文件，
    则从打包的临时目录(_MEIPASS)中复制出来。
    """
    if not is_frozen():
        return

    app_dir = get_app_dir()
    base_path = get_base_path()  # _MEIPASS

    # 需要释放的资源列表 (相对路径: 是否为目录)
    resources = {
        '1.txt': False,
        'Report_Template': True,
        'modules/data_processing/templates': True
    }

    try:
        for rel_path, is_dir in resources.items():
            src = base_path / rel_path
            dst = app_dir / rel_path

            # 如果源文件在包内不存在，跳过（可能打包时就没打进去）
            if not src.exists():
                continue

            # 如果目标已存在，跳过（保留用户修改）
            if dst.exists():
                continue

            # 执行复制
            if is_dir:
                # 递归复制目录
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                # 复制文件
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                
    except Exception as e:
        # 记录错误但不阻断启动，可能因为权限问题失败
        # 在这里由于没有logger，直接打印到控制台（如果有的话）
        print(f"资源释放失败: {e}")


def get_report_template_dir() -> Path:
    """获取 Report_Template 目录的绝对路径"""
    return get_resource_path('Report_Template')


def get_data_processing_templates_dir() -> Path:
    """获取数据处理模板目录的绝对路径"""
    return get_resource_path('modules/data_processing/templates')


def is_frozen() -> bool:
    """检测是否在打包环境中运行"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


__all__ = [
    'get_base_path',
    'get_app_dir',
    'get_resource_path', 
    'get_report_template_dir',
    'get_data_processing_templates_dir',
    'ensure_resources_extracted',
    'is_frozen'
]
