#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题变量模块

提供基于CSS变量的主题切换系统，分离颜色和布局样式
"""


def get_theme_variables(dark_mode=False):
    """
    获取主题CSS变量
    
    Args:
        dark_mode: 是否使用暗黑模式
        
    Returns:
        包含CSS变量定义的字符串
    """
    # 基础变量定义（不随主题变化）
    base_variables = """
        /* 基础布局变量 - 不随主题变化 */
        font-size-small: 12px;
        font-size-normal: 13px;
        font-size-medium: 14px;
        font-size-large: 16px;
        font-size-xlarge: 18px;
        
        padding-small: 5px;
        padding-normal: 8px;
        padding-medium: 10px;
        padding-large: 12px;
        padding-xlarge: 16px;
        
        margin-small: 5px;
        margin-normal: 8px;
        margin-medium: 10px;
        margin-large: 12px;
        margin-xlarge: 16px;
        
        border-radius-small: 4px;
        border-radius-normal: 6px;
        border-radius-medium: 8px;
        border-radius-large: 10px;
        border-radius-xlarge: 12px;
    """
    
    # 亮色主题变量
    light_variables = """
        /* 亮色主题颜色变量 */
        color-bg-primary: #ffffff;
        color-bg-secondary: #f5f5f5;
        color-bg-tertiary: #e0e0e0;
        color-bg-accent: #3498db;
        
        color-text-primary: #333333;
        color-text-secondary: #666666;
        color-text-tertiary: #999999;
        color-text-accent: #3498db;
        color-text-on-accent: #ffffff;
        
        color-border-primary: #e0e0e0;
        color-border-secondary: #cccccc;
        color-border-accent: #3498db;
        
        color-shadow: rgba(0, 0, 0, 0.1);
    """
    
    # 暗色主题变量
    dark_variables = """
        /* 暗色主题颜色变量 */
        color-bg-primary: #1e1e2e;
        color-bg-secondary: #313244;
        color-bg-tertiary: #45475a;
        color-bg-accent: #89b4fa;
        
        color-text-primary: #cdd6f4;
        color-text-secondary: #bac2de;
        color-text-tertiary: #a6adc8;
        color-text-accent: #89b4fa;
        color-text-on-accent: #1e1e2e;
        
        color-border-primary: #45475a;
        color-border-secondary: #585b70;
        color-border-accent: #89b4fa;
        
        color-shadow: rgba(0, 0, 0, 0.3);
    """
    
    # 根据模式返回相应的变量
    if dark_mode:
        return f":root {{\
{base_variables}\
{dark_variables}\
}}"
    else:
        return f":root {{\
{base_variables}\
{light_variables}\
}}"


def get_common_styles():
    """
    获取通用样式定义
    
    Returns:
        包含通用样式的字符串
    """
    return """
    /* 通用样式 */
    QWidget {
        font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
        font-size: 14px !important; /* 统一字体大小 */
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        background-color: #ffffff; /* color-bg-primary - 亮色模式默认值 */
    }
    
    QLabel {
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        background-color: transparent;
        font-size: 14px !important;
    }
    
    QPushButton {
        background-color: #f5f5f5; /* color-bg-secondary - 亮色模式默认值 */
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-radius: 6px; /* border-radius-normal */
        padding: 8px; /* padding-normal */
        font-size: 14px !important; /* 统一字体大小 */
    }
    
    QPushButton:hover {
        background-color: #e0e0e0; /* color-bg-tertiary - 亮色模式默认值 */
    }
    
    QPushButton:pressed {
        background-color: #3498db; /* color-bg-accent - 亮色模式默认值 */
        color: #ffffff; /* color-text-on-accent - 亮色模式默认值 */
    }
    
    QLineEdit, QTextEdit, QPlainTextEdit {
        background-color: #f5f5f5; /* color-bg-secondary - 亮色模式默认值 */
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-radius: 6px; /* border-radius-normal */
        padding: 8px; /* padding-normal */
        font-size: 14px !important; /* 统一字体大小 */
        selection-background-color: #3498db; /* color-bg-accent - 亮色模式默认值 */
        selection-color: #ffffff; /* color-text-on-accent - 亮色模式默认值 */
    }
    
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
        border: 2px solid #3498db; /* color-border-accent - 亮色模式默认值 */
    }
    
    QTabWidget::pane {
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        background-color: #ffffff; /* color-bg-primary - 亮色模式默认值 */
        border-radius: 8px; /* border-radius-medium */
    }
    
    QTabBar::tab {
        background-color: #f5f5f5; /* color-bg-secondary - 亮色模式默认值 */
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        padding: 10px 12px; /* padding-medium padding-large */
        margin-right: 2px;
        border-top-left-radius: 6px; /* border-radius-normal */
        border-top-right-radius: 6px; /* border-radius-normal */
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-bottom: none;
        font-size: 14px !important; /* 统一字体大小 */
    }
    
    QTabBar::tab:selected {
        background-color: #ffffff; /* color-bg-primary - 亮色模式默认值 */
        color: #3498db; /* color-text-accent - 亮色模式默认值 */
        font-weight: bold;
    }
    
    QTabBar::tab:hover {
        background-color: #e0e0e0; /* color-bg-tertiary - 亮色模式默认值 */
    }
    
    QComboBox {
        background-color: #f5f5f5; /* color-bg-secondary - 亮色模式默认值 */
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-radius: 6px; /* border-radius-normal */
        padding: 8px; /* padding-normal */
        font-size: 14px !important; /* 统一字体大小 */
    }
    
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-top-right-radius: 6px; /* border-radius-normal */
        border-bottom-right-radius: 6px; /* border-radius-normal */
    }
    
    QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            selection-background-color: #007bff;
            selection-color: #ffffff;
        }
        
        QComboBox:hover {
            background-color: #e9ecef;
            border: 1px solid #ced4da;
        }
        
        QComboBox:focus {
            border: 2px solid #007bff;
        }
    
    QGroupBox {
        font-weight: bold;
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        border-radius: 8px; /* border-radius-medium */
        margin-top: 10px;
        padding-top: 10px;
    }
    
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px 0 5px;
    }
    
    QCheckBox, QRadioButton {
        color: #333333; /* color-text-primary - 亮色模式默认值 */
        background-color: transparent;
    }
    
    QCheckBox::indicator, QRadioButton::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #e0e0e0; /* color-border-primary - 亮色模式默认值 */
        background-color: #f5f5f5; /* color-bg-secondary - 亮色模式默认值 */
    }
    
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {
        background-color: #3498db; /* color-bg-accent - 亮色模式默认值 */
        border: 1px solid #3498db; /* color-border-accent - 亮色模式默认值 */
    }
    """


def get_theme_style(dark_mode=False):
    """
    获取完整的主题样式
    
    Args:
        dark_mode: 是否使用暗黑模式
        
    Returns:
        完整的CSS样式表字符串
    """
    common_styles = get_common_styles()
    
    # 通用样式定义（不随主题变化）
    base_styles = """
        /* 通用样式定义 - 不随主题变化 */
        QWidget {
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
        }
        
        QLabel[class="title"] {
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        QLabel[class="subtitle"] {
            margin-bottom: 10px;
        }
    """
    
    # 根据模式返回不同的样式表
    if dark_mode:
        # 暗色模式样式
        return base_styles + """
        /* 暗色主题样式 */
        QWidget {
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            font-size: 14px !important;
            color: #cdd6f4;
            background-color: #1e1e2e;
        }
        
        QLabel {
            color: #cdd6f4;
            background-color: transparent;
            font-size: 14px !important;
        }
        
        QLabel[class="title"] {
            font-size: 24px !important;
            font-weight: bold;
            color: #89b4fa;
            margin-bottom: 5px;
        }
        
        QLabel[class="subtitle"] {
            font-size: 16px !important;
            color: #a6adc8;
            margin-bottom: 10px;
        }
        
        QPushButton {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            padding: 10px 15px;
            font-size: 14px !important;
            font-weight: 500;
            /* PySide6不支持box-shadow属性 */
        }
        
        QPushButton:hover {
            background-color: #45475a;
            /* PySide6不支持box-shadow属性 */
            margin-top: -1px;
        }
        
        QPushButton:pressed {
            background-color: #89b4fa;
            color: #1e1e2e;
            /* PySide6不支持box-shadow属性 */
            margin-top: 0px;
        }
        
        QLineEdit, QTextEdit, QPlainTextEdit {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 8px;
            padding: 10px;
            font-size: 14px !important;
            selection-background-color: #89b4fa;
            selection-color: #1e1e2e;
        }
        
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 2px solid #89b4fa;
            /* PySide6不支持box-shadow属性 */
        }
        
        QTabWidget::pane {
            border: 1px solid #45475a;
            background-color: #1e1e2e;
            border-radius: 8px;
            padding: 5px;
        }
        
        QTabBar::tab {
            background-color: #313244;
            color: #cdd6f4;
            padding: 12px 18px;
            margin-right: 3px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #45475a;
            border-bottom: none;
            font-size: 14px !important;
        }
        
        QTabBar::tab:selected {
            background-color: #1e1e2e;
            color: #89b4fa;
            font-weight: bold;
            border-top: 2px solid #89b4fa;
        }
        
        QTabBar::tab:hover {
            background-color: #45475a;
        }
        
        QComboBox {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 8px;
            padding: 10px;
            font-size: 14px !important;
            min-height: 25px;
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 25px;
            border-left: 1px solid #45475a;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            background-color: #45475a;
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%23cdd6f4'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        QComboBox QAbstractItemView {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 8px;
            padding: 5px;
            selection-background-color: #89b4fa;
            selection-color: #1e1e2e;
        }
        
        QGroupBox {
            font-weight: bold;
            border: 1px solid #45475a;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        
        QCheckBox, QRadioButton {
            color: #cdd6f4;
            background-color: transparent;
        }
        
        QCheckBox::indicator, QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #45475a;
            background-color: #313244;
        }
        
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {
            background-color: #89b4fa;
            border: 1px solid #89b4fa;
        }
        """
    else:
        # 亮色模式样式 - 确保包含所有必要的样式
        return base_styles + """
        /* 亮色主题样式 */
        QWidget {
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            font-size: 14px !important;
            color: #333333;
            background-color: #ffffff;
        }
        
        QLabel {
            color: #333333;
            background-color: transparent;
            font-size: 14px !important;
        }
        
        QLabel[class="title"] {
            font-size: 24px !important;
            font-weight: bold;
            color: #007bff;
            margin: 20px 0;
        }
        
        QLabel[class="subtitle"] {
            font-size: 16px !important;
            color: #6c757d;
            margin-bottom: 20px;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #007bff, stop:1 #0056b3);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 15px;
            font-size: 14px !important;
            font-weight: bold;
            margin: 1px;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #66b3ff, stop:1 #007bff);
            margin-top: 0px;
            margin-bottom: 2px;
        }
        
        QPushButton:pressed {
            background-color: #3498db;
            color: #ffffff;
            margin-top: 2px;
            margin-bottom: 0px;
        }
        
        QLineEdit, QTextEdit, QPlainTextEdit {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px !important;
            selection-background-color: #007bff;
            selection-color: #ffffff;
        }
        
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 2px solid #007bff;
            /* PySide6不支持box-shadow属性 */
        }
        
        QTabWidget::pane {
            border: 1px solid #dee2e6;
            background-color: #ffffff;
            border-radius: 8px;
        }
        
        QTabBar::tab {
            background-color: #f5f5f5;
            color: #333333;
            padding: 12px 24px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #dee2e6;
            border-bottom: none;
            font-size: 14px !important;
        }
        
        QTabBar::tab:selected {
            background-color: #ffffff;
            color: #007bff;
            font-weight: bold;
            border-top: 2px solid #007bff;
            border-bottom: 1px solid #ffffff;
        }
        
        QTabBar::tab:hover {
            background-color: #e9ecef;
            color: #007bff;
        }
        
        QComboBox {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            min-width: 6em;
            font-size: 14px !important;
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 25px;
            border-left: 1px solid #dee2e6;
            border-top-right-radius: 4px;
            border-bottom-right-radius: 4px;
            background-color: #f8f9fa;
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%236c757d'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        QComboBox QAbstractItemView {
            background-color: #f5f5f5;
            color: #333333;
            border: 1px solid #d0d0d0;
            border-radius: 8px;
            padding: 5px;
            selection-background-color: #3498db;
            selection-color: #ffffff;
        }
        
        QGroupBox {
            background-color: #ffffff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            margin-top: 20px;
            padding: 15px;
            font-size: 14px !important;
            font-weight: 500;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        
        QCheckBox, QRadioButton {
            color: #333333;
            background-color: transparent;
        }
        
        QCheckBox::indicator, QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #d0d0d0;
            background-color: #f5f5f5;
        }
        
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {
            background-color: #3498db;
            border: 1px solid #3498db;
        }
        """


# 测试函数
def test_theme_style():
    """测试主题样式"""
    print("=== 亮色主题样式 ===")
    print(get_theme_style(False))
    print("\n=== 暗色主题样式 ===")
    print(get_theme_style(True))


if __name__ == "__main__":
    test_theme_style()