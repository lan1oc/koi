use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::UNIX_EPOCH;

#[derive(Debug, Default, Deserialize)]
struct ListDirRequest {
    #[serde(default, deserialize_with = "deserialize_compat_string")]
    path: Option<String>,
    #[serde(
        default,
        alias = "recoverMissingAncestor",
        deserialize_with = "deserialize_compat_bool"
    )]
    recover_missing_ancestor: bool,
    #[serde(
        default,
        alias = "showHidden",
        deserialize_with = "deserialize_compat_bool"
    )]
    show_hidden: bool,
    #[serde(default, deserialize_with = "deserialize_string_array")]
    extensions: Vec<String>,
}

#[derive(Debug, Default, Deserialize)]
struct PathRequest {
    #[serde(default, deserialize_with = "deserialize_compat_string")]
    path: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct RetestOutputRequest {
    #[serde(
        default,
        alias = "targetDir",
        deserialize_with = "deserialize_compat_string"
    )]
    target_dir: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct OpenUrlRequest {
    #[serde(default, deserialize_with = "deserialize_compat_string")]
    url: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct ExportTextRequest {
    #[serde(
        default,
        alias = "outputFile",
        deserialize_with = "deserialize_compat_string"
    )]
    output_file: Option<String>,
    #[serde(default, deserialize_with = "deserialize_compat_string")]
    content: Option<String>,
}

#[derive(Debug, Serialize)]
struct RootEntry {
    path: String,
    name: String,
    #[serde(rename = "type")]
    kind: String,
}

#[derive(Debug, Serialize)]
struct RootsResponse {
    cwd: String,
    home: String,
    roots: Vec<RootEntry>,
    shortcuts: Vec<RootEntry>,
}

#[derive(Debug, Serialize)]
struct DirectoryEntryResponse {
    name: String,
    path: String,
    is_dir: bool,
    extension: String,
    size: Option<u64>,
    size_text: String,
    modified: Option<u64>,
    hidden: bool,
    matches_filter: bool,
}

#[derive(Debug, Serialize)]
struct ListDirResponse {
    path: String,
    parent: Option<String>,
    entries: Vec<DirectoryEntryResponse>,
    separator: String,
    recovered_from: Option<String>,
}

#[derive(Debug, Serialize)]
struct PathInfoResponse {
    path: String,
    exists: bool,
    is_dir: bool,
    is_file: bool,
    parent: String,
    name: String,
}

#[derive(Debug, Serialize)]
struct PathActionResponse {
    success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    path: Option<String>,
}

#[derive(Debug, Serialize)]
struct UrlActionResponse {
    success: bool,
    message: String,
    url: String,
}

#[derive(Debug, Serialize)]
struct ExportTextResponse {
    success: bool,
    message: String,
    output_file: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    bytes: Option<usize>,
}

pub fn roots(cwd: &Path, home: &Path) -> Result<Value, String> {
    let root = if cfg!(windows) { "" } else { "/" };
    let roots = if root.is_empty() {
        windows_roots()
    } else {
        vec![RootEntry {
            path: "/".to_string(),
            name: "/".to_string(),
            kind: "root".to_string(),
        }]
    };
    let shortcuts = [
        (home.to_path_buf(), "用户目录", "home"),
        (home.join("Desktop"), "桌面", "shortcut"),
        (home.join("Documents"), "文档", "shortcut"),
        (home.join("Downloads"), "下载", "shortcut"),
    ]
    .into_iter()
    .filter(|(path, _, _)| path.exists())
    .map(|(path, name, kind)| RootEntry {
        path: path.to_string_lossy().into_owned(),
        name: name.to_string(),
        kind: kind.to_string(),
    })
    .collect::<Vec<_>>();

    serialize_response(RootsResponse {
        cwd: cwd.to_string_lossy().into_owned(),
        home: home.to_string_lossy().into_owned(),
        roots,
        shortcuts,
    })
}

pub fn list_dir(
    payload: &Value,
    fallback_cwd: &Path,
    fallback_home: &Path,
) -> Result<Value, String> {
    let request: ListDirRequest = parse_request(payload)?;
    let requested = request
        .path
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .map(|value| normalize_path(value, fallback_home))
        .unwrap_or_else(|| fallback_home.to_path_buf());
    let mut current = requested.clone();
    let recover = request.recover_missing_ancestor;
    if current.is_file() {
        current = current
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| fallback_cwd.to_path_buf());
    }
    let mut recovered_from = None;
    if !current.exists() {
        if !recover {
            return Err(format!("Path does not exist: {}", current.display()));
        }
        recovered_from = Some(requested.to_string_lossy().to_string());
        current = nearest_existing_directory(&current)
            .or_else(|| nearest_existing_directory(fallback_home))
            .ok_or_else(|| {
                format!(
                    "Path does not exist and no parent directory is available: {}",
                    requested.display()
                )
            })?;
    }
    if !current.is_dir() {
        return Err(format!("Not a directory: {}", current.display()));
    }

    let show_hidden = request.show_hidden;
    let extensions = request
        .extensions
        .into_iter()
        .map(|value| value.trim().trim_start_matches('.').to_ascii_lowercase())
        .filter(|value| !value.is_empty() && value != "*")
        .collect::<Vec<_>>();

    let mut entries = Vec::new();
    let iterator = fs::read_dir(&current)
        .map_err(|error| format!("Permission denied: {} ({error})", current.display()))?;
    for item in iterator {
        let entry = item.map_err(|error| error.to_string())?;
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        let hidden = name.starts_with('.');
        if hidden && !show_hidden {
            continue;
        }
        let metadata = fs::metadata(&path).ok();
        let is_dir = metadata.as_ref().is_some_and(|value| value.is_dir());
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let matches_filter = is_dir || extensions.is_empty() || extensions.contains(&extension);
        let size = if is_dir {
            None
        } else {
            metadata.as_ref().map(|value| value.len())
        };
        let modified = metadata
            .as_ref()
            .and_then(|value| value.modified().ok())
            .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
            .map(|value| value.as_secs());
        entries.push(DirectoryEntryResponse {
            name,
            path: path.to_string_lossy().into_owned(),
            is_dir,
            extension,
            size,
            size_text: size.map(format_size).unwrap_or_default(),
            modified,
            hidden,
            matches_filter,
        });
    }
    entries.sort_by(|left, right| {
        right
            .is_dir
            .cmp(&left.is_dir)
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });

    let parent = current
        .parent()
        .filter(|value| *value != current)
        .map(display_parent);
    serialize_response(ListDirResponse {
        path: current.to_string_lossy().into_owned(),
        parent,
        entries,
        separator: std::path::MAIN_SEPARATOR.to_string(),
        recovered_from,
    })
}

pub fn path_info(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    let request: PathRequest = parse_request_or_default(payload)?;
    let path = request
        .path
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .map(|value| normalize_path(value, fallback_home))
        .unwrap_or_else(|| fallback_home.to_path_buf());
    let exists = path.exists();
    serialize_response(PathInfoResponse {
        path: path.to_string_lossy().into_owned(),
        exists,
        is_dir: exists && path.is_dir(),
        is_file: exists && path.is_file(),
        parent: path.parent().map(display_parent).unwrap_or_default(),
        name: path
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_default(),
    })
}

/// Open a path with the operating system's default file manager.
///
/// The Python implementation deliberately opens a containing directory when
/// the requested target is a file. Keep that behavior here so callers can use
/// this command for both generated files and directories.
pub fn open_path(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    let request: PathRequest = parse_request_or_default(payload)?;
    let target = request
        .path
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .map(|value| normalize_path(&value, fallback_home))
        .unwrap_or_else(|| fallback_home.to_path_buf());
    if !target.exists() {
        return serialize_response(PathActionResponse {
            success: false,
            message: format!("Path does not exist: {}", target.display()),
            path: Some(target.to_string_lossy().into_owned()),
        });
    }

    let open_target = open_target_for_path(&target);
    let opened = open_with_system(open_target);
    serialize_response(PathActionResponse {
        success: opened.is_ok(),
        message: match opened {
            Ok(()) => format!("Opened: {}", open_target.display()),
            Err(error) => format!("Unable to open path: {error}"),
        },
        path: Some(open_target.to_string_lossy().into_owned()),
    })
}

/// Open a document path using the document-processing command's protocol.
///
/// This intentionally remains separate from [`open_path`]: the two commands
/// have different validation and user-facing message contracts. The Python
/// document handler requires a non-empty path and reports validation failures
/// through the outer protocol error, while existence/open failures are data
/// values containing `success`, `message`, and `path`.
pub fn open_document_path(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    let request: PathRequest = parse_request(payload)?;
    let target_text = required_compat_text(request.path, "请选择要打开的路径")?;
    let target = normalize_path(&target_text, fallback_home);
    if !target.exists() {
        return serialize_response(PathActionResponse {
            success: false,
            message: format!("路径不存在: {}", target.display()),
            path: Some(target.to_string_lossy().into_owned()),
        });
    }

    let open_target = open_target_for_path(&target);
    let opened = open_with_system(open_target);
    serialize_response(PathActionResponse {
        success: opened.is_ok(),
        message: match opened {
            Ok(()) => format!("已打开: {}", open_target.display()),
            Err(error) => format!("无法打开: {error}"),
        },
        path: Some(open_target.to_string_lossy().into_owned()),
    })
}

/// Open the directory containing AI retest output.
///
/// The retest command has a distinct payload key and response wording from
/// the generic/document open commands, so keep its compatibility behavior
/// explicit instead of routing it through a generic alias.
pub fn open_retest_output(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    let request: RetestOutputRequest = parse_request(payload)?;
    let target_text = required_compat_text(request.target_dir, "请选择通报目录")?;
    let target_dir = normalize_path(&target_text, fallback_home);
    if !target_dir.exists() || !target_dir.is_dir() {
        return serialize_response(PathActionResponse {
            success: false,
            message: format!("目录不存在: {}", target_dir.display()),
            path: None,
        });
    }

    let opened = open_with_system(&target_dir);
    serialize_response(PathActionResponse {
        success: opened.is_ok(),
        message: match opened {
            Ok(()) => "已打开报告目录".to_string(),
            Err(error) => format!("无法打开报告目录: {error}"),
        },
        path: Some(target_dir.to_string_lossy().into_owned()),
    })
}

/// Open a validated HTTP(S) URL with the operating system's default browser.
pub fn open_url(payload: &Value) -> Result<Value, String> {
    let request: OpenUrlRequest = parse_request_or_default(payload)?;
    let url = request.url.unwrap_or_default().trim().to_string();
    if !is_http_url(&url) {
        return serialize_response(UrlActionResponse {
            success: false,
            message: "Invalid URL".to_string(),
            url,
        });
    }

    let opened = open_with_system(&PathBuf::from(&url));
    serialize_response(UrlActionResponse {
        success: opened.is_ok(),
        message: match opened {
            Ok(()) => format!("Opened URL: {url}"),
            Err(error) => format!("Unable to open URL: {error}"),
        },
        url,
    })
}

fn is_http_url(value: &str) -> bool {
    let Some((scheme, remainder)) = value.split_once("://") else {
        return false;
    };
    if !matches!(scheme.to_ascii_lowercase().as_str(), "http" | "https") {
        return false;
    }
    let authority = remainder.split(['/', '?', '#']).next().unwrap_or_default();
    !authority.is_empty()
}

fn open_target_for_path(target: &Path) -> &Path {
    if target.is_file() {
        target
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."))
    } else {
        target
    }
}

fn open_with_system(target: &Path) -> Result<(), String> {
    #[cfg(windows)]
    let mut command = {
        // Explorer accepts both filesystem paths and HTTP(S) URLs and avoids
        // invoking a shell, so characters such as '&' remain inert.
        let mut command = Command::new("explorer.exe");
        command.arg(target);
        command
    };
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(target);
        command
    };
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(target);
        command
    };

    command
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub fn export_text(payload: &Value, fallback_home: &Path) -> Result<Value, String> {
    let request: ExportTextRequest = parse_request(payload)?;
    let output_file = required_compat_text(request.output_file, "请选择导出文件")?;
    let output_path = normalize_path(&output_file, fallback_home);
    let content = request.content.unwrap_or_default();

    if content.trim().is_empty() {
        return serialize_response(ExportTextResponse {
            success: false,
            message: "没有可导出的内容".to_string(),
            output_file: output_path.to_string_lossy().into_owned(),
            bytes: None,
        });
    }

    if let Some(parent) = output_path
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)
            .map_err(|error| format!("创建导出目录失败: {} ({error})", parent.display()))?;
    }
    let encoded_content = encode_text_content(&content);
    let mut bytes = Vec::with_capacity(encoded_content.len() + 3);
    bytes.extend_from_slice(&[0xEF, 0xBB, 0xBF]);
    bytes.extend_from_slice(&encoded_content);
    fs::write(&output_path, &bytes)
        .map_err(|error| format!("写入导出文件失败: {} ({error})", output_path.display()))?;
    serialize_response(ExportTextResponse {
        success: true,
        message: format!("导出完成: {}", output_path.display()),
        output_file: output_path.to_string_lossy().into_owned(),
        bytes: Some(bytes.len()),
    })
}

fn encode_text_content(content: &str) -> Vec<u8> {
    if !cfg!(windows) {
        return content.as_bytes().to_vec();
    }

    // Python's text-mode UTF-8-sig writer translates every LF to CRLF on Windows.
    let mut bytes =
        Vec::with_capacity(content.len() + content.bytes().filter(|byte| *byte == b'\n').count());
    for byte in content.bytes() {
        if byte == b'\n' {
            bytes.push(b'\r');
        }
        bytes.push(byte);
    }
    bytes
}

fn nearest_existing_directory(path: &Path) -> Option<PathBuf> {
    let mut candidate = path.to_path_buf();
    loop {
        if candidate.exists() {
            return if candidate.is_file() {
                candidate.parent().map(Path::to_path_buf)
            } else {
                Some(candidate)
            };
        }
        let parent = candidate.parent()?.to_path_buf();
        if parent == candidate {
            return None;
        }
        candidate = parent;
    }
}

fn normalize_path(value: &str, home: &Path) -> PathBuf {
    let value = value.trim();
    if value == "~" {
        return home.to_path_buf();
    }
    if let Some(relative) = value
        .strip_prefix("~/")
        .or_else(|| value.strip_prefix("~\\"))
    {
        return home.join(relative);
    }
    PathBuf::from(value)
}

fn display_parent(path: &Path) -> String {
    if path.as_os_str().is_empty() {
        ".".to_string()
    } else {
        path.to_string_lossy().to_string()
    }
}

fn json_truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) | Some(Value::Bool(false)) => false,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|number| number != 0.0),
        Some(Value::String(value)) => !value.is_empty(),
        Some(Value::Array(value)) => !value.is_empty(),
        Some(Value::Object(value)) => !value.is_empty(),
        Some(Value::Bool(true)) => true,
    }
}

fn required_compat_text(value: Option<String>, message: &str) -> Result<String, String> {
    let value = value.unwrap_or_default().trim().to_string();
    if value.is_empty() {
        Err(message.to_string())
    } else {
        Ok(value)
    }
}

fn parse_request<T: DeserializeOwned>(payload: &Value) -> Result<T, String> {
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn parse_request_or_default<T: DeserializeOwned + Default>(payload: &Value) -> Result<T, String> {
    if !payload.is_object() {
        return Ok(T::default());
    }
    parse_request(payload)
}

fn serialize_response<T: Serialize>(response: T) -> Result<Value, String> {
    serde_json::to_value(response).map_err(|error| format!("文件系统响应序列化失败: {error}"))
}

fn deserialize_compat_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value
        .as_ref()
        .filter(|value| json_truthy(Some(value)))
        .map(value_to_string))
}

fn deserialize_compat_bool<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(json_truthy(value.as_ref()))
}

fn deserialize_string_array<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value
        .as_ref()
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(ToOwned::to_owned)
        .collect())
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

fn format_size(size: u64) -> String {
    if size < 1024 {
        return format!("{size} B");
    }
    let units = ["KB", "MB", "GB", "TB"];
    let mut value = size as f64;
    for unit in units {
        value /= 1024.0;
        if value < 1024.0 || unit == "TB" {
            return format!("{value:.1} {unit}");
        }
    }
    format!("{size} B")
}

#[cfg(test)]
#[allow(clippy::items_after_test_module)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn http_url_validation_matches_protocol_boundary() {
        assert!(is_http_url("http://example.test/path?q=1#fragment"));
        assert!(is_http_url("HTTPS://example.test"));
        assert!(!is_http_url(""));
        assert!(!is_http_url("ftp://example.test"));
        assert!(!is_http_url("https:///missing-host"));
        assert!(!is_http_url("https://?missing-host"));
    }

    #[test]
    fn typed_requests_keep_legacy_truthiness_and_camel_case_aliases() {
        let request: ListDirRequest = parse_request(&json!({
            "path": 42,
            "recoverMissingAncestor": 1,
            "showHidden": "yes",
            "extensions": [".DOCX", 3, "*"]
        }))
        .expect("typed list request");
        assert_eq!(request.path.as_deref(), Some("42"));
        assert!(request.recover_missing_ancestor);
        assert!(request.show_hidden);
        assert_eq!(request.extensions, vec![".DOCX", "*"]);

        let export: ExportTextRequest = parse_request(&json!({
            "outputFile": " report.txt ",
            "content": true
        }))
        .expect("typed export request");
        assert_eq!(export.output_file.as_deref(), Some(" report.txt "));
        assert_eq!(export.content.as_deref(), Some("True"));
    }

    #[test]
    fn open_url_rejects_invalid_urls_without_launching_a_process() {
        let response = open_url(&json!({"url": "file:///tmp/report.txt"})).unwrap();
        assert_eq!(
            response,
            json!({
                "success": false,
                "message": "Invalid URL",
                "url": "file:///tmp/report.txt",
            })
        );
    }

    #[test]
    fn open_path_reports_missing_target_without_launching_a_process() {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let missing = std::env::temp_dir().join(format!(
            "koi-open-path-missing-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        ));
        assert!(!missing.exists());
        let response = open_path(&json!({"path": missing}), Path::new("C:\\home")).unwrap();
        assert_eq!(response["success"], false);
        assert_eq!(
            response["message"],
            format!("Path does not exist: {}", missing.display())
        );
    }

    #[test]
    fn document_open_path_requires_a_nonempty_path() {
        let error = open_document_path(&json!({"path": "  "}), Path::new("C:\\home"))
            .expect_err("blank document path must be a protocol validation error");
        assert_eq!(error, "请选择要打开的路径");
    }

    #[test]
    fn document_open_path_reports_missing_target_without_launching_a_process() {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let missing = std::env::temp_dir().join(format!(
            "koi-document-open-path-missing-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        ));
        assert!(!missing.exists());
        let response = open_document_path(&json!({"path": missing}), Path::new("C:\\home"))
            .expect("missing targets return a data response");
        assert_eq!(
            response,
            json!({
                "success": false,
                "message": format!("路径不存在: {}", missing.display()),
                "path": missing.to_string_lossy(),
            })
        );
    }

    #[test]
    fn retest_output_requires_directory_and_keeps_missing_response_isolated() {
        let missing = std::env::temp_dir().join(format!(
            "koi-retest-output-missing-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock must be after epoch")
                .as_nanos(),
        ));
        assert!(!missing.exists());
        let error = open_retest_output(&json!({"target_dir": "  "}), Path::new("C:\\home"))
            .expect_err("blank retest directory must fail validation");
        assert_eq!(error, "请选择通报目录");

        let response = open_retest_output(
            &json!({"target_dir": missing.clone()}),
            Path::new("C:\\home"),
        )
        .expect("missing directory returns a data response");
        assert_eq!(
            response,
            json!({
                "success": false,
                "message": format!("目录不存在: {}", missing.display()),
            })
        );
    }

    #[test]
    fn retest_output_accepts_an_existing_directory_without_starting_test_data() {
        let directory = std::env::temp_dir().join(format!(
            "koi-retest-output-dir-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock must be after epoch")
                .as_nanos(),
        ));
        fs::create_dir_all(&directory).expect("create isolated retest output directory");
        // Validate the path branch without invoking the platform opener.
        assert!(directory.is_dir());
        fs::remove_dir(&directory).expect("remove isolated retest output directory");
    }

    #[test]
    fn file_targets_open_their_parent_directory() {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let directory = std::env::temp_dir().join(format!(
            "koi-open-target-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        ));
        fs::create_dir_all(&directory).expect("create isolated open-target directory");
        let file = directory.join("report.docx");
        fs::write(&file, b"fixture").expect("write isolated open-target fixture");
        assert_eq!(open_target_for_path(&file), directory.as_path());
        fs::remove_file(file).expect("remove isolated open-target fixture");
        fs::remove_dir(directory).expect("remove isolated open-target directory");
    }
}

#[cfg(windows)]
fn windows_roots() -> Vec<RootEntry> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Storage::FileSystem::{GetLogicalDrives, GetVolumeInformationW};
    let bitmask = unsafe { GetLogicalDrives() };
    (0..26)
        .filter(|index| bitmask & (1 << index) != 0)
        .map(|index| {
            let drive = format!("{}:\\", char::from(b'A' + index as u8));
            let root_wide = std::ffi::OsStr::new(&drive)
                .encode_wide()
                .chain(Some(0))
                .collect::<Vec<_>>();
            let mut volume_name = [0_u16; 1024];
            let label = unsafe {
                GetVolumeInformationW(
                    PCWSTR(root_wide.as_ptr()),
                    Some(&mut volume_name),
                    None,
                    None,
                    None,
                    None,
                )
            }
            .ok()
            .and_then(|_| {
                let end = volume_name
                    .iter()
                    .position(|value| *value == 0)
                    .unwrap_or(volume_name.len());
                let name = String::from_utf16_lossy(&volume_name[..end]);
                (!name.is_empty()).then(|| format!("{} ({})", name, drive.trim_end_matches('\\')))
            })
            .unwrap_or_else(|| drive.trim_end_matches('\\').to_string());
            RootEntry {
                path: drive,
                name: label,
                kind: "drive".to_string(),
            }
        })
        .collect()
}

#[cfg(not(windows))]
fn windows_roots() -> Vec<RootEntry> {
    Vec::new()
}
