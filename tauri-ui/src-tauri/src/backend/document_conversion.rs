use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
#[cfg(all(windows, test))]
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const CONVERSION_TIMEOUT: Duration = Duration::from_secs(300);
const DEFAULT_TEMPLATE_SKIP_KEYWORDS: &[&str] =
    &["漏洞隐患处置文件模板", "app整改模板", "处置文件模板"];

static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConversionType {
    WordToPdf,
    WordToDocx,
    PdfToWord,
}

impl ConversionType {
    fn parse(value: &str) -> Result<Self, String> {
        if value.is_empty() {
            return Ok(Self::WordToPdf);
        }
        match value.trim() {
            "word_to_pdf" | "Word转PDF" | "word-pdf" => Ok(Self::WordToPdf),
            "word_to_docx" | "Word转DOCX" | "word-docx" | "doc-to-docx" => Ok(Self::WordToDocx),
            "pdf_to_word" | "PDF转Word" | "pdf-word" => Ok(Self::PdfToWord),
            value => Err(format!("不支持的转换类型: {value}")),
        }
    }

    fn source_label(self) -> &'static str {
        match self {
            Self::WordToPdf => "Word",
            Self::WordToDocx => "Word",
            Self::PdfToWord => "PDF",
        }
    }

    fn source_extensions(self) -> &'static [&'static str] {
        match self {
            Self::WordToPdf => &["doc", "docx"],
            Self::WordToDocx => &["doc", "docx"],
            Self::PdfToWord => &["pdf"],
        }
    }

    fn output_extension(self) -> &'static str {
        match self {
            Self::WordToPdf => "pdf",
            Self::WordToDocx => "docx",
            Self::PdfToWord => "docx",
        }
    }

    fn description(self) -> &'static str {
        match self {
            Self::WordToPdf => "Word转PDF",
            Self::WordToDocx => "Word转DOCX",
            Self::PdfToWord => "PDF转Word",
        }
    }
}

#[derive(Debug, Deserialize)]
struct ConvertRequest {
    #[serde(default = "default_conversion_type")]
    conversion_type: CompatText,
    #[serde(default)]
    input_path: CompatText,
    #[serde(default)]
    output_dir: CompatText,
    #[serde(default = "default_true", deserialize_with = "deserialize_python_bool")]
    recursive: bool,
    #[serde(default = "default_true", deserialize_with = "deserialize_python_bool")]
    overwrite: bool,
    #[serde(default = "default_true", deserialize_with = "deserialize_python_bool")]
    skip_template: bool,
    #[serde(default)]
    skip_keywords: StringList,
}

#[derive(Debug, Default)]
struct CompatText(String);

impl<'de> Deserialize<'de> for CompatText {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self(python_optional_text(&value)))
    }
}

#[derive(Debug, Default)]
struct StringList(Vec<String>);

impl<'de> Deserialize<'de> for StringList {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        let values = match value {
            Value::Null => Vec::new(),
            Value::Array(values) => values
                .iter()
                .map(python_string)
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
                .collect(),
            value => python_string(&value)
                .split(',')
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
                .collect(),
        };
        Ok(Self(values))
    }
}

impl StringList {
    fn into_vec(self) -> Vec<String> {
        self.0
    }
}

#[derive(Debug, Serialize)]
struct ConvertFailure {
    file: PathBuf,
    name: String,
    reason: String,
}

#[derive(Debug, Serialize)]
pub(super) struct ConvertResponse {
    success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    converted: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    skipped: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    failures: Option<Vec<ConvertFailure>>,
    logs: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    output_files: Option<Vec<PathBuf>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total: Option<usize>,
}

impl ConvertResponse {
    pub(super) fn succeeded(&self) -> bool {
        self.success
    }

    pub(super) fn failure_reason(&self, fallback: &str) -> String {
        self.failures
            .as_ref()
            .and_then(|failures| failures.first())
            .map(|failure| failure.reason.clone())
            .filter(|reason| !reason.trim().is_empty())
            .unwrap_or_else(|| {
                if self.message.trim().is_empty() {
                    fallback.to_string()
                } else {
                    self.message.clone()
                }
            })
    }
}

#[derive(Debug, Clone)]
struct ConversionJob {
    source: PathBuf,
    destination: PathBuf,
    output_boundary: PathBuf,
}

fn default_conversion_type() -> CompatText {
    CompatText("word_to_pdf".to_string())
}

fn default_true() -> bool {
    true
}

fn deserialize_python_bool<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(match value {
        Value::Null => false,
        Value::Bool(value) => value,
        Value::Number(value) => value.as_f64().map(|value| value != 0.0).unwrap_or(true),
        Value::String(value) => !value.is_empty(),
        Value::Array(values) => !values.is_empty(),
        Value::Object(values) => !values.is_empty(),
    })
}

fn python_optional_text(value: &Value) -> String {
    match value {
        Value::Null | Value::Bool(false) => String::new(),
        Value::Number(value) if value.as_f64() == Some(0.0) => String::new(),
        Value::String(value) if value.is_empty() => String::new(),
        Value::Array(values) if values.is_empty() => String::new(),
        Value::Object(values) if values.is_empty() => String::new(),
        value => python_string(value),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => value.clone(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn expand_user(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if text == "~" || text.starts_with("~/") || text.starts_with("~\\") {
        if let Some(home) = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")) {
            let suffix = text
                .strip_prefix('~')
                .unwrap_or_default()
                .trim_start_matches(['/', '\\']);
            return PathBuf::from(home).join(suffix);
        }
    }
    path.to_path_buf()
}

fn display_path(path: &Path) -> String {
    let path = if path.exists() {
        fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
    } else {
        path.to_path_buf()
    };
    path.display().to_string()
}

pub fn dispatch(command: &str, payload: &Value) -> Result<Value, String> {
    serde_json::to_value(dispatch_typed(command, payload)?).map_err(|error| error.to_string())
}

pub(super) fn dispatch_typed(command: &str, payload: &Value) -> Result<ConvertResponse, String> {
    if command != "doc.convert.run" {
        return Err(format!("未知文档转换命令: {command}"));
    }
    let request: ConvertRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("请求字段格式不正确: {error}"))?;
    convert(request)
}

fn convert(request: ConvertRequest) -> Result<ConvertResponse, String> {
    convert_with(request, |job, conversion_type| {
        convert_one(job, conversion_type).map(|_| ())
    })
}

fn convert_with<F>(request: ConvertRequest, mut converter: F) -> Result<ConvertResponse, String>
where
    F: FnMut(&ConversionJob, ConversionType) -> Result<(), String>,
{
    let conversion_type = ConversionType::parse(&request.conversion_type.0)?;
    let input_text = request.input_path.0.trim();
    if input_text.is_empty() {
        return Err("请选择输入路径".to_string());
    }
    let input_path = expand_user(Path::new(input_text));
    if !input_path.exists() {
        return Ok(empty_response(format!(
            "输入路径不存在: {}",
            display_path(&input_path)
        )));
    }
    let output_root = if request.output_dir.0.trim().is_empty() {
        None
    } else {
        Some(expand_user(Path::new(request.output_dir.0.trim())))
    };
    if output_root
        .as_ref()
        .map(|path| path.exists() && !path.is_dir())
        .unwrap_or(false)
    {
        return Ok(empty_response(format!(
            "输出路径不是目录: {}",
            display_path(output_root.as_ref().expect("checked"))
        )));
    }
    if let Some(output_root) = output_root.as_ref() {
        ensure_output_root_not_within_input(output_root, &input_path)?;
    }

    let mut skip_keywords = request.skip_keywords.into_vec();
    if request.skip_template && conversion_type == ConversionType::WordToPdf {
        skip_keywords.splice(
            0..0,
            DEFAULT_TEMPLATE_SKIP_KEYWORDS
                .iter()
                .map(|value| (*value).to_string()),
        );
    }
    if input_path.is_file() {
        if !has_extension(&input_path, conversion_type.source_extensions()) {
            return Ok(empty_response(format!(
                "输入文件不是{}文件: {}",
                conversion_type.source_label(),
                display_path(&input_path)
            )));
        }
        let name = input_path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if matches_skip_keyword(name, &skip_keywords) {
            return Ok(empty_response(format!("输入文件命中跳过关键词: {name}")));
        }
    }
    let (input_root, sources) = collect_sources(
        &input_path,
        conversion_type,
        request.recursive,
        &skip_keywords,
    )?;
    if sources.is_empty() {
        return Ok(empty_response(format!(
            "未找到可转换的{}文件",
            conversion_type.source_label()
        )));
    }

    let jobs: Vec<ConversionJob> = sources
        .into_iter()
        .map(|source| {
            let destination = output_path(
                &source,
                &input_root,
                output_root.as_deref(),
                conversion_type.output_extension(),
            );
            let output_boundary = output_root
                .clone()
                .or_else(|| destination.parent().map(Path::to_path_buf))
                .unwrap_or_default();
            ConversionJob {
                source,
                destination,
                output_boundary,
            }
        })
        .collect();
    let mut logs = vec![
        format!("开始转换: {}", conversion_type.description()),
        format!("找到 {} 个文件", jobs.len()),
    ];
    if let Some(root) = output_root.as_ref() {
        logs.push(format!("输出目录: {}", root.display()));
    }

    let mut converted = 0usize;
    let mut skipped = 0usize;
    let mut failures = Vec::new();
    let mut output_files = Vec::new();
    let mut captured_logs = Vec::new();
    for job in &jobs {
        if job.destination.exists() && !request.overwrite {
            skipped += 1;
            output_files.push(job.destination.clone());
            if conversion_type == ConversionType::PdfToWord {
                captured_logs.push(format!("跳过已存在文件: {}", job.destination.display()));
            }
            continue;
        }
        if conversion_type == ConversionType::PdfToWord {
            captured_logs.push(format!(
                "正在转换: {} -> {}",
                job.source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default(),
                job.destination
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
            ));
        }
        match converter(job, conversion_type) {
            Ok(()) => {
                converted += 1;
                output_files.push(job.destination.clone());
                if conversion_type == ConversionType::PdfToWord {
                    captured_logs.push(format!(
                        "转换完成: {}",
                        job.source
                            .file_name()
                            .and_then(|value| value.to_str())
                            .unwrap_or_default()
                    ));
                }
            }
            Err(reason) => {
                let name = job
                    .source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
                    .to_string();
                if conversion_type == ConversionType::PdfToWord {
                    captured_logs.push(format!("转换失败 {name}: {reason}"));
                }
                failures.push(ConvertFailure {
                    file: job.source.clone(),
                    name,
                    reason,
                });
            }
        }
    }
    logs.extend(captured_logs);
    logs.extend(
        failures
            .iter()
            .map(|failure| format!("失败: {} -> {}", failure.name, failure.reason)),
    );
    let message = format!(
        "转换完成：成功 {converted}，跳过 {skipped}，失败 {}",
        failures.len()
    );
    Ok(ConvertResponse {
        success: failures.is_empty(),
        message,
        converted: Some(converted),
        skipped: Some(skipped),
        failures: Some(failures),
        logs,
        output_files: Some(output_files),
        total: Some(jobs.len()),
    })
}

fn ensure_output_root_not_within_input(
    output_root: &Path,
    input_path: &Path,
) -> Result<(), String> {
    if !input_path.is_dir() {
        return Ok(());
    }
    let canonical_input =
        fs::canonicalize(input_path).map_err(|error| format!("无法解析输入目录: {error}"))?;
    let probe = output_root
        .ancestors()
        .find(|ancestor| ancestor.exists())
        .ok_or_else(|| "输出目录缺少可解析的父目录".to_string())?;
    let canonical_probe =
        fs::canonicalize(probe).map_err(|error| format!("无法解析输出目录: {error}"))?;
    if canonical_probe.starts_with(&canonical_input) {
        return Err(format!(
            "输出目录不能位于输入目录内: {}",
            display_path(output_root)
        ));
    }
    Ok(())
}

fn empty_response(message: String) -> ConvertResponse {
    ConvertResponse {
        success: false,
        message,
        converted: None,
        skipped: None,
        failures: None,
        logs: Vec::new(),
        output_files: None,
        total: None,
    }
}

fn collect_sources(
    input: &Path,
    conversion_type: ConversionType,
    recursive: bool,
    skip_keywords: &[String],
) -> Result<(PathBuf, Vec<PathBuf>), String> {
    if input.is_file() {
        let resolved = canonical_regular_file(input)?;
        if !has_extension(&resolved, conversion_type.source_extensions()) {
            return Ok((
                resolved.parent().unwrap_or(Path::new("")).to_path_buf(),
                Vec::new(),
            ));
        }
        let name = resolved
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if matches_skip_keyword(name, skip_keywords) {
            return Ok((
                resolved.parent().unwrap_or(Path::new("")).to_path_buf(),
                Vec::new(),
            ));
        }
        let root = resolved
            .parent()
            .ok_or_else(|| "输入文件缺少父目录".to_string())?
            .to_path_buf();
        return Ok((root, vec![resolved]));
    }

    let root = fs::canonicalize(input).map_err(|error| format!("无法解析输入目录: {error}"))?;
    let mut files = Vec::new();
    collect_directory(
        &root,
        recursive,
        conversion_type.source_extensions(),
        skip_keywords,
        &mut files,
    )?;
    files.sort();
    files.dedup();
    Ok((root, files))
}

fn collect_directory(
    directory: &Path,
    recursive: bool,
    extensions: &[&str],
    skip_keywords: &[String],
    files: &mut Vec<PathBuf>,
) -> Result<(), String> {
    let entries = fs::read_dir(directory)
        .map_err(|error| format!("无法读取输入目录 {}: {error}", directory.display()))?;
    for entry in entries {
        let entry = entry.map_err(|error| format!("无法读取目录项: {error}"))?;
        let file_type = entry
            .file_type()
            .map_err(|error| format!("无法读取目录项类型: {error}"))?;
        if file_type.is_symlink() {
            continue;
        }
        let path = entry.path();
        if file_type.is_dir() {
            if recursive {
                collect_directory(&path, true, extensions, skip_keywords, files)?;
            }
            continue;
        }
        if !file_type.is_file() || !has_extension(&path, extensions) {
            continue;
        }
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if should_skip_discovered(name, skip_keywords) {
            continue;
        }
        files.push(canonical_regular_file(&path)?);
    }
    Ok(())
}

fn canonical_regular_file(path: &Path) -> Result<PathBuf, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("无法读取输入文件 {}: {error}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!("输入路径不是普通文件: {}", path.display()));
    }
    fs::canonicalize(path).map_err(|error| format!("无法解析输入文件: {error}"))
}

fn has_extension(path: &Path, extensions: &[&str]) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| {
            extensions
                .iter()
                .any(|extension| value.eq_ignore_ascii_case(extension))
        })
        .unwrap_or(false)
}

fn matches_skip_keyword(name: &str, keywords: &[String]) -> bool {
    keywords.iter().any(|keyword| name.contains(keyword))
}

fn should_skip_discovered(name: &str, keywords: &[String]) -> bool {
    name.starts_with("~$") || matches_skip_keyword(name, keywords)
}

fn output_path(source: &Path, input_root: &Path, output_root: Option<&Path>, ext: &str) -> PathBuf {
    let file_name = source.with_extension(ext).file_name().map(OsString::from);
    match (output_root, file_name) {
        (Some(root), Some(file_name)) => {
            let relative_parent = source
                .parent()
                .and_then(|parent| parent.strip_prefix(input_root).ok())
                .unwrap_or(Path::new(""));
            root.join(relative_parent).join(file_name)
        }
        _ => source.with_extension(ext),
    }
}

fn convert_one(
    job: &ConversionJob,
    conversion_type: ConversionType,
) -> Result<&'static str, String> {
    let parent = prepare_output_parent(&job.destination, &job.output_boundary)?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let temporary = parent.join(format!(
        ".{}.koi-tmp-{}-{}-{nonce}.{}",
        job.destination
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("converted"),
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed),
        conversion_type.output_extension()
    ));
    let _ = fs::remove_file(&temporary);

    let com_result = run_word_com(&job.source, &temporary, conversion_type);
    let (method, result) = match (conversion_type, com_result) {
        (_, Ok(())) => ("word-com", Ok(())),
        (ConversionType::WordToPdf, Err(com_error)) => {
            let _ = fs::remove_file(&temporary);
            match run_libreoffice(&job.source, &temporary) {
                Ok(()) => ("libreoffice", Ok(())),
                Err(fallback_error) => (
                    "libreoffice",
                    Err(format!(
                        "Word COM 失败: {}; LibreOffice 回退失败: {}",
                        truncate_error(&com_error),
                        truncate_error(&fallback_error)
                    )),
                ),
            }
        }
        (ConversionType::WordToDocx, Err(error)) | (ConversionType::PdfToWord, Err(error)) => {
            ("word-com", Err(error))
        }
    };
    if let Err(error) = result {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    let commit_result = (|| {
        validate_output(&temporary, conversion_type)?;
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&temporary)
            .and_then(|file| file.sync_all())
            .map_err(|error| format!("无法同步转换输出: {error}"))?;
        replace_output(&temporary, &job.destination)?;
        validate_output(&job.destination, conversion_type)
    })();
    if let Err(error) = commit_result {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    Ok(method)
}

fn prepare_output_parent(destination: &Path, boundary: &Path) -> Result<PathBuf, String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "输出文件缺少父目录".to_string())?;
    fs::create_dir_all(boundary).map_err(|error| format!("无法创建输出目录: {error}"))?;
    fs::create_dir_all(parent).map_err(|error| format!("无法创建输出目录: {error}"))?;
    let canonical_boundary =
        fs::canonicalize(boundary).map_err(|error| format!("无法解析输出根目录: {error}"))?;
    let canonical_parent =
        fs::canonicalize(parent).map_err(|error| format!("无法解析输出目录: {error}"))?;
    if !canonical_parent.starts_with(&canonical_boundary) {
        return Err(format!("输出路径越过指定目录: {}", destination.display()));
    }
    Ok(canonical_parent)
}

#[cfg(windows)]
const WORD_COM_WORKER_SWITCH: &str = "--koi-internal-word-com-worker";
#[cfg(windows)]
const WORD_COM_NOTICE_REWRITE_SWITCH: &str = "--koi-internal-notice-rewrite-worker";

#[cfg(windows)]
#[derive(Debug, Clone, PartialEq, Eq)]
struct WordComWorkerRequest {
    source: PathBuf,
    destination: PathBuf,
    kind: ConversionType,
}

#[cfg(windows)]
#[derive(Debug, Clone, PartialEq, Eq)]
struct WordComNoticeRewriteRequest {
    source: PathBuf,
    template: PathBuf,
    destination: PathBuf,
    company: String,
    vulnerability: String,
    current_date: String,
    deadline_date: String,
    copy_to: String,
    confirmation_image: Option<PathBuf>,
}

pub(super) struct NoticeRewriteFields<'a> {
    pub(super) company: &'a str,
    pub(super) vulnerability: &'a str,
    pub(super) current_date: &'a str,
    pub(super) deadline_date: &'a str,
    pub(super) copy_to: &'a str,
    pub(super) confirmation_image: Option<&'a Path>,
}

#[cfg(all(windows, not(test)))]
pub(super) fn rewrite_notice_with_word(
    source: &Path,
    template: &Path,
    destination: &Path,
    fields: NoticeRewriteFields<'_>,
) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let executable = std::env::current_exe()
        .map_err(|error| format!("cannot locate the native notice rewrite worker: {error}"))?;
    let mut command = Command::new(executable);
    command
        .arg(WORD_COM_NOTICE_REWRITE_SWITCH)
        .arg(source)
        .arg(template)
        .arg(destination)
        .arg(fields.company)
        .arg(fields.vulnerability)
        .arg(fields.current_date)
        .arg(fields.deadline_date)
        .arg(fields.copy_to)
        .arg(
            fields
                .confirmation_image
                .map(Path::as_os_str)
                .unwrap_or_default(),
        )
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW);
    run_command(
        command,
        CONVERSION_TIMEOUT,
        "native Word notice rewrite worker",
    )
}

#[cfg(all(windows, test))]
pub(super) fn rewrite_notice_with_word(
    source: &Path,
    template: &Path,
    destination: &Path,
    fields: NoticeRewriteFields<'_>,
) -> Result<(), String> {
    let request = validate_notice_rewrite_worker_request(WordComNoticeRewriteRequest {
        source: source.to_path_buf(),
        template: template.to_path_buf(),
        destination: destination.to_path_buf(),
        company: fields.company.to_string(),
        vulnerability: fields.vulnerability.to_string(),
        current_date: fields.current_date.to_string(),
        deadline_date: fields.deadline_date.to_string(),
        copy_to: fields.copy_to.to_string(),
        confirmation_image: fields.confirmation_image.map(Path::to_path_buf),
    })?;
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::Builder::new()
        .name("koi-word-notice-rewrite-sta-test".to_string())
        .spawn(move || {
            let result = run_notice_rewrite_request(&request);
            let _ = sender.send(result);
        })
        .map_err(|error| format!("cannot start Word notice rewrite STA test worker: {error}"))?;
    receiver
        .recv_timeout(CONVERSION_TIMEOUT)
        .map_err(|error| match error {
            mpsc::RecvTimeoutError::Timeout => {
                "native Word notice rewrite timed out in the STA test worker".to_string()
            }
            mpsc::RecvTimeoutError::Disconnected => {
                "native Word notice rewrite STA test worker exited without a result".to_string()
            }
        })?
}

#[cfg(not(windows))]
pub(super) fn rewrite_notice_with_word(
    _source: &Path,
    _template: &Path,
    _destination: &Path,
    _fields: NoticeRewriteFields<'_>,
) -> Result<(), String> {
    Err("Word notice rewrite is only available on Windows".to_string())
}

#[cfg(all(windows, not(test)))]
fn run_word_com(source: &Path, destination: &Path, kind: ConversionType) -> Result<(), String> {
    use std::os::windows::process::CommandExt;

    // Keep Office automation behind a kill-on-close Job Object boundary while
    // using this Rust executable itself as the worker, with no script host.
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let executable = std::env::current_exe()
        .map_err(|error| format!("cannot locate the native Word COM worker: {error}"))?;
    if !executable.is_file() {
        return Err(format!(
            "native Word COM worker is not a regular file: {}",
            executable.display()
        ));
    }
    let mut command = Command::new(executable);
    command
        .arg(WORD_COM_WORKER_SWITCH)
        .arg(kind.worker_name())
        .arg(source)
        .arg(destination)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW);
    run_command(command, CONVERSION_TIMEOUT, "native Word COM worker")
}

#[cfg(all(windows, test))]
fn run_word_com(source: &Path, destination: &Path, kind: ConversionType) -> Result<(), String> {
    use std::sync::mpsc;

    let request = validate_word_com_worker_request(WordComWorkerRequest {
        source: source.to_path_buf(),
        destination: destination.to_path_buf(),
        kind,
    })?;
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::Builder::new()
        .name("koi-word-com-sta-test".to_string())
        .spawn(move || {
            let result =
                word_automation::convert(&request.source, &request.destination, request.kind);
            let _ = sender.send(result);
        })
        .map_err(|error| format!("cannot start native Word COM STA thread: {error}"))?;
    receiver
        .recv_timeout(CONVERSION_TIMEOUT)
        .map_err(|error| match error {
            mpsc::RecvTimeoutError::Timeout => {
                "native Word COM conversion timed out in the STA test worker".to_string()
            }
            mpsc::RecvTimeoutError::Disconnected => {
                "native Word COM STA test worker exited without a result".to_string()
            }
        })?
}

#[cfg(not(windows))]
fn run_word_com(_source: &Path, _destination: &Path, _kind: ConversionType) -> Result<(), String> {
    Err("Word COM is only available on Windows".to_string())
}

#[cfg(windows)]
impl ConversionType {
    fn worker_name(self) -> &'static str {
        match self {
            Self::WordToPdf => "word-to-pdf",
            Self::WordToDocx => "word-to-docx",
            Self::PdfToWord => "pdf-to-word",
        }
    }

    fn parse_worker_name(value: &OsString) -> Result<Self, String> {
        match value.to_str() {
            Some("word-to-pdf") => Ok(Self::WordToPdf),
            Some("word-to-docx") => Ok(Self::WordToDocx),
            Some("pdf-to-word") => Ok(Self::PdfToWord),
            _ => Err("invalid native Word COM worker conversion type".to_string()),
        }
    }
}

#[cfg(windows)]
fn parse_word_com_worker_args<I>(arguments: I) -> Result<Option<WordComWorkerRequest>, String>
where
    I: IntoIterator<Item = OsString>,
{
    let mut arguments = arguments.into_iter();
    let Some(switch) = arguments.next() else {
        return Ok(None);
    };
    if switch != WORD_COM_WORKER_SWITCH {
        return Ok(None);
    }
    let kind = arguments
        .next()
        .ok_or_else(|| "native Word COM worker requires a conversion type".to_string())
        .and_then(|value| ConversionType::parse_worker_name(&value))?;
    let source = arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "native Word COM worker requires an absolute source path".to_string())?;
    let destination = arguments.next().map(PathBuf::from).ok_or_else(|| {
        "native Word COM worker requires an absolute destination path".to_string()
    })?;
    if arguments.next().is_some() {
        return Err("native Word COM worker received unexpected arguments".to_string());
    }
    Ok(Some(WordComWorkerRequest {
        source,
        destination,
        kind,
    }))
}

#[cfg(windows)]
fn parse_notice_rewrite_worker_args<I>(
    arguments: I,
) -> Result<Option<WordComNoticeRewriteRequest>, String>
where
    I: IntoIterator<Item = OsString>,
{
    let mut arguments = arguments.into_iter();
    let Some(switch) = arguments.next() else {
        return Ok(None);
    };
    if switch != WORD_COM_NOTICE_REWRITE_SWITCH {
        return Ok(None);
    }
    let source = arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "native notice rewrite worker requires a source path".to_string())?;
    let template = arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "native notice rewrite worker requires a template path".to_string())?;
    let destination = arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "native notice rewrite worker requires a destination path".to_string())?;
    let next_string = |value: Option<OsString>, label: &str| {
        value
            .and_then(|value| value.into_string().ok())
            .ok_or_else(|| format!("native notice rewrite worker requires UTF-8 {label}"))
    };
    let company = next_string(arguments.next(), "company")?;
    let vulnerability = next_string(arguments.next(), "vulnerability")?;
    let current_date = next_string(arguments.next(), "current date")?;
    let deadline_date = next_string(arguments.next(), "deadline date")?;
    let copy_to = next_string(arguments.next(), "copy-to")?;
    let confirmation_image = arguments
        .next()
        .map(PathBuf::from)
        .filter(|path| !path.as_os_str().is_empty());
    if arguments.next().is_some() {
        return Err("native notice rewrite worker received unexpected arguments".to_string());
    }
    Ok(Some(WordComNoticeRewriteRequest {
        source,
        template,
        destination,
        company,
        vulnerability,
        current_date,
        deadline_date,
        copy_to,
        confirmation_image,
    }))
}

#[cfg(windows)]
fn validate_notice_rewrite_worker_request(
    mut request: WordComNoticeRewriteRequest,
) -> Result<WordComNoticeRewriteRequest, String> {
    if !request.source.is_absolute()
        || !request.template.is_absolute()
        || !request.destination.is_absolute()
    {
        return Err("native notice rewrite worker paths must be absolute".to_string());
    }
    request.source = canonical_regular_file(&request.source)
        .map_err(|error| format!("invalid notice rewrite source: {error}"))?;
    request.template = canonical_regular_file(&request.template)
        .map_err(|error| format!("invalid notice rewrite template: {error}"))?;
    if !has_extension(&request.source, &["docx"])
        || !has_extension(&request.template, &["docx"])
        || !has_extension(&request.destination, &["docx"])
    {
        return Err(
            "native notice rewrite requires DOCX source, template, and destination".to_string(),
        );
    }
    if request.destination.exists() {
        return Err("native notice rewrite refuses to overwrite an existing file".to_string());
    }
    if let Some(image) = request.confirmation_image.as_mut() {
        *image = canonical_regular_file(image)
            .map_err(|error| format!("invalid notice confirmation image: {error}"))?;
        if !has_extension(image, &["jpg", "jpeg", "png"]) {
            return Err("native notice confirmation image must be JPG or PNG".to_string());
        }
    }
    let parent = request
        .destination
        .parent()
        .ok_or_else(|| "native notice rewrite destination has no parent".to_string())?;
    let parent = fs::canonicalize(parent)
        .map_err(|error| format!("cannot resolve notice rewrite destination parent: {error}"))?;
    let name = request
        .destination
        .file_name()
        .ok_or_else(|| "native notice rewrite destination has no file name".to_string())?;
    request.destination = parent.join(name);
    if request.source == request.destination || request.template == request.destination {
        return Err(
            "native notice rewrite source/template and destination must differ".to_string(),
        );
    }
    for (label, value, required) in [
        ("company", &request.company, true),
        ("vulnerability", &request.vulnerability, true),
        ("current date", &request.current_date, true),
        ("deadline date", &request.deadline_date, true),
        ("copy-to", &request.copy_to, false),
    ] {
        if value.len() > 512
            || value.chars().any(char::is_control)
            || (required && value.trim().is_empty())
        {
            return Err(format!("native notice rewrite received invalid {label}"));
        }
    }
    Ok(request)
}

#[cfg(windows)]
fn run_notice_rewrite_request(request: &WordComNoticeRewriteRequest) -> Result<(), String> {
    word_automation::rewrite_notice(
        &request.source,
        &request.template,
        &request.destination,
        word_automation::NoticeRewriteFields {
            company: &request.company,
            vulnerability: &request.vulnerability,
            current_date: &request.current_date,
            deadline_date: &request.deadline_date,
            copy_to: &request.copy_to,
            confirmation_image: request.confirmation_image.as_deref(),
        },
    )
}

#[cfg(windows)]
fn validate_word_com_worker_request(
    request: WordComWorkerRequest,
) -> Result<WordComWorkerRequest, String> {
    if !request.source.is_absolute() || !request.destination.is_absolute() {
        return Err("native Word COM worker paths must be absolute".to_string());
    }
    let source = canonical_regular_file(&request.source)
        .map_err(|error| format!("invalid native Word COM source: {error}"))?;
    if !has_extension(&source, request.kind.source_extensions()) {
        return Err(format!(
            "native Word COM source must be a {} file",
            request.kind.source_label()
        ));
    }
    if !has_extension(&request.destination, &[request.kind.output_extension()]) {
        return Err(format!(
            "native Word COM destination must use .{}",
            request.kind.output_extension()
        ));
    }
    if request.destination.exists() {
        return Err("native Word COM worker refuses to overwrite an existing file".to_string());
    }
    let destination_parent = request
        .destination
        .parent()
        .ok_or_else(|| "native Word COM destination has no parent directory".to_string())?;
    let parent_metadata = fs::symlink_metadata(destination_parent)
        .map_err(|error| format!("cannot inspect native Word COM destination: {error}"))?;
    if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
        return Err("native Word COM destination parent must be a regular directory".to_string());
    }
    let canonical_parent = fs::canonicalize(destination_parent)
        .map_err(|error| format!("cannot resolve native Word COM destination: {error}"))?;
    let file_name = request
        .destination
        .file_name()
        .ok_or_else(|| "native Word COM destination has no file name".to_string())?;
    let destination = canonical_parent.join(file_name);
    if source == destination {
        return Err("native Word COM source and destination must differ".to_string());
    }
    Ok(WordComWorkerRequest {
        source,
        destination,
        kind: request.kind,
    })
}

#[cfg(windows)]
#[cfg_attr(test, allow(dead_code))]
pub(super) fn run_word_com_worker_from_args() -> Option<i32> {
    match parse_notice_rewrite_worker_args(std::env::args_os().skip(1)) {
        Ok(Some(request)) => {
            return Some(
                match validate_notice_rewrite_worker_request(request)
                    .and_then(|request| run_notice_rewrite_request(&request))
                {
                    Ok(()) => 0,
                    Err(error) => {
                        eprintln!(
                            "native notice rewrite worker failed: {}",
                            truncate_error(&error)
                        );
                        1
                    }
                },
            );
        }
        Ok(None) => {}
        Err(error) => {
            eprintln!("native notice rewrite worker arguments rejected: {error}");
            return Some(2);
        }
    }
    let request = match parse_word_com_worker_args(std::env::args_os().skip(1)) {
        Ok(Some(request)) => request,
        Ok(None) => return None,
        Err(error) => {
            eprintln!("native Word COM worker arguments rejected: {error}");
            return Some(2);
        }
    };
    let result = validate_word_com_worker_request(request).and_then(|request| {
        word_automation::convert(&request.source, &request.destination, request.kind)
    });
    match result {
        Ok(()) => Some(0),
        Err(error) => {
            eprintln!("native Word COM worker failed: {}", truncate_error(&error));
            Some(1)
        }
    }
}

#[cfg(not(windows))]
pub(super) fn run_word_com_worker_from_args() -> Option<i32> {
    None
}

#[cfg(windows)]
#[path = "word_automation.rs"]
mod word_automation;

fn run_libreoffice(source: &Path, destination: &Path) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "LibreOffice 输出缺少父目录".to_string())?;
    let temporary_dir = parent.join(format!(
        ".koi-soffice-{}-{}-{}",
        std::process::id(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    if let Err(error) = fs::create_dir_all(&temporary_dir) {
        return Err(format!("无法创建 LibreOffice 临时目录: {error}"));
    }
    let conversion_result = run_libreoffice_in_directory(source, destination, &temporary_dir);
    let cleanup_result = fs::remove_dir_all(&temporary_dir);
    match (conversion_result, cleanup_result) {
        (Ok(()), Ok(())) => Ok(()),
        (Ok(()), Err(error)) => Err(format!("无法清理 LibreOffice 临时目录: {error}")),
        (Err(error), _) => Err(error),
    }
}

fn run_libreoffice_in_directory(
    source: &Path,
    destination: &Path,
    temporary_dir: &Path,
) -> Result<(), String> {
    let executable = find_soffice().ok_or_else(|| "未找到 LibreOffice/soffice".to_string())?;
    fs::create_dir_all(temporary_dir)
        .map_err(|error| format!("无法创建 LibreOffice 临时目录: {error}"))?;
    let profile_dir = temporary_dir.join("profile");
    fs::create_dir_all(&profile_dir)
        .map_err(|error| format!("无法创建 LibreOffice 隔离配置目录: {error}"))?;
    let profile_url = path_to_file_url(&profile_dir)?;
    let mut command = Command::new(executable);
    command
        .arg(format!("-env:UserInstallation={profile_url}"))
        .args([
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
        ])
        .arg(temporary_dir)
        .arg(source)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let command_result = run_command(command, CONVERSION_TIMEOUT, "LibreOffice");
    let produced = temporary_dir.join(source.with_extension("pdf").file_name().unwrap_or_default());
    let result = command_result.and_then(|_| {
        if !produced.is_file() {
            return Err("LibreOffice 未生成预期 PDF".to_string());
        }
        fs::copy(&produced, destination)
            .map(|_| ())
            .map_err(|error| format!("无法复制 LibreOffice 输出: {error}"))
    });
    result
}

fn path_to_file_url(path: &Path) -> Result<String, String> {
    let absolute = fs::canonicalize(path)
        .map_err(|error| format!("无法解析 LibreOffice 配置目录: {error}"))?;
    let raw = absolute.to_string_lossy();
    let normalized = if let Some(path) = raw.strip_prefix(r"\\?\UNC\") {
        format!("//{}", path.replace('\\', "/"))
    } else {
        raw.strip_prefix(r"\\?\")
            .unwrap_or(raw.as_ref())
            .replace('\\', "/")
    };
    let mut encoded = String::with_capacity(normalized.len() + 16);
    for byte in normalized.as_bytes() {
        if byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'_' | b'.' | b'~' | b'/' | b':')
        {
            encoded.push(*byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    if encoded.starts_with("//") {
        Ok(format!("file:{encoded}"))
    } else if encoded.as_bytes().get(1) == Some(&b':') {
        Ok(format!("file:///{encoded}"))
    } else {
        Ok(format!("file://{encoded}"))
    }
}

fn find_soffice() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    for variable in ["ProgramFiles", "ProgramFiles(x86)"] {
        if let Some(root) = std::env::var_os(variable) {
            candidates.push(PathBuf::from(root).join(r"LibreOffice\program\soffice.exe"));
        }
    }
    if let Some(path) = std::env::var_os("PATH") {
        for directory in std::env::split_paths(&path) {
            candidates.push(directory.join(if cfg!(windows) {
                "soffice.exe"
            } else {
                "soffice"
            }));
            candidates.push(directory.join("libreoffice"));
        }
    }
    candidates.into_iter().find(|path| path.is_file())
}

fn run_command(mut command: Command, timeout: Duration, label: &str) -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_SUSPENDED: u32 = 0x0000_0004;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        // Assignment after a running process is spawned has a real race: the
        // converter can create a child before it joins the Job Object. Start
        // suspended so no descendant can escape the kill-on-close boundary.
        command.creation_flags(CREATE_SUSPENDED | CREATE_NO_WINDOW);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("无法启动 {label}: {error}"))?;
    let process_tree = match ProcessTree::attach(&child) {
        Ok(process_tree) => process_tree,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("无法隔离 {label} 进程树: {error}"));
        }
    };
    #[cfg(windows)]
    if let Err(error) = resume_suspended_process(child.id()) {
        process_tree.terminate();
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!("无法恢复 {label} 进程: {error}"));
    }
    let stdout_reader = child.stdout.take().map(|mut stream| {
        thread::spawn(move || {
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).map(|_| bytes)
        })
    });
    let stderr_reader = child.stderr.take().map(|mut stream| {
        thread::spawn(move || {
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).map(|_| bytes)
        })
    });
    let status = wait_for_child(&mut child, timeout, &process_tree);
    // Closing the kill-on-close job terminates any converter helper that
    // outlived the root process and releases inherited pipe handles.
    drop(process_tree);
    let stdout = join_output(stdout_reader, label)?;
    let stderr = join_output(stderr_reader, label)?;
    let status = status?;
    if status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&stderr);
    let stdout = String::from_utf8_lossy(&stdout);
    let detail = if stderr.trim().is_empty() {
        stdout.trim()
    } else {
        stderr.trim()
    };
    Err(format!(
        "{label} 退出码 {}: {}",
        status.code().unwrap_or(-1),
        truncate_error(detail)
    ))
}

#[cfg(windows)]
fn resume_suspended_process(process_id: u32) -> Result<(), String> {
    use std::mem::size_of;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
    };
    use windows::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) }
        .map_err(|error| format!("无法枚举挂起进程线程: {error}"))?;
    let result = (|| {
        let mut entry = THREADENTRY32 {
            dwSize: size_of::<THREADENTRY32>() as u32,
            ..Default::default()
        };
        unsafe { Thread32First(snapshot, &mut entry) }
            .map_err(|error| format!("无法读取挂起进程线程: {error}"))?;
        let mut resumed = 0usize;
        loop {
            if entry.th32OwnerProcessID == process_id {
                let thread =
                    unsafe { OpenThread(THREAD_SUSPEND_RESUME, false, entry.th32ThreadID) }
                        .map_err(|error| format!("无法打开挂起进程线程: {error}"))?;
                let previous = unsafe { ResumeThread(thread) };
                unsafe { CloseHandle(thread) }.ok();
                if previous == u32::MAX {
                    return Err("恢复挂起进程线程失败".to_string());
                }
                resumed += 1;
            }
            if unsafe { Thread32Next(snapshot, &mut entry) }.is_err() {
                break;
            }
        }
        if resumed == 0 {
            return Err("未找到挂起进程的主线程".to_string());
        }
        Ok(())
    })();
    unsafe { CloseHandle(snapshot) }.ok();
    result
}

fn join_output(
    reader: Option<thread::JoinHandle<std::io::Result<Vec<u8>>>>,
    label: &str,
) -> Result<Vec<u8>, String> {
    match reader {
        Some(reader) => reader
            .join()
            .map_err(|_| format!("读取 {label} 输出的线程异常退出"))?
            .map_err(|error| format!("无法读取 {label} 输出: {error}")),
        None => Ok(Vec::new()),
    }
}

fn wait_for_child(
    child: &mut Child,
    timeout: Duration,
    process_tree: &ProcessTree,
) -> Result<ExitStatus, String> {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(50)),
            Ok(None) => {
                process_tree.terminate();
                let _ = child.kill();
                let _ = child.wait();
                return Err("文档转换超时，已终止转换进程".to_string());
            }
            Err(error) => return Err(format!("无法等待转换进程: {error}")),
        }
    }
}

#[cfg(windows)]
pub(super) struct ProcessTree(windows::Win32::Foundation::HANDLE);

#[cfg(windows)]
impl ProcessTree {
    pub(super) fn attach(child: &Child) -> Result<Self, String> {
        use std::mem::size_of;
        use std::os::windows::io::AsRawHandle;
        use windows::core::PCWSTR;
        use windows::Win32::Foundation::HANDLE;
        use windows::Win32::System::JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        };

        let job = unsafe { CreateJobObjectW(None, PCWSTR::null()) }
            .map_err(|error| format!("无法创建 Job Object: {error}"))?;
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = unsafe {
            SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                std::ptr::from_ref(&limits).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if let Err(error) = configured {
            unsafe { windows::Win32::Foundation::CloseHandle(job) }.ok();
            return Err(format!("无法配置 Job Object: {error}"));
        }
        let process = HANDLE(child.as_raw_handle());
        if let Err(error) = unsafe { AssignProcessToJobObject(job, process) } {
            unsafe { windows::Win32::Foundation::CloseHandle(job) }.ok();
            return Err(format!("无法加入 Job Object: {error}"));
        }
        Ok(Self(job))
    }

    pub(super) fn terminate(&self) {
        unsafe { windows::Win32::System::JobObjects::TerminateJobObject(self.0, 1) }.ok();
    }
}

#[cfg(windows)]
impl Drop for ProcessTree {
    fn drop(&mut self) {
        unsafe { windows::Win32::Foundation::CloseHandle(self.0) }.ok();
    }
}

#[cfg(not(windows))]
pub(super) struct ProcessTree;

#[cfg(not(windows))]
impl ProcessTree {
    pub(super) fn attach(_child: &Child) -> Result<Self, String> {
        Ok(Self)
    }

    pub(super) fn terminate(&self) {}
}

fn validate_output(path: &Path, kind: ConversionType) -> Result<(), String> {
    let metadata = fs::metadata(path).map_err(|_| "转换器未生成输出文件".to_string())?;
    if !metadata.is_file() || metadata.len() < 16 {
        return Err("转换器生成了空或无效文件".to_string());
    }
    match kind {
        ConversionType::WordToPdf => validate_pdf_signature(path, metadata.len()),
        ConversionType::WordToDocx => validate_docx_structure(path, metadata.len()),
        ConversionType::PdfToWord => validate_docx_structure(path, metadata.len()),
    }
}

fn validate_pdf_signature(path: &Path, length: u64) -> Result<(), String> {
    let mut file = File::open(path).map_err(|error| format!("无法验证转换输出: {error}"))?;
    let mut header = [0u8; 8];
    file.read_exact(&mut header)
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    if !header.starts_with(b"%PDF-") {
        return Err("转换输出不是有效 PDF".to_string());
    }
    let tail_length = length.min(64 * 1024) as usize;
    file.seek(SeekFrom::End(-(tail_length as i64)))
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    let mut tail = vec![0u8; tail_length];
    file.read_exact(&mut tail)
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    if !contains_bytes(&tail, b"%%EOF") {
        return Err("转换输出不是完整 PDF".to_string());
    }
    Ok(())
}

fn validate_docx_structure(path: &Path, length: u64) -> Result<(), String> {
    const EOCD_MIN_SIZE: usize = 22;
    const EOCD_MAX_SEARCH: u64 = 65_535 + EOCD_MIN_SIZE as u64;
    const CENTRAL_HEADER_SIZE: usize = 46;

    let mut file = File::open(path).map_err(|error| format!("无法验证转换输出: {error}"))?;
    let tail_length = length.min(EOCD_MAX_SEARCH) as usize;
    file.seek(SeekFrom::End(-(tail_length as i64)))
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    let mut tail = vec![0u8; tail_length];
    file.read_exact(&mut tail)
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    let Some(eocd) = find_signature_from_end(&tail, b"PK\x05\x06") else {
        return Err("转换输出不是有效 DOCX".to_string());
    };
    if tail.len().saturating_sub(eocd) < EOCD_MIN_SIZE {
        return Err("转换输出不是有效 DOCX".to_string());
    }
    let disk = read_u16(&tail[eocd + 4..eocd + 6]);
    let central_disk = read_u16(&tail[eocd + 6..eocd + 8]);
    let disk_entries = read_u16(&tail[eocd + 8..eocd + 10]);
    let entries = read_u16(&tail[eocd + 10..eocd + 12]);
    let central_size = read_u32(&tail[eocd + 12..eocd + 16]) as u64;
    let central_offset = read_u32(&tail[eocd + 16..eocd + 20]) as u64;
    let comment_length = read_u16(&tail[eocd + 20..eocd + 22]) as usize;
    if disk != 0
        || central_disk != 0
        || disk_entries != entries
        || entries == u16::MAX
        || central_size == u32::MAX as u64
        || central_offset == u32::MAX as u64
        || eocd + EOCD_MIN_SIZE + comment_length != tail.len()
        || central_offset
            .checked_add(central_size)
            .is_none_or(|end| end != length - tail_length as u64 + eocd as u64)
    {
        return Err("转换输出不是受支持的 DOCX ZIP 结构".to_string());
    }

    file.seek(SeekFrom::Start(central_offset))
        .map_err(|error| format!("无法读取转换输出: {error}"))?;
    let mut has_content_types = false;
    let mut has_document = false;
    for _ in 0..entries {
        let mut header = [0u8; CENTRAL_HEADER_SIZE];
        file.read_exact(&mut header)
            .map_err(|_| "转换输出不是有效 DOCX".to_string())?;
        if !header.starts_with(b"PK\x01\x02") {
            return Err("转换输出不是有效 DOCX".to_string());
        }
        let name_length = read_u16(&header[28..30]) as usize;
        let extra_length = read_u16(&header[30..32]) as u64;
        let entry_comment_length = read_u16(&header[32..34]) as u64;
        if name_length == 0 || name_length > 65_535 {
            return Err("转换输出不是有效 DOCX".to_string());
        }
        let mut name = vec![0u8; name_length];
        file.read_exact(&mut name)
            .map_err(|_| "转换输出不是有效 DOCX".to_string())?;
        has_content_types |= name == b"[Content_Types].xml";
        has_document |= name == b"word/document.xml";
        let skip = extra_length
            .checked_add(entry_comment_length)
            .ok_or_else(|| "转换输出不是有效 DOCX".to_string())?;
        file.seek(SeekFrom::Current(skip as i64))
            .map_err(|_| "转换输出不是有效 DOCX".to_string())?;
    }
    if !has_content_types || !has_document {
        return Err("转换输出不是有效 DOCX".to_string());
    }
    Ok(())
}

fn contains_bytes(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window == needle)
}

fn find_signature_from_end(haystack: &[u8], signature: &[u8]) -> Option<usize> {
    haystack
        .windows(signature.len())
        .rposition(|window| window == signature)
}

fn read_u16(bytes: &[u8]) -> u16 {
    u16::from_le_bytes([bytes[0], bytes[1]])
}

fn read_u32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

fn replace_output(source: &Path, destination: &Path) -> Result<(), String> {
    replace_output_platform(source, destination)
}

#[cfg(windows)]
fn replace_output_platform(source: &Path, destination: &Path) -> Result<(), String> {
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
    .map_err(|error| format!("无法原子提交转换输出: {error}"))
}

#[cfg(not(windows))]
fn replace_output_platform(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("无法提交转换输出: {error}"))
}

fn truncate_error(value: &str) -> String {
    value.chars().take(500).collect()
}

#[cfg(test)]
mod tests {
    use super::super::protocol::BackendResponse;
    use super::*;
    use serde_json::json;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "koi-document-conversion-{label}-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).expect("create document conversion test directory");
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            if !std::thread::panicking() {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
    }

    #[cfg(windows)]
    fn create_word_fixture(path: &Path) -> Result<(), String> {
        use std::io::Write;
        use zip::write::SimpleFileOptions;
        use zip::{CompressionMethod, ZipWriter};

        const CONTENT_TYPES: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"#;
        const ROOT_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"#;
        const DOCUMENT: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>KOI Rust document conversion smoke test</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>"#;

        let file = File::create(path).map_err(|error| format!("create DOCX fixture: {error}"))?;
        let mut writer = ZipWriter::new(file);
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::DEFLATE);
        for (name, content) in [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", DOCUMENT),
        ] {
            writer
                .start_file(name, options)
                .map_err(|error| format!("write DOCX fixture entry: {error}"))?;
            writer
                .write_all(content.as_bytes())
                .map_err(|error| format!("write DOCX fixture content: {error}"))?;
        }
        writer
            .finish()
            .map(|_| ())
            .map_err(|error| format!("finish DOCX fixture: {error}"))
    }

    #[cfg(windows)]
    fn read_word_text(path: &Path) -> Result<String, String> {
        use quick_xml::events::Event;
        use quick_xml::Reader;
        use zip::ZipArchive;

        let file = File::open(path).map_err(|error| format!("open roundtrip DOCX: {error}"))?;
        let mut archive =
            ZipArchive::new(file).map_err(|error| format!("parse roundtrip DOCX: {error}"))?;
        let mut document = archive
            .by_name("word/document.xml")
            .map_err(|error| format!("roundtrip DOCX lacks document.xml: {error}"))?;
        let mut xml = Vec::new();
        document
            .read_to_end(&mut xml)
            .map_err(|error| format!("read roundtrip document.xml: {error}"))?;
        let mut reader = Reader::from_reader(xml.as_slice());
        reader.config_mut().trim_text(true);
        let mut buffer = Vec::new();
        let mut text = String::new();
        loop {
            match reader.read_event_into(&mut buffer) {
                Ok(Event::Text(value)) => text.push_str(
                    &value
                        .decode()
                        .map_err(|error| format!("decode roundtrip Word text: {error}"))?,
                ),
                Ok(Event::CData(value)) => text.push_str(
                    &value
                        .decode()
                        .map_err(|error| format!("decode roundtrip Word text: {error}"))?,
                ),
                Ok(Event::Eof) => break,
                Ok(_) => {}
                Err(error) => return Err(format!("parse roundtrip Word XML: {error}")),
            }
            buffer.clear();
        }
        Ok(text)
    }

    #[test]
    fn conversion_aliases_are_compatible() {
        assert_eq!(
            ConversionType::parse("Word转PDF").unwrap(),
            ConversionType::WordToPdf
        );
        assert_eq!(
            ConversionType::parse("pdf-word").unwrap(),
            ConversionType::PdfToWord
        );
        assert!(ConversionType::parse("unknown").is_err());
        assert_eq!(
            ConversionType::parse("").unwrap(),
            ConversionType::WordToPdf
        );
        assert!(ConversionType::parse(" ").is_err());
    }

    #[cfg(windows)]
    #[test]
    fn native_word_worker_arguments_are_exact_and_non_ambient() {
        let source = OsString::from(r"C:\input\source.docx");
        let destination = OsString::from(r"C:\output\result.pdf");
        let parsed = parse_word_com_worker_args([
            OsString::from(WORD_COM_WORKER_SWITCH),
            OsString::from(ConversionType::WordToPdf.worker_name()),
            source.clone(),
            destination.clone(),
        ])
        .expect("parse worker arguments")
        .expect("worker switch recognized");
        assert_eq!(
            parsed,
            WordComWorkerRequest {
                source: PathBuf::from(source),
                destination: PathBuf::from(destination),
                kind: ConversionType::WordToPdf,
            }
        );
        assert!(parse_word_com_worker_args([OsString::from("--self-test")])
            .expect("ignore unrelated arguments")
            .is_none());
        assert!(parse_word_com_worker_args([
            OsString::from(WORD_COM_WORKER_SWITCH),
            OsString::from("word-to-pdf"),
            OsString::from(r"C:\input\source.docx"),
            OsString::from(r"C:\output\result.pdf"),
            OsString::from("unexpected"),
        ])
        .is_err());
    }

    #[cfg(windows)]
    #[test]
    fn native_word_worker_rejects_relative_existing_and_mismatched_outputs() {
        let root = TestDir::new("word-worker-boundary");
        let source = root.path().join("source.docx");
        fs::write(&source, b"fixture").unwrap();

        let valid = WordComWorkerRequest {
            source: source.clone(),
            destination: root.path().join("output.pdf"),
            kind: ConversionType::WordToPdf,
        };
        let validated = validate_word_com_worker_request(valid.clone())
            .expect("accept an absolute regular source and new destination");
        assert!(validated.source.is_absolute());
        assert!(validated.destination.is_absolute());

        let mut relative = valid.clone();
        relative.source = PathBuf::from("source.docx");
        assert!(validate_word_com_worker_request(relative).is_err());

        let mut mismatched = valid.clone();
        mismatched.destination = root.path().join("output.docx");
        assert!(validate_word_com_worker_request(mismatched).is_err());

        fs::write(&valid.destination, b"existing").unwrap();
        assert!(validate_word_com_worker_request(valid).is_err());
    }

    #[test]
    fn output_paths_preserve_relative_structure() {
        let source = PathBuf::from(r"C:\input\nested\report.docx");
        let output = output_path(
            &source,
            Path::new(r"C:\input"),
            Some(Path::new(r"D:\output")),
            "pdf",
        );
        assert_eq!(output, PathBuf::from(r"D:\output\nested\report.pdf"));
    }

    #[test]
    fn template_and_office_temporary_files_are_skipped() {
        let keywords = DEFAULT_TEMPLATE_SKIP_KEYWORDS
            .iter()
            .map(|value| (*value).to_string())
            .collect::<Vec<_>>();
        assert!(should_skip_discovered("~$report.docx", &keywords));
        assert!(should_skip_discovered(
            "漏洞隐患处置文件模板.docx",
            &keywords
        ));
        assert!(!should_skip_discovered("customer-report.docx", &keywords));
        assert!(!matches_skip_keyword("~$single.docx", &keywords));
    }

    #[test]
    fn output_signatures_reject_mismatched_formats() {
        let root = std::env::temp_dir().join(format!(
            "koi-convert-signature-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let fake_pdf = root.join("fake.pdf");
        fs::write(&fake_pdf, b"not a pdf file at all").unwrap();
        assert!(validate_output(&fake_pdf, ConversionType::WordToPdf).is_err());
        let fake_docx = root.join("fake.docx");
        fs::write(
            &fake_docx,
            b"PK fake archive containing word/document.xml and [Content_Types].xml",
        )
        .unwrap();
        assert!(validate_output(&fake_docx, ConversionType::PdfToWord).is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn atomic_replace_commits_complete_file() {
        let root = TestDir::new("atomic-replace");
        let source = root.path().join("new.pdf");
        let destination = root.path().join("result.pdf");
        fs::write(&source, b"new-complete-output").unwrap();
        fs::write(&destination, b"old-output").unwrap();
        replace_output(&source, &destination).expect("atomically replace destination");
        assert_eq!(fs::read(&destination).unwrap(), b"new-complete-output");
        assert!(!source.exists());
    }

    #[test]
    fn libreoffice_profile_url_is_encoded_and_absolute() {
        let root = TestDir::new("profile-url");
        let profile = root.path().join("profile space-配置");
        fs::create_dir_all(&profile).unwrap();
        let url = path_to_file_url(&profile).expect("build profile URL");
        assert!(url.starts_with("file:///"), "unexpected file URL: {url}");
        assert!(!url.contains(' '));
        assert!(url.contains("%E9%85%8D%E7%BD%AE"));
    }

    #[cfg(windows)]
    #[test]
    fn output_parent_rejects_reparse_escape() {
        use std::os::windows::process::CommandExt;

        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let root = TestDir::new("output-reparse-escape");
        let boundary = root.path().join("boundary");
        let outside = root.path().join("outside");
        fs::create_dir_all(&boundary).unwrap();
        fs::create_dir_all(&outside).unwrap();
        let link = boundary.join("escape");
        let status = Command::new("cmd.exe")
            .args(["/d", "/c", "mklink", "/J"])
            .arg(&link)
            .arg(&outside)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .expect("create junction fixture");
        assert!(status.success(), "create junction fixture failed");
        let error = prepare_output_parent(&link.join("result.pdf"), &boundary)
            .expect_err("junction must not escape output boundary");
        assert!(error.contains("越过指定目录"));
    }

    #[test]
    fn output_root_inside_input_is_rejected_before_scan() {
        let root = TestDir::new("nested-output-root");
        let input = root.path().join("input");
        fs::create_dir_all(&input).unwrap();
        fs::write(input.join("source.docx"), b"fixture").unwrap();
        let response = rust_stub_call(json!({
            "input_path": input,
            "output_dir": root.path().join("input/output"),
        }));
        assert!(!response.ok);
        assert!(response
            .error
            .as_deref()
            .is_some_and(|error| error.contains("输出目录不能位于输入目录内")));
    }

    #[cfg(windows)]
    #[test]
    fn timeout_terminates_the_managed_process_tree() {
        use std::os::windows::process::CommandExt;
        use windows::Win32::Foundation::{CloseHandle, STILL_ACTIVE};
        use windows::Win32::System::Threading::{
            GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
        };

        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        const SCRIPT: &str = r#"$ErrorActionPreference='Stop';$child=Start-Process -FilePath $env:KOI_POWERSHELL -ArgumentList '-NoLogo','-NoProfile','-NonInteractive','-Command','Start-Sleep -Seconds 30' -PassThru;[IO.File]::WriteAllText($env:KOI_CHILD_PID,[string]$child.Id);Start-Sleep -Seconds 30"#;
        let root = TestDir::new("process-tree-timeout");
        let child_pid_file = root.path().join("child.pid");
        let executable = std::env::var_os("SystemRoot")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(r"C:\Windows"))
            .join(r"System32\WindowsPowerShell\v1.0\powershell.exe");
        let mut command = Command::new(&executable);
        command
            .args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                SCRIPT,
            ])
            .env("KOI_POWERSHELL", &executable)
            .env("KOI_CHILD_PID", &child_pid_file)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(CREATE_NO_WINDOW);
        // A clean Windows test process may spend several seconds starting
        // PowerShell before it can create the child and write its PID. Keep
        // the converter timeout short enough to exercise termination while
        // allowing that one-time startup cost.
        let error = run_command(command, Duration::from_secs(10), "timeout fixture")
            .expect_err("fixture must time out");
        assert!(error.contains("超时"), "unexpected timeout error: {error}");
        let child_pid: u32 = fs::read_to_string(&child_pid_file)
            .expect("child PID fixture")
            .parse()
            .expect("numeric child PID");
        thread::sleep(Duration::from_millis(200));
        let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, child_pid) };
        if let Ok(handle) = process {
            let mut exit_code = 0u32;
            let status = unsafe { GetExitCodeProcess(handle, &mut exit_code) };
            unsafe { CloseHandle(handle) }.ok();
            status.expect("query managed child exit code");
            assert_ne!(
                exit_code, STILL_ACTIVE.0 as u32,
                "managed child process {child_pid} survived timeout"
            );
        }
    }

    fn rust_stub_call(payload: Value) -> BackendResponse {
        let request: ConvertRequest = match serde_json::from_value(payload) {
            Ok(request) => request,
            Err(error) => {
                return BackendResponse::failure(format!("请求字段格式不正确: {error}"));
            }
        };
        let response = convert_with(request, |job, _| {
            if job
                .source
                .file_name()
                .and_then(|value| value.to_str())
                .is_some_and(|name| name.contains("fail"))
            {
                return Err("stub conversion failure".to_string());
            }
            prepare_output_parent(&job.destination, &job.output_boundary)?;
            fs::write(&job.destination, b"KOI-CONVERT-STUB").map_err(|error| error.to_string())
        });
        match response
            .and_then(|response| serde_json::to_value(response).map_err(|error| error.to_string()))
        {
            Ok(data) => BackendResponse::success(data),
            Err(error) => BackendResponse::failure(error),
        }
    }

    fn python_oracle_fixture() -> Value {
        let fixture_text = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/fixtures/python_oracle/document_conversion.v1.json"
        ));
        let fixture: Value = serde_json::from_str(fixture_text)
            .expect("parse document conversion Python oracle fixture");
        assert_eq!(fixture["format"], "koi-python-oracle-golden-v1");
        assert_eq!(fixture["command"], "doc.convert.run");
        assert_eq!(fixture["normalization"]["redacted_fields"], json!([]));
        let fixture_lower = fixture_text.to_ascii_lowercase();
        for forbidden in ["api_key", "cookie", "authorization", "bearer ", "password"] {
            assert!(
                !fixture_lower.contains(forbidden),
                "golden fixture contains forbidden secret marker {forbidden}"
            );
        }
        fixture
    }

    fn fixture_expected(fixture: &Value, group: &str, name: &str) -> Value {
        fixture["groups"][group]
            .as_array()
            .expect("fixture group array")
            .iter()
            .find(|case| case["name"].as_str() == Some(name))
            .unwrap_or_else(|| panic!("missing golden case {group}/{name}"))["expected"]
            .clone()
    }

    fn fixture_fingerprint(fixture: &Value, group: &str, name: &str) -> Value {
        fixture["groups"][group]
            .as_array()
            .expect("fixture group array")
            .iter()
            .find(|case| case["name"].as_str() == Some(name))
            .unwrap_or_else(|| panic!("missing golden case {group}/{name}"))["output_fingerprint"]
            .clone()
    }

    fn output_fingerprint(root: &Path) -> Value {
        use sha2::Digest;

        fn visit(root: &Path, directory: &Path, entries: &mut Vec<Value>) {
            let mut children = fs::read_dir(directory)
                .expect("read output fingerprint directory")
                .collect::<Result<Vec<_>, _>>()
                .expect("read output fingerprint entries");
            children.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
            for entry in children {
                let path = entry.path();
                let relative = path
                    .strip_prefix(root)
                    .expect("output entry under test root")
                    .to_string_lossy()
                    .replace('\\', "/");
                if path.is_dir() {
                    entries.push(json!({"path": relative, "kind": "dir"}));
                    visit(root, &path, entries);
                } else {
                    let bytes = fs::read(&path).expect("read output fingerprint file");
                    let digest = sha2::Sha256::digest(&bytes);
                    entries.push(json!({
                        "path": relative,
                        "kind": "file",
                        "size": bytes.len(),
                        "sha256": format!("{digest:x}"),
                    }));
                }
            }
        }

        let output = root.join("output");
        let mut entries = Vec::new();
        if output.is_dir() {
            visit(root, &output, &mut entries);
        }
        Value::Array(entries)
    }

    fn normalize_test_paths(response: &mut BackendResponse, root: &Path) {
        fn normalize(value: &mut Value, root: &str) {
            match value {
                Value::String(text) => {
                    let normalized = text.replace(r"\\?\", "");
                    *text = normalized.replace(root, "<ROOT>");
                }
                Value::Array(values) => {
                    for value in values {
                        normalize(value, root);
                    }
                }
                Value::Object(values) => {
                    for value in values.values_mut() {
                        normalize(value, root);
                    }
                }
                _ => {}
            }
        }
        let root = root.to_string_lossy().replace(r"\\?\", "");
        normalize(&mut response.data, &root);
        if let Some(error) = response.error.as_mut() {
            *error = error.replace(r"\\?\", "").replace(&root, "<ROOT>");
        }
    }

    fn create_word_tree(root: &Path) {
        fs::create_dir_all(root.join("input/nested")).unwrap();
        fs::create_dir_all(root.join("output")).unwrap();
        for relative in [
            "input/root.docx",
            "input/nested/report.doc",
            "input/nested/fail.docx",
            "input/nested/ignore-secret.docx",
            "input/处置文件模板.docx",
            "input/~$temporary.docx",
        ] {
            fs::write(root.join(relative), b"fixture").unwrap();
        }
        fs::write(root.join("input/notes.txt"), b"ignored").unwrap();
        fs::write(root.join("output/root.pdf"), b"existing").unwrap();
    }

    #[test]
    fn protocol_matches_redacted_python_golden_for_scan_filter_overwrite_failures_and_structure() {
        let fixture = python_oracle_fixture();
        let rust_root = TestDir::new("protocol-rust");
        create_word_tree(rust_root.path());

        let make_payload = |root: &Path| {
            json!({
                "conversion_type": "word_to_pdf",
                "input_path": root.join("input"),
                "output_dir": root.join("output"),
                "recursive": "false",
                "overwrite": false,
                "skip_template": true,
                "skip_keywords": "ignore-secret",
            })
        };
        let mut rust_response = rust_stub_call(make_payload(rust_root.path()));
        normalize_test_paths(&mut rust_response, rust_root.path());
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust response"),
            fixture_expected(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "scan-filter-overwrite-failures"
            )
        );
        assert_eq!(
            output_fingerprint(rust_root.path()),
            fixture_fingerprint(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "scan-filter-overwrite-failures"
            )
        );
        assert_eq!(rust_response.data["total"], 3);
        assert_eq!(rust_response.data["converted"], 1);
        assert_eq!(rust_response.data["skipped"], 1);
        assert_eq!(rust_response.data["failures"].as_array().unwrap().len(), 1);
        assert!(rust_root.path().join("output/nested/report.pdf").is_file());
        assert!(!rust_root.path().join("output/nested/fail.pdf").exists());
        assert!(!rust_root
            .path()
            .join("output/nested/ignore-secret.pdf")
            .exists());
        assert!(!rust_root.path().join("output/处置文件模板.pdf").exists());
        assert!(!rust_root.path().join("output/~$temporary.pdf").exists());

        let make_non_recursive_payload = |root: &Path| {
            json!({
                "input_path": root.join("input"),
                "output_dir": root.join("output"),
                "recursive": false,
                "overwrite": false,
            })
        };
        let mut rust_response = rust_stub_call(make_non_recursive_payload(rust_root.path()));
        normalize_test_paths(&mut rust_response, rust_root.path());
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust response"),
            fixture_expected(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "non-recursive-existing-output"
            )
        );
        assert_eq!(
            output_fingerprint(rust_root.path()),
            fixture_fingerprint(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "non-recursive-existing-output"
            )
        );
        assert_eq!(rust_response.data["total"], 1);
        assert_eq!(rust_response.data["skipped"], 1);

        let make_single_temporary_payload = |root: &Path| {
            json!({
                "input_path": root.join("input/~$temporary.docx"),
                "output_dir": root.join("output"),
            })
        };
        let mut rust_response = rust_stub_call(make_single_temporary_payload(rust_root.path()));
        normalize_test_paths(&mut rust_response, rust_root.path());
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust response"),
            fixture_expected(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "explicit-temporary-file"
            )
        );
        assert_eq!(
            output_fingerprint(rust_root.path()),
            fixture_fingerprint(
                &fixture,
                "scan_filter_overwrite_failures_and_structure",
                "explicit-temporary-file"
            )
        );
        assert!(rust_root.path().join("output/~$temporary.pdf").exists());
    }

    #[test]
    fn protocol_matches_redacted_python_golden_for_pdf_logs_and_early_errors() {
        let fixture = python_oracle_fixture();
        let rust_root = TestDir::new("pdf-protocol-rust");
        fs::create_dir_all(rust_root.path().join("input/nested")).unwrap();
        fs::create_dir_all(rust_root.path().join("output")).unwrap();
        fs::write(rust_root.path().join("input/report.pdf"), b"fixture").unwrap();
        fs::write(rust_root.path().join("input/nested/fail.pdf"), b"fixture").unwrap();
        fs::write(rust_root.path().join("output/report.docx"), b"existing").unwrap();
        let make_payload = |root: &Path| {
            json!({
                "conversion_type": "PDF转Word",
                "input_path": root.join("input"),
                "output_dir": root.join("output"),
                "overwrite": false,
            })
        };
        let mut rust_response = rust_stub_call(make_payload(rust_root.path()));
        normalize_test_paths(&mut rust_response, rust_root.path());
        assert_eq!(
            serde_json::to_value(&rust_response).expect("serialize Rust response"),
            fixture_expected(
                &fixture,
                "pdf_logs_and_early_errors",
                "pdf-logs-skip-and-failure"
            )
        );
        assert_eq!(
            output_fingerprint(rust_root.path()),
            fixture_fingerprint(
                &fixture,
                "pdf_logs_and_early_errors",
                "pdf-logs-skip-and-failure"
            )
        );

        let rust_missing = rust_root.path().join("missing.docx");
        let cases = [
            ("missing-fields", json!({})),
            (
                "blank-conversion-type",
                json!({"conversion_type": " ", "input_path": "unused"}),
            ),
            ("missing-input-path", json!({"input_path": rust_missing})),
            (
                "extension-mismatch",
                json!({"input_path": rust_root.path().join("input/report.pdf")}),
            ),
            (
                "output-directory-is-file",
                json!({
                    "input_path": rust_root.path().join("input/report.pdf"),
                    "conversion_type": "pdf_to_word",
                    "output_dir": rust_root.path().join("input/report.pdf"),
                }),
            ),
        ];
        for (name, rust_payload) in cases {
            let mut rust_response = rust_stub_call(rust_payload);
            normalize_test_paths(&mut rust_response, rust_root.path());
            assert_eq!(
                serde_json::to_value(&rust_response).expect("serialize Rust response"),
                fixture_expected(&fixture, "pdf_logs_and_early_errors", name),
                "Rust response mismatch for golden case {name}"
            );
            assert_eq!(
                output_fingerprint(rust_root.path()),
                fixture_fingerprint(&fixture, "pdf_logs_and_early_errors", name),
                "output side effects mismatch for golden case {name}"
            );
        }
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "requires Microsoft Word in an interactive Windows logon session"]
    fn word_com_converts_both_directions_with_valid_outputs() {
        let root = TestDir::new("word-com-smoke");
        let source = root.path().join("source.docx");
        create_word_fixture(&source).expect("create Word fixture");
        validate_output(&source, ConversionType::PdfToWord).expect("validate source DOCX");

        let pdf = root.path().join("roundtrip.pdf");
        let first = ConversionJob {
            source: source.clone(),
            destination: pdf.clone(),
            output_boundary: root.path().to_path_buf(),
        };
        assert_eq!(
            convert_one(&first, ConversionType::WordToPdf).unwrap(),
            "word-com"
        );
        validate_output(&pdf, ConversionType::WordToPdf).expect("validate generated PDF");

        let docx = root.path().join("roundtrip.docx");
        let second = ConversionJob {
            source: pdf,
            destination: docx.clone(),
            output_boundary: root.path().to_path_buf(),
        };
        assert_eq!(
            convert_one(&second, ConversionType::PdfToWord).unwrap(),
            "word-com"
        );
        validate_output(&docx, ConversionType::PdfToWord).expect("validate generated DOCX");
        let text = read_word_text(&docx).expect("read roundtrip Word text");
        assert!(text.contains("KOI Rust document conversion smoke test"));
    }
}
