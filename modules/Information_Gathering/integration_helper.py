#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信息收集模块集成助手
用于将模块化的信息收集功能集成到主程序中
"""

from PySide6.QtWidgets import QTabWidget, QWidget, QVBoxLayout, QMessageBox
from typing import Optional
import logging


def integrate_information_gathering_to_main_window(main_window) -> bool:
    """
    将信息收集功能集成到主窗口
    
    Args:
        main_window: 主窗口实例
        
    Returns:
        bool: 集成是否成功
    """
    try:
        # 检查主窗口是否有tab_widget属性
        if not hasattr(main_window, 'tab_widget'):
            logging.error("主窗口缺少tab_widget属性")
            return False
        
        # 导入信息收集UI组件
        from .information_gathering_ui import InformationGatheringUI
        
        # 创建信息收集UI实例
        info_gathering_ui = InformationGatheringUI(main_window)
        
        # 加载配置文件并设置到子组件
        if hasattr(main_window, 'load_unified_config'):
            config = main_window.load_unified_config()
            if config:
                # 转换配置格式以适配信息收集模块
                info_config = {
                    'enterprise': {
                        'tianyancha_cookie': config.get('tyc', {}).get('cookie', ''),
                        'aiqicha_cookie': config.get('aiqicha', {}).get('cookie', '')
                    },
                    'asset': {
                        'fofa_api_key': config.get('fofa', {}).get('api_key', ''),
                        'fofa_email': config.get('fofa', {}).get('email', ''),
                        'hunter_api_key': config.get('hunter', {}).get('api_key', ''),
                        'quake_api_key': config.get('quake', {}).get('api_key', '')
                    }
                }
                info_gathering_ui.set_config(info_config)
        
        # 将信息收集标签页添加到主窗口
        main_window.tab_widget.addTab(info_gathering_ui, "🔍 信息收集")
        
        # 保存引用以便后续使用
        main_window.information_gathering_ui = info_gathering_ui
        
        logging.info("信息收集模块集成成功")
        return True
        
    except ImportError as e:
        logging.error(f"导入信息收集模块失败: {e}")
        return False
    except Exception as e:
        logging.error(f"集成信息收集模块失败: {e}")
        return False


def integrate_information_gathering_to_tab_widget(tab_widget: QTabWidget) -> bool:
    """
    将信息收集功能集成到指定的标签页控件
    
    Args:
        tab_widget: 标签页控件实例
        
    Returns:
        bool: 集成是否成功
    """
    try:
        # 导入信息收集UI组件
        from .information_gathering_ui import InformationGatheringUI
        
        # 创建信息收集UI实例
        info_gathering_ui = InformationGatheringUI()
        
        # 将信息收集标签页添加到标签页控件
        tab_widget.addTab(info_gathering_ui, "🔍 信息收集")
        
        logging.info("信息收集模块集成到标签页控件成功")
        return True
        
    except ImportError as e:
        logging.error(f"导入信息收集模块失败: {e}")
        return False
    except Exception as e:
        logging.error(f"集成信息收集模块到标签页控件失败: {e}")
        return False


def create_standalone_information_gathering_window(parent=None) -> Optional[QWidget]:
    """
    创建独立的信息收集窗口
    
    Args:
        parent: 父窗口
        
    Returns:
        QWidget: 信息收集窗口实例，失败时返回None
    """
    try:
        # 导入信息收集UI组件
        from .information_gathering_ui import InformationGatheringUI
        
        # 创建信息收集UI实例
        info_gathering_ui = InformationGatheringUI(parent)
        info_gathering_ui.setWindowTitle("信息收集工具")
        info_gathering_ui.resize(1200, 800)
        
        logging.info("创建独立信息收集窗口成功")
        return info_gathering_ui
        
    except ImportError as e:
        logging.error(f"导入信息收集模块失败: {e}")
        return None
    except Exception as e:
        logging.error(f"创建独立信息收集窗口失败: {e}")
        return None


def get_information_gathering_config() -> dict:
    """
    获取信息收集模块的默认配置
    
    Returns:
        dict: 配置字典
    """
    return {
        'enterprise_query': {
            'tianyancha_cookie': '',
            'aiqicha_cookie': ''
        },
        'asset_mapping': {
            'fofa_api_key': '',
            'hunter_api_key': '',
            'quake_api_key': ''
        },
        'unified_search': {
            'default_platforms': ['fofa', 'hunter', 'quake'],
            'default_limit': 100,
            'enable_debug': False
        }
    }


def validate_information_gathering_config(config: dict) -> bool:
    """
    验证信息收集模块配置
    
    Args:
        config: 配置字典
        
    Returns:
        bool: 配置是否有效
    """
    try:
        # 检查必要的配置项
        required_sections = ['enterprise_query', 'asset_mapping', 'unified_search']
        
        for section in required_sections:
            if section not in config:
                logging.warning(f"配置缺少必要部分: {section}")
                return False
        
        # 检查企业查询配置
        enterprise_config = config['enterprise_query']
        if not isinstance(enterprise_config, dict):
            logging.warning("企业查询配置格式错误")
            return False
        
        # 检查资产查询配置
        asset_config = config['asset_mapping']
        if not isinstance(asset_config, dict):
            logging.warning("资产查询配置格式错误")
            return False
        
        # 检查统一查询配置
        unified_config = config['unified_search']
        if not isinstance(unified_config, dict):
            logging.warning("统一查询配置格式错误")
            return False
        
        logging.info("信息收集模块配置验证通过")
        return True
        
    except Exception as e:
        logging.error(f"验证信息收集模块配置失败: {e}")
        return False


def migrate_legacy_information_gathering_data(legacy_data: dict) -> dict:
    """
    迁移旧版本的信息收集数据到新的模块化格式
    
    Args:
        legacy_data: 旧版本数据
        
    Returns:
        dict: 迁移后的数据
    """
    try:
        migrated_data = {
            'enterprise_results': [],
            'asset_results': [],
            'unified_results': {},
            'migration_info': {
                'migrated_at': str(datetime.now()),
                'source_version': 'legacy'
            }
        }
        
        # 迁移企业查询结果
        if 'tianyancha_results' in legacy_data:
            for result in legacy_data['tianyancha_results']:
                result['source'] = 'tianyancha'
                result['migrated'] = True
                migrated_data['enterprise_results'].append(result)
        
        if 'aiqicha_results' in legacy_data:
            for result in legacy_data['aiqicha_results']:
                result['source'] = 'aiqicha'
                result['migrated'] = True
                migrated_data['enterprise_results'].append(result)
        
        # 迁移资产查询结果
        for platform in ['fofa', 'hunter', 'quake']:
            platform_key = f'{platform}_results'
            if platform_key in legacy_data:
                for result in legacy_data[platform_key]:
                    result['source'] = platform
                    result['migrated'] = True
                    migrated_data['asset_results'].append(result)
        
        # 迁移统一查询结果
        if 'unified_results' in legacy_data:
            migrated_data['unified_results'] = legacy_data['unified_results']
        
        logging.info(f"成功迁移 {len(migrated_data['enterprise_results'])} 个企业查询结果")
        logging.info(f"成功迁移 {len(migrated_data['asset_results'])} 个资产查询结果")
        
        return migrated_data
        
    except Exception as e:
        logging.error(f"迁移旧版本信息收集数据失败: {e}")
        return {}


def export_information_gathering_results(results: dict, file_path: str, format_type: str = 'excel') -> bool:
    """
    导出信息收集结果
    
    Args:
        results: 结果数据
        file_path: 导出文件路径
        format_type: 导出格式 ('excel', 'json', 'csv')
        
    Returns:
        bool: 导出是否成功
    """
    try:
        if format_type == 'excel':
            return _export_to_excel(results, file_path)
        elif format_type == 'json':
            return _export_to_json(results, file_path)
        elif format_type == 'csv':
            return _export_to_csv(results, file_path)
        else:
            logging.error(f"不支持的导出格式: {format_type}")
            return False
            
    except Exception as e:
        logging.error(f"导出信息收集结果失败: {e}")
        return False


def _export_to_excel(results: dict, file_path: str) -> bool:
    """
    导出到Excel文件
    """
    try:
        import pandas as pd
        
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # 导出企业查询结果
            if 'enterprise_results' in results and results['enterprise_results']:
                enterprise_df = pd.DataFrame(results['enterprise_results'])
                enterprise_df.to_excel(writer, sheet_name='企业查询结果', index=False)
            
            # 导出资产查询结果
            if 'asset_results' in results and results['asset_results']:
                asset_df = pd.DataFrame(results['asset_results'])
                asset_df.to_excel(writer, sheet_name='资产查询结果', index=False)
            
            # 导出统一查询结果
            if 'unified_results' in results and results['unified_results']:
                unified_data = []
                for query, platforms_results in results['unified_results'].items():
                    for platform, platform_result in platforms_results.items():
                        if platform_result.get('success', False) and 'results' in platform_result:
                            for item in platform_result['results']:
                                if isinstance(item, dict):
                                    item_copy = item.copy()
                                    item_copy['query'] = query
                                    item_copy['platform'] = platform
                                    unified_data.append(item_copy)
                
                if unified_data:
                    unified_df = pd.DataFrame(unified_data)
                    unified_df.to_excel(writer, sheet_name='统一查询结果', index=False)
        
        return True
        
    except Exception as e:
        logging.error(f"导出Excel文件失败: {e}")
        return False


def _export_to_json(results: dict, file_path: str) -> bool:
    """
    导出到JSON文件
    """
    try:
        import json
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        logging.error(f"导出JSON文件失败: {e}")
        return False


def _export_to_csv(results: dict, file_path: str) -> bool:
    """
    导出到CSV文件
    """
    try:
        import pandas as pd
        
        # 合并所有结果
        all_data = []
        
        # 添加企业查询结果
        if 'enterprise_results' in results:
            all_data.extend(results['enterprise_results'])
        
        # 添加资产查询结果
        if 'asset_results' in results:
            all_data.extend(results['asset_results'])
        
        # 添加统一查询结果
        if 'unified_results' in results:
            for query, platforms_results in results['unified_results'].items():
                for platform, platform_result in platforms_results.items():
                    if platform_result.get('success', False) and 'results' in platform_result:
                        for item in platform_result['results']:
                            if isinstance(item, dict):
                                item_copy = item.copy()
                                item_copy['query'] = query
                                item_copy['platform'] = platform
                                all_data.append(item_copy)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
        
        return True
        
    except Exception as e:
        logging.error(f"导出CSV文件失败: {e}")
        return False


# 导入datetime用于迁移功能
from datetime import datetime


def main():
    """测试函数"""
    print("信息收集模块集成助手加载成功")
    
    # 测试配置验证
    test_config = get_information_gathering_config()
    is_valid = validate_information_gathering_config(test_config)
    print(f"默认配置验证结果: {is_valid}")


if __name__ == "__main__":
    main()