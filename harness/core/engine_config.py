"""Local composition of configured adapters; no credentials enter durable descriptors."""
from urllib.parse import urlsplit

from harness.core.engines import ComfyUIEngine, LlamaCppEngine, OpenAICompatibleEngine
from harness.core.runtime_models import ModelProfile, Worker
from harness.providers.comfyui import ComfyUIProvider
from harness.providers.llamacpp import LlamaCppProvider
from harness.providers.openai_compatible import OpenAICompatibleProvider
from harness.security import scrubber
from harness.storage.runtime import fingerprint


def require_remote_auth(url, key):
    if not key and urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote text workers require a bearer key; set FREECOMPUTE_API_KEY or the worker's api_key_env")


def configured_engines(config, workspace):
    profiles, attachments = {}, []
    for declaration in config.model_profiles:
        profile = ModelProfile(**declaration.model_dump())
        if profile.profile_id in profiles:
            raise ValueError("Duplicate model profile ID")
        profiles[profile.profile_id] = profile
    if bool(config.workers) != bool(profiles):
        raise ValueError("Explicit workers and model_profiles must be configured together")
    for connection in config.workers:
        if any(worker.worker_id == connection.worker_id for worker, _, _ in attachments):
            raise ValueError("Duplicate worker ID")
        if not connection.profiles or any(p not in profiles for p in connection.profiles):
            raise ValueError("Worker references an unknown or empty model profile list")
        models = [profiles[p] for p in connection.profiles]
        capabilities = frozenset().union(*(p.capabilities for p in models))
        key = config.resolve_api_key(connection.api_key_env) if connection.api_key_env else connection.api_key
        if connection.api_key_env and not key:
            raise ValueError("Worker API-key environment variable is unset")
        scrubber.register_secret(key)
        scrubber.register_secret(connection.url)
        if connection.engine != "ComfyUI":
            require_remote_auth(connection.url, key)
        if connection.engine == "llama.cpp":
            adapter = LlamaCppEngine(LlamaCppProvider(connection.url, key, models[0].model, connection.timeout_seconds or config.request_timeout_seconds).client)
        elif connection.engine == "openai-compatible":
            adapter = OpenAICompatibleEngine(OpenAICompatibleProvider(connection.url, key, models[0].model, connection.timeout_seconds or config.request_timeout_seconds,
                                                                     code_tools="code_tools" in capabilities))
        else:
            if key:
                raise ValueError("The existing ComfyUI transport has no bearer-auth contract; use an appropriately protected endpoint")
            if connection.timeout_seconds is not None:
                raise ValueError("The existing ComfyUI workflow keeps its 180-second polling limit; custom timeout configuration is unsupported")
            if len({profile.model for profile in models}) != 1:
                raise ValueError("One ComfyUI attachment uses one existing workflow/model identity; arbitrary checkpoint switching is unsupported")
            adapter = ComfyUIEngine(ComfyUIProvider(connection.url, workspace_root=workspace), model_identity=models[0].model)
        worker = Worker(connection.worker_id, connection.location, connection.engine, capabilities,
                        concurrency_limit=connection.concurrency_limit, resource_pool=connection.resource_pool, resources=connection.resources)
        attachments.append((worker, models, adapter))
    if not attachments:
        require_remote_auth(config.remote_url, config.api_key)
        capabilities = frozenset({"text", "code_tools"}) if config.engine == "llama.cpp" else frozenset({"text"})
        profile = ModelProfile(fingerprint({"model": config.model_alias, "engine": config.engine, "context": config.max_context_tokens}),
                               "supervisor-text", config.model_alias, config.engine, capabilities, config.max_context_tokens,
                               min(2048, max(1, config.max_context_tokens // 4)))
        profiles[profile.profile_id] = profile
        adapter = (LlamaCppEngine(LlamaCppProvider(config.remote_url, config.api_key, config.model_alias, config.request_timeout_seconds).client)
                   if config.engine == "llama.cpp" else OpenAICompatibleEngine(OpenAICompatibleProvider(config.remote_url, config.api_key, config.model_alias, config.request_timeout_seconds)))
        worker = Worker("supervisor-text", "remote-supervisor", config.engine, capabilities,
                        resource_pool="attached-default", resources=frozenset({"inference"}))
        attachments.append((worker, [profile], adapter))
        # Unknown physical placement retains Stage 3's conservative shared slot.
        image = ModelProfile("comfy-image", "comfy-worker", "ComfyUI-default", "ComfyUI", frozenset({"image_gen"}))
        profiles[image.profile_id] = image
        attachments.append((Worker("comfy-worker", "remote-supervisor", "ComfyUI", image.capabilities,
                                   resource_pool="attached-default", resources=frozenset({"inference"})),
                            [image], ComfyUIEngine(ComfyUIProvider(config.image_server_url, workspace_root=workspace))))
    selected = config.selected_profile or next((p.profile_id for p in profiles.values() if "text" in p.capabilities), next(iter(profiles)))
    if selected not in profiles:
        raise ValueError("Selected model profile is not configured")
    candidates = [entry for entry in attachments if any(p.profile_id == selected for p in entry[1]) and (not config.selected_worker or entry[0].worker_id == config.selected_worker)]
    if not candidates:
        raise ValueError("Selected model cannot run on the selected worker")
    return profiles[selected], candidates[0], attachments
