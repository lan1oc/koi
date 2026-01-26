#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业查询UI组件
整合天眼查和爱企查功能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox, QPushButton,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSpinBox,
    QRadioButton, QFileDialog, QMessageBox, QScrollArea, QGridLayout,
    QListWidget, QProgressBar, QPlainTextEdit, QApplication, QStackedWidget
)
from modules.ui.message_box_helper import show_warning, show_information, show_critical
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import QFont, QColor, QTextCursor

# 使用相对导入
from .tianyancha_query import TianyanchaQuery
from .aiqicha_query import AiqichaQuery
from .enterprise_info_widget import EnterpriseInfoWidget
from typing import Dict, List, Optional
import logging
import os
import json
import csv
import time
import re
from datetime import datetime


class EnterpriseBatchQueryThread(QThread):
    """企业批量查询线程"""
    progress_updated = Signal(str)
    progress_percentage = Signal(int)
    query_completed = Signal(dict)
    
    def __init__(self, query_engine, companies: List[str], query_type: str):
        super().__init__()
        self.query_engine = query_engine
        self.companies = companies
        self.query_type = query_type  # 'tianyancha' or 'aiqicha'
        self.results = []

    def run(self):
        """执行批量查询并发射进度与完成信号"""
        try:
            progress_re = re.compile(r"第\s*(\d+)\s*/\s*(\d+)\s*家")

            def progress_cb(message: str):
                try:
                    self.progress_updated.emit(message)
                    m = progress_re.search(message)
                    if m:
                        cur = int(m.group(1))
                        total = int(m.group(2)) if int(m.group(2)) > 0 else 1
                        pct = int(cur * 100 / total)
                        self.progress_percentage.emit(min(max(pct, 0), 100))
                except Exception:
                    # 忽略进度解析中的异常，保持线程健壮
                    pass

            # 执行批量查询（两者接口均提供 batch_search）
            result = self.query_engine.batch_search(self.companies, progress_callback=progress_cb)

            # 保证完成时显示100%
            self.progress_percentage.emit(100)

            # 发射完成信号
            if isinstance(result, dict):
                self.query_completed.emit(result)
            else:
                self.query_completed.emit({
                    'success': False,
                    'message': '批量查询结果类型异常',
                    'results': [],
                    'error': f'type={type(result).__name__}'
                })
        except Exception as e:
            # 异常情况下也发射完成，避免线程卡死
            self.query_completed.emit({
                'success': False,
                'message': f'批量查询异常: {str(e)}',
                'results': [],
                'error': str(e)
            })


class EnterpriseSingleQueryThread(QThread):
    """企业单个查询线程（天眼查）"""
    progress_updated = Signal(str)
    progress_step = Signal(int)
    partial_result = Signal(dict)
    query_completed = Signal(dict)

    def __init__(self, query_engine, company_name: str, no_cookie_mode: bool):
        super().__init__()
        self.query_engine = query_engine
        self.company_name = company_name
        self.no_cookie_mode = no_cookie_mode

    def run(self):
        step_tracker = {'search': 0, 'icp': 1, 'app': 2, 'wechat': 3}

        def status_cb(msg: str):
            self.progress_updated.emit(msg)
            try:
                if '第一步' in msg or '搜索' in msg:
                    self.progress_step.emit(step_tracker['search'])
                elif '第二步' in msg or 'ICP' in msg:
                    self.progress_step.emit(step_tracker['icp'])
                elif '第三步' in msg or 'APP' in msg:
                    self.progress_step.emit(step_tracker['app'])
                elif '第四步' in msg or '微信公众号' in msg:
                    self.progress_step.emit(step_tracker['wechat'])
            except Exception:
                pass

        def partial_cb(data: dict):
            self.partial_result.emit(data)

        result = self.query_engine.query_company_complete(
            self.company_name,
            status_callback=status_cb,
            no_cookie_mode=self.no_cookie_mode,
            partial_callback=partial_cb
        )
        self.query_completed.emit(result)


class EnterpriseAiqichaSingleQueryThread(QThread):
    """企业单个查询线程（爱企查）"""
    progress_updated = Signal(str)
    progress_step = Signal(int)
    query_completed = Signal(dict)

    def __init__(self, query_engine, company_name: str):
        super().__init__()
        self.query_engine = query_engine
        self.company_name = company_name

    def run(self):
        """执行爱企查单个查询"""
        step_tracker = {
            'search': 0,      # 第一步：搜索企业
            'detail': 1,      # 第二步：企业详情
            'icp': 2,         # 第三步：ICP备案
            'app': 3,         # 第四步：APP信息
            'wechat': 4,      # 第五步：微信公众号
            'enterprise': 5,  # 第六步：企业ID
            'unlock': 6       # 第七步：解锁资源
        }

        def status_cb(msg: str, step=None):
            """状态回调函数"""
            self.progress_updated.emit(msg)
            try:
                # 根据消息内容或步骤参数更新进度
                if step is not None:
                    self.progress_step.emit(step)
                elif '第一步' in msg or '搜索企业' in msg:
                    self.progress_step.emit(step_tracker['search'])
                elif '第二步' in msg or '企业详情' in msg:
                    self.progress_step.emit(step_tracker['detail'])
                elif '第三步' in msg or 'ICP' in msg:
                    self.progress_step.emit(step_tracker['icp'])
                elif '第四步' in msg or 'APP' in msg:
                    self.progress_step.emit(step_tracker['app'])
                elif '第五步' in msg or '微信公众号' in msg:
                    self.progress_step.emit(step_tracker['wechat'])
                elif '第六步' in msg or '企业ID' in msg:
                    self.progress_step.emit(step_tracker['enterprise'])
                elif '第七步' in msg or '解锁' in msg:
                    self.progress_step.emit(step_tracker['unlock'])
            except Exception:
                pass

        try:
            # 执行查询
            result = self.query_engine.query_company_info(
                self.company_name,
                status_callback=status_cb
            )
            
            # 构造返回结果，保持与界面期望的格式一致
            if result and isinstance(result, dict):
                # 检查是否有任何有效数据
                has_data = (
                    result.get('basic_info') or 
                    result.get('industry_info') or 
                    result.get('icp_info') or 
                    result.get('contact_info') or 
                    result.get('app_info') or 
                    result.get('wechat_info')
                )
                
                if has_data:
                    self.query_completed.emit({
                        'success': True,
                        'data': result
                    })
                else:
                    self.query_completed.emit({
                        'success': False,
                        'error': '未找到企业信息或需要更新Cookie'
                    })
            else:
                self.query_completed.emit({
                    'success': False,
                    'error': '查询失败: 未返回有效结果'
                })
        except Exception as e:
            self.query_completed.emit({
                'success': False,
                'error': f'查询异常: {str(e)}'
            })


class EnterpriseQueryUI(QWidget):
    """企业查询UI组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.logger = logging.getLogger(__name__)
        
        # 初始化查询引擎
        self.tianyancha_query = TianyanchaQuery()
        self.aiqicha_query = AiqichaQuery()
        
        # 配置管理与文件监控
        try:
            from modules.config.config_manager import ConfigManager
            self._config_manager = ConfigManager()
            self._config_file_path = self._config_manager.config_file_path
            self._config_watcher = QFileSystemWatcher()
            if self._config_file_path:
                # 先确保路径存在再添加监控
                self._config_watcher.addPath(self._config_file_path)
                # 文件可能在保存时产生多次事件，使用轻微防抖处理
                self._config_watcher.fileChanged.connect(self._on_config_file_changed)
        except Exception as e:
            # 监控失败不阻塞UI，仅记录日志
            self._config_manager = None
            self._config_file_path = None
            self._config_watcher = None
            self.logger.warning(f"初始化配置文件监控失败: {e}")
        
        # 查询线程
        self.batch_query_thread = None
        self.single_query_thread = None
        
        # 结果存储
        self.tianyancha_results = []
        self.aiqicha_results = []

        # 进度更新节流控制，减少频繁重绘导致的闪烁
        self._last_tyc_progress_ts = 0.0
        self._last_aiqicha_progress_ts = 0.0
        self._progress_min_interval_ms = 80  # 80ms 最小更新间隔
        
        self.setup_ui()
        self.setup_connections()
        self.load_debug_config()

    def _scroll_text_to_top(self, text_widget):
        """将结果文本滚动到顶部，便于用户查看标题处信息。"""
        try:
            text_widget.moveCursor(QTextCursor.MoveOperation.Start)
        except Exception:
            pass
        try:
            sb = text_widget.verticalScrollBar()
            if sb is not None:
                sb.setValue(0)
        except Exception:
            pass

        # 启动时从配置文件读取Cookie状态，更新UI标签
        try:
            cfg = None
            if self._config_manager:
                cfg = self._config_manager.load_config()
            else:
                from modules.config.config_manager import ConfigManager
                cfg = ConfigManager().load_config()
            init_cfg = {
                'tianyancha_cookie': cfg.get('tyc', {}).get('cookie', ''),
                'aiqicha_cookie': cfg.get('aiqicha', {}).get('cookie', '')
            }
            self.set_config(init_cfg)
        except Exception as e:
            self.logger.warning(f"初始化Cookie状态失败: {e}")
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        
        # 创建子标签页
        self.tab_widget = QTabWidget()
        
        # 创建天眼查标签页
        self.create_tianyancha_tab()
        
        # 创建爱企查标签页
        self.create_aiqicha_tab()
        
        # 创建分类管理标签页
        try:
            from .classification_manager import ClassificationManagerUI
            self.classification_tab = ClassificationManagerUI()
            self.tab_widget.addTab(self.classification_tab, "🗂️ 分类管理")
        except Exception as e:
            self.logger.error(f"加载分类管理组件失败: {e}")
        
        main_layout.addWidget(self.tab_widget)
    
    def create_tianyancha_tab(self):
        """创建天眼查标签页"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(15)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建内容widget
        content_widget = QWidget()
        main_layout = QHBoxLayout(content_widget)
        main_layout.setSpacing(15)
        
        # 左侧操作区域
        left_widget = self.create_tianyancha_controls()
        left_widget.setMaximumWidth(320)
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_tianyancha_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 0)  # 左侧固定宽度，不伸缩
        main_layout.setStretch(1, 1)  # 右侧占据剩余空间
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "👁️ 天眼查")
    
    def create_tianyancha_controls(self) -> QWidget:
        """创建天眼查控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # Cookie配置区域
        cookie_group = QGroupBox("🍪 Cookie配置")
        cookie_layout = QVBoxLayout(cookie_group)
        
        # Cookie状态显示
        self.tyc_cookie_status = QLabel("Cookie状态: 未配置")
        self.tyc_cookie_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
        cookie_layout.addWidget(self.tyc_cookie_status)
        
        # Cookie更新按钮
        cookie_btn_layout = QHBoxLayout()
        self.tyc_update_cookie_btn = QPushButton("🔄 更新Cookie")
        self.tyc_update_cookie_btn.clicked.connect(self.update_tianyancha_cookie)
        cookie_btn_layout.addWidget(self.tyc_update_cookie_btn)
        

        
        cookie_layout.addLayout(cookie_btn_layout)
        layout.addWidget(cookie_group)
        
        # 查询配置区域
        query_group = QGroupBox("🔍 查询配置")
        query_layout = QVBoxLayout(query_group)
        
        # 调试输出选项
        debug_layout = QHBoxLayout()
        self.tyc_debug_checkbox = QCheckBox("🐛 启用调试输出")
        self.tyc_debug_checkbox.setToolTip("勾选后将保存查询响应文件到debug目录")
        self.tyc_debug_checkbox.stateChanged.connect(self.on_debug_option_changed)
        debug_layout.addWidget(self.tyc_debug_checkbox)
        debug_layout.addStretch()
        query_layout.addLayout(debug_layout)
        
        # 无cookie查询选项
        no_cookie_layout = QHBoxLayout()
        self.tyc_no_cookie_checkbox = QCheckBox("🚫 无Cookie查询模式")
        self.tyc_no_cookie_checkbox.setToolTip("勾选后将跳过ICP备案查询，避免因Cookie问题导致的查询失败")
        no_cookie_layout.addWidget(self.tyc_no_cookie_checkbox)
        no_cookie_layout.addStretch()
        query_layout.addLayout(no_cookie_layout)

        # 静默验证浏览器选项
        silent_layout = QHBoxLayout()
        self.tyc_silent_checkbox = QCheckBox("🔕 静默验证浏览器")
        self.tyc_silent_checkbox.setToolTip("验证浏览器不抢焦点、不最大化，减少界面遮挡")
        self.tyc_silent_checkbox.stateChanged.connect(self.on_silent_option_changed)
        silent_layout.addWidget(self.tyc_silent_checkbox)
        silent_layout.addStretch()
        query_layout.addLayout(silent_layout)
        
        # 查询模式选择
        mode_layout = QHBoxLayout()
        self.tyc_single_radio = QRadioButton("单个查询")
        self.tyc_single_radio.setChecked(True)
        self.tyc_batch_radio = QRadioButton("批量查询")
        
        mode_layout.addWidget(self.tyc_single_radio)
        mode_layout.addWidget(self.tyc_batch_radio)
        mode_layout.addStretch()
        query_layout.addLayout(mode_layout)
        
        # 单个查询区域
        self.tyc_single_widget = QWidget()
        single_layout = QVBoxLayout(self.tyc_single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        
        company_layout = QHBoxLayout()
        company_layout.addWidget(QLabel("公司名称:"))
        self.tyc_company_input = QLineEdit()
        self.tyc_company_input.setPlaceholderText("请输入公司名称...")
        company_layout.addWidget(self.tyc_company_input)
        single_layout.addLayout(company_layout)
        
        query_layout.addWidget(self.tyc_single_widget)
        
        # 批量查询区域
        self.tyc_batch_widget = QWidget()
        batch_layout = QVBoxLayout(self.tyc_batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        
        file_layout = QHBoxLayout()
        self.tyc_file_btn = QPushButton("📂 选择公司名单文件")
        self.tyc_file_btn.clicked.connect(self.select_tyc_batch_file)
        file_layout.addWidget(self.tyc_file_btn)
        
        self.tyc_file_label = QLabel("未选择文件")
        self.tyc_file_label.setStyleSheet("color: #7f8c8d;")
        file_layout.addWidget(self.tyc_file_label)
        batch_layout.addLayout(file_layout)
        
        self.tyc_batch_widget.setVisible(False)
        query_layout.addWidget(self.tyc_batch_widget)
        
        layout.addWidget(query_group)
        
        # 操作按钮
        self.tyc_search_btn = QPushButton("🚀 开始查询")
        self.tyc_search_btn.clicked.connect(self.start_tianyancha_query)
        layout.addWidget(self.tyc_search_btn)
        
        # 导出按钮
        export_layout = QHBoxLayout()
        self.tyc_export_btn = QPushButton("💾 导出结果")
        self.tyc_export_btn.clicked.connect(self.export_tianyancha_results)
        self.tyc_export_btn.setEnabled(False)
        export_layout.addWidget(self.tyc_export_btn)
        
        self.tyc_clear_btn = QPushButton("🗑️ 清空结果")
        self.tyc_clear_btn.clicked.connect(self.clear_tianyancha_results)
        export_layout.addWidget(self.tyc_clear_btn)
        
        layout.addLayout(export_layout)
        layout.addStretch()
        
        return widget
    
    def create_tianyancha_results(self) -> QWidget:
        """创建天眼查结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.tyc_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.tyc_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.tyc_status_label.style().polish(self.tyc_status_label)
        layout.addWidget(self.tyc_status_label)
        
        # 进度条
        self.tyc_progress_bar = QProgressBar()
        self.tyc_progress_bar.setVisible(False)
        self.tyc_progress_bar.setFormat("查询进度: %p%")
        self.tyc_progress_bar.setTextVisible(True)
        # 设置进度条样式属性，确保在暗色模式下可见
        self.tyc_progress_bar.setProperty("class", "query-progress-bar")
        layout.addWidget(self.tyc_progress_bar)
        
        # 结果显示
        result_label = QLabel("📊 查询结果")
        # 移除硬编码样式，使用全局样式
        result_label.setProperty("class", "result-label")
        layout.addWidget(result_label)
        
        # 结果显示堆栈
        self.tyc_result_stack = QStackedWidget()
        
        # 1. 文本显示 (用于错误信息或日志)
        self.tyc_result_text = QTextEdit()
        self.tyc_result_text.setReadOnly(True)
        self.tyc_result_stack.addWidget(self.tyc_result_text)
        
        # 2. 美观展示 (用于结构化数据)
        self.tyc_info_widget = EnterpriseInfoWidget()
        self.tyc_result_stack.addWidget(self.tyc_info_widget)
        
        layout.addWidget(self.tyc_result_stack)
        
        return widget
    
    def create_aiqicha_tab(self):
        """创建爱企查标签页"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(15)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建内容widget
        content_widget = QWidget()
        main_layout = QHBoxLayout(content_widget)
        main_layout.setSpacing(15)
        
        # 左侧操作区域
        left_widget = self.create_aiqicha_controls()
        left_widget.setMaximumWidth(320)
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_aiqicha_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 0)  # 左侧固定宽度
        main_layout.setStretch(1, 1)  # 右侧占据剩余空间
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "🔍 爱企查")
    
    def create_aiqicha_controls(self) -> QWidget:
        """创建爱企查控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # Cookie配置区域
        cookie_group = QGroupBox("🍪 Cookie配置")
        cookie_layout = QVBoxLayout(cookie_group)
        
        # Cookie状态显示
        self.aiqicha_cookie_status = QLabel("Cookie状态: 未配置")
        self.aiqicha_cookie_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
        cookie_layout.addWidget(self.aiqicha_cookie_status)
        
        # Cookie更新按钮
        cookie_btn_layout = QHBoxLayout()
        self.aiqicha_update_cookie_btn = QPushButton("🔄 更新Cookie")
        self.aiqicha_update_cookie_btn.clicked.connect(self.update_aiqicha_cookie)
        cookie_btn_layout.addWidget(self.aiqicha_update_cookie_btn)
        

        
        cookie_layout.addLayout(cookie_btn_layout)
        layout.addWidget(cookie_group)
        
        # 查询配置区域
        query_group = QGroupBox("🔍 查询配置")
        query_layout = QVBoxLayout(query_group)

        debug_layout = QHBoxLayout()
        self.aiqicha_debug_checkbox = QCheckBox("🐛 启用调试输出")
        self.aiqicha_debug_checkbox.setToolTip("勾选后将保存查询响应文件到debug目录")
        self.aiqicha_debug_checkbox.stateChanged.connect(self.on_aiqicha_debug_option_changed)
        debug_layout.addWidget(self.aiqicha_debug_checkbox)
        debug_layout.addStretch()
        query_layout.addLayout(debug_layout)
        
        # 查询模式选择
        mode_layout = QHBoxLayout()
        self.aiqicha_single_radio = QRadioButton("单个查询")
        self.aiqicha_single_radio.setChecked(True)
        self.aiqicha_batch_radio = QRadioButton("批量查询")
        
        mode_layout.addWidget(self.aiqicha_single_radio)
        mode_layout.addWidget(self.aiqicha_batch_radio)
        mode_layout.addStretch()
        query_layout.addLayout(mode_layout)
        
        # 单个查询区域
        self.aiqicha_single_widget = QWidget()
        single_layout = QVBoxLayout(self.aiqicha_single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        
        company_layout = QHBoxLayout()
        company_layout.addWidget(QLabel("公司名称:"))
        self.aiqicha_company_input = QLineEdit()
        self.aiqicha_company_input.setPlaceholderText("请输入公司名称...")
        company_layout.addWidget(self.aiqicha_company_input)
        single_layout.addLayout(company_layout)
        
        query_layout.addWidget(self.aiqicha_single_widget)
        
        # 批量查询区域
        self.aiqicha_batch_widget = QWidget()
        batch_layout = QVBoxLayout(self.aiqicha_batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        
        file_layout = QHBoxLayout()
        self.aiqicha_file_btn = QPushButton("📂 选择公司名单文件")
        self.aiqicha_file_btn.clicked.connect(self.select_aiqicha_batch_file)
        file_layout.addWidget(self.aiqicha_file_btn)
        
        self.aiqicha_file_label = QLabel("未选择文件")
        self.aiqicha_file_label.setStyleSheet("color: #7f8c8d;")
        file_layout.addWidget(self.aiqicha_file_label)
        batch_layout.addLayout(file_layout)
        
        self.aiqicha_batch_widget.setVisible(False)
        query_layout.addWidget(self.aiqicha_batch_widget)
        
        layout.addWidget(query_group)
        
        # 操作按钮
        self.aiqicha_search_btn = QPushButton("🚀 开始查询")
        self.aiqicha_search_btn.clicked.connect(self.start_aiqicha_query)
        layout.addWidget(self.aiqicha_search_btn)
        
        # 导出按钮
        export_layout = QHBoxLayout()
        self.aiqicha_export_btn = QPushButton("💾 导出结果")
        self.aiqicha_export_btn.clicked.connect(self.export_aiqicha_results)
        self.aiqicha_export_btn.setEnabled(False)
        export_layout.addWidget(self.aiqicha_export_btn)
        
        self.aiqicha_clear_btn = QPushButton("🗑️ 清空结果")
        self.aiqicha_clear_btn.clicked.connect(self.clear_aiqicha_results)
        export_layout.addWidget(self.aiqicha_clear_btn)
        
        layout.addLayout(export_layout)
        layout.addStretch()
        
        return widget
    
    def create_aiqicha_results(self) -> QWidget:
        """创建爱企查结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.aiqicha_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.aiqicha_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.aiqicha_status_label.style().polish(self.aiqicha_status_label)
        layout.addWidget(self.aiqicha_status_label)
        
        # 进度条
        self.aiqicha_progress_bar = QProgressBar()
        self.aiqicha_progress_bar.setVisible(False)
        self.aiqicha_progress_bar.setFormat("查询进度: %p%")
        self.aiqicha_progress_bar.setTextVisible(True)
        # 设置进度条样式属性，确保在暗色模式下可见
        self.aiqicha_progress_bar.setProperty("class", "query-progress-bar")
        layout.addWidget(self.aiqicha_progress_bar)
        
        # 结果显示
        result_label = QLabel("📊 查询结果")
        # 移除硬编码样式，使用全局样式
        result_label.setProperty("class", "result-label")
        layout.addWidget(result_label)
        
        # 结果显示堆栈
        self.aiqicha_result_stack = QStackedWidget()
        
        # 1. 文本显示
        self.aiqicha_result_text = QTextEdit()
        self.aiqicha_result_text.setReadOnly(True)
        self.aiqicha_result_stack.addWidget(self.aiqicha_result_text)
        
        # 2. 美观展示
        self.aiqicha_info_widget = EnterpriseInfoWidget()
        self.aiqicha_result_stack.addWidget(self.aiqicha_info_widget)
        
        layout.addWidget(self.aiqicha_result_stack)
        
        return widget
    
    def setup_connections(self):
        """设置信号连接"""
        # 天眼查模式切换
        self.tyc_single_radio.toggled.connect(self.toggle_tyc_query_mode)
        self.tyc_batch_radio.toggled.connect(self.toggle_tyc_query_mode)
        
        # 爱企查模式切换
        self.aiqicha_single_radio.toggled.connect(self.toggle_aiqicha_query_mode)
        self.aiqicha_batch_radio.toggled.connect(self.toggle_aiqicha_query_mode)
    
    def toggle_tyc_query_mode(self):
        """切换天眼查查询模式"""
        is_single = self.tyc_single_radio.isChecked()
        self.tyc_single_widget.setVisible(is_single)
        self.tyc_batch_widget.setVisible(not is_single)
    
    def toggle_aiqicha_query_mode(self):
        """切换爱企查查询模式"""
        is_single = self.aiqicha_single_radio.isChecked()
        self.aiqicha_single_widget.setVisible(is_single)
        self.aiqicha_batch_widget.setVisible(not is_single)
    
    def select_tyc_batch_file(self):
        """选择天眼查批量查询文件"""
        from modules.ui.file_dialog_helper import get_open_file_name
        file_path, _ = get_open_file_name(
            self, "选择公司名单文件", "",
            "Text files (*.txt);;Excel files (*.xlsx *.xls);;All files (*.*)"
        )
        
        if file_path:
            self.tyc_batch_file_path = file_path
            self.tyc_file_label.setText(os.path.basename(file_path))
            self.tyc_file_label.setStyleSheet("color: #27ae60; font-weight: bold;")
    
    def select_aiqicha_batch_file(self):
        """选择爱企查批量查询文件"""
        from modules.ui.file_dialog_helper import get_open_file_name
        file_path, _ = get_open_file_name(
            self, "选择公司名单文件", "",
            "Text files (*.txt);;Excel files (*.xlsx *.xls);;All files (*.*)"
        )
        
        if file_path:
            self.aiqicha_batch_file_path = file_path
            self.aiqicha_file_label.setText(os.path.basename(file_path))
            self.aiqicha_file_label.setStyleSheet("color: #27ae60; font-weight: bold;")
    
    def start_tianyancha_query(self):
        """开始天眼查查询"""
        try:
            # 检查查询模式
            if self.tyc_single_radio.isChecked():
                # 单个查询
                company_name = self.tyc_company_input.text().strip()
                if not company_name:
                    show_warning(self, "警告", "请输入公司名称")
                    return
                
                self.tyc_status_label.setText("正在查询...")
                
                # 切换到加载界面
                self.tyc_info_widget.show_loading(f"正在查询 {company_name} ...")
                self.tyc_result_stack.setCurrentWidget(self.tyc_info_widget)
                
                # 显示进度条并设置范围
                self.tyc_progress_bar.setVisible(True)
                self.tyc_progress_bar.setRange(0, 4)  # 搜索、ICP、APP、微信
                self.tyc_progress_bar.setValue(0)
                
                try:
                    # 设置无cookie模式
                    self.tianyancha_query.no_cookie_mode = self.tyc_no_cookie_checkbox.isChecked()

                    # 后台线程执行查询，流式输出部分结果
                    self.single_query_thread = EnterpriseSingleQueryThread(
                        self.tianyancha_query,
                        company_name,
                        self.tyc_no_cookie_checkbox.isChecked()
                    )

                    self.single_query_thread.progress_updated.connect(self.tyc_status_label.setText)
                    self.single_query_thread.progress_step.connect(self.tyc_progress_bar.setValue)

                    def on_partial(data: dict):
                        # 不显示中间查询结果，只在最终汇总时显示企业详细信息
                        pass

                    self.single_query_thread.partial_result.connect(on_partial)

                    def on_completed(result: dict):
                        # 隐藏进度条
                        self.tyc_progress_bar.setVisible(False)
                        # 确保result是字典类型
                        if not isinstance(result, dict):
                            self.tyc_result_stack.setCurrentWidget(self.tyc_result_text)
                            self.tyc_result_text.append(f"查询结果类型错误: {type(result).__name__}")
                            self.tyc_status_label.setText("查询失败")
                            return
                        if result.get('success'):
                            self.tianyancha_results = [{
                                'company': company_name,
                                'data': result,
                                'success': True
                            }]
                            
                            # 使用新组件渲染结果
                            self.tyc_info_widget.render_tianyancha(result)
                            self.tyc_result_stack.setCurrentWidget(self.tyc_info_widget)
                            
                            self.tyc_status_label.setText(f"查询完成: {company_name}")
                            self.tyc_status_label.setProperty("class", "status-label-success")
                            self.tyc_status_label.style().polish(self.tyc_status_label)
                            self.tyc_export_btn.setEnabled(True)
                        else:
                            error_msg = result.get('error', '查询失败')
                            self.tianyancha_results = [{
                                'company': company_name,
                                'error': error_msg,
                                'success': False
                            }]
                            
                            # 失败时切换回文本显示
                            self.tyc_result_stack.setCurrentWidget(self.tyc_result_text)
                            self.tyc_result_text.setText(f"查询失败: {error_msg}")
                            
                            self.tyc_status_label.setText("查询失败")
                            self.tyc_status_label.setProperty("class", "status-label-error")
                            self.tyc_status_label.style().polish(self.tyc_status_label)

                    self.single_query_thread.query_completed.connect(on_completed)
                    self.single_query_thread.start()
                except Exception as e:
                    # 隐藏进度条
                    self.tyc_progress_bar.setVisible(False)
                    self.tyc_result_text.setText(f"查询异常: {str(e)}")
                    self.tyc_status_label.setText("查询异常")
                    self.tyc_status_label.setProperty("class", "status-label-error")
                    self.tyc_status_label.style().polish(self.tyc_status_label)
                    self.logger.error(f"天眼查查询异常: {e}")
            else:
                # 批量查询
                if not hasattr(self, 'tyc_batch_file_path') or not self.tyc_batch_file_path:
                    show_warning(self, "警告", "请先选择公司名单文件")
                    return
                
                # 读取文件中的公司名称
                try:
                    with open(self.tyc_batch_file_path, 'r', encoding='utf-8') as f:
                        companies = [line.strip() for line in f.readlines() if line.strip()]
                    
                    if not companies:
                        show_warning(self, "警告", "文件中没有找到公司名称")
                        return
                    
                    # 设置无cookie模式
                    self.tianyancha_query.no_cookie_mode = self.tyc_no_cookie_checkbox.isChecked()
                    
                    # 启动批量查询线程
                    self.batch_query_thread = EnterpriseBatchQueryThread(
                        self.tianyancha_query, companies, 'tianyancha'
                    )
                    self.batch_query_thread.progress_updated.connect(self.tyc_status_label.setText)
                    self.batch_query_thread.progress_percentage.connect(self.update_tyc_progress)
                    self.batch_query_thread.query_completed.connect(self.on_tianyancha_batch_completed)
                    
                    self.tyc_progress_bar.setVisible(True)
                    self.tyc_progress_bar.setMaximum(len(companies))
                    self.tyc_progress_bar.setValue(0)
                    # 不进行样式重刷，减少界面重绘
                    
                    self.batch_query_thread.start()
                    
                except Exception as e:
                    show_critical(self, "错误", f"读取文件失败: {str(e)}")
                    
        except Exception as e:
            show_critical(self, "错误", f"查询失败: {str(e)}")
            self.tyc_status_label.setText("查询失败")
    
    def start_aiqicha_query(self):
        """开始爱企查查询"""
        try:
            # 检查查询模式
            if self.aiqicha_single_radio.isChecked():
                # 单个查询
                company_name = self.aiqicha_company_input.text().strip()
                if not company_name:
                    show_warning(self, "警告", "请输入公司名称")
                    return
                
                self.aiqicha_status_label.setText("正在查询...")
                
                # 切换到加载界面
                self.aiqicha_info_widget.show_loading(f"正在查询 {company_name} ...")
                self.aiqicha_result_stack.setCurrentWidget(self.aiqicha_info_widget)
                
                # 显示进度条并设置范围
                self.aiqicha_progress_bar.setVisible(True)
                self.aiqicha_progress_bar.setRange(0, 7)  # 7个步骤
                self.aiqicha_progress_bar.setValue(0)
                
                try:
                    # 使用后台线程执行查询
                    self.aiqicha_single_query_thread = EnterpriseAiqichaSingleQueryThread(
                        self.aiqicha_query,
                        company_name
                    )
                    
                    # 连接信号
                    self.aiqicha_single_query_thread.progress_updated.connect(
                        self.aiqicha_status_label.setText
                    )
                    self.aiqicha_single_query_thread.progress_step.connect(
                        self.aiqicha_progress_bar.setValue
                    )
                    
                    def on_completed(result: dict):
                        """查询完成回调"""
                        # 隐藏进度条
                        self.aiqicha_progress_bar.setVisible(False)
                        
                        # 确保result是字典类型
                        if not isinstance(result, dict):
                            self.aiqicha_result_stack.setCurrentWidget(self.aiqicha_result_text)
                            self.aiqicha_result_text.setText(f"查询结果类型错误: {type(result).__name__}")
                            self.aiqicha_status_label.setText("查询失败")
                            return
                        
                        if result.get('success'):
                            # 查询成功
                            data = result.get('data', {})
                            self.aiqicha_results = [data]
                            
                            # 使用新组件渲染结果
                            self.aiqicha_info_widget.render_aiqicha(data)
                            self.aiqicha_result_stack.setCurrentWidget(self.aiqicha_info_widget)
                            
                            self.aiqicha_status_label.setText(f"查询完成: {company_name}")
                            self.aiqicha_status_label.setProperty("class", "status-label-success")
                            self.aiqicha_status_label.style().polish(self.aiqicha_status_label)
                            self.aiqicha_export_btn.setEnabled(True)
                        else:
                            # 查询失败
                            error_msg = result.get('error', '查询失败')
                            
                            # 失败时切换回文本显示
                            self.aiqicha_result_stack.setCurrentWidget(self.aiqicha_result_text)
                            self.aiqicha_result_text.setText(f"查询失败: {error_msg}")
                            
                            self.aiqicha_status_label.setText("查询失败")
                            self.aiqicha_status_label.setProperty("class", "status-label-error")
                            self.aiqicha_status_label.style().polish(self.aiqicha_status_label)
                    
                    self.aiqicha_single_query_thread.query_completed.connect(on_completed)
                    
                    # 启动线程
                    self.aiqicha_single_query_thread.start()
                    
                except Exception as e:
                    # 隐藏进度条
                    self.aiqicha_progress_bar.setVisible(False)
                    self.aiqicha_result_text.setText(f"查询异常: {str(e)}")
                    self._scroll_text_to_top(self.aiqicha_result_text)
                    self.aiqicha_status_label.setText("查询异常")
                    self.aiqicha_status_label.setProperty("class", "status-label-error")
                    self.aiqicha_status_label.style().polish(self.aiqicha_status_label)
                    self.logger.error(f"爱企查查询异常: {e}")
            else:
                # 批量查询
                if not hasattr(self, 'aiqicha_batch_file_path') or not self.aiqicha_batch_file_path:
                    show_warning(self, "警告", "请先选择公司名单文件")
                    return
                
                # 读取文件中的公司名称
                try:
                    with open(self.aiqicha_batch_file_path, 'r', encoding='utf-8') as f:
                        companies = [line.strip() for line in f.readlines() if line.strip()]
                    
                    if not companies:
                        show_warning(self, "警告", "文件中没有找到公司名称")
                        return
                    
                    # 启动批量查询线程
                    self.batch_query_thread = EnterpriseBatchQueryThread(
                        self.aiqicha_query, companies, 'aiqicha'
                    )
                    self.batch_query_thread.progress_updated.connect(self.aiqicha_status_label.setText)
                    self.batch_query_thread.progress_percentage.connect(self.update_aiqicha_progress)
                    self.batch_query_thread.query_completed.connect(self.on_aiqicha_batch_completed)
                    
                    self.aiqicha_progress_bar.setVisible(True)
                    self.aiqicha_progress_bar.setMaximum(len(companies))
                    self.aiqicha_progress_bar.setValue(0)
                    
                    self.batch_query_thread.start()
                    
                except Exception as e:
                    show_critical(self, "错误", f"读取文件失败: {str(e)}")
                    
        except Exception as e:
            show_critical(self, "错误", f"查询失败: {str(e)}")
            self.aiqicha_status_label.setText("查询失败")
    
    def update_tyc_progress(self, percentage):
        """更新天眼查进度条（不重刷样式，避免闪烁）"""
        now = time.perf_counter()
        # 节流：在最小间隔内忽略非关键更新（保留0和100%）
        if percentage not in (0, 100):
            if (now - self._last_tyc_progress_ts) * 1000 < self._progress_min_interval_ms:
                return
        self._last_tyc_progress_ts = now

        max_value = self.tyc_progress_bar.maximum()
        progress_value = int(max_value * percentage / 100)
        self.tyc_progress_bar.setValue(progress_value)
    
    def update_aiqicha_progress(self, percentage):
        """更新爱企查进度条（不重刷样式，避免闪烁）"""
        now = time.perf_counter()
        # 节流：在最小间隔内忽略非关键更新（保留0和100%）
        if percentage not in (0, 100):
            if (now - self._last_aiqicha_progress_ts) * 1000 < self._progress_min_interval_ms:
                return
        self._last_aiqicha_progress_ts = now

        max_value = self.aiqicha_progress_bar.maximum()
        progress_value = int(max_value * percentage / 100)
        self.aiqicha_progress_bar.setValue(progress_value)
    
    def on_tianyancha_batch_completed(self, results):
        """天眼查批量查询完成回调"""
        self.tyc_progress_bar.setVisible(False)
        
        # 确保results是字典类型
        if not isinstance(results, dict):
            self.tyc_result_text.setText(f"查询结果类型错误: {type(results).__name__}")
            self.tyc_status_label.setText("查询失败")
            return
            
        self.tianyancha_results = results.get('results', [])
        
        # 确保tianyancha_results是列表类型
        if not isinstance(self.tianyancha_results, list):
            self.tyc_result_text.setText(f"查询结果类型错误: 预期列表，实际为 {type(self.tianyancha_results).__name__}")
            self.tyc_status_label.setText("查询失败")
            return
        
        # 格式化显示结果
        formatted_results = []
        success_count = 0
        for result in self.tianyancha_results:
            if not isinstance(result, dict):
                formatted_results.append(f"❌ 结果类型错误: {type(result).__name__}")
                continue
                
            company = result.get('company', '未知公司')
            if result.get('success'):
                formatted_results.append(f"✅ {company}: 查询成功")
                success_count += 1
            else:
                formatted_results.append(f"❌ {company}: {result.get('error', '查询失败')}")
        
        self.tyc_result_text.setText("\n".join(formatted_results))
        self._scroll_text_to_top(self.tyc_result_text)
        self.tyc_status_label.setText(f"批量查询完成，共处理 {len(self.tianyancha_results)} 家企业，成功 {success_count} 家")
        
        # 只有在有成功结果时才启用导出按钮
        if success_count > 0:
            self.tyc_export_btn.setEnabled(True)
        else:
            self.tyc_export_btn.setEnabled(False)
    
    def on_aiqicha_batch_completed(self, results):
        """爱企查批量查询完成回调"""
        self.aiqicha_progress_bar.setVisible(False)
        
        # 确保results是字典类型
        if not isinstance(results, dict):
            self.aiqicha_result_text.setText(f"查询结果类型错误: {type(results).__name__}")
            self.aiqicha_status_label.setText("查询失败")
            return
        
        # 保存原始结果数据
        raw_results = results.get('results', [])
        
        # 确保raw_results是列表类型
        if not isinstance(raw_results, list):
            self.aiqicha_result_text.setText(f"查询结果类型错误: 预期列表，实际为 {type(raw_results).__name__}")
            self.aiqicha_status_label.setText("查询失败")
            return
        
        # 保存完整的结果数据用于导出
        self.aiqicha_results = raw_results
        
        # 格式化显示结果
        formatted_results = []
        success_count = 0
        for result in raw_results:
            if not isinstance(result, dict):
                formatted_results.append(f"❌ 结果类型错误: {type(result).__name__}")
                continue
                
            company = result.get('company', '未知公司')
            if result.get('success') and isinstance(result.get('data'), dict):
                formatted_results.append(f"✅ {company}: 查询成功")
                success_count += 1
            else:
                formatted_results.append(f"❌ {company}: {result.get('error', '查询失败')}")
        
        self.aiqicha_result_text.setText("\n".join(formatted_results))
        self._scroll_text_to_top(self.aiqicha_result_text)
        self.aiqicha_status_label.setText(f"批量查询完成，共处理 {len(raw_results)} 家企业，成功 {success_count} 家")
        
        # 只有在有成功结果时才启用导出按钮
        if success_count > 0:
            self.aiqicha_export_btn.setEnabled(True)
        else:
            self.aiqicha_export_btn.setEnabled(False)
    
    def export_tianyancha_results(self):
        """导出天眼查结果"""
        if not hasattr(self, 'tianyancha_results') or not self.tianyancha_results:
            show_warning(self, "警告", "没有可导出的天眼查结果")
            return
        
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
        
        # 创建导出格式选择对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("选择导出格式")
        dialog.setFixedSize(300, 150)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("请选择导出格式:"))
        
        button_layout = QHBoxLayout()
        csv_btn = QPushButton("CSV格式")
        txt_btn = QPushButton("TXT格式")
        both_btn = QPushButton("同时导出")
        cancel_btn = QPushButton("取消")
        
        button_layout.addWidget(csv_btn)
        button_layout.addWidget(txt_btn)
        button_layout.addWidget(both_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        def export_csv():
            self._export_tianyancha_to_csv()
            dialog.accept()
        
        def export_txt():
            self._export_tianyancha_to_txt()
            dialog.accept()
        
        def export_both():
            self._export_tianyancha_to_csv()
            self._export_tianyancha_to_txt()
            dialog.accept()
        
        csv_btn.clicked.connect(export_csv)
        txt_btn.clicked.connect(export_txt)
        both_btn.clicked.connect(export_both)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def export_aiqicha_results(self):
        """导出爱企查结果"""
        if not hasattr(self, 'aiqicha_results') or not self.aiqicha_results:
            show_warning(self, "警告", "没有可导出的爱企查结果")
            return
        
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
        
        # 创建导出格式选择对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("选择导出格式")
        dialog.setFixedSize(300, 150)
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("请选择导出格式:"))
        
        button_layout = QHBoxLayout()
        csv_btn = QPushButton("CSV格式")
        txt_btn = QPushButton("TXT格式")
        both_btn = QPushButton("同时导出")
        cancel_btn = QPushButton("取消")
        
        button_layout.addWidget(csv_btn)
        button_layout.addWidget(txt_btn)
        button_layout.addWidget(both_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        def export_csv():
            self._export_aiqicha_to_csv()
            dialog.accept()
        
        def export_txt():
            self._export_aiqicha_to_txt()
            dialog.accept()
        
        def export_both():
            self._export_aiqicha_to_csv()
            self._export_aiqicha_to_txt()
            dialog.accept()
        
        csv_btn.clicked.connect(export_csv)
        txt_btn.clicked.connect(export_txt)
        both_btn.clicked.connect(export_both)
        cancel_btn.clicked.connect(dialog.reject)
        
        dialog.exec()
    
    def _export_tianyancha_to_csv(self):
        """导出天眼查结果为CSV格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"tianyancha_results_{timestamp}.csv"
        
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存天眼查CSV结果", filename,
            "CSV files (*.csv);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = [
                    '企业名称', '法定代表人', '注册资本', '统一社会信用代码', '注册地址',
                    '联系电话', '邮箱', '网站', '行业分类1', '行业分类2', 
                    'ICP备案数', 'ICP域名列表', 'ICP网站名称列表', 'APP数量', 'APP名称', 
                    '微信公众号数', '微信公众号', '查询状态'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in self.tianyancha_results:
                    if result.get('success', False):
                        # 天眼查的数据结构：result['data'] 包含查询结果
                        data = result.get('data', {})
                        companies = data.get('companies', [])
                        if companies:
                            company = companies[0]
                            
                            # 处理行业分类
                            categories = []
                            for i in range(1, 5):
                                cat = company.get(f'categoryNameLv{i}', '')
                                if cat:
                                    categories.append(cat)
                            
                            # 安全处理列表字段
                            phone_list = company.get('phoneList', [])
                            if not isinstance(phone_list, list):
                                phone_list = []
                            
                            email_list = company.get('emailList', [])
                            if not isinstance(email_list, list):
                                email_list = []
                            
                            icp_records = company.get('icp_records', [])
                            if not isinstance(icp_records, list):
                                icp_records = []
                            
                            # 处理APP信息
                            app_records = company.get('app_records', [])
                            if not isinstance(app_records, list):
                                app_records = []
                            
                            # 处理微信公众号信息
                            wechat_records = company.get('wechat_records', [])
                            if not isinstance(wechat_records, list):
                                wechat_records = []
                            
                            # 处理ICP域名列表
                            icp_domains = []
                            icp_names = []
                            for icp in icp_records:
                                if icp.get('ym'):
                                    icp_domains.append(icp['ym'])
                                if icp.get('webName'):
                                    icp_names.append(icp['webName'])
                            
                            # 处理APP名称列表
                            app_names = [app.get('name', '') for app in app_records if isinstance(app, dict) and app.get('name')]
                            
                            # 处理微信公众号名称列表
                            wechat_names = [wechat.get('title', '') for wechat in wechat_records if isinstance(wechat, dict) and wechat.get('title')]
                            
                            # 计算最大行数（以最多值的字段为准）
                            max_items = max(len(icp_domains), len(app_names), len(wechat_names), 1)
                            
                            # 基础企业信息（只在第一行显示）
                            base_info = {
                                '法定代表人': company.get('legalPersonName', ''),
                                '注册资本': company.get('regCapital', ''),
                                '统一社会信用代码': company.get('creditCode', ''),
                                '注册地址': company.get('regLocation', ''),
                                '联系电话': '; '.join(phone_list),
                                '邮箱': '; '.join(email_list),
                                '网站': company.get('websites', ''),
                                '行业分类1': categories[0] if len(categories) > 0 else '',
                                '行业分类2': categories[1] if len(categories) > 1 else '',
                                'ICP备案数': len(icp_records),
                                'APP数量': len(app_records),
                                '微信公众号数': len(wechat_records),
                                '查询状态': '成功'
                            }
                            
                            # 为每个值创建单独行
                            for i in range(max_items):
                                row = {'企业名称': company.get('name', '')}
                                
                                # 只在第一行填充基础信息
                                if i == 0:
                                    row.update(base_info)
                                else:
                                    # 其他行的基础信息留空
                                    for key in base_info.keys():
                                        row[key] = ''
                                
                                # 填充多值字段
                                row['ICP域名列表'] = icp_domains[i] if i < len(icp_domains) else ''
                                row['ICP网站名称列表'] = icp_names[i] if i < len(icp_names) else ''
                                row['APP名称'] = app_names[i] if i < len(app_names) else ''
                                row['微信公众号'] = wechat_names[i] if i < len(wechat_names) else ''
                                
                                writer.writerow(row)
                        else:
                            row = {
                                '企业名称': result.get('company', ''),
                                '法定代表人': '', '注册资本': '', '统一社会信用代码': '', '注册地址': '',
                                '联系电话': '', '邮箱': '', '网站': '', '行业分类1': '',
                                '行业分类2': '', 'ICP备案数': '', 'APP数量': '', 'APP名称': '',
                                '微信公众号数': '', '微信公众号': '',
                                '查询状态': '成功但无企业信息'
                            }
                            writer.writerow(row)
                    else:
                        row = {
                            '企业名称': result.get('company', ''),
                            '法定代表人': '', '注册资本': '', '统一社会信用代码': '', '注册地址': '',
                            '联系电话': '', '邮箱': '', '网站': '', '行业分类1': '',
                            '行业分类2': '', 'ICP备案数': '', 'APP数量': '', 'APP名称': '',
                            '微信公众号数': '', '微信公众号': '',
                            '查询状态': f"失败: {result.get('error', '未知错误')}"
                        }
                        writer.writerow(row)
            
            show_information(self, "成功", f"CSV文件已导出: {file_path}")
            
        except Exception as e:
            show_critical(self, "错误", f"导出CSV失败: {str(e)}")
    
    def _export_tianyancha_to_txt(self):
        """导出天眼查结果为TXT格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"tianyancha_results_{timestamp}.txt"
        
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存天眼查TXT结果", filename,
            "Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as txtfile:
                # 使用制表符分隔，避免数据截断
                headers = ['序号', '企业名称', '法定代表人', '注册资本', '统一社会信用代码', '注册地址', 
                          '联系电话', '邮箱', '网站', '行业分类1', '行业分类2', 'ICP备案数', 'APP数量', 
                          'APP名称', '微信公众号数', '微信公众号', '查询状态']
                
                # 写入表头（使用制表符分隔）
                txtfile.write('\t'.join(headers) + '\n')
                
                # 写入数据行
                for i, result in enumerate(self.tianyancha_results, 1):
                    if result.get('success', False):
                        # 天眼查的数据结构：result['data'] 包含查询结果
                        data = result.get('data', {})
                        companies = data.get('companies', [])
                        if companies:
                            company = companies[0]
                            
                            # 处理行业分类
                            categories = []
                            for j in range(1, 5):
                                cat = company.get(f'categoryNameLv{j}', '')
                                if cat:
                                    categories.append(cat)
                            
                            # 安全处理列表字段
                            phone_list = company.get('phoneList', [])
                            if not isinstance(phone_list, list):
                                phone_list = []
                            
                            email_list = company.get('emailList', [])
                            if not isinstance(email_list, list):
                                email_list = []
                            
                            icp_records = company.get('icp_records', [])
                            if not isinstance(icp_records, list):
                                icp_records = []
                            
                            # 处理APP信息
                            app_records = company.get('app_records', [])
                            if not isinstance(app_records, list):
                                app_records = []
                            app_names = [app.get('name', '') for app in app_records if isinstance(app, dict)]
                            
                            # 处理微信公众号信息
                            wechat_records = company.get('wechat_records', [])
                            if not isinstance(wechat_records, list):
                                wechat_records = []
                            wechat_names = [wechat.get('title', '') for wechat in wechat_records if isinstance(wechat, dict)]
                            
                            row_data = [
                                str(i),  # 序号
                                company.get('name', ''),  # 企业名称
                                company.get('legalPersonName', ''),  # 法定代表人
                                company.get('regCapital', ''),  # 注册资本
                                company.get('creditCode', ''),  # 统一社会信用代码
                                company.get('regLocation', ''),  # 注册地址
                                '; '.join(phone_list),  # 联系电话
                                '; '.join(email_list),  # 邮箱
                                company.get('websites', ''),  # 网站
                                categories[0] if len(categories) > 0 else '',  # 行业分类1
                                categories[1] if len(categories) > 1 else '',  # 行业分类2
                                str(len(icp_records)),  # ICP备案数
                                str(len(app_records)),  # APP数量
                                '; '.join(app_names),  # APP名称
                                str(len(wechat_records)),  # 微信公众号数
                                '; '.join(wechat_names),  # 微信公众号
                                '成功'  # 查询状态
                            ]
                        else:
                            row_data = [
                                str(i),  # 序号
                                result.get('company', ''),  # 企业名称
                                '', '', '', '',  # 法定代表人, 注册资本, 统一社会信用代码, 注册地址
                                '', '', '',  # 联系电话, 邮箱, 网站
                                '', '',  # 行业分类1, 行业分类2
                                '', '', '', '', '',  # ICP备案数, APP数量, APP名称, 微信公众号数, 微信公众号
                                '无信息'  # 查询状态
                            ]
                    else:
                        row_data = [
                            str(i),  # 序号
                            result.get('company', ''),  # 企业名称
                            '', '', '', '',  # 法定代表人, 注册资本, 统一社会信用代码, 注册地址
                            '', '', '',  # 联系电话, 邮箱, 网站
                            '', '',  # 行业分类1, 行业分类2
                            '', '', '', '', '',  # ICP备案数, APP数量, APP名称, 微信公众号数, 微信公众号
                            '失败'  # 查询状态
                        ]
                    
                    # 写入行数据（使用制表符分隔）
                    txtfile.write('\t'.join(str(item) for item in row_data) + '\n')
            
            show_information(self, "成功", f"TXT文件已导出: {file_path}")
            
        except Exception as e:
             show_critical(self, "错误", f"导出TXT失败: {str(e)}")
    
    def _export_aiqicha_to_csv(self):
        """导出爱企查结果为CSV格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"aiqicha_results_{timestamp}.csv"
        
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存爱企查CSV结果", filename,
            "CSV files (*.csv);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = [
                    '企业名称', '法人代表', '注册资本', '统一社会信用代码', '企业地址',
                    '企业邮箱', '企业网站', '企业电话', '行业大类', '行业中类', 
                    '行业小类', '具体分类', '行业编号', '员工企业邮箱', 'ICP备案数量',
                    'ICP域名列表', 'APP数量', 'APP名称', '微信公众号数量', '微信公众号名称', 
                    '员工手机数量', '员工手机列表', '查询状态'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in self.aiqicha_results:
                    if result.get('success', False):
                        data = result['data']
                        basic_info = data.get('basic_info', {})
                        industry_info = data.get('industry_info', {})
                        icp_info = data.get('icp_info', [])
                        contact_info = data.get('contact_info', [])
                        
                        # 处理ICP信息
                        icp_domains = []
                        for icp in icp_info:
                            domains = icp.get('domain', [])
                            if isinstance(domains, list):
                                icp_domains.extend(domains)
                            else:
                                icp_domains.append(str(domains))
                        
                        # 处理员工邮箱
                        employee_emails = industry_info.get('employee_emails', [])
                        if not isinstance(employee_emails, list):
                            employee_emails = []
                        
                        # 处理员工联系方式
                        if not isinstance(contact_info, list):
                            contact_info = []
                        
                        # 处理APP信息
                        app_info = data.get('app_info', [])
                        if not isinstance(app_info, list):
                            app_info = []
                        
                        # 处理微信公众号信息
                        wechat_info = data.get('wechat_info', [])
                        if not isinstance(wechat_info, list):
                            wechat_info = []
                        
                        # 处理APP名称列表
                        app_names = [app.get('name', '') for app in app_info if isinstance(app, dict) and app.get('name')]
                        
                        # 处理微信公众号名称列表
                        wechat_names = [wechat.get('wechatName', '') for wechat in wechat_info if isinstance(wechat, dict) and wechat.get('wechatName')]
                        
                        # 处理员工手机列表
                        contact_list = [phone for phone in contact_info if phone]
                        
                        # 计算最大行数（以最多值的字段为准）
                        max_items = max(len(icp_domains), len(app_names), len(wechat_names), len(contact_list), 1)
                        
                        # 基础企业信息（只在第一行显示）
                        base_info = {
                            '法人代表': basic_info.get('legalPerson', ''),
                            '注册资本': basic_info.get('regCap', ''),
                            '统一社会信用代码': basic_info.get('regNo', ''),
                            '企业地址': basic_info.get('titleDomicile', ''),
                            '企业邮箱': basic_info.get('email', ''),
                            '企业网站': basic_info.get('website', ''),
                            '企业电话': basic_info.get('telephone', ''),
                            '行业大类': industry_info.get('industryCode1', ''),
                            '行业中类': industry_info.get('industryCode2', ''),
                            '行业小类': industry_info.get('industryCode3', ''),
                            '具体分类': industry_info.get('industryCode4', ''),
                            '行业编号': industry_info.get('industryNum', ''),
                            '员工企业邮箱': '; '.join(employee_emails),
                            'ICP备案数量': len(icp_info),
                            'APP数量': len(app_info),
                            '微信公众号数量': len(wechat_info),
                            '员工手机数量': len(contact_info),
                            '查询状态': '成功'
                        }
                        
                        # 为每个值创建单独行
                        for i in range(max_items):
                            row = {'企业名称': data.get('company_name', '')}
                            
                            # 只在第一行填充基础信息
                            if i == 0:
                                row.update(base_info)
                            else:
                                # 其他行的基础信息留空
                                for key in base_info.keys():
                                    row[key] = ''
                            
                            # 填充多值字段
                            row['ICP域名列表'] = icp_domains[i] if i < len(icp_domains) else ''
                            row['APP名称'] = app_names[i] if i < len(app_names) else ''
                            row['微信公众号名称'] = wechat_names[i] if i < len(wechat_names) else ''
                            row['员工手机列表'] = contact_list[i] if i < len(contact_list) else ''
                            
                            writer.writerow(row)
                    else:
                        row = {
                            '企业名称': result.get('company_name', ''),
                            '法人代表': '', '注册资本': '', '统一社会信用代码': '', '企业地址': '',
                            '企业邮箱': '', '企业网站': '', '企业电话': '', '行业大类': '',
                            '行业中类': '', '行业小类': '', '具体分类': '', '行业编号': '',
                            '员工企业邮箱': '', 'ICP备案数量': '', 'ICP域名列表': '',
                            'APP数量': '', 'APP名称': '', '微信公众号数量': '', '微信公众号名称': '',
                            '员工手机数量': '', '员工手机列表': '',
                            '查询状态': f"失败: {result.get('error', '未知错误')}"
                        }
                    
                    writer.writerow(row)
            
            show_information(self, "成功", f"CSV文件已导出: {file_path}")
            
        except Exception as e:
            show_critical(self, "错误", f"导出CSV失败: {str(e)}")
    
    def _export_aiqicha_to_txt(self):
        """导出爱企查结果为TXT格式"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"aiqicha_results_{timestamp}.txt"
        
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存爱企查TXT结果", filename,
            "Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as txtfile:
                # 使用制表符分隔，避免数据截断
                headers = ['序号', '企业名称', '法人代表', '注册资本', '统一社会信用代码', '企业地址',
                          '企业邮箱', '企业网站', '企业电话', '行业大类', '行业中类', 'ICP备案数',
                          'APP数量', 'APP名称', '微信公众号数', '微信公众号', '员工手机数', '查询状态']
                
                # 写入表头（使用制表符分隔）
                txtfile.write('\t'.join(headers) + '\n')
                
                # 写入数据行
                for i, result in enumerate(self.aiqicha_results, 1):
                    if result.get('success', False):
                        data = result['data']
                        basic_info = data.get('basic_info', {})
                        industry_info = data.get('industry_info', {})
                        icp_info = data.get('icp_info', [])
                        contact_info = data.get('contact_info', [])
                        
                        # 处理员工联系方式
                        if not isinstance(contact_info, list):
                            contact_info = []
                        
                        # 处理APP信息
                        app_info = data.get('app_info', [])
                        if not isinstance(app_info, list):
                            app_info = []
                        app_names = [app.get('name', '') for app in app_info if isinstance(app, dict)]
                        
                        # 处理微信公众号信息
                        wechat_info = data.get('wechat_info', [])
                        if not isinstance(wechat_info, list):
                            wechat_info = []
                        wechat_names = [wechat.get('wechatName', '') for wechat in wechat_info if isinstance(wechat, dict)]
                        
                        row_data = [
                            str(i),  # 序号
                            data.get('company_name', ''),  # 企业名称
                            basic_info.get('legalPerson', ''),  # 法人代表
                            basic_info.get('regCap', ''),  # 注册资本
                            basic_info.get('regNo', ''),  # 统一社会信用代码
                            basic_info.get('titleDomicile', ''),  # 企业地址
                            basic_info.get('email', ''),  # 企业邮箱
                            basic_info.get('website', ''),  # 企业网站
                            basic_info.get('telephone', ''),  # 企业电话
                            industry_info.get('industryCode1', ''),  # 行业大类
                            industry_info.get('industryCode2', ''),  # 行业中类
                            str(len(icp_info)),  # ICP备案数
                            str(len(app_info)),  # APP数量
                            '; '.join(app_names),  # APP名称
                            str(len(wechat_info)),  # 微信公众号数
                            '; '.join(wechat_names),  # 微信公众号
                            str(len(contact_info)),  # 员工手机数
                            '成功'  # 查询状态
                        ]
                    else:
                        row_data = [
                            str(i),  # 序号
                            result.get('company_name', ''),  # 企业名称
                            '', '', '', '',  # 法人代表, 注册资本, 统一社会信用代码, 企业地址
                            '', '', '',  # 企业邮箱, 企业网站, 企业电话
                            '', '',  # 行业大类, 行业中类
                            '', '', '', '', '',  # ICP备案数, APP数量, APP名称, 微信公众号数, 微信公众号
                            '',  # 员工手机数
                            '失败'  # 查询状态
                        ]
                    
                    # 写入行数据（使用制表符分隔）
                    txtfile.write('\t'.join(str(item) for item in row_data) + '\n')
            
            show_information(self, "成功", f"TXT文件已导出: {file_path}")
            
        except Exception as e:
            show_critical(self, "错误", f"导出TXT失败: {str(e)}")
    
    def clear_tianyancha_results(self):
        """清空天眼查结果"""
        self.tianyancha_results.clear()
        self.tyc_result_text.clear()
        self.tyc_status_label.setText("等待查询...")
        self.tyc_status_label.setProperty("class", "status-label-waiting")
        self.tyc_status_label.style().polish(self.tyc_status_label)
        self.tyc_export_btn.setEnabled(False)
    
    def clear_aiqicha_results(self):
        """清空爱企查结果"""
        self.aiqicha_results.clear()
        self.aiqicha_result_text.clear()
        self.aiqicha_status_label.setText("等待查询...")
        self.aiqicha_status_label.setProperty("class", "status-label-waiting")
        self.aiqicha_status_label.style().polish(self.aiqicha_status_label)
        self.aiqicha_export_btn.setEnabled(False)
    
    def get_config(self) -> Dict:
        """获取配置信息"""
        return {
            'tianyancha_cookie': '',  # Cookie通过按钮更新，不直接从输入框获取
            'aiqicha_cookie': ''  # Cookie通过按钮更新，不直接从输入框获取
        }
    
    def set_config(self, config: Dict):
        """设置配置信息"""
        # 更新Cookie状态显示
        if 'tianyancha_cookie' in config and config['tianyancha_cookie']:
            self.tyc_cookie_status.setText("Cookie状态: 已配置")
            self.tyc_cookie_status.setStyleSheet("color: #27ae60; font-weight: bold;")
        
        if 'aiqicha_cookie' in config and config['aiqicha_cookie']:
            self.aiqicha_cookie_status.setText("Cookie状态: 已配置")
            self.aiqicha_cookie_status.setStyleSheet("color: #27ae60; font-weight: bold;")

    def _on_config_file_changed(self, path: str):
        """配置文件变更时回调，使用防抖延迟加载避免部分写入"""
        try:
            # 某些编辑器采用原子写入，可能导致监控路径被移除，尝试重新添加
            if self._config_watcher and path:
                try:
                    watched = set(self._config_watcher.files())
                    if path not in watched:
                        self._config_watcher.addPath(path)
                except Exception:
                    pass
            # Windows 上文件保存可能触发多次事件，延迟后读取
            QTimer.singleShot(300, self._refresh_cookie_status)
        except Exception as e:
            self.logger.warning(f"处理配置文件变更事件失败: {e}")

    def _refresh_cookie_status(self):
        """重新读取配置并刷新Cookie状态标签，同时让查询引擎加载最新配置"""
        try:
            if self._config_manager:
                cfg = self._config_manager.load_config()
            else:
                from modules.config.config_manager import ConfigManager
                cfg = ConfigManager().load_config()

            refresh_cfg = {
                'tianyancha_cookie': cfg.get('tyc', {}).get('cookie', ''),
                'aiqicha_cookie': cfg.get('aiqicha', {}).get('cookie', '')
            }
            self.set_config(refresh_cfg)

            # 让查询引擎也加载最新配置，确保后续请求使用新Cookie
            try:
                if hasattr(self.tianyancha_query, '_load_config'):
                    self.tianyancha_query._load_config()
                if hasattr(self.aiqicha_query, '_load_config'):
                    self.aiqicha_query._load_config()
            except Exception as e:
                self.logger.warning(f"刷新查询引擎配置失败: {e}")
        except Exception as e:
            self.logger.warning(f"刷新Cookie状态失败: {e}")
    
    def update_tianyancha_cookie(self):
        """更新天眼查Cookie"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("更新天眼查Cookie")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setModal(True)
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 说明文本
        info_label = QLabel("请按以下步骤获取天眼查Cookie：\n"
                           "1. 打开浏览器，访问 https://www.tianyancha.com\n"
                           "2. 登录您的天眼查账号\n"
                           "3. 按F12打开开发者工具\n"
                           "4. 切换到Network标签页\n"
                           "5. 刷新页面，找到任意请求\n"
                           "6. 复制请求头中的Cookie值")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Cookie输入框
        cookie_input = QTextEdit()
        cookie_input.setPlaceholderText("请粘贴完整的Cookie字符串...")
        layout.addWidget(cookie_input)
        
        # 按钮
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        
        def save_cookie():
            cookie_text = cookie_input.toPlainText().strip()
            if cookie_text:
                # 保存到配置文件
                self.save_tianyancha_cookie(cookie_text)
                self.tyc_cookie_status.setText("Cookie状态: 已配置")
                self.tyc_cookie_status.setStyleSheet("color: #27ae60; font-weight: bold;")
                show_information(dialog, "成功", "天眼查Cookie已保存")
                dialog.accept()
            else:
                show_warning(dialog, "警告", "请输入Cookie")
        
        save_btn.clicked.connect(save_cookie)
        cancel_btn.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def update_aiqicha_cookie(self):
        """更新爱企查Cookie"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("更新爱企查Cookie")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setModal(True)
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 说明文本
        info_label = QLabel("请按以下步骤获取爱企查Cookie：\n"
                           "1. 打开浏览器，访问 https://aiqicha.baidu.com\n"
                           "2. 登录您的爱企查账号\n"
                           "3. 按F12打开开发者工具\n"
                           "4. 切换到Network标签页\n"
                           "5. 刷新页面，找到任意请求\n"
                           "6. 复制请求头中的Cookie值")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Cookie输入框
        cookie_input = QTextEdit()
        cookie_input.setPlaceholderText("请粘贴完整的Cookie字符串...")
        layout.addWidget(cookie_input)
        
        # 按钮
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        
        def save_cookie():
            cookie_text = cookie_input.toPlainText().strip()
            if cookie_text:
                # 保存到配置文件
                self.save_aiqicha_cookie(cookie_text)
                self.aiqicha_cookie_status.setText("Cookie状态: 已配置")
                self.aiqicha_cookie_status.setStyleSheet("color: #27ae60; font-weight: bold;")
                show_information(dialog, "成功", "爱企查Cookie已保存")
                dialog.accept()
            else:
                show_warning(dialog, "警告", "请输入Cookie")
        
        save_btn.clicked.connect(save_cookie)
        cancel_btn.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    

    
    def save_tianyancha_cookie(self, cookie: str):
        """保存天眼查Cookie到配置文件"""
        try:
            # 使用ConfigManager来安全地保存配置，避免覆盖其他配置项
            from modules.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            config_manager.update_section('tyc', {
                'cookie': cookie
            })
                
        except Exception as e:
            show_critical(self, "错误", f"保存Cookie失败: {str(e)}")
    
    def save_aiqicha_cookie(self, cookie: str):
        """保存爱企查Cookie到配置文件"""
        try:
            # 使用ConfigManager来安全地保存配置，避免覆盖其他配置项
            from modules.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            
            # 只更新爱企查相关配置
            aiqicha_config = {
                'aiqicha': {
                    'cookie': cookie,
                    'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }
            
            # 使用ConfigManager的安全保存方法
            config_manager.save_config(aiqicha_config)
                
        except Exception as e:
            show_critical(self, "错误", f"保存Cookie失败: {str(e)}")
    
    def get_all_results(self) -> List[Dict]:
        """获取所有查询结果"""
        all_results = []
        
        # 添加天眼查结果
        for result in self.tianyancha_results:
            result['source'] = 'tianyancha'
            all_results.append(result)
        
        # 添加爱企查结果
        for result in self.aiqicha_results:
            result['source'] = 'aiqicha'
            all_results.append(result)
        
        return all_results
    
    def format_aiqicha_result(self, result: Dict) -> str:
        """格式化爱企查查询结果"""
        if not result:
            return "查询失败: 未获取到企业信息"
            
        # 确保result是字典类型
        if not isinstance(result, dict):
            return f"查询结果类型错误: {type(result).__name__}"
        
        output = []
        output.append(f"企业查询结果: {result.get('company_name', '未知')}")
        output.append("=" * 50)
        
        # 基本信息
        basic = result.get('basic_info', {})
        # 确保basic是字典类型
        if not isinstance(basic, dict):
            basic = {}
            
        if basic:
            output.append("\n【基本信息】")
            output.append(f"法人代表: {basic.get('legalPerson', '未获取到')}")
            output.append(f"企业地址: {basic.get('titleDomicile', '未获取到')}")
            output.append(f"注册资本: {basic.get('regCap', '未获取到')}")
            output.append(f"统一社会信用代码: {basic.get('regNo', '未获取到')}")
            output.append(f"企业邮箱: {basic.get('email', '未获取到')}")
            output.append(f"企业网站: {basic.get('website', '未获取到')}")
            output.append(f"企业电话: {basic.get('telephone', '未获取到')}")
        
        # 行业信息
        industry = result.get('industry_info', {})
        # 确保industry是字典类型
        if not isinstance(industry, dict):
            industry = {}
            
        if industry:
            output.append("\n【行业分类】")
            output.append(f"行业大类: {industry.get('industryCode1', '未获取到')}")
            output.append(f"行业中类: {industry.get('industryCode2', '未获取到')}")
            output.append(f"行业小类: {industry.get('industryCode3', '未获取到')}")
            output.append(f"具体分类: {industry.get('industryCode4', '未获取到')}")
            output.append(f"行业编号: {industry.get('industryNum', '未获取到')}")
            
            # 员工企业邮箱
            employee_emails = industry.get('employee_emails', [])
            # 确保employee_emails是列表类型
            if not isinstance(employee_emails, list):
                employee_emails = []
                
            if employee_emails:
                output.append("\n【员工企业邮箱】")
                for i, email in enumerate(employee_emails, 1):
                    output.append(f"{i}. {email}")
        
        # ICP信息
        icp_info = result.get('icp_info', [])
        # 确保icp_info是列表类型
        if not isinstance(icp_info, list):
            icp_info = []
            
        output.append("\n【ICP备案信息】")
        if icp_info:
            for i, icp in enumerate(icp_info, 1):
                # 确保icp是字典类型
                if not isinstance(icp, dict):
                    continue
                    
                domains = icp.get('domain', [])
                # 确保domains是列表类型或字符串类型
                domain_str = ', '.join(domains) if isinstance(domains, list) else str(domains)
                output.append(f"{i}. 域名: {domain_str}")
                output.append(f"   网站名称: {icp.get('siteName', 'N/A')}")
                output.append(f"   备案号: {icp.get('icpNo', 'N/A')}")
        else:
            output.append("暂无ICP备案信息")
        
        # APP信息
        app_info = result.get('app_info', [])
        # 确保app_info是列表类型
        if not isinstance(app_info, list):
            app_info = []
            
        output.append("\n【APP信息】")
        if app_info:
            for i, app in enumerate(app_info, 1):
                # 确保app是字典类型
                if not isinstance(app, dict):
                    continue
                output.append(f"{i}. APP名称: {app.get('name', 'N/A')}")
        else:
            output.append("暂无APP信息")
        
        # 微信公众号信息
        wechat_info = result.get('wechat_info', [])
        # 确保wechat_info是列表类型
        if not isinstance(wechat_info, list):
            wechat_info = []
            
        output.append("\n【微信公众号信息】")
        if wechat_info:
            for i, wechat in enumerate(wechat_info, 1):
                # 确保wechat是字典类型
                if not isinstance(wechat, dict):
                    continue
                output.append(f"{i}. 公众号名称: {wechat.get('wechatName', 'N/A')}")
                output.append(f"   微信号: {wechat.get('wechatId', 'N/A')}")
        else:
            output.append("暂无微信公众号信息")
        
        # 联系方式
        contact_info = result.get('contact_info', [])
        # 确保contact_info是列表类型
        if not isinstance(contact_info, list):
            contact_info = []
            
        output.append("\n【员工联系方式】")
        if contact_info:
            for i, contact in enumerate(contact_info, 1):
                output.append(f"{i}. {contact}")
        else:
            output.append("暂无员工联系方式")
        
        return "\n".join(output)
    
    def clear_results(self):
        """清空所有结果"""
        self.clear_tianyancha_results()
        self.clear_aiqicha_results()

    def closeEvent(self, event):
        """窗口关闭时安全终止线程，避免QThread未结束导致的崩溃"""
        try:
            # 停止文件监控（防御式处理）
            try:
                watcher = getattr(self, '_config_watcher', None)
                if watcher is not None:
                    try:
                        watcher.fileChanged.disconnect(self._on_config_file_changed)
                    except Exception:
                        # 若信号已断开或对象无效，忽略
                        pass
            except Exception:
                pass

            # 终止可能仍在运行的线程
            for attr in ('batch_query_thread', 'single_query_thread'):
                th = getattr(self, attr, None)
                if th and th.isRunning():
                    try:
                        th.requestInterruption()
                    except Exception:
                        pass
                    try:
                        th.quit()
                    except Exception:
                        pass
                    try:
                        th.wait(3000)
                    except Exception:
                        pass
        finally:
            try:
                super().closeEvent(event)
            except Exception:
                # 若父类closeEvent抛错，不影响应用关闭
                pass
    
    def load_debug_config(self):
        """加载调试配置"""
        try:
            # 通过统一配置管理器读取，避免直接文件操作
            from modules.config.config_manager import ConfigManager
            cm = ConfigManager()
            debug_config = cm.get_config('debug')
            debug_enabled = debug_config.get('tianyancha_debug_output', False)
            self.tyc_debug_checkbox.setChecked(debug_enabled)
            aiqicha_debug_enabled = debug_config.get('aiqicha_debug_output', False)
            if hasattr(self, 'aiqicha_debug_checkbox'):
                self.aiqicha_debug_checkbox.setChecked(aiqicha_debug_enabled)
        except Exception as e:
            self.logger.error(f"加载调试配置失败: {e}")
    
    def on_debug_option_changed(self, state):
        """调试选项状态改变时的处理"""
        try:
            debug_enabled = state == 2  # Qt.Checked
            
            # 使用统一配置管理器进行更新，避免冲突
            from modules.config.config_manager import ConfigManager
            cm = ConfigManager()
            cm.update_section('debug', {
                'tianyancha_debug_output': debug_enabled
            })
            
            # 通知天眼查查询模块重新加载配置
            self.tianyancha_query._load_config()
            
            status = "启用" if debug_enabled else "禁用"
            self.logger.info(f"调试输出已{status}")
                
        except Exception as e:
            self.logger.error(f"更新调试配置失败: {e}")
            show_warning(self, "警告", f"更新调试配置失败: {e}")

    def on_aiqicha_debug_option_changed(self, state):
        try:
            debug_enabled = state == 2

            from modules.config.config_manager import ConfigManager
            cm = ConfigManager()
            cm.update_section('debug', {
                'aiqicha_debug_output': debug_enabled
            })

            self.aiqicha_query._load_config()

            status = "启用" if debug_enabled else "禁用"
            self.logger.info(f"爱企查调试输出已{status}")

        except Exception as e:
            self.logger.error(f"更新爱企查调试配置失败: {e}")
            show_warning(self, "警告", f"更新爱企查调试配置失败: {e}")

    def on_silent_option_changed(self, state):
        """静默验证浏览器选项变化时同步到查询引擎"""
        try:
            enabled = (state == 2)  # Qt.Checked
            if hasattr(self.tianyancha_query, 'set_silent_verification'):
                self.tianyancha_query.set_silent_verification(enabled)
            else:
                # 兼容旧代码：直接设置属性
                setattr(self.tianyancha_query, 'silent_verification', enabled)
            status = "启用" if enabled else "禁用"
            self.logger.info(f"静默验证浏览器已{status}")
        except Exception as e:
            self.logger.error(f"更新静默验证设置失败: {e}")


def main():
    """测试函数"""
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    window = EnterpriseQueryUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
