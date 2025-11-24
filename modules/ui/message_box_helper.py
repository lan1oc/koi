#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QMessageBox 辅助函数
解决 QMessageBox 不继承全局样式表的问题
"""

from PySide6.QtWidgets import QMessageBox, QWidget
from typing import Optional


def _apply_messagebox_style(msg_box: QMessageBox):
    """
    应用消息框样式
    
    由于 QMessageBox 作为顶层窗口不会自动继承 QApplication 的样式表，
    需要手动应用样式
    """
    from modules.ui.styles.theme_manager import ThemeManager
    theme_manager = ThemeManager()
    
    if theme_manager._dark_mode:
        # 暗色模式
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #1e1e1e;
                color: #f0f0f0;
            }
            QMessageBox QLabel {
                color: #f0f0f0;
                background-color: transparent;
            }
            QMessageBox QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d3d, stop:1 #2d2d2d);
                color: #f0f0f0;
                border: 1px solid #505050;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                min-width: 100px;
                min-height: 36px;
            }
            QMessageBox QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #505050, stop:1 #3d3d3d);
                border: 1px solid #666666;
            }
            QMessageBox QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d2d2d, stop:1 #3d3d3d);
            }
        """)
    else:
        # 亮色模式
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
                color: #343a40;
            }
            QMessageBox QLabel {
                color: #343a40;
                background-color: transparent;
            }
            QMessageBox QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #007bff, stop:1 #0056b3);
                color: #ffffff;
                border: 1px solid #0056b3;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 500;
                font-size: 14px;
                min-width: 80px;
                min-height: 36px;
            }
            QMessageBox QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0056b3, stop:1 #004085);
                border: 1px solid #004085;
            }
            QMessageBox QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #004085, stop:1 #0056b3);
            }
        """)


def show_warning(parent: Optional[QWidget], title: str, text: str) -> int:
    """显示警告消息框"""
    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.Icon.Warning)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _apply_messagebox_style(msg_box)
    return msg_box.exec()


def show_information(parent: Optional[QWidget], title: str, text: str) -> int:
    """显示信息消息框"""
    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.Icon.Information)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _apply_messagebox_style(msg_box)
    return msg_box.exec()


def show_critical(parent: Optional[QWidget], title: str, text: str) -> int:
    """显示错误消息框"""
    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    _apply_messagebox_style(msg_box)
    return msg_box.exec()


def show_question(parent: Optional[QWidget], title: str, text: str, buttons=None) -> int:
    """显示询问消息框"""
    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.Icon.Question)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    if buttons is not None:
        msg_box.setStandardButtons(buttons)
    else:
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    _apply_messagebox_style(msg_box)
    return msg_box.exec()

