//! Local asset-mapping helpers.
//!
//! The syntax documentation is intentionally data-only.  The previous Python
//! implementation built these responses from static modules; embedding the
//! reviewed JSON snapshots keeps the public response byte-for-byte compatible
//! without loading a Python interpreter or treating untrusted input as code.

use serde_json::Value;

const FOFA_DOC: &str = include_str!("syntax_docs/fofa.json");
const HUNTER_DOC: &str = include_str!("syntax_docs/hunter.json");
const QUAKE_DOC: &str = include_str!("syntax_docs/quake.json");

const COMMAND: &str = "info.asset.syntax_doc";

pub fn is_command(command: &str) -> bool {
    command == COMMAND
}

pub fn dispatch(command: &str, payload: &Value) -> Result<Value, String> {
    if command != COMMAND {
        return Err(format!("未知资产测绘命令: {command}"));
    }

    let platform = payload
        .get("platform")
        .filter(|value| python_truthy(value))
        .map(python_string)
        .unwrap_or_default()
        .trim()
        .to_lowercase();
    if platform.is_empty() {
        return Err("请选择语法平台".to_string());
    }

    let raw = match platform.as_str() {
        "fofa" => FOFA_DOC,
        "hunter" => HUNTER_DOC,
        "quake" => QUAKE_DOC,
        _ => return Err(format!("不支持的语法平台: {platform}")),
    };

    let mut response: Value =
        serde_json::from_str(raw).map_err(|error| format!("语法文档资源损坏: {error}"))?;
    // The files are generated from the Python oracle with the platform fixed,
    // but retain this invariant at the boundary in case an asset is replaced.
    if response.get("platform").and_then(Value::as_str) != Some(platform.as_str()) {
        return Err("语法文档平台与资源不匹配".to_string());
    }
    if let Some(object) = response.as_object_mut() {
        object.insert("platform".to_string(), Value::String(platform));
    }
    Ok(response)
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
    }
}
