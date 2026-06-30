#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LLM provider catalog for retest AI configuration."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, urlunparse


PROVIDER_AUTO = "auto"
PROVIDER_CUSTOM_OPENAI = "openai_compatible"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_FREE_MODEL = "openrouter/free"


LLM_PROVIDER_CATALOG: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI 标准",
        "default_name": "OpenAI",
        "base_url": OPENAI_DEFAULT_BASE_URL,
        "model": "gpt-4o-mini",
        "model_placeholder": "gpt-4o-mini",
        "protocol": "openai",
        "json_mode": True,
    },
    "anthropic": {
        "label": "Anthropic 标准",
        "default_name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-sonnet-latest",
        "model_placeholder": "claude-3-5-sonnet-latest",
        "protocol": "anthropic",
        "json_mode": False,
    },
    "openrouter": {
        "label": "OpenRouter 免费路由",
        "default_name": "OpenRouter 免费路由",
        "base_url": OPENROUTER_DEFAULT_BASE_URL,
        "model": OPENROUTER_FREE_MODEL,
        "model_placeholder": OPENROUTER_FREE_MODEL,
        "protocol": "openai",
        "json_mode": False,
    },
    PROVIDER_CUSTOM_OPENAI: {
        "label": "自定义 OpenAI 兼容",
        "default_name": "自定义 OpenAI 兼容",
        "base_url": "",
        "model": "",
        "model_placeholder": "模型 ID",
        "protocol": "openai",
        "json_mode": False,
    },
    "dashscope": {
        "label": "阿里云百炼/通义千问",
        "default_name": "阿里云百炼/通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "model_placeholder": "qwen-plus",
        "protocol": "openai",
        "json_mode": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "default_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "model_placeholder": "deepseek-v4-flash",
        "protocol": "openai",
        "json_mode": False,
    },
    "moonshot": {
        "label": "月之暗面/Kimi",
        "default_name": "月之暗面/Kimi",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "moonshot-v1-8k",
        "model_placeholder": "moonshot-v1-8k",
        "protocol": "openai",
        "json_mode": False,
    },
    "bigmodel": {
        "label": "智谱 BigModel/GLM",
        "default_name": "智谱 BigModel/GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "model_placeholder": "glm-4-flash",
        "protocol": "openai",
        "json_mode": False,
    },
    "qianfan": {
        "label": "百度千帆/文心",
        "default_name": "百度千帆/文心",
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "ernie-4.5-turbo-128k",
        "model_placeholder": "ernie-4.5-turbo-128k 或 qianfan-code-latest",
        "protocol": "openai",
        "json_mode": False,
    },
    "hunyuan": {
        "label": "腾讯混元",
        "default_name": "腾讯混元",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "model": "hunyuan-turbos-latest",
        "model_placeholder": "hunyuan-turbos-latest",
        "protocol": "openai",
        "json_mode": False,
    },
    "volcengine": {
        "label": "火山方舟/豆包",
        "default_name": "火山方舟/豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
        "model_placeholder": "ep-xxxxxxxx 或 ark-code-latest",
        "protocol": "openai",
        "json_mode": False,
    },
    "siliconflow": {
        "label": "硅基流动 SiliconFlow",
        "default_name": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-8B",
        "model_placeholder": "Qwen/Qwen3-8B",
        "protocol": "openai",
        "json_mode": False,
    },
    "lingyiwanwu": {
        "label": "零一万物 01.AI",
        "default_name": "零一万物 01.AI",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "model": "yi-large",
        "model_placeholder": "yi-large",
        "protocol": "openai",
        "json_mode": False,
    },
    "xfyun": {
        "label": "讯飞星火",
        "default_name": "讯飞星火",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "model": "4.0Ultra",
        "model_placeholder": "4.0Ultra",
        "protocol": "openai",
        "json_mode": False,
    },
    "minimax": {
        "label": "MiniMax",
        "default_name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
        "model_placeholder": "MiniMax-Text-01",
        "protocol": "openai",
        "json_mode": False,
    },
    "baichuan": {
        "label": "百川智能",
        "default_name": "百川智能",
        "base_url": "https://api.baichuan-ai.com/v1",
        "model": "Baichuan4",
        "model_placeholder": "Baichuan4",
        "protocol": "openai",
        "json_mode": False,
    },
    "stepfun": {
        "label": "阶跃星辰 StepFun",
        "default_name": "阶跃星辰 StepFun",
        "base_url": "https://api.stepfun.com/v1",
        "model": "step-3.7-flash",
        "model_placeholder": "step-3.7-flash",
        "protocol": "openai",
        "json_mode": False,
    },
    "modelscope": {
        "label": "魔搭 ModelScope",
        "default_name": "魔搭 ModelScope",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "model": "Qwen/Qwen3-8B",
        "model_placeholder": "Qwen/Qwen3-8B",
        "protocol": "openai",
        "json_mode": False,
    },
    "gemini": {
        "label": "Google Gemini OpenAI 兼容",
        "default_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.5-flash",
        "model_placeholder": "gemini-3.5-flash",
        "protocol": "openai",
        "json_mode": False,
    },
}


SUPPORTED_LLM_PROVIDERS = set(LLM_PROVIDER_CATALOG.keys())

PROVIDER_ALIASES = {
    "custom": PROVIDER_CUSTOM_OPENAI,
    "openai-compatible": PROVIDER_CUSTOM_OPENAI,
    "openai_compat": PROVIDER_CUSTOM_OPENAI,
    "aliyun": "dashscope",
    "bailian": "dashscope",
    "dashscope": "dashscope",
    "tongyi": "dashscope",
    "qwen": "dashscope",
    "kimi": "moonshot",
    "zhipu": "bigmodel",
    "glm": "bigmodel",
    "baidu": "qianfan",
    "wenxin": "qianfan",
    "ernie": "qianfan",
    "tencent": "hunyuan",
    "doubao": "volcengine",
    "ark": "volcengine",
    "volces": "volcengine",
    "volcengine": "volcengine",
    "01ai": "lingyiwanwu",
    "yi": "lingyiwanwu",
    "spark": "xfyun",
    "iflytek": "xfyun",
    "baichuan-ai": "baichuan",
    "step": "stepfun",
    "google": "gemini",
    "googleai": "gemini",
    "google-ai": "gemini",
    "gemini": "gemini",
}

URL_PROVIDER_HINTS = (
    ("generativelanguage.googleapis.com", "gemini"),
    ("dashscope.aliyuncs.com", "dashscope"),
    ("dashscope-us.aliyuncs.com", "dashscope"),
    ("cn-hongkong.dashscope.aliyuncs.com", "dashscope"),
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
    ("spark-api-open.xf-yun.com", "xfyun"),
    ("xf-yun.com", "xfyun"),
    ("minimax.chat", "minimax"),
    ("minimaxi.com", "minimax"),
    ("baichuan-ai.com", "baichuan"),
    ("api.stepfun.com", "stepfun"),
    ("modelscope.cn", "modelscope"),
    ("openrouter.ai", "openrouter"),
    ("api.anthropic.com", "anthropic"),
    ("api.openai.com", "openai"),
)

TEXT_PROVIDER_HINTS = (
    (("通义", "千问", "百炼", "阿里云", "qwen", "dashscope"), "dashscope"),
    (("deepseek", "深度求索"), "deepseek"),
    (("kimi", "moonshot", "月之暗面"), "moonshot"),
    (("智谱", "bigmodel", "glm"), "bigmodel"),
    (("千帆", "文心", "ernie", "百度", "qianfan", "wenxin"), "qianfan"),
    (("混元", "hunyuan", "腾讯"), "hunyuan"),
    (("豆包", "火山", "方舟", "doubao", "volc", "ark"), "volcengine"),
    (("硅基", "siliconflow"), "siliconflow"),
    (("零一万物", "01.ai", "01ai", "yi-"), "lingyiwanwu"),
    (("讯飞", "星火", "xfyun", "spark"), "xfyun"),
    (("minimax", "海螺"), "minimax"),
    (("百川", "baichuan"), "baichuan"),
    (("阶跃", "stepfun", "step-"), "stepfun"),
    (("魔搭", "modelscope"), "modelscope"),
    (("openrouter",), "openrouter"),
    (("anthropic", "claude"), "anthropic"),
    (("gemini", "google"), "gemini"),
)


_KNOWN_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/messages/count_tokens",
    "/messages",
    "/responses",
    "/completions",
    "/embeddings",
    "/images/generations",
    "/audio/transcriptions",
    "/audio/translations",
    "/models",
    "/key",
    "/generation",
    "/videos",
)


_PROVIDER_BASE_URL_RULES: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("openai", ("api.openai.com",), "/v1"),
    ("anthropic", ("api.anthropic.com",), "/v1"),
    ("openrouter", ("openrouter.ai",), "/api/v1"),
    (
        "dashscope",
        ("dashscope.aliyuncs.com", "dashscope-us.aliyuncs.com", "dashscope-intl.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com", ".maas.aliyuncs.com"),
        "/compatible-mode/v1",
    ),
    ("deepseek", ("api.deepseek.com",), ""),
    ("moonshot", ("api.moonshot.ai", "api.moonshot.cn", "api.kimi.com"), "/v1"),
    ("bigmodel", ("open.bigmodel.cn",), "/api/paas/v4"),
    ("qianfan", ("qianfan.baidubce.com",), "/v2"),
    ("hunyuan", ("api.hunyuan.cloud.tencent.com",), "/v1"),
    ("volcengine", (".volces.com",), "/api/v3"),
    ("siliconflow", ("api.siliconflow.cn",), "/v1"),
    ("lingyiwanwu", ("api.lingyiwanwu.com",), "/v1"),
    ("xfyun", ("spark-api-open.xf-yun.com",), "/v1"),
    ("minimax", ("api.minimax.chat",), "/v1"),
    ("baichuan", ("api.baichuan-ai.com",), "/v1"),
    ("stepfun", ("api.stepfun.com",), "/v1"),
    ("modelscope", ("api-inference.modelscope.cn",), "/v1"),
    ("gemini", ("generativelanguage.googleapis.com",), "/v1beta/openai"),
)


_PROVIDER_CODING_BASE_PATHS = {
    "qianfan": "/v2/coding",
    "volcengine": "/api/coding/v3",
}


_KNOWN_PROVIDER_WRONG_PATH_PREFIXES = {
    # Claude Code-compatible route. This client appends OpenAI chat/completions,
    # so keeping this prefix produces a provider-side 404.
    "qianfan": ("/anthropic/coding",),
}


def _clean_base_url_text(value: Any) -> str:
    text = str(value or "").strip().strip("`'\"<> \t\r\n\u3000")
    text = re.sub(r"^\s*(?:base_url|baseurl|baseURL)\s*[:=]\s*", "", text, flags=re.IGNORECASE).strip()
    return text.strip().strip("`'\"<> \t\r\n\u3000")


def _default_scheme_for_host(host: str) -> str:
    lower = host.lower().strip()
    if lower.startswith("["):
        lower = lower[1:].split("]", 1)[0]
    elif ":" in lower:
        lower = lower.split(":", 1)[0]
    if (
        lower in {"localhost", "0.0.0.0", "::1"}
        or lower.startswith("127.")
        or lower.startswith("10.")
        or lower.startswith("192.168.")
        or lower.startswith("172.16.")
        or lower.startswith("172.17.")
        or lower.startswith("172.18.")
        or lower.startswith("172.19.")
        or lower.startswith("172.2")
        or lower.startswith("172.30.")
        or lower.startswith("172.31.")
    ):
        return "http"
    return "https"


def _with_scheme(text: str) -> str:
    if not text:
        return ""
    if text.startswith("//"):
        host = text[2:].split("/", 1)[0].split("?", 1)[0]
        return f"{_default_scheme_for_host(host)}:{text}"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", text):
        return text
    host = text.split("/", 1)[0].split("?", 1)[0]
    return f"{_default_scheme_for_host(host)}://{text}"


def _normalize_path(path: str) -> str:
    cleaned = re.sub(r"/{2,}", "/", str(path or "").strip())
    if cleaned and not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned.rstrip("/")


def _strip_known_endpoint_suffixes(path: str) -> str:
    cleaned = _normalize_path(path)
    changed = True
    while changed and cleaned:
        changed = False
        lower = cleaned.lower()
        for suffix in sorted(_KNOWN_ENDPOINT_SUFFIXES, key=len, reverse=True):
            if lower.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].rstrip("/")
                changed = True
                break
    return cleaned


def _host_matches(host: str, patterns: Tuple[str, ...]) -> bool:
    host = host.lower().strip("[]")
    for pattern in patterns:
        marker = pattern.lower()
        if marker.startswith("."):
            if host.endswith(marker):
                return True
            continue
        if host == marker or host.endswith(f".{marker}"):
            return True
    return False


def _provider_path_rule(provider: str, host: str) -> Tuple[str, str] | None:
    for provider_id, hosts, base_path in _PROVIDER_BASE_URL_RULES:
        if _host_matches(host, hosts):
            return provider_id, base_path
    normalized_provider = normalize_provider_id(provider)
    for provider_id, hosts, base_path in _PROVIDER_BASE_URL_RULES:
        if normalized_provider == provider_id and _host_matches(host, hosts):
            return provider_id, base_path
    return None


def _is_provider_coding_model(provider: str, model: Any = "", name: Any = "") -> bool:
    provider_id = normalize_provider_id(provider)
    text = " ".join(str(item or "").strip().lower() for item in (model, name) if str(item or "").strip())
    if provider_id == "qianfan":
        return "qianfan-code" in text
    if provider_id == "volcengine":
        return "ark-code" in text
    return False


def _provider_model_default_path(provider: str, default_path: str, model: Any = "", name: Any = "") -> str:
    provider_id = normalize_provider_id(provider)
    if _is_provider_coding_model(provider_id, model, name):
        return _PROVIDER_CODING_BASE_PATHS.get(provider_id, default_path)
    return default_path


def _is_known_wrong_provider_path(provider: str, path: str) -> bool:
    provider_id = normalize_provider_id(provider)
    normalized = _normalize_path(path).lower()
    for wrong_prefix in _KNOWN_PROVIDER_WRONG_PATH_PREFIXES.get(provider_id, ()):
        wrong = _normalize_path(wrong_prefix).lower()
        if normalized == wrong or normalized.startswith(f"{wrong}/"):
            return True
    return False


def _correct_provider_base_path(provider: str, default_path: str, path: str, model: Any = "", name: Any = "") -> Tuple[str, str]:
    provider_id = normalize_provider_id(provider)
    normalized_path = _normalize_path(path)
    regular_default = _normalize_path(default_path)
    model_default = _normalize_path(_provider_model_default_path(provider_id, regular_default, model, name))
    if not normalized_path:
        return model_default, "provider_default_path"
    if _is_known_wrong_provider_path(provider_id, normalized_path):
        return model_default, "provider_default_path"
    if model_default != regular_default and normalized_path == regular_default:
        return model_default, "model_coding_path"
    return normalized_path, "trimmed_endpoint"


def _provider_default_base_url(provider: str, model: Any = "", name: Any = "") -> str:
    provider_id = normalize_provider_id(provider) or infer_llm_provider(provider, "", model, name)
    default_url = str(llm_provider_spec(provider_id).get("base_url") or "").strip().rstrip("/")
    if not default_url:
        return ""
    parsed = urlparse(default_url)
    if not parsed.netloc:
        return default_url
    path_rule = _provider_path_rule(provider_id, parsed.hostname or parsed.netloc)
    if not path_rule:
        return default_url
    provider_id, default_path = path_rule
    model_path = _provider_model_default_path(provider_id, default_path, model, name)
    normalized_default = _normalize_path(default_path)
    normalized_model = _normalize_path(model_path)
    if normalized_default == normalized_model:
        return default_url
    return urlunparse((parsed.scheme, parsed.netloc, normalized_model, "", "", "")).rstrip("/")


def normalize_provider_id(value: Any) -> str:
    provider = str(value or "").strip().lower().replace(" ", "_")
    if not provider:
        return ""
    if provider in {PROVIDER_AUTO, "自动", "自动识别"}:
        return PROVIDER_AUTO
    provider = PROVIDER_ALIASES.get(provider, provider)
    return provider if provider in SUPPORTED_LLM_PROVIDERS else ""


def infer_llm_provider(provider: Any = "", base_url: Any = "", model: Any = "", name: Any = "") -> str:
    normalized = normalize_provider_id(provider)

    url_text = str(base_url or "").strip().lower()
    for marker, provider_id in URL_PROVIDER_HINTS:
        if marker in url_text:
            return provider_id

    if normalized and normalized not in {PROVIDER_AUTO, "openai"}:
        return normalized

    text = " ".join(str(item or "").strip().lower() for item in (model, name, provider) if str(item or "").strip())
    for markers, provider_id in TEXT_PROVIDER_HINTS:
        if any(marker in text for marker in markers):
            return provider_id

    if normalized == "openai" and not url_text:
        return "openai"
    if url_text:
        return PROVIDER_CUSTOM_OPENAI
    return "openai"


def normalize_llm_base_url(provider: Any = "", base_url: Any = "", model: Any = "", name: Any = "") -> Dict[str, Any]:
    """Return a corrected provider base URL suitable for this client's URL join style.

    The retest client appends either /chat/completions or /messages itself, so this
    helper keeps only the provider API root and removes full endpoint paths pasted
    by users.
    """
    original = _clean_base_url_text(base_url)
    provider_hint = normalize_provider_id(provider)
    inferred_provider = infer_llm_provider(provider, original, model, name)
    provider_id = inferred_provider or provider_hint or "openai"

    if not original:
        default_url = _provider_default_base_url(provider_id, model, name)
        return {
            "base_url": default_url,
            "provider": provider_id,
            "changed": bool(default_url),
            "original": original,
            "reason": "filled_provider_default" if default_url else "",
        }

    text = _with_scheme(original)
    parsed = urlparse(text)
    if not parsed.netloc:
        return {
            "base_url": original.rstrip("/"),
            "provider": provider_id,
            "changed": False,
            "original": original,
            "reason": "",
        }

    scheme = parsed.scheme or _default_scheme_for_host(parsed.hostname or parsed.netloc)
    host = (parsed.hostname or "").lower()
    stripped_path = _strip_known_endpoint_suffixes(parsed.path or "")
    path_rule = _provider_path_rule(provider_id, host)
    reason = "trimmed_endpoint"
    if path_rule:
        provider_id, default_path = path_rule
        stripped_path, reason = _correct_provider_base_path(provider_id, default_path, stripped_path, model, name)
    corrected = urlunparse((scheme, parsed.netloc, _normalize_path(stripped_path), "", "", "")).rstrip("/")
    changed = corrected != original.rstrip("/")
    return {
        "base_url": corrected,
        "provider": provider_id,
        "changed": changed,
        "original": original,
        "reason": reason if changed else "",
    }


def llm_provider_spec(provider: Any) -> Dict[str, Any]:
    provider_id = normalize_provider_id(provider) or infer_llm_provider(provider)
    if provider_id == PROVIDER_AUTO:
        provider_id = "openai"
    return dict(LLM_PROVIDER_CATALOG.get(provider_id) or LLM_PROVIDER_CATALOG["openai"])


def llm_provider_defaults(provider: Any) -> Dict[str, Any]:
    if normalize_provider_id(provider) == PROVIDER_AUTO:
        return {"base_url": "", "model": "", "max_tokens": 1600, "context_window": 128000}
    spec = llm_provider_spec(provider)
    return {
        "base_url": str(spec.get("base_url") or ""),
        "model": str(spec.get("model") or ""),
        "max_tokens": 1600,
        "context_window": 128000,
    }


def llm_provider_label(provider: Any) -> str:
    if normalize_provider_id(provider) == PROVIDER_AUTO:
        return "自动识别"
    return str(llm_provider_spec(provider).get("label") or "OpenAI")


def llm_provider_default_name(provider: Any) -> str:
    if normalize_provider_id(provider) == PROVIDER_AUTO:
        return "自动识别"
    spec = llm_provider_spec(provider)
    return str(spec.get("default_name") or spec.get("label") or "OpenAI")


def llm_provider_options(include_auto: bool = True) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    if include_auto:
        options.append({
            "value": PROVIDER_AUTO,
            "label": "自动识别",
            "base_url": "",
            "model": "",
            "model_placeholder": "按 Base URL / Model 自动匹配",
        })
    for provider_id, spec in LLM_PROVIDER_CATALOG.items():
        options.append({
            "value": provider_id,
            "label": str(spec.get("label") or provider_id),
            "base_url": str(spec.get("base_url") or ""),
            "model": str(spec.get("model") or ""),
            "model_placeholder": str(spec.get("model_placeholder") or spec.get("model") or "模型 ID"),
        })
    return options
