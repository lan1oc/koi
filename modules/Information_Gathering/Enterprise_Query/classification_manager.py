#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类管理UI组件

提供对 1.txt 分类文件的可视化管理功能（增删改查）
"""

import os
import re
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, 
    QPushButton, QLabel, QInputDialog, QMessageBox, QGroupBox,
    QListWidgetItem, QMenu, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal
import logging
from modules.utils.resource_path import get_resource_path

# 复用 group_folders.py 中的正则和关键字逻辑
# 但为了解耦，这里重新定义一套核心逻辑，或者可以尝试导入
# 考虑到 group_folders.py 主要是脚本逻辑，这里独立实现更清晰

class ClassificationManager:
    """分类文件数据管理器"""
    
    def __init__(self, file_path=None):
        self.file_path = file_path or get_resource_path('1.txt')
        self.groups = {}  # {group_name: [company_list]}
        self.group_order = []  # 保持原有顺序
        self.logger = logging.getLogger(__name__)
        self.load()
    
    def load(self):
        """加载分类文件"""
        self.groups = {}
        self.group_order = []
        
        if not os.path.exists(self.file_path):
            self.logger.warning(f"分类文件不存在: {self.file_path}")
            return

        try:
            current_group = "未分组"
            if current_group not in self.group_order:
                self.group_order.append(current_group)
            self.groups[current_group] = []
            
            with open(self.file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 简单判断：如果是一般公司特征词，则视为公司，否则视为分组名
                    # 注意：这里需要与 group_folders.py 的逻辑保持某种程度的一致
                    # 但为了通用性，我们假设用户编辑的文件格式是：
                    # 分组名
                    # 公司1
                    # 公司2
                    if self._is_company(line):
                        if current_group not in self.groups:
                            self.groups[current_group] = []
                        self.groups[current_group].append(line)
                    else:
                        current_group = line
                        if current_group not in self.group_order:
                            self.group_order.append(current_group)
                        if current_group not in self.groups:
                            self.groups[current_group] = []
                            
        except Exception as e:
            self.logger.error(f"加载分类文件失败: {e}")
            


    def save(self):
        """保存到文件"""
        try:
            # 确保目录存在
            file_path = Path(self.file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.file_path, 'w', encoding='utf-8') as f:
                for group in self.group_order:
                    companies = self.groups.get(group, [])
                    # 如果分组是"未分组"且该组为空，可以跳过不写（或者是放在最前面）
                    if group == "未分组" and not companies:
                        continue
                        
                    # 写入分组名
                    f.write(f"{group}\n")
                    
                    # 写入该组下的公司
                    for company in companies:
                        f.write(f"{company}\n")
                    
                    # 分组间空行分隔
                    f.write("\n") 
                    
            self.logger.info(f"分类文件保存成功: {self.file_path}")
            return True
        except Exception as e:
            self.logger.error(f"保存分类文件失败: {e}")
            return False

    def _is_company(self, text: str) -> bool:
        """判断是否为公司名（简单规则：包含特定后缀或关键字）"""
        keywords = [
            "公司", "集团", "股份", "厂", "店", "中心", "所", "院", "校", "行", "社", "场", "室",
            "局", "厅", "处", "署", "队", "站", "网",
            "超市", "商行", "经营部", "便利店", "饭店", "酒店", "宾馆", "旅馆",
            "网吧", "俱乐部", "棋牌", "会所", "KTV", "吧",
            "委员会", "协会", "党支部", "联合会",
            "小学", "中学", "初中", "高中", "大学", "幼儿园", "托儿所"
        ]
        return any(k in text for k in keywords)

    def add_group(self, group_name):
        if group_name in self.groups:
            return False, "分组已存在"
        self.groups[group_name] = []
        self.group_order.append(group_name)
        return True, ""
    
    def rename_group(self, old_name, new_name):
        if new_name in self.groups:
            return False, "新分组名已存在"
        if old_name not in self.groups:
            return False, "原分组不存在"
            
        # 保持顺序
        idx = self.group_order.index(old_name)
        self.group_order[idx] = new_name
        self.groups[new_name] = self.groups.pop(old_name)
        return True, ""
        
    def delete_group(self, group_name):
        if group_name not in self.groups:
            return False
        del self.groups[group_name]
        if group_name in self.group_order:
            self.group_order.remove(group_name)
        return True

    def add_company(self, group_name, company_name):
        if group_name not in self.groups:
            return False, "分组不存在"
        if company_name in self.groups[group_name]:
            return False, "该公司已在此分组中"
        self.groups[group_name].append(company_name)
        return True, ""
        
    def update_company(self, group_name, old_name, new_name):
        """更新公司名称"""
        if group_name not in self.groups:
            return False, "分组不存在"
        if old_name not in self.groups[group_name]:
            return False, "原公司不存在"
        if new_name in self.groups[group_name]:
            return False, "新名称已存在"
            
        # 保持位置不变
        idx = self.groups[group_name].index(old_name)
        self.groups[group_name][idx] = new_name
        return True, ""

    def remove_company(self, group_name, company_name):
        if group_name in self.groups and company_name in self.groups[group_name]:
            self.groups[group_name].remove(company_name)
            return True
        return False
        
    def move_company(self, company_name, old_group, new_group):
        if self.remove_company(old_group, company_name):
            return self.add_company(new_group, company_name)
        return False, "移动失败"


class ClassificationManagerUI(QWidget):
    """分类管理UI"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = ClassificationManager()
        self.init_ui()
        self.refresh_data()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 顶部工具栏
        toolbar = QHBoxLayout()
        self.status_label = QLabel(f"当前文件: {self.manager.file_path}")
        # 如果文件不存在，显示警告色
        if not os.path.exists(self.manager.file_path):
            self.status_label.setStyleSheet("color: red")
            self.status_label.setText(f"文件不存在 (保存后自动创建): {self.manager.file_path}")
            
        save_btn = QPushButton("💾 保存更改")
        save_btn.clicked.connect(self.save_data)
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh_data)
        
        toolbar.addWidget(self.status_label)
        toolbar.addStretch()
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(save_btn)
        layout.addLayout(toolbar)
        
        # 主分割区域
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：分组列表
        group_widget = QWidget()
        group_layout = QVBoxLayout(group_widget)
        group_layout.setContentsMargins(0, 0, 0, 0)
        
        group_header = QHBoxLayout()
        group_header.addWidget(QLabel("📂 分组列表 (双击修改)"))
        add_group_btn = QPushButton("➕")
        add_group_btn.setFixedSize(24, 24)
        add_group_btn.setToolTip("添加分组")
        add_group_btn.clicked.connect(self.add_group)
        group_header.addWidget(add_group_btn)
        group_layout.addLayout(group_header)
        
        self.group_list = QListWidget()
        self.group_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_list.customContextMenuRequested.connect(self.show_group_menu)
        self.group_list.currentItemChanged.connect(self.on_group_selected)
        self.group_list.itemDoubleClicked.connect(self.rename_current_group) # 双击修改
        group_layout.addWidget(self.group_list)
        
        # 右侧：公司列表
        company_widget = QWidget()
        company_layout = QVBoxLayout(company_widget)
        company_layout.setContentsMargins(0, 0, 0, 0)
        
        company_header = QHBoxLayout()
        self.company_label = QLabel("🏢 企业列表 (双击修改)")
        company_header.addWidget(self.company_label)
        add_comp_btn = QPushButton("➕")
        add_comp_btn.setFixedSize(24, 24)
        add_comp_btn.setToolTip("添加企业")
        add_comp_btn.clicked.connect(self.add_company)
        company_header.addWidget(add_comp_btn)
        company_layout.addLayout(company_header)
        
        self.company_list = QListWidget()
        self.company_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.company_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.company_list.customContextMenuRequested.connect(self.show_company_menu)
        self.company_list.itemDoubleClicked.connect(self.edit_current_company) # 双击修改
        company_layout.addWidget(self.company_list)
        
        splitter.addWidget(group_widget)
        splitter.addWidget(company_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
        
    def refresh_data(self):
        """刷新数据"""
        self.manager.load()
        self.group_list.clear()
        self.company_list.clear()
        self.company_label.setText("🏢 企业列表")
        
        # 恢复文件状态显示
        if os.path.exists(self.manager.file_path):
            self.status_label.setStyleSheet("")
            self.status_label.setText(f"当前文件: {self.manager.file_path}")
        
        for group in self.manager.group_order:
            item = QListWidgetItem(group)
            # 显示该组下的企业数量
            count = len(self.manager.groups.get(group, []))
            item.setText(f"{group} ({count})")
            item.setData(Qt.UserRole, group)  # 存储原始分组名
            self.group_list.addItem(item)
            
    def save_data(self):
        """保存数据"""
        if self.manager.save():
            QMessageBox.information(self, "成功", "保存成功！")
            self.refresh_data()
        else:
            QMessageBox.critical(self, "错误", "保存失败，请检查文件权限或日志。")

    def on_group_selected(self, current, previous):
        if not current:
            self.company_list.clear()
            self.company_label.setText("🏢 企业列表")
            return
            
        group_name = current.data(Qt.UserRole)
        self.company_label.setText(f"🏢 企业列表 - {group_name}")
        self.load_companies(group_name)
        
    def load_companies(self, group_name):
        self.company_list.clear()
        companies = self.manager.groups.get(group_name, [])
        for comp in companies:
            self.company_list.addItem(comp)
            
    def add_group(self):
        name, ok = QInputDialog.getText(self, "添加分组", "请输入分组名称:")
        if ok and name.strip():
            success, msg = self.manager.add_group(name.strip())
            if success:
                self.refresh_data()
                # 选中新添加的项
                items = self.group_list.findItems(name.strip(), Qt.MatchFlag.MatchStartsWith)
                if items:
                    self.group_list.setCurrentItem(items[0])
            else:
                QMessageBox.warning(self, "错误", msg)

    def rename_current_group(self, item):
        """重命名当前双击的分组"""
        if not item: return
        group_name = item.data(Qt.UserRole)
        new_name, ok = QInputDialog.getText(self, "重命名分组", "新名称:", text=group_name)
        if ok and new_name.strip():
            success, msg = self.manager.rename_group(group_name, new_name.strip())
            if success:
                self.refresh_data()
            else:
                QMessageBox.warning(self, "错误", msg)

    def show_group_menu(self, pos):
        item = self.group_list.itemAt(pos)
        if not item:
            return
            
        menu = QMenu()
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        
        action = menu.exec(self.group_list.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_current_group(item)
                    
        elif action == delete_action:
            group_name = item.data(Qt.UserRole)
            reply = QMessageBox.question(
                self, "确认删除", 
                f"确定要删除分组 '{group_name}' 及其下所有企业吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.manager.delete_group(group_name)
                self.refresh_data()

    def add_company(self):
        current_group_item = self.group_list.currentItem()
        if not current_group_item:
            QMessageBox.warning(self, "警告", "请先选择一个分组")
            return
            
        group_name = current_group_item.data(Qt.UserRole)
        
        text, ok = QInputDialog.getMultiLineText(self, "添加企业", "请输入企业名称(每行一个):")
        if ok and text.strip():
            companies = [line.strip() for line in text.split('\n') if line.strip()]
            added_count = 0
            for comp in companies:
                success, _ = self.manager.add_company(group_name, comp)
                if success:
                    added_count += 1
            
            self.refresh_data()
            # 保持选中
            items = self.group_list.findItems(group_name, Qt.MatchFlag.MatchStartsWith)
            if items:
                self.group_list.setCurrentItem(items[0])
            
            self.statusBar().showMessage(f"成功添加 {added_count} 个企业", 3000)

    def edit_current_company(self, item):
        """编辑当前双击的公司"""
        if not item: return
        
        current_group_item = self.group_list.currentItem()
        if not current_group_item: return
        group_name = current_group_item.data(Qt.UserRole)
        
        old_name = item.text()
        new_name, ok = QInputDialog.getText(self, "修改企业名称", "新名称:", text=old_name)
        
        if ok and new_name.strip():
            if new_name.strip() == old_name: return
            
            success, msg = self.manager.update_company(group_name, old_name, new_name.strip())
            if success:
                item.setText(new_name.strip())
            else:
                QMessageBox.warning(self, "错误", msg)

    def show_company_menu(self, pos):
        items = self.company_list.selectedItems()
        if not items:
            return
            
        menu = QMenu()
        edit_action = None
        if len(items) == 1:
            edit_action = menu.addAction("✏️ 修改名称")
            
        delete_action = menu.addAction(f"🗑️ 删除选中 ({len(items)})")
        move_menu = menu.addMenu("🚚 移动到...")
        
        # 获取其他分组列表
        current_group_item = self.group_list.currentItem()
        current_group = current_group_item.data(Qt.UserRole) if current_group_item else None
        
        for group in self.manager.group_order:
            if group != current_group:
                action = move_menu.addAction(group)
                action.setData(group)
        
        action = menu.exec(self.company_list.mapToGlobal(pos))
        
        if edit_action and action == edit_action:
            self.edit_current_company(items[0])
            
        elif action == delete_action:
            if QMessageBox.yes == QMessageBox.question(self, "确认", f"确定删除选中的 {len(items)} 个企业吗？"):
                for item in items:
                    self.manager.remove_company(current_group, item.text())
                self.load_companies(current_group)
                self.refresh_gui_counts()
                
        elif action in move_menu.actions():
            target_group = action.data()
            for item in items:
                self.manager.move_company(item.text(), current_group, target_group)
            self.load_companies(current_group)
            self.refresh_gui_counts()

    def refresh_gui_counts(self):
        """仅更新左侧列表的计数，保持选中状态"""
        current_row = self.group_list.currentRow()
        self.group_list.clear()
        for group in self.manager.group_order:
            item = QListWidgetItem(group)
            count = len(self.manager.groups.get(group, []))
            item.setText(f"{group} ({count})")
            item.setData(Qt.UserRole, group)
            self.group_list.addItem(item)
        if current_row >= 0:
            self.group_list.setCurrentRow(current_row)

    def statusBar(self):
        # 简单查找主窗口的状态栏，找不到就算了
        w = self.window()
        if hasattr(w, "statusBar"):
            return w.statusBar()
        return type("MockStatus", (), {"showMessage": lambda *a: None})()
