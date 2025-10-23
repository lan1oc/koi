#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成助手

帮助将周报生成功能集成到主程序中
"""

from PySide6.QtWidgets import QWidget, QTabWidget
from .weekly_report_ui import WeeklyReportUI


def create_weekly_report_tab(parent_tab_widget: QTabWidget) -> QWidget:
    """
    创建周报生成选项卡并添加到父选项卡控件中
    
    Args:
        parent_tab_widget: 父选项卡控件
        
    Returns:
        创建的周报生成控件
    """
    # 创建周报生成UI
    weekly_report_ui = WeeklyReportUI()
    
    # 添加到父选项卡
    parent_tab_widget.addTab(weekly_report_ui, "📝 周报生成")
    
    return weekly_report_ui


def integrate_weekly_report_to_emergency_help(emergency_help_tabs: QTabWidget):
    """
    将周报生成功能集成到江湖救急标签页中
    
    Args:
        emergency_help_tabs: 江湖救急的子标签页控件
    """
    try:
        # 创建周报生成UI实例
        weekly_report_ui = WeeklyReportUI()
        
        # 添加到江湖救急标签页
        emergency_help_tabs.addTab(weekly_report_ui, "📝 周报生成")
        
        return weekly_report_ui
        
    except Exception as e:
        print(f"集成周报生成功能失败: {e}")
        return None


def add_weekly_report_methods_to_main_window(main_window):
    """
    为主窗口添加周报生成相关的方法
    
    Args:
        main_window: 主窗口对象
    """
    def create_weekly_report_tab_method():
        """创建周报生成选项卡的方法"""
        return create_weekly_report_tab(main_window.tab_widget)
    
    def get_weekly_report_ui():
        """获取周报生成UI的方法"""
        return getattr(main_window, 'weekly_report_ui', None)
    
    # 将方法添加到主窗口
    main_window.create_weekly_report_tab = create_weekly_report_tab_method
    main_window.get_weekly_report_ui = get_weekly_report_ui


# 使用示例代码（注释掉，仅供参考）
"""
# 在主程序的fool_tools.py中使用：

# 1. 导入集成助手
from modules.Emergency_help.weekly_report.integration_helper import integrate_weekly_report_to_emergency_help

# 2. 在创建江湖救急标签页时调用集成函数
class MainWindow(QMainWindow):
    def create_emergency_tools_tab(self):
        # ... 创建江湖救急主标签页 ...
        
        # 创建子标签页
        emergency_tabs = QTabWidget()
        
        # 集成周报生成功能
        self.weekly_report_ui = integrate_weekly_report_to_emergency_help(emergency_tabs)
        
        # ... 其他子标签页 ...
        
        # 将子标签页添加到主标签页
        emergency_layout.addWidget(emergency_tabs)
        self.tab_widget.addTab(emergency_widget, "🆘 江湖救急")

# 3. 或者手动创建周报生成选项卡
class MainWindow(QMainWindow):
    def setup_ui(self):
        # ... 其他UI设置代码 ...
        
        # 创建周报生成选项卡
        from modules.Emergency_help.weekly_report.integration_helper import create_weekly_report_tab
        self.weekly_report_ui = create_weekly_report_tab(self.emergency_tabs)
        
        # ... 其他UI设置代码 ...
"""