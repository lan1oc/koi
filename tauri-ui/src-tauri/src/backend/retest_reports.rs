//! Native OOXML retest report generation.

use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

pub const COMMAND: &str = "doc.retest.generate_reports_with_screenshot";
const MAX_SCREENSHOT_BYTES: usize = 10 * 1024 * 1024;
const MAX_TEMPLATE_BYTES: u64 = 64 * 1024 * 1024;
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Deserialize)]
struct ReportRequest {
    target_dir: String,
    source_files: Vec<String>,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    result_data: Value,
    #[serde(default)]
    screenshot_data_url: String,
    #[serde(default)]
    template_path: String,
}

pub fn dispatch(
    command: &str,
    payload: &Value,
    user_data_dir: &Path,
    cwd: &Path,
) -> Result<Value, String> {
    if command != COMMAND {
        return Err(format!("native report command not registered: {command}"));
    }
    let request: ReportRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("invalid retest report request: {error}"))?;
    generate(request, user_data_dir, cwd)
}

fn generate(request: ReportRequest, user_data_dir: &Path, cwd: &Path) -> Result<Value, String> {
    let target = canonical_directory(Path::new(request.target_dir.trim()))?;
    if request.source_files.is_empty() {
        return Ok(json!({"success":false,"message":"缺少待生成报告的原始通报文件列表","logs":[]}));
    }
    let template = resolve_template(&request.template_path, user_data_dir, cwd)?;
    let screenshot = if request.screenshot_data_url.trim().is_empty() {
        None
    } else {
        Some(decode_png(&request.screenshot_data_url)?)
    };
    let result_summary = report_summary(&request.summary, &request.result_data);
    let mut reports = Vec::new();
    let mut failures = Vec::new();
    let mut logs = Vec::new();
    for source in request.source_files {
        let source = source_path_under(&target, Path::new(source.trim()))?;
        if source
            .extension()
            .and_then(|value| value.to_str())
            .is_none_or(|value| !value.eq_ignore_ascii_case("docx"))
        {
            failures.push(json!({"file":source,"reason":"通报文件不存在或不是 DOCX 文档"}));
            continue;
        }
        if is_generated_report(&source) {
            failures.push(json!({"file":source,"reason":"这是已生成的复测报告，不是原始通报文件"}));
            continue;
        }
        let title = source
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("复测")
            .trim_end_matches("的通报")
            .trim_end_matches("通报")
            .to_string();
        let output_name = format!("{}_复测报告.docx", safe_filename(&title));
        let output = source.parent().unwrap_or(&target).join(output_name);
        match build_report(
            &template,
            &output,
            &title,
            &result_summary,
            screenshot.as_deref(),
        ) {
            Ok(()) => {
                logs.push(format!("报告已生成: {}", output.display()));
                reports.push(output.to_string_lossy().to_string());
            }
            Err(error) => failures.push(json!({"file":source,"reason":error})),
        }
    }
    let success = !reports.is_empty() && failures.is_empty();
    Ok(json!({
        "success":success,
        "message": if success {
            format!("复测报告截图写入完成：生成 {} 份，失败 0 份", reports.len())
        } else {
            format!("复测报告未生成或写入失败：生成 {} 份，失败 {} 份", reports.len(), failures.len())
        },
        "target_dir":target,
        "reports":reports,
        "disposal_reports":[],
        "screenshot_path":Value::Null,
        "failures":failures,
        "logs":logs,
    }))
}

fn build_report(
    template: &Path,
    output: &Path,
    title: &str,
    summary: &str,
    screenshot: Option<&[u8]>,
) -> Result<(), String> {
    let input = File::open(template).map_err(|error| format!("无法打开复测模板: {error}"))?;
    let mut archive =
        ZipArchive::new(input).map_err(|error| format!("复测模板不是有效 DOCX: {error}"))?;
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let temp = output.with_file_name(format!(
        ".{}.tmp-{id}",
        output
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("report.docx")
    ));
    let result = (|| {
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp)
            .map_err(|error| format!("创建报告临时文件失败: {error}"))?;
        let mut writer = ZipWriter::new(file);
        for index in 0..archive.len() {
            let mut entry = archive
                .by_index(index)
                .map_err(|error| format!("读取模板部件失败: {error}"))?;
            let name = entry.name().to_string();
            if name.eq_ignore_ascii_case("word/document.xml") {
                let mut bytes = Vec::new();
                entry
                    .read_to_end(&mut bytes)
                    .map_err(|error| error.to_string())?;
                let xml = String::from_utf8(bytes)
                    .map_err(|_| "复测模板 document.xml 不是 UTF-8".to_string())?;
                let xml = rewrite_document_xml(&xml, title, summary, screenshot.is_some())?;
                write_part(&mut writer, &name, xml.as_bytes())?;
            } else if name.eq_ignore_ascii_case("word/_rels/document.xml.rels")
                && screenshot.is_some()
            {
                let mut text = String::new();
                entry
                    .read_to_string(&mut text)
                    .map_err(|error| error.to_string())?;
                let relation = r#"<Relationship Id="rIdKoiEvidence" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/koi-retest-evidence.png"/>"#;
                let text = text.replacen(
                    "</Relationships>",
                    &format!("{relation}</Relationships>"),
                    1,
                );
                write_part(&mut writer, &name, text.as_bytes())?;
            } else if name.eq_ignore_ascii_case("[Content_Types].xml") && screenshot.is_some() {
                let mut text = String::new();
                entry
                    .read_to_string(&mut text)
                    .map_err(|error| error.to_string())?;
                if !text.to_ascii_lowercase().contains("extension=\"png\"") {
                    let content_type = r#"<Default Extension="png" ContentType="image/png"/>"#;
                    text = text.replacen("</Types>", &format!("{content_type}</Types>"), 1);
                }
                write_part(&mut writer, &name, text.as_bytes())?;
            } else {
                writer
                    .raw_copy_file(entry)
                    .map_err(|error| format!("保留模板部件失败: {error}"))?;
            }
        }
        if let Some(image) = screenshot {
            write_part(&mut writer, "word/media/koi-retest-evidence.png", image)?;
        }
        let file = writer
            .finish()
            .map_err(|error| format!("完成报告失败: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("同步报告失败: {error}"))?;
        validate_report(&temp, screenshot.is_some())?;
        atomic_replace(&temp, output)?;
        Ok::<(), String>(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

fn rewrite_document_xml(
    xml: &str,
    title: &str,
    summary: &str,
    has_screenshot: bool,
) -> Result<String, String> {
    let mut output = xml.to_string();
    let escaped_title = xml_escape(title);
    let escaped_summary = xml_escape(summary);
    output = replace_nth(
        &output,
        "<w:t>*</w:t>",
        &format!("<w:t>{escaped_title}</w:t>"),
        0,
    );
    output = replace_nth(&output, "<w:t>*</w:t>", "<w:t>复测结果</w:t>", 0);
    output = replace_nth(&output, "<w:t>*</w:t>", "<w:t>详见复测证据</w:t>", 0);
    output = output.replace("<w:t>*</w:t>", "<w:t>复测证据见下文</w:t>");
    let evidence = format!(
        "<w:p><w:pPr><w:spacing w:after=\"120\"/></w:pPr><w:r><w:t xml:space=\"preserve\">{escaped_summary}</w:t></w:r></w:p>{}",
        if has_screenshot { drawing_xml() } else { "" }
    );
    if let Some(index) = output.find("<w:sectPr") {
        output.insert_str(index, &evidence);
    } else if let Some(index) = output.find("</w:body>") {
        output.insert_str(index, &evidence);
    } else {
        return Err("复测模板缺少 w:body".to_string());
    }
    Ok(output)
}

fn drawing_xml() -> &'static str {
    r#"<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0"><wp:extent cx="3840480" cy="2286000"/><wp:docPr id="9001" name="KOI Retest Evidence"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="koi-retest-evidence.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rIdKoiEvidence"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3840480" cy="2286000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"#
}

fn write_part(writer: &mut ZipWriter<File>, name: &str, bytes: &[u8]) -> Result<(), String> {
    writer
        .start_file(
            name,
            SimpleFileOptions::default().compression_method(CompressionMethod::DEFLATE),
        )
        .map_err(|error| format!("创建报告部件失败: {error}"))?;
    writer
        .write_all(bytes)
        .map_err(|error| format!("写入报告部件失败: {error}"))
}

fn validate_report(path: &Path, image_expected: bool) -> Result<(), String> {
    let input = File::open(path).map_err(|error| error.to_string())?;
    let mut archive =
        ZipArchive::new(input).map_err(|error| format!("报告 DOCX 校验失败: {error}"))?;
    let mut document = String::new();
    archive
        .by_name("word/document.xml")
        .map_err(|_| "报告缺少 word/document.xml".to_string())?
        .read_to_string(&mut document)
        .map_err(|error| error.to_string())?;
    if document.contains("<w:t>*</w:t>") {
        return Err("报告仍包含未替换占位符".to_string());
    }
    if image_expected
        && archive
            .by_name("word/media/koi-retest-evidence.png")
            .is_err()
    {
        return Err("报告缺少复测证据图".to_string());
    }
    Ok(())
}

fn decode_png(value: &str) -> Result<Vec<u8>, String> {
    let encoded = value
        .trim()
        .strip_prefix("data:image/png;base64,")
        .ok_or_else(|| "复测截图必须是 PNG data URL".to_string())?;
    if encoded.len() > MAX_SCREENSHOT_BYTES * 2 {
        return Err("复测截图超过 10 MiB 限制".to_string());
    }
    let bytes = BASE64_STANDARD
        .decode(encoded)
        .map_err(|_| "复测截图 Base64 无效".to_string())?;
    if bytes.len() > MAX_SCREENSHOT_BYTES || !bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err("复测截图不是有效的受限 PNG".to_string());
    }
    Ok(bytes)
}

fn resolve_template(requested: &str, data: &Path, cwd: &Path) -> Result<PathBuf, String> {
    let candidates = [
        (!requested.trim().is_empty()).then(|| PathBuf::from(requested.trim())),
        Some(data.join("Report_Template").join("复测模板.docx")),
        Some(cwd.join("Report_Template").join("复测模板.docx")),
        Some(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("Report_Template")
                .join("复测模板.docx"),
        ),
    ];
    for candidate in candidates.into_iter().flatten() {
        if candidate.is_file()
            && fs::metadata(&candidate)
                .map(|metadata| metadata.len() <= MAX_TEMPLATE_BYTES)
                .unwrap_or(false)
        {
            return fs::canonicalize(candidate).map_err(|error| error.to_string());
        }
    }
    Err("未找到复测模板文件".to_string())
}

fn report_summary(summary: &str, result: &Value) -> String {
    let mut output = summary.trim().chars().take(20_000).collect::<String>();
    if output.is_empty() && !result.is_null() {
        output = result.to_string().chars().take(20_000).collect();
    }
    if output.is_empty() {
        "复测结果未提供摘要。".to_string()
    } else {
        output
    }
}

fn canonical_directory(path: &Path) -> Result<PathBuf, String> {
    if path.as_os_str().is_empty() || !path.is_dir() {
        return Err(format!("通报目录不存在: {}", path.display()));
    }
    fs::canonicalize(path).map_err(|error| error.to_string())
}

fn source_path_under(root: &Path, path: &Path) -> Result<PathBuf, String> {
    let path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    };
    let canonical = fs::canonicalize(&path).map_err(|error| format!("通报文件不存在: {error}"))?;
    if !canonical.starts_with(root) {
        return Err("通报文件必须位于目标目录内".to_string());
    }
    Ok(canonical)
}

fn is_generated_report(path: &Path) -> bool {
    path.file_stem()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.contains("复测报告"))
}

fn safe_filename(value: &str) -> String {
    let value = value
        .chars()
        .map(|ch| {
            if "<>:\"/\\|?*".contains(ch) || ch.is_control() {
                '_'
            } else {
                ch
            }
        })
        .collect::<String>();
    let value = value
        .trim()
        .trim_matches('.')
        .chars()
        .take(120)
        .collect::<String>();
    if value.is_empty() {
        "复测".to_string()
    } else {
        value
    }
}

fn replace_nth(input: &str, needle: &str, replacement: &str, index: usize) -> String {
    let Some((start, _)) = input.match_indices(needle).nth(index) else {
        return input.to_string();
    };
    let mut output = String::with_capacity(input.len() + replacement.len());
    output.push_str(&input[..start]);
    output.push_str(replacement);
    output.push_str(&input[start + needle.len()..]);
    output
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
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
    .map_err(|error| format!("原子替换报告失败: {error}"))
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn creates_valid_report_and_preserves_template_parts() {
        let root = std::env::temp_dir().join(format!(
            "koi-report-test-{}",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let source = root.join("关于测试存在漏洞的通报.docx");
        fs::copy(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../Report_Template/复测模板.docx"),
            &source,
        )
        .unwrap();
        let tiny_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
        let result = dispatch(
            COMMAND,
            &json!({"target_dir":root,"source_files":[source],"summary":"evidence summary","screenshot_data_url":tiny_png}),
            &root,
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").as_path(),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        let report = PathBuf::from(result["reports"][0].as_str().unwrap());
        let file = File::open(report).unwrap();
        let mut archive = ZipArchive::new(file).unwrap();
        assert!(archive.by_name("word/styles.xml").is_ok());
        assert!(archive
            .by_name("word/media/koi-retest-evidence.png")
            .is_ok());
        let _ = fs::remove_dir_all(root);
    }
}
