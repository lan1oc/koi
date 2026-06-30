#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""会话级 ReAct Agent。

把复测会话入口（用户在对话框打字）从"关键词路由器"升级为真正的对话式
ReAct agent：用户的自然语言先经过 client.chat() 理解，模型自己决定调用哪个
会话级工具——列通报、复测某份通报、对用户指定的 URL 现场取证、生成报告、
下载/查看外部工具，或直接回答。

本模块只负责"会话编排循环"：构造消息历史、驱动模型、分发工具调用。所有真正
的副作用（跑流水线、改会话状态、推 WebSocket 事件）都通过 runner 暴露的一组
适配方法完成——session agent 不直接碰 runner 内部状态，保证事件与状态仍由
runner 在锁内统一管理。

工具分两类：
- 会话编排工具：list_reports / retest_report / generate_reports /
  install_tools / tool_status
- 现场取证工具：retest_url —— 对用户在对话里给出的同源 URL 直接启动取证
  （底层复用 scan_url_for_context 的 ReAct 取证引擎）

每份通报的最终 reproduced / not_reproduced 仍由既有 _run_retest_for_source_file
内的 judge 模型裁定；本层不改判定逻辑。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from modules.AI_Testing.retest.retest_ai_agent import RetestLLMClient, load_retest_prompt


class RetestSessionAgent:
    """围绕 RetestLLMClient.chat 的会话级 ReAct 主循环。

    通过 runner adapter 执行副作用，自身只做"理解意图 → 选工具 → 观察 → 回复"。
    """

    DEFAULT_MAX_ROUNDS = 20
    MAX_NO_TOOL_NUDGES = 2
    AUTO_CONTINUE_CUES = (
        "继续",
        "恢复",
        "从断点",
        "一键复测",
        "全部复测",
        "批量复测",
        "都测",
        "都复测",
        "剩余",
        "未完成",
    )

    def _runner_stopped(self, turn_id: str = "") -> bool:
        try:
            lock = getattr(self.runner, "lock", None)
            if lock is None:
                turn_current = True
                if turn_id and hasattr(self.runner, "_turn_is_current"):
                    turn_current = bool(self.runner._turn_is_current(turn_id))
                return bool(getattr(self.runner, "stopped", False)) or not turn_current
            with lock:
                turn_current = True
                if turn_id and hasattr(self.runner, "_is_turn_current_locked"):
                    turn_current = bool(self.runner._is_turn_current_locked(turn_id))
                return bool(getattr(self.runner, "stopped", False)) or not turn_current
        except Exception:
            return False

    def _stop_reply(self, turn_id: str) -> str:
        final_reply = "已停止当前 Agent 执行，未继续处理后续工具。"
        try:
            self.runner._publish(
                "status", "Agent 已停止", final_reply, "warn",
                metadata={"turnId": turn_id, "role": "agent", "phase": "stop"},
            )
        except Exception:
            pass
        return final_reply

    def __init__(self, runner: Any, ai_config: Dict[str, Any]):
        self.runner = runner
        self.ai_config = dict(ai_config or {})
        self.client = RetestLLMClient(self.ai_config)
        try:
            self.max_rounds = int(self.ai_config.get("session_max_rounds") or self.DEFAULT_MAX_ROUNDS)
        except Exception:
            self.max_rounds = self.DEFAULT_MAX_ROUNDS
        self.max_rounds = max(4, min(self.max_rounds, 40))

    # ------------------------------------------------------------------ public

    def run_turn(
        self,
        message: str,
        turn_id: str,
        prior_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """处理一条用户消息。

        返回 (final_reply, persisted_messages)：
        - final_reply：这一轮对话的收尾回复（也已 publish 过）。
        - persisted_messages：本轮结束后的完整 ReAct 消息历史（不含 system，含
          user/assistant/tool 及 tool_calls 结构），由 runner 持久化、下一轮回传，
          实现跨轮记忆——对话框记得"上一轮发过什么请求、拿到什么响应、调过什么工具"。

        过程中的工具调用与中间叙述通过 runner._publish 推送到事件流。
        """
        if not self.client.is_ready():
            raise RuntimeError("AI Agent 未配置 provider/api_key/model")

        tools = self._tool_specs()
        system_prompt = self._system_prompt()
        # 完整保留上一轮的消息结构（含 tool_calls / tool_call_id），不再压成纯文本。
        prior = [dict(m) for m in (prior_messages or []) if isinstance(m, dict)]
        prior.append({"role": "user", "content": self._initial_user_message(message)})

        no_tool_calls = 0
        final_reply = ""
        round_index = 0

        while round_index < self.max_rounds:
            if self._runner_stopped(turn_id):
                return self._stop_reply(turn_id), prior
            messages = self._fit_context(system_prompt, prior)
            # 每轮装两路增量回调，按模型真实输出链路推送：
            #   reasoning_callback：reasoning_content 先于 content 到达 → 先推「模型思考」流式块
            #   stream_callback   ：content 到达 → 后推「Agent 正在回复」流式块
            # 两者各用独立 streamKey，前端按 streamKey 原地升级去重；事件进入顺序即真实链路。
            stream_key = self._stream_key(turn_id, round_index)
            self.client.stream_callback = self._make_stream_callback(turn_id, round_index)
            self.client.reasoning_callback = self._make_reasoning_callback(turn_id, round_index)
            try:
                reply = self.client.chat(messages, tools)
            except Exception as exc:
                self.client.stream_callback = None
                self.client.reasoning_callback = None
                raise
            finally:
                self.client.stream_callback = None
                self.client.reasoning_callback = None

            content = str(reply.get("content") or "")
            thinking = str(reply.get("thinking") or "")
            tool_calls = reply.get("tool_calls") or []

            if thinking:
                # 收尾：把本轮流式「模型思考」原地升级成完整思考（complete 标记），
                # 复用同一 reasoning streamKey，避免和流式块重复成两条。
                self.runner._publish(
                    "thought_summary", "模型思考", thinking[:2000], "info",
                    metadata={
                        "turnId": turn_id, "phase": "session_reasoning", "role": "agent",
                        "modelOutput": True, "completeModelOutput": True,
                        "streamKey": self._reason_key(turn_id, round_index),
                    },
                )

            # 把模型这一轮的产出写回持久化历史 prior（不是每轮重建的 messages），
            # 这样 tool_calls 结构能跨轮保留，下一轮模型记得自己调过什么。
            prior.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                # 没有工具调用 = 模型在直接回话。把它当作本轮收尾回复。
                final_reply = content.strip()
                if final_reply:
                    # 用与本轮流式预览相同的 streamKey，把前端那条 "Agent 正在回复"
                    # 原地升级成权威收尾，避免预览和最终回复重复两条。
                    self.runner._publish(
                        "chat", "Agent", final_reply[:6000], "ok",
                        metadata={
                            "turnId": turn_id, "role": "agent", "phase": "session_react",
                            "completeModelOutput": True, "modelOutput": True, "streamKey": stream_key,
                        },
                    )
                    break
                no_tool_calls += 1
                if no_tool_calls >= self.MAX_NO_TOOL_NUDGES:
                    final_reply = "我已处理完你的指令。"
                    self.runner._publish(
                        "chat", "Agent", final_reply, "ok",
                        metadata={"turnId": turn_id, "role": "agent", "phase": "session_react"},
                    )
                    break
                prior.append({
                    "role": "user",
                    "content": "请直接用一句话回复用户你已经做了什么或下一步建议；若还需要执行动作，请调用相应工具。",
                })
                round_index += 1
                continue

            no_tool_calls = 0
            # 模型在调工具前可能附带一句说明，转给用户看。同样复用本轮 streamKey，
            # 把流式预览原地升级成这句权威说明，避免重复。
            if content.strip():
                self.runner._publish(
                    "chat", "Agent", content.strip()[:4000], "info",
                    metadata={
                        "turnId": turn_id, "role": "agent", "phase": "session_react",
                        "modelOutput": True, "streamKey": stream_key,
                    },
                )

            for call in tool_calls:
                if self._runner_stopped(turn_id):
                    return self._stop_reply(turn_id), prior
                name = str(call.get("name") or "")
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                call_id = str(call.get("id") or "")
                result_text = self._argument_parse_error(name, args) or self._dispatch(name, args, turn_id)
                prior.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text[:16000],
                })
                if self._runner_stopped(turn_id):
                    return self._stop_reply(turn_id), prior

            round_index += 1

        if not final_reply:
            auto_reply = self._auto_continue_reports_if_needed(message, turn_id)
            if auto_reply:
                prior.append({"role": "assistant", "content": auto_reply})
                return auto_reply, prior
            final_reply = "我已处理完当前这一轮，可以继续告诉我下一步。"
            self.runner._publish(
                "chat", "Agent", final_reply, "ok",
                metadata={"turnId": turn_id, "role": "agent", "phase": "session_react"},
            )
        return final_reply, prior

    def _argument_parse_error(self, name: str, args: Dict[str, Any]) -> str:
        if not isinstance(args, dict) or not args.get("__parse_error__"):
            return ""
        raw = str(args.get("__raw_arguments__") or "")[:1200]
        return (
            f"工具 {name or '(未命名)'} 的参数不是合法 JSON 对象，工具没有执行。\n"
            f"解析问题: {args.get('__parse_error__')}\n"
            f"原始参数片段:\n{raw}\n"
            "请在下一轮重新调用同一个或更合适的工具，并把参数改成严格合法 JSON；"
            "Windows 路径里的反斜杠必须写成 \\\\，或者直接使用文件名/正斜杠路径。"
        )

    def _report_queue_state(self) -> Dict[str, Any]:
        try:
            state = self.runner.tool_session_state() or {}
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    def _state_int(self, state: Dict[str, Any], key: str, default: int = 0) -> int:
        try:
            return int(state.get(key))
        except Exception:
            return default

    def _message_requests_continuous_retest(self, message: str) -> bool:
        text = str(message or "").lower()
        if any(word in text for word in ("不要继续", "先别继续", "暂停", "停止")):
            return False
        if any(word in f" {text} " for word in (" stop ", " abort ", " cancel ")):
            return False
        return any(cue.lower() in text for cue in self.AUTO_CONTINUE_CUES)

    def _message_requests_report_output(self, message: str) -> bool:
        text = str(message or "")
        return any(word in text for word in ("生成报告", "写报告", "出报告", "导出报告"))

    def _should_auto_continue_reports(self, message: str) -> bool:
        if not self._message_requests_continuous_retest(message):
            return False
        state = self._report_queue_state()
        if not bool(state.get("has_target_dir")):
            return False
        total = self._state_int(state, "total_reports", 0)
        next_index = self._state_int(state, "next_index", 0)
        # total=0 可能只是还没重新扫描目录；retest_all_reports 会先列目录并恢复断点。
        return total <= 0 or next_index < total

    def _auto_continue_reports_if_needed(self, message: str, turn_id: str) -> str:
        if not self._should_auto_continue_reports(message):
            return ""
        before = self._report_queue_state()
        total = self._state_int(before, "total_reports", 0)
        next_index = self._state_int(before, "next_index", 0)
        remaining = max(0, total - next_index) if total > 0 else 0
        generate_reports = bool(before.get("generate_reports_default")) or self._message_requests_report_output(message)
        self.runner._publish(
            "status",
            "自动继续复测",
            (
                f"模型对话轮数已到上限，但当前队列还有 {remaining} 份未完成通报，"
                "我会自动压缩上下文并从断点继续，不需要你手动再次点击。"
                if total > 0
                else "模型对话轮数已到上限，我会重新读取通报清单并根据断点继续，不需要你手动再次点击。"
            ),
            "info",
            metadata={"turnId": turn_id, "role": "agent", "phase": "auto_continue"},
        )
        result_text = self.runner.tool_retest_all_reports(generate_reports=generate_reports, turn_id=turn_id)
        after = self._report_queue_state()
        after_total = self._state_int(after, "total_reports", total)
        after_next = self._state_int(after, "next_index", next_index)
        if after_total > 0 and after_next >= after_total:
            final_reply = "已自动继续并完成剩余通报复测。"
        else:
            final_reply = f"已自动继续处理，当前断点 {after_next}/{after_total or '未知'}。"
        if result_text:
            final_reply = f"{final_reply}\n{str(result_text)[:4000]}"
        self.runner._publish(
            "chat", "Agent", final_reply[:6000], "ok",
            metadata={"turnId": turn_id, "role": "agent", "phase": "auto_continue"},
        )
        return final_reply

    # --------------------------------------------------------- stream callback

    # 流式节流：与 make_model_stream_callback 同口径（0.25s 或 120 字才推一次）。
    STREAM_MIN_INTERVAL = 0.25
    STREAM_MIN_CHARS = 120

    def _stream_key(self, turn_id: str, round_index: int) -> str:
        """本轮可见正文的唯一键：流式预览与收尾 chat 共用，前端据此原地升级去重。"""
        return f"session-stream:{turn_id}:{round_index}"

    def _reason_key(self, turn_id: str, round_index: int) -> str:
        """本轮模型思考的唯一键：流式思考块与完整思考共用，前端据此原地升级去重。"""
        return f"session-reason:{turn_id}:{round_index}"

    def _make_reasoning_callback(self, turn_id: str, round_index: int) -> Callable[[str], None]:
        """模型 reasoning_content 增量回调：边推理边推「模型思考」流式块。

        reasoning 在模型流里先于 content 到达，实时推送即可让思考事件按真实链路
        排在正文之前——不再靠攒到最后补发、也不靠前端二次重排。节流口径同正文回调。
        """
        import time as _time

        state = {"buffer": "", "last_emit": 0.0, "last_len": 0}
        reason_key = self._reason_key(turn_id, round_index)

        def callback(chunk: str) -> None:
            text = str(chunk or "")
            if not text:
                return
            state["buffer"] = (state["buffer"] + text)[-8000:]
            now = _time.time()
            grown = len(state["buffer"]) - int(state["last_len"])
            if now - float(state["last_emit"]) < self.STREAM_MIN_INTERVAL and grown < self.STREAM_MIN_CHARS:
                return
            preview = state["buffer"].strip()
            if not preview:
                return
            state["last_emit"] = now
            state["last_len"] = len(state["buffer"])
            try:
                self.runner._publish(
                    "thought_summary", "模型思考", preview[:2000], "info",
                    metadata={
                        "turnId": turn_id, "phase": "session_reasoning", "role": "agent",
                        "streaming": True, "modelOutput": True, "streamKey": reason_key,
                    },
                )
            except Exception:
                pass

        return callback

    def _make_stream_callback(self, turn_id: str, round_index: int) -> Callable[[str], None]:
        """构造一个按 turn+round 去重、带节流的增量回调。

        模型边生成边把可见正文推成 streaming 的 thought_summary 事件；前端按
        streamKey 聚合/去重，本轮真正的收尾 chat 事件才是权威输出。结构化数据
        （以 { 开头）不直接展示，避免把 JSON 噪声推给用户。
        """
        import time as _time

        state = {"buffer": "", "last_emit": 0.0, "last_len": 0}
        stream_key = self._stream_key(turn_id, round_index)

        def _visible(raw: str) -> str:
            text = str(raw or "")
            if text.lstrip().startswith("{"):
                return ""
            return text.strip()

        def callback(chunk: str) -> None:
            text = str(chunk or "")
            if not text:
                return
            state["buffer"] = (state["buffer"] + text)[-8000:]
            now = _time.time()
            grown = len(state["buffer"]) - int(state["last_len"])
            if now - float(state["last_emit"]) < self.STREAM_MIN_INTERVAL and grown < self.STREAM_MIN_CHARS:
                return
            preview = _visible(state["buffer"])
            if not preview:
                return
            state["last_emit"] = now
            state["last_len"] = len(state["buffer"])
            try:
                self.runner._publish(
                    "thought_summary", "Agent 正在回复", preview[:4000], "info",
                    metadata={
                        "turnId": turn_id, "role": "agent", "phase": "session_react",
                        "streaming": True, "modelOutput": True, "streamKey": stream_key,
                    },
                )
            except Exception:
                pass

        return callback

    # ----------------------------------------------------------- context fit

    # 单轮 tool 结果全文保留的最近轮数；更早的 tool 结果会被截断成摘要。
    RECENT_TOOL_FULLTEXT = 3
    # 估算：1 token ≈ 3 字符（中英混合粗估，偏保守）。
    CHARS_PER_TOKEN = 3

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

    def _fit_context(self, system_prompt: str, prior: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分层留存 + 滚动，保证每次 client.chat() 前消息体不超预算。

        关键不变量：绝不破坏 assistant.tool_calls 与后续 tool 消息的配对，
        不产生 orphan tool_call（否则 OpenAI/Anthropic 会直接报错）。

        两级杠杆：
        1) 主杠杆（无副作用）：把"较早"的 tool 结果正文截断成摘要，保留消息体
           与 tool_call_id，配对关系不变。
        2) 次杠杆：仍超预算时，从最前面按 user 消息边界整轮丢弃（在 user 边界切，
           不会拆散 tool_call/tool_result 对），并在头部塞一条文字摘要。
        """
        budget = self._context_budget_chars()
        # 深拷贝，避免改到要持久化的原始 prior
        work = [dict(m) for m in prior]

        # --- 主杠杆：截断较早的 tool 结果正文 ---
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

        total = sum(self._msg_chars(m) for m in work) + len(system_prompt)
        if total <= budget:
            return [{"role": "system", "content": system_prompt}] + work

        # --- 次杠杆：从头按 user 边界整轮丢弃 ---
        dropped = 0
        # 找到每个 user 消息的起始位置作为可切割边界
        user_starts = [i for i, m in enumerate(work) if str(m.get("role")) == "user"]
        # 永远保留最后一个 user（本轮新消息）及其之后的内容
        cut_candidates = user_starts[:-1] if len(user_starts) > 1 else []
        cut_at = 0
        for boundary in cut_candidates:
            head_chars = sum(self._msg_chars(work[j]) for j in range(boundary))
            if total - head_chars + len(system_prompt) <= budget:
                cut_at = boundary
                break
            cut_at = boundary
        if cut_at > 0:
            dropped = cut_at
            work = work[cut_at:]
            total = sum(self._msg_chars(m) for m in work) + len(system_prompt)

        head_msgs: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if dropped > 0:
            head_msgs.append({
                "role": "user",
                "content": f"[系统提示] 此前 {dropped} 条更早的对话/取证记录因长度限制已省略，"
                           "如需引用请基于下面保留的最近上下文继续。",
            })
        return head_msgs + work

    # ------------------------------------------------------------- tool specs

    def _tool_specs(self) -> List[Dict[str, Any]]:
        specs = [
            {
                "name": "inspect_session_state",
                "description": (
                    "读取当前会话状态，供模型理解用户话语后再决定动作。返回 workspaceRoot（工程/沙箱根）、"
                    "targetDir（通报目录）、队列进度、前端断点证据、磁盘旧报告证据和默认报告意图。"
                    "当用户问状态、问为什么审批/沙箱拒绝、或你需要判断继续还是重做时先调用。"
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "list_reports",
                "description": (
                    "扫描当前会话的通报目录，列出可复测的通报文档（Word 报告）。"
                    "这是观察工具；use_progress_evidence=false 时只列原始队列，不把前端断点或磁盘旧报告当成已完成。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "use_progress_evidence": {"type": "boolean", "description": "是否用前端断点/磁盘旧报告作为完成进度。继续时 true，重做时 false。"},
                    },
                },
            },
            {
                "name": "run_retest_queue",
                "description": (
                    "执行固定复测流水线：扫描通报、逐份读取、取证、二元判定，并按需要生成报告。"
                    "模型根据用户自然话语决定 use_progress_evidence：继续/恢复未完成工作时为 true；重新做一轮时为 false。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "generate_reports": {"type": "boolean", "description": "是否在每份复测后生成 Word 报告。"},
                        "use_progress_evidence": {"type": "boolean", "description": "是否用旧进度/旧报告跳过已完成项。true=续跑，false=重新完整跑。"},
                    },
                },
            },
            {
                "name": "retest_report",
                "description": (
                    "对一份通报文档执行完整复测流水线：读取通报 → 自主取证（构造请求/探针/外部工具）"
                    " → 模型给出 reproduced/not_reproduced 二元结论。这是复测通报漏洞的核心动作。"
                    "用 file_index（从 list_reports 的序号，从 1 开始）或 file_name 指定；不指定则复测下一份未完成的通报。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_index": {"type": "integer", "description": "通报序号（从 1 开始），对应 list_reports 的清单"},
                        "file_name": {"type": "string", "description": "通报文件名（含扩展名），与 file_index 二选一"},
                        "generate_report": {"type": "boolean", "description": "复测后是否立即生成复测报告，默认 false"},
                        "use_progress_evidence": {"type": "boolean", "description": "是否允许旧进度/旧报告让该通报被跳过；重测已完成通报时传 false。"},
                    },
                },
            },
            {
                "name": "retest_all_reports",
                "description": (
                    "兼容旧工具名，语义等同 run_retest_queue；新规划优先调用 run_retest_queue。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "generate_reports": {"type": "boolean", "description": "每份复测后是否生成报告，默认 false"},
                        "use_progress_evidence": {"type": "boolean", "description": "是否用旧进度/旧报告跳过已完成项。true=续跑，false=重新完整跑。"},
                    },
                },
            },
            {
                "name": "retest_url",
                "description": (
                    "对用户在对话中直接给出的某个 URL 现场取证（无需通报文档）。"
                    "用于『帮我看看这个接口有没有越权』『测一下这个登录框弱口令』这类即时请求。"
                    "底层启动黑盒取证引擎，自由构造 HTTP 请求/探针，仅限该 URL 同源范围。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要现场取证的目标 URL（http/https）"},
                        "vulnerability_types": {
                            "type": "array", "items": {"type": "string"},
                            "description": "用户关注的漏洞类型，如 ['SQL注入','越权']（可选）",
                        },
                        "note": {"type": "string", "description": "用户的具体诉求/已知线索，转给取证引擎（可选）"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "generate_reports",
                "description": (
                    "为本会话已完成复测的通报生成复测报告（Word）。"
                    "只有用户明确要『生成报告/写报告/出报告/导出报告』时才调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string", "description": "只为某一份通报生成报告时填其文件名；缺省为所有已完成的通报生成"},
                    },
                },
            },
            {
                "name": "delete_reports",
                "description": "删除当前 targetDir 下已生成的旧复测 Word 报告。只有用户明确表达删除/清理旧报告时才调用。",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "install_tools",
                "description": "下载并配置外部渗透工具（nmap/sqlmap/ffuf）到项目工具目录。用户要求安装/下载工具时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tools": {
                            "type": "array", "items": {"type": "string", "enum": ["nmap", "sqlmap", "ffuf"]},
                            "description": "要安装的工具，缺省安装全部三个",
                        },
                    },
                },
            },
            {
                "name": "tool_status",
                "description": "查看外部工具（nmap/sqlmap/ffuf）当前是否已安装/可用。",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
        try:
            from modules.AI_Testing.hybrid_agent_runtime import HybridWorkspaceTools

            runtime_factory = getattr(self.runner, "_agent_runtime", None)
            if callable(runtime_factory):
                specs.extend(HybridWorkspaceTools(runtime_factory()).tool_specs())
        except Exception:
            pass
        return specs

    # --------------------------------------------------------------- dispatch

    def _dispatch(self, name: str, args: Dict[str, Any], turn_id: str) -> str:
        try:
            if self._runner_stopped(turn_id):
                return "会话已停止，未执行新的工具调用。"
            try:
                from modules.AI_Testing.hybrid_agent_runtime import HybridWorkspaceTools

                if name in HybridWorkspaceTools.READ_TOOL_NAMES or name in HybridWorkspaceTools.MUTATING_TOOL_NAMES:
                    runtime_factory = getattr(self.runner, "_agent_runtime", None)
                    if not callable(runtime_factory):
                        return f"工程工具 {name} 当前不可用：runner 未提供 Agent Runtime。"
                    return HybridWorkspaceTools(runtime_factory()).execute(name, args)
            except Exception as exc:
                return f"工程工具 {name} 执行失败: {exc}"
            if name == "inspect_session_state":
                return self.runner.tool_inspect_session_state(turn_id)
            if name == "list_reports":
                return self.runner.tool_list_reports(
                    turn_id,
                    use_progress_evidence=bool(args.get("use_progress_evidence", True)),
                )
            if name == "run_retest_queue":
                return self.runner.tool_run_retest_queue(
                    generate_reports=bool(args.get("generate_reports")),
                    use_progress_evidence=bool(args.get("use_progress_evidence", True)),
                    turn_id=turn_id,
                )
            if name == "retest_report":
                return self.runner.tool_retest_report(
                    file_index=args.get("file_index"),
                    file_name=args.get("file_name"),
                    generate_report=bool(args.get("generate_report")),
                    use_progress_evidence=bool(args.get("use_progress_evidence", True)),
                    turn_id=turn_id,
                )
            if name == "retest_all_reports":
                return self.runner.tool_retest_all_reports(
                    generate_reports=bool(args.get("generate_reports")),
                    use_progress_evidence=bool(args.get("use_progress_evidence", True)),
                    turn_id=turn_id,
                )
            if name == "retest_url":
                return self.runner.tool_retest_url(
                    url=str(args.get("url") or ""),
                    vuln_types=[str(item) for item in (args.get("vulnerability_types") or []) if str(item).strip()],
                    note=str(args.get("note") or ""),
                    turn_id=turn_id,
                )
            if name == "generate_reports":
                return self.runner.tool_generate_reports(
                    file_name=str(args.get("file_name") or ""),
                    turn_id=turn_id,
                )
            if name == "delete_reports":
                return self.runner.tool_delete_reports(turn_id)
            if name == "install_tools":
                return self.runner.tool_install_tools(
                    tools=[str(item) for item in (args.get("tools") or []) if str(item).strip()],
                    turn_id=turn_id,
                )
            if name == "tool_status":
                return self.runner.tool_tool_status(turn_id)
            return f"未知工具: {name}"
        except Exception as exc:  # 把工具错误回灌给模型，不让整轮崩掉
            if exc.__class__.__name__ == "RetestAIBlockedError":
                raise
            logging.warning("会话工具执行失败 %s: %s", name, exc)
            return f"工具 {name} 执行失败: {exc}"

    # ------------------------------------------------------------- prompt build

    def _system_prompt(self) -> str:
        try:
            return load_retest_prompt("agent_session_system")
        except Exception as exc:
            logging.warning("加载 agent_session_system 提示词失败，使用内置兜底: %s", exc)
            return self._fallback_system_prompt()

    def _initial_user_message(self, message: str) -> str:
        state = {}
        try:
            state = self.runner.tool_session_state() or {}
        except Exception:
            state = {}
        payload = {
            "user_message": message,
            "session_state": state,
            "rules": [
                "先理解用户意图，再决定调用哪个工具；不要凭空编造复测结论。",
                "复测通报漏洞用 retest_report / retest_all_reports；用户给了具体 URL 想现场测用 retest_url。",
                "默认只复测，不生成报告；但 session_state.generate_reports_default 为 true 时，表示本会话来自一键复测/用户已要求报告，继续复测时要保持生成报告意图。",
                "只能在通报范围或用户明确给出的同源 URL 内操作，禁止新增目标、扩大范围、爆破或绕过访问控制。",
                "动作完成后用一句简洁中文回复用户你做了什么、关键结论是什么。",
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _fallback_system_prompt(self) -> str:
        return (
            "你是一个漏洞复测会话 Agent。用户用自然语言和你对话，你要理解意图并调用工具完成复测，"
            "而不是只做关键词匹配。\n\n"
            "可用工具：list_reports（列通报）、retest_report（复测一份通报，含读取/取证/二元判定）、"
            "retest_all_reports（复测全部通报）、retest_url（对用户给的 URL 现场取证）、"
            "generate_reports（生成报告）、install_tools/tool_status（外部工具）。\n\n"
            "工作方式（ReAct）：理解用户意图 → 调用合适的工具 → 观察结果 → 必要时继续 → 用一句中文回复用户。\n"
            "纪律：默认只复测不出报告（除非用户明确要，或 session_state.generate_reports_default 为 true）；只在通报范围或用户给定的同源 URL 内操作；"
            "禁止新增目标、爆破、绕过访问控制；复测结论必须来自工具实际取证，不能编造。"
        )
