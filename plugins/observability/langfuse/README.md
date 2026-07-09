# Langfuse Observability Plugin

This plugin ships bundled with Robin but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
robin tools  # → Langfuse Observability

# Manual
pip install langfuse
robin plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.robin/.env` (or via `robin tools`):

```bash
ROBIN_LANGFUSE_PUBLIC_KEY=pk-lf-...
ROBIN_LANGFUSE_SECRET_KEY=sk-lf-...
ROBIN_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
robin plugins list                 # observability/langfuse should show "enabled"
robin chat -q "hello"              # then check Langfuse for a "Robin turn" trace
```

## Optional tuning

```bash
ROBIN_LANGFUSE_ENV=production       # environment tag
ROBIN_LANGFUSE_RELEASE=v1.0.0       # release tag
ROBIN_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ROBIN_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ROBIN_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
robin plugins disable observability/langfuse
```
