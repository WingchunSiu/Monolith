# DeepRecurse — Cloudflare MCP + Session Upload

Shared-history chat prototype where RLM execution lives in an MCP tool, deployed via Cloudflare Workers with Durable Objects.

This branch adds **`upload_context`** — a second MCP tool that uploads Claude Code session transcripts to the shared context store, so the RLM can reason over past sessions.

## Tools

| Tool | Description |
|------|-------------|
| `chat_rlm_query` | Query the RLM with shared persistent thread context. The RLM reads chat history, runs recursive sub-LLM reasoning, and appends the turn. |
| `upload_context` | Upload a Claude Code session transcript to the context store. Can be called manually or automatically via a SessionEnd hook. |

## How It Works

```
Developer using Claude Code
  │
  ├─ [automatic] SessionEnd hook fires
  │   └─ Parses session JSONL → formatted transcript
  │   └─ Calls upload_context MCP tool → stored in ChatStore DO
  │
  └─ [manual] Asks a question that needs shared context
      └─ Claude calls chat_rlm_query MCP tool
          └─ Cloudflare Worker → RLM Container DO
              └─ Reads context (including uploaded transcripts)
              └─ Runs RLM REPL with sub-LLM reasoning
              └─ Returns answer, appends turn
```

## What Changed (for Cloudflare deployer)

If you already have the CloudflareIntegration branch deployed, here's what to redeploy to get the new `upload_context` tool:

**Step 1: Rebuild + push the container image** (Python MCP server)
```bash
# from repo root
docker build -t deeprecurse-mcp:latest .
# tag and push to your Cloudflare registry
docker tag deeprecurse-mcp:latest registry.cloudflare.com/<account>/deeprecurse-rlm:latest
docker push registry.cloudflare.com/<account>/deeprecurse-rlm:latest
```

**Step 2: Redeploy the Worker gateway**
```bash
cd cloudflare/worker-gateway
npm install
npx wrangler deploy
```

That's it. After redeploy, `tools/list` will show both `chat_rlm_query` and `upload_context`. No config changes needed — same env vars, same wrangler.toml.

**Step 3 (optional): Each team member adds the SessionEnd hook**

Each developer who wants auto-upload adds to their `.claude/settings.local.json`:
```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/scripts/session_end_upload.sh",
            "timeout": 30000
          }
        ]
      }
    ]
  }
}
```

---

## Setup (from scratch)

### 1. Local development (stdio MCP)

```bash
pip install -r requirements.txt
python claude_tool_mcp/server.py
```

Add to Claude Code:
```bash
claude mcp add deeprecurse --transport stdio -- \
  python /path/to/DeepRecurse/claude_tool_mcp/server.py
```

### 2. Cloud deployment (Cloudflare)

The Python MCP server runs inside a Cloudflare Container (Durable Object). The Cloudflare Worker gateway handles MCP JSON-RPC at the edge.

#### Environment variables (container)

- `OPENAI_API_KEY`
- `MCP_TRANSPORT=streamable-http`
- `CHAT_STORE_BACKEND=r2` (for R2-backed storage)
- `R2_BUCKET`, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`

#### Deploy Worker

```bash
cd cloudflare/worker-gateway
npm install
npx wrangler deploy
```

#### Connect Claude Code to remote MCP

```bash
claude mcp add --transport http deeprecurse https://<your-worker-domain>/mcp
```

### 3. Auto-upload session transcripts (SessionEnd hook)

Add to your `.claude/settings.local.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/scripts/session_end_upload.sh",
            "timeout": 30000
          }
        ]
      }
    ]
  }
}
```

The hook script (`scripts/session_end_upload.sh`) parses the session JSONL and uploads it via the `upload_context` MCP tool. This happens automatically when a Claude Code session ends.

## `upload_context` Tool

### Parameters

| Param | Required | Description |
|-------|----------|-------------|
| `transcript` | Yes (remote) | Full session transcript text |
| `session_id` | Yes | Session identifier |
| `thread_id` | No | Thread to store under (default: `transcripts`) |
| `developer` | No | Developer name |

### Local mode (stdio)

When running locally, the tool can read session JSONL files directly from `~/.claude/projects/`:

| Param | Required | Description |
|-------|----------|-------------|
| `session_id` | No | Session ID to upload (latest if omitted) |
| `project_dir` | No | Project directory name under `~/.claude/projects/` |
| `thread_id` | No | Thread to store under (default: `transcripts`) |

## Request Flow

### RLM Query
1. Claude calls Worker at `POST /mcp` with `chat_rlm_query`
2. Worker reads context from ChatStore Durable Object
3. Worker forwards to RLM Container Durable Object
4. RLM runs recursive reasoning with sub-LLMs
5. Answer + turn appended to ChatStore

### Session Upload
1. SessionEnd hook fires → parses JSONL → calls `upload_context`
2. Worker stores transcript in ChatStore Durable Object
3. Next `chat_rlm_query` call sees the uploaded transcript as part of context

## Key Files

| File | Purpose |
|------|---------|
| `claude_tool_mcp/server.py` | Python MCP server (stdio + HTTP, file + R2 storage) |
| `cloudflare/worker-gateway/src/index.ts` | Cloudflare Worker MCP gateway |
| `rlm-minimal/` | RLM REPL implementation |
