#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成助手

帮助将数据处理功能集成到主程序中
"""

from PySide6.QtWidgets import QWidget, QTabWidget
from .data_processor_ui import DataProcessorUI

def create_data_processing_tab(parent_tab_widget: QTabWidget) -> QWidget:
    """
    创建数据处理选项卡并添加到父选项卡控件中
    
    Args:
        parent_tab_widget: 父选项卡控件
        
    Returns:
        创建的数据处理控件
    """
    # 创建数据处理UI
    data_processor_ui = DataProcessorUI()
    
    # 添加到父选项卡
    parent_tab_widget.addTab(data_processor_ui, "📊 数据处理")
    
    return data_processor_ui

def integrate_data_processing_to_main_window(main_window):
    """
    将数据处理功能集成到主窗口中，完全匹配原始布局
    
    Args:
        main_window: 主窗口对象，需要有tab_widget属性
    """
    try:
        # 检查主窗口是否有tab_widget属性
        if not hasattr(main_window, 'tab_widget'):
            raise AttributeError("主窗口缺少tab_widget属性")
        
        # 完全按照原始fool_tools1.py的布局创建
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget
        
        # 创建数据处理主标签页
        data_processing_widget = QWidget()
        data_processing_layout = QVBoxLayout(data_processing_widget)
        data_processing_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建数据处理子标签页
        data_processing_tabs = QTabWidget()
        data_processing_layout.addWidget(data_processing_tabs)
        
        # 创建数据处理UI实例
        data_processor_ui = DataProcessorUI()
        
        # 添加数据处理相关的子标签页（完全匹配原始标签名称和顺序）
        # 字段提取标签页
        field_extraction_tab = data_processor_ui.create_field_extraction_tab()
        data_processing_tabs.addTab(field_extraction_tab, "📄 字段提取")
        
        # 数据填充标签页  
        data_filling_tab = data_processor_ui.create_data_filling_tab()
        data_processing_tabs.addTab(data_filling_tab, "📝 数据填充")
        
        # 模板管理标签页
        template_management_tab = data_processor_ui.create_template_management_tab()
        data_processing_tabs.addTab(template_management_tab, "📋 模板管理")
        
        # 确保模板列表已加载
        if hasattr(data_processor_ui, 'templates') and data_processor_ui.templates:
            data_processor_ui.update_template_list()
        
        # 将数据处理主标签页添加到主标签页控件
        main_window.tab_widget.addTab(data_processing_widget, "📊 数据处理")
        
        # 将数据处理UI保存到主窗口，以便后续访问
        main_window.data_processor_ui = data_processor_ui
        
        return True
        
    except Exception as e:
        print(f"集成数据处理功能失败: {e}")
        return False

def add_data_processing_methods_to_main_window(main_window):
    """
    为主窗口添加数据处理相关的方法
    
    Args:
        main_window: 主窗口对象
    """
    def create_data_processing_tab_method():
        """创建数据处理选项卡的方法"""
        return create_data_processing_tab(main_window.tab_widget)
    
    def get_data_processor_ui():
        """获取数据处理UI的方法"""
        return getattr(main_window, 'data_processor_ui', None)
    
    # 将方法添加到主窗口
    main_window.create_data_processing_tab = create_data_processing_tab_method
    main_window.get_data_processor_ui = get_data_processor_ui

# 使用示例代码（注释掉，仅供参考）
"""
# 在主程序的fool_tools.py中使用：

# 1. 导入集成助手
from modules.data_processing.integration_helper import integrate_data_processing_to_main_window

# 2. 在主窗口的__init__方法中调用集成函数
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... 其他初始化代码 ...
        
        # 集成数据处理功能
        integrate_data_processing_to_main_window(self)
        
        # ... 其他初始化代码 ...

# 3. 或者手动创建数据处理选项卡
class MainWindow(QMainWindow):
    def setup_ui(self):
        # ... 其他UI设置代码 ...
        
        # 创建数据处理选项卡
        from modules.data_processing.integration_helper import create_data_processing_tab
        self.data_processor_ui = create_data_processing_tab(self.tab_widget)
        
        # ... 其他UI设置代码 ...
"""