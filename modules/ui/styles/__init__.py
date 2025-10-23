#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI样式模块

提供样式设置和主题管理功能
"""

from .main_styles import setup_main_style, add_shadow_effect
from .theme_manager import ThemeManager

__all__ = [
    'setup_main_style',
    'add_shadow_effect', 
    'ThemeManager'
]