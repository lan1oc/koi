#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOI Tauri Python 后端专用打包入口。

避免导入 modules.data_processing / modules.Emergency_help 的 __init__.py，
因为这些包的 __init__ 会继续导入 PySide6 UI 文件，导致后端 exe 变大、启动变慢。
"""

from modules.backend_api.main import main


if __name__ == "__main__":
    raise SystemExit(main())
