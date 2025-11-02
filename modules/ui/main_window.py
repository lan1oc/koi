#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块

从fool_tools.py提取的主窗口类
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QPushButton, QLabel, QListWidget, QTextEdit,
    QComboBox, QLineEdit, QFileDialog, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QSplitter, QFrame, QScrollArea, QGridLayout,
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QDialog,
    QGraphicsDropShadowEffect, QPlainTextEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QRadioButton
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QEvent, QSize
from PySide6.QtGui import QFont, QPixmap, QIcon, QColor, QPalette

# 导入模块化组件
from modules.Information_Gathering.Enterprise_Query.aiqicha_query import AiqichaQuery
from modules.Information_Gathering.Enterprise_Query.tianyancha_query import TianyanchaQuery
from modules.Information_Gathering.Asset_Mapping.hunter import HunterAPI
from modules.config.config_manager import ConfigManager
from modules.ui.styles.main_styles import setup_main_style, add_shadow_effect


class ModernDataProcessorPySide6(QMainWindow):
    """现代化数据处理主窗口"""
    
    def __init__(self, config_manager=None):
        super().__init__()
        
        # 配置管理器
        self.config_manager = config_manager or ConfigManager()
        
        # 线程管理列表 - 用于跟踪所有活动线程
        self.active_threads = []
        
        # 设置窗口基本属性
        self.setWindowTitle("koi")
        
        # 设置窗口无边框
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 允许自定义窗口背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 设置窗口图标
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "1.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        # 用于窗口拖动
        self.dragging = False
        self.drag_position = None
        
        # 设置窗口居中和大小
        self.setup_window_geometry()
        
        # 初始化配置
        self.init_config()
        
        # 设置暗黑模式状态
        self.dark_mode = self.config.get('ui_settings', {}).get('dark_mode', False)
        
        # 应用样式 - 使用ThemeManager
        from modules.ui.styles.theme_manager import ThemeManager
        self.theme_manager = ThemeManager()
        
        # 应用主题 - 先应用主题，让ThemeManager处理字体大小和样式
        self.theme_manager.set_dark_mode(self.dark_mode)
        
        # 确保主题样式被正确应用
        self.theme_manager._apply_theme_to_application()
        
        # 预先创建UI控件（避免None错误）
        self.init_ui_components()
        
        # 初始化UI
        self.setup_ui()
        
        # 设置状态栏
        self.statusBar().showMessage("就绪")
        
        # 延迟初始化API实例，减少启动时间
        QTimer.singleShot(800, self.init_apis)
        
        # 设置输入框焦点阴影效果
        QTimer.singleShot(1000, self.setup_input_focus_effects)
        
        # 设置窗口样式
        self.setStyleSheet("""
            QMainWindow {
                border-radius: 10px;
                background-color: palette(window);
                border: 1px solid palette(mid);
            }
            
            #windowButton {
                border-radius: 0px;
                padding: 0px;
                background-color: transparent;
                border: none;
                font-size: 16px;
                color: palette(text);
            }
            
            #windowButton:hover {
                background-color: rgba(128, 128, 128, 0.2);
            }
            
            #windowButton:pressed {
                background-color: rgba(128, 128, 128, 0.3);
            }
            
            #themeButton {
                border-radius: 0px;
                padding: 0px;
                background-color: transparent;
                border: none;
                font-size: 16px;
                color: palette(text);
            }
            
            #themeButton:hover {
                background-color: rgba(128, 128, 128, 0.2);
            }
            
            #themeButton:pressed {
                background-color: rgba(128, 128, 128, 0.3);
            }
        """)
    
    def setup_window_geometry(self):
        """设置窗口几何属性"""
        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.5)
        height = int(screen.height() * 0.9)
        self.resize(width, height)
        
        x = (screen.width() - width) // 2
        y = int(screen.height() * 0.01)
        self.move(x, y)
        
        self.setMinimumSize(1000, 820)
    
    def init_config(self):
        """初始化配置"""
        self.config = self.config_manager.load_config()
        self.hunter_config = self.config.get('hunter', {})
        self.quake_config = self.config.get('quake', {})
        self.fofa_config = self.config.get('fofa', {})
        self.tyc_config = self.config.get('tyc', {})
        self.aiqicha_config = self.config.get('aiqicha', {})
        
        # 确保UI设置存在
        if 'ui_settings' not in self.config:
            self.config['ui_settings'] = {}
            self.config_manager.save_config(self.config)
    
    def init_apis(self):
        """初始化API实例"""
        # 使用延迟初始化，减少启动时的性能开销
        # 只预先设置变量，实际初始化在需要时进行
        
        # API实例
        self.tyc_searcher = None
        self.aiqicha_query = None
        self.hunter_api = None
        
        # 线程和结果缓存
        self.hunter_search_thread = None
        self.hunter_results = None
        self.quake_full_result = None
        
        # 使用定时器延迟初始化API，减少启动时间
        QTimer.singleShot(1000, self._delayed_init_apis)
    
    def _delayed_init_apis(self):
        """延迟初始化API实例，减少启动时的性能开销"""
        try:
            # 天眼查查询器
            self.tyc_searcher = TianyanchaQuery()
            
            # 爱企查查询器
            self.aiqicha_query = AiqichaQuery()
            
            # 加载爱企查保存的Cookie
            saved_aiqicha_cookie = self.aiqicha_config.get('cookie', '')
            if saved_aiqicha_cookie:
                self.aiqicha_query.aiqicha_cookies.update(self.parse_cookie_string(saved_aiqicha_cookie))
                saved_xunkebao_cookie = self.aiqicha_config.get('xunkebao_cookie', '')
                if saved_xunkebao_cookie:
                    self.aiqicha_query.xunkebao_cookies.update(self.parse_cookie_string(saved_xunkebao_cookie))

            # 加载天眼查保存的Cookie到查询实例
            saved_tyc_cookie = self.tyc_config.get('cookie', '')
            if saved_tyc_cookie:
                try:
                    self.tyc_searcher.tianyancha_cookies.update(self.parse_cookie_string(saved_tyc_cookie))
                    print("✅ 已加载天眼查Cookie到查询实例")
                except Exception as e:
                    print(f"⚠️ 加载天眼查Cookie失败: {e}")
            
            # 初始化Hunter API
            self.init_hunter_api()
            
            print("✅ API实例延迟初始化完成")
        except Exception as e:
            print(f"❌ API实例初始化失败: {e}")
    
    def init_hunter_api(self):
        """初始化Hunter API"""
        try:
            hunter_api_key = self.hunter_config.get('api_key', '')
            if hunter_api_key:
                self.hunter_api = HunterAPI(api_key=hunter_api_key)
                print(f"Hunter API 初始化成功")
            else:
                print("Hunter API Key 未配置")
        except Exception as e:
            print(f"初始化Hunter API失败: {e}")
            self.hunter_api = None
    
    def init_ui_components(self):
        """初始化UI组件"""
        # 主要控件
        self.tab_widget = QTabWidget()
        
        # 数据处理相关控件
        self.template_list = QListWidget()
        self.template_combo = QComboBox()
        self.mapping_tree = QTreeWidget()
        self.source_file_label = QLabel("未选择文件")
        self.target_file_label = QLabel("未选择模板")
        self.headers_list = QListWidget()
        self.result_info_label = QLabel("等待提取...")
        self.result_preview = QTextEdit()
        self.save_file_label = QLabel("保存位置: 未保存")
        self.open_file_btn = QPushButton("📂 打开文件")
        self.extract_file_label = QLabel("未选择文件")
        self.extract_file_btn = QPushButton("🗂️ 选择Excel文件")
        
        # 爱企查相关控件
        self.aiqicha_company_input = QLineEdit()
        self.aiqicha_status_label = QLabel("等待查询...")
        self.aiqicha_result_text = QTextEdit()
        self.aiqicha_save_label = QLabel("保存位置: 未保存")
        self.aiqicha_export_btn = QPushButton("💾 导出结果")
        self.aiqicha_open_btn = QPushButton("📂 打开结果文件")
        self.aiqicha_debug_checkbox = QCheckBox("调试模式")
        
        # 文件路径属性
        self.current_file = None
        self.current_headers = []
        self.current_data = None
        self.source_file = None
        self.target_file = None
        self.extracted_file_path = None
    
    def setup_ui(self):
        """设置主界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题区域
        title_widget = self.create_title_section()
        main_layout.addWidget(title_widget)
        
        # 主要内容区域
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 使用延迟加载模块，减少启动时间
        # 首先只加载数据处理标签页，其他标签页延迟加载
        self.create_data_processing_tab()
        
        # 使用定时器延迟加载其他标签页
        QTimer.singleShot(500, self._delayed_load_tabs)
    
    def _delayed_load_tabs(self):
        """延迟加载其他标签页，减少启动时间"""
        try:
            # 创建信息收集标签页
            self.create_information_collection_tab()
            # 创建文档处理标签页
            self.create_document_processing_tab()
            # 创建江湖救急标签页
            self.create_emergency_tools_tab()
            print("✅ 延迟加载标签页完成")
        except Exception as e:
            print(f"❌ 延迟加载标签页失败: {e}")
    
    def create_title_section(self):
        """创建标题区域"""
        title_widget = QWidget()
        title_layout = QVBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)  # 减少边距
        
        # 创建顶部布局，包含窗口控制按钮和主题切换按钮
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)  # 减少边距
        title_layout.addLayout(top_layout)
        
        # 添加应用图标和标题（左对齐）
        app_title_layout = QHBoxLayout()
        app_icon = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "1.ico")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            app_icon.setPixmap(pixmap)
        app_title = QLabel("koi")
        app_title.setProperty("class", "window-title")
        app_title_layout.addWidget(app_icon)
        app_title_layout.addWidget(app_title)
        app_title_layout.addStretch(1)
        top_layout.addLayout(app_title_layout)
        
        # 添加一个占位标签，用于推动按钮到右侧
        top_layout.addStretch(1)  # 添加弹性空间
        
        # 添加窗口控制按钮
        window_controls = QHBoxLayout()
        window_controls.setSpacing(8)
        
        # 添加暗黑模式切换按钮
        self.theme_toggle_btn = QPushButton()
        self.update_theme_button_text()
        self.theme_toggle_btn.setFixedSize(30, 30)  # 调整按钮大小
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        self.theme_toggle_btn.setObjectName("themeButton")
        window_controls.addWidget(self.theme_toggle_btn)
        
        # 最小化按钮
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setToolTip("最小化窗口")
        self.min_btn.clicked.connect(self.showMinimized)
        self.min_btn.setObjectName("windowButton")
        window_controls.addWidget(self.min_btn)
        
        # 最大化/还原按钮
        self.max_btn = QPushButton("□")
        self.max_btn.setFixedSize(30, 30)
        self.max_btn.setToolTip("最大化窗口")
        self.max_btn.clicked.connect(self.toggle_maximize)
        self.max_btn.setObjectName("windowButton")
        window_controls.addWidget(self.max_btn)
        
        # 关闭按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setToolTip("关闭程序")
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setObjectName("windowButton")
        window_controls.addWidget(self.close_btn)
        
        # 初始化窗口控制按钮样式
        self.update_window_control_buttons()
        
        top_layout.addLayout(window_controls)
        
        # 主标题和副标题的中央布局
        center_layout = QVBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addLayout(center_layout)
        
        # 主标题
        title_label = QLabel("🚀 koi")
        title_label.setProperty("class", "title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(title_label)
        
        # 副标题
        subtitle_label = QLabel("57qv6I+c54uX572i5LqG | by lan1oc")
        subtitle_label.setProperty("class", "subtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(subtitle_label)
        
        return title_widget
        
    def update_theme_button_text(self):
        """更新主题切换按钮文本"""
        if self.dark_mode:
            self.theme_toggle_btn.setText("☀")  # 太阳图标表示切换到亮色模式
            self.theme_toggle_btn.setToolTip("切换到亮色模式")
        else:
            self.theme_toggle_btn.setText("☾")  # 月亮图标表示切换到暗黑模式
            self.theme_toggle_btn.setToolTip("切换到暗黑模式")
    
    def update_window_control_buttons(self):
        """更新窗口控制按钮的样式"""
        if self.dark_mode:
            # 暗色模式：使用明亮的白色，添加悬停效果
            button_style = """
                QPushButton {
                    color: #ffffff;
                    font-weight: bold;
                    font-size: 16px;
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(187, 134, 252, 0.3);
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background-color: rgba(187, 134, 252, 0.5);
                    color: #ffffff;
                }
            """
        else:
            # 亮色模式：使用深色，添加悬停效果
            button_style = """
                QPushButton {
                    color: #343a40;
                    font-weight: bold;
                    font-size: 16px;
                    background-color: transparent;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(0, 123, 255, 0.1);
                    color: #007bff;
                }
                QPushButton:pressed {
                    background-color: rgba(0, 123, 255, 0.2);
                    color: #0056b3;
                }
            """
        
        # 更新所有窗口控制按钮的样式
        self.min_btn.setStyleSheet(button_style)
        self.max_btn.setStyleSheet(button_style)
        self.close_btn.setStyleSheet(button_style)
        self.theme_toggle_btn.setStyleSheet(button_style)

    
    def toggle_theme(self):
        """切换主题"""
        # 使用ThemeManager切换主题
        self.dark_mode = self.theme_manager.toggle_dark_mode()
        
        # 更新按钮文本 - 这是必须立即更新的UI元素
        self.update_theme_button_text()
        
        # 更新窗口控制按钮的颜色
        self.update_window_control_buttons()
        
        # 更新状态栏消息
        mode_name = "暗黑模式" if self.dark_mode else "亮色模式"
        self.statusBar().showMessage(f"已切换到{mode_name}")
        
        # 优化：使用更长的延迟时间异步保存配置，减少主题切换过程中的IO操作
        # 延迟更新配置，避免在主题切换过程中进行IO操作
        def delayed_config_save():
            self.config['ui_settings']['dark_mode'] = self.dark_mode
            self.config_manager.save_config(self.config)
        
        # 使用更长的延迟时间，确保主题切换动画完成后再保存配置
        QTimer.singleShot(500, delayed_config_save)
        
        # 不再手动刷新任何UI元素，完全依赖ThemeManager的刷新机制
        # ThemeManager已经处理了样式应用和窗口刷新
    
    def toggle_maximize(self):
        """切换最大化/还原窗口"""
        # 使用窗口状态标志来跟踪目标状态，而不是依赖isMaximized()
        if not hasattr(self, '_target_maximized'):
            self._target_maximized = False
        
        # 切换目标状态
        self._target_maximized = not self._target_maximized
        
        if self._target_maximized:
            # 目标是最大化
            self.max_btn.setText("❐")
            self.max_btn.setToolTip("还原窗口大小")
            self.showMaximized()
        else:
            # 目标是还原
            self.max_btn.setText("□")
            self.max_btn.setToolTip("最大化窗口")
            self.showNormal()
        
        # 强制更新按钮显示
        self.max_btn.update()
        QApplication.processEvents()
    
    def _update_maximize_button(self):
        """更新最大化/还原按钮状态"""
        is_maximized = self.isMaximized()
        
        # 保持原有样式，只更新文本和提示
        if is_maximized:
            self.max_btn.setText("❐")
            self.max_btn.setToolTip("还原窗口大小")
        else:
            self.max_btn.setText("□")
            self.max_btn.setToolTip("最大化窗口")
        
        # 强制更新按钮
        self.max_btn.update()
        # 强制处理事件，确保UI更新
        QApplication.processEvents()
            
    def changeEvent(self, event):
        """处理窗口状态变化事件"""
        # 调用父类方法处理其他事件
        super().changeEvent(event)
        
        # 处理窗口状态变化事件（仅处理非用户点击触发的状态变化）
        if event.type() == QEvent.Type.WindowStateChange:
            # 强制更新UI
            QApplication.processEvents()
    
    def mousePressEvent(self, event):
        """鼠标按下事件，用于实现窗口拖动"""
        # 只在标题栏区域允许拖动，减少不必要的事件处理
        if event.button() == Qt.MouseButton.LeftButton:
            # 获取鼠标位置
            pos = event.position().toPoint()
            # 检查是否在标题栏区域内
            if pos.y() <= 50:  # 假设标题栏高度为50像素
                self.dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件，用于实现窗口拖动"""
        # 只有在拖动状态下才处理移动事件，减少不必要的计算
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragging:
            # 使用QTimer延迟更新窗口位置，减少频繁重绘
            if not hasattr(self, "_move_timer"):
                self._move_timer = QTimer(self)
                self._move_timer.setSingleShot(True)
                self._move_timer.timeout.connect(self._do_move)
                self._pending_move_pos = None
            
            self._pending_move_pos = event.globalPosition().toPoint() - self.drag_position
            if not self._move_timer.isActive():
                self._move_timer.start(5)  # 5毫秒的延迟，平衡响应性和性能
            
            event.accept()
    
    def _do_move(self):
        """执行窗口移动，由定时器触发"""
        if self._pending_move_pos is not None:
            self.move(self._pending_move_pos)
            self._pending_move_pos = None
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件，用于实现窗口拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            # 清除待处理的移动位置
            if hasattr(self, "_move_timer") and self._move_timer.isActive():
                self._move_timer.stop()
                if self._pending_move_pos is not None:
                    self.move(self._pending_move_pos)
                    self._pending_move_pos = None
            event.accept()
    
    def create_data_processing_tab(self):
        """创建数据处理主标签页"""
        try:
            # 使用模块化的数据处理功能
            from modules.data_processing.integration_helper import integrate_data_processing_to_main_window
            
            # 集成数据处理模块到主窗口
            success = integrate_data_processing_to_main_window(self)
            
            if success:
                print("✅ 模块化数据处理组件集成成功")
            else:
                print("❌ 模块化数据处理组件集成失败")
                
        except Exception as e:
            print(f"❌ 集成数据处理模块失败: {e}")
    
    def create_information_collection_tab(self):
        """创建信息收集主标签页"""
        try:
            # 使用模块化的信息收集功能
            from modules.Information_Gathering.integration_helper import integrate_information_gathering_to_main_window
            
            # 集成信息收集模块到主窗口
            success = integrate_information_gathering_to_main_window(self)
            
            if success:
                print("✅ 模块化信息收集组件集成成功")
            else:
                print("❌ 模块化信息收集组件集成失败")
                
        except Exception as e:
            print(f"❌ 集成信息收集模块失败: {e}")
    
    def create_emergency_tools_tab(self):
        """创建江湖救急主标签页"""
        try:
            # 创建江湖救急主标签页
            emergency_widget = QWidget()
            emergency_layout = QVBoxLayout(emergency_widget)
            emergency_layout.setContentsMargins(10, 10, 10, 10)
            
            # 创建江湖救急子标签页
            emergency_tabs = QTabWidget()
            emergency_layout.addWidget(emergency_tabs)
            
            # 使用模块化的周报生成功能
            from modules.Emergency_help.weekly_report.integration_helper import integrate_weekly_report_to_emergency_help
            self.weekly_report_ui = integrate_weekly_report_to_emergency_help(emergency_tabs)
            
            # 将江湖救急主标签页添加到主标签页控件
            self.tab_widget.addTab(emergency_widget, "🚨 江湖救急")
            
            print("✅ 模块化江湖救急组件集成成功")
            
        except Exception as e:
            print(f"❌ 集成江湖救急模块失败: {e}")
    
    def parse_cookie_string(self, cookie_string):
        """解析Cookie字符串"""
        cookies = {}
        if cookie_string:
            for item in cookie_string.split(';'):
                if '=' in item:
                    key, value = item.strip().split('=', 1)
                    cookies[key] = value
        return cookies
    
    def setup_input_focus_effects(self):
        """设置输入框焦点效果"""
        # 使用延迟初始化，减少启动时的性能开销
        QTimer.singleShot(500, self._delayed_setup_focus_effects)
    
    def _delayed_setup_focus_effects(self):
        """延迟设置焦点效果，减少启动时的性能开销"""
        # 为所有输入框添加焦点效果，但限制数量以提高性能
        for widget in self.findChildren(QLineEdit):
            widget.installEventFilter(self)
        
        for widget in self.findChildren(QTextEdit):
            widget.installEventFilter(self)
        
        # 预创建阴影效果对象，避免频繁创建和销毁
        self._focus_shadow = QGraphicsDropShadowEffect()
        self._focus_shadow.setBlurRadius(15)
        self._focus_shadow.setOffset(0, 0)
        self._focus_shadow.setColor(QColor(52, 152, 219, 100))
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理焦点事件"""
        # 只处理输入框的焦点事件，减少不必要的处理
        if isinstance(obj, (QLineEdit, QTextEdit)):
            if event.type() == QEvent.Type.FocusIn:
                self.on_focus_in(obj)
            elif event.type() == QEvent.Type.FocusOut:
                self.on_focus_out(obj)
        
        return super().eventFilter(obj, event)
    
    def on_focus_in(self, widget):
        """焦点进入时添加蓝色阴影效果"""
        if widget is None or not hasattr(self, '_focus_shadow'):
            return
        
        try:
            # 使用预创建的阴影效果对象，避免频繁创建和销毁
            widget.setGraphicsEffect(self._focus_shadow)
        except Exception as e:
            # 使用pass而不是print，减少日志输出开销
            pass
    
    def on_focus_out(self, widget):
        """焦点离开时恢复原始阴影或移除阴影"""
        if widget is None:
            return
        
        try:
            # 移除焦点阴影
            widget.setGraphicsEffect(None)
        except Exception as e:
            # 使用pass而不是print，减少日志输出开销
            pass
    
    def apply_theme_to_all_modules(self):
        """将当前主题应用到所有子模块，包括深层嵌套的组件"""
        # 使用ThemeManager应用主题，不再需要递归处理
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        theme_manager.set_dark_mode(self.dark_mode)
        
        # 刷新所有标签页
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab:
                tab.update()
                
        # 更新状态栏消息
        mode_name = "暗黑模式" if self.dark_mode else "亮色模式"
        self.statusBar().showMessage(f"已应用{mode_name}")
        
        # 刷新UI以确保样式正确应用
        self.repaint()
     
    def _apply_theme_recursive(self, parent_widget, processed_widgets=None):
        """Recursively apply theme to all child widgets
        
        Note: This method is deprecated, now using ThemeManager for unified style management
        This method is kept only for backward compatibility
        """
        # 初始化已处理部件集合，防止无限递归
        if processed_widgets is None:
            processed_widgets = set()
            
        # 如果部件已处理过，则跳过
        if parent_widget in processed_widgets:
            return
            
        # 标记当前部件为已处理
        processed_widgets.add(parent_widget)
        
        # 不再直接应用样式，让ThemeManager处理
        # 以下代码已弃用，保留注释以便理解历史实现
        
        # 遍历所有子部件并应用主题
        for child in parent_widget.findChildren(QWidget):
            if child not in processed_widgets:
                self._apply_theme_recursive(child, processed_widgets)

        # else:
        #     # 应用亮色模式样式
        #     parent_widget.setStyleSheet("")
        
        # 处理当前部件的焦点阴影
        try:
            # 移除焦点阴影
            parent_widget.setGraphicsEffect(None)
            
            # 如果是按钮，恢复原始阴影
            if isinstance(parent_widget, QPushButton):
                add_shadow_effect(parent_widget, blur_radius=8, offset_x=2, offset_y=2)
        except Exception as e:
            print(f"处理部件阴影效果失败: {e}")
        
        # 递归处理所有直接子部件
        for child in parent_widget.findChildren(QWidget):
            if child not in processed_widgets:
                self._apply_theme_recursive(child, processed_widgets)
    
    # 配置管理方法
    def load_unified_config(self):
        """加载统一配置文件（兼容方法）"""
        return self.config_manager.load_config()
    
    def save_unified_config(self, config=None):
        """保存统一配置文件（兼容方法）"""
        if config is None:
            config = self.config
        self.config_manager.save_config(config)
    
    def save_hunter_config(self):
        """保存Hunter配置"""
        self.config['hunter']['api_key'] = self.hunter_config.get('api_key', '')
        self.config['hunter']['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.config_manager.save_config(self.config)
    
    def save_quake_config(self):
        """保存Quake配置"""
        self.config['quake']['api_key'] = self.quake_config.get('api_key', '')
        self.config['quake']['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.config_manager.save_config(self.config)
    
    def save_fofa_config(self):
        """保存FOFA配置"""
        self.config['fofa']['email'] = self.fofa_config.get('email', '')
        self.config['fofa']['api_key'] = self.fofa_config.get('api_key', '')
        self.config['fofa']['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.config_manager.save_config(self.config)
    
    def save_tyc_config(self):
        """保存天眼查配置"""
        self.config['tyc']['cookie'] = self.tyc_config.get('cookie', '')
        self.config['tyc']['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.config_manager.save_config(self.config)
    
    def create_document_processing_tab(self):
        """创建文档处理标签页"""
        try:
            from modules.Document_Processing.document_processing_ui import DocumentProcessingUI
            
            # 创建文档处理UI组件
            document_processing_widget = DocumentProcessingUI(self)
            
            # 添加到主标签页
            self.tab_widget.addTab(document_processing_widget, "📄 文档处理")
            
            print("✅ 文档处理组件集成成功")
            
        except Exception as e:
            print(f"❌ 创建文档处理标签页失败: {e}")
            # 创建错误提示页面
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"文档处理模块加载失败：{str(e)}")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_layout.addWidget(error_label)
            self.tab_widget.addTab(error_widget, "📄 文档处理")
    
    # 兼容方法（保持向后兼容）
    def load_templates(self):
        """加载模板（兼容方法）"""
        return []
    
    # 线程管理方法
    def register_thread(self, thread):
        """注册线程到管理列表"""
        if thread not in self.active_threads:
            self.active_threads.append(thread)
            # 当线程完成时自动从列表中移除
            thread.finished.connect(lambda: self.unregister_thread(thread))
    
    def unregister_thread(self, thread):
        """从管理列表中移除线程"""
        if thread in self.active_threads:
            self.active_threads.remove(thread)
    
    def stop_all_threads(self):
        """停止所有活动线程"""
        for thread in self.active_threads[:]:  # 使用副本避免在迭代时修改列表
            try:
                if thread.isRunning():
                    # 尝试优雅地停止线程
                    if hasattr(thread, 'stop'):
                        thread.stop()
                    
                    # 请求线程中断
                    thread.requestInterruption()
                    
                    # 等待线程结束，最多等待3秒
                    if not thread.wait(3000):
                        # 如果线程没有在3秒内结束，强制终止
                        thread.terminate()
                        thread.wait(1000)  # 再等待1秒确保终止
                        
            except Exception as e:
                print(f"停止线程时出错: {e}")
        
        # 清空线程列表
        self.active_threads.clear()
    
    def closeEvent(self, event):
        """窗口关闭事件处理"""
        try:
            # 停止所有活动线程
            self.stop_all_threads()
            
            # 保存配置
            if hasattr(self, 'config_manager'):
                try:
                    # 重新加载最新配置，避免覆盖其他模块的更新（如通报编号）
                    latest_config = self.config_manager.load_config()
                    
                    # 只保存UI相关的配置更改，保留其他模块的更新
                    ui_config = {
                        'hunter': self.config.get('hunter', {}),
                        'quake': self.config.get('quake', {}),
                        'fofa': self.config.get('fofa', {}),
                        'tyc': self.config.get('tyc', {}),
                        'aiqicha': self.config.get('aiqicha', {}),
                        'ui_settings': self.config.get('ui_settings', {}),
                        'app': self.config.get('app', {})
                    }
                    
                    # 合并策略：对 tyc/aiqicha 节，避免旧内存 cookie 覆盖磁盘上的新值（按时间戳择优）
                    def merge_preserve_cookie(section_name: str):
                        mem_sec = ui_config.get(section_name, {}) or {}
                        disk_sec = latest_config.get(section_name, {}) or {}
                        merged = dict(disk_sec)

                        mem_cookie = str(mem_sec.get('cookie', '') or '').strip()
                        disk_cookie = str(disk_sec.get('cookie', '') or '').strip()
                        mem_ts = str(mem_sec.get('last_updated', '') or '').strip()
                        disk_ts = str(disk_sec.get('last_updated', '') or '').strip()

                        def parse_ts(ts: str):
                            try:
                                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if ts else None
                            except Exception:
                                return None

                        mem_dt = parse_ts(mem_ts)
                        disk_dt = parse_ts(disk_ts)

                        # 只有在内存 cookie 非空且更新更“新”的情况下，才覆盖磁盘
                        if mem_cookie:
                            if mem_cookie != disk_cookie:
                                if mem_dt and (not disk_dt or mem_dt >= disk_dt):
                                    merged['cookie'] = mem_cookie
                                    merged['last_updated'] = mem_ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                else:
                                    # 内存较旧或无时间戳，保留磁盘 cookie
                                    merged['cookie'] = disk_cookie
                                    if disk_ts:
                                        merged['last_updated'] = disk_ts
                            else:
                                # 值相同，保持磁盘即可，但补齐时间戳
                                if disk_ts:
                                    merged['last_updated'] = disk_ts
                                elif mem_ts:
                                    merged['last_updated'] = mem_ts
                        else:
                            # 内存 cookie 为空，保留磁盘
                            if disk_ts:
                                merged['last_updated'] = disk_ts

                        # 合并其它键（非空覆盖）
                        for k, v in mem_sec.items():
                            if k == 'cookie' or k == 'last_updated':
                                continue
                            if isinstance(v, str):
                                if v.strip():
                                    merged[k] = v
                            else:
                                merged[k] = v

                        latest_config[section_name] = merged
                    
                    # 针对 cookie 的两个平台采用安全合并
                    merge_preserve_cookie('tyc')
                    merge_preserve_cookie('aiqicha')
                    
                    # 其它节采用直接覆盖（保持原有逻辑）
                    for key in ['hunter', 'quake', 'fofa', 'ui_settings', 'app']:
                        value = ui_config.get(key)
                        if value:
                            latest_config[key] = value
                    
                    self.config_manager.save_config(latest_config)
                except Exception as e:
                    print(f"保存配置时出错: {e}")
            
            # 清理资源
            if hasattr(self, 'theme_manager'):
                del self.theme_manager
            
            # 接受关闭事件
            event.accept()
            
        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            # 即使出错也要关闭窗口
            event.accept()