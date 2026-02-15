"""Local stdio MCP server that calls Modal .remote() directly.

Usage (Claude Code MCP config):
  {
    "mcpServers": {
      "deeprecurse": {
        "command": "python",
        "args": ["mcp-modal/server.py"],
        "cwd": "/path/to/rlm-explorations"
      }
    }
  }

Requires: pip install mcp modal
"""

from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

import modal

mcp = FastMCP("deeprecurse-local")

# Lazy-lookup Modal functions (avoids import-time Modal client init)
_query_fn = None
_store_fn = None


def _get_query_fn():
    global _query_fn
    if _query_fn is None:
        _query_fn = modal.Function.from_name("rlm-repl", "run_rlm_remote")
    return _query_fn


def _get_store_fn():
    global _store_fn
    if _store_fn is None:
        _store_fn = modal.Function.from_name("rlm-repl", "store_context")
    return _store_fn


@mcp.tool()
def chat_rlm_query(query: str, thread_id: str) -> str:
    """Query the Python RLM backend while reading/updating shared persistent thread context (thread_id)."""
    fn = _get_query_fn()
    context_relpath = f"{thread_id}/context.txt"
    answer = fn.remote(
        query=query,
        context_relpath=context_relpath,
    )
    # Also append the turn to context
    turn_text = f"\nUSER: {query}\nASSISTANT: {answer}\n"
    _get_store_fn().remote(thread_id=thread_id, text=turn_text)
    return answer


@mcp.tool()
def upload_context(transcript: str, session_id: str, thread_id: str = "transcripts", developer: str = "unknown") -> str:
    """Upload a Claude Code session transcript to the shared context store."""
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    header = f"\n[SESSION UPLOAD] {session_id} | developer={developer} | {timestamp}\n"
    text = header + transcript + "\n"

    fn = _get_store_fn()
    result = fn.remote(thread_id=thread_id, text=text)
    return f"Uploaded session {session_id} to thread '{thread_id}'. {result}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
