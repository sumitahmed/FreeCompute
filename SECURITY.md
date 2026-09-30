# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

---

## Reporting a Vulnerability

If you discover a security vulnerability within FreeCompute, please report it privately. **Do not open a public GitHub issue.**

Please report security vulnerabilities by creating a Private Security Advisory via GitHub's Security tab or by contacting the maintainers directly. You will receive a response within 48 hours.

---

## Security Model & Guarantees

### 1. Local-First Isolation & Tool Sandboxing
- FreeCompute treats the remote GPU host as an untrusted inference provider.
- All tool execution (`edit_file`, `write_file`, `run_command`, `search_web`) runs strictly on your local machine under local sandbox constraints (`harness/tools/sandbox.py`).
- Protected directories (`.git`, `.ssh`, `.env`, `.aws`) are blocked from agent inspection or modification.
- Risky filesystem modifications and shell commands require explicit interactive user approval before execution.

### 2. Transport Security & Network Ingress
- **Tailscale WireGuard Mesh (Recommended):** Creates an end-to-end encrypted, private network between your local machine and the remote GPU container. No ports are published to the public internet.
- **Cloudflare Tunnel (`cloudflared`):** Provides TLS-encrypted transport from the edge to the remote supervisor on port `8081`. All endpoints enforce `Authorization: Bearer <TOKEN>` authentication.

### 3. Truth in Remote Privacy
- **Transport Encryption vs. Host Runtime:** While transport between your PC and the remote supervisor is encrypted, prompts and generated code are processed by the remote inference engine inside the remote container.
- If running on free hosted cloud services (e.g., Kaggle or Google Colab), your compute session runs within the host provider's terms of service and infrastructure. Cloudflare encryption protects data in transit across the public internet, but does not conceal activity from the host container runtime.

### 4. Credential Redaction
- FreeCompute includes a built-in `SecretScrubber` (`harness/cli/formatter.py`) that filters API keys, Bearer tokens, private tunnel URLs, and credentials before terminal display or disk logging.
- Never commit `.env` or `config.yaml` to source control.
