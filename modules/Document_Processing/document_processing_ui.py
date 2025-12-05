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
from typing import Optional, List

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
    QListWidget, QListWidgetItem, QAbstractItemView
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
    """PDF预览工作线程"""
    page_loaded = Signal(int, QPixmap, str)  # 页码, 图像, 页面信息
    preview_finished = Signal(bool, str)
    
    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.should_stop = False
    
    def stop(self):
        """停止预览加载"""
        self.should_stop = True
    
    def run(self):
        try:
            # 尝试导入PyMuPDF
            try:
                import fitz  # PyMuPDF
            except ImportError:
                self.preview_finished.emit(False, "未安装 PyMuPDF，请先安装：pip install PyMuPDF")
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
                
                # 发送信号
                self.page_loaded.emit(page_num + 1, pixmap, page_info)
            
            pdf_document.close()
            self.preview_finished.emit(True, f"预览加载完成，共 {total_pages} 页")
            
        except Exception as e:
            self.preview_finished.emit(False, f"预览加载失败: {str(e)}")


class PdfExtractWorker(QThread):
    """PDF页面提取工作线程"""
    progress_updated = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, script_path: str, args: list):
        super().__init__()
        self.script_path = script_path
        self.args = args
    
    def run(self):
        try:
            # 构建命令
            cmd = [sys.executable, self.script_path] + self.args
            
            # 执行提取
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'  # 忽略编码错误
            )
            
            stdout_output, stderr_output = process.communicate()
            
            if process.returncode == 0:
                self.progress_updated.emit(stdout_output)
                self.finished_signal.emit(True, "提取完成")
            else:
                error_msg = stderr_output if stderr_output else f"提取失败，返回码: {process.returncode}"
                self.finished_signal.emit(False, error_msg)
                
        except Exception as e:
            self.finished_signal.emit(False, f"执行错误: {str(e)}")


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
        left_panel.setMaximumWidth(400)
        
        # 输入设置组
        input_group = QGroupBox("输入设置")
        input_layout = QFormLayout(input_group)
        
        # PDF文件路径
        self.pdf_input_path = QLineEdit()
        self.pdf_input_path.setPlaceholderText("选择要提取的PDF文件")
        self.pdf_input_path.textChanged.connect(self.on_pdf_path_changed)
        pdf_browse_btn = QPushButton("📄 浏览...")
        pdf_browse_btn.clicked.connect(self.browse_pdf_input)
        
        pdf_input_layout = QHBoxLayout()
        pdf_input_layout.addWidget(self.pdf_input_path)
        pdf_input_layout.addWidget(pdf_browse_btn)
        input_layout.addRow("PDF文件:", pdf_input_layout)
        
        # 预览控制按钮
        preview_btn_layout = QHBoxLayout()
        self.pdf_preview_btn = QPushButton("👁️ 加载预览")
        self.pdf_preview_btn.clicked.connect(self.load_pdf_preview)
        self.pdf_preview_btn.setEnabled(False)
        
        self.pdf_clear_preview_btn = QPushButton("🗑️ 清除预览")
        self.pdf_clear_preview_btn.clicked.connect(self.clear_pdf_preview)
        self.pdf_clear_preview_btn.setEnabled(False)
        
        preview_btn_layout.addWidget(self.pdf_preview_btn)
        preview_btn_layout.addWidget(self.pdf_clear_preview_btn)
        input_layout.addRow("预览控制:", preview_btn_layout)
        
        # 页码范围
        self.pdf_page_ranges = QLineEdit()
        self.pdf_page_ranges.setPlaceholderText("例如: 2-6,9,11-12 或点击预览页面选择")
        input_layout.addRow("页码范围:", self.pdf_page_ranges)
        
        # 快捷选择按钮
        quick_select_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("☑️ 全选")
        self.select_all_btn.clicked.connect(self.select_all_pages)
        self.select_all_btn.setEnabled(False)
        
        self.clear_selection_btn = QPushButton("⬜ 清除选择")
        self.clear_selection_btn.clicked.connect(self.clear_page_selection)
        self.clear_selection_btn.setEnabled(False)
        
        quick_select_layout.addWidget(self.select_all_btn)
        quick_select_layout.addWidget(self.clear_selection_btn)
        input_layout.addRow("快捷选择:", quick_select_layout)
        
        # 输出文件
        self.pdf_output_path = QLineEdit()
        self.pdf_output_path.setPlaceholderText("输出PDF文件路径（可选）")
        pdf_output_btn = QPushButton("📁 浏览...")
        pdf_output_btn.clicked.connect(self.browse_pdf_output)
        
        pdf_output_layout = QHBoxLayout()
        pdf_output_layout.addWidget(self.pdf_output_path)
        pdf_output_layout.addWidget(pdf_output_btn)
        input_layout.addRow("输出文件:", pdf_output_layout)
        
        left_layout.addWidget(input_group)
        
        # 提取按钮
        self.pdf_extract_btn = QPushButton("开始提取")
        self.pdf_extract_btn.clicked.connect(self.start_pdf_extraction)
        left_layout.addWidget(self.pdf_extract_btn)
        
        # 进度显示
        self.pdf_progress = QTextEdit()
        self.pdf_progress.setMaximumHeight(150)
        self.pdf_progress.setReadOnly(True)
        left_layout.addWidget(self.pdf_progress)
        
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
        self.pdf_preview_area.setMinimumWidth(400)
        
        # 预览内容容器
        self.preview_content = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_content)
        self.preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pdf_preview_area.setWidget(self.preview_content)
        
        right_layout.addWidget(self.pdf_preview_area)
        
        # 添加到分割器
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])  # 设置初始比例
        
        # 初始化变量
        self.selected_pages = set()
        self.page_widgets = {}
        self.total_pages = 0
        self.preview_worker = None
        
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
        """浏览PDF输入文件"""
        from modules.ui.file_dialog_helper import get_open_file_name
        file_path, _ = get_open_file_name(
            self, "选择PDF文件", "", "PDF文件 (*.pdf);;所有文件 (*)"
        )
        if file_path:
            self.pdf_input_path.setText(file_path)
            
    def browse_pdf_output(self):
        """浏览PDF输出文件"""
        from modules.ui.file_dialog_helper import get_save_file_name
        file_path, _ = get_save_file_name(
            self, "保存PDF文件", "", "PDF文件 (*.pdf);;所有文件 (*)"
        )
        if file_path:
            self.pdf_output_path.setText(file_path)
            
    def on_pdf_path_changed(self):
        """PDF路径改变时的处理"""
        pdf_path = self.pdf_input_path.text().strip()
        has_valid_path = bool(pdf_path and Path(pdf_path).exists() and pdf_path.lower().endswith('.pdf'))
        
        # 启用/禁用预览按钮
        self.pdf_preview_btn.setEnabled(has_valid_path)
        
        # 如果路径无效，清除预览
        if not has_valid_path:
            self.clear_pdf_preview()
            
    def load_pdf_preview(self):
        """加载PDF预览"""
        pdf_path = self.pdf_input_path.text().strip()
        if not pdf_path or not Path(pdf_path).exists():
            show_warning(self, "警告", "请选择有效的PDF文件")
            return
            
        # 停止之前的预览加载
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.stop()
            self.preview_worker.wait()
            
        # 清除之前的预览
        self.clear_pdf_preview()
        
        # 更新状态
        self.preview_status.setText("正在加载预览...")
        self.pdf_preview_btn.setEnabled(False)
        
        # 启动预览工作线程
        self.preview_worker = PdfPreviewWorker(pdf_path)
        self.preview_worker.page_loaded.connect(self.on_page_loaded)
        self.preview_worker.preview_finished.connect(self.on_preview_finished)
        
        # 注册线程到主窗口管理器
        parent = self.parent()
        if hasattr(parent, 'register_thread'):
            parent.register_thread(self.preview_worker)  # type: ignore
        
        self.preview_worker.start()
        
    def clear_pdf_preview(self):
        """清除PDF预览"""
        # 停止预览加载
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.stop()
            self.preview_worker.wait()
            
        # 清除预览内容
        for widget in self.page_widgets.values():
            widget.setParent(None)
        self.page_widgets.clear()
        
        # 重置变量
        self.selected_pages.clear()
        self.total_pages = 0
        
        # 更新UI状态
        self.preview_status.setText("请选择PDF文件并点击'加载预览'")
        self.pdf_clear_preview_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.clear_selection_btn.setEnabled(False)
        
        # 清除页码范围
        self.pdf_page_ranges.clear()
        
    def on_page_loaded(self, page_num: int, pixmap: QPixmap, page_info: str):
        """页面加载完成回调"""
        # 创建页面预览组件
        page_widget = self.create_page_preview_widget(page_num, pixmap, page_info)
        self.page_widgets[page_num] = page_widget
        self.preview_layout.addWidget(page_widget)
        
        # 更新总页数
        self.total_pages = max(self.total_pages, page_num)
        
    def on_preview_finished(self, success: bool, message: str):
        """预览加载完成回调"""
        self.pdf_preview_btn.setEnabled(True)
        
        if success:
            self.preview_status.setText(message)
            self.pdf_clear_preview_btn.setEnabled(True)
            self.select_all_btn.setEnabled(True)
            self.clear_selection_btn.setEnabled(True)
        else:
            self.preview_status.setText(f"预览加载失败: {message}")
            show_critical(self, "错误", message)
            
    def create_page_preview_widget(self, page_num: int, pixmap: QPixmap, page_info: str) -> QWidget:
        """创建页面预览组件"""
        widget = QWidget()
        widget.setFixedWidth(350)
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
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
        image_label.mousePressEvent = lambda event: self.toggle_page_selection(page_num)
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
        setattr(widget, 'page_num', page_num)
        
        return widget
        
    def toggle_page_selection(self, page_num: int):
        """切换页面选择状态"""
        if page_num in self.selected_pages:
            self.selected_pages.remove(page_num)
            self.update_page_widget_style(page_num, False)
        else:
            self.selected_pages.add(page_num)
            self.update_page_widget_style(page_num, True)
            
        # 更新页码范围文本
        self.update_page_ranges_text()
        
    def update_page_widget_style(self, page_num: int, selected: bool):
        """更新页面组件样式"""
        if page_num not in self.page_widgets:
            return
            
        widget = self.page_widgets[page_num]
        image_label = getattr(widget, 'image_label')
        status_label = getattr(widget, 'status_label')
        
        if selected:
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
            status_label.setText("✓ 已选择")
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
        """更新页码范围文本"""
        if not self.selected_pages:
            self.pdf_page_ranges.clear()
            return
            
        # 将选中的页码排序并转换为范围格式
        sorted_pages = sorted(self.selected_pages)
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
            
        self.pdf_page_ranges.setText(",".join(ranges))
        
    def select_all_pages(self):
        """选择所有页面"""
        if self.total_pages == 0:
            return
            
        for page_num in range(1, self.total_pages + 1):
            if page_num not in self.selected_pages:
                self.selected_pages.add(page_num)
                self.update_page_widget_style(page_num, True)
                
        self.update_page_ranges_text()
        
    def clear_page_selection(self):
        """清除页面选择"""
        for page_num in list(self.selected_pages):
            self.selected_pages.remove(page_num)
            self.update_page_widget_style(page_num, False)
            
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
                    input_files.extend([str(p) for p in input_path_obj.rglob(pattern)])
                else:
                    input_files.extend([str(p) for p in input_path_obj.glob(pattern)])
        
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
        """开始PDF页面提取"""
        input_path = self.pdf_input_path.text().strip()
        page_ranges = self.pdf_page_ranges.text().strip()
        
        if not input_path:
            show_warning(self, "警告", "请选择PDF文件")
            return
            
        if not page_ranges:
            show_warning(self, "警告", "请输入页码范围")
            return
            
        if not Path(input_path).exists():
            show_warning(self, "警告", "PDF文件不存在")
            return
            
        # 构建参数
        args = [input_path, page_ranges]
        
        # 输出文件
        output_path = self.pdf_output_path.text().strip()
        if output_path:
            args.extend(["-o", output_path])
        
        # 禁用按钮
        self.pdf_extract_btn.setEnabled(False)
        self.pdf_progress.clear()
        self.pdf_progress.append("开始提取...")
        
        # 启动工作线程
        self.pdf_worker = PdfExtractWorker(str(self.pdf_extract_script), args)
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
