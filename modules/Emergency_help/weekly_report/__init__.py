#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报生成模块

提供工作周报自动生成功能。

注意：Tauri 后端只需要 WeeklyReportGenerator。不要在包初始化时导入
weekly_report_ui，否则 PyInstaller 会把 PySide6 UI 链路打进 koi-backend.exe。
"""

__all__ = [
    'WeeklyReportGenerator'
]

__version__ = '1.0.0'
__author__ = 'WeeklyReport Team'
__description__ = '周报生成模块 - 提供工作周报自动生成功能'


def __getattr__(name):
    if name == 'WeeklyReportGenerator':
        from .weekly_report_generator import WeeklyReportGenerator
        return WeeklyReportGenerator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
