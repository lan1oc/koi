import sys
import os
from PySide6.QtWidgets import QApplication
from modules.ui.splash import AnimatedSplash

def main():
    # 创建独立的应用程序实例
    app = QApplication(sys.argv)
    
    # 获取图标路径
    icon_path = os.path.join(os.path.dirname(__file__), "1.ico")
    
    # 创建并显示动画窗口
    splash = AnimatedSplash(icon_path if os.path.exists(icon_path) else None)
    splash.showCentered()
    
    # 运行事件循环
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
