#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ReAct 复测引擎。

把"分析 → 6 轮选预设工具 → 判定"这套割裂的 complete_json 调用，替换为一个带
完整消息历史、原生 function calling 的 reason-act-observe 主循环。模型可以自由
构造 HTTP 请求、运行受限 Python 探针、调用外部工具（nmap/sqlmap/ffuf）、复用既有
27 个只读复核，并自行决定何时结束取证。

引擎只负责"取证"：产出 observations（写回 scanner 结果的 vulnerabilities）和
executed_tools。最终 reproduced / not_reproduced 仍由 judge_retest（模型）裁定，
本引擎不写 verdict。借鉴 AICTF runner 的循环纪律：
- 第 0 轮强制先给复测计划（plan），不允许直接收尾；
- 软反思阈值后注入一次进度自检，硬阈值后提示尽快收敛；
- 连续不调用工具会被提醒，多次后强制结束；
- 总轮数上限兜底，避免空转烧 token。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from modules.AI_Testing.retest.retest_ai_agent import RetestLLMClient, load_retest_prompt
from modules.AI_Testing.retest.retest_agent_tools import RetestToolExecutor


class RetestReActAgent:
    """围绕 RetestLLMClient.chat 的取证用 ReAct 主循环。"""

    DEFAULT_MAX_ROUNDS = 40
    SOFT_REFLECTION_ROUND = 14      # 软反思：注入一次进度自检
    HARD_PIVOT_ROUND = 28           # 硬提示：尽快收敛取证
    MAX_NO_TOOL_NUDGES = 3          # 连续不调用工具的最大容忍次数

    def __init__(self, ai_config: Dict[str, Any], scanner: Any):
        self.ai_config = dict(ai_config or {})
        self.scanner = scanner
        self.client = RetestLLMClient(self.ai_config)
        try:
            self.max_rounds = int(self.ai_config.get("react_max_rounds") or self.DEFAULT_MAX_ROUNDS)
        except Exception:
            self.max_rounds = self.DEFAULT_MAX_ROUNDS
        # 上限放宽到 120：复杂目标可多跑；简单目标靠 finish_investigation 早停，不会空耗。
        self.max_rounds = max(4, min(self.max_rounds, 120))

    def _should_stop(self) -> bool:
        check = getattr(self.scanner, "stop_check", None)
        if not callable(check):
            return False
        try:
            return bool(check())
        except Exception:
            return False

    # ------------------------------------------------------------------ public

    def run(
        self,
        url: str,
        vuln_types: List[str],
        context: Dict[str, Any],
        probe: Any,
        probe_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """跑完一个目标的取证循环。

        返回:
            {"records": [...], "executed_tools": [...], "summary": str, "rounds": int}
        records 已是 scanner vulnerabilities 兼容格式（type/severity/detail/evidence/...）。
        """
        if not self.client.is_ready():
            raise RuntimeError("AI Agent 未配置 provider/api_key/model")

        executor = RetestToolExecutor(self.scanner, url, context, probe)
        tools = executor.tool_specs()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._initial_user_message(url, vuln_types, context, probe_result)},
        ]

        no_tool_calls = 0
        soft_done = False
        hard_done = False
        round_index = 0

        self._trace_status(
            url,
            "ReAct 取证开始",
            "模型将基于通报与首包响应，自主构造请求、运行探针并记录证据，直到调用 finish_investigation 或达到轮数上限。",
            {"phase": "react", "maxRounds": self.max_rounds},
        )

        while round_index < self.max_rounds and not executor.finished:
            if self._should_stop():
                self._trace_status(
                    url,
                    "复测已停止",
                    "收到停止指令，已中断 ReAct 取证循环。",
                    {"phase": "react", "round": round_index + 1, "stopped": True},
                )
                break
            self._trace_status(
                url,
                f"ReAct 第 {round_index + 1}/{self.max_rounds} 轮",
                "调用模型决定下一步动作。",
                {"phase": "react", "round": round_index + 1},
            )
            try:
                reply = self.client.chat(messages, tools)
            except Exception as exc:
                self._trace_error(url, f"模型调用失败: {exc}")
                raise

            content = str(reply.get("content") or "")
            thinking = str(reply.get("thinking") or "")
            tool_calls = reply.get("tool_calls") or []

            if thinking:
                self._trace_thought(url, "模型思考", thinking[:2000], "reasoning")
            if content:
                self._trace_thought(url, "Agent 决策", content[:2000], "react")

            # 把本轮 assistant 回复写回历史（含工具调用），供下一轮上下文衔接
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                no_tool_calls += 1
                if executor.records and (no_tool_calls >= self.MAX_NO_TOOL_NUDGES or hard_done):
                    # 已有证据且模型反复不动手，按收尾处理
                    executor.finish_summary = executor.finish_summary or content
                    break
                if no_tool_calls >= self.MAX_NO_TOOL_NUDGES:
                    break
                messages.append({
                    "role": "user",
                    "content": (
                        "你本轮没有调用任何工具。复测必须基于真实请求证据：请调用 http_request / "
                        "run_python_probe / run_preset_check 等工具继续取证；若确实已收集到足够证据，"
                        "请调用 finish_investigation 并给出总结，不要只用文字描述。"
                    ),
                })
                round_index += 1
                continue

            no_tool_calls = 0

            for call in tool_calls:
                name = str(call.get("name") or "")
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                call_id = str(call.get("id") or "")
                result_text = executor.execute(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text[:16000],
                })
                if executor.finished:
                    break

            # 反思/收敛提示注入
            current_round = round_index + 1
            if not executor.finished and current_round >= self.SOFT_REFLECTION_ROUND and not soft_done:
                soft_done = True
                messages.append({"role": "user", "content": self._soft_reflection(executor)})
            if not executor.finished and current_round >= self.HARD_PIVOT_ROUND and not hard_done:
                hard_done = True
                messages.append({"role": "user", "content": self._hard_pivot(executor)})

            round_index += 1

        if not executor.finished and round_index >= self.max_rounds:
            self._trace_status(
                url,
                "ReAct 轮数上限",
                f"已达 {self.max_rounds} 轮取证上限，进入最终判定。",
                {"phase": "react", "round": round_index},
            )

        summary = executor.finish_summary or "模型已结束取证。"
        self._trace_status(
            url,
            "ReAct 取证结束",
            f"{summary}\n共 {len(executor.records)} 条证据观察，调用工具 {len(executor.executed_tools)} 次。",
            {"phase": "react", "records": len(executor.records), "rounds": round_index},
        )

        return {
            "records": executor.records,
            "executed_tools": executor.executed_tools,
            "summary": summary,
            "rounds": round_index,
        }

    # ------------------------------------------------------------- prompt build

    def _system_prompt(self) -> str:
        try:
            return load_retest_prompt("react_system")
        except Exception as exc:
            logging.warning("加载 react_system 提示词失败，使用内置兜底: %s", exc)
            return self._fallback_system_prompt()

    def _initial_user_message(
        self,
        url: str,
        vuln_types: List[str],
        context: Dict[str, Any],
        probe_result: Dict[str, Any],
    ) -> str:
        safe_context = self._safe_context(context)
        payload = {
            "task": "对下面这个通报目标启动黑盒复测取证。先给复测计划，再用工具逐步验证，最后 finish_investigation 收尾。",
            "target_url": url,
            "reported_vulnerability_types": vuln_types or [],
            "issue_tags": context.get("issue_tags") or [],
            "report_text": str(context.get("raw_text") or "")[:60000],
            "retest_context": safe_context,
            "first_response": {
                "status_code": (probe_result.get("request_meta") or {}).get("status_code"),
                "final_url": (probe_result.get("request_meta") or {}).get("final_url"),
                "content_length": (probe_result.get("request_meta") or {}).get("content_length"),
                "response_headers_safe": probe_result.get("response_headers_safe") or {},
                "response_body_preview": str(probe_result.get("response_body_preview") or "")[:12000],
            },
            "scope_rule": "你只能请求通报目标的同源 URL（协议+主机+端口一致）。越界请求会被工具拒绝。",
            "evidence_rule": (
                "只有当你能在通报目标/路径/请求/证据特征与实际响应之间建立直接对应时，才算复现线索；"
                "顺带发现但无法对应原通报的问题，用 record_finding 记为旁路观察即可。"
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _safe_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        safe: Dict[str, Any] = {}
        for key in ("target_urls", "path_candidates", "expected_status_codes",
                    "expected_markers", "parameter_names"):
            values = context.get(key) or []
            if values:
                safe[key] = values[:40]
        safe["http_request_candidates"] = [
            {
                "method": item.get("method"),
                "url": item.get("url"),
                "has_body": bool(item.get("body")),
                "body_preview": str(item.get("body") or "")[:800],
            }
            for item in (context.get("http_request_candidates") or [])
            if isinstance(item, dict)
        ][:8]
        safe["payload_candidates"] = [
            {
                "parameter": item.get("parameter"),
                "url": item.get("url"),
                "raw_preview": str(item.get("raw") or "")[:600],
            }
            for item in (context.get("payload_candidates") or [])
            if isinstance(item, dict)
        ][:12]
        safe["credential_candidates"] = [
            {
                "username": item.get("username"),
                "password_masked": item.get("password_masked"),
                "password_available": bool(item.get("password")),
            }
            for item in (context.get("credential_candidates") or [])
            if isinstance(item, dict)
        ][:6]
        page = context.get("page_observations")
        if isinstance(page, dict) and page:
            safe["page_observations"] = {
                "url": page.get("url"),
                "frameworks": page.get("frameworks") or [],
                "forms": page.get("forms") or [],
                "candidate_endpoints": (page.get("candidate_endpoints") or [])[:20],
            }
        return safe

    def _soft_reflection(self, executor: RetestToolExecutor) -> str:
        return (
            "【进度自检】请快速回顾：(1) 通报漏洞是否已被验证为可复现或不可复现？"
            "(2) 还有哪个关键假设没验证？(3) 是否在重复相似请求而无新信息？"
            f"目前已记录 {len(executor.records)} 条证据。若已能下结论，请尽快用 record_finding 留痕并 "
            "finish_investigation；否则只做最关键的一步验证。"
        )

    def _hard_pivot(self, executor: RetestToolExecutor) -> str:
        return (
            "【收敛提示】取证轮数已较多。除非还差一步关键证据，否则请立即用 record_finding 固定结论性观察，"
            "并调用 finish_investigation 结束取证，不要再做探索性请求。"
        )

    def _fallback_system_prompt(self) -> str:
        return (
            "你是一个黑盒漏洞复测取证 Agent。给定一个通报目标和首包响应，你要通过真实工具调用验证"
            "通报漏洞当前是否仍可复现。\n\n"
            "工作方式（ReAct）：\n"
            "1. 第一轮先用简短文字给出复测计划：要验证什么、打算用哪些工具。\n"
            "2. 之后每轮调用一个或多个工具（http_request 自由构造请求是核心），观察返回再决定下一步。\n"
            "3. 只能请求通报目标同源 URL。\n"
            "4. 关键现象用 record_finding 记录（无论是否构成复现）。\n"
            "5. 证据足够后调用 finish_investigation 给出取证总结。\n\n"
            "纪律：不要凭空下结论，结论必须有请求/响应证据支撑；不要无意义地重复请求；"
            "顺带发现但无法对应原通报的问题只作旁路观察。最终复现判定由后续环节裁定，你只负责取证。"
        )

    # -------------------------------------------------------------- trace utils

    def _trace_status(self, url: str, title: str, content: str, metadata: Dict[str, Any]) -> None:
        try:
            self.scanner._trace_event("status", title, content, "info", metadata=metadata)
        except Exception:
            pass

    def _trace_thought(self, url: str, title: str, content: str, phase: str) -> None:
        try:
            self.scanner._trace_event(
                "thought_summary", title, content, "info",
                metadata={"phase": phase, "target": url},
            )
        except Exception:
            pass

    def _trace_error(self, url: str, message: str) -> None:
        try:
            self.scanner._trace_event(
                "tool_result", "ReAct 取证", message, "error",
                {"toolId": "react_loop", "label": "ReAct 取证", "status": "failed",
                 "target": url, "resultPreview": message, "failureReason": message},
                metadata={"phase": "react"},
            )
        except Exception:
            pass
