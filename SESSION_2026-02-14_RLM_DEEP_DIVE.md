# RLM Deep Dive & S3 Optimization Session
**Date**: 2026-02-14
**Version**: v1 — initial understanding + architecture mapping + optimization plan

---

## 1. What is RLM? (The Paper's Core Idea)

RLM (Recursive Language Model) is an **inference paradigm** that enables LLMs to process **near-infinite context lengths** by giving them a Python REPL environment.

Instead of cramming a 1M-line document into the context window, the LLM:
1. Gets a `context` variable in a sandboxed Python REPL
2. Writes code to explore/slice/chunk that context
3. Calls `llm_query(prompt)` to delegate semantic understanding of chunks to sub-LLMs
4. Iterates (up to 20-30 rounds) until it has enough info
5. Returns a final answer via `FINAL(answer)` or `FINAL_VAR(variable_name)`

**Key insight**: The LLM doesn't read the whole context — it **programs its way through it**.

---

## 2. Three Codebases in This Repo

### 2a. `rlm/` — Full Production RLM
- ~3000+ LOC, pip-installable as `rlms`
- 9 LLM backends (OpenAI, Anthropic, Gemini, Azure, etc.)
- 6 execution environments (Local, Docker, Modal, Prime, E2B, Daytona)
- TCP socket protocol between REPL and LM handler (enables cloud sandboxing)
- `llm_query_batched()` for concurrent sub-LLM calls
- Trajectory logging + React visualizer
- Token/cost tracking per model
- 100+ tests

### 2b. `rlm-minimal-modded/` — Our Modified Minimal Version
- ~600 LOC, stripped to essentials
- OpenAI only, local execution only
- Direct function calls (no TCP sockets)
- Added `analyze_sessions.py` for **automatic single-file processing**
  - Load a chat/transcript file → feed to RLM → get structured summary
  - RLM internally chunks, queries sub-LLMs, aggregates
- Uses `gpt-5` as root model, `gpt-5-nano` as recursive model
- Context is an **in-memory Python string** — slicing is nanoseconds

### 2c. `deep-recurse-s3/` — DeepRecurse (Pulled from WingchunSiu/DeepRecurse, branch pranav/s3-stuff)
- Extends RLM with **S3-backed context storage**
- Two approaches on different branches:
  - **pranav/s3-stuff** (current): TranscriptRLM with Modal CloudBucketMount filesystem interface
  - **pranav/s3** (experimental): `Monocontext` class — S3 lazy-loading with `__getitem__` slicing

---

## 3. The S3 Context Problem

### What Changed: String → S3 Objects

| Aspect | Original RLM | DeepRecurse S3 |
|--------|-------------|----------------|
| Context storage | In-memory Python string | ~1000 S3 objects × ~1000 lines each |
| `context[0:5000]` | Nanoseconds (string slice) | ~1-3 seconds (multiple S3 GET calls) |
| `len(context)` | Instant | First call fetches manifest from S3 |
| Full materialization | Already in memory | Would require fetching ALL 1000 objects |

### How Monocontext Works (pranav/s3 branch)

```python
@dataclass
class Monocontext:
    bucket: str           # S3 bucket name
    prefix: str           # Key prefix
    manifest_name: str    # "manifest.json"
```

**Manifest**: JSON array stored in S3
```json
[
  {"segment": "segment_000001.log", "start_line": 0, "line_count": 1000},
  {"segment": "segment_000002.log", "start_line": 1000, "line_count": 1000},
  ...
]
```

**`__getitem__(slice)`**: When model writes `context[500:1500]`:
1. Looks up manifest to find which segments overlap lines 500-1500
2. Issues **sequential** S3 GetObject for each overlapping segment
3. Extracts relevant lines from each
4. Joins and returns as string

**`__len__()`**: Loads manifest once, caches total line count.

**REPL injection**: `context_obj` parameter passes the Monocontext directly into REPL locals — no serialization needed.

### The Performance Bottleneck

Current: **Sequential S3 fetches**
- `context[0:50000]` = 50 segments × ~150ms each = **~7.5 seconds**
- `context[0:1000000]` = 1000 segments × ~150ms each = **~150 seconds**
- The RLM does this **multiple times per iteration** across **multiple iterations**
- Total wallclock: minutes to tens of minutes for what should take milliseconds

---

## 4. Optimization Strategy (Three Layers)

### Layer 1: Systems Prompt
**What**: Tell the model to use smarter access patterns.
**Impact**: Low-medium. Model might still generate `for i in range(1000)` loops.
**Actions**:
- Instruct model to use large slice ranges instead of line-by-line
- Teach batch-first patterns
- Warn against full materialization

### Layer 2: REPL Environment Interception (BIGGEST LEVER)
**What**: Override `__getitem__` to parallelize S3 calls invisibly. The model writes `context[0:50000]`, your backend fires 50 concurrent fetches.

**Key insight**: The model doesn't know or care where context lives. It writes Python slicing. Your infrastructure does the heavy lifting.

**Implementation ideas**:
```python
# In Monocontext.__getitem__:
async def _fetch_segments_parallel(self, segment_keys):
    async with aioboto3.Session().client('s3') as s3:
        tasks = [s3.get_object(Bucket=self.bucket, Key=k) for k in segment_keys]
        return await asyncio.gather(*tasks)
```

Or with `concurrent.futures.ThreadPoolExecutor`:
```python
def __getitem__(self, key):
    segments = self._find_overlapping_segments(key)
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(self._fetch_segment, segments))
    return self._stitch(results, key)
```

**Expected improvement**: 50 parallel fetches in ~300ms instead of ~7.5s sequential = **~25x speedup**.

### Layer 3: Storage Layer
**What**: Reduce the number of round-trips regardless of model behavior.

**3a. Bigger chunks**
- Current: 1000 objects × 1000 lines = very granular
- Better: 20 objects × 50,000 lines = fewer S3 calls
- `context[0:50000]` goes from 50 GETs to 1 GET

**3b. Local cache**
- First access pulls from S3, then cached in-memory
- RLM re-reads overlapping sections constantly during recursion — cache compounds fast
- LRU cache keyed by segment name

**3c. Prefetching**
- While model is "thinking" (LLM API call takes 2-5s), prefetch next likely chunks in background
- RLMs typically scan linearly first, then zoom into regions — predictable patterns
- Free fetch time during LLM inference latency

**3d. S3 byte-range requests**
- Instead of 1000 small objects, store one large object
- Use `Range` header to fetch byte ranges
- Combine with an offset index for line-to-byte mapping

### Combined Effect

| Approach | `context[0:50000]` latency |
|----------|---------------------------|
| Current (sequential) | ~7.5s |
| Parallel fetches only | ~300ms |
| Bigger chunks (50K/obj) | ~150ms (1 GET) |
| Parallel + cache (warm) | ~0ms |
| Single object + byte-range | ~100ms |

---

## 5. Product Abstraction

> The REPL environment that the RLM writes code against should expose the same `context[start:end]` API whether it's in-memory or S3-backed. The optimization is invisible to the model.

The model writes:
```python
chunk = context[50000:60000]
summary = llm_query(f"Summarize: {chunk}")
```

It doesn't know if `context` is:
- A Python string (nanoseconds)
- An S3-backed Monocontext with parallel fetches (milliseconds)
- A cached version (microseconds)

**That's the product**: transparent context scaling.

---

## 6. Architecture Diagram

```
                    User Query
                        │
                        ▼
                   ┌─────────┐
                   │ RLM_REPL │ (Root Model: gpt-5)
                   └────┬────┘
                        │
            ┌───────────┼───────────┐
            │     REPL Environment  │
            │                       │
            │  context = Monocontext│──── S3 Bucket
            │  (or local string)    │     ├─ manifest.json
            │                       │     ├─ segment_000001.log
            │  llm_query(prompt)────│──── Sub-LLM (gpt-5-nano)
            │  FINAL_VAR(var)       │
            └───────────────────────┘
                        │
                   Model writes:
                   context[0:10000]
                        │
                        ▼
              ┌─────────────────────┐
              │  Optimization Layer │
              │  • Parallel S3 GETs │
              │  • Local cache      │
              │  • Prefetching      │
              │  • Bigger chunks    │
              └─────────────────────┘
```

---

## 7. Hackathon / Demo Strategy

> For the demo, prefetch the whole thing into memory on session start and let slicing be fast. Optimize the streaming/lazy version after.

**Phase 1 (Demo)**:
- On `Monocontext.__init__`, fetch all segments in parallel into memory
- All subsequent slices hit in-memory cache
- Frame as "initializing shared knowledge base"

**Phase 2 (Post-hackathon)**:
- Lazy loading with parallel fetches
- LRU segment cache
- Prefetch during LLM think time
- Bigger chunk sizes or single-object-with-byte-ranges

---

## 8. Files Reference

### This Repo Structure
```
rlm-explorations/
├── rlm/                      # Full production RLM (pip: rlms)
├── rlm-minimal/              # Original minimal RLM
├── rlm-minimal-modded/       # Our modified version (analyze_sessions.py)
├── deep-recurse-s3/          # DeepRecurse (pulled pranav/s3-stuff)
│   ├── deeprecurse/
│   │   ├── store.py          # S3 transcript uploader
│   │   ├── config.py         # Constants (bucket, models)
│   │   ├── modal_app.py      # Modal cloud functions
│   │   └── rlm_runner.py     # TranscriptRLM (helpers for REPL)
│   ├── claude_tool_mcp/
│   │   └── server.py         # MCP tool server
│   ├── main.py               # CLI chat client
│   └── rlm-minimal/          # Their copy of rlm-minimal
│       └── rlm/
│           ├── monocontext.py # S3-backed context (on pranav/s3 branch)
│           └── repl.py        # Modified REPL with context_obj support
├── rlm-visualizer/           # Visualization tools
├── comparison.html           # RLM vs RLM-minimal comparison
└── platform-plan.html        # Multi-agent platform architecture
```

### Key Files for Optimization Work
| File | Why It Matters |
|------|---------------|
| `deep-recurse-s3/rlm-minimal/rlm/monocontext.py` | S3 lazy-loading — **optimize `__getitem__` here** |
| `deep-recurse-s3/rlm-minimal/rlm/repl.py` | REPL environment — `context_obj` injection |
| `deep-recurse-s3/rlm-minimal/rlm/utils/prompts.py` | System prompt — teach model better access patterns |
| `deep-recurse-s3/deeprecurse/config.py` | Chunk sizes, model selection |
| `rlm-minimal-modded/rlm/rlm_repl.py` | Our working RLM implementation |

---

## 9. Pivot: Modal Volume + Prefetch-to-RAM Approach

**Decision**: Instead of optimizing S3 lazy-loading (Monocontext), we're going simpler:
1. Store conversation context on a **Modal Volume** (`rlm-context`)
2. On session start, **pull everything into RAM** — slicing is nanoseconds
3. RLM runs in a **Modal Sandbox** with the volume mounted

This eliminates the entire S3 latency problem. 200MB of text in RAM is trivial.

### What We Built (2026-02-14)

#### `/upload-context` Skill
- **Skill file**: `.claude/skills/upload-context.md`
- **Script**: `scripts/upload_context.py`
- Parses Claude Code session JSONL files
- Extracts user/assistant messages into readable transcript
- Uploads to Modal volume `rlm-context` at `/sessions/<session-id>/`
- Supports: latest session, specific session ID, or `--all`

#### SessionEnd Auto-Upload Hook
- **Hook config**: `.claude/settings.local.json`
- **Hook script**: `scripts/session_end_upload.sh`
- Automatically uploads session transcript when Claude Code session ends
- Logs to `/tmp/rlm-session-upload.log`

#### Modal Setup
- **Volume**: `rlm-context` (created, verified)
- **Auth**: dmku33 workspace, token at `~/.modal.toml`
- **Uploaded**: 3 sessions (87.6 KB + 11.7 KB + 13.8 KB = ~113 KB total)

### Volume Structure
```
rlm-context (Modal Volume)
└── sessions/
    ├── 84ede0c3-.../
    │   ├── transcript.txt        # Human-readable
    │   ├── session.json          # Structured JSON
    │   └── transcript_<ts>.txt   # Timestamped backup
    ├── c6157f62-.../
    │   └── ...
    └── 86b31bd5-.../
        └── ...
```

## 10. Next Steps

- [ ] Build Modal Sandbox that mounts `rlm-context` volume and runs RLM REPL
- [ ] Test pulling full context from volume into RAM at sandbox start
- [ ] Implement swappable LLM backend (Claude Agent SDK)
  - Sonnet as orchestrator, Haiku as sub-LLMs
  - Target: multi-provider prize
- [ ] Hook up the DeepRecurse TranscriptRLM helpers to work with volume-mounted context
- [ ] Scale test: upload larger conversation histories, verify RAM approach holds

### File Reference (New)
| File | Purpose |
|------|---------|
| `scripts/upload_context.py` | Parse + upload session transcripts to Modal volume |
| `scripts/session_end_upload.sh` | SessionEnd hook script |
| `.claude/skills/upload-context.md` | `/upload-context` skill definition |
| `.claude/settings.local.json` | Hook configuration (SessionEnd) |

---

*Session notes by Claude Code — for continuity across sessions*
