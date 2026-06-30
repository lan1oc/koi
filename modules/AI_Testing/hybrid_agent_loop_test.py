import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.AI_Testing.hybrid_agent_runtime import HybridAgentLoop, HybridAgentRuntime, HybridWorkspaceTools
from modules.AI_Testing.retest.retest_http_evidence import repair_utf8_mojibake, response_body_preview


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


class HybridAgentLoopTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
