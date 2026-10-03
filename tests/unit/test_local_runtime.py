"""Production runtime contracts; deterministic inference and real approved local tools."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

from harness.core.client import CancellationToken
from harness.core.engines import EngineFailure
from harness.core.inference import AllocationUnavailable
from harness.core.models import RemoteHealth, StreamChunk
from harness.core.runtime_models import ModelProfile
from harness.core.service import CoreService, bounded_result
from harness.security import scrubber
from harness.skills.manager import SkillManager
from harness.storage.runtime import RuntimeStore


def text_reply(text="done", reason="stop", complete=True):
    chunks = [StreamChunk(delta_content=text, finish_reason=reason)]
    return chunks + ([StreamChunk(stream_complete=True)] if complete else [])


def tool_reply(calls, complete=True, reason="tool_calls"):
    deltas = [{"index": i, "id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}
              for i, (call_id, name, arguments) in enumerate(calls)]
    return [StreamChunk(tool_call_deltas=deltas, finish_reason=reason)] + ([StreamChunk(stream_complete=True)] if complete else [])


class FixtureEngine:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def stream(self, profile, messages, tools, cancellation):
        self.requests.append({"profile": profile.profile_id, "messages": json.loads(json.dumps(messages)),
                              "tools": json.loads(json.dumps(tools))})
        if not self.replies:
            raise AssertionError("Unexpected inference request")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        yield from reply

    def get_health(self):
        return RemoteHealth(status="healthy", raw={"status": "healthy", "gpus": []})


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-runtime-unit-")
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.directory = self.base / "state"
        self.profile = ModelProfile("profile-1", "worker-1", "generic", "fixture", frozenset({"text", "code_tools"}))
        self.core = None

    def tearDown(self):
        if self.core:
            self.core.close()
        self.temp.cleanup()

    def start(self, *replies, **options):
        self.engine = FixtureEngine(*replies)
        self.core = CoreService(self.workspace, self.engine, options.pop("profile", self.profile),
                                state_dir=self.directory, system_prompt="immutable system", **options)
        return self.core

    def restart(self, *replies):
        self.core.close()
        return self.start(*replies)

    def test_approved_edit_and_real_test_command_then_restart_without_repeat(self):
        (self.workspace / "value.txt").write_text("old", encoding="utf-8")
        command = f'"{sys.executable}" -c "from pathlib import Path; assert Path(\'value.txt\').read_text() == \'new\'"'
        core = self.start(tool_reply([("edit-1", "edit_file", {"path": "value.txt", "old_str": "old", "new_str": "new"}),
                                     ("test-1", "run_command", {"command": command})]), text_reply("Edited and tests passed"))
        approvals = []
        task_id = core.submit("edit and test")
        result = core.run(task_id, approval_resolver=lambda n, a: approvals.append(n) or True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(approvals, ["edit_file", "run_command"])
        actions = core.store.all("SELECT * FROM actions ORDER BY rowid")
        self.assertTrue(all(a["state"] == "completed" for a in actions))
        self.assertEqual(json.loads(actions[1]["result"])["exit_code"], 0)
        self.assertEqual(core.artifacts.latest()["state"], "sealed")
        sid = result["session_id"]
        core = self.restart()
        self.assertEqual(core.resume(sid)["status"], "completed")
        self.assertEqual(len(self.engine.requests), 0)
        self.assertEqual((self.workspace / "value.txt").read_text(), "new")

    def test_missing_resolver_denial_and_non_boolean_consent(self):
        core = self.start()
        for resolver in (None, lambda *_: False, lambda *_: 1, lambda *_: "yes"):
            self.engine.replies += [tool_reply([("write", "write_file", {"path": "blocked.txt", "content": "bad"})]), text_reply()]
            result = core.run(core.submit("write"), approval_resolver=resolver)
            self.assertEqual(result["status"], "completed")
            self.assertFalse((self.workspace / "blocked.txt").exists())
        self.assertTrue(all(r["state"] == "denied" for r in core.store.all("SELECT state FROM actions")))

    def test_stale_revision_capability_and_changed_file_approvals(self):
        core = self.start()
        target = self.workspace / "a.txt"
        for mutation in ("revision", "capabilities", "file"):
            target.write_text("before")
            self.engine.replies += [tool_reply([("edit", "edit_file", {"path": "a.txt", "old_str": "before", "new_str": "after"})]), text_reply()]
            task_id = core.submit("edit")
            def approve(*_):
                if mutation == "file":
                    target.write_text("external")
                else:
                    with core.store.transaction() as db:
                        if mutation == "revision":
                            db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (task_id,))
                        else:
                            db.execute("UPDATE tasks SET allowed_tools='[]' WHERE id=?", (task_id,))
                return True
            core.run(task_id, approval_resolver=approve)
            self.assertEqual(target.read_text(), "external" if mutation == "file" else "before")
        approvals = core.store.all("SELECT * FROM approvals")
        self.assertTrue(all(a["state"] == "denied" for a in approvals))
        with self.assertRaises(ValueError):
            core.permissions.resolve(approvals[0]["id"], True, None)

    def test_protected_paths_and_traversal_are_rejected(self):
        core = self.start()
        for path in (".env", ".git/config", "../outside.txt"):
            self.engine.replies += [tool_reply([("unsafe", "write_file", {"path": path, "content": "bad"})]), text_reply()]
            core.run(core.submit("write"), approval_resolver=lambda *_: True)
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM approvals")["n"], 0)
        self.assertFalse((self.base / "outside.txt").exists())

    def test_malformed_batch_executes_nothing_even_if_first_call_is_valid(self):
        reply = tool_reply([("good", "write_file", {"path": "good.txt", "content": "bad"})])
        reply[0].tool_call_deltas.append({"index": 1, "id": "bad", "function": {"name": "write_file", "arguments": "{"}})
        core = self.start(reply)
        self.assertEqual(core.run(core.submit("write"), approval_resolver=lambda *_: True)["status"], "malformed")
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM actions")["n"], 0)
        self.assertFalse((self.workspace / "good.txt").exists())

    def test_truncation_and_incomplete_finish_never_execute_calls(self):
        core = self.start()
        for reason, complete, expected in (("length", True, "truncated"), ("tool_calls", False, "incomplete")):
            self.engine.replies.append(tool_reply([("call", "write_file", {"path": "a.txt", "content": "bad"})], complete, reason))
            self.assertEqual(core.run(core.submit("write"), approval_resolver=lambda *_: True)["status"], expected)
        self.assertFalse((self.workspace / "a.txt").exists())
        self.assertEqual(core.inference.allocation()["state"], "quarantined")

    def test_submission_idempotency_and_payload_collision(self):
        core = self.start(text_reply("one answer"))
        one = core.submit("hi", request_id="client-id")
        two = core.submit("hi", request_id="client-id")
        self.assertEqual(one, two)
        core.run(one)
        core.run(two)
        self.assertEqual(len(self.engine.requests), 1)
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM tasks")["n"], 1)
        with self.assertRaises(ValueError):
            core.submit("different", request_id="client-id")

    def test_ordered_events_checkpoints_and_sqlite_integrity(self):
        core = self.start(tool_reply([("read", "list_dir", {})]), text_reply())
        result = core.run(core.submit("list"))
        events = core.store.events(result["session_id"])
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(len({e["id"] for e in events}), len(events))
        self.assertLess(next(e["sequence"] for e in events if e["kind"] == "tool.execution_intent"),
                        next(e["sequence"] for e in events if e["kind"] == "tool.completed"))
        checkpoint = core.store.one("SELECT * FROM checkpoints ORDER BY rowid DESC LIMIT 1")
        self.assertEqual(checkpoint["task_revision"], core.task(result["task_id"])["revision"])
        self.assertEqual(checkpoint["event_sequence"], events[-1]["sequence"])
        self.assertEqual(core.store.all("PRAGMA foreign_key_check"), [])
        self.assertEqual(next(iter(core.store.one("PRAGMA integrity_check").values())), "ok")

    def test_context_overflow_prevents_request_and_max_turns_prevents_second(self):
        profile = replace(self.profile, context_capacity=300, reserved_completion=100)
        core = self.start(profile=profile)
        result = core.run(core.submit("large" * 100, allowed_tools=[]))
        self.assertEqual(result["status"], "context_overflow")
        self.assertEqual(len(self.engine.requests), 0)
        core.close()
        core = self.start(tool_reply([("read", "list_dir", {})]))
        result = core.run(core.submit("list", max_turns=1))
        self.assertEqual(result["status"], "max_turns")
        self.assertEqual(len(self.engine.requests), 1)

    def test_tool_result_truncation_is_explicit_and_byte_bounded(self):
        encoded = bounded_result({"content": '\\"' * 2000 + "π" * 3000}, 400)
        self.assertLessEqual(len(encoded.encode()), 400)
        self.assertEqual(json.loads(encoded)["status"], "truncated")
        self.assertGreater(json.loads(encoded)["original_bytes"], 400)

    def test_cancel_between_actions_denies_remaining_without_inventing_remote_ack(self):
        core = self.start(tool_reply([("first", "write_file", {"path": "first.txt", "content": "one"}),
                                     ("second", "write_file", {"path": "second.txt", "content": "two"})]))
        core.subscribe(lambda e: core.cancel() if e["kind"] == "tool.completed" else None)
        result = core.run(core.submit("write two"), approval_resolver=lambda *_: True)
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue((self.workspace / "first.txt").exists())
        self.assertFalse((self.workspace / "second.txt").exists())
        self.assertFalse(result["cancellation"]["remote_cancel_confirmed"])
        history = json.loads(core.task(result["task_id"])["history"])
        self.assertEqual(len([m for m in history if m["role"] == "tool"]), 2)

    def test_inference_cancel_quarantines_allocation_across_restart(self):
        core = self.start(text_reply("partial"))
        core.subscribe(lambda e: core.cancel() if e["kind"] == "stream.text" else None)
        result = core.run(core.submit("hi"))
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        core = self.restart(text_reply("resumed"))
        tid = core.submit("new")
        self.assertEqual(core.run(tid)["status"], "paused")
        self.assertEqual(len(self.engine.requests), 0)
        with self.assertRaises(ValueError):
            core.inference.reconcile_idle(lambda *_: False)
        core.inference.reconcile_idle(lambda *_: True)
        self.assertEqual(core.resume(core.task(tid)["session_id"])["status"], "completed")

    def test_stream_payload_limit_is_independent_of_text_packet_size(self):
        core = self.start(profile=replace(self.profile, reserved_completion=256))
        text, reasoning = "x" * 6000, "y" * 1500
        for packet_size in (6000, 64):
            with self.subTest(packet_size=packet_size):
                chunks = [StreamChunk(delta_reasoning=reasoning[i:i + packet_size])
                          for i in range(0, len(reasoning), packet_size)]
                chunks += [StreamChunk(delta_content=text[i:i + packet_size])
                           for i in range(0, len(text), packet_size)]
                chunks += [StreamChunk(finish_reason="stop"), StreamChunk(stream_complete=True)]
                self.engine.replies.append(chunks)
                result = core.run(core.submit("short prompt", allowed_tools=[]))
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["final_answer"], text)
                self.assertEqual(core.inference.allocation()["state"], "idle")

    def test_stream_payload_limit_still_bounds_utf8_reasoning(self):
        core = self.start([StreamChunk(delta_reasoning="π" * 4097)] + text_reply("done"),
                          profile=replace(self.profile, reserved_completion=256))
        result = core.run(core.submit("short prompt", allowed_tools=[]))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        self.assertIn("stream byte allowance", core.store.one("SELECT error FROM inference_attempts")["error"])
        self.assertEqual(core.store.all("SELECT * FROM actions"), [])

    def test_oversized_tool_fragments_are_rejected_before_approval(self):
        core = self.start(tool_reply([("large", "write_file", {"path": "blocked.txt", "content": "z" * 9000})]),
                          profile=replace(self.profile, reserved_completion=256))
        approvals = []
        result = core.run(core.submit("short prompt"), approval_resolver=lambda *args: approvals.append(args) or True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        self.assertEqual(approvals, [])
        self.assertEqual(core.store.all("SELECT * FROM actions"), [])
        self.assertFalse((self.workspace / "blocked.txt").exists())

    def test_empty_stream_packet_prevents_not_started_capacity_release(self):
        def reply():
            yield StreamChunk()
            raise EngineFailure("rejection after streaming began", remote_not_started=True)
        core = self.start(reply())
        result = core.run(core.submit("short prompt", allowed_tools=[]))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        saved = json.loads(core.store.one("SELECT response FROM inference_attempts")["response"])
        self.assertEqual(saved["remote_outcome"], "unknown")

    def test_one_active_allocation_and_profile_change_refusal(self):
        entered, release = threading.Event(), threading.Event()
        core = self.start()
        class BlockingEngine:
            def stream(self, *args):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test did not release inference")
                yield from text_reply()
        core.inference.engine = BlockingEngine()
        tid = core.submit("hi")
        result = []
        thread = threading.Thread(target=lambda: result.append(core.run(tid)))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(AllocationUnavailable):
                core.inference.infer(core.task(tid), self.profile, [], [], CancellationToken())
            with self.assertRaises(ValueError):
                core.select_profile(replace(self.profile, profile_id="other"))
            self.assertEqual(core.store.one("SELECT COUNT(*) n FROM inference_attempts")["n"], 1)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["status"], "completed")

    def test_frozen_prefix_generic_qwen_and_profile_epoch(self):
        profile = replace(self.profile, model="qwen-fixture")
        core = self.start(tool_reply([("read", "list_dir", {})]), text_reply(), profile=profile)
        tid = core.submit("list")
        result = core.run(tid)
        first, second = self.engine.requests
        self.assertEqual(first["messages"][0], second["messages"][0])
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(first["messages"][1]["content"], "list")
        other = replace(profile, profile_id="profile-2")
        core.select_profile(other)
        next_task = core.submit("next", session_id=result["session_id"])
        self.assertEqual(core.task(next_task)["context_epoch"], 1)
        self.assertEqual(core.task(next_task)["profile_id"], "profile-2")

    def test_workspace_lock_state_location_and_schema_fail_closed(self):
        core = self.start()
        with self.assertRaises(RuntimeError):
            RuntimeStore(self.workspace, self.base / "another-state")
        with self.assertRaises(ValueError):
            RuntimeStore(self.workspace, self.workspace / "state")
        core.close()
        self.core = None
        connection = sqlite3.connect(self.directory / "runtime.sqlite3")
        connection.execute("PRAGMA user_version=99")
        connection.commit()
        connection.close()
        with self.assertRaises(ValueError):
            RuntimeStore(self.workspace, self.directory)
        connection = sqlite3.connect(self.directory / "runtime.sqlite3")
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 1)
        connection.close()

    def test_snapshot_corruption_and_conflict_preserve_target(self):
        target = self.workspace / "a.txt"
        target.write_text("original")
        core = self.start(tool_reply([("edit", "edit_file", {"path": "a.txt", "old_str": "original", "new_str": "new"})]), text_reply())
        core.run(core.submit("edit"), approval_resolver=lambda *_: True)
        target.write_text("external")
        result = core.undo_last(approval_callback=lambda *_: True)
        self.assertNotEqual(result["status"], "success")
        self.assertEqual(target.read_text(), "external")
        target.write_text("new")
        snapshot = core.artifacts.latest()
        artifact = core.store.one("SELECT * FROM artifacts WHERE id=?", (snapshot["pre_artifact_id"],))
        (core.artifacts.blobs / artifact["digest"]).write_bytes(b"corrupted")
        result = core.undo_last(approval_callback=lambda *_: True)
        self.assertNotEqual(result["status"], "success")
        self.assertEqual(target.read_text(), "new")

    def test_secret_text_reasoning_and_escaped_arguments_do_not_reach_sinks(self):
        secret = "RUNTIME_SYNTHETIC_SECRET_ABCDE"
        scrubber.register_secret(secret)
        escaped = "".join("\\u%04x" % ord(c) for c in secret)
        reply = [StreamChunk(delta_content=secret[:12], delta_reasoning=secret[:10]),
                 StreamChunk(delta_content=secret[12:], delta_reasoning=secret[10:], tool_call_deltas=[
                     {"index": 0, "id": "secret", "function": {"name": "write_file", "arguments": '{"path":"a.txt","content":"' + escaped + '"}'}}], finish_reason="tool_calls"),
                 StreamChunk(stream_complete=True)]
        core = self.start(reply)
        visible = []
        core.subscribe(visible.append)
        result = core.run(core.submit("do work"), approval_resolver=lambda *_: True)
        self.assertEqual(result["status"], "malformed")
        self.assertFalse((self.workspace / "a.txt").exists())
        self.assertNotIn(secret, json.dumps(visible))
        tables = core.store.all("SELECT name FROM sqlite_master WHERE type='table'")
        for table in tables:
            rows = core.store.all('SELECT * FROM "' + table["name"] + '"')
            self.assertNotIn(secret, json.dumps(rows))
            self.assertNotIn(escaped, json.dumps(rows))

    def test_skill_scope_slash_and_dynamic_loading_cannot_grant_write(self):
        skilldir = self.workspace / "skills" / "reader"
        skilldir.mkdir(parents=True)
        (skilldir / "SKILL.md").write_text("---\nname: reader\nslash_command: /read\nallowed_tools: [inspect_file]\n---\nRead only", encoding="utf-8")
        core = self.start(tool_reply([("write", "write_file", {"path": "bad.txt", "content": "bad"})]), text_reply())
        tid = core.submit("a.txt", skill="/read")
        core.run(tid, approval_resolver=lambda *_: True)
        self.assertEqual(json.loads(core.task(tid)["allowed_tools"]), ["read_file"])
        self.assertFalse((self.workspace / "bad.txt").exists())
        self.engine.replies += [tool_reply([("load", "read_skill", {"skill_name": "reader"}),
                                            ("write", "write_file", {"path": "bad.txt", "content": "bad"})]), text_reply()]
        result = core.run(core.submit("load reader then write"), approval_resolver=lambda *_: True)
        self.assertEqual(result["status"], "completed")
        self.assertFalse((self.workspace / "bad.txt").exists())
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM approvals")["n"], 0)

    def test_skill_manifest_invalid_missing_capability_empty_scope_and_override(self):
        user = self.base / "user-skills"
        user.mkdir()
        (user / "reader.md").write_text("---\nname: Reader\nslash_command: /old\n---\nUser", encoding="utf-8")
        project = self.workspace / "skills"
        project.mkdir()
        (project / "reader.md").write_text("---\nname: reader\nslash_command: /new\nallowed_tools: []\n---\nProject", encoding="utf-8")
        (project / "broken.md").write_text("---\nallowed_tools: write_file\n---\nBad", encoding="utf-8")
        (project / "image.md").write_text("---\nrequired_capabilities: [image_gen]\n---\nImage", encoding="utf-8")
        manager = SkillManager(str(self.workspace), str(user))
        self.assertIsNone(manager.get_skill("/old"))
        self.assertEqual(manager.restrictions(manager.get_skill("/new"), {"write_file"}, {"text"}), frozenset())
        self.assertIsNone(manager.get_skill("broken"))
        self.assertTrue(manager.diagnostics)
        with self.assertRaisesRegex(ValueError, "compatible profile"):
            manager.restrictions(manager.get_skill("image"), {"write_file"}, {"text"})

    def test_reentrant_action_cannot_overwrite_a_completed_receipt(self):
        core = self.start(tool_reply([("write", "write_file", {"path": "a.txt", "content": "one"})]), text_reply())
        def approve(*_):
            action = core.store.one("SELECT id FROM actions ORDER BY rowid DESC LIMIT 1")
            with self.assertRaisesRegex(RuntimeError, "re-enter"):
                core.tool_broker.execute(action["id"], resolver=lambda *_: True)
            return True
        result = core.run(core.submit("write once"), approval_resolver=approve)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM approvals")["n"], 1)
        self.assertEqual(core.store.one("SELECT state FROM actions")["state"], "completed")
        self.assertEqual((self.workspace / "a.txt").read_text(), "one")

    def test_stream_byte_limit_stops_untrusted_output_without_proposals(self):
        core = self.start([StreamChunk(delta_content="X" * 70000)])
        result = core.run(core.submit("hi"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(core.inference.allocation()["state"], "quarantined")
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM actions")["n"], 0)
        self.assertIn("byte allowance", core.store.events(result["session_id"])[-1]["payload"]["detail"])

    def test_legacy_undo_remains_readable_and_runs_through_durable_approval(self):
        from harness.storage.undo import UndoManager
        target = self.workspace / "legacy.txt"
        target.write_text("old")
        old = UndoManager(str(self.workspace), str(self.base / "legacy"))
        snapshot = old.record_pre_change("legacy.txt")
        target.write_text("new")
        old.record_post_change(snapshot, "old -> new")
        original = old.history_file.read_bytes()
        core = self.start()
        core.attach_legacy_undo(old)
        self.assertEqual(old.history_file.read_bytes(), original)
        self.assertEqual(core.get_last_diff(), "old -> new")
        self.assertEqual(core.undo_last()["status"], "rejected")
        self.assertEqual(target.read_text(), "new")
        self.assertEqual(old.history_file.read_bytes(), original)
        self.assertEqual(core.undo_last(approval_callback=lambda *_: True)["status"], "success")
        self.assertEqual(target.read_text(), "old")
        self.assertEqual(len(self.engine.requests), 0)
        self.assertEqual(core.store.one("SELECT COUNT(*) n FROM actions")["n"], 2)

    def test_empty_skill_list_shows_invalid_manifest_diagnostic(self):
        project = self.workspace / "skills"
        project.mkdir()
        (project / "bad.md").write_text("---\nallowed_tools: write_file\n---\nBad", encoding="utf-8")
        manager = SkillManager(str(self.workspace), str(self.base / "missing-user"))
        self.assertIn("Invalid skill", manager.format_skills_list())

    def test_image_facade_uses_single_allocation_and_retains_completed_session(self):
        from harness.cli.core_client import CoreClient
        core = self.start()
        class ImageFixture:
            server_url = "http://127.0.0.1:1"
            calls = 0
            def generate_image(provider, prompt):
                self.assertEqual(core.inference.allocation()["state"], "active")
                provider.calls += 1
                target = self.workspace / "image.png"
                target.write_bytes(b"fixture image bytes")
                return {"file_path": str(target), "job_id": "fixture-job"}
        provider = ImageFixture()
        core.image_provider = provider
        client = CoreClient(core)
        result = client.generate_image("fixture image")
        self.assertTrue(Path(result["file_path"]).is_file())
        self.assertEqual(provider.calls, 1)
        session = core.list_sessions()[0]
        self.assertEqual(core.resume(session["id"])["status"], "completed")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(core.inference.allocation()["state"], "idle")
        with self.assertRaises(ValueError):
            client.server_url = "file:///outside"
        core._run_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                client.generate_image("second")
        finally:
            core._run_lock.release()
        self.assertEqual(provider.calls, 1)

    def test_restore_approval_preview_identifies_target_and_deletion(self):
        core = self.start(tool_reply([("new", "write_file", {"path": "new.txt", "content": "one"})]), text_reply())
        core.run(core.submit("write"), approval_resolver=lambda *_: True)
        previews = []
        result = core.undo_last(approval_callback=lambda name, args: previews.append(args) or False)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(previews[0]["path"], "new.txt")
        self.assertEqual(previews[0]["operation"], "delete file created by the task")
        self.assertIsNone(previews[0]["pre_hash"])
        self.assertTrue(previews[0]["expected_current_hash"])
        self.assertTrue((self.workspace / "new.txt").is_file())

    def test_unscrubbed_legacy_restore_metadata_is_redacted_at_approval_sink(self):
        from harness.storage.undo import UndoManager
        target = self.workspace / "old.txt"
        target.write_text("old")
        manager = UndoManager(str(self.workspace), str(self.base / "legacy"))
        snapshot = manager.record_pre_change("old.txt")
        target.write_text("new")
        manager.record_post_change(snapshot)
        secret = "LEGACY_SYNTHETIC_PREVIEW_CREDENTIAL_ABCDE"
        scrubber.register_secret(secret)
        data = json.loads(manager.history_file.read_text())
        data[-1]["diff"] = secret  # Simulate a historical, unsanitized user ledger.
        manager.history_file.write_text(json.dumps(data), encoding="utf-8")
        manager = UndoManager(str(self.workspace), str(self.base / "legacy"))
        original = manager.history_file.read_bytes()
        core = self.start()
        core.attach_legacy_undo(manager)
        previews = []
        result = core.undo_last(approval_callback=lambda n, a: previews.append(a) or False)
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn(secret, json.dumps(previews))
        self.assertEqual(manager.history_file.read_bytes(), original)
        self.assertEqual(target.read_text(), "new")


if __name__ == "__main__":
    unittest.main()
