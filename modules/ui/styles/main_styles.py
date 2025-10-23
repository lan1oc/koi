#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主样式模块

从fool_tools.py提取的样式设置功能
"""

from PySide6.QtWidgets import QGraphicsDropShadowEffect, QPushButton, QApplication
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from typing import cast

# 导入主题变量模块
from .theme_variables import get_theme_style


def setup_main_style(main_window, dark_mode=False):
    """设置主窗口样式
    
    Args:
        main_window: 主窗口实例
        dark_mode: 是否启用暗黑模式
    """
    # 使用ThemeManager来应用样式，确保样式一致性
    from .theme_manager import ThemeManager
    theme_manager = ThemeManager()
    
    # 设置暗黑模式状态
    theme_manager.set_dark_mode(dark_mode)
    
    # 强制刷新主窗口，确保样式正确应用
    if main_window:
        main_window.repaint()
    
    # ThemeManager会自动应用样式到整个应用程序
    # 不再需要手动设置样式表

def setup_light_style():
    """设置亮色模式样式"""
    return """
        /* 状态标签样式 */
        QLabel[class="status-label-info"] {
            color: #3498db;
            font-weight: bold;
            padding: 10px;
            background-color: #ebf3fd;
            border-radius: 8px;
            border-left: 3px solid #3498db;
        }
        
        QLabel[class="status-label-success"] {
            color: #27ae60;
            font-weight: bold;
            padding: 10px;
            background-color: #eafaf1;
            border-radius: 8px;
            border-left: 3px solid #27ae60;
        }
        
        QLabel[class="status-label-error"] {
            color: #e74c3c;
            font-weight: bold;
            padding: 10px;
            background-color: #fdedec;
            border-radius: 8px;
            border-left: 3px solid #e74c3c;
        }
        
        QLabel[class="status-label-waiting"] {
            color: #7f8c8d;
            font-style: italic;
            padding: 10px;
            background-color: #ecf0f1;
            border-radius: 8px;
            border-left: 3px solid #95a5a6;
        }
        
        QLabel[class="status-label-processing"] {
            color: #f39c12;
            font-weight: bold;
            padding: 10px;
            background-color: #fef9e7;
            border-radius: 8px;
            border-left: 3px solid #f39c12;
        }
        
        QMainWindow {
            background-color: #f5f5f5;
        }
        
        QTabWidget::pane {
            border: none;
            background-color: white;
            border-radius: 8px;
        }
        
        QTabBar::tab {
            background-color: #e8e8e8;
            color: #333;
            padding: 12px 24px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #d0d0d0;
            border-bottom: none;
            font-size: 14px;
        }
        
        QTabBar::tab:selected {
            background-color: white;
            color: #2c3e50;
            font-weight: bold;
            border-top: 2px solid #4a90e2;
        }
        
        QTabBar::tab:hover {
            background-color: #f0f0f0;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a90e2, stop:1 #357abd);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: bold;
            font-size: 14px;
            outline: none;
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5ba0f2, stop:1 #4a90e2);
            margin-top: -1px;
            margin-bottom: 1px;
        }
        
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #357abd, stop:1 #2968a3);
            margin-top: 1px;
            margin-bottom: -1px;
        }
        
        QPushButton:focus {
            outline: none;
            border: 2px solid #74b9ff;
        }
        
        QPushButton.success {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #27ae60, stop:1 #229954);
        }
        
        QPushButton.success:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2ecc71, stop:1 #27ae60);
        }
        
        QGroupBox {
            font-weight: bold;
            border: 2px solid #d0d0d0;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: white;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        
        QListWidget {
            border: 1px solid #d0d0d0;
            border-radius: 8px;
            background-color: white;
            selection-background-color: #4a90e2;
            font-size: 18px;
            font-weight: 600;
            padding: 12px;
        }
        
        QListWidget::item {
            padding: 20px 24px;
            border-bottom: 1px solid #f8f9fa;
            border-radius: 8px;
            margin: 4px 0;
            min-height: 35px;
            font-size: 18px;
            font-weight: 600;
        }
        
        QListWidget::item:selected {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a90e2, stop:1 #357abd);
            color: white;
            font-weight: bold;
            font-size: 19px;
        }
        
        QListWidget::item:hover {
            background-color: #e3f2fd;
            color: #1976d2;
            font-weight: bold;
            font-size: 18px;
        }
        
        QTreeWidget {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            background-color: white;
            selection-background-color: #4a90e2;
            font-size: 11px;
        }
        
        QLineEdit {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            padding: 8px;
            font-size: 11px;
            background-color: white;
        }
        
        QLineEdit:focus {
            border: 2px solid #4a90e2;
        }
        
        QComboBox {
            border: 2px solid #e0e6ed;
            border-radius: 8px;
            padding: 10px 15px;
            font-size: 13px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #ffffff, stop:1 #f8f9fa);
            min-width: 200px;
            min-height: 20px;
            outline: none;
        }
        
        QComboBox:hover {
            border: 2px solid #74b9ff;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #ffffff, stop:1 #f1f3f4);
        }
        
        QComboBox:focus {
            border: 2px solid #4a90e2;
            outline: none;
            background: white;
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 35px;
            border-left: 1px solid #e0e6ed;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f8f9fa, stop:1 #e9ecef);
        }
        
        QComboBox::drop-down:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #e3f2fd, stop:1 #bbdefb);
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%236c757d'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        QComboBox::down-arrow:hover {
            border-top: 8px solid #4a90e2;
            border-left: 7px solid transparent;
            border-right: 7px solid transparent;
        }
        
        QComboBox QAbstractItemView {
            border: 2px solid #e0e6ed;
            border-radius: 8px;
            background-color: white;
            selection-background-color: #4a90e2;
            selection-color: white;
            outline: none;
            padding: 5px;
        }
        
        QComboBox QAbstractItemView::item {
            height: 35px;
            padding: 8px 15px;
            border-radius: 4px;
            margin: 2px;
        }
        
        QComboBox QAbstractItemView::item:hover {
            background-color: #e3f2fd;
            color: #1976d2;
        }
        
        QComboBox QAbstractItemView::item:selected {
            background-color: #4a90e2;
            color: white;
        }
        
        /* 查询进度条样式 */
        QProgressBar[class="query-progress-bar"] {
            border: 1px solid #d0d0d0;
            border-radius: 8px;
            text-align: center;
            background-color: #f5f5f5;
            height: 25px;
            font-weight: bold;
            font-size: 12px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3498db, stop:0.5 #2ecc71, stop:1 #1abc9c);
            border-radius: 6px;
            margin: 1px;
        }
        
        QTextEdit {
            border: 1px solid #d0d0d0;
            border-radius: 4px;
            background-color: white;
            font-size: 11px;
        }
        
        QTextEdit:focus {
            border: 2px solid #4a90e2;
        }
        
        QLabel {
            color: #333;
            font-size: 11px;
        }
        
        QLabel.title {
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
            margin: 20px 0;
        }
        
        QLabel.subtitle {
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 20px;
        }
        
        /* 标题标签样式 */
        QLabel[class="section-title"] {
            font-size: 16px;
            font-weight: bold;
            color: #2c3e50;
            padding: 8px;
            background-color: #ecf0f1;
            border-radius: 6px;
            border-left: 4px solid #27ae60;
        }
        
        /* 样式化下拉框 */
        QComboBox[class="styled-combo"] {
            padding: 8px 12px;
            border: 2px solid #bdc3c7;
            border-radius: 6px;
            background-color: white;
            font-size: 13px;
        }
        
        QComboBox[class="styled-combo"]:focus {
            border-color: #3498db;
        }
        
        QComboBox[class="styled-combo"]::drop-down {
            border: none;
            width: 20px;
        }
        
        QComboBox[class="styled-combo"]::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #7f8c8d;
        }
        
        /* 主要按钮样式 */
        QPushButton[class="primary-button"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3498db, stop:1 #2980b9);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 20px;
            font-weight: bold;
            font-size: 14px;
        }
        
        QPushButton[class="primary-button"]:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5dade2, stop:1 #3498db);
        }
        
        QPushButton[class="primary-button"]:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2980b9, stop:1 #1f618d);
        }
        
        /* 次要按钮样式 */
        QPushButton[class="secondary-button"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #95a5a6, stop:1 #7f8c8d);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: bold;
            font-size: 13px;
        }
        
        QPushButton[class="secondary-button"]:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #b2bec3, stop:1 #95a5a6);
        }
        
        /* 配置组样式 */
        QGroupBox[class="config-group"] {
            font-weight: bold;
            border: 2px solid #bdc3c7;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: white;
        }
        
        /* 滚动条样式 - 亮色模式 */
        QScrollBar:vertical {
            border: none;
            background: rgba(220, 220, 220, 0.2);
            width: 8px;
            margin: 0px 0px 0px 0px;
        }
        
        QScrollBar::handle:vertical {
            background: rgba(180, 180, 180, 0.7);
            min-height: 20px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:vertical:hover {
            background: rgba(160, 160, 160, 0.9);
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QScrollBar:horizontal {
            border: none;
            background: rgba(220, 220, 220, 0.2);
            height: 8px;
            margin: 0px 0px 0px 0px;
        }
        
        QScrollBar::handle:horizontal {
            background: rgba(180, 180, 180, 0.7);
            min-width: 20px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: rgba(160, 160, 160, 0.9);
        }
        
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        
        /* 透明滚动区域 */
        QScrollArea[class="transparent-scroll-area"] {
            background-color: transparent;
            border: none;
        }
        
        QScrollArea[class="transparent-scroll-area"] > QWidget > QWidget {
            background-color: transparent;
        }
    """


def add_shadow_effect(widget, blur_radius=10, offset_x=2, offset_y=2, color=None):
    """为控件添加阴影效果"""
    # 注意：此函数已被修改，不再使用QGraphicsDropShadowEffect
    # 因为PySide6的样式表不支持box-shadow属性
    # 现在使用边框和margin来模拟阴影效果
    
    # 检查控件是否有效
    if widget is None:
        return
    
    try:
        # 使用边框和margin来模拟阴影效果
        widget.setStyleSheet("""
            QPushButton {
                margin-top: 2px;
                margin-bottom: 2px;
                border: 1px solid rgba(0, 0, 0, 0.1);
            }
        """)
    except Exception as e:
        print(f"添加阴影效果替代方案失败: {e}")


def apply_button_style(button, style_type="default"):
    """应用按钮样式"""
    if style_type == "success":
        button.setProperty("class", "success")
    elif style_type == "danger":
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e74c3c, stop:1 #c0392b);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ec7063, stop:1 #e74c3c);
            }
        """)
    elif style_type == "warning":
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f39c12, stop:1 #e67e22);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f7dc6f, stop:1 #f39c12);
            }
        """)
    
    # 不再添加阴影效果，因为PySide6不支持box-shadow属性
    # 改为使用边框和margin来模拟立体感
    button.setStyleSheet(button.styleSheet() + """
        QPushButton {
            margin-top: 2px;
            margin-bottom: 2px;
            border: 1px solid rgba(0, 0, 0, 0.1);
        }
    """)


def apply_input_focus_style(widget):
    """应用输入框焦点样式"""
    widget.setStyleSheet("""
        QLineEdit:focus, QTextEdit:focus {
            border: 2px solid #4a90e2;
            background-color: #f8f9ff;
        }
    """)


def setup_dark_style():
    """设置暗黑模式样式"""
    return """
        /* 状态标签样式 */
        QLabel[class="status-label-info"] {
            color: #89b4fa;
            font-weight: bold;
            padding: 10px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 3px solid #89b4fa;
        }
        
        QLabel[class="status-label-success"] {
            color: #a6e3a1;
            font-weight: bold;
            padding: 10px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 3px solid #a6e3a1;
        }
        
        QLabel[class="status-label-error"] {
            color: #f38ba8;
            font-weight: bold;
            padding: 10px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 3px solid #f38ba8;
        }
        
        QLabel[class="status-label-waiting"] {
            color: #9399b2;
            font-style: italic;
            padding: 10px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 3px solid #7f849c;
        }
        
        QLabel[class="status-label-processing"] {
            color: #fab387;
            font-weight: bold;
            padding: 10px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 3px solid #fab387;
        }
        
        QMainWindow {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        
        QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        
        QTabWidget::pane {
            border: none;
            background-color: #1e1e2e;
            border-radius: 8px;
        }
        
        QTabBar::tab {
            background-color: #313244;
            color: #cdd6f4;
            padding: 12px 24px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #45475a;
            border-bottom: none;
        }
        
        QTabBar::tab:selected {
            background-color: #1e1e2e;
            color: #89b4fa;
            font-weight: bold;
        }
        
        QTabBar::tab:hover {
            background-color: #45475a;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #89b4fa, stop:1 #74c7ec);
            color: #1e1e2e;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: bold;
            font-size: 13px;
            outline: none;
        }
        
        QPushButton:hover {
             background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                 stop:0 #b4befe, stop:1 #89b4fa);
             margin-top: -1px;
             margin-bottom: 1px;
         }
        
        QPushButton:pressed {
             background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                 stop:0 #74c7ec, stop:1 #89dceb);
             margin-top: 1px;
             margin-bottom: -1px;
         }
        
        QPushButton:focus {
            outline: none;
            border: 2px solid #b4befe;
        }
        
        QPushButton.success {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #a6e3a1, stop:1 #94e2d5);
        }
        
        QPushButton.success:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #94e2d5, stop:1 #a6e3a1);
        }
        
        /* 主要按钮样式 */
        QPushButton[class="primary-button"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #89b4fa, stop:1 #74c7ec);
            color: #1e1e2e;
            border: none;
            border-radius: 8px;
            padding: 12px 20px;
            font-weight: bold;
            font-size: 14px;
        }
        
        QPushButton[class="primary-button"]:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #b4befe, stop:1 #89b4fa);
        }
        
        QPushButton[class="primary-button"]:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #74c7ec, stop:1 #89dceb);
        }
        
        /* 次要按钮样式 */
        QPushButton[class="secondary-button"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #7f849c, stop:1 #6c7086);
            color: #cdd6f4;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: bold;
            font-size: 13px;
        }
        
        QPushButton[class="secondary-button"]:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #9399b2, stop:1 #7f849c);
        }
        
        QGroupBox {
            font-weight: bold;
            border: 2px solid #45475a;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
            color: #cdd6f4;
        }
        
        /* 配置组样式 */
        QGroupBox[class="config-group"] {
            font-weight: bold;
            border: 2px solid #45475a;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
        
        QListWidget {
            border: 1px solid #45475a;
            border-radius: 4px;
            background-color: #1e1e2e;
            selection-background-color: #89b4fa;
            font-size: 18px;
            font-weight: 600;
            padding: 12px;
            color: #cdd6f4;
        }
        
        QListWidget::item {
            padding: 20px 24px;
            border-bottom: 1px solid #313244;
            border-radius: 8px;
            margin: 4px 0;
            min-height: 35px;
            font-size: 18px;
            font-weight: 600;
            color: #cdd6f4;
        }
        
        QListWidget::item:selected {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #89b4fa, stop:1 #74c7ec);
            color: #1e1e2e;
            font-weight: bold;
            font-size: 19px;
        }
        
        QListWidget::item:hover {
            background-color: #313244;
            color: #89b4fa;
            font-weight: bold;
            font-size: 18px;
        }
        
        QTreeWidget {
            border: 1px solid #45475a;
            border-radius: 4px;
            background-color: #1e1e2e;
            selection-background-color: #89b4fa;
            font-size: 11px;
            color: #cdd6f4;
        }
        
        QLineEdit {
            border: 1px solid #45475a;
            border-radius: 4px;
            padding: 8px;
            font-size: 11px;
            background-color: #313244;
            color: #cdd6f4;
        }
        
        QLineEdit::placeholder {
            color: #6c7086;
        }
        
        QLineEdit:focus {
            border: 2px solid #89b4fa;
        }
        
        QTextEdit {
            border: 1px solid #45475a;
            border-radius: 4px;
            padding: 8px;
            background-color: #313244;
            color: #cdd6f4;
        }
        
        QTextEdit:focus {
            border: 2px solid #89b4fa;
        }
        
        QComboBox {
            border: 2px solid #45475a;
            border-radius: 8px;
            padding: 10px 15px;
            font-size: 13px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #313244, stop:1 #45475a);
            min-width: 200px;
            min-height: 20px;
            outline: none;
            color: #cdd6f4;
        }
        
        QComboBox:hover {
            border: 2px solid #89b4fa;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #313244, stop:1 #45475a);
        }
        
        QComboBox:focus {
            border: 2px solid #89b4fa;
            outline: none;
            background: #313244;
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 35px;
            border-left: 1px solid #45475a;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #313244, stop:1 #45475a);
        }
        
        QComboBox::drop-down:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #45475a, stop:1 #585b70);
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%23cdd6f4'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        QComboBox::down-arrow:hover {
            border-top: 8px solid #89b4fa;
            border-left: 7px solid transparent;
            border-right: 7px solid transparent;
        }
        
        QComboBox QAbstractItemView {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            selection-background-color: #89b4fa;
            selection-color: #1e1e2e;
            outline: 0px;
        }
        
        /* 样式化下拉框 */
        QComboBox[class="styled-combo"] {
            border: 2px solid #45475a;
            border-radius: 6px;
            padding: 8px 12px;
            background-color: #313244;
            color: #cdd6f4;
            font-size: 13px;
        }
        
        QComboBox[class="styled-combo"]:focus {
            border-color: #89b4fa;
        }
        
        QComboBox[class="styled-combo"]::drop-down {
            border: none;
            width: 20px;
        }
        
        QComboBox[class="styled-combo"]::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #cdd6f4;
        }
        
        QLabel {
            color: #cdd6f4;
        }
        
        QLabel.title {
            font-size: 32px;
            font-weight: bold;
            color: #89b4fa;
        }
        
        QLabel.subtitle {
            font-size: 16px;
            color: #bac2de;
        }
        
        /* 标题标签样式 */
        QLabel[class="section-title"] {
            font-size: 16px;
            font-weight: bold;
            color: #cdd6f4;
            padding: 8px;
            background-color: #313244;
            border-radius: 6px;
            border-left: 4px solid #89b4fa;
        }
        
        QCheckBox {
            color: #cdd6f4;
        }
        
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #45475a;
            border-radius: 3px;
            background-color: #313244;
        }
        
        QCheckBox::indicator:checked {
            background-color: #89b4fa;
            border: 1px solid #89b4fa;
            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%231e1e2e' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'%3E%3C/polyline%3E%3C/svg%3E");
        }
        
        QCheckBox::indicator:hover {
            border: 1px solid #89b4fa;
        }
        
        QRadioButton {
            color: #cdd6f4;
        }
        
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #45475a;
            border-radius: 8px;
            background-color: #313244;
        }
        
        QRadioButton::indicator:checked {
            background-color: #313244;
            border: 1px solid #89b4fa;
            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='8' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='8' fill='%2389b4fa'/%3E%3C/svg%3E");
        }
        
        QRadioButton::indicator:hover {
            border: 1px solid #89b4fa;
        }
        
        QProgressBar {
            border: 2px solid #45475a;
            border-radius: 8px;
            background-color: #1e1e2e;
            text-align: center;
            font-weight: bold;
            font-size: 12px;
            color: #cdd6f4;
            height: 25px;
        }
        
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #89b4fa, stop:0.5 #74c7ec, stop:1 #89dceb);
            border-radius: 6px;
            margin: 1px;
            border: 1px solid #cdd6f4;
        }
        
        QProgressBar::chunk:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #b4befe, stop:0.5 #89b4fa, stop:1 #74c7ec);
        }
        
        /* 查询进度条样式 */
        QProgressBar[class="query-progress-bar"] {
            border: 2px solid #45475a;
            border-radius: 8px;
            background-color: #1e1e2e;
            text-align: center;
            font-weight: bold;
            font-size: 12px;
            color: #cdd6f4;
            height: 25px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #89b4fa, stop:0.5 #74c7ec, stop:1 #89dceb);
            border-radius: 6px;
            margin: 1px;
            border: 1px solid #cdd6f4;
        }
        
        QSpinBox, QDoubleSpinBox {
            background-color: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 4px;
            padding: 5px;
        }
        
        QSpinBox::up-button, QDoubleSpinBox::up-button {
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 20px;
            border-left: 1px solid #45475a;
            border-bottom: 1px solid #45475a;
            border-top-right-radius: 3px;
            background: #313244;
        }
        
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 20px;
            border-left: 1px solid #45475a;
            border-top-right-radius: 0px;
            border-bottom-right-radius: 3px;
            background: #313244;
        }
        
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
            background: #45475a;
        }
        
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
            image: none;
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-bottom: 5px solid #cdd6f4;
        }
        
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
            image: none;
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #cdd6f4;
        }
        
        QScrollBar:vertical {
            border: none;
            background: rgba(49, 50, 68, 0.2);
            width: 8px;
            margin: 0px 0px 0px 0px;
        }
        
        QScrollBar::handle:vertical {
            background: rgba(69, 71, 90, 0.7);
            min-height: 20px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:vertical:hover {
            background: rgba(69, 71, 90, 0.9);
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QScrollBar:horizontal {
            border: none;
            background: rgba(49, 50, 68, 0.2);
            height: 8px;
            margin: 0px 0px 0px 0px;
        }
        
        QScrollBar::handle:horizontal {
            background: rgba(69, 71, 90, 0.7);
            min-width: 20px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: rgba(69, 71, 90, 0.9);
        }
        
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        
        /* 透明滚动区域 */
        QScrollArea[class="transparent-scroll-area"] {
            background-color: transparent;
            border: none;
        }
        
        QScrollArea[class="transparent-scroll-area"] > QWidget > QWidget {
            background-color: transparent;
        }
        
        QTableWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 4px;
            gridline-color: #45475a;
        }
        
        QTableWidget::item {
            padding: 5px;
            border-bottom: 1px solid #313244;
        }
        
        QTableWidget::item:selected {
            background-color: #89b4fa;
            color: #1e1e2e;
        }
        
        QHeaderView::section {
            background-color: #313244;
            color: #cdd6f4;
            padding: 5px;
            border: 1px solid #45475a;
        }
        
        QMenu {
            background-color: #1e1e2e;
            color: #cdd6f4;
            border: 1px solid #45475a;
        }
        
        QMenu::item {
            padding: 5px 20px 5px 20px;
        }
        
        QMenu::item:selected {
            background-color: #89b4fa;
            color: #1e1e2e;
        }
        
        QStatusBar {
            background-color: #1e1e2e;
            color: #cdd6f4;
        }
    """

def get_color_palette(dark_mode=False):
    """获取颜色调色板
    
    Args:
        dark_mode: 是否使用暗黑模式调色板
    """
    if dark_mode:
        return {
            'primary': '#89b4fa',
            'primary_dark': '#74c7ec',
            'primary_light': '#b4befe',
            'success': '#a6e3a1',
            'success_dark': '#94e2d5',
            'success_light': '#94e2d5',
            'danger': '#f38ba8',
            'danger_dark': '#eba0ac',
            'danger_light': '#f5c2e7',
            'warning': '#fab387',
            'warning_dark': '#f9e2af',
            'warning_light': '#f9e2af',
            'info': '#89dceb',
            'info_dark': '#74c7ec',
            'info_light': '#89b4fa',
            'light': '#bac2de',
            'dark': '#181825',
            'muted': '#6c7086',
            'white': '#cdd6f4',
            'background': '#1e1e2e',
            'border': '#45475a',
            'border_light': '#313244'
        }
    else:
        return {
        'primary': '#4a90e2',
        'primary_dark': '#357abd',
        'primary_light': '#5ba0f2',
        'success': '#27ae60',
        'success_dark': '#229954',
        'success_light': '#2ecc71',
        'danger': '#e74c3c',
        'danger_dark': '#c0392b',
        'danger_light': '#ec7063',
        'warning': '#f39c12',
        'warning_dark': '#e67e22',
        'warning_light': '#f7dc6f',
        'info': '#3498db',
        'info_dark': '#2980b9',
        'info_light': '#5dade2',
        'light': '#ecf0f1',
        'dark': '#2c3e50',
        'muted': '#7f8c8d',
        'white': '#ffffff',
        'background': '#f5f5f5',
        'border': '#d0d0d0',
        'border_light': '#e0e6ed'
    }


def main():
    """测试函数"""
    print("主样式模块加载成功")
    
    # 测试颜色调色板
    colors = get_color_palette()
    print(f"颜色调色板: {colors}")


if __name__ == "__main__":
    main()