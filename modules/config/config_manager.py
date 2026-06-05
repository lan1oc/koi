#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一配置管理器

提供统一的配置加载、保存和管理功能
"""

import os
import sys
import json
import shutil
from datetime import datetime
from typing import Dict, Any, Optional
import logging


class ConfigManager:
    """统一配置管理器"""

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_file: 配置文件路径，默认为项目根目录下的config.json
        """
        self.logger = logging.getLogger(__name__)

        if config_file:
            self.config_file = config_file
        else:
            # 获取应用程序目录（兼容PyInstaller打包）
            app_dir = self._get_app_directory()
            self.config_file = os.path.join(app_dir, 'config.json')

        self._config = None
        self._default_config = self._get_default_config()

        if getattr(sys, 'frozen', False) and not os.path.exists(self.config_file):
            try:
                config_dir = os.path.dirname(self.config_file)
                if config_dir and not os.path.exists(config_dir):
                    os.makedirs(config_dir, exist_ok=True)
                bundled_config = None
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass:
                    bundled_config = os.path.join(meipass, 'config.json')
                if bundled_config and os.path.exists(bundled_config):
                    shutil.copy2(bundled_config, self.config_file)
                else:
                    with open(self.config_file, 'w', encoding='utf-8') as f:
                        json.dump(self._default_config, f, indent=2, ensure_ascii=False)
                self._remove_app_version_from_file()
                self.logger.info(f"已释放默认配置文件到: {self.config_file}")
            except Exception as e:
                self.logger.error(f"创建默认配置文件失败: {e}")

    def _get_app_directory(self) -> str:
        """
        获取应用程序目录
        兼容PyInstaller打包后的环境
        """
        env_data_dir = os.environ.get('KOI_USER_DATA_DIR')
        if env_data_dir:
            return os.path.abspath(env_data_dir)

        try:
            from modules.utils.resource_path import get_app_dir

            return str(get_app_dir())
        except Exception:
            pass

        env_app_dir = os.environ.get('KOI_APP_DIR')
        if env_app_dir:
            return os.path.abspath(env_app_dir)

        if getattr(sys, 'frozen', False):
            # PyInstaller打包后的环境
            app_dir = os.path.dirname(sys.executable)
            if os.path.basename(app_dir).lower() in {'koi-backend', 'koi_backend'}:
                parent_dir = os.path.dirname(app_dir)
                if parent_dir:
                    return parent_dir
        else:
            # 开发环境
            app_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        return app_dir

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'hunter': {
                'api_key': '',
                'last_updated': ''
            },
            'quake': {
                'api_key': '',
                'last_updated': ''
            },
            'fofa': {
                'email': '',
                'api_key': '',
                'last_updated': ''
            },
            'aiqicha': {
                'cookie': '',
                'xunkebao_cookie': '',
                'last_updated': ''
            },
            'tyc': {
                'cookie': '',
                'last_updated': ''
            },
            'ui': {
                'theme': 'default',
                'window_size': {'width': 1400, 'height': 900},
                'window_position': {'x': -1, 'y': -1},
                'dark_mode': False,
                'last_updated': ''
            },
            'ui_settings': {
                'dark_mode': False,
                'close_to_tray': False,
                'last_updated': ''
            },
            'app': {
                'first_run': True,
                'last_updated': ''
            },
            'report_counters': {
                'notification_number': 1,
                'rectification_number': 1,
                # 不可用编号：当编号递增/取号命中这些数字时自动跳过
                # 例如设置 [170]，则 169 → 171
                # 分别维护通报与责令整改两套列表
                'unavailable_notification_numbers': [],
                'unavailable_rectification_numbers': [],
                'year': datetime.now().year,
                'last_updated': ''
            },
            'debug': {
                'tianyancha_debug_output': False,
                'tianyancha_console_log': False,
                'last_updated': ''
            },
            'retest_ai_agent': {
                'enabled': False,
                'active_profile_id': 'default',
                'profiles': [
                    {
                        'id': 'default',
                        'name': '默认 OpenAI',
                        'provider': 'openai',
                        'base_url': '',
                        'api_key': '',
                        'model': '',
                        'temperature': 0.1,
                        'max_tokens': 800,
                        'last_updated': ''
                    },
                    {
                        'id': 'openrouter-free',
                        'name': 'OpenRouter 免费路由',
                        'provider': 'openrouter',
                        'base_url': 'https://openrouter.ai/api/v1',
                        'api_key': '',
                        'model': 'openrouter/free',
                        'temperature': 0.1,
                        'max_tokens': 1600,
                        'context_window': 128000,
                        'last_updated': ''
                    }
                ],
                'last_updated': ''
            },
            'threatbook_api_key': ''
        }

    def _remove_app_version_from_file(self) -> None:
        """从已有配置文件中移除旧版本字段。"""
        try:
            if not os.path.exists(self.config_file):
                return
            with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
            had_app_version = isinstance(config.get('app'), dict) and 'version' in config['app']
            if not had_app_version:
                return
            migrated = self._migrate_config(config)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(migrated, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.warning(f"清理配置版本字段失败: {e}")

    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                # 增加重试以处理并发写入导致的部分内容或临时不可读
                config = None
                read_error = None
                for _ in range(5):
                    try:
                        with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                            config = json.load(f)
                        read_error = None
                        break
                    except Exception as e:
                        read_error = e
                        import time
                        time.sleep(0.1)
                if config is None:
                    self.logger.warning(f"读取配置文件失败，使用默认配置: {read_error}")
                    config = {}

                # 合并默认配置（确保所有必要的键都存在）
                merged_config = self._merge_config(self._default_config, config)
                had_app_version = isinstance(config.get('app'), dict) and 'version' in config['app']

                # 自动迁移配置（检查版本并更新）
                merged_config = self._migrate_config(merged_config)
                if had_app_version:
                    self._config = merged_config
                    self.save_config(merged_config)

                self._config = merged_config

                self.logger.info(f"配置文件加载成功: {self.config_file}")
                return merged_config
            else:
                # 配置文件不存在，创建默认配置
                self.logger.info(f"配置文件不存在，创建默认配置: {self.config_file}")
                self._config = self._default_config.copy()
                self.save_config(self._config)
                return self._config

        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            # 返回默认配置
            self._config = self._default_config.copy()
            return self._config

    def save_config(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """保存配置文件"""
        try:
            # 文件锁路径，避免并发覆盖
            lock_file = f"{self.config_file}.lock"
            if config is None:
                config = self._config

            if config is None:
                self.logger.error("没有配置数据可保存")
                return False

            # 确保目录存在
            config_dir = os.path.dirname(self.config_file)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)

            # 获取锁，串行化写入
            lock_acquired = False
            for _ in range(50):  # 最多等待5秒
                try:
                    fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    os.close(fd)
                    lock_acquired = True
                    break
                except FileExistsError:
                    import time
                    time.sleep(0.1)
                except Exception as e:
                    self.logger.warning(f"创建锁文件失败，继续尝试: {e}")
                    import time
                    time.sleep(0.1)

            if not lock_acquired:
                self.logger.error("保存配置失败：无法获取锁")
                return False

            try:
                # 读取最新配置，避免覆盖其他写入者的更改
                latest_config = {}
                if os.path.exists(self.config_file):
                    try:
                        with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                            latest_config = json.load(f)
                    except Exception as e:
                        self.logger.warning(f"读取现有配置文件失败，将使用默认配置: {e}")
                        latest_config = self._default_config.copy()
                else:
                    latest_config = self._default_config.copy()

                # 合并配置（保留最新的配置，只更新传入的部分）
                merged_config = self._merge_config(latest_config, config)
                merged_config = self._migrate_config(merged_config)

                # 原子写入：先写临时文件，再替换
                tmp_file = f"{self.config_file}.tmp"
                with open(tmp_file, 'w', encoding='utf-8') as f:
                    json.dump(merged_config, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(tmp_file, self.config_file)

                self._config = merged_config
                self.logger.info(f"配置文件保存成功: {self.config_file}")
                return True
            finally:
                try:
                    if os.path.exists(lock_file):
                        os.remove(lock_file)
                except Exception as e:
                    self.logger.warning(f"删除锁文件失败: {e}")

        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")
            return False

    def get_config(self, section: Optional[str] = None) -> Dict[str, Any]:
        """获取配置"""
        if self._config is None:
            self._config = self.load_config()

        if section:
            return self._config.get(section, {})
        return self._config

    def set_config(self, section: str, key: str, value: Any) -> bool:
        """设置配置项"""
        try:
            if self._config is None:
                self._config = self.load_config()

            if section not in self._config:
                self._config[section] = {}

            self._config[section][key] = value
            self._config[section]['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return self.save_config()

        except Exception as e:
            self.logger.error(f"设置配置项失败: {e}")
            return False

    def update_section(self, section: str, data: Dict[str, Any]) -> bool:
        """更新整个配置节"""
        try:
            if self._config is None:
                self._config = self.load_config()

            if section not in self._config:
                self._config[section] = {}

            self._config[section].update(data)
            self._config[section]['last_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return self.save_config()

        except Exception as e:
            self.logger.error(f"更新配置节失败: {e}")
            return False

    def _merge_config(self, default: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """合并配置（确保所有默认键都存在）"""
        merged = default.copy()

        for key, value in user.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_config(merged[key], value)
            else:
                merged[key] = value

        return merged

    def _migrate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """自动迁移配置。应用版本不再写入用户配置。"""
        try:
            app_config = config.get('app')
            if isinstance(app_config, dict) and 'version' in app_config:
                app_config.pop('version', None)
            return config
        except Exception as e:
            self.logger.error(f"配置迁移失败: {e}")
            return config

    def backup_config(self, backup_suffix: Optional[str] = None) -> Optional[str]:
        """备份配置文件，返回备份文件路径"""
        try:
            if not os.path.exists(self.config_file):
                self.logger.warning("配置文件不存在，无法备份")
                return None

            if backup_suffix is None:
                backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")

            backup_file = f"{self.config_file}.backup_{backup_suffix}"

            import shutil
            shutil.copy2(self.config_file, backup_file)

            self.logger.info(f"配置文件备份成功: {backup_file}")
            return backup_file

        except Exception as e:
            self.logger.error(f"备份配置文件失败: {e}")
            return None

    def restore_config(self, backup_file: str) -> bool:
        """从备份恢复配置文件"""
        try:
            if not os.path.exists(backup_file):
                self.logger.error(f"备份文件不存在: {backup_file}")
                return False

            import shutil
            shutil.copy2(backup_file, self.config_file)

            # 重新加载配置
            self._config = None
            self.load_config()

            self.logger.info(f"配置文件恢复成功: {backup_file}")
            return True

        except Exception as e:
            self.logger.error(f"恢复配置文件失败: {e}")
            return False

    def reset_config(self) -> bool:
        """重置配置为默认值"""
        try:
            self._config = self._default_config.copy()
            return self.save_config()

        except Exception as e:
            self.logger.error(f"重置配置失败: {e}")
            return False

    def validate_config(self) -> bool:
        """验证配置文件的完整性"""
        try:
            if self._config is None:
                self._config = self.load_config()

            # 检查必要的配置节是否存在
            required_sections = ['hunter', 'quake', 'fofa', 'aiqicha', 'tyc']

            for section in required_sections:
                if section not in self._config:
                    self.logger.warning(f"配置缺少必要节: {section}")
                    return False

            self.logger.info("配置文件验证通过")
            return True

        except Exception as e:
            self.logger.error(f"验证配置文件失败: {e}")
            return False

    def get_api_config(self, platform: str) -> Dict[str, Any]:
        """获取特定平台的API配置"""
        config = self.get_config()
        return config.get(platform, {})

    def set_api_config(self, platform: str, api_data: Dict[str, Any]) -> bool:
        """设置特定平台的API配置"""
        return self.update_section(platform, api_data)

    @property
    def config_file_path(self) -> str:
        """获取配置文件路径"""
        return self.config_file

    @property
    def is_first_run(self) -> bool:
        """检查是否首次运行"""
        # 确保配置已被加载
        if self._config is None:
            self._config = self.load_config()
        config = self._config
        first_run = config.get('app', {}).get('first_run', True)
        self.logger.debug(f"is_first_run检查: {first_run}, 配置文件: {self.config_file}")
        return first_run

    def mark_first_run_complete(self) -> bool:
        """标记首次运行完成"""
        self.logger.info(f"标记首次运行完成，配置文件: {self.config_file}")
        success = self.set_config('app', 'first_run', False)
        if success:
            self.logger.info("首次运行标记已成功保存")
        else:
            self.logger.error("首次运行标记保存失败")
        return success


def main():
    """测试函数"""
    print("配置管理器模块加载成功")

    # 测试配置管理器
    config_manager = ConfigManager()

    # 加载配置
    config = config_manager.load_config()
    print(f"加载的配置: {config}")

    # 验证配置
    is_valid = config_manager.validate_config()
    print(f"配置验证结果: {is_valid}")


if __name__ == "__main__":
    main()
