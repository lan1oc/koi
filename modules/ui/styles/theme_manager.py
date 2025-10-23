#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题管理器

提供主题切换和管理功能
"""

from typing import Dict, Any, Optional, Set, cast
from PySide6.QtWidgets import QWidget, QApplication, QPushButton
from PySide6.QtCore import QObject, Signal, QCoreApplication, QTimer
from PySide6.QtGui import QWindow
from .main_styles import setup_main_style, get_color_palette
# 不再从外部导入get_theme_style，使用内部方法


class ThemeManager(QObject):
    """主题管理器"""
    
    # 单例实例
    _instance = None
    
    # 主题变更信号
    theme_changed = Signal(str)
    # 暗黑模式变更信号
    dark_mode_changed = Signal(bool)
    
    def __new__(cls):
        # 实现单例模式
        if cls._instance is None:
            cls._instance = super(ThemeManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if self._initialized:
            return
            
        super().__init__()
        self.current_theme = "default"
        self.themes = self._load_themes()
        self._dark_mode = False
        self._widget_cache = set()  # 缓存已处理的部件，避免重复处理
        self._initialized = True
    
    def _load_themes(self) -> Dict[str, Dict[str, Any]]:
        """加载主题配置"""
        colors = get_color_palette()
        
        return {
            "default": {
                "name": "默认主题",
                "description": "现代化蓝色主题",
                "colors": colors,
                "style_sheet": self._get_default_theme_style()
            },
            "dark": {
                "name": "深色主题",
                "description": "深色护眼主题",
                "colors": self._get_dark_colors(),
                "style_sheet": self._get_dark_theme_style()
            },
            "light": {
                "name": "浅色主题",
                "description": "简洁浅色主题",
                "colors": self._get_light_colors(),
                "style_sheet": self._get_light_theme_style()
            }
        }
        
    def toggle_dark_mode(self) -> bool:
        """切换暗黑模式
        
        Returns:
            bool: 切换后的暗黑模式状态
        """
        self._dark_mode = not self._dark_mode
        self.dark_mode_changed.emit(self._dark_mode)
        self._apply_theme_to_application()
        return self._dark_mode
    
    def set_dark_mode(self, dark_mode: bool) -> None:
        """设置暗黑模式
        
        Args:
            dark_mode: 是否启用暗黑模式
        """
        # 无论是否改变，都应用主题样式，确保样式正确应用
        self._dark_mode = dark_mode
        self.dark_mode_changed.emit(self._dark_mode)
        self._apply_theme_to_application()
    
    def _apply_theme_to_application(self) -> None:
        """将主题应用到整个应用程序
        
        使用全局样式表而非递归处理每个部件，提高性能
        确保在亮色模式和暗色模式下都能正确应用样式
        """
        # 获取应用程序实例
        app = QApplication.instance()
        if not app:
            return
            
        # 强制设置字体大小为14pt，解决亮色模式首次启动字体小的问题
        app_instance = cast(QApplication, app)  # 类型转换，告诉类型检查器这是QApplication
        
        # 只在应用启动时设置一次字体，避免重复设置
        if not hasattr(self, '_font_set'):
            app_font = app_instance.font()
            app_font.setPointSize(14)  # 统一设置字体大小为14pt，与样式表一致
            app_instance.setFont(app_font)
            self._font_set = True
        
        # 优化：使用分阶段样式应用，减少一次性处理的样式量
        self._apply_theme_in_stages(app_instance)
    
    def _apply_theme_in_stages(self, app_instance):
        """分阶段应用主题样式，减少UI阻塞时间
        
        将样式表分为几个部分，分阶段应用，减少每次应用的样式量
        使用预编译和懒加载技术优化样式表处理
        """
        # 初始化样式缓存和预编译样式
        self._initialize_style_cache()
        
        # 检查是否需要应用新样式
        if hasattr(self, '_cached_style') and self._cached_style['mode'] == self._dark_mode:
            # 如果模式没变，使用缓存的样式表
            print(f"使用缓存样式表，当前模式：{'暗色' if self._dark_mode else '亮色'}模式")
            # 直接跳到刷新窗口阶段
            self._schedule_window_refresh()
            return
        
        # 获取当前主题的预编译样式块
        if self._dark_mode:
            style_blocks = self._dark_theme_style_blocks
        else:
            style_blocks = self._light_theme_style_blocks
        
        # 使用单阶段应用样式，避免多次设置样式表导致的解析错误
        # 这种方法在某些情况下比分阶段应用更可靠，尤其是当样式表包含复杂选择器时
        try:
            # 构建完整样式
            final_style = self._common_font_style
            for block in style_blocks:
                final_style += block
            
            # 一次性应用完整样式
            app_instance.setStyleSheet(final_style)
            
            # 缓存样式表
            self._cached_style = {
                'mode': self._dark_mode,
                'style': final_style
            }
            
            print(f"样式表应用完成，当前模式：{'暗色' if self._dark_mode else '亮色'}模式")
            
            # 安排窗口刷新
            self._schedule_window_refresh()
        except Exception as e:
            print(f"样式表应用失败: {e}")
            # 回退到基本样式
            try:
                # 只应用基本样式
                app_instance.setStyleSheet(self._common_font_style)
                print("已应用基本样式")
                self._schedule_window_refresh()
            except Exception as e2:
                print(f"基本样式应用失败: {e2}")
                # 最后的回退：清空样式表
                app_instance.setStyleSheet("")
                self._schedule_window_refresh()
    
    def _initialize_style_cache(self):
        """初始化样式缓存和预编译样式"""
        # 预先加载和缓存通用字体样式
        if not hasattr(self, '_common_font_style'):
            self._common_font_style = """
            /* 通用字体大小设置 - 适用于所有主题 */
            * {
                font-size: 14px !important;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QCheckBox, QRadioButton {
                font-size: 14px !important;
            }
            QTabBar::tab {
                font-size: 14px !important;
            }
            QLabel[class="title"] {
                font-size: 24px !important;
            }
            QLabel[class="subtitle"] {
                font-size: 16px !important;
            }
            
            /* 通用边框样式 - 确保在亮色和暗色模式下边框一致 */
            QTabWidget::pane, QGroupBox, QLineEdit, QTextEdit, QPlainTextEdit {
                border: 1px solid;
                border-radius: 8px;
            }
            
            QPushButton {
                border-radius: 8px;
                padding: 10px 15px;
            }
            """
        
        # 预编译主题样式，将样式表分成多个块以便分阶段加载
        if not hasattr(self, '_dark_theme_style_blocks'):
            # 加载完整样式
            if not hasattr(self, '_dark_theme_style'):
                self._dark_theme_style = self._get_dark_theme_style()
                self._light_theme_style = self._get_light_theme_style()
            
            # 将样式表分成三个块
            self._dark_theme_style_blocks = self._split_style_into_blocks(self._dark_theme_style)
            self._light_theme_style_blocks = self._split_style_into_blocks(self._light_theme_style)
    
    def _split_style_into_blocks(self, style):
        """将样式表分成多个块，便于分阶段加载"""
        lines = style.split('\n')
        total_lines = len(lines)
        
        # 计算每个块的大小，优先加载关键样式
        # 第一个块：主窗口和基本控件样式（约30%）
        # 第二个块：次要控件样式（约30%）
        # 第三个块：其余样式（约40%）
        block1_end = int(total_lines * 0.3)
        block2_end = int(total_lines * 0.6)
        
        # 创建样式块
        block1 = '\n'.join(lines[:block1_end])
        block2 = '\n'.join(lines[block1_end:block2_end])
        block3 = '\n'.join(lines[block2_end:])
        
        return [block1, block2, block3]
    
    def _schedule_window_refresh(self):
        """安排窗口刷新"""
        # 使用定时器延迟刷新窗口，避免在样式应用后立即刷新导致的性能问题
        if not hasattr(self, '_refresh_timer'):
            self._refresh_timer = QTimer()
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.timeout.connect(self._refresh_windows)
        
        # 如果定时器已经在运行，不重新启动
        if self._refresh_timer.isActive():
            return
        
        # 启动定时器，使用更短的延迟时间
        self._refresh_timer.start(20)
    
    def _refresh_windows(self):
        """智能刷新窗口
        
        使用分层刷新策略和智能缓存机制，减少不必要的重绘操作
        """
        app = QApplication.instance()
        if not app:
            return
            
        # 明确指定app为QApplication类型，解决类型检查错误
        app_instance = cast(QApplication, app)
        
        # 初始化窗口缓存
        if not hasattr(self, '_window_cache'):
            self._window_cache = {
                'main_window': None,  # 主窗口引用
                'last_refresh': 0,   # 上次刷新时间
                'visible_windows': set()  # 可见窗口集合
            }
        
        # 查找并缓存主窗口
        main_window = self._window_cache['main_window']
        if main_window is None or not main_window.isVisible():
            # 重新查找主窗口
            for window in app_instance.topLevelWidgets():
                # 通常主窗口是第一个可见的顶层QWidget，且有标题
                if isinstance(window, QWidget) and window.isVisible() and window.windowTitle():
                    self._window_cache['main_window'] = window
                    main_window = window
                    break
        
        # 如果找到了主窗口，优先刷新它
        if main_window and main_window.isVisible():
            # 使用更高效的刷新方法
            main_window.update()
            
            # 智能刷新：只刷新主窗口的直接子部件，而不是递归刷新所有子部件
            # 这样可以减少不必要的重绘操作，同时保证UI的一致性
            for child in main_window.children():
                if isinstance(child, QWidget) and child.isVisible():
                    child.update()
        else:
            # 回退策略：如果没有找到主窗口，刷新所有可见的顶层窗口
            visible_windows = set()
            for window in app_instance.topLevelWidgets():
                if isinstance(window, QWidget) and window.isVisible():
                    window.update()
                    visible_windows.add(window)
                    
                    # 如果找到了主窗口，缓存它
                    if window.windowTitle() and self._window_cache['main_window'] is None:
                        self._window_cache['main_window'] = window
    
    def _get_dark_colors(self) -> Dict[str, str]:
        """获取深色主题颜色"""
        return {
            'primary': '#bb86fc',
            'primary_dark': '#985eff',
            'primary_light': '#d7aefb',
            'success': '#4caf50',
            'success_dark': '#388e3c',
            'success_light': '#81c784',
            'danger': '#f44336',
            'danger_dark': '#d32f2f',
            'danger_light': '#ef5350',
            'warning': '#ff9800',
            'warning_dark': '#f57c00',
            'warning_light': '#ffb74d',
            'info': '#2196f3',
            'info_dark': '#1976d2',
            'info_light': '#64b5f6',
            'light': '#424242',
            'dark': '#1e1e1e',  # 修改为较浅的黑色，降低对比度
            'muted': '#757575',
            'white': '#1e1e1e',
            'background': '#1e1e1e',  # 修改为较浅的黑色，降低对比度
            'border': '#333333',
            'border_light': '#424242'
        }
    
    def _get_light_colors(self) -> Dict[str, str]:
        """获取浅色主题颜色"""
        return {
            'primary': '#007bff',
            'primary_dark': '#0056b3',
            'primary_light': '#66b3ff',
            'success': '#28a745',
            'success_dark': '#1e7e34',
            'success_light': '#71dd8a',
            'danger': '#dc3545',
            'danger_dark': '#bd2130',
            'danger_light': '#f1b0b7',
            'warning': '#ffc107',
            'warning_dark': '#d39e00',
            'warning_light': '#fff3cd',
            'info': '#17a2b8',
            'info_dark': '#117a8b',
            'info_light': '#b8daff',
            'light': '#f8f9fa',
            'dark': '#343a40',
            'muted': '#6c757d',
            'white': '#ffffff',
            'background': '#ffffff',
            'border': '#dee2e6',
            'border_light': '#e9ecef'
        }
    
    def _get_default_theme_style(self) -> str:
        """获取默认主题样式"""
        return """
        /* 默认主题样式已在main_styles.py中定义 */
        """
    
    def _get_dark_theme_style(self) -> str:
        """获取深色主题样式"""
        return         """
        /* 全局隐藏焦点虚线框 */
        * {
            outline: none;
        }
        
        QMainWindow {
            background-color: #1e1e1e;
            color: #f0f0f0;
        }
        
        QWidget {
            background-color: #1e1e1e;
            color: #f0f0f0;
        }
        
        /* 列表和树形控件样式 */
        QListWidget, QTreeWidget {
            background-color: #2d2d2d;
            color: #f0f0f0;
            border: 1px solid #3d3d3d;
            border-radius: 8px;
            padding: 5px;
            outline: none;
        }
        
        QTreeWidget::header {
            background-color: #2d2d2d;
            color: #f0f0f0;
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            padding: 5px;
        }
        
        QHeaderView {
            background-color: #2d2d2d;
            color: #f0f0f0;
        }
        
        QHeaderView::section {
            background-color: #2d2d2d;
            color: #f0f0f0;
            padding: 8px;
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            font-weight: bold;
        }
        
        QHeaderView::section:hover {
            background-color: #3d3d3d;
        }
        
        /* 表格样式 */
        QTableWidget {
            background-color: #2d2d2d !important;
            color: #f0f0f0 !important;
            gridline-color: #3d3d3d;
            selection-background-color: #483d8b;
            selection-color: #ffffff;
            alternate-background-color: #333333;
        }
        
        QTableWidget::item {
            color: #f0f0f0 !important;
            background-color: #2d2d2d !important;
            padding: 12px 8px;
            border: none;
        }
        
        QTableWidget QTableWidgetItem {
            background-color: #2d2d2d !important;
            color: #f0f0f0 !important;
        }
        
        QTableWidget::item:selected {
            background-color: #483d8b;
            color: #ffffff;
        }
        
        QTableWidget::item:hover {
            background-color: #3d3d3d;
        }
        
        /* 表格表头样式 - 暗色模式 */
        QTableWidget QHeaderView {
            background-color: #2d2d2d;
            color: #f0f0f0;
        }
        
        QTableWidget QHeaderView::section {
            background-color: #2d2d2d;
            color: #f0f0f0;
            padding: 8px;
            border: 1px solid #3d3d3d;
            border-radius: 0px;
            font-weight: bold;
        }
        
        QTableWidget QHeaderView::section:hover {
            background-color: #3d3d3d;
        }
        
        QListWidget::item, QTreeWidget::item {
            padding: 10px 15px;
            border-bottom: 1px solid #3d3d3d;
            border-radius: 4px;
            margin: 2px 0px;
        }
        
        QListWidget::item:hover, QTreeWidget::item:hover {
            background-color: #3d3d3d;
        }
        
        QListWidget::item:selected, QTreeWidget::item:selected {
            background-color: #483d8b;
            color: #ffffff;
            border-left: 3px solid #bb86fc;
        }
        
        /* 对话框和弹窗样式 - 现代化设计 */
        QDialog, QMessageBox, QFileDialog {
            background-color: #1e1e1e;
            color: #f0f0f0;
            border: 1px solid #333333;
            border-radius: 12px;
            padding: 12px;
        }
        
        /* 对话框标题栏 */
        QDialog QLabel#qt_msgbox_label, QMessageBox QLabel#qt_msgbox_label {
            font-size: 18px;
            font-weight: bold;
            color: #bb86fc;
            padding: 12px 0;
            margin-bottom: 12px;
            border-bottom: 1px solid #333333;
        }
        
        /* 对话框内容区域 */
        QDialog QLabel, QMessageBox QLabel {
            font-size: 14px;
            color: #f0f0f0;
            padding: 5px 0;
        }
        
        /* 对话框按钮区域 */
        QDialog QDialogButtonBox, QMessageBox QDialogButtonBox {
            padding: 10px 0;
            spacing: 10px;
        }
        
        /* 对话框按钮样式 */
        QDialog QPushButton, QMessageBox QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3d3d3d, stop:1 #2d2d2d);
            color: #f0f0f0;
            border: 1px solid #505050;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: bold;
            min-width: 100px;
            min-height: 36px;
        }
        
        QDialog QPushButton:hover, QMessageBox QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #505050, stop:1 #3d3d3d);
            border: 1px solid #bb86fc;
        }
        
        QDialog QPushButton:pressed, QMessageBox QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2d2d2d, stop:1 #3d3d3d);
        }
        
        /* 标签页样式 - 现代化美观设计 */
        QTabWidget::pane {
            border: 1px solid #333333;
            background-color: #252525;
            border-radius: 8px;
            top: -1px; /* 微调标签页与内容的连接 */
        }
        
        QTabBar::tab {
            background-color: #2d2d2d;
            color: #b0b0b0;
            padding: 12px 24px;
            margin-right: 4px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #333333;
            border-bottom: none;
            font-size: 14px !important;
            min-width: 80px;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QTabBar::tab:selected {
            background-color: #252525;
            color: #bb86fc;
            font-weight: bold;
            border-bottom: 2px solid #bb86fc;
        }
        
        QTabBar::tab:hover:!selected {
            background-color: #383838;
            color: #d0d0d0;
        }
        
        QTabBar::close-button {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23b0b0b0'%3E%3Cpath d='M1 1l10 10m0-10L1 11'/%3E%3C/svg%3E");
            subcontrol-position: right;
            subcontrol-origin: margin;
            margin: 2px;
        }
        
        QTabBar::close-button:hover {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23bb86fc'%3E%3Cpath d='M1 1l10 10m0-10L1 11'/%3E%3C/svg%3E");
            background-color: rgba(187, 134, 252, 0.1);
            border-radius: 2px;
        }
        
        /* 窗口控制按钮样式 - 暗色模式优化 */
        #windowButton {
            border-radius: 0px;
            padding: 0px;
            background-color: transparent;
            border: none;
            font-size: 16px;
            color: #ffffff;  /* 明亮的白色，提高可见性 */
            font-weight: bold;
        }
        
        #windowButton:hover {
            background-color: rgba(187, 134, 252, 0.3);  /* 紫色高亮 */
            color: #ffffff;
        }
        
        #windowButton:pressed {
            background-color: rgba(187, 134, 252, 0.5);
            color: #ffffff;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3d3d3d, stop:1 #2d2d2d);
            color: #f0f0f0;
            border: 1px solid #505050;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: bold;
            font-size: 14px !important;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #505050, stop:1 #3d3d3d);
            border: 1px solid #bb86fc;
        }
        
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2d2d2d, stop:1 #3d3d3d);
        }
        
        QPushButton:focus {
            /* 自定义焦点样式，替代默认虚线框 */
            border: 1px solid #bb86fc;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a4a4a, stop:1 #3a3a3a);
            outline: none;
        }
        
        QGroupBox {
            font-weight: bold;
            border: 2px solid #383838;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #252525;
            color: #f0f0f0;
        }
        
        QLineEdit {
            border: 1px solid #383838;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px !important;
            background-color: #252525;
            color: #f0f0f0;
        }
        
        QLineEdit:focus {
            border: 2px solid #bb86fc;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QTextEdit {
            border: 1px solid #383838;
            border-radius: 4px;
            background-color: #252525;
            color: #f0f0f0;
            font-size: 14px !important;
        }
        
        QTextEdit:focus {
            border: 2px solid #bb86fc;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QLabel {
            color: #f0f0f0;
            font-size: 14px !important;
            background-color: transparent;
        }
        
        QLabel.title {
            font-size: 24px !important;
            font-weight: bold;
            color: #bb86fc;
            margin: 20px 0;
        }
        
        QLabel.subtitle {
            font-size: 16px !important;
            color: #a0a0a0;
            margin-bottom: 20px;
        }
        
        /* 下拉框样式 - 现代化美观设计 */
        QComboBox {
            background-color: #252525;
            color: #f0f0f0;
            border: 1px solid #383838;
            border-radius: 8px;
            padding: 10px 15px;
            min-width: 6em;
            font-size: 14px !important;
            selection-background-color: #bb86fc;
            selection-color: #1e1e1e;
            padding-right: 35px; /* 为下拉箭头留出空间 */
        }
        
        QComboBox:hover {
            border: 1px solid #bb86fc;
            background-color: #2d2d2d;
        }
        
        QComboBox:focus {
            border: 2px solid #bb86fc;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border-left: none;
            margin-right: 5px;
            background-color: transparent;
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%23bb86fc'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        /* 现代化进度条样式 - 暗色模式 */
        QProgressBar {
            border: none;
            border-radius: 12px;
            background-color: #2d2d2d;
            text-align: center;
            font-weight: bold;
            font-size: 13px;
            color: #ffffff;
            height: 24px;
            padding: 2px;
        }
        
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #bb86fc, stop:0.3 #9c27b0, stop:0.7 #673ab7, stop:1 #3f51b5);
            border-radius: 10px;
            margin: 1px;
        }
        
        QProgressBar::chunk:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #d1c4e9, stop:0.3 #bb86fc, stop:0.7 #9c27b0, stop:1 #673ab7);
        }
        
        /* 查询进度条特殊样式 */
        QProgressBar[class="query-progress-bar"] {
            border: none;
            border-radius: 15px;
            background-color: rgba(45, 45, 45, 0.8);
            text-align: center;
            font-weight: bold;
            font-size: 14px;
            color: #ffffff;
            height: 30px;
            padding: 3px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00bcd4, stop:0.2 #4caf50, stop:0.5 #8bc34a, stop:0.8 #cddc39, stop:1 #ffeb3b);
            border-radius: 12px;
            margin: 2px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #26c6da, stop:0.2 #66bb6a, stop:0.5 #9ccc65, stop:0.8 #d4e157, stop:1 #ffee58);
        }
        
        QComboBox QAbstractItemView {
            background-color: #2d2d2d;
            color: #f0f0f0;
            border: 1px solid #bb86fc;
            border-radius: 8px;
            padding: 5px;
            selection-background-color: #bb86fc;
            selection-color: #1e1e1e;
            outline: none;
        }
        
        QComboBox QAbstractItemView::item {
            padding: 8px 10px;
            border-radius: 4px;
            min-height: 25px;
        }
        
        QComboBox QAbstractItemView::item:hover {
            background-color: #3d3d3d;
        }
        
        /* 滚动条样式 */
        QScrollBar:vertical {
            border: none;
            background: #252525;
            width: 10px;
            margin: 0px 0px 0px 0px;
            border-radius: 5px;
        }
        
        QScrollBar::handle:vertical {
            background: #505050;
            min-height: 20px;
            border-radius: 5px;
        }
        
        QScrollBar::handle:vertical:hover {
            background: #bb86fc;
        }
        
        QScrollBar:horizontal {
            border: none;
            background: #252525;
            height: 10px;
            margin: 0px 0px 0px 0px;
            border-radius: 5px;
        }
        
        QScrollBar::handle:horizontal {
            background: #505050;
            min-width: 20px;
            border-radius: 5px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background: #bb86fc;
        }
        
        /* 表格样式 */
        QTableWidget {
            background-color: #ffffff;
            color: #343a40;
            gridline-color: #dee2e6;
            selection-background-color: #007bff;
            selection-color: #ffffff;
            alternate-background-color: #f8f9fa;
        }
        
        QTableWidget::item {
            color: #343a40;
            background-color: transparent;
            padding: 12px 8px;
            border: none;
        }
        
        QTableWidget::item:selected {
            background-color: #007bff;
            color: #ffffff;
        }
        
        QTableWidget::item:hover {
            background-color: #e9ecef;
        }
        """
    
    def _get_light_theme_style(self) -> str:
        """获取浅色主题样式"""
        # 确保返回完整的亮色模式样式定义
        return         """
        /* 全局隐藏焦点虚线框 */
        * {
            outline: none;
        }
        
        /* 基础控件样式 */
        QMainWindow, QWidget {
            background-color: #ffffff;
            color: #343a40;
        }
        
        /* 对话框和弹窗样式 - 现代化设计 */
        QDialog, QMessageBox, QFileDialog {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 12px;
            padding: 12px;
        }
        
        /* 对话框标题栏 */
        QDialog QLabel#qt_msgbox_label, QMessageBox QLabel#qt_msgbox_label {
            font-size: 18px;
            font-weight: bold;
            color: #007bff;
            padding: 12px 0;
            margin-bottom: 12px;
            border-bottom: 1px solid #dee2e6;
        }
        
        /* 对话框内容区域 */
        QDialog QLabel, QMessageBox QLabel {
            font-size: 14px;
            color: #343a40;
            padding: 5px 0;
        }
        
        /* 对话框按钮区域 */
        QDialog QDialogButtonBox, QMessageBox QDialogButtonBox {
            padding: 10px 0;
            spacing: 10px;
        }
        
        /* 对话框按钮样式 */
        QDialog QPushButton, QMessageBox QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #007bff, stop:1 #0056b3);
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: bold;
            min-width: 100px;
            min-height: 36px;
        }
        
        QDialog QPushButton:hover, QMessageBox QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #0069d9, stop:1 #0062cc);
            border: none;
        }
        
        QDialog QPushButton:pressed, QMessageBox QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #0056b3, stop:1 #004085);
        }
        
        /* 列表和树形控件样式 */
        QListWidget, QTreeWidget {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 5px;
            outline: none;
        }
        
        QListWidget::item, QTreeWidget::item {
            padding: 10px 15px;
            border-bottom: 1px solid #f0f0f0;
            border-radius: 4px;
            margin: 2px 0px;
        }
        
        QListWidget::item:hover, QTreeWidget::item:hover {
            background-color: #f5f5f5;
        }
        
        QListWidget::item:selected, QTreeWidget::item:selected {
            background-color: #e3f2fd;
            color: #007bff;
            border-left: 3px solid #007bff;
        }
        
        /* 树形控件表头样式 */
        QTreeWidget::header {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
        }
        
        QHeaderView {
            background-color: #f8f9fa;
            color: #343a40;
        }
        
        QHeaderView::section {
            background-color: #f8f9fa;
            color: #343a40;
            padding: 8px;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            font-weight: bold;
        }
        
        /* 标签页样式 - 现代化美观设计 */
        QTabWidget::pane {
            border: 1px solid #dee2e6;
            background-color: #ffffff;
            border-radius: 8px;
            top: -1px; /* 微调标签页与内容的连接 */
        }
        
        QTabBar::tab {
            background-color: #f8f9fa;
            color: #6c757d;
            padding: 12px 24px;
            margin-right: 4px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            border: 1px solid #dee2e6;
            border-bottom: none;
            font-size: 14px !important;
            min-width: 80px;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QTabBar::tab:selected {
            background-color: #ffffff;
            color: #007bff;
            font-weight: bold;
            border-bottom: 2px solid #007bff;
        }
        
        QTabBar::tab:hover:!selected {
            background-color: #e9ecef;
            color: #343a40;
        }
        
        QTabBar::close-button {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%236c757d'%3E%3Cpath d='M1 1l10 10m0-10L1 11'/%3E%3C/svg%3E");
            subcontrol-position: right;
            subcontrol-origin: margin;
            margin: 2px;
        }
        
        QTabBar::close-button:hover {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23007bff'%3E%3Cpath d='M1 1l10 10m0-10L1 11'/%3E%3C/svg%3E");
            background-color: rgba(0, 123, 255, 0.1);
            border-radius: 2px;
        }
        
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #007bff, stop:1 #0056b3);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: bold;
            font-size: 14px !important;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #66b3ff, stop:1 #007bff);
        }
        
        QPushButton:focus {
            /* 自定义焦点样式，替代默认虚线框 */
            border: 2px solid #007bff;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4da6ff, stop:1 #007bff);
            outline: none;
        }
        
        /* 标签样式 */
        QLabel {
            color: #343a40;
            background-color: transparent;
            font-size: 14px !important;
        }
        
        QLineEdit, QTextEdit, QPlainTextEdit {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 5px;
            font-size: 14px !important;
        }
        
        /* 下拉框样式 - 现代化美观设计 */
        QComboBox {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 10px 15px;
            min-width: 6em;
            font-size: 14px !important;
            selection-background-color: #007bff;
            selection-color: #ffffff;
            padding-right: 35px; /* 为下拉箭头留出空间 */
        }
        
        QComboBox:hover {
            border: 1px solid #007bff;
            background-color: #f8f9fa;
        }
        
        QComboBox:focus {
            border: 2px solid #007bff;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border-left: none;
            margin-right: 5px;
            background-color: transparent;
        }
        
        QComboBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%23007bff'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
            width: 20px;
            height: 20px;
            margin-right: 5px;
        }
        
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #007bff;
            border-radius: 8px;
            padding: 5px;
            selection-background-color: #007bff;
            selection-color: #ffffff;
            outline: none;
        }
        
        QComboBox QAbstractItemView::item {
            padding: 8px 10px;
            border-radius: 4px;
            min-height: 25px;
        }
        
        QComboBox QAbstractItemView::item:hover {
            background-color: #e9ecef;
        }
        
        QComboBox QAbstractItemView::item {
            padding: 8px 10px;
            border-radius: 4px;
            min-height: 25px;
        }
        
        QComboBox QAbstractItemView::item:hover {
            background-color: #e9ecef;
        }
        
        /* 复选框和单选按钮样式 */
        QCheckBox, QRadioButton {
            color: #343a40;
            background-color: transparent;
            font-size: 14px !important;
        }
        
        /* 数字输入框样式 */
        QSpinBox, QDoubleSpinBox {
            background-color: #ffffff;
            color: #343a40;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 5px;
            font-size: 14px !important;
        }
        
        QSpinBox::up-button, QDoubleSpinBox::up-button {
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 16px;
            border-left: 1px solid #dee2e6;
            border-bottom: 1px solid #dee2e6;
            border-top-right-radius: 3px;
            background-color: #f8f9fa;
        }
        
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 16px;
            border-left: 1px solid #dee2e6;
            border-top: 1px solid #dee2e6;
            border-bottom-right-radius: 3px;
            background-color: #f8f9fa;
        }
        
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23343a40'%3E%3Cpath d='M6 0l6 6H0z'/%3E%3C/svg%3E");
            width: 12px;
            height: 12px;
        }
        
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
            image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23343a40'%3E%3Cpath d='M0 0l6 6 6-6z'/%3E%3C/svg%3E");
            width: 12px;
            height: 12px;
        }
        
        QGroupBox {
            font-weight: bold;
            border: 2px solid #dee2e6;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #ffffff;
            color: #343a40;
        }
        
        QLineEdit {
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px !important;
            background-color: #ffffff;
            color: #343a40;
        }
        
        QLineEdit:focus {
            border: 2px solid #007bff;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        /* 表格样式 */
        QTableWidget, QTableView {
            background-color: #ffffff;
            color: #343a40;
            gridline-color: #dee2e6;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            selection-background-color: #e9ecef;
            selection-color: #343a40;
        }
        
        QTableWidget::item, QTableView::item {
            padding: 5px;
            border: none;
        }
        
        QTableWidget::item:selected, QTableView::item:selected {
            background-color: #e9ecef;
            color: #343a40;
        }
        
        QHeaderView {
            background-color: #f8f9fa;
            color: #343a40;
            border: none;
            border-bottom: 1px solid #dee2e6;
        }
        
        QHeaderView::section {
            background-color: #f8f9fa;
            color: #343a40;
            padding: 5px;
            border: none;
            border-right: 1px solid #dee2e6;
            border-bottom: 1px solid #dee2e6;
            font-weight: bold;
        }
        
        QTextEdit {
            border: 1px solid #dee2e6;
            border-radius: 4px;
            background-color: #ffffff;
            color: #343a40;
            font-size: 14px !important;
        }
        
        QTextEdit:focus {
            border: 2px solid #007bff;
            outline: none; /* 隐藏焦点虚线框 */
        }
        
        QLabel {
            color: #343a40;
            font-size: 14px !important;
        }
        
        QLabel.title {
            font-size: 24px !important;
            font-weight: bold;
            color: #007bff;
            margin: 20px 0;
        }
        
        QLabel.subtitle {
            font-size: 16px !important;
            color: #6c757d;
            margin-bottom: 20px;
        }
        
        /* 滚动条样式 */
        QScrollBar:vertical {
            border: none;
            background: #f8f9fa;
            width: 12px;
            margin: 0px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical {
            background: #dee2e6;
            min-height: 20px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical:hover {
            background: #ced4da;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollBar:horizontal {
            border: none;
            background: #f8f9fa;
            height: 12px;
            margin: 0px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal {
            background: #dee2e6;
            min-width: 20px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal:hover {
            background: #ced4da;
        }

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        
        /* 表格样式 */
        QTableWidget {
            background-color: #ffffff;
            color: #343a40;
            gridline-color: #dee2e6;
            selection-background-color: #007bff;
            selection-color: #ffffff;
            alternate-background-color: #f8f9fa;
        }
        
        QTableWidget::item {
            color: #343a40;
            background-color: transparent;
            padding: 8px;
            border: none;
        }
        
        QTableWidget::item:selected {
            background-color: #007bff;
            color: #ffffff;
        }
        
        QTableWidget::item:hover {
            background-color: #e9ecef;
        }
        
        /* 表格表头样式 - 亮色模式 */
        QTableWidget QHeaderView {
            background-color: #f8f9fa;
            color: #343a40;
        }
        
        QTableWidget QHeaderView::section {
            background-color: #f8f9fa;
            color: #343a40;
            padding: 10px;
            border: 1px solid #dee2e6;
            border-radius: 0px;
            font-weight: bold;
        }
        
        QTableWidget QHeaderView::section:hover {
            background-color: #e9ecef;
        }
        
        /* 现代化进度条样式 - 亮色模式 */
        QProgressBar {
            border: none;
            border-radius: 12px;
            background-color: #f8f9fa;
            text-align: center;
            font-weight: bold;
            font-size: 13px;
            color: #343a40;
            height: 24px;
            padding: 2px;
        }
        
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #007bff, stop:0.3 #0056b3, stop:0.7 #004085, stop:1 #002752);
            border-radius: 10px;
            margin: 1px;
        }
        
        QProgressBar::chunk:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0069d9, stop:0.3 #007bff, stop:0.7 #0056b3, stop:1 #004085);
        }
        
        /* 查询进度条特殊样式 */
        QProgressBar[class="query-progress-bar"] {
            border: none;
            border-radius: 15px;
            background-color: rgba(248, 249, 250, 0.9);
            text-align: center;
            font-weight: bold;
            font-size: 14px;
            color: #343a40;
            height: 30px;
            padding: 3px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #17a2b8, stop:0.2 #28a745, stop:0.5 #ffc107, stop:0.8 #fd7e14, stop:1 #dc3545);
            border-radius: 12px;
            margin: 2px;
        }
        
        QProgressBar[class="query-progress-bar"]::chunk:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #20c997, stop:0.2 #34ce57, stop:0.5 #ffcd39, stop:0.8 #ff851b, stop:1 #e74c3c);
        }
        """
    
    def apply_theme(self, widget: QWidget, theme_name: str | None = None) -> bool:
        """应用主题"""
        try:
            if theme_name is None:
                theme_name = self.current_theme
            
            if theme_name not in self.themes:
                print(f"主题 '{theme_name}' 不存在")
                return False
            
            theme = self.themes[theme_name]
            
            if theme_name == "default":
                # 使用默认样式
                setup_main_style(widget)
            else:
                # 应用自定义主题样式
                widget.setStyleSheet(theme["style_sheet"])
            
            self.current_theme = theme_name
            self.theme_changed.emit(theme_name)
            
            print(f"主题 '{theme['name']}' 应用成功")
            return True
            
        except Exception as e:
            print(f"应用主题失败: {e}")
            return False
    
    def get_available_themes(self) -> Dict[str, str]:
        """获取可用主题列表"""
        return {name: theme["name"] for name, theme in self.themes.items()}
    
    def get_theme_info(self, theme_name: str) -> Optional[Dict[str, Any]]:
        """获取主题信息"""
        return self.themes.get(theme_name)
    
    def get_current_theme(self) -> str:
        """获取当前主题名称"""
        return self.current_theme
    
    def get_theme_colors(self, theme_name: str | None = None) -> Dict[str, str]:
        """获取主题颜色"""
        if theme_name is None:
            theme_name = self.current_theme
        
        theme = self.themes.get(theme_name)
        if theme:
            return theme["colors"]
        return get_color_palette()
    
    def add_custom_theme(self, name: str, theme_data: Dict[str, Any]) -> bool:
        """添加自定义主题"""
        try:
            required_keys = ["name", "description", "colors", "style_sheet"]
            
            for key in required_keys:
                if key not in theme_data:
                    print(f"主题数据缺少必要字段: {key}")
                    return False
            
            self.themes[name] = theme_data
            print(f"自定义主题 '{name}' 添加成功")
            return True
            
        except Exception as e:
            print(f"添加自定义主题失败: {e}")
            return False
    
    def remove_theme(self, theme_name: str) -> bool:
        """移除主题（不能移除内置主题）"""
        if theme_name in ["default", "dark", "light"]:
            print(f"不能移除内置主题: {theme_name}")
            return False
        
        if theme_name in self.themes:
            del self.themes[theme_name]
            print(f"主题 '{theme_name}' 移除成功")
            return True
        
        print(f"主题 '{theme_name}' 不存在")
        return False
    
    def export_theme(self, theme_name: str, file_path: str) -> bool:
        """导出主题到文件"""
        try:
            if theme_name not in self.themes:
                print(f"主题 '{theme_name}' 不存在")
                return False
            
            import json
            
            theme_data = self.themes[theme_name]
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(theme_data, f, indent=2, ensure_ascii=False)
            
            print(f"主题 '{theme_name}' 导出成功: {file_path}")
            return True
            
        except Exception as e:
            print(f"导出主题失败: {e}")
            return False
    
    def import_theme(self, file_path: str, theme_name: str | None = None) -> bool:
        """从文件导入主题"""
        try:
            import json
            import os
            
            if not os.path.exists(file_path):
                print(f"主题文件不存在: {file_path}")
                return False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                theme_data = json.load(f)
            
            if theme_name is None:
                theme_name = os.path.splitext(os.path.basename(file_path))[0]
            
            return self.add_custom_theme(theme_name, theme_data)
            
        except Exception as e:
            print(f"导入主题失败: {e}")
            return False


def main():
    """测试函数"""
    print("主题管理器模块加载成功")
    
    # 测试主题管理器
    theme_manager = ThemeManager()
    
    # 获取可用主题
    themes = theme_manager.get_available_themes()
    print(f"可用主题: {themes}")
    
    # 获取当前主题
    current = theme_manager.get_current_theme()
    print(f"当前主题: {current}")


if __name__ == "__main__":
    main()