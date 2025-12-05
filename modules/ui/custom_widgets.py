from PySide6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, 
    QLabel, QStackedWidget, QFrame, QScrollArea, QSizePolicy, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, QSize, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QLinearGradient, QFont, QIcon
from modules.ui.styles.icons import get_icon

class RainbowBorderButton(QPushButton):
    """Button with a flowing RGB gradient border on hover"""
    def __init__(self, text="", icon_name=None, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(120)  # Large button for function list
        
        if icon_name:
            icon = get_icon(icon_name, 32)
            if icon:
                self.setIcon(icon)
                self.setIconSize(QSize(32, 32))
        
        self._hover_progress = 0.0
        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(self._update_hover)
        
        self._hue = 0
        self._rgb_timer = QTimer(self)
        self._rgb_timer.timeout.connect(self._update_rgb)
        self._rgb_timer.start(20) # 50fps for smooth color flow
        
        self._is_dark = True # Default to dark
        self.update_style()
        
    def set_theme(self, is_dark):
        """Set the theme for the button"""
        self._is_dark = is_dark
        self.update_style()
        
    def update_style(self):
        """Update stylesheet based on theme"""
        if self._is_dark:
            # Dark Mode: Deep, rich background with subtle border
            bg_color = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2c3e50, stop:1 #202020)"
            text_color = "white"
            border = "1px solid rgba(255, 255, 255, 0.1)"
        else:
            # Light Mode: Bright, visible background with distinct border
            bg_color = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f0f2f5)"
            text_color = "#000000"
            border = "1px solid #d1d5db" # Visible grey border
            
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg_color};
                color: {text_color} !important;
                border: {border};
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
                text-align: center;
                padding: 10px;
            }}
            QPushButton:hover {{
                border: 1px solid rgba(100, 100, 100, 0.3);
            }}
        """)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        
    def _update_hover(self):
        if self.underMouse():
            self._hover_progress = min(1.0, self._hover_progress + 0.1)
        else:
            self._hover_progress = max(0.0, self._hover_progress - 0.1)
            
        if self._hover_progress == 0 or self._hover_progress == 1:
            if not self.underMouse() and self._hover_progress == 0:
                self._hover_timer.stop()
        
        self.update()
        
    def _update_rgb(self):
        self._hue = (self._hue + 2) % 360
        if self._hover_progress > 0:
            self.update()

    def enterEvent(self, event):
        self._hover_timer.start(16)
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self._hover_timer.start(16)
        super().leaveEvent(event)
        
    def paintEvent(self, event):
        # Draw default button
        super().paintEvent(event)
        
        if self._hover_progress > 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Create RGB Gradient
            grad = QLinearGradient(0, 0, self.width(), self.height())
            c1 = QColor.fromHsl(self._hue, 255, 128)
            c2 = QColor.fromHsl((self._hue + 120) % 360, 255, 128)
            c3 = QColor.fromHsl((self._hue + 240) % 360, 255, 128)
            
            grad.setColorAt(0, c1)
            grad.setColorAt(0.5, c2)
            grad.setColorAt(1, c3)
            
            # Draw Border
            pen = QPen(QBrush(grad), 3 * self._hover_progress)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            
            rect = self.rect().adjusted(2, 2, -2, -2)
            p.drawRoundedRect(rect, 10, 10)
            
            # Draw Glow
            p.setOpacity(0.2 * self._hover_progress)
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), 10, 10)
            
            p.end()

class SidebarButton(QPushButton):
    """Sidebar button with RGB glow effect"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(50)
        self.setCheckable(True) # Allow selected state
        
        self._hover_progress = 0.0
        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(self._update_hover)
        
        self._hue = 0
        self._rgb_timer = QTimer(self)
        self._rgb_timer.timeout.connect(self._update_rgb)
        self._rgb_timer.start(20)
        
        self._is_dark = True
        self.update_style()
        
    def set_theme(self, is_dark):
        self._is_dark = is_dark
        self.update_style()
        
    def update_style(self):
        if self._is_dark:
            text_color = "#cdd6f4"
            bg_color = "rgba(35, 35, 48, 0.75)"
            hover_bg = "rgba(55, 55, 75, 0.85)"
            border_color = "rgba(80, 80, 110, 0.4)"
        else:
            text_color = "#333333"
            bg_color = "rgba(255, 255, 255, 0.8)"
            hover_bg = "rgba(240, 242, 248, 0.9)"
            border_color = "rgba(0, 0, 0, 0.08)"
            
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                text-align: left;
                padding-left: 20px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border: 1px solid {"rgba(187, 134, 252, 0.5)" if self._is_dark else "rgba(0, 123, 255, 0.3)"};
            }}
            QPushButton:checked {{
                background-color: {hover_bg};
                border-left: 3px solid {"#bb86fc" if self._is_dark else "#007bff"};
            }}
        """)

    def _update_hover(self):
        # Animate hover progress based on mouse state OR checked state
        target = 1.0 if (self.underMouse() or self.isChecked()) else 0.0
        
        if self._hover_progress < target:
            self._hover_progress = min(target, self._hover_progress + 0.1)
        elif self._hover_progress > target:
            self._hover_progress = max(target, self._hover_progress - 0.1)
            
        if self._hover_progress == 0 or self._hover_progress == 1:
            if not self.underMouse() and not self.isChecked() and self._hover_progress == 0:
                self._hover_timer.stop()
        
        self.update()
        
    def _update_rgb(self):
        self._hue = (self._hue + 2) % 360
        if self._hover_progress > 0:
            self.update()

    def enterEvent(self, event):
        self._hover_timer.start(16)
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self._hover_timer.start(16)
        super().leaveEvent(event)
        
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if self._hover_progress > 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # RGB Gradient
            grad = QLinearGradient(0, 0, self.width(), 0) # Horizontal gradient
            c1 = QColor.fromHsl(self._hue, 255, 128)
            c2 = QColor.fromHsl((self._hue + 60) % 360, 255, 128)
            
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            
            # Draw Left Border/Glow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            
            # Animated width for the left indicator
            indicator_width = int(4 * self._hover_progress)
            p.drawRoundedRect(0, 10, indicator_width, self.height() - 20, 2, 2)
            
            # Subtle background glow
            p.setOpacity(0.1 * self._hover_progress)
            p.drawRoundedRect(self.rect(), 8, 8)
            
            p.end()

class ModuleContainer(QWidget):
    """
    Manages the navigation between "Function List" and "Function Page".
    Takes a QTabWidget (legacy module) and converts it into a modern navigation flow.
    """
    def __init__(self, title, tab_widget: QTabWidget, parent=None):
        super().__init__(parent)
        self.title = title
        self.tab_widget = tab_widget
        
        # Hide the original tab bar and apply frosted glass effect
        self.tab_widget.tabBar().setVisible(False)
        self.tab_widget.setDocumentMode(True)
        
        # Apply frosted glass background to tab content area - dark mode default
        # This comprehensive styling targets inner page widgets too
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { 
                border: 0; 
                background-color: rgba(28, 28, 38, 0.92);
                border-radius: 10px;
                padding: 12px;
            }
            /* Inner page widget backgrounds */
            QTabWidget > QStackedWidget > QWidget {
                background-color: rgba(28, 28, 38, 0.92);
                border-radius: 8px;
            }
            QWidget {
                background-color: transparent;
            }
            QFrame {
                background-color: rgba(35, 35, 48, 0.8);
                border: 1px solid rgba(80, 80, 110, 0.3);
                border-radius: 8px;
            }
            QGroupBox {
                background-color: rgba(35, 35, 48, 0.85);
                border: 1px solid rgba(80, 80, 110, 0.4);
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                color: #bb86fc;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        self._is_dark = True  # Track current theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        
        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stack.setStyleSheet("background: transparent;")
        self._layout.addWidget(self.stack)
        
        # Page 1: Function List
        self.function_list_page = QWidget()
        self.function_list_layout = QVBoxLayout(self.function_list_page)
        self.function_list_layout.setContentsMargins(40, 40, 40, 40)
        self.function_list_layout.setSpacing(20)
        
        # Title - initialize with dark mode color (app starts in dark mode)
        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet("font-size: 32px; font-weight: bold; color: white !important; margin-bottom: 20px;")
        self.function_list_layout.addWidget(self.title_label)
        
        # Grid for buttons
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(20)
        self.function_list_layout.addWidget(self.grid_widget)
        self.function_list_layout.addStretch(1)
        
        self.stack.addWidget(self.function_list_page)
        
        # Page 2: Function Detail Container
        self.detail_page = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_page)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header (Back button + Title)
        self.header = QWidget()
        self.header.setStyleSheet("background-color: rgba(30, 30, 40, 0.5); border-bottom: 1px solid rgba(255, 255, 255, 0.1);")
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(20, 10, 20, 10)
        
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #00aaff;
                font-size: 16px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.back_btn.clicked.connect(self.go_back)
        
        self.current_func_label = QLabel("")
        self.current_func_label.setStyleSheet("font-size: 18px; font-weight: bold; color: white !important; margin-left: 20px;")
        
        self.header_layout.addWidget(self.back_btn)
        self.header_layout.addWidget(self.current_func_label)
        self.header_layout.addStretch(1)
        
        self.detail_layout.addWidget(self.header)
        self.detail_layout.addWidget(self.tab_widget) # Add the original tab widget here
        
        self.stack.addWidget(self.detail_page)
        
        # Populate Function List
        self._populate_functions()
        
    def _populate_functions(self):
        count = self.tab_widget.count()
        cols = 3
        
        for i in range(count):
            tab_text = self.tab_widget.tabText(i)
            # Clean up tab text (remove emojis if needed, though they look good)
            
            btn = RainbowBorderButton(tab_text)
            # Try to map text to icon? For now just text
            
            # Use closure to capture index
            btn.clicked.connect(lambda checked=False, idx=i, text=tab_text: self.open_function(idx, text))
            
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(btn, row, col)
            
    def open_function(self, index, text):
        self.tab_widget.setCurrentIndex(index)
        self.current_func_label.setText(text)
        self.stack.setCurrentWidget(self.detail_page)
        
    def set_theme(self, is_dark):
        """Propagate theme to children"""
        # Update title color
        title_color = "white" if is_dark else "#000000"
        # Use direct reference if available, else findChild
        if hasattr(self, 'title_label'):
            self.title_label.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {title_color} !important; margin-bottom: 20px;")
        else:
            label = self.findChild(QLabel)
            if label:
                label.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {title_color} !important; margin-bottom: 20px;")
        
        # Update back button color
        back_color = "#00aaff" if is_dark else "#0056b3" # Darker blue for light mode visibility
        self.back_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {back_color} !important;
                font-size: 16px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{
                color: {title_color} !important;
            }}
        """)
        
        # Update current func label
        self.current_func_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {title_color} !important; margin-left: 20px;")
        
        # Update header background - enhanced frosted glass effect
        if is_dark:
            header_bg = "rgba(25, 25, 35, 0.85)"
            border_color = "rgba(100, 100, 130, 0.3)"
        else:
            header_bg = "rgba(248, 249, 252, 0.92)"
            border_color = "rgba(0, 0, 0, 0.1)"
        self.header.setStyleSheet(f"background-color: {header_bg}; border-bottom: 1px solid {border_color}; border-radius: 8px 8px 0 0;")
        
        # Update tab_widget frosted glass background
        self._is_dark = is_dark
        if is_dark:
            self.tab_widget.setStyleSheet("""
                QTabWidget::pane { 
                    border: 0; 
                    background-color: rgba(28, 28, 38, 0.92);
                    border-radius: 10px;
                    padding: 12px;
                }
                /* Inner page widget backgrounds */
                QTabWidget > QStackedWidget > QWidget {
                    background-color: rgba(28, 28, 38, 0.92);
                    border-radius: 8px;
                }
                QWidget {
                    background-color: transparent;
                }
                QFrame {
                    background-color: rgba(35, 35, 48, 0.8);
                    border: 1px solid rgba(80, 80, 110, 0.3);
                    border-radius: 8px;
                }
                QGroupBox {
                    background-color: rgba(35, 35, 48, 0.85);
                    border: 1px solid rgba(80, 80, 110, 0.4);
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 8px;
                    color: #bb86fc;
                }
                QScrollArea {
                    background-color: transparent;
                    border: none;
                }
                QScrollArea > QWidget > QWidget {
                    background-color: transparent;
                }
            """)
        else:
            self.tab_widget.setStyleSheet("""
                QTabWidget::pane { 
                    border: 0; 
                    background-color: rgba(255, 255, 255, 0.94);
                    border-radius: 10px;
                    padding: 12px;
                }
                /* Inner page widget backgrounds */
                QTabWidget > QStackedWidget > QWidget {
                    background-color: rgba(255, 255, 255, 0.94);
                    border-radius: 8px;
                }
                QWidget {
                    background-color: transparent;
                }
                QFrame {
                    background-color: rgba(248, 249, 252, 0.9);
                    border: 1px solid rgba(0, 0, 0, 0.08);
                    border-radius: 8px;
                }
                QGroupBox {
                    background-color: rgba(248, 249, 252, 0.92);
                    border: 1px solid rgba(0, 0, 0, 0.08);
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 8px;
                    color: #007bff;
                }
                QScrollArea {
                    background-color: transparent;
                    border: none;
                }
                QScrollArea > QWidget > QWidget {
                    background-color: transparent;
                }
            """)
        
        # Update all RainbowBorderButtons
        for btn in self.findChildren(RainbowBorderButton):
            btn.set_theme(is_dark)
            
        # Force refresh of the container itself
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def go_back(self):
        self.stack.setCurrentWidget(self.function_list_page)
