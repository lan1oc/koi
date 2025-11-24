#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周报生成UI组件

提供周报生成功能的图形界面组件
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLabel, QTextEdit, QComboBox, QMessageBox, QSplitter,
    QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor

from .weekly_report_generator import WeeklyReportGenerator
from typing import Optional
import logging
from modules.ui.message_box_helper import show_warning, show_information, show_critical


class WeeklyReportThread(QThread):
    """周报生成线程"""
    progress_updated = Signal(str)
    report_completed = Signal(str)
    
    def __init__(self, generator: WeeklyReportGenerator, days: Optional[int], detailed: bool):
        super().__init__()
        self.generator = generator
        self.days = days
        self.detailed = detailed
    
    def run(self):
        """执行周报生成"""
        try:
            self.progress_updated.emit("正在收集文件活动记录...")
            report = self.generator.generate_report(self.days, self.detailed)
            self.report_completed.emit(report)
        except Exception as e:
            self.report_completed.emit(f"生成报告时出错: {str(e)}")


class WeeklyReportUI(QWidget):
    """周报生成UI主组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        
        # 安装事件过滤器以监听样式变化
        self.installEventFilter(self)
        
        # 初始化周报生成器
        self.weekly_report_generator = None
        self.weekly_report_thread = None
        
        self.setup_ui()
        
        # 使用事件过滤器监听样式变化
        self.installEventFilter(self)
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 创建分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧控制面板
        left_widget = self.create_control_panel()
        splitter.addWidget(left_widget)
        
        # 右侧结果显示
        right_widget = self.create_result_panel()
        splitter.addWidget(right_widget)
        
        # 设置分割比例
        splitter.setSizes([300, 700])  # 左侧300，右侧700
        
        main_layout.addWidget(splitter)
    
    def create_control_panel(self) -> QWidget:
        """创建控制面板"""
        # 创建主容器
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 不使用内联样式，使用全局样式
        scroll_area.setProperty("class", "transparent-scroll-area")
        scroll_area.style().polish(scroll_area)
        
        # 创建滚动内容容器
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("📝 周报生成器")
        title_label.setProperty("class", "section-title")
        title_label.style().polish(title_label)
        scroll_layout.addWidget(title_label)
        
        # 配置组
        config_group = QGroupBox("⚙️ 生成配置")
        config_group.setProperty("class", "config-group")
        config_group.style().polish(config_group)
        config_layout = QVBoxLayout(config_group)
        
        # 时间范围选择
        range_label = QLabel("📅 统计时间范围:")
        range_label.setStyleSheet("font-weight: bold; color: #34495e;")
        config_layout.addWidget(range_label)
        
        self.report_range_combo = QComboBox()
        self.report_range_combo.addItems([
            "本周工作日", "最近3天", "最近7天", "最近14天", "最近30天"
        ])
        self.report_range_combo.setProperty("class", "styled-combo")
        self.report_range_combo.style().polish(self.report_range_combo)
        config_layout.addWidget(self.report_range_combo)
        
        # 报告类型选择
        type_label = QLabel("📋 报告详细程度:")
        type_label.setStyleSheet("font-weight: bold; color: #34495e;")
        config_layout.addWidget(type_label)
        
        self.report_type_combo = QComboBox()
        self.report_type_combo.addItems(["简要报告", "详细报告"])
        self.report_type_combo.setProperty("class", "styled-combo")
        self.report_type_combo.style().polish(self.report_type_combo)
        config_layout.addWidget(self.report_type_combo)
        
        scroll_layout.addWidget(config_group)
        
        # 操作按钮组
        button_group = QGroupBox("🎯 操作")
        button_group.setProperty("class", "config-group")
        button_group.style().polish(button_group)
        button_layout = QVBoxLayout(button_group)
        
        # 生成按钮
        self.generate_btn = QPushButton("🚀 生成周报")
        self.generate_btn.setProperty("class", "primary-button")
        self.generate_btn.style().polish(self.generate_btn)
        self.generate_btn.clicked.connect(self.generate_weekly_report)
        button_layout.addWidget(self.generate_btn)
        
        # 清空按钮
        self.clear_btn = QPushButton("🗑️ 清空结果")
        self.clear_btn.setProperty("class", "secondary-button")
        self.clear_btn.style().polish(self.clear_btn)
        self.clear_btn.clicked.connect(self.clear_weekly_report)
        button_layout.addWidget(self.clear_btn)
        
        scroll_layout.addWidget(button_group)
        
        # 状态显示
        status_group = QGroupBox("📊 状态")
        status_group.setProperty("class", "config-group")
        status_group.style().polish(status_group)
        status_layout = QVBoxLayout(status_group)
        
        self.report_status_label = QLabel("等待生成...")
        # 使用全局样式类属性
        self.report_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.report_status_label.style().polish(self.report_status_label)
        status_layout.addWidget(self.report_status_label)
        
        scroll_layout.addWidget(status_group)
        
        # 添加弹性空间
        scroll_layout.addStretch()
        
        # 设置滚动区域的内容
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        return main_widget
    
    def create_result_panel(self) -> QWidget:
        """创建结果显示面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 结果标题
        result_label = QLabel("📄 周报结果")
        result_label.setProperty("class", "section-title")
        result_label.style().polish(result_label)
        layout.addWidget(result_label)
        
        # 结果文本框
        self.weekly_report_result = QTextEdit()
        self.weekly_report_result.setPlaceholderText("周报内容将在这里显示...")
        # 不使用内联样式，使用全局样式
        layout.addWidget(self.weekly_report_result)
        
        return widget
    
    def generate_weekly_report(self):
        """生成工作周报"""
        try:
            # 初始化周报生成器
            if not self.weekly_report_generator:
                self.weekly_report_generator = WeeklyReportGenerator()
            
            # 获取配置
            range_text = self.report_range_combo.currentText()
            is_detailed = self.report_type_combo.currentText().startswith("详细")
            
            # 解析天数
            days = None
            if range_text == "最近3天":
                days = 3
            elif range_text == "最近7天":
                days = 7
            elif range_text == "最近14天":
                days = 14
            elif range_text == "最近30天":
                days = 30
            # 本周工作日保持days=None
            
            # 更新状态
            self.report_status_label.setText("正在生成周报...")
            # 使用全局样式类属性
            self.report_status_label.setProperty("class", "status-label-processing")
            # 刷新样式
            self.report_status_label.style().polish(self.report_status_label)
            
            # 启动生成线程
            self.weekly_report_thread = WeeklyReportThread(
                self.weekly_report_generator, days, is_detailed
            )
            self.weekly_report_thread.progress_updated.connect(self.update_report_progress)
            self.weekly_report_thread.report_completed.connect(self.on_report_completed)
            self.weekly_report_thread.start()
            
        except Exception as e:
            show_critical(self, "错误", f"生成周报时出错: {str(e)}")
            self.report_status_label.setText("生成失败")
            # 使用全局样式类属性
            self.report_status_label.setProperty("class", "status-label-error")
            # 刷新样式
            self.report_status_label.style().polish(self.report_status_label)
    
    def update_report_progress(self, message: str):
        """更新生成进度"""
        self.report_status_label.setText(message)
        # 设置状态标签的类属性，使用全局样式
        self.report_status_label.setProperty("class", "status-label-info")
        # 刷新样式
        self.report_status_label.style().polish(self.report_status_label)
    
    def on_report_completed(self, report: str):
        """报告生成完成"""
        self.weekly_report_result.setPlainText(report)
        
        # 确保滚动条可以正常工作
        from PySide6.QtCore import QTimer
        
        def adjust_scrollbar():
            # 移动到文档开始位置
            self.weekly_report_result.moveCursor(QTextCursor.MoveOperation.Start)
            # 确保滚动条更新到顶部
            self.weekly_report_result.verticalScrollBar().setValue(0)
            self.weekly_report_result.update()
        
        QTimer.singleShot(100, adjust_scrollbar)  # 延迟100ms执行
        
        if report.startswith("生成报告时出错"):
            self.report_status_label.setText("生成失败")
            # 使用全局样式类属性
            self.report_status_label.setProperty("class", "status-label-error")
            # 刷新样式
            self.report_status_label.style().polish(self.report_status_label)
        else:
            self.report_status_label.setText("生成完成")
            # 使用全局样式类属性
            self.report_status_label.setProperty("class", "status-label-success")
            # 刷新样式
            self.report_status_label.style().polish(self.report_status_label)
    
    def clear_weekly_report(self):
        """清空周报结果"""
        self.weekly_report_result.clear()
        self.report_status_label.setText("等待生成...")
        # 使用全局样式类属性
        self.report_status_label.setProperty("class", "status-label-waiting")
        # 刷新样式
        self.report_status_label.style().polish(self.report_status_label)
    
    def eventFilter(self, obj, event):
        """事件过滤器，用于监听样式变化"""
        from PySide6.QtCore import QEvent
        
        # 监听样式变化事件
        if event.type() == QEvent.Type.StyleChange:
            # 获取当前状态标签的类属性
            current_class = self.report_status_label.property("class")
            if current_class:
                # 重新应用当前样式类
                self.report_status_label.style().unpolish(self.report_status_label)
                self.report_status_label.style().polish(self.report_status_label)
        
        # 继续传递事件
        return super().eventFilter(obj, event)


def main():
    """测试函数"""
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 创建周报UI
    weekly_ui = WeeklyReportUI()
    weekly_ui.setWindowTitle("周报生成器")
    weekly_ui.resize(1000, 700)
    weekly_ui.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()