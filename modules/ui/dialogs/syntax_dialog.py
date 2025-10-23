#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语法文档对话框模块

从fool_tools.py提取的语法文档对话框
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QLineEdit,
    QTextEdit, QPushButton, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# 导入主题管理器
from modules.ui.styles.theme_manager import ThemeManager

# 导入语法文档模块
from modules.Information_Gathering.Asset_Mapping.fofa_syntax_doc import get_fofa_syntax_doc
from modules.Information_Gathering.Asset_Mapping.hunter_syntax_doc import get_hunter_syntax_doc
from modules.Information_Gathering.Asset_Mapping.quake_syntax_doc import get_quake_syntax_doc
from modules.Information_Gathering.Asset_Mapping.platform_syntax_comparison import get_platform_comparison_doc


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
        self.center_window()
        
        # 设置窗口样式
        self.setup_style()
        
        # 设置UI
        self.setup_ui()
        
        # 加载文档
        self.load_documents()
    
    def center_window(self):
        """窗口居中显示"""
        parent_widget = self.parent()
        # 检查父窗口是否为有效的QWidget
        from PySide6.QtWidgets import QWidget
        if (parent_widget and 
            isinstance(parent_widget, QWidget) and
            hasattr(parent_widget, 'geometry') and 
            callable(getattr(parent_widget, 'geometry', None))):
            try:
                parent_geometry = parent_widget.geometry()
                if parent_geometry and hasattr(parent_geometry, 'x') and hasattr(parent_geometry, 'y'):
                    x = parent_geometry.x() + (parent_geometry.width() - 1000) // 2
                    y = parent_geometry.y() + (parent_geometry.height() - 700) // 2
                    self.move(max(0, x), max(0, y))
                else:
                    self._center_on_screen()
            except Exception:
                # 如果获取父窗口几何信息失败，使用屏幕居中
                self._center_on_screen()
                return
        else:
            self._center_on_screen()
    
    def _center_on_screen(self):
        """在屏幕上居中显示"""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.geometry()
            x = (screen_geometry.width() - 1000) // 2
            y = (screen_geometry.height() - 700) // 2
            self.move(x, y)
    
    def setup_style(self):
        """设置窗口样式"""
        # 根据当前主题设置对话框样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        # 如果强制暗色模式或当前已是暗色模式
        if self.force_dark_mode or theme_manager._dark_mode:
            # 暗色模式样式
            self.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                    border-radius: 10px;
                }
                QTabWidget {
                    background-color: #1e1e1e;
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
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #bb86fc, stop:1 #985eff);
                    color: #1e1e1e;
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
                        stop:0 #d7aefb, stop:1 #bb86fc);
                    margin-top: 0px;
                    margin-bottom: 2px;
                }
                QPushButton:pressed {
                    background-color: #7b39fb;
                    margin-top: 0px;
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
                QPushButton:disabled {
                    background-color: #6c757d;
                    color: #adb5bd;
                }
                QLabel {
                    color: #495057;
                    font-size: 16px;
                    font-weight: 500;
                    padding: 4px;
                }
                QLineEdit {
                    border: 2px solid #dee2e6;
                    border-radius: 8px;
                    padding: 12px 16px;
                    font-size: 16px;
                    background-color: white;
                    min-height: 20px;
                }
                QLineEdit:focus {
                    border-color: #007bff;
                    outline: none;
                }
            """)

    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 标题
        title_label = QLabel("网络空间测绘语法文档")
        
        # 根据当前主题设置标题样式
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if theme_manager._dark_mode:
            # 暗色模式标题样式
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 20px;
                    font-weight: bold;
                    color: #bb86fc;
                    margin-bottom: 5px;
                    background-color: transparent;
                }
            """)
        else:
            # 亮色模式标题样式
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 20px;
                    font-weight: bold;
                    color: #212529;
                    margin-bottom: 5px;
                }
            """)
            
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 搜索框
        search_layout = QHBoxLayout()
        search_label = QLabel("搜索语法:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索语法...")
        self.search_input.textChanged.connect(self.search_syntax)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # 选项卡
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        copy_button = QPushButton("复制当前内容")
        copy_button.clicked.connect(self.copy_current_content)
        button_layout.addWidget(copy_button)
        
        # 设置复制按钮样式
        if self.force_dark_mode or ThemeManager()._dark_mode:
            copy_button.setStyleSheet("""
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
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        # 确保关闭按钮应用相同的样式
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
        """根据当前主题调整HTML内容的样式"""
        from modules.ui.styles.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        
        if self.force_dark_mode or theme_manager._dark_mode:
            # 替换背景色
            html_content = html_content.replace('background-color: #f8f9fa;', 'background-color: #333333;')
            html_content = html_content.replace('background-color: white;', 'background-color: #252525;')
            html_content = html_content.replace('background-color: #e9ecef;', 'background-color: #383838;')
            html_content = html_content.replace('background-color: #d4edda;', 'background-color: #2a3a2a;')
            
            # 替换边框色
            html_content = html_content.replace('border: 1px solid #dee2e6;', 'border: 1px solid #444444;')
            html_content = html_content.replace('border-bottom: 2px solid #007bff;', 'border-bottom: 2px solid #bb86fc;')
            
            # 替换文本颜色
            html_content = html_content.replace('color: #212529;', 'color: #f0f0f0;')
            html_content = html_content.replace('color: #495057;', 'color: #e0e0e0;')
            html_content = html_content.replace('color: #155724;', 'color: #a0e0a0;')
            
            # 替换标题和特殊颜色
            html_content = html_content.replace('color: #007bff;', 'color: #bb86fc;')
            html_content = html_content.replace('color: #28a745;', 'color: #03dac6;')
        
        return html_content
    
    def load_documents(self):
        """加载文档内容"""
        try:
            # FOFA文档
            fofa_content = self.adapt_html_for_dark_mode(get_fofa_syntax_doc())
            fofa_text = QTextEdit()
            fofa_text.setReadOnly(True)
            fofa_text.setHtml(fofa_content)
            self.tab_widget.addTab(fofa_text, "FOFA")
            
            # Hunter文档
            hunter_content = self.adapt_html_for_dark_mode(get_hunter_syntax_doc())
            hunter_text = QTextEdit()
            hunter_text.setReadOnly(True)
            hunter_text.setHtml(hunter_content)
            self.tab_widget.addTab(hunter_text, "Hunter")
            
            # Quake文档
            quake_content = self.adapt_html_for_dark_mode(get_quake_syntax_doc())
            quake_text = QTextEdit()
            quake_text.setReadOnly(True)
            quake_text.setHtml(quake_content)
            self.tab_widget.addTab(quake_text, "Quake")
            
            # 语法对比
            comparison_content = self.adapt_html_for_dark_mode(get_platform_comparison_doc())
            comparison_text = QTextEdit()
            comparison_text.setReadOnly(True)
            comparison_text.setHtml(comparison_content)
            self.tab_widget.addTab(comparison_text, "语法对比")
            
        except Exception as e:
            print(f"加载语法文档失败: {e}")
            # 创建错误提示
            error_text = QTextEdit()
            error_text.setReadOnly(True)
            error_text.setPlainText(f"加载语法文档失败: {str(e)}")
            self.tab_widget.addTab(error_text, "错误")
    
    def search_syntax(self):
        """搜索语法"""
        search_text = self.search_input.text().lower()
        
        if not search_text:
            # 如果搜索框为空，恢复所有内容的显示
            self.load_documents()
            return
        
        # 获取当前选中的标签页
        current_index = self.tab_widget.currentIndex()
        current_widget = self.tab_widget.widget(current_index)
        
        if isinstance(current_widget, QTextEdit):
            # 高亮搜索结果
            cursor = current_widget.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            current_widget.setTextCursor(cursor)
            
            # 查找并高亮匹配的文本
            found = current_widget.find(search_text)
            if found:
                # 滚动到找到的位置
                current_widget.ensureCursorVisible()
    
    def copy_current_content(self):
        """复制当前标签页内容"""
        try:
            current_widget = self.tab_widget.currentWidget()
            if isinstance(current_widget, QTextEdit):
                # 获取纯文本内容
                content = current_widget.toPlainText()
                
                # 复制到剪贴板
                clipboard = QApplication.clipboard()
                clipboard.setText(content)
                
                # 显示提示（可以考虑添加状态栏或临时提示）
                print("内容已复制到剪贴板")
                
        except Exception as e:
            print(f"复制内容失败: {e}")
    
    def get_fofa_content(self):
        """获取FOFA文档内容（兼容方法）"""
        return get_fofa_syntax_doc()
    
    def get_hunter_content(self):
        """获取Hunter文档内容（兼容方法）"""
        return get_hunter_syntax_doc()
    
    def get_quake_content(self):
        """获取Quake文档内容（兼容方法）"""
        return get_quake_syntax_doc()
    
    def get_comparison_content(self):
        """获取语法对比内容（兼容方法）"""
        return get_platform_comparison_doc()


def main():
    """测试函数"""
    import sys
    
    app = QApplication(sys.argv)
    
    dialog = ModernSyntaxDocumentDialog()
    dialog.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()