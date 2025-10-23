#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信息收集模块主UI组件
整合企业查询和资产查询功能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox, QPushButton,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QRadioButton, QFileDialog, QMessageBox, QScrollArea, QGridLayout,
    QListWidget, QTreeWidget, QTreeWidgetItem, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor

# 使用绝对导入
from modules.Information_Gathering.Enterprise_Query.enterprise_query_ui import EnterpriseQueryUI
from .Asset_Mapping.asset_mapping_ui import AssetMappingUI
from .Threat_Intelligence.threat_intelligence_ui import ThreatIntelligenceUI
from typing import Dict, List, Optional
import logging


class InformationGatheringUI(QWidget):
    """信息收集主UI组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.logger = logging.getLogger(__name__)
        
        # 初始化子组件
        self.enterprise_query_ui = None
        self.asset_mapping_ui = None
        self.threat_intelligence_ui = None
        
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        
        # 创建主要内容区域（移除标题区域以节省空间）
        content_widget = self.create_content_section()
        main_layout.addWidget(content_widget)
    

    
    def create_content_section(self) -> QWidget:
        """创建主要内容区域"""
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建子标签页
        self.tab_widget = QTabWidget()
        # 移除硬编码样式，使用全局样式
        
        # 创建企业查询标签页
        self.create_enterprise_query_tab()
        
        # 创建资产查询标签页
        self.create_asset_mapping_tab()
        
        # 创建威胁情报标签页
        self.create_threat_intelligence_tab()
        
        content_layout.addWidget(self.tab_widget)
        return content_widget
    
    def create_enterprise_query_tab(self):
        """创建企业查询标签页"""
        try:
            self.enterprise_query_ui = EnterpriseQueryUI(self)
            self.tab_widget.addTab(self.enterprise_query_ui, "🏢 企业查询")
        except Exception as e:
            self.logger.error(f"创建企业查询标签页失败: {e}")
            # 创建占位符
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            label = QLabel(f"企业查询模块加载失败: {str(e)}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            self.tab_widget.addTab(placeholder, "🏢 企业查询")
    
    def create_asset_mapping_tab(self):
        """创建资产查询标签页"""
        try:
            self.asset_mapping_ui = AssetMappingUI(self)
            self.tab_widget.addTab(self.asset_mapping_ui, "🌐 资产查询")
        except Exception as e:
            self.logger.error(f"创建资产查询标签页失败: {e}")
            # 创建占位符
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            label = QLabel(f"资产查询模块加载失败: {str(e)}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            self.tab_widget.addTab(placeholder, "🌐 资产查询")
    
    def create_threat_intelligence_tab(self):
        """创建威胁情报标签页"""
        try:
            self.threat_intelligence_ui = ThreatIntelligenceUI(self)
            self.tab_widget.addTab(self.threat_intelligence_ui, "🛡️ 威胁情报")
        except Exception as e:
            self.logger.error(f"创建威胁情报标签页失败: {e}")
            # 创建占位符
            placeholder = QWidget()
            layout = QVBoxLayout(placeholder)
            label = QLabel(f"威胁情报模块加载失败: {str(e)}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            self.tab_widget.addTab(placeholder, "🛡️ 威胁情报")
    
    def setup_connections(self):
        """设置信号连接"""
        # 这里可以添加子组件之间的信号连接
        pass
    
    def get_config(self) -> Dict:
        """获取配置信息"""
        config = {}
        
        if self.enterprise_query_ui:
            config['enterprise'] = self.enterprise_query_ui.get_config()
        
        if self.asset_mapping_ui:
            config['asset'] = self.asset_mapping_ui.get_config()
        
        if self.threat_intelligence_ui:
            config['threat_intelligence'] = self.threat_intelligence_ui.get_config()
        
        return config
    
    def set_config(self, config: Dict):
        """设置配置信息"""
        if self.enterprise_query_ui and 'enterprise' in config:
            self.enterprise_query_ui.set_config(config['enterprise'])
        
        if self.asset_mapping_ui and 'asset' in config:
            self.asset_mapping_ui.set_config(config['asset'])
        
        if self.threat_intelligence_ui and 'threat_intelligence' in config:
            self.threat_intelligence_ui.set_config(config['threat_intelligence'])
    
    def export_results(self, file_path: Optional[str] = None) -> bool:
        """导出所有结果"""
        try:
            if not file_path:
                file_path, _ = QFileDialog.getSaveFileName(
                    self, "导出信息收集结果", "",
                    "Excel files (*.xlsx);;JSON files (*.json);;All files (*.*)"
                )
            
            if not file_path:
                return False
            
            # 收集所有结果
            all_results = {
                'enterprise_results': [],
                'asset_results': [],
                'threat_intelligence_results': []
            }
            
            if self.enterprise_query_ui:
                all_results['enterprise_results'] = self.enterprise_query_ui.get_all_results()
            
            if self.asset_mapping_ui:
                all_results['asset_results'] = self.asset_mapping_ui.get_all_results()
            
            if self.threat_intelligence_ui:
                all_results['threat_intelligence_results'] = self.threat_intelligence_ui.get_all_results()
            
            # 根据文件扩展名选择导出格式
            if file_path.endswith('.xlsx'):
                return self._export_to_excel(all_results, file_path)
            elif file_path.endswith('.json'):
                return self._export_to_json(all_results, file_path)
            else:
                return self._export_to_text(all_results, file_path)
                
        except Exception as e:
            self.logger.error(f"导出结果失败: {e}")
            QMessageBox.critical(self, "错误", f"导出结果失败: {str(e)}")
            return False
    
    def _export_to_excel(self, results: Dict, file_path: str) -> bool:
        """导出到Excel文件"""
        try:
            import pandas as pd
            
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # 导出企业查询结果
                if results['enterprise_results']:
                    enterprise_df = pd.DataFrame(results['enterprise_results'])
                    enterprise_df.to_excel(writer, sheet_name='企业查询结果', index=False)
                
                # 导出资产查询结果
                if results['asset_results']:
                    asset_df = pd.DataFrame(results['asset_results'])
                    asset_df.to_excel(writer, sheet_name='资产查询结果', index=False)
            
            return True
        except Exception as e:
            self.logger.error(f"导出Excel失败: {e}")
            return False
    
    def _export_to_json(self, results: Dict, file_path: str) -> bool:
        """导出到JSON文件"""
        try:
            import json
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            self.logger.error(f"导出JSON失败: {e}")
            return False
    
    def _export_to_text(self, results: Dict, file_path: str) -> bool:
        """导出到文本文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("信息收集结果汇总\n")
                f.write("=" * 50 + "\n\n")
                
                # 写入企业查询结果
                if results['enterprise_results']:
                    f.write("企业查询结果:\n")
                    f.write("-" * 30 + "\n")
                    for i, result in enumerate(results['enterprise_results'], 1):
                        f.write(f"{i}. {result}\n")
                    f.write("\n")
                
                # 写入资产查询结果
                if results['asset_results']:
                    f.write("资产查询结果:\n")
                    f.write("-" * 30 + "\n")
                    for i, result in enumerate(results['asset_results'], 1):
                        f.write(f"{i}. {result}\n")
                    f.write("\n")
            
            return True
        except Exception as e:
            self.logger.error(f"导出文本失败: {e}")
            return False
    
    def clear_all_results(self):
        """清空所有结果"""
        if self.enterprise_query_ui:
            self.enterprise_query_ui.clear_results()
        
        if self.asset_mapping_ui:
            self.asset_mapping_ui.clear_results()
        
        if self.threat_intelligence_ui:
            self.threat_intelligence_ui.clear_results()


def main():
    """测试函数"""
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    window = InformationGatheringUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()