# FORK_NOTES.md — ROBIN Fork Metadata

## Upstream Origin

- **Upstream repo:** `github.com/NousResearch/hermes-agent` (MIT License)
- **Base commit hash:** `8d302e37a8966a20c472c6ef202524685b864021`
- **Base commit message:** `feat(tts): add Piper as a native local TTS provider (closes #8508) (#17885)`
- **Fork date:** 2026-04-30
- **Fork owner:** decodedbyrajat (Shanu / Rajat)
- **Fork repo:** `github.com/decodedbyrajat/Robin`

## Attribution

ROBIN is a fork of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).  
Original Hermes code © Nous Research under the MIT License.  
See `LICENSE.HERMES.md` for the original license text.

## Customizations Per Phase

### Phase 0 — Mac Setup, Fork, Baseline (2026-04-30)
- Status: In Progress
- Upstream deltas: None — unmodified baseline
- Added: `FORK_NOTES.md`, `RESUME.md` (this file and resume)
- Venv: Python 3.11.15 via uv at `/Users/ifthenvoid/Robin/Robin_V4/.venv`
- Extras installed: `messaging`, `cli`, `honcho`, `pty`

### Phase 1 — Strip (planned)
- TBD

### Phase 2 — Rebrand (planned)
- TBD

### Phase 3 — Tier Routing (planned)
- TBD

---

## Upstream Sync Policy

- Pull upstream only between sealed phases
- Command: `git fetch upstream && git merge upstream/main`
- Never during an active phase
- Document deltas here after each sync

## Core Files Modified (vs Upstream)

| File | Change | Phase | Reason |
|------|--------|-------|--------|
| `FORK_NOTES.md` | NEW | 0 | Fork tracking |
| `RESUME.md` | NEW | 0 | Session continuity |
