# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('fake_useragent')
datas += [('1.ico', '.')]
datas += [('modules', 'modules')]
datas += [('config_template.json', 'config.json')]
# 将templates文件夹单独提取到可执行文件旁边，使其可见且可编辑
datas += [('modules/data_processing/templates', 'templates')]
# 添加Report_Template文件夹
datas += [('Report_Template', 'Report_Template')]


a = Analysis(
    ['koi.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'fake_useragent', 'fake_useragent.data', 'fake_useragent.utils', 'fake_useragent.fake',
        # 核心模块
        'modules', 'modules.__init__',
        # 信息收集模块
        'modules.Information_Gathering', 'modules.Information_Gathering.__init__',
        'modules.Information_Gathering.Enterprise_Query', 'modules.Information_Gathering.Enterprise_Query.__init__',
        'modules.Information_Gathering.Enterprise_Query.aiqicha_query', 'modules.Information_Gathering.Enterprise_Query.tianyancha_query',
        'modules.Information_Gathering.Enterprise_Query.enterprise_query_ui',
        'modules.Information_Gathering.Asset_Mapping', 'modules.Information_Gathering.Asset_Mapping.__init__',
        'modules.Information_Gathering.Asset_Mapping.hunter', 'modules.Information_Gathering.Asset_Mapping.fofa',
        'modules.Information_Gathering.Asset_Mapping.quake', 'modules.Information_Gathering.Asset_Mapping.asset_mapping_ui',
        'modules.Information_Gathering.Asset_Mapping.fofa_syntax_doc', 'modules.Information_Gathering.Asset_Mapping.hunter_syntax_doc',
        'modules.Information_Gathering.Asset_Mapping.quake_syntax_doc', 'modules.Information_Gathering.Asset_Mapping.platform_syntax_comparison',
        'modules.Information_Gathering.Threat_Intelligence', 'modules.Information_Gathering.Threat_Intelligence.__init__',
        'modules.Information_Gathering.Threat_Intelligence.threat_intelligence_ui', 'modules.Information_Gathering.Threat_Intelligence.threatbook_api',
        'modules.Information_Gathering.information_gathering_ui', 'modules.Information_Gathering.integration_helper',
        'modules.Information_Gathering.unified_search',
        # 应急救助模块
        'modules.Emergency_help', 'modules.Emergency_help.__init__',
        'modules.Emergency_help.weekly_report', 'modules.Emergency_help.weekly_report.__init__',
        'modules.Emergency_help.weekly_report.weekly_report_generator', 'modules.Emergency_help.weekly_report.weekly_report_ui',
        'modules.Emergency_help.weekly_report.integration_helper',
        # 数据处理模块
        'modules.data_processing', 'modules.data_processing.__init__',
        'modules.data_processing.data_filler', 'modules.data_processing.data_processor_ui',
        'modules.data_processing.excel_processor', 'modules.data_processing.field_extractor',
        'modules.data_processing.integration_helper', 'modules.data_processing.template_manager',
        # 文档处理模块
        'modules.Document_Processing', 'modules.Document_Processing.__init__',
        'modules.Document_Processing.doc_pdf', 'modules.Document_Processing.document_processing_ui',
        'modules.Document_Processing.pdf_extract', 'modules.Document_Processing.report_rewrite_ui',
        'modules.Document_Processing.Report_Rewrite', 'modules.Document_Processing.Report_Rewrite.__init__',
        'modules.Document_Processing.Report_Rewrite.rewrite_report', 'modules.Document_Processing.Report_Rewrite.read_word',
        'modules.Document_Processing.Report_Rewrite.edit_rectification', 'modules.Document_Processing.Report_Rewrite.edit_authorization',
        'modules.Document_Processing.Report_Rewrite.edit_disposal',
        # UI模块
        'modules.ui', 'modules.ui.__init__', 'modules.ui.main_window',
        'modules.ui.dialogs', 'modules.ui.dialogs.__init__', 'modules.ui.dialogs.syntax_dialog',
        'modules.ui.styles', 'modules.ui.styles.__init__', 'modules.ui.styles.main_styles', 'modules.ui.styles.theme_manager',
        # 配置模块
        'modules.config', 'modules.config.__init__', 'modules.config.config_manager',
        # 工具模块
        'modules.utils', 'modules.utils.__init__', 'modules.utils.async_delay', 'modules.utils.com_error_handler',
        # 第三方库
        'requests', 'json', 'time', 'urllib.parse', 'typing', 'PySide6', 'PySide6.QtWidgets',
        'PySide6.QtCore', 'PySide6.QtGui', 'pandas', 'openpyxl', 'datetime', 'beautifulsoup4',
        'colorama', 'lxml', 'jinja2', 'tldextract', 'tqdm', 'urllib3', 'docx', 'python-docx',
        'win32api', 'win32con', 'win32gui', 'winreg', 'pathlib', 're', 'logging', 'threading',
        'queue', 'copy', 'zipfile', 'shutil', 'tempfile', 'base64', 'hashlib', 'uuid'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='1.ico'
)

# 单独创建配置文件和模板文件夹的拷贝
import shutil
import os
from pathlib import Path

# 在编译后复制必要文件到dist目录
if os.path.exists('dist'):
    dist_path = Path('dist')
    
    # 复制配置文件模板
    if os.path.exists('config_template.json'):
        shutil.copy2('config_template.json', dist_path / 'config.json')
    
    # 复制模板文件夹
    templates_src = Path('modules/data_processing/templates')
    templates_dst = dist_path / 'templates'
    if templates_src.exists():
        if templates_dst.exists():
            shutil.rmtree(templates_dst)
        shutil.copytree(templates_src, templates_dst)
