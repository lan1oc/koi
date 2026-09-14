//! Local asset-mapping helpers.
//!
//! The syntax documentation is intentionally data-only.  The previous Python
//! implementation built these responses from static modules; embedding the
//! reviewed JSON snapshots keeps the public response byte-for-byte compatible
//! without loading a Python interpreter or treating untrusted input as code.

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

const FOFA_DOC: &str = include_str!("syntax_docs/fofa.json");
const HUNTER_DOC: &str = include_str!("syntax_docs/hunter.json");
const QUAKE_DOC: &str = include_str!("syntax_docs/quake.json");

const COMMAND: &str = "info.asset.syntax_doc";

#[derive(Debug, Clone, Default)]
struct CompatText(String);

impl<'de> Deserialize<'de> for CompatText {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        Ok(Self(if python_truthy(&value) {
            python_string(&value).trim().to_string()
        } else {
            String::new()
        }))
    }
}

#[derive(Debug, Default, Deserialize)]
struct SyntaxDocRequest {
    #[serde(default)]
    platform: CompatText,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum AssetPlatform {
    Fofa,
    Hunter,
    Quake,
}

impl AssetPlatform {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "fofa" => Some(Self::Fofa),
            "hunter" => Some(Self::Hunter),
            "quake" => Some(Self::Quake),
            _ => None,
        }
    }

    fn document(self) -> &'static str {
        match self {
            Self::Fofa => FOFA_DOC,
            Self::Hunter => HUNTER_DOC,
            Self::Quake => QUAKE_DOC,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct SyntaxExamples {
    #[serde(rename = "基础查询")]
    basic: Vec<String>,
    #[serde(rename = "组合查询")]
    combined: Vec<String>,
    #[serde(rename = "高级查询")]
    advanced: Vec<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct SyntaxDocResponse {
    success: bool,
    message: String,
    platform: AssetPlatform,
    title: String,
    text: String,
    common_fields: Vec<String>,
    examples: SyntaxExamples,
}

pub fn dispatch(command: &str, payload: &Value) -> Result<Value, String> {
    if command != COMMAND {
        return Err(format!("未知资产测绘命令: {command}"));
    }

    let request = parse_request(payload)?;
    let normalized_platform = request.platform.0.to_lowercase();
    if normalized_platform.is_empty() {
        return Err("请选择语法平台".to_string());
    }
    let platform = AssetPlatform::parse(&normalized_platform)
        .ok_or_else(|| format!("不支持的语法平台: {normalized_platform}"))?;

    let response: SyntaxDocResponse = serde_json::from_str(platform.document())
        .map_err(|error| format!("语法文档资源损坏: {error}"))?;
    // The files are generated from the Python oracle with the platform fixed,
    // but retain this invariant at the boundary in case an asset is replaced.
    if response.platform != platform {
        return Err("语法文档平台与资源不匹配".to_string());
    }
    serde_json::to_value(response).map_err(|error| format!("语法文档响应序列化失败: {error}"))
}

fn parse_request(payload: &Value) -> Result<SyntaxDocRequest, String> {
    // Legacy callers treat a non-object payload like an object with no fields.
    if !payload.is_object() {
        return Ok(SyntaxDocRequest::default());
    }
    serde_json::from_value(payload.clone()).map_err(|error| format!("请求参数格式错误: {error}"))
}

fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn python_string(value: &Value) -> String {
    match value {
        Value::Null => "None".to_string(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_string(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        Value::Array(_) | Value::Object(_) => value.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn returns_compatibility_snapshot_for_each_platform() {
        for platform in ["fofa", "hunter", "quake"] {
            let response = dispatch(COMMAND, &json!({"platform": platform})).unwrap();
            assert_eq!(response["success"], true);
            assert_eq!(response["platform"], platform);
            assert!(response["title"]
                .as_str()
                .is_some_and(|value| !value.is_empty()));
            assert!(response["text"]
                .as_str()
                .is_some_and(|value| !value.is_empty()));
            assert!(response["common_fields"]
                .as_array()
                .is_some_and(|value| !value.is_empty()));
            assert!(response["examples"]
                .as_object()
                .is_some_and(|value| !value.is_empty()));
        }
    }

    #[test]
    fn typed_response_matches_the_embedded_oracle_snapshot() {
        let expected: Value = serde_json::from_str(FOFA_DOC).unwrap();
        let actual = dispatch(COMMAND, &json!({"platform": " fOfA "})).unwrap();
        assert_eq!(actual, expected);
    }

    #[test]
    fn normalizes_platform_case_and_rejects_missing_or_unknown_platform() {
        assert_eq!(
            dispatch(COMMAND, &json!({"platform": "FOFA"})).unwrap()["platform"],
            "fofa"
        );
        assert!(dispatch(COMMAND, &json!({"platform": 0}))
            .unwrap_err()
            .contains("请选择"));
        assert!(dispatch(COMMAND, &json!({"platform": 1}))
            .unwrap_err()
            .contains("不支持"));
        assert!(dispatch(COMMAND, &json!({}))
            .unwrap_err()
            .contains("请选择"));
        assert!(dispatch(COMMAND, &json!({"platform": "unknown"}))
            .unwrap_err()
            .contains("不支持"));
        assert_eq!(dispatch(COMMAND, &json!([])).unwrap_err(), "请选择语法平台");
        assert_eq!(
            dispatch(COMMAND, &json!({"platform": true})).unwrap_err(),
            "不支持的语法平台: true"
        );
    }
}
