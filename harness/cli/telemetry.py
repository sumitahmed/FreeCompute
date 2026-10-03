"""Compact rendering of normalized metrics, including provenance and staleness."""
import time
from harness.telemetry.models import normalize
from harness.telemetry.session_tracker import format_duration


def value(item, *, duration=False, mib=False, unit=""):
    v = item['value']
    if v is None:
        return "unknown"
    if v == "none":
        rendered = "none"
    elif duration:
        rendered = format_duration(v)
    elif mib:
        rendered = f"{v / (1024 * 1024):,.0f} MiB"
    elif isinstance(v, (int, float)):
        rendered = f"{v:,.1f}".removesuffix(".0") + unit
    else:
        rendered = str(v)
    return rendered + " (" + item['status'] + ")"


def lines(raw, *, compact=False, now=None):
    telemetry = normalize(raw, now=now)
    m = telemetry.metrics
    age = max(0, (time.time() if now is None else now) - telemetry.observed_at)
    yield f"Sample {age:.0f}s ago" + (" [STALE]" if telemetry.stale(now) else "")
    yield "Provider " + value(m['provider']) + " | connected " + value(m['connected_uptime_seconds'], duration=True)
    yield "Session age " + value(m['session_age_seconds'], duration=True) + " | limit " + value(m['session_limit_seconds'], duration=True) + " | remaining " + value(m['session_remaining_seconds'], duration=True)
    if not compact:
        yield "Supervisor uptime " + value(m['supervisor_uptime_seconds'], duration=True) + " | Linux/kernel uptime " + value(m['kernel_uptime_seconds'], duration=True)
    for index, gpu in enumerate(telemetry.gpus):
        yield f"GPU{index} " + value(gpu['name']) + " | VRAM " + value(gpu['vram_used_mib'], unit=" MiB") + "/" + value(gpu['vram_total_mib'], unit=" MiB") + " | utilization " + value(gpu['utilization_pct'], unit="%") + " | temperature " + value(gpu['temperature_c'], unit=" C")
    if not telemetry.gpus:
        yield "GPUs unknown; no hardware sample reported"
    yield "CPU " + value(m['cpu_utilization_pct'], unit="%") + " | cores " + value(m['cpu_count']) + " | RAM " + value(m['ram_used_bytes'], mib=True) + "/" + value(m['ram_total_bytes'], mib=True)
    if not compact:
        yield "Disk free " + value(m['disk_free_bytes'], mib=True) + "/" + value(m['disk_total_bytes'], mib=True) + " | model " + value(m['model_loaded']) + " | active inference slots " + value(m['active_inference_slots'])
        for name in ('session_age_seconds', 'session_limit_seconds', 'session_remaining_seconds'):
            if m[name]['value'] is not None:
                yield "  " + name + " source: " + m[name]['source']
    warning = telemetry.warning(now)
    if warning:
        yield "Session warning: " + warning + " or less remaining; " + m['session_limit_seconds']['status'] + " limit, sampled estimate. Save work locally."
