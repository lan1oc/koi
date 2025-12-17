#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件对话框辅助模块

提供统一的文件对话框创建和配置，包括：
- 暗色模式支持
- 可编辑地址栏
- 回车键导航功能
"""

from pathlib import Path
from typing import Optional, Tuple, List
from PySide6.QtWidgets import QFileDialog, QComboBox, QWidget, QPushButton, QHBoxLayout, QLabel, QVBoxLayout
from PySide6.QtCore import Qt


def _apply_file_dialog_style(dialog: QFileDialog):
    """
    应用文件对话框样式
    
    由于 QFileDialog 作为顶层窗口不会自动继承 QApplication 的样式表，
    需要手动应用样式以符合当前颜色模式
    """
    from modules.ui.styles.theme_manager import ThemeManager
    theme_manager = ThemeManager()
    
    if theme_manager._dark_mode:
        # 暗色模式样式
        dialog.setStyleSheet("""
            QFileDialog {
                background-color: #1e1e1e;
                color: #f0f0f0;
            }
            QFileDialog QWidget {
                background-color: #1e1e1e !important;
                color: #f0f0f0 !important;
            }
            QFileDialog QListView, QFileDialog QTreeView {
                background-color: #2d2d2d !important;
                color: #f0f0f0 !important;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                selection-background-color: #483d8b;
                selection-color: #ffffff;
            }
            QFileDialog QListView::item, QFileDialog QTreeView::item {
                color: #f0f0f0 !important;
                padding: 8px;
            }
            QFileDialog QListView::item:hover, QFileDialog QTreeView::item:hover {
                background-color: #3d3d3d;
            }
            QFileDialog QListView::item:selected, QFileDialog QTreeView::item:selected {
                background-color: #483d8b;
                color: #ffffff;
            }
            QFileDialog QHeaderView {
                background-color: #2d2d2d;
                color: #f0f0f0;
            }
            QFileDialog QHeaderView::section {
                background-color: #2d2d2d;
                color: #f0f0f0;
                padding: 6px;
                border: 1px solid #3d3d3d;
            }
            QFileDialog QSidebar {
                background-color: #2d2d2d !important;
                color: #f0f0f0 !important;
            }
            QFileDialog QLineEdit {
                background-color: #252525 !important;
                color: #f0f0f0 !important;
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QLineEdit:focus {
                border: 2px solid #bb86fc;
            }
            QFileDialog QComboBox {
                background-color: #252525 !important;
                color: #f0f0f0 !important;
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QComboBox:hover {
                border: 1px solid #bb86fc;
            }
            QFileDialog QComboBox QAbstractItemView {
                background-color: #2d2d2d !important;
                color: #f0f0f0 !important;
                selection-background-color: #483d8b;
                selection-color: #ffffff;
            }
            QFileDialog QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d3d, stop:1 #2d2d2d);
                color: #f0f0f0 !important;
                border: 1px solid #505050;
                border-radius: 6px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QFileDialog QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #505050, stop:1 #3d3d3d);
                border: 1px solid #bb86fc;
            }
            QFileDialog QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d2d2d, stop:1 #3d3d3d);
            }
            QFileDialog QLabel {
                color: #f0f0f0 !important;
                background-color: transparent !important;
            }
            QFileDialog QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:vertical {
                background-color: #505050;
                border-radius: 6px;
                min-height: 20px;
            }
            QFileDialog QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }
            QFileDialog QScrollBar:horizontal {
                background-color: #2d2d2d;
                height: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:horizontal {
                background-color: #505050;
                border-radius: 6px;
                min-width: 20px;
            }
            QFileDialog QScrollBar::handle:horizontal:hover {
                background-color: #666666;
            }
        """)
    else:
        # 亮色模式样式
        dialog.setStyleSheet("""
            QFileDialog {
                background-color: #ffffff;
                color: #343a40;
            }
            QFileDialog QWidget {
                background-color: #ffffff !important;
                color: #343a40 !important;
            }
            QFileDialog QListView, QFileDialog QTreeView {
                background-color: #ffffff !important;
                color: #343a40 !important;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                selection-background-color: #007bff;
                selection-color: #ffffff;
            }
            QFileDialog QListView::item, QFileDialog QTreeView::item {
                color: #343a40 !important;
                padding: 8px;
            }
            QFileDialog QListView::item:hover, QFileDialog QTreeView::item:hover {
                background-color: #f8f9fa;
            }
            QFileDialog QListView::item:selected, QFileDialog QTreeView::item:selected {
                background-color: #007bff;
                color: #ffffff;
            }
            QFileDialog QHeaderView {
                background-color: #f8f9fa;
                color: #343a40;
            }
            QFileDialog QHeaderView::section {
                background-color: #f8f9fa;
                color: #343a40;
                padding: 6px;
                border: 1px solid #dee2e6;
            }
            QFileDialog QSidebar {
                background-color: #f8f9fa !important;
                color: #343a40 !important;
            }
            QFileDialog QLineEdit {
                background-color: #ffffff !important;
                color: #343a40 !important;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QLineEdit:focus {
                border: 2px solid #007bff;
            }
            QFileDialog QComboBox {
                background-color: #ffffff !important;
                color: #343a40 !important;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
            }
            QFileDialog QComboBox:hover {
                border: 1px solid #007bff;
            }
            QFileDialog QComboBox QAbstractItemView {
                background-color: #ffffff !important;
                color: #343a40 !important;
                selection-background-color: #007bff;
                selection-color: #ffffff;
            }
            QFileDialog QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                color: #343a40 !important;
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QFileDialog QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border: 1px solid #007bff;
            }
            QFileDialog QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dee2e6, stop:1 #ced4da);
            }
            QFileDialog QLabel {
                color: #343a40 !important;
                background-color: transparent !important;
            }
            QFileDialog QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:vertical {
                background-color: #ced4da;
                border-radius: 6px;
                min-height: 20px;
            }
            QFileDialog QScrollBar::handle:vertical:hover {
                background-color: #adb5bd;
            }
            QFileDialog QScrollBar:horizontal {
                background-color: #f8f9fa;
                height: 12px;
                border-radius: 6px;
            }
            QFileDialog QScrollBar::handle:horizontal {
                background-color: #ced4da;
                border-radius: 6px;
                min-width: 20px;
            }
            QFileDialog QScrollBar::handle:horizontal:hover {
                background-color: #adb5bd;
            }
        """)


def _add_mode_selector(dialog: QFileDialog, default_mode: str = "文件", is_save_dialog: bool = False):
    """
    添加模式选择下拉框（目录/文件）
    
    在文件对话框的文件类型过滤器上方添加一个下拉框，用于选择"文件"或"目录"模式
    
    Args:
        dialog: QFileDialog实例
        default_mode: 默认模式，"文件"或"目录"，默认为"文件"
        is_save_dialog: 是否为保存对话框，保存对话框使用AnyFile模式
    """
    # 创建模式选择下拉框
    mode_combo = QComboBox()
    mode_combo.addItems(["文件", "目录"])
    mode_combo.setCurrentText(default_mode)  # 使用指定的默认模式
    mode_combo.setMinimumWidth(100)
    
    # 设置样式
    from modules.ui.styles.theme_manager import ThemeManager
    theme_manager = ThemeManager()
    if theme_manager._dark_mode:
        mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #252525 !important;
                color: #f0f0f0 !important;
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 6px;
                min-width: 100px;
            }
            QComboBox:hover {
                border: 1px solid #bb86fc;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d !important;
                color: #f0f0f0 !important;
                selection-background-color: #483d8b;
                selection-color: #ffffff;
            }
        """)
    else:
        mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #ffffff !important;
                color: #343a40 !important;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                min-width: 100px;
            }
            QComboBox:hover {
                border: 1px solid #007bff;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff !important;
                color: #343a40 !important;
                selection-background-color: #007bff;
                selection-color: #ffffff;
            }
        """)
    
    # 创建标签
    mode_label = QLabel("选择类型:")
    if theme_manager._dark_mode:
        mode_label.setStyleSheet("color: #f0f0f0;")
    else:
        mode_label.setStyleSheet("color: #343a40;")
    
    # 查找文件类型过滤器标签，在其上方添加模式选择器
    labels = dialog.findChildren(QLabel)
    filter_label = None
    for label in labels:
        text = label.text()
        if "文件类型" in text or "Files of type" in text or "Name:" in text:
            filter_label = label
            break
    
    # 定义模式切换函数
    def on_mode_changed(mode: str):
        if mode == "目录":
            # 目录模式：只显示目录，只能选择目录
            dialog.setFileMode(QFileDialog.FileMode.Directory)
            dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        else:  # 文件
            # 文件模式：显示文件和目录
            # 保存对话框使用AnyFile模式（允许输入新文件名）
            # 打开对话框使用ExistingFile模式（只能选择已有文件）
            if is_save_dialog:
                dialog.setFileMode(QFileDialog.FileMode.AnyFile)
            else:
                dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
    
    # 连接信号
    mode_combo.currentTextChanged.connect(on_mode_changed)
    # 初始化模式
    on_mode_changed(default_mode)
    
    # 在文件类型过滤器附近添加模式选择器
    # 由于QFileDialog的布局比较复杂，我们创建一个容器widget来放置模式选择器
    # 然后尝试将其添加到对话框的合适位置
    mode_container = QWidget()
    mode_container_layout = QHBoxLayout(mode_container)
    mode_container_layout.setContentsMargins(0, 0, 0, 0)
    mode_container_layout.addWidget(mode_label)
    mode_container_layout.addWidget(mode_combo)
    mode_container_layout.addStretch()
    
    # 尝试将模式选择器添加到文件类型过滤器附近
    # 查找文件类型过滤器的父容器
    if filter_label:
        parent = filter_label.parent()
        if parent and isinstance(parent, QWidget):
            parent_layout = parent.layout()
            if parent_layout:
                try:
                    # 尝试在文件类型过滤器之前添加
                    # 找到filter_label在布局中的位置
                    for i in range(parent_layout.count()):
                        item = parent_layout.itemAt(i)
                        if item and item.widget() == filter_label:
                            # 尝试插入模式选择器
                            try:
                                if hasattr(parent_layout, 'insertWidget'):
                                    parent_layout.insertWidget(i, mode_container)  # type: ignore
                                else:
                                    parent_layout.addWidget(mode_container)  # type: ignore
                            except Exception:
                                # 如果无法插入，尝试添加到末尾
                                try:
                                    parent_layout.addWidget(mode_container)  # type: ignore
                                except Exception:
                                    pass
                            break
                    else:
                        # 如果没找到，尝试添加到末尾
                        try:
                            parent_layout.addWidget(mode_container)  # type: ignore
                        except Exception:
                            pass
                except Exception:
                    pass
    
    return mode_combo


def setup_file_dialog_features(dialog: QFileDialog, allow_directory: bool = False, default_mode: str = "文件", is_save_dialog: bool = False):
    """
    为文件对话框设置所有增强功能
    
    Args:
        dialog: QFileDialog实例
        allow_directory: 是否允许选择目录模式（添加目录/文件下拉框）
        default_mode: 默认模式，"文件"或"目录"，默认为"文件"
        is_save_dialog: 是否为保存对话框，保存对话框使用AnyFile模式
    """
    # 应用主题样式
    _apply_file_dialog_style(dialog)
    
    # 添加模式选择器（如果需要）
    mode_combo = None
    if allow_directory:
        mode_combo = _add_mode_selector(dialog, default_mode, is_save_dialog)
    
    # 启用可编辑地址栏
    combo_boxes = dialog.findChildren(QComboBox)
    for combo in combo_boxes:
        # 跳过模式选择器
        if combo == mode_combo:
            continue
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        
        # 绑定回车键导航功能
        line_edit = combo.lineEdit()
        if line_edit:
            # 使用lambda捕获当前combo和dialog实例
            line_edit.returnPressed.connect(
                lambda c=combo, d=dialog: _navigate_to_path(c, d)
            )


def _navigate_to_path(combo: QComboBox, dialog: QFileDialog):
    """
    导航到组合框中输入的路径
    
    Args:
        combo: QComboBox实例
        dialog: QFileDialog实例
    """
    path_text = combo.currentText().strip()
    if path_text:
        path = Path(path_text)
        # 如果路径存在，跳转到该路径
        if path.exists():
            if path.is_dir():
                dialog.setDirectory(str(path))
            else:
                # 如果是文件，跳转到其父目录并选中该文件
                dialog.setDirectory(str(path.parent))
                dialog.selectFile(str(path))
        else:
            # 路径不存在，尝试跳转到最接近的存在的父目录
            parent = path.parent
            while parent and not parent.exists():
                parent = parent.parent
            if parent and parent.exists():
                dialog.setDirectory(str(parent))


def get_open_file_name(
    parent: Optional[QWidget] = None,
    caption: str = "",
    directory: str = "",
    filter: str = "",
    selected_filter: str = ""
) -> Tuple[str, str]:
    """
    显示打开文件对话框（替代QFileDialog.getOpenFileName）
    
    自动应用暗色模式、可编辑地址栏和回车导航功能
    
    Args:
        parent: 父窗口
        caption: 对话框标题
        directory: 初始目录
        filter: 文件过滤器
        selected_filter: 默认选中的过滤器
        
    Returns:
        (选中的文件路径, 使用的过滤器)
    """
    dialog = QFileDialog(parent)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setWindowTitle(caption)
    dialog.setDirectory(directory)
    dialog.setNameFilter(filter)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    
    # 应用增强功能（添加选择类型功能）
    setup_file_dialog_features(dialog, allow_directory=True, default_mode="文件")
    
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0], dialog.selectedNameFilter()
    
    return "", ""


def get_open_file_names(
    parent: Optional[QWidget] = None,
    caption: str = "",
    directory: str = "",
    filter: str = "",
    selected_filter: str = ""
) -> Tuple[List[str], str]:
    """
    显示打开多个文件对话框（替代QFileDialog.getOpenFileNames）
    
    自动应用暗色模式、可编辑地址栏和回车导航功能
    
    Args:
        parent: 父窗口
        caption: 对话框标题
        directory: 初始目录
        filter: 文件过滤器
        selected_filter: 默认选中的过滤器
        
    Returns:
        (选中的文件路径列表, 使用的过滤器)
    """
    dialog = QFileDialog(parent)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setWindowTitle(caption)
    dialog.setDirectory(directory)
    dialog.setNameFilter(filter)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    
    # 应用增强功能（添加选择类型功能）
    setup_file_dialog_features(dialog, allow_directory=True, default_mode="文件")
    
    if dialog.exec():
        return dialog.selectedFiles(), dialog.selectedNameFilter()
    
    return [], ""


def get_save_file_name(
    parent: Optional[QWidget] = None,
    caption: str = "",
    directory: str = "",
    filter: str = "",
    selected_filter: str = ""
) -> Tuple[str, str]:
    """
    显示保存文件对话框（替代QFileDialog.getSaveFileName）
    
    自动应用暗色模式、可编辑地址栏和回车导航功能
    
    Args:
        parent: 父窗口
        caption: 对话框标题
        directory: 初始目录/文件名
        filter: 文件过滤器
        selected_filter: 默认选中的过滤器
        
    Returns:
        (选中的文件路径, 使用的过滤器)
    """
    dialog = QFileDialog(parent)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setWindowTitle(caption)
    dialog.setDirectory(directory)
    dialog.setNameFilter(filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    
    if selected_filter:
        dialog.selectNameFilter(selected_filter)
    
    # 应用增强功能（添加选择类型功能，标记为保存对话框）
    setup_file_dialog_features(dialog, allow_directory=True, default_mode="文件", is_save_dialog=True)
    
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0], dialog.selectedNameFilter()
    
    return "", ""


def get_file_or_directory(
    parent: Optional[QWidget] = None,
    caption: str = "",
    directory: str = "",
    filter: str = "",
    selected_filter: str = ""
) -> str:
    """
    显示选择文件或目录对话框
    
    提供下拉框选择"文件"或"目录"模式：
    - 选择"目录"：只显示目录，只能选择目录
    - 选择"文件"：显示文件和目录，但只能选择文件
    
    自动应用暗色模式、可编辑地址栏和回车导航功能
    
    Args:
        parent: 父窗口
        caption: 对话框标题
        directory: 初始目录
        filter: 文件过滤器（仅在文件模式下有效）
        selected_filter: 默认选中的过滤器
        
    Returns:
        选中的文件或目录路径
    """
    dialog = QFileDialog(parent)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setWindowTitle(caption)
    dialog.setDirectory(directory)
    
    # 默认使用文件模式
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
    
    # 设置文件过滤器
    if filter:
        dialog.setNameFilter(filter)
        if selected_filter:
            dialog.selectNameFilter(selected_filter)
        else:
            filters = filter.split(";;")
            if filters:
                dialog.selectNameFilter(filters[0])
    else:
        dialog.setNameFilter("所有文件 (*)")
    
    # 应用增强功能（包括模式选择器）
    setup_file_dialog_features(dialog, allow_directory=True, default_mode="文件")
    
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0]
    
    return ""


def get_existing_directory(
    parent: Optional[QWidget] = None,
    caption: str = "",
    directory: str = "",
    options: QFileDialog.Option = QFileDialog.Option.ShowDirsOnly
) -> str:
    """
    显示选择目录对话框（替代QFileDialog.getExistingDirectory）
    
    自动应用暗色模式、可编辑地址栏和回车导航功能
    
    Args:
        parent: 父窗口
        caption: 对话框标题
        directory: 初始目录
        options: 对话框选项
        
    Returns:
        选中的目录路径
    """
    dialog = QFileDialog(parent)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setWindowTitle(caption)
    dialog.setDirectory(directory)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    
    if options:
        dialog.setOption(options, True)
    
    # 应用增强功能（添加选择类型功能，默认目录模式）
    setup_file_dialog_features(dialog, allow_directory=True, default_mode="目录")
    
    if dialog.exec():
        selected = dialog.selectedFiles()
        if selected:
            return selected[0]
    
    return ""
