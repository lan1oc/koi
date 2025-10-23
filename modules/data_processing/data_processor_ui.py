#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理UI组件

提供数据处理功能的图形界面组件
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox, QPushButton,
    QLabel, QListWidget, QTextEdit, QComboBox, QLineEdit, QFileDialog,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QSplitter, QFrame,
    QScrollArea, QGridLayout, QAbstractItemView, QHeaderView, QTableWidget,
    QTableWidgetItem, QDialog, QPlainTextEdit, QCheckBox, QSpinBox,
    QProgressBar, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap, QIcon, QColor

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import json

from .excel_processor import ExcelProcessor
from .field_extractor import FieldExtractor
from .data_filler import DataFiller
from .template_manager import TemplateManager
from modules.ui.styles.theme_manager import ThemeManager

class DataProcessingThread(QThread):
    """数据处理线程"""
    progress_updated = Signal(str)
    processing_completed = Signal(dict)
    
    def __init__(self, operation_type: str, **kwargs):
        super().__init__()
        self.operation_type = operation_type
        self.kwargs = kwargs
        self.excel_processor = ExcelProcessor()
        self.field_extractor = FieldExtractor()
        self.data_filler = DataFiller()
    
    def run(self):
        try:
            if self.operation_type == 'extract_fields':
                self.progress_updated.emit("正在提取字段...")
                result = self.field_extractor.extract_fields(**self.kwargs)
            elif self.operation_type == 'fill_template':
                self.progress_updated.emit("正在填充模板...")
                result = self.data_filler.fill_template(**self.kwargs)
                print(f"[DEBUG] 数据填充结果: {result}")  # 调试信息
            elif self.operation_type == 'preview_extraction':
                self.progress_updated.emit("正在生成预览...")
                result = self.field_extractor.preview_extraction(**self.kwargs)
            elif self.operation_type == 'preview_filling':
                self.progress_updated.emit("正在生成预览...")
                result = self.data_filler.preview_filling(**self.kwargs)
            else:
                result = {'success': False, 'message': f'未知操作类型: {self.operation_type}'}
            
            # 在结果中添加操作类型信息
            result['operation_type'] = self.operation_type
            
            print(f"[DEBUG] 准备发出processing_completed信号: {result}")  # 调试信息
            self.processing_completed.emit(result)
            print(f"[DEBUG] processing_completed信号已发出")  # 调试信息
        except Exception as e:
            error_result = {
                'success': False,
                'message': f'处理失败: {str(e)}',
                'operation_type': self.operation_type
            }
            print(f"[DEBUG] 发生异常，发出错误信号: {error_result}")  # 调试信息
            self.processing_completed.emit(error_result)

class DataProcessorUI(QWidget):
    """数据处理UI主组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # 初始化处理器
        self.excel_processor = ExcelProcessor()
        self.field_extractor = FieldExtractor()
        self.data_filler = DataFiller()
        self.template_manager = TemplateManager()
        
        # 当前文件信息
        self.current_source_file = None
        self.current_template_file = None
        self.current_headers = []
        self.current_templates = []
        
        # 文件路径属性
        self.extracted_file_path = None
        
        # 处理线程
        self.processing_thread = None
        
        self.setup_ui()
        self.load_templates()
        
        # 连接主题管理器
        self._setup_theme_connections()
    
    def get_templates_file_path(self):
        """获取模板文件路径 - 支持开发环境和编译后环境"""
        import sys
        from pathlib import Path
        
        if getattr(sys, 'frozen', False):
            # 编译后的环境：templates文件夹在可执行文件旁边
            base_path = Path(sys.executable).parent
            return base_path / 'templates' / 'templates.json'
        else:
            # 开发环境：使用模块内的templates目录
            return Path(__file__).parent / 'templates' / 'templates.json'
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # 字段提取选项卡
        extraction_tab = self.create_field_extraction_tab()
        self.tab_widget.addTab(extraction_tab, "📄 字段提取")
        
        # 数据填充选项卡
        filling_tab = self.create_data_filling_tab()
        self.tab_widget.addTab(filling_tab, "📝 数据填充")
        
        # 模板管理选项卡
        template_tab = self.create_template_management_tab()
        self.tab_widget.addTab(template_tab, "📋 模板管理")
    
    def create_field_extraction_tab(self):
        """创建字段提取选项卡（完全匹配原始布局）"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建内容widget
        content_widget = QWidget()
        main_layout = QHBoxLayout(content_widget)  # 水平布局
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 左侧操作区域
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(15)
        
        # 文件选择区域
        file_group = QGroupBox("📁 文件选择")
        file_layout = QVBoxLayout(file_group)
        
        # 文件选择行
        file_select_layout = QHBoxLayout()
        self.extract_file_btn = QPushButton("🗂️ 选择数据文件")
        self.extract_file_btn.clicked.connect(self.select_extraction_file)
        
        self.extract_file_label = QLabel("未选择文件")
        self.extract_file_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        
        file_select_layout.addWidget(self.extract_file_btn)
        file_select_layout.addWidget(self.extract_file_label)
        file_select_layout.addStretch()
        file_layout.addLayout(file_select_layout)
        
        # 自定义分隔符行
        separator_layout = QHBoxLayout()
        separator_label = QLabel("自定义分隔符:")
        self.custom_separator_input = QLineEdit()
        self.custom_separator_input.setPlaceholderText("留空自动检测，或输入如: \\t, |, ;, \\s+")
        self.custom_separator_input.setMaximumWidth(200)
        self.custom_separator_input.textChanged.connect(self.on_separator_changed)
        
        # 检测到的分隔符显示
        self.detected_separator_label = QLabel("")
        self.detected_separator_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        
        separator_layout.addWidget(separator_label)
        separator_layout.addWidget(self.custom_separator_input)
        separator_layout.addWidget(self.detected_separator_label)
        separator_layout.addStretch()
        file_layout.addLayout(separator_layout)
        
        left_layout.addWidget(file_group)
        
        # 表头显示区域
        headers_group = QGroupBox("📋 表头信息")
        headers_layout = QVBoxLayout(headers_group)
        
        self.headers_list = QListWidget()
        self.headers_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        headers_layout.addWidget(self.headers_list)
        
        # 字段选择按钮
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self.select_all_extract_fields)
        
        select_none_btn = QPushButton("清空")
        select_none_btn.clicked.connect(self.select_none_extract_fields)
        
        select_layout.addWidget(select_all_btn)
        select_layout.addWidget(select_none_btn)
        select_layout.addStretch()
        
        headers_layout.addLayout(select_layout)
        left_layout.addWidget(headers_group)
        
        # 提取按钮
        extract_btn = QPushButton("🚀 提取选中字段")
        extract_btn.clicked.connect(self.extract_selected_fields)
        left_layout.addWidget(extract_btn)
        
        left_layout.addStretch()
        main_layout.addWidget(left_widget, 1)
        
        # 右侧结果显示区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(15)
        
        # 结果信息
        result_group = QGroupBox("📊 提取结果")
        result_layout = QVBoxLayout(result_group)
        
        self.result_info_label = QLabel("等待提取...")
        self.result_info_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        result_layout.addWidget(self.result_info_label)
        
        # 结果预览
        self.result_preview = QTextEdit()
        self.result_preview.setReadOnly(True)
        self.result_preview.setMaximumHeight(200)
        result_layout.addWidget(self.result_preview)
        
        # 保存文件信息
        self.save_file_label = QLabel("保存位置: 未保存")
        self.save_file_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        result_layout.addWidget(self.save_file_label)
        
        # 打开文件按钮
        self.open_file_btn = QPushButton("📂 打开文件")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self.open_extracted_file)
        result_layout.addWidget(self.open_file_btn)
        right_layout.addWidget(result_group)
        
        right_layout.addStretch()
        main_layout.addWidget(right_widget, 2)
        
        # 将内容widget设置到滚动区域
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        return tab
    
    def create_data_filling_tab(self):
        """创建数据填充选项卡（匹配原始垂直布局）"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建内容widget
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)  # 垂直布局
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 源文件选择
        source_group = QGroupBox("📄 源文件选择")
        source_layout = QHBoxLayout(source_group)
        
        source_btn = QPushButton("📂 选择源文件")
        source_btn.clicked.connect(self.select_source_file)
        
        self.source_file_label = QLabel("未选择文件")
        self.source_file_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        
        source_layout.addWidget(source_btn)
        source_layout.addWidget(self.source_file_label)
        source_layout.addStretch()
        
        layout.addWidget(source_group)
        
        # 目标模板选择
        target_group = QGroupBox("📋 目标模板选择")
        target_layout = QHBoxLayout(target_group)
        
        target_btn = QPushButton("📊 选择目标模板")
        target_btn.clicked.connect(self.select_template_file)
        
        self.template_file_label = QLabel("未选择模板")
        self.template_file_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        
        target_layout.addWidget(target_btn)
        target_layout.addWidget(self.template_file_label)
        target_layout.addStretch()
        
        layout.addWidget(target_group)
        
        # 模板选择区域
        template_select_group = QGroupBox("🎯 模板选择")
        template_select_layout = QHBoxLayout(template_select_group)
        
        template_select_layout.addWidget(QLabel("选择模板:"))
        
        self.template_combo = QComboBox()
        self.template_combo.addItem("请选择模板")
        self.update_template_combo()
        template_select_layout.addWidget(self.template_combo)
        
        use_template_btn = QPushButton("✅ 使用模板")
        use_template_btn.clicked.connect(self.use_template)
        template_select_layout.addWidget(use_template_btn)
        
        template_select_layout.addStretch()
        
        layout.addWidget(template_select_group)
        
        # 字段映射区域
        mapping_group = QGroupBox("🔗 字段映射")
        mapping_layout = QVBoxLayout(mapping_group)
        
        self.mapping_tree = QTreeWidget()
        self.mapping_tree.setHeaderLabels(["源字段", "目标字段", "映射状态"])
        mapping_layout.addWidget(self.mapping_tree)
        
        # 映射操作按钮
        mapping_btn_layout = QHBoxLayout()
        
        display_btn = QPushButton("👁️ 显示映射")
        display_btn.setMinimumSize(120, 40)
        display_btn.clicked.connect(self.show_field_mapping)
        mapping_btn_layout.addWidget(display_btn)
        
        auto_map_btn = QPushButton("🤖 自动映射")
        auto_map_btn.setMinimumSize(120, 40)
        auto_map_btn.clicked.connect(self.auto_map_fields)
        mapping_btn_layout.addWidget(auto_map_btn)
        
        custom_btn = QPushButton("⚙️ 自定义映射")
        custom_btn.setMinimumSize(120, 40)
        custom_btn.clicked.connect(self.custom_field_mapping)
        mapping_btn_layout.addWidget(custom_btn)
        
        mapping_btn_layout.addStretch()
        
        mapping_layout.addLayout(mapping_btn_layout)
        layout.addWidget(mapping_group)
        
        # 进度条区域
        progress_group = QGroupBox("📊 处理进度")
        progress_layout = QVBoxLayout(progress_group)
        
        self.fill_progress_bar = QProgressBar()
        self.fill_progress_bar.setVisible(False)  # 初始隐藏
        # 不设置硬编码样式，让主题管理器处理样式
        progress_layout.addWidget(self.fill_progress_bar)
        
        self.fill_status_label = QLabel("")
        self.fill_status_label.setVisible(False)  # 初始隐藏
        # 使用动态样式，根据主题设置颜色
        self._update_status_label_style()
        progress_layout.addWidget(self.fill_status_label)
        
        layout.addWidget(progress_group)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        fill_btn = QPushButton("🚀 开始填充")
        fill_btn.clicked.connect(self.start_data_filling)
        
        save_template_btn = QPushButton("💾 保存为模板")
        save_template_btn.clicked.connect(lambda: QMessageBox.information(self, "提示", "请在字段映射完成后使用映射对话框中的保存模板功能"))
        
        button_layout.addWidget(fill_btn)
        button_layout.addWidget(save_template_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        # 将内容widget设置到滚动区域
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        return tab
    
    def create_template_management_tab(self):
        """创建模板管理选项卡（匹配原始水平布局）"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 创建内容widget
        content_widget = QWidget()
        layout = QHBoxLayout(content_widget)  # 水平布局
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 左侧模板列表
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # 模板列表
        template_group = QGroupBox("📚 模板列表")
        template_layout = QVBoxLayout(template_group)
        
        self.template_list = QListWidget()
        self.template_list.itemClicked.connect(self.on_template_item_selected)
        template_layout.addWidget(self.template_list)
        
        left_layout.addWidget(template_group)
        
        # 右侧操作区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # 模板操作
        operation_group = QGroupBox("⚙️ 模板操作")
        operation_layout = QGridLayout(operation_group)
        
        view_btn = QPushButton("👁️ 查看模板")
        view_btn.clicked.connect(self.view_template)
        operation_layout.addWidget(view_btn, 0, 0)
        
        edit_btn = QPushButton("✏️ 编辑模板")
        edit_btn.clicked.connect(self.edit_selected_template)
        operation_layout.addWidget(edit_btn, 0, 1)
        
        delete_btn = QPushButton("🗑️ 删除模板")
        delete_btn.clicked.connect(self.delete_selected_template)
        operation_layout.addWidget(delete_btn, 1, 0)
        
        import_btn = QPushButton("📥 导入模板")
        import_btn.clicked.connect(self.import_template)
        operation_layout.addWidget(import_btn, 1, 1)
        
        export_btn = QPushButton("📤 导出模板")
        export_btn.clicked.connect(self.export_template)
        operation_layout.addWidget(export_btn, 2, 0)
        
        create_btn = QPushButton("➕ 创建模板")
        create_btn.clicked.connect(self.create_new_template)
        operation_layout.addWidget(create_btn, 2, 1)
        
        right_layout.addWidget(operation_group)
        right_layout.addStretch()
        
        # 将左右两部分添加到主布局
        layout.addWidget(left_widget, 1)
        layout.addWidget(right_widget, 2)
        
        # 将内容widget设置到滚动区域
        scroll_area.setWidget(content_widget)
        tab_layout.addWidget(scroll_area)
        
        return tab
    
    # 字段提取相关方法
    def select_extraction_file(self):
        """选择要提取字段的文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择数据文件", "", 
            "所有支持的文件 (*.xlsx *.xls *.csv *.txt);;Excel文件 (*.xlsx *.xls);;CSV文件 (*.csv);;文本文件 (*.txt);;所有文件 (*)"
        )
        
        if file_path:
            self.current_source_file = file_path
            self.extract_file_label.setText(f"已选择: {Path(file_path).name}")
            self.extract_file_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
            
            # 加载文件头信息
            self.load_file_headers()
    
    def on_separator_changed(self):
        """当分隔符改变时重新加载文件头"""
        if self.current_source_file:
            self.load_file_headers()
    
    def load_file_headers(self):
        """加载文件头信息"""
        if not self.current_source_file:
            return
        
        try:
            # 获取自定义分隔符
            custom_separator = self.custom_separator_input.text().strip()
            if not custom_separator:
                custom_separator = None
            
            # 使用字段提取器获取可用字段
            result = self.field_extractor.get_available_fields(self.current_source_file, custom_separator=custom_separator)
            if result['success']:
                headers = result['fields']
                self.current_headers = headers
                
                # 显示检测到的分隔符
                detected_separator = result.get('detected_separator', '未知')
                self.detected_separator_label.setText(f"检测到: {detected_separator}")
            else:
                QMessageBox.warning(self, "警告", f"无法读取文件头信息: {result['message']}")
                return
            
            # 更新字段列表
            self.headers_list.clear()
            for header in headers:
                self.headers_list.addItem(header)
            
            self.result_info_label.setText(f"已加载 {len(headers)} 个字段")
            self.result_info_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载文件头失败: {str(e)}")
            self.result_info_label.setText("加载失败")
            self.result_info_label.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 5px;")
    
    def select_all_extract_fields(self):
        """选择所有字段"""
        for i in range(self.headers_list.count()):
            self.headers_list.item(i).setSelected(True)
    
    def select_none_extract_fields(self):
        """清空字段选择"""
        self.headers_list.clearSelection()
    
    def get_selected_extract_fields(self) -> List[str]:
        """获取选中的字段"""
        selected_items = self.headers_list.selectedItems()
        return [item.text() for item in selected_items]
    
    def preview_field_extraction(self):
        """预览字段提取"""
        if not self.current_source_file:
            QMessageBox.warning(self, "警告", "请先选择源文件")
            return
        
        selected_fields = self.get_selected_extract_fields()
        if not selected_fields:
            QMessageBox.warning(self, "警告", "请选择要提取的字段")
            return
        
        # 获取自定义分隔符
        custom_separator = self.custom_separator_input.text().strip()
        if not custom_separator:
            custom_separator = None
        
        # 启动预览线程
        self.start_processing_thread('preview_extraction', {
            'source_file': self.current_source_file,
            'selected_fields': selected_fields,
            'preview_rows': 10,
            'custom_separator': custom_separator
        })
    
    def extract_selected_fields(self):
        """提取选中的字段"""
        if not self.current_source_file:
            QMessageBox.warning(self, "警告", "请先选择源文件")
            return
        
        selected_fields = self.get_selected_extract_fields()
        if not selected_fields:
            QMessageBox.warning(self, "警告", "请选择要提取的字段")
            return
        
        # 选择输出文件
        output_file, _ = QFileDialog.getSaveFileName(
            self, "保存提取结果", "", 
            "Excel文件 (*.xlsx);;文本文件 (*.txt);;CSV文件 (*.csv);;所有文件 (*)"
        )
        
        if output_file:
            # 获取自定义分隔符
            custom_separator = self.custom_separator_input.text().strip()
            if not custom_separator:
                custom_separator = None
            
            # 启动提取线程
            self.start_processing_thread('extract_fields', {
                'source_file': self.current_source_file,
                'selected_fields': selected_fields,
                'output_file': output_file,
                'custom_separator': custom_separator
            })
    
    def save_extraction_result(self):
        """保存提取结果"""
        # 这里可以实现保存当前预览结果的功能
        QMessageBox.information(self, "提示", "请使用'提取选中字段'功能直接保存结果")
    
    def open_extracted_file(self):
        """打开提取的文件"""
        if hasattr(self, 'extracted_file_path') and self.extracted_file_path:
            try:
                import os
                os.startfile(self.extracted_file_path)
            except Exception as e:
                QMessageBox.warning(self, "警告", f"无法打开文件: {str(e)}")
        else:
            QMessageBox.information(self, "提示", "没有可打开的文件")
    
    # 数据填充相关方法
    def select_source_file(self):
        """选择源文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择源文件", "", 
            "Excel文件 (*.xlsx *.xls);;文本文件 (*.txt *.csv);;所有文件 (*)"
        )
        
        if file_path:
            self.current_source_file = file_path
            self.source_file_label.setText(f"已选择: {Path(file_path).name}")
            self.source_file_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
            
            # 加载源文件字段
            self.load_source_fields()
            
            # 如果模板文件也已选择，更新映射
            if hasattr(self, 'current_template_file') and self.current_template_file:
                self.update_field_mapping_display()
    
    def select_template_file(self):
        """选择模板文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择模板文件", "", 
            "Excel文件 (*.xlsx *.xls);;所有文件 (*)"
        )
        
        if file_path:
            self.current_template_file = file_path
            self.template_file_label.setText(f"已选择: {Path(file_path).name}")
            self.template_file_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
            
            # 加载模板文件字段
            self.load_template_fields()
            
            # 如果源文件也已选择，更新映射
            if hasattr(self, 'current_source_file') and self.current_source_file:
                self.update_field_mapping_display()
    
    def load_templates(self):
        """加载模板配置"""
        import os
        
        # 获取模板文件路径
        templates_file = self.get_templates_file_path()
        templates = {}
        
        # 从文件加载所有模板（包括预定义模板和用户自定义模板）
        if os.path.exists(str(templates_file)):
            try:
                with open(str(templates_file), 'r', encoding='utf-8') as f:
                    user_templates = json.load(f)
                    templates.update(user_templates)
                    print(f"成功加载 {len(user_templates)} 个用户模板")
            except Exception as e:
                print(f"加载用户模板失败: {e}")
        else:
            print(f"模板文件不存在: {templates_file}")
        
        self.templates = templates
        self.update_template_list()
        self.update_template_combo()
        
    def update_template_list(self):
        """更新模板列表显示"""
        if not hasattr(self, 'template_list') or self.template_list is None:
            return
        
        self.template_list.clear()
        for name, template in self.templates.items():
            self.template_list.addItem(name)
        
        # 强制刷新界面
        if hasattr(self.template_list, 'repaint'):
            self.template_list.repaint()
    
    def update_template_combo(self):
        """更新模板下拉框"""
        if hasattr(self, 'template_combo') and hasattr(self, 'templates'):
            self.template_combo.clear()
            self.template_combo.addItem("请选择模板")
            for name in self.templates.keys():
                self.template_combo.addItem(name)
    
    def load_source_fields(self):
        """加载源文件字段"""
        if not hasattr(self, 'current_source_file') or not self.current_source_file:
            return
        
        try:
            # 使用字段提取器获取字段信息
            result = self.field_extractor.get_available_fields(self.current_source_file)
            if result['success']:
                self.source_fields = result['fields']
            else:
                QMessageBox.warning(self, "警告", f"加载源文件字段失败: {result['message']}")
                self.source_fields = []
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载源文件字段失败: {str(e)}")
            self.source_fields = []
    
    def load_template_fields(self):
        """加载模板文件字段"""
        if not hasattr(self, 'current_template_file') or not self.current_template_file:
            return
        
        try:
            # 使用字段提取器获取字段信息
            result = self.field_extractor.get_available_fields(self.current_template_file)
            if result['success']:
                self.template_fields = result['fields']
            else:
                QMessageBox.warning(self, "警告", f"加载模板文件字段失败: {result['message']}")
                self.template_fields = []
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载模板文件字段失败: {str(e)}")
            self.template_fields = []
    
    def update_field_mapping_display(self):
        """更新字段映射显示"""
        if not hasattr(self, 'source_fields') or not hasattr(self, 'template_fields'):
            return
        
        self.mapping_tree.clear()
        
        # 显示源文件字段和模板字段的对应关系
        for i, source_field in enumerate(self.source_fields):
            item = QTreeWidgetItem(self.mapping_tree)
            item.setText(0, source_field)  # 源字段
            item.setText(1, "未映射")      # 目标字段
            item.setText(2, "待映射")      # 映射状态
        
        # 调整列宽
        self.mapping_tree.resizeColumnToContents(0)
        self.mapping_tree.resizeColumnToContents(1)
        self.mapping_tree.resizeColumnToContents(2)
    
    def use_template(self):
        """使用选中的模板"""
        if not hasattr(self, 'template_combo'):
            return
        
        template_name = self.template_combo.currentText()
        if template_name == "请选择模板" or template_name not in self.templates:
            QMessageBox.warning(self, "警告", "请选择一个有效的模板")
            return
        
        template = self.templates[template_name]
        
        # 检查是否已选择源文件和模板文件
        if not hasattr(self, 'current_source_file') or not self.current_source_file:
            QMessageBox.warning(self, "警告", "请先选择源文件")
            return
        
        if not hasattr(self, 'current_template_file') or not self.current_template_file:
            QMessageBox.warning(self, "警告", "请先选择目标模板文件")
            return
        
        # 应用模板映射
        try:
            self.apply_template_mapping(template)
            QMessageBox.information(self, "成功", f"已应用模板: {template_name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"应用模板失败: {str(e)}")
    
    def apply_template_mapping(self, template):
        """应用模板映射"""
        mapping = template.get('mapping', {})
        field_names = template.get('field_names', [])
        
        if not mapping:
            QMessageBox.warning(self, "警告", "模板中没有映射信息")
            return
        
        # 清空当前映射
        self.mapping_tree.clear()
        
        # 根据模板映射创建映射关系
        for target_col, source_idx in mapping.items():
            if isinstance(source_idx, int) and source_idx < len(field_names):
                source_field = field_names[source_idx]
                
                item = QTreeWidgetItem(self.mapping_tree)
                item.setText(0, source_field)  # 源字段
                item.setText(1, f"列{target_col}")  # 目标字段
                item.setText(2, "已映射")      # 映射状态
        
        # 调整列宽
        self.mapping_tree.resizeColumnToContents(0)
        self.mapping_tree.resizeColumnToContents(1)
        self.mapping_tree.resizeColumnToContents(2)
    
    def on_template_selected(self, template_name: str):
        """模板选择事件（保留兼容性）"""
        pass
    
    def show_template_info(self, template: Dict[str, Any]):
        """显示模板信息（保留兼容性）"""
        pass
    
    def use_selected_template(self):
        """使用选中的模板（保留兼容性）"""
        QMessageBox.information(self, "提示", "请使用模板管理页面查看和应用模板")
    
    def update_mapping_tree(self, field_mapping: Dict[str, str]):
        """更新字段映射树"""
        self.mapping_tree.clear()
        
        for template_field, source_field in field_mapping.items():
            item = QTreeWidgetItem([template_field, source_field, "未知"])
            self.mapping_tree.addTopLevelItem(item)
        
        # 调整列宽
        self.mapping_tree.resizeColumnToContents(0)
        self.mapping_tree.resizeColumnToContents(1)
        self.mapping_tree.resizeColumnToContents(2)
    
    def auto_map_fields(self):
        """自动映射字段"""
        if not hasattr(self, 'current_source_file') or not self.current_source_file:
            QMessageBox.warning(self, "警告", "请先选择源文件")
            return
        
        if not hasattr(self, 'current_template_file') or not self.current_template_file:
            QMessageBox.warning(self, "警告", "请先选择模板文件")
            return
        
        if not hasattr(self, 'source_fields') or not hasattr(self, 'template_fields'):
            QMessageBox.warning(self, "警告", "请先加载文件字段信息")
            return
        
        try:
            # 简单的自动映射逻辑：根据字段名相似度进行匹配
            auto_mapping = {}
            mapped_source = set()
            
            for i, template_field in enumerate(self.template_fields):
                best_match = None
                best_score = 0
                
                for j, source_field in enumerate(self.source_fields):
                    if j in mapped_source:
                        continue
                    
                    # 简单的相似度计算
                    if source_field.lower() == template_field.lower():
                        score = 1.0
                    elif source_field.lower() in template_field.lower() or template_field.lower() in source_field.lower():
                        score = 0.8
                    else:
                        score = 0
                    
                    if score > best_score:
                        best_score = score
                        best_match = j
                
                if best_match is not None and best_score > 0.5:
                    auto_mapping[str(i)] = best_match
                    mapped_source.add(best_match)
            
            # 更新映射树显示
            self.mapping_tree.clear()
            
            for i, source_field in enumerate(self.source_fields):
                item = QTreeWidgetItem(self.mapping_tree)
                item.setText(0, source_field)  # 源字段
                
                # 查找是否有映射
                mapped_to = None
                for target_idx, source_idx in auto_mapping.items():
                    if source_idx == i:
                        mapped_to = int(target_idx)
                        break
                
                if mapped_to is not None and mapped_to < len(self.template_fields):
                    item.setText(1, self.template_fields[mapped_to])  # 目标字段
                    item.setText(2, "已映射")  # 映射状态
                else:
                    item.setText(1, "未映射")  # 目标字段
                    item.setText(2, "待映射")  # 映射状态
            
            # 调整列宽
            self.mapping_tree.resizeColumnToContents(0)
            self.mapping_tree.resizeColumnToContents(1)
            self.mapping_tree.resizeColumnToContents(2)
            
            # 显示映射结果
            mapped_count = len(auto_mapping)
            unmapped_count = len(self.source_fields) - mapped_count
            
            info = f"自动映射完成:\n"
            info += f"成功映射: {mapped_count} 个字段\n"
            info += f"未映射: {unmapped_count} 个字段\n"
            
            QMessageBox.information(self, "自动映射结果", info)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"自动映射失败: {str(e)}")
    
    def show_field_mapping(self):
        """显示字段映射"""
        if self.mapping_tree.topLevelItemCount() == 0:
            QMessageBox.information(self, "提示", "当前没有字段映射")
            return
        
        # 收集映射信息
        mapping_info = "当前字段映射:\n\n"
        for i in range(self.mapping_tree.topLevelItemCount()):
            item = self.mapping_tree.topLevelItem(i)
            if item is not None:
                source_field = item.text(0)      # 第0列是源字段
                template_field = item.text(1)    # 第1列是模板字段
                mapping_info += f"{template_field} <- {source_field}\n"
        
        QMessageBox.information(self, "字段映射", mapping_info)
    
    def custom_field_mapping(self):
        """自定义字段映射"""
        if not hasattr(self, 'source_fields') or not hasattr(self, 'template_fields'):
            QMessageBox.warning(self, "警告", "请先选择源文件和模板文件")
            return
        
        if not self.source_fields or not self.template_fields:
            QMessageBox.warning(self, "警告", "源文件或模板文件字段为空")
            return
        
        # 创建自定义映射对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("⚙️ 自定义字段映射")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setGeometry(200, 200, 800, 600)
        
        # 根据当前主题设置对话框样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if theme_manager._dark_mode:
            # 暗色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    border-radius: 10px;
                }
                QLabel {
                    font-size: 14px;
                    color: #f0f0f0;
                    padding: 5px 0;
                    background-color: transparent;
                }
                QLabel.title {
                    font-size: 18px;
                    font-weight: bold;
                    color: #bb86fc;
                    padding: 10px 0;
                    border-bottom: 2px solid #383838;
                    margin-bottom: 15px;
                }
                QComboBox {
                    border: 2px solid #383838;
                    border-radius: 6px;
                    padding: 8px 12px;
                    padding-right: 35px; /* 为下拉箭头留出空间 */
                    font-size: 13px;
                    background-color: #252525;
                    color: #f0f0f0;
                    min-width: 150px;
                }
                QComboBox:focus {
                    border-color: #bb86fc;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                    background-color: transparent;
                }
                QComboBox::down-arrow {
                    image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%23bb86fc'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
                    width: 20px;
                    height: 20px;
                    margin-right: 5px;
                }
                QComboBox QAbstractItemView {
                    background-color: #252525;
                    color: #f0f0f0;
                    border: 1px solid #383838;
                    selection-background-color: #bb86fc;
                    selection-color: #1e1e1e;
                    outline: 0px;
                }
                QScrollArea {
                    background: #252525;
                    border: 2px solid #383838;
                    border-radius: 10px;
                    padding: 5px;
                }
                QScrollArea QWidget {
                    background: transparent;
                }
                /* 移除按钮样式，使用全局样式 */
                QPushButton#add {
                    min-width: 80px;
                    padding: 10px 20px;
                }
                QPushButton#remove {
                    min-width: 80px;
                    padding: 10px 20px;
                }
                QPushButton#cancel {
                    min-width: 80px;
                    padding: 10px 20px;
                }
            """)
        else:
            # 亮色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #f8f9fa;
                    border-radius: 10px;
                }
                QLabel {
                    font-size: 14px;
                    color: #2c3e50;
                    padding: 5px 0;
                }
                QLabel.title {
                    font-size: 18px;
                    font-weight: bold;
                    color: #1976d2;
                    padding: 10px 0;
                    border-bottom: 2px solid #e3f2fd;
                    margin-bottom: 15px;
                }
                QComboBox {
                    border: 2px solid #e3f2fd;
                    border-radius: 6px;
                    padding: 8px 12px;
                    padding-right: 35px; /* 为下拉箭头留出空间 */
                    font-size: 13px;
                    background: white;
                    min-width: 150px;
                }
                QComboBox:focus {
                    border-color: #1976d2;
                    outline: none;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                    background-color: transparent;
                }
                QComboBox::down-arrow {
                    image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='%231976d2'%3E%3Cpath d='M0 5l10 10 10-5z'/%3E%3C/svg%3E");
                    width: 20px;
                    height: 20px;
                    margin-right: 5px;
                }
            """)
            
            self.setStyleSheet("""
                /* 移除按钮样式，使用全局样式 */
                QPushButton {
                    min-width: 80px;
                    padding: 10px 20px;
                }
            QScrollArea {
                background: white;
                border: 2px solid #e3f2fd;
                border-radius: 10px;
                padding: 5px;
            }
            QScrollArea QWidget {
                background: transparent;
            }
        """)
        
        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)
        
        # 标题
        title_label = QLabel("⚙️ 自定义字段映射")
        title_label.setProperty("class", "title")
        main_layout.addWidget(title_label)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # 映射列表
        self.mapping_widgets = []
        
        # 添加现有映射
        current_mappings = self.get_current_field_mapping()
        if current_mappings:
            for target_field, source_field in current_mappings.items():
                self.add_mapping_row(scroll_layout, source_field, target_field)
        else:
            # 根据源文件字段数量添加对应数量的空映射行
            if self.source_fields:
                for source_field in self.source_fields:
                    self.add_mapping_row(scroll_layout, source_field, "")
            else:
                # 如果没有源字段，至少添加一个空的映射行
                self.add_mapping_row(scroll_layout)
        
        # 设置滚动区域背景色
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        if theme_manager._dark_mode:
            scroll_widget.setStyleSheet("background-color: #252525;")
            # 确保滚动区域在暗色模式下有正确的边框和背景色
            scroll_area.setStyleSheet("""
                QScrollArea {
                    background-color: #252525;
                    border: 2px solid #383838;
                    border-radius: 10px;
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
            """)
        else:
            scroll_widget.setStyleSheet("background-color: white;")
            
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ 添加映射")
        add_btn.setObjectName("add")
        add_btn.clicked.connect(lambda: self.add_mapping_row(scroll_layout))
        button_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("➖ 删除最后一行")
        remove_btn.setObjectName("remove")
        remove_btn.clicked.connect(lambda: self.remove_last_mapping_row(scroll_layout))
        button_layout.addWidget(remove_btn)
        
        button_layout.addStretch()
        
        apply_btn = QPushButton("✅ 应用映射")
        apply_btn.clicked.connect(lambda: self.apply_custom_mapping(dialog))
        button_layout.addWidget(apply_btn)
        
        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(button_layout)
        
        dialog.exec()
    
    def add_mapping_row(self, layout, source_field="", target_field=""):
        """添加映射行"""
        row_widget = QWidget()
        # 设置行部件背景色
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        if theme_manager._dark_mode:
            row_widget.setStyleSheet("background-color: #252525;")
        else:
            row_widget.setStyleSheet("background-color: white;")
            
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(10, 5, 10, 5)
        
        # 源字段下拉框
        source_label = QLabel("源字段:")
        source_combo = QComboBox()
        source_combo.addItem("请选择源字段")
        source_combo.addItems(self.source_fields)
        if source_field and source_field in self.source_fields:
            source_combo.setCurrentText(source_field)
        
        # 目标字段下拉框
        target_label = QLabel("→ 目标字段:")
        target_combo = QComboBox()
        target_combo.addItem("请选择目标字段")
        target_combo.addItems(self.template_fields)
        if target_field and target_field in self.template_fields:
            target_combo.setCurrentText(target_field)
        
        row_layout.addWidget(source_label)
        row_layout.addWidget(source_combo)
        row_layout.addWidget(target_label)
        row_layout.addWidget(target_combo)
        row_layout.addStretch()
        
        # 保存组件引用
        self.mapping_widgets.append({
            'widget': row_widget,
            'source_combo': source_combo,
            'target_combo': target_combo
        })
        
        layout.addWidget(row_widget)
    
    def remove_last_mapping_row(self, layout):
        """删除最后一行映射"""
        if len(self.mapping_widgets) > 1:  # 至少保留一行
            last_mapping = self.mapping_widgets.pop()
            last_mapping['widget'].deleteLater()
    
    def apply_custom_mapping(self, dialog):
        """应用自定义映射"""
        # 收集映射关系
        mappings = {}
        
        for mapping_widget in self.mapping_widgets:
            source_field = mapping_widget['source_combo'].currentText()
            target_field = mapping_widget['target_combo'].currentText()
            
            if (source_field != "请选择源字段" and target_field != "请选择目标字段" and
                source_field in self.source_fields and target_field in self.template_fields):
                mappings[target_field] = source_field
        
        if not mappings:
            QMessageBox.warning(dialog, "警告", "请至少设置一个有效的字段映射")
            return
        
        # 更新映射树显示
        self.mapping_tree.clear()
        
        for target_field, source_field in mappings.items():
            item = QTreeWidgetItem(self.mapping_tree)
            item.setText(0, source_field)  # 源字段
            item.setText(1, target_field)  # 目标字段
            item.setText(2, "已映射")      # 映射状态
        
        # 调整列宽
        self.mapping_tree.resizeColumnToContents(0)
        self.mapping_tree.resizeColumnToContents(1)
        self.mapping_tree.resizeColumnToContents(2)
        
        QMessageBox.information(dialog, "成功", f"已设置 {len(mappings)} 个字段映射")
        dialog.accept()
    
    def preview_data_filling(self):
        """预览数据填充"""
        if not self.current_source_file or not self.current_template_file:
            QMessageBox.warning(self, "警告", "请先选择源文件和模板文件")
            return
        
        # 获取字段映射
        field_mapping = self.get_current_field_mapping()
        if not field_mapping:
            QMessageBox.warning(self, "警告", "请先设置字段映射")
            return
        
        # 启动预览线程
        self.start_processing_thread('preview_filling', {
            'source_file': self.current_source_file,
            'template_file': self.current_template_file,
            'field_mapping': field_mapping,
            'preview_rows': 10
        })
    
    def start_data_filling(self):
        """开始数据填充"""
        if not self.current_source_file or not self.current_template_file:
            QMessageBox.warning(self, "警告", "请先选择源文件和模板文件")
            return
        
        # 获取字段映射
        field_mapping = self.get_current_field_mapping()
        if not field_mapping:
            QMessageBox.warning(self, "警告", "请先设置字段映射")
            return
        
        # 选择输出文件
        output_file, _ = QFileDialog.getSaveFileName(
            self, "保存填充结果", "", 
            "Excel文件 (*.xlsx);;所有文件 (*)"
        )
        
        if output_file:
            # 启动填充线程
            self.start_processing_thread('fill_template', {
                'source_file': self.current_source_file,
                'template_file': self.current_template_file,
                'field_mapping': field_mapping,
                'output_file': output_file
            })
    
    def get_current_field_mapping(self) -> Dict[str, str]:
        """获取当前字段映射"""
        field_mapping = {}
        
        for i in range(self.mapping_tree.topLevelItemCount()):
            item = self.mapping_tree.topLevelItem(i)
            if item is not None:
                source_field = item.text(0)    # 第0列是源字段
                template_field = item.text(1)  # 第1列是模板字段
                if template_field and source_field and template_field != "未映射":
                    field_mapping[template_field] = source_field  # key: 模板字段, value: 源字段
        
        return field_mapping
    
    def save_filling_result(self):
        """保存填充结果"""
        QMessageBox.information(self, "提示", "请使用'开始填充'功能直接保存结果")
    
    # 模板管理相关方法
    def on_template_item_selected(self, item):
        """模板项选择事件"""
        # 从项目文本中提取模板名称
        item_text = item.text()
        template_name = item_text.split(" - ")[0]
        
        # 找到对应的模板
        selected_template = None
        for template in self.current_templates:
            if template['name'] == template_name:
                selected_template = template
                break
        
        if selected_template:
            self.show_template_info(selected_template)
    
    def create_new_template(self):
        """创建新模板"""
        # 创建新模板对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("➕ 创建新模板")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setGeometry(200, 200, 500, 300)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
                border-radius: 10px;
            }
            QLabel {
                font-size: 14px;
                color: #2c3e50;
                padding: 5px 0;
            }
            QLineEdit, QTextEdit {
                border: 2px solid #e3f2fd;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                background: white;
            }
            QLineEdit:focus, QTextEdit:focus {
                border-color: #1976d2;
                outline: none;
            }
            /* 移除按钮样式，使用全局样式 */
            QPushButton {
                min-width: 80px;
                padding: 10px 20px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 模板名称
        name_label = QLabel("模板名称:")
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("请输入模板名称")
        layout.addWidget(name_label)
        layout.addWidget(name_edit)
        
        # 描述
        desc_label = QLabel("描述:")
        desc_edit = QTextEdit()
        desc_edit.setPlaceholderText("请输入模板描述")
        desc_edit.setMaximumHeight(80)
        layout.addWidget(desc_label)
        layout.addWidget(desc_edit)
        
        # 目标模板文件
        target_label = QLabel("目标模板文件:")
        target_layout = QHBoxLayout()
        target_edit = QLineEdit()
        target_edit.setPlaceholderText("请选择目标模板文件")
        target_btn = QPushButton("浏览")
        
        def select_target_file():
            file_path, _ = QFileDialog.getOpenFileName(
                dialog, "选择目标模板文件", "", 
                "Excel文件 (*.xlsx *.xls);;所有文件 (*)"
            )
            if file_path:
                target_edit.setText(file_path)
        
        target_btn.clicked.connect(select_target_file)
        target_layout.addWidget(target_edit)
        target_layout.addWidget(target_btn)
        
        layout.addWidget(target_label)
        layout.addLayout(target_layout)
        
        # 按钮
        button_layout = QHBoxLayout()
        create_btn = QPushButton("✅ 创建")
        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setObjectName("cancel")
        
        def create_template():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(dialog, "警告", "请输入模板名称")
                return
            
            if name in self.templates:
                QMessageBox.warning(dialog, "警告", "模板名称已存在")
                return
            
            # 创建新模板
            from datetime import datetime
            new_template = {
                "description": desc_edit.toPlainText().strip(),
                "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "target_template": target_edit.text().strip(),
                "mapping": {},
                "source_format": "txt",
                "delimiter": "|",
                "field_names": []
            }
            
            self.templates[name] = new_template
            
            # 保存到文件
            try:
                import os
                templates_file = self.get_templates_file_path()
                
                # 保存所有模板（包括预定义模板）
                with open(str(templates_file), 'w', encoding='utf-8') as f:
                    json.dump(self.templates, f, ensure_ascii=False, indent=2)
                
                self.update_template_list()
                QMessageBox.information(dialog, "成功", "模板创建成功")
                dialog.accept()
            except Exception as e:
                QMessageBox.critical(dialog, "错误", f"创建模板失败: {str(e)}")
        
        create_btn.clicked.connect(create_template)
        cancel_btn.clicked.connect(dialog.reject)
        
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        dialog.exec()
    
    def view_template(self):
        """查看模板详情"""
        current_item = self.template_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择一个模板")
            return
        
        template_name = current_item.text()
        if template_name not in self.templates:
            QMessageBox.warning(self, "警告", "模板信息不存在")
            return
        
        template = self.templates[template_name]
        
        # 创建现代化模板详情对话框
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📋 模板详情 - {template_name}")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setGeometry(150, 150, 800, 600)
        
        # 根据当前主题设置对话框样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if theme_manager._dark_mode:
            # 暗色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    border-radius: 10px;
                }
                QLabel.title {
                    font-size: 20px;
                    font-weight: bold;
                    color: #bb86fc;
                    padding: 10px 0;
                    margin-bottom: 15px;
                    background-color: transparent;
                }
                QLabel.section {
                    font-size: 16px;
                    color: #bb86fc;
                    padding: 8px 0;
                    border-bottom: 2px solid #383838;
                    margin: 10px 0 5px 0;
                    background-color: transparent;
                }
                QLabel.content {
                    font-size: 13px;
                    color: #f0f0f0;
                    padding: 5px 10px;
                    background: #252525;
                    border-radius: 6px;
                }
                
                QScrollArea {
                    background: #252525;
                    border: 2px solid #383838;
                    border-radius: 10px;
                    padding: 5px;
                }
                
                QScrollArea QWidget {
                    background: transparent;
                }
            """)
        else:
            # 亮色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #f8f9fa;
                    border-radius: 10px;
                }
                QLabel.title {
                    font-size: 20px;
                    font-weight: bold;
                    color: #2c3e50;
                    padding: 10px 0;
                    margin-bottom: 15px;
                }
                QLabel.section {
                    font-size: 16px;
                    color: #1976d2;
                    padding: 8px 0;
                    border-bottom: 2px solid #e3f2fd;
                    margin: 10px 0 5px 0;
                }
                QLabel.content {
                    font-size: 13px;
                    color: #37474f;
                    padding: 5px 10px;
                    background: #f8f9fa;
                    border-radius: 6px;
            """)

            # 不再直接引用不存在的属性
            # 而是应用样式到当前对话框的元素
            
            # 设置对话框中的样式
            dialog.setStyleSheet(dialog.styleSheet() + """
                QLabel {
                    margin: 3px 0;
                    font-weight: normal;
                }
                
                QScrollArea {
                    background: white;
                    border: 2px solid #e3f2fd;
                    border-radius: 10px;
                    padding: 5px;
                }
                QScrollArea QWidget {
                    background: transparent;
                }
                
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #42a5f5, stop:1 #1976d2);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 12px 30px;
                    font-weight: bold;
                    font-size: 14px;
                    outline: none;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #64b5f6, stop:1 #1e88e5);
                    transform: translateY(-1px);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1976d2, stop:1 #0d47a1);
                    transform: translateY(1px);
                }
            """)
        
        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(25, 25, 25, 25)
        
        # 标题
        title_label = QLabel(f"📋 {template_name}")
        title_label.setProperty("class", "title")
        main_layout.addWidget(title_label)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # 基本信息部分
        basic_section = QLabel("📝 基本信息")
        basic_section.setProperty("class", "section")
        scroll_layout.addWidget(basic_section)
        
        # 描述
        desc_label = QLabel(f"描述: {template.get('description', '无描述')}")
        desc_label.setProperty("class", "content")
        desc_label.setWordWrap(True)
        scroll_layout.addWidget(desc_label)
        
        # 创建时间
        created_at = template.get('created_at', '未知')
        if created_at != '未知' and 'T' in created_at:
            # 格式化ISO时间戳为可读格式
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                created_at = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        time_label = QLabel(f"创建时间: {created_at}")
        time_label.setProperty("class", "content")
        scroll_layout.addWidget(time_label)
        
        # 目标模板文件
        target_file = template.get('target_template', '未指定')
        target_label = QLabel(f"目标模板文件: {target_file}")
        target_label.setProperty("class", "content")
        target_label.setWordWrap(True)
        scroll_layout.addWidget(target_label)
        
        # 源数据格式
        format_info = f"源数据格式: {template.get('source_format', 'txt')}"
        if template.get('delimiter'):
            format_info += f" (分隔符: {template.get('delimiter')})"
        format_label = QLabel(format_info)
        format_label.setProperty("class", "content")
        scroll_layout.addWidget(format_label)
        
        # 字段映射部分
        mapping_section = QLabel("🔗 字段映射关系")
        mapping_section.setProperty("class", "section")
        scroll_layout.addWidget(mapping_section)
        
        # 显示字段映射
        field_mapping = template.get('field_mapping', {})
        
        if field_mapping:
            for target_field, source_field in field_mapping.items():
                mapping_text = f"目标字段 {target_field} ← 源字段 {source_field}"
                mapping_label = QLabel(mapping_text)
                mapping_label.setProperty("class", "content")
                scroll_layout.addWidget(mapping_label)
        else:
            no_mapping_label = QLabel("暂无字段映射信息")
            no_mapping_label.setProperty("class", "content")
            scroll_layout.addWidget(no_mapping_label)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        main_layout.addWidget(close_btn)
        
        dialog.exec()
    
    def edit_selected_template(self):
        """编辑选中的模板"""
        current_item = self.template_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要编辑的模板")
            return
        
        template_name = current_item.text()
        if template_name not in self.templates:
            QMessageBox.warning(self, "警告", "模板信息不存在")
            return
        
        template = self.templates[template_name]
        
        # 创建编辑对话框
        dialog = QDialog(self)
        dialog.setWindowTitle(f"✏️ 编辑模板 - {template_name}")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setGeometry(200, 200, 600, 400)
        
        # 根据当前主题设置对话框样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if theme_manager._dark_mode:
            # 暗色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    border-radius: 10px;
                }
                QLabel {
                    font-size: 14px;
                    color: #f0f0f0;
                    padding: 5px 0;
                    background-color: transparent;
                }
                QLineEdit, QTextEdit {
                    border: 2px solid #383838;
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 13px;
                    background-color: #252525;
                    color: #f0f0f0;
                }
                QLineEdit:focus, QTextEdit:focus {
                    border-color: #bb86fc;
                    outline: none;
                }
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #bb86fc, stop:1 #985eff);
            """)
        else:
            # 亮色模式样式
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #f8f9fa;
                    border-radius: 10px;
                }
                QLabel {
                    font-size: 14px;
                    color: #2c3e50;
                    padding: 5px 0;
                }
                QLineEdit, QTextEdit {
                    border: 2px solid #e3f2fd;
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-size: 13px;
                    background: white;
                }
                QLineEdit:focus, QTextEdit:focus {
                    border-color: #1976d2;
                    outline: none;
                }
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #42a5f5, stop:1 #1976d2);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #64b5f6, stop:1 #1e88e5);
                }
                QPushButton#cancel {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #bdbdbd, stop:1 #757575);
                }
                QPushButton#cancel:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #e0e0e0, stop:1 #9e9e9e);
                }
            """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 模板名称
        name_label = QLabel("模板名称:")
        name_edit = QLineEdit(template_name)
        layout.addWidget(name_label)
        layout.addWidget(name_edit)
        
        # 描述
        desc_label = QLabel("描述:")
        desc_edit = QTextEdit(template.get('description', ''))
        desc_edit.setMaximumHeight(100)
        layout.addWidget(desc_label)
        layout.addWidget(desc_edit)
        
        # 目标模板文件
        target_label = QLabel("目标模板文件:")
        target_edit = QLineEdit(template.get('target_template', ''))
        layout.addWidget(target_label)
        layout.addWidget(target_edit)
        
        # 按钮
        button_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存")
        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setObjectName("cancel")
        
        def save_changes():
            new_name = name_edit.text().strip()
            if not new_name:
                QMessageBox.warning(dialog, "警告", "模板名称不能为空")
                return
            
            # 更新模板信息
            updated_template = template.copy()
            updated_template['description'] = desc_edit.toPlainText().strip()
            updated_template['target_template'] = target_edit.text().strip()
            
            # 如果名称改变了，删除旧的，添加新的
            if new_name != template_name:
                if new_name in self.templates:
                    QMessageBox.warning(dialog, "警告", "模板名称已存在")
                    return
                del self.templates[template_name]
            
            self.templates[new_name] = updated_template
            
            # 保存到文件
            try:
                import os
                templates_file = self.get_templates_file_path()
                
                # 保存所有模板（包括预定义模板）
                with open(str(templates_file), 'w', encoding='utf-8') as f:
                     json.dump(self.templates, f, indent=2, ensure_ascii=False)
                
                self.update_template_list()
                QMessageBox.information(dialog, "成功", "模板已保存")
                dialog.accept()
            except Exception as e:
                QMessageBox.critical(dialog, "错误", f"保存模板失败: {str(e)}")
        
        save_btn.clicked.connect(save_changes)
        cancel_btn.clicked.connect(dialog.reject)
        
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        dialog.exec()
    
    def delete_selected_template(self):
        """删除选中的模板"""
        current_item = self.template_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要删除的模板")
            return
        
        template_name = current_item.text()
        
        # 检查是否为预定义模板
        if template_name == "网络安全协调指挥平台系统档案模板":
            QMessageBox.warning(self, "警告", "不能删除预定义模板")
            return
        
        # 确认删除
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除模板 '{template_name}' 吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 从内存中删除
                if template_name in self.templates:
                    del self.templates[template_name]
                
                # 保存到文件
                import os
                templates_file = self.get_templates_file_path()
                
                # 保存所有剩余模板（包括预定义模板）
                with open(str(templates_file), 'w', encoding='utf-8') as f:
                    json.dump(self.templates, f, ensure_ascii=False, indent=2)
                
                # 更新列表
                self.update_template_list()
                QMessageBox.information(self, "成功", f"模板 '{template_name}' 已删除")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除模板失败: {str(e)}")
    
    def import_template(self):
        """导入模板"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入模板", "", 
            "JSON文件 (*.json);;所有文件 (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_data = json.load(f)
                
                # 验证导入的数据格式
                if not isinstance(imported_data, dict):
                    QMessageBox.critical(self, "错误", "无效的模板文件格式")
                    return
                
                # 检查是否为单个模板还是多个模板
                if 'mapping' in imported_data:  # 单个模板
                    template_name = imported_data.get('name', f"导入模板_{len(self.templates)}")
                    if template_name in self.templates:
                        reply = QMessageBox.question(
                            self, "模板已存在", 
                            f"模板 '{template_name}' 已存在，是否覆盖？",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply != QMessageBox.StandardButton.Yes:
                            return
                    
                    self.templates[template_name] = imported_data
                    imported_count = 1
                else:  # 多个模板
                    imported_count = 0
                    for name, template in imported_data.items():
                        if isinstance(template, dict) and 'mapping' in template:
                            if name in self.templates:
                                reply = QMessageBox.question(
                                    self, "模板已存在", 
                                    f"模板 '{name}' 已存在，是否覆盖？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                )
                                if reply != QMessageBox.StandardButton.Yes:
                                    continue
                            
                            self.templates[name] = template
                            imported_count += 1
                
                # 保存到文件
                import os
                templates_file = self.get_templates_file_path()
                
                # 保存所有模板（包括预定义模板）
                with open(str(templates_file), 'w', encoding='utf-8') as f:
                    json.dump(self.templates, f, ensure_ascii=False, indent=2)
                
                # 更新列表
                self.update_template_list()
                QMessageBox.information(self, "成功", f"成功导入 {imported_count} 个模板")
                
            except json.JSONDecodeError:
                QMessageBox.critical(self, "错误", "无效的JSON文件格式")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入模板失败: {str(e)}")
    
    def export_template(self):
        """导出模板"""
        current_item = self.template_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要导出的模板")
            return
        
        template_name = current_item.text()
        if template_name not in self.templates:
            QMessageBox.warning(self, "警告", "模板信息不存在")
            return
        
        template = self.templates[template_name]
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出模板", f"{template_name}.json", 
            "JSON文件 (*.json);;所有文件 (*)"
        )
        
        if file_path:
            try:
                # 添加模板名称到导出数据中
                export_data = template.copy()
                export_data['name'] = template_name
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                
                QMessageBox.information(self, "成功", f"模板已导出到: {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出模板失败: {str(e)}")
    
    # 通用处理方法
    def start_processing_thread(self, operation_type: str, kwargs: Dict[str, Any]):
        """启动处理线程"""
        if self.processing_thread and self.processing_thread.isRunning():
            return
        
        self.processing_thread = DataProcessingThread(operation_type, **kwargs)
        self.processing_thread.progress_updated.connect(self.on_progress_updated)
        self.processing_thread.processing_completed.connect(self.on_processing_completed)
        self.processing_thread.start()
        
        # 显示进度状态
        if operation_type.startswith('extract'):
            self.result_info_label.setText("正在处理...")
            self.result_info_label.setStyleSheet("color: #3498db; font-weight: bold; padding: 5px;")
        elif operation_type == 'fill_template':
            # 显示数据填充进度条
            self.fill_progress_bar.setVisible(True)
            self.fill_status_label.setVisible(True)
            self.fill_progress_bar.setRange(0, 0)  # 不确定进度的进度条
            self.fill_status_label.setText("正在填充数据，请稍候...")
    
    def on_progress_updated(self, message: str):
        """进度更新"""
        # 根据当前选项卡更新状态
        current_tab = self.tab_widget.currentIndex()
        if current_tab == 0:  # 字段提取
            self.result_info_label.setText(message)
            self.result_info_label.setStyleSheet("color: #3498db; font-weight: bold; padding: 5px;")
        elif current_tab == 1:  # 数据填充
            if hasattr(self, 'fill_status_label'):
                self.fill_status_label.setText(message)
    
    def on_processing_completed(self, result: Dict[str, Any]):
        """处理完成"""
        print(f"[DEBUG] on_processing_completed被调用，结果: {result}")  # 调试信息
        if result['success']:
            operation_type = result.get('operation_type', '')
            print(f"[DEBUG] 操作类型: {operation_type}")  # 调试信息
            
            if operation_type == 'extract_fields':  # 字段提取操作
                # 显示提取结果信息
                self.result_info_label.setText(result['message'])
                self.result_info_label.setStyleSheet("color: #27ae60; font-weight: bold; padding: 5px;")
                
                # 显示实际提取的数据内容而不是统计信息
                if 'extracted_data' in result:
                    extracted_data = result['extracted_data']
                    selected_fields = result.get('selected_fields', [])
                    
                    if extracted_data and len(extracted_data) > 0:
                        # 格式化显示前几行数据
                        preview_lines = []
                        preview_lines.append(f"提取字段: {', '.join(selected_fields)}")
                        preview_lines.append("=" * 60)
                        
                        # 显示前15行数据
                        for i, row in enumerate(extracted_data[:15]):
                            if isinstance(row, list):
                                row_data = []
                                for j, cell in enumerate(row):
                                    if j < len(selected_fields):
                                        row_data.append(f"{selected_fields[j]}: {str(cell)}")
                                    else:
                                        row_data.append(str(cell))
                                preview_lines.append(f"第{i+1}行: {' | '.join(row_data)}")
                            else:
                                preview_lines.append(f"第{i+1}行: {str(row)}")
                        
                        if len(extracted_data) > 15:
                            preview_lines.append(f"\n... 还有 {len(extracted_data) - 15} 行数据，请打开文件查看完整内容")
                        
                        self.result_preview.setPlainText('\n'.join(preview_lines))
                    else:
                        self.result_preview.setPlainText("未提取到数据")
                elif 'preview_data' in result:
                    # 兼容旧格式
                    preview_text = json.dumps(result['preview_data'], indent=2, ensure_ascii=False)
                    self.result_preview.setPlainText(preview_text)
                
                # 更新文件保存信息
                if 'output_file' in result:
                    self.save_file_label.setText(f"保存位置: {result['output_file']}")
                    self.save_file_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                    self.open_file_btn.setEnabled(True)
                    self.extracted_file_path = result['output_file']
            
            elif operation_type == 'fill_template':  # 数据填充操作
                # 隐藏进度条
                if hasattr(self, 'fill_progress_bar'):
                    self.fill_progress_bar.setVisible(False)
                if hasattr(self, 'fill_status_label'):
                    self.fill_status_label.setVisible(False)
                
                # 数据填充完成处理
                if 'output_file' in result:
                    # 从statistics中获取统计信息
                    statistics = result.get('statistics', {})
                    filled_count = statistics.get('filled_rows', 0)
                    mapped_fields = len(statistics.get('field_mapping', {}))
                    
                    # 如果statistics为空，尝试从result直接获取
                    if filled_count == 0 and 'filled_count' in result:
                        filled_count = result['filled_count']
                    if mapped_fields == 0 and 'mapped_fields' in result:
                        mapped_fields = result['mapped_fields']
                    
                    # 显示详细的成功信息
                    success_msg = f"✅ 数据填充完成！\n\n📊 处理统计:\n• 填充行数: {filled_count} 行\n• 映射字段: {mapped_fields} 个\n\n💾 结果文件:\n{result['output_file']}"
                    QMessageBox.information(self, "填充成功", success_msg)
        else:
            # 隐藏进度条（如果有的话）
            operation_type = result.get('operation_type', '')
            if operation_type == 'fill_template':  # 数据填充操作
                if hasattr(self, 'fill_progress_bar'):
                    self.fill_progress_bar.setVisible(False)
                if hasattr(self, 'fill_status_label'):
                    self.fill_status_label.setVisible(False)
            
            # 显示错误
            QMessageBox.critical(self, "错误", result['message'])
            if operation_type == 'extract_fields':
                self.result_info_label.setText("处理失败")
                self.result_info_label.setStyleSheet("color: #e74c3c; font-weight: bold; padding: 5px;")
    
    def _setup_theme_connections(self):
        """设置主题管理器连接"""
        try:
            theme_manager = ThemeManager()
            # 连接主题变化信号
            theme_manager.dark_mode_changed.connect(self._on_theme_changed)
            # 初始化样式
            self._update_status_label_style()
        except Exception as e:
            logging.warning(f"主题连接设置失败: {e}")
    
    def _on_theme_changed(self, is_dark_mode: bool):
        """主题变化时的回调"""
        self._update_status_label_style()
    
    def _update_status_label_style(self):
        """更新状态标签样式"""
        if hasattr(self, 'fill_status_label'):
            try:
                theme_manager = ThemeManager()
                if theme_manager._dark_mode:
                    # 暗色模式样式
                    color = "#64b5f6"  # 蓝色
                else:
                    # 亮色模式样式
                    color = "#1976d2"  # 深蓝色
                
                self.fill_status_label.setStyleSheet(f"color: {color}; font-weight: bold; padding: 5px;")
            except Exception as e:
                logging.warning(f"状态标签样式更新失败: {e}")
                # 使用默认样式
                self.fill_status_label.setStyleSheet("font-weight: bold; padding: 5px;")