# Skills, slash commands and workflows

Proposed, 2026-10-02. Preserve the useful SKILL.md experience, while repairing current wiring before expansion.

## Compatibility baseline

Use the [Agent Skills specification](https://agentskills.io/specification) for required `name`/`description`, optional license/compatibility/metadata, directory conventions and progressive disclosure. Its `allowed-tools` field is experimental and format support varies. A manifest's requested/preferred tools never override FreeCompute's local approval policy. Keep portable metadata string-valued; structured FreeCompute extensions belong in a separate validated companion manifest.

Example proposal, not installed configuration:

```text
skills/code-reviewer/
  SKILL.md
  freecompute.yaml       # optional versioned extensions
  references/
  scripts/
```

```yaml
# SKILL.md frontmatter
name: code-reviewer
description: Review a selected diff and report evidence-backed defects.
metadata:
  freecompute-schema: "1"
```

```yaml
# Illustrative companion manifest; proposed schema only
schema_version: 1
required_capabilities: [text, tool_calling]
allowed_tools: [read_file, grep_search]
preferred_model_profile: coding-review
permission_requests: []
arguments:
  target:
    type: string
workflow: null
```

Existing underscore `allowed_tools` metadata and missing `inspect_file` naming need an explicit legacy compatibility/diagnostic path. Do not silently translate an unknown tool into a higher-privilege alias. Surface which skill version and source were selected.

## Discovery and trust

Search bundled, global user, and project skill directories in deterministic order; project overrides require a visible source/version decision. Resolve collisions explicitly and sort catalog output. Parse manifests without executing scripts. Validate names, schema versions, argument types, referenced files, size limits and resource-path containment. Symlink or `../` references cannot escape a skill package grant.

Global skill installation and project-local instructions are distinct trust scopes. A cloned repo may contain hostile skill scripts or AGENTS.md text; neither can expand grants, daemon listeners, telemetry, or secret access. Discovery does not automatically run anything. Scripts go through the same tool/process broker with explicit approvals and environment/network limits.

## Slash behavior

`/skill-name arguments` resolves a skill and validates its structured argument schema. `/skill name ...` can be a deliberate compatibility alias. Keep existing `/review`, `/leetcode`, `/research` aliases with visible canonical mapping. Local lifecycle commands such as `/help`, `/status`, `/model`, `/worker`, `/cancel`, `/resume`, `/diff`, `/undo`, and `/memory` are parsed by the client/core command contract; they are not sent to inference as arbitrary prompts.

Unknown slash commands report an actionable error, not silent model input. Reserved-name collisions are rejected. Argument strings are data: never concatenate them into shell commands or instructions with implicit execution privileges. Activation records source/hash/version/arguments and the effective tool subset.

Preflight checks required operations, eligible model/worker, permission requests and budget. A preferred model is a routing hint; hard privacy constraints always win. Effective tools are the intersection of global policy, task/agent grant, skill allowlist and capability support. Missing tools or denied permissions stop or offer an explicit alternative rather than attempting unsupported behavior.

## Prompt behavior

Stable catalog summaries can sit in a versioned prefix. Activate full body/resources lazily in the task appendix. Full skill text is not needed in every model turn. Project instructions receive an explicit trust tier, distinct from runtime policy. Skill edits mid-task create a new version and an explicit reload decision; they do not silently alter the reviewed workflow.

## Workflows

Portable skills remain instruction packages. Optional FreeCompute workflows are constrained, versioned DAGs of agent/tool/job stages, inspired by Goose recipes and Cline team/cron machinery. Each node declares inputs/outputs, operation/model hints, tool subset, timeout/budget, dependency, retry classification and permission requirements. Avoid a Turing-complete script language for initial workflows.

Example: read-only research -> reviewed patch proposal -> user approval -> single writer edit -> approved deterministic tests -> summary proposal. The scheduler admits each stage; parent completion cannot conceal a failed test. An image stage returns artifact references, not file paths supplied by a remote server.

Workflow authors cannot grant privileges, auto-merge work, send bot messages, or mark uncertain effects retryable. Runtime validates acyclicity, fan-out/depth and total budgets. Scheduled invocation uses the same reviewable standing-grant policy as manual tasks.

Acceptance: existing aliases remain usable, skill tools actually resolve, malformed manifests fail clearly, unknown commands do not become chat, paths/scripts respect boundaries, children never widen grants, and dynamic activation changes prompt metadata predictably.
