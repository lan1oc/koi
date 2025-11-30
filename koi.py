#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import subprocess

# 全局变量用于存储动画进程
g_splash_process = None

# --- 极速启动动画 ---
# 在导入任何重型库（如PySide6）之前启动动画进程
# 使用模块方式启动，这样在打包后也能正常工作
if __name__ == "__main__":
    try:
        g_splash_process = subprocess.Popen([sys.executable, "-m", "modules.ui.run_splash"])
    except Exception as e:
        print(f"启动动画失败: {e}")

import logging
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QTimer, QEasingCurve, QPropertyAnimation, Qt

# 延迟导入模块化组件
try:
    from modules.config.config_manager import ConfigManager
except ImportError as e:
    print(f"导入配置模块失败: {e}")
    sys.exit(1)


def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('app.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def setup_application():
    """设置应用程序属性"""
    # 设置高DPI支持，避免缩放问题
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    # 禁用Qt的内部缓存，减少内存使用
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    
    # 设置应用程序信息
    app.setApplicationName("koi")
    
    # 从配置读取版本号
    try:
        from modules.config.config_manager import ConfigManager
        config = ConfigManager().load_config()
        version = config.get('app', {}).get('version', '1.3.0')
    except Exception:
        version = "1.3.0"
        
    app.setApplicationVersion(version)
    app.setOrganizationName("koi")
    app.setOrganizationDomain("github.com")
    
    # 设置应用程序图标
    icon_path = os.path.join(os.path.dirname(__file__), "1.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 设置高DPI支持
    app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    # 禁用原生对话框，使用Qt对话框以应用QSS样式
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app.setQuitOnLastWindowClosed(True)
    
    # 不在这里设置全局字体大小，完全由ThemeManager处理样式
    # 这样可以确保亮色模式和暗色模式下样式一致
    
    return app


def create_main_window(show_immediately=True):
    """创建主窗口"""
    try:
        # 在此处导入主窗口类，避免启动时阻塞
        from modules.ui.main_window import ModernDataProcessorPySide6
        
        # 初始化配置管理器
        config_manager = ConfigManager()
        
        # 创建主窗口
        window = ModernDataProcessorPySide6(config_manager)
        
        # 启动淡入动画
        try:
            window.setWindowOpacity(0.0)
        except Exception:
            pass
        
        if show_immediately:
            # 显示窗口 - 确保窗口正确显示并激活
            window.show()
            window.raise_()
            window.activateWindow()
            
            # 强制窗口到前台 - 解决窗口不自动显示的问题
            try:
                # 确保窗口不被最小化，并设置为活动窗口
                window.setWindowState(Qt.WindowState.WindowActive)
                window.raise_()
                window.activateWindow()
                # 确保窗口获得焦点
                window.setFocus()
                # 强制显示在最前面
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                window.show()  # 重新显示以应用标志
                # 移除置顶标志，避免影响后续使用
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                window.show()
            except Exception:
                pass
        
        try:
            anim = QPropertyAnimation(window, b"windowOpacity", window)
            anim.setDuration(350)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
        except Exception:
            pass
        
        # 使用定时器延迟显示欢迎信息，避免启动时阻塞UI
        if config_manager.is_first_run:
            def show_welcome():
                QMessageBox.information(
                    window,
                    "欢迎使用",
                    "欢迎使用 koi ！\n\n"
                    "本版本已完全重构，采用模块化架构：\n"
                    "• 📊 数据处理 - Excel处理、字段提取、数据填充、模板管理\n"
                    "• 🔍 信息收集 - 企业查询(爱企查/天眼查)、资产查询(FOFA/Hunter/Quake)、威胁情报\n"
                    "• 🚨 江湖救急 - 周报生成\n"
                    "• 📄 文档处理 - Word转PDF、PDF提取、网信办通报批量处理（指向性太强基本无用）\n\n"
                )
                config_manager.mark_first_run_complete()
            
            # 延迟2秒显示欢迎信息，让UI先完成渲染
            QTimer.singleShot(2000, show_welcome)
        
        return window
        
    except Exception as e:
        logging.error(f"创建主窗口失败: {e}")
        QMessageBox.critical(
            None,
            "启动错误",
            f"创建主窗口失败：\n{str(e)}\n\n请检查模块文件是否完整。"
        )
        return None


def main():
    """主函数"""
    global g_splash_process
    try:
        # 获取之前启动的动画进程
        splash_process = g_splash_process

        # 设置日志
        setup_logging()
        
        # 从配置读取版本号
        try:
            from modules.config.config_manager import ConfigManager
            config = ConfigManager().load_config()
            version = config.get('app', {}).get('version', '1.3.0')
        except Exception:
            version = "1.3.0"
            
        logging.info(f"koi {version} 启动中...")
        
        # 创建应用程序
        app = setup_application()
        
        # 立即开始创建主窗口，但保持隐藏
        # 此时 splash_process 正在独立运行，动画非常流畅
        window = create_main_window(show_immediately=False)
        
        if window is None:
            if splash_process:
                splash_process.terminate()
            return 1
        
        # 给动画一点展示时间（如果加载太快的话）
        # 这里是主进程在 sleep，不会影响 splash 进程的流畅度
        time.sleep(1.5)
        
        if window:
            try:
                window.showNormal()
            except Exception:
                window.show()
            try:
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                window.show()
                window.raise_()
                window.activateWindow()
                try:
                    window.setWindowState(Qt.WindowState.WindowActive)
                    window.setFocus()
                except Exception:
                    pass
                window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                window.show()
            except Exception:
                window.raise_()
                window.activateWindow()
            try:
                QTimer.singleShot(0, lambda: (window.raise_(), window.activateWindow()))
            except Exception:
                pass
        
        logging.info("应用程序启动成功")
        
        # 关闭启动动画进程
        if splash_process:
            try:
                splash_process.terminate()
                splash_process.wait(timeout=1)
            except Exception:
                pass
        
        # 运行应用程序
        exit_code = app.exec()
        
        logging.info(f"应用程序退出，退出码: {exit_code}")
        return exit_code
        
    except Exception as e:
        logging.error(f"应用程序启动失败: {e}")
        
        # 尝试显示错误对话框
        try:
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "启动失败",
                f"应用程序启动失败：\n{str(e)}\n\n请检查依赖和模块文件。"
            )
        except:
            print(f"应用程序启动失败: {e}")
        
        return 1


if __name__ == "__main__":
    sys.exit(main())