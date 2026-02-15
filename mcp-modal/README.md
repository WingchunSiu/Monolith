# mcp-modal — RLM on Modal with Cloudflare MCP Gateway

Architecture:

```
Claude Code → MCP (streamable-http) → Cloudflare Worker (/mcp)
  ├─ chat_rlm_query → POST Modal /query_endpoint
  │     Modal: reads context from volume, runs RLM, appends turn, returns answer
  └─ upload_context → POST Modal /upload_endpoint
        Modal: appends transcript to volume file
```

## Setup

### 1. Deploy Modal backend

```bash
cd mcp-modal
pip install -r requirements.txt
modal deploy modal_runtime.py
```

### 2. Upload .env to Modal volume

```bash
modal volume put rlm-shared-volume .env .env
```

### 3. Deploy Cloudflare Worker (optional — for remote MCP)

```bash
cd cloudflare/worker-gateway
npm install
npm run deploy
```

Update `MODAL_BACKEND_URL` in `wrangler.toml` if your Modal URL differs.

### 4. Configure Claude Code

**Option A: Remote MCP via Cloudflare Worker**

```json
{
  "mcpServers": {
    "deeprecurse": {
      "url": "https://deeprecurse-mcp-gateway.<your-subdomain>.workers.dev/mcp"
    }
  }
}
```

**Option B: Local MCP via stdio (calls Modal .remote() directly)**

```json
{
  "mcpServers": {
    "deeprecurse": {
      "command": "python",
      "args": ["mcp-modal/server.py"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `chat_rlm_query` | Query RLM with persistent thread context |
| `upload_context` | Upload session transcript to shared volume |

## Testing

```bash
# Deploy
cd mcp-modal && modal deploy modal_runtime.py

# Test upload
curl -s -X POST https://dmku33--rlm-repl-upload-endpoint.modal.run \
  -H 'Content-Type: application/json' \
  -d '{"transcript":"test content","session_id":"test-001","thread_id":"test-thread"}'

# Verify on volume
modal volume ls rlm-shared-volume /test-thread/

# Test query
curl -s -X POST https://dmku33--rlm-repl-query-endpoint.modal.run \
  -H 'Content-Type: application/json' \
  -d '{"query":"Summarize the context.","thread_id":"test-thread"}'
```

## Session End Hook

Auto-upload transcripts when Claude Code sessions end:

```json
{
  "hooks": {
    "SessionEnd": [
      { "command": "/path/to/mcp-modal/scripts/session_end_upload.sh" }
    ]
  }
}
```
