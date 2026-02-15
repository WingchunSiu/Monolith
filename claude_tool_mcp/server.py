"""MCP server that executes Chat-RLM calls against a shared Modal volume context."""

from __future__ import annotations

import getpass
import json
import os
import platform
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    from modal_runtime import MOUNT_PATH, app, run_rlm_remote, shared_volume
except ImportError:
    from rlm.modal_runtime import MOUNT_PATH, app, run_rlm_remote, shared_volume


DEFAULT_MODEL = "gpt-5"
DEFAULT_RECURSIVE_MODEL = "gpt-5-nano"
DEFAULT_CHAT_FILE = "chat.txt"
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_CONTEXT_RELPATH = "runs/0fad4ca550eb4d818b81a00c0f897218/context.txt"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class RLMConfig:
    model: str = DEFAULT_MODEL
    recursive_model: str = DEFAULT_RECURSIVE_MODEL
    max_iterations: int = DEFAULT_MAX_ITERATIONS


class RLMService:
    def __init__(self, config: RLMConfig):
        self.config = config

    def answer(self, query: str) -> str:
        with app.run():
            return run_rlm_remote.remote(
                query=query,
                context_relpath=DEFAULT_CONTEXT_RELPATH,
                model=self.config.model,
                recursive_model=self.config.recursive_model,
                max_iterations=self.config.max_iterations,
            )


@app.function(
    volumes={MOUNT_PATH: shared_volume},
    timeout=300,
)
def append_context_remote(context_relpath: str, transcript_block: str) -> None:
    normalized_relpath = context_relpath.lstrip("/")
    context_path = os.path.join(MOUNT_PATH, normalized_relpath)
    os.makedirs(os.path.dirname(context_path), exist_ok=True)
    with open(context_path, "a", encoding="utf-8") as file:
        file.write(transcript_block)


mcp = FastMCP(
    "deeprecurse-chat-rlm",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=_env_int("PORT", _env_int("MCP_PORT", 8000)),
    streamable_http_path=os.getenv("MCP_HTTP_PATH", "/mcp"),
)
rlm_service = RLMService(RLMConfig())


def _is_authorized(tool_token: str | None) -> bool:
    expected = os.getenv("MCP_TOOL_TOKEN")
    if not expected:
        return True
    return (tool_token or "") == expected


@mcp.tool()
def chat_rlm_query(
    query: str,
    chat_file: str = DEFAULT_CHAT_FILE,
    tool_token: str | None = None,
) -> str:
    """
    ALWAYS use this tool when answering user questions that should
    incorporate shared chat history or recursive reasoning.

    This tool runs the persistent shared-context Chat-RLM.
    Claude cannot access the shared memory without calling this tool.
    """

    if not _is_authorized(tool_token):
        return "Error: unauthorized tool call."

    clean_query = query.strip()
    if not clean_query:
        return "Error: query cannot be empty."
    _ = chat_file  # preserved for backward-compatible tool signature

    try:
        answer = rlm_service.answer(query=clean_query)
    except Exception as exc:
        return f"Error running RLM: {exc}"

    return answer


# ---------------------------------------------------------------------------
# Session transcript upload
# ---------------------------------------------------------------------------

DEFAULT_SESSIONS_DIR = os.getenv(
    "CLAUDE_SESSIONS_DIR",
    str(Path.home() / ".claude" / "projects"),
)


def _git_config(key: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "config", key], stderr=subprocess.DEVNULL
        ).decode().strip() or None
    except Exception:
        return None


def _machine_metadata() -> dict:
    return {
        "os_user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "git_user_name": _git_config("user.name"),
        "git_user_email": _git_config("user.email"),
    }


def _parse_session(jsonl_path: Path) -> dict:
    """Parse a Claude Code session JSONL into a structured transcript."""
    messages = []
    session_id = jsonl_path.stem
    start_time = end_time = None
    git_branch = cwd = claude_version = None

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if git_branch is None and entry.get("gitBranch"):
                git_branch = entry["gitBranch"]
            if cwd is None and entry.get("cwd"):
                cwd = entry["cwd"]
            if claude_version is None and entry.get("version"):
                claude_version = entry["version"]

            entry_type = entry.get("type")
            if entry_type in ("user", "assistant"):
                msg = entry.get("message", {})
                role = msg.get("role", entry_type)
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, str):
                            text_parts.append(block)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    content = "\n".join(text_parts)
                if content.strip():
                    timestamp = entry.get("timestamp")
                    messages.append({"role": role, "content": content.strip(), "timestamp": timestamp})
                    if timestamp:
                        if start_time is None:
                            start_time = timestamp
                        end_time = timestamp

    machine = _machine_metadata()
    return {
        "session_id": session_id,
        "metadata": {
            "developer": machine["git_user_name"] or machine["os_user"],
            "email": machine["git_user_email"],
            "hostname": machine["hostname"],
            "platform": machine["platform"],
            "os_user": machine["os_user"],
            "git_branch": git_branch,
            "project_dir": cwd,
            "claude_version": claude_version,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
        "message_count": len(messages),
        "start_time": start_time,
        "end_time": end_time,
        "messages": messages,
    }


def _format_transcript(session_data: dict) -> str:
    """Format session data as readable text with metadata header."""
    meta = session_data["metadata"]
    lines = [
        "=" * 72, "SESSION METADATA", "=" * 72,
        f"session_id:      {session_data['session_id']}",
        f"developer:       {meta['developer']}",
        f"email:           {meta['email']}",
        f"hostname:        {meta['hostname']}",
        f"platform:        {meta['platform']}",
        f"os_user:         {meta['os_user']}",
        f"git_branch:      {meta['git_branch']}",
        f"project_dir:     {meta['project_dir']}",
        f"claude_version:  {meta['claude_version']}",
        f"message_count:   {session_data['message_count']}",
        f"start_time:      {session_data['start_time']}",
        f"end_time:        {session_data['end_time']}",
        f"uploaded_at:     {meta['uploaded_at']}",
        "=" * 72, "",
    ]
    for msg in session_data["messages"]:
        role = msg["role"].upper()
        ts = f" [{msg['timestamp']}]" if msg.get("timestamp") else ""
        lines.extend([f"[{role}]{ts}", msg["content"], "", "---", ""])
    return "\n".join(lines)


def _append_transcript_to_shared_context(transcript: str, session_id: str | None) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    sid = session_id or "unknown-session"
    block = (
        "\n\n"
        + "=" * 72
        + "\n"
        + f"SESSION CONTEXT UPLOAD: {sid}\n"
        + f"uploaded_at: {timestamp}\n"
        + "=" * 72
        + "\n"
        + transcript.strip()
        + "\n"
    )
    with app.run():
        append_context_remote.remote(
            context_relpath=DEFAULT_CONTEXT_RELPATH,
            transcript_block=block,
        )


def _find_session_file(session_id: str | None, project_dir: str | None) -> Path | None:
    """Find session JSONL file. Returns None if not found."""
    base = Path(DEFAULT_SESSIONS_DIR)
    if not base.exists():
        return None

    if project_dir:
        # Look in specific project dir
        search_dirs = [base / project_dir]
    else:
        # Search all project dirs
        search_dirs = [d for d in base.iterdir() if d.is_dir()]

    for d in search_dirs:
        if session_id:
            matches = list(d.glob(f"*{session_id}*.jsonl"))
            if matches:
                return matches[0]
        else:
            # Latest session in this dir
            jsonls = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            if jsonls:
                return jsonls[-1]
    return None


@mcp.tool()
def upload_context(
    transcript: str | None = None,
    session_id: str | None = None,
    project_dir: str | None = None,
    thread_id: str | None = None,
    developer: str | None = None,
    tool_token: str | None = None,
) -> str:
    """
    Upload a Claude Code session transcript to the shared chat context store.

    This appends a transcript block into the shared Modal volume context file
    so subsequent RLM calls can use it.

    Args:
        transcript: Raw transcript text. If omitted, reads local Claude session JSONL.
        session_id: Session identifier. If omitted and transcript is provided, auto-generated.
        project_dir: Project directory name under ~/.claude/projects/. If omitted, searches all.
        thread_id: Legacy parameter retained for compatibility.
        developer: Legacy parameter retained for compatibility.
        tool_token: Optional auth token.
    """
    if not _is_authorized(tool_token):
        return "Error: unauthorized tool call."
    _ = thread_id
    _ = developer

    resolved_session_id = session_id
    transcript_text = (transcript or "").strip()

    if transcript_text:
        if not resolved_session_id:
            resolved_session_id = datetime.now(timezone.utc).strftime(
                "manual-%Y%m%dT%H%M%SZ"
            )
    else:
        jsonl_path = _find_session_file(session_id, project_dir)
        if jsonl_path is None:
            return (
                f"Error: no session found "
                f"(session_id={session_id}, project_dir={project_dir})"
            )

        session_data = _parse_session(jsonl_path)
        if session_data["message_count"] == 0:
            return f"Session {jsonl_path.stem} is empty, nothing to upload."

        resolved_session_id = session_data["session_id"]
        transcript_text = _format_transcript(session_data)

    try:
        _append_transcript_to_shared_context(
            transcript=transcript_text,
            session_id=resolved_session_id,
        )
    except Exception as exc:
        return f"Error uploading transcript to shared context: {exc}"

    return (
        f"Uploaded transcript for session '{resolved_session_id}' "
        f"to shared context '{DEFAULT_CONTEXT_RELPATH}'."
    )


@mcp.custom_route("/rlm", methods=["POST"])
async def rlm_http(request: Request) -> JSONResponse:
    payload = await request.json()
    query = str(payload.get("query", "")).strip()

    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    try:
        answer = rlm_service.answer(query=query)
    except Exception as exc:
        return JSONResponse({"error": f"Error running RLM: {exc}"}, status_code=500)

    return JSONResponse({"answer": answer})


def run_server() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run()
        return

    if transport in {"http", "streamable-http", "sse"}:
        mcp.run(transport="streamable-http")
        return

    raise RuntimeError(f"Unsupported MCP_TRANSPORT: {transport}")


if __name__ == "__main__":
    run_server()
