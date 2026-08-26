# 通报处理资源说明

KOI 4.0.0 的通报改写、分类、五阶段断点、PDF 操作和 ZIP/7z/RAR 预解压均由 Rust 实现：

- `tauri-ui/src-tauri/src/backend/pdf_notice.rs`
- `tauri-ui/src-tauri/src/backend/archive_runtime.rs`
- `tauri-ui/src-tauri/src/backend/document_conversion.rs`

处理状态仍使用兼容的 `.koi_notice_process_state.json`。源 SHA-256、产物验证、编号事务、原件保留和 `koi.notice.rewritten.v1` 回填规则由 Rust 测试覆盖。

模板位于仓库根目录 `Report_Template/`；本目录不再包含或加载 Python 业务实现。
