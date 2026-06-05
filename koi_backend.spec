# -*- mode: python ; coding: utf-8 -*-
"""
KOI Tauri Python 后端打包配置
使用方法: pyinstaller koi_backend.spec
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT_DIR = os.path.dirname(os.path.abspath(SPEC))

# 只保留当前 Tauri bridge 已经接入的无 UI 后端模块。
# 不再 collect_submodules(pandas/openpyxl/...)，避免把测试包、无关子模块和 PySide6 UI 链路打进后端 exe。
hiddenimports = [
    'modules.backend_api',
    'modules.backend_api.main',
    'modules.config',
    'modules.config.config_manager',
    'modules.data_processing',
    'modules.data_processing.excel_processor',
    'modules.data_processing.field_extractor',
    'modules.data_processing.template_manager',
    'modules.Emergency_help',
    'modules.Emergency_help.weekly_report',
    'modules.Emergency_help.weekly_report.weekly_report_generator',
    'modules.utils',
    'modules.utils.resource_path',
    'pandas',
    'openpyxl',
    'openpyxl.cell._writer',
    'openpyxl.styles',
    'openpyxl.worksheet._reader',
    'numpy',
]


def safe_collect_submodules(package):
    try:
        return collect_submodules(package)
    except Exception:
        return [package]


for package in ('pypdf', 'docx', 'pdf2docx', 'fitz', 'py7zr', 'rarfile', 'DrissionPage'):
    hiddenimports += safe_collect_submodules(package)

hiddenimports += [
    'win32com',
    'win32com.client',
    'win32com.client.dynamic',
    'win32com.client.gencache',
    'win32com.client.makepy',
    'pythoncom',
    'pywintypes',
]

datas = []
for source, target in [
    (os.path.join(ROOT_DIR, 'Report_Template'), 'Report_Template'),
    (os.path.join(ROOT_DIR, 'modules', 'data_processing', 'templates'), os.path.join('modules', 'data_processing', 'templates')),
    (os.path.join(ROOT_DIR, 'modules', 'AI_Testing', 'retest', 'prompts'), os.path.join('modules', 'AI_Testing', 'retest', 'prompts')),
    (os.path.join(ROOT_DIR, 'enterprise_classification.db'), '.'),
]:
    if os.path.exists(source):
        datas.append((source, target))

try:
    datas += collect_data_files('fake_useragent')
except Exception:
    pass

excludes = [
    'PySide6',
    'PyQt5',
    'PyQt6',
    'tkinter',
    'matplotlib',
    'scipy',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'unittest',
    'test',
    'tests',
    'pandas.tests',
    'numpy.tests',
    'openpyxl.tests',
    'setuptools.tests',
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'modules', 'backend_api', 'pyinstaller_entry.py')],
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

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='koi-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, '1.ico'),
    version=None,
    uac_admin=False,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='koi-backend',
    contents_directory='_internal',
)
