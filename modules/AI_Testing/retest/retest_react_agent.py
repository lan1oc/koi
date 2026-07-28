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

    _INVESTIGATION_TOOLS = {
        "http_request", "collect_page_context", "run_python_probe",
        "run_nmap", "run_sqlmap", "run_ffuf", "run_preset_check",
    }

    DEFAULT_MAX_ROUNDS = 16
    SOFT_REFLECTION_ROUND = 5       # 软反思：尽早检查证据是否已经充分
    HARD_PIVOT_ROUND = 10           # 硬提示：停止探索并尽快收敛
    MAX_NO_TOOL_NUDGES = 3          # 连续不调用工具的最大容忍次数
    MAX_MODEL_CALL_SECONDS = 60     # 单轮模型调用预算，避免一轮占满整段复测时间
    MAX_REPAIR_CALL_SECONDS = 45
    FINALIZATION_RESERVE_SECONDS = 8
    DEFAULT_MAX_SECONDS = 300       # 兜底而非正常结束路径；阳性证据应触发自动早停
    # 单轮 tool 结果全文保留的最近轮数；更早的会被折叠成摘要（与会话层同口径）。
    RECENT_TOOL_FULLTEXT = 3
    # 估算：1 token ≈ 3 字符（中英混合粗估，偏保守）。
    CHARS_PER_TOKEN = 3

    def __init__(self, ai_config: Dict[str, Any], scanner: Any):
        self.ai_config = dict(ai_config or {})
        self.scanner = scanner
        self.client = RetestLLMClient(self.ai_config)
        try:
            self.max_rounds = int(self.ai_config.get("react_max_rounds") or self.DEFAULT_MAX_ROUNDS)
        except Exception:
            self.max_rounds = self.DEFAULT_MAX_ROUNDS
        self.max_rounds = max(4, min(self.max_rounds, 40))
        try:
            self.max_seconds = int(self.ai_config.get("react_max_seconds") or self.DEFAULT_MAX_SECONDS)
        except Exception:
            self.max_seconds = self.DEFAULT_MAX_SECONDS
        self.max_seconds = max(60, min(self.max_seconds, 900))

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
        started = time.monotonic()
        timed_out = False
        repair_model_failures = 0

        self._trace_status(
            url,
            "ReAct 取证开始",
            "模型将基于通报与首包响应，自主构造请求、运行探针并记录证据，直到调用 finish_investigation 或达到轮数上限。",
            {"phase": "react", "maxRounds": self.max_rounds, "maxSeconds": self.max_seconds},
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
            if time.monotonic() - started > self.max_seconds:
                timed_out = True
                self._trace_status(
                    url,
                    "ReAct 取证超时",
                    f"取证已超过 {self.max_seconds} 秒兜底时限，停止继续取证并用已有证据进入最终判定。",
                    {"phase": "react", "round": round_index + 1, "timedOut": True},
                )
                break
            self._trace_status(
                url,
                f"ReAct 第 {round_index + 1}/{self.max_rounds} 轮",
                "调用模型决定下一步动作。",
                {"phase": "react", "round": round_index + 1},
            )
            remaining_seconds = self.max_seconds - (time.monotonic() - started)
            if remaining_seconds <= self.FINALIZATION_RESERVE_SECONDS:
                timed_out = True
                self._trace_status(
                    url,
                    "ReAct 预算不足",
                    "剩余时间不足以安全完成下一次模型调用，停止继续取证并进入最终判定。",
                    {"phase": "react", "round": round_index + 1, "timedOut": True},
                )
                break
            call_budget = min(
                self.MAX_REPAIR_CALL_SECONDS if executor.requires_probe_repair else self.MAX_MODEL_CALL_SECONDS,
                max(1.0, remaining_seconds - self.FINALIZATION_RESERVE_SECONDS),
            )
            previous_read_timeout = getattr(self.client, "read_timeout", None)
            previous_max_retries = getattr(self.client, "max_retries", None)
            try:
                if previous_read_timeout is not None:
                    self.client.read_timeout = min(int(previous_read_timeout), max(5, int(call_budget)))
                if previous_max_retries is not None:
                    self.client.max_retries = 0
                set_deadline = getattr(self.client, "set_request_deadline", None)
                if callable(set_deadline):
                    set_deadline(call_budget)
                reply = self.client.chat(self._fit_messages(messages), tools)
                repair_model_failures = 0
            except Exception as exc:
                self._trace_error(url, f"模型调用失败: {exc}")
                if executor.requires_probe_repair:
                    repair_model_failures += 1
                    if repair_model_failures <= 1 and (self.max_seconds - (time.monotonic() - started)) > self.FINALIZATION_RESERVE_SECONDS + 10:
                        messages.append({
                            "role": "user",
                            "content": (
                                "脚本修复所需的模型调用失败或超时。请立即根据上一条 Python 探针错误重写不同脚本，"
                                "只调用 run_python_probe，不要解释也不要切换其它工具。"
                            ),
                        })
                        round_index += 1
                        continue
                    executor.finished = True
                    executor.requires_probe_repair = False
                    executor.finish_summary = (
                        "Python 探针失败后，脚本修复模型调用也未在预算内完成；当前无法验证，不能据此判定已修复。"
                    )
                    break
                raise
            finally:
                clear_deadline = getattr(self.client, "clear_request_deadline", None)
                if callable(clear_deadline):
                    clear_deadline()
                if previous_read_timeout is not None:
                    self.client.read_timeout = previous_read_timeout
                if previous_max_retries is not None:
                    self.client.max_retries = previous_max_retries

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
                if executor.requires_probe_repair:
                    if no_tool_calls >= self.MAX_NO_TOOL_NUDGES:
                        executor.finished = True
                        executor.requires_probe_repair = False
                        executor.finish_summary = "脚本失败后模型未能完成修复调用，当前无法验证，不能据此判定已修复。"
                        break
                    messages.append({"role": "user", "content": executor.probe_repair_instruction()})
                    round_index += 1
                    continue
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

            investigation_tool_used = False
            for call in tool_calls:
                name = str(call.get("name") or "")
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                call_id = str(call.get("id") or "")
                if name in self._INVESTIGATION_TOOLS and investigation_tool_used:
                    result_text = (
                        "本轮已执行一个取证工具，后续探索工具已跳过。请先观察当前真实响应；"
                        "若证据已直接对应原通报，立即 record_finding 并 finish_investigation，"
                        "否则下一轮只补做一个最关键的验证。"
                    )
                else:
                    result_text = self._argument_parse_error(name, args) or executor.execute(name, args)
                    if name in self._INVESTIGATION_TOOLS and not result_text.startswith("工具调用被复测策略拒绝"):
                        investigation_tool_used = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text[:16000],
                })
                if executor.auto_finished:
                    self._trace_status(
                        url,
                        "阳性证据已充分",
                        "现有请求/响应证据已直接证明原通报漏洞可复现；按最小充分取证原则停止调用其它工具。",
                        {"phase": "react", "round": round_index + 1, "earlyStop": True, "reason": "decisive_reproduction"},
                    )
                if executor.finished:
                    break

            if executor.requires_probe_repair and not executor.finished:
                messages.append({"role": "user", "content": executor.probe_repair_instruction()})

            # 反思/收敛提示注入
            current_round = round_index + 1
            if not executor.finished and current_round >= self.SOFT_REFLECTION_ROUND and not soft_done:
                soft_done = True
                messages.append({"role": "user", "content": self._soft_reflection(executor)})
            if not executor.finished and current_round >= self.HARD_PIVOT_ROUND and not hard_done:
                hard_done = True
                messages.append({"role": "user", "content": self._hard_pivot(executor)})

            round_index += 1

        if not executor.finished and timed_out:
            self._trace_status(
                url,
                "ReAct 超时收尾",
                f"取证已达 {self.max_seconds} 秒兜底时限，用已有证据进入最终判定。",
                {"phase": "react", "round": round_index, "timedOut": True},
            )
        elif not executor.finished and round_index >= self.max_rounds:
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
            "decisive_reproduction": executor.has_decisive_reproduction_evidence(),
            "decisive_evidence": next(
                (
                    dict(item)
                    for item in executor.records
                    if isinstance(item, dict) and executor._is_decisive_reproduction_record(item)
                ),
                {},
            ),
        }

    def _argument_parse_error(self, name: str, args: Dict[str, Any]) -> str:
        if not isinstance(args, dict) or not args.get("__parse_error__"):
            return ""
        raw = str(args.get("__raw_arguments__") or "")[:1200]
        return (
            f"工具 {name or '(未命名)'} 的参数不是合法 JSON 对象，工具没有执行。\n"
            f"解析问题: {args.get('__parse_error__')}\n"
            f"原始参数片段:\n{raw}\n"
            "请重新调用工具，并输出严格合法 JSON 参数；URL、payload、Windows 路径里的反斜杠必须正确转义。"
        )

    # ----------------------------------------------------------- context fit

    def _context_budget_chars(self) -> int:
        """可用于历史消息的字符预算 = (上下文窗口 - 输出预留 - 余量) * 每token字符数。"""
        try:
            window = int(getattr(self.client, "context_window", 0) or 128000)
        except Exception:
            window = 128000
        try:
            reserve = int(getattr(self.client, "max_tokens", 0) or 1600)
        except Exception:
            reserve = 1600
        headroom = 2000  # system + tool specs + 安全余量（token）
        usable_tokens = max(4000, window - reserve - headroom)
        return usable_tokens * self.CHARS_PER_TOKEN

    @staticmethod
    def _msg_chars(msg: Dict[str, Any]) -> int:
        size = len(str(msg.get("content") or ""))
        for call in msg.get("tool_calls") or []:
            size += len(str(call.get("name") or "")) + len(json.dumps(call.get("arguments") or {}, ensure_ascii=False))
        return size

    def _fit_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分层留存 + 滚动，保证每次 client.chat() 前消息体不超预算（与会话层同口径）。

        关键不变量：绝不破坏 assistant.tool_calls 与后续 tool 消息的配对，
        不产生 orphan tool_call（否则 OpenAI/Anthropic 会直接报错）。

        两级杠杆：
        1) 主杠杆（无副作用）：把"较早"的 tool 结果正文折叠成摘要，保留消息体
           与 tool_call_id，配对关系不变。
        2) 次杠杆：仍超预算时，从最前面按 user 消息边界整轮丢弃（在 user 边界切，
           不会拆散 tool_call/tool_result 对），system(0) 与首条 user 任务始终保留。
        """
        if not messages:
            return messages
        budget = self._context_budget_chars()
        work = [dict(m) for m in messages]

        # --- 主杠杆：折叠较早的 tool 结果正文 ---
        tool_positions = [i for i, m in enumerate(work) if str(m.get("role")) == "tool"]
        if len(tool_positions) > self.RECENT_TOOL_FULLTEXT:
            keep_full = set(tool_positions[-self.RECENT_TOOL_FULLTEXT:])
            for i in tool_positions:
                if i in keep_full:
                    continue
                content = str(work[i].get("content") or "")
                if len(content) > 600:
                    work[i] = {
                        **work[i],
                        "content": content[:500] + f"\n…[早期工具结果已折叠，原长 {len(content)} 字]",
                    }

        total = sum(self._msg_chars(m) for m in work)
        if total <= budget:
            return work

        # --- 次杠杆：从头按 user 边界整轮丢弃 ---
        # work[0]=system、work[1]=首条 user 任务（含通报上下文），二者始终保留；
        # 只在之后的 user 边界上切割，避免拆散 tool_call/tool_result 对。
        user_starts = [i for i, m in enumerate(work) if str(m.get("role")) == "user"]
        cut_candidates = [i for i in user_starts if i >= 2][:-1] if len(user_starts) > 2 else []
        cut_at = 0
        for boundary in cut_candidates:
            head_chars = sum(self._msg_chars(work[j]) for j in range(2, boundary))
            if total - head_chars <= budget:
                cut_at = boundary
                break
            cut_at = boundary
        if cut_at > 2:
            dropped = cut_at - 2
            note = {
                "role": "user",
                "content": f"[系统提示] 此前 {dropped} 条更早的取证记录因长度限制已省略，"
                           "请基于下面保留的最近上下文继续，必要时重新取证确认。",
            }
            work = work[:2] + [note] + work[cut_at:]
        return work

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
