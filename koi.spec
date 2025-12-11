# -*- mode: python ; coding: utf-8 -*-
"""
koi 打包配置文件
使用方法: pyinstaller koi.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.abspath(SPEC))

# 收集 PySide6 的隐藏导入
hiddenimports = [
    # PySide6 核心模块
    'PySide6.QtCore',
    'PySide6.QtGui', 
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    
    # 项目模块
    'modules',
    'modules.ui',
    'modules.ui.splash',
    'modules.ui.main_window',
    'modules.ui.custom_widgets',
    'modules.ui.styles',
    'modules.ui.styles.theme_manager',
    'modules.ui.styles.main_styles',
    'modules.ui.styles.icons',
    'modules.ui.message_box_helper',
    'modules.ui.file_dialog_helper',
    'modules.ui.dialogs',
    'modules.ui.dialogs.manual_fix_dialog',
    'modules.ui.dialogs.syntax_dialog',
    'modules.config',
    'modules.config.config_manager',
    'modules.data_processing',
    'modules.data_processing.data_processor_ui',
    'modules.data_processing.excel_processor',
    'modules.data_processing.field_extractor',
    'modules.data_processing.data_filler',
    'modules.data_processing.template_manager',
    'modules.Document_Processing',
    'modules.Document_Processing.document_processing_ui',
    'modules.Document_Processing.doc_pdf',
    'modules.Document_Processing.pdf_extract',
    'modules.Document_Processing.report_rewrite_ui',
    'modules.Document_Processing.Report_Rewrite',
    'modules.Document_Processing.retest',
    'modules.Information_Gathering',
    'modules.Information_Gathering.information_gathering_ui',
    'modules.Information_Gathering.Enterprise_Query',
    'modules.Information_Gathering.Asset_Mapping',
    'modules.Information_Gathering.Threat_Intelligence',
    'modules.Emergency_help',
    'modules.Emergency_help.weekly_report',
    'modules.utils',
    'modules.utils.com_error_handler',
    
    # 第三方库
    'requests',
    'bs4',
    'lxml',
    'jinja2',
    'tldextract',
    'pandas',
    'openpyxl',
    'docx',
    'fitz',  # PyMuPDF
    'pdf2docx',
    'PIL',
    'win32com',
    'win32com.client',
    'pythoncom',
    'DrissionPage',
]

# 收集 PySide6 子模块
hiddenimports += collect_submodules('PySide6')

# 需要打包的数据文件
datas = [
    # 图标文件
    (os.path.join(ROOT_DIR, '1.ico'), '.'),
    # 配置文件
    (os.path.join(ROOT_DIR, 'config.json'), '.'),
    # 模板文件夹
    (os.path.join(ROOT_DIR, 'Report_Template'), 'Report_Template'),
    # 数据处理模板
    (os.path.join(ROOT_DIR, 'modules', 'data_processing', 'templates'), 
     os.path.join('modules', 'data_processing', 'templates')),
]

# 收集 PySide6 数据文件
datas += collect_data_files('PySide6')

# 排除不需要的模块（减小体积）
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'numpy.distutils',
    'test',
    'tests',
    'unittest',
]

# Analysis 配置
a = Analysis(
    [os.path.join(ROOT_DIR, 'koi.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# PYZ 配置
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# EXE 配置
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
    upx=True,  # 使用 UPX 压缩
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, '1.ico'),  # 应用图标
    version=None,
    uac_admin=False,  # 不需要管理员权限
)

