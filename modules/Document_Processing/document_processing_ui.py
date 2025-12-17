#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档处理UI组件

提供Word转PDF和PDF页面提取的图形界面
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict

# 减少Qt字体和DirectWrite警告
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts.warning=false;qt.qpa.fonts=false'
os.environ['QT_QPA_PLATFORM'] = 'windows:fontengine=freetype'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'RoundPreferFloor'

from PySide6.QtCore import QThread, Signal, Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, 
    QLineEdit, QTextEdit, QLabel, QCheckBox, QFileDialog, 
    QProgressBar, QMessageBox, QTabWidget, QFormLayout,
    QSpinBox, QComboBox, QScrollArea, QSplitter, QFrame,
    QListWidget, QListWidgetItem, QAbstractItemView, QLayout
)
from PySide6.QtGui import QPixmap, QImage, QPainter
from modules.ui.message_box_helper import show_warning, show_information, show_critical


class DocumentConversionWorker(QThread):
    """文档转换工作线程（支持Word<->PDF双向转换）"""
    progress_updated = Signal(str)
    progress_percentage = Signal(int)  # 进度百分比信号
    finished_signal = Signal(bool, str)
    
    def __init__(self, conversion_type: str, input_files: List[str], output_dir: Optional[str] = None, **options):
        super().__init__()
        self.conversion_type = conversion_type  # 'word_to_pdf' 或 'pdf_to_word'
        self.input_files = input_files
        self.output_dir = output_dir
        self.options = options
    
    def run(self):
        try:
            if self.conversion_type == 'word_to_pdf':
                self._word_to_pdf_conversion()
            elif self.conversion_type == 'pdf_to_word':
                self._pdf_to_word_conversion()
            else:
                self.finished_signal.emit(False, f"不支持的转换类型: {self.conversion_type}")
                
        except Exception as e:
            self.finished_signal.emit(False, f"转换过程中发生错误: {str(e)}")
    
    def _word_to_pdf_conversion(self):
        """Word转PDF转换 - 直接调用函数"""
        try:
            # 直接导入转换函数
            from modules.Document_Processing.doc_pdf import convert_with_word_com, list_document_files, compute_output_path
            
            # 准备文件列表
            files_to_convert = []
            total_files = len(self.input_files)
            processed_files = 0
            
            self.progress_updated.emit(f"开始处理 {total_files} 个文件...")
            
            for input_file in self.input_files:
                input_path = Path(input_file)
                
                # 计算输出路径
                if len(self.input_files) == 1:
                    # 单文件处理
                    input_root = input_path.parent
                else:
                    # 多文件处理，使用第一个文件的父目录
                    input_root = Path(self.input_files[0]).parent
                
                output_root = Path(self.output_dir) if self.output_dir else None
                output_path = compute_output_path(input_path, input_root, output_root, "word_to_pdf")
                
                files_to_convert.append((input_path, output_path))
                
                # 更新进度
                processed_files += 1
                progress = int(processed_files * 50 / total_files)  # 前50%用于准备
                self.progress_percentage.emit(progress)
                self.progress_updated.emit(f"准备转换: {input_path.name}")
            
            # 执行转换
            self.progress_updated.emit("开始Word转PDF转换...")
            converted, skipped, failures = convert_with_word_com(
                files_to_convert, 
                overwrite=self.options.get('overwrite', True)
            )
            
            # 更新最终进度
            self.progress_percentage.emit(100)
            
            # 报告结果
            if converted > 0:
                self.progress_updated.emit(f"转换成功: {converted} 个文件")
            if skipped > 0:
                self.progress_updated.emit(f"跳过: {skipped} 个文件")
            if failures:
                self.progress_updated.emit(f"失败: {len(failures)} 个文件")
                for src, reason in failures:
                    self.progress_updated.emit(f"  {src.name}: {reason}")
            
            # 发送完成信号
            if len(failures) == 0:
                self.finished_signal.emit(True, f"Word转PDF完成：成功 {converted}，跳过 {skipped}")
            else:
                error_msg = f"转换完成但有失败：成功 {converted}，跳过 {skipped}，失败 {len(failures)}"
                self.finished_signal.emit(False, error_msg)
                
        except Exception as e:
            self.finished_signal.emit(False, f"Word转PDF错误: {str(e)}")
    
    def _pdf_to_word_conversion(self):
        """PDF转Word转换 - 直接调用函数"""
        try:
            # 直接导入转换函数
            from modules.Document_Processing.doc_pdf import convert_pdf_to_word, compute_output_path
            
            # 准备文件列表
            files_to_convert = []
            total_files = len(self.input_files)
            processed_files = 0
            
            self.progress_updated.emit(f"开始处理 {total_files} 个文件...")
            
            for input_file in self.input_files:
                input_path = Path(input_file)
                
                # 计算输出路径
                if len(self.input_files) == 1:
                    # 单文件处理
                    input_root = input_path.parent
                else:
                    # 多文件处理，使用第一个文件的父目录
                    input_root = Path(self.input_files[0]).parent
                
                output_root = Path(self.output_dir) if self.output_dir else None
                output_path = compute_output_path(input_path, input_root, output_root, "pdf_to_word")
                
                files_to_convert.append((input_path, output_path))
                
                # 更新进度
                processed_files += 1
                progress = int(processed_files * 50 / total_files)  # 前50%用于准备
                self.progress_percentage.emit(progress)
                self.progress_updated.emit(f"准备转换: {input_path.name}")
            
            # 执行转换
            self.progress_updated.emit("开始PDF转Word转换...")
            converted, skipped, failures = convert_pdf_to_word(
                files_to_convert, 
                overwrite=self.options.get('overwrite', True)
            )
            
            # 更新最终进度
            self.progress_percentage.emit(100)
            
            # 报告结果
            if converted > 0:
                self.progress_updated.emit(f"转换成功: {converted} 个文件")
            if skipped > 0:
                self.progress_updated.emit(f"跳过: {skipped} 个文件")
            if failures:
                self.progress_updated.emit(f"失败: {len(failures)} 个文件")
                for src, reason in failures:
                    self.progress_updated.emit(f"  {src.name}: {reason}")
            
            # 发送完成信号
            if len(failures) == 0:
                self.finished_signal.emit(True, f"PDF转Word完成：成功 {converted}，跳过 {skipped}")
            else:
                error_msg = f"转换完成但有失败：成功 {converted}，跳过 {skipped}，失败 {len(failures)}"
                self.finished_signal.emit(False, error_msg)
                
        except Exception as e:
            self.finished_signal.emit(False, f"PDF转Word错误: {str(e)}")


class PdfPreviewWorker(QThread):
    """PDF预览工作线程（支持多文件）"""
    page_loaded = Signal(str, int, QPixmap, str)  # 文件路径, 页码, 图像, 页面信息
    preview_finished = Signal(str, bool, str)  # 文件路径, 成功标志, 消息
    
    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.should_stop = False
        self._success = False
    
    def stop(self):
        """停止预览加载"""
        self.should_stop = True
    
    def run(self):
        try:
            # 尝试导入PyMuPDF
            try:
                import fitz  # PyMuPDF
            except ImportError:
                self.preview_finished.emit(self.pdf_path, False, "未安装 PyMuPDF，请先安装：pip install PyMuPDF")
                return
            
            # 打开PDF文件
            pdf_document = fitz.open(self.pdf_path)
            total_pages = len(pdf_document)
            
            # 逐页加载预览
            for page_num in range(total_pages):
                if self.should_stop:
                    break
                    
                page = pdf_document.load_page(page_num)
                
                # 设置缩放比例（适合预览）
                zoom = 0.5  # 50%缩放
                mat = fitz.Matrix(zoom, zoom)
                # 兼容 PyMuPDF 新旧版本的 get_pixmap 方法
                if hasattr(page, "get_pixmap"):
                    pix = page.get_pixmap(matrix=mat)  # type: ignore
                else:
                    pix = page.getPixmap(matrix=mat)  # type: ignore
                # 转换为QPixmap
                img_data = pix.tobytes("ppm")
                qimg = QImage.fromData(img_data)
                pixmap = QPixmap.fromImage(qimg)
                
                # 页面信息
                page_info = f"第 {page_num + 1} 页 / 共 {total_pages} 页"
                
                # 发送信号（包含文件路径）
                self.page_loaded.emit(self.pdf_path, page_num + 1, pixmap, page_info)
            
            pdf_document.close()
            self._success = True
            self.preview_finished.emit(self.pdf_path, True, f"预览加载完成，共 {total_pages} 页")
            
        except Exception as e:
            self._success = False
            self.preview_finished.emit(self.pdf_path, False, f"预览加载失败: {str(e)}")


class PdfExtractWorker(QThread):
    """PDF页面提取工作线程"""
    progress_updated = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, mode: str, **kwargs):
        """
        初始化PDF提取工作线程
        
        Args:
            mode: 'single' 单文件模式 或 'merge' 多文件合并模式
            **kwargs:
                单文件模式需要: input_path, output_path, page_numbers
                合并模式需要: page_selections, output_path
        """
        super().__init__()
        self.mode = mode
        self.kwargs = kwargs
    
    def run(self):
        try:
            if self.mode == 'single':
                self._extract_single()
            elif self.mode == 'merge':
                self._extract_merge()
            else:
                self.finished_signal.emit(False, f"未知模式: {self.mode}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(False, f"执行错误: {str(e)}")
    
    def _extract_single(self):
        """单文件提取模式"""
        from modules.Document_Processing.pdf_extract import extract_pages
        from pathlib import Path
        
        input_path = Path(self.kwargs['input_path'])
        output_path = Path(self.kwargs['output_path'])
        page_numbers = self.kwargs['page_numbers']
        
        self.progress_updated.emit(f"正在提取 {input_path.name} 的 {len(page_numbers)} 页...")
        
        extracted, total = extract_pages(input_path, output_path, page_numbers)
        
        self.progress_updated.emit(f"已从 {input_path.name} 提取 {extracted}/{total} 页 -> {output_path}")
        self.finished_signal.emit(True, f"提取完成: {output_path}")
    
    def _extract_merge(self):
        """多文件合并模式"""
        from modules.Document_Processing.pdf_extract import merge_pages_from_multiple_pdfs
        from pathlib import Path
        
        page_selections = self.kwargs['page_selections']
        output_path = Path(self.kwargs['output_path'])
        
        self.progress_updated.emit(f"正在合并 {len(page_selections)} 页...")
        
        merged_count, file_count = merge_pages_from_multiple_pdfs(page_selections, output_path)
        
        self.progress_updated.emit(f"已合并 {merged_count} 页（来自 {file_count} 个文件）-> {output_path}")
        self.finished_signal.emit(True, f"合并完成: {output_path}")


class DocumentProcessingUI(QWidget):
    """文档处理UI组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 使用ThemeManager来管理主题
        from ..ui.styles.theme_manager import ThemeManager
        self.theme_manager = ThemeManager()
        
        # 连接主题变更信号
        self.theme_manager.dark_mode_changed.connect(self.on_theme_changed)
        
        self.init_ui()
        
        # 获取脚本路径
        current_dir = Path(__file__).parent
        self.word_to_pdf_script = current_dir / "doc_pdf.py"
        self.pdf_extract_script = current_dir / "pdf_extract.py"
        
    def on_theme_changed(self, is_dark_mode):
        """主题变更时的回调"""
        # 主题变更时，ThemeManager会自动应用全局样式
        # 我们不需要手动重新设置样式，因为全局样式表已经包含了所有组件的样式
        pass
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        
        # 文档转换标签页（Word<->PDF双向转换）
        document_conversion_tab = self.create_document_conversion_tab()
        self.tab_widget.addTab(document_conversion_tab, "文档转换")
        
        # PDF页面提取标签页
        pdf_extract_tab = self.create_pdf_extract_tab()
        self.tab_widget.addTab(pdf_extract_tab, "PDF页面提取")
        
        # 网信办标签页（内部再细分为：通报杂活 / 复测一键出）
        try:
            from .report_rewrite_ui import ReportRewriteUI
            report_rewrite_tab = ReportRewriteUI()
            self.tab_widget.addTab(report_rewrite_tab, "网信办")
        except Exception as e:
            import traceback
            print(f"加载网信办模块失败: {e}")
            traceback.print_exc()
            # 创建一个错误提示页面
            error_widget = QWidget()
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(
                f"⚠️ 网信办模块加载失败\n\n"
                f"错误信息：{str(e)}\n\n"
                f"请检查依赖是否完整"
            )
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("color: red; padding: 20px;")
            error_layout.addWidget(error_label)
            self.tab_widget.addTab(error_widget, "网信办（错误）")
        
        layout.addWidget(self.tab_widget)
        
    def create_document_conversion_tab(self):
        """创建文档转换标签页（Word<->PDF双向转换）"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 滚动区域内容
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        
        # 转换类型选择组
        conversion_type_group = QGroupBox("🔄 转换类型")
        conversion_type_layout = QHBoxLayout(conversion_type_group)
        
        self.conversion_type = QComboBox()
        self.conversion_type.addItems(["Word转PDF", "PDF转Word"])
        self.conversion_type.currentTextChanged.connect(self.on_conversion_type_changed)
        conversion_type_layout.addWidget(QLabel("转换方向:"))
        conversion_type_layout.addWidget(self.conversion_type)
        conversion_type_layout.addStretch()
        
        layout.addWidget(conversion_type_group)
        
        # 输入设置组
        input_group = QGroupBox("输入设置")
        input_layout = QFormLayout(input_group)
        
        # 输入路径
        self.doc_input_path = QLineEdit()
        self.doc_input_path.setPlaceholderText("选择Word文件或文件夹")
        doc_browse_btn = QPushButton("📁 浏览...")
        doc_browse_btn.clicked.connect(self.browse_doc_input)
        
        doc_input_layout = QHBoxLayout()
        doc_input_layout.addWidget(self.doc_input_path)
        doc_input_layout.addWidget(doc_browse_btn)
        input_layout.addRow("输入路径:", doc_input_layout)
        
        # 输出目录
        self.doc_output_dir = QLineEdit()
        self.doc_output_dir.setPlaceholderText("输出目录（可选，默认与源文件同目录）")
        doc_output_btn = QPushButton("📂 浏览...")
        doc_output_btn.clicked.connect(self.browse_doc_output)
        
        doc_output_layout = QHBoxLayout()
        doc_output_layout.addWidget(self.doc_output_dir)
        doc_output_layout.addWidget(doc_output_btn)
        input_layout.addRow("输出目录:", doc_output_layout)
        
        layout.addWidget(input_group)
        
        # 选项设置组
        options_group = QGroupBox("⚙️ 转换选项")
        options_layout = QVBoxLayout(options_group)
        
        # 递归搜索（仅Word转PDF时可用）
        self.doc_recursive = QCheckBox("递归搜索子目录")
        self.doc_recursive.setChecked(True)
        options_layout.addWidget(self.doc_recursive)
        
        # 覆盖已存在文件
        self.doc_overwrite = QCheckBox("覆盖已存在的文件")
        self.doc_overwrite.setChecked(True)
        options_layout.addWidget(self.doc_overwrite)
        
        # 跳过模板文件（仅Word转PDF时可用）
        self.doc_skip_template = QCheckBox("跳过模板文件")
        self.doc_skip_template.setChecked(True)
        options_layout.addWidget(self.doc_skip_template)
        
        # 额外跳过关键词（仅Word转PDF时可用）
        skip_keyword_layout = QHBoxLayout()
        skip_keyword_layout.addWidget(QLabel("跳过关键词:"))
        self.doc_skip_keywords = QLineEdit()
        self.doc_skip_keywords.setPlaceholderText("用逗号分隔多个关键词")
        skip_keyword_layout.addWidget(self.doc_skip_keywords)
        self.skip_keyword_layout = skip_keyword_layout
        options_layout.addLayout(skip_keyword_layout)
        
        layout.addWidget(options_group)
        
        # 转换按钮
        self.doc_convert_btn = QPushButton("🚀 开始转换")
        self.doc_convert_btn.clicked.connect(self.start_document_conversion)
        layout.addWidget(self.doc_convert_btn)
        
        # 现代化进度条
        progress_group = QGroupBox("📊 转换进度")
        progress_layout = QVBoxLayout(progress_group)
        
        self.doc_progress_bar = QProgressBar()
        self.doc_progress_bar.setVisible(False)
        progress_layout.addWidget(self.doc_progress_bar)
        
        # 进度显示文本区域（带滚动条）
        self.doc_progress = QTextEdit()
        self.doc_progress.setMaximumHeight(180)
        self.doc_progress.setReadOnly(True)
        progress_layout.addWidget(self.doc_progress)
        
        layout.addWidget(progress_group)
        
        # 设置滚动区域
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # 存储选项组件引用，便于动态控制
        self.word_only_options = [self.doc_recursive, self.doc_skip_template]
        self.skip_keyword_widgets = [widget for widget in skip_keyword_layout.parent().findChildren(QWidget) if widget.parent() == skip_keyword_layout.parent()]
        
        return widget
        
    def create_pdf_extract_tab(self):
        """创建PDF页面提取标签页"""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # 左侧：设置和控制面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        # 移除固定宽度限制，允许用户调整
        # left_panel.setMaximumWidth(400)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # 不需要横向滚动
        
        # 滚动区域的内容容器
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 15, 0) # 右侧留出更多空间给滚动条，避免遮挡
        scroll_layout.setSpacing(15) # 增加控件间距
        # 关键修复：强制布局计算最小尺寸，配合ScrollArea使用
        scroll_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        
        # 标题：输入设置（替代原来的GroupBox标题）
        title_label = QLabel("输入设置")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #aaa; margin-bottom: 10px;")
        scroll_layout.addWidget(title_label)
        
        # 1. PDF文件选择区域
        file_select_container = QWidget()
        file_select_layout = QVBoxLayout(file_select_container)
        file_select_layout.setContentsMargins(0, 0, 0, 0)
        file_select_layout.setSpacing(8)
        
        file_label = QLabel("PDF文件:")
        file_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        file_select_layout.addWidget(file_label)
        
        # 路径显示和按钮行
        path_btn_layout = QHBoxLayout()
        self.pdf_input_path = QLineEdit()
        self.pdf_input_path.setPlaceholderText("选择要提取的PDF文件（可多选）")
        self.pdf_input_path.setMinimumHeight(40) # 增加高度
        self.pdf_input_path.textChanged.connect(self.on_pdf_path_changed)
        
        pdf_browse_btn = QPushButton("📄 浏览...")
        pdf_browse_btn.setMinimumHeight(40)
        pdf_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pdf_browse_btn.clicked.connect(self.browse_pdf_input)
        
        pdf_add_btn = QPushButton("➕ 添加文件")
        pdf_add_btn.setMinimumHeight(40)
        pdf_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pdf_add_btn.clicked.connect(self.add_pdf_input)
        
        path_btn_layout.addWidget(self.pdf_input_path)
        path_btn_layout.addWidget(pdf_browse_btn)
        path_btn_layout.addWidget(pdf_add_btn)
        
        file_select_layout.addLayout(path_btn_layout)
        scroll_layout.addWidget(file_select_container)
        
        # 2. 已选文件列表
        files_list_container = QWidget()
        files_list_layout = QVBoxLayout(files_list_container)
        files_list_layout.setContentsMargins(0, 0, 0, 0)
        files_list_layout.setSpacing(8)
        
        list_label = QLabel("已选文件列表:")
        list_label.setStyleSheet("font-size: 13px;")
        files_list_layout.addWidget(list_label)
        
        self.pdf_files_list = QListWidget()
        self.pdf_files_list.setMinimumHeight(120) # 增加列表高度
        self.pdf_files_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pdf_files_list.itemDoubleClicked.connect(self.remove_pdf_file)
        self.pdf_files_list.setToolTip("双击移除文件")
        files_list_layout.addWidget(self.pdf_files_list)
        
        scroll_layout.addWidget(files_list_container)
        
        # 3. 预览控制
        preview_container = QWidget()
        preview_layout = QHBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.pdf_preview_btn = QPushButton("👁️ 加载预览")
        self.pdf_preview_btn.setMinimumHeight(40)
        self.pdf_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_preview_btn.clicked.connect(self.load_pdf_preview)
        self.pdf_preview_btn.setEnabled(False)
        
        self.pdf_clear_preview_btn = QPushButton("🗑️ 清除预览")
        self.pdf_clear_preview_btn.setMinimumHeight(40)
        self.pdf_clear_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_clear_preview_btn.clicked.connect(self.clear_pdf_preview)
        self.pdf_clear_preview_btn.setEnabled(False)
        
        preview_layout.addWidget(self.pdf_preview_btn)
        preview_layout.addWidget(self.pdf_clear_preview_btn)
        preview_layout.addStretch()
        
        scroll_layout.addWidget(preview_container)
        
        # 分割线
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        scroll_layout.addWidget(line1)

        # 4. 页码范围设置
        range_container = QWidget()
        range_layout = QVBoxLayout(range_container)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(8)
        
        range_label = QLabel("页码范围:")
        range_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        range_layout.addWidget(range_label)
        
        self.pdf_page_ranges = QLineEdit()
        self.pdf_page_ranges.setMinimumHeight(40)
        self.pdf_page_ranges.setPlaceholderText("例如: 2-6,9,11-12 或点击预览页面选择")
        self.pdf_page_ranges.setToolTip("手动输入页码范围，或通过右侧预览点击选择")
        range_layout.addWidget(self.pdf_page_ranges)
        
        scroll_layout.addWidget(range_container)
        
        # 5. 快捷选择
        quick_select_container = QWidget()
        quick_select_layout = QHBoxLayout(quick_select_container)
        quick_select_layout.setContentsMargins(0, 0, 0, 0)
        
        self.select_all_btn = QPushButton("☑️ 全选")
        self.select_all_btn.setMinimumHeight(40)
        self.select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_btn.clicked.connect(self.select_all_pages)
        self.select_all_btn.setEnabled(False)
        
        self.clear_selection_btn = QPushButton("⬜ 清除选择")
        self.clear_selection_btn.setMinimumHeight(40)
        self.clear_selection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_selection_btn.clicked.connect(self.clear_page_selection)
        self.clear_selection_btn.setEnabled(False)
        
        quick_select_layout.addWidget(self.select_all_btn)
        quick_select_layout.addWidget(self.clear_selection_btn)
        quick_select_layout.addStretch()
        
        scroll_layout.addWidget(quick_select_container)
        
        # 分割线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        scroll_layout.addWidget(line2)
        
        # 6. 输出文件设置
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(8)
        
        output_label = QLabel("输出文件:")
        output_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        output_layout.addWidget(output_label)
        
        output_path_layout = QHBoxLayout()
        self.pdf_output_path = QLineEdit()
        self.pdf_output_path.setMinimumHeight(40)
        self.pdf_output_path.setPlaceholderText("输出PDF文件路径（可选，默认保存到源文件目录）")
        
        pdf_output_btn = QPushButton("📁 浏览...")
        pdf_output_btn.setMinimumHeight(40)
        pdf_output_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pdf_output_btn.clicked.connect(self.browse_pdf_output)
        
        output_path_layout.addWidget(self.pdf_output_path)
        output_path_layout.addWidget(pdf_output_btn)
        output_layout.addLayout(output_path_layout)
        
        scroll_layout.addWidget(output_container)
        
        # 添加弹簧，确保内容靠上
        scroll_layout.addStretch()
        
        # 设置滚动区域内容
        scroll_area.setWidget(scroll_content)
        
        # 将滚动区域添加到左侧布局
        left_layout.addWidget(scroll_area)
        
        # 提取按钮区域（固定在底部）
        action_layout = QHBoxLayout()
        self.pdf_extract_btn = QPushButton("开始提取")
        self.pdf_extract_btn.setMinimumHeight(50) # 进一步加大
        self.pdf_extract_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pdf_extract_btn.setStyleSheet("font-weight: bold; font-size: 15px;")
        self.pdf_extract_btn.clicked.connect(self.start_pdf_extraction)
        action_layout.addWidget(self.pdf_extract_btn)
        
        left_layout.addLayout(action_layout)
        
        # 进度显示（固定在底部）
        progress_group = QGroupBox("处理进度")
        progress_group.setMaximumHeight(150) # 限制进度区域高度
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setContentsMargins(5, 5, 5, 5)
        self.pdf_progress = QTextEdit()
        # self.pdf_progress.setMaximumHeight(100)
        self.pdf_progress.setReadOnly(True)
        progress_layout.addWidget(self.pdf_progress)
        
        left_layout.addWidget(progress_group)
        
        # 右侧：PDF预览面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # 预览标题
        preview_title = QLabel("PDF预览")
        preview_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_title.setStyleSheet("font-size: 14px; font-weight: bold; margin: 5px;")
        right_layout.addWidget(preview_title)
        
        # 预览状态标签
        self.preview_status = QLabel("请选择PDF文件并点击'加载预览'")
        self.preview_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_status.setStyleSheet("color: gray; margin: 5px;")
        right_layout.addWidget(self.preview_status)
        
        # 预览区域
        self.pdf_preview_area = QScrollArea()
        self.pdf_preview_area.setWidgetResizable(True)
        self.pdf_preview_area.setMinimumWidth(300) # 稍微减小最小宽度要求
        
        # 预览内容容器
        self.preview_content = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_content)
        self.preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pdf_preview_area.setWidget(self.preview_content)
        
        right_layout.addWidget(self.pdf_preview_area)
        
        # 添加到分割器
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 550])  # 设置初始比例，左侧稍微宽一点
        
        # 初始化变量
        self.selected_pages = []  # 改为列表，保持选择顺序，每个元素是 (file_path, page_num, order)
        self.page_widgets = {}  # key: (file_path, page_num), value: widget
        self.pdf_files = []  # 存储所有PDF文件路径
        self.preview_workers = []  # 支持多个预览工作线程
        self.selection_order = 0  # 选择顺序计数器
        self.preview_finished_count = 0  # 预览完成计数
        self.preview_success_count = 0  # 预览成功计数
        
        return widget
        
    def on_conversion_type_changed(self):
        """转换类型改变时的处理"""
        conversion_type = self.conversion_type.currentText()
        is_word_to_pdf = conversion_type == "Word转PDF"
        
        # 更新输入路径提示文本
        if is_word_to_pdf:
            self.doc_input_path.setPlaceholderText("选择Word文件或文件夹")
        else:
            self.doc_input_path.setPlaceholderText("选择PDF文件或文件夹")
        
        # 更新覆盖文件选项文本
        if is_word_to_pdf:
            self.doc_overwrite.setText("覆盖已存在的PDF文件")
        else:
            self.doc_overwrite.setText("覆盖已存在的Word文件")
        
        # 控制Word转PDF专用选项的可见性
        for widget in self.word_only_options:
            widget.setVisible(is_word_to_pdf)
        
        # 控制跳过关键词选项的可见性
        for i in range(self.skip_keyword_layout.count()):
            item = self.skip_keyword_layout.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(is_word_to_pdf)
        
        # 清空输入路径
        self.doc_input_path.clear()
            
    def browse_doc_input(self):
        """浏览文档输入路径"""
        from modules.ui.file_dialog_helper import get_file_or_directory
        
        conversion_type = self.conversion_type.currentText()
        is_word_to_pdf = conversion_type == "Word转PDF"
        
        if is_word_to_pdf:
            # Word转PDF：可以选择Word文件或目录
            path = get_file_or_directory(
                self,
                "选择Word文件或文件夹",
                "",
                "所有文件 (*);;Word文档 (*.doc *.docx)"
            )
            if path:
                self.doc_input_path.setText(path)
        else:
            # PDF转Word：可以选择PDF文件或目录
            path = get_file_or_directory(
                self,
                "选择PDF文件或文件夹",
                "",
                "所有文件 (*);;PDF文件 (*.pdf)"
            )
            if path:
                self.doc_input_path.setText(path)
            
    def browse_doc_output(self):
        """浏览文档输出目录"""
        from modules.ui.file_dialog_helper import get_existing_directory
        path = get_existing_directory(self, "选择输出目录")
        if path:
            self.doc_output_dir.setText(path)
            
    def browse_pdf_input(self):
        """浏览PDF输入文件（多选）"""
        from PySide6.QtWidgets import QFileDialog
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择PDF文件（可多选）", "", "PDF文件 (*.pdf);;所有文件 (*)"
        )
        if file_paths:
            for file_path in file_paths:
                if file_path not in self.pdf_files:
                    self.pdf_files.append(file_path)
                    self.pdf_files_list.addItem(Path(file_path).name)
            self.update_pdf_input_display()
            
    def add_pdf_input(self):
        """添加PDF文件"""
        from PySide6.QtWidgets import QFileDialog
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "添加PDF文件", "", "PDF文件 (*.pdf);;所有文件 (*)"
        )
        if file_paths:
            for file_path in file_paths:
                if file_path not in self.pdf_files:
                    self.pdf_files.append(file_path)
                    self.pdf_files_list.addItem(Path(file_path).name)
            self.update_pdf_input_display()
            
    def remove_pdf_file(self, item):
        """移除PDF文件"""
        index = self.pdf_files_list.row(item)
        if 0 <= index < len(self.pdf_files):
            removed_file = self.pdf_files.pop(index)
            self.pdf_files_list.takeItem(index)
            self.update_pdf_input_display()
            # 清除该文件的预览和选择
            self.clear_file_preview(removed_file)
            
    def update_pdf_input_display(self):
        """更新PDF输入显示"""
        if self.pdf_files:
            file_names = [Path(f).name for f in self.pdf_files]
            self.pdf_input_path.setText(f"已选择 {len(self.pdf_files)} 个文件: {', '.join(file_names[:3])}{'...' if len(file_names) > 3 else ''}")
        else:
            self.pdf_input_path.clear()
        # 更新预览按钮状态
        self.pdf_preview_btn.setEnabled(len(self.pdf_files) > 0)
            
    def browse_pdf_output(self):
        """浏览PDF输出文件"""
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存PDF文件", "", "PDF文件 (*.pdf);;所有文件 (*)"
        )
        if file_path:
            self.pdf_output_path.setText(file_path)
            
    def on_pdf_path_changed(self):
        """PDF路径改变时的处理（多文件模式）"""
        # 多文件模式下，这个函数主要用于UI更新
        pass
            
    def load_pdf_preview(self):
        """加载PDF预览（支持多文件）"""
        if not self.pdf_files:
            show_warning(self, "警告", "请先选择PDF文件")
            return
            
        # 停止之前的预览加载
        for worker in self.preview_workers:
            if worker and worker.isRunning():
                worker.stop()
                worker.wait()
        self.preview_workers.clear()
            
        # 清除之前的预览
        self.clear_pdf_preview()
        
        # 更新状态
        self.preview_status.setText(f"正在加载 {len(self.pdf_files)} 个文件的预览...")
        self.pdf_preview_btn.setEnabled(False)
        
        # 重置预览完成计数
        self.preview_finished_count = 0
        self.preview_success_count = 0
        
        # 为每个PDF文件启动预览工作线程
        for pdf_path in self.pdf_files:
            worker = PdfPreviewWorker(pdf_path)
            # 信号已经包含文件路径，直接连接
            worker.page_loaded.connect(self.on_page_loaded)
            worker.preview_finished.connect(self.on_preview_finished)
            
            # 注册线程到主窗口管理器
            parent = self.parent()
            if hasattr(parent, 'register_thread'):
                parent.register_thread(worker)  # type: ignore
            
            self.preview_workers.append(worker)
            worker.start()
        
    def clear_pdf_preview(self):
        """清除PDF预览"""
        # 停止预览加载
        for worker in self.preview_workers:
            if worker and worker.isRunning():
                worker.stop()
                worker.wait()
        self.preview_workers.clear()
            
        # 清除预览内容
        for widget in self.page_widgets.values():
            widget.setParent(None)
        self.page_widgets.clear()
        
        # 重置变量
        self.selected_pages.clear()
        self.selection_order = 0
        self.preview_finished_count = 0
        self.preview_success_count = 0
        
        # 更新UI状态
        self.preview_status.setText("请选择PDF文件并点击'加载预览'")
        self.pdf_clear_preview_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.clear_selection_btn.setEnabled(False)
        
        # 清除页码范围
        self.pdf_page_ranges.clear()
        
    def clear_file_preview(self, file_path: str):
        """清除特定文件的预览"""
        # 移除该文件的所有页面预览
        keys_to_remove = [key for key in self.page_widgets.keys() if key[0] == file_path]
        for key in keys_to_remove:
            widget = self.page_widgets.pop(key)
            widget.setParent(None)
        
        # 移除该文件的所有选择
        self.selected_pages = [p for p in self.selected_pages if p[0] != file_path]
        
        # 更新页码范围
        self.update_page_ranges_text()
        
    def on_page_loaded(self, file_path: str, page_num: int, pixmap: QPixmap, page_info: str):
        """页面加载完成回调（多文件模式）"""
        # 创建页面预览组件
        file_name = Path(file_path).name
        page_widget = self.create_page_preview_widget(file_path, page_num, pixmap, page_info, file_name)
        key = (file_path, page_num)
        self.page_widgets[key] = page_widget
        self.preview_layout.addWidget(page_widget)
        
    def on_preview_finished(self, file_path: str, success: bool, message: str):
        """预览加载完成回调（多文件模式）"""
        # 更新完成计数
        self.preview_finished_count += 1
        if success:
            self.preview_success_count += 1
        
        # 检查是否所有预览都完成了
        if self.preview_finished_count >= len(self.preview_workers):
            self.pdf_preview_btn.setEnabled(True)
            
            if self.preview_success_count == len(self.preview_workers):
                self.preview_status.setText(f"预览加载完成，共 {len(self.page_widgets)} 页")
                self.pdf_clear_preview_btn.setEnabled(True)
                self.select_all_btn.setEnabled(True)
                self.clear_selection_btn.setEnabled(True)
            else:
                failed_count = len(self.preview_workers) - self.preview_success_count
                self.preview_status.setText(f"预览加载完成，{failed_count} 个文件加载失败")
                if not success:
                    show_critical(self, "错误", f"文件 {Path(file_path).name} 预览失败: {message}")
            
    def create_page_preview_widget(self, file_path: str, page_num: int, pixmap: QPixmap, page_info: str, file_name: str) -> QWidget:
        """创建页面预览组件（多文件模式）"""
        widget = QWidget()
        widget.setFixedWidth(350)
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 文件名标签
        file_label = QLabel(f"📄 {file_name}")
        file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_label.setStyleSheet("font-weight: bold; color: #666; font-size: 11px; margin-bottom: 2px;")
        layout.addWidget(file_label)
        
        # 页面信息标签
        info_label = QLabel(page_info)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(info_label)
        
        # 页面图像标签（可点击）
        image_label = QLabel()
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("""
            QLabel {
                border: 2px solid #ccc;
                border-radius: 5px;
                padding: 5px;
                background-color: white;
            }
            QLabel:hover {
                border-color: #007acc;
            }
        """)
        image_label.mousePressEvent = lambda event: self.toggle_page_selection(file_path, page_num)
        # 设置鼠标光标为手形指针
        image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(image_label)
        
        # 选择状态标签
        status_label = QLabel("点击选择此页")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(status_label)
        
        # 存储组件引用 (使用动态属性)
        setattr(widget, 'image_label', image_label)
        setattr(widget, 'status_label', status_label)
        setattr(widget, 'file_path', file_path)
        setattr(widget, 'page_num', page_num)
        
        return widget
        
    def toggle_page_selection(self, file_path: str, page_num: int):
        """切换页面选择状态（多文件模式，保持选择顺序）"""
        key = (file_path, page_num)
        
        # 查找是否已选择
        selected_index = None
        for i, (fp, pn, _) in enumerate(self.selected_pages):
            if fp == file_path and pn == page_num:
                selected_index = i
                break
        
        if selected_index is not None:
            # 取消选择
            self.selected_pages.pop(selected_index)
            self.update_page_widget_style(file_path, page_num, False)
        else:
            # 添加选择（记录选择顺序）
            self.selection_order += 1
            self.selected_pages.append((file_path, page_num, self.selection_order))
            self.update_page_widget_style(file_path, page_num, True)
            
        # 更新页码范围文本
        self.update_page_ranges_text()
        
    def update_page_widget_style(self, file_path: str, page_num: int, selected: bool):
        """更新页面组件样式（多文件模式）"""
        key = (file_path, page_num)
        if key not in self.page_widgets:
            return
            
        widget = self.page_widgets[key]
        image_label = getattr(widget, 'image_label')
        status_label = getattr(widget, 'status_label')
        
        # 查找选择顺序
        order = None
        for fp, pn, o in self.selected_pages:
            if fp == file_path and pn == page_num:
                order = o
                break
        
        if selected and order is not None:
            image_label.setStyleSheet("""
                QLabel {
                    border: 3px solid #007acc;
                    border-radius: 5px;
                    padding: 5px;
                    background-color: #e6f3ff;
                }
                QLabel:hover {
                    border-color: #005999;
                }
            """)
            status_label.setText(f"✓ 已选择 (#{order})")
            status_label.setStyleSheet("color: #007acc; font-size: 12px; font-weight: bold;")
        else:
            image_label.setStyleSheet("""
                QLabel {
                    border: 2px solid #ccc;
                    border-radius: 5px;
                    padding: 5px;
                    background-color: white;
                }
                QLabel:hover {
                    border-color: #007acc;
                }
            """)
            status_label.setText("点击选择此页")
            status_label.setStyleSheet("color: gray; font-size: 12px;")
            
    def update_page_ranges_text(self):
        """更新页码范围文本（多文件模式）"""
        if not self.selected_pages:
            self.pdf_page_ranges.clear()
            return
        
        # 按文件分组显示
        file_groups: Dict[str, List[int]] = {}
        for file_path, page_num, _ in self.selected_pages:
            file_name = Path(file_path).name
            if file_name not in file_groups:
                file_groups[file_name] = []
            file_groups[file_name].append(page_num)
        
        # 为每个文件生成范围文本
        range_texts = []
        for file_name, pages in file_groups.items():
            sorted_pages = sorted(pages)
            ranges = []
            start = sorted_pages[0]
            end = start
            
            for i in range(1, len(sorted_pages)):
                if sorted_pages[i] == end + 1:
                    end = sorted_pages[i]
                else:
                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{end}")
                    start = end = sorted_pages[i]
            
            # 添加最后一个范围
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            
            range_texts.append(f"{file_name}: {','.join(ranges)}")
        
        self.pdf_page_ranges.setText(" | ".join(range_texts))
        
    def select_all_pages(self):
        """选择所有页面（多文件模式）"""
        if not self.page_widgets:
            return
        
        # 按文件分组，每个文件内的页面按页码顺序选择
        file_pages: Dict[str, List[int]] = {}
        for (file_path, page_num) in self.page_widgets.keys():
            if file_path not in file_pages:
                file_pages[file_path] = []
            file_pages[file_path].append(page_num)
        
        # 按文件顺序和页码顺序选择
        for file_path in sorted(file_pages.keys()):
            pages = sorted(file_pages[file_path])
            for page_num in pages:
                key = (file_path, page_num)
                # 检查是否已选择
                already_selected = any(fp == file_path and pn == page_num for fp, pn, _ in self.selected_pages)
                if not already_selected:
                    self.selection_order += 1
                    self.selected_pages.append((file_path, page_num, self.selection_order))
                    self.update_page_widget_style(file_path, page_num, True)
                
        self.update_page_ranges_text()
        
    def clear_page_selection(self):
        """清除页面选择（多文件模式）"""
        for file_path, page_num, _ in list(self.selected_pages):
            self.update_page_widget_style(file_path, page_num, False)
        self.selected_pages.clear()
        self.selection_order = 0
        self.update_page_ranges_text()
            
    def start_document_conversion(self):
        """开始文档转换"""
        input_path = self.doc_input_path.text().strip()
        if not input_path:
            show_warning(self, "警告", "请选择输入路径")
            return
            
        if not Path(input_path).exists():
            show_warning(self, "警告", "输入路径不存在")
            return
        
        # 获取转换类型
        conversion_type = "word_to_pdf" if self.conversion_type.currentText() == "Word转PDF" else "pdf_to_word"
        
        # 获取输入文件列表
        input_files = []
        input_path_obj = Path(input_path)
        
        if input_path_obj.is_file():
            input_files = [input_path]
        else:
            # 目录模式
            if conversion_type == "word_to_pdf":
                patterns = ["*.doc", "*.docx"]
            else:
                patterns = ["*.pdf"]
            
            for pattern in patterns:
                if self.doc_recursive.isChecked() and conversion_type == "word_to_pdf":
                    _found = list(input_path_obj.rglob(pattern))
                else:
                    _found = list(input_path_obj.glob(pattern))
                # 过滤掉Word临时文件（以~$开头的文件）
                _found = [p for p in _found if not p.name.startswith("~$")]
                input_files.extend([str(p) for p in _found])
        
        if not input_files:
            file_type = "Word" if conversion_type == "word_to_pdf" else "PDF"
            show_warning(self, "警告", f"在指定路径中未找到{file_type}文件")
            return
        
        # 输出目录
        output_dir_text = self.doc_output_dir.text().strip()
        output_dir = output_dir_text if output_dir_text else None
        
        # 构建选项
        options = {
            'overwrite': self.doc_overwrite.isChecked(),
        }
        
        if conversion_type == "word_to_pdf":
            options.update({
                'recursive': self.doc_recursive.isChecked(),
                'skip_template': self.doc_skip_template.isChecked(),
            })
            
            # 跳过关键词
            skip_keywords = self.doc_skip_keywords.text().strip()
            if skip_keywords:
                skip_keyword_list = [kw.strip() for kw in skip_keywords.split(',') if kw.strip()]
                if skip_keyword_list:
                    # 确保类型正确
                    from typing import cast, Any
                    options_dict = cast(dict[str, Any], options)
                    options_dict['skip_keywords'] = skip_keyword_list
        
        # 禁用按钮并显示进度
        self.doc_convert_btn.setEnabled(False)
        self.doc_progress.clear()
        self.doc_progress_bar.setValue(0)
        self.doc_progress_bar.setVisible(True)
        
        conversion_name = "Word转PDF" if conversion_type == "word_to_pdf" else "PDF转Word"
        self.doc_progress.append(f"🚀 开始{conversion_name}转换...")
        self.doc_progress.append(f"📁 找到 {len(input_files)} 个文件")
        
        # 启动工作线程
        self.doc_worker = DocumentConversionWorker(conversion_type, input_files, output_dir, **options)
        # 不连接详细进度输出，只连接进度条更新
        # self.doc_worker.progress_updated.connect(self.doc_progress.append)
        self.doc_worker.progress_percentage.connect(self.doc_progress_bar.setValue)
        self.doc_worker.finished_signal.connect(self.on_document_conversion_finished)
        
        # 注册线程到主窗口管理器
        parent = self.parent()
        if hasattr(parent, 'register_thread'):
            parent.register_thread(self.doc_worker)  # type: ignore
        
        self.doc_worker.start()
        
    def start_pdf_extraction(self):
        """开始PDF页面提取（支持多文件合并）"""
        if not self.selected_pages:
            show_warning(self, "警告", "请先选择要提取的页面")
            return
        
        # 输出文件
        output_path = self.pdf_output_path.text().strip()
        if not output_path:
            # 生成默认输出文件名
            if len(self.pdf_files) == 1:
                # 单文件模式：从selected_pages提取纯页码格式用于生成默认文件名
                from modules.Document_Processing.pdf_extract import build_default_output_path
                input_path = Path(self.pdf_files[0])
                
                # 提取纯页码范围（不含文件名）用于文件名生成
                page_nums = sorted([pn for _, pn, _ in self.selected_pages])
                if page_nums:
                    # 生成简洁的范围字符串
                    ranges = []
                    start = page_nums[0]
                    end = start
                    for i in range(1, len(page_nums)):
                        if page_nums[i] == end + 1:
                            end = page_nums[i]
                        else:
                            if start == end:
                                ranges.append(str(start))
                            else:
                                ranges.append(f"{start}-{end}")
                            start = end = page_nums[i]
                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{end}")
                    page_ranges_for_filename = ",".join(ranges)
                else:
                    page_ranges_for_filename = "all"
                
                output_path = str(build_default_output_path(input_path, page_ranges_for_filename))
            else:
                # 多文件模式
                output_path = str(Path(self.pdf_files[0]).parent / "merged_pages.pdf")
        
        # 检查是单文件还是多文件模式
        if len(self.pdf_files) == 1 and len(set(fp for fp, _, _ in self.selected_pages)) == 1:
            # 单文件模式，使用原来的提取逻辑
            input_path = self.pdf_files[0]
            
            # 从selected_pages中提取纯页码范围字符串（不包含文件名）
            # 因为update_page_ranges_text()会生成"文件名: 页码"格式，但命令行脚本只接受纯页码格式
            page_nums = sorted([pn for _, pn, _ in self.selected_pages])
            
            # 将页码列表转换为范围字符串（如 1,2,3,5,6 -> "1-3,5-6"）
            ranges = []
            if page_nums:
                start = page_nums[0]
                end = start
                for i in range(1, len(page_nums)):
                    if page_nums[i] == end + 1:
                        end = page_nums[i]
                    else:
                        if start == end:
                            ranges.append(str(start))
                        else:
                            ranges.append(f"{start}-{end}")
                        start = end = page_nums[i]
                # 添加最后一个范围
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
            
            page_ranges = ",".join(ranges)
            
            if not Path(input_path).exists():
                show_warning(self, "警告", "PDF文件不存在")
                return
            
            # 禁用按钮
            self.pdf_extract_btn.setEnabled(False)
            self.pdf_progress.clear()
            self.pdf_progress.append("开始提取...")
            
            # 启动工作线程（使用直接函数调用方式）
            self.pdf_worker = PdfExtractWorker(
                'single',
                input_path=input_path,
                output_path=output_path,
                page_numbers=page_nums
            )
            self.pdf_worker.progress_updated.connect(self.pdf_progress.append)
            self.pdf_worker.finished_signal.connect(self.on_pdf_extraction_finished)
            
            # 注册线程到主窗口管理器
            parent = self.parent()
            if hasattr(parent, 'register_thread'):
                parent.register_thread(self.pdf_worker)  # type: ignore
            
            self.pdf_worker.start()
        else:
            # 多文件合并模式
            
            # 准备页面选择数据
            page_selections = []
            for file_path, page_num, order in self.selected_pages:
                page_selections.append({
                    'file_path': file_path,
                    'page_num': page_num,
                    'order': order
                })
            
            # 禁用按钮
            self.pdf_extract_btn.setEnabled(False)
            self.pdf_progress.clear()
            self.pdf_progress.append(f"开始合并 {len(page_selections)} 页（来自 {len(set(fp for fp, _, _ in self.selected_pages))} 个文件）...")
            
            # 启动工作线程（使用直接函数调用方式）
            self.pdf_worker = PdfExtractWorker(
                'merge',
                page_selections=page_selections,
                output_path=output_path
            )
            self.pdf_worker.progress_updated.connect(self.pdf_progress.append)
            self.pdf_worker.finished_signal.connect(self.on_pdf_extraction_finished)
            
            # 注册线程到主窗口管理器
            parent = self.parent()
            if hasattr(parent, 'register_thread'):
                parent.register_thread(self.pdf_worker)  # type: ignore
            
            self.pdf_worker.start()
        
    def on_document_conversion_finished(self, success: bool, message: str):
        """文档转换完成回调"""
        self.doc_convert_btn.setEnabled(True)
        
        # 清除进度框内容，只显示最终结果
        self.doc_progress.clear()
        
        if success:
            self.doc_progress_bar.setValue(100)
            self.doc_progress.append(f"✅ {message}")
        else:
            self.doc_progress.append(f"❌ {message}")
        
        conversion_name = "Word转PDF" if self.conversion_type.currentText() == "Word转PDF" else "PDF转Word"
        
        if success:
            show_information(self, "转换成功", f"🎉 {conversion_name}转换完成！")
        else:
            show_critical(self, "转换失败", f"❌ 转换失败：{message}")
            
        # 3秒后隐藏进度条
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self.doc_progress_bar.setVisible(False))
            
    def on_pdf_extraction_finished(self, success: bool, message: str):
        """PDF提取完成回调"""
        self.pdf_extract_btn.setEnabled(True)
        self.pdf_progress.append(f"\n{message}")
        
        if success:
            show_information(self, "成功", "PDF页面提取完成！")
        else:
            show_critical(self, "错误", f"提取失败：{message}")
