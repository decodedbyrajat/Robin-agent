# Robin Agent Security Policy

Robin is a personal agent for a trusted operator. It can run commands, read and
write files, call APIs, and connect to messaging platforms, so treat it like a
powerful local automation tool.

## Reporting Security Issues

Do not open public issues for vulnerabilities. Use GitHub Security Advisories
for the project repository:

https://github.com/IfThenVoid/Robin/security/advisories/new

Include:

- A clear title and severity.
- Affected files or components.
- Operating system, Python version, Robin version or commit SHA.
- Reproduction steps.
- Impact and what security boundary was crossed.

## Trust Model

- Robin assumes one trusted operator.
- Messaging callers that pass your configured allowlists are trusted.
- `terminal.backend: local` runs directly on the host.
- Skills are local code and should be reviewed before installation.
- MCP servers run with a filtered environment, but should still be treated as
  third-party code.

## Approval Boundary

The command approval system in `tools/approval.py` is the main safety gate for
dangerous terminal and file operations. Keep approvals enabled unless you are in
a controlled break-glass session.

## Secrets

Store credentials only in `~/.robin/.env` or the configured Robin home. Do not
put API keys in `config.yaml`, skill files, prompts, docs, or checked-in data.
Display output is redacted by `agent/redact.py`, but redaction is a last line of
defense, not a substitute for safe secret handling.

## Hardening

- Use Docker or SSH-backed isolation for untrusted workloads.
- Keep `~/.robin/.env` private with `chmod 600`.
- Do not expose the gateway or API server publicly without VPN, Tailscale, or a
  firewall.
- Review third-party skills and MCP servers before enabling them.
- Keep dependencies current and run `robin doctor` after upgrades.

## Out of Scope

- Prompt injection that does not bypass approvals, tool restrictions, or a real
  sandbox boundary.
- Reports requiring pre-existing write access to `~/.robin`, `.env`, or
  `config.yaml`.
- Host command execution when `terminal.backend` is intentionally set to
  `local`.
