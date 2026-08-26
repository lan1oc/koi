# 数据处理资源

KOI 4.0.0 的字段提取、填充和模板管理由 Rust 实现：

- `tauri-ui/src-tauri/src/backend/data_processing.rs`
- `tauri-ui/src-tauri/src/backend/templates.rs`

本目录只保留发布时需要的 `templates/templates.json` seed。运行时会把缺失的 seed 复制到用户数据目录，不覆盖用户模板。

兼容命令、请求字段和超时定义见 `contracts/backend-commands.json`。本目录不再是 Python 包，也不需要 pandas、openpyxl 或系统 Python。
