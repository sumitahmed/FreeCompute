"""HTTP clients drive the existing Core, including real approval-gated demo tools."""
import http.client
import json
from pathlib import Path
import tempfile
import time
import unittest

from harness.api.demo import create_demo
from harness.api.server import APIServer, PREFIX


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-api-test-")
        self.workspace = Path(self.temp.name) / "workspace"
        self.state_dir = Path(self.temp.name) / "state"
        self.server = None
        self.start()

    def start(self):
        core = create_demo(self.workspace, state_dir=self.state_dir, delay=0.003)
        self.server = APIServer(core, port=0, simulated=True).start()
        self.port = self.server.server_address[1]
        self.cookie = self.csrf = None

    def tearDown(self):
        if self.server:
            self.server.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, *, auth=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        request_headers = {"Content-Type": "application/json"}
        if auth:
            request_headers["Authorization"] = "Bearer " + self.server.token
        request_headers.update(headers or {})
        connection.request(method, path if path.startswith("/") else PREFIX + "/" + path,
                           json.dumps(body) if body is not None else None, request_headers)
        response = connection.getresponse()
        data, response_headers, status = json.loads(response.read()), dict(response.getheaders()), response.status
        connection.close()
        return status, data, response_headers

    def login(self):
        status, data, headers = self.request("POST", "auth/session", {"token": self.server.token}, auth=False,
                                            headers={"Origin": self.server.origin})
        self.assertEqual(status, 200)
        self.cookie, self.csrf = headers["Set-Cookie"].split(";")[0], data["csrf"]

    def session(self):
        status, data, _ = self.request("POST", "sessions", {})
        self.assertEqual(status, 201)
        return data["session"]["id"]

    def submit(self, prompt="hello", sid=None, request_id="request-1", **kwargs):
        status, data, _ = self.request("POST", "tasks", {"prompt": prompt, "session_id": sid or self.session(), "request_id": request_id, **kwargs})
        self.assertEqual(status, 202, data)
        return data

    def until(self, condition, timeout=8):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = condition()
            if result:
                return result
            time.sleep(0.02)
        self.fail("Condition did not become true")

    def task_state(self, task_id, state):
        data = self.request("GET", "tasks/" + task_id)[1]
        return data if data.get("state") == state else None

    def pending(self, tool=None):
        values = self.request("GET", "approvals")[1]
        if tool:
            values = [value for value in values if value["tool"] == tool]
        return values[0] if values else None

    def decision(self, approval, decision=True, **override):
        body = {key: approval[key] for key in ("action_revision", "task_revision", "arguments_hash", "target_hash")}
        body.update(decision=decision, **override)
        return self.request("POST", f"approvals/{approval['id']}/decision", body)

    def test_authentication_cookie_csrf_and_logout(self):
        self.assertEqual(self.request("GET", "sessions", auth=False)[0], 401)
        self.assertEqual(self.request("POST", "auth/session", {"token": "incorrect-local-token-value"}, auth=False)[0], 401)
        self.login()
        self.assertIn("HttpOnly", self.request("POST", "auth/session", {"token": self.server.token})[2]["Set-Cookie"])
        headers = {"Cookie": self.cookie, "Origin": self.server.origin}
        self.assertEqual(self.request("POST", "sessions", {}, auth=False, headers=headers)[0], 403)
        headers["X-FreeCompute-CSRF"] = self.csrf
        self.assertEqual(self.request("POST", "sessions", {}, auth=False, headers=headers)[0], 201)
        self.assertEqual(self.request("POST", "auth/logout", {}, auth=False, headers=headers)[0], 200)
        self.assertEqual(self.request("GET", "sessions", auth=False, headers=headers)[0], 401)

    def test_origin_host_and_public_listener_rejected(self):
        for headers in ({"Origin": "https://attacker.example"}, {"Host": "attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("GET", "status", headers=headers)[0], 403)
        with self.assertRaises(ValueError):
            APIServer(self.server.core, host="0.0.0.0")

    def test_malformed_and_mass_assignment_body_rejected(self):
        for body in ({"profile_id": []}, {"id": "frontend-id"}, {"profile_id": "missing"}):
            self.assertEqual(self.request("POST", "sessions", body)[0], 400)
        self.assertEqual(self.request("POST", "tasks", {"prompt": "x"})[0], 400)
        self.assertEqual(self.request("POST", "reconcile/inference", {"confirmed_idle": 1})[0], 400)

    def test_registry_defaults_and_unsupported_worker(self):
        workers = self.request("GET", "workers")[1]
        profiles = self.request("GET", "profiles")[1]
        self.assertEqual(len(workers), 2)
        self.assertTrue(all(w["last_seen"] and w["observed_resources"]["source"].startswith("SIMULATED") for w in workers))
        self.assertEqual({p["profile_id"] for p in profiles}, {"demo-code", "demo-chat"})
        self.assertEqual(self.request("POST", "defaults", {"profile_id": "demo-code", "worker_id": "demo-chat-worker"})[0], 400)
        self.assertEqual(self.request("POST", "defaults", {"profile_id": "demo-chat", "worker_id": "demo-chat-worker"})[0], 200)
        self.assertEqual(self.request("GET", "status")[1]["default_profile"], "demo-chat")

    def test_empty_session_and_submit_idempotency_persist(self):
        sid = self.session()
        self.assertEqual(self.request("GET", "sessions/" + sid)[1]["tasks"], [])
        task = self.submit(sid=sid)
        second = self.submit(sid=sid)
        self.assertEqual(second["id"], task["id"])
        self.until(lambda: self.task_state(task["id"], "completed"))
        self.server.close()
        self.server = None
        self.start()
        snapshot = self.request("GET", "sessions/" + sid)[1]
        self.assertEqual(snapshot["tasks"][0]["id"], task["id"])
        self.assertIn("SIMULATED", snapshot["tasks"][0]["final_answer"])
        self.assertEqual(self.request("POST", f"tasks/{task['id']}/resume", {})[0], 202)

    def test_events_ordered_page_and_cursor_validation(self):
        task = self.submit()
        self.until(lambda: self.task_state(task["id"], "completed"))
        path = f"sessions/{task['session_id']}/events"
        events = self.request("GET", path)[1]["events"]
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        replay = self.request("GET", path + "?after=3")[1]["events"]
        self.assertEqual(replay, events[3:])
        self.assertEqual(self.request("GET", path + "?after=99999")[0], 400)
        self.assertEqual(self.request("GET", path + "?after=-1")[0], 400)

    def test_sse_replay_and_detach_does_not_cancel(self):
        task = self.submit("[demo:long]")
        self.until(lambda: self.task_state(task["id"], "running"))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", PREFIX + f"/sessions/{task['session_id']}/events", headers={
            "Authorization": "Bearer " + self.server.token, "Accept": "text/event-stream", "Last-Event-ID": "1"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline().decode().strip(), "id: 2")
        response.close()
        connection.close()
        self.assertEqual(self.request("GET", "tasks/" + task["id"])[1]["cancellation"]["requested"], False)
        self.request("POST", f"tasks/{task['id']}/cancel", {})
        self.until(lambda: self.task_state(task["id"], "cancelled"))

    def test_missing_viewer_never_approves_and_denial_is_receipted(self):
        task = self.submit("[demo:edit]")
        approval = self.until(self.pending)
        time.sleep(0.05)
        self.assertIn("//", (self.workspace / "calculator.py").read_text())
        self.assertEqual(self.request("GET", "tasks/" + task["id"])[1]["state"], "waiting_approval")
        self.assertEqual(approval["tool"], "edit_file")
        self.assertIn("-return a // b", approval["diff"])
        self.assertEqual(self.decision(approval, False)[0], 202)
        command = self.until(lambda: self.pending("run_command"))
        self.assertEqual(command["tool"], "run_command")
        self.decision(command, False)
        final = self.until(lambda: self.task_state(task["id"], "completed"))
        self.assertIn("not confirmed", final["final_answer"])

    def test_approved_edit_command_receipts_and_refresh(self):
        task = self.submit("[demo:edit]")
        for name in ("edit_file", "run_command"):
            approval = self.until(self.pending)
            self.assertEqual(approval["tool"], name)
            self.assertEqual(self.decision(approval)[0], 202)
            self.until(lambda: not any(a["id"] == approval["id"] for a in self.request("GET", "approvals")[1]))
        self.until(lambda: self.task_state(task["id"], "completed"))
        self.assertIn("a / b", (self.workspace / "calculator.py").read_text())
        actions = self.request("GET", "actions?task_id=" + task["id"])[1]
        command = next(a for a in actions if a["name"] == "run_command")
        self.assertEqual(command["result"]["exit_code"], 0)
        self.assertIn("Ran 2 tests", command["result"]["stderr"])
        self.assertIn("final_answer", self.request("GET", "sessions/" + task["session_id"])[1]["tasks"][0])

    def test_stale_revision_and_file_witness_fail_closed(self):
        task = self.submit("[demo:edit]")
        approval = self.until(self.pending)
        self.assertEqual(self.decision(approval, action_revision=approval["action_revision"] + 1)[0], 409)
        (self.workspace / "calculator.py").write_text("# changed externally\n")
        self.assertEqual(self.decision(approval)[0], 202)
        self.assertEqual(self.decision(approval)[0], 409)
        command = self.until(lambda: self.pending("run_command"))
        self.decision(command, False)
        self.until(lambda: self.task_state(task["id"], "completed"))
        decided = [e for e in self.server.core.views.events(task["session_id"]) if e["kind"] == "approval.decided"]
        self.assertFalse(decided[0]["payload"]["binding_valid"])
        self.assertEqual((self.workspace / "calculator.py").read_text(), "# changed externally\n")

    def test_cancel_records_local_stop_and_quarantined_unknown(self):
        task = self.submit("[demo:long]")
        self.until(lambda: self.server.core.views.leases())
        self.request("POST", f"tasks/{task['id']}/cancel", {})
        final = self.until(lambda: self.task_state(task["id"], "cancelled"))
        self.assertTrue(final["cancellation"]["local_stop_confirmed"])
        self.assertFalse(final["cancellation"]["remote_cancel_confirmed"])
        self.assertEqual(final["cancellation"]["remote_outcome"], "unknown")
        lease = self.server.core.views.leases()[0]
        self.assertEqual(lease["state"], "quarantined")
        self.assertEqual(self.request("POST", "reconcile/inference", {"lease_id": lease["id"], "confirmed_idle": False})[0], 400)
        self.assertEqual(self.request("POST", "reconcile/inference", {"lease_id": lease["id"], "confirmed_idle": True})[0], 200)
        self.assertEqual(self.server.core.views.leases(), [])

    def test_disconnected_worker_waits_and_queued_cancel_is_local(self):
        self.request("POST", "demo/worker", {"connected": False})
        task = self.submit()
        self.until(lambda: self.task_state(task["id"], "queued"))
        queue = self.request("GET", "queue")[1]
        self.assertTrue(queue["jobs"])
        self.assertFalse(queue["leases"])
        self.request("POST", f"tasks/{task['id']}/cancel", {})
        final = self.until(lambda: self.task_state(task["id"], "cancelled"))
        self.assertEqual(final["cancellation"]["remote_outcome"], "not_started")

    def test_disconnect_reconnect_dispatches_without_new_task(self):
        self.request("POST", "demo/worker", {"connected": False})
        task = self.submit()
        self.until(lambda: self.task_state(task["id"], "queued"))
        self.request("POST", "demo/worker", {"connected": True})
        self.until(lambda: self.task_state(task["id"], "completed"))
        self.assertEqual(len(self.request("GET", "tasks")[1]), 1)

    def test_context_overflow_and_engine_failure_are_truthful(self):
        task = self.submit("x" * 25000, profile_id="demo-chat", worker_id="demo-chat-worker")
        self.until(lambda: self.task_state(task["id"], "context_overflow"))
        failure = self.submit("[demo:failure]", request_id="failure-request")
        self.until(lambda: self.task_state(failure["id"], "failed"))
        events = self.server.core.views.events(failure["session_id"])
        self.assertTrue(any("authentication failure" in str(e["payload"]) for e in events))
        self.assertFalse(self.server.core.views.leases())

    def test_old_task_resume_does_not_resume_new_current_task(self):
        task = self.submit()
        self.until(lambda: self.task_state(task["id"], "completed"))
        newer = self.submit(sid=task["session_id"], request_id="newer")
        self.until(lambda: self.task_state(newer["id"], "completed"))
        self.assertEqual(self.request("POST", f"tasks/{task['id']}/resume", {})[0], 409)


if __name__ == "__main__":
    unittest.main()
