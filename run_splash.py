import sys
import os
import json
from PySide6.QtWidgets import QApplication
from modules.ui.splash import AnimatedSplash

def get_version():
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('app', {}).get('version', '1.3.0')
    except Exception:
        pass
    return "1.3.0"

def main():
    # 创建独立的应用程序实例
    app = QApplication(sys.argv)
    
    # 获取图标路径
    icon_path = os.path.join(os.path.dirname(__file__), "1.ico")
    
    # 获取版本号
    version = get_version()
    
    # 创建并显示动画窗口
    splash = AnimatedSplash(icon_path if os.path.exists(icon_path) else None, version=version)
    splash.showCentered()
    
    # 运行事件循环
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
