use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct BackendRequest {
    pub command: String,
    #[serde(default)]
    pub payload: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BackendResponse {
    pub ok: bool,
    pub data: Value,
    pub error: Option<String>,
}

impl BackendResponse {
    pub fn success(data: Value) -> Self {
        Self {
            ok: true,
            data,
            error: None,
        }
    }

    pub fn failure(error: impl Into<String>) -> Self {
        Self {
            ok: false,
            data: Value::Null,
            error: Some(error.into()),
        }
    }
}
