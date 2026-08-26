#[allow(dead_code)]
#[path = "../src/backend/document_conversion.rs"]
mod document_conversion;
#[allow(dead_code)]
#[path = "../src/backend/protocol.rs"]
mod protocol;

use quick_xml::events::Event;
use quick_xml::Reader;
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{SystemTime, UNIX_EPOCH};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

const EXPECTED_TEXT: &str = "KOI Rust COM roundtrip 4.0.0";

fn main() -> ExitCode {
    if let Some(exit_code) = document_conversion::run_word_com_worker_from_args() {
        return ExitCode::from(exit_code as u8);
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(".tmp-word-com-interactive");
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let run_dir = root.join(format!("run-{}-{nonce}", std::process::id()));
    let result = run_smoke(&run_dir);
    let report = match result {
        Ok(report) => report,
        Err(error) => json!({
            "ok": false,
            "error": error,
            "run_dir": run_dir,
        }),
    };
    let _ = fs::create_dir_all(&root);
    let _ = fs::write(
        root.join("latest.json"),
        serde_json::to_vec_pretty(&report).unwrap_or_else(|_| b"{\"ok\":false}".to_vec()),
    );
    if report.get("ok") == Some(&Value::Bool(true)) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn run_smoke(run_dir: &Path) -> Result<Value, String> {
    fs::create_dir_all(run_dir).map_err(|error| error.to_string())?;
    let source = run_dir.join("source.docx");
    let pdf = run_dir.join("source.pdf");
    let converted_dir = run_dir.join("converted");
    let roundtrip = converted_dir.join("source.docx");
    write_docx(&source)?;

    let word_to_pdf = document_conversion::dispatch(
        "doc.convert.run",
        &json!({
            "conversion_type": "word_to_pdf",
            "input_path": source,
            "output_dir": run_dir,
            "recursive": false,
            "overwrite": true,
            "skip_template": false,
        }),
    )?;
    if word_to_pdf.get("success") != Some(&Value::Bool(true)) {
        return Err(format!("DOCX to PDF failed: {word_to_pdf}"));
    }
    let pdf_bytes = fs::read(&pdf).map_err(|error| format!("read PDF: {error}"))?;
    if !pdf_bytes.starts_with(b"%PDF-") || pdf_bytes.len() < 512 {
        return Err("DOCX to PDF produced an invalid PDF signature".to_string());
    }

    let pdf_to_word = document_conversion::dispatch(
        "doc.convert.run",
        &json!({
            "conversion_type": "pdf_to_word",
            "input_path": pdf,
            "output_dir": converted_dir,
            "recursive": false,
            "overwrite": true,
            "skip_template": false,
        }),
    )?;
    if pdf_to_word.get("success") != Some(&Value::Bool(true)) {
        return Err(format!("PDF to DOCX failed: {pdf_to_word}"));
    }
    let roundtrip_text = docx_text(&roundtrip)?;
    if !roundtrip_text.contains(EXPECTED_TEXT) {
        return Err(format!(
            "roundtrip DOCX lost expected text; extracted={roundtrip_text:?}"
        ));
    }

    Ok(json!({
        "ok": true,
        "run_dir": run_dir,
        "source": source,
        "pdf": pdf,
        "roundtrip": roundtrip,
        "pdf_bytes": pdf_bytes.len(),
        "roundtrip_text": roundtrip_text,
        "word_to_pdf": word_to_pdf,
        "pdf_to_word": pdf_to_word,
    }))
}

fn write_docx(path: &Path) -> Result<(), String> {
    let file = File::create(path).map_err(|error| error.to_string())?;
    let mut writer = ZipWriter::new(file);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for (name, contents) in [
        (
            "[Content_Types].xml",
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"#,
        ),
        (
            "_rels/.rels",
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"#,
        ),
        (
            "word/document.xml",
            r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>KOI Rust COM roundtrip 4.0.0</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>"#,
        ),
    ] {
        writer
            .start_file(name, options)
            .map_err(|error| error.to_string())?;
        writer
            .write_all(contents.as_bytes())
            .map_err(|error| error.to_string())?;
    }
    writer.finish().map_err(|error| error.to_string())?;
    Ok(())
}

fn docx_text(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|error| format!("read DOCX: {error}"))?;
    let mut archive =
        ZipArchive::new(Cursor::new(bytes)).map_err(|error| format!("open DOCX ZIP: {error}"))?;
    let mut xml = Vec::new();
    archive
        .by_name("word/document.xml")
        .map_err(|error| format!("open Word XML: {error}"))?
        .read_to_end(&mut xml)
        .map_err(|error| format!("read Word XML: {error}"))?;
    let mut reader = Reader::from_reader(Cursor::new(xml));
    reader.config_mut().trim_text(false);
    let mut buffer = Vec::new();
    let mut output = String::new();
    loop {
        match reader.read_event_into(&mut buffer) {
            Ok(Event::Text(text)) => output.push_str(
                &text
                    .decode()
                    .map_err(|error| format!("decode Word text: {error}"))?,
            ),
            Ok(Event::Eof) => break,
            Ok(_) => {}
            Err(error) => return Err(format!("parse Word XML: {error}")),
        }
        buffer.clear();
    }
    Ok(output)
}
