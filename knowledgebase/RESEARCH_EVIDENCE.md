# Research evidence and provenance

Research date: 2026-10-02. FreeCompute baseline: `ea6d39a44d40e50f2ffebc84c0fce83a198ba24b` on `main`, initially clean. This is a source audit and local fixture investigation, not a live GPU acceptance run.

## Method and coverage

Inspected the tracked repository inventory: root documentation/guidance/license/build/configuration/launchers, all harness modules, all twelve unit-test modules and scanner, all six older knowledge-base documents, notebook cell source, saved proof outputs, generators, and diagram specification/receipt metadata. Duplicate image scripts were compared; generator notebook literals were extracted statically rather than executed. Generated diagram rendering/runtime bundles were inventoried rather than interpreted as product code. Empty package markers were inventoried.

Ignored private journals, caches, image outputs, and user runtime credentials were not dumped. No personal workspace outside temporary fixtures was used for boundary probes. The tracked sample config was inspected; secret-bearing runtime config was not needed. All research downloads reside outside production source in a temporary directory. No upstream dependency was installed and no upstream code was copied into FreeCompute.

External research used GitHub recursive trees at recorded commit SHAs, raw source files, root license files, and official protocol/provider documentation. Selected control flow and boundary implementations were inspected, not merely READMEs. The inventory below records retrieved sources; it does not claim every line of every large upstream file was reviewed. No upstream project was built or benchmarked. Mechanism claims and adoption limits are in [OPEN_SOURCE_AGENT_RESEARCH.md](OPEN_SOURCE_AGENT_RESEARCH.md).

## Local verification

| Check | Observed result | Limit |
| --- | --- | --- |
| `python -m unittest discover -s tests/unit -p "test_*.py"` | 42 tests, OK; initial run 0.986 seconds | Mock-heavy suite; no live remote worker or main CLI end-to-end proof |
| `python tests/security_scan.py` | Exit 0; 85 files scanned; zero matches before these documents | Narrow selected-pattern scan, not a release safety certification |
| Noninteractive orchestrator fixture | Missing approval callback executed `write_file` against fake temp content | Reproduces actual fallback path, not the interactive CLI callback |
| Sandbox variants | `.env.local` and `.ENV` accepted | Windows-specific casing matters |
| Recursive search | `grep_search` returned fake secret text in `secrets.yaml` | Fixture contents were synthetic |
| Undo boundary | `record_pre_change` accepted fake outside-workspace file | Demonstrates snapshot authority flaw without reading user data |
| Undo collision | Frozen timestamp plus two changes to one file reused backup; two restores removed the file | Reproduces collision/lost restore within one second |
| Checkpoint payload | Keys were `turn`, `history_len` | Does not contain transcript required for restart |
| Skill wiring | Four referenced methods absent: `get_project_instructions`, `get_skills_prompt_summary`, `list_skills`, `read_skill` | CLI shortcuts follow a separate manual injection path |
| Comfy health | `TypeError`: unexpected `supervisor_uptime_seconds` | Safe unconfigured-provider branch; no image server connection |
| Quota accounting | One hour logged; stopped estimate remained 25 hours | Local ledger arithmetic; no account quota queried |
| Config precedence | Legacy key overrode canonical key; example timeout variable ignored | Fake environment values only |
| Supervisor defaults/health | Predictable fallback exists; in-memory GET health never called mocked rejecting auth | No public listener or tunnel created |

Fixture method: `TemporaryDirectory`, standard-library `unittest.mock`, synthetic file contents, fake streaming client, and in-memory HTTP-handler streams. For collision reproduction, fix `harness.storage.undo.time.time` to one value, snapshot/change the same path twice, then undo twice. For approval reproduction, send a mocked `write_file` tool call through `AgentOrchestrator` with no approval callback. For recursive search, place a fake matching line in `secrets.yaml` below an otherwise permitted temp root. These are diagnostics, not committed tests or fixes.

Additional code-derived risks (process escape, file symlinks, SSRF, remote stream framing/cancellation) were not executed against real private files, processes, or remote services. They require future focused tests; the audit labels them as inferences where applicable.

## Saved notebook provenance

| Artifact | SHA-256 / observed output | Evidence status |
| --- | --- | --- |
| Two text server notebooks | Both `93445ff508003bd90d41c4fee391b079ba5ff264cd098666921cffaeb12e3d2e`; ten cells each, no outputs | Identical source; not executed evidence |
| Root dual-T4 proof | `edbe9117c22c6aff131900118a19ad94c23de9eb14e99a4a1d23ddcea310a362` | Preserved execution outputs, not rerun |
| Proof configuration | llama.cpp `2b129ccfa03aea330d2d9ac4650a10de393dbe3a`; 32,768 context; one slot; two Tesla T4 devices | Historical source/output |
| Proof long-context cell | Explicitly skipped performance test | No measured 64K guarantee |
| Legacy handoff 64K recall | User report: 46,722 prompt tokens, 171.5 seconds | Historical user report separately identified; not independently reproduced |
| Image and dataset notebooks | Source inspected; no saved executed outputs | Workflows/configuration, not successful run certification |

## Primary transport and policy sources

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/): SSE unsupported, development/testing positioning. Treat this as a documented limitation, not a new live transport experiment.
- [Colab FAQ](https://research.google.com/colaboratory/faq.html): managed-runtime restrictions and variable availability. A paid account is not blanket permission for unattended serving; adapter scope must match applicable policy.
- [Kaggle notebooks](https://www.kaggle.com/docs/notebooks) and [terms](https://www.kaggle.com/terms): official URLs were opened but provided no readable policy text to this research tool. Current account quota and permission for any proposed network mode remain unverified. Existing 12h/weekly quota numbers are historical/local assumptions, not fresh guarantees.
- [Tailscale userspace networking](https://tailscale.com/docs/concepts/userspace-networking): background reference; inbound reachability of the shipped notebook configuration was not proven.
- [Agent Skills specification](https://agentskills.io/specification): portable manifest baseline, not a grant of host permissions.

## Upstream pins and root licenses

All licenses below were fetched at the listed commit. A root license does not settle every vendored dependency, model weight, plugin, bundled binary, or trademark obligation. Review the actual reused subtree and its notices before importing code or distributing a package.

| Project | Commit | Root license | Source |
| --- | --- | --- | --- |
| codex | `a20fe6335f960a350483d0079db2ec281c68202c` | Apache-2.0 | [license](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/LICENSE) |
| opencode | `1ddb0873aee50d209d1a8d7f91b89c5daf692d49` | MIT | [license](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/LICENSE) |
| cline | `4515a410a06e92a78608d5267171a340d2aa32f6` | Apache-2.0 | [license](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/LICENSE) |
| aider | `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` | Apache-2.0 | [license](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/LICENSE.txt) |
| openhands | `1ff45c267fe5737c9387ccaf54d44cab3da6d9dd` | MIT | [license](https://github.com/OpenHands/OpenHands/blob/1ff45c267fe5737c9387ccaf54d44cab3da6d9dd/LICENSE) |
| openhands-sdk | `53a4bc5014902ca84bb21fff30eac606ff4905aa` | MIT | [license](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/LICENSE) |
| continue | `5522c6f44ca0ac3528b37244818fbfa39b5af470` | Apache-2.0 | [license](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/LICENSE) |
| goose | `caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15` | Apache-2.0 | [license](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/LICENSE) |
| pi | `7fbbd5f4a1d982bb02d63472dde0774fa639f99b` | MIT | [license](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/LICENSE) |
| mcp | `17aaf2557205c3768ed61831398a4e074b21e96d` | MIT | [license](https://github.com/modelcontextprotocol/python-sdk/blob/17aaf2557205c3768ed61831398a4e074b21e96d/LICENSE) |
| llama | `207bdab95010a0489e661bad8ca109c96aad46a8` | MIT | [license](https://github.com/ggml-org/llama.cpp/blob/207bdab95010a0489e661bad8ca109c96aad46a8/LICENSE) |
| vllm | `4056c8ac1f8a7e8fb50cf1c56ff96649fcadccc6` | Apache-2.0 | [license](https://github.com/vllm-project/vllm/blob/4056c8ac1f8a7e8fb50cf1c56ff96649fcadccc6/LICENSE) |
| comfy | `65787d668397d230bf5839d69a0a7239e2dad378` | GPL-3.0 license text | [license](https://github.com/Comfy-Org/ComfyUI/blob/65787d668397d230bf5839d69a0a7239e2dad378/LICENSE) |

## Retrieved source inventory

Links are pinned and remain usable without the temporary research directory. SHA-256 values allow an implementer to verify the exact downloaded bytes. Some upstream module paths have moved: a missing old path was not used as evidence. For example, current OpenHands runtime is in its software-agent SDK, and Cline has a host-independent SDK; treating either solely as its older application architecture would be inaccurate.

| Project | Pinned source | SHA-256 |
| --- | --- | --- |
| codex | [codex-rs/app-server/README.md](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/app-server/README.md) | `5d1b3014441120061a8e41e233b5d9c0d0d6f8bf9e2aaf9765b1bf581ebdcb79` |
| codex | [codex-rs/core/src/client.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/client.rs) | `6a725a3e1548e667e8fadbbe8e7b39288fd9393daf188276e6f9554cf008c2bb` |
| codex | [codex-rs/core/src/compact.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/compact.rs) | `645b1cd090a5c1fea81bec4cf308259f634d212dbdcf0fb3310cf0b8d0592ad4` |
| codex | [codex-rs/core/src/rollout.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/rollout.rs) | `1aa136709f80968ee68f4430efcffd6442a2837c34c7c7c78cc43bd83e738bf3` |
| codex | [codex-rs/core/src/session/turn.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/session/turn.rs) | `257725fe93f5c065f29772d263ff44d1c194ae61ea8809d4669313a2d5dd8f1f` |
| codex | [codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs) | `91102f864043adbf49f7d5aff6778d358ea99ad8c3d7d59fb913950fad60784f` |
| codex | [codex-rs/core/src/tools/sandboxing.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/tools/sandboxing.rs) | `eacb70e5c7b746834d16b11eca6f37aecd5655ef3dfbb38440e1013c59da987a` |
| codex | [codex-rs/core/src/unified_exec/process_manager.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/core/src/unified_exec/process_manager.rs) | `ab5661b74605323dcae6fe82752ceaff9cac403add2363e598c574a49fdc48db` |
| codex | [codex-rs/ext/memories/src/lib.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/ext/memories/src/lib.rs) | `0751544b5fb6e06e88be10720a89eebee59c6fc6c6bf1c09a1346402bab413ea` |
| codex | [codex-rs/ext/skills/src/loader/metadata.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/ext/skills/src/loader/metadata.rs) | `0b203b4696b17ccf695bbcf8eb3a4e471e9c8b47477081126a06f98f35f600eb` |
| codex | [codex-rs/model-provider-info/src/lib.rs](https://github.com/openai/codex/blob/a20fe6335f960a350483d0079db2ec281c68202c/codex-rs/model-provider-info/src/lib.rs) | `941a8ec0e8be4b45080cac3df3d052999a4cb104811575634b1a9ed510690958` |
| opencode | [packages/opencode/src/mcp/index.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/mcp/index.ts) | `82c459309dfd005d25daecfabc1007d807d4bee23f6078434974277938a1c026` |
| opencode | [packages/opencode/src/permission/evaluate.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/permission/evaluate.ts) | `0ee7b7fea6766c57ce0583bd6f23a303c5af314c0e5287018fa6bdfdc38e5a6e` |
| opencode | [packages/opencode/src/permission/index.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/permission/index.ts) | `5b9e4aa65290a39363722b9fae4c68080188d8ed76896afa0d96cd9dbfd2821d` |
| opencode | [packages/opencode/src/provider/provider.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/provider/provider.ts) | `9fb8958a521bbc5a70e5e6d4ecb130149115fe891fb78bca0ae73a966b9f547a` |
| opencode | [packages/opencode/src/server/server.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/server/server.ts) | `ba4503a8da66a7e8cda86ea7ad7ea0e8e4172abcaa87abd8c35835ffa0a494f9` |
| opencode | [packages/opencode/src/session/compaction.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/session/compaction.ts) | `8d478570a7e4ad32b746030d4f86a1c673949b1e2259bd716b3885d99283289a` |
| opencode | [packages/opencode/src/session/processor.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/session/processor.ts) | `0b31e207beda56bd9a4b9b88c9e42d89a0651dd011773748c8e2938dfc3dcb74` |
| opencode | [packages/opencode/src/session/prompt.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/session/prompt.ts) | `f0c5bc64c0f0e966693d4a57f7ede1e9d6e188b396152f04b55303dc75b9b768` |
| opencode | [packages/opencode/src/skill/index.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/skill/index.ts) | `91dce57f590e1ad3103e0555b893500e098a95cde2739422b699233889b205e6` |
| opencode | [packages/opencode/src/tool/edit.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/tool/edit.ts) | `f84d9d242137e1f18ce912188efb7a97b71bf4f255e0a69f16a1fe9d1ff236d4` |
| opencode | [packages/opencode/src/tool/shell.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/tool/shell.ts) | `342d742ae324782d222465c202dcdfcb7cc35a4cecf04e87f9881f1794d921ac` |
| opencode | [packages/opencode/src/tool/task.ts](https://github.com/anomalyco/opencode/blob/1ddb0873aee50d209d1a8d7f91b89c5daf692d49/packages/opencode/src/tool/task.ts) | `db09fa5868ad3ecfdd83aa2bb7243f85e9e2cd13d0b19fd6f307f7a337b2b36e` |
| cline | [sdk/ARCHITECTURE.md](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/ARCHITECTURE.md) | `62d340a07748ee9369bd14e87b9190c1f05423073346e1af52b19697841dc204` |
| cline | [sdk/packages/agents/src/agent-runtime.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/agents/src/agent-runtime.ts) | `30f6e9dd226c7c5c2b01e82c7b242ce5d3f2421b32dfd189e1ac5f3d01d0f61c` |
| cline | [sdk/packages/core/package.json](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/package.json) | `bceb7c7e0b1771d164bd5c46d1aa20c04eea090ad0b981ed867349f4c41caece` |
| cline | [sdk/packages/core/src/cron/service/cron-service.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/cron/service/cron-service.ts) | `6c4f0479af9f49698ec6d827e43d880d918df1f882789455bf8b791a10bf1b88` |
| cline | [sdk/packages/core/src/cron/store/sqlite-cron-store.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/cron/store/sqlite-cron-store.ts) | `d5323b0e9b5fe90ddb65efddcabea4b95ecc81245be64a4b1aedb7015c3eb85a` |
| cline | [sdk/packages/core/src/extensions/agent-plugin/agent-skill.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/agent-plugin/agent-skill.ts) | `92e8e12949b224af4b396d4cfe791f0baae5a294fea3d905bc577e3e705392ba` |
| cline | [sdk/packages/core/src/extensions/context/basic-compaction.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/context/basic-compaction.ts) | `c2e593c2d6663d9ff2aa26b3af1fd0e7037a010f3200ba9c8cf6f1e6d02f6719` |
| cline | [sdk/packages/core/src/extensions/context/compaction.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/context/compaction.ts) | `50534c940f999797fbe5cacf821739ff99d81610e042aab9c9269ee15dedc696` |
| cline | [sdk/packages/core/src/extensions/mcp/manager.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/mcp/manager.ts) | `35b09d5a251f3e802493c80694adf6f39df416f27cf03d9171593ce4b83b816a` |
| cline | [sdk/packages/core/src/extensions/tools/executors/run-command-execution-controller.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/tools/executors/run-command-execution-controller.ts) | `0bd2acdd4402162b5e2a64f55ef180bb87cc5f9730853d6c0ea4465cbf055b47` |
| cline | [sdk/packages/core/src/extensions/tools/runtime.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/tools/runtime.ts) | `37c85ffd307bcbc7c89e7f3f1815110673e5259a844fa3018ac90f29476d5b18` |
| cline | [sdk/packages/core/src/extensions/tools/team/multi-agent.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/extensions/tools/team/multi-agent.ts) | `8a7a11589339592a535d951395477335a52701c5784c5f1e235d48bd5c93a3a7` |
| cline | [sdk/packages/core/src/runtime/host/local-runtime-host.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/runtime/host/local-runtime-host.ts) | `1df5feac2079db8c527907307a713330bedb779fde6c575b08e5aa18072c9379` |
| cline | [sdk/packages/core/src/runtime/tools/tool-approval.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/runtime/tools/tool-approval.ts) | `ebd9bcdf7e431600d9b7a956d741a97b120c2c25aaaf9b45af799ee48dfbaff5` |
| cline | [sdk/packages/core/src/session/checkpoint-restore.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/session/checkpoint-restore.ts) | `a1aa2fa03033b464380c068924056c647325ed6753134bd57a56348a5a9dfe03` |
| cline | [sdk/packages/core/src/session/services/persistence-service.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/core/src/session/services/persistence-service.ts) | `d89fa9c138f4bb361fa54605ce22ddfdc969df7c64c07a64ae616419c7c1793f` |
| cline | [sdk/packages/llms/src/providers/vendors/openai-compatible.ts](https://github.com/cline/cline/blob/4515a410a06e92a78608d5267171a340d2aa32f6/sdk/packages/llms/src/providers/vendors/openai-compatible.ts) | `c9cfe9b6a8e021e94f642b54b9b55595d7544559c8d65a21ad5f8b1f055b37df` |
| aider | [aider/coders/base_coder.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/base_coder.py) | `04a7b38c4f1d2b1684ac958f40bcd81a28b00139eae88afed59d2c970bef1ee1` |
| aider | [aider/coders/editblock_coder.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/editblock_coder.py) | `244df08f5ccd19928bcdac1901ae591a7a786d12a6f70d31400baaefb5a136a3` |
| aider | [aider/commands.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/commands.py) | `4457e9da5ac3d89003648d68f596aa9857a7e76e36dcff8ebd10f4b59ccd77e7` |
| aider | [aider/history.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/history.py) | `5c9377875d6c9268ba16ec6cfd3cc30c7d3d8c23d42ffb2a5c3bc375aefc7e79` |
| aider | [aider/models.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/models.py) | `37784de662eeafacf17cbc4eb656246aadee20477b8ad43768caf7d373ab6e0d` |
| aider | [aider/repomap.py](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/repomap.py) | `a5d4befe70445114b9f62da47b0eeb2a5384f9e84a0c083c77a4b339caf61ecd` |
| openhands | [package.json](https://github.com/OpenHands/OpenHands/blob/1ff45c267fe5737c9387ccaf54d44cab3da6d9dd/package.json) | `0b11ca82ca4f6c1f062f62d138a7d1681c0f0138aac88c9cc48832a477af1f80` |
| openhands | [README.md](https://github.com/OpenHands/OpenHands/blob/1ff45c267fe5737c9387ccaf54d44cab3da6d9dd/README.md) | `b7c1e6e52f95654bbf812ed442d28955392fa238c3fb50a49e3e2bb24b862159` |
| openhands | [src/api/README.md](https://github.com/OpenHands/OpenHands/blob/1ff45c267fe5737c9387ccaf54d44cab3da6d9dd/src/api/README.md) | `932c22576c88a1ee11bf47a9e7cfa3a3d9afda91049be0c801f9671d3aeb6174` |
| openhands-sdk | [openhands-sdk/openhands/sdk/agent/agent.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/agent/agent.py) | `8e7e7cabbe4c079cca56f0aee9dbacd85b22353e460532322f4ac81d49115879` |
| openhands-sdk | [openhands-sdk/openhands/sdk/agent/parallel_executor.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/agent/parallel_executor.py) | `a2ce8ebc42009a660c0eda2330958d0df1eb452b7b9f24da02f7c23f5f3038bb` |
| openhands-sdk | [openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py) | `8e3ddb4a770ba80d7aaa0b96247d95d8985cd860133b0efa6d0315de50727e6e` |
| openhands-sdk | [openhands-sdk/openhands/sdk/context/memory.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/context/memory.py) | `a6689139d83713560d67b075cc74ee59bff6da3201cf026d93fe610e227fa4cf` |
| openhands-sdk | [openhands-sdk/openhands/sdk/conversation/conversation.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/conversation/conversation.py) | `7fb48719db9006bb8ac4144fafdf6f036085d2eeaa7a09b70ce2c859dd4b8122` |
| openhands-sdk | [openhands-sdk/openhands/sdk/conversation/event_store.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/conversation/event_store.py) | `af721391c46a1979c45e0e414c45a82dfc42d8a92d62ac2ccea0242f725450b0` |
| openhands-sdk | [openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py) | `fb539877039c848fbec24b65961de0e089803553bf65d852414945c7975739c9` |
| openhands-sdk | [openhands-sdk/openhands/sdk/conversation/state.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/conversation/state.py) | `7e488ee6cb483f35b852bcb0900f5f49e0490a2b5bf28d6387d869d207727360` |
| openhands-sdk | [openhands-sdk/openhands/sdk/io/local.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/io/local.py) | `051913a427a03ec811f38697e362d71fd8f9df506895e38ee74a81890910131b` |
| openhands-sdk | [openhands-sdk/openhands/sdk/llm/llm.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/llm/llm.py) | `a3261d1d021eebeb81114acdf3e36c38ea08e0bbb1d037def25c0ad8995f92d3` |
| openhands-sdk | [openhands-sdk/openhands/sdk/mcp/client.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/mcp/client.py) | `ddc68e0ab69ed9401399ed789ee4a523add3309811c6f196beffcac96b232c9c` |
| openhands-sdk | [openhands-sdk/openhands/sdk/security/confirmation_policy.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/security/confirmation_policy.py) | `6ecac839fa3740e5cdc8aae6515cd0cf4ef4177c5b27bb99a7d593af844c765f` |
| openhands-sdk | [openhands-sdk/openhands/sdk/tool/tool.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/openhands/sdk/tool/tool.py) | `c60d5c5b7598071c2a9f17eb223132b8eafa6aad3a139ec2840b9856bc7d6ccf` |
| openhands-sdk | [openhands-sdk/pyproject.toml](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-sdk/pyproject.toml) | `a7eebcfca6d031eaceec814fdc02ccd951961061ca726d2a4e6741685795f8e7` |
| openhands-sdk | [openhands-tools/openhands/tools/delegate/impl.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-tools/openhands/tools/delegate/impl.py) | `5641671e08e6abc7c7106ff75dba385353d2154aad06ac8f0eb4aef24d28ddc1` |
| openhands-sdk | [openhands-tools/openhands/tools/terminal/impl.py](https://github.com/OpenHands/software-agent-sdk/blob/53a4bc5014902ca84bb21fff30eac606ff4905aa/openhands-tools/openhands/tools/terminal/impl.py) | `60e668d8b75d52907568eff55f9ef81bac1f62727a37c9c722979dc45bb16245` |
| continue | [core/config/markdown/loadMarkdownSkills.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/config/markdown/loadMarkdownSkills.ts) | `502d651f8e6282cb604efff4d8104f0d7b43f2918e1eef4016798881caa309a7` |
| continue | [core/indexing/CodebaseIndexer.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/indexing/CodebaseIndexer.ts) | `08611069f4c88ba6fee313e6df46022e3e9b07cd1f90341e47186e592e704f19` |
| continue | [core/llm/index.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/llm/index.ts) | `1e81cf6e96e415262950f23302562462fc7bf713ca4f2f62ade019a52e6198e6` |
| continue | [core/llm/llms/OpenAI.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/llm/llms/OpenAI.ts) | `01ec4636ee1c0b16046724e039ee0098c4149b0fd37f83fa9c64e6ad8d26b218` |
| continue | [extensions/cli/src/compaction.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/compaction.ts) | `d0ef6111106c10073da4eac1d5df8a814b63bd68b67f3ecc8f7d7092426f047e` |
| continue | [extensions/cli/src/permissions/permissionChecker.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/permissions/permissionChecker.ts) | `4f31a1b7430ec26312d8fd79159a6acaa750b685e2c9d2f0c32777eabc01c787` |
| continue | [extensions/cli/src/permissions/precedenceResolver.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/permissions/precedenceResolver.ts) | `f5bb75685d4b04117e162182b711571e414da4b007a1b542f2dbd3c60c0a1a33` |
| continue | [extensions/cli/src/session.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/session.ts) | `08f9d93f804fed2b9cb6f153f931d2fbd470466de7ab5f4f040c78e3281e3e2b` |
| continue | [extensions/cli/src/subagent/executor.ts](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/subagent/executor.ts) | `c8c2ad8294c34be82098511ba35dd871265d89878acdb8e64aaa1062de36eab9` |
| goose | [crates/goose/src/agents/agent.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/agents/agent.rs) | `c0e6128bb6bf400ea066e908f2656159c2c1895a0061a1e44f030078922ec193` |
| goose | [crates/goose/src/agents/extension_manager/mod.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/agents/extension_manager/mod.rs) | `cca72e241d8786ba44256a8d2e4671f3f353e6b57e04427b8892a3c346bf1943` |
| goose | [crates/goose/src/agents/subagent_handler.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/agents/subagent_handler.rs) | `86e6001c7f292ddeef77cbb4351dfb46cad4c5ba88dde7637d4ac5dd0a295978` |
| goose | [crates/goose/src/agents/subagent_task_config.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/agents/subagent_task_config.rs) | `0d92505f86ccf16de6032f674150e78fc43dc29d7e78d98e30d5e0cf71af4e4f` |
| goose | [crates/goose/src/context_mgmt/mod.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/context_mgmt/mod.rs) | `8747c8239e2ef43ac9db9012f0d9110479e73c0931249409c34d90b5f6ac9769` |
| goose | [crates/goose/src/permission/permission_inspector.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/permission/permission_inspector.rs) | `c9944a12742c443bb834abead6f3a5120f6b09d666a41d80ab1491752b545390` |
| goose | [crates/goose/src/providers/base.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/providers/base.rs) | `0f3545ba8bb149ec38f6ecab97a686b68bdeb7cf20ff9a6ab28d06c31235c941` |
| goose | [crates/goose/src/recipe/mod.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/recipe/mod.rs) | `a3a44044680ba30f447836d31d96f4cbf625683289625c2457ae90f0c6a56fe1` |
| goose | [crates/goose/src/session/session_manager.rs](https://github.com/block/goose/blob/caadd5f6bcc27c84cd6e4588666a4e3ccc18cc15/crates/goose/src/session/session_manager.rs) | `089428a6cc15875360c72a44a6b1220f729a4bb3dd6275321285870c223926c6` |
| pi | [packages/agent/src/agent-loop.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/agent/src/agent-loop.ts) | `e773e822a2587caf314e6bb66ea6370fce3468b7eecd26d6a67afe673f81eabc` |
| pi | [packages/agent/src/agent.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/agent/src/agent.ts) | `7024a3145a6ebc951a0f030164adb1dfb12d33d6e0dbbac15ef0efda49c87457` |
| pi | [packages/ai/src/types.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/ai/src/types.ts) | `7ac401b31a7679a77469037091093c4c25d3719d7c9e9078378fece509fa8e8d` |
| pi | [packages/coding-agent/src/core/agent-session.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/agent-session.ts) | `11ce7b78ee9d4235f2cdc80632332c93935ad23d7e5d68fe1aa5b155e1a297c0` |
| pi | [packages/coding-agent/src/core/compaction/compaction.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/compaction/compaction.ts) | `d5aebd41333957b57fa3f1bee2a18b3c00b5d47bb1b4af6f913cf8cd791099c8` |
| pi | [packages/coding-agent/src/core/extensions/runner.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/extensions/runner.ts) | `1a0d73843fba5773d415f484c46898138723b73d27bf8c3159f491fa0b6232f3` |
| pi | [packages/coding-agent/src/core/session-manager.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/session-manager.ts) | `450d82c529933214e088b8422f00061815e617f352f6c834689787a314064bff` |
| pi | [packages/coding-agent/src/core/skills.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/skills.ts) | `055dbfde974fd1951267dd6f9204b5d713ff0004e0991eb870fce9158c6e359a` |
| pi | [packages/coding-agent/src/core/tools/bash.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/core/tools/bash.ts) | `de2b54d4f4bfbb844ce6d8077f63d715f7d8e80079dd9689b561e45b6679c81b` |
| pi | [packages/coding-agent/src/modes/rpc/rpc-mode.ts](https://github.com/badlogic/pi-mono/blob/7fbbd5f4a1d982bb02d63472dde0774fa639f99b/packages/coding-agent/src/modes/rpc/rpc-mode.ts) | `36dbbf3f884af4c9cd1f51bbad6b2c7a4e442b0c83ebcabf0eb5ee3440afb9bd` |
| mcp | [LICENSE](https://github.com/modelcontextprotocol/python-sdk/blob/17aaf2557205c3768ed61831398a4e074b21e96d/LICENSE) | `5e13dbbc1d120fc2a03cecde7c91424ae2d7de11b63d58ded2f4431e261ee50d` |
| mcp | [src/mcp/client/session.py](https://github.com/modelcontextprotocol/python-sdk/blob/17aaf2557205c3768ed61831398a4e074b21e96d/src/mcp/client/session.py) | `fb1365c908c0dfc65ad9b59f63d1f5d433153c5da050725f5f98450871fc9a39` |
| llama | [LICENSE](https://github.com/ggml-org/llama.cpp/blob/207bdab95010a0489e661bad8ca109c96aad46a8/LICENSE) | `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d` |
| llama | [tools/server/README.md](https://github.com/ggml-org/llama.cpp/blob/207bdab95010a0489e661bad8ca109c96aad46a8/tools/server/README.md) | `37866b6b348e49a44205f776467afc16322d136bfa06c4448354a6c93b74f52e` |
| vllm | [docs/serving/online_serving/openai_compatible_server.md](https://github.com/vllm-project/vllm/blob/4056c8ac1f8a7e8fb50cf1c56ff96649fcadccc6/docs/serving/online_serving/openai_compatible_server.md) | `7170004eb80878c31d5a47ac9f7dfc2df06842c4968fac5187f8f25b4b4030a5` |
| vllm | [LICENSE](https://github.com/vllm-project/vllm/blob/4056c8ac1f8a7e8fb50cf1c56ff96649fcadccc6/LICENSE) | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| comfy | [LICENSE](https://github.com/Comfy-Org/ComfyUI/blob/65787d668397d230bf5839d69a0a7239e2dad378/LICENSE) | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |
| comfy | [server.py](https://github.com/Comfy-Org/ComfyUI/blob/65787d668397d230bf5839d69a0a7239e2dad378/server.py) | `7dc4ca3bd801a64da1fe7c2d1af81da61999f6b96dd96637d456e0562e8ce40b` |

## Audited tracked inventory

At the initial baseline, 80 tracked files. This inventory is taken from the fixed audited commit, not a later working-tree snapshot. No ignored runtime artifact is implied by this list.

```text
.archify/architecture-freecompute-20260930-234700/candidate.json
.archify/architecture-freecompute-20260930-234700/freecompute.browser-check.json
.archify/architecture-freecompute-20260930-234700/freecompute.delivery.json
.archify/architecture-freecompute-20260930-234700/freecompute.finalize-summary.json
.archify/architecture-freecompute-20260930-234700/freecompute.finalize.json
.archify/architecture-freecompute-20260930-234700/freecompute.html
.env.example
.gitignore
AGENTS.md
CHANGELOG.md
CODE_OF_CONDUCT.md
CONTRIBUTING.md
LICENSE
README.md
SECURITY.md
build_dataset_nb.py
build_universal_nb.py
generate_image.py
harness/__init__.py
harness/cli/formatter.py
harness/cli/image.py
harness/cli/main.py
harness/config.py
harness/config.sample.yaml
harness/core/__init__.py
harness/core/client.py
harness/core/models.py
harness/core/orchestrator.py
harness/core/prompt.py
harness/providers/__init__.py
harness/providers/base.py
harness/providers/comfyui.py
harness/providers/llamacpp.py
harness/skills/__init__.py
harness/skills/manager.py
harness/storage/journal.py
harness/storage/undo.py
harness/telemetry/quota_ledger.py
harness/telemetry/session_tracker.py
harness/tools/__init__.py
harness/tools/fs.py
harness/tools/registry.py
harness/tools/sandbox.py
harness/tools/terminal.py
harness/tools/web.py
kaggle/dataset_builder.ipynb
kaggle/freecompute_dual_gpu_server.ipynb
kaggle/supervisor.py
kaggle/universal_dual_gpu_server.ipynb
knowledgebase/ARCHITECTURE_DECISIONS.md
knowledgebase/DEPLOYMENT_RUNBOOK.md
knowledgebase/KAGGLE_QWEN_CODING_HARNESS_HANDOFF.md
knowledgebase/PHASE_0_AUDIT_AND_ARCHITECTURE.md
knowledgebase/PROGRESS_TRACKER.md
knowledgebase/ROADMAP.md
pyproject.toml
qwen3-8-27b-abliterated-q4-kaggle-dual-t4-proof.ipynb
qwen_image_2_1_kaggle.ipynb
qwen_image_2_1_uncensored_colab.ipynb
requirements.txt
run.bat
run.ps1
run_image.bat
run_image.ps1
skills/code-reviewer/SKILL.md
skills/neetcode-solver/SKILL.md
skills/web-researcher/SKILL.md
tests/security_scan.py
tests/unit/test_cli_smoke.py
tests/unit/test_client.py
tests/unit/test_fs_tools.py
tests/unit/test_journal.py
tests/unit/test_orchestrator.py
tests/unit/test_providers.py
tests/unit/test_sandbox.py
tests/unit/test_skills.py
tests/unit/test_telemetry.py
tests/unit/test_terminal.py
tests/unit/test_undo.py
tests/unit/test_web_tools.py
```

## Final document verification

The required unit command was rerun after writing: **42 tests passed**, 1.301 seconds. The repository scanner then reported **99 files, zero pattern matches**, exit 0. Its printed release-safety wording is not endorsed by this audit. Markdown relative targets were checked: no missing targets.

All fourteen new documents are under `knowledgebase/`; the six existing documents received only a historical notice, with their original bodies preserved. Comparison to the fixed initial baseline found no non-knowledgebase content changes after accounting for pre-existing Windows checkout CRLF conversion. Production modules, config, launchers, tests and notebook content were unchanged.

Git HEAD advanced while documents were being written; this agent did not invoke commit, push, merge or reset. Validation therefore used the original fixed audit commit, rather than assuming HEAD remained stationary. Those commits were left intact.
