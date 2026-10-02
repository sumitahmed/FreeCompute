"""Additive schema-v2 migration. No existing authority or user data is replaced."""

SCHEDULER_SCHEMA = """
CREATE TABLE model_profiles(id TEXT PRIMARY KEY, version INTEGER NOT NULL, declaration TEXT NOT NULL);
CREATE TABLE workers(
 id TEXT PRIMARY KEY, version INTEGER NOT NULL, declaration TEXT NOT NULL,
 health TEXT NOT NULL, last_seen TEXT, checked_at REAL, observation TEXT NOT NULL DEFAULT '{}');
CREATE TABLE worker_profiles(
 worker_id TEXT NOT NULL REFERENCES workers(id), profile_id TEXT NOT NULL REFERENCES model_profiles(id),
 PRIMARY KEY(worker_id,profile_id));
CREATE TABLE inference_queue(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
 task_id TEXT NOT NULL REFERENCES tasks(id), profile_id TEXT NOT NULL REFERENCES model_profiles(id),
 context_epoch INTEGER NOT NULL, turn INTEGER NOT NULL, required_capabilities TEXT NOT NULL,
 requested_worker TEXT, request_hash TEXT, state TEXT NOT NULL,
 waiting_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(task_id,context_epoch,turn));
CREATE TABLE inference_leases(
 id TEXT PRIMARY KEY, queue_id TEXT NOT NULL REFERENCES inference_queue(id),
 worker_id TEXT NOT NULL REFERENCES workers(id), profile_id TEXT NOT NULL REFERENCES model_profiles(id),
 attempt_id TEXT UNIQUE REFERENCES inference_attempts(id), state TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE resource_claims(
 pool_id TEXT NOT NULL, resource_id TEXT NOT NULL,
 lease_id TEXT NOT NULL REFERENCES inference_leases(id), PRIMARY KEY(pool_id,resource_id));
CREATE INDEX queue_ready ON inference_queue(state,sequence);
CREATE INDEX lease_worker_state ON inference_leases(worker_id,state);
CREATE UNIQUE INDEX lease_active_queue ON inference_leases(queue_id) WHERE state IN ('active','quarantined');
"""
