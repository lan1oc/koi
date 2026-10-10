//! Report figures and editable text use the same recorded tool output as the Agent UI.
use fontdue::{Font, FontSettings};
use image::{ImageEncoder, Rgb, RgbImage};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::OnceLock;

fn format_time(raw: &str) -> String {
    chrono::DateTime::parse_from_rfc3339(raw)
        .map(|time| {
            time.with_timezone(&chrono::FixedOffset::east_opt(8 * 3600).expect("valid timezone"))
                .format("%Y-%m-%d %H:%M:%S +0800")
                .to_string()
        })
        .unwrap_or_else(|_| raw.to_string())
}

fn append(lines: &mut Vec<String>, label: &str, value: &Value) {
    if value.is_null() {
        return;
    }
    let text = value
        .as_str()
        .map(str::to_string)
        .unwrap_or_else(|| serde_json::to_string_pretty(value).unwrap_or_default());
    if !text.trim().is_empty() {
        lines.push(format!("{label}\n{text}"));
    }
}

pub(super) fn tool_text(tool: &str, data: &Value) -> String {
    let mut lines = Vec::new();
    if let Some(url) = data["url"].as_str() {
        lines.push(format!(
            "{} {url}",
            data["method"].as_str().unwrap_or("GET")
        ));
    }
    if data["status_code"].is_number() {
        lines.push(format!("HTTP {}", data["status_code"]));
    }
    append(&mut lines, "响应头", &data["headers"]);
    append(&mut lines, "响应正文", &data["body_excerpt"]);
    if let Some(findings) = data["findings"].as_array() {
        for finding in findings {
            append(&mut lines, "探测输出", &finding["evidence"]);
        }
    }
    if let Some(observations) = data["observations"].as_array() {
        for item in observations {
            let text = tool_text("http_request", item);
            if !text.is_empty() {
                lines.push(text);
            }
        }
    }
    if tool == "run_python_probe" || data["python_probe"] == true {
        append(&mut lines, "脚本标准输出", &data["stdout"]);
        append(&mut lines, "脚本返回值", &data["result"]);
        append(&mut lines, "请求记录", &data["http_observations"]);
        append(&mut lines, "脚本错误输出", &data["stderr"]);
    }
    for key in ["raw_output", "output", "evidence"] {
        append(&mut lines, "工具输出", &data[key]);
    }
    append(&mut lines, "错误", &data["error"]);
    if data["body_truncated"] == true {
        lines.push("响应超过读取上限，正文已截断".into());
    }
    if lines.is_empty() {
        append(&mut lines, "工具返回", data);
    }
    lines.join("\n\n")
}

#[derive(Debug)]
pub(super) struct EvidenceBlock {
    pub title: String,
    pub metadata: String,
    pub text: String,
}

pub(super) fn blocks(result: &Value) -> Vec<EvidenceBlock> {
    let cited = result["finding_judgements"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|judgement| judgement["evidence_ids"].as_array().into_iter().flatten())
        .filter_map(Value::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    let mut blocks = Vec::new();
    for evidence in result["agent_evidence"].as_array().into_iter().flatten() {
        let id = evidence["id"].as_str().unwrap_or_default();
        let tool = evidence["tool"].as_str().unwrap_or("tool");
        if (!cited.is_empty() && !cited.contains(id))
            || matches!(
                tool,
                "read_notice"
                    | "read_evidence"
                    | "record_finding"
                    | "finish_investigation"
                    | "install_tools"
                    | "tool_status"
            )
        {
            continue;
        }
        let data = &evidence["data"];
        blocks.push(EvidenceBlock {
            title: format!("证据 {id}  {tool}"),
            metadata: format!(
                "采集时间 {}    执行状态 {}",
                format_time(evidence["checked_at"].as_str().unwrap_or("未记录")),
                if evidence["success"] == true {
                    "完成"
                } else {
                    "未完成"
                }
            ),
            text: tool_text(tool, data),
        });
    }
    if blocks.is_empty() {
        for (index, item) in result["retest_results"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            blocks.push(EvidenceBlock {
                title: format!("访问记录 {}", index + 1),
                metadata: format!(
                    "采集时间 {}",
                    format_time(item["checked_at"].as_str().unwrap_or("未记录"))
                ),
                text: tool_text("http_request", item),
            });
        }
    }
    blocks
}

pub(super) fn snapshot_text(result: &Value) -> String {
    blocks(result)
        .into_iter()
        .map(|block| format!("{}\n{}\n{}", block.title, block.metadata, block.text))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn font() -> Result<&'static Font, String> {
    static FONT: OnceLock<Result<Font, String>> = OnceLock::new();
    FONT.get_or_init(|| {
        let system = std::env::var_os("SystemRoot")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(r"C:\Windows"));
        for name in ["msyh.ttc", "simhei.ttf", "simsun.ttc"] {
            if let Ok(bytes) = std::fs::read(system.join("Fonts").join(name)) {
                if let Ok(font) = Font::from_bytes(bytes, FontSettings::default()) {
                    return Ok(font);
                }
            }
        }
        Err("无法加载证据图字体".into())
    })
    .as_ref()
    .map_err(Clone::clone)
}

fn mono_font() -> Result<&'static Font, String> {
    static FONT: OnceLock<Result<Font, String>> = OnceLock::new();
    FONT.get_or_init(|| {
        let system = std::env::var_os("SystemRoot")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(r"C:\Windows"));
        let bytes =
            std::fs::read(system.join("Fonts/consola.ttf")).map_err(|error| error.to_string())?;
        Font::from_bytes(bytes, FontSettings::default()).map_err(|error| error.to_string())
    })
    .as_ref()
    .map_err(Clone::clone)
}

fn layout(
    value: &str,
    x: f32,
    y: f32,
    width: f32,
    size: f32,
    mono: bool,
) -> Result<fontdue::layout::Layout, String> {
    let fonts = [font()?, mono_font()?];
    let mut layout = fontdue::layout::Layout::new(fontdue::layout::CoordinateSystem::PositiveYDown);
    layout.reset(&fontdue::layout::LayoutSettings {
        x,
        y,
        max_width: if mono { None } else { Some(width) },
        ..Default::default()
    });
    let mut run = String::new();
    let mut index = 0;
    for character in value.chars() {
        let next = usize::from(mono && character.is_ascii());
        if next != index && !run.is_empty() {
            layout.append(&fonts, &fontdue::layout::TextStyle::new(&run, size, index));
            run.clear();
        }
        index = next;
        run.push(character);
    }
    if !run.is_empty() {
        layout.append(&fonts, &fontdue::layout::TextStyle::new(&run, size, index));
    }
    Ok(layout)
}

#[allow(clippy::too_many_arguments)]
fn text(
    image: &mut RgbImage,
    value: &str,
    x: f32,
    y: f32,
    width: f32,
    size: f32,
    color: [u8; 3],
    mono: bool,
) -> Result<f32, String> {
    let fonts = [font()?, mono_font()?];
    let layout = layout(value, x, y, width, size, mono)?;
    for glyph in layout.glyphs() {
        if glyph.parent.is_control() {
            continue;
        }
        let (metrics, bitmap) = fonts[glyph.font_index].rasterize_config(glyph.key);
        for gy in 0..metrics.height {
            for gx in 0..metrics.width {
                let px = glyph.x as i32 + gx as i32;
                let py = glyph.y as i32 + gy as i32;
                if px >= 0 && py >= 0 && px < image.width() as i32 && py < image.height() as i32 {
                    let alpha = u16::from(bitmap[gy * metrics.width + gx]);
                    let background = image.get_pixel(px as u32, py as u32).0;
                    let mut pixel = [0u8; 3];
                    for i in 0..3 {
                        pixel[i] = ((u16::from(color[i]) * alpha
                            + u16::from(background[i]) * (255 - alpha))
                            / 255) as u8;
                    }
                    image.put_pixel(px as u32, py as u32, Rgb(pixel));
                }
            }
        }
    }
    Ok(layout.height())
}

pub(super) fn render_snapshots(result: &Value) -> Result<Vec<Vec<u8>>, String> {
    let mut images = Vec::new();
    for block in blocks(result).into_iter().take(8) {
        let mut wrapped = Vec::new();
        for line in block.text.lines() {
            if line.is_empty() {
                wrapped.push(String::new());
                continue;
            }
            let mut current = String::new();
            let mut width = 0.0;
            for character in line.chars() {
                let advance = if character.is_ascii() {
                    mono_font()?
                } else {
                    font()?
                }
                .metrics(character, 30.0)
                .advance_width;
                if width + advance > 1368.0 && !current.is_empty() {
                    let boundary = current
                        .char_indices()
                        .rev()
                        .find(|(index, character)| {
                            *index > current.len() / 2 && character.is_whitespace()
                        })
                        .map(|(index, _)| index);
                    if let Some(boundary) = boundary {
                        let tail = current[boundary + 1..].to_string();
                        wrapped.push(current[..boundary].to_string());
                        current = tail;
                        width = current
                            .chars()
                            .map(|c| {
                                if c.is_ascii() {
                                    mono_font().expect("font loaded")
                                } else {
                                    font().expect("font loaded")
                                }
                                .metrics(c, 30.0)
                                .advance_width
                            })
                            .sum();
                    } else {
                        wrapped.push(std::mem::take(&mut current));
                        width = 0.0;
                    }
                }
                current.push(character);
                width += advance;
            }
            if !current.is_empty() {
                wrapped.push(current);
            }
        }
        for (index, lines) in wrapped.chunks(18).take(6).enumerate() {
            let body = lines.join("\n");
            let height = (layout(&body, 32.0, 136.0, 1368.0, 30.0, true)?
                .height()
                .ceil() as u32
                + 180)
                .max(240);
            let mut image = RgbImage::from_pixel(1440, height, Rgb([247, 249, 252]));
            for pixel in image.rows_mut().take(108).flatten() {
                *pixel = Rgb([26, 35, 52]);
            }
            let title = if index == 0 {
                block.title.clone()
            } else {
                format!("{}  续 {}", block.title, index + 1)
            };
            text(
                &mut image,
                &title,
                32.0,
                22.0,
                1368.0,
                28.0,
                [244, 247, 252],
                false,
            )?;
            text(
                &mut image,
                &block.metadata,
                32.0,
                66.0,
                1368.0,
                20.0,
                [183, 197, 219],
                false,
            )?;
            text(
                &mut image,
                &body,
                32.0,
                136.0,
                1368.0,
                30.0,
                [31, 41, 55],
                true,
            )?;
            let mut bytes = Vec::new();
            image::codecs::png::PngEncoder::new(&mut bytes)
                .write_image(
                    image.as_raw(),
                    image.width(),
                    image.height(),
                    image::ColorType::Rgb8,
                )
                .map_err(|error| error.to_string())?;
            images.push(bytes);
            if images.len() >= 16 {
                return Ok(images);
            }
        }
    }
    Ok(images)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn report_uses_cited_raw_tool_output_instead_of_repeated_model_conclusion() {
        let result = json!({"summary":"模型结论不应放进证据图","finding_judgements":[{"evidence_ids":["e2"]}],"agent_evidence":[{"id":"e1","tool":"record_finding","data":{"detail":"无用重复"}},{"id":"e2","tool":"run_tls_probe","success":true,"checked_at":"2026-10-09T08:00:00Z","data":{"findings":[{"evidence":"ssl-cert: Subject: CN=fixture.example\nNot valid before: 2026-09-23\nNot valid after: 2027-04-09"}]}}]});
        let text = snapshot_text(&result);
        assert!(text.contains("ssl-cert: Subject:"));
        assert!(text.contains("Not valid after: 2027-04-09"));
        assert!(!text.contains("模型结论"));
        assert!(!text.contains("无用重复"));
    }
}
