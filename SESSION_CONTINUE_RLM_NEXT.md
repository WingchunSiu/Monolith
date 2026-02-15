# RLM Next Steps — Continue From Here
**Continues from**: `SESSION_2026-02-14_RLM_DEEP_DIVE.md`
**Date**: 2026-02-14 (late)

---

## Where We Left Off

- Modal set up (workspace: `dmku33`, volume: `rlm-context`)
- `/upload-context` skill works — uploads session transcripts to Modal volume
- `SessionEnd` hook configured for auto-upload
- 3 sessions already on volume (~113 KB total)
- DeepRecurse repo pulled into `deep-recurse-s3/`

## Key Architecture Decision: Pre-process on Close, Not on Open

**Problem**: If Dev B opens a session and has to wait for RLM to process all shared sessions (could be 200MB+), that's 2+ minutes of dead time.

**Solution**: Async pre-compilation pipeline.

```
Dev A closes CC
  ↓ SessionEnd hook
  ├─ Upload transcript to Modal volume        (few seconds)
  └─ Spawn Modal function (async):            (runs in background)
      ├─ Pull all session transcripts from volume
      ├─ Run RLM to produce compiled context:
      │   • Cross-session summary
      │   • Key decisions & patterns
      │   • Searchable index
      └─ Write compiled_context.txt back to volume

Dev B opens CC
  ↓ SessionStart hook (or manual)
  ├─ Pull compiled_context.txt from volume    (instant, pre-digested)
  └─ Ready to work
```

RLM runs **between sessions**, not during them. The heavy compute is hidden.

## Original RLM Optimization: What They Did

The full RLM (`rlm/`) optimizes **sub-LLM inference**, not storage:
- `llm_query_batched(prompts)` — fires N sub-LLM calls concurrently
- `ThreadingTCPServer` handles concurrent socket requests from REPL to LM handler
- Each request routes to the right backend (OpenAI, Anthropic, etc.)
- Model writes `llm_query_batched([p1, p2, ...])` and all API calls happen in parallel

They assume context is in-memory (fast slicing). Bottleneck = LLM API latency.

## TODO: Build Order

### Phase 1: Modal Sandbox + RLM in Cloud
- [ ] Create Modal function that mounts `rlm-context` volume
- [ ] Pull all transcripts into RAM at function start
- [ ] Run rlm-minimal on the concatenated context
- [ ] Test with a simple query ("summarize all sessions")

### Phase 2: Async Pre-compilation Pipeline
- [ ] On SessionEnd: after upload, `modal run` a pre-compilation function
- [ ] RLM processes all sessions → produces `compiled_context.txt`
- [ ] On SessionStart: hook pulls `compiled_context.txt` into Claude Code context
- [ ] Measure: how fast is the open-session experience?

### Phase 3: Swappable Backend (Claude Agent SDK)
- [ ] Replace OpenAI calls with Claude API
- [ ] Sonnet as root/orchestrator model
- [ ] Haiku as recursive/sub-LLM model (cheap, fast)
- [ ] Target: multi-provider hackathon prize
- [ ] Use Claude Agent SDK for orchestration

### Phase 4: Multi-user Shared Context
- [ ] Multiple devs uploading to same volume
- [ ] Pre-compiled context includes all devs' sessions
- [ ] Conflict handling (concurrent writes to volume)
- [ ] Consider Modal Dict for real-time shared state

## Files Created This Session

| File | What It Does |
|------|-------------|
| `scripts/upload_context.py` | Parse Claude Code JSONL → upload to Modal volume |
| `scripts/session_end_upload.sh` | Hook script for auto-upload on session end |
| `.claude/skills/upload-context.md` | `/upload-context` skill definition |
| `.claude/settings.local.json` | SessionEnd hook config |
| `deep-recurse-s3/` | Pulled DeepRecurse repo (pranav/s3-stuff branch) |
| `SESSION_2026-02-14_RLM_DEEP_DIVE.md` | Full deep dive notes |
| `SESSION_CONTINUE_RLM_NEXT.md` | This file |

## Quick Commands Reference

```bash
# Upload latest session
python3 scripts/upload_context.py

# Upload all sessions
python3 scripts/upload_context.py --all

# Check what's on the volume
modal volume ls rlm-context /sessions/

# Download a transcript to inspect
modal volume get rlm-context /sessions/<id>/transcript.txt -

# Create/delete volumes
modal volume create <name>
modal volume delete <name>
```
