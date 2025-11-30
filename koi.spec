# -*- mode: python ; coding: utf-8 -*-
"""
KOI 应用程序 PyInstaller 配置文件
支持独立进程启动动画,打包为单可执行文件
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 项目根目录
block_cipher = None
root_dir = os.path.abspath(SPECPATH)

# 收集所有模块
hiddenimports = [
    # PySide6 核心模块
    'PySide6.QtCore',
    'PySide6.QtGui', 
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    
    # 启动动画相关 - 关键!
    'modules.ui.run_splash',
    'modules.ui.splash',
    
    # UI 模块
    'modules.ui',
    'modules.ui.main_window',
    'modules.ui.backgrounds',
    'modules.ui.custom_widgets',
    'modules.ui.file_dialog_helper',
    'modules.ui.message_box_helper',
    'modules.ui.styles',
    'modules.ui.styles.theme_manager',
    'modules.ui.styles.theme_variables',
    'modules.ui.styles.main_styles',
    'modules.ui.dialogs',
    
    # 配置模块
    'modules.config',
    'modules.config.config_manager',
    
    # 数据处理模块
    'modules.data_processing',
    
    # 信息收集模块
    'modules.Information_Gathering',
    
    # 文档处理模块
    'modules.Document_Processing',
    
    # 工具模块
    'modules.utils',
    'modules.utils.com_error_handler',
    
    # 第三方库
    'requests',
    'beautifulsoup4',
    'bs4',
    'lxml',
    'jinja2',
    'tldextract',
    'tqdm',
    'pandas',
    'urllib3',
    'fake_useragent',
    'openpyxl',
    'docx',
    'win32com',
    'win32com.client',
    'pythoncom',
    'DrissionPage',
]

# 数据文件收集
datas = [
    # 配置文件
    (os.path.join(root_dir, 'config.json'), '.'),
    
    # 图标文件
    (os.path.join(root_dir, '1.ico'), '.'),
    
    # 报告模板目录 - 所有 .docx 和 .jpg 文件
    (os.path.join(root_dir, 'Report_Template'), 'Report_Template'),
    
    # 数据处理模板目录
    (os.path.join(root_dir, 'modules', 'data_processing', 'templates'), 
     os.path.join('modules', 'data_processing', 'templates')),
    
    # modules 目录下的所有 Python 文件(确保模块完整)
    (os.path.join(root_dir, 'modules'), 'modules'),
]

# 主程序分析
a = Analysis(
    [os.path.join(root_dir, 'koi.py')],
    pathex=[root_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块以减小体积和加快启动
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'PIL',
        'cv2',
        'pytest',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'setuptools',
        '_pytest',
        'distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 过滤掉不需要的文件
def filter_binaries(binaries):
    """过滤二进制文件,移除不必要的 Qt 插件"""
    excluded = [
        'qml',  # QML 相关
        'qt3d',  # 3D 相关
        'qtquick',  # Quick 相关
        'designer',  # Designer
        'qtwebengine',  # WebEngine (如果不需要)
    ]
    return [(name, path, type_) for name, path, type_ in binaries 
            if not any(ex in name.lower() for ex in excluded)]

a.binaries = filter_binaries(a.binaries)

# PYZ 归档
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# EXE 可执行文件 - 单文件模式 (优化启动速度)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='koi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 禁用 UPX 压缩 - 文件稍大但启动更快
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(root_dir, '1.ico'),  # 应用程序图标
    version_file=None,
    uac_admin=False,  # 不需要管理员权限
    uac_uiaccess=False,
)

# 如果需要打包成文件夹模式(调试用),取消下面的注释
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='koi'
# )
