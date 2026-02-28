#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业信息展示组件
用于美观地展示天眼查和爱企查的结构化查询结果
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QBrush
from modules.ui.styles.theme_manager import ThemeManager

class InfoRow(QWidget):
    """单个信息行组件"""
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(10)
        
        # 标签
        lbl = QLabel(label)
        lbl.setProperty("class", "info-label")
        lbl.setFixedWidth(100)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 值
        val = QLabel(value if value else "暂无")
        val.setProperty("class", "info-value")
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        layout.addWidget(lbl)
        layout.addWidget(val)
        layout.setStretch(1, 1)

class SectionBox(QGroupBox):
    """带样式的分组框"""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setProperty("class", "info-section")

class EnterpriseInfoWidget(QScrollArea):
    """企业信息展示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "enterprise-info")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        
        # 内容容器
        self.content_widget = QWidget()
        self.content_widget.setProperty("class", "enterprise-info-content")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(20)
        
        self.setWidget(self.content_widget)
        
        self.theme_manager = ThemeManager()
        self._dark_mode = self.theme_manager._dark_mode
        self.theme_manager.dark_mode_changed.connect(self._apply_theme)
        self._apply_theme(self._dark_mode)

        self.show_welcome()

    def show_welcome(self):
        """显示欢迎/初始界面"""
        self._clear_layout()
        
        lbl = QLabel("请开始查询以获取企业信息")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setProperty("class", "info-muted")
        self.content_layout.addWidget(lbl)
        self.content_layout.addStretch()

    def show_loading(self, message="正在查询中，请稍候..."):
        """显示加载状态"""
        self._clear_layout()
        
        lbl = QLabel(message)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setProperty("class", "info-loading")
        self.content_layout.addWidget(lbl)
        self.content_layout.addStretch()

    def _clear_layout(self):
        """清空布局"""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_tianyancha(self, data: dict):
        """渲染天眼查数据"""
        self._clear_layout()
        
        company = data.get('companies', [{}])[0] if data.get('companies') else {}
        if not company:
            self._render_error("未获取到有效的企业数据")
            return

        # 1. 头部信息（企业名称）
        self._render_header(company.get('name', '未知企业'))
        
        # 2. 基本信息
        categories = []
        for i in range(1, 5):
            cat = company.get(f'categoryNameLv{i}', '')
            if cat:
                categories.append(cat)
        category_full = ' > '.join(categories) if categories else ''
        if categories:
            category_text = category_full # 主显示也显示完整路径
        else:
            alt = company.get('industryCategory', '') or company.get('industry', '')
            category_text = alt if alt else '-'
            category_full = alt if alt else ''

        basic_info = {
            '法定代表人': company.get('legalPersonName'),
            '注册资本': company.get('regCapital'),
            # 天眼查无 estiblishTime 字段，保留为空以防止误映射
            '成立日期': company.get('estiblishTime'),
            '统一社会信用代码': company.get('creditCode'),
            '企业状态': company.get('regStatus'),
            '注册地址': company.get('regLocation'),
            '联系电话': '; '.join(company.get('phoneList', []) or []),
            '邮箱': '; '.join(company.get('emailList', []) or []),
            '网址': company.get('websites'),
            '行业分类': category_text
        }
        self._render_basic_info(basic_info, {
            '行业分类': category_full if category_full else '-'
        })
        
        # 3. ICP备案信息
        icp_records = company.get('icp_records', [])
        self._render_table_section("ICP备案信息", icp_records, [
            ('网站名称', 'webName'),
            ('域名', 'ym'),
            ('许可证号', 'liscense'),
            ('审核日期', 'examineDate')
        ])
        
        # 4. APP信息
        app_records = company.get('app_records', [])
        self._render_table_section("APP信息", app_records, [
            ('APP名称', 'name'),
            ('产品分类', 'type'),
            ('领域', 'classes')
        ])
        
        # 5. 微信公众号信息
        wechat_records = company.get('wechat_records', [])
        self._render_table_section("微信公众号", wechat_records, [
            ('公众号名称', 'title'),
            ('微信号', 'publicNum')
        ])
        
        self.content_layout.addStretch()

    def render_aiqicha(self, data: dict):
        """渲染爱企查数据"""
        self._clear_layout()
        
        basic_info_data = data.get('basic_info', {})
        if not basic_info_data:
            self._render_error("未获取到有效的企业基础信息")
            return

        # 1. 头部信息
        self._render_header(data.get('company_name', '未知企业'))
        
        # 2. 基本信息
        industry_info = data.get('industry_info', {})
        employee_emails = industry_info.get('employee_emails', [])
        contact_info = data.get('contact_info', []) # 这是一个列表，包含手机号
        aiqicha_categories = []
        for i in range(1, 5):
            key = f'industryCode{i}'
            val = industry_info.get(key, '')
            if val:
                aiqicha_categories.append(val)
        if aiqicha_categories:
            aiqicha_category_full = ' > '.join(aiqicha_categories)
            aiqicha_category_text = aiqicha_categories[-1]
        else:
            alt = ''
            for i in range(1, 5):
                k2 = f'industryName{i}'
                v2 = industry_info.get(k2, '')
                if v2:
                    aiqicha_categories.append(v2)
            if aiqicha_categories:
                aiqicha_category_full = ' > '.join(aiqicha_categories)
                aiqicha_category_text = aiqicha_categories[-1]
            else:
                alt = industry_info.get('industryNum', '')
                aiqicha_category_full = alt if alt else ''
                aiqicha_category_text = alt if alt else '-'
        
        basic_info = {
            '法定代表人': basic_info_data.get('legalPerson'),
            '注册资本': basic_info_data.get('regCap'),
            '成立日期': basic_info_data.get('openTime'), # 假设字段
            '统一社会信用代码': basic_info_data.get('regNo'),
            '企业地址': basic_info_data.get('titleDomicile'),
            '联系电话': basic_info_data.get('telephone'),
            '更多电话': '; '.join(contact_info) if contact_info else None,
            '邮箱': basic_info_data.get('email'),
            '员工邮箱': '; '.join(employee_emails) if employee_emails else None,
            '网址': basic_info_data.get('website'),
            '行业分类': aiqicha_category_text
        }
        self._render_basic_info(basic_info, {
            '行业分类': aiqicha_category_full if aiqicha_category_full else '-'
        })
        
        # 3. ICP备案信息
        icp_info = data.get('icp_info', [])
        self._render_table_section("ICP备案信息", icp_info, [
            ('网站名称', 'siteName'),
            ('域名', 'domain'),  # 可能是列表
            ('备案号', 'icpNo')
        ])
        
        # 4. APP信息
        app_info = data.get('app_info', [])
        self._render_table_section("APP信息", app_info, [
            ('APP名称', 'name'),
            ('包名', 'packageName') # 假设字段
        ])
        
        # 5. 微信公众号信息
        wechat_info = data.get('wechat_info', [])
        self._render_table_section("微信公众号", wechat_info, [
            ('公众号名称', 'wechatName'),
            ('微信号', 'wechatId')
        ])
        
        self.content_layout.addStretch()

    def _render_header(self, title):
        """渲染头部标题"""
        lbl = QLabel(title)
        lbl.setProperty("class", "info-header")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_layout.addWidget(lbl)

    def _render_basic_info(self, info_dict, tooltip_map=None):
        """渲染基本信息区域"""
        box = SectionBox("🏢 基本信息")
        layout = QGridLayout(box)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setSpacing(10)
        
        row = 0
        col = 0
        
        for label, value in info_dict.items():
            if value is None: # 跳过显式None的字段
                continue
                
            # 标签
            lbl = QLabel(label + ":")
            lbl.setProperty("class", "info-label")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            # 值
            display_text = str(value) if value else "-"
            val = QLabel(display_text)
            val.setProperty("class", "info-value")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if tooltip_map and label in tooltip_map:
                val.setToolTip(tooltip_map[label])
            
            layout.addWidget(lbl, row, col)
            layout.addWidget(val, row, col + 1)
            
            col += 2
            if col >= 4:
                col = 0
                row += 1
                
        self.content_layout.addWidget(box)

    def _render_table_section(self, title, data_list, columns):
        """渲染表格区域"""
        if not data_list:
            return

        box = SectionBox(f"📋 {title} ({len(data_list)})")
        layout = QVBoxLayout(box)
        
        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([col[0] for col in columns])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setRowCount(len(data_list))
        table.setProperty("class", "info-table")
        
        for r, item_data in enumerate(data_list):
            for c, (col_name, key) in enumerate(columns):
                val = item_data.get(key)
                
                # 特殊处理域名列表
                if key == 'domain' and isinstance(val, list):
                    val = ', '.join(val)
                
                # 处理None
                if val is None:
                    val = ""
                else:
                    val = str(val)
                    
                table_item = QTableWidgetItem(val)
                table_item.setFlags(table_item.flags() ^ Qt.ItemFlag.ItemIsEditable) # 只读
                table.setItem(r, c, table_item)
                
        # 自适应高度
        row_height = 35
        header_height = table.horizontalHeader().height()
        total_height = header_height + (row_height * min(len(data_list), 10)) + 10 # 最多显示10行，超过滚动
        if len(data_list) > 10:
             total_height += 15 # 滚动条高度
             
        table.setMinimumHeight(min(total_height, 400))
        table.setMaximumHeight(400)

        layout.addWidget(table)
        self.content_layout.addWidget(box)

    def _render_error(self, message):
        """渲染错误信息"""
        lbl = QLabel(f"⚠️ {message}")
        lbl.setProperty("class", "info-error")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(lbl)
        self.content_layout.addStretch()

    def _format_industry(self, company):
        """格式化行业信息"""
        cats = []
        for i in range(1, 5):
            cat = company.get(f'categoryNameLv{i}')
            if cat:
                cats.append(cat)
        return ' > '.join(cats) if cats else "未知"

    def _apply_theme(self, dark_mode: bool):
        self._dark_mode = dark_mode
        if dark_mode:
            colors = {
                "bg": "#1e1e2e",
                "panel": "#242736",
                "border": "#45475a",
                "text": "#cdd6f4",
                "muted": "#a6adc8",
                "accent": "#89b4fa",
                "header_bg": "#313244",
                "table_bg": "#1e1e2e",
                "table_alt": "#2a2f3a",
                "selection_bg": "#89b4fa",
                "selection_text": "#1e1e2e",
                "hover_bg": "#3a3f54",
                "scroll_track": "rgba(49, 50, 68, 0.2)",
                "scroll_handle": "rgba(69, 71, 90, 0.7)",
                "danger": "#f38ba8",
            }
        else:
            colors = {
                "bg": "#ffffff",
                "panel": "#f8f9fa",
                "border": "#dee2e6",
                "text": "#343a40",
                "muted": "#6c757d",
                "accent": "#0d6efd",
                "header_bg": "#f1f3f5",
                "table_bg": "#ffffff",
                "table_alt": "#f8f9fa",
                "selection_bg": "#0d6efd",
                "selection_text": "#ffffff",
                "hover_bg": "#e9ecef",
                "scroll_track": "rgba(220, 220, 220, 0.2)",
                "scroll_handle": "rgba(180, 180, 180, 0.7)",
                "danger": "#dc3545",
            }

        self.setStyleSheet(f"""
            QScrollArea[class="enterprise-info"] {{
                background-color: {colors["bg"]};
                border: none;
            }}
            QScrollArea[class="enterprise-info"] > QWidget > QWidget {{
                background-color: {colors["bg"]};
            }}
            QWidget[class="enterprise-info-content"] {{
                background-color: {colors["bg"]};
            }}
            QGroupBox[class="info-section"] {{
                border: 1px solid {colors["border"]};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 14px;
                font-weight: bold;
                color: {colors["accent"]};
                background-color: {colors["panel"]};
            }}
            QGroupBox[class="info-section"]::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                left: 10px;
                color: {colors["accent"]};
            }}
            QLabel[class="info-header"] {{
                color: {colors["accent"]};
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 8px;
            }}
            QLabel[class="info-muted"] {{
                color: {colors["muted"]};
                font-size: 16px;
                margin-top: 50px;
            }}
            QLabel[class="info-loading"] {{
                color: {colors["accent"]};
                font-size: 16px;
                margin-top: 50px;
                font-weight: bold;
            }}
            QLabel[class="info-error"] {{
                color: {colors["danger"]};
                font-size: 16px;
                font-weight: bold;
            }}
            QLabel[class="info-label"] {{
                color: {colors["muted"]};
                font-weight: bold;
            }}
            QLabel[class="info-value"] {{
                color: {colors["text"]};
            }}
            QTableWidget {{
                background-color: {colors["table_bg"]};
                alternate-background-color: {colors["table_alt"]};
                color: {colors["text"]};
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                gridline-color: {colors["border"]};
            }}
            QTableWidget::item {{
                background-color: {colors["table_bg"]};
                color: {colors["text"]};
                padding: 6px;
                border: none;
            }}
            QTableWidget::item:alternate {{
                background-color: {colors["table_alt"]};
            }}
            QTableWidget::item:selected {{
                background-color: {colors["selection_bg"]};
                color: {colors["selection_text"]};
            }}
            QTableWidget::item:hover {{
                background-color: {colors["hover_bg"]};
            }}
            QHeaderView::section {{
                background-color: {colors["header_bg"]};
                color: {colors["text"]};
                padding: 6px;
                border: 1px solid {colors["border"]};
            }}
            QTableCornerButton::section {{
                background-color: {colors["header_bg"]};
                border: 1px solid {colors["border"]};
            }}
            QAbstractScrollArea::corner {{
                background-color: {colors["header_bg"]};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {colors["scroll_track"]};
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {colors["scroll_handle"]};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: {colors["scroll_track"]};
                height: 10px;
                margin: 0px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background: {colors["scroll_handle"]};
                min-width: 20px;
                border-radius: 5px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)
