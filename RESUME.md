# ROBIN — Resume Point

## Current Phase
Phase 0 — Mac Setup, Fork, Baseline  
Status: **In Progress**

## Upstream Tracking
- Base commit (Hermes): `8d302e37a8966a20c472c6ef202524685b864021`
- Commit message: `feat(tts): add Piper as a native local TTS provider (closes #8508) (#17885)`
- Fork date: 2026-04-30
- Last upstream sync: N/A (fresh fork)
- Pending upstream deltas: No

## Last Completed Step
→ Fork cloned to `~/code/robin`, upstream remote added, Python 3.11 venv created with `uv`, hermes installed with messaging+cli+honcho+pty extras. `hermes --version` returns v0.11.0. `FORK_NOTES.md` created at repo root. `~/.robin/` directory structure initialized. `~/.robin/.env` template created. `nomic-embed-text` pulled successfully to Ollama.

## Next Step
→ Add OpenRouter API key to `~/.robin/.env`, then run `HERMES_HOME=~/.robin hermes setup` (interactive) and `hermes chat` to verify end-to-end baseline response.

## Open Questions / Blockers
→ **OpenRouter API key** — Shanu needs to add this to `~/.robin/.env` (line: `OPENROUTER_API_KEY=`)
→ **pmset sleep** — needs `sudo pmset -a sleep 0 && sudo pmset -a disksleep 0` run manually in Terminal (sudo required)
→ **gemma4 Ollama tag** — `gemma4:27b` tag not found; verifying correct tag name on ollama.com
→ **Telegram bot token** — Creating new bot via @BotFather (next step after hermes chat works)

## Session Notes
- Tailscale is installed as `.app` at `/Applications/Tailscale.app` (v1.96.5), not via Homebrew CLI — works fine
- iPhone replaces Pixel 4a as the Telegram testing device
- `uv` v0.11.8 installed via Homebrew
- `HERMES_HOME` env var lets us point hermes at `~/.robin` without any code changes ✅
- gemma4 pull in background failed due to wrong tag — finding correct Ollama tag

## Upstream Deltas This Session
→ Core files changed: NONE (unmodified upstream baseline)
→ Added: `FORK_NOTES.md`, `RESUME.md` (new files, not in upstream)

## Phase 0 Definition of Done — Status
- [ ] `robin` repo on Shanu's GitHub as clean fork  ← ✅ Done (created 2026-04-30)
- [ ] ROBIN (still hermes) runs on Mac Mini ← ✅ `hermes --version` works
- [ ] End-to-end: iPhone Telegram → Mac → LLM → response ← ⏳ Pending OpenRouter key + bot token
- [ ] Shanu explains four memory layers in own words ← ⏳ Pending (discuss at end of phase)
- [ ] `RESUME.md` and `FORK_NOTES.md` at repo root ← ✅ Both created
- [ ] `pmset -g` shows sleep = 0 ← ⏳ Pending (sudo required from Terminal)
