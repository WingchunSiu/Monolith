# MCP-Modal: Cloudflare Gateway + Modal Backend

RLM-as-MCP-tool with two deployment modes:
- **Local (stdio)** — Python MCP server calls Modal directly
- **Cloud (Cloudflare + Modal)** — Cloudflare Worker proxies MCP to Modal HTTP endpoints

## Architecture

```
Claude Code
  │
  └─ MCP (streamable-http or stdio)
      │
      ▼
Cloudflare Worker (/mcp)          ← thin JSON-RPC proxy (cloud mode)
  │                                  OR
  │                                Python server.py (local/stdio mode)
  │
  ├─ chat_rlm_query  ──→ Modal /query endpoint
  │                       → reads context from Modal Volume
  │                       → runs RLM
  │                       → appends turn to volume
  │                       → returns answer
  │
  └─ upload_context   ──→ Modal /upload endpoint
                           → appends transcript to Modal Volume
```

## Setup

### Prerequisites

- Python 3.12+
- [Modal](https://modal.com) account + `modal token set`
- OpenAI API key in a `.env` file on the Modal Volume (`/rlm-data/.env`)

### 1. Install dependencies

```bash
cd mcp-modal
pip install -r requirements.txt
```

### 2. Deploy Modal functions

```bash
modal deploy modal_runtime.py
```

This creates:
- `run_rlm_remote` — callable via `.remote()` from Python
- `store_context` — callable via `.remote()` from Python
- `query_endpoint` — HTTP POST endpoint for Cloudflare Worker
- `upload_endpoint` — HTTP POST endpoint for Cloudflare Worker

### 3a. Local mode (stdio)

Add the MCP server to Claude Code:

```bash
claude mcp add deeprecurse --transport stdio -- python /path/to/mcp-modal/server.py
```

### 3b. Cloud mode (Cloudflare + Modal)

1. Update `MODAL_BACKEND_URL` in `cloudflare/worker-gateway/wrangler.toml` with your Modal endpoint URL (found after `modal deploy`).

2. Deploy the Cloudflare Worker:

```bash
cd cloudflare/worker-gateway
npm install
npm run deploy
```

3. Add the MCP server to Claude Code:

```bash
claude mcp add deeprecurse --transport http --url https://deeprecurse-mcp-modal.<your-subdomain>.workers.dev/mcp
```

## MCP Tools

### `chat_rlm_query`
Query the RLM with persistent thread context.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | The question to ask |
| `thread_id` | string | yes | Thread identifier for context persistence |

### `upload_context`
Upload a session transcript for RLM context.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `transcript` | string | yes | Full transcript text |
| `session_id` | string | yes | Session identifier |
| `thread_id` | string | no | Thread to store under (default: `transcripts`) |

## SessionEnd Hook

Auto-upload transcripts when a Claude Code session ends:

```json
{
  "hooks": {
    "SessionEnd": [{
      "command": "/path/to/mcp-modal/scripts/session_end_upload.sh"
    }]
  }
}
```

## Volume Layout

```
/rlm-data/
  .env                          ← OpenAI API key
  {thread_id}/context.txt       ← accumulated context per thread
```
