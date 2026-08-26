//! Native configuration and local tool inventory for the retest workbench.
//!
//! Model calls, downloads, and probe execution are intentionally outside this
//! module. Credentials remain durable internally and are always redacted from
//! IPC responses.

use super::config::ConfigStore;
use super::external_tools;
use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
#[cfg(test)]
use std::{env, path::PathBuf};

const COMMANDS: &[&str] = &[
    "doc.retest.ai_config.get",
    "doc.retest.ai_config.set",
    "doc.retest.tools.list",
    "doc.retest.tools.status",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct AiProfile {
    id: String,
    name: String,
    provider: String,
    base_url: String,
    api_key: String,
    model: String,
    temperature: f64,
    max_tokens: i64,
    context_window: i64,
    last_updated: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct AiStore {
    enabled: bool,
    active_profile_id: String,
    profiles: Vec<AiProfile>,
    last_updated: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct RuntimeAiProfile {
    pub id: String,
    pub name: String,
    pub provider: String,
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub temperature: f64,
    pub max_tokens: i64,
    pub context_window: i64,
}

#[derive(Debug, Clone, Serialize)]
struct SafeAiProfile {
    id: String,
    name: String,
    provider: String,
    base_url: String,
    api_key: String,
    model: String,
    temperature: f64,
    max_tokens: i64,
    context_window: i64,
    last_updated: String,
    api_key_configured: bool,
    api_key_masked: String,
}

#[derive(Debug, Clone, Serialize)]
struct ProviderOption {
    value: &'static str,
    label: &'static str,
    base_url: &'static str,
    model: &'static str,
    model_placeholder: &'static str,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
struct ToolSpec {
    tool_id: String,
    label: String,
    category: String,
    risk: String,
    tags: Vec<String>,
    requires: Vec<String>,
    description: String,
}

#[derive(Clone, Copy)]
struct ProviderDefaults {
    id: &'static str,
    label: &'static str,
    name: &'static str,
    base_url: &'static str,
    model: &'static str,
    placeholder: &'static str,
}

pub fn is_command(command: &str) -> bool {
    COMMANDS.contains(&command)
}

pub fn dispatch(
    command: &str,
    payload: &Value,
    config: &ConfigStore,
    tool_root: &Path,
) -> Result<Value, String> {
    match command {
        "doc.retest.ai_config.get" => ai_config_get(config),
        "doc.retest.ai_config.set" => ai_config_set(config, payload),
        "doc.retest.tools.list" => Ok(tools_list()),
        "doc.retest.tools.status" => Ok(tools_status(tool_root)),
        _ => Err(format!(
            "native retest config command not registered: {command}"
        )),
    }
}

pub(crate) fn runtime_profile(
    config: &ConfigStore,
    payload: &Value,
) -> Result<RuntimeAiProfile, String> {
    let root = config.load()?;
    let store = normalize_store(root.get("retest_ai_agent"));
    let request = payload.as_object().cloned().unwrap_or_default();
    let requested_id = request
        .get("profile_id")
        .and_then(value_text)
        .map(|value| sanitize_id(&value))
        .unwrap_or_else(|| store.active_profile_id.clone());
    let saved = store
        .profiles
        .iter()
        .find(|profile| profile.id == requested_id)
        .or_else(|| {
            store
                .profiles
                .iter()
                .find(|profile| profile.id == store.active_profile_id)
        })
        .or_else(|| store.profiles.first())
        .cloned()
        .unwrap_or_else(|| default_profile("default", "OpenAI", "openai"));
    let fallback_id = saved.id.clone();
    let fallback_name = saved.name.clone();
    let mut runtime = serde_json::to_value(saved)
        .map_err(|error| format!("serialize runtime AI profile: {error}"))?;
    let runtime_object = runtime
        .as_object_mut()
        .ok_or_else(|| "runtime AI profile must be an object".to_string())?;

    for key in ["provider", "base_url", "model"] {
        if let Some(value) = request.get(key) {
            runtime_object.insert(
                key.to_string(),
                Value::String(value_text(value).unwrap_or_default().trim().to_string()),
            );
        }
    }
    for key in ["temperature", "max_tokens", "context_window"] {
        if let Some(value) = request.get(key) {
            runtime_object.insert(key.to_string(), value.clone());
        }
    }
    if let Some(value) = request.get("api_key") {
        let incoming = value_text(value).unwrap_or_default().trim().to_string();
        if !incoming.is_empty()
            || request
                .get("clear_api_key")
                .and_then(value_bool)
                .unwrap_or(false)
        {
            runtime_object.insert("api_key".to_string(), Value::String(incoming));
        }
    }

    let normalized = normalize_profile(&runtime, &fallback_id, &fallback_name);
    Ok(RuntimeAiProfile {
        id: normalized.id,
        name: normalized.name,
        provider: normalized.provider,
        base_url: normalized.base_url,
        api_key: normalized.api_key,
        model: normalized.model,
        temperature: normalized.temperature,
        max_tokens: normalized.max_tokens,
        context_window: normalized.context_window,
    })
}

fn ai_config_get(config: &ConfigStore) -> Result<Value, String> {
    config.transact(|root| {
        let store = normalize_store(root.get("retest_ai_agent"));
        Ok((
            json!({
                "success": true,
                "message": "复测 AI Agent 配置已读取",
                "config": safe_store(&store),
            }),
            false,
        ))
    })
}

fn ai_config_set(config: &ConfigStore, payload: &Value) -> Result<Value, String> {
    let request = payload.as_object().cloned().unwrap_or_default();
    config.transact(move |root| {
        let mut store = normalize_store(root.get("retest_ai_agent"));
        if request.contains_key("enabled") {
            store.enabled = request.get("enabled").and_then(value_bool).unwrap_or(false);
        }
        let action = request
            .get("action")
            .and_then(value_text)
            .unwrap_or_else(|| "save_profile".to_string())
            .trim()
            .to_ascii_lowercase();
        let mut active_id = store.active_profile_id.clone();
        let message = match action.as_str() {
            "set_enabled" => if store.enabled {
                "复测 AI Agent 已启用"
            } else {
                "复测 AI Agent 已关闭"
            }
            .to_string(),
            "create_profile" => create_profile(&request, &mut store.profiles, &mut active_id),
            "switch_profile" => switch_profile(&request, &store.profiles, &mut active_id)?,
            "delete_profile" => delete_profile(&request, &mut store.profiles, &mut active_id)?,
            _ => save_profile(&request, &mut store.profiles, &mut active_id),
        };
        if store.profiles.is_empty() {
            store
                .profiles
                .push(default_profile("default", "OpenAI", "openai"));
        }
        if !store.profiles.iter().any(|profile| profile.id == active_id) {
            active_id = store.profiles[0].id.clone();
        }
        store.active_profile_id = active_id;
        store.last_updated = timestamp();
        let persisted = serde_json::to_value(&store)
            .map_err(|error| format!("serialize retest AI configuration: {error}"))?;
        root.as_object_mut()
            .ok_or_else(|| "configuration root must be an object".to_string())?
            .insert("retest_ai_agent".to_string(), persisted);
        Ok((
            json!({"success": true, "message": message, "config": safe_store(&store)}),
            true,
        ))
    })
}

fn create_profile(
    request: &Map<String, Value>,
    profiles: &mut Vec<AiProfile>,
    active_id: &mut String,
) -> String {
    let provider_text = request
        .get("provider")
        .and_then(value_text)
        .unwrap_or_else(|| "openai".to_string());
    let provider = normalize_provider(&provider_text);
    let requested = request
        .get("profile_id")
        .or_else(|| request.get("name"))
        .and_then(value_text)
        .unwrap_or_else(|| provider.to_string());
    let id = unique_id(&sanitize_id(&requested), profiles);
    let name = request
        .get("name")
        .and_then(value_text)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| provider_defaults(provider).name.to_string());
    let mut profile = default_profile(&id, name.trim(), provider);
    profile.last_updated = timestamp();
    profiles.push(profile);
    *active_id = id;
    "复测 AI 配置档已创建".to_string()
}

fn switch_profile(
    request: &Map<String, Value>,
    profiles: &[AiProfile],
    active_id: &mut String,
) -> Result<String, String> {
    let requested = sanitize_id(
        &request
            .get("profile_id")
            .and_then(value_text)
            .unwrap_or_else(|| active_id.clone()),
    );
    if !profiles.iter().any(|profile| profile.id == requested) {
        return Err("要切换的 AI 配置档不存在".to_string());
    }
    *active_id = requested;
    Ok("已切换复测 AI 配置档".to_string())
}

fn delete_profile(
    request: &Map<String, Value>,
    profiles: &mut Vec<AiProfile>,
    active_id: &mut String,
) -> Result<String, String> {
    if profiles.len() <= 1 {
        return Err("至少需要保留一个 AI 配置档".to_string());
    }
    let requested = sanitize_id(
        &request
            .get("profile_id")
            .and_then(value_text)
            .unwrap_or_else(|| active_id.clone()),
    );
    let before = profiles.len();
    profiles.retain(|profile| profile.id != requested);
    if profiles.len() == before {
        return Err("要删除的 AI 配置档不存在".to_string());
    }
    if active_id == &requested {
        *active_id = profiles[0].id.clone();
    }
    Ok("复测 AI 配置档已删除".to_string())
}

fn save_profile(
    request: &Map<String, Value>,
    profiles: &mut Vec<AiProfile>,
    active_id: &mut String,
) -> String {
    let requested = sanitize_id(
        &request
            .get("profile_id")
            .and_then(value_text)
            .unwrap_or_else(|| active_id.clone()),
    );
    let position = profiles.iter().position(|profile| profile.id == requested);
    let existing_provider = position
        .map(|index| profiles[index].provider.as_str())
        .unwrap_or("openai");
    let provider_text = request
        .get("provider")
        .and_then(value_text)
        .unwrap_or_else(|| existing_provider.to_string());
    let provider = normalize_provider(&provider_text);
    if position.is_none() {
        let name = request
            .get("name")
            .and_then(value_text)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| provider_defaults(provider).name.to_string());
        profiles.push(default_profile(&requested, &name, provider));
    }
    let index = position.unwrap_or(profiles.len() - 1);
    let profile = &mut profiles[index];
    let previous_provider = profile.provider.clone();
    profile.provider = provider.to_string();
    let defaults = provider_defaults(provider);
    if request.contains_key("name") {
        let name = request
            .get("name")
            .and_then(value_text)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| {
                if profile.name.trim().is_empty() {
                    profile.id.clone()
                } else {
                    profile.name.clone()
                }
            });
        profile.name = name.trim().chars().take(80).collect();
    }
    if request.contains_key("base_url") {
        let incoming = request
            .get("base_url")
            .and_then(value_text)
            .unwrap_or_default();
        profile.base_url = if incoming.trim().is_empty() {
            defaults.base_url.to_string()
        } else {
            incoming.trim().to_string()
        };
    } else if provider != previous_provider && profile.base_url.trim().is_empty() {
        profile.base_url = defaults.base_url.to_string();
    }
    if request.contains_key("model") {
        let incoming = request
            .get("model")
            .and_then(value_text)
            .unwrap_or_default();
        profile.model = if incoming.trim().is_empty() {
            defaults.model.to_string()
        } else {
            incoming.trim().to_string()
        };
    } else if provider != previous_provider && profile.model.trim().is_empty() {
        profile.model = defaults.model.to_string();
    }
    if request.contains_key("api_key") {
        let incoming = request
            .get("api_key")
            .and_then(value_text)
            .unwrap_or_default();
        if !incoming.trim().is_empty()
            || request
                .get("clear_api_key")
                .and_then(value_bool)
                .unwrap_or(false)
        {
            profile.api_key = incoming.trim().to_string();
        }
    }
    if request.contains_key("temperature") {
        profile.temperature = request
            .get("temperature")
            .and_then(value_f64)
            .unwrap_or(0.1)
            .clamp(0.0, 2.0);
    }
    if request.contains_key("max_tokens") {
        profile.max_tokens = request
            .get("max_tokens")
            .and_then(value_i64)
            .unwrap_or(800)
            .clamp(128, 65_536);
    }
    if request.contains_key("context_window") {
        profile.context_window = request
            .get("context_window")
            .and_then(value_i64)
            .unwrap_or(128_000)
            .clamp(4_096, 2_000_000);
    }
    profile.last_updated = timestamp();
    let before_resolve = profile.base_url.trim().to_string();
    resolve_profile_provider(profile, true);
    *active_id = requested;
    let mut message = format!(
        "复测 AI 配置档已保存（{}）",
        provider_defaults(&profile.provider).label
    );
    if !before_resolve.is_empty()
        && !profile.base_url.is_empty()
        && before_resolve.trim_end_matches('/') != profile.base_url.trim_end_matches('/')
    {
        message.push_str(&format!("，Base URL 已自动修正为 {}", profile.base_url));
    }
    message
}

const PROVIDERS: &[ProviderDefaults] = &[
    ProviderDefaults {
        id: "openai",
        label: "OpenAI 标准",
        name: "OpenAI",
        base_url: "https://api.openai.com/v1",
        model: "gpt-4o-mini",
        placeholder: "gpt-4o-mini",
    },
    ProviderDefaults {
        id: "anthropic",
        label: "Anthropic 标准",
        name: "Anthropic",
        base_url: "https://api.anthropic.com/v1",
        model: "claude-3-5-sonnet-latest",
        placeholder: "claude-3-5-sonnet-latest",
    },
    ProviderDefaults {
        id: "openrouter",
        label: "OpenRouter 免费路由",
        name: "OpenRouter 免费路由",
        base_url: "https://openrouter.ai/api/v1",
        model: "openrouter/free",
        placeholder: "openrouter/free",
    },
    ProviderDefaults {
        id: "openai_compatible",
        label: "自定义 OpenAI 兼容",
        name: "自定义 OpenAI 兼容",
        base_url: "",
        model: "",
        placeholder: "模型 ID",
    },
    ProviderDefaults {
        id: "dashscope",
        label: "阿里云百炼/通义千问",
        name: "阿里云百炼/通义千问",
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-plus",
        placeholder: "qwen-plus",
    },
    ProviderDefaults {
        id: "deepseek",
        label: "DeepSeek",
        name: "DeepSeek",
        base_url: "https://api.deepseek.com",
        model: "deepseek-v4-flash",
        placeholder: "deepseek-v4-flash",
    },
    ProviderDefaults {
        id: "moonshot",
        label: "月之暗面/Kimi",
        name: "月之暗面/Kimi",
        base_url: "https://api.moonshot.ai/v1",
        model: "moonshot-v1-8k",
        placeholder: "moonshot-v1-8k",
    },
    ProviderDefaults {
        id: "bigmodel",
        label: "智谱 BigModel/GLM",
        name: "智谱 BigModel/GLM",
        base_url: "https://open.bigmodel.cn/api/paas/v4",
        model: "glm-4-flash",
        placeholder: "glm-4-flash",
    },
    ProviderDefaults {
        id: "qianfan",
        label: "百度千帆/文心",
        name: "百度千帆/文心",
        base_url: "https://qianfan.baidubce.com/v2",
        model: "ernie-4.5-turbo-128k",
        placeholder: "ernie-4.5-turbo-128k 或 qianfan-code-latest",
    },
    ProviderDefaults {
        id: "hunyuan",
        label: "腾讯混元",
        name: "腾讯混元",
        base_url: "https://api.hunyuan.cloud.tencent.com/v1",
        model: "hunyuan-turbos-latest",
        placeholder: "hunyuan-turbos-latest",
    },
    ProviderDefaults {
        id: "volcengine",
        label: "火山方舟/豆包",
        name: "火山方舟/豆包",
        base_url: "https://ark.cn-beijing.volces.com/api/v3",
        model: "",
        placeholder: "ep-xxxxxxxx 或 ark-code-latest",
    },
    ProviderDefaults {
        id: "siliconflow",
        label: "硅基流动 SiliconFlow",
        name: "硅基流动 SiliconFlow",
        base_url: "https://api.siliconflow.cn/v1",
        model: "Qwen/Qwen3-8B",
        placeholder: "Qwen/Qwen3-8B",
    },
    ProviderDefaults {
        id: "lingyiwanwu",
        label: "零一万物 01.AI",
        name: "零一万物 01.AI",
        base_url: "https://api.lingyiwanwu.com/v1",
        model: "yi-large",
        placeholder: "yi-large",
    },
    ProviderDefaults {
        id: "xfyun",
        label: "讯飞星火",
        name: "讯飞星火",
        base_url: "https://spark-api-open.xf-yun.com/v1",
        model: "4.0Ultra",
        placeholder: "4.0Ultra",
    },
    ProviderDefaults {
        id: "minimax",
        label: "MiniMax",
        name: "MiniMax",
        base_url: "https://api.minimax.chat/v1",
        model: "MiniMax-Text-01",
        placeholder: "MiniMax-Text-01",
    },
    ProviderDefaults {
        id: "baichuan",
        label: "百川智能",
        name: "百川智能",
        base_url: "https://api.baichuan-ai.com/v1",
        model: "Baichuan4",
        placeholder: "Baichuan4",
    },
    ProviderDefaults {
        id: "stepfun",
        label: "阶跃星辰 StepFun",
        name: "阶跃星辰 StepFun",
        base_url: "https://api.stepfun.com/v1",
        model: "step-3.7-flash",
        placeholder: "step-3.7-flash",
    },
    ProviderDefaults {
        id: "modelscope",
        label: "魔搭 ModelScope",
        name: "魔搭 ModelScope",
        base_url: "https://api-inference.modelscope.cn/v1",
        model: "Qwen/Qwen3-8B",
        placeholder: "Qwen/Qwen3-8B",
    },
    ProviderDefaults {
        id: "gemini",
        label: "Google Gemini OpenAI 兼容",
        name: "Google Gemini",
        base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
        model: "gemini-3.5-flash",
        placeholder: "gemini-3.5-flash",
    },
];

const AUTO_PROVIDER: ProviderDefaults = ProviderDefaults {
    id: "auto",
    label: "自动识别",
    name: "自动识别",
    base_url: "",
    model: "",
    placeholder: "按 Base URL / Model 自动匹配",
};

fn provider_defaults(provider: &str) -> ProviderDefaults {
    if provider == "auto" {
        return AUTO_PROVIDER;
    }
    PROVIDERS
        .iter()
        .copied()
        .find(|item| item.id == provider)
        .unwrap_or(PROVIDERS[0])
}

fn normalize_provider(value: &str) -> &'static str {
    match value.trim().to_ascii_lowercase().replace(' ', "_").as_str() {
        "auto" | "automatic" | "自动" | "自动识别" => "auto",
        "anthropic" => "anthropic",
        "openrouter" => "openrouter",
        "custom" | "openai-compatible" | "openai_compat" | "openai_compatible" => {
            "openai_compatible"
        }
        "dashscope" | "aliyun" | "bailian" | "tongyi" | "qwen" => "dashscope",
        "deepseek" => "deepseek",
        "moonshot" | "kimi" => "moonshot",
        "bigmodel" | "zhipu" | "glm" => "bigmodel",
        "qianfan" | "baidu" | "wenxin" | "ernie" => "qianfan",
        "hunyuan" | "tencent" => "hunyuan",
        "volcengine" | "doubao" | "ark" | "volces" => "volcengine",
        "siliconflow" => "siliconflow",
        "lingyiwanwu" | "01ai" | "yi" => "lingyiwanwu",
        "xfyun" | "spark" | "iflytek" => "xfyun",
        "minimax" => "minimax",
        "baichuan" | "baichuan-ai" => "baichuan",
        "stepfun" | "step" => "stepfun",
        "modelscope" => "modelscope",
        "gemini" | "google" | "googleai" | "google-ai" => "gemini",
        _ => "openai",
    }
}

fn provider_options() -> Vec<ProviderOption> {
    std::iter::once(AUTO_PROVIDER)
        .chain(PROVIDERS.iter().copied())
        .map(|item| ProviderOption {
            value: item.id,
            label: item.label,
            base_url: item.base_url,
            model: item.model,
            model_placeholder: item.placeholder,
        })
        .collect()
}

fn default_profile(id: &str, name: &str, provider: &str) -> AiProfile {
    let provider = normalize_provider(provider);
    let defaults = provider_defaults(provider);
    AiProfile {
        id: sanitize_id(id),
        name: if name.trim().is_empty() {
            defaults.name.to_string()
        } else {
            name.trim().chars().take(80).collect()
        },
        provider: provider.to_string(),
        base_url: defaults.base_url.to_string(),
        api_key: String::new(),
        model: defaults.model.to_string(),
        temperature: 0.1,
        max_tokens: 1600,
        context_window: 128_000,
        last_updated: String::new(),
    }
}

fn default_store() -> AiStore {
    AiStore {
        enabled: false,
        active_profile_id: "auto".to_string(),
        profiles: vec![
            default_profile("auto", "自动识别", "auto"),
            default_profile("default", "OpenAI", "openai"),
            default_profile("openrouter-free", "OpenRouter 免费路由", "openrouter"),
        ],
        last_updated: String::new(),
    }
}

fn normalize_store(raw: Option<&Value>) -> AiStore {
    let Some(source) = raw.and_then(Value::as_object) else {
        return default_store();
    };
    let enabled = source.get("enabled").and_then(value_bool).unwrap_or(false);
    let last_updated = source
        .get("last_updated")
        .and_then(value_text)
        .unwrap_or_default();
    let raw_profiles = source.get("profiles").and_then(Value::as_array);
    if raw_profiles.is_none() {
        let has_legacy = ["provider", "base_url", "api_key", "model", "name"]
            .iter()
            .any(|key| {
                source
                    .get(*key)
                    .and_then(value_text)
                    .is_some_and(|value| !value.trim().is_empty())
            });
        if !has_legacy {
            let mut store = default_store();
            store.enabled = enabled;
            store.last_updated = last_updated;
            return store;
        }
        let migrated = normalize_profile(
            &Value::Object(source.clone()),
            "default",
            &source
                .get("name")
                .and_then(value_text)
                .filter(|name| !name.trim().is_empty())
                .unwrap_or_else(|| "默认 OpenAI".to_string()),
        );
        let mut profiles = vec![default_profile("auto", "自动识别", "auto"), migrated];
        if !profiles
            .iter()
            .any(|profile| profile.provider == "openrouter")
        {
            profiles.push(default_profile(
                "openrouter-free",
                "OpenRouter 免费路由",
                "openrouter",
            ));
        }
        return AiStore {
            enabled,
            active_profile_id: profiles[1].id.clone(),
            profiles,
            last_updated,
        };
    }

    let mut profiles = raw_profiles
        .into_iter()
        .flatten()
        .enumerate()
        .filter(|(_, item)| item.is_object())
        .map(|(index, item)| {
            let fallback_id = if index == 0 {
                "default".to_string()
            } else {
                format!("profile-{}", index + 1)
            };
            let fallback_name = item
                .get("name")
                .and_then(value_text)
                .filter(|name| !name.trim().is_empty())
                .unwrap_or_else(|| format!("配置 {}", index + 1));
            normalize_profile(item, &fallback_id, &fallback_name)
        })
        .collect::<Vec<_>>();
    ensure_required_profiles(&mut profiles);
    let ids = profiles
        .iter()
        .map(|profile| profile.id.clone())
        .collect::<HashSet<_>>();
    let requested_active = source
        .get("active_profile_id")
        .and_then(value_text)
        .map(|value| sanitize_id(&value))
        .unwrap_or_else(|| profiles[0].id.clone());
    let active_profile_id = if ids.contains(&requested_active) {
        requested_active
    } else {
        profiles[0].id.clone()
    };
    AiStore {
        enabled,
        active_profile_id,
        profiles,
        last_updated,
    }
}

fn normalize_profile(raw: &Value, fallback_id: &str, fallback_name: &str) -> AiProfile {
    let source = raw.as_object();
    let id = sanitize_id(
        &source
            .and_then(|item| item.get("id"))
            .and_then(value_text)
            .unwrap_or_else(|| fallback_id.to_string()),
    );
    let provider_text = source
        .and_then(|item| item.get("provider"))
        .and_then(value_text)
        .unwrap_or_else(|| "openai".to_string());
    let provider = normalize_provider(&provider_text);
    let defaults = provider_defaults(provider);
    let mut profile = AiProfile {
        id,
        name: source
            .and_then(|item| item.get("name"))
            .and_then(value_text)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| fallback_name.to_string())
            .trim()
            .chars()
            .take(80)
            .collect(),
        provider: provider.to_string(),
        base_url: nonempty_text(source, "base_url")
            .unwrap_or_else(|| defaults.base_url.to_string()),
        api_key: source
            .and_then(|item| item.get("api_key"))
            .and_then(value_text)
            .unwrap_or_default()
            .trim()
            .to_string(),
        model: nonempty_text(source, "model").unwrap_or_else(|| defaults.model.to_string()),
        temperature: source
            .and_then(|item| item.get("temperature"))
            .and_then(value_f64)
            .unwrap_or(0.1)
            .clamp(0.0, 2.0),
        max_tokens: source
            .and_then(|item| item.get("max_tokens"))
            .and_then(value_i64)
            .unwrap_or(1600)
            .clamp(128, 65_536),
        context_window: source
            .and_then(|item| item.get("context_window"))
            .and_then(value_i64)
            .unwrap_or(128_000)
            .clamp(4_096, 2_000_000),
        last_updated: source
            .and_then(|item| item.get("last_updated"))
            .and_then(value_text)
            .unwrap_or_default(),
    };
    resolve_profile_provider(&mut profile, true);
    profile
}

fn nonempty_text(source: Option<&Map<String, Value>>, key: &str) -> Option<String> {
    source
        .and_then(|item| item.get(key))
        .and_then(value_text)
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn ensure_required_profiles(profiles: &mut Vec<AiProfile>) {
    if profiles.is_empty() {
        profiles.push(default_profile("default", "OpenAI", "openai"));
    }
    let mut used = profiles
        .iter()
        .map(|profile| profile.id.clone())
        .collect::<HashSet<_>>();
    if !profiles.iter().any(|profile| profile.provider == "auto") {
        let id = unused_id("auto", &used);
        used.insert(id.clone());
        profiles.insert(0, default_profile(&id, "自动识别", "auto"));
    }
    if !profiles
        .iter()
        .any(|profile| profile.provider == "openrouter")
    {
        let id = unused_id("openrouter-free", &used);
        profiles.push(default_profile(&id, "OpenRouter 免费路由", "openrouter"));
    }
    let mut normalized_ids = HashSet::new();
    for profile in profiles {
        let base = sanitize_id(&profile.id);
        let id = unused_id(&base, &normalized_ids);
        normalized_ids.insert(id.clone());
        profile.id = id;
    }
}

fn resolve_profile_provider(profile: &mut AiProfile, keep_empty_auto: bool) {
    let raw_provider = normalize_provider(&profile.provider);
    if raw_provider == "auto"
        && keep_empty_auto
        && profile.base_url.trim().is_empty()
        && profile.model.trim().is_empty()
    {
        profile.provider = "auto".to_string();
        return;
    }
    let provider = infer_provider(
        raw_provider,
        &profile.base_url,
        &profile.model,
        &profile.name,
    );
    profile.base_url =
        normalize_base_url(provider, &profile.base_url, &profile.model, &profile.name);
    profile.provider =
        infer_provider(provider, &profile.base_url, &profile.model, &profile.name).to_string();
    let defaults = provider_defaults(&profile.provider);
    if profile.base_url.is_empty() {
        profile.base_url = defaults.base_url.to_string();
    }
    if profile.model.trim().is_empty() {
        profile.model = defaults.model.to_string();
    }
}

fn infer_provider(provider: &str, base_url: &str, model: &str, name: &str) -> &'static str {
    let normalized = normalize_provider(provider);
    let url = base_url.trim().to_ascii_lowercase();
    for (marker, candidate) in [
        ("generativelanguage.googleapis.com", "gemini"),
        ("dashscope.aliyuncs.com", "dashscope"),
        ("maas.aliyuncs.com", "dashscope"),
        ("api.deepseek.com", "deepseek"),
        ("api.moonshot.ai", "moonshot"),
        ("api.moonshot.cn", "moonshot"),
        ("api.kimi.com", "moonshot"),
        ("open.bigmodel.cn", "bigmodel"),
        ("bigmodel.cn", "bigmodel"),
        ("qianfan.baidubce.com", "qianfan"),
        ("aip.baidubce.com", "qianfan"),
        ("hunyuan.cloud.tencent.com", "hunyuan"),
        ("ark.cn-", "volcengine"),
        ("volces.com", "volcengine"),
        ("siliconflow.cn", "siliconflow"),
        ("lingyiwanwu.com", "lingyiwanwu"),
        ("xf-yun.com", "xfyun"),
        ("minimax.chat", "minimax"),
        ("minimaxi.com", "minimax"),
        ("baichuan-ai.com", "baichuan"),
        ("api.stepfun.com", "stepfun"),
        ("modelscope.cn", "modelscope"),
        ("openrouter.ai", "openrouter"),
        ("api.anthropic.com", "anthropic"),
        ("api.openai.com", "openai"),
    ] {
        if url.contains(marker) {
            return candidate;
        }
    }
    if !matches!(normalized, "auto" | "openai") {
        return normalized;
    }
    let text = format!("{model} {name} {provider}").to_ascii_lowercase();
    for (markers, candidate) in [
        (
            &["通义", "千问", "百炼", "阿里云", "qwen", "dashscope"][..],
            "dashscope",
        ),
        (&["deepseek", "深度求索"][..], "deepseek"),
        (&["kimi", "moonshot", "月之暗面"][..], "moonshot"),
        (&["智谱", "bigmodel", "glm"][..], "bigmodel"),
        (
            &["千帆", "文心", "ernie", "百度", "qianfan", "wenxin"][..],
            "qianfan",
        ),
        (&["混元", "hunyuan", "腾讯"][..], "hunyuan"),
        (
            &["豆包", "火山", "方舟", "doubao", "volc", "ark"][..],
            "volcengine",
        ),
        (&["硅基", "siliconflow"][..], "siliconflow"),
        (&["零一万物", "01.ai", "01ai", "yi-"][..], "lingyiwanwu"),
        (&["讯飞", "星火", "xfyun", "spark"][..], "xfyun"),
        (&["minimax", "海螺"][..], "minimax"),
        (&["百川", "baichuan"][..], "baichuan"),
        (&["阶跃", "stepfun", "step-"][..], "stepfun"),
        (&["魔搭", "modelscope"][..], "modelscope"),
        (&["openrouter"][..], "openrouter"),
        (&["anthropic", "claude"][..], "anthropic"),
        (&["gemini", "google"][..], "gemini"),
    ] {
        if markers.iter().any(|marker| text.contains(marker)) {
            return candidate;
        }
    }
    if normalized == "openai" && url.is_empty() {
        "openai"
    } else if !url.is_empty() {
        "openai_compatible"
    } else {
        "openai"
    }
}

fn normalize_base_url(provider: &str, value: &str, model: &str, name: &str) -> String {
    let mut original = value
        .trim()
        .trim_matches(|character: char| {
            matches!(character, '`' | '\'' | '"' | '<' | '>' | '\u{3000}')
                || character.is_whitespace()
        })
        .to_string();
    let lower = original.to_ascii_lowercase();
    if lower.starts_with("base_url:") || lower.starts_with("baseurl:") {
        original = original
            .split_once(':')
            .map(|(_, value)| value)
            .unwrap_or("")
            .trim()
            .to_string();
    } else if lower.starts_with("base_url=") || lower.starts_with("baseurl=") {
        original = original
            .split_once('=')
            .map(|(_, value)| value)
            .unwrap_or("")
            .trim()
            .to_string();
    }
    if original.is_empty() {
        return provider_default_base_url(provider, model, name);
    }
    let with_scheme = if original.starts_with("//") {
        format!("https:{original}")
    } else if original.contains("://") {
        original.clone()
    } else {
        let host = original.split('/').next().unwrap_or("");
        let private = is_private_host(host);
        format!("{}://{original}", if private { "http" } else { "https" })
    };
    let Ok(mut parsed) = reqwest::Url::parse(&with_scheme) else {
        return original.trim_end_matches('/').to_string();
    };
    parsed.set_query(None);
    parsed.set_fragment(None);
    let mut path = collapse_slashes(parsed.path());
    loop {
        let lower = path.to_ascii_lowercase();
        let suffix = known_endpoint_suffixes()
            .iter()
            .find(|suffix| lower.ends_with(**suffix));
        let Some(suffix) = suffix else { break };
        path.truncate(path.len() - suffix.len());
        path = path.trim_end_matches('/').to_string();
    }
    let host = parsed.host_str().unwrap_or("").to_ascii_lowercase();
    if let Some((detected, regular_path)) = provider_path_rule(&host) {
        let expected = coding_path(detected, regular_path, model, name);
        if path.is_empty()
            || path == "/"
            || known_wrong_path(detected, &path)
            || (expected != regular_path && path.trim_end_matches('/') == regular_path)
        {
            path = expected.to_string();
        }
    }
    parsed.set_path(path.trim_end_matches('/'));
    parsed.to_string().trim_end_matches('/').to_string()
}

fn provider_default_base_url(provider: &str, model: &str, name: &str) -> String {
    let defaults = provider_defaults(provider);
    if defaults.base_url.is_empty() {
        return String::new();
    }
    let Ok(mut parsed) = reqwest::Url::parse(defaults.base_url) else {
        return defaults.base_url.to_string();
    };
    let host = parsed.host_str().unwrap_or("").to_ascii_lowercase();
    if let Some((detected, regular_path)) = provider_path_rule(&host) {
        parsed.set_path(coding_path(detected, regular_path, model, name));
    }
    parsed.to_string().trim_end_matches('/').to_string()
}

fn provider_path_rule(host: &str) -> Option<(&'static str, &'static str)> {
    let rules: &[(&str, &[&str], &str)] = &[
        ("openai", &["api.openai.com"], "/v1"),
        ("anthropic", &["api.anthropic.com"], "/v1"),
        ("openrouter", &["openrouter.ai"], "/api/v1"),
        (
            "dashscope",
            &[
                "dashscope.aliyuncs.com",
                "dashscope-us.aliyuncs.com",
                "dashscope-intl.aliyuncs.com",
                "cn-hongkong.dashscope.aliyuncs.com",
                ".maas.aliyuncs.com",
            ],
            "/compatible-mode/v1",
        ),
        ("deepseek", &["api.deepseek.com"], ""),
        (
            "moonshot",
            &["api.moonshot.ai", "api.moonshot.cn", "api.kimi.com"],
            "/v1",
        ),
        ("bigmodel", &["open.bigmodel.cn"], "/api/paas/v4"),
        ("qianfan", &["qianfan.baidubce.com"], "/v2"),
        ("hunyuan", &["api.hunyuan.cloud.tencent.com"], "/v1"),
        ("volcengine", &[".volces.com"], "/api/v3"),
        ("siliconflow", &["api.siliconflow.cn"], "/v1"),
        ("lingyiwanwu", &["api.lingyiwanwu.com"], "/v1"),
        ("xfyun", &["spark-api-open.xf-yun.com"], "/v1"),
        ("minimax", &["api.minimax.chat"], "/v1"),
        ("baichuan", &["api.baichuan-ai.com"], "/v1"),
        ("stepfun", &["api.stepfun.com"], "/v1"),
        ("modelscope", &["api-inference.modelscope.cn"], "/v1"),
        (
            "gemini",
            &["generativelanguage.googleapis.com"],
            "/v1beta/openai",
        ),
    ];
    rules.iter().find_map(|(provider, hosts, path)| {
        hosts
            .iter()
            .any(|pattern| host_matches(host, pattern))
            .then_some((*provider, *path))
    })
}

fn host_matches(host: &str, pattern: &str) -> bool {
    if pattern.starts_with('.') {
        host.ends_with(pattern)
    } else {
        host == pattern || host.ends_with(&format!(".{pattern}"))
    }
}

fn coding_path(
    provider: &str,
    regular_path: &'static str,
    model: &str,
    name: &str,
) -> &'static str {
    let text = format!("{model} {name}").to_ascii_lowercase();
    match provider {
        "qianfan" if text.contains("qianfan-code") => "/v2/coding",
        "volcengine" if text.contains("ark-code") => "/api/coding/v3",
        _ => regular_path,
    }
}

fn known_wrong_path(provider: &str, path: &str) -> bool {
    let path = path.to_ascii_lowercase();
    provider == "qianfan" && (path == "/anthropic/coding" || path.starts_with("/anthropic/coding/"))
}

fn known_endpoint_suffixes() -> &'static [&'static str] {
    &[
        "/messages/count_tokens",
        "/chat/completions",
        "/images/generations",
        "/audio/transcriptions",
        "/audio/translations",
        "/responses",
        "/completions",
        "/embeddings",
        "/messages",
        "/generation",
        "/models",
        "/videos",
        "/key",
    ]
}

fn collapse_slashes(value: &str) -> String {
    let mut result = String::with_capacity(value.len());
    let mut slash = false;
    for character in value.chars() {
        if character == '/' {
            if !slash {
                result.push(character);
            }
            slash = true;
        } else {
            slash = false;
            result.push(character);
        }
    }
    result.trim_end_matches('/').to_string()
}

fn is_private_host(value: &str) -> bool {
    let host = value
        .trim()
        .trim_start_matches('[')
        .split(']')
        .next()
        .unwrap_or(value)
        .split(':')
        .next()
        .unwrap_or(value)
        .to_ascii_lowercase();
    host == "localhost"
        || host == "0.0.0.0"
        || host == "::1"
        || host.starts_with("127.")
        || host.starts_with("10.")
        || host.starts_with("192.168.")
        || host.starts_with("172.16.")
        || host.starts_with("172.17.")
        || host.starts_with("172.18.")
        || host.starts_with("172.19.")
        || host.starts_with("172.2")
        || host.starts_with("172.30.")
        || host.starts_with("172.31.")
}

fn safe_profile(profile: &AiProfile) -> SafeAiProfile {
    SafeAiProfile {
        id: profile.id.clone(),
        name: profile.name.clone(),
        provider: profile.provider.clone(),
        base_url: profile.base_url.clone(),
        api_key: String::new(),
        model: profile.model.clone(),
        temperature: profile.temperature,
        max_tokens: profile.max_tokens,
        context_window: profile.context_window,
        last_updated: profile.last_updated.clone(),
        api_key_configured: !profile.api_key.is_empty(),
        api_key_masked: mask_secret(&profile.api_key),
    }
}

fn safe_store(store: &AiStore) -> Value {
    let normalized = normalize_store(serde_json::to_value(store).ok().as_ref());
    let profiles = normalized
        .profiles
        .iter()
        .map(safe_profile)
        .collect::<Vec<_>>();
    let active_profile = profiles
        .iter()
        .find(|profile| profile.id == normalized.active_profile_id)
        .cloned()
        .unwrap_or_else(|| profiles[0].clone());
    json!({
        "enabled": normalized.enabled,
        "active_profile_id": active_profile.id,
        "active_profile": active_profile,
        "profiles": profiles,
        "last_updated": normalized.last_updated,
        "provider": active_profile.provider,
        "base_url": active_profile.base_url,
        "model": active_profile.model,
        "temperature": active_profile.temperature,
        "max_tokens": active_profile.max_tokens,
        "context_window": active_profile.context_window,
        "api_key": "",
        "api_key_configured": active_profile.api_key_configured,
        "api_key_masked": active_profile.api_key_masked,
        "provider_options": provider_options(),
    })
}

fn tools_list() -> Value {
    let tools: Vec<ToolSpec> = serde_json::from_str(include_str!("retest_tool_catalog.json"))
        .expect("embedded retest tool catalog must be valid JSON");
    let mut categories = BTreeMap::<String, usize>::new();
    for tool in &tools {
        *categories.entry(tool.category.clone()).or_default() += 1;
    }
    json!({
        "success": true,
        "message": format!("已加载 {} 个复测工具", tools.len()),
        "tools": tools,
        "categories": categories,
    })
}

pub(crate) fn tools_status(root: &Path) -> Value {
    let preferred_root = root.to_path_buf();
    let _ = fs::create_dir_all(&preferred_root);
    let tools = ["nmap", "sqlmap", "ffuf"]
        .iter()
        .map(|id| {
            if *id == "sqlmap" {
                return json!({
                    "id": id,
                    "name": id,
                    "installed": true,
                    "command": ["koi://builtin/sql-validator"],
                    "source": "builtin",
                    "installable": false,
                    "root": "",
                });
            }
            let (command, verification_error) =
                match external_tools::verified_tool_path(&preferred_root, id) {
                    Ok(Some(path)) => (vec![path.to_string_lossy().to_string()], String::new()),
                    Ok(None) => (Vec::new(), String::new()),
                    Err(error) => (Vec::new(), error),
                };
            json!({
                "id": id,
                "name": id,
                "installed": !command.is_empty(),
                "command": command,
                "source": if verification_error.is_empty() && !command.is_empty() {"locked"} else {""},
                "installable": true,
                "root": preferred_root.join(id),
                "verification_error": verification_error,
            })
        })
        .collect::<Vec<_>>();
    json!({
        "success": true,
        "message": "External retest tool status loaded.",
        "tool_root": preferred_root,
        "tools": tools,
    })
}

fn value_bool(value: &Value) -> Option<bool> {
    match value {
        Value::Bool(value) => Some(*value),
        Value::Number(value) => value.as_f64().map(|value| value != 0.0),
        Value::String(value) => match value.trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "y" | "on" => Some(true),
            "0" | "false" | "no" | "n" | "off" => Some(false),
            _ => Some(!value.is_empty()),
        },
        Value::Null => None,
        Value::Array(value) => Some(!value.is_empty()),
        Value::Object(value) => Some(!value.is_empty()),
    }
}

fn value_text(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(value) => Some(value.clone()),
        Value::Bool(value) => Some(if *value { "True" } else { "False" }.to_string()),
        Value::Number(value) => Some(value.to_string()),
        Value::Array(_) | Value::Object(_) => Some(value.to_string()),
    }
}

fn value_f64(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
}

fn value_i64(value: &Value) -> Option<i64> {
    value.as_i64().or_else(|| {
        value
            .as_f64()
            .map(|number| number as i64)
            .or_else(|| value.as_str()?.trim().parse::<i64>().ok())
    })
}

fn sanitize_id(value: &str) -> String {
    static NEXT_PROFILE_ID: AtomicU64 = AtomicU64::new(0);
    let mut output = String::new();
    for character in value.trim().chars() {
        if character.is_ascii_alphanumeric() || matches!(character, '_' | '-') {
            output.push(character);
        } else if !output.ends_with('-') {
            output.push('-');
        }
        if output.len() >= 64 {
            break;
        }
    }
    let output = output.trim_matches('-').to_string();
    if output.is_empty() {
        let seed = Local::now().timestamp_nanos_opt().unwrap_or_default() as u64
            ^ NEXT_PROFILE_ID.fetch_add(1, Ordering::Relaxed);
        format!("profile-{:08x}", seed as u32)
    } else {
        output
    }
}

fn unique_id(requested: &str, profiles: &[AiProfile]) -> String {
    let used = profiles
        .iter()
        .map(|profile| profile.id.clone())
        .collect::<HashSet<_>>();
    unused_id(requested, &used)
}

fn unused_id(requested: &str, used: &HashSet<String>) -> String {
    if !used.contains(requested) {
        return requested.to_string();
    }
    for suffix in 2..10_000 {
        let candidate = format!("{requested}-{suffix}");
        if !used.contains(&candidate) {
            return candidate;
        }
    }
    format!("{requested}-{}", Local::now().format("%H%M%S%3f"))
}

fn mask_secret(value: &str) -> String {
    let characters = value.chars().collect::<Vec<_>>();
    if characters.is_empty() {
        String::new()
    } else if characters.len() < 8 {
        "***".to_string()
    } else {
        format!(
            "{}***{}",
            characters.iter().take(3).collect::<String>(),
            characters
                .iter()
                .skip(characters.len() - 3)
                .collect::<String>()
        )
    }
}

fn timestamp() -> String {
    Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config_store(label: &str) -> (ConfigStore, PathBuf) {
        let root = env::temp_dir().join(format!(
            "koi-retest-config-{label}-{}-{}",
            std::process::id(),
            Local::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        fs::create_dir_all(&root).unwrap();
        (ConfigStore::new(root.join("config.json")), root)
    }

    #[test]
    fn default_and_legacy_config_shapes_match_the_oracle_contract() {
        let default = normalize_store(None);
        assert_eq!(default.active_profile_id, "auto");
        assert_eq!(
            default
                .profiles
                .iter()
                .map(|profile| profile.id.as_str())
                .collect::<Vec<_>>(),
            ["auto", "default", "openrouter-free"]
        );

        let legacy = normalize_store(Some(&json!({
            "enabled": "yes",
            "provider": "deepseek",
            "api_key": "legacy-secret",
            "model": "deepseek-chat",
            "name": "旧配置"
        })));
        assert_eq!(legacy.active_profile_id, "default");
        let migrated = legacy
            .profiles
            .iter()
            .find(|profile| profile.id == "default")
            .unwrap();
        assert_eq!(migrated.provider, "deepseek");
        assert_eq!(migrated.api_key, "legacy-secret");
        assert!(legacy
            .profiles
            .iter()
            .any(|profile| profile.provider == "auto"));
        assert!(legacy
            .profiles
            .iter()
            .any(|profile| profile.provider == "openrouter"));
    }

    #[test]
    fn config_round_trip_preserves_and_explicitly_clears_key() {
        let (store, root) = config_store("roundtrip");
        let saved = dispatch(
            "doc.retest.ai_config.set",
            &json!({
                "action": "save_profile",
                "profile_id": "default",
                "api_key": "secret-value",
                "model": "mock"
            }),
            &store,
            &root,
        )
        .unwrap();
        assert_eq!(saved["success"], true);
        assert_eq!(saved["config"]["api_key"], "");
        assert_eq!(saved["config"]["api_key_configured"], true);
        assert_eq!(saved["config"]["api_key_masked"], "sec***lue");
        assert_eq!(saved["config"]["active_profile"]["id"], "default");
        assert!(!saved.to_string().contains("secret-value"));

        let preserved = dispatch(
            "doc.retest.ai_config.set",
            &json!({"profile_id": "default", "api_key": "", "model": "next"}),
            &store,
            &root,
        )
        .unwrap();
        assert_eq!(preserved["config"]["api_key_configured"], true);
        assert!(!fs::read_to_string(root.join("config.json"))
            .unwrap()
            .contains("secret-value"));
        assert!(root.join("secrets.dpapi.json").is_file());

        let cleared = dispatch(
            "doc.retest.ai_config.set",
            &json!({"profile_id": "default", "api_key": "", "clear_api_key": true}),
            &store,
            &root,
        )
        .unwrap();
        assert_eq!(cleared["config"]["api_key_configured"], false);
        assert!(!fs::read_to_string(root.join("config.json"))
            .unwrap()
            .contains("secret-value"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn profile_actions_and_base_url_normalization_are_compatible() {
        let (store, root) = config_store("actions");
        let created = dispatch(
            "doc.retest.ai_config.set",
            &json!({"action": "create_profile", "name": "Mock", "provider": "deepseek"}),
            &store,
            &root,
        )
        .unwrap();
        let created_id = created["config"]["active_profile_id"]
            .as_str()
            .unwrap()
            .to_string();
        assert_eq!(created_id, "Mock");
        let corrected = dispatch(
            "doc.retest.ai_config.set",
            &json!({
                "profile_id": created_id,
                "provider": "openai",
                "base_url": "api.openai.com/v1/chat/completions",
                "max_tokens": "12"
            }),
            &store,
            &root,
        )
        .unwrap();
        assert_eq!(corrected["config"]["provider"], "openai");
        assert_eq!(corrected["config"]["base_url"], "https://api.openai.com/v1");
        assert_eq!(corrected["config"]["max_tokens"], 128);
        assert!(corrected["message"]
            .as_str()
            .unwrap()
            .contains("Base URL 已自动修正"));
        assert!(dispatch(
            "doc.retest.ai_config.set",
            &json!({"action": "switch_profile", "profile_id": "missing"}),
            &store,
            &root,
        )
        .is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn tool_catalog_is_the_sorted_python_oracle_snapshot() {
        let response = tools_list();
        let tools = response["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 29);
        let ids = tools
            .iter()
            .map(|tool| tool["tool_id"].as_str().unwrap())
            .collect::<Vec<_>>();
        let mut sorted = ids.clone();
        sorted.sort_unstable();
        assert_eq!(ids, sorted);
        assert_eq!(tools[0]["tool_id"], "check_ai_python_probe");
        assert_eq!(tools[0]["requires"], json!(["target_urls", "agent_advice"]));
        assert_eq!(response["categories"]["agent_tools"], 2);
        assert_eq!(response["message"], "已加载 29 个复测工具");
    }

    #[test]
    fn tool_status_rejects_unlocked_binaries_and_legacy_sqlmap_python() {
        let root = env::temp_dir().join(format!(
            "koi-retest-tools-{}-{}",
            std::process::id(),
            Local::now().timestamp_nanos_opt().unwrap_or_default()
        ));
        fs::create_dir_all(root.join("nmap").join("bin")).unwrap();
        fs::create_dir_all(root.join("sqlmap")).unwrap();
        let nmap_name = if cfg!(windows) { "nmap.exe" } else { "nmap" };
        fs::write(root.join("nmap").join("bin").join(nmap_name), b"test").unwrap();
        fs::write(root.join("sqlmap").join("sqlmap.py"), b"print('legacy')").unwrap();
        let response = tools_status(&root);
        assert_eq!(response["success"], true);
        assert_eq!(response["message"], "External retest tool status loaded.");
        let tools = response["tools"].as_array().unwrap();
        let nmap = tools.iter().find(|tool| tool["id"] == "nmap").unwrap();
        assert_eq!(nmap["installed"], false);
        assert_eq!(nmap["source"], "");
        assert_eq!(nmap["installable"], true);
        assert!(nmap["verification_error"]
            .as_str()
            .is_some_and(|error| !error.is_empty()));
        let sqlmap = tools.iter().find(|tool| tool["id"] == "sqlmap").unwrap();
        assert_eq!(sqlmap["installed"], true);
        assert_eq!(sqlmap["source"], "builtin");
        assert!(!sqlmap["command"].to_string().contains("sqlmap.py"));
        fs::remove_dir_all(root).unwrap();
    }
}
