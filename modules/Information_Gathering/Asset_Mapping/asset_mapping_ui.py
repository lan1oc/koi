#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资产查询UI组件
整合FOFA、Hunter、Quake等平台的资产查询功能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox, QPushButton,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QRadioButton, QFileDialog, QMessageBox, QScrollArea, QGridLayout,
    QListWidget, QProgressBar, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QDialog, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor

from .fofa import FOFASearcher
from .hunter import HunterAPI
from .quake import QuakeAPI
from ..unified_search import UnifiedSearchEngine
from typing import Dict, List, Optional
import logging
import os
import json
import time
import csv
from datetime import datetime


class UnifiedSearchThread(QThread):
    """统一查询线程"""
    progress_updated = Signal(str)
    progress_percentage = Signal(int)
    search_completed = Signal(dict)
    
    def __init__(self, platforms: List[str], queries: List[str], api_configs: Dict):
        super().__init__()
        self.platforms = platforms
        self.queries = queries
        self.api_configs = api_configs
        self.search_engine = UnifiedSearchEngine(api_configs)
        self.results = {}
    
    def run(self):
        try:
            # 使用UnifiedSearchEngine进行查询，支持语法转换
            total_queries = len(self.queries)
            total_platforms = len(self.platforms)
            total_steps = total_queries * total_platforms
            current_step = 0
            
            self.progress_updated.emit("🚀 开始统一查询...")
            self.progress_percentage.emit(0)
            
            # 发送进度更新
            for i, query in enumerate(self.queries, 1):
                self.progress_updated.emit(f"📝 处理查询 {i}/{total_queries}: {query[:50]}...")
                
                # 转换查询语法
                converted_queries = self.search_engine.convert_query_syntax(query)
                
                query_results = {}
                
                # 执行各平台查询
                for j, platform in enumerate(self.platforms, 1):
                    platform_icons = {"fofa": "🌐", "hunter": "🦅", "quake": "⚡"}
                    icon = platform_icons.get(platform, "🔍")
                    
                    self.progress_updated.emit(f"{icon} 查询 {platform.upper()}... ({i}/{total_queries})")
                    
                    try:
                        # 使用转换后的查询语句
                        platform_query = converted_queries.get(platform, query)
                        result = self.search_engine.search_single_platform(platform, platform_query, limit=100)
                        query_results[platform] = result
                        
                        # 显示查询结果
                        if result.get('success'):
                            count = len(result.get('results', []))
                            self.progress_updated.emit(f"✅ {platform.upper()} 查询完成，找到 {count} 条结果")
                        else:
                            error = result.get('error', '未知错误')
                            self.progress_updated.emit(f"❌ {platform.upper()} 查询失败: {error}")
                        
                    except Exception as e:
                        query_results[platform] = {
                            'success': False,
                            'error': str(e),
                            'query': query,
                            'platform': platform
                        }
                        self.progress_updated.emit(f"❌ {platform.upper()} 查询异常: {str(e)}")
                    
                    # 更新进度百分比
                    current_step += 1
                    progress = int((current_step / total_steps) * 100)
                    self.progress_percentage.emit(progress)
                    
                    # 使用AsyncDelay工具类进行非阻塞延时
                    from ...utils.async_delay import AsyncDelay
                    AsyncDelay.delay(
                        milliseconds=1000,  # 1秒延时
                        progress_callback=lambda msg: self.progress_updated.emit(msg)
                    )
                
                self.results[query] = query_results
            
            # 最终进度更新
            self.progress_percentage.emit(100)
            self.progress_updated.emit("🎉 所有查询已完成，正在整理结果...")
            
            self.search_completed.emit({
                'success': True,
                'results': self.results,
                'total_queries': total_queries
            })
            
        except Exception as e:
            self.search_completed.emit({
                'success': False,
                'error': str(e)
            })
    
    def _query_fofa(self, query: str) -> Dict:
        """查询FOFA"""
        try:
            fofa_config = self.api_configs.get('fofa', {})
            fofa_api = FOFASearcher(
                api_key=fofa_config.get('api_key', ''),
                email=fofa_config.get('email', '')
            )
            result = fofa_api.search(query, size=100)
            # 统一返回格式
            if result.get('success'):
                return {
                    'success': True,
                    'results': result.get('results', []),
                    'total': result.get('total', 0),
                    'query': query,
                    'platform': 'fofa'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', '未知错误'),
                    'query': query,
                    'platform': 'fofa'
                }
        except Exception as e:
            return {'success': False, 'error': str(e), 'query': query, 'platform': 'fofa'}
    
    def _query_hunter(self, query: str) -> Dict:
        """查询Hunter"""
        try:
            hunter_config = self.api_configs.get('hunter', {})
            hunter_api = HunterAPI(api_key=hunter_config.get('api_key', ''))
            result = hunter_api.search(query, page_size=100)
            # 统一返回格式 - 修复Hunter API返回格式处理
            if result.get('code') == 200:
                data = result.get('data', {})
                results = data.get('arr', [])
                # 处理arr为null的情况
                if results is None:
                    results = []
                return {
                    'success': True,
                    'results': results,
                    'total': data.get('total', len(results)),
                    'query': query,
                    'platform': 'hunter'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('message', '未知错误'),
                    'query': query,
                    'platform': 'hunter'
                }
        except Exception as e:
            return {'success': False, 'error': str(e), 'query': query, 'platform': 'hunter'}
    
    def _query_quake(self, query: str) -> Dict:
        """查询Quake"""
        try:
            quake_config = self.api_configs.get('quake', {})
            quake_api = QuakeAPI(api_key=quake_config.get('api_key', ''))
            result = quake_api.search(query, size=100)
            # 统一返回格式
            if result.get('success'):
                return {
                    'success': True,
                    'results': result.get('data', []),
                    'total': result.get('total', 0),
                    'query': query,
                    'platform': 'quake'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', '未知错误'),
                    'query': query,
                    'platform': 'quake'
                }
        except Exception as e:
            return {'success': False, 'error': str(e), 'query': query, 'platform': 'quake'}


class AssetBatchSearchThread(QThread):
    """资产批量搜索线程"""
    progress_updated = Signal(str)
    search_completed = Signal(dict)
    
    def __init__(self, api_instance, queries: List[str], platform: str, **kwargs):
        super().__init__()
        self.api_instance = api_instance
        self.queries = queries
        self.platform = platform
        self.kwargs = kwargs
        self.results = []
    
    def run(self):
        try:
            total_queries = len(self.queries)
            
            for i, query in enumerate(self.queries, 1):
                query = query.strip()
                if not query:
                    continue
                
                self.progress_updated.emit(f"正在处理第 {i}/{total_queries} 个查询: {query[:50]}...")
                
                try:
                    if self.platform == 'hunter':
                        result = self.api_instance.search(query, **self.kwargs)
                    elif self.platform == 'fofa':
                        result = self.api_instance.search(query, **self.kwargs)
                    elif self.platform == 'quake':
                        result = self.api_instance.search(query, **self.kwargs)
                    else:
                        continue
                    
                    if result and result.get('success', False):
                        # 为每个结果添加来源查询标记
                        if 'results' in result:
                            for item in result['results']:
                                if isinstance(item, dict):
                                    item['source_query'] = query
                        elif 'data' in result:
                            for item in result['data']:
                                if isinstance(item, dict):
                                    item['source_query'] = query
                        
                        self.results.append(result)
                        self.progress_updated.emit(f"查询 {i} 完成，获得结果")
                    else:
                        self.progress_updated.emit(f"查询 {i} 失败: {result.get('error', '未知错误')}")
                
                except Exception as e:
                    self.progress_updated.emit(f"查询 {i} 异常: {str(e)}")
                
                # 查询间延时 - 使用异步方式避免线程阻塞
                if i < total_queries:
                    # 使用AsyncDelay工具类进行非阻塞延时
                    from ...utils.async_delay import AsyncDelay
                    AsyncDelay.delay(
                        milliseconds=1000,  # 1秒延时
                        progress_callback=lambda msg: self.progress_updated.emit(msg)
                    )
            
            self.search_completed.emit({
                'success': True,
                'results': self.results,
                'total_queries': total_queries,
                'platform': self.platform
            })
            
        except Exception as e:
            self.search_completed.emit({
                'success': False,
                'error': str(e),
                'platform': self.platform
            })


class AssetMappingUI(QWidget):
    """资产查询UI组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.logger = logging.getLogger(__name__)
        
        # 初始化API实例
        self.fofa_api = None
        self.hunter_api = None
        self.quake_api = None
        
        # 搜索线程
        self.search_thread = None
        
        # 结果存储
        self.unified_results = {}
        self.fofa_results = []
        self.hunter_results = []
        self.quake_results = []
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        
        # 创建子标签页
        self.tab_widget = QTabWidget()
        
        # 创建统一查询标签页
        self.create_unified_search_tab()
        
        # 创建FOFA标签页
        self.create_fofa_tab()
        
        # 创建Hunter标签页
        self.create_hunter_tab()
        
        # 创建Quake标签页
        self.create_quake_tab()
        
        main_layout.addWidget(self.tab_widget)
    
    def create_unified_search_tab(self):
        """创建统一查询标签页"""
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
        left_widget = self.create_unified_controls()
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_unified_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 1)  # 左侧
        main_layout.setStretch(1, 2)  # 右侧
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "🔄 统一查询")
    
    def create_unified_controls(self) -> QWidget:
        """创建统一查询控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # API配置区域
        api_group = QGroupBox("🔑 API配置")
        api_layout = QVBoxLayout(api_group)
        
        # FOFA API配置
        fofa_email_layout = QHBoxLayout()
        fofa_email_layout.addWidget(QLabel("FOFA Email:"))
        self.unified_fofa_email = QLineEdit()
        self.unified_fofa_email.setPlaceholderText("请输入FOFA注册邮箱...")
        fofa_email_layout.addWidget(self.unified_fofa_email)
        api_layout.addLayout(fofa_email_layout)
        
        fofa_key_layout = QHBoxLayout()
        fofa_key_layout.addWidget(QLabel("FOFA API Key:"))
        self.unified_fofa_key = QLineEdit()
        self.unified_fofa_key.setPlaceholderText("请输入FOFA API Key...")
        self.unified_fofa_key.setEchoMode(QLineEdit.EchoMode.Password)
        fofa_key_layout.addWidget(self.unified_fofa_key)
        api_layout.addLayout(fofa_key_layout)
        
        # Hunter API配置
        hunter_layout = QHBoxLayout()
        hunter_layout.addWidget(QLabel("Hunter API Key:"))
        self.unified_hunter_key = QLineEdit()
        self.unified_hunter_key.setPlaceholderText("请输入Hunter API Key...")
        self.unified_hunter_key.setEchoMode(QLineEdit.EchoMode.Password)
        hunter_layout.addWidget(self.unified_hunter_key)
        api_layout.addLayout(hunter_layout)
        
        # Quake API配置
        quake_layout = QHBoxLayout()
        quake_layout.addWidget(QLabel("Quake API Key:"))
        self.unified_quake_key = QLineEdit()
        self.unified_quake_key.setPlaceholderText("请输入Quake API Key...")
        self.unified_quake_key.setEchoMode(QLineEdit.EchoMode.Password)
        quake_layout.addWidget(self.unified_quake_key)
        api_layout.addLayout(quake_layout)
        
        layout.addWidget(api_group)
        
        # 查询配置区域
        search_group = QGroupBox("🔍 统一查询")
        search_layout = QVBoxLayout(search_group)
        
        # 平台选择
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("选择平台:"))
        
        self.unified_fofa_check = QCheckBox("FOFA")
        self.unified_fofa_check.setChecked(True)
        self.unified_hunter_check = QCheckBox("Hunter")
        self.unified_hunter_check.setChecked(True)
        self.unified_quake_check = QCheckBox("Quake")
        self.unified_quake_check.setChecked(True)
        
        platform_layout.addWidget(self.unified_fofa_check)
        platform_layout.addWidget(self.unified_hunter_check)
        platform_layout.addWidget(self.unified_quake_check)
        platform_layout.addStretch()
        search_layout.addLayout(platform_layout)
        
        # 查询模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("查询模式:"))
        
        self.unified_single_radio = QRadioButton("单个查询")
        self.unified_single_radio.setChecked(True)
        self.unified_batch_radio = QRadioButton("批量查询")
        
        mode_layout.addWidget(self.unified_single_radio)
        mode_layout.addWidget(self.unified_batch_radio)
        mode_layout.addStretch()
        search_layout.addLayout(mode_layout)
        
        # 单个查询区域
        self.unified_single_widget = QWidget()
        single_layout = QVBoxLayout(self.unified_single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        
        query_layout = QHBoxLayout()
        query_layout.addWidget(QLabel("查询语句:"))
        self.unified_query_input = QLineEdit()
        self.unified_query_input.setPlaceholderText("输入查询语句，系统将自动识别并转换为各平台语法...")
        query_layout.addWidget(self.unified_query_input)
        single_layout.addLayout(query_layout)
        
        search_layout.addWidget(self.unified_single_widget)
        
        # 批量查询区域
        self.unified_batch_widget = QWidget()
        batch_layout = QVBoxLayout(self.unified_batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        
        file_layout = QHBoxLayout()
        self.unified_file_btn = QPushButton("📂 选择查询文件")
        self.unified_file_btn.clicked.connect(self.select_unified_batch_file)
        file_layout.addWidget(self.unified_file_btn)
        
        self.unified_file_label = QLabel("未选择文件")
        # 移除硬编码样式，使用全局样式
        self.unified_file_label.setProperty("class", "file-label-inactive")
        file_layout.addWidget(self.unified_file_label)
        batch_layout.addLayout(file_layout)
        
        self.unified_batch_widget.setVisible(False)
        search_layout.addWidget(self.unified_batch_widget)
        
        # 查询选项
        options_layout = QHBoxLayout()
        self.unified_get_all_check = QCheckBox("获取全部数据")
        self.unified_debug_check = QCheckBox("调试模式")
        
        options_layout.addWidget(self.unified_get_all_check)
        options_layout.addWidget(self.unified_debug_check)
        
        options_layout.addWidget(QLabel("限制:"))
        self.unified_limit_input = QSpinBox()
        self.unified_limit_input.setMinimum(1)
        self.unified_limit_input.setMaximum(10000)
        self.unified_limit_input.setValue(100)
        options_layout.addWidget(self.unified_limit_input)
        options_layout.addStretch()
        
        search_layout.addLayout(options_layout)
        layout.addWidget(search_group)
        
        # 操作按钮
        self.unified_search_btn = QPushButton("🚀 开始统一查询")
        self.unified_search_btn.clicked.connect(self.start_unified_search)
        layout.addWidget(self.unified_search_btn)
        
        # 导出按钮
        export_layout = QHBoxLayout()
        self.unified_export_btn = QPushButton("💾 导出结果")
        self.unified_export_btn.clicked.connect(self.export_unified_results)
        self.unified_export_btn.setEnabled(False)
        export_layout.addWidget(self.unified_export_btn)
        
        self.unified_clear_btn = QPushButton("🗑️ 清空结果")
        self.unified_clear_btn.clicked.connect(self.clear_unified_results)
        export_layout.addWidget(self.unified_clear_btn)
        
        layout.addLayout(export_layout)
        layout.addStretch()
        
        return widget
    
    def create_unified_results(self) -> QWidget:
        """创建统一查询结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.unified_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.unified_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.unified_status_label.style().polish(self.unified_status_label)
        layout.addWidget(self.unified_status_label)
        
        # 现代化进度条
        self.unified_progress_bar = QProgressBar()
        self.unified_progress_bar.setVisible(False)
        self.unified_progress_bar.setMinimum(0)
        self.unified_progress_bar.setMaximum(100)
        self.unified_progress_bar.setValue(0)
        self.unified_progress_bar.setTextVisible(True)
        self.unified_progress_bar.setFormat("查询进度: %p%")
        # 设置进度条样式属性，确保在暗色模式下可见
        self.unified_progress_bar.setProperty("class", "query-progress-bar")
        # 移除硬编码样式，使用全局样式
        # 刷新样式
        self.unified_progress_bar.style().polish(self.unified_progress_bar)
        layout.addWidget(self.unified_progress_bar)
        
        # 结果显示
        result_label = QLabel("📊 统一查询结果")
        result_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(result_label)
        
        self.unified_result_text = QTextEdit()
        self.unified_result_text.setReadOnly(True)
        layout.addWidget(self.unified_result_text)
        
        return widget
    
    def create_fofa_tab(self):
        """创建FOFA标签页"""
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
        left_widget = self.create_fofa_controls()
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_fofa_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 1)  # 左侧
        main_layout.setStretch(1, 2)  # 右侧
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "🔍 FOFA")
    
    def create_hunter_tab(self):
        """创建Hunter标签页"""
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
        left_widget = self.create_hunter_controls()
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_hunter_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 1)  # 左侧
        main_layout.setStretch(1, 2)  # 右侧
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "🦅 Hunter")
    
    def create_quake_tab(self):
        """创建Quake标签页"""
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
        left_widget = self.create_quake_controls()
        main_layout.addWidget(left_widget)
        
        # 右侧结果显示区域
        right_widget = self.create_quake_results()
        main_layout.addWidget(right_widget)
        
        # 设置比例
        main_layout.setStretch(0, 1)  # 左侧
        main_layout.setStretch(1, 2)  # 右侧
        
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(tab, "🌍 Quake")
    
    def setup_connections(self):
        """设置信号连接"""
        # 统一查询模式切换
        self.unified_single_radio.toggled.connect(self.toggle_unified_query_mode)
        self.unified_batch_radio.toggled.connect(self.toggle_unified_query_mode)
    
    def toggle_unified_query_mode(self):
        """切换统一查询模式"""
        is_single = self.unified_single_radio.isChecked()
        self.unified_single_widget.setVisible(is_single)
        self.unified_batch_widget.setVisible(not is_single)
    
    def select_unified_batch_file(self):
        """选择统一查询批量文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择查询文件", "",
            "Text files (*.txt);;All files (*.*)"
        )
        
        if file_path:
            self.unified_batch_file_path = file_path
            self.unified_file_label.setText(os.path.basename(file_path))
            # 移除硬编码样式，使用全局样式
            self.unified_file_label.setProperty("class", "file-label-active")
    
    def start_unified_search(self):
        """开始统一查询"""
        # 检查查询模式
        if self.unified_single_radio.isChecked():
            # 单个查询模式
            query = self.unified_query_input.text().strip()
            if not query:
                QMessageBox.warning(self, "警告", "请输入查询语句")
                return
            queries = [query]
        else:
            # 批量查询模式
            if not hasattr(self, 'unified_batch_file_path') or not self.unified_batch_file_path:
                QMessageBox.warning(self, "警告", "请选择查询文件")
                return
            
            try:
                with open(self.unified_batch_file_path, 'r', encoding='utf-8') as f:
                    queries = [line.strip() for line in f.readlines() if line.strip()]
                
                if not queries:
                    QMessageBox.warning(self, "警告", "查询文件为空或格式不正确")
                    return
                    
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取查询文件失败: {str(e)}")
                return
        
        # 检查至少选择一个平台
        platforms = []
        if self.unified_fofa_check.isChecked():
            platforms.append('fofa')
        if self.unified_hunter_check.isChecked():
            platforms.append('hunter')
        if self.unified_quake_check.isChecked():
            platforms.append('quake')
        
        if not platforms:
            QMessageBox.warning(self, "警告", "请至少选择一个查询平台")
            return
        
        # 准备API配置
        api_configs = {
            'fofa': {
                'api_key': self.unified_fofa_key.text().strip(),
                'email': self.unified_fofa_email.text().strip()
            },
            'hunter': {'api_key': self.unified_hunter_key.text().strip()},
            'quake': {'api_key': self.unified_quake_key.text().strip()}
        }
        
        # 启动查询线程
        self.unified_status_label.setText("🚀 准备开始统一查询...")
        self.unified_status_label.setProperty("class", "status-label-waiting")
        self.unified_status_label.style().polish(self.unified_status_label)
        self.unified_progress_bar.setVisible(True)
        self.unified_progress_bar.setValue(0)
        self.unified_search_btn.setEnabled(False)
        
        self.search_thread = UnifiedSearchThread(platforms, queries, api_configs)
        self.search_thread.progress_updated.connect(self.update_unified_progress)
        self.search_thread.progress_percentage.connect(self.update_unified_progress_bar)
        self.search_thread.search_completed.connect(self.on_unified_search_completed)
        
        # 注册线程到主窗口管理器
        parent = self.parent()
        if hasattr(parent, 'register_thread'):
            parent.register_thread(self.search_thread)  # type: ignore
        
        self.search_thread.start()
    
    def update_unified_progress(self, message: str):
        """更新统一查询进度"""
        self.unified_status_label.setText(message)
        self.unified_status_label.setProperty("class", "status-label-waiting")
        self.unified_status_label.style().polish(self.unified_status_label)
    
    def update_unified_progress_bar(self, percentage: int):
        """更新统一查询进度条"""
        self.unified_progress_bar.setValue(percentage)
        # 刷新样式
        self.unified_progress_bar.style().polish(self.unified_progress_bar)
    
    def on_unified_search_completed(self, result: Dict):
        """统一查询完成"""
        # 确保进度条显示100%
        self.unified_progress_bar.setValue(100)
        # 刷新样式
        self.unified_progress_bar.style().polish(self.unified_progress_bar)
        
        # 延迟隐藏进度条，让用户看到完成状态
        QTimer.singleShot(1500, lambda: self.unified_progress_bar.setVisible(False))
        
        self.unified_search_btn.setEnabled(True)
        
        if result.get('success', False):
            self.unified_results = result.get('results', {})
            self.display_unified_results()
            self.unified_export_btn.setEnabled(True)
            
            # 统计查询结果
            total_results = 0
            successful_platforms = 0
            for query_results in self.unified_results.values():
                for platform_result in query_results.values():
                    if platform_result.get('success', False):
                        total_results += len(platform_result.get('results', []))
                        successful_platforms += 1
            
            self.unified_status_label.setText(
                f"🎉 统一查询完成！共处理 {result.get('total_queries', 0)} 个查询，"
                f"获得 {total_results} 条结果，{successful_platforms} 个平台成功"
            )
            self.unified_status_label.setProperty("class", "status-label-success")
            self.unified_status_label.style().polish(self.unified_status_label)
        else:
            error_msg = result.get('error', '未知错误')
            QMessageBox.critical(self, "错误", f"统一查询失败: {error_msg}")
            self.unified_status_label.setText("❌ 统一查询失败")
            self.unified_status_label.setProperty("class", "status-label-error")
            self.unified_status_label.style().polish(self.unified_status_label)
    
    def display_unified_results(self):
        """显示统一查询结果"""
        if not self.unified_results:
            self.unified_result_text.setText("没有查询结果")
            return
        
        result_text = "🔍 统一查询结果详情\n"
        result_text += "=" * 60 + "\n\n"
        
        total_results = 0
        successful_platforms = 0
        
        for query, platforms_results in self.unified_results.items():
            result_text += f"🎯 查询语句: {query}\n"
            result_text += "-" * 40 + "\n"
            
            for platform, platform_result in platforms_results.items():
                platform_icon = {"fofa": "🌐", "hunter": "🦅", "quake": "⚡"}.get(platform, "🔍")
                result_text += f"\n{platform_icon} 【{platform.upper()}】\n"
                
                if platform_result.get('success', False):
                    if 'results' in platform_result and platform_result['results'] is not None:
                        count = len(platform_result['results'])
                        total_results += count
                        successful_platforms += 1
                        result_text += f"  ✅ 查询成功 - 找到 {count} 条结果\n"
                        
                        # 显示前几条详细结果
                        for i, item in enumerate(platform_result['results'][:5]):
                            if isinstance(item, dict):
                                # 根据平台显示不同的信息
                                if platform == 'fofa':
                                    host = item.get('host', 'N/A')
                                    ip = item.get('ip', 'N/A')
                                    port = item.get('port', 'N/A')
                                    title = item.get('title', 'N/A')[:30] + '...' if len(item.get('title', '')) > 30 else item.get('title', 'N/A')
                                    result_text += f"    {i+1}. {host} ({ip}:{port}) - {title}\n"
                                elif platform == 'hunter':
                                    url = item.get('url', item.get('domain', 'N/A'))
                                    ip = item.get('ip', 'N/A')
                                    port = item.get('port', 'N/A')
                                    title = item.get('web_title', 'N/A')
                                    if len(title) > 30:
                                        title = title[:30] + '...'
                                    domain = item.get('domain', 'N/A')
                                    country = item.get('country', '')
                                    province = item.get('province', '')
                                    city = item.get('city', '')
                                    location = f"{country} {province} {city}".strip()
                                    
                                    result_text += f"    {i+1}. 🌐 {url}\n"
                                    result_text += f"       📍 IP: {ip}:{port}\n"
                                    if title != 'N/A':
                                        result_text += f"       📄 标题: {title}\n"
                                    if domain != 'N/A':
                                        result_text += f"       🌍 域名: {domain}\n"
                                    if location:
                                        result_text += f"       🗺️ 位置: {location}\n"
                                    
                                    # 显示组件信息
                                    components = item.get('component', [])
                                    if components:
                                        comp_names = []
                                        for comp in components:
                                            if isinstance(comp, dict):
                                                name = comp.get('name', '')
                                                version = comp.get('version', '')
                                                if name:
                                                    comp_names.append(f"{name} {version}".strip())
                                        if comp_names:
                                            result_text += f"       🔧 组件: {', '.join(comp_names)}\n"
                                elif platform == 'quake':
                                    ip = item.get('ip', 'N/A')
                                    port = item.get('port', 'N/A')
                                    domain = item.get('domain', '')
                                    hostname = item.get('hostname', '')
                                    org = item.get('org', '')
                                    
                                    result_text += f"    {i+1}. 🌐 {ip}:{port}\n"
                                    
                                    if domain:
                                        result_text += f"       🌍 域名: {domain}\n"
                                    if hostname:
                                        result_text += f"       🏠 主机名: {hostname}\n"
                                    if org:
                                        result_text += f"       🏢 组织: {org}\n"
                                    
                                    # 服务信息
                                    service_info = item.get('service', {})
                                    if service_info:
                                        service_name = service_info.get('name', '')
                                        if service_name:
                                            result_text += f"       🔧 服务: {service_name}\n"
                                        
                                        # HTTP信息
                                        http_info = service_info.get('http', {})
                                        if http_info:
                                            title = http_info.get('title', '')
                                            if title:
                                                title_display = title[:30] + '...' if len(title) > 30 else title
                                                result_text += f"       📄 标题: {title_display}\n"
                                            
                                            server = http_info.get('server', '')
                                            if server:
                                                result_text += f"       🖥️ 服务器: {server}\n"
                                    
                                    # 地理位置
                                    location = item.get('location', {})
                                    if location:
                                        country = location.get('country_cn', location.get('country_en', ''))
                                        province = location.get('province_cn', location.get('province_en', ''))
                                        city = location.get('city_cn', location.get('city_en', ''))
                                        
                                        location_str = ''
                                        if country:
                                            location_str += country
                                        if province:
                                            location_str += f' {province}'
                                        if city:
                                            location_str += f' {city}'
                                        
                                        if location_str:
                                            result_text += f"       🗺️ 位置: {location_str.strip()}\n"
                                    
                                    # 组件信息
                                    components = item.get('components', [])
                                    if components:
                                        comp_names = []
                                        for comp in components[:3]:  # 只显示前3个组件
                                            if isinstance(comp, dict):
                                                name = comp.get('product_name_cn', comp.get('product_name_en', ''))
                                                if name:
                                                    comp_names.append(name)
                                        
                                        if comp_names:
                                            result_text += f"       🔧 组件: {', '.join(comp_names)}\n"
                                            if len(components) > 3:
                                                result_text += f"       📦 还有 {len(components) - 3} 个组件...\n"
                                else:
                                    # 通用显示
                                    if 'host' in item:
                                        result_text += f"    {i+1}. {item.get('host', 'N/A')}\n"
                                    elif 'ip' in item:
                                        result_text += f"    {i+1}. {item.get('ip', 'N/A')}\n"
                                    else:
                                        result_text += f"    {i+1}. {str(item)[:50]}...\n"
                        
                        if count > 5:
                            result_text += f"    📋 ... 还有 {count - 5} 条结果\n"
                    else:
                        result_text += "  ⚠️ 查询成功，但无结果数据\n"
                else:
                    error_msg = platform_result.get('error', '未知错误')
                    result_text += f"  ❌ 查询失败: {error_msg}\n"
            
            result_text += "\n" + "=" * 60 + "\n\n"
        
        # 添加汇总信息
        result_text += f"📈 查询汇总:\n"
        result_text += f"  • 总结果数: {total_results} 条\n"
        result_text += f"  • 成功平台: {successful_platforms} 个\n"
        result_text += f"  • 查询语句: {len(self.unified_results)} 条\n"
        
        self.unified_result_text.setText(result_text)
    
    def export_unified_results(self):
        """导出统一查询结果"""
        if not self.unified_results:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出统一查询结果", "",
            "Excel files (*.xlsx);;JSON files (*.json);;Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.xlsx'):
                self._export_unified_to_excel(file_path)
            elif file_path.endswith('.json'):
                self._export_unified_to_json(file_path)
            else:
                self._export_unified_to_text(file_path)
            
            QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def _export_unified_to_excel(self, file_path: str):
        """导出到Excel文件"""
        import pandas as pd
        
        all_data = []
        
        for query, platforms_results in self.unified_results.items():
            for platform, platform_result in platforms_results.items():
                if platform_result.get('success', False) and 'results' in platform_result:
                    for item in platform_result['results']:
                        if isinstance(item, dict):
                            item_copy = item.copy()
                            item_copy['query'] = query
                            item_copy['platform'] = platform
                            all_data.append(item_copy)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_excel(file_path, index=False)
    
    def _export_unified_to_json(self, file_path: str):
        """导出到JSON文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.unified_results, f, ensure_ascii=False, indent=2)
    
    def _export_unified_to_text(self, file_path: str):
        """导出到表格格式的文本文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            # 使用制表符分隔，避免数据截断
            headers = ['序号', '查询语句', '平台', 'IP地址', '端口', '域名/URL', '标题', '服务', '位置', '状态']
            
            # 写入表头（使用制表符分隔）
            f.write('\t'.join(headers) + '\n')
            
            # 写入数据行
            row_num = 1
            for query, platforms_results in self.unified_results.items():
                for platform, platform_result in platforms_results.items():
                    if platform_result.get('success', False):
                        if 'results' in platform_result and platform_result['results'] is not None:
                            for item in platform_result['results']:
                                if isinstance(item, dict):
                                    # 根据平台提取数据
                                    if platform == 'fofa':
                                        ip = item.get('ip', '')
                                        port = item.get('port', '')
                                        host = item.get('host', '')
                                        title = item.get('title', '')
                                        country = item.get('country', '')
                                        service = ''
                                    elif platform == 'hunter':
                                        ip = item.get('ip', '')
                                        port = item.get('port', '')
                                        host = item.get('url', item.get('domain', ''))
                                        title = item.get('web_title', '')
                                        country = item.get('country', '')
                                        province = item.get('province', '')
                                        city = item.get('city', '')
                                        location = f"{country} {province} {city}".strip()
                                        country = location
                                        service = ''
                                    elif platform == 'quake':
                                        ip = item.get('ip', '')
                                        port = item.get('port', '')
                                        host = item.get('hostname', '')
                                        title = ''
                                        country = ''
                                        service = item.get('service', {}).get('name', '') if isinstance(item.get('service'), dict) else ''
                                    else:
                                        ip = port = host = title = country = service = ''
                                    
                                    row_data = [
                                        str(row_num),  # 序号
                                        query,  # 查询语句
                                        platform.upper(),  # 平台
                                        ip,  # IP地址
                                        str(port),  # 端口
                                        host,  # 域名/URL
                                        title,  # 标题
                                        service,  # 服务
                                        country,  # 位置
                                        '成功'  # 状态
                                    ]
                                    
                                    # 写入行数据（使用制表符分隔）
                                    f.write('\t'.join(str(item) for item in row_data) + '\n')
                                    row_num += 1
                        else:
                            # 查询成功但无结果
                            row_data = [
                                str(row_num),  # 序号
                                query,  # 查询语句
                                platform.upper(),  # 平台
                                '', '', '', '', '', '',  # IP地址, 端口, 域名/URL, 标题, 服务, 位置
                                '无结果'  # 状态
                            ]
                            
                            f.write('\t'.join(str(item) for item in row_data) + '\n')
                            row_num += 1
                    else:
                        # 查询失败
                        row_data = [
                            str(row_num),  # 序号
                            query,  # 查询语句
                            platform.upper(),  # 平台
                            '', '', '', '', '', '',  # IP地址, 端口, 域名/URL, 标题, 服务, 位置
                            '失败'  # 状态
                        ]
                        
                        f.write('\t'.join(str(item) for item in row_data) + '\n')
                        row_num += 1
    
    def clear_unified_results(self):
        """清空统一查询结果"""
        self.unified_results.clear()
        self.unified_result_text.clear()
        self.unified_status_label.setText("等待查询...")
        self.unified_status_label.setProperty("class", "status-label-waiting")
        self.unified_status_label.style().polish(self.unified_status_label)
        self.unified_export_btn.setEnabled(False)
    
    def get_config(self) -> Dict:
        """获取配置信息"""
        config = {}
        
        # 获取统一查询的API配置
        if hasattr(self, 'unified_fofa_key'):
            config['fofa_api_key'] = self.unified_fofa_key.text()
        if hasattr(self, 'unified_hunter_key'):
            config['hunter_api_key'] = self.unified_hunter_key.text()
        if hasattr(self, 'unified_quake_key'):
            config['quake_api_key'] = self.unified_quake_key.text()
        
        # 获取独立标签页的API配置
        if hasattr(self, 'fofa_key'):
            config['fofa_api_key'] = self.fofa_key.text()
        if hasattr(self, 'fofa_email'):
            config['fofa_email'] = self.fofa_email.text()
        if hasattr(self, 'hunter_key'):
            config['hunter_api_key'] = self.hunter_key.text()
        if hasattr(self, 'quake_key'):
            config['quake_api_key'] = self.quake_key.text()
        
        return config
    
    def set_config(self, config: Dict):
        """设置配置信息"""
        # 设置统一查询的API配置
        if hasattr(self, 'unified_fofa_key') and 'fofa_api_key' in config:
            self.unified_fofa_key.setText(config['fofa_api_key'])
        if hasattr(self, 'unified_hunter_key') and 'hunter_api_key' in config:
            self.unified_hunter_key.setText(config['hunter_api_key'])
        if hasattr(self, 'unified_quake_key') and 'quake_api_key' in config:
            self.unified_quake_key.setText(config['quake_api_key'])
        
        # 设置独立标签页的API配置
        if hasattr(self, 'fofa_key') and 'fofa_api_key' in config:
            self.fofa_key.setText(config['fofa_api_key'])
        if hasattr(self, 'fofa_email') and 'fofa_email' in config:
            self.fofa_email.setText(config['fofa_email'])
        if hasattr(self, 'hunter_key') and 'hunter_api_key' in config:
            self.hunter_key.setText(config['hunter_api_key'])
        if hasattr(self, 'quake_key') and 'quake_api_key' in config:
            self.quake_key.setText(config['quake_api_key'])
    
    def get_all_results(self) -> List[Dict]:
        """获取所有查询结果"""
        all_results = []
        
        # 添加统一查询结果
        for query, platforms_results in self.unified_results.items():
            for platform, platform_result in platforms_results.items():
                if platform_result.get('success', False) and 'results' in platform_result:
                    for item in platform_result['results']:
                        if isinstance(item, dict):
                            item_copy = item.copy()
                            item_copy['query'] = query
                            item_copy['platform'] = platform
                            item_copy['source'] = 'unified_search'
                            all_results.append(item_copy)
        
        # 添加其他平台的结果
        for result in self.fofa_results:
            result['source'] = 'fofa'
            all_results.append(result)
        
        for result in self.hunter_results:
            result['source'] = 'hunter'
            all_results.append(result)
        
        for result in self.quake_results:
            result['source'] = 'quake'
            all_results.append(result)
        
        return all_results
    
    def create_fofa_controls(self) -> QWidget:
        """创建FOFA控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # API配置区域
        api_group = QGroupBox("🔑 API配置")
        api_layout = QVBoxLayout(api_group)
        
        # FOFA API配置
        fofa_layout = QHBoxLayout()
        fofa_layout.addWidget(QLabel("FOFA API Key:"))
        self.fofa_key = QLineEdit()
        self.fofa_key.setPlaceholderText("请输入FOFA API Key...")
        self.fofa_key.setEchoMode(QLineEdit.EchoMode.Password)
        fofa_layout.addWidget(self.fofa_key)
        api_layout.addLayout(fofa_layout)
        
        # FOFA Email配置
        email_layout = QHBoxLayout()
        email_layout.addWidget(QLabel("FOFA Email:"))
        self.fofa_email = QLineEdit()
        self.fofa_email.setPlaceholderText("请输入FOFA Email...")
        email_layout.addWidget(self.fofa_email)
        api_layout.addLayout(email_layout)
        
        layout.addWidget(api_group)
        
        # 查询配置区域
        search_group = QGroupBox("🔍 FOFA查询")
        search_layout = QVBoxLayout(search_group)
        
        # 查询语句
        query_layout = QHBoxLayout()
        query_layout.addWidget(QLabel("查询语句:"))
        self.fofa_query_input = QLineEdit()
        self.fofa_query_input.setPlaceholderText("输入FOFA查询语句...")
        query_layout.addWidget(self.fofa_query_input)
        search_layout.addLayout(query_layout)
        
        # 查询参数
        params_layout = QGridLayout()
        
        params_layout.addWidget(QLabel("页码:"), 0, 0)
        self.fofa_page = QSpinBox()
        self.fofa_page.setMinimum(1)
        self.fofa_page.setMaximum(10000)
        self.fofa_page.setValue(1)
        params_layout.addWidget(self.fofa_page, 0, 1)
        
        params_layout.addWidget(QLabel("每页数量:"), 0, 2)
        self.fofa_size = QSpinBox()
        self.fofa_size.setMinimum(1)
        self.fofa_size.setMaximum(10000)
        self.fofa_size.setValue(100)
        params_layout.addWidget(self.fofa_size, 0, 3)
        
        search_layout.addLayout(params_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.fofa_search_btn = QPushButton("🔍 开始查询")
        self.fofa_search_btn.clicked.connect(self.start_fofa_search)
        btn_layout.addWidget(self.fofa_search_btn)
        
        self.fofa_export_btn = QPushButton("💾 导出结果")
        self.fofa_export_btn.clicked.connect(self.export_fofa_results)
        self.fofa_export_btn.setEnabled(False)
        btn_layout.addWidget(self.fofa_export_btn)
        
        self.fofa_clear_btn = QPushButton("🗑️ 清空结果")
        self.fofa_clear_btn.clicked.connect(self.clear_fofa_results)
        btn_layout.addWidget(self.fofa_clear_btn)
        
        # 语法文档按钮
        fofa_doc_button = QPushButton("📖 查看语法文档")
        fofa_doc_button.clicked.connect(self.show_fofa_syntax_doc)
        btn_layout.addWidget(fofa_doc_button)
        
        search_layout.addLayout(btn_layout)
        layout.addWidget(search_group)
        
        layout.addStretch()
        return widget
    
    def create_fofa_results(self) -> QWidget:
        """创建FOFA结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.fofa_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.fofa_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.fofa_status_label.style().polish(self.fofa_status_label)
        layout.addWidget(self.fofa_status_label)
        
        # 结果显示
        result_label = QLabel("📊 查询结果")
        result_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(result_label)
        
        self.fofa_result_text = QTextEdit()
        self.fofa_result_text.setReadOnly(True)
        layout.addWidget(self.fofa_result_text)
        
        return widget
    
    def start_fofa_search(self):
        """开始FOFA查询"""
        api_key = self.fofa_key.text().strip()
        email = self.fofa_email.text().strip()
        query = self.fofa_query_input.text().strip()
        
        if not api_key or not email or not query:
            QMessageBox.warning(self, "警告", "请填写完整的API配置和查询语句")
            return
        
        try:
            self.fofa_status_label.setText("正在查询...")
            fofa_api = FOFASearcher(api_key=api_key, email=email)
            
            result = fofa_api.search(
                query=query,
                page=self.fofa_page.value(),
                size=self.fofa_size.value()
            )
            
            if result and result.get('success'):
                self.fofa_results = result.get('results', [])
                self.fofa_result_text.setText(json.dumps(result, indent=2, ensure_ascii=False))
                self.fofa_status_label.setText(f"查询完成，共找到 {len(self.fofa_results)} 条结果")
                self.fofa_status_label.setProperty("class", "status-label-success")
                self.fofa_status_label.style().polish(self.fofa_status_label)
                self.fofa_export_btn.setEnabled(True)
            else:
                self.fofa_status_label.setText("查询失败")
                self.fofa_status_label.setProperty("class", "status-label-error")
                self.fofa_status_label.style().polish(self.fofa_status_label)
                self.fofa_result_text.setText(f"查询失败: {result.get('error', '未知错误')}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"查询失败: {str(e)}")
            self.fofa_status_label.setText("查询失败")
    
    def clear_fofa_results(self):
        """清空FOFA结果"""
        self.fofa_results.clear()
        self.fofa_result_text.clear()
        self.fofa_status_label.setText("等待查询...")
        self.fofa_status_label.setProperty("class", "status-label-waiting")
        self.fofa_status_label.style().polish(self.fofa_status_label)
        self.fofa_export_btn.setEnabled(False)
    
    def export_fofa_results(self):
        """导出FOFA查询结果"""
        if not self.fofa_results:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出FOFA查询结果", "",
            "Excel files (*.xlsx);;JSON files (*.json);;Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.xlsx'):
                self._export_fofa_to_excel(file_path)
            elif file_path.endswith('.json'):
                self._export_fofa_to_json(file_path)
            else:
                self._export_fofa_to_text(file_path)
            
            QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def _export_fofa_to_excel(self, file_path: str):
        """导出FOFA结果到Excel文件"""
        import pandas as pd
        
        all_data = []
        for i, item in enumerate(self.fofa_results, 1):
            data_row = {
                '序号': i,
                'IP地址': item.get('ip', 'N/A'),
                '端口': item.get('port', 'N/A'),
                'Host': item.get('host', 'N/A'),
                '标题': item.get('title', 'N/A'),
                '国家': item.get('country', 'N/A'),
                '城市': item.get('city', 'N/A'),
                '服务器': item.get('server', 'N/A'),
            }
            all_data.append(data_row)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_excel(file_path, index=False)
    
    def _export_fofa_to_json(self, file_path: str):
        """导出FOFA结果到JSON文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.fofa_results, f, ensure_ascii=False, indent=2)
    
    def _export_fofa_to_text(self, file_path: str):
        """导出FOFA结果到文本文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            headers = ['序号', 'IP地址', '端口', 'Host', '标题', '国家', '城市', '服务器']
            f.write('\t'.join(headers) + '\n')
            f.write('=' * 100 + '\n')
            
            for i, item in enumerate(self.fofa_results, 1):
                row = [
                    str(i),
                    str(item.get('ip', 'N/A')),
                    str(item.get('port', 'N/A')),
                    str(item.get('host', 'N/A')),
                    str(item.get('title', 'N/A')),
                    str(item.get('country', 'N/A')),
                    str(item.get('city', 'N/A')),
                    str(item.get('server', 'N/A')),
                ]
                f.write('\t'.join(row) + '\n')
            
            f.write('\n' + '=' * 100 + '\n')
            f.write(f'总计: {len(self.fofa_results)} 条结果\n')
    
    def create_hunter_controls(self) -> QWidget:
        """创建Hunter控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # API配置区域
        api_group = QGroupBox("🔑 API配置")
        api_layout = QVBoxLayout(api_group)
        
        # Hunter API配置
        hunter_layout = QHBoxLayout()
        hunter_layout.addWidget(QLabel("Hunter API Key:"))
        self.hunter_key = QLineEdit()
        self.hunter_key.setPlaceholderText("请输入Hunter API Key...")
        self.hunter_key.setEchoMode(QLineEdit.EchoMode.Password)
        hunter_layout.addWidget(self.hunter_key)
        api_layout.addLayout(hunter_layout)
        
        layout.addWidget(api_group)
        
        # 查询配置区域
        search_group = QGroupBox("🔍 Hunter查询")
        search_layout = QVBoxLayout(search_group)
        
        # 查询语句
        query_layout = QHBoxLayout()
        query_layout.addWidget(QLabel("查询语句:"))
        self.hunter_query_input = QLineEdit()
        self.hunter_query_input.setPlaceholderText("输入Hunter查询语句...")
        query_layout.addWidget(self.hunter_query_input)
        search_layout.addLayout(query_layout)
        
        # 查询参数
        params_layout = QGridLayout()
        
        params_layout.addWidget(QLabel("页码:"), 0, 0)
        self.hunter_page = QSpinBox()
        self.hunter_page.setMinimum(1)
        self.hunter_page.setMaximum(10000)
        self.hunter_page.setValue(1)
        params_layout.addWidget(self.hunter_page, 0, 1)
        
        params_layout.addWidget(QLabel("每页数量:"), 0, 2)
        self.hunter_size = QSpinBox()
        self.hunter_size.setMinimum(1)
        self.hunter_size.setMaximum(10000)
        self.hunter_size.setValue(100)
        params_layout.addWidget(self.hunter_size, 0, 3)
        
        params_layout.addWidget(QLabel("是否为Web:"), 1, 0)
        self.hunter_is_web = QComboBox()
        self.hunter_is_web.addItems(["全部", "是", "否"])
        self.hunter_is_web.setCurrentIndex(0)
        params_layout.addWidget(self.hunter_is_web, 1, 1)
        
        params_layout.addWidget(QLabel("端口过滤:"), 1, 2)
        self.hunter_port_filter = QCheckBox("启用")
        params_layout.addWidget(self.hunter_port_filter, 1, 3)
        
        search_layout.addLayout(params_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.hunter_search_btn = QPushButton("🔍 开始查询")
        self.hunter_search_btn.clicked.connect(self.start_hunter_search)
        btn_layout.addWidget(self.hunter_search_btn)
        
        self.hunter_export_btn = QPushButton("💾 导出结果")
        self.hunter_export_btn.clicked.connect(self.export_hunter_results)
        self.hunter_export_btn.setEnabled(False)
        btn_layout.addWidget(self.hunter_export_btn)
        
        self.hunter_clear_btn = QPushButton("🗑️ 清空结果")
        self.hunter_clear_btn.clicked.connect(self.clear_hunter_results)
        btn_layout.addWidget(self.hunter_clear_btn)
        
        # 语法文档按钮
        hunter_doc_button = QPushButton("📖 查看语法文档")
        hunter_doc_button.clicked.connect(self.show_hunter_syntax_doc)
        btn_layout.addWidget(hunter_doc_button)
        
        search_layout.addLayout(btn_layout)
        layout.addWidget(search_group)
        
        layout.addStretch()
        return widget
    
    def create_hunter_results(self) -> QWidget:
        """创建Hunter结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.hunter_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.hunter_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.hunter_status_label.style().polish(self.hunter_status_label)
        layout.addWidget(self.hunter_status_label)
        
        # 结果显示
        result_label = QLabel("📊 查询结果")
        result_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(result_label)
        
        self.hunter_result_text = QTextEdit()
        self.hunter_result_text.setReadOnly(True)
        layout.addWidget(self.hunter_result_text)
        
        return widget
    
    def start_hunter_search(self):
        """开始Hunter查询"""
        api_key = self.hunter_key.text().strip()
        query = self.hunter_query_input.text().strip()
        
        if not api_key or not query:
            QMessageBox.warning(self, "警告", "请填写完整的API配置和查询语句")
            return
        
        try:
            self.hunter_status_label.setText("正在查询...")
            hunter_api = HunterAPI(api_key)
            
            # 获取is_web参数
            is_web_map = {"全部": 3, "是": 1, "否": 2}
            is_web = is_web_map[self.hunter_is_web.currentText()]
            
            result = hunter_api.search(
                query=query,
                page=self.hunter_page.value(),
                page_size=self.hunter_size.value(),
                is_web=is_web,
                port_filter=self.hunter_port_filter.isChecked()
            )
            
            if result and result.get('code') == 200:
                data = result.get('data', {})
                arr_data = data.get('arr', [])
                self.hunter_results = arr_data if arr_data is not None else []
                total = data.get('total', 0)
                
                # 格式化显示结果
                if total > 0 and self.hunter_results:
                    formatted_text = f"🦅 Hunter查询结果\n"
                    formatted_text += "=" * 50 + "\n\n"
                    formatted_text += f"📊 查询统计:\n"
                    formatted_text += f"  • 总结果数: {total} 条\n"
                    formatted_text += f"  • 账户类型: {data.get('account_type', 'N/A')}\n"
                    formatted_text += f"  • 消耗积分: {data.get('consume_quota', 'N/A')}\n"
                    formatted_text += f"  • 剩余积分: {data.get('rest_quota', 'N/A')}\n"
                    formatted_text += f"  • 查询耗时: {data.get('time', 'N/A')}ms\n\n"
                    
                    formatted_text += "📋 查询结果详情:\n"
                    formatted_text += "-" * 30 + "\n"
                    
                    for i, item in enumerate(self.hunter_results[:10], 1):
                        formatted_text += f"\n{i}. "
                        if item.get('url'):
                            formatted_text += f"🌐 {item.get('url')}\n"
                        if item.get('ip'):
                            formatted_text += f"   📍 IP: {item.get('ip')}"
                        if item.get('port'):
                            formatted_text += f":{item.get('port')}"
                        formatted_text += "\n"
                        if item.get('web_title'):
                            formatted_text += f"   📄 标题: {item.get('web_title')}\n"
                        if item.get('domain'):
                            formatted_text += f"   🌍 域名: {item.get('domain')}\n"
                        # 备案信息
                        if item.get('company'):
                            formatted_text += f"   🏢 公司: {item.get('company')}\n"
                        if item.get('icp') or item.get('number'):
                            icp_number = item.get('icp') or item.get('number')
                            formatted_text += f"   📋 备案号: {icp_number}\n"
                        if item.get('country'):
                            formatted_text += f"   🗺️ 位置: {item.get('country')}"
                            if item.get('province'):
                                formatted_text += f" {item.get('province')}"
                            if item.get('city'):
                                formatted_text += f" {item.get('city')}"
                            formatted_text += "\n"
                        if item.get('os'):
                            formatted_text += f"   💻 系统: {item.get('os')}\n"
                        if item.get('status_code'):
                            formatted_text += f"   📊 状态码: {item.get('status_code')}\n"
                        if item.get('component'):
                            components = [f"{comp.get('name', '')} {comp.get('version', '')}" for comp in item.get('component', [])]
                            if components:
                                formatted_text += f"   🔧 组件: {', '.join(components)}\n"
                    
                    if total > 10:
                        formatted_text += f"\n... 还有 {total - 10} 条结果\n"
                    
                    self.hunter_result_text.setText(formatted_text)
                    self.hunter_export_btn.setEnabled(True)
                else:
                    # 无结果但查询成功
                    formatted_text = f"🦅 Hunter查询结果\n"
                    formatted_text += "=" * 50 + "\n\n"
                    formatted_text += f"📊 查询统计:\n"
                    formatted_text += f"  • 总结果数: {total} 条\n"
                    formatted_text += f"  • 账户类型: {data.get('account_type', 'N/A')}\n"
                    formatted_text += f"  • 消耗积分: {data.get('consume_quota', 'N/A')}\n"
                    formatted_text += f"  • 剩余积分: {data.get('rest_quota', 'N/A')}\n"
                    formatted_text += f"  • 查询耗时: {data.get('time', 'N/A')}ms\n\n"
                    formatted_text += "ℹ️ 查询成功，但未找到匹配的结果\n"
                    if data.get('syntax_prompt'):
                        formatted_text += f"💡 语法提示: {data.get('syntax_prompt')}\n"
                    
                    self.hunter_result_text.setText(formatted_text)
                
                self.hunter_status_label.setText(f"查询完成，共找到 {total} 条结果")
                self.hunter_status_label.setProperty("class", "status-label-success")
                self.hunter_status_label.style().polish(self.hunter_status_label)
            else:
                self.hunter_status_label.setText("查询失败")
                self.hunter_status_label.setProperty("class", "status-label-error")
                self.hunter_status_label.style().polish(self.hunter_status_label)
                error_msg = result.get('message', '未知错误') if result else '未知错误'
                formatted_error = f"❌ Hunter查询失败\n"
                formatted_error += "=" * 50 + "\n\n"
                formatted_error += f"错误信息: {error_msg}\n"
                if result and result.get('code'):
                    formatted_error += f"错误代码: {result.get('code')}\n"
                self.hunter_result_text.setText(formatted_error)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"查询失败: {str(e)}")
            self.hunter_status_label.setText("查询失败")
    
    def clear_hunter_results(self):
        """清空Hunter结果"""
        self.hunter_results.clear()
        self.hunter_result_text.clear()
        self.hunter_status_label.setText("等待查询...")
        self.hunter_status_label.setProperty("class", "status-label-waiting")
        self.hunter_status_label.style().polish(self.hunter_status_label)
        self.hunter_export_btn.setEnabled(False)
    
    def export_hunter_results(self):
        """导出Hunter查询结果"""
        if not self.hunter_results:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出Hunter查询结果", "",
            "Excel files (*.xlsx);;JSON files (*.json);;Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.xlsx'):
                self._export_hunter_to_excel(file_path)
            elif file_path.endswith('.json'):
                self._export_hunter_to_json(file_path)
            else:
                self._export_hunter_to_text(file_path)
            
            QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def _export_hunter_to_excel(self, file_path: str):
        """导出Hunter结果到Excel文件"""
        import pandas as pd
        
        all_data = []
        for i, item in enumerate(self.hunter_results, 1):
            data_row = {
                '序号': i,
                'URL': item.get('url', 'N/A'),
                'IP地址': item.get('ip', 'N/A'),
                '端口': item.get('port', 'N/A'),
                '域名': item.get('domain', 'N/A'),
                '标题': item.get('web_title', 'N/A'),
                '公司': item.get('company', 'N/A'),
                '备案号': item.get('icp') or item.get('number', 'N/A'),
                '国家': item.get('country', 'N/A'),
                '省份': item.get('province', 'N/A'),
                '城市': item.get('city', 'N/A'),
                '系统': item.get('os', 'N/A'),
                '状态码': item.get('status_code', 'N/A'),
            }
            all_data.append(data_row)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_excel(file_path, index=False)
    
    def _export_hunter_to_json(self, file_path: str):
        """导出Hunter结果到JSON文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.hunter_results, f, ensure_ascii=False, indent=2)
    
    def _export_hunter_to_text(self, file_path: str):
        """导出Hunter结果到文本文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            headers = ['序号', 'URL', 'IP地址', '端口', '域名', '标题', '公司', '备案号', '国家', '省份', '城市', '系统', '状态码']
            f.write('\t'.join(headers) + '\n')
            f.write('=' * 150 + '\n')
            
            for i, item in enumerate(self.hunter_results, 1):
                row = [
                    str(i),
                    str(item.get('url', 'N/A')),
                    str(item.get('ip', 'N/A')),
                    str(item.get('port', 'N/A')),
                    str(item.get('domain', 'N/A')),
                    str(item.get('web_title', 'N/A')),
                    str(item.get('company', 'N/A')),
                    str(item.get('icp') or item.get('number', 'N/A')),
                    str(item.get('country', 'N/A')),
                    str(item.get('province', 'N/A')),
                    str(item.get('city', 'N/A')),
                    str(item.get('os', 'N/A')),
                    str(item.get('status_code', 'N/A')),
                ]
                f.write('\t'.join(row) + '\n')
            
            f.write('\n' + '=' * 150 + '\n')
            f.write(f'总计: {len(self.hunter_results)} 条结果\n')
    
    def create_quake_controls(self) -> QWidget:
        """创建Quake控制区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        
        # API配置区域
        api_group = QGroupBox("🔑 API配置")
        api_layout = QVBoxLayout(api_group)
        
        # Quake API配置
        quake_layout = QHBoxLayout()
        quake_layout.addWidget(QLabel("Quake API Key:"))
        self.quake_key = QLineEdit()
        self.quake_key.setPlaceholderText("请输入Quake API Key...")
        self.quake_key.setEchoMode(QLineEdit.EchoMode.Password)
        quake_layout.addWidget(self.quake_key)
        api_layout.addLayout(quake_layout)
        
        layout.addWidget(api_group)
        
        # 查询配置区域
        search_group = QGroupBox("🔍 Quake查询")
        search_layout = QVBoxLayout(search_group)
        
        # 查询语句
        query_layout = QHBoxLayout()
        query_layout.addWidget(QLabel("查询语句:"))
        self.quake_query_input = QLineEdit()
        self.quake_query_input.setPlaceholderText("输入Quake查询语句...")
        query_layout.addWidget(self.quake_query_input)
        search_layout.addLayout(query_layout)
        
        # 查询参数
        params_layout = QGridLayout()
        
        params_layout.addWidget(QLabel("页码:"), 0, 0)
        self.quake_page = QSpinBox()
        self.quake_page.setMinimum(0)
        self.quake_page.setMaximum(10000)
        self.quake_page.setValue(0)
        params_layout.addWidget(self.quake_page, 0, 1)
        
        params_layout.addWidget(QLabel("每页数量:"), 0, 2)
        self.quake_size = QSpinBox()
        self.quake_size.setMinimum(1)
        self.quake_size.setMaximum(10000)
        self.quake_size.setValue(100)
        params_layout.addWidget(self.quake_size, 0, 3)
        
        search_layout.addLayout(params_layout)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.quake_search_btn = QPushButton("🔍 开始查询")
        self.quake_search_btn.clicked.connect(self.start_quake_search)
        btn_layout.addWidget(self.quake_search_btn)
        
        self.quake_export_btn = QPushButton("💾 导出结果")
        self.quake_export_btn.clicked.connect(self.export_quake_results)
        self.quake_export_btn.setEnabled(False)
        btn_layout.addWidget(self.quake_export_btn)
        
        self.quake_clear_btn = QPushButton("🗑️ 清空结果")
        self.quake_clear_btn.clicked.connect(self.clear_quake_results)
        btn_layout.addWidget(self.quake_clear_btn)
        
        # 语法文档按钮
        quake_doc_button = QPushButton("📖 查看语法文档")
        quake_doc_button.clicked.connect(self.show_quake_syntax_doc)
        btn_layout.addWidget(quake_doc_button)
        
        search_layout.addLayout(btn_layout)
        layout.addWidget(search_group)
        
        layout.addStretch()
        return widget
    
    def create_quake_results(self) -> QWidget:
        """创建Quake结果显示区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # 状态显示
        self.quake_status_label = QLabel("等待查询...")
        # 使用全局样式类属性
        self.quake_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.quake_status_label.style().polish(self.quake_status_label)
        layout.addWidget(self.quake_status_label)
        
        # 结果显示
        result_label = QLabel("📊 查询结果")
        result_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(result_label)
        
        self.quake_result_text = QTextEdit()
        self.quake_result_text.setReadOnly(True)
        layout.addWidget(self.quake_result_text)
        
        return widget
    
    def start_quake_search(self):
        """开始Quake查询"""
        api_key = self.quake_key.text().strip()
        query = self.quake_query_input.text().strip()
        
        if not api_key or not query:
            QMessageBox.warning(self, "警告", "请填写完整的API配置和查询语句")
            return
        
        try:
            self.quake_status_label.setText("正在查询...")
            quake_api = QuakeAPI(api_key)
            
            result = quake_api.search(
                query=query,
                start=self.quake_page.value(),
                size=self.quake_size.value()
            )
            
            if result and result.get('success'):
                data = result.get('data', [])
                self.quake_results = data
                total = result.get('total', 0)
                
                # 格式化显示结果
                formatted_text = f"⚡ Quake查询结果\n"
                formatted_text += "=" * 50 + "\n\n"
                formatted_text += f"📊 查询统计:\n"
                formatted_text += f"  • 总结果数: {total} 条\n"
                formatted_text += f"  • 本次获取: {len(self.quake_results)} 条\n"
                formatted_text += f"  • 查询语句: {query}\n\n"
                
                if len(self.quake_results) > 0:
                    formatted_text += "📋 查询结果详情:\n"
                    formatted_text += "-" * 30 + "\n"
                    
                    for i, item in enumerate(self.quake_results[:10], 1):
                        formatted_text += f"\n{i}. "
                        
                        # IP和端口信息
                        ip = item.get('ip', 'N/A')
                        port = item.get('port', 'N/A')
                        formatted_text += f"🌐 {ip}:{port}\n"
                        
                        # 域名信息
                        domain = item.get('domain', '')
                        if domain:
                            formatted_text += f"   🌍 域名: {domain}\n"
                        
                        # 主机名信息
                        hostname = item.get('hostname', '')
                        if hostname:
                            formatted_text += f"   🏠 主机名: {hostname}\n"
                        
                        # 标题信息
                        http_info = item.get('service', {}).get('http', {}) if item.get('service') else {}
                        title = http_info.get('title', '') if http_info else ''
                        if title:
                            formatted_text += f"   📄 标题: {title}\n"
                        
                        # ICP备案信息
                        icp = item.get('icp', '')
                        if icp:
                            formatted_text += f"   📋 备案号: {icp}\n"
                        
                        # 组织信息
                        org = item.get('org', '')
                        if org:
                            formatted_text += f"   🏢 组织: {org}\n"
                        
                        # 服务信息
                        service_info = item.get('service', {})
                        if service_info:
                            service_name = service_info.get('name', 'N/A')
                            formatted_text += f"   🔧 服务: {service_name}\n"
                            
                            # HTTP服务的详细信息
                            http_info = service_info.get('http', {})
                            if http_info:
                                server = http_info.get('server', '')
                                if server:
                                    formatted_text += f"   🖥️ 服务器: {server}\n"
                                
                                status_code = http_info.get('status_code', '')
                                if status_code:
                                    formatted_text += f"   📊 状态码: {status_code}\n"
                                
                                host = http_info.get('host', '')
                                if host:
                                    formatted_text += f"   🌐 Host: {host}\n"
                        
                        # 地理位置信息
                        location = item.get('location', {})
                        if location:
                            country = location.get('country_cn', location.get('country_en', ''))
                            province = location.get('province_cn', location.get('province_en', ''))
                            city = location.get('city_cn', location.get('city_en', ''))
                            
                            location_str = ''
                            if country:
                                location_str += country
                            if province:
                                location_str += f' {province}'
                            if city:
                                location_str += f' {city}'
                            
                            if location_str:
                                formatted_text += f"   🗺️ 位置: {location_str.strip()}\n"
                            
                            # ISP信息
                            isp = location.get('isp', '')
                            if isp:
                                formatted_text += f"   🌐 ISP: {isp}\n"
                        
                        # 组件信息
                        components = item.get('components', [])
                        if components:
                            comp_names = []
                            for comp in components[:5]:  # 只显示前5个组件
                                if isinstance(comp, dict):
                                    name = comp.get('product_name_cn', comp.get('product_name_en', ''))
                                    version = comp.get('version', '')
                                    if name:
                                        comp_str = name
                                        if version and version.strip():
                                            comp_str += f' {version}'
                                        comp_names.append(comp_str)
                            
                            if comp_names:
                                formatted_text += f"   🔧 组件: {', '.join(comp_names)}\n"
                                if len(components) > 5:
                                    formatted_text += f"   📦 还有 {len(components) - 5} 个组件...\n"
                        
                        # 传输协议
                        transport = item.get('transport', '')
                        if transport:
                            formatted_text += f"   📡 协议: {transport.upper()}\n"
                        
                        # ASN信息
                        asn = item.get('asn', '')
                        if asn:
                            formatted_text += f"   🏢 ASN: {asn}\n"
                        
                        # 时间信息
                        time_info = item.get('time', '')
                        if time_info:
                            formatted_text += f"   ⏰ 扫描时间: {time_info}\n"
                    
                    if total > 10:
                        formatted_text += f"\n... 还有 {total - 10} 条结果\n"
                else:
                    # 无结果但查询成功
                    formatted_text += "ℹ️ 查询成功，但未找到匹配的结果\n"
                
                self.quake_result_text.setText(formatted_text)
                
                self.quake_status_label.setText(f"查询完成，共找到 {total} 条结果")
                self.quake_status_label.setProperty("class", "status-label-success")
                self.quake_status_label.style().polish(self.quake_status_label)
                if len(self.quake_results) > 0:
                    self.quake_export_btn.setEnabled(True)
            else:
                self.quake_status_label.setText("查询失败")
                self.quake_status_label.setProperty("class", "status-label-error")
                self.quake_status_label.style().polish(self.quake_status_label)
                error_msg = result.get('error', '未知错误') if result else '未知错误'
                formatted_error = f"❌ Quake查询失败\n"
                formatted_error += "=" * 50 + "\n\n"
                formatted_error += f"错误信息: {error_msg}\n"
                if result and result.get('code'):
                    formatted_error += f"错误代码: {result.get('code')}\n"
                self.quake_result_text.setText(formatted_error)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"查询失败: {str(e)}")
            self.quake_status_label.setText("查询失败")
    
    def clear_quake_results(self):
        """清空Quake结果"""
        self.quake_results.clear()
        self.quake_result_text.clear()
        self.quake_status_label.setText("等待查询...")
        self.quake_status_label.setProperty("class", "status-label-waiting")
        self.quake_status_label.style().polish(self.quake_status_label)
        self.quake_export_btn.setEnabled(False)
    
    def export_quake_results(self):
        """导出Quake查询结果"""
        if not self.quake_results:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出Quake查询结果", "",
            "Excel files (*.xlsx);;JSON files (*.json);;Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.xlsx'):
                self._export_quake_to_excel(file_path)
            elif file_path.endswith('.json'):
                self._export_quake_to_json(file_path)
            else:
                self._export_quake_to_text(file_path)
            
            QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def _export_quake_to_excel(self, file_path: str):
        """导出Quake结果到Excel文件"""
        import pandas as pd
        
        all_data = []
        for i, item in enumerate(self.quake_results, 1):
            # 获取服务信息
            service = item.get('service', {})
            service_name = service.get('name', 'N/A') if service else 'N/A'
            
            # 获取HTTP信息（标题等）
            http_info = service.get('http', {}) if service else {}
            title = http_info.get('title', 'N/A') if http_info else 'N/A'
            
            # 获取位置信息
            location = item.get('location', {})
            country = location.get('country_cn', location.get('country_en', 'N/A')) if location else 'N/A'
            province = location.get('province_cn', location.get('province_en', '')) if location else ''
            city = location.get('city_cn', location.get('city_en', '')) if location else ''
            
            location_str = country
            if province:
                location_str += f' {province}'
            if city:
                location_str += f' {city}'
            
            data_row = {
                '序号': i,
                'IP地址': item.get('ip', 'N/A'),
                '端口': item.get('port', 'N/A'),
                '域名': item.get('domain', 'N/A'),
                '主机名': item.get('hostname', 'N/A'),
                '标题': title,
                '备案号': item.get('icp', 'N/A'),
                '服务': service_name,
                '位置': location_str.strip(),
                '组织': item.get('org', 'N/A'),
                '传输协议': item.get('transport', 'N/A').upper() if item.get('transport') else 'N/A',
                'ASN': item.get('asn', 'N/A'),
            }
            all_data.append(data_row)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_excel(file_path, index=False)
    
    def _export_quake_to_json(self, file_path: str):
        """导出Quake结果到JSON文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.quake_results, f, ensure_ascii=False, indent=2)
    
    def _export_quake_to_text(self, file_path: str):
        """导出Quake结果到文本文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            headers = ['序号', 'IP地址', '端口', '域名', '主机名', '标题', '备案号', '服务', '位置', '组织', '传输协议', 'ASN']
            f.write('\t'.join(headers) + '\n')
            f.write('=' * 150 + '\n')
            
            for i, item in enumerate(self.quake_results, 1):
                # 获取服务信息
                service = item.get('service', {})
                service_name = service.get('name', 'N/A') if service else 'N/A'
                
                # 获取HTTP信息（标题等）
                http_info = service.get('http', {}) if service else {}
                title = http_info.get('title', 'N/A') if http_info else 'N/A'
                
                # 获取位置信息
                location = item.get('location', {})
                country = location.get('country_cn', location.get('country_en', 'N/A')) if location else 'N/A'
                province = location.get('province_cn', location.get('province_en', '')) if location else ''
                city = location.get('city_cn', location.get('city_en', '')) if location else ''
                
                location_str = country
                if province:
                    location_str += f' {province}'
                if city:
                    location_str += f' {city}'
                
                row = [
                    str(i),
                    str(item.get('ip', 'N/A')),
                    str(item.get('port', 'N/A')),
                    str(item.get('domain', 'N/A')),
                    str(item.get('hostname', 'N/A')),
                    str(title),
                    str(item.get('icp', 'N/A')),
                    str(service_name),
                    str(location_str.strip()),
                    str(item.get('org', 'N/A')),
                    str(item.get('transport', 'N/A').upper() if item.get('transport') else 'N/A'),
                    str(item.get('asn', 'N/A')),
                ]
                f.write('\t'.join(row) + '\n')
            
            f.write('\n' + '=' * 150 + '\n')
            f.write(f'总计: {len(self.quake_results)} 条结果\n')
    
    def clear_results(self):
        """清空所有结果"""
        self.clear_unified_results()
        self.fofa_results.clear()
        self.hunter_results.clear()
        self.quake_results.clear()
    
    def _get_fofa_syntax_doc(self) -> str:
        """获取FOFA语法文档"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>FOFA 查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑连接符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>符号</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>含义</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配，=""时，可查询不存在字段或者值为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>完全匹配，=""时，可查询存在且值为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title==""</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>与，同时满足多个条件</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1" && port="80"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>或，满足任一条件</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80" || port="443"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>不匹配，!=""时，可查询值不为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country!="CN"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>*=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊匹配，使用*或者?进行搜索</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title*="管理"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>确认查询优先级，括号内容优先级最高</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>(port="80" || port="8080") && country="CN"</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>基础类（General）</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>=</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>!=</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>*=</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"<br>ip="220.181.111.1/24"<br>ip="2600:9000:202a:2600:18:4ab7:f600:93a1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过IPv4/IPv6地址或C段进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="6379"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过端口号进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="qq.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过根域名进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="管理后台"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网页标题进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body="login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网页内容进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app="Microsoft-Exchange"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过FOFA整理的规则进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>app="Apache httpd" && country="CN"</code> - 搜索中国的Apache服务器</p>
        <p><code>title="登录" && port="8080"</code> - 搜索8080端口的登录页面</p>
        <p><code>body="管理" && header="nginx"</code> - 搜索包含管理的nginx网站</p>
        <p><code>domain="edu.cn"</code> - 搜索教育网域名</p>
        <p><code>ip="1.1.1.0/24" && port="22"</code> - 搜索C段内开放SSH的主机</p>
        </div>
        </div>
        """
    
    def _get_hunter_syntax_doc(self) -> str:
        """获取Hunter语法文档"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Hunter 鹰图平台查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑连接符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>连接符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>查询含义</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊查询，表示查询包含关键词的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>精确查询，表示查询有且仅有关键词的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊剔除，表示剔除包含关键词的资产。使用!=""时，可查询值不为空的情况</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&、||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>多种条件组合查询，&&同and，表示和；||同or，表示或</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>括号内表示查询优先级最高</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>IP相关语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP为"1.1.1.1"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port="80"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放端口为"80"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.country</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.country="中国"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机所在国为"中国"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.title="北京"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>从网站标题中搜索"北京"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.body="网络空间测绘"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站正文包含"网络空间测绘"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="qianxin"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名包含"qianxin"的网站</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>app="Apache httpd" && ip.country="CN"</code> - 搜索中国的Apache服务器</p>
        <p><code>web.title="登录" && ip.port="8080"</code> - 搜索8080端口的登录页面</p>
        <p><code>ip.port_count>"10"</code> - 搜索开放端口数大于10的IP</p>
        <p><code>domain.suffix="edu.cn"</code> - 搜索教育网域名</p>
        </div>
        </div>
        """
    
    def _get_quake_syntax_doc(self) -> str:
        """获取Quake语法文档"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Quake 360网络空间测绘查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>基础语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip:"1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定IP地址的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放指定端口的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>hostname</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定主机名的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title:"管理后台"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站标题包含指定内容的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body:"login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网页内容包含指定文本的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>service</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>service:"http"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定服务类型的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app:"nginx"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定应用的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑运算符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>运算符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>AND / &&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 AND country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑与，同时满足多个条件</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>OR / ||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 OR port:443</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑或，满足任一条件</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>NOT / -</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 NOT country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑非，排除指定条件</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>country:"China" AND port:80</code> - 搜索中国的80端口资产</p>
        <p><code>service:"http" AND NOT port:8080</code> - 搜索HTTP服务但排除8080端口</p>
        <p><code>hostname:"*.baidu.com"</code> - 搜索百度的子域名</p>
        <p><code>app:"nginx" AND country:"China"</code> - 搜索中国的nginx服务器</p>
        </div>
        </div>
        """
    
    def show_fofa_syntax_doc(self):
        """显示FOFA语法文档"""
        from modules.ui.dialogs.syntax_dialog import ModernSyntaxDocumentDialog
        from modules.ui.styles.theme_manager import ThemeManager
        # 根据当前主题决定是否使用暗色模式
        dialog = ModernSyntaxDocumentDialog(self, force_dark_mode=ThemeManager()._dark_mode)
        dialog.exec()
    
    def show_hunter_syntax_doc(self):
        """显示Hunter语法文档"""
        from modules.ui.dialogs.syntax_dialog import ModernSyntaxDocumentDialog
        from modules.ui.styles.theme_manager import ThemeManager
        # 根据当前主题决定是否使用暗色模式
        dialog = ModernSyntaxDocumentDialog(self, force_dark_mode=ThemeManager()._dark_mode)
        dialog.exec()
    
    def show_quake_syntax_doc(self):
        """显示Quake语法文档"""
        from modules.ui.dialogs.syntax_dialog import ModernSyntaxDocumentDialog
        from modules.ui.styles.theme_manager import ThemeManager
        # 根据当前主题决定是否使用暗色模式
        dialog = ModernSyntaxDocumentDialog(self, force_dark_mode=ThemeManager()._dark_mode)
        dialog.exec()


class ModernSyntaxDocumentDialog(QDialog):
    """现代化语法文档查看对话框"""
    
    def __init__(self, parent=None, force_dark_mode=False):
        super().__init__(parent)
        self.setWindowTitle("网络空间测绘语法文档")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.resize(1000, 700)
        
        # 强制暗色模式设置
        self.force_dark_mode = force_dark_mode
        
        # 居中显示
        if parent:
            parent_geometry = parent.geometry()
            x = parent_geometry.x() + (parent_geometry.width() - 1000) // 2
            y = parent_geometry.y() + (parent_geometry.height() - 700) // 2
            self.move(max(0, x), max(0, y))
        else:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - 1000) // 2
            y = (screen.height() - 700) // 2
            self.move(x, y)
        
        # 根据当前主题设置对话框样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if self.force_dark_mode or theme_manager._dark_mode:
            # 暗色模式样式
            self.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    border-radius: 10px;
                }
                QTabWidget::pane {
                    border: 1px solid #383838;
                    background-color: #252525;
                    border-radius: 8px;
                }
                QTabWidget::tab-bar {
                    alignment: center;
                }
                QTabBar::tab {
                    background-color: #333333;
                    color: #e0e0e0;
                    padding: 16px 32px;
                    margin-right: 4px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    font-weight: 500;
                    font-size: 16px;
                    min-width: 120px;
                    min-height: 40px;
                }
                QTabBar::tab:selected {
                    background-color: #bb86fc;
                    color: #1e1e1e;
                }
                QTabBar::tab:hover {
                    background-color: #985eff;
                    color: #1e1e1e;
                }
                QTextEdit {
                    border: 1px solid #383838;
                    border-radius: 8px;
                    background-color: #252525;
                    color: #f0f0f0;
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 14px;
                    line-height: 1.8;
                    padding: 12px;
                }
                
                /* 确保HTML内容在暗色模式下正确显示 */
                QTextEdit, QTextEdit * {
                    background-color: #252525;
                    color: #f0f0f0;
                }
                
                QTextEdit a {
                    color: #bb86fc;
                }
                
                QTextEdit table {
                    border-collapse: collapse;
                    border: 1px solid #383838;
                }
                
                QTextEdit td, QTextEdit th {
                    border: 1px solid #383838;
                    padding: 8px;
                    color: #f0f0f0;
                    background-color: #333333;
                }
                QPushButton {
                    background-color: #bb86fc;
                    color: #1e1e1e;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 8px;
                    font-weight: 500;
                    font-size: 16px;
                    min-width: 100px;
                    min-height: 40px;
                }
                QPushButton:hover {
                    background-color: #985eff;
                }
                QPushButton:pressed {
                    background-color: #7b39fb;
                }
                QPushButton:disabled {
                    background-color: #666666;
                    color: #999999;
                }
                QLabel {
                    color: #f0f0f0;
                    font-size: 16px;
                    font-weight: 500;
                    padding: 4px;
                    background-color: transparent;
                }
                QLineEdit {
                    border: 2px solid #383838;
                    border-radius: 8px;
                    padding: 12px 16px;
                    font-size: 16px;
                    background-color: #252525;
                    color: #f0f0f0;
                    min-height: 20px;
                }
                QLineEdit:focus {
                    border-color: #bb86fc;
                    outline: none;
                }
            """)
        else:
            # 亮色模式样式
            self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
                border-radius: 10px;
            }
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                background-color: white;
                border-radius: 8px;
            }
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                background-color: #e9ecef;
                color: #495057;
                padding: 16px 32px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: 500;
                font-size: 16px;
                min-width: 120px;
                min-height: 40px;
            }
            QTabBar::tab:selected {
                background-color: #007bff;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #0056b3;
                color: white;
            }
            QTextEdit {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 14px;
                line-height: 1.8;
                padding: 12px;
            }
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: 500;
                font-size: 16px;
                min-width: 100px;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:pressed {
                background-color: #004085;
            }
        """)
        
        self.setup_ui()
        self.load_documents()
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 标题
        title_label = QLabel("网络空间测绘语法文档")
        # 移除硬编码样式，使用全局样式
        title_label.setProperty("class", "title-label")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 选项卡
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        
        # 确保关闭按钮应用正确的样式
        from modules.ui.styles.theme_manager import ThemeManager
        if self.force_dark_mode or ThemeManager()._dark_mode:
            close_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #444444, stop:1 #333333);
                    color: #e0e0e0;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 8px;
                    font-weight: 500;
                    font-size: 16px;
                    min-width: 100px;
                    min-height: 40px;
                    margin: 1px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #555555, stop:1 #444444);
                    margin-top: 0px;
                    margin-bottom: 2px;
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #333333, stop:1 #222222);
                    margin-top: 2px;
                    margin-bottom: 0px;
                }
            """)
        
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
    
    def adapt_html_for_dark_mode(self, html_content):
        """根据当前主题模式调整HTML内容的样式"""
        # 使用ThemeManager获取当前主题模式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        is_dark_mode = self.force_dark_mode or theme_manager._dark_mode
        
        if is_dark_mode:
            # 替换HTML中的背景色和文本颜色
            html_content = html_content.replace('background-color: #f8f9fa;', 'background-color: #333333;')
            html_content = html_content.replace('background-color: white;', 'background-color: #252525;')
            html_content = html_content.replace('border: 1px solid #dee2e6;', 'border: 1px solid #444444;')
            html_content = html_content.replace('color: #007bff;', 'color: #bb86fc;')
            html_content = html_content.replace('border-bottom: 2px solid #007bff;', 'border-bottom: 2px solid #bb86fc;')
            html_content = html_content.replace('color: #28a745;', 'color: #03dac6;')
            
            # 添加更多颜色替换，确保所有文本颜色都被正确替换
            html_content = html_content.replace('color: #333;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: #333333;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: #666;', 'color: #d0d0d0;')
            html_content = html_content.replace('color: #666666;', 'color: #d0d0d0;')
            html_content = html_content.replace('color: #000;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: #000000;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: black;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: #444;', 'color: #e0e0e0;')
            html_content = html_content.replace('color: #444444;', 'color: #e0e0e0;')
            html_content = html_content.replace('color: #555;', 'color: #d5d5d5;')
            html_content = html_content.replace('color: #555555;', 'color: #d5d5d5;')
            
            # 表格样式替换
            html_content = html_content.replace('background-color: #f5f5f5;', 'background-color: #383838;')
            html_content = html_content.replace('background-color: #eee;', 'background-color: #3a3a3a;')
            html_content = html_content.replace('background-color: #eeeeee;', 'background-color: #3a3a3a;')
            html_content = html_content.replace('background-color: #f9f9f9;', 'background-color: #353535;')
            
            # 如果没有明确指定文本颜色，添加默认文本颜色
            if 'color:' not in html_content or 'color: #f0f0f0;' not in html_content:
                html_content = html_content.replace('<div style=', '<div style="color: #f0f0f0; ')
            
            # 确保表格中的文本颜色正确
            html_content = html_content.replace('<td style=', '<td style="color: #f0f0f0; ')
            html_content = html_content.replace('<th style=', '<th style="color: #f0f0f0; ')
        else:
            # 亮色模式下确保样式正确
            # 确保表格背景色正确
            html_content = html_content.replace('background-color: #333333;', 'background-color: #f8f9fa;')
            html_content = html_content.replace('background-color: #252525;', 'background-color: white;')
            html_content = html_content.replace('background-color: #383838;', 'background-color: #f5f5f5;')
            html_content = html_content.replace('background-color: #3a3a3a;', 'background-color: #eeeeee;')
            html_content = html_content.replace('background-color: #353535;', 'background-color: #f9f9f9;')
            
            # 确保边框颜色正确
            html_content = html_content.replace('border: 1px solid #444444;', 'border: 1px solid #dee2e6;')
            
            # 确保文本颜色正确
            html_content = html_content.replace('color: #f0f0f0;', 'color: #333333;')
            html_content = html_content.replace('color: #d0d0d0;', 'color: #666666;')
            html_content = html_content.replace('color: #e0e0e0;', 'color: #444444;')
            html_content = html_content.replace('color: #d5d5d5;', 'color: #555555;')
            html_content = html_content.replace('color: #bb86fc;', 'color: #007bff;')
            html_content = html_content.replace('color: #03dac6;', 'color: #28a745;')
            
            # 确保表格中的文本颜色正确
            html_content = html_content.replace('<td style="color: #f0f0f0;', '<td style="color: #333333;')
            html_content = html_content.replace('<th style="color: #f0f0f0;', '<th style="color: #333333;')
        
        return html_content
    
    def load_documents(self):
        """加载文档内容"""
        # 获取当前主题模式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        is_dark_mode = self.force_dark_mode or theme_manager._dark_mode
        
        # 设置QTextEdit的样式
        text_edit_style = """
            QTextEdit {
                border: 1px solid #383838;
                border-radius: 8px;
                background-color: #252525;
                color: #f0f0f0;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 14px;
                line-height: 1.8;
                padding: 12px;
            }
            QScrollBar:vertical {
                background-color: #333333;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """ if is_dark_mode else """
            QTextEdit {
                border: 1px solid #dee2e6;
                border-radius: 8px;
                background-color: white;
                color: #333333;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 14px;
                line-height: 1.8;
                padding: 12px;
            }
        """
        
        # FOFA文档
        fofa_content = self.get_fofa_content()
        fofa_content = self.adapt_html_for_dark_mode(fofa_content)
        fofa_text = QTextEdit()
        fofa_text.setReadOnly(True)
        fofa_text.setStyleSheet(text_edit_style)
        fofa_text.setHtml(fofa_content)
        self.tab_widget.addTab(fofa_text, "FOFA")
        
        # Hunter文档
        hunter_content = self.get_hunter_content()
        hunter_content = self.adapt_html_for_dark_mode(hunter_content)
        hunter_text = QTextEdit()
        hunter_text.setReadOnly(True)
        hunter_text.setStyleSheet(text_edit_style)
        hunter_text.setHtml(hunter_content)
        self.tab_widget.addTab(hunter_text, "Hunter")
        
        # Quake文档
        quake_content = self.get_quake_content()
        quake_content = self.adapt_html_for_dark_mode(quake_content)
        quake_text = QTextEdit()
        quake_text.setReadOnly(True)
        quake_text.setStyleSheet(text_edit_style)
        quake_text.setHtml(quake_content)
        self.tab_widget.addTab(quake_text, "Quake")
        
        # 语法对比
        comparison_content = self.get_comparison_content()
        comparison_content = self.adapt_html_for_dark_mode(comparison_content)
        comparison_text = QTextEdit()
        comparison_text.setReadOnly(True)
        comparison_text.setStyleSheet(text_edit_style)
        comparison_text.setHtml(comparison_content)
        self.tab_widget.addTab(comparison_text, "语法对比")
    
    def get_fofa_content(self):
        """获取FOFA文档内容"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>FOFA 查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑连接符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>符号</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>含义</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配，=""时，可查询不存在字段或者值为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>完全匹配，=""时，可查询存在且值为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title==""</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>与，同时满足多个条件</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1" && port="80"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>或，满足任一条件</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80" || port="443"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>不匹配，!=""时，可查询值不为空的情况</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country!="CN"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>*=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊匹配，使用*或者?进行搜索</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title*="管理"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>确认查询优先级，括号内容优先级最高</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>(port="80" || port="8080") && country="CN"</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>基础类（General）</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>=</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>!=</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: center;'>*=</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"<br>ip="220.181.111.1/24"<br>ip="2600:9000:202a:2600:18:4ab7:f600:93a1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过IPv4/IPv6地址或C段进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="6379"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过端口号进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="qq.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过根域名进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>host</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>host=".fofa.info"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过主机名进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>os</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>os="centos"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过操作系统进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>server</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server="Microsoft-IIS/10"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过服务器进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>asn</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>asn="19551"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过自治系统号进行搜索</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>org</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>org="LLC Baxet"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过所属组织进行查询</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_domain=true<br>is_domain=false</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>筛选拥有/没有域名的资产</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_ipv6</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_ipv6=true<br>is_ipv6=false</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>筛选ipv6/ipv4的资产</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: green;'>✓</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; text-align: center; color: red;'>-</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>标记类（Special Label）</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app="Microsoft-Exchange"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过FOFA整理的规则进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="管理后台"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网页标题进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body="login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过网页内容进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header="nginx"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过HTTP响应头进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>banner</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>banner="SSH-2.0"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过协议banner进行查询</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>地理位置类</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>用途说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>country</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country="CN"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过国家代码进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>region</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>region="Beijing"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过省份/地区进行查询</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>city</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>city="Beijing"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>通过城市进行查询</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>app="Apache httpd" && country="CN"</code> - 搜索中国的Apache服务器</p>
        <p><code>title="登录" && port="8080"</code> - 搜索8080端口的登录页面</p>
        <p><code>body="管理" && header="nginx"</code> - 搜索包含管理的nginx网站</p>
        <p><code>domain="edu.cn"</code> - 搜索教育网域名</p>
        <p><code>ip="1.1.1.0/24" && port="22"</code> - 搜索C段内开放SSH的主机</p>
        </div>
        </div>
        """
    
    def get_hunter_content(self):
        """获取Hunter文档内容"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Hunter 鹰图平台查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑连接符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>连接符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>查询含义</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊查询，表示查询包含关键词的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>==</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>精确查询，表示查询有且仅有关键词的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>模糊剔除，表示剔除包含关键词的资产。使用!=""时，可查询值不为空的情况</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>&&、||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>多种条件组合查询，&&同and，表示和；||同or，表示或</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>括号内表示查询优先级最高</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>IP相关语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP为"1.1.1.1"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port="80"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放端口为"80"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.country</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.country="中国"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机所在国为"中国"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.province</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.province="江苏"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机在江苏省的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.city</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.city="北京"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索IP对应主机所在城市为"北京"市的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.isp</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.isp="电信"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索运营商为"中国电信"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.os</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.os="Windows"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索操作系统标记为"Windows"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.port_count</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port_count>"2"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放端口大于2的IP（支持等于、大于、小于）</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.ports</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.ports="80" && ip.ports="443"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询开放了80和443端口号的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip.tag</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.tag="CDN"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询包含IP标签"CDN"的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>域名相关语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_domain=true</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名标记不为空的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="qianxin"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名包含"qianxin"的网站</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain.suffix</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain.suffix="qianxin.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索主域为"qianxin.com"的网站</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain.status</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain.status="clientDeleteProhibited"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索域名状态为"client Delete Prohibited"的网站</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>Web相关语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>is_web</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>is_web=true</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索web资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.title="北京"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>从网站标题中搜索"北京"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.body="网络空间测绘"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站正文包含"网络空间测绘"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar="baidu.com:443"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询与baidu.com:443网站的特征相似的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar_icon</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar_icon=="17262739310191283300"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询网站icon与该icon相似的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.similar_id</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.similar_id="3322dfb483ea6fd250b29de488969b35"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询与该网页相似的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.icon</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.icon="22eeab765346f14faf564a4709f98548"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询网站icon与该icon相同的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>web.tag</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.tag="登录页面"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询包含资产标签"登录页面"的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>Header响应头语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.server</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.server=="Microsoft-IIS/10"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索server全名为"Microsoft-IIS/10"的服务器</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.content_length</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.content_length="691"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP消息主体的大小为691的网站</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header.status_code</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header.status_code="402"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP请求返回状态码为"402"的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>header</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>header="elastic"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索HTTP响应头中含有"elastic"的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>ICP备案语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.province</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.province="江苏"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在江苏省的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.city</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.city="上海"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在"上海"这个城市的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.district</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.district="杨浦"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索icp备案企业注册地址在"杨浦"这个区县的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.is_exception</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.is_exception=true</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索含有ICP备案异常的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>icp.name</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>icp.name!=""</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>查询备案企业不为空的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>证书相关语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>cert.is_trust</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>cert.is_trust=true</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索证书可信的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>app="Apache httpd" && ip.country="CN"</code> - 搜索中国的Apache服务器</p>
        <p><code>web.title="登录" && ip.port="8080"</code> - 搜索8080端口的登录页面</p>
        <p><code>ip.port_count>"10"</code> - 搜索开放端口数大于10的IP</p>
        <p><code>domain.suffix="edu.cn"</code> - 搜索教育网域名</p>
        </div>
        </div>
        """
    
    def get_quake_content(self):
        """获取Quake文档内容"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>Quake 360网络空间测绘查询语法文档</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>基础语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>ip</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip:"1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定IP地址的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>port</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索开放指定端口的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>hostname</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定主机名的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>domain</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain:"example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定域名的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>service</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>service:"http"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定服务类型的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>app</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>app:"nginx"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定应用的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>title</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title:"管理后台"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网站标题包含指定内容的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>body</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body:"login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索网页内容包含指定文本的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>os</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>os:"Windows"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定操作系统的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>server</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>server:"Apache"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定Web服务器的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>cert</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>cert:"example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索SSL证书包含指定内容的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>jarm</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>jarm:"2ad2ad0002ad2ad00042d42d00000ad9fb3bc51631e1c39ac59a7e"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定JARM指纹的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>asn</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>asn:4134</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定ASN的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>org</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>org:"China Telecom"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定组织的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>isp</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>isp:"China Telecom"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定ISP的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>地理位置语法</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>country</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定国家的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>province</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>province:"Beijing"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定省份的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>city</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>city:"Shanghai"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索指定城市的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑运算符</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>运算符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>AND / &&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 AND country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑与，同时满足多个条件</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>OR / ||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 OR port:443</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑或，满足任一条件</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>NOT / -</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80 NOT country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>逻辑非，排除指定条件</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>()</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>(port:80 OR port:443) AND country:"China"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>括号用于控制查询优先级</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>范围查询</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>语法</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>[x TO y]</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:[80 TO 90]</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口在80到90之间的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>>=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:>=80</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口大于等于80的资产</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'><=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:<=1024</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>搜索端口小于等于1024的资产</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>通配符查询</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>通配符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>示例</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>说明</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>*</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"*.example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配任意字符序列</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold; color: #007bff;'>?</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"test?.example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px;'>匹配单个字符</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>示例查询</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><code>country:"China" AND port:80</code> - 搜索中国的80端口资产</p>
        <p><code>service:"http" AND NOT port:8080</code> - 搜索HTTP服务但排除8080端口</p>
        <p><code>hostname:"*.baidu.com"</code> - 搜索百度的子域名</p>
        <p><code>title:/.*管理.*/</code> - 使用正则表达式搜索标题</p>
        <p><code>app:"nginx" AND country:"China"</code> - 搜索中国的nginx服务器</p>
        </div>
        </div>
        """
    
    def get_comparison_content(self):
        """获取语法对比内容"""
        return """
        <div style='font-family: Consolas, Monaco, monospace; line-height: 1.6;'>
        <h2 style='color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;'>三大平台语法对比</h2>
        
        <h3 style='color: #28a745; margin-top: 20px;'>基础查询对比</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>查询类型</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>FOFA</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Hunter</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Quake</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>IP地址</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip="1.1.1.1"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip:"1.1.1.1"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>端口</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port="80"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>ip.port="80"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>port:80</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>域名</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>domain="example.com"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>hostname:"example.com"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>网页标题</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title="管理"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.title="管理"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>title:"管理"</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>网页内容</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body="login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>web.body="login"</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>body:"login"</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>逻辑运算符对比</h3>
        <table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
        <tr style='background-color: #f8f9fa;'>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>运算符</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>FOFA</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Hunter</th>
            <th style='border: 1px solid #dee2e6; padding: 8px; text-align: left;'>Quake</th>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑与</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>&&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>&&</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>AND 或 &&</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑或</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>||</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>OR 或 ||</td>
        </tr>
        <tr>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-weight: bold;'>逻辑非</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>!=</td>
            <td style='border: 1px solid #dee2e6; padding: 8px; font-family: monospace; background-color: #f8f9fa;'>NOT 或 -</td>
        </tr>
        </table>
        
        <h3 style='color: #28a745; margin-top: 20px;'>特色功能对比</h3>
        <div style='background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <h4 style='color: #6f42c1;'>FOFA特色:</h4>
        <ul>
        <li>丰富的证书查询语法</li>
        <li>完善的时间筛选功能</li>
        <li>独立IP语法系列</li>
        <li>支持模糊匹配(*=)</li>
        </ul>
        
        <h4 style='color: #6f42c1;'>Hunter特色:</h4>
        <ul>
        <li>网站相似性搜索</li>
        <li>图标hash搜索</li>
        <li>IP标签分类</li>
        <li>ICP备案信息查询</li>
        </ul>
        
        <h4 style='color: #6f42c1;'>Quake特色:</h4>
        <ul>
        <li>支持正则表达式</li>
        <li>范围查询语法</li>
        <li>存在性查询</li>
        <li>灵活的通配符支持</li>
        </ul>
        </div>
        
        <h3 style='color: #28a745; margin-top: 20px;'>使用建议</h3>
        <div style='background-color: #e9ecef; padding: 15px; border-radius: 8px; margin: 10px 0;'>
        <p><strong>FOFA:</strong> 适合精确查询和大规模数据分析，语法最为丰富</p>
        <p><strong>Hunter:</strong> 适合威胁情报和相似性分析，特色功能突出</p>
        <p><strong>Quake:</strong> 适合灵活查询和正则匹配，语法相对简洁</p>
        </div>
        </div>
        """


def main():
    """测试函数"""
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    window = AssetMappingUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()