#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import logging
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtCore import QTimer, QEasingCurve, QPropertyAnimation
from PySide6.QtCore import Qt

# 导入模块化组件
try:
    from modules.ui.main_window import ModernDataProcessorPySide6
    from modules.config.config_manager import ConfigManager
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有模块文件都存在且路径正确")
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
    app.setApplicationVersion("1.0.8")
    app.setOrganizationName("koi")
    app.setOrganizationDomain("github.com")
    
    # 设置应用程序图标
    icon_path = os.path.join(os.path.dirname(__file__), "1.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 设置高DPI支持
    app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    # 使用新的高DPI像素图属性，避免过时警告
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)
    app.setQuitOnLastWindowClosed(True)
    
    # 不在这里设置全局字体大小，完全由ThemeManager处理样式
    # 这样可以确保亮色模式和暗色模式下样式一致
    
    return app


def create_main_window():
    """创建主窗口"""
    try:
        # 初始化配置管理器
        config_manager = ConfigManager()
        
        # 创建主窗口
        window = ModernDataProcessorPySide6(config_manager)
        
        # 启动淡入动画
        try:
            window.setWindowOpacity(0.0)
        except Exception:
            pass
        
        # 显示窗口
        window.show()
        window.raise_()
        window.activateWindow()
        
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
    try:
        # 设置日志
        setup_logging()
        logging.info("koi 1.0 启动中...")
        
        # 创建应用程序
        app = setup_application()
        
        # 轻量启动页（Splash）
        splash = None
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "1.ico")
            pixmap = None
            if os.path.exists(icon_path):
                pixmap = QIcon(icon_path).pixmap(96, 96)
            if pixmap is None or pixmap.isNull():
                pixmap = QPixmap(180, 100)
                pixmap.fill(QColor('black'))
            splash = QSplashScreen(pixmap)
            splash.show()
            app.processEvents()
        except Exception:
            splash = None
        
        # 创建主窗口
        window = create_main_window()
        if window is None:
            return 1
        
        logging.info("应用程序启动成功")
        
        # 关闭启动页
        try:
            if splash:
                QTimer.singleShot(200, splash.close)
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