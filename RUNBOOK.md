# ROBIN — Runbook

## Model Routing

### Current Configuration (Phase 3)

| Tier | Role | Provider | Model | Cost |
|------|------|----------|-------|------|
| REASONING | Primary | OpenRouter | moonshotai/kimi-k2.5 | ~$0.15/M in, $0.60/M out |
| SIMPLE | Delegation | Ollama local | gemma4:26b | $0 |
| AUXILIARY | Side tasks | Ollama local | gemma4:26b | $0 |
| VISION | Images | Primary (Kimi) | — | included |

**Azure AI Foundry** (target PRIMARY when key is available):
- Endpoint: `AZURE_OPENAI_ENDPOINT` in `.env`
- Deployment: `AZURE_OPENAI_DEPLOYMENT` in `.env`
- Key: `AZURE_OPENAI_KEY` ← **NOT YET SET**
- Activate: uncomment Azure block in `config.yaml`, comment OpenRouter block

### Switching to Azure (when key is ready)

1. Add `AZURE_OPENAI_KEY=<your-key>` to `Robin_V4/.robin/.env`
2. Edit `Robin_V4/.robin/config.yaml`:
   - Comment out: `default: moonshotai/kimi-k2.5` + `provider: openrouter`
   - Uncomment: Azure block (`provider: custom`, `model: Kimi-K2.5`, etc.)
   - Uncomment: `fallback_model` block at bottom
3. Run `robin doctor` — should show config valid
4. Test: `robin chat` → verify response comes from Azure in logs

---

## A/B Test Log — Gemma 4 26B as Delegation/Auxiliary Tier

**Start date:** 2026-04-30
**Target eval date:** 2026-05-07 (1 week)

### Metrics to track

| Metric | Target | Result |
|--------|--------|--------|
| Delegation response time (casual chat) | <2s | TBD |
| Delegation quality (subjective) | "good enough" | TBD |
| Compression quality vs Kimi | acceptable | TBD |
| Kimi token savings vs all-Kimi baseline | >30% | TBD |

### Decision after eval

- [ ] Gemma fast enough? Keep as SIMPLE tier
- [ ] Gemma quality good enough as PRIMARY fallback? Yes/No
- [ ] Vision split worth it? Gemma for screenshots, Kimi for complex?

---

## Monthly Cost Estimate

*To be filled after 1 week of real use.*

| Component | Estimated monthly | Actual |
|-----------|-----------------|--------|
| Azure Foundry / OpenRouter Kimi | TBD | — |
| Ollama (electricity, M4 ~5W idle / ~50W inference) | ~$3–5 CAD | — |
| Telegram bot | $0 | — |
| **Total** | **TBD** | — |

---

## Common Operations

### Restart gateway

```bash
cd ~/Robin/Robin_V4
ROBIN_HOME=.robin .venv/bin/robin gateway restart
```

### Check logs

```bash
tail -f ~/.robin/logs/robin.jsonl | python3 -m json.tool
```

### Verify Ollama is running

```bash
curl http://localhost:11434/api/tags
```

### Force-pull Gemma model

```bash
ollama pull gemma4:26b
```

### View active config

```bash
cat ~/Robin/Robin_V4/.robin/config.yaml
```
