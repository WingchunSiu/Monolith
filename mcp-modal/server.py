"""Stdio MCP server for local dev (no Cloudflare needed).

Calls Modal functions directly via .remote().

Usage:
  claude mcp add deeprecurse --transport stdio -- python /path/to/mcp-modal/server.py
"""

from __future__ import annotations

import modal
from mcp.server.fastmcp import FastMCP

MODAL_APP_NAME = "rlm-repl"

mcp = FastMCP("deeprecurse-chat-rlm")


@mcp.tool()
def chat_rlm_query(query: str, thread_id: str) -> str:
    """Use this to query the Python RLM backend while reading/updating
    shared persistent thread context (thread_id)."""
    clean_query = query.strip()
    if not clean_query:
        return "Error: query cannot be empty."

    context_relpath = f"{thread_id}/context.txt"

    try:
        run_rlm_remote = modal.Function.from_name(MODAL_APP_NAME, "run_rlm_remote")
        answer = run_rlm_remote.remote(query=clean_query, context_relpath=context_relpath)
    except Exception as exc:
        return f"Error running RLM: {exc}"

    return answer


@mcp.tool()
def upload_context(
    transcript: str,
    session_id: str,
    thread_id: str = "transcripts",
) -> str:
    """Upload a session transcript to the shared context store on Modal Volume.
    The transcript is stored under a thread so the RLM can reason over past sessions."""
    if not transcript.strip():
        return "Error: transcript cannot be empty."
    if not session_id.strip():
        return "Error: session_id cannot be empty."

    try:
        store_context_fn = modal.Function.from_name(MODAL_APP_NAME, "store_context")
        store_context_fn.remote(
            thread_id=thread_id,
            session_id=session_id,
            transcript=transcript,
        )
        return f"Uploaded session {session_id} to thread '{thread_id}'."
    except Exception as exc:
        return f"Error uploading context: {exc}"


if __name__ == "__main__":
    mcp.run()
