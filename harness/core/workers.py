"""Small durable registry; adapters and credentials remain in process memory."""
import json
import time

from harness.core.runtime_models import ModelProfile, Worker
from harness.security import scrubber
from harness.storage.runtime import encode, timestamp


class WorkerRegistry:
    def __init__(self, store, *, health_ttl=30, clock=time.time):
        if health_ttl <= 0:
            raise ValueError("Worker health TTL must be positive")
        self.store, self.health_ttl, self.clock = store, health_ttl, clock
        self.engines, self.trusted_embeddings = {}, set()
        with store.transaction() as db:
            db.execute("UPDATE workers SET health='unverified',checked_at=NULL")

    def add_profile(self, profile, *, replace_completed=False):
        value = profile.to_dict()
        if scrubber.structured(value) != value:
            raise ValueError("Profile declarations cannot contain credentials or secret endpoints")
        with self.store.transaction() as db:
            old = db.execute("SELECT declaration FROM model_profiles WHERE id=?", (profile.profile_id,)).fetchone()
            if old and old[0] != encode(value):
                unfinished = db.execute("SELECT 1 FROM tasks WHERE profile_id=? AND state NOT IN ('completed','failed','malformed','truncated','incomplete','max_turns','context_overflow','cancelled')", (profile.profile_id,)).fetchone()
                held = db.execute("SELECT 1 FROM inference_leases WHERE profile_id=? AND state IN ('active','quarantined')", (profile.profile_id,)).fetchone()
                if not replace_completed or unfinished or held:
                    raise ValueError("Profile IDs are immutable while referenced; use a new ID for changed declarations")
                # Retain the old embedding API after terminal tasks, and its declarations.
                from harness.storage.runtime import fingerprint
                db.execute("INSERT OR IGNORE INTO metadata VALUES(?,?)", ("profile_history:" + fingerprint(json.loads(old[0])), old[0]))
                db.execute("UPDATE model_profiles SET declaration=? WHERE id=?", (encode(value), profile.profile_id))
            db.execute("INSERT OR IGNORE INTO model_profiles VALUES(?,1,?)", (profile.profile_id, encode(value)))

    def profile(self, profile_id):
        row = self.store.one("SELECT declaration FROM model_profiles WHERE id=?", (profile_id,))
        if not row:
            raise ValueError("Unknown model profile; inspect /models")
        return ModelProfile(**json.loads(row["declaration"]))

    def attach(self, worker, profiles, engine, *, trusted_embedding=False):
        profiles = list(profiles)
        if not profiles:
            raise ValueError("Worker needs at least one model profile")
        supported = engine.get_capabilities() if hasattr(engine, "get_capabilities") else worker.capabilities
        if not worker.capabilities <= frozenset(supported):
            raise ValueError("Worker capabilities exceed the adapter's declared support")
        for profile in profiles:
            if worker.engine not in profile.engine_requirements or not profile.capabilities <= worker.capabilities or not profile.resource_requirements <= worker.resources:
                raise ValueError("Model profile cannot run on this worker's engine/capabilities/resources")
            self.add_profile(profile, replace_completed=trusted_embedding)
        declaration = worker.to_dict()
        for transient in ("health", "last_seen", "observed_resources"):
            declaration.pop(transient)
        declaration["adapter_identity"] = getattr(engine, "identity_hash", None)
        if scrubber.structured(declaration) != declaration:
            raise ValueError("Worker identities/resources cannot contain secrets")
        with self.store.transaction() as db:
            old = db.execute("SELECT declaration FROM workers WHERE id=?", (worker.worker_id,)).fetchone()
            held = db.execute("SELECT 1 FROM inference_leases WHERE worker_id=? AND state IN ('active','quarantined')", (worker.worker_id,)).fetchone()
            old_profiles = {r[0] for r in db.execute("SELECT profile_id FROM worker_profiles WHERE worker_id=?", (worker.worker_id,))}
            if held and (old[0] != encode(declaration) or old_profiles != {p.profile_id for p in profiles}):
                raise ValueError("Resolve worker leases before changing identity, capacity, resources or models")
            db.execute("INSERT INTO workers VALUES(?,1,?,'unverified',NULL,NULL,'{}') ON CONFLICT(id) DO UPDATE SET declaration=excluded.declaration",
                       (worker.worker_id, encode(declaration)))
            if old and old[0] != encode(declaration):
                db.execute("UPDATE workers SET health='unverified',checked_at=NULL,observation='{}' WHERE id=?", (worker.worker_id,))
            db.execute("DELETE FROM worker_profiles WHERE worker_id=?", (worker.worker_id,))
            db.executemany("INSERT INTO worker_profiles VALUES(?,?)", [(worker.worker_id, p.profile_id) for p in profiles])
        self.engines[worker.worker_id] = engine
        if trusted_embedding:
            self.trusted_embeddings.add(worker.worker_id)
            self.observe(worker.worker_id, "healthy", {"source": "trusted in-process declaration"})

    def worker(self, worker_id):
        row = self.store.one("SELECT declaration FROM workers WHERE id=?", (worker_id,))
        if not row:
            raise ValueError("Unknown worker")
        value = json.loads(row["declaration"])
        value.pop("adapter_identity", None)
        return Worker(**value)

    def engine(self, worker_id):
        try:
            return self.engines[worker_id]
        except KeyError:
            raise ValueError("Worker is not attached; restore its local configuration") from None

    def observe(self, worker_id, health, resources=None):
        if health not in {"healthy", "unhealthy", "unreachable", "unverified", "unconfigured"}:
            health = "unhealthy"
        with self.store.transaction() as db:
            if not db.execute("SELECT 1 FROM workers WHERE id=?", (worker_id,)).fetchone():
                raise ValueError("Unknown worker")
            db.execute("UPDATE workers SET health=?,last_seen=CASE WHEN ?='healthy' THEN ? ELSE last_seen END,checked_at=?,observation=? WHERE id=?",
                       (health, health, timestamp(), self.clock(), encode(resources or {}), worker_id))

    def refresh(self, worker_id):
        engine = self.engine(worker_id)
        try:
            if not hasattr(engine, "get_health") and worker_id in self.trusted_embeddings:
                self.observe(worker_id, "healthy", {"source": "trusted in-process declaration"})
                return None
            health = engine.get_health()
            self.observe(worker_id, health.status, health.raw)
            return health
        except Exception as exc:
            self.observe(worker_id, "unreachable", {"error": scrubber.scrub(exc)})
            return None

    def candidates(self, profile_id, requested_worker=None):
        self.profile(profile_id)
        rows = self.store.all("SELECT w.* FROM workers w JOIN worker_profiles p ON p.worker_id=w.id WHERE p.profile_id=? ORDER BY w.id", (profile_id,))
        return [r for r in rows if not requested_worker or r["id"] == requested_worker]

    def refresh_candidates(self, profile_id, requested_worker=None):
        for row in self.candidates(profile_id, requested_worker):
            if row["id"] in self.engines and (row["health"] != "healthy" or row["checked_at"] is None or self.clock() - row["checked_at"] > self.health_ttl):
                self.refresh(row["id"])

    def available(self, row):
        return row["id"] in self.engines and row["health"] == "healthy" and row["checked_at"] is not None and 0 <= self.clock() - row["checked_at"] <= self.health_ttl

    def list_workers(self):
        result = []
        for row in self.store.all("SELECT * FROM workers ORDER BY id"):
            declaration = json.loads(row["declaration"])
            declaration.pop("adapter_identity", None)
            count = self.store.one("SELECT COUNT(*) n FROM inference_leases WHERE worker_id=? AND state IN ('active','quarantined')", (row["id"],))["n"]
            result.append(dict(declaration, health=row["health"] if self.available(row) else "stale" if row["health"] == "healthy" else row["health"],
                               attached=row["id"] in self.engines, last_seen=row["last_seen"], observed_resources=json.loads(row["observation"]),
                               active_or_quarantined=count, profiles=[p["profile_id"] for p in self.store.all("SELECT profile_id FROM worker_profiles WHERE worker_id=? ORDER BY profile_id", (row["id"],))]))
        return scrubber.structured(result)

    def list_profiles(self):
        return [dict(json.loads(row["declaration"]), workers=[w["worker_id"] for w in self.store.all("SELECT worker_id FROM worker_profiles WHERE profile_id=? ORDER BY worker_id", (row["id"],))])
                for row in self.store.all("SELECT * FROM model_profiles ORDER BY id")]
