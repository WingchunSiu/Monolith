#!/usr/bin/env python3
"""Upload Claude Code session transcript to a Modal volume.

Usage:
    python scripts/upload_context.py                    # Upload current/latest session
    python scripts/upload_context.py <session-id>       # Upload specific session
    python scripts/upload_context.py --all              # Upload all sessions for this project
"""

import getpass
import json
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import modal

VOLUME_NAME = "rlm-context"
PROJECT_DIR = "-Users-dmytro-Desktop-Gits-rlm-explorations"
SESSIONS_PATH = Path.home() / ".claude" / "projects" / PROJECT_DIR


def get_machine_metadata() -> dict:
    """Collect machine/user identity metadata."""
    def _git_config(key):
        try:
            return subprocess.check_output(
                ["git", "config", key], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            return None

    return {
        "os_user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "git_user_name": _git_config("user.name"),
        "git_user_email": _git_config("user.email"),
    }


def get_session_files():
    """Find all session JSONL files for this project."""
    if not SESSIONS_PATH.exists():
        print(f"No sessions found at {SESSIONS_PATH}")
        sys.exit(1)
    return sorted(SESSIONS_PATH.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def parse_session(jsonl_path: Path) -> dict:
    """Parse a session JSONL into a structured transcript with metadata."""
    messages = []
    session_id = jsonl_path.stem
    start_time = None
    end_time = None
    # Session-level metadata extracted from JSONL entries
    git_branch = None
    cwd = None
    claude_version = None

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract session metadata from first entries that have it
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

                # Content can be a string or list of content blocks
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
                    messages.append({
                        "role": role,
                        "content": content.strip(),
                        "timestamp": timestamp,
                    })
                    if timestamp:
                        if start_time is None:
                            start_time = timestamp
                        end_time = timestamp

    machine = get_machine_metadata()

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


def format_transcript(session_data: dict) -> str:
    """Format session data as readable text with metadata header for RLM agents."""
    meta = session_data["metadata"]
    lines = []

    # Structured metadata header — agents parse this to differentiate users/sessions
    lines.append("=" * 72)
    lines.append("SESSION METADATA")
    lines.append("=" * 72)
    lines.append(f"session_id:      {session_data['session_id']}")
    lines.append(f"developer:       {meta['developer']}")
    lines.append(f"email:           {meta['email']}")
    lines.append(f"hostname:        {meta['hostname']}")
    lines.append(f"platform:        {meta['platform']}")
    lines.append(f"os_user:         {meta['os_user']}")
    lines.append(f"git_branch:      {meta['git_branch']}")
    lines.append(f"project_dir:     {meta['project_dir']}")
    lines.append(f"claude_version:  {meta['claude_version']}")
    lines.append(f"message_count:   {session_data['message_count']}")
    lines.append(f"start_time:      {session_data['start_time']}")
    lines.append(f"end_time:        {session_data['end_time']}")
    lines.append(f"uploaded_at:     {meta['uploaded_at']}")
    lines.append("=" * 72)
    lines.append("")

    for msg in session_data["messages"]:
        role = msg["role"].upper()
        ts = f" [{msg['timestamp']}]" if msg.get("timestamp") else ""
        lines.append(f"[{role}]{ts}")
        lines.append(msg["content"])
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def upload_to_volume(session_id: str, transcript_text: str, session_data: dict):
    """Upload transcript to Modal volume."""
    vol = modal.Volume.from_name(VOLUME_NAME)

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    remote_dir = f"/sessions/{session_id}"

    # Upload the readable transcript
    transcript_bytes = transcript_text.encode("utf-8")
    # Upload the raw JSON for programmatic access
    json_bytes = json.dumps(session_data, indent=2, ensure_ascii=False).encode("utf-8")

    import io
    with vol.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(transcript_bytes), f"{remote_dir}/transcript.txt")
        batch.put_file(io.BytesIO(json_bytes), f"{remote_dir}/session.json")
        # Also keep a timestamped copy
        batch.put_file(io.BytesIO(transcript_bytes), f"{remote_dir}/transcript_{now}.txt")

    size_kb = len(transcript_bytes) / 1024
    print(f"Uploaded to Modal volume '{VOLUME_NAME}':")
    print(f"  {remote_dir}/transcript.txt ({size_kb:.1f} KB)")
    print(f"  {remote_dir}/session.json")
    print(f"  {session_data['message_count']} messages")


def main():
    args = sys.argv[1:]

    session_files = get_session_files()
    if not session_files:
        print("No session files found.")
        sys.exit(1)

    if "--all" in args:
        targets = session_files
    elif args and args[0] != "--all":
        # Find specific session
        sid = args[0]
        matches = [f for f in session_files if sid in f.stem]
        if not matches:
            print(f"No session matching '{sid}' found.")
            sys.exit(1)
        targets = matches
    else:
        # Latest session (most recently modified)
        targets = [session_files[-1]]

    for jsonl_path in targets:
        print(f"\nProcessing: {jsonl_path.stem}")
        session_data = parse_session(jsonl_path)

        if session_data["message_count"] == 0:
            print("  (empty session, skipping)")
            continue

        transcript = format_transcript(session_data)
        upload_to_volume(jsonl_path.stem, transcript, session_data)

    print("\nDone.")


if __name__ == "__main__":
    main()
