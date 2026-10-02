"""Deterministic worker routing, real SQLite leases and local core integration."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from harness.core.client import CancellationToken
from harness.core.inference import AllocationUnavailable
from harness.core.models import RemoteHealth, StreamChunk
from harness.core.runtime_models import ModelProfile, Worker
from harness.core.scheduler import QueueWaiting
from harness.core.service import CoreService
from harness.security import scrubber


TEXT = frozenset({"text", "code_tools"})
SMALL = ModelProfile("small", "local-small", "small-fixture", "fixture", TEXT)
QWEN = ModelProfile("qwen", model="Qwen-27B-fixture", engine="fixture", capabilities=TEXT,
                    resource_requirements=frozenset({"gpu0", "gpu1"}), verification="fixture-tested")
IMAGE = ModelProfile("image", model="image-fixture", engine="ComfyUI", capabilities=frozenset({"image_gen"}),
                     resource_requirements=frozenset({"gpu0"}))
KAGGLE = Worker("kaggle-qwen", "kaggle", "fixture", TEXT, resource_pool="kaggle-dual-t4", resources=QWEN.resource_requirements)
IMAGE_WORKER = Worker("image-worker", "private", "ComfyUI", IMAGE.capabilities, resource_pool="image-host", resources=IMAGE.resource_requirements)


class FakeEngine:
    def __init__(self, capabilities=TEXT):
        self.capabilities = capabilities
        self.calls, self.health_calls = [], 0
        self.health, self.models, self.failure = "healthy", None, None
        self.complete, self.block, self.entered = True, None, threading.Event()

    def get_capabilities(self):
        return self.capabilities

    def get_health(self):
        self.health_calls += 1
        if isinstance(self.health, Exception):
            raise self.health
        return RemoteHealth(self.health, 0, 0, 0, 0, raw={} if self.models is None else {"models": self.models})

    def stream(self, profile, messages, tools, cancellation):
        self.calls.append(profile.profile_id)
        self.entered.set()
        if self.block and not self.block.wait(5):
            raise AssertionError("fixture was not released")
        if self.failure:
            raise self.failure
        yield StreamChunk(delta_content=profile.model + " answer", finish_reason="stop")
        if self.complete:
            yield StreamChunk(stream_complete=True)

    def generate(self, profile, prompt, cancellation):
        self.calls.append(profile.profile_id)
        return {"file_path": "fixture-image.png", "job_id": "fake-job"}


class WorkerSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fc-v1-workers-")
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.start()

    def start(self):
        self.local, self.qwen, self.image = FakeEngine(), FakeEngine(), FakeEngine(IMAGE.capabilities)
        self.core = CoreService(self.workspace, self.local, SMALL, state_dir=self.base / "state", system_prompt="fixture")
        self.core.attach_worker(KAGGLE, [QWEN], self.qwen)
        self.core.attach_worker(IMAGE_WORKER, [IMAGE], self.image)

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()

    def submit(self, profile=SMALL, worker=None, **kwargs):
        return self.core.submit("fixture request", profile_id=profile.profile_id, worker_id=worker, allowed_tools=[], **kwargs)

    def claim(self, task_id):
        job = self.core.store.one("SELECT * FROM inference_queue WHERE task_id=? ORDER BY sequence DESC", (task_id,))
        self.core.registry.refresh_candidates(job["profile_id"], job["requested_worker"])
        with self.core.store.transaction() as db:
            lease, reason, quarantined = self.core.scheduler.claim(db, job["id"])
            return lease, reason, quarantined

    def release(self, lease, confirmed=True):
        with self.core.store.transaction() as db:
            self.core.scheduler.finish(db, lease["id"], confirmed=confirmed)
            self.core.scheduler.sync_allocation(db)

    def test_correct_local_kaggle_and_image_routing(self):
        self.assertEqual(self.core.run(self.submit())["status"], "completed")
        self.assertEqual(self.core.run(self.submit(QWEN))["final_answer"], "Qwen-27B-fixture answer")
        task_id = self.core.sessions.submit("image", IMAGE, "image", [], [], operation="image")
        task = self.core.task(task_id)
        result = self.core.inference.image(task, IMAGE, "image", CancellationToken())
        self.assertEqual(result["job_id"], "fake-job")
        self.assertEqual(self.local.calls, ["small"])
        self.assertEqual(self.qwen.calls, ["qwen"])
        self.assertEqual(self.image.calls, ["image"])
        events = self.core.store.all("SELECT payload FROM events WHERE kind='model.requested'")
        self.assertEqual([json.loads(e["payload"])["worker_id"] for e in events], ["local-small", "kaggle-qwen", "image-worker"])

    def test_one_model_profile_can_route_to_two_workers(self):
        alternate = replace(KAGGLE, worker_id="private-qwen", location="private", resource_pool="private-dual-t4")
        engine = FakeEngine()
        self.core.attach_worker(alternate, [QWEN], engine)
        self.assertEqual(QWEN.worker_id, "")
        self.assertEqual(self.core.run(self.submit(QWEN, "private-qwen"))["status"], "completed")
        self.assertEqual(engine.calls, ["qwen"])
        self.assertEqual(self.qwen.calls, [])

    def test_capability_and_route_mismatch_rejected_before_dispatch(self):
        with self.assertRaises(ValueError):
            self.submit(IMAGE)
        with self.assertRaises(ValueError):
            self.submit(QWEN, "local-small")
        task_id = self.submit(QWEN)
        with self.assertRaises(ValueError):
            self.core.scheduler.enqueue(self.core.task(task_id), QWEN, {"image_gen"})
        self.assertEqual(self.local.calls + self.qwen.calls + self.image.calls, [])

    def test_plain_text_profile_does_not_gain_tools(self):
        profile = ModelProfile("plain", model="plain", engine="fixture", capabilities=frozenset({"text"}))
        engine = FakeEngine(profile.capabilities)
        self.core.attach_worker(Worker("plain-worker", "local", "fixture", profile.capabilities), [profile], engine)
        with self.assertRaises(ValueError):
            self.core.submit("edit", profile_id="plain", allowed_tools=["write_file"])
        task_id = self.core.submit("chat", profile_id="plain")
        self.assertEqual(json.loads(self.core.task(task_id)["allowed_tools"]), [])
        self.assertEqual(self.core.run(task_id)["status"], "completed")

    def test_busy_worker_waits_then_runs_without_early_inference(self):
        first, second = self.submit(QWEN), self.submit(QWEN)
        lease, _, _ = self.claim(first)
        self.assertIsNotNone(lease)
        self.assertEqual(self.core.run(second)["status"], "queued")
        self.assertEqual(self.qwen.calls, [])
        self.release(lease)
        self.assertEqual(self.core.run_next()["task_id"], second)
        self.assertEqual(self.qwen.calls, ["qwen"])

    def test_fifo_skips_requests_whose_worker_is_busy(self):
        held = self.submit(QWEN)
        lease, _, _ = self.claim(held)
        waiting, local = self.submit(QWEN), self.submit()
        result = self.core.run_next()
        self.assertEqual(result["task_id"], local)
        self.assertEqual(self.core.task(waiting)["state"], "queued")
        self.release(lease)
        self.assertEqual(self.core.run_next()["task_id"], waiting)

    def test_fifo_does_not_allow_newer_ready_request_to_jump_queue(self):
        first, second = self.submit(), self.submit()
        self.assertEqual(self.core.run(second)["status"], "queued")
        self.assertEqual(self.local.calls, [])
        self.assertEqual(self.core.run_next()["task_id"], first)
        self.assertEqual(self.core.run_next()["task_id"], second)

    def test_two_gpu_model_blocks_alias_using_one_shared_gpu(self):
        alias = replace(IMAGE_WORKER, worker_id="kaggle-image", location="kaggle", resource_pool=KAGGLE.resource_pool)
        self.core.attach_worker(alias, [IMAGE], FakeEngine(IMAGE.capabilities))
        first = self.submit(QWEN)
        lease, _, _ = self.claim(first)
        image_task = self.core.sessions.submit("image", IMAGE, "image", [], [], operation="image", requested_worker=alias.worker_id)
        blocked, reason, _ = self.claim(image_task)
        self.assertIsNone(blocked)
        self.assertIn("shared resources", reason)
        claims = self.core.store.all("SELECT * FROM resource_claims WHERE lease_id=?", (lease["id"],))
        self.assertEqual({c["resource_id"] for c in claims}, {"gpu0", "gpu1"})
        self.release(lease)
        self.assertIsNotNone(self.claim(image_task)[0])

    def test_parallel_admission_cannot_exceed_worker_concurrency(self):
        profile = ModelProfile("many", model="many", engine="fixture", capabilities=TEXT)
        worker = Worker("many-worker", "private", "fixture", TEXT, concurrency_limit=2)
        self.core.attach_worker(worker, [profile], FakeEngine())
        tasks = [self.submit(profile) for _ in range(8)]
        self.core.registry.refresh(worker.worker_id)
        barrier, outcomes = threading.Barrier(8), []
        def claim(task_id):
            barrier.wait(5)
            outcomes.append(self.claim(task_id)[0])
        threads = [threading.Thread(target=claim, args=(t,)) for t in tasks]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertLessEqual(len([x for x in outcomes if x]), 2)
        active = self.core.store.one("SELECT COUNT(*) n FROM inference_leases WHERE worker_id=? AND state='active'", (worker.worker_id,))["n"]
        self.assertEqual(active, len([x for x in outcomes if x]))
        self.assertGreater(active, 0)

    def test_declared_two_slots_allow_two_actual_inferences_and_queue_third(self):
        profile = ModelProfile("parallel", model="parallel", engine="fixture", capabilities=TEXT)
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeEngine):
            def stream(engine, *args):
                engine.calls.append("parallel")
                if len(engine.calls) == 2:
                    entered.set()
                if not release.wait(5):
                    raise AssertionError("fixture was not released")
                yield StreamChunk(delta_content="done", finish_reason="stop")
                yield StreamChunk(stream_complete=True)
        engine = Blocking()
        self.core.attach_worker(Worker("parallel-worker", "private", "fixture", TEXT, concurrency_limit=2), [profile], engine)
        tasks = [self.submit(profile) for _ in range(3)]
        outcomes = []
        def infer(task_id):
            outcomes.append(self.core.inference.infer(self.core.task(task_id), profile, [], [], CancellationToken()))
        first = threading.Thread(target=infer, args=(tasks[0],))
        second = threading.Thread(target=infer, args=(tasks[1],))
        first.start()
        deadline = time.monotonic() + 3
        while not engine.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        second.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.core.store.one("SELECT COUNT(*) n FROM inference_leases WHERE state='active'")["n"], 2)
            with self.assertRaises(QueueWaiting):
                self.core.inference.infer(self.core.task(tasks[2]), profile, [], [], CancellationToken())
        finally:
            release.set()
            first.join(5)
            second.join(5)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(engine.calls, ["parallel", "parallel"])
        self.assertEqual(self.core.inference.allocation()["state"], "idle")

    def test_local_core_busy_submission_waits_without_concurrent_tool_loop(self):
        entered, release = threading.Event(), threading.Event()
        self.local.block, self.local.entered = release, entered
        first = self.submit()
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(self.core.run(first)))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            second = self.submit(QWEN)
            self.assertEqual(self.core.run(second)["status"], "queued")
            self.assertEqual(self.qwen.calls, [])
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(outcomes[0]["status"], "completed")
        self.assertEqual(self.core.run_next()["task_id"], second)

    def test_submission_queue_failure_rolls_back_task_command_and_events(self):
        original = self.core.sessions.queue_writer
        def failure(*args):
            original(*args)
            raise RuntimeError("fixture failure after queue insert")
        self.core.sessions.queue_writer = failure
        with self.assertRaises(RuntimeError):
            self.submit(QWEN)
        for table in ("tasks", "sessions", "commands", "events", "checkpoints", "inference_queue"):
            self.assertEqual(self.core.store.one('SELECT COUNT(*) n FROM "' + table + '"')["n"], 0)

    def test_cancel_after_admission_before_dispatch_releases_without_calling_engine(self):
        self.core.subscribe(lambda e: self.core.cancel() if e["kind"] == "queue.assigned" else None)
        result = self.core.run(self.submit(QWEN))
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.qwen.calls, [])
        self.assertEqual(self.core.inference.allocation()["state"], "idle")
        self.assertEqual(self.core.store.all("SELECT * FROM resource_claims"), [])

    def test_late_cancel_cannot_change_committed_completed_task(self):
        self.core.subscribe(lambda e: self.core.cancel() if e["kind"] == "task.completed" else None)
        result = self.core.run(self.submit())
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["is_cancelled"])

    def test_unhealthy_worker_waits_and_reconnects(self):
        self.qwen.health = ConnectionError("fixture disconnected")
        task_id = self.submit(QWEN)
        self.assertEqual(self.core.run(task_id)["status"], "queued")
        self.assertEqual(self.qwen.calls, [])
        self.qwen.health = "healthy"
        self.assertEqual(self.core.run_next()["status"], "completed")

    def test_health_expiry_and_missing_model_are_not_eligible(self):
        now = [time.time()]
        self.core.registry.clock = lambda: now[0]
        self.core.registry.refresh(KAGGLE.worker_id)
        now[0] += 31
        self.assertEqual(next(w for w in self.core.list_workers() if w["worker_id"] == KAGGLE.worker_id)["health"], "stale")
        self.qwen.models = ["different-model"]
        task_id = self.submit(QWEN)
        self.assertEqual(self.core.run(task_id)["status"], "queued")
        self.assertEqual(self.qwen.calls, [])
        self.qwen.models = [QWEN.model]
        self.core.registry.refresh(KAGGLE.worker_id)
        self.assertEqual(self.core.run_next()["status"], "completed")

    def test_detached_worker_keeps_task_until_local_reattachment(self):
        task_id = self.submit(QWEN)
        self.core.registry.engines.pop(KAGGLE.worker_id)
        self.assertEqual(self.core.run(task_id)["status"], "queued")
        self.core.attach_worker(KAGGLE, [QWEN], self.qwen)
        self.assertEqual(self.core.run_next()["task_id"], task_id)

    def test_queued_cancellation_is_durable_and_never_dispatches(self):
        task_id = self.submit(QWEN)
        self.core.cancel(task_id)
        self.assertEqual(self.core.task(task_id)["state"], "cancelled")
        self.core.close()
        self.start()
        self.assertEqual(self.core.run(task_id)["status"], "cancelled")
        self.assertEqual(self.qwen.calls, [])
        self.assertEqual(self.core.list_queue(), [])

    def test_queue_survives_restart_in_original_order(self):
        first, second = self.submit(QWEN), self.submit()
        before = [(q["id"], q["sequence"]) for q in self.core.list_queue()]
        self.core.close()
        self.start()
        self.assertEqual([(q["id"], q["sequence"]) for q in self.core.list_queue()], before)
        self.assertEqual(self.core.run_next()["task_id"], first)
        self.assertEqual(self.core.run_next()["task_id"], second)

    def test_timeout_keeps_resources_after_worker_reconnect(self):
        self.qwen.failure = TimeoutError("fixture inference timeout")
        first = self.submit(QWEN)
        self.assertEqual(self.core.run(first)["status"], "failed")
        self.assertEqual(self.core.inference.allocation()["state"], "quarantined")
        self.assertEqual(len(self.core.store.all("SELECT * FROM resource_claims")), 2)
        self.qwen.failure = None
        self.core.registry.refresh(KAGGLE.worker_id)
        second = self.submit(QWEN)
        self.assertEqual(self.core.run(second)["status"], "paused")
        self.assertEqual(self.qwen.calls, ["qwen"])
        with self.assertRaises(ValueError):
            self.core.inference.reconcile_idle(lambda *_: False)
        self.core.inference.reconcile_idle(lambda *_: True)
        self.assertEqual(self.core.run(second)["status"], "completed")

    def test_incomplete_stream_has_no_success_and_keeps_two_gpu_claims(self):
        self.qwen.complete = False
        result = self.core.run(self.submit(QWEN))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["final_answer"], "")
        self.assertEqual(len(self.core.store.all("SELECT * FROM resource_claims")), 2)

    def test_running_cancellation_never_fakes_remote_ack(self):
        remove = self.core.subscribe(lambda e: self.core.cancel() if e["kind"] == "stream.text" else None)
        result = self.core.run(self.submit(QWEN))
        remove()
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["cancellation"]["remote_cancel_confirmed"])
        self.assertEqual(len(self.core.store.all("SELECT * FROM resource_claims")), 2)

    def test_restart_quarantines_active_lease_and_does_not_repeat_inference(self):
        task_id = self.submit(QWEN)
        lease, _, _ = self.claim(task_id)
        self.core.close()
        self.start()
        self.assertEqual(self.core.inference.allocation()["state"], "quarantined")
        self.assertEqual(self.core.run(task_id)["status"], "paused")
        self.assertEqual(self.qwen.calls, [])
        self.core.inference.reconcile_idle(lambda *_: True, lease["id"])
        self.assertEqual(self.core.run(task_id)["status"], "completed")

    def test_two_unknown_workers_require_separate_idle_confirmations(self):
        first, second = self.submit(QWEN), self.submit()
        qwen_lease, _, _ = self.claim(first)
        local_lease, _, _ = self.claim(second)
        self.release(qwen_lease, False)
        self.release(local_lease, False)
        with self.assertRaises(ValueError):
            self.core.inference.reconcile_idle(lambda *_: True)
        seen = []
        self.core.inference.reconcile_idle(lambda n, p: seen.append(p) or True, qwen_lease["id"])
        self.assertEqual(seen[0]["worker_id"], KAGGLE.worker_id)
        self.assertEqual(self.core.inference.allocation()["state"], "quarantined")
        self.assertEqual({l["id"] for l in self.core.inference.allocation()["leases"]}, {local_lease["id"]})

    def test_live_worker_capacity_resources_and_model_identity_cannot_be_redefined(self):
        task_id = self.submit(QWEN)
        self.claim(task_id)
        with self.assertRaises(ValueError):
            self.core.attach_worker(replace(KAGGLE, concurrency_limit=2), [QWEN], self.qwen)
        with self.assertRaises(ValueError):
            self.core.attach_worker(KAGGLE, [replace(QWEN, model="changed")], self.qwen)
        self.assertEqual(self.core.registry.profile(QWEN.profile_id).model, QWEN.model)

    def test_default_selection_does_not_rebind_queued_task(self):
        task_id = self.submit(QWEN, KAGGLE.worker_id)
        before = self.core.task(task_id)
        self.core.select_model("qwen", KAGGLE.worker_id)
        self.core.select_model("small", "local-small")
        after = self.core.task(task_id)
        self.assertEqual((after["profile_id"], after["context_epoch"], after["driver"]),
                         (before["profile_id"], before["context_epoch"], before["driver"]))
        self.assertEqual(self.core.scheduler.requested_worker(task_id), KAGGLE.worker_id)

    def test_unknown_remote_worker_does_not_block_healthy_independent_worker(self):
        self.qwen.failure = TimeoutError("fixture timeout")
        self.core.run(self.submit(QWEN))
        self.core.select_model("small", "local-small")
        result = self.core.run(self.submit())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.core.inference.allocation()["state"], "quarantined")
        self.assertEqual(len(self.core.store.all("SELECT * FROM resource_claims")), 2)

    def test_idempotent_submission_binds_worker_route_and_stays_one_queue_entry(self):
        task_id = self.submit(QWEN, KAGGLE.worker_id, request_id="request")
        self.assertEqual(self.submit(QWEN, KAGGLE.worker_id, request_id="request"), task_id)
        alternate = replace(KAGGLE, worker_id="other-qwen", resource_pool="other-host")
        self.core.attach_worker(alternate, [QWEN], FakeEngine())
        with self.assertRaises(ValueError):
            self.submit(QWEN, alternate.worker_id, request_id="request")
        self.assertEqual(len(self.core.list_queue()), 1)

    def test_registered_secrets_do_not_reach_worker_observations_or_events(self):
        secret = "SCHEDULER_SYNTHETIC_CREDENTIAL_ABCDE"
        scrubber.register_secret(secret)
        self.qwen.health = RuntimeError(secret)
        self.core.run(self.submit(QWEN))
        for table in ("workers", "inference_queue", "inference_leases", "events", "checkpoints"):
            self.assertNotIn(secret, json.dumps(self.core.store.all('SELECT * FROM "' + table + '"')))


if __name__ == "__main__":
    unittest.main()
