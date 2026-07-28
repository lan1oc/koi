import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.AI_Testing.hybrid_agent_runtime import HybridAgentLoop, HybridAgentRuntime, HybridWorkspaceTools
from modules.AI_Testing import backend_commands
from modules.AI_Testing.retest.retest_http_evidence import repair_utf8_mojibake, response_body_preview
from modules.AI_Testing.retest.retest_ai_agent import RetestAIAgent, RetestLLMClient
from modules.AI_Testing.retest.retest_agent_tools import RetestToolExecutor
from modules.AI_Testing.retest.retest_python_probe import RetestPythonProbeRunner


class FakeChatClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def is_ready(self):
        return True

    def chat(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if not self.replies:
            return {"content": "done", "tool_calls": []}
        return self.replies.pop(0)


class FakeModelResponse:
    def __init__(self, json_data=None, lines=None, status_code=200, text="OK"):
        self._json_data = json_data or {}
        self._lines = list(lines or [])
        self.status_code = status_code
        self.text = text

    def iter_lines(self, chunk_size=1, decode_unicode=True):
        yield from self._lines

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class HybridAgentLoopTests(unittest.TestCase):
    def test_llm_client_honors_zero_retries(self) -> None:
        client = RetestLLMClient({
            "provider": "openai",
            "api_key": "test",
            "model": "test-model",
            "max_retries": 0,
        })

        self.assertEqual(client.max_retries, 0)

    def test_complete_json_falls_back_to_non_stream_when_stream_is_empty(self) -> None:
        stream_response = FakeModelResponse(lines=[
            'data: {"choices":[{"delta":{"reasoning_content":"thinking only"},"finish_reason":null}]}',
            "data: [DONE]",
        ])
        non_stream_response = FakeModelResponse(json_data={
            "choices": [{"message": {"content": '{"ok": true, "message": "pong"}'}}],
        })
        client = RetestLLMClient({
            "provider": "volcengine",
            "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "api_key": "ark-test",
            "model": "ark-code-latest",
            "max_retries": 0,
        })

        with mock.patch(
            "modules.AI_Testing.retest.retest_ai_agent.requests.post",
            side_effect=[stream_response, non_stream_response],
        ) as post_mock:
            result = client.complete_json("system", "user")

        self.assertEqual(result["message"], "pong")
        self.assertEqual(post_mock.call_count, 2)
        self.assertTrue(post_mock.call_args_list[0].kwargs["json"]["stream"])
        self.assertNotIn("stream", post_mock.call_args_list[1].kwargs["json"])

    def test_judgement_accepts_model_conclusion_without_verdict(self) -> None:
        agent = RetestAIAgent({"provider": "volcengine", "model": "test-model"})
        judgement = agent._normalize_judgement({
            "conclusion": "未复现：目标当前不可达，未能验证，建议目标恢复后复查",
            "reason": "模型已基于证据判断当前没有形成可复现证据。",
        }, {
            "target_unreachable": True,
        })

        self.assertEqual(judgement["verdict"], "not_reproduced")
        self.assertFalse(judgement["reproduced"])
        self.assertTrue(judgement["unverified_unreachable"])
        self.assertIn("目标当前不可达", judgement["conclusion"])

    def test_judgement_accepts_raw_agent_message_without_verdict(self) -> None:
        agent = RetestAIAgent({"provider": "volcengine", "model": "test-model"})
        judgement = agent._normalize_judgement({
            "_raw_model_text": "AGENT_MESSAGE: 工具证据仍命中通报特征，模型结论为 reproduced / 漏洞未修复。",
            "reason": "响应仍包含通报证据特征",
        }, {})

        self.assertEqual(judgement["verdict"], "reproduced")
        self.assertTrue(judgement["reproduced"])

    def test_backend_model_verdict_reads_nested_chinese_conclusion(self) -> None:
        judgement = {
            "JSON_RESULT": {
                "结论": "漏洞未修复，可以复现",
                "原因": "响应仍包含通报证据特征",
            },
        }

        self.assertEqual(backend_commands._model_verdict_from_judgement(judgement), "reproduced")

    def test_backend_model_verdict_reads_raw_agent_message(self) -> None:
        judgement = {
            "AGENT_MESSAGE": "模型判断：未形成可复现证据，应输出 not_reproduced。",
        }

        self.assertEqual(backend_commands._model_verdict_from_judgement(judgement), "not_reproduced")

    def test_http_evidence_decodes_utf8_body_when_charset_is_missing(self) -> None:
        class FakeResponse:
            content = "未授权访问测试成功".encode("utf-8")
            headers = {"Content-Type": "text/html"}
            encoding = "ISO-8859-1"
            apparent_encoding = "ISO-8859-1"
            status_code = 200
            url = "http://example.test/"
            text = content.decode("ISO-8859-1")

        preview = response_body_preview(FakeResponse())
        self.assertIn("未授权访问测试成功", preview)
        self.assertNotIn("æœª", preview)

    def test_repairs_mixed_utf8_mojibake_fragments(self) -> None:
        broken = "未经授权".encode("utf-8").decode("latin-1")
        repaired = repair_utf8_mojibake(f"AI判定理由: {broken} success")
        self.assertIn("未经授权", repaired)

    def test_records_plan_tool_observation_and_final(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("hello hybrid agent", encoding="utf-8")
            events = []
            runtime = HybridAgentRuntime("loop-test", root, publish=events.append)
            client = FakeChatClient([
                {
                    "content": "计划：先读取 README，再基于内容回复。",
                    "tool_calls": [{"id": "call_1", "name": "read_file", "arguments": {"path": "README.md"}}],
                },
                {"content": "反思：README 已读取。\n最终：README 提到了 hybrid agent。", "tool_calls": []},
            ])

            result = HybridAgentLoop(runtime, client, "system").run("看看 README")

            self.assertTrue(result["success"])
            self.assertFalse(result["blocked"])
            self.assertIn("hybrid agent", result["final_message"])
            snapshot = runtime.snapshot()
            self.assertTrue(snapshot["runs"][-1]["plan"].startswith("计划"))
            self.assertEqual(snapshot["runs"][-1]["observations"][0]["tool"], "read_file")
            self.assertTrue(any(item["role"] == "tool" and "hello hybrid agent" in item["content"] for item in snapshot["conversation"]))
            self.assertTrue({"status", "tool_call", "tool_result", "thought_summary", "chat"}.issubset({event["type"] for event in events}))

    def test_blocks_mutating_tool_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("approval-test", root, publish=lambda _event: None)
            runtime.set_auto_approve(False, "unit test")
            patch = "--- /dev/null\n+++ b/created-by-agent.txt\n@@ -0,0 +1 @@\n+created\n"
            client = FakeChatClient([
                {
                    "content": "计划：需要修改文件，因此先发起审批。",
                    "tool_calls": [{"id": "call_1", "name": "apply_patch", "arguments": {"patch": patch}}],
                },
            ])

            result = HybridAgentLoop(runtime, client, "system").run("修改文件")

            self.assertTrue(result["success"])
            self.assertTrue(result["blocked"])
            self.assertTrue(result["approval_id"].startswith("approval-"))
            snapshot = runtime.snapshot()
            approval = snapshot["approvals"][result["approval_id"]]
            self.assertEqual(approval["tool_name"], "apply_patch")
            self.assertTrue(approval["preview_artifact_id"].startswith("artifact-"))
            self.assertIn("workspace unified text diff", approval["sandbox_summary"])
            self.assertFalse((root / "created-by-agent.txt").exists())

    def test_auto_approval_queues_mutating_tool_without_loop_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = []
            runtime = HybridAgentRuntime("auto-approval-test", root, publish=events.append)
            runtime.set_auto_approve(True, "unit test")
            patch = "--- /dev/null\n+++ b/auto-created.txt\n@@ -0,0 +1 @@\n+created\n"
            client = FakeChatClient([
                {
                    "content": "plan: create a file after approval",
                    "tool_calls": [{"id": "call_1", "name": "apply_patch", "arguments": {"patch": patch}}],
                },
            ])

            result = HybridAgentLoop(runtime, client, "system").run("create file")

            self.assertTrue(result["success"])
            self.assertFalse(result["blocked"])
            self.assertTrue(result["running"])
            self.assertTrue(result["auto_approved"])
            self.assertTrue(result["approval_id"].startswith("approval-"))
            self.assertTrue(result["operation_id"].startswith("operation-"))
            self.assertFalse((root / "auto-created.txt").exists())
            snapshot = runtime.snapshot()
            self.assertTrue(snapshot["auto_approve"])
            self.assertEqual(snapshot["approvals"][result["approval_id"]]["status"], "pending")
            self.assertEqual(snapshot["operations"][result["operation_id"]]["status"], "pending")
            approval_events = [event for event in events if event.get("type") == "approval_request"]
            self.assertTrue(approval_events)
            self.assertFalse(approval_events[-1]["metadata"]["requiresUserDecision"])
            self.assertTrue(approval_events[-1]["metadata"]["autoApproved"])

    def test_invalid_mutating_tool_request_is_rejected_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = HybridAgentRuntime("invalid-approval-test", Path(temp_dir), publish=lambda _event: None)
            client = FakeChatClient([
                {
                    "content": "plan",
                    "tool_calls": [{"id": "call_1", "name": "apply_patch", "arguments": {"patch": "*** Begin Patch"}}],
                },
                {"content": "final after sandbox rejection", "tool_calls": []},
            ])

            result = HybridAgentLoop(runtime, client, "system").run("write invalid patch")

            self.assertTrue(result["success"])
            self.assertFalse(result["blocked"])
            self.assertEqual(runtime.snapshot()["approvals"], {})
            self.assertTrue(any("sandbox rejected" in event.get("content", "").lower() for event in runtime.snapshot()["events"]))

    def test_approved_run_command_executes_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("command-execute-test", root, publish=lambda _event: None)
            approval = runtime.request_approval(
                "run_command",
                "run_command requires approval",
                "test command",
                '{"command":"echo hello-agent"}',
                args={"command": "echo hello-agent"},
                risk="command",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            result = runtime.execute_approved_operation(approval.id)

            self.assertTrue(result["success"])
            self.assertEqual(result["status"], "completed")
            self.assertIn("hello-agent", result["raw_output"])
            operation = runtime.snapshot()["operations"][result["operation_id"]]
            self.assertEqual(operation["status"], "completed")

    def test_command_sandbox_rejects_high_risk_inline_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("command-sandbox-test", root, publish=lambda _event: None)
            marker = root / "should-not-exist.txt"
            approval = runtime.request_approval(
                "run_command",
                "run_command requires approval",
                "dangerous command",
                '{"command":"python -c ..."}',
                args={"command": f"python -c \"open(r'{marker}', 'w').write('bad')\""},
                risk="command",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            result = runtime.execute_approved_operation(approval.id)

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "failed")
            self.assertIn("sandbox", result["raw_output"].lower())
            self.assertFalse(marker.exists())

    def test_command_sandbox_rejects_network_install_and_inline_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("command-network-test", root, publish=lambda _event: None)
            for command in ("curl https://example.com/file.zip", "npm install left-pad", "powershell -Command Get-Date"):
                approval = runtime.request_approval(
                    "run_command",
                    "run_command requires approval",
                    "dangerous command",
                    command,
                    args={"command": command},
                    risk="command",
                )
                self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
                result = runtime.execute_approved_operation(approval.id)
                self.assertFalse(result["success"], command)
                self.assertEqual(result["status"], "failed")
                self.assertIn("sandbox", result["raw_output"].lower())

    def test_run_command_timeout_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sleeper = root / "sleeper.py"
            sleeper.write_text("import time\nprint('start')\ntime.sleep(5)\nprint('end')\n", encoding="utf-8")
            runtime = HybridAgentRuntime("command-timeout-test", root, publish=lambda _event: None)
            approval = runtime.request_approval(
                "run_command",
                "run_command requires approval",
                "timeout command",
                "python sleeper.py",
                args={"command": "python sleeper.py", "timeout_seconds": 1},
                risk="command",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            started = time.time()
            result = runtime.execute_approved_operation(approval.id)

            self.assertLess(time.time() - started, 4.5)
            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "failed")
            self.assertIn("timed out", result["raw_output"].lower())

    def test_approved_apply_patch_writes_workspace_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "note.txt"
            target.write_text("old\n", encoding="utf-8")
            runtime = HybridAgentRuntime("patch-execute-test", root, publish=lambda _event: None)
            patch = "--- a/note.txt\n+++ b/note.txt\n@@ -1 +1 @@\n-old\n+new\n"
            approval = runtime.request_approval(
                "apply_patch",
                "apply_patch requires approval",
                "patch note.txt",
                patch,
                args={"patch": patch},
                risk="write",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            result = runtime.execute_approved_operation(approval.id)

            self.assertTrue(result["success"], result["raw_output"])
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertTrue(result["artifact_ids"])

    def test_approved_apply_patch_creates_workspace_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "created.txt"
            runtime = HybridAgentRuntime("patch-create-test", root, publish=lambda _event: None)
            patch = "--- /dev/null\n+++ b/created.txt\n@@ -0,0 +1,2 @@\n+hello\n+agent\n"
            approval = runtime.request_approval(
                "apply_patch",
                "apply_patch requires approval",
                "create created.txt",
                patch,
                args={"patch": patch},
                risk="write",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            result = runtime.execute_approved_operation(approval.id)

            self.assertTrue(result["success"], result["raw_output"])
            self.assertEqual(target.read_text(encoding="utf-8"), "hello\nagent\n")
            self.assertIn("created.txt", result["raw_output"])

    def test_apply_patch_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("patch-sandbox-test", root, publish=lambda _event: None)
            patch = "--- a/../escape.txt\n+++ b/../escape.txt\n@@ -0,0 +1 @@\n+bad\n"
            approval = runtime.request_approval(
                "apply_patch",
                "apply_patch requires approval",
                "escape patch",
                patch,
                args={"patch": patch},
                risk="write",
            )

            self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
            result = runtime.execute_approved_operation(approval.id)

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "failed")
            self.assertFalse((root.parent / "escape.txt").exists())

    def test_apply_patch_rejects_delete_and_binary_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "note.txt").write_text("old\n", encoding="utf-8")
            runtime = HybridAgentRuntime("patch-delete-test", root, publish=lambda _event: None)
            for patch in (
                "--- a/note.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n",
                "GIT binary patch\nliteral 0\n",
            ):
                approval = runtime.request_approval(
                    "apply_patch",
                    "apply_patch requires approval",
                    "bad patch",
                    patch,
                    args={"patch": patch},
                    risk="write",
                )
                self.assertTrue(runtime.resolve_approval(approval.id, "approve", "unit test"))
                result = runtime.execute_approved_operation(approval.id)
                self.assertFalse(result["success"])
                self.assertEqual(result["status"], "failed")

    def test_operation_schema_migration_marks_restored_running_operation_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = HybridAgentRuntime("stale-operation-test", root, publish=lambda _event: None)
            approval = runtime.request_approval(
                "run_command",
                "run_command requires approval",
                "legacy running command",
                "echo stale",
                args={"command": "echo stale"},
                risk="command",
            )
            operation_id = approval.operation_id
            runtime.session.operations[operation_id].status = "running"
            runtime.session.approvals[approval.id].status = "running"
            runtime.session.schema_version = 1
            runtime.store.save(runtime.session)

            restored = HybridAgentRuntime("stale-operation-test", root, publish=lambda _event: None)
            snapshot = restored.snapshot()

            self.assertEqual(snapshot["schema_version"], 2)
            self.assertEqual(snapshot["operations"][operation_id]["status"], "stale")
            self.assertEqual(snapshot["approvals"][approval.id]["status"], "stale")

    def test_operation_cancel_marks_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = HybridAgentRuntime("operation-cancel-test", Path(temp_dir), publish=lambda _event: None)
            approval = runtime.request_approval(
                "run_command",
                "run_command requires approval",
                "pending command",
                "echo cancel",
                args={"command": "echo cancel"},
                risk="command",
            )

            self.assertTrue(runtime.mark_operation_cancel_requested(approval.operation_id, "unit cancel"))
            operation = runtime.operation_snapshot(approval.operation_id)

            self.assertEqual(operation["status"], "cancelled")
            self.assertEqual(operation["error"], "unit cancel")

    def test_tool_manifest_includes_sandbox_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = HybridAgentRuntime("manifest-test", Path(temp_dir), publish=lambda _event: None)
            specs = HybridWorkspaceTools(runtime).tool_specs()

            self.assertTrue(all(spec.get("sandboxPolicySummary") for spec in specs))
            run_command = next(spec for spec in specs if spec["name"] == "run_command")
            self.assertTrue(run_command["requiresApproval"])
            self.assertTrue(run_command["autoApprovalSupported"])
            self.assertTrue(run_command["workspaceOnly"])

    def test_retest_agent_status_does_not_create_runner(self) -> None:
        session_id = "status-inactive-unit-test"
        with backend_commands._RETEST_AGENT_LOCK:
            backend_commands._RETEST_AGENT_RUNNERS.pop(session_id, None)

        result = backend_commands._doc_retest_agent_status({"session_id": session_id})

        self.assertTrue(result["success"])
        self.assertFalse(result["active"])
        self.assertFalse(result["running"])
        with backend_commands._RETEST_AGENT_LOCK:
            self.assertNotIn(session_id, backend_commands._RETEST_AGENT_RUNNERS)

    def test_stopped_retest_runner_exposes_resumable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "notice.docx")
            runner = backend_commands.RetestAgentRunner("stopped-resume-test")
            runner.target_dir = temp_dir
            runner.source_files = [source]
            runner.next_index = 0
            runner.stopped = True

            snapshot = runner.snapshot()
            patch = runner._session_patch()

            self.assertTrue(snapshot["stopped"])
            self.assertEqual(snapshot["status"], "已停止")
            self.assertTrue(snapshot["resume_state"]["canContinue"])
            self.assertEqual(snapshot["resume_state"]["sourceFiles"], [source])
            self.assertTrue(patch["resumeState"]["canContinue"])

    def test_retest_runner_does_not_skip_same_name_in_another_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = str(root / "tenant-a" / "notice.docx")
            second = str(root / "tenant-b" / "notice.docx")
            runner = backend_commands.RetestAgentRunner("same-name-path-test")
            runner.source_files = [first, second]
            runner.frontend_completed_file_names = ["notice.docx"]
            runner.disk_completed_report_evidence = [{"source_file": first}]

            self.assertTrue(runner._source_file_completed_locked(0))
            self.assertFalse(runner._source_file_completed_locked(1))

    def test_cancelled_retest_turn_does_not_commit_late_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "notice.docx")
            runner = backend_commands.RetestAgentRunner("cancelled-turn-test")
            runner.source_files = [source]

            def fake_run(*_args, **_kwargs):
                runner.stopped = True
                return "late result", {}, False, []

            with mock.patch.object(backend_commands, "_run_retest_for_source_file", side_effect=fake_run):
                outcome = runner._retest_single_file(0, False, "old-turn")

            self.assertEqual(outcome["status"], "stopped")
            self.assertEqual(runner.completion_items, [])
            self.assertEqual(runner.next_index, 0)

    def test_retest_runner_keeps_judgement_resume_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = str(root / "notice.docx")
            runner = backend_commands.RetestAgentRunner("judgement-resume-test")
            snapshot = {
                "stage": "judgement",
                "source_file": source,
                "scan_result": {"targets": ["https://example.test"]},
                "result_data": {"file": source},
            }

            with runner.lock:
                runner.target_dir = str(root)
                runner.source_files = [source]
                runner.next_index = 0
                runner.current_file_resume = runner._current_file_resume_from_snapshot_locked(snapshot)
                state = runner._resume_state_locked(True)
                restored = runner._resume_snapshot_for_source_locked(0, source)

            self.assertIsNotNone(state["currentFile"])
            self.assertEqual(state["currentFile"]["stage"], "judgement")
            self.assertEqual(restored["stage"], "judgement")
            self.assertEqual(restored["scan_result"]["targets"], ["https://example.test"])

    def test_retest_runner_keeps_execution_resume_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = str(root / "notice.docx")
            runner = backend_commands.RetestAgentRunner("execution-resume-test")
            snapshot = backend_commands._execution_resume_snapshot(
                source,
                {"vulnerability_types": ["info leak"], "urls": ["https://example.test/a"]},
                ["https://example.test/a"],
                [{"url": "https://example.test/a", "context_checks": [{"type": "stored"}]}],
                1,
                False,
                True,
            )

            with runner.lock:
                runner.target_dir = str(root)
                runner.source_files = [source]
                runner.next_index = 0
                runner.current_file_resume = runner._current_file_resume_from_snapshot_locked(snapshot)
                state = runner._resume_state_locked(True)
                restored = runner._resume_snapshot_for_source_locked(0, source)

            self.assertIsNotNone(state["currentFile"])
            self.assertEqual(state["currentFile"]["stage"], "execution")
            self.assertEqual(restored["stage"], "execution")
            self.assertEqual(restored["next_url_index"], 1)
            self.assertEqual(restored["retest_results"][0]["url"], "https://example.test/a")

    def test_retest_initial_execution_writes_url_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "notice.docx")
            urls = ["https://example.test/a", "https://example.test/b"]
            scan_result = {
                "vulnerability_types": ["info leak"],
                "urls": list(urls),
                "retest_context": {"target_urls": list(urls)},
            }
            checkpoints = []
            scanned_urls = []

            def fake_scan_document(_scanner, _file_path):
                return dict(scan_result)

            def fake_scan_url(_scanner, url, _vuln_types, _context):
                scanned_urls.append(url)
                return {"url": url, "vulnerabilities": [], "context_checks": [{"type": "checked"}], "observation_count": 0}

            with mock.patch(
                "modules.AI_Testing.retest.word_vulnerability_scanner.WordVulnerabilityScanner.scan_document",
                autospec=True,
                side_effect=fake_scan_document,
            ), mock.patch(
                "modules.AI_Testing.retest.vulnerability_batch_scanner.VulnerabilityRetestScanner.scan_url_fast_for_context",
                autospec=True,
                side_effect=fake_scan_url,
            ):
                summary, result_data, manual_required, _trace = backend_commands._run_retest_for_source_file(
                    Path(source),
                    {"use_ai": False},
                    [],
                    checkpoint_callback=checkpoints.append,
                )

            execution_indexes = [
                item.get("next_url_index")
                for item in checkpoints
                if item.get("stage") == "execution"
            ]
            self.assertEqual(scanned_urls, urls)
            self.assertEqual(execution_indexes, [0, 1, 2])
            self.assertEqual(len(result_data["retest_results"]), 2)
            self.assertFalse(manual_required)
            self.assertIn("复测URL数量: 2", summary)

    def test_retest_execution_resume_skips_completed_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "missing.docx")
            first_url = "https://example.test/a"
            second_url = "https://example.test/b"
            stored_result = {
                "url": first_url,
                "vulnerabilities": [],
                "context_checks": [{"type": "stored", "detail": "kept"}],
                "observation_count": 0,
            }
            snapshot = backend_commands._execution_resume_snapshot(
                source,
                {
                    "vulnerability_types": ["info leak"],
                    "urls": [first_url, second_url],
                    "retest_context": {"target_urls": [first_url, second_url]},
                },
                [first_url, second_url],
                [stored_result],
                1,
                False,
                True,
            )
            logs = []
            events = []
            checkpoints = []
            scanned_urls = []

            def fake_scan_url(_scanner, url, _vuln_types, _context):
                scanned_urls.append(url)
                return {"url": url, "vulnerabilities": [], "context_checks": [{"type": "checked"}], "observation_count": 0}

            with mock.patch(
                "modules.AI_Testing.retest.vulnerability_batch_scanner.VulnerabilityRetestScanner.scan_url_fast_for_context",
                autospec=True,
                side_effect=fake_scan_url,
            ):
                _summary, result_data, manual_required, _trace = backend_commands._run_retest_for_source_file(
                    Path(source),
                    {"resume_snapshot": snapshot, "use_ai": False},
                    logs,
                    event_callback=events.append,
                    checkpoint_callback=checkpoints.append,
                )

            self.assertEqual(scanned_urls, [second_url])
            self.assertEqual([item["url"] for item in result_data["retest_results"]], [first_url, second_url])
            self.assertEqual(result_data["retest_results"][0]["context_checks"][0]["detail"], "kept")
            self.assertFalse(manual_required)
            self.assertIn("resumed execution checkpoint", "\n".join(logs))
            self.assertTrue(any(event.get("metadata", {}).get("resumedFromSnapshot") for event in events))
            self.assertTrue(any(item.get("stage") == "execution" and item.get("next_url_index") == 2 for item in checkpoints))

    def test_retest_report_resume_snapshot_skips_retest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "missing.docx")
            result_data = {
                "file": source,
                "final_verdict": "not_reproduced",
                "ai_judgement": {
                    "verdict": "not_reproduced",
                    "conclusion": "fixed",
                    "reason": "stored judgement",
                },
            }
            snapshot = backend_commands._report_resume_snapshot(
                source,
                "stored summary",
                result_data,
                "stored report evidence",
            )
            logs = []
            events = []

            summary, restored_data, manual_required, _trace = backend_commands._run_retest_for_source_file(
                Path(source),
                {"resume_snapshot": snapshot},
                logs,
                event_callback=events.append,
            )

            self.assertEqual(summary, "stored summary")
            self.assertEqual(restored_data["final_verdict"], "not_reproduced")
            self.assertFalse(manual_required)
            self.assertIn("resumed from report snapshot", "\n".join(logs))
            self.assertTrue(any(event.get("metadata", {}).get("resumeStage") == "report" for event in events))

    def test_retest_disposal_report_deletes_word_after_successful_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "关于测试单位存在漏洞的通报.docx"
            source.write_bytes(b"notice")
            screenshot = root / "evidence.png"
            screenshot.write_bytes(b"image")
            template = root / "template.docx"
            template.write_bytes(b"template")
            logs = []

            def fake_convert(word_path, _logs):
                pdf_path = word_path.with_suffix(".pdf")
                pdf_path.write_bytes(b"%PDF-1.4")
                return pdf_path, None

            with mock.patch(
                "modules.AI_Testing.backend_commands._retest_disposal_template_path",
                return_value=template,
            ), mock.patch(
                "modules.AI_Testing.backend_commands._fill_disposal_report_document",
            ), mock.patch(
                "modules.AI_Testing.backend_commands._convert_single_word_to_pdf",
                side_effect=fake_convert,
            ):
                result = backend_commands._prepare_retest_disposal_report(
                    source,
                    {"title": "测试标题", "vulnerability_type": "信息泄露", "url": "https://example.test"},
                    screenshot,
                    logs,
                )

            self.assertIsNotNone(result)
            word_path = Path(result["word"])
            pdf_path = Path(result["pdf"])
            self.assertFalse(word_path.exists())
            self.assertTrue(pdf_path.exists())
            self.assertTrue(result["word_deleted"])
            self.assertEqual(result["word_delete_error"], "")
            self.assertIn("处置文件Word版已删除", "\n".join(logs))

    def test_retest_disposal_report_keeps_word_when_pdf_conversion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "关于测试单位存在漏洞的通报.docx"
            source.write_bytes(b"notice")
            screenshot = root / "evidence.png"
            screenshot.write_bytes(b"image")
            template = root / "template.docx"
            template.write_bytes(b"template")
            logs = []

            with mock.patch(
                "modules.AI_Testing.backend_commands._retest_disposal_template_path",
                return_value=template,
            ), mock.patch(
                "modules.AI_Testing.backend_commands._fill_disposal_report_document",
            ), mock.patch(
                "modules.AI_Testing.backend_commands._convert_single_word_to_pdf",
                return_value=(None, "convert failed"),
            ):
                result = backend_commands._prepare_retest_disposal_report(
                    source,
                    {"title": "测试标题", "vulnerability_type": "信息泄露", "url": "https://example.test"},
                    screenshot,
                    logs,
                )

            self.assertIsNotNone(result)
            self.assertTrue(Path(result["word"]).exists())
            self.assertEqual(result["pdf"], "")
            self.assertEqual(result["pdf_error"], "convert failed")
            self.assertFalse(result["word_deleted"])

    def test_nudges_no_tool_then_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = HybridAgentRuntime("no-tool-test", Path(temp_dir), publish=lambda _event: None)
            client = FakeChatClient([
                {"content": "我可以直接回答。", "tool_calls": []},
                {"content": "还是不调用工具。", "tool_calls": []},
                {"content": "最终但没有工具。", "tool_calls": []},
            ])

            result = HybridAgentLoop(runtime, client, "system").run("分析项目")

            self.assertTrue(result["success"])
            self.assertFalse(result["blocked"])
            self.assertEqual(len(client.calls), 3)
            self.assertIn("最终但没有工具", result["final_message"])
            self.assertTrue(any(event["type"] == "chat" and event["tone"] == "warn" for event in runtime.snapshot()["events"]))

    @staticmethod
    def _retest_tool_executor(url: str = "https://example.test/report") -> RetestToolExecutor:
        scanner = mock.Mock()
        scanner.session = mock.Mock()
        scanner.timeout = 10
        scanner.confirm_callback = None
        scanner._build_request_meta = mock.Mock(return_value={})
        scanner._trace_event = mock.Mock()
        return RetestToolExecutor(scanner, url, {"target_urls": [url]}, probe=None)

    def test_retest_tool_executor_enforces_same_origin(self) -> None:
        executor = self._retest_tool_executor()

        self.assertEqual(executor._resolve_target("/api/check"), "https://example.test/api/check")
        with self.assertRaisesRegex(RuntimeError, "超出通报授权同源范围"):
            executor._resolve_target("https://other.test/api/check")

    def test_retest_tool_executor_rejects_waf_bypass_intent(self) -> None:
        executor = self._retest_tool_executor()

        result = executor.execute("run_python_probe", {
            "reason": "尝试绕过 WAF 后重新验证",
            "script": "def run(targets, context):\n    return None",
        })

        self.assertIn("复测策略拒绝", result)
        self.assertIn("禁止绕过", result)
        self.assertEqual(executor.executed_tools, [])

    def test_retest_tool_executor_auto_finishes_only_direct_reproduction(self) -> None:
        side_executor = self._retest_tool_executor()
        side_executor.executed_tools.append("http_request")
        side_executor._has_real_observation = True
        side_executor.execute("record_finding", {
            "title": "旁路版本泄露",
            "severity": "high",
            "detail": "响应头暴露版本，但与原通报 SQL 注入无关。",
            "evidence": "Server: example/1.0",
            "relation": "side_observation",
            "verdict_support": "inconclusive",
        })
        self.assertFalse(side_executor.finished)

        direct_executor = self._retest_tool_executor()
        direct_executor.executed_tools.append("http_request")
        direct_executor._has_real_observation = True
        direct_executor.execute("record_finding", {
            "title": "原通报漏洞复现",
            "severity": "high",
            "detail": "通报载荷在原路径产生相同回显。",
            "evidence": "POST /report -> HTTP 200, marker=reported-proof",
            "relation": "reported_vulnerability",
            "verdict_support": "reproduced",
        })
        self.assertTrue(direct_executor.finished)
        self.assertTrue(direct_executor.auto_finished)

    def test_retest_tool_executor_does_not_auto_finish_without_real_tool(self) -> None:
        executor = self._retest_tool_executor()

        executor.execute("record_finding", {
            "title": "未经工具验证的模型判断",
            "severity": "high",
            "detail": "只有文字判断。",
            "evidence": "模型声称存在",
            "relation": "reported_vulnerability",
            "verdict_support": "reproduced",
        })

        self.assertFalse(executor.finished)
        self.assertFalse(executor.auto_finished)

    def test_page_context_observation_can_finish_direct_reproduction(self) -> None:
        executor = self._retest_tool_executor()
        executor.scanner._execute_agent_tool.return_value = []

        observed = executor.execute("collect_page_context", {"url": "/report"})
        self.assertIn("页面上下文采集完成", observed)
        executor.execute("record_finding", {
            "title": "原通报页面泄露复现",
            "severity": "high",
            "detail": "页面正文仍包含通报中的敏感标记。",
            "evidence": "marker=reported-proof",
            "relation": "reported_vulnerability",
            "verdict_support": "reproduced",
        })

        self.assertTrue(executor.auto_finished)

    def test_python_probe_failure_requires_rewritten_script_and_stops_after_three(self) -> None:
        executor = self._retest_tool_executor()
        failed_record = {
            "type": "python_probe_error",
            "severity": "info",
            "detail": "脚本执行失败",
            "evidence": "Traceback: NameError on line 3",
            "tool_failed": True,
        }
        executor._probe_runner.run_probe = mock.Mock(return_value=[failed_record])
        scripts = [
            "def run(targets, context):\n    missing_name()",
            "def run(targets, context):\n    other_missing_name()",
            "def run(targets, context):\n    third_missing_name()",
        ]

        first = executor.execute("run_python_probe", {"reason": "首次验证", "script": scripts[0]})
        self.assertIn("必须重写", first)
        self.assertTrue(executor.requires_probe_repair)
        self.assertEqual(executor.probe_failure_count, 1)

        unchanged = executor.execute("run_python_probe", {"reason": "原样重试", "script": scripts[0]})
        self.assertIn("完全相同", unchanged)
        self.assertEqual(executor._probe_runner.run_probe.call_count, 1)

        switched = executor.execute("run_nmap", {"reason": "换工具"})
        self.assertIn("必须先根据错误重写", switched)
        self.assertEqual(executor.executed_tools, ["run_python_probe"])

        executor.execute("run_python_probe", {"reason": "第一次重写", "script": scripts[1]})
        final = executor.execute("run_python_probe", {"reason": "第二次重写", "script": scripts[2]})
        self.assertIn("连续三份不同脚本均执行失败", final)
        self.assertTrue(executor.finished)
        self.assertFalse(executor.requires_probe_repair)
        self.assertEqual(executor.probe_failure_count, 3)
        self.assertEqual(len([item for item in executor.records if item.get("tool_failed")]), 3)

    def test_nmap_flags_cannot_add_another_target_or_unbounded_script(self) -> None:
        executor = self._retest_tool_executor()
        executor.scanner.blackbox_tools._run_external.return_value = {
            "output": "scan complete",
            "returncode": 0,
            "elapsed_ms": 10,
        }

        with mock.patch(
            "modules.AI_Testing.retest.retest_agent_tools.find_tool_command",
            return_value=["nmap"],
        ):
            executor.execute("run_nmap", {
                "flags": "-sV evil.test --script vuln -p80 -T4",
            })

        command = executor.scanner.blackbox_tools._run_external.call_args.args[0]
        self.assertEqual(command[-1], "example.test")
        self.assertNotIn("evil.test", command)
        self.assertNotIn("--script", command)
        self.assertIn("-p80", command)
        self.assertEqual(executor.scanner.blackbox_tools._run_external.call_args.kwargs["timeout"], 60)

    def test_retest_pipeline_deduplicates_urls_and_skips_remaining_after_decisive_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "notice.docx")
            scan_result = {
                "vulnerability_types": ["信息泄露"],
                "urls": [
                    "https://EXAMPLE.test/a#proof",
                    "https://example.test/a",
                    "https://example.test/b",
                ],
                "retest_context": {},
            }
            scanned_urls = []

            def fake_scan_document(_scanner, _file_path):
                return dict(scan_result)

            def fake_scan_url(_scanner, url, _vuln_types, _context):
                scanned_urls.append(url)
                return {
                    "url": url,
                    "vulnerabilities": [{"type": "直接证据", "severity": "high"}],
                    "observation_count": 1,
                    "decisive_reproduction": True,
                    "decisive_evidence": {
                        "type": "原通报漏洞复现",
                        "severity": "high",
                        "evidence": "HTTP 200 marker=proof",
                        "relation": "reported_vulnerability",
                        "verdict_support": "reproduced",
                    },
                }

            with mock.patch(
                "modules.AI_Testing.retest.word_vulnerability_scanner.WordVulnerabilityScanner.scan_document",
                autospec=True,
                side_effect=fake_scan_document,
            ), mock.patch(
                "modules.AI_Testing.retest.vulnerability_batch_scanner.VulnerabilityRetestScanner.scan_url_for_context",
                autospec=True,
                side_effect=fake_scan_url,
            ), mock.patch.object(backend_commands, "_apply_retest_ai_agent") as planning_mock, mock.patch.object(
                backend_commands, "_apply_retest_ai_judgement"
            ) as judgement_mock:
                _summary, result_data, _manual, _trace = backend_commands._run_retest_for_source_file(
                    Path(source),
                    {"use_ai": True},
                    [],
                )

            self.assertEqual(scanned_urls, ["https://example.test/a"])
            self.assertEqual(result_data["urls"], ["https://example.test/a", "https://example.test/b"])
            self.assertEqual(result_data["final_verdict"], "reproduced")
            self.assertEqual(result_data["ai_judgement"]["source"], "react_decisive_evidence")
            planning_mock.assert_not_called()
            judgement_mock.assert_not_called()

    def test_retest_resume_does_not_reuse_ambiguous_same_name_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = str(root / "tenant-a" / "notice.docx")
            second = str(root / "tenant-b" / "notice.docx")
            runner = backend_commands.RetestAgentRunner("ambiguous-resume-test")
            runner.source_files = [first, second]
            snapshot = {
                "stage": "execution",
                "source_file": first,
                "scan_result": {"urls": ["https://example.test/a"]},
            }
            runner.current_file_resume = runner._current_file_resume_from_snapshot_locked(snapshot)

            self.assertEqual(runner._resume_snapshot_for_source_locked(0, first)["source_file"], first)
            self.assertEqual(runner._resume_snapshot_for_source_locked(1, second), {})

    def test_retest_progress_skips_only_path_completed_same_name_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = str(root / "tenant-a" / "notice.docx")
            second = str(root / "tenant-b" / "notice.docx")
            runner = backend_commands.RetestAgentRunner("same-name-progress-test")
            runner.source_files = [first, second]
            runner.frontend_completed_file_names = ["notice.docx"]
            runner.disk_completed_report_evidence = [{"source_file": first}]
            runner.next_index = 0

            self.assertEqual(runner._advance_next_index_past_completed_locked(), 1)
            self.assertFalse(runner._source_file_completed_locked(1))

    def test_python_probe_rejects_cross_origin_before_request(self) -> None:
        session = mock.Mock()
        runner = RetestPythonProbeRunner(session, 5, lambda _response, _started: {})

        records = runner.run_probe(
            "def run(targets, context):\n    http_request('GET', 'https://other.test/private')",
            {},
            ["https://example.test/report"],
        )

        self.assertTrue(records[0].get("tool_failed"))
        self.assertIn("超出通报授权同源范围", records[0].get("evidence", ""))
        session.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
