//! Native PDF and notice-processing primitives.
//!
//! PDF operations are self-contained and never invoke a sidecar. Notice
//! processing persists a source fingerprint and five explicit stages; a
//! source is only removed when a valid PDF artifact already exists. A missing
//! Rust converter therefore fails closed and leaves the source untouched.

use super::archive_runtime;
use super::config::ConfigStore;
use super::document_conversion;
use super::pdfium_runtime;
use super::task_manager::TaskManager;
use base64::Engine;
use lopdf::{Dictionary, Document, LoadOptions, Object, ObjectId};
use quick_xml::events::{BytesText, Event};
use quick_xml::{Reader as XmlReader, Writer as XmlWriter};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Cursor, Read, Write};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

const MAX_PDF_BYTES: u64 = 256 * 1024 * 1024;
const MAX_PDF_DECOMPRESSED_STREAM_BYTES: usize = 64 * 1024 * 1024;
const MAX_NOTICE_DOCX_BYTES: u64 = 256 * 1024 * 1024;
const MAX_NOTICE_XML_BYTES: usize = 64 * 1024 * 1024;
const MAX_NOTICE_ARCHIVE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_NOTICE_ARCHIVE_ENTRIES: usize = 10_000;
const MAX_NOTICE_ARCHIVE_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_NOTICE_ARCHIVE_EXPANDED_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const MAX_NOTICE_ARCHIVE_LISTING_BYTES: usize = 32 * 1024 * 1024;
const MAX_NOTICE_ARCHIVE_DIAGNOSTIC_BYTES: usize = 64 * 1024;
const NOTICE_ARCHIVE_LIST_TIMEOUT: Duration = Duration::from_secs(60);
const NOTICE_ARCHIVE_FILE_TIMEOUT: Duration = Duration::from_secs(120);
const NOTICE_ARCHIVE_TOTAL_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const NOTICE_STATE_FILE: &str = ".koi_notice_process_state.json";
const NOTICE_STATE_VERSION: u32 = 1;
const NOTICE_TASK_MAX_ACTIVE: usize = 4;
const NOTICE_TASK_MAX_COMPLETED: usize = 24;
const NOTICE_TASK_RETENTION_SECONDS: u64 = 6 * 60 * 60;

pub const COMMANDS: &[&str] = &[
    "doc.pdf_extract.preview",
    "doc.pdf_extract.run",
    "doc.pdf_extract.compress",
    "doc.notice.process",
    "doc.notice.process.start",
    "doc.notice.process.status",
    "doc.notice.classify",
    "doc.notice.convert_failed_pdf",
];

static NEXT_ID: AtomicU64 = AtomicU64::new(1);

pub fn is_command(command: &str) -> bool {
    COMMANDS.contains(&command)
}

pub fn dispatch(command: &str, payload: &Value) -> Result<Value, String> {
    match command {
        "doc.pdf_extract.preview" => pdf_preview(payload),
        "doc.pdf_extract.run" => pdf_extract(payload),
        "doc.pdf_extract.compress" => pdf_compress(payload),
        "doc.notice.process" => notice_process(payload),
        "doc.notice.process.start" => notice_process_start(payload),
        "doc.notice.process.status" => notice_process_status(payload),
        "doc.notice.classify" => notice_classify(payload),
        "doc.notice.convert_failed_pdf" => notice_convert_failed_pdf(payload),
        _ => Err(format!("未知文档处理命令: {command}")),
    }
}

#[derive(Debug, Clone)]
pub(crate) struct PageInfo {
    pub(crate) width: Option<f64>,
    pub(crate) height: Option<f64>,
}

#[derive(Debug, Clone)]
struct PdfInfo {
    path: PathBuf,
    page_count: usize,
    pages: Vec<PageInfo>,
    bytes: Vec<u8>,
    document: Document,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
enum PdfPathInput {
    One(String),
    Many(Vec<String>),
}

impl PdfPathInput {
    fn into_paths(self) -> Result<Vec<PathBuf>, String> {
        let values = match self {
            Self::One(value) => vec![value],
            Self::Many(values) => values,
        };
        values
            .into_iter()
            .map(|value| {
                let value = value.trim();
                if value.is_empty() {
                    Err("文件路径列表包含无效项目".to_string())
                } else {
                    Ok(PathBuf::from(value))
                }
            })
            .collect()
    }

    fn is_empty(&self) -> bool {
        match self {
            Self::One(value) => value.trim().is_empty(),
            Self::Many(values) => values.is_empty(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
struct PdfPageSelectionRequest {
    #[serde(alias = "path")]
    file_path: String,
    #[serde(alias = "page_number", deserialize_with = "deserialize_positive_usize")]
    page_num: usize,
    #[serde(default, deserialize_with = "deserialize_optional_i64")]
    order: Option<i64>,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct PdfExtractRequest {
    #[serde(default)]
    pdf_files: Option<PdfPathInput>,
    #[serde(default)]
    pdf_file: Option<PdfPathInput>,
    #[serde(default)]
    page_ranges: Option<String>,
    #[serde(default)]
    output_file: Option<String>,
    #[serde(default)]
    page_selections: Option<Vec<PdfPageSelectionRequest>>,
}

#[derive(Debug, Clone, Deserialize, Default)]
struct PdfPreviewRequest {
    #[serde(default)]
    pdf_files: Option<PdfPathInput>,
    #[serde(default)]
    pdf_file: Option<PdfPathInput>,
    #[serde(default)]
    include_thumbnails: bool,
    #[serde(default, deserialize_with = "deserialize_optional_i64")]
    thumbnail_limit: Option<i64>,
}

impl PdfPreviewRequest {
    fn take_paths(&mut self) -> Result<Vec<PathBuf>, String> {
        let selected = self
            .pdf_files
            .take()
            .filter(|value| !value.is_empty())
            .or_else(|| self.pdf_file.take());
        selected
            .map(PdfPathInput::into_paths)
            .unwrap_or(Ok(Vec::new()))
    }
}

impl PdfExtractRequest {
    fn take_paths(&mut self) -> Result<Vec<PathBuf>, String> {
        let selected = self
            .pdf_files
            .take()
            .filter(|value| !value.is_empty())
            .or_else(|| self.pdf_file.take());
        selected
            .map(PdfPathInput::into_paths)
            .unwrap_or(Ok(Vec::new()))
    }
}

fn deserialize_positive_usize<'de, D>(deserializer: D) -> Result<usize, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    let parsed = match value {
        Value::Number(value) => value.as_u64().and_then(|value| usize::try_from(value).ok()),
        Value::String(value) => value.trim().parse::<usize>().ok(),
        _ => None,
    };
    parsed
        .filter(|value| *value > 0)
        .ok_or_else(|| serde::de::Error::custom("page_num must be a positive integer"))
}

fn deserialize_optional_i64<'de, D>(deserializer: D) -> Result<Option<i64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    match value {
        Value::Null => Ok(None),
        Value::Number(value) => value
            .as_i64()
            .map(Some)
            .ok_or_else(|| serde::de::Error::custom("order must be an integer")),
        Value::String(value) if value.trim().is_empty() => Ok(None),
        Value::String(value) => value
            .trim()
            .parse::<i64>()
            .map(Some)
            .map_err(serde::de::Error::custom),
        _ => Err(serde::de::Error::custom("order must be an integer")),
    }
}

fn required_string(payload: &Value, key: &str) -> Result<String, String> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .ok_or_else(|| format!("缺少必要字段: {key}"))
}

fn optional_string(payload: &Value, key: &str) -> Option<String> {
    payload
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn path_list(value: Option<&Value>) -> Result<Vec<PathBuf>, String> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    match value {
        Value::String(path) if !path.trim().is_empty() => Ok(vec![PathBuf::from(path.trim())]),
        Value::Array(items) => items
            .iter()
            .map(|item| {
                item.as_str()
                    .map(str::trim)
                    .filter(|path| !path.is_empty())
                    .map(PathBuf::from)
                    .ok_or_else(|| "文件路径列表包含无效项目".to_string())
            })
            .collect(),
        _ => Err("文件路径格式不正确".to_string()),
    }
}

fn canonical_input(path: &Path, extension: &str) -> Result<PathBuf, String> {
    let metadata =
        fs::symlink_metadata(path).map_err(|_| format!("文件不存在: {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!("路径不是普通文件: {}", path.display()));
    }
    if path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case(extension))
        != Some(true)
    {
        return Err(format!("文件扩展名必须为 .{extension}: {}", path.display()));
    }
    let resolved = fs::canonicalize(path).map_err(|error| format!("无法解析文件路径: {error}"))?;
    let size = fs::metadata(&resolved)
        .map_err(|error| format!("无法读取文件信息: {error}"))?
        .len();
    if size > MAX_PDF_BYTES {
        return Err(format!("PDF 文件超过大小限制（{} bytes）", MAX_PDF_BYTES));
    }
    Ok(resolved)
}

fn ensure_output_path(path: &Path, extension: &str, sources: &[&Path]) -> Result<PathBuf, String> {
    if path.as_os_str().is_empty() {
        return Err("输出路径不能为空".to_string());
    }
    if path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case(extension))
        != Some(true)
    {
        return Err(format!("输出文件扩展名必须为 .{extension}"));
    }
    if fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
    {
        return Err("拒绝覆盖符号链接输出路径".to_string());
    }
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| format!("无法解析当前目录: {error}"))?
            .join(path)
    };
    for source in sources {
        let source = fs::canonicalize(source).map_err(|error| error.to_string())?;
        if fs::canonicalize(&absolute).ok().as_deref() == Some(source.as_path()) {
            return Err("输出路径不能覆盖输入 PDF".to_string());
        }
    }
    if let Some(parent) = absolute.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("无法创建输出目录: {error}"))?;
    }
    Ok(absolute)
}

fn read_pdf(path: &Path) -> Result<PdfInfo, String> {
    let resolved = canonical_input(path, "pdf")?;
    let mut file = File::open(&resolved).map_err(|error| format!("无法打开 PDF: {error}"))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| format!("无法读取 PDF: {error}"))?;
    if !bytes.starts_with(b"%PDF-") {
        return Err(format!("不是有效的 PDF 文件: {}", resolved.display()));
    }
    let document = load_pdf_document(&bytes)
        .map_err(|error| format!("无法解析 PDF {}: {error}", resolved.display()))?;
    let page_ids = document.get_pages();
    let page_count = page_ids.len();
    if page_count == 0 {
        return Err("PDF 未包含可识别的页面".to_string());
    }
    let pages = page_ids
        .into_values()
        .map(|page_id| page_dimensions(&document, page_id))
        .collect();
    Ok(PdfInfo {
        path: resolved,
        page_count,
        pages,
        bytes,
        document,
    })
}

fn load_pdf_document(bytes: &[u8]) -> Result<Document, String> {
    let mut document = Document::load_mem_with_options(
        bytes,
        LoadOptions::with_max_decompressed_size(MAX_PDF_DECOMPRESSED_STREAM_BYTES),
    )
    .map_err(|error| error.to_string())?;
    if document.encryption_state.is_some() || document.trailer.has(b"Encrypt") {
        return Err("加密 PDF 暂不支持页面提取".to_string());
    }
    document.trailer.remove(b"Prev");
    document.trailer.remove(b"XRefStm");
    document.trailer.remove(b"Encrypt");
    Ok(document)
}

fn inherited_page_attribute(document: &Document, page_id: ObjectId, name: &[u8]) -> Option<Object> {
    let mut current = Some(page_id);
    let mut visited = HashSet::new();
    while let Some(object_id) = current {
        if !visited.insert(object_id) {
            return None;
        }
        let dictionary = document.get_dictionary(object_id).ok()?;
        if let Ok(value) = dictionary.get(name) {
            return Some(value.clone());
        }
        current = dictionary
            .get(b"Parent")
            .and_then(Object::as_reference)
            .ok();
    }
    None
}

fn pdf_number(document: &Document, object: &Object) -> Option<f64> {
    let (_, value) = document.dereference(object).ok()?;
    match value {
        Object::Integer(value) => Some(*value as f64),
        Object::Real(value) => Some(*value as f64),
        _ => None,
    }
}

fn page_dimensions(document: &Document, page_id: ObjectId) -> PageInfo {
    let dimensions = inherited_page_attribute(document, page_id, b"MediaBox")
        .and_then(|value| {
            document
                .dereference(&value)
                .ok()
                .map(|(_, value)| value.clone())
        })
        .and_then(|value| value.as_array().ok().cloned())
        .and_then(|values| {
            if values.len() != 4 {
                return None;
            }
            Some((
                (pdf_number(document, &values[2])? - pdf_number(document, &values[0])?).abs(),
                (pdf_number(document, &values[3])? - pdf_number(document, &values[1])?).abs(),
            ))
        });
    PageInfo {
        width: dimensions.map(|(width, _)| width),
        height: dimensions.map(|(_, height)| height),
    }
}

fn page_json(index: usize, total: usize, page: &PageInfo, thumbnail: Option<&[u8]>) -> Value {
    let thumbnail = thumbnail.map(|bytes| {
        format!(
            "data:image/png;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(bytes)
        )
    });
    json!({
        "page_number": index,
        "label": format!("第 {index} 页 / 共 {total} 页"),
        "width": page.width,
        "height": page.height,
        "thumbnail": thumbnail,
    })
}

fn pdf_preview(payload: &Value) -> Result<Value, String> {
    let mut request: PdfPreviewRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("PDF 预览请求格式无效: {error}"))?;
    let paths = request.take_paths()?;
    if paths.is_empty() {
        return Ok(json!({"success": false, "message": "请先选择PDF文件", "files": []}));
    }
    let thumbnail_limit = request.thumbnail_limit.unwrap_or(80).max(0) as usize;
    let mut files = Vec::new();
    let mut failures = Vec::new();
    for path in paths {
        match read_pdf(&path) {
            Ok(info) => {
                let thumbnails = if request.include_thumbnails && thumbnail_limit > 0 {
                    match pdfium_runtime::render_thumbnails(&info.bytes, thumbnail_limit) {
                        Ok(thumbnails) => thumbnails,
                        Err(error) => {
                            failures.push(json!({"file": info.path, "reason": error}));
                            continue;
                        }
                    }
                } else {
                    Vec::new()
                };
                let pages: Vec<Value> = info
                    .pages
                    .iter()
                    .enumerate()
                    .map(|(index, page)| {
                        page_json(
                            index + 1,
                            info.page_count,
                            page,
                            thumbnails.get(index).map(Vec::as_slice),
                        )
                    })
                    .collect();
                files.push(json!({
                    "path": info.path,
                    "name": info.path.file_name().and_then(|value| value.to_str()).unwrap_or_default(),
                    "page_count": info.page_count,
                    "pages": pages,
                }));
            }
            Err(error) => failures.push(json!({"file": path, "reason": error})),
        }
    }
    let total_pages = files
        .iter()
        .filter_map(|file| file.get("page_count").and_then(Value::as_u64))
        .sum::<u64>();
    let success = !files.is_empty() && failures.is_empty();
    let message = if files.is_empty() {
        "预览加载失败".to_string()
    } else if failures.is_empty() {
        format!("预览加载完成，共 {} 个文件、{total_pages} 页", files.len())
    } else {
        format!("预览部分完成，{} 个文件加载失败", failures.len())
    };
    Ok(json!({
        "success": success,
        "message": message,
        "files": files,
        "failures": failures,
        "total_pages": total_pages,
    }))
}

fn parse_page_ranges(value: &str, total_pages: usize) -> Result<Vec<usize>, String> {
    if value.trim().is_empty() {
        return Err("请输入页码范围，例如: 2-6 或 2-6,9,11-12".to_string());
    }
    let mut pages = std::collections::BTreeSet::new();
    for raw_part in value.split(',') {
        let part = raw_part.trim();
        if part.is_empty() {
            continue;
        }
        let (start, end) = if let Some((left, right)) = part.split_once('-') {
            let start = left
                .trim()
                .parse::<usize>()
                .map_err(|_| format!("范围格式错误: {part}"))?;
            let end = right
                .trim()
                .parse::<usize>()
                .map_err(|_| format!("范围格式错误: {part}"))?;
            if start > end {
                return Err(format!("范围起止顺序错误: {part}"));
            }
            (start, end)
        } else {
            let number = part
                .parse::<usize>()
                .map_err(|_| format!("页码格式错误: {part}"))?;
            (number, number)
        };
        for page in start..=end {
            if page == 0 || page > total_pages {
                return Err(format!("页码超出范围: {page}，总页数: {total_pages}"));
            }
            pages.insert(page);
        }
    }
    if pages.is_empty() {
        return Err("页码范围格式不正确".to_string());
    }
    Ok(pages.into_iter().collect())
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "输出路径没有父目录".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("无法创建输出目录: {error}"))?;
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let temporary = parent.join(format!(
        ".{}.tmp-{id}",
        path.file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("koi")
    ));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| format!("无法创建临时文件: {error}"))?;
        file.write_all(bytes)
            .and_then(|_| file.flush())
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("无法写入临时文件: {error}"))?;
        drop(file);
        atomic_replace_file(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(windows)]
fn atomic_replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        MoveFileExW(
            PCWSTR(source.as_ptr()),
            PCWSTR(destination.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|error| format!("无法原子替换输出文件: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("无法原子替换输出文件: {error}"))
}

#[cfg(test)]
fn format_pdf_number(value: f64) -> String {
    if (value - value.round()).abs() < 0.001 {
        format!("{}", value.round() as i64)
    } else {
        format!("{value:.3}")
    }
}

#[cfg(test)]
pub(crate) fn make_blank_pdf(pages: &[PageInfo]) -> Vec<u8> {
    let mut objects: Vec<Vec<u8>> = Vec::new();
    objects.push(b"<< /Type /Catalog /Pages 2 0 R >>".to_vec());
    let kids: Vec<String> = pages
        .iter()
        .enumerate()
        .map(|(index, _)| format!("{} 0 R", 3 + index * 2))
        .collect();
    objects.push(
        format!(
            "<< /Type /Pages /Kids [{}] /Count {} >>",
            kids.join(" "),
            pages.len()
        )
        .into_bytes(),
    );
    for page in pages {
        let width = page.width.unwrap_or(595.0).max(1.0);
        let height = page.height.unwrap_or(842.0).max(1.0);
        let page_object = format!(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {} {}] /Resources << >> /Contents {} 0 R >>",
            format_pdf_number(width),
            format_pdf_number(height),
            objects.len() + 2
        );
        objects.push(page_object.into_bytes());
        objects.push(b"<< /Length 0 >>\nstream\n\nendstream".to_vec());
    }
    let mut output = b"%PDF-1.7\n%\xFF\xFF\xFF\xFF\n".to_vec();
    let mut offsets = Vec::with_capacity(objects.len() + 1);
    offsets.push(0usize);
    for (index, object) in objects.iter().enumerate() {
        offsets.push(output.len());
        output.extend_from_slice(format!("{} 0 obj\n", index + 1).as_bytes());
        output.extend_from_slice(object);
        output.extend_from_slice(b"\nendobj\n");
    }
    let xref_offset = output.len();
    output.extend_from_slice(format!("xref\n0 {}\n", objects.len() + 1).as_bytes());
    output.extend_from_slice(b"0000000000 65535 f \n");
    for offset in offsets.iter().skip(1) {
        output.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
    }
    output.extend_from_slice(
        format!(
            "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n",
            objects.len() + 1
        )
        .as_bytes(),
    );
    output
}

fn flatten_page_attributes(document: &mut Document, page_id: ObjectId) -> Result<(), String> {
    let inherited = [b"Resources".as_slice(), b"MediaBox", b"CropBox", b"Rotate"]
        .into_iter()
        .filter_map(|name| {
            inherited_page_attribute(document, page_id, name).map(|value| (name.to_vec(), value))
        })
        .collect::<Vec<_>>();
    let page = document
        .get_dictionary_mut(page_id)
        .map_err(|error| format!("无法读取 PDF 页面对象: {error}"))?;
    for (name, value) in inherited {
        if !page.has(&name) {
            page.set(name, value);
        }
    }
    Ok(())
}

fn select_single_page(mut selected: Document, page_number: usize) -> Result<Document, String> {
    let pages = selected.get_pages();
    let page_id = pages
        .get(&(page_number as u32))
        .copied()
        .ok_or_else(|| format!("页码超出范围: {page_number}，总页数: {}", pages.len()))?;
    flatten_page_attributes(&mut selected, page_id)?;
    let removed = pages
        .keys()
        .copied()
        .filter(|candidate| *candidate != page_number as u32)
        .collect::<Vec<_>>();
    selected.delete_pages(&removed);
    selected.prune_objects();
    if selected.get_pages().len() != 1 {
        return Err("PDF 页面树重建失败".to_string());
    }
    Ok(selected)
}

fn pdf_version_key(version: &str) -> (u32, u32) {
    let mut parts = version.splitn(2, '.');
    (
        parts
            .next()
            .and_then(|value| value.parse().ok())
            .unwrap_or(1),
        parts
            .next()
            .and_then(|value| value.parse().ok())
            .unwrap_or(4),
    )
}

fn serialize_selected_pages(selections: Vec<(Document, usize)>) -> Result<Vec<u8>, String> {
    if selections.is_empty() {
        return Err("没有选择任何页面".to_string());
    }
    let version = selections
        .iter()
        .map(|(document, _)| document.version.as_str())
        .chain(std::iter::once("1.5"))
        .max_by_key(|version| pdf_version_key(version))
        .unwrap_or("1.5")
        .to_string();
    let selected_documents = selections
        .into_iter()
        .map(|(source, page_number)| select_single_page(source, page_number))
        .collect::<Result<Vec<_>, _>>()?;
    let mut output = Document::with_version(version);
    let mut page_objects = Vec::with_capacity(selected_documents.len());
    for selected in &selected_documents {
        import_selected_document(&mut output, selected, &mut page_objects)?;
    }
    let pages_id = output.new_object_id();
    let mut page_ids = Vec::with_capacity(page_objects.len());
    for (page_id, page) in page_objects {
        let mut dictionary = page
            .as_dict()
            .map_err(|error| format!("选中页面不是有效字典: {error}"))?
            .clone();
        dictionary.set("Parent", pages_id);
        output
            .objects
            .insert(page_id, Object::Dictionary(dictionary));
        page_ids.push(Object::Reference(page_id));
    }
    let page_count =
        i64::try_from(page_ids.len()).map_err(|_| "PDF 页数超过支持范围".to_string())?;
    let mut pages = Dictionary::new();
    pages.set("Type", "Pages");
    pages.set("Kids", page_ids);
    pages.set("Count", page_count);
    output.set_object(pages_id, pages);
    let mut catalog = Dictionary::new();
    catalog.set("Type", "Catalog");
    catalog.set("Pages", pages_id);
    let catalog_id = output.add_object(catalog);
    output.trailer.set("Root", catalog_id);
    output.prune_objects();
    output.renumber_objects();
    let expected_pages = output.get_pages().len();
    if expected_pages == 0 {
        return Err("PDF 页面树重建失败".to_string());
    }
    let mut bytes = Vec::new();
    output
        .save_to(&mut bytes)
        .map_err(|error| format!("无法序列化 PDF: {error}"))?;
    let verified =
        load_pdf_document(&bytes).map_err(|error| format!("输出 PDF 结构校验失败: {error}"))?;
    if verified.get_pages().len() != expected_pages {
        return Err("输出 PDF 页数校验失败".to_string());
    }
    Ok(bytes)
}

fn import_selected_document(
    output: &mut Document,
    source: &Document,
    page_objects: &mut Vec<(ObjectId, Object)>,
) -> Result<(), String> {
    let page_ids = source.get_pages().into_values().collect::<BTreeSet<_>>();
    if page_ids.len() != 1 {
        return Err("PDF 页面树重建失败".to_string());
    }
    let root_id = source
        .trailer
        .get(b"Root")
        .and_then(Object::as_reference)
        .ok();
    let mut object_ids = source.objects.keys().copied().collect::<Vec<_>>();
    object_ids.sort_unstable();
    let id_map = object_ids
        .into_iter()
        .map(|old_id| (old_id, output.new_object_id()))
        .collect::<BTreeMap<_, _>>();

    for (old_id, object) in &source.objects {
        if Some(*old_id) == root_id
            || matches!(
                object.type_name().unwrap_or(b""),
                b"Pages" | b"Outlines" | b"Outline"
            )
        {
            continue;
        }
        let new_id = id_map[old_id];
        let mut imported = object.clone();
        remap_object_references(&mut imported, &id_map);
        if page_ids.contains(old_id) {
            page_objects.push((new_id, imported));
        } else {
            output.objects.insert(new_id, imported);
        }
    }
    Ok(())
}

fn remap_object_references(object: &mut Object, id_map: &BTreeMap<ObjectId, ObjectId>) {
    match object {
        Object::Array(items) => {
            for item in items {
                remap_object_references(item, id_map);
            }
        }
        Object::Dictionary(dictionary) => {
            for (_, value) in dictionary.iter_mut() {
                remap_object_references(value, id_map);
            }
        }
        Object::Stream(stream) => {
            for (_, value) in stream.dict.iter_mut() {
                remap_object_references(value, id_map);
            }
        }
        Object::Reference(id) => {
            if let Some(new_id) = id_map.get(id) {
                *id = *new_id;
            }
        }
        _ => {}
    }
}

fn pdf_extract(payload: &Value) -> Result<Value, String> {
    let mut request: PdfExtractRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("PDF 页面提取请求格式无效: {error}"))?;
    let paths = request.take_paths()?;
    if paths.is_empty() {
        return Ok(json!({"success": false, "message": "请先选择PDF文件", "logs": []}));
    }
    let selections = request.page_selections.take().unwrap_or_default();
    if !selections.is_empty() {
        return merge_selected_pages(&paths, &selections, request.output_file.take());
    }
    if paths.len() != 1 {
        return Ok(
            json!({"success": false, "message": "多文件提取请先加载预览并选择页面", "logs": []}),
        );
    }
    if !paths[0].exists()
        || paths[0]
            .extension()
            .and_then(|value| value.to_str())
            .is_none_or(|value| !value.eq_ignore_ascii_case("pdf"))
    {
        return Ok(json!({
            "success": false,
            "message": format!("PDF文件不存在或格式不正确: {}", paths[0].display()),
            "logs": []
        }));
    }
    let ranges = request
        .page_ranges
        .take()
        .unwrap_or_default()
        .trim()
        .to_string();
    if ranges.is_empty() {
        return Ok(json!({
            "success": false,
            "message": "请输入页码范围，或先加载预览选择页面",
            "logs": []
        }));
    }
    let info = match read_pdf(&paths[0]) {
        Ok(value) => value,
        Err(error) => {
            return Ok(json!({"success": false, "message": error, "logs": []}));
        }
    };
    let pages = parse_page_ranges(&ranges, info.page_count)?;
    let output = if let Some(value) = request
        .output_file
        .take()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        ensure_output_path(Path::new(&value), "pdf", &[&info.path])?
    } else {
        let safe_ranges = ranges.replace(' ', "").replace(',', "_");
        info.path.with_file_name(format!(
            "{}_extract_{safe_ranges}.pdf",
            info.path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("output")
        ))
    };
    let selected = pages
        .iter()
        .map(|page| (info.document.clone(), *page))
        .collect();
    let output_bytes = serialize_selected_pages(selected)?;
    atomic_write(&output, &output_bytes)?;
    let output_info = read_pdf(&output)?;
    let output_size = fs::metadata(&output_info.path)
        .map_err(|error| format!("无法读取输出 PDF 信息: {error}"))?
        .len();
    let mut logs = vec![format!(
        "开始提取 {} 的 {} 页",
        info.path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default(),
        pages.len()
    )];
    logs.push(format!("[DEBUG] 开始读取PDF: {}", info.path.display()));
    logs.push(format!("[DEBUG] PDF共 {} 页", info.page_count));
    logs.extend(pages.iter().map(|page| format!("[DEBUG] 添加第 {page} 页")));
    logs.push(format!("[DEBUG] 准备写入: {}", output.display()));
    logs.push(format!("[DEBUG] 输出文件大小: {output_size} bytes"));
    Ok(json!({
        "success": true,
        "message": format!(
            "已从 {} 提取 {}/{} 页",
            info.path.file_name().and_then(|value| value.to_str()).unwrap_or_default(),
            pages.len(),
            info.page_count
        ),
        "output_file": output_info.path,
        "extracted": pages.len(),
        "total_pages": info.page_count,
        "logs": logs,
    }))
}

fn parse_selection(
    value: &PdfPageSelectionRequest,
    index: usize,
) -> Result<(PathBuf, usize, i64), String> {
    let path = value.file_path.trim();
    if path.is_empty() {
        return Err("页面选择数据不完整".to_string());
    }
    Ok((
        PathBuf::from(path),
        value.page_num,
        value.order.unwrap_or(index as i64 + 1),
    ))
}

fn merge_selected_pages(
    paths: &[PathBuf],
    selections: &[PdfPageSelectionRequest],
    output: Option<String>,
) -> Result<Value, String> {
    let first_input = &paths[0];
    let mut parsed = Vec::new();
    for (index, selection) in selections.iter().enumerate() {
        let (path, page, order) = parse_selection(selection, index)?;
        let info = read_pdf(&path)?;
        if page > info.page_count {
            return Err(format!(
                "文件 {} 的页码 {} 超出范围（总页数: {}）",
                path.file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default(),
                page,
                info.page_count
            ));
        }
        parsed.push((info, page, order));
    }
    let same_file = parsed
        .iter()
        .map(|(info, _, _)| &info.path)
        .collect::<BTreeSet<_>>()
        .len()
        == 1;
    if same_file {
        parsed.sort_by_key(|(_, page, _)| *page);
    } else {
        parsed.sort_by_key(|(_, _, order)| *order);
    }
    let merged_count = parsed.len();
    let output = if let Some(path) = output {
        let input_paths = parsed
            .iter()
            .map(|(info, _, _)| info.path.as_path())
            .collect::<Vec<_>>();
        ensure_output_path(Path::new(&path), "pdf", &input_paths)?
    } else {
        fs::canonicalize(first_input)
            .unwrap_or_else(|_| first_input.to_path_buf())
            .with_file_name(format!(
                "{}_merged_pages.pdf",
                first_input
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or("output")
            ))
    };
    let file_count = parsed
        .iter()
        .map(|(info, _, _)| &info.path)
        .collect::<BTreeSet<_>>()
        .len();
    let selected = parsed
        .into_iter()
        .map(|(info, page, _)| (info.document, page))
        .collect();
    let output_bytes = serialize_selected_pages(selected)?;
    atomic_write(&output, &output_bytes)?;
    let output_info = read_pdf(&output)?;
    Ok(json!({
        "success": true,
        "message": format!("已合并 {merged_count} 页（来自 {file_count} 个文件）"),
        "output_file": output_info.path,
        "merged_count": merged_count,
        "file_count": file_count,
        "logs": [format!("开始合并 {merged_count} 页")],
    }))
}

fn optimize_standard_pdf(input: &PdfInfo) -> Result<(Vec<u8>, &'static str), String> {
    let mut document = input.document.clone();
    let expected_pages = document.get_pages().len();
    document.prune_objects();
    document.renumber_objects();
    document.compress();
    let mut optimized = Vec::new();
    document
        .save_to(&mut optimized)
        .map_err(|error| format!("PDF 标准压缩失败: {error}"))?;
    let verified =
        load_pdf_document(&optimized).map_err(|error| format!("压缩输出结构校验失败: {error}"))?;
    if verified.get_pages().len() != expected_pages {
        return Err("压缩输出页数校验失败".to_string());
    }
    if optimized.len() <= input.bytes.len() {
        Ok((optimized, "standard"))
    } else {
        Ok((input.bytes.clone(), "standard-unchanged"))
    }
}

fn compression_summary(input: &PdfInfo, output: &Path, method: &str) -> Result<Value, String> {
    let original_size = input.bytes.len() as u64;
    let compressed_size = fs::metadata(output)
        .map_err(|error| error.to_string())?
        .len();
    let saved_bytes = original_size as i128 - compressed_size as i128;
    let saved_percent = if original_size == 0 {
        0.0
    } else {
        ((saved_bytes as f64 / original_size as f64) * 10_000.0).round() / 100.0
    };
    Ok(json!({
        "input_file": input.path,
        "output_file": output,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "saved_bytes": saved_bytes,
        "saved_percent": saved_percent,
        "method": method,
        "original_size_text": format_size(original_size),
        "compressed_size_text": format_size(compressed_size),
    }))
}

fn format_size(size: u64) -> String {
    let mut value = size as f64;
    for unit in ["B", "KB", "MB", "GB"] {
        if value < 1024.0 || unit == "GB" {
            return if unit == "B" {
                format!("{} B", value as u64)
            } else {
                format!("{value:.2} {unit}")
            };
        }
        value /= 1024.0;
    }
    format!("{value:.2} GB")
}

fn pdf_compress(payload: &Value) -> Result<Value, String> {
    let paths = path_list(payload.get("pdf_files").or_else(|| payload.get("pdf_file")))?;
    if paths.is_empty() {
        return Ok(
            json!({"success": false, "message": "请先选择PDF文件", "logs": [], "output_files": []}),
        );
    }
    let mode = payload
        .get("compression_mode")
        .and_then(Value::as_str)
        .unwrap_or("standard")
        .trim()
        .to_ascii_lowercase();
    if mode != "standard" && mode != "strong" {
        return Ok(
            json!({"success": false, "message": format!("不支持的压缩模式: {mode}"), "logs": [], "output_files": []}),
        );
    }
    let output_dir = optional_string(payload, "output_dir").map(PathBuf::from);
    if let Some(directory) = output_dir.as_ref() {
        if directory.exists() && !directory.is_dir() {
            return Ok(
                json!({"success": false, "message": format!("输出路径不是目录: {}", directory.display()), "logs": [], "output_files": []}),
            );
        }
        fs::create_dir_all(directory).map_err(|error| format!("无法创建输出目录: {error}"))?;
    }
    let explicit_output = optional_string(payload, "output_file");
    let mut results = Vec::new();
    let mut failures = Vec::new();
    let mut logs = vec![format!("开始压缩 {} 个PDF文件", paths.len())];
    for (index, path) in paths.iter().enumerate() {
        match read_pdf(path) {
            Ok(info) => {
                let output = if paths.len() == 1 {
                    explicit_output
                        .as_ref()
                        .map(|value| ensure_output_path(Path::new(value), "pdf", &[&info.path]))
                        .transpose()?
                        .unwrap_or_else(|| {
                            info.path.with_file_name(format!(
                                "{}_compressed.pdf",
                                info.path
                                    .file_stem()
                                    .and_then(|value| value.to_str())
                                    .unwrap_or("output")
                            ))
                        })
                } else {
                    let directory = output_dir
                        .as_deref()
                        .unwrap_or_else(|| info.path.parent().unwrap_or(Path::new(".")));
                    ensure_output_path(
                        &directory.join(format!(
                            "{}_compressed.pdf",
                            info.path
                                .file_stem()
                                .and_then(|value| value.to_str())
                                .unwrap_or("output")
                        )),
                        "pdf",
                        &[&info.path],
                    )?
                };
                logs.push(format!(
                    "[{}/{}] 压缩 {}",
                    index + 1,
                    paths.len(),
                    info.path
                        .file_name()
                        .and_then(|value| value.to_str())
                        .unwrap_or_default()
                ));
                let optimized = if mode == "strong" {
                    pdfium_runtime::strong_compress_pdf(&info.bytes).map(|bytes| {
                        if bytes.len() <= info.bytes.len() {
                            (bytes, "strong")
                        } else {
                            (info.bytes.clone(), "strong-unchanged")
                        }
                    })
                } else {
                    optimize_standard_pdf(&info)
                };
                let (bytes, method) = match optimized {
                    Ok(value) => value,
                    Err(error) => {
                        logs.push(format!(
                            "失败: {} -> {error}",
                            info.path
                                .file_name()
                                .and_then(|value| value.to_str())
                                .unwrap_or_default()
                        ));
                        failures.push(json!({"file": info.path, "reason": error}));
                        continue;
                    }
                };
                if let Err(error) =
                    atomic_write(&output, &bytes).and_then(|_| read_pdf(&output).map(|_| ()))
                {
                    failures.push(json!({"file": info.path, "reason": error}));
                    continue;
                }
                let result = compression_summary(&info, &output, method)?;
                let original_size_text = result["original_size_text"].as_str().unwrap_or_default();
                let compressed_size_text =
                    result["compressed_size_text"].as_str().unwrap_or_default();
                let saved_percent = result["saved_percent"].as_f64().unwrap_or(0.0);
                logs.push(format!(
                    "完成: {original_size_text} -> {compressed_size_text} (节省 {saved_percent}%)"
                ));
                if saved_percent <= 0.0 {
                    logs.push("提示: 该文件已经比较紧凑，压缩后体积未明显降低".to_string());
                }
                results.push(result);
            }
            Err(error) => failures.push(json!({"file": path, "reason": error})),
        }
    }
    let output_files: Vec<Value> = results
        .iter()
        .filter_map(|result| result.get("output_file").cloned())
        .collect();
    let total_original: u64 = results
        .iter()
        .filter_map(|result| result.get("original_size").and_then(Value::as_u64))
        .sum();
    let total_compressed: u64 = results
        .iter()
        .filter_map(|result| result.get("compressed_size").and_then(Value::as_u64))
        .sum();
    let saved = total_original as i128 - total_compressed as i128;
    let total_saved_percent = if total_original == 0 {
        0.0
    } else {
        ((saved as f64 / total_original as f64) * 10_000.0).round() / 100.0
    };
    let success = !results.is_empty() && failures.is_empty();
    let message = if success {
        format!(
            "压缩完成：成功 {} 个，失败 0 个，整体节省 {total_saved_percent}%",
            results.len()
        )
    } else if !results.is_empty() {
        format!(
            "压缩部分完成：成功 {} 个，失败 {} 个",
            results.len(),
            failures.len()
        )
    } else {
        format!("压缩失败：{} 个文件未处理", failures.len())
    };
    Ok(json!({
        "success": success,
        "message": message,
        "logs": logs,
        "output_file": output_files.first().cloned().unwrap_or(Value::Null),
        "output_files": output_files,
        "results": results,
        "failures": failures,
        "total_original_size": total_original,
        "total_compressed_size": total_compressed,
        "total_saved_bytes": saved,
        "total_saved_percent": total_saved_percent,
    }))
}

// Notice state is deliberately separate from task state so a restart can
// recover verified artifacts without trusting a stale in-memory task.

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
struct NoticeStages {
    rewrite: bool,
    authorization: bool,
    rectification: bool,
    disposal: bool,
    pdf: bool,
}

impl NoticeStages {
    fn all(&self) -> bool {
        self.rewrite && self.authorization && self.rectification && self.disposal && self.pdf
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct NoticeArchiveOutput {
    #[serde(default)]
    member_index: usize,
    #[serde(default)]
    member_name: String,
    path: String,
    size: u64,
    sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct NoticeArchiveExtraction {
    archive_path: String,
    archive_sha256: String,
    outputs: Vec<NoticeArchiveOutput>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct NoticeState {
    #[serde(default = "default_notice_state_version")]
    schema_version: u32,
    #[serde(default = "default_notice_state_version")]
    version: u32,
    #[serde(default)]
    target_path: String,
    #[serde(default)]
    source_sha256: String,
    #[serde(default)]
    stages: NoticeStages,
    #[serde(default)]
    artifacts: Vec<String>,
    #[serde(default)]
    generated_files: Vec<String>,
    #[serde(default)]
    pdf_outputs: Vec<String>,
    #[serde(default)]
    deleted_files: Vec<String>,
    #[serde(default)]
    archive_extractions: Vec<NoticeArchiveExtraction>,
    #[serde(default, rename = "complete", alias = "completed")]
    completed: bool,
    #[serde(default)]
    updated_at: Value,
    #[serde(flatten)]
    compatibility_fields: BTreeMap<String, Value>,
}

fn default_notice_state_version() -> u32 {
    NOTICE_STATE_VERSION
}

fn new_notice_state(root: &Path) -> NoticeState {
    NoticeState {
        schema_version: NOTICE_STATE_VERSION,
        version: NOTICE_STATE_VERSION,
        target_path: root.to_string_lossy().to_string(),
        source_sha256: String::new(),
        stages: NoticeStages::default(),
        artifacts: Vec::new(),
        generated_files: Vec::new(),
        pdf_outputs: Vec::new(),
        deleted_files: Vec::new(),
        archive_extractions: Vec::new(),
        completed: false,
        updated_at: Value::Null,
        compatibility_fields: BTreeMap::new(),
    }
}

#[derive(Debug, Clone)]
struct NoticeTask {
    task_id: String,
    generation: u64,
    target_path: String,
    target_key: String,
    running: bool,
    done: bool,
    success: bool,
    progress: u8,
    message: String,
    logs: Vec<String>,
    result: Option<Value>,
    error: Option<String>,
    created_at: u64,
    finished_at: Option<u64>,
}

static NOTICE_TASKS: OnceLock<Mutex<HashMap<String, NoticeTask>>> = OnceLock::new();
static NOTICE_TASK_LIFECYCLE: OnceLock<TaskManager> = OnceLock::new();

fn notice_tasks() -> &'static Mutex<HashMap<String, NoticeTask>> {
    NOTICE_TASKS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn notice_task_lifecycle() -> &'static TaskManager {
    NOTICE_TASK_LIFECYCLE.get_or_init(TaskManager::in_memory)
}

fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn local_date_text() -> String {
    use chrono::Datelike;

    let today = chrono::Local::now().date_naive();
    format!("{}年{}月{}日", today.year(), today.month(), today.day())
}

fn parse_notice_counter_numbers(value: Option<&Value>) -> BTreeSet<i64> {
    let mut numbers = BTreeSet::new();
    let values = match value {
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| item.to_string())
            .collect::<Vec<_>>(),
        Some(Value::String(value)) => vec![value.clone()],
        Some(other) => vec![other.to_string()],
        None => Vec::new(),
    };
    for value in values {
        for part in value.split([',', '，', ';', '；']) {
            let part = part.trim();
            if let Some((left, right)) = part.split_once('-') {
                let Ok(left) = left.trim().parse::<i64>() else {
                    continue;
                };
                let Ok(right) = right.trim().parse::<i64>() else {
                    continue;
                };
                let (low, high) = (left.min(right).max(1), left.max(right));
                numbers.extend(low..=high);
            } else if let Ok(number) = part.parse::<i64>() {
                if number > 0 {
                    numbers.insert(number);
                }
            }
        }
    }
    numbers
}

fn reserve_notice_number_and_rewrite(
    config_path: &Path,
    document: &Path,
    rectification: bool,
) -> Result<Option<(i64, i32)>, String> {
    let pattern = if rectification {
        Regex::new(r"鄞网办责字\[\d{4}\]\d+号")
            .map_err(|error| format!("compile rectification number pattern failed: {error}"))?
    } else {
        Regex::new(r"〔\d{4}〕第\d+期")
            .map_err(|error| format!("compile notification number pattern failed: {error}"))?
    };
    let text = docx_text_content(document)?;
    if !pattern.is_match(&text) {
        return Ok(None);
    }
    let key = if rectification {
        "rectification_number"
    } else {
        "notification_number"
    };
    let unavailable_key = if rectification {
        "unavailable_rectification_numbers"
    } else {
        "unavailable_notification_numbers"
    };
    let store = ConfigStore::new(config_path.to_path_buf());
    let response = store.transact(|config| {
        let counters = config
            .get("report_counters")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        use chrono::Datelike;
        let now = chrono::Local::now();
        let year = counters
            .get("year")
            .and_then(Value::as_i64)
            .filter(|value| *value > 1900)
            .unwrap_or(i64::from(now.year()));
        let mut current = counters
            .get(key)
            .and_then(Value::as_i64)
            .filter(|value| *value > 0)
            .unwrap_or(1);
        let unavailable = parse_notice_counter_numbers(counters.get(unavailable_key));
        while unavailable.contains(&current) {
            current = current.saturating_add(1);
        }
        let mut next = current.saturating_add(1);
        while unavailable.contains(&next) {
            next = next.saturating_add(1);
        }
        let replacement = if rectification {
            format!("鄞网办责字[{year}]{current}号")
        } else {
            format!("〔{year}〕第{current}期")
        };
        let temporary = document.with_file_name(format!(
            ".{}.koi-number-{}.tmp",
            document
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("notice.docx"),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let rewrite_result = rewrite_ooxml_document_part(document, &temporary, |xml| {
            let (rewritten, changed) = rewrite_docx_paragraphs(&xml, |paragraph| {
                pattern.is_match(paragraph).then(|| {
                    pattern
                        .replace(paragraph, replacement.as_str())
                        .into_owned()
                })
            })?;
            if !changed {
                return Err("notice number disappeared before atomic commit".to_string());
            }
            Ok(rewritten)
        });
        if let Err(error) = rewrite_result {
            let _ = fs::remove_file(&temporary);
            return Err(error);
        }
        let backup = document.with_file_name(format!(
            ".{}.koi-number-backup-{}.tmp",
            document
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("notice.docx"),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::rename(document, &backup)
            .map_err(|error| format!("numbered DOCX backup rename failed: {error}"))?;
        if let Err(error) = fs::rename(&temporary, document) {
            let _ = fs::rename(&backup, document);
            return Err(format!("numbered DOCX atomic replace failed: {error}"));
        }
        fs::remove_file(&backup)
            .map_err(|error| format!("numbered DOCX backup cleanup failed: {error}"))?;

        let target = config
            .as_object_mut()
            .ok_or_else(|| "config root is not an object".to_string())?;
        let counters = target
            .entry("report_counters".to_string())
            .or_insert_with(|| json!({}));
        let counters = counters
            .as_object_mut()
            .ok_or_else(|| "report_counters is not an object".to_string())?;
        counters.insert(key.to_string(), json!(next));
        counters.insert("year".to_string(), json!(year));
        counters.insert(
            "last_updated".to_string(),
            Value::String(now.format("%Y-%m-%d %H:%M:%S").to_string()),
        );
        Ok((json!({"number": current, "year": year}), true))
    })?;
    let number = response
        .get("number")
        .and_then(Value::as_i64)
        .zip(response.get("year").and_then(Value::as_i64))
        .map(|(number, year)| (number, year as i32));
    Ok(number)
}

fn prune_notice_tasks_locked(tasks: &mut HashMap<String, NoticeTask>, now: u64) {
    tasks.retain(|_, task| {
        task.running
            || now.saturating_sub(task.finished_at.unwrap_or(task.created_at))
                <= NOTICE_TASK_RETENTION_SECONDS
    });

    let mut completed = tasks
        .values()
        .filter(|task| !task.running)
        .map(|task| {
            (
                task.finished_at.unwrap_or(task.created_at),
                task.task_id.clone(),
            )
        })
        .collect::<Vec<_>>();
    completed.sort();
    let overflow = completed.len().saturating_sub(NOTICE_TASK_MAX_COMPLETED);
    for (_, task_id) in completed.into_iter().take(overflow) {
        tasks.remove(&task_id);
    }
}

fn canonical_dir(path: &Path) -> Result<PathBuf, String> {
    let metadata =
        fs::symlink_metadata(path).map_err(|_| format!("目标路径不存在: {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(format!("目标路径不是目录: {}", path.display()));
    }
    fs::canonicalize(path).map_err(|error| format!("无法解析目标路径: {error}"))
}

fn walk_files(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut files = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let entries = fs::read_dir(&directory)
            .map_err(|error| format!("无法读取目录 {}: {error}", directory.display()))?;
        for entry in entries {
            let entry = entry.map_err(|error| format!("读取目录项失败: {error}"))?;
            let path = entry.path();
            let metadata =
                fs::symlink_metadata(&path).map_err(|error| format!("读取目录项失败: {error}"))?;
            if metadata.file_type().is_symlink() {
                continue;
            }
            if metadata.is_dir() {
                stack.push(path);
            } else if metadata.is_file() {
                files.push(path);
            }
        }
    }
    files.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    Ok(files)
}

fn sha256_file(path: &Path, digest: &mut Sha256) -> Result<(), String> {
    let mut file = File::open(path).map_err(|error| format!("无法读取源文件: {error}"))?;
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("读取源文件失败: {error}"))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(())
}

fn file_sha256(path: &Path) -> Result<String, String> {
    let mut digest = Sha256::new();
    sha256_file(path, &mut digest)?;
    Ok(format!("{:x}", digest.finalize()))
}

fn source_digest(root: &Path) -> Result<String, String> {
    let mut digest = Sha256::new();
    let mut files = walk_files(root)?;
    files.retain(|path| notice_digest_includes(path));
    for file in files {
        let relative = file
            .strip_prefix(root)
            .unwrap_or(&file)
            .to_string_lossy()
            .replace('\\', "/");
        digest.update(relative.as_bytes());
        digest.update([0]);
        let length = fs::metadata(&file)
            .map_err(|error| format!("无法读取源文件信息: {error}"))?
            .len();
        digest.update(length.to_le_bytes());
        sha256_file(&file, &mut digest)?;
        digest.update([0xff]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn notice_digest_includes(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if name == NOTICE_STATE_FILE || name.starts_with(".koi_notice_process_state.json.tmp-") {
        return false;
    }
    if path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("pdf"))
    {
        return false;
    }
    if path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
        && docx_path_has_rewrite_marker(path)
    {
        return false;
    }
    let generated_name = ["授权委托书", "责令整改", "处置文件", "处置报告"]
        .iter()
        .any(|keyword| name.contains(keyword));
    if generated_name && !name.starts_with(|character: char| character.is_ascii_digit()) {
        return false;
    }
    true
}

fn state_path(root: &Path) -> PathBuf {
    root.join(NOTICE_STATE_FILE)
}

fn load_notice_state(root: &Path) -> Result<Option<NoticeState>, String> {
    let path = state_path(root);
    if !path.exists() {
        return Ok(None);
    }
    let bytes = fs::read(&path).map_err(|error| format!("无法读取通报断点文件: {error}"))?;
    let state: NoticeState =
        serde_json::from_slice(&bytes).map_err(|error| format!("通报断点文件损坏: {error}"))?;
    if state.schema_version != NOTICE_STATE_VERSION || state.version != NOTICE_STATE_VERSION {
        return Err("不支持的通报断点版本".to_string());
    }
    Ok(Some(state))
}

fn save_notice_state(root: &Path, state: &NoticeState) -> Result<(), String> {
    let bytes =
        serde_json::to_vec_pretty(state).map_err(|error| format!("序列化通报断点失败: {error}"))?;
    atomic_write(&state_path(root), &bytes)
        .map_err(|error| format!("原子写入通报断点失败: {error}"))
}

#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
enum NoticeFingerprintSize {
    Number(u64),
    Text(String),
}

impl NoticeFingerprintSize {
    fn value(&self) -> Option<u64> {
        match self {
            Self::Number(value) => Some(*value),
            Self::Text(value) => value.trim().parse::<u64>().ok(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
struct NoticeSourceFingerprint {
    name: String,
    #[serde(default, alias = "relative_path")]
    path: Option<String>,
    #[serde(default)]
    size: Option<NoticeFingerprintSize>,
    #[serde(default)]
    sha256: Option<String>,
}

/// Validate the legacy Python checkpoint before allowing its stage flags to
/// influence a Rust run.  Python releases stored `input_signature` as a list
/// of `{name, size, sha256}` records (newer snapshots may also include a
/// relative `path`).  Stage flags alone are not evidence: a user can replace a
/// same-named source after a crash, and blindly trusting those flags would
/// skip the rewrite/numbering transaction for the new contents.
fn python_checkpoint_matches_sources(root: &Path, state: &NoticeState) -> bool {
    let signature = state
        .compatibility_fields
        .get("input_signature")
        .and_then(Value::as_array);
    let Some(signature) = signature else {
        return false;
    };
    if signature.is_empty() {
        return false;
    }

    let files = match walk_files(root) {
        Ok(files) => files
            .into_iter()
            .filter(|path| {
                path.file_name()
                    .and_then(|value| value.to_str())
                    .map(|name| {
                        name != NOTICE_STATE_FILE
                            && !name.starts_with(".koi_notice_process_state.json.tmp-")
                    })
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>(),
        Err(_) => return false,
    };

    let mut matched_sources = HashSet::new();
    for entry in signature {
        let Ok(entry) = serde_json::from_value::<NoticeSourceFingerprint>(entry.clone()) else {
            return false;
        };
        let name = entry.name.trim();
        let expected_size = entry.size.as_ref().and_then(NoticeFingerprintSize::value);
        let expected_hash = entry
            .sha256
            .as_deref()
            .map(|value| value.trim().to_ascii_lowercase());
        if name.is_empty() || expected_size.is_none() || expected_hash.as_deref().is_none() {
            return false;
        }
        let expected_size = expected_size.unwrap_or_default();
        let expected_hash = expected_hash.unwrap_or_default();
        if expected_hash.len() != 64
            || !expected_hash
                .chars()
                .all(|character| character.is_ascii_hexdigit())
        {
            return false;
        }

        let explicit_path = entry
            .path
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty());
        let candidate = if let Some(relative) = explicit_path {
            let relative = Path::new(relative);
            if relative.is_absolute()
                || relative.components().any(|component| {
                    matches!(
                        component,
                        Component::ParentDir | Component::RootDir | Component::Prefix(_)
                    )
                })
            {
                return false;
            }
            let candidate = root.join(relative);
            let metadata = match fs::symlink_metadata(&candidate) {
                Ok(metadata) => metadata,
                Err(_) => return false,
            };
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return false;
            }
            let canonical = match fs::canonicalize(candidate) {
                Ok(path) if path.starts_with(root) => path,
                _ => return false,
            };
            if canonical.file_name().and_then(|value| value.to_str()) != Some(name) {
                return false;
            }
            canonical
        } else {
            let candidates = files
                .iter()
                .filter(|path| {
                    path.file_name()
                        .and_then(|value| value.to_str())
                        .map(|value| value == name)
                        .unwrap_or(false)
                })
                .cloned()
                .collect::<Vec<_>>();
            // A filename-only Python record cannot distinguish two sources
            // with the same name in different company folders. Refuse to use
            // that ambiguous evidence rather than selecting one arbitrarily.
            if candidates.len() != 1 {
                return false;
            }
            candidates.into_iter().next().unwrap_or_default()
        };
        let fingerprint_matches = fs::metadata(&candidate)
            .ok()
            .filter(|metadata| metadata.is_file() && metadata.len() == expected_size)
            .is_some_and(|_| {
                file_sha256(&candidate).is_ok_and(|hash| hash.eq_ignore_ascii_case(&expected_hash))
            });
        if !fingerprint_matches {
            return false;
        }
        matched_sources.insert(candidate);
    }

    // A checkpoint also becomes stale when another source was added after it
    // was written. Python prefixes discovered source notices with digits
    // before saving the checkpoint; generated authorization/rectification/
    // disposal documents are excluded by name, and rewritten notices are
    // excluded by their provenance marker.
    files
        .iter()
        .filter(|path| likely_python_notice_source(path))
        .all(|path| matched_sources.contains(path))
}

fn likely_python_notice_source(path: &Path) -> bool {
    if path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case("docx") || value.eq_ignore_ascii_case("doc"))
        != Some(true)
    {
        return false;
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if name.starts_with("~$")
        || !name.starts_with(|character: char| character.is_ascii_digit())
        || ["模板", "授权委托书", "责令整改", "处置"]
            .iter()
            .any(|keyword| name.contains(keyword))
        || [".clean_backup.", ".final_backup.", ".backup.", ".temp."]
            .iter()
            .any(|marker| name.contains(marker))
    {
        return false;
    }
    if path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
        && docx_path_has_rewrite_marker(path)
    {
        return false;
    }
    name.contains("关于") || name.contains("通报") || name.contains("存在")
}

fn valid_docx_package(path: &Path) -> bool {
    if path
        .extension()
        .and_then(|value| value.to_str())
        .is_none_or(|value| !value.eq_ignore_ascii_case("docx"))
    {
        return false;
    }
    File::open(path)
        .ok()
        .and_then(|file| ZipArchive::new(file).ok())
        .is_some_and(|mut archive| archive.by_name("word/document.xml").is_ok())
}

fn normalize_notice_source_names(
    root: &Path,
    logs: &mut Vec<String>,
) -> Result<Vec<PathBuf>, String> {
    let mut candidates = Vec::new();
    for path in walk_files(root)? {
        if !likely_python_notice_source(&path) {
            continue;
        }
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if name.starts_with(|character: char| character.is_ascii_digit()) {
            candidates.push(path);
            continue;
        }
        // Keep malformed inputs in place so the failure response does not
        // hide the original path. Valid DOCX notices follow Python's
        // numeric-prefix discovery rule before stage 1 starts.
        if !valid_docx_package(&path) {
            candidates.push(path);
            continue;
        }
        let prefix = format!(
            "{}{}",
            now_seconds(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        );
        let target = path.with_file_name(format!(
            "{prefix}{}",
            path.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("notice.docx")
        ));
        fs::rename(&path, &target)
            .map_err(|error| format!("重命名通报源失败 {}: {error}", path.display()))?;
        logs.push(format!(
            "重命名原始通报: {} -> {}",
            path.display(),
            target.display()
        ));
        candidates.push(target);
    }
    candidates.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    candidates.dedup();
    Ok(candidates)
}

fn notice_file_kind(path: &Path) -> Option<&'static str> {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .as_deref()
    {
        Some("docx") | Some("doc") => Some("word"),
        Some("pdf") => Some("pdf"),
        _ => None,
    }
}

/// Return whether a Word file belongs to the notice workflow.
///
/// The Python command does not treat every ``*.docx`` below the target as a
/// report.  In particular, an unrelated office document must not turn an
/// otherwise empty directory into a failed notice run.  Keep the filtering
/// here before the result/counting pass so the Rust response has the same
/// no-op semantics as the legacy command.
fn notice_word_candidate(path: &Path) -> bool {
    if path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case("docx"))
        != Some(true)
    {
        return false;
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    if name.is_empty()
        || name.starts_with("~$")
        || name.starts_with('.')
        || name.contains("模板")
        || [".clean_backup.", ".final_backup.", ".backup.", ".temp."]
            .iter()
            .any(|marker| name.contains(marker))
        || path
            .components()
            .any(|component| component.as_os_str() == "Report_Template")
    {
        return false;
    }
    if docx_path_has_rewrite_marker(path) {
        return true;
    }
    notice_name_candidate(path)
}

fn notice_source_candidate(path: &Path) -> bool {
    if !notice_word_candidate(path) || docx_path_has_rewrite_marker(path) {
        return false;
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    !["授权委托书", "责令整改", "处置文件", "处置报告"]
        .iter()
        .any(|keyword| name.contains(keyword))
}

fn notice_pdf_artifact_candidate(path: &Path) -> bool {
    if path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.eq_ignore_ascii_case("pdf"))
        != Some(true)
    {
        return false;
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    name.starts_with("授权委托书") || name.starts_with("责令整改")
}

fn notice_archive_kind(path: &Path) -> Option<&'static str> {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .as_deref()
    {
        Some("zip") => Some("zip"),
        Some("7z") => Some("7z"),
        Some("rar") => Some("rar"),
        _ => None,
    }
}

fn canonical_notice_target(path: &Path) -> Result<(PathBuf, Option<PathBuf>), String> {
    let metadata =
        fs::symlink_metadata(path).map_err(|_| format!("目标路径不存在: {}", path.display()))?;
    if metadata.file_type().is_symlink() {
        return Err("目标路径不能是符号链接".to_string());
    }
    if metadata.is_dir() {
        return canonical_dir(path).map(|root| (root, None));
    }
    if !metadata.is_file() || notice_archive_kind(path).is_none() {
        return Err("只支持文件夹或 ZIP/7z/RAR 压缩包".to_string());
    }
    let archive = fs::canonicalize(path).map_err(|error| format!("无法解析压缩包路径: {error}"))?;
    let root = archive
        .parent()
        .ok_or_else(|| "压缩包没有可用的父目录".to_string())?
        .to_path_buf();
    Ok((root, Some(archive)))
}

fn archive_relative_path(name: &str) -> Result<PathBuf, String> {
    if name.encode_utf16().count() > 8_192 {
        return Err("压缩包成员路径过长，已拒绝".to_string());
    }
    let normalized = name.replace('\\', "/");
    let mut relative = PathBuf::new();
    for component in Path::new(&normalized).components() {
        match component {
            Component::Normal(value) => {
                let text = value.to_string_lossy();
                let stem = text
                    .trim_end_matches([' ', '.'])
                    .split('.')
                    .next()
                    .unwrap_or_default()
                    .trim_end_matches([' ', '.'])
                    .to_ascii_uppercase();
                let reserved_device =
                    matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL" | "CLOCK$")
                        || stem
                            .strip_prefix("COM")
                            .or_else(|| stem.strip_prefix("LPT"))
                            .is_some_and(|suffix| {
                                (suffix.len() == 1 && matches!(suffix.as_bytes()[0], b'1'..=b'9'))
                                    || matches!(suffix, "¹" | "²" | "³")
                            });
                if text.is_empty()
                    || text.encode_utf16().count() > 255
                    || text.ends_with([' ', '.'])
                    || text.chars().any(|character| {
                        character < ' '
                            || matches!(character, '<' | '>' | ':' | '"' | '|' | '?' | '*')
                    })
                    || reserved_device
                {
                    return Err(format!("压缩包包含不安全路径: {name}"));
                }
                relative.push(value);
            }
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(format!("压缩包包含不安全路径: {name}"));
            }
        }
    }
    if relative.as_os_str().is_empty() {
        return Err(format!("压缩包包含空路径: {name}"));
    }
    Ok(relative)
}

fn ensure_safe_directory_chain(root: &Path, directory: &Path) -> Result<(), String> {
    let relative = directory
        .strip_prefix(root)
        .map_err(|_| format!("解压目标越过根目录: {}", directory.display()))?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        let Component::Normal(value) = component else {
            return Err(format!("解压目标包含不安全路径: {}", directory.display()));
        };
        current.push(value);
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(format!("解压目标包含符号链接: {}", current.display()));
            }
            Ok(metadata) if !metadata.is_dir() => {
                return Err(format!("解压目标父路径不是目录: {}", current.display()));
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                fs::create_dir(&current)
                    .map_err(|error| format!("创建解压目录失败 {}: {error}", current.display()))?;
            }
            Err(error) => {
                return Err(format!("检查解压目录失败 {}: {error}", current.display()));
            }
        }
    }
    Ok(())
}

fn archive_target_key(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/").to_lowercase()
}

fn unique_archive_target(path: &Path, reserved: &mut HashSet<String>) -> PathBuf {
    let available = |candidate: &Path, reserved: &HashSet<String>| {
        !candidate.exists() && !reserved.contains(&archive_target_key(candidate))
    };
    if available(path, reserved) {
        reserved.insert(archive_target_key(path));
        return path.to_path_buf();
    }
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("file");
    let suffix = path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{value}"))
        .unwrap_or_default();
    for index in 2..1000 {
        let candidate = path.with_file_name(format!("{stem} ({index}){suffix}"));
        if available(&candidate, reserved) {
            reserved.insert(archive_target_key(&candidate));
            return candidate;
        }
    }
    let candidate = path.with_file_name(format!(
        "{stem}_{}{suffix}",
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    ));
    reserved.insert(archive_target_key(&candidate));
    candidate
}

#[derive(Debug)]
struct ZipExtractionEntry {
    index: usize,
    member_name: String,
    target: PathBuf,
    is_directory: bool,
    already_valid: bool,
    expected_size: u64,
}

#[derive(Debug)]
struct ExtractedArchiveOutput {
    member_index: usize,
    member_name: String,
    path: PathBuf,
}

#[derive(Debug, Clone)]
struct SevenZipEntry {
    index: usize,
    member_name: String,
    target: PathBuf,
    is_directory: bool,
    already_valid: bool,
    expected_size: u64,
}

fn read_bounded<R: Read>(mut reader: R, limit: usize) -> Result<Vec<u8>, String> {
    let mut output = Vec::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = reader
            .read(&mut buffer)
            .map_err(|error| format!("读取 7-Zip 输出失败: {error}"))?;
        if count == 0 {
            return Ok(output);
        }
        if output.len().saturating_add(count) > limit {
            return Err(format!("7-Zip 输出超过 {} bytes 限制", limit));
        }
        output.extend_from_slice(&buffer[..count]);
    }
}

fn archive_command_error(status: Option<std::process::ExitStatus>, stderr: &[u8]) -> String {
    let detail =
        String::from_utf8_lossy(&stderr[..stderr.len().min(MAX_NOTICE_ARCHIVE_DIAGNOSTIC_BYTES)])
            .trim()
            .to_string();
    match status {
        Some(status) if status.success() => String::new(),
        Some(status) => {
            if detail.is_empty() {
                format!("7-Zip 命令失败: {status}")
            } else {
                format!("7-Zip 命令失败: {status}: {detail}")
            }
        }
        None => "7-Zip 命令未返回退出状态".to_string(),
    }
}

fn run_7z_listing(
    runtime: &archive_runtime::VerifiedRuntime,
    archive_path: &Path,
) -> Result<Vec<u8>, String> {
    let args = vec![
        "l".to_string(),
        "-slt".to_string(),
        "-ba".to_string(),
        "-sccUTF-8".to_string(),
        "-p-".to_string(),
        "--".to_string(),
        archive_path.to_string_lossy().to_string(),
    ];
    let mut command = Command::new(runtime.executable());
    command
        .args(&args)
        .current_dir(runtime.root())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000);
    let mut child = command
        .spawn()
        .map_err(|error| format!("启动 7-Zip 目录检查失败: {error}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "7-Zip 目录检查没有标准输出".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "7-Zip 目录检查没有错误输出".to_string())?;
    let (stdout_tx, stdout_rx) = mpsc::channel();
    let (stderr_tx, stderr_rx) = mpsc::channel();
    let stdout_thread = thread::spawn({
        let tx = stdout_tx;
        move || {
            let result = read_bounded(stdout, MAX_NOTICE_ARCHIVE_LISTING_BYTES);
            let _ = tx.send(result);
        }
    });
    let stderr_thread = thread::spawn(move || {
        let result = read_bounded(stderr, MAX_NOTICE_ARCHIVE_DIAGNOSTIC_BYTES);
        let _ = stderr_tx.send(result);
    });

    let deadline = Instant::now() + NOTICE_ARCHIVE_LIST_TIMEOUT;
    let mut reader_error = None;
    let mut listing = None;
    let mut stderr_bytes = None;
    let status = loop {
        if let Ok(result) = stdout_rx.try_recv() {
            match result {
                Ok(bytes) => listing = Some(bytes),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                    let _ = child.kill();
                }
            }
        }
        if let Ok(result) = stderr_rx.try_recv() {
            match result {
                Ok(bytes) => stderr_bytes = Some(bytes),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                    let _ = child.kill();
                }
            }
        }
        if let Some(value) = child
            .try_wait()
            .map_err(|error| format!("等待 7-Zip 目录检查失败: {error}"))?
        {
            break Some(value);
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("7-Zip 目录检查超时".to_string());
        }
        thread::sleep(Duration::from_millis(20));
    };
    let _ = stdout_thread.join();
    let _ = stderr_thread.join();
    if listing.is_none() {
        if let Ok(result) = stdout_rx.recv_timeout(Duration::from_secs(5)) {
            match result {
                Ok(bytes) => listing = Some(bytes),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                }
            }
        }
    }
    if stderr_bytes.is_none() {
        if let Ok(result) = stderr_rx.recv_timeout(Duration::from_secs(5)) {
            match result {
                Ok(bytes) => stderr_bytes = Some(bytes),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                }
            }
        }
    }
    if let Some(error) = reader_error {
        return Err(error);
    }
    let status_error = archive_command_error(status, stderr_bytes.as_deref().unwrap_or_default());
    if !status_error.is_empty() {
        return Err(status_error);
    }
    listing.ok_or_else(|| "7-Zip 目录检查没有输出".to_string())
}

fn parse_7z_listing(listing: &[u8]) -> Result<Vec<(String, u64, bool, bool)>, String> {
    let text = String::from_utf8(listing.to_vec())
        .map_err(|error| format!("7-Zip 目录输出不是 UTF-8: {error}"))?;
    let mut entries = Vec::new();
    let normalized = text.replace("\r\n", "\n");
    for block in normalized.split("\n\n") {
        let mut path = None::<String>;
        let mut size = 0_u64;
        let mut is_directory = false;
        let mut encrypted = false;
        for line in block.lines() {
            let Some((key, value)) = line.split_once(" = ") else {
                continue;
            };
            match key {
                "Path" => path = Some(value.to_string()),
                "Size" => {
                    let value = value.trim();
                    size = value
                        .parse::<u64>()
                        .map_err(|error| format!("7-Zip 成员大小无效 {value:?}: {error}"))?;
                }
                "Attributes" => {
                    is_directory = value.contains('D');
                    let attributes = value.trim_start();
                    if value.contains('L') || attributes.starts_with('l') {
                        return Err("7-Zip 包含链接成员，已拒绝".to_string());
                    }
                }
                "Encrypted" => {
                    let value = value.trim();
                    encrypted = !value.is_empty() && value != "-";
                }
                "Symbolic Link" | "Hard Link" | "Copy Link"
                    if !value.trim().is_empty() && value.trim() != "-" =>
                {
                    return Err("7-Zip 包含链接成员，已拒绝".to_string());
                }
                "Alternate Stream" if !value.trim().is_empty() && value.trim() != "-" => {
                    return Err("7-Zip 包含备用数据流成员，已拒绝".to_string());
                }
                "Split Before" | "Split After"
                    if !value.trim().is_empty() && value.trim() != "-" =>
                {
                    return Err("7-Zip 多卷分片成员尚未完整，已拒绝".to_string());
                }
                _ => {}
            }
        }
        if let Some(member_name) = path {
            entries.push((member_name, size, is_directory, encrypted));
        }
    }
    Ok(entries)
}

fn stream_7z_member_to_file(
    runtime: &archive_runtime::VerifiedRuntime,
    archive_path: &Path,
    member_name: &str,
    temporary: &Path,
    expected_size: u64,
) -> Result<(), String> {
    let args = vec![
        "e".to_string(),
        "-so".to_string(),
        "-y".to_string(),
        "-bd".to_string(),
        "-bb0".to_string(),
        "-sccUTF-8".to_string(),
        "-spd".to_string(),
        "-p-".to_string(),
        "--".to_string(),
        archive_path.to_string_lossy().to_string(),
        member_name.to_string(),
    ];
    let mut command = Command::new(runtime.executable());
    command
        .args(&args)
        .current_dir(runtime.root())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000);
    let mut child = command
        .spawn()
        .map_err(|error| format!("启动 7-Zip 解压失败: {error}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "7-Zip 解压没有标准输出".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "7-Zip 解压没有错误输出".to_string())?;
    let temporary_path = temporary.to_path_buf();
    let (stream_tx, stream_rx) = mpsc::channel();
    let (stderr_tx, stderr_rx) = mpsc::channel();
    let stdout_thread = thread::spawn(move || {
        let result = (|| -> Result<(u64, String), String> {
            let mut stdout = stdout;
            let mut output = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary_path)
                .map_err(|error| format!("创建 7-Zip 临时文件失败: {error}"))?;
            let mut hasher = Sha256::new();
            let mut total = 0_u64;
            let mut buffer = [0_u8; 64 * 1024];
            loop {
                let remaining = expected_size.saturating_sub(total);
                let read_limit = ((remaining.saturating_add(1)) as usize).min(buffer.len());
                let count = stdout
                    .read(&mut buffer[..read_limit.max(1)])
                    .map_err(|error| format!("读取 7-Zip 成员失败: {error}"))?;
                if count == 0 {
                    break;
                }
                total = total
                    .checked_add(count as u64)
                    .ok_or_else(|| "7-Zip 成员大小溢出".to_string())?;
                if total > expected_size {
                    return Err(format!(
                        "7-Zip 成员超过目录声明大小: expected {expected_size}, got {total}"
                    ));
                }
                output
                    .write_all(&buffer[..count])
                    .map_err(|error| format!("写入 7-Zip 临时文件失败: {error}"))?;
                hasher.update(&buffer[..count]);
            }
            output
                .flush()
                .and_then(|_| output.sync_all())
                .map_err(|error| format!("同步 7-Zip 临时文件失败: {error}"))?;
            if total != expected_size {
                return Err(format!(
                    "7-Zip 成员大小不匹配: expected {expected_size}, got {total}"
                ));
            }
            Ok((total, format!("{:x}", hasher.finalize())))
        })();
        let _ = stream_tx.send(result);
    });
    let stderr_thread = thread::spawn(move || {
        let result = read_bounded(stderr, MAX_NOTICE_ARCHIVE_DIAGNOSTIC_BYTES);
        let _ = stderr_tx.send(result);
    });
    let deadline = Instant::now() + NOTICE_ARCHIVE_FILE_TIMEOUT;
    let mut reader_error = None;
    let mut stream_result = None;
    let mut stderr_bytes = None;
    let status = loop {
        if let Ok(result) = stream_rx.try_recv() {
            match result {
                Ok((size, hash)) => stream_result = Some((size, hash)),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                    let _ = child.kill();
                }
            }
        }
        if let Ok(result) = stderr_rx.try_recv() {
            if let Err(error) = result {
                let _ = reader_error.get_or_insert(error);
                let _ = child.kill();
            } else if let Ok(bytes) = result {
                stderr_bytes = Some(bytes);
            }
        }
        if let Some(value) = child
            .try_wait()
            .map_err(|error| format!("等待 7-Zip 解压失败: {error}"))?
        {
            break Some(value);
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_thread.join();
            let _ = stderr_thread.join();
            let _ = fs::remove_file(temporary);
            return Err("7-Zip 解压超时".to_string());
        }
        thread::sleep(Duration::from_millis(20));
    };
    let _ = stdout_thread.join();
    let _ = stderr_thread.join();
    if stream_result.is_none() {
        if let Ok(result) = stream_rx.recv_timeout(Duration::from_secs(5)) {
            match result {
                Ok(value) => stream_result = Some(value),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                }
            }
        }
    }
    if stderr_bytes.is_none() {
        if let Ok(result) = stderr_rx.recv_timeout(Duration::from_secs(5)) {
            match result {
                Ok(value) => stderr_bytes = Some(value),
                Err(error) => {
                    let _ = reader_error.get_or_insert(error);
                }
            }
        }
    }
    if let Some(error) = reader_error {
        let _ = fs::remove_file(temporary);
        return Err(error);
    }
    let status_error = archive_command_error(status, stderr_bytes.as_deref().unwrap_or_default());
    if !status_error.is_empty() {
        let _ = fs::remove_file(temporary);
        return Err(status_error);
    }
    if stream_result.is_none() {
        let _ = fs::remove_file(temporary);
        return Err("7-Zip 解压没有输出".to_string());
    }
    Ok(())
}

fn extract_notice_external_archive(
    archive_path: &Path,
    root: &Path,
    previous: Option<&NoticeArchiveExtraction>,
) -> Result<Vec<ExtractedArchiveOutput>, String> {
    let archive_metadata =
        fs::symlink_metadata(archive_path).map_err(|error| format!("无法读取压缩包: {error}"))?;
    if archive_metadata.file_type().is_symlink() || !archive_metadata.is_file() {
        return Err("拒绝解压符号链接或非普通压缩包".to_string());
    }
    if archive_metadata.len() > MAX_NOTICE_ARCHIVE_BYTES {
        return Err(format!(
            "压缩包超过大小限制: {} bytes",
            MAX_NOTICE_ARCHIVE_BYTES
        ));
    }
    let canonical_archive =
        fs::canonicalize(archive_path).map_err(|error| format!("无法解析压缩包路径: {error}"))?;
    if !canonical_archive.starts_with(root) {
        return Err("压缩包必须位于目标目录内".to_string());
    }
    let runtime = archive_runtime::discover_verified_runtime()?;
    let listing = run_7z_listing(&runtime, &canonical_archive)?;
    let total_deadline = Instant::now() + NOTICE_ARCHIVE_TOTAL_TIMEOUT;
    let listed = parse_7z_listing(&listing)?;
    if listed.len() > MAX_NOTICE_ARCHIVE_ENTRIES {
        return Err(format!(
            "压缩包文件数量超过限制: {}",
            MAX_NOTICE_ARCHIVE_ENTRIES
        ));
    }
    let mut expanded = 0_u64;
    let mut reserved = HashSet::new();
    let mut seen_members = HashSet::new();
    let mut plan = Vec::with_capacity(listed.len());
    for (index, (name, expected_size, is_directory, encrypted)) in listed.into_iter().enumerate() {
        if encrypted {
            return Err(format!("压缩包成员已加密，无法安全处理: {name}"));
        }
        let relative = archive_relative_path(&name)?;
        if !seen_members.insert(archive_target_key(&relative)) {
            return Err(format!("压缩包包含重复成员路径: {name}"));
        }
        let raw_target = root.join(relative);
        if !raw_target.starts_with(root) {
            return Err(format!("压缩包包含不安全路径: {name}"));
        }
        if !is_directory {
            if expected_size > MAX_NOTICE_ARCHIVE_FILE_BYTES {
                return Err(format!("压缩包成员超过大小限制: {name}"));
            }
            expanded = expanded
                .checked_add(expected_size)
                .ok_or_else(|| "压缩包解压大小溢出".to_string())?;
            if expanded > MAX_NOTICE_ARCHIVE_EXPANDED_BYTES {
                return Err(format!(
                    "压缩包解压总大小超过限制: {} bytes",
                    MAX_NOTICE_ARCHIVE_EXPANDED_BYTES
                ));
            }
        }
        let previous_output = previous.and_then(|record| {
            record.outputs.iter().find(|output| {
                output.member_index == index
                    && (output.member_name.is_empty() || output.member_name == name)
            })
        });
        let (target, already_valid) = if is_directory {
            (raw_target, false)
        } else if let Some(output) = previous_output {
            let recorded_relative = archive_relative_path(&output.path)?;
            let recorded_target = root.join(recorded_relative);
            if archive_output_is_valid(root, output) {
                reserved.insert(archive_target_key(&recorded_target));
                (recorded_target, true)
            } else if !recorded_target.exists()
                && !reserved.contains(&archive_target_key(&recorded_target))
            {
                reserved.insert(archive_target_key(&recorded_target));
                (recorded_target, false)
            } else {
                (unique_archive_target(&raw_target, &mut reserved), false)
            }
        } else {
            (unique_archive_target(&raw_target, &mut reserved), false)
        };
        if let Some(parent) = target.parent() {
            let relative_parent = parent
                .strip_prefix(root)
                .map_err(|_| format!("压缩包包含不安全路径: {name}"))?;
            let mut current = root.to_path_buf();
            for component in relative_parent.components() {
                let Component::Normal(value) = component else {
                    return Err(format!("压缩包包含不安全路径: {name}"));
                };
                current.push(value);
                if fs::symlink_metadata(&current)
                    .map(|metadata| metadata.file_type().is_symlink())
                    .unwrap_or(false)
                {
                    return Err(format!("解压目标包含符号链接: {}", current.display()));
                }
            }
        }
        plan.push(SevenZipEntry {
            index,
            member_name: name,
            target,
            is_directory,
            already_valid,
            expected_size,
        });
    }

    let mut outputs = Vec::new();
    for item in plan {
        if Instant::now() >= total_deadline {
            return Err("压缩包解压超过 10 分钟总时限".to_string());
        }
        if item.is_directory {
            ensure_safe_directory_chain(root, &item.target)?;
            continue;
        }
        if item.already_valid {
            outputs.push(ExtractedArchiveOutput {
                member_index: item.index,
                member_name: item.member_name,
                path: item.target,
            });
            continue;
        }
        let parent = item
            .target
            .parent()
            .ok_or_else(|| "压缩包成员没有父目录".to_string())?;
        ensure_safe_directory_chain(root, parent)?;
        let temporary = parent.join(format!(
            ".{}.koi-extract-{}.tmp",
            item.target
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("file"),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        stream_7z_member_to_file(
            &runtime,
            &canonical_archive,
            &item.member_name,
            &temporary,
            item.expected_size,
        )?;
        if item.target.exists() {
            let _ = fs::remove_file(&temporary);
            return Err(format!(
                "解压目标在写入期间被占用: {}",
                item.target.display()
            ));
        }
        fs::rename(&temporary, &item.target).map_err(|error| {
            let _ = fs::remove_file(&temporary);
            format!("提交解压文件失败: {error}")
        })?;
        outputs.push(ExtractedArchiveOutput {
            member_index: item.index,
            member_name: item.member_name,
            path: item.target,
        });
    }
    Ok(outputs)
}

fn archive_output_is_valid(root: &Path, output: &NoticeArchiveOutput) -> bool {
    let Ok(relative) = archive_relative_path(&output.path) else {
        return false;
    };
    let path = root.join(relative);
    let canonical = match fs::canonicalize(&path) {
        Ok(path) if path.starts_with(root) => path,
        _ => return false,
    };
    fs::symlink_metadata(&canonical)
        .ok()
        .filter(|metadata| !metadata.file_type().is_symlink() && metadata.is_file())
        .filter(|metadata| metadata.len() == output.size)
        .is_some()
        && file_sha256(&canonical).ok().as_deref() == Some(output.sha256.as_str())
}

fn extract_notice_zip(
    archive_path: &Path,
    root: &Path,
    previous: Option<&NoticeArchiveExtraction>,
) -> Result<Vec<ExtractedArchiveOutput>, String> {
    let archive_metadata =
        fs::symlink_metadata(archive_path).map_err(|error| format!("无法读取压缩包: {error}"))?;
    if archive_metadata.file_type().is_symlink() || !archive_metadata.is_file() {
        return Err("拒绝解压符号链接或非普通压缩包".to_string());
    }
    if archive_metadata.len() > MAX_NOTICE_ARCHIVE_BYTES {
        return Err(format!(
            "压缩包超过大小限制: {} bytes",
            MAX_NOTICE_ARCHIVE_BYTES
        ));
    }
    let canonical_archive =
        fs::canonicalize(archive_path).map_err(|error| format!("无法解析压缩包路径: {error}"))?;
    if !canonical_archive.starts_with(root) {
        return Err("压缩包必须位于目标目录内".to_string());
    }

    let source =
        File::open(&canonical_archive).map_err(|error| format!("无法打开 ZIP: {error}"))?;
    let mut archive = ZipArchive::new(source).map_err(|error| format!("ZIP 格式无效: {error}"))?;
    if archive.len() > MAX_NOTICE_ARCHIVE_ENTRIES {
        return Err(format!(
            "ZIP 文件数量超过限制: {}",
            MAX_NOTICE_ARCHIVE_ENTRIES
        ));
    }

    // Validate every member before creating anything. A traversal entry late
    // in the archive therefore cannot leave a partially extracted tree.
    let mut expanded = 0u64;
    let mut reserved = HashSet::new();
    let mut plan = Vec::with_capacity(archive.len());
    for index in 0..archive.len() {
        let entry = archive
            .by_index(index)
            .map_err(|error| format!("读取 ZIP 成员失败: {error}"))?;
        let name = entry.name().to_string();
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err(format!("ZIP 包含符号链接，已拒绝: {name}"));
        }
        let relative = archive_relative_path(&name)?;
        let raw_target = root.join(relative);
        if !raw_target.starts_with(root) {
            return Err(format!("压缩包包含不安全路径: {name}"));
        }
        let is_directory = entry.is_dir();
        let expected_size = entry.size();
        if !is_directory {
            if expected_size > MAX_NOTICE_ARCHIVE_FILE_BYTES {
                return Err(format!("ZIP 成员超过大小限制: {name}"));
            }
            expanded = expanded
                .checked_add(expected_size)
                .ok_or_else(|| "ZIP 解压大小溢出".to_string())?;
            if expanded > MAX_NOTICE_ARCHIVE_EXPANDED_BYTES {
                return Err(format!(
                    "ZIP 解压总大小超过限制: {} bytes",
                    MAX_NOTICE_ARCHIVE_EXPANDED_BYTES
                ));
            }
        }
        let previous_output = previous.and_then(|record| {
            record.outputs.iter().find(|output| {
                output.member_index == index
                    && (output.member_name.is_empty() || output.member_name == name)
            })
        });
        let (target, already_valid) = if is_directory {
            (raw_target, false)
        } else if let Some(output) = previous_output {
            let recorded_relative = archive_relative_path(&output.path)?;
            let recorded_target = root.join(recorded_relative);
            if archive_output_is_valid(root, output) {
                reserved.insert(archive_target_key(&recorded_target));
                (recorded_target, true)
            } else if !recorded_target.exists()
                && !reserved.contains(&archive_target_key(&recorded_target))
            {
                reserved.insert(archive_target_key(&recorded_target));
                (recorded_target, false)
            } else {
                (unique_archive_target(&raw_target, &mut reserved), false)
            }
        } else {
            (unique_archive_target(&raw_target, &mut reserved), false)
        };
        if let Some(parent) = target.parent() {
            let relative_parent = parent
                .strip_prefix(root)
                .map_err(|_| format!("压缩包包含不安全路径: {name}"))?;
            let mut current = root.to_path_buf();
            for component in relative_parent.components() {
                let Component::Normal(value) = component else {
                    return Err(format!("压缩包包含不安全路径: {name}"));
                };
                current.push(value);
                if fs::symlink_metadata(&current)
                    .map(|metadata| metadata.file_type().is_symlink())
                    .unwrap_or(false)
                {
                    return Err(format!("解压目标包含符号链接: {}", current.display()));
                }
            }
        }
        plan.push(ZipExtractionEntry {
            index,
            member_name: name,
            target,
            is_directory,
            already_valid,
            expected_size,
        });
    }

    let mut outputs = Vec::new();
    for item in plan {
        if item.is_directory {
            ensure_safe_directory_chain(root, &item.target)?;
            continue;
        }
        if item.already_valid {
            outputs.push(ExtractedArchiveOutput {
                member_index: item.index,
                member_name: item.member_name,
                path: item.target,
            });
            continue;
        }
        let parent = item
            .target
            .parent()
            .ok_or_else(|| "ZIP 成员没有父目录".to_string())?;
        ensure_safe_directory_chain(root, parent)?;
        let mut entry = archive
            .by_index(item.index)
            .map_err(|error| format!("读取 ZIP 成员失败: {error}"))?;
        let temporary = parent.join(format!(
            ".{}.koi-extract-{}.tmp",
            item.target
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("file"),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let write_result = (|| {
            let mut output = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)
                .map_err(|error| format!("创建解压临时文件失败: {error}"))?;
            let copied = std::io::copy(
                &mut entry.by_ref().take(item.expected_size.saturating_add(1)),
                &mut output,
            )
            .map_err(|error| format!("解压 ZIP 成员失败: {error}"))?;
            if copied != item.expected_size {
                return Err(format!(
                    "ZIP 成员大小不匹配: {} (expected {}, got {copied})",
                    entry.name(),
                    item.expected_size
                ));
            }
            output
                .flush()
                .and_then(|_| output.sync_all())
                .map_err(|error| format!("同步解压文件失败: {error}"))?;
            if item.target.exists() {
                return Err(format!(
                    "解压目标在写入期间被占用: {}",
                    item.target.display()
                ));
            }
            fs::rename(&temporary, &item.target)
                .map_err(|error| format!("提交解压文件失败: {error}"))?;
            Ok::<(), String>(())
        })();
        if write_result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        write_result?;
        outputs.push(ExtractedArchiveOutput {
            member_index: item.index,
            member_name: item.member_name,
            path: item.target,
        });
    }
    Ok(outputs)
}

fn notice_archives(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut archives: Vec<PathBuf> = walk_files(root)?
        .into_iter()
        .filter(|path| notice_archive_kind(path).is_some())
        .collect();
    archives.sort_by(|left, right| {
        let left_depth = left
            .strip_prefix(root)
            .map(|path| path.components().count())
            .unwrap_or(usize::MAX);
        let right_depth = right
            .strip_prefix(root)
            .map(|path| path.components().count())
            .unwrap_or(usize::MAX);
        left_depth.cmp(&right_depth).then_with(|| {
            left.to_string_lossy()
                .to_ascii_lowercase()
                .cmp(&right.to_string_lossy().to_ascii_lowercase())
        })
    });
    Ok(archives)
}

fn archive_relative_string(root: &Path, path: &Path) -> Result<String, String> {
    path.strip_prefix(root)
        .map(|relative| relative.to_string_lossy().replace('\\', "/"))
        .map_err(|_| format!("压缩包产物越过目标目录: {}", path.display()))
}

fn archive_record_is_valid(root: &Path, record: &NoticeArchiveExtraction) -> bool {
    !record.outputs.is_empty()
        && record
            .outputs
            .iter()
            .all(|output| archive_output_is_valid(root, output))
}

fn archive_record(
    root: &Path,
    archive: &Path,
    archive_sha256: String,
    outputs: &[ExtractedArchiveOutput],
) -> Result<NoticeArchiveExtraction, String> {
    let mut recorded_outputs = Vec::with_capacity(outputs.len());
    for output in outputs {
        let metadata = fs::symlink_metadata(&output.path)
            .map_err(|error| format!("无法验证解压产物 {}: {error}", output.path.display()))?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(format!("解压产物不是普通文件: {}", output.path.display()));
        }
        recorded_outputs.push(NoticeArchiveOutput {
            member_index: output.member_index,
            member_name: output.member_name.clone(),
            path: archive_relative_string(root, &output.path)?,
            size: metadata.len(),
            sha256: file_sha256(&output.path)?,
        });
    }
    Ok(NoticeArchiveExtraction {
        archive_path: archive_relative_string(root, archive)?,
        archive_sha256,
        outputs: recorded_outputs,
    })
}

fn extract_notice_archives(
    root: &Path,
    logs: &mut Vec<String>,
    records: &mut Vec<NoticeArchiveExtraction>,
) -> Result<Vec<Value>, String> {
    let mut processed = HashSet::new();
    let mut failures = Vec::new();
    loop {
        let archives: Vec<PathBuf> = notice_archives(root)?
            .into_iter()
            .filter(|path| {
                fs::canonicalize(path)
                    .ok()
                    .map(|path| !processed.contains(&archive_target_key(&path)))
                    .unwrap_or(true)
            })
            .collect();
        if archives.is_empty() {
            break;
        }
        logs.push(format!("预解压压缩包: 发现 {} 个", archives.len()));
        for archive_path in archives {
            let canonical = match fs::canonicalize(&archive_path) {
                Ok(path) => path,
                Err(error) => {
                    failures.push(json!({"file": archive_path, "reason": error.to_string()}));
                    continue;
                }
            };
            processed.insert(archive_target_key(&canonical));
            logs.push(format!("预解压: {}", canonical.display()));
            let relative_archive = archive_relative_string(root, &canonical)?;
            let archive_sha256 = match file_sha256(&canonical) {
                Ok(value) => value,
                Err(error) => {
                    logs.push(format!(
                        "读取压缩包指纹失败 {}: {error}",
                        canonical.display()
                    ));
                    failures.push(json!({"file": canonical, "reason": error}));
                    continue;
                }
            };
            let previous_record = records
                .iter()
                .find(|record| {
                    record.archive_path == relative_archive
                        && record.archive_sha256 == archive_sha256
                })
                .cloned();
            if previous_record
                .as_ref()
                .is_some_and(|record| archive_record_is_valid(root, record))
            {
                logs.push(format!(
                    "压缩包及已验证产物未变化，跳过重复解压: {}",
                    canonical.display()
                ));
                continue;
            }
            match notice_archive_kind(&canonical) {
                Some("zip") => match extract_notice_zip(&canonical, root, previous_record.as_ref())
                {
                    Ok(outputs) => {
                        let record = archive_record(root, &canonical, archive_sha256, &outputs)?;
                        records.retain(|existing| existing.archive_path != relative_archive);
                        records.push(record);
                        logs.push(format!(
                            "解压完成，写入 {} 个文件，已保留原压缩包: {}",
                            outputs.len(),
                            canonical
                                .file_name()
                                .and_then(|value| value.to_str())
                                .unwrap_or_default()
                        ));
                    }
                    Err(error) => {
                        logs.push(format!("解压失败 {}: {error}", canonical.display()));
                        failures.push(json!({"file": canonical, "reason": error}));
                    }
                },
                Some("7z") | Some("rar") => {
                    match extract_notice_external_archive(
                        &canonical,
                        root,
                        previous_record.as_ref(),
                    ) {
                        Ok(outputs) => {
                            let record =
                                archive_record(root, &canonical, archive_sha256, &outputs)?;
                            records.retain(|existing| existing.archive_path != relative_archive);
                            records.push(record);
                            logs.push(format!(
                                "7-Zip 解压完成，写入 {} 个文件，已保留原压缩包: {}",
                                outputs.len(),
                                canonical
                                    .file_name()
                                    .and_then(|value| value.to_str())
                                    .unwrap_or_default()
                            ));
                        }
                        Err(error) => {
                            logs.push(format!("7-Zip 解压失败 {}: {error}", canonical.display()));
                            failures.push(json!({"file": canonical, "reason": error}));
                        }
                    }
                }
                _ => {}
            }
        }
    }
    Ok(failures)
}

fn notice_process_result(payload: &Value) -> Result<Value, String> {
    let requested = required_string(payload, "target_path")?;
    let (root, _requested_archive) = canonical_notice_target(Path::new(&requested))?;
    let mut logs = Vec::new();
    let mut pipeline_company_groups = BTreeMap::<String, String>::new();
    let mut previous = load_notice_state(&root)?;
    let mut archive_extractions = previous
        .as_ref()
        .map(|state| state.archive_extractions.clone())
        .unwrap_or_default();
    let archive_failures = extract_notice_archives(&root, &mut logs, &mut archive_extractions)?;
    if !archive_extractions.is_empty() {
        let mut checkpoint = previous.take().unwrap_or_else(|| new_notice_state(&root));
        checkpoint.target_path = root.to_string_lossy().to_string();
        checkpoint.archive_extractions = archive_extractions.clone();
        checkpoint.updated_at = json!(now_seconds());
        save_notice_state(&root, &checkpoint)?;
        previous = Some(checkpoint);
    }
    if payload
        .get("auto_group")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        logs.push("执行自动分类".to_string());
        let grouping = run_notice_grouping(&root, payload)?;
        if let Some(group_logs) = grouping.get("log").and_then(Value::as_array) {
            logs.extend(
                group_logs
                    .iter()
                    .filter_map(Value::as_str)
                    .map(ToOwned::to_owned),
            );
        }
        let mut company_groups = BTreeMap::new();
        if let Some(items) = grouping.get("company_group_list").and_then(Value::as_array) {
            for item in items {
                let Some(values) = item.as_array() else {
                    continue;
                };
                let Some(company) = values.first().and_then(Value::as_str) else {
                    continue;
                };
                let Some(group) = values.get(1).and_then(Value::as_str) else {
                    continue;
                };
                let normalized = normalize_notice_company(company);
                if !normalized.is_empty() {
                    company_groups.insert(normalized.clone(), group.to_string());
                    pipeline_company_groups.insert(normalized, group.to_string());
                }
            }
        }
        let (updated, skipped, errors, copy_logs) =
            fill_rewritten_notice_copy_to(&root, &company_groups)?;
        logs.extend(copy_logs);
        logs.push(format!(
            "自动分类完成：移动 {} 个，补写抄送 {updated} 个，无分组跳过 {skipped} 个，抄送错误 {errors} 个",
            grouping.get("moved").and_then(Value::as_u64).unwrap_or(0)
        ));
    }
    if payload
        .get("_rust_notice_pipeline")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return run_notice_pipeline_result(
            payload,
            &root,
            logs,
            archive_failures,
            archive_extractions,
        );
    }
    let mut state = previous.take().unwrap_or_else(|| new_notice_state(&root));
    let state_was_resumable = state.completed
        || state.stages.rewrite
        || state.stages.authorization
        || state.stages.rectification
        || state.stages.disposal
        || state.stages.pdf
        || !state.artifacts.is_empty()
        || !state.generated_files.is_empty()
        || !state.pdf_outputs.is_empty()
        || state.compatibility_fields.contains_key("active_stage")
        || state.compatibility_fields.contains_key("input_signature");
    let pipeline_enabled = payload
        .get("_rust_notice_pipeline")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut pipeline_ran = false;
    let mut pipeline_report_count = 0usize;
    if pipeline_enabled {
        let sources = normalize_notice_source_names(&root, &mut logs)?
            .into_iter()
            .filter(|path| {
                path.extension()
                    .and_then(|value| value.to_str())
                    .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
            })
            .collect::<Vec<_>>();
        pipeline_report_count = sources.len();
        if let Some(source) = sources.first() {
            pipeline_ran = true;
            let company = normalize_notice_company(
                source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default(),
            );
            let company = if company.is_empty() {
                source
                    .parent()
                    .and_then(Path::file_name)
                    .and_then(|value| value.to_str())
                    .unwrap_or("未知企业")
                    .to_string()
            } else {
                company
            };
            logs.push("步骤1/5: Rust OOXML 通报改写".to_string());
            for source in &sources {
                let output = numeric_notice_output(source)?;
                if !docx_path_has_rewrite_marker(&output) {
                    let copy_to = group_for_docx(source, &root, &pipeline_company_groups);
                    let artifact =
                        run_notice_rewrite_stage(&root, &mut state, source, copy_to.as_deref())?;
                    logs.push(format!("改写产物已验证: {}", artifact.display()));
                }
            }
            let rewritten = walk_files(&root)?
                .into_iter()
                .filter(|path| docx_path_has_rewrite_marker(path))
                .collect::<Vec<_>>();
            let rewritten_first = rewritten.first().cloned();
            let rewritten = rewritten_first
                .as_ref()
                .ok_or_else(|| "通报改写阶段没有有效产物".to_string())?;
            let report_title = rewritten
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or_default()
                .to_string();
            if !state.stages.authorization {
                logs.push("步骤2/5: 生成授权委托书".to_string());
                let template = template_by_keyword(payload, "授权委托书")
                    .ok_or_else(|| "未找到授权委托书 DOCX 模板".to_string())?;
                let artifact =
                    run_notice_authorization_stage(&root, &mut state, &template, &report_title)?;
                logs.push(format!("授权产物已验证: {}", artifact.display()));
            }
            if !state.stages.rectification {
                logs.push("步骤3/5: 生成责令整改通知书".to_string());
                let template = template_by_keyword(payload, "责令整改")
                    .ok_or_else(|| "未找到责令整改 DOCX 模板".to_string())?;
                let artifact = run_notice_rectification_stage(
                    &root,
                    &mut state,
                    &template,
                    &company,
                    "网络安全漏洞",
                )?;
                logs.push(format!("整改产物已验证: {}", artifact.display()));
            }
            if !state.stages.disposal {
                logs.push("步骤4/5: 生成处置文件".to_string());
                if let Some(template) = template_by_keyword(payload, "处置") {
                    let artifact = run_notice_disposal_stage(&root, &mut state, &template)?;
                    logs.push(format!("处置产物已验证: {}", artifact.display()));
                } else {
                    begin_notice_pipeline_stage(
                        &root,
                        &mut state,
                        NoticePipelineStage::Disposal,
                        None,
                    )?;
                    finish_notice_pipeline_stage(
                        &root,
                        &mut state,
                        NoticePipelineStage::Disposal,
                        None,
                    )?;
                    logs.push("未找到处置模板，按 Python 兼容规则跳过".to_string());
                }
            }
            if !state.stages.pdf {
                logs.push("步骤5/5: Rust Word COM 转 PDF".to_string());
                let generated_words = state
                    .generated_files
                    .iter()
                    .map(PathBuf::from)
                    .filter(|path| {
                        path.extension()
                            .and_then(|value| value.to_str())
                            .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
                            && path
                                .file_name()
                                .and_then(|value| value.to_str())
                                .is_some_and(|name| {
                                    name.contains("授权委托书") || name.contains("责令整改")
                                })
                    })
                    .collect::<Vec<_>>();
                let outputs = run_notice_pdf_stage(&root, &mut state, &generated_words)?;
                for output in outputs {
                    logs.push(format!("PDF 产物已验证: {}", output.display()));
                }
                cleanup_notice_word_artifacts_after_pdf(&mut state, &mut logs)?;
            }
            if state.stages.all() {
                let mut deleted = Vec::new();
                for source in &sources {
                    if !source
                        .file_name()
                        .and_then(|value| value.to_str())
                        .is_some_and(|name| {
                            name.starts_with(|character: char| character.is_ascii_digit())
                        })
                    {
                        continue;
                    }
                    let metadata = fs::symlink_metadata(source)
                        .map_err(|error| format!("读取待清理通报源失败: {error}"))?;
                    if metadata.file_type().is_symlink() || !metadata.is_file() {
                        return Err("拒绝清理非普通通报源".to_string());
                    }
                    fs::remove_file(source)
                        .map_err(|error| format!("PDF 全部验证后删除原始通报失败: {error}"))?;
                    let path = source.to_string_lossy().to_string();
                    if !state.deleted_files.contains(&path) {
                        state.deleted_files.push(path.clone());
                    }
                    deleted.push(path);
                }
                if !deleted.is_empty() {
                    logs.push(format!(
                        "五阶段完成，已清理 {} 个数字前缀原始通报",
                        deleted.len()
                    ));
                    state.updated_at = json!(now_seconds());
                    save_notice_state(&root, &state)?;
                }
            }
        }
    }
    // Pipeline cleanup may remove numeric-prefixed source notices.  Compute
    // the checkpoint digest after that mutation so a completed run remains
    // resumable instead of looking like a stale source-change checkpoint on
    // the next process start.
    let digest = source_digest(&root)?;
    let files = walk_files(&root)?;
    // Count only report sources (or one resumable company directory) just as
    // Python's `_count_notification_docs` does.  Existing PDFs and unrelated
    // office documents are inputs to neither the five-stage workflow nor its
    // progress counters.
    let source_candidates = files
        .iter()
        .filter(|path| notice_source_candidate(path))
        .cloned()
        .collect::<Vec<_>>();
    let mut valid_pdfs = Vec::new();
    let mut failures = archive_failures;
    let mut manual_files = Vec::new();
    let mut rewritten_notice_files = Vec::new();
    for file in files {
        match notice_file_kind(&file) {
            Some("pdf") if notice_pdf_artifact_candidate(&file) => match read_pdf(&file) {
                Ok(_) => valid_pdfs.push(file),
                Err(error) => failures.push(json!({"file": file, "reason": error})),
            },
            Some("word")
                if file
                    .extension()
                    .and_then(|value| value.to_str())
                    .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
                    && docx_path_has_rewrite_marker(&file) =>
            {
                // A provenance-marked DOCX is the output of stage 1, not a
                // new source that needs manual conversion.  Keep it in the
                // artifact list so a restart can resume at stage 2.
                rewritten_notice_files.push(file);
            }
            Some("word") if notice_word_candidate(&file) => {
                let reason = "Rust OOXML/Word 转换器尚未配置；原文件已保留";
                manual_files.push(json!({"file": file, "reason": reason}));
                failures.push(json!({"file": file, "reason": reason}));
            }
            _ => {}
        }
    }
    let mut stages = NoticeStages {
        rewrite: !rewritten_notice_files.is_empty(),
        ..NoticeStages::default()
    };
    let has_artifact = |needle: &str| {
        rewritten_notice_files
            .iter()
            .chain(valid_pdfs.iter())
            .any(|path| {
                path.file_name()
                    .and_then(|value| value.to_str())
                    .is_some_and(|name| name.contains(needle))
            })
    };
    stages.authorization = has_artifact("授权委托书");
    stages.rectification = has_artifact("责令整改");
    stages.disposal = has_artifact("处置");
    if manual_files.is_empty() && rewritten_notice_files.is_empty() && valid_pdfs.is_empty() {
        // No source or generated artifact is not a completed five-stage
        // workflow.  Keep all flags false while preserving the Python
        // command's successful no-op response below.
        stages = NoticeStages::default();
    }
    stages.pdf = !valid_pdfs.is_empty()
        && manual_files.is_empty()
        && failures.iter().all(|failure| {
            failure
                .get("reason")
                .and_then(Value::as_str)
                .map(|reason| !reason.contains("PDF"))
                .unwrap_or(true)
        });
    let pdf_artifacts: Vec<String> = valid_pdfs
        .iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect();
    let artifacts: Vec<String> = pdf_artifacts
        .iter()
        .cloned()
        .chain(
            rewritten_notice_files
                .iter()
                .map(|path| path.to_string_lossy().to_string()),
        )
        .collect();
    let python_checkpoint = state.source_sha256.is_empty()
        && [
            "company_name",
            "input_signature",
            "rewrite_items",
            "rewrite_required",
        ]
        .iter()
        .any(|key| state.compatibility_fields.contains_key(*key));
    let trusted_python_checkpoint =
        python_checkpoint && python_checkpoint_matches_sources(&root, &state);
    if python_checkpoint && !trusted_python_checkpoint {
        logs.push(
            "旧版 Python 断点的源文件指纹缺失或不匹配，已失效全部阶段并保留现有文件".to_string(),
        );
        for key in [
            "input_signature",
            "rewrite_items",
            "rewrite_required",
            "active_stage",
            "active_source",
            "stage_started_at",
        ] {
            state.compatibility_fields.remove(key);
        }
    }
    if !pipeline_enabled && !trusted_python_checkpoint && state.source_sha256 != digest {
        state.stages = NoticeStages::default();
        state.completed = false;
        state.generated_files.clear();
        state.pdf_outputs.clear();
        state.deleted_files.clear();
    }
    state.target_path = root.to_string_lossy().to_string();
    state.generated_files = rewritten_notice_files
        .iter()
        .map(|path| path.to_string_lossy().to_string())
        .chain(state.generated_files)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    state.artifacts = artifacts.clone();
    state.pdf_outputs = pdf_artifacts;
    state.archive_extractions = archive_extractions.clone();
    if !pipeline_enabled && !trusted_python_checkpoint {
        state.source_sha256 = digest;
        state.stages = stages;
        state.completed = state.stages.all() && failures.is_empty();
    } else if pipeline_enabled && pipeline_ran {
        state.source_sha256 = digest;
        state.completed = state.stages.all() && failures.is_empty();
    } else if pipeline_enabled {
        state.source_sha256 = digest;
        state.stages = stages;
        state.completed = state.stages.all() && failures.is_empty();
    }
    // Python counts one resumable unit per company directory, not one global
    // boolean.  Keep source directories out of that set because a directory
    // containing a new source is already represented by its source count.
    let source_dirs = source_candidates
        .iter()
        .filter_map(|path| {
            path.parent()
                .and_then(|parent| fs::canonicalize(parent).ok())
        })
        .collect::<BTreeSet<_>>();
    let mut resumable_dirs = rewritten_notice_files
        .iter()
        .filter_map(|path| {
            path.parent()
                .and_then(|parent| fs::canonicalize(parent).ok())
        })
        .collect::<BTreeSet<_>>();
    if state_was_resumable && source_candidates.is_empty() {
        resumable_dirs.insert(root.clone());
    }
    for source_dir in &source_dirs {
        resumable_dirs.remove(source_dir);
    }
    let resumable_count = resumable_dirs.len();
    let report_total = if pipeline_report_count > 0 {
        pipeline_report_count.max(source_candidates.len() + resumable_count)
    } else {
        source_candidates.len() + resumable_count
    };
    let processed_reports = report_total;
    state.updated_at = json!(now_seconds());
    // Python leaves no checkpoint behind for a genuine empty/PDF-only
    // no-op.  Avoid turning the next invocation into a synthetic resumable
    // company merely because Rust inspected the directory.
    let has_notice_work = report_total > 0 || !manual_files.is_empty() || !failures.is_empty();
    if has_notice_work || !archive_extractions.is_empty() {
        save_notice_state(&root, &state)?;
    }
    if valid_pdfs.is_empty() && manual_files.is_empty() {
        logs.push("未找到可验证的 PDF 或 Word 通报文件".to_string());
    } else {
        logs.push(format!("已验证 {} 个 PDF 产物", valid_pdfs.len()));
    }
    if !manual_files.is_empty() {
        logs.push("Word 阶段未执行，原始文件保留以等待 Rust 转换器".to_string());
    }
    // A directory with no notice source and no processing failure is a
    // compatible no-op (Python returns success for this case), but it must
    // not be persisted as a completed five-stage workflow.
    let no_op_success = report_total == 0
        && manual_files.is_empty()
        && rewritten_notice_files.is_empty()
        && failures.is_empty();
    let success = (state.completed && failures.is_empty()) || no_op_success;
    Ok(json!({
        "success": success,
        "message": if success {
            format!("处理完成：验证 {} 个 PDF 产物", valid_pdfs.len())
        } else {
            "处理未完成：存在待迁移或未验证阶段；原文件已保留".to_string()
        },
        "target_path": root,
        "total_reports": report_total,
        "processed": processed_reports,
        "generated_files": state.generated_files,
        "manual_files": manual_files,
        "failures": failures,
        "pdf_outputs": state.pdf_outputs,
        "logs": logs,
        "state_file": state_path(&root),
        "stages": state.stages,
        "source_sha256": state.source_sha256,
    }))
}

fn notice_process(payload: &Value) -> Result<Value, String> {
    notice_process_result(payload)
}

#[derive(Debug, Default)]
struct NoticePipelineBatchResult {
    processed: usize,
    generated_files: Vec<String>,
    manual_files: Vec<Value>,
    failures: Vec<Value>,
    pdf_outputs: Vec<String>,
    logs: Vec<String>,
}

fn notice_company_batches(
    root: &Path,
    logs: &mut Vec<String>,
) -> Result<Vec<(PathBuf, Vec<PathBuf>)>, String> {
    let sources = normalize_notice_source_names(root, logs)?
        .into_iter()
        .filter(|path| valid_docx_package(path))
        .collect::<Vec<_>>();
    let mut batches = BTreeMap::<String, (PathBuf, Vec<PathBuf>)>::new();
    for source in sources {
        let work_dir = source.parent().unwrap_or(root).to_path_buf();
        let key = work_dir
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        batches
            .entry(key)
            .or_insert_with(|| (work_dir, Vec::new()))
            .1
            .push(source);
    }
    let mut values = batches.into_values().collect::<Vec<_>>();
    for (_, sources) in &mut values {
        sources.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    }
    Ok(values)
}

fn source_signature_values(work_dir: &Path, sources: &[PathBuf]) -> Result<Vec<Value>, String> {
    let mut values = Vec::with_capacity(sources.len());
    for source in sources {
        let metadata = fs::symlink_metadata(source)
            .map_err(|error| format!("cannot inspect notice source: {error}"))?;
        values.push(json!({
            "name": source.file_name().and_then(|value| value.to_str()).unwrap_or_default(),
            "path": source.strip_prefix(work_dir).unwrap_or(source).to_string_lossy().replace('\\', "/"),
            "size": metadata.len(),
            "sha256": file_sha256(source)?,
        }));
    }
    Ok(values)
}

fn state_signature_matches(state: &NoticeState, signature: &[Value]) -> bool {
    state
        .compatibility_fields
        .get("input_signature")
        .and_then(Value::as_array)
        .is_some_and(|existing| existing == signature)
}

fn notice_company_name(work_dir: &Path, sources: &[PathBuf]) -> String {
    sources
        .iter()
        .filter_map(|source| {
            source
                .file_name()
                .and_then(|value| value.to_str())
                .map(normalize_notice_company)
                .filter(|value| !value.is_empty())
        })
        .next()
        .or_else(|| {
            work_dir
                .file_name()
                .and_then(|value| value.to_str())
                .map(normalize_notice_company)
                .filter(|value| !value.is_empty())
        })
        .unwrap_or_else(|| "未知企业".to_string())
}

fn notice_report_title(sources: &[PathBuf]) -> String {
    if sources.len() > 1 {
        let company = sources
            .first()
            .and_then(|path| path.file_name())
            .and_then(|value| value.to_str())
            .map(normalize_notice_company)
            .unwrap_or_default();
        return format!("{company}存在多个漏洞");
    }
    sources
        .first()
        .and_then(|path| numeric_notice_output(path).ok())
        .and_then(|path| {
            path.file_stem()
                .map(|value| value.to_string_lossy().to_string())
        })
        .unwrap_or_else(|| "网络安全预警通报".to_string())
}

fn notice_vulnerability_text(sources: &[PathBuf]) -> String {
    let mut values = BTreeSet::new();
    for source in sources {
        let name = source
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if let Some(start) = name.find("存在") {
            let mut value = name[start + "存在".len()..].trim().to_string();
            for suffix in ["的通报", "通报", "报告"] {
                if let Some(stripped) = value.strip_suffix(suffix) {
                    value = stripped.trim().to_string();
                    break;
                }
            }
            if !value.is_empty() {
                values.insert(value);
            }
        }
    }
    if values.is_empty() {
        "网络安全漏洞".to_string()
    } else {
        values.into_iter().collect::<Vec<_>>().join("、")
    }
}

fn configured_soe_companies(payload: &Value) -> BTreeSet<String> {
    let mut values = BTreeSet::new();
    for key in ["soe_companies", "state_owned_companies"] {
        if let Some(items) = payload.get(key).and_then(Value::as_array) {
            for item in items.iter().filter_map(Value::as_str) {
                let value = item.trim().trim_end_matches("{国企}").trim();
                if !value.is_empty() {
                    values.insert(value.to_string());
                }
            }
        }
    }
    for key in ["company_group_list", "company_groups", "groups"] {
        if let Some(items) = payload.get(key).and_then(Value::as_array) {
            for item in items {
                let company = item
                    .as_array()
                    .and_then(|values| values.first())
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if company.contains("{国企}") {
                    values.insert(company.replace("{国企}", "").trim().to_string());
                }
            }
        }
    }
    values
}

fn remove_completed_notice_sources(
    state: &mut NoticeState,
    sources: &[PathBuf],
    logs: &mut Vec<String>,
) -> Result<(), String> {
    for source in sources {
        if !source.exists() {
            continue;
        }
        let name = source
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if !name.starts_with(|character: char| character.is_ascii_digit()) {
            continue;
        }
        fs::remove_file(source)
            .map_err(|error| format!("企业五阶段完成后删除原始通报失败: {error}"))?;
        let path = source.to_string_lossy().to_string();
        if !state.deleted_files.contains(&path) {
            state.deleted_files.push(path);
        }
        logs.push(format!("企业流程已全部完成，删除原始通报: {name}"));
    }
    Ok(())
}

fn process_notice_company_batch(
    payload: &Value,
    work_dir: &Path,
    sources: &[PathBuf],
    company_groups: &BTreeMap<String, String>,
    soe_companies: &BTreeSet<String>,
) -> Result<NoticePipelineBatchResult, String> {
    let company = notice_company_name(work_dir, sources);
    let signature = source_signature_values(work_dir, sources)?;
    let mut state = load_notice_state(work_dir)?.unwrap_or_else(|| new_notice_state(work_dir));
    state.target_path = work_dir.to_string_lossy().to_string();
    state
        .compatibility_fields
        .insert("company_name".to_string(), json!(company));
    if !state_signature_matches(&state, &signature) {
        state.stages = NoticeStages::default();
        state.completed = false;
        state.artifacts.clear();
        state.generated_files.clear();
        state.pdf_outputs.clear();
        state.deleted_files.clear();
        state.compatibility_fields.insert(
            "input_signature".to_string(),
            Value::Array(signature.clone()),
        );
        state
            .compatibility_fields
            .insert("rewrite_items".to_string(), json!([]));
        save_notice_state(work_dir, &state)?;
    }

    let mut result = NoticePipelineBatchResult::default();
    result.logs.push("=".repeat(80));
    result.logs.push(format!(
        "处理企业: {company} (原始通报 {} 个)",
        sources.len()
    ));
    let copy_to = company_groups.get(&company).map(String::as_str);
    let config_path = payload
        .get("_notice_config_path")
        .and_then(Value::as_str)
        .map(PathBuf::from);
    result.logs.push("步骤1/5: Rust OOXML 通报改写".to_string());
    let mut rewrite_items = Vec::new();
    for (source, fingerprint) in sources.iter().zip(signature.iter()) {
        let output = numeric_notice_output(source)?;
        if !docx_path_has_rewrite_marker(&output) {
            rewrite_notice_docx_with_provenance(source, work_dir, copy_to)?;
        }
        if !docx_path_has_rewrite_marker(&output) {
            return Err(format!("通报改写产物验证失败: {}", output.display()));
        }
        if let Some(config_path) = config_path.as_deref() {
            if let Some((number, year)) =
                reserve_notice_number_and_rewrite(config_path, &output, false)?
            {
                result
                    .logs
                    .push(format!("已分配通报编号: 〔{year}〕第{number}期"));
            }
        }
        record_notice_pipeline_artifact(&mut state, NoticePipelineStage::Rewrite, &output)?;
        rewrite_items.push(json!({
            "source": fingerprint,
            "artifact": output.file_name().and_then(|value| value.to_str()).unwrap_or_default(),
        }));
    }
    state
        .compatibility_fields
        .insert("rewrite_items".to_string(), Value::Array(rewrite_items));
    finish_notice_pipeline_stage(work_dir, &mut state, NoticePipelineStage::Rewrite, None)?;

    let report_title = notice_report_title(sources);
    if !state.stages.authorization {
        result.logs.push("步骤2/5: 生成授权委托书".to_string());
        let template = notice_template_as_docx(payload, "授权委托书", work_dir)?;
        run_notice_authorization_stage(work_dir, &mut state, &template, &report_title)?;
    }

    let is_soe = soe_companies.contains(&company);
    if is_soe {
        begin_notice_pipeline_stage(
            work_dir,
            &mut state,
            NoticePipelineStage::Rectification,
            None,
        )?;
        finish_notice_pipeline_stage(
            work_dir,
            &mut state,
            NoticePipelineStage::Rectification,
            None,
        )?;
        result
            .logs
            .push(format!("步骤3/5: 检测到国企 {company}，无需责令整改通知书"));
    } else if !state.stages.rectification {
        result.logs.push("步骤3/5: 生成责令整改通知书".to_string());
        let template = notice_template_as_docx(payload, "责令整改", work_dir)?;
        let vulnerability = notice_vulnerability_text(sources);
        let rectification = run_notice_rectification_stage(
            work_dir,
            &mut state,
            &template,
            &company,
            &vulnerability,
        )?;
        if let Some(config_path) = config_path.as_deref() {
            if let Some((number, year)) =
                reserve_notice_number_and_rewrite(config_path, &rectification, true)?
            {
                result
                    .logs
                    .push(format!("已分配整改编号: 鄞网办责字[{year}]{number}号"));
            }
        }
    }

    if !state.stages.disposal {
        result.logs.push("步骤4/5: 生成处置文件".to_string());
        if let Ok(template) = notice_template_as_docx(payload, "处置", work_dir) {
            run_notice_disposal_stage(work_dir, &mut state, &template)?;
        } else {
            begin_notice_pipeline_stage(work_dir, &mut state, NoticePipelineStage::Disposal, None)?;
            finish_notice_pipeline_stage(
                work_dir,
                &mut state,
                NoticePipelineStage::Disposal,
                None,
            )?;
            result
                .logs
                .push("未找到处置模板，按现有规则跳过".to_string());
        }
    }

    if !state.stages.pdf {
        result
            .logs
            .push("步骤5/5: Rust Word COM 转 PDF".to_string());
        let words = state
            .generated_files
            .iter()
            .map(PathBuf::from)
            .filter(|path| {
                path.is_file()
                    && path
                        .file_name()
                        .and_then(|value| value.to_str())
                        .is_some_and(|name| {
                            name.contains("授权委托书") || name.contains("责令整改")
                        })
            })
            .collect::<Vec<_>>();
        run_notice_pdf_stage(work_dir, &mut state, &words)?;
        cleanup_notice_word_artifacts_after_pdf(&mut state, &mut result.logs)?;
    }

    state.completed = state.stages.all();
    if state.completed {
        remove_completed_notice_sources(&mut state, sources, &mut result.logs)?;
        state.source_sha256 = source_digest(work_dir)?;
        state.updated_at = json!(now_seconds());
        save_notice_state(work_dir, &state)?;
    }
    result.processed = sources.len();
    result.generated_files = state.generated_files.clone();
    result.pdf_outputs = state.pdf_outputs.clone();
    Ok(result)
}

fn run_notice_pipeline_result(
    payload: &Value,
    root: &Path,
    mut logs: Vec<String>,
    archive_failures: Vec<Value>,
    _archive_extractions: Vec<NoticeArchiveExtraction>,
) -> Result<Value, String> {
    let batches = notice_company_batches(root, &mut logs)?;
    let total_reports = batches
        .iter()
        .map(|(_, sources)| sources.len())
        .sum::<usize>();
    if batches.is_empty() {
        return Ok(json!({
            "success": archive_failures.is_empty(),
            "message": format!("处理完成：处理 0 个文档，失败 {} 个，需手动处理 0 个", archive_failures.len()),
            "target_path": root,
            "total_reports": 0,
            "processed": 0,
            "generated_files": [],
            "manual_files": [],
            "failures": archive_failures,
            "pdf_outputs": [],
            "logs": logs,
        }));
    }
    let mut company_groups = BTreeMap::new();
    for (company, group) in grouping_database(payload) {
        company_groups.insert(company, group);
    }
    let soe_companies = configured_soe_companies(payload);
    let mut aggregate = NoticePipelineBatchResult {
        failures: archive_failures,
        ..NoticePipelineBatchResult::default()
    };
    for (work_dir, sources) in batches {
        match process_notice_company_batch(
            payload,
            &work_dir,
            &sources,
            &company_groups,
            &soe_companies,
        ) {
            Ok(batch) => {
                aggregate.processed += batch.processed;
                aggregate.generated_files.extend(batch.generated_files);
                aggregate.manual_files.extend(batch.manual_files);
                aggregate.failures.extend(batch.failures);
                aggregate.pdf_outputs.extend(batch.pdf_outputs);
                aggregate.logs.extend(batch.logs);
            }
            Err(error) => {
                aggregate.failures.push(json!({
                    "file": work_dir,
                    "reason": error,
                }));
            }
        }
    }
    aggregate.generated_files.sort();
    aggregate.generated_files.dedup();
    aggregate.pdf_outputs.sort();
    aggregate.pdf_outputs.dedup();
    logs.extend(aggregate.logs);
    let success = aggregate.failures.is_empty();
    let message = format!(
        "处理完成：处理 {} 个文档，失败 {} 个，需手动处理 {} 个",
        aggregate.processed,
        aggregate.failures.len(),
        aggregate.manual_files.len()
    );
    Ok(json!({
        "success": success,
        "message": message,
        "target_path": root,
        "total_reports": total_reports,
        "processed": aggregate.processed,
        "generated_files": aggregate.generated_files,
        "manual_files": aggregate.manual_files,
        "failures": aggregate.failures,
        "pdf_outputs": aggregate.pdf_outputs,
        "stages": {
            "rewrite": success,
            "authorization": success,
            "rectification": success,
            "disposal": success,
            "pdf": success,
        },
        "logs": logs,
    }))
}

fn active_notice_task_locked(
    tasks: &HashMap<String, NoticeTask>,
    target_key: &str,
    exclude: Option<&str>,
) -> Option<NoticeTask> {
    tasks
        .values()
        .find(|task| {
            task.running
                && task.target_key == target_key
                && exclude.map(|id| id != task.task_id).unwrap_or(true)
        })
        .cloned()
}

fn target_conflict(root: &Path, exclude: Option<&str>) -> Option<NoticeTask> {
    let key = root.to_string_lossy().to_ascii_lowercase();
    let mut guard = notice_tasks().lock().ok()?;
    prune_notice_tasks_locked(&mut guard, now_seconds());
    active_notice_task_locked(&guard, &key, exclude)
}

fn failed_notice_task_result(target_path: &str, error: &str) -> Value {
    json!({
        "success": false,
        "message": format!("处理失败: {error}"),
        "target_path": target_path,
        "total_reports": 0,
        "processed": 0,
        "generated_files": [],
        "manual_files": [],
        "failures": [{"file": target_path, "reason": error}],
        "pdf_outputs": [],
        "logs": [error],
    })
}

fn finish_notice_task(task: &mut NoticeTask, result: Result<Value, String>, finished_at: u64) {
    let outer_error = result.as_ref().err().cloned();
    let result =
        result.unwrap_or_else(|error| failed_notice_task_result(&task.target_path, &error));
    task.running = false;
    task.done = true;
    task.success = result
        .get("success")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    task.progress = if task.success { 100 } else { 0 };
    task.message = result
        .get("message")
        .and_then(Value::as_str)
        .unwrap_or(if task.success {
            "处理完成"
        } else {
            "处理失败"
        })
        .to_string();
    task.logs = result
        .get("logs")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToOwned::to_owned)
                .collect()
        })
        .unwrap_or_default();
    task.error = outer_error;
    task.result = Some(result);
    task.finished_at = Some(finished_at);
}

fn notice_task_status_response(task: &NoticeTask) -> Value {
    let result = task.result.as_ref();
    let value_or = |key: &str, fallback: Value| {
        result
            .and_then(|value| value.get(key))
            .cloned()
            .unwrap_or(fallback)
    };
    let mut response = json!({
        "success": if task.done { task.success } else { true },
        "task_id": task.task_id,
        "generation": task.generation,
        "running": task.running,
        "stopped": false,
        "done": task.done,
        "message": task.message,
        "progress": if task.done && task.success { 100 } else { task.progress },
        "logs": task.logs,
        "processed": value_or("processed", json!(0)),
        "total_reports": value_or("total_reports", json!(0)),
        "target_path": value_or("target_path", Value::Null),
        "generated_files": value_or("generated_files", json!([])),
        "manual_files": value_or("manual_files", json!([])),
        "failures": value_or("failures", json!([])),
        "pdf_outputs": value_or("pdf_outputs", json!([])),
        "error": task.error,
    });
    if task.done {
        response["result"] = result.cloned().unwrap_or_else(|| {
            failed_notice_task_result(&task.target_path, "任务结束但结果数据缺失")
        });
    }
    response
}

fn notice_process_start(payload: &Value) -> Result<Value, String> {
    let requested = required_string(payload, "target_path")?;
    let (root, _) = canonical_notice_target(Path::new(&requested))?;
    let target_key = root.to_string_lossy().to_ascii_lowercase();
    let mut tasks = notice_tasks()
        .lock()
        .map_err(|_| "通报任务锁不可用".to_string())?;
    prune_notice_tasks_locked(&mut tasks, now_seconds());
    if let Some(existing) = active_notice_task_locked(&tasks, &target_key, None) {
        return Ok(json!({
            "success": true,
            "already_running": true,
            "task_id": existing.task_id,
            "generation": existing.generation,
            "running": true,
            "stopped": false,
            "done": false,
            "message": "该目标已有通报任务正在运行，已连接到原任务",
            "progress": existing.progress,
            "logs": existing.logs,
            "processed": 0,
            "total_reports": 0,
        }));
    }
    let active = tasks.values().filter(|task| task.running).count();
    if active >= NOTICE_TASK_MAX_ACTIVE {
        return Ok(json!({
            "success": false,
            "message": format!("已有 {active} 个通报任务正在运行，请等待任务结束后重试"),
            "logs": []
        }));
    }
    let id = format!(
        "notice-{}-{}",
        now_seconds(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    );
    let ticket =
        notice_task_lifecycle().register(id.clone(), "notice-processing", target_key.clone())?;
    tasks.insert(
        id.clone(),
        NoticeTask {
            task_id: id.clone(),
            generation: ticket.generation,
            target_path: root.to_string_lossy().to_string(),
            target_key: root.to_string_lossy().to_ascii_lowercase(),
            running: true,
            done: false,
            success: false,
            progress: 1,
            message: "任务已创建，正在启动...".to_string(),
            logs: Vec::new(),
            result: None,
            error: None,
            created_at: now_seconds(),
            finished_at: None,
        },
    );
    drop(tasks);
    let worker_payload = payload.clone();
    let worker_id = id.clone();
    let worker_ticket = ticket.clone();
    let spawn_result = std::thread::Builder::new()
        .name(format!("koi-notice-{id}"))
        .spawn(move || {
            if !notice_task_lifecycle().is_active(&worker_ticket) {
                return;
            }
            let result = notice_process_result(&worker_payload);
            let success = result
                .as_ref()
                .ok()
                .and_then(|value| value.get("success"))
                .and_then(Value::as_bool)
                .unwrap_or(false);
            if !notice_task_lifecycle()
                .finish(&worker_ticket, success)
                .unwrap_or(false)
            {
                return;
            }
            if let Ok(mut tasks) = notice_tasks().lock() {
                if let Some(task) = tasks.get_mut(&worker_id) {
                    finish_notice_task(task, result, now_seconds());
                }
                prune_notice_tasks_locked(&mut tasks, now_seconds());
            }
        });
    if let Err(error) = spawn_result {
        let _ = notice_task_lifecycle().cancel(&ticket.task_id);
        if let Ok(mut tasks) = notice_tasks().lock() {
            tasks.remove(&id);
        }
        return Err(format!("无法启动通报任务线程: {error}"));
    }
    Ok(json!({
        "success": true,
        "task_id": id,
        "generation": ticket.generation,
        "running": true,
        "stopped": false,
        "done": false,
        "message": "任务已创建，正在启动...",
        "progress": 1,
        "logs": [],
        "processed": 0,
        "total_reports": 0,
    }))
}

fn notice_process_status(payload: &Value) -> Result<Value, String> {
    let task_id = required_string(payload, "task_id")?;
    let mut tasks = notice_tasks()
        .lock()
        .map_err(|_| "通报任务锁不可用".to_string())?;
    prune_notice_tasks_locked(&mut tasks, now_seconds());
    let Some(task) = tasks.get(&task_id) else {
        if let Some(snapshot) = notice_task_lifecycle().snapshot(&task_id) {
            return Ok(json!({
                "success": false,
                "task_id": task_id,
                "generation": snapshot.generation,
                "done": true,
                "running": false,
                "stopped": snapshot.stopped,
                "message": "任务已由统一任务管理器恢复为停止状态",
                "error_code": "notice_task_not_found",
                "logs": [],
            }));
        }
        return Ok(json!({
            "success": false,
            "task_id": task_id,
            "done": true,
            "running": false,
            "stopped": false,
            "message": "任务不存在或已过期，可能是后端已经重启",
            "error_code": "notice_task_not_found",
            "logs": [],
        }));
    };
    Ok(notice_task_status_response(task))
}

const REWRITTEN_NOTICE_MARKER: &str = "koi.notice.rewritten.v1";
const WORD_NS_PREFIX: &[u8] = b"w:";

fn xml_local_name(name: &[u8]) -> &[u8] {
    name.rsplit(|byte| *byte == b':').next().unwrap_or(name)
}

fn is_word_element(event: &Event<'_>, local: &[u8]) -> bool {
    match event {
        Event::Start(start) | Event::Empty(start) => {
            let qualified_name = start.name();
            let name = qualified_name.as_ref();
            name.starts_with(WORD_NS_PREFIX) && xml_local_name(name) == local
        }
        Event::End(end) => {
            let qualified_name = end.name();
            let name = qualified_name.as_ref();
            name.starts_with(WORD_NS_PREFIX) && xml_local_name(name) == local
        }
        _ => false,
    }
}

fn docx_has_rewrite_marker(core_xml: &[u8]) -> bool {
    // python-docx stores ``core_properties.comments`` in dc:description. Do
    // not accept the marker when it appears in an unrelated XML part or in a
    // longer value; the semicolon-token behavior matches Python exactly.
    let mut reader = XmlReader::from_reader(Cursor::new(core_xml));
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut in_description = false;
    let mut description = String::new();
    loop {
        let event = match reader.read_event_into(&mut buffer) {
            Ok(event) => event,
            Err(_) => return false,
        };
        match event {
            Event::Start(start) => {
                let name = start.name();
                if name.as_ref().starts_with(b"dc:")
                    && xml_local_name(name.as_ref()) == b"description"
                {
                    in_description = true;
                    description.clear();
                }
            }
            Event::End(end) => {
                let name = end.name();
                if name.as_ref().starts_with(b"dc:")
                    && xml_local_name(name.as_ref()) == b"description"
                {
                    if in_description
                        && description
                            .split(';')
                            .any(|token| token.trim() == REWRITTEN_NOTICE_MARKER)
                    {
                        return true;
                    }
                    in_description = false;
                }
            }
            Event::Text(text) if in_description => {
                let Ok(decoded) = text.decode() else {
                    return false;
                };
                let Ok(decoded) = quick_xml::escape::unescape(&decoded) else {
                    return false;
                };
                description.push_str(&decoded);
            }
            Event::CData(text) if in_description => {
                let Ok(decoded) = text.decode() else {
                    return false;
                };
                description.push_str(&decoded);
            }
            Event::Eof => return false,
            _ => {}
        }
        buffer.clear();
    }
}

fn xml_event_text(event: &Event<'_>) -> Result<String, String> {
    match event {
        Event::Text(text) => text
            .decode()
            .map(|value| value.into_owned())
            .map_err(|error| format!("DOCX 文本解码失败: {error}")),
        Event::CData(text) => text
            .decode()
            .map(|value| value.into_owned())
            .map_err(|error| format!("DOCX CDATA 解码失败: {error}")),
        _ => Ok(String::new()),
    }
}

fn replace_copy_to_paragraph(
    events: &mut [Event<'static>],
    township: &str,
) -> Result<bool, String> {
    // python-docx's ``Document.paragraphs`` excludes paragraphs nested in
    // table cells; keep the same provenance boundary instead of rewriting
    // arbitrary table content.
    if events
        .iter()
        .any(|event| is_word_element(event, b"tbl") && matches!(event, Event::Start(_)))
    {
        return Ok(false);
    }
    let mut paragraph_text = String::new();
    let mut text_indices = Vec::new();
    let mut element_stack: Vec<Vec<u8>> = Vec::new();
    for (index, event) in events.iter().enumerate() {
        match event {
            Event::Start(start) => {
                let qualified_name = start.name();
                element_stack.push(xml_local_name(qualified_name.as_ref()).to_vec());
            }
            Event::End(_) => {
                element_stack.pop();
            }
            Event::Empty(start) => {
                let qualified_name = start.name();
                if qualified_name.as_ref().starts_with(WORD_NS_PREFIX)
                    && xml_local_name(qualified_name.as_ref()) == b"tab"
                {
                    paragraph_text.push('\t');
                }
            }
            Event::Text(_) | Event::CData(_)
                if element_stack.last().map(Vec::as_slice) == Some(b"t") =>
            {
                paragraph_text.push_str(&xml_event_text(event)?);
                text_indices.push(index);
            }
            _ => {}
        }
    }

    let normalized = paragraph_text.trim();
    let is_blank_copy_to = is_blank_copy_to_text(normalized);
    if !is_blank_copy_to || text_indices.is_empty() || township.trim().is_empty() {
        return Ok(false);
    }

    let replacement = format!("抄送：{}", township.trim());
    let first = text_indices[0];
    events[first] = Event::Text(BytesText::new(&replacement).into_owned());
    for index in text_indices.into_iter().skip(1) {
        events[index] = Event::Text(BytesText::new("").into_owned());
    }
    Ok(true)
}

fn is_blank_copy_to_text(value: &str) -> bool {
    let Some(rest) = value.trim().strip_prefix("抄送") else {
        return false;
    };
    let rest = rest.trim_start_matches(char::is_whitespace);
    let Some(rest) = rest.strip_prefix(':').or_else(|| rest.strip_prefix('：')) else {
        return false;
    };
    rest.trim().is_empty()
}

fn rewrite_document_copy_to(
    document_xml: &[u8],
    township: &str,
) -> Result<(Vec<u8>, bool), String> {
    let mut reader = XmlReader::from_reader(Cursor::new(document_xml));
    reader.config_mut().trim_text(false);
    let mut writer = XmlWriter::new(Vec::with_capacity(document_xml.len() + township.len()));
    let mut read_buffer = Vec::new();
    let mut paragraph: Option<Vec<Event<'static>>> = None;
    let mut paragraph_depth = 0usize;
    let mut updated = false;

    loop {
        let event = reader
            .read_event_into(&mut read_buffer)
            .map_err(|error| format!("DOCX XML 解析失败: {error}"))?
            .into_owned();
        read_buffer.clear();
        if matches!(event, Event::Eof) {
            break;
        }

        if let Some(events) = paragraph.as_mut() {
            let starts_paragraph =
                is_word_element(&event, b"p") && matches!(event, Event::Start(_));
            let ends_paragraph = matches!(&event, Event::End(end) if end.name().as_ref().starts_with(WORD_NS_PREFIX) && xml_local_name(end.name().as_ref()) == b"p");
            if starts_paragraph {
                paragraph_depth = paragraph_depth.saturating_add(1);
            }
            events.push(event);
            if ends_paragraph {
                paragraph_depth = paragraph_depth.saturating_sub(1);
                if paragraph_depth == 0 {
                    let mut finished = paragraph.take().unwrap_or_default();
                    if replace_copy_to_paragraph(&mut finished, township)? {
                        updated = true;
                    }
                    for item in finished {
                        writer
                            .write_event(item)
                            .map_err(|error| format!("DOCX XML 写入失败: {error}"))?;
                    }
                }
            }
            continue;
        }

        if is_word_element(&event, b"p") && matches!(event, Event::Start(_)) {
            paragraph_depth = 1;
            paragraph = Some(vec![event]);
        } else {
            writer
                .write_event(event)
                .map_err(|error| format!("DOCX XML 写入失败: {error}"))?;
        }
    }

    if paragraph.is_some() {
        return Err("DOCX XML 段落未闭合".to_string());
    }
    Ok((writer.into_inner(), updated))
}

fn atomic_replace_docx_with_copy_to(path: &Path, township: &str) -> Result<bool, String> {
    // Bound both the package and the XML part before buffering or rewriting.
    let package_size = fs::metadata(path)
        .map_err(|error| format!("DOCX metadata read failed: {error}"))?
        .len();
    if package_size > MAX_NOTICE_DOCX_BYTES {
        return Err(format!(
            "DOCX size exceeds limit: {} bytes",
            MAX_NOTICE_DOCX_BYTES
        ));
    }
    let metadata = fs::symlink_metadata(path).map_err(|error| format!("无法读取 DOCX: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("拒绝处理符号链接或非普通 DOCX 文件".to_string());
    }

    let source = File::open(path).map_err(|error| format!("无法打开 DOCX: {error}"))?;
    let mut archive = ZipArchive::new(source).map_err(|error| format!("DOCX ZIP 无效: {error}"))?;
    let mut core_xml = None;
    let mut document_xml = None;
    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|error| format!("读取 DOCX 部件失败: {error}"))?;
        let name = entry.name().to_ascii_lowercase();
        if name == "docprops/core.xml" {
            let mut bytes = Vec::new();
            entry
                .read_to_end(&mut bytes)
                .map_err(|error| format!("读取 DOCX 元数据失败: {error}"))?;
            core_xml = Some(bytes);
        } else if name == "word/document.xml" {
            let mut bytes = Vec::new();
            entry
                .read_to_end(&mut bytes)
                .map_err(|error| format!("读取 DOCX 文档失败: {error}"))?;
            document_xml = Some(bytes);
        }
    }
    if !core_xml
        .as_deref()
        .map(docx_has_rewrite_marker)
        .unwrap_or(false)
    {
        return Ok(false);
    }
    let Some(document_xml) = document_xml else {
        return Err("DOCX 缺少 word/document.xml".to_string());
    };
    if document_xml.len() > MAX_NOTICE_XML_BYTES {
        return Err(format!(
            "word/document.xml size exceeds limit: {} bytes",
            MAX_NOTICE_XML_BYTES
        ));
    }
    let (rewritten_xml, updated) = rewrite_document_copy_to(&document_xml, township)?;
    if !updated {
        return Ok(false);
    }

    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let temporary = path.with_file_name(format!(
        ".{}.koi-copy-to-{}.tmp",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("document.docx"),
        id
    ));
    let result = (|| {
        let output =
            File::create(&temporary).map_err(|error| format!("创建 DOCX 临时文件失败: {error}"))?;
        let mut writer = ZipWriter::new(output);
        let source = File::open(path).map_err(|error| format!("重新打开 DOCX 失败: {error}"))?;
        let mut archive =
            ZipArchive::new(source).map_err(|error| format!("DOCX ZIP 无效: {error}"))?;
        for index in 0..archive.len() {
            let entry = archive
                .by_index(index)
                .map_err(|error| format!("读取 DOCX 部件失败: {error}"))?;
            let name = entry.name().to_string();
            if name.eq_ignore_ascii_case("word/document.xml") {
                writer
                    .start_file(
                        name,
                        SimpleFileOptions::default()
                            .compression_method(CompressionMethod::Deflated),
                    )
                    .map_err(|error| format!("写入 DOCX 文档部件失败: {error}"))?;
                writer
                    .write_all(&rewritten_xml)
                    .map_err(|error| format!("写入 DOCX 文档失败: {error}"))?;
            } else {
                writer
                    .raw_copy_file(entry)
                    .map_err(|error| format!("保留 DOCX 部件失败: {error}"))?;
            }
        }
        drop(archive);
        let output = writer
            .finish()
            .map_err(|error| format!("完成 DOCX 临时文件失败: {error}"))?;
        output
            .sync_all()
            .map_err(|error| format!("同步 DOCX 临时文件失败: {error}"))?;
        let backup = path.with_file_name(format!(
            ".{}.koi-copy-to-backup-{}",
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("document.docx"),
            id
        ));
        fs::rename(path, &backup).map_err(|error| format!("DOCX backup rename failed: {error}"))?;
        if let Err(error) = fs::rename(&temporary, path) {
            let _ = fs::rename(&backup, path);
            return Err(format!("DOCX atomic replace failed: {error}"));
        }
        fs::remove_file(&backup).map_err(|error| format!("DOCX backup cleanup failed: {error}"))?;
        Ok::<(), String>(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map(|()| true)
}

#[allow(dead_code)]
fn template_by_keyword(payload: &Value, keyword: &str) -> Option<PathBuf> {
    let directory = payload
        .get("_notice_templates_dir")
        .and_then(Value::as_str)
        .map(PathBuf::from)?;
    let mut candidates = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .is_some_and(|name| name.contains(keyword))
                && path
                    .extension()
                    .and_then(|value| value.to_str())
                    .is_some_and(|extension| {
                        extension.eq_ignore_ascii_case("docx")
                            || extension.eq_ignore_ascii_case("doc")
                    })
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    candidates.into_iter().next()
}

fn notice_template_as_docx(
    payload: &Value,
    keyword: &str,
    work_dir: &Path,
) -> Result<PathBuf, String> {
    let template = template_by_keyword(payload, keyword)
        .ok_or_else(|| format!("未找到 {keyword} DOC/DOCX 模板"))?;
    if template
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
    {
        return Ok(template);
    }
    let stem = template
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "DOC 模板文件名无效".to_string())?;
    let output = work_dir.join(format!("{stem}.docx"));
    let response = document_conversion::dispatch(
        "doc.convert.run",
        &json!({
            "conversion_type": "word_to_docx",
            "input_path": template,
            "output_dir": work_dir,
            "recursive": false,
            "overwrite": true,
            "skip_template": false,
        }),
    )?;
    if response.get("success").and_then(Value::as_bool) != Some(true) {
        return Err(response
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("DOC 模板转换为 DOCX 失败")
            .to_string());
    }
    if !output.is_file() {
        return Err("DOC 模板转换未生成 DOCX 输出".to_string());
    }
    Ok(output)
}

#[allow(dead_code)]
fn rewrite_ooxml_document_part<F>(
    source: &Path,
    destination: &Path,
    rewrite: F,
) -> Result<(), String>
where
    F: FnOnce(Vec<u8>) -> Result<Vec<u8>, String>,
{
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("cannot inspect DOCX template: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("DOCX template must be a regular file".to_string());
    }
    if metadata.len() > MAX_NOTICE_DOCX_BYTES {
        return Err("DOCX template exceeds the bounded size".to_string());
    }
    let parent = destination
        .parent()
        .ok_or_else(|| "DOCX destination has no parent".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("create DOCX output failed: {error}"))?;
    let temporary = parent.join(format!(
        ".{}.koi-stage-{}-{}.tmp",
        destination
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("notice.docx"),
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    ));
    let input =
        File::open(source).map_err(|error| format!("open DOCX template failed: {error}"))?;
    let mut archive =
        ZipArchive::new(input).map_err(|error| format!("invalid DOCX template: {error}"))?;
    let result = (|| {
        let output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| format!("create DOCX temporary file failed: {error}"))?;
        let mut writer = ZipWriter::new(output);
        let mut document_seen = false;
        let mut rewrite = Some(rewrite);
        for index in 0..archive.len() {
            let mut entry = archive
                .by_index(index)
                .map_err(|error| format!("read DOCX part failed: {error}"))?;
            let name = entry.name().to_string();
            if name.eq_ignore_ascii_case("word/document.xml") {
                let mut bytes = Vec::new();
                entry
                    .by_ref()
                    .take(MAX_NOTICE_XML_BYTES as u64 + 1)
                    .read_to_end(&mut bytes)
                    .map_err(|error| format!("read DOCX document part failed: {error}"))?;
                if bytes.len() > MAX_NOTICE_XML_BYTES {
                    return Err("DOCX document part exceeds the bounded size".to_string());
                }
                let rewritten = rewrite.take().expect("rewrite closure used once")(bytes)?;
                writer
                    .start_file(
                        name,
                        SimpleFileOptions::default()
                            .compression_method(CompressionMethod::Deflated),
                    )
                    .map_err(|error| format!("create rewritten DOCX part failed: {error}"))?;
                writer
                    .write_all(&rewritten)
                    .map_err(|error| format!("write rewritten DOCX part failed: {error}"))?;
                document_seen = true;
            } else {
                writer
                    .raw_copy_file(entry)
                    .map_err(|error| format!("preserve DOCX part failed: {error}"))?;
            }
        }
        if !document_seen {
            return Err("DOCX template has no word/document.xml".to_string());
        }
        let output = writer
            .finish()
            .map_err(|error| format!("finish DOCX output failed: {error}"))?;
        output
            .sync_all()
            .map_err(|error| format!("sync DOCX output failed: {error}"))?;
        ZipArchive::new(
            File::open(&temporary)
                .map_err(|error| format!("reopen DOCX output failed: {error}"))?,
        )
        .map_err(|error| format!("DOCX output validation failed: {error}"))?;
        atomic_write(
            destination,
            &fs::read(&temporary).map_err(|error| error.to_string())?,
        )?;
        Ok::<(), String>(())
    })();
    let _ = fs::remove_file(&temporary);
    result
}

fn rewrite_docx_paragraphs<F>(document_xml: &[u8], transform: F) -> Result<(Vec<u8>, bool), String>
where
    F: Fn(&str) -> Option<String>,
{
    let mut reader = XmlReader::from_reader(Cursor::new(document_xml));
    reader.config_mut().trim_text(false);
    let mut writer = XmlWriter::new(Vec::with_capacity(document_xml.len() + 256));
    let mut input = Vec::new();
    let mut paragraph: Option<Vec<Event<'static>>> = None;
    let mut depth = 0usize;
    let mut changed = false;
    loop {
        let event = reader
            .read_event_into(&mut input)
            .map_err(|error| format!("DOCX paragraph XML parse failed: {error}"))?
            .into_owned();
        input.clear();
        if matches!(event, Event::Eof) {
            break;
        }
        if let Some(events) = paragraph.as_mut() {
            let starts = is_word_element(&event, b"p") && matches!(event, Event::Start(_));
            let ends = matches!(&event, Event::End(end)
                if end.name().as_ref().starts_with(WORD_NS_PREFIX)
                    && xml_local_name(end.name().as_ref()) == b"p");
            if starts {
                depth = depth.saturating_add(1);
            }
            events.push(event);
            if ends {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    let mut finished = paragraph.take().unwrap_or_default();
                    let mut text = String::new();
                    let mut text_indices = Vec::new();
                    let mut stack = Vec::<Vec<u8>>::new();
                    for (index, item) in finished.iter().enumerate() {
                        match item {
                            Event::Start(start) => {
                                stack.push(xml_local_name(start.name().as_ref()).to_vec());
                            }
                            Event::End(_) => {
                                stack.pop();
                            }
                            Event::Text(_) | Event::CData(_)
                                if stack.last().map(Vec::as_slice) == Some(b"t") =>
                            {
                                text.push_str(&xml_event_text(item)?);
                                text_indices.push(index);
                            }
                            _ => {}
                        }
                    }
                    if !text_indices.is_empty() {
                        if let Some(replacement) = transform(&text) {
                            let first = text_indices[0];
                            finished[first] =
                                Event::Text(BytesText::new(&replacement).into_owned());
                            for index in text_indices.into_iter().skip(1) {
                                finished[index] = Event::Text(BytesText::new("").into_owned());
                            }
                            changed = true;
                        }
                    }
                    for item in finished {
                        writer
                            .write_event(item)
                            .map_err(|error| format!("DOCX paragraph XML write failed: {error}"))?;
                    }
                }
            }
            continue;
        }
        if is_word_element(&event, b"p") && matches!(event, Event::Start(_)) {
            depth = 1;
            paragraph = Some(vec![event]);
        } else {
            writer
                .write_event(event)
                .map_err(|error| format!("DOCX XML write failed: {error}"))?;
        }
    }
    if paragraph.is_some() {
        return Err("DOCX paragraph XML is not closed".to_string());
    }
    Ok((writer.into_inner(), changed))
}

fn docx_text_content(path: &Path) -> Result<String, String> {
    let file =
        File::open(path).map_err(|error| format!("open DOCX for validation failed: {error}"))?;
    let mut archive =
        ZipArchive::new(file).map_err(|error| format!("invalid DOCX for validation: {error}"))?;
    let mut xml = Vec::new();
    archive
        .by_name("word/document.xml")
        .map_err(|error| format!("DOCX lacks word/document.xml: {error}"))?
        .take(MAX_NOTICE_XML_BYTES as u64 + 1)
        .read_to_end(&mut xml)
        .map_err(|error| format!("read DOCX document.xml failed: {error}"))?;
    if xml.len() > MAX_NOTICE_XML_BYTES {
        return Err("DOCX document.xml exceeds the bounded size".to_string());
    }
    let mut reader = XmlReader::from_reader(Cursor::new(xml));
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut text = String::new();
    loop {
        match reader.read_event_into(&mut buffer) {
            Ok(Event::Text(value)) => text.push_str(
                &value
                    .decode()
                    .map_err(|error| format!("decode DOCX text failed: {error}"))?,
            ),
            Ok(Event::CData(value)) => text.push_str(
                &value
                    .decode()
                    .map_err(|error| format!("decode DOCX CDATA failed: {error}"))?,
            ),
            Ok(Event::Eof) => break,
            Ok(_) => {}
            Err(error) => return Err(format!("parse DOCX document.xml failed: {error}")),
        }
        buffer.clear();
    }
    Ok(text)
}

#[allow(dead_code)]
fn replace_first_literal(xml: Vec<u8>, from: &str, to: &str) -> Result<Vec<u8>, String> {
    let text = String::from_utf8(xml).map_err(|_| "DOCX document.xml is not UTF-8".to_string())?;
    if !text.contains(from) {
        return Err(format!("DOCX template marker not found: {from}"));
    }
    Ok(text.replacen(from, &xml_escape_text(to), 1).into_bytes())
}

#[allow(dead_code)]
fn xml_escape_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

#[allow(dead_code)]
fn generate_authorization_document(
    template: &Path,
    work_dir: &Path,
    report_title: &str,
) -> Result<PathBuf, String> {
    let output = work_dir.join(
        template
            .file_name()
            .ok_or_else(|| "authorization template has no filename".to_string())?,
    );
    rewrite_ooxml_document_part(template, &output, |xml| {
        let (rewritten, changed) = rewrite_docx_paragraphs(&xml, |text| {
            text.contains('*')
                .then(|| text.replacen('*', report_title, 1))
        })?;
        if !changed {
            return replace_first_literal(xml, "*", report_title);
        }
        Ok(rewritten)
    })?;
    let text = docx_text_content(&output)?;
    if text.contains('*') || !text.contains(report_title) {
        return Err("authorization DOCX content validation failed".to_string());
    }
    Ok(output)
}

#[allow(dead_code)]
fn generate_disposal_document(template: &Path, work_dir: &Path) -> Result<PathBuf, String> {
    let name = template
        .file_name()
        .and_then(|value| value.to_str())
        .map(clean_template_name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "disposal template has no filename".to_string())?;
    let output = work_dir.join(name);
    rewrite_ooxml_document_part(template, &output, |xml| {
        let (rewritten, changed) = rewrite_docx_paragraphs(&xml, |text| {
            (["××网信办：", "XX网信办：", "xx网信办："])
                .iter()
                .find_map(|marker| {
                    text.contains(marker)
                        .then(|| text.replacen(marker, "鄞州区网信办：", 1))
                })
        })?;
        if !changed {
            return Err("disposal template addressee marker not found".to_string());
        }
        Ok(rewritten)
    })?;
    let text = docx_text_content(&output)?;
    if !text.contains("鄞州区网信办：") {
        return Err("disposal DOCX content validation failed".to_string());
    }
    Ok(output)
}

#[derive(Debug, Clone, Copy)]
enum NoticePipelineStage {
    Rewrite,
    Authorization,
    Rectification,
    Disposal,
    Pdf,
}

impl NoticePipelineStage {
    fn name(self) -> &'static str {
        match self {
            Self::Rewrite => "rewrite",
            Self::Authorization => "authorization",
            Self::Rectification => "rectification",
            Self::Disposal => "disposal",
            Self::Pdf => "pdf",
        }
    }

    fn set(self, stages: &mut NoticeStages, value: bool) {
        match self {
            Self::Rewrite => stages.rewrite = value,
            Self::Authorization => stages.authorization = value,
            Self::Rectification => stages.rectification = value,
            Self::Disposal => stages.disposal = value,
            Self::Pdf => stages.pdf = value,
        }
    }
}

fn begin_notice_pipeline_stage(
    root: &Path,
    state: &mut NoticeState,
    stage: NoticePipelineStage,
    source: Option<&Path>,
) -> Result<(), String> {
    stage.set(&mut state.stages, false);
    state.completed = false;
    state
        .compatibility_fields
        .insert("active_stage".to_string(), json!(stage.name()));
    state
        .compatibility_fields
        .insert("stage_started_at".to_string(), json!(now_seconds()));
    let source_fingerprint = source
        .map(|path| -> Result<Value, String> {
            let metadata = fs::symlink_metadata(path)
                .map_err(|error| format!("cannot fingerprint notice source: {error}"))?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err("notice source must be a regular file".to_string());
            }
            Ok(json!({
                "name": path.file_name().and_then(|value| value.to_str()).unwrap_or_default(),
                "size": metadata.len(),
                "sha256": file_sha256(path)?,
            }))
        })
        .transpose()?
        .unwrap_or(Value::Null);
    state
        .compatibility_fields
        .insert("active_source".to_string(), source_fingerprint.clone());
    if matches!(stage, NoticePipelineStage::Rewrite) && !source_fingerprint.is_null() {
        state.compatibility_fields.insert(
            "input_signature".to_string(),
            Value::Array(vec![source_fingerprint]),
        );
    }
    state.updated_at = json!(now_seconds());
    save_notice_state(root, state)
}

fn finish_notice_pipeline_stage(
    root: &Path,
    state: &mut NoticeState,
    stage: NoticePipelineStage,
    artifact: Option<&Path>,
) -> Result<(), String> {
    if let Some(path) = artifact {
        record_notice_pipeline_artifact(state, stage, path)?;
    }
    stage.set(&mut state.stages, true);
    state.completed = state.stages.all();
    state
        .compatibility_fields
        .insert("active_stage".to_string(), Value::Null);
    state
        .compatibility_fields
        .insert("stage_started_at".to_string(), Value::Null);
    state
        .compatibility_fields
        .insert("active_source".to_string(), Value::Null);
    state.updated_at = json!(now_seconds());
    save_notice_state(root, state)
}

fn record_notice_pipeline_artifact(
    state: &mut NoticeState,
    stage: NoticePipelineStage,
    path: &Path,
) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot validate notice stage artifact: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("notice stage artifact must be a regular file".to_string());
    }
    let path = path.to_string_lossy().to_string();
    if !state.artifacts.contains(&path) {
        state.artifacts.push(path.clone());
    }
    if !matches!(stage, NoticePipelineStage::Pdf) && !state.generated_files.contains(&path) {
        state.generated_files.push(path.clone());
    }
    if matches!(stage, NoticePipelineStage::Pdf) && !state.pdf_outputs.contains(&path) {
        state.pdf_outputs.push(path);
    }
    Ok(())
}

#[allow(dead_code)]
fn append_rewrite_marker(core_xml: Vec<u8>) -> Result<Vec<u8>, String> {
    let mut text = String::from_utf8(core_xml)
        .map_err(|_| "DOCX core properties are not UTF-8".to_string())?;
    if docx_has_rewrite_marker(text.as_bytes()) {
        return Ok(text.into_bytes());
    }
    if let Some(index) = text.find("</dc:description>") {
        let opening = text[..index].rfind('>').unwrap_or(index);
        let separator = if text[opening.saturating_add(1)..index].trim().is_empty() {
            ""
        } else {
            ";"
        };
        text.insert_str(index, &format!("{separator}{REWRITTEN_NOTICE_MARKER}"));
        return Ok(text.into_bytes());
    }
    let close = "</cp:coreProperties>";
    if !text.contains(close) {
        return Err("DOCX core properties root is invalid".to_string());
    }
    if !text.contains("xmlns:dc=") {
        let Some(root_start) = text.find("<cp:coreProperties") else {
            return Err("DOCX core properties root is invalid".to_string());
        };
        let Some(root_end) = text[root_start..].find('>').map(|index| root_start + index) else {
            return Err("DOCX core properties root is invalid".to_string());
        };
        text.insert_str(root_end, r#" xmlns:dc="http://purl.org/dc/elements/1.1/""#);
    }
    let Some(index) = text.find(close) else {
        return Err("DOCX core properties root is invalid".to_string());
    };
    text.insert_str(
        index,
        &format!(
            "<dc:description>{}</dc:description>",
            REWRITTEN_NOTICE_MARKER
        ),
    );
    Ok(text.into_bytes())
}

#[allow(dead_code)]
fn rewrite_notice_source_ooxml(
    source: &Path,
    output: &Path,
    copy_to: Option<&str>,
) -> Result<(), String> {
    let metadata = fs::symlink_metadata(source)
        .map_err(|error| format!("cannot inspect notice source: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("notice source must be a regular DOCX file".to_string());
    }
    if source
        .extension()
        .and_then(|value| value.to_str())
        .is_none_or(|value| !value.eq_ignore_ascii_case("docx"))
    {
        return Err("notice rewrite source must use .docx".to_string());
    }
    let input =
        File::open(source).map_err(|error| format!("open notice source failed: {error}"))?;
    let mut archive =
        ZipArchive::new(input).map_err(|error| format!("invalid notice DOCX: {error}"))?;
    let parent = output
        .parent()
        .ok_or_else(|| "notice output has no parent".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("create notice output directory failed: {error}"))?;
    let temporary = parent.join(format!(
        ".{}.koi-rewrite-{}.tmp",
        output
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("notice.docx"),
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    ));
    let result = (|| {
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| format!("create notice rewrite temporary failed: {error}"))?;
        let mut writer = ZipWriter::new(file);
        let mut document_seen = false;
        let mut core_seen = false;
        for index in 0..archive.len() {
            let mut entry = archive
                .by_index(index)
                .map_err(|error| format!("read notice DOCX part failed: {error}"))?;
            let name = entry.name().to_string();
            if name.eq_ignore_ascii_case("docProps/core.xml") {
                let mut bytes = Vec::new();
                entry
                    .by_ref()
                    .take(MAX_NOTICE_XML_BYTES as u64 + 1)
                    .read_to_end(&mut bytes)
                    .map_err(|error| format!("read notice core properties failed: {error}"))?;
                if bytes.len() > MAX_NOTICE_XML_BYTES {
                    return Err("notice core properties exceed the bounded size".to_string());
                }
                let bytes = append_rewrite_marker(bytes)?;
                writer
                    .start_file(
                        name,
                        SimpleFileOptions::default()
                            .compression_method(CompressionMethod::Deflated),
                    )
                    .map_err(|error| format!("create notice core part failed: {error}"))?;
                writer
                    .write_all(&bytes)
                    .map_err(|error| format!("write notice core part failed: {error}"))?;
                core_seen = true;
            } else if name.eq_ignore_ascii_case("word/document.xml") && copy_to.is_some() {
                let mut bytes = Vec::new();
                entry
                    .by_ref()
                    .take(MAX_NOTICE_XML_BYTES as u64 + 1)
                    .read_to_end(&mut bytes)
                    .map_err(|error| format!("read notice document failed: {error}"))?;
                let (bytes, _) = rewrite_document_copy_to(&bytes, copy_to.unwrap_or_default())?;
                writer
                    .start_file(
                        name,
                        SimpleFileOptions::default()
                            .compression_method(CompressionMethod::Deflated),
                    )
                    .map_err(|error| format!("create notice document part failed: {error}"))?;
                writer
                    .write_all(&bytes)
                    .map_err(|error| format!("write notice document failed: {error}"))?;
                document_seen = true;
            } else {
                if name.eq_ignore_ascii_case("word/document.xml") {
                    document_seen = true;
                }
                writer
                    .raw_copy_file(entry)
                    .map_err(|error| format!("preserve notice DOCX part failed: {error}"))?;
            }
        }
        if !document_seen || !core_seen {
            return Err("notice DOCX is missing required OOXML parts".to_string());
        }
        let file = writer
            .finish()
            .map_err(|error| format!("finish notice rewrite failed: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("sync notice rewrite failed: {error}"))?;
        atomic_write(
            output,
            &fs::read(&temporary).map_err(|error| error.to_string())?,
        )?;
        Ok::<(), String>(())
    })();
    let _ = fs::remove_file(&temporary);
    result?;
    if !docx_path_has_rewrite_marker(output) {
        return Err("rewritten notice provenance verification failed".to_string());
    }
    Ok(())
}

#[allow(dead_code)]
fn numeric_notice_output(source: &Path) -> Result<PathBuf, String> {
    let name = source
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "notice source filename is invalid".to_string())?;
    if !name.starts_with(|character: char| character.is_ascii_digit()) {
        return Err("notice rewrite source must have a numeric prefix".to_string());
    }
    let output_name = name.trim_start_matches(|character: char| character.is_ascii_digit());
    if output_name.is_empty() {
        return Err("notice rewrite output filename is empty".to_string());
    }
    Ok(source.with_file_name(output_name))
}

#[allow(dead_code)]
fn rewrite_notice_docx_with_provenance(
    source: &Path,
    output_dir: &Path,
    copy_to: Option<&str>,
) -> Result<PathBuf, String> {
    let output = numeric_notice_output(source).map(|path| {
        output_dir.join(
            path.file_name()
                .unwrap_or_else(|| std::ffi::OsStr::new("notice.docx")),
        )
    })?;
    rewrite_notice_source_ooxml(source, &output, copy_to)?;
    Ok(output)
}

#[allow(dead_code)]
fn run_notice_rewrite_stage(
    root: &Path,
    state: &mut NoticeState,
    source: &Path,
    copy_to: Option<&str>,
) -> Result<PathBuf, String> {
    begin_notice_pipeline_stage(root, state, NoticePipelineStage::Rewrite, Some(source))?;
    let output = rewrite_notice_docx_with_provenance(source, root, copy_to)?;
    finish_notice_pipeline_stage(root, state, NoticePipelineStage::Rewrite, Some(&output))?;
    Ok(output)
}

fn generate_rectification_document(
    template: &Path,
    work_dir: &Path,
    company: &str,
    vulnerability: &str,
) -> Result<PathBuf, String> {
    let output = work_dir.join(
        template
            .file_name()
            .ok_or_else(|| "rectification template has no filename".to_string())?,
    );
    rewrite_ooxml_document_part(template, &output, |xml| {
        let company = company.to_string();
        let vulnerability = vulnerability.to_string();
        let (rewritten, changed) = rewrite_docx_paragraphs(&xml, |paragraph| {
            let mut text = paragraph.to_string();
            let mut touched = false;
            for marker in ["【公司名】", "{公司名}", "公司名】"] {
                if text.contains(marker) {
                    text = text.replace(marker, &company);
                    touched = true;
                }
            }
            for marker in ["【漏洞类型】", "{漏洞类型}", "漏洞类型】"] {
                if text.contains(marker) {
                    text = text.replace(marker, &vulnerability);
                    touched = true;
                }
            }
            if let Some(existing) = company_from_text(&text) {
                if existing != company && text.contains(&existing) {
                    text = text.replacen(&existing, &company, 1);
                    touched = true;
                }
            }
            if let Some(start) = text.find("存在") {
                if let Some(end) = ["漏洞", "风险", "隐患", "事件"]
                    .iter()
                    .filter_map(|suffix| {
                        text[start..]
                            .find(suffix)
                            .map(|offset| start + offset + suffix.len())
                    })
                    .min()
                {
                    let replacement = if vulnerability.starts_with("存在") {
                        vulnerability.clone()
                    } else {
                        format!("存在{vulnerability}")
                    };
                    text.replace_range(start..end, &replacement);
                    touched = true;
                }
            }
            let date_regex = Regex::new(r"20\d{2}\s*年\s*\d+\s*月\s*\d+\s*日").ok()?;
            let date = local_date_text();
            if date_regex.is_match(&text) {
                text = date_regex.replace(&text, date.as_str()).into_owned();
                touched = true;
            }
            touched.then_some(text)
        })?;
        if !changed {
            return Err("rectification template contains no replaceable company, vulnerability, or date fields".to_string());
        }
        Ok(rewritten)
    })?;
    let text = docx_text_content(&output)?;
    if text.contains("【公司名】")
        || text.contains("【漏洞类型】")
        || !text.contains(company)
        || (!vulnerability.is_empty() && !text.contains(vulnerability))
    {
        return Err("rectification DOCX content validation failed".to_string());
    }
    Ok(output)
}

fn run_notice_generated_stage<F>(
    root: &Path,
    state: &mut NoticeState,
    stage: NoticePipelineStage,
    generate: F,
) -> Result<PathBuf, String>
where
    F: FnOnce() -> Result<PathBuf, String>,
{
    begin_notice_pipeline_stage(root, state, stage, None)?;
    let artifact = generate()?;
    finish_notice_pipeline_stage(root, state, stage, Some(&artifact))?;
    Ok(artifact)
}

#[allow(dead_code)]
fn run_notice_authorization_stage(
    root: &Path,
    state: &mut NoticeState,
    template: &Path,
    report_title: &str,
) -> Result<PathBuf, String> {
    run_notice_generated_stage(root, state, NoticePipelineStage::Authorization, || {
        generate_authorization_document(template, root, report_title)
    })
}

#[allow(dead_code)]
fn run_notice_rectification_stage(
    root: &Path,
    state: &mut NoticeState,
    template: &Path,
    company: &str,
    vulnerability: &str,
) -> Result<PathBuf, String> {
    run_notice_generated_stage(root, state, NoticePipelineStage::Rectification, || {
        generate_rectification_document(template, root, company, vulnerability)
    })
}

#[allow(dead_code)]
fn run_notice_disposal_stage(
    root: &Path,
    state: &mut NoticeState,
    template: &Path,
) -> Result<PathBuf, String> {
    run_notice_generated_stage(root, state, NoticePipelineStage::Disposal, || {
        generate_disposal_document(template, root)
    })
}

fn run_notice_pdf_stage_with<F>(
    root: &Path,
    state: &mut NoticeState,
    sources: &[PathBuf],
    mut convert: F,
) -> Result<Vec<PathBuf>, String>
where
    F: FnMut(&Path, &Path) -> Result<(), String>,
{
    if sources.is_empty() {
        return Err("notice PDF stage requires at least one Word artifact".to_string());
    }
    begin_notice_pipeline_stage(
        root,
        state,
        NoticePipelineStage::Pdf,
        sources.first().map(PathBuf::as_path),
    )?;
    let mut outputs = Vec::with_capacity(sources.len());
    for source in sources {
        let output = source.with_extension("pdf");
        convert(source, &output)?;
        read_pdf(&output).map_err(|error| format!("converted PDF validation failed: {error}"))?;
        record_notice_pipeline_artifact(state, NoticePipelineStage::Pdf, &output)?;
        state.updated_at = json!(now_seconds());
        save_notice_state(root, state)?;
        outputs.push(output);
    }
    finish_notice_pipeline_stage(root, state, NoticePipelineStage::Pdf, None)?;
    Ok(outputs)
}

#[allow(dead_code)]
fn run_notice_pdf_stage(
    root: &Path,
    state: &mut NoticeState,
    sources: &[PathBuf],
) -> Result<Vec<PathBuf>, String> {
    run_notice_pdf_stage_with(root, state, sources, |source, output| {
        convert_notice_word_to_pdf(source, output).map(|_| ())
    })
}

fn cleanup_notice_word_artifacts_after_pdf(
    state: &mut NoticeState,
    logs: &mut Vec<String>,
) -> Result<(), String> {
    let candidates = state
        .generated_files
        .iter()
        .map(PathBuf::from)
        .filter(|path| {
            path.extension()
                .and_then(|value| value.to_str())
                .is_some_and(|value| value.eq_ignore_ascii_case("docx"))
                && path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .is_some_and(|name| name.contains("授权委托书") || name.contains("责令整改"))
        })
        .collect::<Vec<_>>();
    for source in candidates {
        let pdf = source.with_extension("pdf");
        if !pdf.is_file() {
            continue;
        }
        read_pdf(&pdf).map_err(|error| {
            format!("拒绝清理 Word 产物 {}，PDF 无效: {error}", source.display())
        })?;
        fs::remove_file(&source)
            .map_err(|error| format!("删除已验证 PDF 对应 Word 产物失败: {error}"))?;
        logs.push(format!(
            "PDF 已验证，清理生成的 Word 产物: {}",
            source.display()
        ));
    }
    Ok(())
}

const LEGAL_COMPANY_SUFFIXES: &[&str] = &[
    "股份有限公司",
    "有限责任公司",
    "责任有限公司",
    "有限公司",
    "集团公司",
    "集团",
    "公司",
    "制造厂",
    "工厂",
];

const ORG_COMPANY_SUFFIXES: &[&str] = &[
    "研究所",
    "研究院",
    "测绘院",
    "幼儿园",
    "托儿所",
    "事务所",
    "合作社",
    "工作室",
    "委员会",
    "联合会",
    "基金会",
    "经营部",
    "便利店",
    "俱乐部",
    "会所",
    "网吧",
    "KTV",
    "中心",
    "医院",
    "学校",
    "商行",
    "农场",
    "超市",
    "饭店",
    "酒店",
    "宾馆",
    "旅馆",
    "棋牌",
    "制造厂",
    "工厂",
    "厂",
    "店",
    "局",
    "厅",
    "处",
    "署",
    "队",
    "站",
    "网",
    "吧",
];

fn is_company_trim_character(character: char) -> bool {
    character.is_whitespace()
        || matches!(
            character,
            '，' | ',' | '。' | '；' | ';' | '：' | ':' | '、' | '-' | '_' | '—' | '–'
        )
}

fn clean_company_candidate(value: &str) -> String {
    let value = value.trim();
    let value = value.trim_start_matches(|character: char| character.is_ascii_digit());
    let mut value = value.to_string();
    for prefix in ["（专项）", "(专项)", "【专项】"] {
        if let Some(rest) = value.strip_prefix(prefix) {
            value = rest.to_string();
            break;
        }
    }
    if let Some(rest) = value.strip_prefix("关于疑似") {
        value = rest.to_string();
    } else if let Some(rest) = value.strip_prefix("关于") {
        value = rest.to_string();
    }
    if let Some(rest) = value.strip_prefix("疑似") {
        value = rest.to_string();
    }
    if let Some(rest) = value
        .strip_prefix("通报：")
        .or_else(|| value.strip_prefix("通报:"))
    {
        value = rest.to_string();
    }
    value.trim_matches(is_company_trim_character).to_string()
}

fn company_from_notice_title(value: &str) -> Option<String> {
    let title = Path::new(value)
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(value);
    let title = title
        .trim()
        .trim_start_matches(|character: char| character.is_ascii_digit())
        .trim_matches(is_company_trim_character);
    if !title.starts_with("关于") || !(title.contains("通报") || title.contains("报告")) {
        return None;
    }
    let body = title
        .strip_prefix("关于疑似")
        .or_else(|| title.strip_prefix("关于"))?;
    let marker_position = [
        "所属",
        "存在",
        "远程技术检查",
        "技术检查",
        "检查",
        "发现",
        "遭受",
        "发生",
    ]
    .iter()
    .filter_map(|marker| body.find(marker))
    .min()?;
    let candidate = clean_company_candidate(&body[..marker_position]);
    (!candidate.is_empty()).then_some(candidate)
}

fn org_suffix_has_boundary(value: &str, end: usize) -> bool {
    let rest = &value[end..];
    if rest.is_empty()
        || [
            "所属",
            "存在",
            "远程技术检查",
            "技术检查",
            "检查",
            "通报",
            "报告",
            "的",
        ]
        .iter()
        .any(|marker| rest.starts_with(marker))
    {
        return true;
    }
    rest.chars().next().is_some_and(|character| {
        character.is_whitespace()
            || matches!(
                character,
                '_' | '，'
                    | ','
                    | '。'
                    | '；'
                    | ';'
                    | '：'
                    | ':'
                    | '、'
                    | '/'
                    | '\\'
                    | '.'
                    | '-'
                    | '—'
                    | '–'
                    | '（'
                    | '('
                    | '【'
                    | '['
            )
    })
}

fn company_from_text(value: &str) -> Option<String> {
    let value = clean_company_candidate(value);
    if value.is_empty() {
        return None;
    }
    let mut best: Option<(usize, String)> = None;
    for suffix in LEGAL_COMPANY_SUFFIXES {
        for (start, _) in value.match_indices(suffix) {
            let end = start + suffix.len();
            let candidate = clean_company_candidate(&value[..end]);
            if candidate.is_empty() {
                continue;
            }
            if best
                .as_ref()
                .map(|(best_end, best_value)| {
                    end > *best_end || (end == *best_end && candidate.len() > best_value.len())
                })
                .unwrap_or(true)
            {
                best = Some((end, candidate));
            }
        }
    }
    if let Some((_, candidate)) = best {
        return Some(candidate);
    }

    let mut best: Option<(usize, String)> = None;
    for suffix in ORG_COMPANY_SUFFIXES {
        for (start, _) in value.match_indices(suffix) {
            let end = start + suffix.len();
            if !org_suffix_has_boundary(&value, end) {
                continue;
            }
            let candidate = clean_company_candidate(&value[..end]);
            if !candidate.is_empty()
                && best
                    .as_ref()
                    .map(|(best_end, _)| end > *best_end)
                    .unwrap_or(true)
            {
                best = Some((end, candidate));
            }
        }
    }
    best.map(|(_, candidate)| candidate)
}

fn normalize_grouping_company(value: &str) -> Option<String> {
    if let Some(company) = company_from_notice_title(value) {
        return Some(company);
    }
    let value = clean_company_candidate(value);
    let mut segments = Vec::new();
    for marker in [
        "所属",
        "远程技术检查",
        "技术检查",
        "检查",
        "存在",
        "通报",
        "报告",
    ] {
        if let Some((prefix, _)) = value.split_once(marker) {
            if !prefix.trim().is_empty() {
                segments.push(prefix.trim().to_string());
            }
        }
    }
    segments.push(value);
    let mut seen = HashSet::new();
    for segment in segments {
        for part in segment.split(['—', '-', '–', '_']) {
            let part = part.trim();
            if !part.is_empty() && seen.insert(part.to_string()) {
                if let Some(company) = company_from_text(part) {
                    return Some(company);
                }
            }
        }
    }
    None
}

fn normalize_notice_company(value: &str) -> String {
    normalize_grouping_company(value).unwrap_or_default()
}

fn docx_company_candidates(path: &Path, root: &Path) -> Vec<String> {
    let mut candidates = Vec::new();
    if let Some(parent) = path.parent() {
        if let Ok(relative) = parent.strip_prefix(root) {
            for component in relative.components().rev() {
                let candidate = normalize_notice_company(&component.as_os_str().to_string_lossy());
                if !candidate.is_empty() && !candidates.contains(&candidate) {
                    candidates.push(candidate);
                }
            }
        }
    }
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    let from_file = normalize_notice_company(file_name);
    if !from_file.is_empty() && !candidates.contains(&from_file) {
        candidates.push(from_file);
    }
    candidates
}

fn group_for_docx(path: &Path, root: &Path, groups: &BTreeMap<String, String>) -> Option<String> {
    let candidates = docx_company_candidates(path, root);
    for candidate in &candidates {
        if let Some(group) = groups.get(candidate) {
            return Some(group.clone());
        }
    }
    // Filename normalization can leave a title suffix that differs from the
    // enterprise database spelling. Use a longest-key containment match only
    // after exact matches, avoiding short generic names such as "材料".
    groups
        .iter()
        .filter(|(key, _)| key.chars().count() >= 4)
        .filter_map(|(key, group)| {
            candidates
                .iter()
                .find(|candidate| {
                    candidate.contains(key.as_str()) || key.contains(candidate.as_str())
                })
                .map(|_| (key.chars().count(), group.clone()))
        })
        .max_by_key(|(length, _)| *length)
        .map(|(_, group)| group)
}

fn docx_path_has_rewrite_marker(path: &Path) -> bool {
    File::open(path)
        .ok()
        .and_then(|file| ZipArchive::new(file).ok())
        .and_then(|mut archive| {
            archive.by_name("docProps/core.xml").ok().map(|mut entry| {
                let mut bytes = Vec::new();
                let _ = entry
                    .by_ref()
                    .take(MAX_NOTICE_XML_BYTES as u64 + 1)
                    .read_to_end(&mut bytes);
                bytes.len() <= MAX_NOTICE_XML_BYTES && docx_has_rewrite_marker(&bytes)
            })
        })
        .unwrap_or(false)
}

fn fill_rewritten_notice_copy_to(
    root: &Path,
    groups: &BTreeMap<String, String>,
) -> Result<(usize, usize, usize, Vec<String>), String> {
    let mut updated = 0usize;
    let mut skipped_no_group = 0usize;
    let mut errors = 0usize;
    let mut logs = Vec::new();
    for path in walk_files(root)? {
        let file_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if file_name.starts_with("~$") || file_name.starts_with('.') {
            continue;
        }
        if path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("docx"))
            != Some(true)
        {
            continue;
        }
        if !docx_path_has_rewrite_marker(&path) {
            continue;
        }
        let Some(township) = group_for_docx(&path, root, groups) else {
            skipped_no_group += 1;
            continue;
        };
        match atomic_replace_docx_with_copy_to(&path, &township) {
            Ok(true) => {
                updated += 1;
                logs.push(format!("copy-to updated: {}", path.display()));
            }
            Ok(false) => {}
            Err(error) => {
                errors += 1;
                logs.push(format!("copy-to failed: {}: {error}", path.display()));
            }
        }
    }
    Ok((updated, skipped_no_group, errors, logs))
}

fn strip_company_tags(value: &str) -> String {
    let mut remaining = value;
    let mut result = String::with_capacity(value.len());
    while let Some(start) = remaining.find('{') {
        result.push_str(&remaining[..start]);
        let after_start = &remaining[start + 1..];
        if let Some(end) = after_start.find('}') {
            remaining = &after_start[end + 1..];
        } else {
            result.push_str(&remaining[start..]);
            remaining = "";
            break;
        }
    }
    result.push_str(remaining);
    result.trim().to_string()
}

fn add_company_group_values(value: Option<&Value>, companies: &mut Vec<(String, String)>) {
    let Some(Value::Array(entries)) = value else {
        return;
    };
    for entry in entries {
        let Some(values) = entry.as_array() else {
            continue;
        };
        let Some(company) = values.first().and_then(Value::as_str) else {
            continue;
        };
        let Some(group) = values.get(1).and_then(Value::as_str) else {
            continue;
        };
        let company = strip_company_tags(company);
        let group = group.trim();
        if !company.is_empty() && !group.is_empty() {
            companies.push((company, group.to_string()));
        }
    }
}

fn safe_notice_component(value: &str) -> bool {
    let path = Path::new(value);
    let mut components = path.components();
    let one_normal_component = matches!(components.next(), Some(Component::Normal(_)))
        && components.next().is_none()
        && !value.chars().any(|character| {
            character.is_control() || matches!(character, '<' | '>' | ':' | '"' | '|' | '?' | '*')
        })
        && value.trim_matches(|character| character == ' ' || character == '.') == value;
    if !one_normal_component {
        return false;
    }
    let base = value
        .split('.')
        .next()
        .unwrap_or(value)
        .to_ascii_uppercase();
    !matches!(
        base.as_str(),
        "CON"
            | "PRN"
            | "AUX"
            | "NUL"
            | "COM1"
            | "COM2"
            | "COM3"
            | "COM4"
            | "COM5"
            | "COM6"
            | "COM7"
            | "COM8"
            | "COM9"
            | "LPT1"
            | "LPT2"
            | "LPT3"
            | "LPT4"
            | "LPT5"
            | "LPT6"
            | "LPT7"
            | "LPT8"
            | "LPT9"
    )
}

fn inferred_company_groups(root: &Path) -> Result<Vec<(String, String)>, String> {
    let mut pairs = Vec::new();
    let mut root_entries = fs::read_dir(root)
        .map_err(|error| format!("无法读取分类目录: {error}"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("读取分类目录项失败: {error}"))?;
    root_entries.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
    for group_entry in root_entries {
        let group_path = group_entry.path();
        let metadata = fs::symlink_metadata(&group_path)
            .map_err(|error| format!("读取分类目录项失败: {error}"))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            continue;
        }
        let group_name = group_entry.file_name().to_string_lossy().to_string();
        if normalize_grouping_company(&group_name).is_some() {
            continue;
        }
        let mut company_entries = fs::read_dir(&group_path)
            .map_err(|error| format!("无法读取街道目录 {}: {error}", group_path.display()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| format!("读取企业目录项失败: {error}"))?;
        company_entries
            .sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
        for company_entry in company_entries {
            let metadata = fs::symlink_metadata(company_entry.path())
                .map_err(|error| format!("读取企业目录项失败: {error}"))?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                continue;
            }
            let raw_name = company_entry.file_name().to_string_lossy().to_string();
            if let Some(company) = normalize_grouping_company(&raw_name) {
                pairs.push((company, group_name.clone()));
            }
        }
    }
    Ok(pairs)
}

fn grouping_database(payload: &Value) -> Vec<(String, String)> {
    if payload
        .get("groups_source")
        .and_then(Value::as_str)
        .unwrap_or("db")
        != "db"
    {
        return Vec::new();
    }
    let mut raw = Vec::new();
    add_company_group_values(payload.get("company_group_list"), &mut raw);
    add_company_group_values(payload.get("company_groups"), &mut raw);
    add_company_group_values(payload.get("groups"), &mut raw);
    let mut normalized = Vec::new();
    for (company, group) in raw {
        let company = normalize_grouping_company(&company).unwrap_or(company);
        if !company.trim().is_empty() && !group.trim().is_empty() {
            normalized.push((company.trim().to_string(), group.trim().to_string()));
        }
    }
    normalized
}

fn clean_template_name(value: &str) -> &str {
    value.trim_start_matches(|character: char| character.is_ascii_digit())
}

fn disposal_template(payload: &Value) -> Option<PathBuf> {
    let directory = payload
        .get("_notice_templates_dir")
        .and_then(Value::as_str)
        .map(PathBuf::from)?;
    let mut candidates = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .extension()
                    .and_then(|value| value.to_str())
                    .map(|value| value.eq_ignore_ascii_case("docx"))
                    == Some(true)
                && path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .map(|value| value.contains("处置"))
                    .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|path| path.to_string_lossy().to_ascii_lowercase());
    candidates
        .iter()
        .find(|path| {
            path.file_name()
                .and_then(|value| value.to_str())
                .map(|value| value.contains("模板"))
                .unwrap_or(false)
        })
        .cloned()
        .or_else(|| candidates.into_iter().next())
}

fn ensure_disposal_template(
    company_directory: &Path,
    template: Option<&Path>,
) -> Result<bool, String> {
    let Some(template) = template else {
        return Ok(false);
    };
    let already_exists = fs::read_dir(company_directory)
        .map_err(|error| format!("无法检查处置模板: {error}"))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .any(|path| {
            path.extension()
                .and_then(|value| value.to_str())
                .map(|value| value.eq_ignore_ascii_case("docx"))
                == Some(true)
                && path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .map(|value| value.contains("处置") && value.contains("模板"))
                    .unwrap_or(false)
        });
    if already_exists {
        return Ok(false);
    }
    let target_name = template
        .file_name()
        .and_then(|value| value.to_str())
        .map(clean_template_name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "处置模板文件名无效".to_string())?;
    let target = company_directory.join(target_name);
    if target.exists() {
        return Ok(false);
    }
    fs::copy(template, &target)
        .map_err(|error| format!("复制处置模板失败 {}: {error}", target.display()))?;
    Ok(true)
}

#[derive(Debug, Default)]
struct GroupingStats {
    moved: usize,
    skipped_exist: usize,
    miss_no_company: usize,
    miss_not_found: usize,
    miss_ambiguous: usize,
    errors: usize,
    preprocessed_folders: usize,
    preprocessed_files: usize,
}

fn preprocess_loose_notice_files(
    root: &Path,
    template: Option<&Path>,
    stats: &mut GroupingStats,
    logs: &mut Vec<String>,
) -> Result<(), String> {
    logs.push("[PREPROCESS] 开始预处理松散文件...".to_string());
    let mut entries = fs::read_dir(root)
        .map_err(|error| format!("无法读取分类目录: {error}"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("读取分类目录项失败: {error}"))?;
    entries.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
    let mut skipped = 0usize;
    for entry in entries {
        let source = entry.path();
        let metadata = match fs::symlink_metadata(&source) {
            Ok(metadata) => metadata,
            Err(error) => {
                skipped += 1;
                logs.push(format!(
                    "[PREPROCESS ERROR] 无法读取 '{}': {error}",
                    source.display()
                ));
                continue;
            }
        };
        if metadata.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            skipped += 1;
            logs.push(format!("[PREPROCESS SKIP] 拒绝移动非普通文件 '{name}'"));
            continue;
        }
        let Some(company) = normalize_grouping_company(&name) else {
            skipped += 1;
            logs.push(format!("[PREPROCESS SKIP] 文件 '{name}' 无法提取公司名称"));
            continue;
        };
        if !safe_notice_component(&company) {
            skipped += 1;
            logs.push(format!(
                "[PREPROCESS SKIP] 文件 '{name}' 提取出不安全公司名称"
            ));
            continue;
        }
        let company_directory = root.join(&company);
        let mut created = false;
        if !company_directory.exists() {
            fs::create_dir(&company_directory)
                .map_err(|error| format!("创建企业目录失败 '{}': {error}", company))?;
            stats.preprocessed_folders += 1;
            created = true;
            logs.push(format!("[PREPROCESS CREATE] 创建文件夹: {company}"));
        }
        let directory_metadata = fs::symlink_metadata(&company_directory)
            .map_err(|error| format!("检查企业目录失败 '{}': {error}", company))?;
        if directory_metadata.file_type().is_symlink() || !directory_metadata.is_dir() {
            skipped += 1;
            logs.push(format!(
                "[PREPROCESS ERROR] 企业目标不是安全目录: {company}"
            ));
            continue;
        }
        let destination = company_directory.join(&name);
        if destination.exists() {
            skipped += 1;
            logs.push(format!(
                "[PREPROCESS SKIP] 文件已存在: {}",
                destination.display()
            ));
            continue;
        }
        match fs::rename(&source, &destination) {
            Ok(()) => {
                stats.preprocessed_files += 1;
                let action = if created {
                    "新建文件夹并移动"
                } else {
                    "移动"
                };
                logs.push(format!(
                    "[PREPROCESS MOVE] {action}文件 '{name}' -> {company}/"
                ));
                if ensure_disposal_template(&company_directory, template).unwrap_or(false) {
                    logs.push(format!(
                        "[PREPROCESS TEMPLATE] 已补充处置文件模板: {company}/"
                    ));
                }
            }
            Err(error) => {
                skipped += 1;
                logs.push(format!("[PREPROCESS ERROR] 移动文件失败 '{name}': {error}"));
            }
        }
    }
    logs.push(format!(
        "[PREPROCESS SUMMARY] 创建文件夹={} 移动文件={} 跳过={skipped}",
        stats.preprocessed_folders, stats.preprocessed_files
    ));
    Ok(())
}

fn choose_notice_group(
    company: &str,
    database: &[(String, String)],
    pattern: &str,
) -> Result<String, String> {
    if let Some((_, group)) = database.iter().find(|(candidate, _)| candidate == company) {
        return Ok(group.clone());
    }
    if pattern == "exact" {
        return Err("not_found".to_string());
    }
    let candidates: Vec<_> = database
        .iter()
        .filter(|(candidate, _)| company.contains(candidate) || candidate.contains(company))
        .collect();
    match candidates.as_slice() {
        [(_, group)] => Ok((*group).clone()),
        [] => Err("not_found".to_string()),
        values => Err(format!(
            "ambiguous:{}",
            values
                .iter()
                .map(|(company, _)| company.as_str())
                .collect::<Vec<_>>()
                .join("|")
        )),
    }
}

fn collect_company_groups(root: &Path) -> Result<Vec<(String, String)>, String> {
    inferred_company_groups(root)
}

fn unclassified_companies(root: &Path) -> Result<Vec<String>, String> {
    let mut values = Vec::new();
    for entry in fs::read_dir(root).map_err(|error| format!("无法读取分类目录: {error}"))? {
        let entry = entry.map_err(|error| format!("读取分类目录项失败: {error}"))?;
        let metadata = fs::symlink_metadata(entry.path())
            .map_err(|error| format!("读取分类目录项失败: {error}"))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            continue;
        }
        if let Some(company) = normalize_grouping_company(&entry.file_name().to_string_lossy()) {
            values.push(company);
        }
    }
    values.sort();
    Ok(values)
}

fn run_notice_grouping(root: &Path, payload: &Value) -> Result<Value, String> {
    let template = disposal_template(payload);
    let mut stats = GroupingStats::default();
    let database_source = payload
        .get("groups_source")
        .and_then(Value::as_str)
        .unwrap_or("db")
        == "db";
    let mut logs = vec![format!("[INFO] source-dir: {}", root.display())];
    logs.push(if database_source {
        "[INFO] groups-source: database".to_string()
    } else {
        "[INFO] groups-file: None".to_string()
    });
    preprocess_loose_notice_files(root, template.as_deref(), &mut stats, &mut logs)?;
    let database = grouping_database(payload);
    if database.is_empty() {
        stats.errors += 1;
        logs.push(if database_source {
            "[ERROR] groups-source database is empty".to_string()
        } else {
            "[ERROR] --groups-file not found: None".to_string()
        });
        return Ok(json!({
            "moved": stats.moved,
            "skipped_exist": stats.skipped_exist,
            "miss_no_company": stats.miss_no_company,
            "miss_not_found": stats.miss_not_found,
            "miss_ambiguous": stats.miss_ambiguous,
            "errors": stats.errors,
            "log": logs,
            "preprocessed_folders": stats.preprocessed_folders,
            "preprocessed_files": stats.preprocessed_files,
        }));
    } else {
        let entries_mode = payload
            .get("entries")
            .and_then(Value::as_str)
            .unwrap_or("both");
        let pattern = payload
            .get("pattern")
            .and_then(Value::as_str)
            .unwrap_or("exact");
        let mut entries = fs::read_dir(root)
            .map_err(|error| format!("无法读取分类目录: {error}"))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| format!("读取分类目录项失败: {error}"))?;
        entries.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
        entries.retain(|entry| {
            fs::symlink_metadata(entry.path())
                .map(|metadata| {
                    (entries_mode != "dirs" || metadata.is_dir())
                        && (entries_mode != "files" || !metadata.is_dir())
                })
                .unwrap_or(true)
        });
        let group_count = database
            .iter()
            .map(|(_, group)| group)
            .collect::<BTreeSet<_>>()
            .len();
        logs.push(format!(
            "[INFO] detected {} items in source ({entries_mode})",
            entries.len()
        ));
        logs.push(format!("[INFO] parsed {group_count} groups"));
        for entry in entries {
            let source = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();
            let metadata = match fs::symlink_metadata(&source) {
                Ok(metadata) => metadata,
                Err(error) => {
                    stats.errors += 1;
                    logs.push(format!("[WARN] 无法读取 '{name}': {error}"));
                    continue;
                }
            };
            if metadata.file_type().is_symlink() {
                stats.errors += 1;
                logs.push(format!("[WARN] 拒绝分类符号链接: {}", source.display()));
                continue;
            }
            let Some(company) = normalize_grouping_company(&name) else {
                stats.miss_no_company += 1;
                logs.push(format!("[MISS] entry '{name}' -> no_company_extracted"));
                continue;
            };
            let group = match choose_notice_group(&company, &database, pattern) {
                Ok(group) => group,
                Err(reason) => {
                    if reason == "not_found" {
                        stats.miss_not_found += 1;
                    } else if reason.starts_with("ambiguous:") {
                        stats.miss_ambiguous += 1;
                    } else {
                        stats.errors += 1;
                    }
                    logs.push(format!("[MISS] entry '{name}' ({company}) -> {reason}"));
                    if metadata.is_dir() {
                        let _ = ensure_disposal_template(&source, template.as_deref());
                    }
                    continue;
                }
            };
            if !safe_notice_component(&group) {
                stats.errors += 1;
                logs.push(format!("[ERROR] unsafe group path for '{name}': {group}"));
                continue;
            }
            let group_directory = root.join(&group);
            if !group_directory.exists() {
                fs::create_dir(&group_directory)
                    .map_err(|error| format!("创建街道目录失败 '{group}': {error}"))?;
            }
            let group_metadata = fs::symlink_metadata(&group_directory)
                .map_err(|error| format!("检查街道目录失败 '{group}': {error}"))?;
            if group_metadata.file_type().is_symlink() || !group_metadata.is_dir() {
                stats.errors += 1;
                logs.push(format!("[ERROR] 街道目标不是安全目录: {group}"));
                continue;
            }
            let destination = group_directory.join(&name);
            if destination.exists() {
                stats.skipped_exist += 1;
                logs.push(format!(
                    "[SKIP] already exists in group: {}",
                    destination.display()
                ));
                continue;
            }
            match fs::rename(&source, &destination) {
                Ok(()) => {
                    stats.moved += 1;
                    logs.push(format!(
                        "[MOVE] {} -> {}",
                        source.display(),
                        destination.display()
                    ));
                    if metadata.is_dir() {
                        let _ = ensure_disposal_template(&destination, template.as_deref());
                    }
                }
                Err(error) => {
                    stats.errors += 1;
                    logs.push(format!("[WARN] move failed {}: {error}", source.display()));
                }
            }
        }
    }

    logs.push(format!(
        "[SUMMARY] moved={} skipped_exist={} miss_no_company={} miss_not_found={} miss_ambiguous={} errors={}",
        stats.moved,
        stats.skipped_exist,
        stats.miss_no_company,
        stats.miss_not_found,
        stats.miss_ambiguous,
        stats.errors
    ));
    let company_groups = collect_company_groups(root)?;
    let unclassified = unclassified_companies(root)?;
    Ok(json!({
        "moved": stats.moved,
        "skipped_exist": stats.skipped_exist,
        "miss_no_company": stats.miss_no_company,
        "miss_not_found": stats.miss_not_found,
        "miss_ambiguous": stats.miss_ambiguous,
        "errors": stats.errors,
        "log": logs,
        "preprocessed_folders": stats.preprocessed_folders,
        "preprocessed_files": stats.preprocessed_files,
        "company_group_list": company_groups.into_iter().map(|(company, group)| json!([company, group])).collect::<Vec<_>>(),
        "all_classified": unclassified.is_empty(),
        "unclassified": unclassified,
    }))
}

fn notice_classify(payload: &Value) -> Result<Value, String> {
    let requested = required_string(payload, "target_path")?;
    let root = canonical_dir(Path::new(&requested))?;
    if let Some(existing) = target_conflict(&root, None) {
        return Ok(json!({
            "success": false,
            "message": "该目标仍有通报处理任务在运行，暂不能执行分类",
            "error_code": "notice_task_active",
            "task_id": existing.task_id,
            "running": true,
            "done": false,
            "logs": []
        }));
    }
    let mut result = run_notice_grouping(&root, payload)?;
    let groups = result
        .get("company_group_list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut normalized_groups = BTreeMap::new();
    for item in &groups {
        let Some(values) = item.as_array() else {
            continue;
        };
        let Some(company) = values.first().and_then(Value::as_str) else {
            continue;
        };
        let Some(group) = values.get(1).and_then(Value::as_str) else {
            continue;
        };
        let key = normalize_notice_company(company);
        if !key.is_empty() {
            normalized_groups.insert(key, group.to_string());
        }
    }
    let (copy_to_updated, copy_to_skipped_no_group, copy_to_errors, mut copy_logs) =
        fill_rewritten_notice_copy_to(&root, &normalized_groups)?;
    let mut logs = result
        .get("log")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(ToOwned::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    logs.append(&mut copy_logs);
    if copy_to_updated > 0 {
        logs.push(format!(
            "copy-to backfill updated {copy_to_updated} document(s)"
        ));
    }
    if copy_to_skipped_no_group > 0 {
        logs.push(format!(
            "copy-to backfill skipped {copy_to_skipped_no_group} rewritten document(s) without a group"
        ));
    }
    result["copy_to_updated"] = json!(copy_to_updated);
    result["copy_to_skipped_no_group"] = json!(copy_to_skipped_no_group);
    result["copy_to_errors"] = json!(copy_to_errors);
    let grouping_errors = result.get("errors").and_then(Value::as_u64).unwrap_or(0);
    let moved = result.get("moved").and_then(Value::as_u64).unwrap_or(0);
    let skipped = result
        .get("skipped_exist")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let mut message =
        format!("分类完成：移动 {moved} 个，跳过 {skipped} 个，错误 {grouping_errors} 个");
    if copy_to_updated > 0 {
        message.push_str(&format!("，补写抄送 {copy_to_updated} 个"));
    }
    if copy_to_errors > 0 {
        message.push_str(&format!("，抄送补写错误 {copy_to_errors} 个"));
    }
    Ok(json!({
        "success": grouping_errors == 0 && copy_to_errors == 0,
        "message": message,
        "logs": logs,
        "result": result,
    }))
}

fn notice_name_candidate(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    ["授权委托书", "责令整改", "关于", "通报", "通知"]
        .iter()
        .any(|keyword| name.contains(keyword))
}

fn path_under(root: &Path, path: &Path) -> Result<PathBuf, String> {
    let candidate = if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    };
    let canonical =
        fs::canonicalize(&candidate).map_err(|error| format!("文件路径不存在: {error}"))?;
    if !canonical.starts_with(root) {
        return Err("文件路径必须位于目标目录内".to_string());
    }
    Ok(canonical)
}

fn convert_notice_word_to_pdf(source: &Path, output: &Path) -> Result<PdfInfo, String> {
    let response = document_conversion::dispatch(
        "doc.convert.run",
        &json!({
            "conversion_type": "word_to_pdf",
            "input_path": source,
            "recursive": false,
            "overwrite": true,
            "skip_template": false,
        }),
    )?;
    if response.get("success").and_then(Value::as_bool) != Some(true) {
        let reason = response
            .get("failures")
            .and_then(Value::as_array)
            .and_then(|items| items.first())
            .and_then(|item| item.get("reason"))
            .and_then(Value::as_str)
            .or_else(|| response.get("message").and_then(Value::as_str))
            .unwrap_or("Rust Word to PDF conversion failed");
        return Err(reason.to_string());
    }
    read_pdf(output).map_err(|error| format!("converted PDF validation failed: {error}"))
}

fn notice_convert_failed_pdf(payload: &Value) -> Result<Value, String> {
    let requested = required_string(payload, "target_path")?;
    let root = canonical_dir(Path::new(&requested))?;
    if let Some(existing) = target_conflict(&root, None) {
        return Ok(json!({
            "success": false,
            "message": "该目标仍有通报处理任务在运行，暂不能转换PDF",
            "error_code": "notice_task_active",
            "task_id": existing.task_id,
            "running": true,
            "done": false,
            "logs": []
        }));
    }
    let explicit = payload.get("failed_files");
    if explicit.is_some() && !explicit.unwrap().is_array() {
        return Ok(json!({
            "success": false,
            "message": "失败文件列表格式无效",
            "error_code": "invalid_failed_files",
            "logs": []
        }));
    }
    let mut candidates = Vec::new();
    if let Some(items) = explicit.and_then(Value::as_array) {
        for item in items {
            let object = item
                .as_object()
                .ok_or_else(|| "失败文件列表格式无效".to_string())?;
            let source = object
                .get("output_file")
                .or_else(|| object.get("file"))
                .and_then(Value::as_str)
                .ok_or_else(|| "失败文件缺少路径".to_string())?;
            candidates.push(path_under(&root, Path::new(source))?);
        }
    } else if payload
        .get("scan_target")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        for file in walk_files(&root)? {
            if notice_file_kind(&file) == Some("word") && notice_name_candidate(&file) {
                candidates.push(file);
            }
        }
    }
    candidates.sort();
    candidates.dedup();
    if candidates.is_empty() {
        return Ok(json!({"success": false, "message": "未找到可转换的 Word 文档", "logs": []}));
    }
    let mut output_files = Vec::new();
    let mut deleted_files = Vec::new();
    let mut failures = Vec::new();
    let mut skipped = 0;
    let mut logs = Vec::new();
    for source in candidates {
        let output = source.with_extension("pdf");
        match read_pdf(&output) {
            Ok(info) => {
                if fs::remove_file(&source).is_ok() {
                    output_files.push(info.path.to_string_lossy().to_string());
                    deleted_files.push(source.to_string_lossy().to_string());
                    logs.push(format!(
                        "PDF 产物已验证，已删除原 Word 文件: {}",
                        source.display()
                    ));
                } else {
                    failures.push(json!({
                        "file": source,
                        "reason": "PDF 已生成但删除原 Word 文件失败"
                    }));
                }
            }
            Err(_) => {
                if let Ok(info) = convert_notice_word_to_pdf(&source, &output) {
                    if fs::remove_file(&source).is_ok() {
                        output_files.push(info.path.to_string_lossy().to_string());
                        deleted_files.push(source.to_string_lossy().to_string());
                        logs.push(format!(
                            "Word converted by Rust and PDF verified; source removed: {}",
                            source.display()
                        ));
                        continue;
                    }
                    failures.push(json!({
                        "file": source,
                        "reason": "PDF was converted and verified, but the source Word file could not be removed"
                    }));
                    continue;
                }
                skipped += 1;
                failures.push(json!({
                    "file": source,
                    "reason": "Rust Word 转 PDF 转换器不可用；未删除原文件"
                }));
            }
        }
    }
    Ok(json!({
        "success": failures.is_empty() && !output_files.is_empty(),
        "message": format!(
            "转换完成：成功 {}，跳过 {}，失败 {}，删除原 Word {} 个",
            output_files.len(),
            skipped,
            failures.len(),
            deleted_files.len()
        ),
        "converted": output_files.len(),
        "skipped": skipped,
        "failures": failures,
        "output_files": output_files,
        "deleted_files": deleted_files,
        "logs": logs,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use lopdf::content::{Content, Operation};
    use lopdf::{dictionary, Stream};
    use serde_json::json;
    use std::process::Command;

    fn python_oracle_fixture() -> Value {
        let source = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/fixtures/python_oracle/pdf_notice.v1.json"
        ));
        let fixture: Value = serde_json::from_str(source).expect("parse PDF/notice oracle fixture");
        assert_eq!(fixture["format"], "koi-python-oracle-golden-v1");
        for forbidden in ["C:\\Users", "cookie", "api_key", "secret", "token="] {
            assert!(
                !source
                    .to_ascii_lowercase()
                    .contains(&forbidden.to_ascii_lowercase()),
                "PDF/notice oracle contains forbidden host or secret marker {forbidden}"
            );
        }
        fixture
    }

    fn temp_dir(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock is after unix epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "koi-pdf-notice-{label}-{}-{}-{nonce}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    fn write_docx_fixture(path: &Path, marker: bool, copy_to: &str) {
        let core_description = if marker {
            REWRITTEN_NOTICE_MARKER
        } else {
            "ordinary.document"
        };
        let document_xml = format!(
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>抄送</w:t></w:r><w:r><w:t>：</w:t></w:r></w:p>
    <w:p><w:r><w:t>抄送：{copy_to}</w:t></w:r></w:p>
    <w:p><w:r><w:t>ordinary body</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>"#
        );
        let entries: Vec<(String, Vec<u8>)> = vec![
            (
                "[Content_Types].xml".to_string(),
                r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>"#.as_bytes().to_vec(),
            ),
            (
                "_rels/.rels".to_string(),
                r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>"#.as_bytes().to_vec(),
            ),
            (
                "docProps/core.xml".to_string(),
                format!(
                    r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>{core_description}</dc:description></cp:coreProperties>"#
                )
                .into_bytes(),
            ),
            ("word/document.xml".to_string(), document_xml.into_bytes()),
            (
                "word/customXml/opaque.bin".to_string(),
                b"opaque-part-v1".to_vec(),
            ),
        ];
        let output = File::create(path).expect("create DOCX fixture");
        let mut writer = ZipWriter::new(output);
        for (name, content) in entries {
            writer
                .start_file(
                    name,
                    SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
                )
                .expect("start DOCX fixture part");
            writer.write_all(&content).expect("write DOCX fixture part");
        }
        writer.finish().expect("finish DOCX fixture");
    }

    fn zip_fixture_bytes(entries: Vec<(&str, Vec<u8>)>) -> Vec<u8> {
        let output = Cursor::new(Vec::new());
        let mut writer = ZipWriter::new(output);
        for (name, bytes) in entries {
            writer
                .start_file(
                    name,
                    SimpleFileOptions::default().compression_method(CompressionMethod::Deflated),
                )
                .expect("start ZIP fixture entry");
            writer.write_all(&bytes).expect("write ZIP fixture entry");
        }
        writer.finish().expect("finish ZIP fixture").into_inner()
    }

    fn write_zip_fixture(path: &Path, entries: Vec<(&str, Vec<u8>)>) {
        fs::write(path, zip_fixture_bytes(entries)).expect("write ZIP fixture");
    }

    fn write_7z_fixture(path: &Path, entries: &[(&str, &[u8])]) {
        let source = temp_dir("7z-source");
        for (relative, bytes) in entries {
            let target = source.join(relative);
            fs::create_dir_all(target.parent().expect("fixture parent")).unwrap();
            fs::write(target, bytes).unwrap();
        }
        let runtime = archive_runtime::discover_verified_runtime()
            .expect("verified archive runtime for fixture");
        let wildcard = source.join("*").to_string_lossy().to_string();
        let status = Command::new(runtime.executable())
            .args([
                "a",
                "-t7z",
                "-y",
                "-bd",
                "-bb0",
                &path.to_string_lossy(),
                &wildcard,
            ])
            .current_dir(runtime.root())
            .status()
            .expect("create 7z fixture");
        assert!(status.success());
        let _ = fs::remove_dir_all(source);
    }

    fn rename_7z_member(path: &Path, old: &str, new: &str) {
        let runtime = archive_runtime::discover_verified_runtime()
            .expect("verified archive runtime for fixture rename");
        let status = Command::new(runtime.executable())
            .args(["rn", "-y", "-bd", "-bb0", &path.to_string_lossy(), old, new])
            .current_dir(runtime.root())
            .status()
            .expect("rename 7z fixture member");
        assert!(status.success());
    }

    fn rar4_safe_fixture() -> Vec<u8> {
        let original = base64::engine::general_purpose::STANDARD
            .decode(RAR4_WITH_SYMLINK)
            .expect("decode RAR4 fixture");
        // The non-solid link record occupies [90, 148): a 50-byte file
        // header followed by the 8-byte target `test.txt`. Removing that
        // complete record leaves a valid RAR with the regular entries intact.
        let mut safe = Vec::with_capacity(original.len() - 58);
        safe.extend_from_slice(&original[..90]);
        safe.extend_from_slice(&original[148..]);
        safe
    }

    fn write_rar_fixture(path: &Path, base64_bytes: &str) {
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(base64_bytes)
            .expect("decode reviewed RAR fixture");
        fs::write(path, bytes).expect("write RAR fixture");
    }

    // libarchive test_read_format_rar5_multiple_files.rar, BSD-2-Clause.
    // Source: https://github.com/libarchive/libarchive/tree/master/libarchive/test
    const RAR5_MULTIPLE_FILES: &str = concat!(
        "UmFyIRoHAQDz4YLrCwEFBwAGAQGAgIAAAxaewicCAwvkAgSAIKSDAsayE36ABQEJdGVzdDEuYmluCgMTZ1+sWxpanhDK8WABEGRU",
        "Zy9XBW9SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSST9/exzM7d9roun2pLrrtxu75nR5vOfJ8",
        "YzMM6cw1zOeZ5pz4n6gAgAgBsMPHTht6efl4+Hf3dvZ19XT0c/Ny8nHxcPBv727ube1s7Gvraupp6WjoZ+dm5mXlZORj42LiYeFg",
        "4F/fXt5d3VzcW9ta2lnZWNhX11bWVdVU1FPTUtJR0VDQT89Ozk3NTMxLy0rKSclIyEfHRsZFxUTEQ8NCwkHBQMA/vz6+Pb1/fd9j",
        "3RS4Ut32cUKAz8MALZ0RvEaAh0IWsCwHCJ27S08IfnZoBZgBbOiN0jQEOhC1gWA4RO3KWnhD85NALMALZ0RuEaAh0IWsCwHCJ23S",
        "08Ifm5oBZgBbOiNsjQEOhC1gWA4RNY/fRX5jVV99hK+m/FfMOU1zVNOtTQp+JH/+gE59beQnAgML5AIEgCCkgwLLr2bxgAUBCXRl",
        "c3QyLmJpbgoDE3pfrFstVHMXyfJgARBkVGcvVwVvUkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk",
        "kk/f3sczO3fa6Lp9qS667cbu+Z0ebznyfGMzDOnMNcznmeac+J+oAIAIAamHjpw29PPy8fDv7u3s6+rp6Ofm5eTj4uHg397d3Nva",
        "2djX1tXU09LR0M/OzczLysnIx8bFxMPCwcC/vr28u7q5uLe2tbSzsrGwr66trKuqqainpqWko6KhoJ+enZybmpmYl5aVlJOSkZCP",
        "jo2Mi4qJiIeGhYSDgoGAf359fHt6/vu+x7opcKW77OKFAZ+GAFs6I3iNAQ6ELWBYDhE7dpaeEPzs0AswAtnRG6RoCHQhawLAcInb",
        "lLTwh+cmgFmAFs6I3CNAQ6ELWBYDhE7bpaeEPzc0AswAtnRG2RoCHQhawLAcImsfvor8xqq++wlfTfivmHKa5qmnWpoU/Ej//QBz",
        "ewC3JwIDC/ACBIAgpIMC2SOxn4AFAQl0ZXN0My5iaW4KAxN+X6xb0D0AA8n+bAEQdFVGL3V9SSSSSSSSSSSSSSSSSSSSSSSSSSSS",
        "SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSTft+37exzmeOm72vC8dqS869czmZ3PDO85/T4xmYZ45nWHO5+/cOfyfqACACAGwowus",
        "r6efl4+Hf3dvZ19XT0c/Ny8nHxcPBv727ube1s7Gvraupp6WjoZ+dm5mXlZORj42LiYeFg4F/fXt5d3VzcW9ta2lnZWNhX11bWVd",
        "VU1FPTUtJR0VDQT89Ozk3NTMxLy0rKSclIyEfHRsZFxUTEQ8NCwkHBQMA/vz6+Pb1/fe9T3BDfxDZezEGDqbCAmk4E2CZVg0wTbk",
        "wnjSZYUu3hEoeDTwA6GICaTgTXJlVzQ8abkANpMsKXbsiUPBp2AdDEBNJwJrEyqxoeNNyAG0mWFLt0RKHg06AOhiAmk4E1SZVU0P",
        "Gm5ADaTLCl9T98EfmOVH32kj6b8R8xchzrUOPWhwafio//wAM0zNwCcCAwvwAgSAIKSDAtQ+xBCABQEJdGVzdDQuYmluCgMTgV+s",
        "W6EmHRLK/WwBEHRVRi91f5JJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJJN+37d3sc5njpu9rwv",
        "HakvOvXM5mdzwzvOf0+MZmGeOZ1hzufv3Dn8n6gAgAgBrumFlVPTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dD",
        "Pzs3My8rJyMfGxcTDwsHAv769vLu6ubi3trW0s7KxsK+urayrqqmop6alpKOioaCfnp2cm5qZmJeWlZSTkpGQj46NjIuKiYiHhoW",
        "Eg4KBgH9+fXx7ev773uvcEN/ENl7MQYOpsICaTgTYJlWDTBNuTCeNJlhS7XIlDwaXAOhiAmk4E1iZVY0PGm5ADaTLCl28IlDwaeA",
        "HQxATScCapMqqaHjTcgBtJlhS7dkSh4NOwDoYgJpOBNQmVUNDxpuQA2kywpfdfvgj8xyo++0kfTfiPmLkOdahx60ODT8VH/+AB13",
        "VlEDBQQA",
    );

    // libarchive test_read_format_rar.rar. It intentionally contains a Unix
    // symlink so the extractor can prove that no preceding member is written.
    const RAR4_WITH_SYMLINK: &str = "UmFyIRoHAM+QcwAADQAAAAAAAACEUnQgkDIAFAAAABQAAAADQqLIvrd22j4UMAgApIEAAHRlc3QudHh0gAi3dto+t3baPnRlc3QgdGV4dCBkb2N1bWVudA0KnS90IJAyAAgAAAAIAAAAA3tEybbRTNg+FDAIAP+hAAB0ZXN0bGlua8AI0UzYPlBf2j50ZXN0LnR4dM3gdCCQOgAUAAAAFAAAAANCosi+Y3faPhQwEACkgQAAdGVzdGRpclx0ZXN0LnR4dMDMY3faPmN32j50ZXN0IHRleHQgZG9jdW1lbnQNCqHIdOCQMQAAAAAAAAAAAAMAAAAAY3faPhQwBwDtQQAAdGVzdGRpcsDMY3faPmR32j7m53TgkDYAAAAAAAAAAAADAAAAAJ2r1T4UMAwA7UEAAHRlc3RlbXB0eWRpcoDMnavVPsVd2j7EPXsAQAcA";

    fn docx_first_copy_to(path: &Path) -> String {
        let file = File::open(path).expect("open DOCX fixture");
        let mut archive = ZipArchive::new(file).expect("read DOCX fixture");
        let mut document = String::new();
        archive
            .by_name("word/document.xml")
            .expect("document part")
            .read_to_string(&mut document)
            .expect("decode document part");
        let start = document.find("<w:t>").expect("first text");
        let end = document[start + 5..]
            .find("</w:t>")
            .expect("first text end");
        document[start + 5..start + 5 + end].to_string()
    }

    fn docx_document_xml(path: &Path) -> String {
        let file = File::open(path).expect("open DOCX fixture");
        let mut archive = ZipArchive::new(file).expect("read DOCX fixture");
        let mut document = String::new();
        archive
            .by_name("word/document.xml")
            .expect("document part")
            .read_to_string(&mut document)
            .expect("decode document part");
        document
    }

    #[test]
    fn classify_backfills_marked_docx_only_and_preserves_opaque_parts() {
        let root = temp_dir("notice-copy-to");
        let group = "中河街道";
        let company = "上海万科物业服务有限公司宁波分公司";
        let company_dir = root.join(group).join(company);
        fs::create_dir_all(&company_dir).unwrap();
        let rewritten = company_dir.join(format!("关于{company}存在漏洞的通报.docx"));
        let ordinary = company_dir.join("ordinary.docx");
        write_docx_fixture(&rewritten, true, "");
        write_docx_fixture(&ordinary, false, "");

        let result = notice_classify(&json!({
            "target_path": &root,
            "company_group_list": [[company, group]],
        }))
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["result"]["copy_to_updated"], 1);
        assert_eq!(result["result"]["copy_to_errors"], 0);
        assert_eq!(docx_first_copy_to(&rewritten), "抄送：中河街道");
        assert_eq!(docx_first_copy_to(&ordinary), "抄送");

        let file = File::open(&rewritten).unwrap();
        let mut archive = ZipArchive::new(file).unwrap();
        let mut opaque = Vec::new();
        archive
            .by_name("word/customXml/opaque.bin")
            .unwrap()
            .read_to_end(&mut opaque)
            .unwrap();
        assert_eq!(opaque, b"opaque-part-v1");

        let second = notice_classify(&json!({
            "target_path": &root,
            "company_group_list": [[company, group]],
        }))
        .unwrap();
        assert_eq!(second["result"]["copy_to_updated"], 0);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn classify_uses_explicit_company_group_for_generic_filenames() {
        let root = temp_dir("notice-copy-to-explicit-map");
        let company = "上海万科物业服务有限公司宁波分公司";
        let company_dir = root.join(company);
        fs::create_dir_all(&company_dir).unwrap();
        let rewritten = company_dir.join("rewritten.docx");
        write_docx_fixture(&rewritten, true, "");
        let result = notice_classify(&json!({
            "target_path": &root,
            "company_group_list": [[company, "中河街道"]],
        }))
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["result"]["moved"], 1);
        assert_eq!(result["result"]["copy_to_updated"], 1);
        let classified = root.join("中河街道").join(company).join("rewritten.docx");
        assert!(!rewritten.exists());
        assert_eq!(docx_first_copy_to(&classified), "抄送：中河街道");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_company_normalization_matches_redacted_python_golden() {
        let fixture = python_oracle_fixture();
        let values = json!([
            "001关于宁波测试有限公司所属系统存在未授权访问漏洞的通报.docx",
            "关于疑似宁波第二有限责任公司发现风险的报告.pdf",
            "通报：宁波第三股份有限公司-弱口令.docx",
            "（专项）宁波某研究院技术检查报告.docx",
            "宁波某医院（联系不上）",
            "宁波某中心材料",
            "中河街道",
            "关于某无后缀单位发生安全事件的通报.docx",
            "宁波甲有限公司_宁波乙有限公司_报告.docx",
            "123宁波测试制造厂存在漏洞.pdf"
        ]);
        let rust = Value::Array(
            values
                .as_array()
                .unwrap()
                .iter()
                .map(|value| {
                    normalize_grouping_company(value.as_str().unwrap())
                        .map(Value::String)
                        .unwrap_or(Value::Null)
                })
                .collect(),
        );
        assert_eq!(rust, fixture["company_normalization"]);
    }

    #[test]
    fn loose_classification_matches_redacted_python_golden_side_effects() {
        let fixture = python_oracle_fixture();
        let root = temp_dir("notice-loose-classification-diff");
        let rust_root = root.join("rust");
        let groups = json!([
            ["宁波测试有限公司", "中河街道"],
            ["宁波第二有限责任公司", "首南街道"],
            ["宁波碰撞有限公司", "中河街道"]
        ]);
        let target = &rust_root;
        fs::create_dir_all(target).unwrap();
        fs::write(
            target.join("001关于宁波测试有限公司所属系统存在漏洞的通报.pdf"),
            b"loose-notice",
        )
        .unwrap();
        let second = target.join("宁波第二有限责任公司");
        fs::create_dir_all(&second).unwrap();
        fs::write(second.join("evidence.bin"), b"second-company").unwrap();
        let collision = target.join("宁波碰撞有限公司");
        fs::create_dir_all(&collision).unwrap();
        fs::write(collision.join("source.txt"), b"source-copy").unwrap();
        let existing = target.join("中河街道").join("宁波碰撞有限公司");
        fs::create_dir_all(&existing).unwrap();
        fs::write(existing.join("existing.txt"), b"existing-copy").unwrap();
        fs::write(target.join("说明.txt"), b"unclassified").unwrap();

        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("workspace root")
            .to_path_buf();
        let rust = notice_classify(&json!({
            "target_path": &rust_root,
            "company_group_list": &groups,
            "_notice_templates_dir": workspace.join("Report_Template"),
        }))
        .unwrap();
        assert_eq!(rust["success"], fixture["classification"]["success"]);
        let summary = json!({
            "moved": rust["result"]["moved"],
            "skipped_exist": rust["result"]["skipped_exist"],
            "miss_no_company": rust["result"]["miss_no_company"],
            "miss_not_found": rust["result"]["miss_not_found"],
            "miss_ambiguous": rust["result"]["miss_ambiguous"],
            "errors": rust["result"]["errors"],
            "preprocessed_folders": rust["result"]["preprocessed_folders"],
            "preprocessed_files": rust["result"]["preprocessed_files"],
            "all_classified": rust["result"]["all_classified"],
            "copy_to_updated": rust["result"]["copy_to_updated"],
            "copy_to_skipped_no_group": rust["result"]["copy_to_skipped_no_group"],
            "copy_to_errors": rust["result"]["copy_to_errors"],
        });
        assert_eq!(summary, fixture["classification"]["summary"]);
        assert_eq!(
            json!(tree_fingerprint(&rust_root)),
            fixture["classification"]["tree_fingerprint"],
            "classification filesystem side effects differ from golden capture"
        );
        assert!(rust_root
            .join("中河街道")
            .join("宁波测试有限公司")
            .join("001关于宁波测试有限公司所属系统存在漏洞的通报.pdf")
            .is_file());
        assert!(rust_root.join("宁波碰撞有限公司/source.txt").is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn classify_rejects_unsafe_group_path_and_preserves_source_inside_root() {
        let root = temp_dir("notice-unsafe-group");
        let source = root.join("关于宁波测试有限公司存在漏洞的通报.pdf");
        fs::write(&source, b"notice").unwrap();
        let escaped = root.parent().unwrap().join(format!(
            "koi-escaped-group-{}",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let unsafe_group = format!("../{}", escaped.file_name().unwrap().to_string_lossy());
        let result = notice_classify(&json!({
            "target_path": &root,
            "company_group_list": [["宁波测试有限公司", unsafe_group]],
        }))
        .unwrap();
        assert_eq!(result["success"], false);
        assert_eq!(result["result"]["errors"], 1);
        assert!(root
            .join("宁波测试有限公司")
            .join(source.file_name().unwrap())
            .is_file());
        assert!(!escaped.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rewrite_marker_requires_core_description_token() {
        assert!(docx_has_rewrite_marker(
            br#"<cp:coreProperties xmlns:cp="x"><dc:description xmlns:dc="y">legacy;koi.notice.rewritten.v1</dc:description></cp:coreProperties>"#
        ));
        assert!(!docx_has_rewrite_marker(
            br#"<cp:coreProperties xmlns:cp="x"><cp:keywords>koi.notice.rewritten.v1</cp:keywords></cp:coreProperties>"#
        ));
        assert!(!docx_has_rewrite_marker(
            br#"<cp:coreProperties xmlns:cp="x"><description>koi.notice.rewritten.v1</description></cp:coreProperties>"#
        ));
        assert!(!docx_has_rewrite_marker(
            br#"<cp:coreProperties xmlns:cp="x"><dc:description xmlns:dc="y">koi.notice.rewritten.v1-extra</dc:description></cp:coreProperties>"#
        ));
        assert!(is_blank_copy_to_text("抄送 ：   "));
        assert!(is_blank_copy_to_text("抄送: \t"));
        assert!(!is_blank_copy_to_text("抄送：原街道"));
    }

    #[test]
    fn classify_copy_to_matches_redacted_python_golden() {
        let fixture = python_oracle_fixture();
        let root = temp_dir("notice-copy-to-diff");
        let rust_root = root.join("rust");
        let group = "中河街道";
        let company = "上海万科物业服务有限公司宁波分公司";
        let company_dir = rust_root.join(group).join(company);
        fs::create_dir_all(&company_dir).unwrap();
        write_docx_fixture(
            &company_dir.join(format!("关于{company}存在漏洞的通报.docx")),
            true,
            "",
        );
        write_docx_fixture(&company_dir.join("ordinary.docx"), false, "");

        let rust = notice_classify(&json!({
            "target_path": &rust_root,
            "company_group_list": [[company, group]],
        }))
        .unwrap();
        for (key, golden_key) in [
            ("copy_to_updated", "updated"),
            ("copy_to_skipped_no_group", "skipped_no_group"),
            ("copy_to_errors", "errors"),
        ] {
            assert_eq!(
                rust["result"][key], fixture["copy_to"][golden_key],
                "notice classify golden mismatch for {key}"
            );
        }
        let rewritten = rust_root
            .join(group)
            .join(company)
            .join(format!("关于{company}存在漏洞的通报.docx"));
        assert_eq!(
            docx_first_copy_to(&rewritten),
            fixture["copy_to"]["rewritten_text"].as_str().unwrap()
        );
        assert_eq!(
            docx_first_copy_to(&rust_root.join(group).join(company).join("ordinary.docx")),
            fixture["copy_to"]["ordinary_text"].as_str().unwrap()
        );
        let _ = fs::remove_dir_all(root);
    }

    fn fixture_pdf(path: &Path, pages: usize) {
        let dimensions = (0..pages)
            .map(|_| PageInfo {
                width: Some(300.0),
                height: Some(400.0),
            })
            .collect::<Vec<_>>();
        fs::write(path, make_blank_pdf(&dimensions)).unwrap();
    }

    fn fixture_text_pdf(path: &Path, texts: &[&str]) {
        fixture_text_pdf_with_shared_resource(path, texts, None);
    }

    fn fixture_text_pdf_with_shared_resource(
        path: &Path,
        texts: &[&str],
        shared_name: Option<&str>,
    ) {
        let mut document = Document::with_version("1.5");
        let pages_id = document.new_object_id();
        let font_id = document.add_object(dictionary! {
            "Type" => "Font",
            "Subtype" => "Type1",
            "BaseFont" => "Courier",
        });
        let resources_id = document.add_object(dictionary! {
            "Font" => dictionary! { "F1" => font_id },
        });
        if let Some(name) = shared_name {
            let shared_id = document.add_object(Object::string_literal(name));
            document.trailer.set("KoiShared", shared_id);
            document
                .get_dictionary_mut(resources_id)
                .unwrap()
                .set("KoiShared", shared_id);
        }
        let mut kids = Vec::new();
        for text in texts {
            let content = Content {
                operations: vec![
                    Operation::new("BT", vec![]),
                    Operation::new("Tf", vec!["F1".into(), 24.into()]),
                    Operation::new("Td", vec![48.into(), 300.into()]),
                    Operation::new("Tj", vec![Object::string_literal(*text)]),
                    Operation::new("ET", vec![]),
                ],
            };
            let content_id = document.add_object(Stream::new(
                dictionary! {},
                content.encode().expect("encode PDF content"),
            ));
            let page_id = document.add_object(dictionary! {
                "Type" => "Page",
                "Parent" => pages_id,
                "Contents" => content_id,
            });
            kids.push(Object::Reference(page_id));
        }
        document.set_object(
            pages_id,
            dictionary! {
                "Type" => "Pages",
                "Kids" => kids,
                "Count" => i64::try_from(texts.len()).unwrap(),
                "Resources" => resources_id,
                "MediaBox" => vec![0.into(), 0.into(), 300.into(), 400.into()],
            },
        );
        let catalog_id = document.add_object(dictionary! {
            "Type" => "Catalog",
            "Pages" => pages_id,
        });
        document.trailer.set("Root", catalog_id);
        document.save(path).expect("save text PDF fixture");
    }

    fn extracted_text(path: &Path, page_number: u32) -> String {
        Document::load(path)
            .expect("load output PDF")
            .extract_text_with_limit(&[page_number], 1024 * 1024)
            .expect("extract output PDF text")
    }

    fn tree_fingerprint(root: &Path) -> Vec<String> {
        let mut result = Vec::new();
        let mut stack = vec![root.to_path_buf()];
        while let Some(directory) = stack.pop() {
            let mut entries = fs::read_dir(&directory)
                .expect("read fingerprint directory")
                .collect::<Result<Vec<_>, _>>()
                .expect("read fingerprint entries");
            entries.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
            for entry in entries {
                let path = entry.path();
                let relative = path
                    .strip_prefix(root)
                    .expect("fingerprint relative path")
                    .to_string_lossy()
                    .replace('\\', "/");
                let metadata = fs::symlink_metadata(&path).expect("fingerprint metadata");
                if metadata.is_dir() {
                    result.push(format!("D:{relative}"));
                    stack.push(path);
                } else {
                    result.push(format!(
                        "F:{relative}:{}:{}",
                        metadata.len(),
                        file_sha256(&path).expect("fingerprint file")
                    ));
                }
            }
        }
        result.sort();
        result
    }

    fn normalize_pdf_protocol(value: &mut Value, output: &Path, root: &Path) {
        let output = output.to_string_lossy();
        let root = root.to_string_lossy();
        match value {
            Value::String(text) => {
                *text = text.replace(r"\\?\", "");
                *text = text.replace(output.as_ref(), "<OUTPUT>");
                *text = text.replace(root.as_ref(), "<ROOT>");
                if text.starts_with("[DEBUG] 输出文件大小:") {
                    *text = "[DEBUG] 输出文件大小: <SIZE> bytes".to_string();
                }
            }
            Value::Array(items) => {
                for item in items {
                    normalize_pdf_protocol(
                        item,
                        Path::new(output.as_ref()),
                        Path::new(root.as_ref()),
                    );
                }
            }
            Value::Object(items) => {
                for item in items.values_mut() {
                    normalize_pdf_protocol(
                        item,
                        Path::new(output.as_ref()),
                        Path::new(root.as_ref()),
                    );
                }
            }
            _ => {}
        }
    }

    #[test]
    fn parses_signature_pages_and_media_boxes() {
        let root = temp_dir("preview");
        let path = root.join("a.pdf");
        fixture_text_pdf(&path, &["preview-one", "preview-two"]);
        let response = pdf_preview(&json!({
            "pdf_files": [path],
            "include_thumbnails": true,
            "thumbnail_limit": 1,
        }))
        .unwrap();
        assert_eq!(response["success"], true);
        assert_eq!(response["total_pages"], 2);
        assert_eq!(response["files"][0]["pages"][0]["width"], 300.0);
        let data_url = response["files"][0]["pages"][0]["thumbnail"]
            .as_str()
            .expect("first page PNG data URL");
        let encoded = data_url
            .strip_prefix("data:image/png;base64,")
            .expect("PNG data URL prefix");
        let png = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .expect("decode thumbnail");
        if let Some(output) = std::env::var_os("KOI_PDFIUM_THUMBNAIL_OUTPUT") {
            let output = PathBuf::from(output);
            if let Some(parent) = output.parent() {
                fs::create_dir_all(parent).expect("create visual thumbnail output directory");
            }
            fs::write(output, &png).expect("write visual thumbnail output");
        }
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        let image = image::load_from_memory(&png)
            .expect("decode thumbnail PNG")
            .to_rgb8();
        assert!(image.width() > 0 && image.width() <= 180);
        assert!(image.pixels().any(|pixel| pixel.0 != [255, 255, 255]));
        assert!(response["files"][0]["pages"][1]["thumbnail"].is_null());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn extraction_rejects_invalid_ranges_and_writes_verified_output() {
        let root = temp_dir("extract");
        let input = root.join("source.pdf");
        fixture_text_pdf(&input, &["alpha-page", "middle-page", "omega-page"]);
        let invalid = pdf_extract(&json!({"pdf_file": input, "page_ranges": "4"}))
            .expect_err("out-of-range pages use the outer error envelope");
        assert_eq!(invalid, "页码超出范围: 4，总页数: 3");
        let input = root.join("source.pdf");
        let valid = pdf_extract(&json!({"pdf_file": input, "page_ranges": "1,3"})).unwrap();
        assert_eq!(valid["success"], true);
        assert_eq!(valid["extracted"], 2);
        assert_eq!(
            read_pdf(Path::new(valid["output_file"].as_str().unwrap()))
                .unwrap()
                .page_count,
            2
        );
        let output = Path::new(valid["output_file"].as_str().unwrap());
        assert!(extracted_text(output, 1).contains("alpha-page"));
        assert!(extracted_text(output, 2).contains("omega-page"));
        assert!(!extracted_text(output, 1).contains("middle-page"));
        let output_document = Document::load(output).unwrap();
        for page_id in output_document.get_pages().into_values() {
            let page = output_document.get_dictionary(page_id).unwrap();
            assert!(page.has(b"Resources"));
            assert!(page.has(b"MediaBox"));
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn valid_extract_and_merge_match_redacted_python_golden_on_real_pdfs() {
        let fixture = python_oracle_fixture();
        let root = temp_dir("python-differential");
        let first = root.join("first.pdf");
        let second = root.join("second.pdf");
        fixture_text_pdf(&first, &["first-one", "first-two", "first-three"]);
        fixture_text_pdf(&second, &["second-one", "second-two"]);

        let rust_extract_output = root.join("rust-extract.pdf");
        let mut rust_extract = pdf_extract(&json!({
            "pdf_file": &first,
            "page_ranges": "1,3",
            "output_file": &rust_extract_output,
        }))
        .expect("Rust extract");
        normalize_pdf_protocol(&mut rust_extract, &rust_extract_output, &root);
        assert_eq!(rust_extract, fixture["pdf_extract"]);

        let output = &rust_extract_output;
        let document = Document::load(output).expect("load extracted output");
        assert_eq!(document.get_pages().len(), 2);
        assert!(extracted_text(output, 1).contains("first-one"));
        assert!(extracted_text(output, 2).contains("first-three"));
        assert!(!extracted_text(output, 1).contains("first-two"));

        let rust_merge_output = root.join("rust-merge.pdf");
        let selections = json!([
            {"file_path": &first, "page_num": "2", "order": "2"},
            {"path": &second, "page_number": 1, "order": 1}
        ]);
        let mut rust_merge = pdf_extract(&json!({
            "pdf_files": [&first, &second],
            "page_selections": selections,
            "output_file": &rust_merge_output,
        }))
        .expect("Rust merge");
        normalize_pdf_protocol(&mut rust_merge, &rust_merge_output, &root);
        assert_eq!(rust_merge, fixture["pdf_merge"]);

        let output = &rust_merge_output;
        let document = Document::load(output).expect("load merged output");
        assert_eq!(document.get_pages().len(), 2);
        assert!(extracted_text(output, 1).contains("second-one"));
        assert!(extracted_text(output, 2).contains("first-two"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn merge_preserves_cross_document_order_and_page_content() {
        let root = temp_dir("merge-content");
        let first = root.join("first.pdf");
        let second = root.join("second.pdf");
        fixture_text_pdf(&first, &["first-one", "first-two"]);
        fixture_text_pdf(&second, &["second-one", "second-two"]);
        let output = root.join("merged.pdf");
        let result = pdf_extract(&json!({
            "pdf_files": [&first, &second],
            "page_selections": [
                {"file_path": &first, "page_num": 1, "order": 2},
                {"file_path": &second, "page_num": 2, "order": 1}
            ],
            "output_file": &output,
        }))
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["merged_count"], 2);
        assert_eq!(result["file_count"], 2);
        assert_eq!(result["logs"], json!(["开始合并 2 页"]));
        assert!(extracted_text(&output, 1).contains("second-two"));
        assert!(extracted_text(&output, 2).contains("first-one"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn merge_remaps_cross_document_ids_without_resource_collisions() {
        let root = temp_dir("merge-id-collision");
        let first = root.join("first.pdf");
        let second = root.join("second.pdf");
        fixture_text_pdf_with_shared_resource(&first, &["first-content"], Some("FIRST"));
        fixture_text_pdf_with_shared_resource(&second, &["second-content"], Some("SECOND"));
        let output = root.join("merged.pdf");
        pdf_extract(&json!({
            "pdf_files": [&first, &second],
            "page_selections": [
                {"file_path": &first, "page_num": 1, "order": 1},
                {"file_path": &second, "page_num": 1, "order": 2}
            ],
            "output_file": &output,
        }))
        .unwrap();
        let document = Document::load(&output).unwrap();
        let pages = document.get_pages();
        let resource_ids = pages
            .into_values()
            .map(|page_id| {
                document
                    .get_dictionary(page_id)
                    .unwrap()
                    .get(b"Resources")
                    .and_then(Object::as_reference)
                    .unwrap()
            })
            .collect::<BTreeSet<_>>();
        assert_eq!(resource_ids.len(), 2);
        assert!(extracted_text(&output, 1).contains("first-content"));
        assert!(extracted_text(&output, 2).contains("second-content"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn standard_and_strong_compression_write_verified_outputs() {
        let root = temp_dir("compression-content");
        let input = root.join("source.pdf");
        let standard_output = root.join("standard.pdf");
        fixture_text_pdf(&input, &["compression-content"]);
        let standard = pdf_compress(&json!({
            "pdf_file": &input,
            "output_file": &standard_output,
            "compression_mode": "standard",
        }))
        .unwrap();
        assert_eq!(standard["success"], true);
        assert!(extracted_text(&standard_output, 1).contains("compression-content"));
        assert!(matches!(
            standard["results"][0]["method"].as_str(),
            Some("standard" | "standard-unchanged")
        ));

        let strong_output = root.join("strong.pdf");
        let strong = pdf_compress(&json!({
            "pdf_file": &input,
            "output_file": &strong_output,
            "compression_mode": "strong",
        }))
        .unwrap();
        assert_eq!(strong["success"], true);
        assert!(strong_output.exists());
        assert_eq!(read_pdf(&strong_output).unwrap().page_count, 1);
        assert!(matches!(
            strong["results"][0]["method"].as_str(),
            Some("strong" | "strong-unchanged")
        ));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_state_keeps_word_source_when_converter_is_unavailable() {
        let root = temp_dir("state");
        fs::write(root.join("关于测试.docx"), b"not-a-docx").unwrap();
        let result = notice_process(&json!({"target_path": root})).unwrap();
        assert_eq!(result["success"], false);
        assert!(root.join(NOTICE_STATE_FILE).exists());
        assert!(root.join("关于测试.docx").exists());
        let state: NoticeState =
            serde_json::from_slice(&fs::read(root.join(NOTICE_STATE_FILE)).unwrap()).unwrap();
        assert!(!state.completed);
        assert!(!state.stages.rewrite);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_empty_and_pdf_only_inputs_match_python_noop_contract() {
        let root = temp_dir("notice-noop-counts");

        let empty = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(empty["success"], true);
        assert_eq!(empty["total_reports"], 0);
        assert_eq!(empty["processed"], 0);
        assert_eq!(empty["pdf_outputs"], json!([]));
        assert!(
            !root.join(NOTICE_STATE_FILE).exists(),
            "a genuine empty run must not manufacture a resumable company"
        );

        fixture_pdf(&root.join("existing.pdf"), 1);
        let pdf_only = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(pdf_only["success"], true);
        assert_eq!(pdf_only["total_reports"], 0);
        assert_eq!(pdf_only["processed"], 0);
        assert_eq!(pdf_only["pdf_outputs"], json!([]));
        assert!(root.join("existing.pdf").is_file());
        assert!(
            !root.join(NOTICE_STATE_FILE).exists(),
            "an existing unrelated PDF must not become a notice checkpoint"
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_ignores_unrelated_docx_files_when_counting_reports() {
        let root = temp_dir("notice-unrelated-docx");
        fs::write(root.join("meeting-notes.docx"), b"not-a-notice").unwrap();

        let result = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], true);
        assert_eq!(result["total_reports"], 0);
        assert_eq!(result["processed"], 0);
        assert_eq!(result["manual_files"], json!([]));
        assert!(root.join("meeting-notes.docx").is_file());

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_counts_resumable_company_directories_independently() {
        let root = temp_dir("notice-resumable-company-count");
        let first = root.join("中河街道").join("宁波甲有限公司");
        let second = root.join("首南街道").join("宁波乙有限公司");
        fs::create_dir_all(&first).unwrap();
        fs::create_dir_all(&second).unwrap();
        write_docx_fixture(
            &first.join("关于宁波甲有限公司存在漏洞的通报.docx"),
            true,
            "中河街道",
        );
        write_docx_fixture(
            &second.join("关于宁波乙有限公司存在漏洞的通报.docx"),
            true,
            "首南街道",
        );

        let result = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["total_reports"], 2);
        assert_eq!(result["processed"], 2);
        assert_eq!(result["manual_files"], json!([]));
        assert_eq!(result["failures"], json!([]));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_process_treats_marked_rewrite_as_stage_one_artifact() {
        let root = temp_dir("marked-rewrite-stage");
        let rewritten = root.join("关于测试有限公司存在漏洞的通报.docx");
        write_docx_fixture(&rewritten, true, "首南街道");
        assert!(docx_path_has_rewrite_marker(&rewritten));

        let result = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();

        assert_eq!(result["success"], false);
        assert_eq!(result["manual_files"], json!([]));
        assert_eq!(result["failures"], json!([]));
        assert_eq!(result["stages"]["rewrite"], true);
        assert_eq!(result["stages"]["authorization"], false);
        assert_eq!(result["stages"]["rectification"], false);
        assert_eq!(result["stages"]["disposal"], false);
        assert_eq!(result["stages"]["pdf"], false);
        assert_eq!(result["pdf_outputs"], json!([]));
        assert!(result["generated_files"].as_array().is_some_and(|items| {
            items.iter().any(|item| {
                item.as_str()
                    .map(|value| value.replace(r"\\?\", "") == rewritten.to_string_lossy())
                    .unwrap_or(false)
            })
        }));
        assert!(rewritten.is_file(), "stage-one artifact must be retained");

        let _ = fs::remove_dir_all(root);
    }

    fn notice_task_fixture(
        task_id: &str,
        target_key: &str,
        running: bool,
        created_at: u64,
        finished_at: Option<u64>,
    ) -> NoticeTask {
        NoticeTask {
            task_id: task_id.to_string(),
            generation: 1,
            target_path: format!(r"C:\notice\{target_key}"),
            target_key: target_key.to_string(),
            running,
            done: !running,
            success: false,
            progress: if running { 1 } else { 0 },
            message: if running {
                "任务已创建，正在启动...".to_string()
            } else {
                "处理失败".to_string()
            },
            logs: Vec::new(),
            result: None,
            error: None,
            created_at,
            finished_at,
        }
    }

    #[test]
    fn notice_task_pruning_uses_finish_time_and_bounds_completed_history() {
        let mut tasks = HashMap::new();
        tasks.insert(
            "active".to_string(),
            notice_task_fixture("active", "active-target", true, 1, None),
        );
        for index in 0..26u64 {
            let id = format!("completed-{index:02}");
            tasks.insert(
                id.clone(),
                notice_task_fixture(&id, &id, false, 1, Some(100 + index)),
            );
        }
        tasks.insert(
            "recent-long-running".to_string(),
            notice_task_fixture(
                "recent-long-running",
                "recent-long-running",
                false,
                1,
                Some(125),
            ),
        );

        prune_notice_tasks_locked(&mut tasks, 125);

        assert!(tasks.contains_key("active"));
        assert!(tasks.contains_key("recent-long-running"));
        assert_eq!(tasks.values().filter(|task| !task.running).count(), 24);
        assert!(!tasks.contains_key("completed-00"));
        assert!(!tasks.contains_key("completed-01"));
        assert!(!tasks.contains_key("completed-02"));

        tasks.insert(
            "expired".to_string(),
            notice_task_fixture("expired", "expired", false, 1, Some(1)),
        );
        prune_notice_tasks_locked(&mut tasks, NOTICE_TASK_RETENTION_SECONDS + 2);
        assert!(!tasks.contains_key("expired"));
        assert!(tasks.contains_key("active"), "running tasks never expire");
    }

    #[test]
    fn notice_task_outer_error_still_produces_terminal_result_protocol() {
        let mut task = notice_task_fixture("failed-task", "failed-target", true, 10, None);
        finish_notice_task(&mut task, Err("fixture failure".to_string()), 20);

        assert!(!task.running);
        assert!(task.done);
        assert_eq!(task.finished_at, Some(20));
        assert_eq!(task.error.as_deref(), Some("fixture failure"));

        let response = notice_task_status_response(&task);
        assert_eq!(response["success"], false);
        assert_eq!(response["running"], false);
        assert_eq!(response["done"], true);
        assert_eq!(response["processed"], 0);
        assert_eq!(response["total_reports"], 0);
        assert_eq!(response["generated_files"], json!([]));
        assert_eq!(response["manual_files"], json!([]));
        assert_eq!(response["pdf_outputs"], json!([]));
        assert_eq!(response["result"]["success"], false);
        assert_eq!(
            response["result"]["failures"][0]["reason"],
            "fixture failure"
        );
    }

    #[test]
    fn running_notice_task_status_has_python_compatible_default_fields() {
        let task = notice_task_fixture("running-task", "running-target", true, 10, None);
        let response = notice_task_status_response(&task);

        assert_eq!(
            response,
            json!({
                "success": true,
                "task_id": "running-task",
                "generation": 1,
                "running": true,
                "stopped": false,
                "done": false,
                "message": "任务已创建，正在启动...",
                "progress": 1,
                "logs": [],
                "processed": 0,
                "total_reports": 0,
                "target_path": null,
                "generated_files": [],
                "manual_files": [],
                "failures": [],
                "pdf_outputs": [],
                "error": null,
            })
        );
    }

    #[test]
    fn notice_process_worker_error_remains_reconnectable_with_result() {
        let root = temp_dir("notice-task-worker-error");
        fs::write(root.join(NOTICE_STATE_FILE), b"{broken-json").unwrap();
        let started = notice_process_start(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        let task_id = started["task_id"]
            .as_str()
            .expect("worker task id")
            .to_string();

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        let terminal = loop {
            let status = notice_process_status(&json!({"task_id": &task_id})).unwrap();
            if status["done"] == true {
                break status;
            }
            assert!(std::time::Instant::now() < deadline, "worker must finish");
            std::thread::sleep(std::time::Duration::from_millis(10));
        };

        assert_eq!(terminal["success"], false);
        assert_eq!(terminal["running"], false);
        assert_eq!(terminal["result"]["success"], false);
        assert!(terminal["result"]["message"]
            .as_str()
            .is_some_and(|message| message.contains("断点文件损坏")));
        assert_eq!(
            terminal["result"]["failures"].as_array().map(Vec::len),
            Some(1)
        );

        if let Ok(mut tasks) = notice_tasks().lock() {
            tasks.remove(&task_id);
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_state_round_trips_python_checkpoint_fields() {
        let root = temp_dir("notice-python-state-compat");
        fs::write(
            root.join(NOTICE_STATE_FILE),
            serde_json::to_vec_pretty(&json!({
                "version": 1,
                "company_name": "宁波测试有限公司",
                "stages": {
                    "rewrite": true,
                    "authorization": false,
                    "rectification": false,
                    "disposal": false,
                    "pdf": false
                },
                "rewrite_items": [{"source": {"name": "source.docx"}, "artifact": "rewritten.docx"}],
                "rewrite_required": [{"name": "source.docx"}],
                "input_signature": [{"name": "source.docx", "size": 4, "sha256": "abcd"}],
                "active_stage": "authorization",
                "complete": false,
                "updated_at": "2026-08-23T10:00:00+08:00"
            }))
            .unwrap(),
        )
        .unwrap();
        let mut state = load_notice_state(&root)
            .unwrap()
            .expect("load Python state");
        assert!(state.stages.rewrite);
        assert_eq!(
            state.compatibility_fields["company_name"],
            "宁波测试有限公司"
        );
        state.archive_extractions.push(NoticeArchiveExtraction {
            archive_path: "input.zip".to_string(),
            archive_sha256: "hash".to_string(),
            outputs: Vec::new(),
        });
        save_notice_state(&root, &state).unwrap();
        let saved: Value =
            serde_json::from_slice(&fs::read(root.join(NOTICE_STATE_FILE)).unwrap()).unwrap();
        assert_eq!(saved["complete"], false);
        assert!(saved.get("completed").is_none());
        assert_eq!(saved["company_name"], "宁波测试有限公司");
        assert_eq!(saved["active_stage"], "authorization");
        assert_eq!(saved["rewrite_items"].as_array().unwrap().len(), 1);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn changed_same_name_source_invalidates_python_notice_checkpoint() {
        let root = temp_dir("notice-python-state-source-change");
        let source = root.join("123关于宁波测试有限公司所属系统存在未授权访问漏洞的通报.docx");
        fs::write(&source, b"original-source").unwrap();
        let original_size = fs::metadata(&source).unwrap().len();
        let original_sha256 = file_sha256(&source).unwrap();
        fs::write(
            root.join(NOTICE_STATE_FILE),
            serde_json::to_vec_pretty(&json!({
                "version": 1,
                "company_name": "宁波测试有限公司",
                "stages": {
                    "rewrite": true,
                    "authorization": true,
                    "rectification": true,
                    "disposal": true,
                    "pdf": true
                },
                "rewrite_items": [{
                    "source": {
                        "name": source.file_name().unwrap().to_string_lossy(),
                        "size": original_size,
                        "sha256": original_sha256,
                    },
                    "artifact": "关于宁波测试有限公司所属系统存在未授权访问漏洞的通报.docx"
                }],
                "rewrite_required": [],
                "input_signature": [{
                    "name": source.file_name().unwrap().to_string_lossy(),
                    "size": original_size,
                    "sha256": original_sha256,
                }],
                "complete": true,
            }))
            .unwrap(),
        )
        .unwrap();
        let state = load_notice_state(&root).unwrap().unwrap();
        assert!(python_checkpoint_matches_sources(&root, &state));

        // Keep the same path and byte length to prove that the SHA-256, rather
        // than a filename/size hint, controls checkpoint reuse.
        fs::write(&source, b"modified-source").unwrap();
        assert_eq!(fs::metadata(&source).unwrap().len(), original_size);
        assert!(!python_checkpoint_matches_sources(&root, &state));

        let result = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], false);
        assert!(source.is_file(), "the changed source must be retained");
        assert!(result["logs"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .any(|line| line.contains("源文件指纹缺失或不匹配")));
        let saved: Value =
            serde_json::from_slice(&fs::read(root.join(NOTICE_STATE_FILE)).unwrap()).unwrap();
        assert_eq!(saved["complete"], false);
        assert_eq!(saved["stages"]["rewrite"], false);
        assert!(saved["source_sha256"]
            .as_str()
            .is_some_and(|value| !value.is_empty()));
        assert!(saved.get("input_signature").is_none());
        assert!(saved.get("rewrite_items").is_none());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn python_notice_checkpoint_rejects_escaping_relative_source_path() {
        let root = temp_dir("notice-python-state-escape");
        let outside = root.parent().unwrap().join(format!(
            "outside-notice-source-{}.docx",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::write(&outside, b"outside-source").unwrap();
        let state: NoticeState = serde_json::from_value(json!({
            "version": 1,
            "company_name": "宁波测试有限公司",
            "input_signature": [{
                "name": outside.file_name().unwrap().to_string_lossy(),
                "path": format!("../{}", outside.file_name().unwrap().to_string_lossy()),
                "size": fs::metadata(&outside).unwrap().len(),
                "sha256": file_sha256(&outside).unwrap(),
            }]
        }))
        .unwrap();
        assert!(!python_checkpoint_matches_sources(&root, &state));
        let _ = fs::remove_file(outside);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn python_notice_checkpoint_rejects_same_name_cross_directory_ambiguity() {
        let root = temp_dir("notice-python-state-duplicate-name");
        let name = "123关于宁波测试有限公司存在漏洞的通报.docx";
        let first = root.join("first").join(name);
        let second = root.join("second").join(name);
        fs::create_dir_all(first.parent().unwrap()).unwrap();
        fs::create_dir_all(second.parent().unwrap()).unwrap();
        fs::write(&first, b"same-source").unwrap();
        fs::write(&second, b"same-source").unwrap();
        let state: NoticeState = serde_json::from_value(json!({
            "version": 1,
            "company_name": "宁波测试有限公司",
            "input_signature": [{
                "name": name,
                "size": fs::metadata(&first).unwrap().len(),
                "sha256": file_sha256(&first).unwrap(),
            }]
        }))
        .unwrap();

        assert!(!python_checkpoint_matches_sources(&root, &state));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn python_notice_checkpoint_rejects_source_added_after_snapshot() {
        let root = temp_dir("notice-python-state-added-source");
        let original = root.join("123关于宁波甲公司存在漏洞的通报.docx");
        let added = root.join("124关于宁波乙公司存在漏洞的通报.docx");
        fs::write(&original, b"first-source").unwrap();
        let state: NoticeState = serde_json::from_value(json!({
            "version": 1,
            "company_name": "宁波甲公司",
            "input_signature": [{
                "name": original.file_name().unwrap().to_string_lossy(),
                "size": fs::metadata(&original).unwrap().len(),
                "sha256": file_sha256(&original).unwrap(),
            }]
        }))
        .unwrap();
        assert!(python_checkpoint_matches_sources(&root, &state));

        fs::write(&added, b"second-source").unwrap();
        assert!(!python_checkpoint_matches_sources(&root, &state));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_zip_preextract_is_resumable_and_retains_nested_archives() {
        let root = temp_dir("notice-zip-resume");
        let first_pdf = root.join("first-source.pdf");
        let second_pdf = root.join("second-source.pdf");
        fixture_text_pdf(&first_pdf, &["first-archive-pdf"]);
        fixture_text_pdf(&second_pdf, &["second-archive-pdf"]);
        let first_bytes = fs::read(&first_pdf).unwrap();
        let second_bytes = fs::read(&second_pdf).unwrap();
        fs::remove_file(&first_pdf).unwrap();
        fs::remove_file(&second_pdf).unwrap();
        let nested = zip_fixture_bytes(vec![("nested-report.pdf", second_bytes)]);
        let archive = root.join("reports.zip");
        write_zip_fixture(
            &archive,
            vec![("report.pdf", first_bytes), ("nested.zip", nested)],
        );

        let first = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(first["success"], true);
        assert!(
            archive.is_file(),
            "the selected source archive must be retained"
        );
        assert!(root.join("nested.zip").is_file());
        assert!(root.join("report.pdf").is_file());
        assert!(root.join("nested-report.pdf").is_file());
        let state: NoticeState =
            serde_json::from_slice(&fs::read(root.join(NOTICE_STATE_FILE)).unwrap()).unwrap();
        assert_eq!(state.archive_extractions.len(), 2);

        let second = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(second["success"], true);
        assert!(!root.join("report (2).pdf").exists());
        assert!(!root.join("nested-report (2).pdf").exists());
        assert!(second["logs"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .any(|line| line.contains("跳过重复解压")));

        fs::remove_file(root.join("report.pdf")).unwrap();
        let recovered = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(recovered["success"], true);
        assert!(root.join("report.pdf").is_file());
        assert!(!root.join("report (2).pdf").exists());
        assert!(!root.join("nested (2).zip").exists());
        assert!(!root.join("nested-report (2).pdf").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_zip_rejects_traversal_before_writing_any_member() {
        let root = temp_dir("notice-zip-traversal");
        let outside = root.parent().unwrap().join(format!(
            "koi-notice-escape-{}.txt",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let traversal = format!("../{}", outside.file_name().unwrap().to_string_lossy());
        let archive = root.join("malicious.zip");
        write_zip_fixture(
            &archive,
            vec![
                ("safe-before.txt", b"must-not-extract".to_vec()),
                (&traversal, b"escape".to_vec()),
            ],
        );
        let result = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], false);
        assert!(archive.is_file());
        assert!(!root.join("safe-before.txt").exists());
        assert!(!outside.exists());
        assert!(result["failures"][0]["reason"]
            .as_str()
            .unwrap()
            .contains("不安全路径"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn archive_member_paths_reject_windows_aliases_and_wildcards() {
        for unsafe_name in [
            "CON.txt",
            "CON .txt",
            "nested/aux",
            "nested/CLOCK$",
            "COM¹.log",
            "report.txt.",
            "report.txt ",
            "folder/*.docx",
            "folder/name?.pdf",
            "folder/stream:name",
        ] {
            assert!(
                archive_relative_path(unsafe_name).is_err(),
                "unsafe Windows archive path accepted: {unsafe_name}"
            );
        }
        assert_eq!(
            archive_relative_path("安全目录/report.docx").unwrap(),
            PathBuf::from("安全目录/report.docx")
        );
    }

    #[test]
    fn notice_7z_preextract_is_verified_resumable_and_retains_source() {
        let root = temp_dir("notice-7z-resume");
        let archive = root.join("reports.7z");
        write_7z_fixture(
            &archive,
            &[("nested/alpha.txt", b"alpha"), ("unicode.txt", b"beta")],
        );

        let first = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(first["success"], true, "{first:#}");
        assert!(archive.is_file(), "the selected 7z source must be retained");
        assert_eq!(fs::read(root.join("nested/alpha.txt")).unwrap(), b"alpha");
        assert_eq!(fs::read(root.join("unicode.txt")).unwrap(), b"beta");

        let second = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(second["success"], true, "{second:#}");
        assert!(!root.join("nested/alpha (2).txt").exists());
        assert!(second["logs"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .any(|line| line.contains("跳过重复解压")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_7z_rejects_traversal_before_writing_any_member() {
        let root = temp_dir("notice-7z-traversal");
        let outside = root.parent().unwrap().join(format!(
            "koi-notice-7z-escape-{}.txt",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let archive = root.join("malicious.7z");
        write_7z_fixture(
            &archive,
            &[
                ("safe-before.txt", b"must-not-extract"),
                ("escape.txt", b"escape"),
            ],
        );
        let traversal = format!("../{}", outside.file_name().unwrap().to_string_lossy());
        rename_7z_member(&archive, "escape.txt", &traversal);

        let result = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], false, "{result:#}");
        assert!(archive.is_file());
        assert!(!root.join("safe-before.txt").exists());
        assert!(!outside.exists());
        assert!(result["failures"][0]["reason"]
            .as_str()
            .unwrap()
            .contains("不安全路径"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_rar_preextract_uses_real_decoder_and_is_resumable() {
        let root = temp_dir("notice-rar-resume");
        let archive = root.join("reports.rar");
        fs::write(&archive, rar4_safe_fixture()).unwrap();

        let first = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(first["success"], true, "{first:#}");
        assert!(
            archive.is_file(),
            "the selected RAR source must be retained"
        );
        assert_eq!(
            fs::read(root.join("test.txt")).unwrap(),
            b"test text document\r\n"
        );
        assert_eq!(
            fs::read(root.join("testdir/test.txt")).unwrap(),
            b"test text document\r\n"
        );

        let second = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(second["success"], true, "{second:#}");
        assert!(!root.join("test (2).txt").exists());
        assert!(second["logs"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_str)
            .any(|line| line.contains("跳过重复解压")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_rar5_preextract_uses_locked_runtime_and_retains_source() {
        let root = temp_dir("notice-rar5");
        let archive = root.join("reports.rar");
        write_rar_fixture(&archive, RAR5_MULTIPLE_FILES);

        let result = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], true, "{result:#}");
        assert!(
            archive.is_file(),
            "the selected RAR source must be retained"
        );
        for index in 1..=4 {
            let output = root.join(format!("test{index}.bin"));
            assert_eq!(fs::metadata(output).unwrap().len(), 4096);
        }

        let second = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(second["success"], true, "{second:#}");
        assert!(!root.join("test1 (2).bin").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn notice_rar_rejects_symlink_before_writing_any_member() {
        let root = temp_dir("notice-rar-link");
        let archive = root.join("linked.rar");
        write_rar_fixture(&archive, RAR4_WITH_SYMLINK);

        let result = notice_process(&json!({
            "target_path": &archive,
            "auto_group": false,
        }))
        .unwrap();
        assert_eq!(result["success"], false, "{result:#}");
        assert!(archive.is_file());
        assert!(!root.join("test.txt").exists());
        assert!(result["failures"][0]["reason"]
            .as_str()
            .unwrap()
            .contains("链接成员"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn failed_pdf_conversion_only_deletes_after_pdf_validation() {
        let root = temp_dir("convert");
        let source = root.join("授权委托书.docx");
        fs::write(&source, b"word").unwrap();
        let result = notice_convert_failed_pdf(
            &json!({"target_path": root, "failed_files": [{"file": source}]}),
        )
        .unwrap();
        assert_eq!(result["success"], false);
        assert!(source.exists());
        fixture_pdf(&root.join("授权委托书.pdf"), 1);
        let result = notice_convert_failed_pdf(
            &json!({"target_path": root, "failed_files": [{"file": source}]}),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        assert!(!source.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rewrite_stage_keeps_numeric_source_marks_output_and_preserves_template_parts() {
        let root = temp_dir("notice-rust-rewrite-stage");
        let source = root.join("123关于宁波测试有限公司存在漏洞的通报.docx");
        write_docx_fixture(&source, false, "");
        let source_hash = file_sha256(&source).unwrap();
        let mut state = new_notice_state(&root);
        let output =
            run_notice_rewrite_stage(&root, &mut state, &source, Some("中河街道")).unwrap();

        assert!(source.is_file(), "stage 1 must retain its numeric source");
        assert_eq!(file_sha256(&source).unwrap(), source_hash);
        assert_eq!(
            output.file_name().and_then(|value| value.to_str()),
            Some("关于宁波测试有限公司存在漏洞的通报.docx")
        );
        assert!(docx_path_has_rewrite_marker(&output));
        assert!(state.stages.rewrite);

        let file = File::open(&output).unwrap();
        let mut archive = ZipArchive::new(file).unwrap();
        let mut document = String::new();
        archive
            .by_name("word/document.xml")
            .unwrap()
            .read_to_string(&mut document)
            .unwrap();
        assert!(document.contains("抄送：中河街道"));
        let mut opaque = Vec::new();
        archive
            .by_name("word/customXml/opaque.bin")
            .unwrap()
            .read_to_end(&mut opaque)
            .unwrap();
        assert_eq!(opaque, b"opaque-part-v1");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rewrite_stage_failure_never_deletes_source_or_commits_partial_output() {
        let root = temp_dir("notice-rust-rewrite-failure");
        let source = root.join("123关于宁波测试有限公司存在漏洞的通报.docx");
        fs::write(&source, b"not-a-zip").unwrap();
        let output = root.join("关于宁波测试有限公司存在漏洞的通报.docx");
        let mut state = new_notice_state(&root);

        assert!(run_notice_rewrite_stage(&root, &mut state, &source, None).is_err());
        assert!(source.is_file());
        assert!(!output.exists());
        assert!(!state.stages.rewrite);
        assert_eq!(state.compatibility_fields["active_stage"], "rewrite");
        let _ = fs::remove_dir_all(root);
    }

    fn write_stage_template(path: &Path, body: &str) {
        let core = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>stage.template</dc:description></cp:coreProperties>"#;
        let document = format!(
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>"#
        );
        let entries = vec![
            (
                "[Content_Types].xml",
                r#"<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>"#,
            ),
            (
                "_rels/.rels",
                r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>"#,
            ),
            ("docProps/core.xml", core),
            ("word/document.xml", document.as_str()),
            ("word/customXml/opaque.bin", "stage-opaque"),
        ];
        let file = File::create(path).expect("create stage template");
        let mut writer = ZipWriter::new(file);
        for (name, content) in entries {
            writer
                .start_file(
                    name,
                    SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
                )
                .expect("start stage template part");
            writer
                .write_all(content.as_bytes())
                .expect("write stage template part");
        }
        writer.finish().expect("finish stage template");
    }

    #[test]
    fn generated_notice_stages_replace_markers_and_persist_each_checkpoint() {
        let root = temp_dir("notice-generated-stages");
        let templates = root.join("templates");
        let outputs = root.join("outputs");
        fs::create_dir_all(&templates).unwrap();
        fs::create_dir_all(&outputs).unwrap();
        let auth_template = templates.join("授权模板.docx");
        let rect_template = templates.join("责令整改模板.docx");
        let disposal_template = templates.join("处置模板.docx");
        write_stage_template(&auth_template, "涉嫌 * 的代理权限");
        write_stage_template(&rect_template, "【公司名】|【漏洞类型】");
        write_stage_template(&disposal_template, "XX网信办：关于××单位××系统的处置报告");
        let mut state = new_notice_state(&outputs);

        let authorization = run_notice_authorization_stage(
            &outputs,
            &mut state,
            &auth_template,
            "关于宁波测试有限公司存在漏洞的通报",
        )
        .unwrap();
        assert!(authorization.is_file());
        assert!(state.stages.authorization);
        assert_eq!(state.compatibility_fields["active_stage"], Value::Null);
        assert!(docx_document_xml(&authorization).contains("关于宁波测试有限公司存在漏洞的通报"));

        let rectification = run_notice_rectification_stage(
            &outputs,
            &mut state,
            &rect_template,
            "宁波测试有限公司",
            "未授权访问漏洞",
        )
        .unwrap();
        assert!(state.stages.rectification);
        let rect_text = docx_document_xml(&rectification);
        assert!(rect_text.contains("宁波测试有限公司"));
        assert!(rect_text.contains("未授权访问漏洞"));

        let disposal = run_notice_disposal_stage(&outputs, &mut state, &disposal_template).unwrap();
        assert!(state.stages.disposal);
        assert!(docx_document_xml(&disposal).contains("鄞州区网信办："));

        let saved: NoticeState = serde_json::from_slice(
            &fs::read(outputs.join(NOTICE_STATE_FILE)).expect("read stage checkpoint"),
        )
        .expect("parse stage checkpoint");
        assert!(saved.stages.authorization);
        assert!(saved.stages.rectification);
        assert!(saved.stages.disposal);
        assert!(saved
            .generated_files
            .iter()
            .any(|path| path.ends_with("授权模板.docx")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn generated_notice_stage_failure_keeps_active_checkpoint_and_no_partial_artifact() {
        let root = temp_dir("notice-generated-stage-failure");
        let template = root.join("授权模板.docx");
        write_stage_template(&template, "没有占位符");
        let mut state = new_notice_state(&root);

        let result = run_notice_authorization_stage(&root, &mut state, &template, "标题");
        assert!(result.is_err());
        assert!(!state.stages.authorization);
        assert_eq!(state.compatibility_fields["active_stage"], "authorization");
        assert!(state.compatibility_fields["stage_started_at"]
            .as_u64()
            .is_some());
        assert!(!root.join("授权模板.docx").exists() || root.join("授权模板.docx").is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn pdf_stage_validates_all_outputs_before_finishing_checkpoint() {
        let root = temp_dir("notice-pdf-stage");
        let first = root.join("授权委托书.docx");
        let second = root.join("责令整改通知书.docx");
        write_stage_template(&first, "授权委托书");
        write_stage_template(&second, "责令整改通知书");
        let mut state = new_notice_state(&root);
        state.stages = NoticeStages {
            rewrite: true,
            authorization: true,
            rectification: true,
            disposal: true,
            pdf: false,
        };

        let outputs = run_notice_pdf_stage_with(
            &root,
            &mut state,
            &[first.clone(), second.clone()],
            |_source, output| {
                fixture_pdf(output, 1);
                Ok(())
            },
        )
        .unwrap();

        assert_eq!(outputs.len(), 2);
        assert!(outputs.iter().all(|output| read_pdf(output).is_ok()));
        assert!(state.stages.pdf);
        assert!(state.completed);
        assert_eq!(state.pdf_outputs.len(), 2);
        assert!(first.is_file() && second.is_file());
        let saved = load_notice_state(&root).unwrap().unwrap();
        assert!(saved.stages.pdf && saved.completed);
        assert_eq!(saved.compatibility_fields["active_stage"], Value::Null);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn pdf_stage_failure_keeps_word_files_and_active_pdf_checkpoint() {
        let root = temp_dir("notice-pdf-stage-failure");
        let first = root.join("授权委托书.docx");
        let second = root.join("责令整改通知书.docx");
        write_stage_template(&first, "授权委托书");
        write_stage_template(&second, "责令整改通知书");
        let mut state = new_notice_state(&root);

        let result = run_notice_pdf_stage_with(
            &root,
            &mut state,
            &[first.clone(), second.clone()],
            |source, output| {
                if source == first {
                    fixture_pdf(output, 1);
                    Ok(())
                } else {
                    Err("fixture conversion failure".to_string())
                }
            },
        );

        assert!(result.is_err());
        assert!(!state.stages.pdf);
        assert_eq!(state.compatibility_fields["active_stage"], "pdf");
        assert!(first.is_file() && second.is_file());
        assert!(first.with_extension("pdf").is_file());
        assert!(!second.with_extension("pdf").exists());
        let saved = load_notice_state(&root).unwrap().unwrap();
        assert!(!saved.stages.pdf);
        assert_eq!(saved.compatibility_fields["active_stage"], "pdf");
        let _ = fs::remove_dir_all(root);
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "requires interactive Microsoft Word for the final PDF stage"]
    fn rust_notice_pipeline_completes_all_stages_and_cleans_numeric_source() {
        let root = temp_dir("notice-rust-full-pipeline");
        let templates = root.join("templates");
        fs::create_dir_all(&templates).unwrap();
        let source = root.join("123关于宁波测试有限公司存在漏洞的通报.docx");
        write_docx_fixture(&source, false, "");
        write_stage_template(&templates.join("授权委托书模板.docx"), "涉嫌 * 的代理权限");
        write_stage_template(
            &templates.join("责令整改模板.docx"),
            "【公司名】存在【漏洞类型】\\n2025年9月2日",
        );
        write_stage_template(
            &templates.join("处置模板.docx"),
            "XX网信办：关于××单位××系统的处置报告",
        );

        let result = notice_process(&json!({
            "target_path": &root,
            "auto_group": false,
            "_rust_notice_pipeline": true,
            "_notice_templates_dir": &templates,
        }))
        .expect("Rust notice pipeline response");

        assert_eq!(result["success"], true, "pipeline response: {result}");
        assert!(
            !source.exists(),
            "numeric source is removed only after all stages"
        );
        assert_eq!(result["stages"]["rewrite"], true);
        assert_eq!(result["stages"]["authorization"], true);
        assert_eq!(result["stages"]["rectification"], true);
        assert_eq!(result["stages"]["disposal"], true);
        assert_eq!(result["stages"]["pdf"], true);
        assert!(result["pdf_outputs"]
            .as_array()
            .is_some_and(|items| items.len() >= 2));
        let state: NoticeState = serde_json::from_slice(
            &fs::read(root.join(NOTICE_STATE_FILE)).expect("read completed state"),
        )
        .expect("parse completed state");
        assert!(state.completed);
        assert!(!state.deleted_files.is_empty());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rewrite_marker_adds_dc_namespace_to_minimal_core_properties() {
        let input =
            br#"<?xml version="1.0"?><cp:coreProperties xmlns:cp="urn:cp"></cp:coreProperties>"#;
        let output = append_rewrite_marker(input.to_vec()).unwrap();
        assert!(docx_has_rewrite_marker(&output));
        let text = String::from_utf8(output).unwrap();
        assert!(text.contains("xmlns:dc="));
        assert!(text.contains("<dc:description>koi.notice.rewritten.v1</dc:description>"));
    }

    #[test]
    fn notice_number_transaction_skips_unavailable_numbers_and_updates_document_atomically() {
        let root = temp_dir("notice-number-transaction");
        let config_path = root.join("config.json");
        fs::write(
            &config_path,
            serde_json::to_vec_pretty(&json!({
                "report_counters": {
                    "notification_number": 1,
                    "rectification_number": 1,
                    "unavailable_notification_numbers": [1, 3],
                    "unavailable_rectification_numbers": [2],
                    "year": 2026
                }
            }))
            .unwrap(),
        )
        .unwrap();
        let document = root.join("notice.docx");
        write_stage_template(&document, "〔2025〕第99期");
        let assigned = reserve_notice_number_and_rewrite(&config_path, &document, false)
            .unwrap()
            .expect("notification number");
        assert_eq!(assigned, (2, 2026));
        assert!(docx_text_content(&document)
            .unwrap()
            .contains("〔2026〕第2期"));
        let config: Value = serde_json::from_slice(&fs::read(&config_path).unwrap()).unwrap();
        assert_eq!(config["report_counters"]["notification_number"], 4);
        assert!(config["report_counters"]["unavailable_notification_numbers"] == json!([1, 3]));
        let _ = fs::remove_dir_all(root);
    }
}
