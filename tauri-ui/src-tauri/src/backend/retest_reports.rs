//! Native OOXML retest report generation.

use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use quick_xml::events::{BytesStart, BytesText, Event};
use quick_xml::{Reader as XmlReader, Writer as XmlWriter};
use regex::Regex;
use serde::{Deserialize, Serialize};
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

#[derive(Debug)]
struct ReportFields {
    vulnerability_name: String,
    targets: Vec<String>,
}

fn source_report_fields(source: &Path) -> Result<ReportFields, String> {
    let text = super::native_runtime::extract_word_text(source)?;
    let vulnerability_name = source
        .file_stem()
        .and_then(|name| name.to_str())
        .and_then(super::pdf_notice::notice_issue_from_name)
        .unwrap_or_else(|| "未知漏洞".to_string());
    let mut targets = preferred_report_urls(&text);
    if targets.is_empty() {
        targets = source_hyperlink_urls(source)?;
    }
    if targets.is_empty() {
        let domains = Regex::new(r"(?im)(?:domain|域名)\s*[:：]\s*([^\s、，。；（）【】<>]+)")
            .expect("valid domain marker");
        for capture in domains.captures_iter(&text) {
            let domain = &capture[1];
            if reqwest::Url::parse(&format!("http://{domain}"))
                .ok()
                .is_some_and(|url| url.host_str().is_some())
                && !targets.iter().any(|item| item == domain)
            {
                targets.push(domain.to_string());
            }
        }
    }
    if targets.is_empty() {
        let ips = Regex::new(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b").expect("valid IPv4 pattern");
        for found in ips.find_iter(&text) {
            let ip = found.as_str();
            if ip.parse::<std::net::Ipv4Addr>().is_ok() && !targets.iter().any(|item| item == ip) {
                targets.push(ip.to_string());
            }
        }
    }
    Ok(ReportFields {
        vulnerability_name,
        targets,
    })
}

fn preferred_report_urls(text: &str) -> Vec<String> {
    // Match the old generator's preference for verification evidence over
    // reference links in the vulnerability description or remediation text.
    let mut verification = String::new();
    let mut in_verification = false;
    for line in text.lines() {
        if line.contains("验证情况") {
            in_verification = true;
        } else if ["处置措施", "修复建议", "漏洞描述"]
            .iter()
            .any(|name| line.contains(name))
        {
            in_verification = false;
        }
        if in_verification {
            verification.push_str(line);
            verification.push('\n');
        }
    }
    let urls = super::native_runtime::extract_http_urls(&verification);
    if !urls.is_empty() {
        return urls;
    }
    let marker = Regex::new(r"(?i)(?:url|网址|地址)\s*[:：]").expect("valid URL marker");
    let labelled = text
        .lines()
        .filter(|line| marker.is_match(line))
        .collect::<Vec<_>>()
        .join("\n");
    let urls = super::native_runtime::extract_http_urls(&labelled);
    if !urls.is_empty() {
        return urls;
    }
    super::native_runtime::extract_http_urls(text)
}

fn source_hyperlink_urls(source: &Path) -> Result<Vec<String>, String> {
    let mut archive = ZipArchive::new(File::open(source).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    let mut part = match archive.by_name("word/_rels/document.xml.rels") {
        Ok(part) => part,
        Err(zip::result::ZipError::FileNotFound) => return Ok(Vec::new()),
        Err(error) => return Err(format!("读取通报超链接失败: {error}")),
    };
    if part.size() > MAX_TEMPLATE_BYTES {
        return Err("通报超链接部件超过 64 MiB 限制".to_string());
    }
    let mut xml = String::new();
    part.read_to_string(&mut xml)
        .map_err(|error| error.to_string())?;
    let mut reader = XmlReader::from_str(&xml);
    let mut urls = Vec::new();
    loop {
        match reader.read_event().map_err(|error| error.to_string())? {
            Event::Start(element) | Event::Empty(element)
                if element.local_name().as_ref() == b"Relationship" =>
            {
                let mut hyperlink = false;
                let mut external = false;
                let mut target = String::new();
                for attribute in element.attributes() {
                    let attribute = attribute.map_err(|error| error.to_string())?;
                    let value = attribute
                        .decode_and_unescape_value(reader.decoder())
                        .map_err(|error| error.to_string())?;
                    match attribute.key.as_ref() {
                        b"Type" => hyperlink = value.ends_with("/hyperlink"),
                        b"TargetMode" => external = value == "External",
                        b"Target" => target = value.into_owned(),
                        _ => {}
                    }
                }
                if hyperlink
                    && external
                    && !urls.contains(&target)
                    && reqwest::Url::parse(&target).ok().is_some_and(|url| {
                        url.host_str().is_some() && matches!(url.scheme(), "http" | "https")
                    })
                {
                    urls.push(target);
                }
            }
            Event::Eof => break,
            _ => {}
        }
    }
    Ok(urls)
}

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

#[derive(Debug, Serialize)]
pub(super) struct ReportResponse {
    success: bool,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    target_dir: Option<PathBuf>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reports: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    disposal_reports: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    screenshot_path: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    failures: Option<Vec<Value>>,
    logs: Vec<String>,
}

impl ReportResponse {
    pub(super) fn succeeded(&self) -> bool {
        self.success
    }

    pub(super) fn reports(&self) -> &[String] {
        self.reports.as_deref().unwrap_or_default()
    }
}

pub fn dispatch(
    command: &str,
    payload: &Value,
    user_data_dir: &Path,
    cwd: &Path,
) -> Result<Value, String> {
    serde_json::to_value(dispatch_typed(command, payload, user_data_dir, cwd)?)
        .map_err(|error| format!("serialize retest report response failed: {error}"))
}

pub(super) fn dispatch_typed(
    command: &str,
    payload: &Value,
    user_data_dir: &Path,
    cwd: &Path,
) -> Result<ReportResponse, String> {
    if command != COMMAND {
        return Err(format!("native report command not registered: {command}"));
    }
    let request: ReportRequest = serde_json::from_value(payload.clone())
        .map_err(|error| format!("invalid retest report request: {error}"))?;
    generate(request, user_data_dir, cwd)
}

fn generate(
    request: ReportRequest,
    user_data_dir: &Path,
    cwd: &Path,
) -> Result<ReportResponse, String> {
    let target = canonical_directory(Path::new(request.target_dir.trim()))?;
    if request.source_files.is_empty() {
        return Ok(ReportResponse {
            success: false,
            message: "缺少待生成报告的原始通报文件列表".to_string(),
            target_dir: None,
            reports: None,
            disposal_reports: None,
            screenshot_path: None,
            failures: None,
            logs: Vec::new(),
        });
    }
    let template = resolve_template(&request.template_path, user_data_dir, cwd)?;
    let screenshot = if request.screenshot_data_url.trim().is_empty() {
        if request.result_data["assessment_basis"] == "target_unreachable" {
            Some(super::retest_evidence::render_snapshot(
                &request.result_data,
            )?)
        } else {
            None
        }
    } else {
        Some(decode_png(&request.screenshot_data_url)?)
    };
    let result_summary = report_summary(&request.summary, &request.result_data);
    let report_conclusion = if request.result_data["assessment_basis"] == "target_unreachable" {
        "未复现（目标不可访问）"
    } else if request.result_data["verification_incomplete"] == true {
        "待核验"
    } else if request.result_data["final_verdict"] == "reproduced" {
        "未修复"
    } else {
        "已复核"
    };
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
        let fields = match source_report_fields(&source) {
            Ok(fields) => fields,
            Err(error) => {
                failures.push(json!({"file":source,"reason":error}));
                continue;
            }
        };
        let title = source
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or("复测")
            .trim_end_matches("的通报")
            .trim_end_matches("通报")
            .to_string();
        let output_name = if request.result_data["verification_incomplete"] == true {
            format!("{}_复测待核验报告.docx", safe_filename(&title))
        } else {
            format!("{}_复测报告.docx", safe_filename(&title))
        };
        let output = source.parent().unwrap_or(&target).join(output_name);
        match build_report(
            &template,
            &output,
            &title,
            &fields,
            &result_summary,
            report_conclusion,
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
    Ok(ReportResponse {
        success,
        message: if success {
            format!("复测报告截图写入完成：生成 {} 份，失败 0 份", reports.len())
        } else {
            format!(
                "复测报告未生成或写入失败：生成 {} 份，失败 {} 份",
                reports.len(),
                failures.len()
            )
        },
        target_dir: Some(target),
        reports: Some(reports),
        disposal_reports: Some(Vec::new()),
        screenshot_path: Some(Value::Null),
        failures: Some(failures),
        logs,
    })
}

fn build_report(
    template: &Path,
    output: &Path,
    title: &str,
    fields: &ReportFields,
    summary: &str,
    conclusion: &str,
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
                let xml =
                    rewrite_document_xml(&xml, title, fields, summary, conclusion, screenshot)?;
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
    fields: &ReportFields,
    summary: &str,
    conclusion: &str,
    screenshot: Option<&[u8]>,
) -> Result<String, String> {
    let targets = if fields.targets.is_empty() {
        "未检测到URL".to_string()
    } else {
        fields.targets.join("\n")
    };
    let evidence = format!(
        "<w:p><w:pPr><w:spacing w:after=\"120\"/></w:pPr><w:r><w:t xml:space=\"preserve\">{}</w:t></w:r></w:p>{}",
        xml_escape(summary),
        screenshot.map(drawing_xml).transpose()?.unwrap_or_default()
    );
    let mut reader = XmlReader::from_str(xml);
    let mut writer = XmlWriter::new(Vec::new());
    let mut stack: Vec<Vec<u8>> = Vec::new();
    let mut cells: Vec<Option<usize>> = Vec::new();
    let mut text_tag: Option<BytesStart<'static>> = None;
    let mut title_replaced = false;
    let mut evidence_inserted = false;
    loop {
        let event = reader
            .read_event()
            .map_err(|error| format!("解析复测模板失败: {error}"))?;
        match &event {
            Event::Start(element) | Event::Empty(element) => {
                let local = element.local_name().as_ref().to_vec();
                if local == b"sectPr"
                    && stack.last().is_some_and(|name| name == b"body")
                    && !evidence_inserted
                {
                    writer.get_mut().extend_from_slice(evidence.as_bytes());
                    evidence_inserted = true;
                }
                if matches!(event, Event::Start(_)) {
                    match local.as_slice() {
                        b"tbl" => cells.push(None),
                        b"tr" => {
                            if let Some(cell) = cells.last_mut() {
                                *cell = Some(0);
                            }
                        }
                        b"t" => text_tag = Some(element.clone().into_owned()),
                        _ => {}
                    }
                    stack.push(local);
                }
            }
            Event::End(element) => {
                match element.local_name().as_ref() {
                    b"t" => text_tag = None,
                    b"tc" => {
                        if let Some(Some(index)) = cells.last_mut() {
                            *index += 1;
                        }
                    }
                    b"tr" => {
                        if let Some(cell) = cells.last_mut() {
                            *cell = None;
                        }
                    }
                    b"tbl" => {
                        cells.pop();
                    }
                    b"body" if !evidence_inserted => {
                        writer.get_mut().extend_from_slice(evidence.as_bytes());
                        evidence_inserted = true;
                    }
                    _ => {}
                }
                stack.pop();
            }
            Event::Text(value) if text_tag.is_some() => {
                let value = value.decode().map_err(|error| error.to_string())?;
                let mut replacement = value.replace("已复核", conclusion);
                if value.contains('*') {
                    let field = match cells.last().copied().flatten() {
                        Some(1) => fields.vulnerability_name.as_str(),
                        Some(2) => targets.as_str(),
                        _ if cells.is_empty() && !title_replaced => {
                            title_replaced = true;
                            title
                        }
                        _ => "复测证据见下文",
                    };
                    replacement = replacement.replace('*', field);
                }
                // Keep the cell's runs, fonts and paragraph properties. Word
                // needs explicit breaks to display multiple target URLs.
                for (index, line) in replacement.split('\n').enumerate() {
                    if index > 0 {
                        let tag = text_tag.as_ref().expect("text element");
                        writer
                            .write_event(Event::End(tag.to_end()))
                            .map_err(|error| error.to_string())?;
                        writer
                            .write_event(Event::Empty(BytesStart::new("w:br")))
                            .map_err(|error| error.to_string())?;
                        writer
                            .write_event(Event::Start(tag.clone()))
                            .map_err(|error| error.to_string())?;
                    }
                    writer
                        .write_event(Event::Text(BytesText::new(line)))
                        .map_err(|error| error.to_string())?;
                }
                continue;
            }
            Event::Eof => break,
            _ => {}
        }
        writer
            .write_event(event)
            .map_err(|error| error.to_string())?;
    }
    if !evidence_inserted {
        return Err("复测模板缺少 w:body".to_string());
    }
    String::from_utf8(writer.into_inner()).map_err(|error| error.to_string())
}

fn drawing_xml(png: &[u8]) -> Result<String, String> {
    let image = image::load_from_memory(png).map_err(|_| "复测证据图不是有效图像")?;
    let ratio =
        (5_100_000.0 / f64::from(image.width())).min(4_100_000.0 / f64::from(image.height()));
    let width = (f64::from(image.width()) * ratio) as u64;
    let height = (f64::from(image.height()) * ratio) as u64;
    Ok(format!(
        r#"<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{width}" cy="{height}"/><wp:docPr id="9001" name="KOI Retest Evidence"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="koi-retest-evidence.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rIdKoiEvidence"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"#
    ))
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
    if result["assessment_basis"] == "target_unreachable" {
        output.push_str("\n\n本次访问记录：");
        for item in result["retest_results"].as_array().into_iter().flatten() {
            output.push_str(&format!(
                "\n目标：{}\n时间：{}\n状态：目标不可访问\n原因：{}\n",
                item["url"].as_str().unwrap_or_default(),
                item["checked_at"].as_str().unwrap_or("未记录"),
                item["error"].as_str().unwrap_or("连接失败")
            ));
        }
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
        .is_some_and(|value| value.contains("复测报告") || value.contains("复测待核验报告"))
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

    fn write_source(path: &Path, xml: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let mut archive = ZipWriter::new(File::create(path).unwrap());
        write_part(&mut archive, "word/document.xml", xml.as_bytes()).unwrap();
        archive.finish().unwrap();
    }

    fn table_text(xml: &str) -> Vec<Vec<String>> {
        let mut reader = XmlReader::from_str(xml);
        let mut rows = Vec::new();
        let mut row = Vec::new();
        let mut cell = None::<String>;
        loop {
            match reader.read_event().unwrap() {
                Event::Start(element) if element.local_name().as_ref() == b"tc" => {
                    cell = Some(String::new())
                }
                Event::Text(value) if cell.is_some() => {
                    cell.as_mut().unwrap().push_str(&value.decode().unwrap())
                }
                Event::GeneralRef(value) if cell.is_some() => cell.as_mut().unwrap().push_str(
                    &quick_xml::escape::unescape(&format!("&{};", value.decode().unwrap()))
                        .unwrap(),
                ),
                Event::Empty(element) if element.local_name().as_ref() == b"br" => {
                    if let Some(cell) = cell.as_mut() {
                        cell.push('\n');
                    }
                }
                Event::End(element) if element.local_name().as_ref() == b"tc" => {
                    row.push(cell.take().unwrap())
                }
                Event::End(element) if element.local_name().as_ref() == b"tr" => {
                    rows.push(std::mem::take(&mut row))
                }
                Event::Eof => break,
                _ => {}
            }
        }
        rows
    }

    #[test]
    fn table_fields_use_each_sources_vulnerability_and_complete_urls() {
        let root = std::env::temp_dir().join(format!(
            "koi-report-fields-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        let first = root.join("first/关于测试企业存在跨站脚本攻击(XSS)的安全通报_20260921.docx");
        let second = root.join("second/关于测试企业存在sweet32攻击漏洞的安全通报.docx");
        let first_xml = r#"<w:document xmlns:w="urn:word"><w:body>
            <w:p><w:r><w:t>参考资料 https://reference.example.test/</w:t></w:r></w:p>
            <w:p><w:r><w:t>2.验证情况</w:t></w:r></w:p>
            <w:p><w:r><w:t>URL: https://one.example.test/feed</w:t></w:r><w:r><w:t>back.asp?action=&amp;page=1</w:t></w:r></w:p>
            <w:p><w:r><w:t>URL: https://two.example.test/path</w:t></w:r></w:p>
            <w:p><w:r><w:t>3.处置措施</w:t></w:r></w:p>
            <w:p><w:r><w:t>https://remediation.example.test/</w:t></w:r></w:p>
            </w:body></w:document>"#;
        write_source(&first, first_xml);
        write_source(
            &second,
            r#"<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>URL: https://sweet32.example.test/</w:t></w:r></w:p></w:body></w:document>"#,
        );
        let first_before = fs::read(&first).unwrap();
        let result = dispatch(
            COMMAND,
            &json!({
                "target_dir":root,"source_files":[first,second],
                "summary":"recorded evidence",
                "result_data":{"final_verdict":"not_reproduced","urls":["https://wrong-batch.example.test/"]}
            }),
            &root,
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").as_path(),
        ).unwrap();
        assert_eq!(result["success"], true, "{result}");
        let expected = [
            ("跨站脚本攻击(XSS)", "https://one.example.test/feedback.asp?action=&page=1\nhttps://two.example.test/path"),
            ("sweet32攻击漏洞", "https://sweet32.example.test/"),
        ];
        for (report, (name, urls)) in result["reports"].as_array().unwrap().iter().zip(expected) {
            let mut archive =
                ZipArchive::new(File::open(report.as_str().unwrap()).unwrap()).unwrap();
            let mut xml = String::new();
            archive
                .by_name("word/document.xml")
                .unwrap()
                .read_to_string(&mut xml)
                .unwrap();
            let rows = table_text(&xml);
            let row = rows
                .iter()
                .find(|row| row.get(1).is_some_and(|value| value == name))
                .expect("vulnerability table row");
            assert_eq!(row[2], urls);
            assert!(!xml.contains("详见复测证据"));
            assert!(!row[2].contains("reference.example"));
            assert!(!row[2].contains("wrong-batch.example"));
        }
        assert_eq!(fs::read(&first).unwrap(), first_before);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn table_replacement_preserves_cell_formatting_and_escaped_urls() {
        let xml = r#"<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>*的复测报告</w:t></w:r></w:p>
            <w:tbl><w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>
            <w:tc><w:tcPr><w:tcW w:w="2000"/></w:tcPr><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">*</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">*</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>已复核</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:sectPr/></w:body></w:document>"#;
        let output = rewrite_document_xml(
            xml,
            "测试",
            &ReportFields {
                vulnerability_name: "XSS".into(),
                targets: vec![
                    "https://example.test/?x=1&y=2".into(),
                    "https://second.example.test/".into(),
                ],
            },
            "evidence",
            "未复现",
            None,
        )
        .unwrap();
        assert!(output.contains(r#"<w:tcPr><w:tcW w:w="2000"/></w:tcPr>"#));
        assert!(output.contains(r#"<w:pPr><w:jc w:val="center"/></w:pPr>"#));
        assert!(output.contains(r#"<w:rPr><w:b/></w:rPr>"#));
        assert!(output.contains(r#"<w:rPr><w:sz w:val="18"/></w:rPr>"#));
        assert!(output.contains("x=1&amp;y=2"));
        assert_eq!(
            table_text(&output)[0][2],
            "https://example.test/?x=1&y=2\nhttps://second.example.test/"
        );
    }

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

    #[test]
    fn unreachable_result_creates_a_non_completion_report() {
        let root = std::env::temp_dir().join(format!(
            "koi-inconclusive-report-test-{}",
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let source = root.join("关于测试存在漏洞的通报.docx");
        fs::copy(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../Report_Template/复测模板.docx"),
            &source,
        )
        .unwrap();
        let result = dispatch(
            COMMAND,
            &json!({
                "target_dir":root,
                "source_files":[source],
                "summary":"目标不可达，尚未核验",
                "result_data":{"verification_incomplete":true,"final_verdict":"inconclusive"},
            }),
            &root,
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .as_path(),
        )
        .unwrap();
        assert_eq!(result["success"], true);
        let report = PathBuf::from(result["reports"][0].as_str().unwrap());
        assert!(report
            .file_name()
            .unwrap()
            .to_string_lossy()
            .contains("复测待核验报告"));
        assert!(report.is_file());
        assert!(!root.join("关于测试存在漏洞_复测报告.docx").exists());
        let _ = fs::remove_dir_all(root);
    }
}
