use calamine::{open_workbook_auto, Data, Reader};
use encoding_rs::GBK;
use std::fs;
use std::path::Path;

pub(super) fn read_lines_file(path: &Path) -> Result<Vec<String>, String> {
    if !path.exists() {
        return Err(format!("文件不存在: {}", path.display()));
    }
    match path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "xlsx" | "xls" => read_excel_first_column(path),
        "csv" => read_delimited_first_column(path, b',', "CSV"),
        "tsv" => read_delimited_first_column(path, b'\t', "TSV"),
        _ => read_text_lines(path),
    }
}

fn read_excel_first_column(path: &Path) -> Result<Vec<String>, String> {
    let mut workbook =
        open_workbook_auto(path).map_err(|error| format!("读取 Excel 批量文件失败: {error}"))?;
    let range = workbook
        .worksheet_range_at(0)
        .ok_or_else(|| "Excel 文件没有工作表".to_string())?
        .map_err(|error| format!("读取 Excel 工作表失败: {error}"))?;
    Ok(range
        .rows()
        .filter_map(|row| row.first())
        .map(display_excel)
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .collect())
}

fn read_delimited_first_column(
    path: &Path,
    delimiter: u8,
    format_name: &str,
) -> Result<Vec<String>, String> {
    let bytes = fs::read(path).map_err(|error| format!("读取批量文件失败: {error}"))?;
    let content = decode_text(&bytes);
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .delimiter(delimiter)
        .from_reader(content.as_bytes());
    let mut lines = Vec::new();
    for row in reader.records() {
        let row = row.map_err(|error| format!("读取 {format_name} 批量文件失败: {error}"))?;
        if let Some(value) = row.get(0).map(str::trim).filter(|value| !value.is_empty()) {
            lines.push(value.to_string());
        }
    }
    Ok(lines)
}

fn read_text_lines(path: &Path) -> Result<Vec<String>, String> {
    let bytes = fs::read(path).map_err(|error| format!("读取批量文件失败: {error}"))?;
    let content = decode_text(&bytes);
    Ok(content
        .lines()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect())
}

fn decode_text(bytes: &[u8]) -> String {
    if let Ok(text) = std::str::from_utf8(strip_utf8_bom(bytes)) {
        text.to_string()
    } else {
        let (decoded, _, had_errors) = GBK.decode(bytes);
        if had_errors {
            decode_utf8_ignoring_invalid(bytes)
        } else {
            decoded.into_owned()
        }
    }
}

fn strip_utf8_bom(bytes: &[u8]) -> &[u8] {
    bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(bytes)
}

fn decode_utf8_ignoring_invalid(bytes: &[u8]) -> String {
    let mut remaining = bytes;
    let mut output = String::new();
    while !remaining.is_empty() {
        match std::str::from_utf8(remaining) {
            Ok(valid) => {
                output.push_str(valid);
                break;
            }
            Err(error) => {
                let valid = error.valid_up_to();
                if valid > 0 {
                    output.push_str(
                        std::str::from_utf8(&remaining[..valid])
                            .expect("UTF-8 error valid_up_to prefix must be valid"),
                    );
                }
                match error.error_len() {
                    Some(length) => remaining = &remaining[valid + length..],
                    None => break,
                }
            }
        }
    }
    output
}

fn display_excel(value: &Data) -> String {
    match value {
        Data::Empty => String::new(),
        Data::Int(value) => value.to_string(),
        Data::Float(value) => value.to_string(),
        Data::String(value) | Data::DateTimeIso(value) | Data::DurationIso(value) => value.clone(),
        Data::Bool(true) => "True".to_string(),
        Data::Bool(false) => "False".to_string(),
        Data::DateTime(value) => value.as_f64().to_string(),
        Data::Error(value) => format!("{value:?}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    static NEXT_FILE_ID: AtomicU64 = AtomicU64::new(0);

    fn temp_file(extension: &str, contents: &[u8]) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock after epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "koi-batch-input-{}-{nanos}-{}.{}",
            std::process::id(),
            NEXT_FILE_ID.fetch_add(1, Ordering::Relaxed),
            extension
        ));
        fs::write(&path, contents).expect("write batch fixture");
        path
    }

    #[test]
    fn reads_text_and_delimited_first_columns() {
        let text = temp_file("txt", "3.3.3.3\r\n4.4.4.4\r\n".as_bytes());
        assert_eq!(
            read_lines_file(&text).expect("text lines"),
            vec!["3.3.3.3", "4.4.4.4"]
        );
        fs::remove_file(text).expect("remove text fixture");

        let csv = temp_file("csv", b"\xef\xbb\xbf5.5.5.5,name\r\n6.6.6.6,name\r\n");
        assert_eq!(
            read_lines_file(&csv).expect("CSV lines"),
            vec!["5.5.5.5", "6.6.6.6"]
        );
        fs::remove_file(csv).expect("remove CSV fixture");

        let tsv = temp_file("tsv", b"7.7.7.7\tname\r\n8.8.8.8\tname\r\n");
        assert_eq!(
            read_lines_file(&tsv).expect("TSV lines"),
            vec!["7.7.7.7", "8.8.8.8"]
        );
        fs::remove_file(tsv).expect("remove TSV fixture");

        let (gbk, _, _) = GBK.encode("域名.example,名称\r\n第二.example,名称\r\n");
        let csv = temp_file("csv", &gbk);
        assert_eq!(
            read_lines_file(&csv).expect("GBK CSV lines"),
            vec!["域名.example", "第二.example"]
        );
        fs::remove_file(csv).expect("remove GBK CSV fixture");
    }
}
