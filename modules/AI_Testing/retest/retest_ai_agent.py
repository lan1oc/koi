#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI 测试 Agent。

Agent 必须参与通报读取、复测规划和最终结论判定。固定工具负责实际 HTTP
动作和证据记录，AI 负责补全文档读取遗漏、选择/生成复测步骤并解释结论。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from modules.AI_Testing.retest.retest_tool_registry import RetestToolRegistry


_AI_REQUEST_SEMAPHORE = threading.BoundedSemaphore(2)
_OPENROUTER_FREE_REQUEST_SEMAPHORE = threading.BoundedSemaphore(1)
_OPENROUTER_FREE_RATE_LOCK = threading.RLock()
_OPENROUTER_FREE_REQUEST_TIMES: List[float] = []

SUPPORTED_LLM_PROVIDERS = {"openai", "anthropic", "openrouter"}
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_FREE_MODEL = "openrouter/free"
OPENROUTER_FREE_REQUESTS_PER_MINUTE = 20
_PROMPT_CACHE: Dict[str, str] = {}


def load_retest_prompt(name: str) -> str:
    prompt_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip()).strip("_")
    if not prompt_name:
        raise RuntimeError("AI 系统提示词名称为空")
    cached = _PROMPT_CACHE.get(prompt_name)
    if cached is not None:
        return cached

    relative_path = f"modules/AI_Testing/retest/prompts/{prompt_name}.md"
    candidates: List[Path] = []
    try:
        from modules.utils.resource_path import get_resource_path

        candidates.append(get_resource_path(relative_path))
    except Exception:
        pass
    candidates.append(Path(__file__).resolve().parent / "prompts" / f"{prompt_name}.md")

    for prompt_path in candidates:
        try:
            if prompt_path.exists() and prompt_path.is_file():
                text = prompt_path.read_text(encoding="utf-8").strip()
                if text:
                    _PROMPT_CACHE[prompt_name] = text
                    return text
        except Exception as exc:
            logging.warning("读取 AI 系统提示词失败: %s (%s)", prompt_path, exc)
    checked = "、".join(str(path) for path in candidates)
    raise RuntimeError(f"AI 系统提示词文件缺失或为空: {prompt_name}.md；已检查 {checked}")


class RetestLLMClient:
    """OpenAI Chat Completions / Anthropic Messages 兼容客户端。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.provider = str(self.config.get("provider") or "openai").strip().lower()
        self.base_url = str(self.config.get("base_url") or "").strip().rstrip("/")
        self.api_key = str(self.config.get("api_key") or "").strip()
        self.model = str(self.config.get("model") or "").strip()
        self.temperature = float(self.config.get("temperature") if self.config.get("temperature") is not None else 0.1)
        self.max_tokens = int(self.config.get("max_tokens") or 1600)
        self.context_window = int(self.config.get("context_window") or 128000)
        self.connect_timeout = int(self.config.get("connect_timeout") or 15)
        self.read_timeout = int(self.config.get("read_timeout") or 180)
        self.max_retries = int(self.config.get("max_retries") or 2)
        callback = self.config.get("_stream_callback")
        self.stream_callback = callback if callable(callback) else None
        reasoning_cb = self.config.get("_reasoning_callback")
        self.reasoning_callback = reasoning_cb if callable(reasoning_cb) else None
        self.dialogue_stream = bool(self.config.get("_dialogue_stream"))

    def is_ready(self) -> bool:
        return bool(self.api_key and self.model and self.provider in SUPPORTED_LLM_PROVIDERS)

    def missing_items(self) -> List[str]:
        missing: List[str] = []
        if self.provider not in SUPPORTED_LLM_PROVIDERS:
            missing.append("Provider")
        if not self.api_key:
            missing.append("API Key")
        if not self.model:
            missing.append("Model")
        return missing

    def complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self.is_ready():
            raise RuntimeError("AI Agent 未配置 provider/api_key/model")
        if self.provider == "anthropic":
            text = self._anthropic_messages(system_prompt, user_prompt)
        else:
            text = self._openai_chat_completions(system_prompt, user_prompt)
        return self._parse_json_object(text)

    # ====== 原生 function-calling 接口（供 ReAct loop 使用）======

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """带原生工具调用的单轮对话。

        messages 使用 provider 无关的中间格式（OpenAI 风格）：
            {"role": "system"|"user"|"assistant"|"tool", "content": str,
             "tool_calls": [{"id", "name", "arguments": dict}],  # assistant
             "tool_call_id": str}                                # tool
        tools 使用统一格式：
            {"name", "description", "parameters": <json schema>}

        返回归一化结果：
            {"content": str, "thinking": str,
             "tool_calls": [{"id", "name", "arguments": dict}],
             "finish_reason": str}
        """
        if not self.is_ready():
            raise RuntimeError("AI Agent 未配置 provider/api_key/model")
        if self.provider == "anthropic":
            return self._anthropic_chat(messages, tools or [])
        return self._openai_chat(messages, tools or [])

    def _openai_chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        base_url = self.base_url or (OPENROUTER_DEFAULT_BASE_URL if self.provider == "openrouter" else "https://api.openai.com/v1")
        url = f"{base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": str(tool.get("name") or ""),
                        "description": str(tool.get("description") or ""),
                        "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"
        label = "OpenRouter" if self.provider == "openrouter" else "OpenAI-compatible"
        # 有 stream_callback 时走真流式（边想边吐字 + 工具调用增量拼装）；
        # 否则保持一次性返回，稳健且对无回调的调用方（冒烟/批处理）零影响。
        if self.stream_callback:
            return self._with_retries(lambda: self._openai_chat_stream(url, payload), label)
        data = self._with_retries(lambda: self._openai_post(url, payload), label)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = str(message.get("content") or "")
        tool_calls: List[Dict[str, Any]] = []
        for item in message.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else {}
            tool_calls.append({
                "id": str(item.get("id") or f"call_{len(tool_calls)}"),
                "name": str(fn.get("name") or ""),
                "arguments": self._safe_json_args(fn.get("arguments")),
            })
        return {
            "content": content,
            "thinking": str(message.get("reasoning_content") or ""),
            "tool_calls": tool_calls,
            "finish_reason": str(choice.get("finish_reason") or ""),
        }

    def _openai_chat_stream(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """OpenAI/OpenRouter 真流式：逐 SSE chunk 组装 content 与 tool_calls。

        - delta.content：实时回调 stream_callback（边想边吐字）。
        - delta.tool_calls：按 index 累积 id / function.name / function.arguments
          （arguments 是字符串分片，全部拼完后再 _safe_json_args 解析）。
        返回与一次性路径完全一致的归一化 dict，对上层零感知。
        """
        stream_payload = {**payload, "stream": True}
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=stream_payload,
            timeout=(self.connect_timeout, self.read_timeout),
            stream=True,
        )
        self._raise_for_status(response)
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        # index -> {"id","name","args"}：按 OpenAI 流式协议的 tool_calls[].index 累积
        tool_acc: Dict[int, Dict[str, str]] = {}
        finish_reason = ""
        for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
            line = str(raw_line or "").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            if line == "[DONE]":
                break
            try:
                data = json.loads(line)
            except Exception:
                logging.debug("ignore malformed model stream line: %s", line[:200])
                continue
            choice = (data.get("choices") or [{}])[0]
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason"))
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            text = delta.get("content")
            if text:
                chunk = str(text)
                content_parts.append(chunk)
                if self.stream_callback:
                    try:
                        self.stream_callback(chunk)
                    except Exception:
                        logging.debug("model stream callback failed", exc_info=True)
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                reasoning_parts.append(str(reasoning))
                if self.reasoning_callback:
                    try:
                        self.reasoning_callback(str(reasoning))
                    except Exception:
                        logging.debug("model reasoning callback failed", exc_info=True)
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                try:
                    idx = int(tc.get("index") or 0)
                except Exception:
                    idx = 0
                slot = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = str(tc.get("id"))
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                if fn.get("name"):
                    slot["name"] = str(fn.get("name"))
                if fn.get("arguments"):
                    slot["args"] += str(fn.get("arguments"))
        tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(tool_acc.keys()):
            slot = tool_acc[idx]
            if not slot.get("name"):
                continue
            tool_calls.append({
                "id": slot.get("id") or f"call_{idx}",
                "name": slot.get("name") or "",
                "arguments": self._safe_json_args(slot.get("args")),
            })
        return {
            "content": "".join(content_parts),
            "thinking": "".join(reasoning_parts),
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
        }

    def _openai_post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(self.connect_timeout, self.read_timeout),
        )
        self._raise_for_status(response)
        return response.json()

    def _anthropic_chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        base_url = self.base_url or "https://api.anthropic.com/v1"
        url = f"{base_url}/messages"
        system_text, anthropic_messages = self._to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = [
                {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or ""),
                    "input_schema": tool.get("parameters") or {"type": "object", "properties": {}},
                }
                for tool in tools
            ]
        data = self._with_retries(lambda: self._anthropic_request(url, payload), "Anthropic")
        content = ""
        tool_calls: List[Dict[str, Any]] = []
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                content += str(block.get("text") or "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": str(block.get("id") or f"call_{len(tool_calls)}"),
                    "name": str(block.get("name") or ""),
                    "arguments": block.get("input") if isinstance(block.get("input"), dict) else {},
                })
        if content and self.stream_callback:
            try:
                self.stream_callback(content)
            except Exception:
                logging.debug("model stream callback failed", exc_info=True)
        return {
            "content": content,
            "thinking": "",
            "tool_calls": tool_calls,
            "finish_reason": str(data.get("stop_reason") or ""),
        }

    def _to_openai_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for msg in messages:
            role = str(msg.get("role") or "user")
            if role == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": str(msg.get("tool_call_id") or ""),
                    "content": str(msg.get("content") or ""),
                })
                continue
            if role == "assistant" and msg.get("tool_calls"):
                out.append({
                    "role": "assistant",
                    "content": str(msg.get("content") or "") or None,
                    "tool_calls": [
                        {
                            "id": str(call.get("id") or f"call_{idx}"),
                            "type": "function",
                            "function": {
                                "name": str(call.get("name") or ""),
                                "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                            },
                        }
                        for idx, call in enumerate(msg.get("tool_calls") or [])
                    ],
                })
                continue
            out.append({"role": role, "content": str(msg.get("content") or "")})
        return out

    def _to_anthropic_messages(self, messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
        system_parts: List[str] = []
        out: List[Dict[str, Any]] = []
        for msg in messages:
            role = str(msg.get("role") or "user")
            if role == "system":
                system_parts.append(str(msg.get("content") or ""))
                continue
            if role == "tool":
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": str(msg.get("tool_call_id") or ""),
                        "content": str(msg.get("content") or ""),
                    }],
                })
                continue
            if role == "assistant" and msg.get("tool_calls"):
                blocks: List[Dict[str, Any]] = []
                text = str(msg.get("content") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
                for call in msg.get("tool_calls") or []:
                    blocks.append({
                        "type": "tool_use",
                        "id": str(call.get("id") or ""),
                        "name": str(call.get("name") or ""),
                        "input": call.get("arguments") or {},
                    })
                out.append({"role": "assistant", "content": blocks})
                continue
            out.append({"role": role, "content": str(msg.get("content") or "")})
        return "\n\n".join(part for part in system_parts if part), out

    @staticmethod
    def _safe_json_args(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            try:
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(text)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}

    def _openai_chat_completions(self, system_prompt: str, user_prompt: str) -> str:
        base_url = self.base_url or (OPENROUTER_DEFAULT_BASE_URL if self.provider == "openrouter" else "https://api.openai.com/v1")
        url = f"{base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if not self.dialogue_stream:
            payload["response_format"] = {"type": "json_object"}
        label = "OpenRouter" if self.provider == "openrouter" else "OpenAI-compatible"
        return self._with_retries(lambda: self._openai_stream(url, payload), label)

    def _openai_stream(self, url: str, payload: Dict[str, Any]) -> str:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(self.connect_timeout, self.read_timeout),
            stream=True,
        )
        self._raise_for_status(response)
        chunks: List[str] = []
        for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
            line = str(raw_line or "").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            if line == "[DONE]":
                break
            try:
                data = json.loads(line)
            except Exception:
                logging.debug("ignore malformed model stream line: %s", line[:200])
                continue
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            content = delta.get("content") if delta else message.get("content")
            if content:
                text = str(content)
                chunks.append(text)
                if self.stream_callback:
                    try:
                        self.stream_callback(text)
                    except Exception:
                        logging.debug("model stream callback failed", exc_info=True)
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("模型流式响应为空")
        return text

    def _anthropic_messages(self, system_prompt: str, user_prompt: str) -> str:
        base_url = self.base_url or "https://api.anthropic.com/v1"
        url = f"{base_url}/messages"
        payload: Dict[str, Any] = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        data = self._with_retries(lambda: self._anthropic_request(url, payload), "Anthropic")
        parts = data.get("content") or []
        return "\n".join(str(item.get("text") or "") for item in parts if isinstance(item, dict))

    def _anthropic_request(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(self.connect_timeout, self.read_timeout),
        )
        self._raise_for_status(response)
        return response.json()

    def _with_retries(self, fn, label: str):
        last_error: Exception | None = None
        free_route = self._is_openrouter_free_request()
        if free_route:
            with _OPENROUTER_FREE_REQUEST_SEMAPHORE:
                return self._retry_model_request(fn, label, True)
        return self._retry_model_request(fn, label, False)

    def _retry_model_request(self, fn, label: str, throttle_openrouter_free: bool):
        last_error: Exception | None = None
        with _AI_REQUEST_SEMAPHORE:
            for attempt in range(self.max_retries + 1):
                try:
                    if throttle_openrouter_free:
                        self._wait_for_openrouter_free_slot()
                    return fn()
                except requests.exceptions.ReadTimeout as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        break
                    time.sleep(min(2 ** attempt, 4))
                except requests.exceptions.ConnectTimeout as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        break
                    time.sleep(min(2 ** attempt, 4))
                except requests.exceptions.Timeout as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        break
                    time.sleep(min(2 ** attempt, 4))
        if isinstance(last_error, requests.exceptions.Timeout):
            raise RuntimeError(f"{label} 模型响应超时/网络超时，已暂停，可稍后继续: {last_error}") from last_error
        if last_error:
            raise last_error
        raise RuntimeError(f"{label} 模型调用失败")

    def _is_openrouter_free_request(self) -> bool:
        model = self.model.strip().lower()
        return self.provider == "openrouter" and (model == OPENROUTER_FREE_MODEL or model.endswith(":free"))

    @staticmethod
    def _wait_for_openrouter_free_slot() -> None:
        while True:
            now = time.monotonic()
            with _OPENROUTER_FREE_RATE_LOCK:
                cutoff = now - 60.0
                while _OPENROUTER_FREE_REQUEST_TIMES and _OPENROUTER_FREE_REQUEST_TIMES[0] <= cutoff:
                    _OPENROUTER_FREE_REQUEST_TIMES.pop(0)
                if len(_OPENROUTER_FREE_REQUEST_TIMES) < OPENROUTER_FREE_REQUESTS_PER_MINUTE:
                    _OPENROUTER_FREE_REQUEST_TIMES.append(now)
                    return
                wait_seconds = max(0.25, 60.0 - (now - _OPENROUTER_FREE_REQUEST_TIMES[0]) + 0.1)
            time.sleep(min(wait_seconds, 5.0))

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code == 429:
            raise RuntimeError("模型并发/限流（HTTP 429），请稍后继续测试")
        if response.status_code == 402:
            raise RuntimeError(f"模型额度不足或余额为负（HTTP 402）: {response.text[:500]}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"模型接口返回 HTTP {response.status_code}: {response.text[:500]}") from exc

    def _parse_json_object(self, text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        fence = re.search(r"```(?:json|JSON)\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
        if fence:
            parsed = json.loads(fence.group(1))
            return parsed if isinstance(parsed, dict) else {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            decoder = json.JSONDecoder()
            best: tuple[int, Dict[str, Any]] | None = None
            for match in re.finditer(r"\{", raw):
                try:
                    parsed, end = decoder.raw_decode(raw[match.start():])
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    span = int(end)
                    if best is None or span > best[0]:
                        best = (span, parsed)
            if best is not None:
                return best[1]
            raise


class RetestAIAgent:
    """复测 Agent：通报分析、复测规划和结论判定都必须由 AI 参与。"""

    def __init__(self, config: Dict[str, Any], registry: Optional[RetestToolRegistry] = None):
        self.config = config or {}
        self.registry = registry or RetestToolRegistry()
        self.client = RetestLLMClient(self.config)

    def enabled(self) -> bool:
        return bool(self.config.get("enabled") and self.client.is_ready())

    def require_ready(self) -> None:
        if self.enabled():
            return
        if not self.config.get("enabled"):
            raise RuntimeError("AI 测试需要先在「模型与工具」中启用 AI Agent")
        missing = "、".join(self.client.missing_items() or ["必要配置"])
        raise RuntimeError(f"AI 测试配置不完整，缺少 {missing}")

    def analyze_report(self, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        """读取通报全文，纠正规则提取遗漏，并给出完整复测计划。"""
        self.require_ready()
        response = self.client.complete_json(
            self._analysis_system_prompt(),
            self._analysis_user_prompt(scan_result),
        )
        return self._normalize_report_analysis(response, scan_result)

    def plan_retest(self, scan_result: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """把 AI 读取结果归一化为执行层可消费的建议。"""
        state = self._base_state(scan_result)
        return self._normalize_advice(analysis, state)

    def judge_retest(self, scan_result: Dict[str, Any], result_data: Dict[str, Any]) -> Dict[str, Any]:
        """根据实际工具输出给出最终复测结论。"""
        self.require_ready()
        response = self.client.complete_json(
            self._judge_system_prompt(),
            self._judge_user_prompt(scan_result, result_data),
        )
        return self._normalize_judgement(response, result_data)

    def generate_python_probe(self, scan_result: Dict[str, Any], result_data: Dict[str, Any], tool_context: Dict[str, Any]) -> Dict[str, str]:
        """执行阶段固定工具不足时，基于页面/JS/工具观察生成一次受限 HTTP 探针。"""
        self.require_ready()
        response = self.client.complete_json(
            self._probe_system_prompt(),
            self._probe_user_prompt(scan_result, result_data, tool_context),
        )
        return self._normalize_python_probe(self._merged_response(response).get("python_probe") or response)

    def repair_python_probe(
        self,
        scan_result: Dict[str, Any],
        result_data: Dict[str, Any],
        tool_context: Dict[str, Any],
        previous_script: str,
        failure: str,
        attempt: int,
    ) -> Dict[str, str]:
        """Python 探针失败后，让模型按失败原因继续修正脚本。"""
        self.require_ready()
        response = self.client.complete_json(
            self._probe_repair_system_prompt(),
            self._probe_repair_user_prompt(scan_result, result_data, tool_context, previous_script, failure, attempt),
        )
        return self._normalize_python_probe(self._merged_response(response).get("python_probe") or response)

    def decide_next_action(self, scan_result: Dict[str, Any], result_data: Dict[str, Any], tool_context: Dict[str, Any]) -> Dict[str, Any]:
        """像正常 Agent 一样在观察工具输出后决定下一步工具或是否进入判定。"""
        self.require_ready()
        response = self.client.complete_json(
            self._decision_system_prompt(),
            self._decision_user_prompt(scan_result, result_data, tool_context),
        )
        return self._normalize_decision(response)

    def advise(self, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        analysis = self.analyze_report(scan_result)
        return self.plan_retest(scan_result, analysis)

    def apply_advice(self, scan_result: Dict[str, Any], advice: Dict[str, Any]) -> Dict[str, Any]:
        context = scan_result.get("retest_context")
        if not isinstance(context, dict):
            context = {}
            scan_result["retest_context"] = context

        reported_findings = self._normalize_reported_findings(advice.get("reported_findings") or [])
        corrected_vulns = self._string_list(advice.get("corrected_vulnerability_types") or [])[:20]
        corrected_urls = self._http_url_list(advice.get("corrected_target_urls") or [])[:20]
        extra_paths = self._path_list(advice.get("extra_path_candidates") or [])[:40]
        expected_markers = self._string_list(advice.get("expected_markers") or [])[:40]

        for finding in reported_findings:
            vuln_type = str(finding.get("vulnerability_type") or "").strip()
            if vuln_type:
                corrected_vulns.append(vuln_type)
            for target in finding.get("targets") or []:
                target_text = str(target or "").strip()
                if target_text.startswith(("http://", "https://")):
                    corrected_urls.append(target_text)
                elif target_text.startswith("/"):
                    extra_paths.append(target_text)
            for path in finding.get("path_candidates") or []:
                extra_paths.append(str(path or ""))
            for evidence in finding.get("evidence") or []:
                evidence_text = str(evidence or "").strip()
                if evidence_text and len(evidence_text) <= 120:
                    expected_markers.append(evidence_text)

        if corrected_vulns:
            existing_vulns = [str(item) for item in (scan_result.get("vulnerability_types") or []) if str(item).strip()]
            scan_result["vulnerability_types"] = list(dict.fromkeys(existing_vulns + corrected_vulns))

        if corrected_urls:
            existing_urls = [str(item) for item in (context.get("target_urls") or scan_result.get("urls") or []) if str(item).strip()]
            merged_urls = list(dict.fromkeys(existing_urls + corrected_urls))
            context["target_urls"] = merged_urls
            scan_result["urls"] = merged_urls

        if extra_paths:
            context["path_candidates"] = list(dict.fromkeys([str(item) for item in (context.get("path_candidates") or [])] + self._path_list(extra_paths)))

        if expected_markers:
            context["expected_markers"] = list(dict.fromkeys([str(item) for item in (context.get("expected_markers") or [])] + expected_markers))

        recommended = self.registry.filter_known(advice.get("recommended_checks") or [])
        if recommended:
            context["agent_recommended_checks"] = recommended

        corrected_tags = self._known_tags(advice.get("corrected_issue_tags") or [])
        if corrected_tags:
            existing = [str(item) for item in (context.get("issue_tags") or [])]
            context["issue_tags"] = list(dict.fromkeys(existing + corrected_tags))

        if reported_findings:
            context["reported_findings"] = reported_findings

        context["agent_advice"] = {
            "enabled": True,
            "used": bool(advice.get("used", True)),
            "provider": advice.get("provider") or self.client.provider,
            "model": advice.get("model") or self.client.model,
            "phase": "analysis_and_planning",
            "overall_report_summary": advice.get("overall_report_summary") or "",
            "reported_findings": reported_findings,
            "plan_steps": advice.get("plan_steps") or [],
            "confidence": advice.get("confidence"),
            "notes": advice.get("notes") or "",
            "warnings": advice.get("warnings") or [],
            "recommended_checks": recommended,
            "corrected_vulnerability_types": list(dict.fromkeys(corrected_vulns))[:20],
            "corrected_target_urls": list(dict.fromkeys(corrected_urls))[:20],
            "extra_path_candidates": self._path_list(list(dict.fromkeys(extra_paths)))[:40],
            "expected_markers": list(dict.fromkeys(expected_markers))[:40],
            "python_probe": advice.get("python_probe") or {},
            "reason": advice.get("reason") or "",
            "error": advice.get("error") or "",
        }
        return scan_result

    def _base_state(self, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "enabled": True,
            "used": True,
            "provider": self.client.provider,
            "model": self.client.model,
            "overall_report_summary": "",
            "reported_findings": [],
            "recommended_checks": [],
            "corrected_issue_tags": [],
            "corrected_vulnerability_types": [],
            "corrected_target_urls": [],
            "extra_path_candidates": [],
            "expected_markers": [],
            "plan_steps": [],
            "confidence": "medium",
            "notes": "",
            "warnings": [],
            "python_probe": {},
        }

    def _analysis_system_prompt(self) -> str:
        return load_retest_prompt("analysis_system")

    def _analysis_user_prompt(self, scan_result: Dict[str, Any]) -> str:
        payload = {
            "task": "读取通报全文，补全文档提取遗漏，并给出完整 AI 复测计划。",
            "schema": {
                "overall_report_summary": "一句话概括通报问题",
                "reported_findings": [
                    {
                        "id": "finding-1",
                        "title": "通报中的漏洞标题",
                        "vulnerability_type": "漏洞类型",
                        "targets": ["http/https URL 或通报目标"],
                        "path_candidates": ["/通报路径"],
                        "evidence": ["通报里的证据特征"],
                        "retest_goal": "如何判断是否仍可复现",
                        "confidence": "low|medium|high",
                    }
                ],
                "corrected_vulnerability_types": ["通报全文读到的所有漏洞类型"],
                "corrected_target_urls": ["http/https URL"],
                "extra_path_candidates": ["/通报中出现或复测必须使用的路径"],
                "expected_markers": ["响应/页面/接口证据特征"],
                "corrected_issue_tags": ["tag"],
                "recommended_checks": ["registered tool_id"],
                "plan_steps": ["短句，说明将如何复测"],
                "python_probe": {"reason": "固定工具不足时为什么需要脚本", "script": "def run(targets, context): ..."},
                "confidence": "low|medium|high",
                "notes": "短说明",
                "warnings": ["执行限制或不确定性"],
            },
            "registered_tools": self.registry.catalog(),
            "scan_result": self._safe_scan_result(scan_result),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _probe_system_prompt(self) -> str:
        return load_retest_prompt("probe_system")

    def _decision_system_prompt(self) -> str:
        return load_retest_prompt("decision_system")

    def _probe_repair_system_prompt(self) -> str:
        return load_retest_prompt("probe_repair_system")

    def _probe_user_prompt(self, scan_result: Dict[str, Any], result_data: Dict[str, Any], tool_context: Dict[str, Any]) -> str:
        payload = {
            "task": "基于页面/JS/工具观察生成一次执行阶段 Python HTTP 探针。",
            "schema": {
                "python_probe": {
                    "reason": "为什么固定工具不足、脚本将验证什么",
                    "script": "def run(targets, context): ...",
                }
            },
            "script_contract": {
                "targets": "通报目标 URL 列表，脚本只能请求这些 URL 的同源地址",
                "allowed_python": "可使用普通 Python 控制流、函数、异常、推导式、字符串/列表/字典处理。",
                "network": "只能通过 http_request(...) 或预置的 requests/http 对象访问 targets 同源 URL。",
                "context": {
                    "credential_candidates": "含 username/password/password_masked，仅使用这里的通报凭据",
                    "http_request_candidates": "通报中的 HTTP 请求块",
                    "payload_candidates": "通报中的载荷",
                    "page_observations": "当前页面 HTML、同源 JS 摘要、候选 endpoint",
                    "tool_observations": "固定工具已经执行过的输出摘要",
                },
            },
            "scan_result": self._safe_scan_result(scan_result),
            "result_data": self._safe_result_data(result_data),
            "tool_context": self._safe_tool_context(tool_context),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _probe_repair_user_prompt(
        self,
        scan_result: Dict[str, Any],
        result_data: Dict[str, Any],
        tool_context: Dict[str, Any],
        previous_script: str,
        failure: str,
        attempt: int,
    ) -> str:
        payload = {
            "task": "上一次 Python HTTP 探针未达成执行目标。请根据失败原因修正脚本并继续验证，不要改变复测范围。",
            "attempt": attempt,
            "failure": str(failure or "")[:4000],
            "previous_script": str(previous_script or "")[:12000],
            "schema": {
                "python_probe": {
                    "reason": "说明你修正了什么、下一次脚本将验证什么",
                    "script": "def run(targets, context): ...",
                }
            },
            "script_contract": {
                "targets": "通报目标 URL 列表，脚本只能请求这些 URL 的同源地址",
                "allowed_python": "可使用普通 Python 控制流、函数、异常、推导式、字符串/列表/字典处理。",
                "network": "只能通过 http_request(...) 或预置的 requests/http 对象访问 targets 同源 URL。",
                "requests_args": "支持 headers、params、data、json/json_body、files、content_type、allow_redirects。",
                "record": "每个关键请求或判断必须调用 record(title,severity,detail,evidence)。",
            },
            "scan_result": self._safe_scan_result(scan_result),
            "result_data": self._safe_result_data(result_data),
            "tool_context": self._safe_tool_context(tool_context),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _decision_user_prompt(self, scan_result: Dict[str, Any], result_data: Dict[str, Any], tool_context: Dict[str, Any]) -> str:
        payload = {
            "task": "根据当前观察决定下一步工具调用，或说明已经可以进入最终判定。",
            "schema": {
                "message": "给用户看的简短执行说明",
                "final_ready": False,
                "tool_calls": [
                    {
                        "tool_id": "registered tool_id",
                        "reason": "为什么调用这个工具",
                    }
                ],
                "python_probe": {
                    "reason": "需要自主 HTTP 探针时说明原因",
                    "script": "def run(targets, context): ...",
                },
            },
            "available_tools": [
                tool for tool in self.registry.catalog()
                if tool.get("category") != "agent_tools"
            ],
            "script_contract": {
                "targets": "通报目标 URL 列表，脚本只能请求这些 URL 的同源地址",
                "allowed_python": "可使用普通 Python 控制流、函数、异常、推导式、字符串/列表/字典处理。",
                "network": "只能通过 http_request(...) 或预置的 requests/http 对象访问 targets 同源 URL。",
                "context": {
                    "credential_candidates": "通报凭据，含 username/password/password_masked",
                    "http_request_candidates": "通报 HTTP 请求块",
                    "payload_candidates": "通报 payload",
                    "page_observations": "页面 HTML、JS、表单、候选 endpoint",
                    "tool_observations": "已执行工具观察",
                },
            },
            "scan_result": self._safe_scan_result(scan_result),
            "result_data": self._safe_result_data(result_data),
            "tool_context": self._safe_tool_context(tool_context),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _judge_system_prompt(self) -> str:
        return load_retest_prompt("judge_system")

    def _judge_user_prompt(self, scan_result: Dict[str, Any], result_data: Dict[str, Any]) -> str:
        payload = {
            "task": "根据通报和复测工具输出，判断漏洞是否仍可复现。",
            "judgement_rules": [
                "只判断通报正文描述的同一漏洞是否复现。",
                "工具输出只提供请求、响应、脚本记录和运行错误；不要把工具字段当作结论。",
                "只有你能从通报目标、通报路径、通报请求/载荷或通报证据特征与当前响应之间建立直接关系时，才能支撑 reproduced。",
                "本次复测中新发现但不能对应原通报的其它问题，只能作为旁路观察，不能作为原漏洞可复现证据。",
                "通报 phpinfo 页面未返回 phpinfo() / PHPINFO 页面时，应判 not_reproduced；500 错误页暴露版本/路径/邮箱属于旁路观察。",
            ],
            "schema": {
                "verdict": "reproduced|not_reproduced",
                "confidence": "low|medium|high",
                "reason": "中文说明",
                "evidence": ["支撑判断的关键证据"],
                "fix_status": "risk|clean",
                "conclusion": "漏洞未修复/可复现 或 漏洞已修复/复测通过",
            },
            "scan_result": self._safe_scan_result(scan_result),
            "result_data": self._safe_result_data(result_data),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _normalize_report_analysis(self, response: Dict[str, Any], scan_result: Dict[str, Any]) -> Dict[str, Any]:
        merged = self._merged_response(response)
        merged["provider"] = self.client.provider
        merged["model"] = self.client.model
        merged["enabled"] = True
        merged["used"] = True
        return merged

    def _normalize_advice(self, response: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        source = self._merged_response(response)
        recommended = self.registry.filter_known(source.get("recommended_checks") or [])
        reported_findings = self._normalize_reported_findings(source.get("reported_findings") or source.get("findings") or [])
        state.update({
            "enabled": True,
            "used": True,
            "provider": self.client.provider,
            "model": self.client.model,
            "overall_report_summary": str(source.get("overall_report_summary") or source.get("summary") or ""),
            "reported_findings": reported_findings,
            "recommended_checks": recommended,
            "corrected_issue_tags": self._known_tags(source.get("corrected_issue_tags") or source.get("issue_tags") or []),
            "corrected_vulnerability_types": self._string_list(source.get("corrected_vulnerability_types") or source.get("vulnerability_types") or [])[:20],
            "corrected_target_urls": self._http_url_list(source.get("corrected_target_urls") or source.get("target_urls") or [])[:20],
            "extra_path_candidates": self._path_list(source.get("extra_path_candidates") or source.get("path_candidates") or [])[:40],
            "expected_markers": self._string_list(source.get("expected_markers") or [])[:40],
            "plan_steps": self._string_list(source.get("plan_steps") or [])[:10],
            "confidence": str(source.get("confidence") or "medium"),
            "notes": str(source.get("notes") or ""),
            "warnings": self._string_list(source.get("warnings") or [])[:8],
            "python_probe": self._normalize_python_probe(source.get("python_probe")),
        })
        if state["python_probe"] and "check_ai_python_probe" not in state["recommended_checks"]:
            state["recommended_checks"].append("check_ai_python_probe")
        return state

    def _normalize_judgement(self, response: Dict[str, Any], result_data: Dict[str, Any]) -> Dict[str, Any]:
        source = self._merged_response(response)
        raw = str(source.get("verdict") or source.get("reproduction_status") or source.get("fix_status") or "").strip().lower()
        reproduced_values = {"reproduced", "reproducible", "unfixed", "not_fixed", "risk", "vulnerable", "可复现", "未修复"}
        clean_values = {"not_reproduced", "not reproducible", "fixed", "clean", "pass", "passed", "已修复", "复测通过", "不可复现"}
        if isinstance(source.get("reproduced"), bool):
            reproduced = bool(source.get("reproduced"))
        elif raw in reproduced_values:
            reproduced = True
        elif raw in clean_values:
            reproduced = False
        else:
            raise RuntimeError("模型判定缺少明确 verdict。必须输出 reproduced 或 not_reproduced，不能由代码按工具结果兜底。")
        verdict = "reproduced" if reproduced else "not_reproduced"
        reason = str(source.get("reason") or source.get("notes") or "")
        return {
            "enabled": True,
            "used": True,
            "provider": self.client.provider,
            "model": self.client.model,
            "verdict": verdict,
            "reproduced": reproduced,
            "fix_status": "risk" if reproduced else "clean",
            "conclusion": "漏洞未修复/可复现" if reproduced else "漏洞已修复/复测通过",
            "confidence": str(source.get("confidence") or "medium"),
            "reason": reason,
            "evidence": self._string_list(source.get("evidence") or [])[:12],
            "raw_verdict": raw,
        }

    def _normalize_python_probe(self, value: Any) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        script = str(value.get("script") or "").strip()
        if not script:
            return {}
        if len(script) > 12000:
            script = script[:12000]
        return {
            "reason": str(value.get("reason") or value.get("notes") or "固定工具不足，使用受限 Python HTTP 探针补充验证。")[:500],
            "script": script,
        }

    def _normalize_decision(self, response: Dict[str, Any]) -> Dict[str, Any]:
        source = self._merged_response(response)
        calls: List[Dict[str, str]] = []
        for item in (source.get("tool_calls") or source.get("tools") or [])[:4]:
            if not isinstance(item, dict):
                continue
            tool_id = str(item.get("tool_id") or item.get("name") or "").strip()
            if not self.registry.has_tool(tool_id):
                continue
            spec = self.registry.get(tool_id)
            if spec and spec.category == "agent_tools":
                continue
            calls.append({
                "tool_id": tool_id,
                "reason": str(item.get("reason") or item.get("notes") or "")[:500],
            })
        probe = self._normalize_python_probe(source.get("python_probe"))
        if probe and not any(item.get("tool_id") == "check_ai_python_probe" for item in calls):
            calls.append({"tool_id": "check_ai_python_probe", "reason": probe.get("reason") or "AI 自主生成 HTTP 探针。"})
        return {
            "message": str(source.get("message") or source.get("notes") or source.get("reason") or "")[:1000],
            "final_ready": bool(source.get("final_ready") or source.get("ready_to_judge") or source.get("done")),
            "tool_calls": calls,
            "python_probe": probe,
        }

    def _normalize_reported_findings(self, values: Any) -> List[Dict[str, Any]]:
        if not isinstance(values, list):
            return []
        findings: List[Dict[str, Any]] = []
        for index, item in enumerate(values[:20], 1):
            if not isinstance(item, dict):
                continue
            targets = self._string_list(item.get("targets") or item.get("target_urls") or [])
            paths = self._path_list(item.get("path_candidates") or item.get("paths") or [])
            findings.append({
                "id": str(item.get("id") or f"finding-{index}")[:80],
                "title": str(item.get("title") or item.get("name") or f"通报漏洞 {index}")[:200],
                "vulnerability_type": str(item.get("vulnerability_type") or item.get("type") or "")[:160],
                "targets": targets[:12],
                "path_candidates": paths[:20],
                "evidence": self._string_list(item.get("evidence") or item.get("markers") or [])[:12],
                "retest_goal": str(item.get("retest_goal") or item.get("goal") or item.get("description") or "")[:500],
                "confidence": str(item.get("confidence") or "medium"),
            })
        return findings

    def _safe_scan_result(self, scan_result: Dict[str, Any]) -> Dict[str, Any]:
        context = scan_result.get("retest_context") or {}
        safe_context: Dict[str, Any] = {}
        if isinstance(context, dict):
            for key in (
                "target_urls", "all_urls", "path_candidates", "expected_status_codes", "expected_markers",
                "parameter_names", "issue_tags", "evidence_lines", "reported_findings",
            ):
                safe_context[key] = context.get(key) or []
            safe_context["http_request_candidates"] = [
                {
                    "method": item.get("method"),
                    "url": item.get("url"),
                    "target": item.get("target"),
                    "has_body": bool(item.get("body")),
                    "body_preview": str(item.get("body") or "")[:1200],
                    "body_line_count": item.get("body_line_count"),
                    "evidence_lines": item.get("evidence_lines") or [],
                }
                for item in (context.get("http_request_candidates") or [])
                if isinstance(item, dict)
            ][:12]
            safe_context["payload_candidates"] = [
                {
                    "parameter": item.get("parameter"),
                    "url": item.get("url"),
                    "evidence": item.get("evidence"),
                    "raw_preview": str(item.get("raw") or "")[:1200],
                }
                for item in (context.get("payload_candidates") or [])
                if isinstance(item, dict)
            ][:20]
            safe_context["credential_candidates"] = [
                {
                    "username": item.get("username"),
                    "password_masked": item.get("password_masked"),
                    "password_available": bool(item.get("password")),
                    "evidence": item.get("evidence"),
                }
                for item in (context.get("credential_candidates") or [])
                if isinstance(item, dict)
            ][:8]
            safe_context["page_observations"] = context.get("page_observations") or {}
            safe_context["tool_observations"] = context.get("tool_observations") or []

        return {
            "file": scan_result.get("file"),
            "vulnerability_types": scan_result.get("vulnerability_types") or [],
            "urls": scan_result.get("urls") or [],
            "ips": scan_result.get("ips") or [],
            "report_text_from_docx": str(scan_result.get("raw_text") or "")[:80000],
            "retest_context": safe_context,
        }

    def _safe_result_data(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        safe_results: List[Dict[str, Any]] = []
        for item in (result_data.get("retest_results") or [])[:12]:
            if not isinstance(item, dict):
                continue
            vulnerabilities = []
            for vuln in (item.get("vulnerabilities") or [])[:20]:
                if not isinstance(vuln, dict):
                    continue
                vulnerabilities.append({
                    "type": vuln.get("type"),
                    "severity": vuln.get("severity"),
                    "detail": str(vuln.get("detail") or "")[:1000],
                    "evidence": str(vuln.get("evidence") or "")[:1200],
                    "request_safe": str(vuln.get("request_safe") or "")[:4000],
                    "response_meta": vuln.get("response_meta") or {},
                    "response_headers_safe": vuln.get("response_headers_safe") or {},
                    "response_body_preview": str(vuln.get("response_body_preview") or "")[:4000],
                    "response_raw_excerpt": str(vuln.get("response_raw_excerpt") or "")[:5000],
                    "tool_unavailable": bool(vuln.get("tool_unavailable")),
                    "tool_failed": bool(vuln.get("tool_failed")),
                    "python_probe": bool(vuln.get("python_probe")),
                    "python_probe_script": str(vuln.get("python_probe_script") or "")[:12000],
                })
            safe_results.append({
                "url": item.get("url"),
                "request_meta": item.get("request_meta") or {},
                "request_safe": str(item.get("request_safe") or "")[:4000],
                "response_meta": item.get("response_meta") or {},
                "response_headers_safe": item.get("response_headers_safe") or {},
                "response_body_preview": str(item.get("response_body_preview") or "")[:4000],
                "target_unreachable": bool(item.get("target_unreachable")),
                "error": str(item.get("error") or "")[:800],
                "note": str(item.get("note") or "")[:800],
                "observation_count": item.get("observation_count", len(vulnerabilities)),
                "failed_count": item.get("failed_count"),
                "vulnerabilities": vulnerabilities,
            })
        return {
            "urls": result_data.get("urls") or [],
            "observation_count": result_data.get("observation_count"),
            "failed_count": result_data.get("failed_count"),
            "target_unreachable": result_data.get("target_unreachable"),
            "reason": result_data.get("reason"),
            "retest_results": safe_results,
        }

    def _safe_tool_context(self, tool_context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(tool_context, dict):
            return {}
        page = tool_context.get("page_observations") if isinstance(tool_context.get("page_observations"), dict) else {}
        return {
            "target_url": tool_context.get("target_url"),
            "vulnerability_types": tool_context.get("vulnerability_types") or [],
            "issue_tags": tool_context.get("issue_tags") or [],
            "page_observations": {
                "url": page.get("url"),
                "status_code": page.get("status_code"),
                "final_url": page.get("final_url"),
                "frameworks": page.get("frameworks") or [],
                "forms": page.get("forms") or [],
                "script_urls": page.get("script_urls") or [],
                "candidate_endpoints": page.get("candidate_endpoints") or [],
                "html_preview": str(page.get("html_preview") or "")[:12000],
                "javascript_preview": str(page.get("javascript_preview") or "")[:30000],
            },
            "tool_observations": [
                {
                    "type": item.get("type"),
                    "severity": item.get("severity"),
                    "detail": str(item.get("detail") or "")[:1200],
                    "evidence": str(item.get("evidence") or "")[:1200],
                    "request_safe": str(item.get("request_safe") or "")[:2000],
                    "response_meta": item.get("response_meta") or {},
                    "response_body_preview": str(item.get("response_body_preview") or "")[:2000],
                    "tool_failed": bool(item.get("tool_failed")),
                    "tool_unavailable": bool(item.get("tool_unavailable")),
                    "python_probe": bool(item.get("python_probe")),
                }
                for item in (tool_context.get("tool_observations") or [])[:20]
                if isinstance(item, dict)
            ],
        }

    def _merged_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(response or {})
        for key in ("analysis", "report_analysis", "plan", "retest_plan", "judgement", "judgment", "result"):
            value = response.get(key) if isinstance(response, dict) else None
            if isinstance(value, dict):
                merged.update(value)
        return merged

    def _known_tags(self, values: Iterable[Any]) -> List[str]:
        known = {
            "unauthorized", "directory_listing", "path_traversal", "file_read", "sensitive_file",
            "config_leak", "source_leak", "backup_file", "swagger_api", "phpinfo", "js_library",
            "response_header", "tls", "cors", "clickjacking", "http_methods", "weak_password",
            "sql_injection", "xss", "ssrf", "rce", "file_upload", "service_exposure", "open_redirect",
            "csrf", "idor", "logic", "deserialization", "command_injection",
        }
        return [item for item in self._string_list(values) if item in known]

    def _string_list(self, values: Iterable[Any]) -> List[str]:
        if not isinstance(values, list):
            return []
        return [str(item).strip() for item in values if str(item).strip()]

    def _http_url_list(self, values: Iterable[Any]) -> List[str]:
        return [item for item in self._string_list(values) if item.startswith(("http://", "https://"))]

    def _path_list(self, values: Iterable[Any]) -> List[str]:
        paths = []
        for item in self._string_list(values):
            if item.startswith(("http://", "https://")):
                continue
            if not item.startswith("/"):
                item = "/" + item
            paths.append(item)
        return paths
