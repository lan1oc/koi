#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威胁情报查询UI

提供微步威胁情报查询的用户界面
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox, QPushButton,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSpinBox,
    QRadioButton, QFileDialog, QMessageBox, QScrollArea, QGridLayout,
    QListWidget, QProgressBar, QPlainTextEdit, QApplication, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices

from .threatbook_api import ThreatBookAPI
from typing import Dict, List, Optional
import logging
from ...ui.styles.theme_manager import ThemeManager


class ModernDetailDialog(QDialog):
    """现代化的详细信息弹窗"""
    
    def __init__(self, title: str, main_info: str, detail_info: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setup_ui(title, main_info, detail_info)
        
    def setup_ui(self, title: str, main_info: str, detail_info: str):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 主容器
        main_frame = QFrame()
        main_frame.setObjectName("modernDialog")
        main_frame.setStyleSheet("""
            QFrame#modernDialog {
                background-color: #2d2d2d;
                border: 1px solid #bb86fc;
                border-radius: 12px;
                padding: 0px;
            }
        """)
        
        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题栏
        title_layout = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #bb86fc;
                font-size: 18px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }
        """)
        
        # 关闭按钮
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #f0f0f0;
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 15px;
            }
            QPushButton:hover {
                background-color: #ff4757;
                color: white;
            }
        """)
        close_btn.clicked.connect(self.close)
        
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(close_btn)
        main_layout.addLayout(title_layout)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("QFrame { color: #3d3d3d; }")
        main_layout.addWidget(separator)
        
        # 主要信息
        main_info_label = QLabel(main_info)
        main_info_label.setStyleSheet("""
            QLabel {
                color: #f0f0f0;
                font-size: 14px;
                line-height: 1.5;
                padding: 10px;
                background-color: #3d3d3d;
                border-radius: 8px;
            }
        """)
        main_info_label.setWordWrap(True)
        main_layout.addWidget(main_info_label)
        
        # 详细信息（可折叠）
        detail_label = QLabel("详细信息")
        detail_label.setStyleSheet("""
            QLabel {
                color: #bb86fc;
                font-size: 14px;
                font-weight: bold;
                margin-top: 10px;
            }
        """)
        main_layout.addWidget(detail_label)
        
        detail_text = QTextEdit()
        detail_text.setPlainText(detail_info)
        detail_text.setMinimumHeight(600)
        detail_text.setMinimumWidth(900)
        detail_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #f0f0f0;
                border: 1px solid #3d3d3d;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)
        detail_text.setReadOnly(True)
        main_layout.addWidget(detail_text)
        
        layout.addWidget(main_frame)
        
        # 自适应对话框大小，但限制最大尺寸避免超出屏幕
        self.resize(1200, 900)
        self.setMinimumSize(1000, 700)
        self.setMaximumSize(1600, 1200)
        
        # 居中显示并确保不超出屏幕边界
        self.center_on_screen()
    
    def center_on_screen(self):
        """将对话框居中显示并确保不超出屏幕边界"""
        from PySide6.QtWidgets import QApplication
        
        # 获取屏幕几何信息
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        
        # 获取父窗口信息
        parent_widget = self.parent()
        if parent_widget and isinstance(parent_widget, QWidget):
            parent_rect = parent_widget.geometry()
            # 尝试相对于父窗口居中
            x = parent_rect.x() + (parent_rect.width() - self.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - self.height()) // 2
        else:
            # 相对于屏幕居中
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
        
        # 确保对话框不超出屏幕边界
        x = max(screen_geometry.x(), min(x, screen_geometry.x() + screen_geometry.width() - self.width()))
        y = max(screen_geometry.y(), min(y, screen_geometry.y() + screen_geometry.height() - self.height()))
        
        self.move(x, y)


class ThreatIntelQueryThread(QThread):
    """威胁情报查询线程"""
    
    progress_updated = Signal(str)
    query_completed = Signal(dict)
    
    def __init__(self, api_instance, query_type: str, query_data: str, **kwargs):
        super().__init__()
        self.api_instance = api_instance
        self.query_type = query_type
        self.query_data = query_data
        self.kwargs = kwargs
    
    def run(self):
        """执行查询"""
        try:
            self.progress_updated.emit(f"开始{self.query_type}查询...")
            
            if self.query_type == "ip_reputation":
                # 传递所有kwargs参数给IP信誉查询
                result = self.api_instance.query_ip_reputation(self.query_data, **self.kwargs)
            elif self.query_type == "dns_compromise":
                result = self.api_instance.query_dns_compromise(self.query_data)
            elif self.query_type == "file_report":
                resource_type = self.kwargs.get('resource_type', 'sha256')
                result = self.api_instance.query_file_report(self.query_data, resource_type)
            elif self.query_type == "file_multiengines":
                resource_type = self.kwargs.get('resource_type', 'sha256')
                result = self.api_instance.query_file_multiengines(self.query_data, resource_type)
            elif self.query_type == "file_upload":
                sandbox_type = self.kwargs.get('sandbox_type', 'win7_sp1_enx86_office2013')
                run_time = self.kwargs.get('run_time', 60)
                result = self.api_instance.upload_file(self.query_data, sandbox_type, run_time)
            else:
                result = {'error': f'不支持的查询类型: {self.query_type}'}
            
            self.progress_updated.emit("查询完成")
            self.query_completed.emit({
                'type': self.query_type,
                'query': self.query_data,
                'result': result,
                'success': 'error' not in result
            })
            
        except Exception as e:
            self.progress_updated.emit(f"查询失败: {str(e)}")
            self.query_completed.emit({
                'type': self.query_type,
                'query': self.query_data,
                'result': {'error': str(e)},
                'success': False
            })


class BatchIPQueryThread(QThread):
    """批量IP查询线程"""
    
    progress_updated = Signal(str)
    single_query_completed = Signal(dict, int, int)  # result, current, total
    batch_query_completed = Signal(int, int)  # success_count, total_count
    
    def __init__(self, api_instance, ip_list: List[str], **kwargs):
        super().__init__()
        self.api_instance = api_instance
        self.ip_list = ip_list
        self.kwargs = kwargs
        self.success_count = 0
    
    def run(self):
        """执行批量查询"""
        total_count = len(self.ip_list)
        self.success_count = 0
        
        for i, ip in enumerate(self.ip_list, 1):
            try:
                self.progress_updated.emit(f"正在查询 {ip} ({i}/{total_count})")
                
                # 执行单个IP查询
                result = self.api_instance.query_ip_reputation(ip, **self.kwargs)
                
                if 'error' not in result:
                    self.success_count += 1
                    success = True
                else:
                    success = False
                
                # 发送单个查询完成信号
                self.single_query_completed.emit({
                    'type': 'ip_reputation',
                    'query': ip,
                    'result': result,
                    'success': success
                }, i, total_count)
                
                # 添加延迟避免API限制
                self.msleep(500)  # 500ms延迟
                
            except Exception as e:
                # 发送失败信号
                self.single_query_completed.emit({
                    'type': 'ip_reputation',
                    'query': ip,
                    'result': {'error': str(e)},
                    'success': False
                }, i, total_count)
        
        # 发送批量查询完成信号
        self.batch_query_completed.emit(self.success_count, total_count)


class ThreatIntelligenceUI(QWidget):
    """威胁情报查询UI类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.threatbook_api = ThreatBookAPI()
        self.query_results = []
        self.query_thread = None
        
        # 获取主题管理器实例
        self.theme_manager = ThemeManager()
        
        self.setup_ui()
        self.setup_connections()
        
        # 连接主题变化信号
        self.theme_manager.dark_mode_changed.connect(self.update_table_theme)
        
        # 加载配置
        self.load_config()
        
        # 初始化表格主题
        self.update_table_theme(self.theme_manager._dark_mode)
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("🛡️ 威胁情报查询")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(title_label)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # IP信誉查询标签页
        self.create_ip_reputation_tab()
        
        # 域名失陷检测标签页
        self.create_dns_query_tab()
        
        # 文件分析标签页
        self.create_file_analysis_tab()
        
        # 配置标签页
        self.create_config_tab()
    
    def create_ip_reputation_tab(self):
        """创建IP信誉查询标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 查询控件
        query_group = self.create_ip_query_controls()
        layout.addWidget(query_group)
        
        # 结果显示
        result_group = self.create_ip_results_display()
        layout.addWidget(result_group)
        
        # 设置滚动区域的内容
        scroll_area.setWidget(tab)
        
        self.tab_widget.addTab(scroll_area, "IP信誉查询")
    
    def create_ip_query_controls(self) -> QWidget:
        """创建IP查询控件"""
        group = QGroupBox("查询设置")
        layout = QGridLayout(group)
        
        # IP输入
        layout.addWidget(QLabel("IP地址:"), 0, 0)
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("输入IP地址，如: 8.8.8.8")
        layout.addWidget(self.ip_input, 0, 1, 1, 2)
        
        # 语言选择
        layout.addWidget(QLabel("语言:"), 1, 0)
        self.ip_lang_combo = QComboBox()
        self.ip_lang_combo.addItems(["中文", "English"])
        layout.addWidget(self.ip_lang_combo, 1, 1)
        
        # 高级查询选项
        advanced_group = QGroupBox("高级选项 (v5 API)")
        advanced_layout = QGridLayout(advanced_group)
        
        self.include_malware_family = QCheckBox("包含恶意软件家族")
        self.include_malware_family.setChecked(True)
        advanced_layout.addWidget(self.include_malware_family, 0, 0)
        
        self.include_campaign = QCheckBox("包含攻击活动")
        self.include_campaign.setChecked(True)
        advanced_layout.addWidget(self.include_campaign, 0, 1)
        
        self.include_actor = QCheckBox("包含威胁行为者")
        self.include_actor.setChecked(True)
        advanced_layout.addWidget(self.include_actor, 1, 0)
        
        self.include_ttp = QCheckBox("包含TTP信息")
        self.include_ttp.setChecked(True)
        advanced_layout.addWidget(self.include_ttp, 1, 1)
        
        self.include_cve = QCheckBox("包含CVE信息")
        self.include_cve.setChecked(True)
        advanced_layout.addWidget(self.include_cve, 2, 0)
        
        layout.addWidget(advanced_group, 2, 0, 1, 3)
        
        # 查询按钮
        self.ip_query_btn = QPushButton("🔍 查询IP信誉")
        self.ip_query_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        layout.addWidget(self.ip_query_btn, 3, 1)
        
        # 批量查询按钮
        self.batch_ip_query_btn = QPushButton("📋 批量查询")
        self.batch_ip_query_btn.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)
        layout.addWidget(self.batch_ip_query_btn, 3, 2)
        
        # 进度条
        self.ip_progress = QProgressBar()
        self.ip_progress.setVisible(False)
        layout.addWidget(self.ip_progress, 4, 0, 1, 3)
        
        # 状态标签
        self.ip_status_label = QLabel("就绪")
        self.ip_status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(self.ip_status_label, 5, 0, 1, 3)
        
        return group
    
    def create_ip_results_display(self) -> QWidget:
        """创建IP结果显示区域"""
        group = QGroupBox("查询结果")
        layout = QVBoxLayout(group)
        
        # 结果表格
        self.ip_results_table = QTableWidget()
        self.ip_results_table.setColumnCount(10)
        self.ip_results_table.setHorizontalHeaderLabels([
            "IP地址", "信誉等级", "威胁评分", "威胁类型", "恶意软件家族", "攻击活动", "位置", "首次发现", "查询时间", "详情链接"
        ])
        
        # 设置表格属性
        header = self.ip_results_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        
        # 设置表格选择模式
        self.ip_results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ip_results_table.setAlternatingRowColors(True)
        
        # 隐藏垂直表头（行号）
        self.ip_results_table.verticalHeader().setVisible(False)
        
        # 设置表格最小高度
        self.ip_results_table.setMinimumHeight(200)  # 设置表格最小高度
        
        # 设置行高
        self.ip_results_table.verticalHeader().setDefaultSectionSize(40)  # 设置默认行高为40像素
        self.ip_results_table.verticalHeader().setMinimumSectionSize(35)   # 设置最小行高为35像素
        
        # 设置列宽
        self.ip_results_table.setColumnWidth(0, 120)  # IP地址
        self.ip_results_table.setColumnWidth(1, 80)   # 信誉等级
        self.ip_results_table.setColumnWidth(2, 80)   # 置信度
        self.ip_results_table.setColumnWidth(3, 150)  # 威胁类型
        self.ip_results_table.setColumnWidth(4, 200)  # 位置
        self.ip_results_table.setColumnWidth(5, 150)  # 查询时间
        
        layout.addWidget(self.ip_results_table)
        
        # 连接双击事件显示详细信息弹窗
        self.ip_results_table.itemDoubleClicked.connect(self.show_ip_detail_dialog)
        # 连接单击事件处理permalink链接
        self.ip_results_table.itemClicked.connect(self.handle_table_item_click)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.ip_export_btn = QPushButton("📄 导出结果")
        self.ip_clear_btn = QPushButton("🗑️ 清空结果")
        
        btn_layout.addWidget(self.ip_export_btn)
        btn_layout.addWidget(self.ip_clear_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        return group
    
    def create_dns_query_tab(self):
        """创建域名失陷检测标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 查询控件
        query_group = self.create_dns_query_controls()
        layout.addWidget(query_group)
        
        # 结果显示
        result_group = self.create_dns_results_display()
        layout.addWidget(result_group)
        
        # 设置滚动区域的内容
        scroll_area.setWidget(tab)
        
        self.tab_widget.addTab(scroll_area, "域名失陷检测")
    
    def create_dns_query_controls(self) -> QWidget:
        """创建域名失陷检测控件"""
        group = QGroupBox("域名失陷检测")
        layout = QGridLayout(group)
        
        # 域名输入
        layout.addWidget(QLabel("域名:"), 0, 0)
        self.dns_input = QLineEdit()
        self.dns_input.setPlaceholderText("输入域名，如: example.com")
        layout.addWidget(self.dns_input, 0, 1, 1, 2)
        
        # 查询按钮
        self.dns_query_btn = QPushButton("🔍 检测域名失陷")
        self.dns_query_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        layout.addWidget(self.dns_query_btn, 1, 0, 1, 3)
        
        # 进度条
        self.dns_progress = QProgressBar()
        self.dns_progress.setVisible(False)
        layout.addWidget(self.dns_progress, 2, 0, 1, 3)
        
        # 状态标签
        self.dns_status_label = QLabel("就绪")
        self.dns_status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(self.dns_status_label, 3, 0, 1, 3)
        
        return group
    
    def create_dns_results_display(self) -> QWidget:
        """创建域名失陷检测结果显示区域"""
        group = QGroupBox("失陷检测结果")
        layout = QVBoxLayout(group)
        
        # 结果表格
        self.dns_results_table = QTableWidget()
        self.dns_results_table.setColumnCount(7)
        self.dns_results_table.setHorizontalHeaderLabels([
            "域名", "失陷状态", "威胁类型", "置信度", "恶意软件家族", "威胁等级", "详情链接"
        ])
        
        # 设置表格属性
        header = self.dns_results_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        # 隐藏垂直表头（行号）
        self.dns_results_table.verticalHeader().setVisible(False)
        
        # 设置表格最小高度
        self.dns_results_table.setMinimumHeight(200)
        
        # 设置行高
        self.dns_results_table.verticalHeader().setDefaultSectionSize(40)
        self.dns_results_table.verticalHeader().setMinimumSectionSize(35)
        
        layout.addWidget(self.dns_results_table)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.dns_export_btn = QPushButton("📄 导出结果")
        self.dns_clear_btn = QPushButton("🗑️ 清空结果")
        
        btn_layout.addWidget(self.dns_export_btn)
        btn_layout.addWidget(self.dns_clear_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        return group
    
    def create_file_analysis_tab(self):
        """创建文件分析标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 查询控件
        query_group = self.create_file_query_controls()
        layout.addWidget(query_group)
        
        # 结果显示
        result_group = self.create_file_results_display()
        layout.addWidget(result_group)
        
        # 设置滚动区域的内容
        scroll_area.setWidget(tab)
        
        self.tab_widget.addTab(scroll_area, "文件分析")
    
    def create_file_query_controls(self) -> QWidget:
        """创建文件查询控件"""
        group = QGroupBox("文件分析")
        layout = QGridLayout(group)
        
        # 查询方式选择
        layout.addWidget(QLabel("查询方式:"), 0, 0)
        self.file_query_type = QComboBox()
        self.file_query_type.addItems(["哈希查询", "文件上传"])
        layout.addWidget(self.file_query_type, 0, 1)
        
        # 哈希输入
        self.file_hash_label = QLabel("文件哈希:")
        layout.addWidget(self.file_hash_label, 1, 0)
        self.file_hash_input = QLineEdit()
        self.file_hash_input.setPlaceholderText("输入文件哈希值 (SHA256/MD5/SHA1)")
        layout.addWidget(self.file_hash_input, 1, 1, 1, 2)
        
        # 哈希类型
        self.hash_type_label = QLabel("哈希类型:")
        layout.addWidget(self.hash_type_label, 2, 0)
        self.hash_type_combo = QComboBox()
        self.hash_type_combo.addItems(["SHA256", "MD5", "SHA1"])
        layout.addWidget(self.hash_type_combo, 2, 1)
        
        # 文件选择
        self.file_path_label = QLabel("选择文件:")
        layout.addWidget(self.file_path_label, 3, 0)
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("选择要上传分析的文件")
        self.file_path_input.setEnabled(False)
        layout.addWidget(self.file_path_input, 3, 1)
        
        self.file_browse_btn = QPushButton("📁 浏览")
        self.file_browse_btn.setEnabled(False)
        layout.addWidget(self.file_browse_btn, 3, 2)
        
        # 沙箱类型选择
        self.sandbox_type_label = QLabel("沙箱类型:")
        layout.addWidget(self.sandbox_type_label, 4, 0)
        self.sandbox_type_combo = QComboBox()
        # 根据官方文档添加所有支持的沙箱类型
        sandbox_types = [
            # Windows 环境
            ("Windows 7 SP1 x64 + Office 2013", "win7_sp1_enx64_office2013"),
            ("Windows 7 SP1 x86 + Office 2013", "win7_sp1_enx86_office2013"),
            ("Windows 7 SP1 x86 + Office 2010", "win7_sp1_enx86_office2010"),
            ("Windows 7 SP1 x86 + Office 2007", "win7_sp1_enx86_office2007"),
            ("Windows 7 SP1 x86 + Office 2003", "win7_sp1_enx86_office2003"),
            ("Windows 10 1903 x64 + Office 2016", "win10_1903_enx64_office2016"),
            # Linux 环境
            ("Ubuntu 17.04 x64", "ubuntu_1704_x64"),
            ("CentOS 7 x64", "centos_7_x64"),
            # 麒麟环境
            ("银河麒麟桌面版 V10", "kylin_desktop_v10")
        ]
        
        for display_name, value in sandbox_types:
            self.sandbox_type_combo.addItem(display_name, value)
        
        self.sandbox_type_combo.setEnabled(False)
        layout.addWidget(self.sandbox_type_combo, 4, 1)
        
        # 运行时间设置
        self.run_time_label = QLabel("运行时间:")
        layout.addWidget(self.run_time_label, 5, 0)
        self.run_time_spin = QSpinBox()
        self.run_time_spin.setRange(30, 300)  # 30秒到5分钟
        self.run_time_spin.setValue(60)  # 默认60秒
        self.run_time_spin.setSuffix(" 秒")
        self.run_time_spin.setEnabled(False)
        layout.addWidget(self.run_time_spin, 5, 1)
        
        # 查询按钮
        btn_layout = QHBoxLayout()
        
        self.file_query_btn = QPushButton("🔍 查询文件报告")
        self.file_query_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        
        self.file_multiengine_btn = QPushButton("🛡️ 多引擎检测")
        self.file_multiengine_btn.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
        """)
        
        btn_layout.addWidget(self.file_query_btn)
        btn_layout.addWidget(self.file_multiengine_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout, 6, 0, 1, 3)
        
        # 进度条
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        layout.addWidget(self.file_progress, 7, 0, 1, 3)
        
        # 状态标签
        self.file_status_label = QLabel("就绪")
        self.file_status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        layout.addWidget(self.file_status_label, 8, 0, 1, 3)
        
        return group
    
    def create_file_results_display(self) -> QWidget:
        """创建文件结果显示区域"""
        group = QGroupBox("分析结果")
        layout = QVBoxLayout(group)
        
        # 结果表格
        self.file_results_table = QTableWidget()
        self.file_results_table.setColumnCount(5)
        self.file_results_table.setHorizontalHeaderLabels([
            "文件名", "SHA256", "文件大小", "分析状态", "操作"
        ])
        
        # 设置表格属性
        header = self.file_results_table.horizontalHeader()
        
        # 设置列宽模式 - 更灵活的列宽分配
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # 文件名 - 可调整
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # SHA256 - 可调整
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 文件大小 - 自适应内容
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # 分析状态/信誉等级 - 可调整
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # 操作/威胁类型 - 拉伸填充
        
        # 设置初始列宽
        self.file_results_table.setColumnWidth(0, 150)  # 文件名
        self.file_results_table.setColumnWidth(1, 120)  # SHA256
        self.file_results_table.setColumnWidth(3, 100)  # 分析状态/信誉等级
        
        # 隐藏垂直表头（行号）
        self.file_results_table.verticalHeader().setVisible(False)
        
        # 设置表格高度和滚动
        self.file_results_table.setMinimumHeight(250)
        self.file_results_table.setMaximumHeight(400)
        
        # 设置行高
        self.file_results_table.verticalHeader().setDefaultSectionSize(50)
        self.file_results_table.verticalHeader().setMinimumSectionSize(45)
        
        # 启用水平滚动条
        self.file_results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_results_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 设置选择行为
        self.file_results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_results_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.file_results_table)
        
        # 详细信息显示
        self.file_detail_text = QPlainTextEdit()
        self.file_detail_text.setPlaceholderText("点击表格行查看详细信息...")
        self.file_detail_text.setMinimumHeight(400)
        self.file_detail_text.setMaximumHeight(800)
        self.file_detail_text.setMinimumWidth(800)
        layout.addWidget(self.file_detail_text)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        self.file_export_btn = QPushButton("📄 导出结果")
        self.file_clear_btn = QPushButton("🗑️ 清空结果")
        
        btn_layout.addWidget(self.file_export_btn)
        btn_layout.addWidget(self.file_clear_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        return group
    
    def create_config_tab(self):
        """创建配置标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # API配置
        config_group = QGroupBox("API配置")
        config_layout = QGridLayout(config_group)
        
        # API密钥
        config_layout.addWidget(QLabel("API密钥:"), 0, 0)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入微步威胁情报API密钥")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        config_layout.addWidget(self.api_key_input, 0, 1)
        
        # 显示/隐藏密钥
        self.show_key_btn = QPushButton("👁️ 显示")
        self.show_key_btn.setMinimumWidth(80)
        self.show_key_btn.setMaximumWidth(100)
        config_layout.addWidget(self.show_key_btn, 0, 2)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 测试连接
        self.test_connection_btn = QPushButton("🔗 测试连接")
        self.test_connection_btn.setStyleSheet("""
            QPushButton {
                background-color: #f39c12;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #e67e22;
            }
        """)
        button_layout.addWidget(self.test_connection_btn)
        
        # 保存配置
        self.save_config_btn = QPushButton("💾 保存配置")
        self.save_config_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        button_layout.addWidget(self.save_config_btn)
        
        # 添加按钮布局到网格布局
        config_layout.addLayout(button_layout, 1, 0, 1, 3)
        
        # 连接状态
        self.connection_status_label = QLabel("未测试")
        self.connection_status_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        config_layout.addWidget(self.connection_status_label, 2, 0, 1, 3)
        
        layout.addWidget(config_group)
        
        # 使用说明
        help_group = QGroupBox("使用说明")
        help_layout = QVBoxLayout(help_group)
        
        help_text = QPlainTextEdit()
        help_text.setPlainText("""
微步威胁情报查询工具使用说明：

1. API配置：
   - 在配置标签页中输入您的微步威胁情报API密钥
   - 点击"测试连接"验证API密钥是否有效
   - 点击"保存配置"保存设置

2. IP信誉查询：
   - 输入要查询的IP地址
   - 选择查询结果的语言
   - 点击"查询IP信誉"获取结果

3. 域名失陷检测：
   - 输入要检测的域名
   - 点击"检测域名失陷"获取域名安全状态
   - 查看域名是否被恶意利用或失陷

4. 文件分析：
   - 哈希查询：输入文件哈希值进行查询
   - 文件上传：选择本地文件上传进行分析
   - 支持SHA256、MD5、SHA1哈希格式
   - 可查看详细报告和多引擎检测结果

5. 结果导出：
   - 所有查询结果都可以导出为Excel或JSON格式
   - 点击表格行可查看详细信息

注意事项：
- 请确保您有有效的微步威胁情报API权限
- 查询频率受API限制，请合理使用
- 文件上传功能需要相应的API权限
        """)
        help_text.setReadOnly(True)
        help_layout.addWidget(help_text)
        
        layout.addWidget(help_group)
        layout.addStretch()
        
        # 设置滚动区域的内容
        scroll_area.setWidget(tab)
        
        self.tab_widget.addTab(scroll_area, "配置与帮助")
    
    def setup_connections(self):
        """设置信号连接"""
        # IP查询
        self.ip_query_btn.clicked.connect(self.start_ip_query)
        self.batch_ip_query_btn.clicked.connect(self.start_batch_ip_query)
        self.ip_export_btn.clicked.connect(self.export_ip_results)
        self.ip_clear_btn.clicked.connect(self.clear_ip_results)
        
        # DNS查询
        self.dns_query_btn.clicked.connect(self.start_dns_query)
        self.dns_export_btn.clicked.connect(self.export_dns_results)
        self.dns_clear_btn.clicked.connect(self.clear_dns_results)
        self.dns_results_table.itemClicked.connect(self.handle_dns_table_item_click)
        
        # 文件分析
        self.file_query_type.currentTextChanged.connect(self.on_file_query_type_changed)
        self.file_browse_btn.clicked.connect(self.browse_file)
        self.file_query_btn.clicked.connect(self.start_file_query)
        self.file_multiengine_btn.clicked.connect(self.start_multiengine_query)
        self.file_export_btn.clicked.connect(self.export_file_results)
        self.file_clear_btn.clicked.connect(self.clear_file_results)
        self.file_results_table.itemSelectionChanged.connect(self.show_file_detail)
        
        # 配置
        self.show_key_btn.clicked.connect(self.toggle_key_visibility)
        self.test_connection_btn.clicked.connect(self.test_api_connection)
        self.save_config_btn.clicked.connect(self.save_config)
        
        # 设置初始状态
        self.file_query_type.setCurrentIndex(0)  # 确保默认选择哈希查询
        self.on_file_query_type_changed("哈希查询")  # 强制设置初始状态
    
    def on_file_query_type_changed(self, query_type: str):
        """文件查询类型改变"""
        if query_type == "哈希查询":
            # 显示哈希查询相关控件
            self.file_hash_label.setVisible(True)
            self.file_hash_input.setVisible(True)
            self.file_hash_input.setEnabled(True)
            self.hash_type_label.setVisible(True)
            self.hash_type_combo.setVisible(True)
            self.hash_type_combo.setEnabled(True)
            
            # 显示沙箱类型选择（哈希查询也需要）
            self.sandbox_type_label.setVisible(True)
            self.sandbox_type_combo.setVisible(True)
            self.sandbox_type_combo.setEnabled(True)
            
            # 显示多引擎检测按钮（哈希查询需要）
            self.file_multiengine_btn.setVisible(True)
            
            # 隐藏文件上传相关控件
            self.file_path_label.setVisible(False)
            self.file_path_input.setVisible(False)
            self.file_browse_btn.setVisible(False)
            self.run_time_label.setVisible(False)
            self.run_time_spin.setVisible(False)
            
            # 更新按钮文本和提示
            self.file_query_btn.setText("🔍 查询哈希报告")
            self.file_hash_input.setPlaceholderText("输入文件哈希值 (SHA256/MD5/SHA1)")
            self.file_status_label.setText("请输入文件哈希值进行查询")
            
            # 更新表格结构为哈希查询适用的字段
            self.file_results_table.setColumnCount(9)
            self.file_results_table.setHorizontalHeaderLabels([
                "文件名", "SHA256", "威胁等级", "木马/病毒家族", "威胁分类", "多引擎检出", "沙箱环境", "提交时间", "操作"
            ])
            
            # 重新设置列宽（哈希查询模式）
            self.file_results_table.setColumnWidth(0, 120)  # 文件名
            self.file_results_table.setColumnWidth(1, 180)  # SHA256
            self.file_results_table.setColumnWidth(2, 100)  # 威胁等级
            self.file_results_table.setColumnWidth(3, 120)  # 木马/病毒家族
            self.file_results_table.setColumnWidth(4, 150)  # 威胁分类
            self.file_results_table.setColumnWidth(5, 100)  # 多引擎检出
            self.file_results_table.setColumnWidth(6, 120)  # 沙箱环境
            self.file_results_table.setColumnWidth(7, 130)  # 提交时间
            self.file_results_table.setColumnWidth(8, 200)  # 操作列操作 - 增加宽度容纳两个按钮
            
        else:  # 文件上传
            # 隐藏哈希查询相关控件
            self.file_hash_label.setVisible(False)
            self.file_hash_input.setVisible(False)
            self.hash_type_label.setVisible(False)
            self.hash_type_combo.setVisible(False)
            
            # 隐藏多引擎检测按钮（文件上传不需要）
            self.file_multiengine_btn.setVisible(False)
            
            # 显示文件上传相关控件
            self.file_path_label.setVisible(True)
            self.file_path_input.setVisible(True)
            self.file_path_input.setEnabled(True)
            self.file_browse_btn.setVisible(True)
            self.file_browse_btn.setEnabled(True)
            self.sandbox_type_label.setVisible(True)
            self.sandbox_type_combo.setVisible(True)
            self.sandbox_type_combo.setEnabled(True)
            self.run_time_label.setVisible(True)
            self.run_time_spin.setVisible(True)
            self.run_time_spin.setEnabled(True)
            
            # 更新按钮文本和提示
            self.file_query_btn.setText("🔍 上传文件分析")
            self.file_path_input.setPlaceholderText("选择要上传分析的文件")
            self.file_status_label.setText("请选择文件并配置沙箱环境进行分析")
            
            # 更新表格结构为文件上传适用的字段
            self.file_results_table.setColumnCount(5)
            self.file_results_table.setHorizontalHeaderLabels([
                "文件名", "SHA256", "文件大小", "分析状态", "操作"
            ])
            
            # 重新设置列宽（文件上传模式）
            self.file_results_table.setColumnWidth(0, 180)  # 文件名（稍宽一些）
            self.file_results_table.setColumnWidth(1, 120)  # SHA256
            self.file_results_table.setColumnWidth(3, 100)  # 分析状态
            self.file_results_table.setColumnWidth(4, 200)  # 操作列操作 - 增加宽度容纳两个按钮
        
        # 清空表格数据，防止数据残留
        self.file_results_table.setRowCount(0)
        
        # 强制刷新表格显示
        self.file_results_table.viewport().update()
        self.file_results_table.repaint()
    
    def browse_file(self):
        """浏览文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择要分析的文件", "", "所有文件 (*.*)"
        )
        if file_path:
            self.file_path_input.setText(file_path)
    
    def toggle_key_visibility(self):
        """切换API密钥可见性"""
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("🙈 隐藏")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("👁️ 显示")
    
    def start_ip_query(self):
        """开始IP查询"""
        ip = self.ip_input.text().strip()
        if not ip:
            QMessageBox.warning(self, "警告", "请输入IP地址")
            return
        
        if not self.threatbook_api.api_key:
            QMessageBox.warning(self, "警告", "请先配置API密钥")
            return
        
        # 设置语言
        lang = 'zh' if self.ip_lang_combo.currentText() == '中文' else 'en'
        
        # 获取高级选项
        advanced_options = {
            'lang': lang,
            'include_malware_family': self.include_malware_family.isChecked(),
            'include_campaign': self.include_campaign.isChecked(),
            'include_actor': self.include_actor.isChecked(),
            'include_ttp': self.include_ttp.isChecked(),
            'include_cve': self.include_cve.isChecked()
        }
        
        # 启动查询线程
        self.query_thread = ThreatIntelQueryThread(
            self.threatbook_api, "ip_reputation", ip, **advanced_options
        )
        self.query_thread.progress_updated.connect(self.ip_status_label.setText)
        self.query_thread.query_completed.connect(self.on_ip_query_completed)
        
        # 更新UI状态
        self.ip_query_btn.setEnabled(False)
        self.ip_progress.setVisible(True)
        self.ip_progress.setRange(0, 0)  # 不确定进度
        
        self.query_thread.start()
    
    def start_batch_ip_query(self):
        """开始批量IP查询"""
        if not self.threatbook_api.api_key:
            QMessageBox.warning(self, "警告", "请先配置API密钥")
            return
        
        # 弹出对话框让用户输入IP列表
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, 
            "批量IP查询", 
            "请输入IP地址列表（每行一个IP）：",
            ""
        )
        
        if not ok or not text.strip():
            return
        
        # 解析IP列表
        ip_list = [ip.strip() for ip in text.strip().split('\n') if ip.strip()]
        if not ip_list:
            QMessageBox.warning(self, "警告", "请输入有效的IP地址")
            return
        
        # 确认查询
        reply = QMessageBox.question(
            self, 
            "确认批量查询", 
            f"将查询 {len(ip_list)} 个IP地址，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 设置语言和高级选项
        lang = 'zh' if self.ip_lang_combo.currentText() == '中文' else 'en'
        advanced_options = {
            'lang': lang,
            'include_malware_family': self.include_malware_family.isChecked(),
            'include_campaign': self.include_campaign.isChecked(),
            'include_actor': self.include_actor.isChecked(),
            'include_ttp': self.include_ttp.isChecked(),
            'include_cve': self.include_cve.isChecked()
        }
        
        # 启动批量查询线程
        self.batch_query_thread = BatchIPQueryThread(
            self.threatbook_api, ip_list, **advanced_options
        )
        self.batch_query_thread.progress_updated.connect(self.ip_status_label.setText)
        self.batch_query_thread.single_query_completed.connect(self.on_single_ip_completed)
        self.batch_query_thread.batch_query_completed.connect(self.on_batch_ip_completed)
        
        # 更新UI状态
        self.ip_query_btn.setEnabled(False)
        self.batch_ip_query_btn.setEnabled(False)
        self.ip_progress.setVisible(True)
        self.ip_progress.setRange(0, len(ip_list))
        self.ip_progress.setValue(0)
        
        self.batch_query_thread.start()
    
    def on_single_ip_completed(self, result: Dict, current: int, total: int):
        """单个IP查询完成"""
        if result['success']:
            self.add_ip_result(result['result'])
        
        # 更新进度
        self.ip_progress.setValue(current)
        self.ip_status_label.setText(f"批量查询进行中... ({current}/{total})")
    
    def on_batch_ip_completed(self, success_count: int, total_count: int):
        """批量IP查询完成"""
        self.ip_query_btn.setEnabled(True)
        self.batch_ip_query_btn.setEnabled(True)
        self.ip_progress.setVisible(False)
        
        self.ip_status_label.setText(f"批量查询完成: 成功 {success_count}/{total_count}")
        QMessageBox.information(
            self, 
            "批量查询完成", 
            f"批量查询完成！\n成功查询: {success_count}\n总数: {total_count}"
        )
    
    def on_ip_query_completed(self, result: Dict):
        """IP查询完成"""
        self.ip_query_btn.setEnabled(True)
        self.ip_progress.setVisible(False)
        
        if result['success']:
            self.add_ip_result(result['result'])
            self.ip_status_label.setText("查询完成")
        else:
            error_msg = result['result'].get('error', '未知错误')
            QMessageBox.critical(self, "查询失败", f"IP查询失败: {error_msg}")
            self.ip_status_label.setText(f"查询失败: {error_msg}")
    
    def add_ip_result(self, result: Dict):
        """添加IP查询结果到表格"""
        row = self.ip_results_table.rowCount()
        self.ip_results_table.insertRow(row)
        
        # 提取地理位置信息
        location = result.get('location', {})
        location_str = f"{location.get('country', '')} {location.get('province', '')} {location.get('city', '')}".strip()
        if not location_str:
            location_str = '未知'
        
        # 提取威胁类型，优先使用judgments
        threat_types = result.get('threat_types', [])
        judgments = result.get('judgments', [])
        threat_display = ', '.join(judgments) if judgments else ', '.join(threat_types)
        if not threat_display:
            threat_display = '无'
        
        # 提取恶意软件家族
        malware_families = result.get('malware_families', [])
        malware_display = ', '.join([mf.get('name', '') for mf in malware_families]) if malware_families else '无'
        
        # 提取攻击活动
        campaigns = result.get('campaigns', [])
        campaign_display = ', '.join([c.get('name', '') for c in campaigns]) if campaigns else '无'
        
        # 获取permalink链接
        permalink = result.get('permalink', '')
        permalink_display = '查看详情' if permalink else '无链接'
        
        # 填充数据
        items = [
            result.get('ip', ''),
            result.get('reputation_level', '未知'),
            str(result.get('threat_score', 0)),
            threat_display,
            malware_display,
            campaign_display,
            location_str,
            result.get('first_seen', '未知'),
            result.get('query_time', ''),
            permalink_display
        ]
        
        for col, item in enumerate(items):
            table_item = QTableWidgetItem(str(item))
            
            # 特殊处理permalink列（最后一列）
            if col == len(items) - 1 and permalink:  # 详情链接列
                table_item.setForeground(QColor(0, 100, 200))  # 蓝色链接文本
                table_item.setData(Qt.ItemDataRole.UserRole + 1, permalink)  # 存储permalink链接
                table_item.setToolTip(f"点击打开详情页面: {permalink}")
            
            # 根据信誉等级设置颜色（除了链接列）
            if col != len(items) - 1:  # 不是链接列
                reputation = result.get('reputation_level', '未知')
                if reputation == '恶意':
                    table_item.setBackground(QColor(255, 200, 200))  # 红色背景
                    table_item.setForeground(QColor(0, 0, 0))  # 黑色文本
                elif reputation in ['高危', '中危']:
                    table_item.setBackground(QColor(255, 235, 200))  # 橙色背景
                    table_item.setForeground(QColor(0, 0, 0))  # 黑色文本
                elif reputation == '良好':
                    table_item.setBackground(QColor(200, 255, 200))  # 绿色背景
                    table_item.setForeground(QColor(0, 0, 0))  # 黑色文本
                # 其他情况使用主题默认颜色，不强制设置
            
            table_item.setData(Qt.ItemDataRole.UserRole, result)  # 存储完整数据
            self.ip_results_table.setItem(row, col, table_item)
        
        # 保存到结果列表
        self.query_results.append({
            'type': 'ip_reputation',
            'data': result
        })
    
    def handle_table_item_click(self, item):
        """处理表格项点击事件，特别是permalink链接"""
        if item:
            # 检查是否是最后一列（详情链接列）
            if item.column() == self.ip_results_table.columnCount() - 1:
                # 获取存储的permalink链接
                permalink = item.data(Qt.ItemDataRole.UserRole + 1)
                if permalink:
                    try:
                        # 打开链接
                        QDesktopServices.openUrl(QUrl(permalink))
                    except Exception as e:
                        QMessageBox.warning(self, "打开链接失败", f"无法打开链接: {str(e)}")
    
    def handle_dns_table_item_click(self, item):
        """处理域名失陷检测表格项点击事件"""
        if item:
            # 检查是否点击的是最后一列（permalink列）
            if item.column() == self.dns_results_table.columnCount() - 1:
                # 获取存储的permalink
                permalink = item.data(Qt.ItemDataRole.UserRole + 1)
                if permalink:
                    try:
                        # 打开链接
                        QDesktopServices.openUrl(QUrl(permalink))
                    except Exception as e:
                        QMessageBox.warning(self, "打开链接失败", f"无法打开链接: {str(e)}")
    
    def show_ip_detail_dialog(self, item):
        """显示IP详细信息弹窗"""
        if item:
            result = item.data(Qt.ItemDataRole.UserRole)
            if result:
                # 格式化显示内容
                detail_text = json.dumps(result, indent=2, ensure_ascii=False)
                
                # 设置主要信息
                ip = result.get('ip', '未知')
                reputation = result.get('reputation_level', '未知')
                confidence = result.get('confidence', '未知')
                location = result.get('location', {})
                location_str = f"{location.get('country', '')} {location.get('province', '')} {location.get('city', '')}".strip()
                
                main_info = f"""🌐 IP地址: {ip}
🛡️ 信誉等级: {reputation}
📊 置信度: {confidence}
📍 地理位置: {location_str}
⚠️ 威胁类型: {', '.join(result.get('judgments', []))}"""
                
                # 创建现代化弹窗
                dialog = ModernDetailDialog("IP威胁情报详情", main_info, detail_text, self)
                dialog.exec()
    
    def update_table_theme(self, is_dark_mode: bool):
        """根据主题模式更新表格样式"""
        if is_dark_mode:
            # 暗色模式样式
            style = """
                QTableWidget {
                    background-color: #2d2d2d;
                    color: #f0f0f0;
                    gridline-color: #3d3d3d;
                    selection-background-color: #483d8b;
                    selection-color: #ffffff;
                    alternate-background-color: #333333;
                }
                QTableWidget::item {
                    background-color: #2d2d2d;
                    color: #f0f0f0;
                    padding: 12px 8px;
                    border: none;
                }
                QTableWidget::item:selected {
                    background-color: #483d8b;
                    color: #ffffff;
                }
                QTableWidget::item:hover {
                    background-color: #3d3d3d;
                }
                QHeaderView::section {
                    background-color: #2d2d2d;
                    color: #f0f0f0;
                    padding: 8px;
                    border: 1px solid #3d3d3d;
                    font-weight: bold;
                }
            """
        else:
            # 亮色模式样式
            style = """
                QTableWidget {
                    background-color: #ffffff;
                    color: #343a40;
                    gridline-color: #dee2e6;
                    selection-background-color: #007bff;
                    selection-color: #ffffff;
                    alternate-background-color: #f8f9fa;
                }
                QTableWidget::item {
                    background-color: #ffffff;
                    color: #343a40;
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
                QHeaderView::section {
                    background-color: #f8f9fa;
                    color: #343a40;
                    padding: 8px;
                    border: 1px solid #dee2e6;
                    font-weight: bold;
                }
            """
        
        # 应用样式到所有表格
        if hasattr(self, 'ip_results_table'):
            self.ip_results_table.setStyleSheet(style)
        if hasattr(self, 'dns_results_table'):
            self.dns_results_table.setStyleSheet(style)
        if hasattr(self, 'file_results_table'):
            self.file_results_table.setStyleSheet(style)
    
    def start_dns_query(self):
        """开始域名失陷检测"""
        domain = self.dns_input.text().strip()
        if not domain:
            QMessageBox.warning(self, "警告", "请输入域名")
            return
        
        if not self.threatbook_api.api_key:
            QMessageBox.warning(self, "警告", "请先配置API密钥")
            return
        
        # 启动查询线程
        self.query_thread = ThreatIntelQueryThread(
            self.threatbook_api, "dns_compromise", domain
        )
        self.query_thread.progress_updated.connect(self.dns_status_label.setText)
        self.query_thread.query_completed.connect(self.on_dns_query_completed)
        
        # 更新UI状态
        self.dns_query_btn.setEnabled(False)
        self.dns_progress.setVisible(True)
        self.dns_progress.setRange(0, 0)
        
        self.query_thread.start()
    
    def on_dns_query_completed(self, result: Dict):
        """域名失陷检测完成"""
        self.dns_query_btn.setEnabled(True)
        self.dns_progress.setVisible(False)
        
        if result['success']:
            self.add_dns_results(result['result'])
            self.dns_status_label.setText("检测完成")
        else:
            error_msg = result['result'].get('error', '未知错误')
            QMessageBox.critical(self, "检测失败", f"域名失陷检测失败: {error_msg}")
            self.dns_status_label.setText(f"检测失败: {error_msg}")
    
    def add_dns_results(self, result: Dict):
        """添加域名失陷检测结果到表格"""
        # 添加调试日志
        print(f"[DEBUG] UI接收到的DNS结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        row = self.dns_results_table.rowCount()
        self.dns_results_table.insertRow(row)
        
        # 格式化失陷状态
        is_malicious = result.get('is_malicious', False)
        compromise_status = "已失陷" if is_malicious else "正常"
        
        # 格式化威胁类型
        judgments = result.get('judgments', [])
        threat_types = ', '.join(judgments) if judgments else '无'
        
        # 格式化恶意软件家族
        malware_families = result.get('malware_families', [])
        malware_family_str = ', '.join(malware_families) if malware_families else '无'
        
        # 格式化威胁等级
        severity = result.get('severity', '无威胁')
        
        # 格式化置信度
        confidence_level = result.get('confidence_level', '未知')
        
        # 处理permalink
        permalink = result.get('permalink', '').strip()
        permalink_display = "查看详情" if permalink else "无链接"
        
        items = [
            result.get('domain', ''),
            compromise_status,
            threat_types,
            confidence_level,
            malware_family_str,
            severity,
            permalink_display
        ]
        
        for col, item in enumerate(items):
            table_item = QTableWidgetItem(str(item))
            
            # 如果域名已失陷，设置红色背景（除了permalink列）
            if col == 1 and is_malicious:
                table_item.setBackground(QColor(255, 200, 200))
            
            # 为permalink列设置特殊样式
            if col == len(items) - 1:  # 最后一列是permalink列
                if permalink:
                    table_item.setForeground(QColor(0, 100, 200))  # 蓝色文字
                    table_item.setData(Qt.ItemDataRole.UserRole + 1, permalink)  # 存储permalink
                    table_item.setToolTip(f"点击查看详情: {permalink}")
                else:
                    table_item.setForeground(QColor(128, 128, 128))  # 灰色文字
            
            table_item.setData(Qt.ItemDataRole.UserRole, result)  # 存储完整数据
            self.dns_results_table.setItem(row, col, table_item)
        
        # 保存到结果列表
        self.query_results.append({
            'type': 'dns_compromise',
            'data': result
        })
    
    def start_file_query(self):
        """开始文件查询"""
        if not self.threatbook_api.api_key:
            QMessageBox.warning(self, "警告", "请先配置API密钥")
            return
        
        query_type = self.file_query_type.currentText()
        
        if query_type == "哈希查询":
            file_hash = self.file_hash_input.text().strip()
            if not file_hash:
                QMessageBox.warning(self, "警告", "请输入文件哈希值")
                return
            
            # 清空表格，避免数据混合显示
            self.file_results_table.setRowCount(0)
            
            hash_type = self.hash_type_combo.currentText().lower()
            sandbox_type = self.sandbox_type_combo.currentData()
            
            # 启动查询线程
            self.query_thread = ThreatIntelQueryThread(
                self.threatbook_api, "file_report", file_hash, 
                resource_type=hash_type, sandbox_type=sandbox_type
            )
        else:  # 文件上传
            file_path = self.file_path_input.text().strip()
            if not file_path or not os.path.exists(file_path):
                QMessageBox.warning(self, "警告", "请选择有效的文件")
                return
            
            # 获取沙箱类型和运行时间
            sandbox_type = self.sandbox_type_combo.currentData()
            run_time = self.run_time_spin.value()
            
            # 启动上传线程
            self.query_thread = ThreatIntelQueryThread(
                self.threatbook_api, "file_upload", file_path, 
                sandbox_type=sandbox_type, run_time=run_time
            )
        
        self.query_thread.progress_updated.connect(self.file_status_label.setText)
        self.query_thread.query_completed.connect(self.on_file_query_completed)
        
        # 更新UI状态
        self.file_query_btn.setEnabled(False)
        self.file_multiengine_btn.setEnabled(False)
        self.file_progress.setVisible(True)
        self.file_progress.setRange(0, 0)
        
        self.query_thread.start()
    
    def start_multiengine_query(self):
        """开始多引擎检测查询"""
        if not self.threatbook_api.api_key:
            QMessageBox.warning(self, "警告", "请先配置API密钥")
            return
        
        file_hash = self.file_hash_input.text().strip()
        if not file_hash:
            QMessageBox.warning(self, "警告", "请输入文件哈希值")
            return
        
        # 清空表格，避免数据混合显示
        self.file_results_table.setRowCount(0)
        
        # 确保表格有正确的列设置（多引擎检测使用与哈希查询相同的结构）
        self.file_results_table.setColumnCount(9)
        self.file_results_table.setHorizontalHeaderLabels([
            "文件名", "SHA256", "威胁等级", "木马/病毒家族", "病毒类型", "多引擎检出", "沙箱环境", "提交时间", "操作"
        ])
        
        # 重新设置列宽
        self.file_results_table.setColumnWidth(0, 120)  # 文件名
        self.file_results_table.setColumnWidth(1, 180)  # SHA256
        self.file_results_table.setColumnWidth(2, 100)  # 威胁等级
        self.file_results_table.setColumnWidth(3, 120)  # 木马/病毒家族
        self.file_results_table.setColumnWidth(4, 150)  # 病毒类型
        self.file_results_table.setColumnWidth(5, 100)  # 多引擎检出
        self.file_results_table.setColumnWidth(6, 120)  # 沙箱环境
        self.file_results_table.setColumnWidth(7, 130)  # 提交时间
        self.file_results_table.setColumnWidth(8, 200)  # 操作列
        
        hash_type = self.hash_type_combo.currentText().lower()
        
        # 启动查询线程
        self.query_thread = ThreatIntelQueryThread(
            self.threatbook_api, "file_multiengines", file_hash, resource_type=hash_type
        )
        self.query_thread.progress_updated.connect(self.file_status_label.setText)
        self.query_thread.query_completed.connect(self.on_file_query_completed)
        
        # 更新UI状态
        self.file_query_btn.setEnabled(False)
        self.file_multiengine_btn.setEnabled(False)
        self.file_progress.setVisible(True)
        self.file_progress.setRange(0, 0)
        
        self.query_thread.start()
    
    def on_file_query_completed(self, result: Dict):
        """文件查询完成"""
        self.file_query_btn.setEnabled(True)
        self.file_multiengine_btn.setEnabled(True)
        self.file_progress.setVisible(False)
        
        if result['success']:
            # 将查询类型信息添加到结果中
            result_data = result['result'].copy()
            result_data['query_type'] = result.get('type', '')
            self.add_file_result(result_data)
            self.file_status_label.setText("查询完成")
        else:
            error_msg = result['result'].get('error', '未知错误')
            QMessageBox.critical(self, "查询失败", f"文件查询失败: {error_msg}")
            self.file_status_label.setText(f"查询失败: {error_msg}")
    
    def get_threat_level_display(self, threat_level: str) -> str:
        """格式化威胁等级显示"""
        level_map = {
            'malicious': '🔴 恶意',
            'suspicious': '🟡 可疑', 
            'clean': '🟢 安全',
            'unknown': '⚪ 未知'
        }
        return level_map.get(threat_level, f'⚪ {threat_level}')
    
    def add_file_result(self, result: Dict):
        """添加文件查询结果到表格"""
        row = self.file_results_table.rowCount()
        self.file_results_table.insertRow(row)
        
        # 处理文件大小显示
        file_size = result.get('file_size', 0)
        if isinstance(file_size, (int, float)) and file_size > 0:
            if file_size > 1024 * 1024:
                size_str = f"{file_size / (1024 * 1024):.2f} MB"
            elif file_size > 1024:
                size_str = f"{file_size / 1024:.2f} KB"
            else:
                size_str = f"{file_size} B"
        else:
            size_str = "未知"
        
        # 根据查询类型显示不同的字段
        current_query_type = self.file_query_type.currentText()
        actual_query_type = result.get('query_type', '')
        
        # 哈希查询和多引擎检测都使用相同的表格结构
        if current_query_type == "哈希查询" or actual_query_type == "file_multiengines":
            # 从API响应中提取数据
            raw_data = result.get('raw_data', {}).get('data', {})
            static_data = raw_data.get('static', {}).get('basic', {})
            multiengines = raw_data.get('multiengines', {})
            tag_data = raw_data.get('tag', {})
            summary_data = raw_data.get('summary', {})
            
            # 提取文件基本信息
            file_name = static_data.get('file_name', result.get('file_name', ''))
            if not file_name:
                file_name = static_data.get('sha256', '')[:16] + '...' if static_data.get('sha256') else '未知'
            
            sha256 = static_data.get('sha256', '')
            sha256_display = sha256[:16] + '...' if sha256 else '未知'
            
            # 根据查询类型提取威胁等级
            if actual_query_type == "file_multiengines":
                # 多引擎检测：使用API返回的威胁等级
                threat_level = result.get('threat_level', 'unknown')
            else:
                # 哈希查询：从 summary_data.threat_level 获取威胁等级
                threat_level = summary_data.get('threat_level', 'unknown')
            
            # 根据查询类型提取不同的字段
            threat_classification = '未检测'
            virus_family = '未知'
            
            if actual_query_type == "file_multiengines":
                # 多引擎检测：从 malware_type 字段提取病毒类型
                threat_classification = result.get('malware_type', '未检测')
                
                # 提取OneStatic检测结果并解析木马家族
                onestatic_malware_family = ''
                if multiengines.get('result') and 'OneStatic' in multiengines['result']:
                    onestatic_detection = multiengines['result']['OneStatic']
                    if onestatic_detection and onestatic_detection not in ['safe', 'clean', '']:
                        # 解析 OneStatic 格式: "威胁分类/木马家族"
                        if '/' in onestatic_detection:
                            parts = onestatic_detection.split('/', 1)
                            onestatic_malware_family = parts[1]  # 木马家族，如 "stowaway.a"
                        else:
                            onestatic_malware_family = onestatic_detection
                
                # 提取病毒家族信息（优先使用API的malware_family，其次使用OneStatic解析结果，最后使用其他引擎）
                api_malware_family = result.get('malware_family', '')
                if api_malware_family:
                    virus_family = api_malware_family
                elif onestatic_malware_family:
                    virus_family = onestatic_malware_family
                elif multiengines.get('result'):
                    for engine, result_text in multiengines['result'].items():
                        if engine != 'OneStatic' and result_text not in ['safe', 'clean', '']:
                            virus_family = result_text
                            break
            else:
                # 哈希查询：从 summary_data 获取病毒类型和家族
                threat_classification = summary_data.get('malware_type', '未检测')  # 病毒类型，如 "Hacktool"
                virus_family = summary_data.get('malware_family', '未知')  # 病毒家族，如 "stowaway"
            
            # 沙箱环境（从当前选择获取）
            sandbox_env = self.sandbox_type_combo.currentText() if hasattr(self, 'sandbox_type_combo') else '未指定'
            
            # 提交时间
            submit_time = result.get('query_time', '未知')
            
            # 根据查询类型提取多引擎检出率
            if actual_query_type == "file_multiengines":
                # 多引擎检测：使用API返回的检出率
                positives = result.get('positive_engines', 0)
                total = result.get('total_engines', 0)
                detect_rate = f"{positives}/{total}" if total > 0 else "0/0"
            else:
                # 哈希查询：从 multiengines.detect_rate 获取检出率
                detect_rate = multiengines.get('detect_rate', '0/0')
            
            # 哈希查询显示：文件名、SHA256、威胁等级、木马/病毒家族、威胁分类、多引擎检出、沙箱环境、提交时间、操作
            items = [
                file_name,
                sha256_display,
                self.get_threat_level_display(threat_level),
                virus_family,
                threat_classification,
                detect_rate,
                sandbox_env,
                submit_time,
            ]
            
            for col, item in enumerate(items):
                table_item = QTableWidgetItem(str(item))
                table_item.setData(Qt.ItemDataRole.UserRole, result)
                
                # 根据威胁等级设置颜色
                if col == 2:  # 威胁等级列
                    if threat_level == 'malicious':
                        table_item.setBackground(QColor(231, 76, 60, 50))  # 红色背景
                    elif threat_level == 'suspicious':
                        table_item.setBackground(QColor(243, 156, 18, 50))  # 橙色背景
                    elif threat_level == 'clean':
                        table_item.setBackground(QColor(46, 204, 113, 50))  # 绿色背景
                
                # 威胁分类列特殊处理
                if col == 4:  # 威胁分类列
                    # 设置工具提示显示完整内容
                    table_item.setToolTip(f"威胁分类: {str(item)}")
                    # 如果检测到威胁，设置特殊颜色
                    if str(item) != '未检测' and str(item) != '':
                        table_item.setBackground(QColor(255, 193, 7, 50))  # 黄色背景表示检测到威胁分类
                
                self.file_results_table.setItem(row, col, table_item)
            
            # 操作按钮列
            btn_widget = QWidget()
            btn_widget.setFixedHeight(40)  # 设置容器固定高度
            btn_widget.setStyleSheet("QWidget { background: transparent; }")  # 设置透明背景
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 4, 4, 4)  # 增加边距确保按钮完全显示
            btn_layout.setSpacing(6)
            btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 居中对齐
            
            # 如果有permalink，添加打开链接按钮
            if 'permalink' in result:
                open_btn = QPushButton("报告")
                open_btn.setObjectName("table_action_btn")
                open_btn.setFixedSize(70, 32)
                open_btn.setStyleSheet("""
                    QPushButton#table_action_btn {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #4a5568, stop: 1 #2d3748) !important;
                        color: #e2e8f0 !important;
                        border: 1px solid #4a5568 !important;
                        border-radius: 4px !important;
                        font-size: 11px !important;
                        font-weight: 600 !important;
                        padding: 6px 12px !important;
                    }
                    QPushButton#table_action_btn:hover {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #5a6578, stop: 1 #3d4758) !important;
                        border: 1px solid #5a6578 !important;
                    }
                    QPushButton#table_action_btn:pressed {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #3a4558, stop: 1 #1d2738) !important;
                        border: 1px solid #3a4558 !important;
                    }
                """)
                open_btn.clicked.connect(lambda: self.open_permalink(result['permalink']))
                btn_layout.addWidget(open_btn)
            
            # 详情按钮
            detail_btn = QPushButton("详情")
            detail_btn.setObjectName("table_detail_btn")
            detail_btn.setFixedSize(70, 32)
            detail_btn.setStyleSheet("""
                QPushButton#table_detail_btn {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #4a5568, stop: 1 #2d3748) !important;
                    color: #e2e8f0 !important;
                    border: 1px solid #4a5568 !important;
                    border-radius: 4px !important;
                    font-size: 11px !important;
                    font-weight: 600 !important;
                    padding: 6px 12px !important;
                }
                QPushButton#table_detail_btn:hover {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #5a6578, stop: 1 #3d4758) !important;
                    border: 1px solid #5a6578 !important;
                }
                QPushButton#table_detail_btn:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #3a4558, stop: 1 #1d2738) !important;
                    border: 1px solid #3a4558 !important;
                }
            """)
            detail_btn.clicked.connect(lambda: self.show_file_detail_by_row(row))
            btn_layout.addWidget(detail_btn)
            
            self.file_results_table.setCellWidget(row, 8, btn_widget)
                
        else:  # 文件上传
            # 确定分析状态
            if 'permalink' in result:
                status = "✅ 上传成功"
            elif result.get('reputation_level'):
                status = f"🔍 {result.get('reputation_level', 'unknown')}"
            else:
                status = "⏳ 处理中"
            
            # 文件上传显示：文件名、SHA256、文件大小、分析状态、操作
            items = [
                result.get('file_name', result.get('resource', '')),
                result.get('sha256', '')[:16] + '...' if result.get('sha256') else '',
                size_str,
                status
            ]
            
            for col, item in enumerate(items):
                table_item = QTableWidgetItem(str(item))
                table_item.setData(Qt.ItemDataRole.UserRole, result)
                self.file_results_table.setItem(row, col, table_item)
            
            # 操作按钮列
            btn_widget = QWidget()
            btn_widget.setFixedHeight(40)  # 设置容器固定高度
            btn_widget.setStyleSheet("QWidget { background: transparent; }")  # 设置透明背景
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 4, 4, 4)  # 增加边距确保按钮完全显示
            btn_layout.setSpacing(6)
            btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 居中对齐
            
            # 如果有permalink，添加打开链接按钮
            if 'permalink' in result:
                open_btn = QPushButton("报告")
                open_btn.setObjectName("upload_action_btn")
                open_btn.setFixedSize(70, 32)
                open_btn.setStyleSheet("""
                    QPushButton#upload_action_btn {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #4a5568, stop: 1 #2d3748) !important;
                        color: #e2e8f0 !important;
                        border: 1px solid #4a5568 !important;
                        border-radius: 4px !important;
                        font-size: 11px !important;
                        font-weight: 600 !important;
                        padding: 6px 12px !important;
                    }
                    QPushButton#upload_action_btn:hover {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #5a6578, stop: 1 #3d4758) !important;
                        border: 1px solid #5a6578 !important;
                    }
                    QPushButton#upload_action_btn:pressed {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                            stop: 0 #3a4558, stop: 1 #1d2738) !important;
                        border: 1px solid #3a4558 !important;
                    }
                """)
                open_btn.clicked.connect(lambda: self.open_permalink(result['permalink']))
                btn_layout.addWidget(open_btn)
            
            # 详情按钮
            detail_btn = QPushButton("详情")
            detail_btn.setObjectName("upload_detail_btn")
            detail_btn.setFixedSize(70, 32)
            detail_btn.setStyleSheet("""
                QPushButton#upload_detail_btn {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #4a5568, stop: 1 #2d3748) !important;
                    color: #e2e8f0 !important;
                    border: 1px solid #4a5568 !important;
                    border-radius: 4px !important;
                    font-size: 11px !important;
                    font-weight: 600 !important;
                    padding: 6px 12px !important;
                }
                QPushButton#upload_detail_btn:hover {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #5a6578, stop: 1 #3d4758) !important;
                    border: 1px solid #5a6578 !important;
                }
                QPushButton#upload_detail_btn:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                        stop: 0 #3a4558, stop: 1 #1d2738) !important;
                    border: 1px solid #3a4558 !important;
                }
            """)
            detail_btn.clicked.connect(lambda: self.show_file_detail_by_row(row))
            btn_layout.addWidget(detail_btn)
            
            btn_layout.addStretch()
            self.file_results_table.setCellWidget(row, 4, btn_widget)
        
        # 保存到结果列表
        self.query_results.append({
            'type': 'file_analysis',
            'data': result
        })
    
    def show_file_detail(self):
        """显示文件详细信息"""
        current_row = self.file_results_table.currentRow()
        if current_row >= 0:
            self.show_file_detail_by_row(current_row)
    
    def show_file_detail_by_row(self, row: int):
        """按行号显示文件详细信息"""
        item = self.file_results_table.item(row, 0)
        if item:
            result = item.data(Qt.ItemDataRole.UserRole)
            if result:
                detail_text = json.dumps(result, indent=2, ensure_ascii=False)
                self.file_detail_text.setPlainText(detail_text)
    
    def open_permalink(self, url: str):
        """打开permalink链接"""
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"无法打开链接: {str(e)}")
    
    def test_api_connection(self):
        """测试API连接"""
        api_key = self.api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入API密钥")
            return
        
        # 设置API密钥并测试
        self.threatbook_api.set_api_key(api_key)
        
        self.test_connection_btn.setEnabled(False)
        self.connection_status_label.setText("正在测试连接...")
        
        # 使用定时器异步测试
        QTimer.singleShot(100, self._do_connection_test)
    
    def _do_connection_test(self):
        """执行连接测试"""
        try:
            result = self.threatbook_api.test_connection()
            
            if result['success']:
                self.connection_status_label.setText("✅ 连接成功")
                self.connection_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                QMessageBox.information(self, "成功", "API连接测试成功！")
            else:
                self.connection_status_label.setText(f"❌ 连接失败: {result['message']}")
                self.connection_status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
                QMessageBox.critical(self, "失败", f"API连接测试失败:\n{result['message']}")
        
        except Exception as e:
            self.connection_status_label.setText(f"❌ 测试异常: {str(e)}")
            self.connection_status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            QMessageBox.critical(self, "异常", f"连接测试异常:\n{str(e)}")
        
        finally:
            self.test_connection_btn.setEnabled(True)
    
    def save_config(self):
        """保存配置"""
        config = {
            'threatbook_api_key': self.api_key_input.text().strip()
        }
        
        try:
            # 保存到配置文件
            config_path = Path.cwd() / 'config.json'
            
            # 读取现有配置
            existing_config = {}
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
            
            # 只更新威胁情报相关配置，避免覆盖其他模块的配置
            existing_config['threatbook_api_key'] = config['threatbook_api_key']
            
            # 保存配置
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(existing_config, f, indent=2, ensure_ascii=False)
            
            QMessageBox.information(self, "成功", "配置已保存")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败:\n{str(e)}")
    
    def load_config(self):
        """加载配置"""
        try:
            config_path = Path.cwd() / 'config.json'
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 加载威胁情报配置
                api_key = config.get('threatbook_api_key', '')
                if api_key:
                    self.api_key_input.setText(api_key)
                    self.threatbook_api.set_api_key(api_key)
        
        except Exception as e:
            print(f"加载配置失败: {str(e)}")
    
    def export_ip_results(self):
        """导出IP查询结果"""
        if self.ip_results_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        self._export_results("IP信誉查询结果", self.ip_results_table)
    
    def export_dns_results(self):
        """导出DNS查询结果"""
        if self.dns_results_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        self._export_results("DNS查询结果", self.dns_results_table)
    
    def export_file_results(self):
        """导出文件分析结果"""
        if self.file_results_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
        
        self._export_results("文件分析结果", self.file_results_table)
    
    def _export_results(self, title: str, table: QTableWidget):
        """导出结果到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"{title}_{timestamp}.json"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, f"导出{title}", default_filename,
            "JSON文件 (*.json);;Excel文件 (*.xlsx);;所有文件 (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            # 收集表格数据
            data = []
            headers = []
            
            # 获取表头
            for col in range(table.columnCount()):
                header_item = table.horizontalHeaderItem(col)
                if header_item:
                    headers.append(header_item.text())
                else:
                    headers.append(f"列{col + 1}")
            
            # 获取数据
            for row in range(table.rowCount()):
                row_data = {}
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item:
                        row_data[headers[col]] = item.text()
                        # 如果有原始数据，也包含进去
                        if col == 0:  # 第一列通常存储完整数据
                            raw_data = item.data(Qt.ItemDataRole.UserRole)
                            if raw_data:
                                row_data['原始数据'] = raw_data
                data.append(row_data)
            
            # 根据文件扩展名选择导出格式
            if file_path.lower().endswith('.json'):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'export_time': datetime.now().isoformat(),
                        'title': title,
                        'data': data
                    }, f, indent=2, ensure_ascii=False)
            
            elif file_path.lower().endswith('.xlsx'):
                try:
                    import pandas as pd
                    
                    # 创建DataFrame
                    df_data = []
                    for item in data:
                        row = {k: v for k, v in item.items() if k != '原始数据'}
                        df_data.append(row)
                    
                    df = pd.DataFrame(df_data)
                    df.to_excel(file_path, index=False, engine='openpyxl')
                    
                except ImportError:
                    QMessageBox.warning(self, "警告", "导出Excel需要安装pandas和openpyxl库")
                    return
            
            QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def clear_ip_results(self):
        """清空IP查询结果"""
        self.ip_results_table.setRowCount(0)
    
    def clear_dns_results(self):
        """清空DNS查询结果"""
        self.dns_results_table.setRowCount(0)
    
    def clear_file_results(self):
        """清空文件分析结果"""
        self.file_results_table.setRowCount(0)
        self.file_detail_text.clear()
    
    def get_config(self) -> Dict:
        """获取配置"""
        return {
            'threatbook_api_key': self.api_key_input.text().strip()
        }
    
    def set_config(self, config: Dict):
        """设置配置"""
        api_key = config.get('threatbook_api_key', '')
        if api_key:
            self.api_key_input.setText(api_key)
            self.threatbook_api.set_api_key(api_key)
    
    def get_all_results(self) -> List[Dict]:
        """获取所有查询结果"""
        return self.query_results.copy()
    
    def clear_results(self):
        """清空所有结果"""
        self.clear_ip_results()
        self.clear_dns_results()
        self.clear_file_results()
        self.query_results.clear()


def main():
    """测试函数"""
    import sys
    
    app = QApplication(sys.argv)
    
    # 创建威胁情报UI
    threat_ui = ThreatIntelligenceUI()
    threat_ui.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()