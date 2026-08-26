use koi_tauri_lib::{run_internal_worker_from_args, BackendContext, BackendCore};
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{SystemTime, UNIX_EPOCH};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

fn main() -> ExitCode {
    if let Some(code) = run_internal_worker_from_args() {
        return ExitCode::from(code as u8);
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(".tmp-notice-pipeline-interactive");
    let result = run_smoke(&root);
    let report = match result {
        Ok(value) => json!({"ok": true, "result": value}),
        Err(error) => json!({"ok": false, "error": error}),
    };
    let _ = fs::create_dir_all(&root);
    let _ = fs::write(
        root.join("latest.json"),
        serde_json::to_vec_pretty(&report).unwrap_or_else(|_| b"{\"ok\":false}".to_vec()),
    );
    if report["ok"] == Value::Bool(true) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run_smoke(root: &Path) -> Result<Value, String> {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    let data_dir = root.join(format!("run-{}-{nonce}", std::process::id()));
    let template_dir = data_dir.join("Report_Template");
    let target = data_dir.join("notice");
    fs::create_dir_all(&template_dir).map_err(|error| error.to_string())?;
    fs::create_dir_all(&target).map_err(|error| error.to_string())?;
    write_docx(
        &target.join("123关于宁波测试有限公司存在漏洞的通报.docx"),
        "抄送：",
    )?;
    write_docx(
        &template_dir.join("授权委托书模板.docx"),
        "涉嫌 * 的代理权限",
    )?;
    write_docx(
        &template_dir.join("责令整改模板.docx"),
        "【公司名】存在【漏洞类型】\n2025年9月2日",
    )?;
    write_docx(
        &template_dir.join("处置模板.docx"),
        "XX网信办：关于××单位××系统的处置报告",
    )?;
    let context = BackendContext::new(
        data_dir.clone(),
        std::env::temp_dir(),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")),
        "4.0.0",
    );
    let core = BackendCore::new(context)?;
    let response = core.dispatch(
        "doc.notice.process",
        json!({
            "target_path": target,
            "auto_group": false,
            "_rust_notice_pipeline": true,
        }),
    );
    let data = response.data.clone();
    if !response.ok {
        return Err(format!("notice smoke returned an error: {response:?}"));
    }
    if data["success"] != true {
        return Err(format!("notice pipeline failed: {data}"));
    }
    if data["stages"]["rewrite"] != true
        || data["stages"]["authorization"] != true
        || data["stages"]["rectification"] != true
        || data["stages"]["disposal"] != true
        || data["stages"]["pdf"] != true
    {
        return Err(format!("notice pipeline stages incomplete: {data}"));
    }
    Ok(data)
}

fn write_docx(path: &Path, text: &str) -> Result<(), String> {
    let file = File::create(path).map_err(|error| error.to_string())?;
    let mut writer = ZipWriter::new(file);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    let document = format!(
        r#"<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>"#,
        text.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
    );
    let core = r#"<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>notice.smoke</dc:description></cp:coreProperties>"#;
    for (name, body) in [
        ("[Content_Types].xml", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/><Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/></Types>"),
        ("_rels/.rels", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/><Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/></Relationships>"),
        ("docProps/core.xml", core),
        ("word/document.xml", document.as_str()),
    ] {
        writer
            .start_file(name, options)
            .map_err(|error| error.to_string())?;
        writer
            .write_all(body.as_bytes())
            .map_err(|error| error.to_string())?;
    }
    writer.finish().map_err(|error| error.to_string())?;
    Ok(())
}
