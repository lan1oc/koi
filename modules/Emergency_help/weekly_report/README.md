# 周报模块

KOI 4.0.0 的周报配置和生成由 `tauri-ui/src-tauri/src/backend/weekly_report.rs` 实现。

命令名称、JSON 字段和响应包络继续与旧版本兼容，定义见 `contracts/backend-commands.json`。实现不依赖 PySide、系统 Python 或 Python sidecar。
