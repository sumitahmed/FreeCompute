# Security policy

FreeCompute 0.1.x is a beta CLI candidate. Report vulnerabilities privately through
the repository's GitHub Security tab or its maintainers. Do not post credentials
or private workspace contents in public issues. No response-time SLA is promised.

The remote worker proposes inference results. Only local Core validates tool
arguments, obtains explicit approval, executes tools and records durable receipts.
File tools enforce workspace/protected-path/reparse boundaries. Edits, writes,
commands and undo require approval. **An approved shell command runs with your
user privileges, not in an OS sandbox**; inspect its command and cwd carefully.

Prompts, selected file contents and tool results reach the inference host. Transport
encryption does not hide them from that host or make model output trustworthy.
Untrusted web/model content does not grant permission. Web tools reject private/
local addresses, validate redirect targets and bound response size; those checks
are not an OS network sandbox or protection against every DNS rebinding race.

The Kaggle supervisor requires a nonempty bearer key on all public endpoints.
Text and image credentials are separate; keys come from private dotenv/process
environment/config references and are never printed. Authenticated adapters reject
redirect forwarding. Non-loopback image routes require an authenticated gateway;
the fixed ComfyUI workflow is not an authentication server by itself. Temporary
/connect and /connect-image URLs stay in memory. Active/uncertain leases fence
endpoint changes. Source/config samples contain no live tunnel endpoints.

`harness/security.py` owns SecretScrubber and stream redaction. Registered secrets
and known token/URL patterns are scrubbed before output/state; terminal controls
from untrusted text are removed. Redaction is best effort for unregistered secrets
and is not general data-loss prevention. Never put secrets in prompts or approve
commands that print them. Private dotenv/config files, journals and generated
assets must stay ignored and outside public artifacts.

Unknown external outcomes keep capacity held across restart; health or low GPU
utilization cannot release it. Idle reconciliation requires independent evidence
and explicit approval. Dataset manifests verify integrity/provenance for your own
trusted assets; they do not authenticate a stranger's executable.

See [the runtime security model](knowledgebase/V2_SECURITY_MODEL.md) and
[telemetry limitations](knowledgebase/WORKER_TELEMETRY.md). Security tests, package
acceptance and scans use synthetic fixtures; they do not certify all providers,
transports, user commands or model behavior.
