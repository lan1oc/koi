//! Render the recorded HTTP results, never a simulated target browser page.
use fontdue::{Font, FontSettings};
use image::{ImageEncoder, Rgb, RgbImage};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::OnceLock;

pub(super) fn snapshot_text(result: &Value) -> String {
    let mut lines = vec![
        "KOI 复测结果记录".to_string(),
        "依据本次 HTTP 请求记录生成".to_string(),
        result["summary"]
            .as_str()
            .unwrap_or("复测观察记录")
            .chars()
            .take(250)
            .collect(),
    ];
    if let Some(observations) = result["retest_results"].as_array() {
        for (index, item) in observations.iter().take(3).enumerate() {
            lines.push(String::new());
            lines.push(format!(
                "目标 {}：{}",
                index + 1,
                item["url"]
                    .as_str()
                    .unwrap_or_default()
                    .chars()
                    .take(160)
                    .collect::<String>()
            ));
            lines.push(format!(
                "时间：{}",
                item["checked_at"].as_str().unwrap_or("未记录")
            ));
            if item["target_unreachable"] == true {
                lines.push("访问结果：目标当前不可访问，本次未复现".into());
                lines.push(format!(
                    "原因：{}",
                    item["error"]
                        .as_str()
                        .unwrap_or("连接失败")
                        .chars()
                        .take(200)
                        .collect::<String>()
                ));
            } else {
                lines.push(format!("HTTP 状态：{}", item["status_code"]));
            }
        }
        if observations.len() > 3 {
            lines.push("更多目标详见报告文字记录。".into());
        }
    }
    lines.join("\n")
}

pub(super) fn render_snapshot(result: &Value) -> Result<Vec<u8>, String> {
    static FONT: OnceLock<Result<Font, String>> = OnceLock::new();
    let font = FONT
        .get_or_init(|| {
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
            Err("无法加载中文字体以生成复测证据图".into())
        })
        .as_ref()
        .map_err(Clone::clone)?;
    let text = snapshot_text(result);
    let mut layout = fontdue::layout::Layout::new(fontdue::layout::CoordinateSystem::PositiveYDown);
    layout.reset(&fontdue::layout::LayoutSettings {
        x: 32.0,
        y: 28.0,
        max_width: Some(896.0),
        ..Default::default()
    });
    layout.append(&[font], &fontdue::layout::TextStyle::new(&text, 22.0, 0));
    let height = (layout.height().ceil() as u32 + 60).clamp(280, 2200);
    let mut image = RgbImage::from_pixel(960, height, Rgb([255, 255, 255]));
    for glyph in layout.glyphs() {
        if glyph.parent.is_control() {
            continue;
        }
        let (metrics, bitmap) = font.rasterize_config(glyph.key);
        for y in 0..metrics.height {
            for x in 0..metrics.width {
                let px = glyph.x as i32 + x as i32;
                let py = glyph.y as i32 + y as i32;
                if px < 0 || py < 0 || px >= 960 || py >= height as i32 {
                    continue;
                }
                let alpha = u16::from(bitmap[y * metrics.width + x]);
                let shade = (255 - (alpha * 222 / 255)) as u8;
                image.put_pixel(px as u32, py as u32, Rgb([shade, shade, shade]));
            }
        }
    }
    let mut bytes = Vec::new();
    image::codecs::png::PngEncoder::new(&mut bytes)
        .write_image(
            image.as_raw(),
            image.width(),
            image.height(),
            image::ColorType::Rgb8,
        )
        .map_err(|error| format!("生成复测证据图失败: {error}"))?;
    Ok(bytes)
}
