# FreeCompute V2 vision

Proposed, 2026-10-02. See the [audit](CURRENT_ARCHITECTURE_AUDIT.md) before treating any feature below as available.

## Product

FreeCompute should be a local-first harness for open-weight models and agent workflows. The user's machine owns workspaces, tools, approvals, task state, and project knowledge. Inference runs on explicitly chosen local or remote compute. CLI, future GUI, SDK, and automation clients operate the same core.

Today it is a Python coding REPL tied to a concrete Kaggle/llama.cpp client, plus separate image-generation paths and notebook deployment experiments. It has useful primitives and passing unit tests. It does not yet have a working general capability router, durable resumable sessions, a resource scheduler, or a consistently enforced security boundary.

The product promise should be: **Your workspace stays under your control; choose where inference runs.** Remote inference necessarily receives selected prompts, file content, tool results, and any authorized media. Local-first does not imply that remote hosts cannot see those inputs. Open-weight does not imply unrestricted model licensing or cost-free compute.

## Recommended direction

Keep Python as the core language, provisionally raise the supported floor to Python 3.12 if the OpenHands SDK integration passes review, and avoid a wholesale fork. Use an `AgentDriver` adapter for reusable agent-loop machinery. FreeCompute owns the components that express its distinctive requirements: worker identity, capability evidence, physical resource accounting, local permission grants, secure tools, journal/recovery, and controlled memory promotion.

This is a conditional foundation recommendation, not a claim of drop-in compatibility. The [reuse decision](BUILD_VS_REUSE_DECISION.md) defines a spike with hard stop conditions. Cline SDK is the strongest alternative if a TypeScript/Node core is acceptable; Pi provides a smaller TypeScript runtime option. Codex, OpenCode, Goose, Continue, and Aider provide specific design lessons and components, not interchangeable black-box safety guarantees.

## Supported concepts

Users select local only, Kaggle only, private server only, or an allowed combination through worker constraints. A worker is a compute location; llama.cpp, vLLM, and ComfyUI are engines; TLS, a private mesh, or a tunnel is a transport. These are different axes. An OpenAI-compatible URL may provide no GPU telemetry or lifecycle control.

Operations include text generation, tool calling, vision input, image generation, video understanding, video generation, and embeddings. Reasoning is a model/profile behavior, not permission to execute tools. Coding quality is measured evidence, not a capability guaranteed by a model name. Unsupported operations fail before resource allocation with an actionable alternative.

Multi-agent work comprises a main agent, bounded children, independent tasks, and deterministic local test jobs. Queues and tested capacity determine actual parallelism. Two T4 devices do not create unlimited model instances or agent slots. A local research model and a remote image worker can overlap with a Kaggle coding model only when their physical resource pools and privacy grants permit it.

## First useful V2 milestone

A single user can connect one existing local or private llama.cpp endpoint, complete an approved file edit and local test, close the client, reconnect, and recover the task with truthful tool/approval/inference events. Denied actions do not execute. Incomplete tool calls do not execute. Secret fixtures do not appear in rendered or persisted streams. No notebook provider is required for this milestone.

Only after that foundation should V2 add verified notebook adapters, bounded delegation, image jobs, durable knowledge, scheduling, and a GUI. Website claims must follow released acceptance evidence.

## Boundaries

No remote host receives local terminal or filesystem authority. No model can promote its own memory, expand its permissions, silently change providers, or retry an uncertain side effect. No GUI or bot bypasses the same permission engine. No unattended notebook restarter or quota-evasion mechanism belongs in the product.

Kaggle and Colab are temporary, policy-dependent compute. Persistent homelab/server workers support background jobs. An offline local core keeps state but cannot continue inference on an unavailable worker.

## Decisions for user review

1. Approve Python 3.12 plus a gated OpenHands SDK evaluation, or prefer Cline/Pi and a Node/TypeScript core?
2. First release scope: coding/text plus one llama.cpp worker is recommended; image jobs follow the foundation. Confirm whether images must ship in the first milestone.
3. Default execution isolation: approved host commands for a trusted personal workspace, or a container/WSL backend as a release requirement? Windows support needs an explicit acceptance target.
4. Primary remote transport and privacy posture: private network/direct TLS preferred; a managed named tunnel requires separate setup and provider-policy verification.
5. GUI target: local browser dashboard first is recommended; desktop packaging and VS Code integration remain later alternatives.
6. Background autonomy: which recurring tasks may receive narrowly scoped standing grants? Default remains interactive approval, with headless jobs waiting or denied.

No choice above has been treated as user approval to implement.
