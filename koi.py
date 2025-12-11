#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import subprocess

# 全局变量用于存储动画进程
g_splash_process = None


def is_frozen():
    """检测是否在打包环境中运行"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_resource_path(relative_path):
    """获取资源文件的绝对路径(支持开发和打包环境)"""
    if is_frozen():
        # 打包后,资源在 exe 同级目录
        base_path = os.path.dirname(sys.executable)
    else:
        # 开发环境
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)


def run_splash_mode():
    """启动动画模式 - 作为独立子进程运行"""
    from modules.ui.splash import AnimatedSplash
    from PySide6.QtWidgets import QApplication
    import json
    
    app = QApplication(sys.argv)
    
    # 获取图标路径和版本号
    icon_path = get_resource_path("1.ico")
    
    # 获取版本号
    version = "1.3.0"
    try:
        config_path = get_resource_path("config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                version = config.get('app', {}).get('version', '1.3.0')
    except Exception:
        pass
    
    # 创建并显示动画窗口
    splash = AnimatedSplash(
        icon_path if os.path.exists(icon_path) else None, 
        version=version
    )
    splash.showCentered()
    
    # 运行事件循环
    sys.exit(app.exec())


# --- 极速启动动画 ---
# 在导入任何重型库（如PySide6）之前启动动画
if __name__ == "__main__":
    # 检查是否为启动动画子进程模式
    if "--splash" in sys.argv:
        run_splash_mode()
        # run_splash_mode 会调用 sys.exit，不会执行到这里
    
    # 主程序模式 - 启动启动动画子进程
    try:
        # 统一使用 --splash 参数启动子进程（开发和打包环境一致）
        if is_frozen():
            # 打包环境: 使用当前exe
            splash_cmd = [sys.executable, "--splash"]
        else:
            # 开发环境: 使用当前脚本
            splash_cmd = [sys.executable, os.path.abspath(__file__), "--splash"]
        
        g_splash_process = subprocess.Popen(
            splash_cmd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
    except Exception as e:
        print(f"启动动画失败: {e}")

# 只导入标准库,延迟导入重型库
import logging
import time

# PySide6 和其他重型库延迟到需要时才导入
# 这样可以让启动动画更快显示


def setup_logging():
    """设置日志配置 - 异步初始化,不阻塞启动"""
    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('app.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    except Exception as e:
        # 日志初始化失败不应该阻止程序启动
        print(f"日志初始化失败: {e}")




def setup_application():
    """设置应用程序属性 - 延迟导入 PySide6"""
    # 在此处导入 PySide6,避免启动时阻塞
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import Qt
    
    # 设置高DPI支持，避免缩放问题
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    # 禁用Qt的内部缓存，减少内存使用
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    
    # 设置应用程序信息
    app.setApplicationName("koi")
    
    # 从配置读取版本号 - 延迟导入 ConfigManager
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
    
    # 禁用原生对话框，使用Qt对话框以应用QSS样式
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app.setQuitOnLastWindowClosed(True)
    
    return app




def create_main_window(show_immediately=True):
    """创建主窗口 - 延迟导入,优化启动速度"""
    try:
        # 在此处导入主窗口类和必要的 Qt 模块,避免启动时阻塞
        from modules.ui.main_window import ModernDataProcessorPySide6
        from modules.config.config_manager import ConfigManager
        from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
        
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
            # 显示窗口 - 简化显示逻辑,减少重复操作
            window.show()
            window.raise_()
            window.activateWindow()
        
        # 淡入动画
        try:
            anim = QPropertyAnimation(window, b"windowOpacity", window)
            anim.setDuration(350)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
        except Exception:
            pass
        
        # 延迟显示欢迎信息,避免阻塞启动
        if config_manager.is_first_run:
            def show_welcome():
                from PySide6.QtWidgets import QMessageBox
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
        from PySide6.QtWidgets import QMessageBox
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
        # 延迟导入 PySide6 组件，避免在启动动画之前加载
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox

        # 获取之前启动的动画子进程
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
        # 此时 splash 正在独立运行，动画非常流畅
        window = create_main_window(show_immediately=False)
        
        if window is None:
            # 清理启动动画子进程
            if splash_process:
                try:
                    splash_process.terminate()
                    splash_process.wait(timeout=1)
                except Exception:
                    pass
            return 1
        
        # 优化: 给动画足够的展示时间,确保进度条完整播放到100%
        # 进度条需要4.5秒到100%,主窗口在后台已准备好,不会浪费时间
        # 这样用户能看到完整的启动动画,体验更好
        time.sleep(4.5)
        
        # 现在进度条已经到100%,可以平滑切换到主窗口了
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
        
        # 关闭启动动画子进程
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
        except Exception:
            print(f"应用程序启动失败: {e}")
        
        return 1


if __name__ == "__main__":
    sys.exit(main())