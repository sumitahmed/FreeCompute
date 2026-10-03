"""Provider-neutral optional observations. Telemetry never grants capacity."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import math
import time

STATES = {"observed", "provider-reported", "configured", "estimated", "user-provided", "unknown"}
FIELDS = ("provider", "worker_id", "session_age_seconds", "session_limit_seconds", "session_remaining_seconds",
          "supervisor_uptime_seconds", "kernel_uptime_seconds", "connected_uptime_seconds", "gpu_count",
          "cpu_utilization_pct", "cpu_count", "ram_used_bytes", "ram_total_bytes", "disk_free_bytes",
          "disk_total_bytes", "engine_health", "model_loaded", "active_inference_slots")
GPU_FIELDS = ("name", "vram_used_mib", "vram_total_mib", "utilization_pct", "temperature_c")
TEXT_FIELDS = {"provider", "worker_id", "engine_health", "model_loaded", "name"}


@dataclass(frozen=True)
class Metric:
    value: object = None
    status: str = "unknown"
    source: str = "not reported"


def metric(value=None, status="observed", source="health endpoint", *, name=""):
    if value is None or status not in STATES or status == "unknown":
        return asdict(Metric())
    if name == "session_limit_seconds" and value == "none":
        return asdict(Metric("none", status, source))
    if name in TEXT_FIELDS:
        if not isinstance(value, str) or not value or len(value) > 512:
            return asdict(Metric())
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return asdict(Metric())
    if name.endswith("_pct") and value > 100:
        return asdict(Metric())
    return asdict(Metric(value, status, str(source)[:160]))


def _read(values, name):
    item = values.get(name, {}) if isinstance(values, dict) else {}
    if not isinstance(item, dict):
        return asdict(Metric())
    return metric(item.get("value"), item.get("status", "unknown"), item.get("source", "health endpoint"), name=name)


def _time(value, default):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        return float(value) if isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= default + 5 else default
    except (ValueError, OverflowError):
        return default


@dataclass
class WorkerTelemetry:
    metrics: dict = field(default_factory=dict)
    gpus: list = field(default_factory=list)
    observed_at: float = field(default_factory=time.time)
    schema_version: int = 1

    def to_dict(self):
        return asdict(self)

    def stale(self, now=None, ttl=30):
        return (time.time() if now is None else now) - self.observed_at > ttl

    def warning(self, now=None):
        if self.stale(now):
            return None
        limit, remaining = self.metrics["session_limit_seconds"], self.metrics["session_remaining_seconds"]
        if limit["status"] not in {"observed", "provider-reported", "configured", "user-provided"} or remaining["value"] is None:
            return None
        seconds = remaining["value"]
        return "10 minutes" if seconds <= 600 else "30 minutes" if seconds <= 1800 else "60 minutes" if seconds <= 3600 else None


def normalize(raw, *, worker_id="", provider="", configured_limit=None, no_deadline=False, connected_age=None, now=None):
    """Tolerate old/missing/malformed payloads without changing engine health."""
    now = time.time() if now is None else now
    raw = raw if isinstance(raw, dict) else {}
    contract = raw.get("telemetry", {})
    contract = contract if isinstance(contract, dict) and contract.get("schema_version") == 1 else {}
    values = contract.get("metrics", {})
    result = WorkerTelemetry({name: _read(values, name) for name in FIELDS}, observed_at=_time(contract.get("observed_at"), now))
    m = result.metrics
    for name, value in (("worker_id", worker_id), ("provider", provider)):
        if m[name]["value"] is None:
            m[name] = metric(value, "configured", "local worker declaration", name=name)
    # Legacy adapters have distinct supervisor/kernel ages, not account session ages.
    for name, key in (("supervisor_uptime_seconds", "supervisorUptimeSeconds"), ("kernel_uptime_seconds", "linuxUptimeSeconds")):
        if m[name]["value"] is None:
            m[name] = metric(raw.get(key), source="legacy health: " + key, name=name)
    source = str(raw.get("sessionAgeSource", ""))
    if m["session_age_seconds"]["value"] is None and source in {"provider", "runtime", "authoritative"}:
        m["session_age_seconds"] = metric(raw.get("sessionAgeSeconds"), "provider-reported", source, name="session_age_seconds")
    limit = m["session_limit_seconds"]
    if limit["value"] is None:
        # Old supervisors explicitly reported a 12h assumption; it is not runtime evidence.
        legacy = raw.get("maxSessionSeconds") if raw.get("sessionLimitSource") in {"provider", "runtime", "authoritative"} else None
        if legacy is not None:
            m["session_limit_seconds"] = metric(legacy, "provider-reported", str(raw["sessionLimitSource"]), name="session_limit_seconds")
    manifest = raw.get('session_manifest', {})
    if isinstance(manifest, dict):
        used_manifest = False
        for name in ('session_age_seconds', 'session_limit_seconds', 'session_remaining_seconds'):
            if m[name]['value'] is None and manifest.get(name) is not None:
                m[name] = metric(manifest[name], 'configured', 'worker/session manifest', name=name)
                used_manifest |= m[name]['value'] is not None
        if used_manifest:
            result.observed_at = min(result.observed_at, _time(manifest.get('observed_at'), now))
    if m['session_limit_seconds']['value'] is None:
        if no_deadline:
            m["session_limit_seconds"] = metric("none", "configured", "worker session_has_no_deadline", name="session_limit_seconds")
        elif configured_limit is not None:
            m["session_limit_seconds"] = metric(configured_limit, "configured", "worker session_limit_seconds", name="session_limit_seconds")
    limit, age = m["session_limit_seconds"], m["session_age_seconds"]
    if not isinstance(limit["value"], (int, float)):
        m["session_remaining_seconds"] = asdict(Metric())
    elif m["session_remaining_seconds"]["value"] is None and age["value"] is not None:
        m["session_remaining_seconds"] = metric(max(0, limit["value"] - age["value"]), "estimated",
                                                  "limit minus reported session age; sampled countdown", name="session_remaining_seconds")
    if connected_age is not None:
        m["connected_uptime_seconds"] = metric(connected_age, source="local connection clock", name="connected_uptime_seconds")
    if m["engine_health"]["value"] is None:
        m["engine_health"] = metric(raw.get("status"), source="health endpoint", name="engine_health")
    devices = contract.get("gpus")
    if isinstance(devices, list):
        result.gpus = [{name: _read(gpu, name) for name in GPU_FIELDS} for gpu in devices[:16] if isinstance(gpu, dict)]
    elif isinstance(raw.get("gpus"), list):
        aliases = {"name": "name", "vram_used_mib": "vramUsedMiB", "vram_total_mib": "vramTotalMiB",
                   "temperature_c": "tempC", "utilization_pct": "utilizationPct"}
        result.gpus = [{name: metric(gpu.get(key), source="legacy GPU observation", name=name) for name, key in aliases.items()}
                       for gpu in raw['gpus'][:16] if isinstance(gpu, dict)]
    if result.gpus and m["gpu_count"]["value"] is None:
        m["gpu_count"] = metric(len(result.gpus), source="devices reported by health", name="gpu_count")
    return result
