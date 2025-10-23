#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报生成模块

提供工作周报自动生成功能
"""

from .weekly_report_generator import WeeklyReportGenerator
from .weekly_report_ui import WeeklyReportUI

__all__ = [
    'WeeklyReportGenerator',
    'WeeklyReportUI'
]

__version__ = '1.0.0'
__author__ = 'WeeklyReport Team'
__description__ = '周报生成模块 - 提供工作周报自动生成功能'