#!/usr/bin/env bash
# session_end_upload.sh — Claude Code Stop hook
# Uploads the current session transcript (with metadata header) to Modal.
#
# Hook config (.claude/settings.local.json):
#   "hooks": {
#     "Stop": [{
#       "type": "command",
#       "command": "/path/to/scripts/session_end_upload.sh"
#     }]
#   }
#
# Env overrides:
#   MODAL_UPLOAD_URL  — endpoint URL (defaults to michaelxiao1219 Modal app)
#   THREAD_ID         — context thread (defaults to "transcripts")

set -euo pipefail

export MODAL_UPLOAD_URL="${MODAL_UPLOAD_URL:-https://michaelxiao1219--rlm-repl-upload-endpoint.modal.run}"
export THREAD_ID="${THREAD_ID:-transcripts}"

# Read hook JSON from stdin (Claude Code pipes session context)
HOOK_JSON="$(cat)"

export TRANSCRIPT_PATH="$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('transcript_path',''))")"
export SESSION_ID="$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))")"
export SESSION_ID="${SESSION_ID:-$(date +%Y%m%dT%H%M%S)-$$}"

[ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ] && exit 0

# All processing in Python via heredoc (quoted PYEOF = no shell expansion)
python3 << 'PYEOF'
import json, os, re, sys, getpass, socket, platform, subprocess, urllib.request
from datetime import datetime, timezone

transcript_path = os.environ["TRANSCRIPT_PATH"]
session_id      = os.environ["SESSION_ID"]
thread_id       = os.environ["THREAD_ID"]
upload_url      = os.environ["MODAL_UPLOAD_URL"]

# ---------------------------------------------------------------------------
# System tag handling: strip injected tags instead of dropping whole messages
# ---------------------------------------------------------------------------
_TAG_NAMES = (
    r'local-command-caveat|local-command-stdout|command-name'
    r'|command-message|command-args|system-reminder'
)
# Paired tags: <tag ...>...</tag>
_PAIRED = re.compile(
    rf'<({_TAG_NAMES})\b[^>]*>.*?</\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
# Leftover opening tags (unclosed — consume to next '<' or end)
_OPEN = re.compile(
    rf'<({_TAG_NAMES})\b[^>]*>[^<]*',
    re.IGNORECASE,
)

def strip_system_tags(text: str) -> str:
    text = _PAIRED.sub('', text)
    text = _OPEN.sub('', text)
    return text.strip()

# ---------------------------------------------------------------------------
# Machine / git metadata
# ---------------------------------------------------------------------------
def git_config(key: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "config", key], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""

developer = git_config("user.name") or getpass.getuser()
email     = git_config("user.email")
hostname  = socket.gethostname()
os_plat   = platform.system()
os_user   = getpass.getuser()

# ---------------------------------------------------------------------------
# Parse JSONL transcript
# ---------------------------------------------------------------------------
turns = []
git_branch = None
project_dir = None
claude_version = None
start_time = None
end_time = None

with open(transcript_path) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Extract session-level metadata from early entries
        if git_branch is None and entry.get("gitBranch"):
            git_branch = entry["gitBranch"]
        if project_dir is None and entry.get("cwd"):
            project_dir = entry["cwd"]
        if claude_version is None and entry.get("version"):
            claude_version = entry["version"]

        entry_type = entry.get("type", "")
        if entry_type not in ("user", "assistant"):
            continue

        msg = entry.get("message", {})
        content = msg.get("content", "")
        timestamp = entry.get("timestamp")

        if timestamp:
            if start_time is None:
                start_time = timestamp
            end_time = timestamp

        # --- Extract text + note tool_use blocks ---
        tool_names = []
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tool_names.append(block.get("name", "unknown"))
            content = "\n".join(text_parts)

        # Strip system tags instead of dropping the whole message
        content = strip_system_tags(content)

        # If no text remained but assistant used tools, keep a marker
        if not content and tool_names:
            content = "[tools: " + ", ".join(tool_names) + "]"

        if not content:
            continue

        role = msg.get("role", entry_type).upper()
        ts_label = f" [{timestamp}]" if timestamp else ""
        turns.append(f"[{role}]{ts_label}\n{content}")

# ---------------------------------------------------------------------------
# Format transcript with metadata header
# ---------------------------------------------------------------------------
message_count = len(turns)
if message_count == 0:
    sys.exit(0)

now = datetime.now(timezone.utc).isoformat()

header = (
    f"{'=' * 72}\n"
    f"SESSION METADATA\n"
    f"{'=' * 72}\n"
    f"session_id:      {session_id}\n"
    f"developer:       {developer}\n"
    f"email:           {email}\n"
    f"hostname:        {hostname}\n"
    f"platform:        {os_plat}\n"
    f"os_user:         {os_user}\n"
    f"git_branch:      {git_branch or 'unknown'}\n"
    f"project_dir:     {project_dir or 'unknown'}\n"
    f"claude_version:  {claude_version or 'unknown'}\n"
    f"message_count:   {message_count}\n"
    f"start_time:      {start_time or 'unknown'}\n"
    f"end_time:        {end_time or 'unknown'}\n"
    f"uploaded_at:     {now}\n"
    f"{'=' * 72}"
)

transcript = header + "\n\n" + "\n\n---\n\n".join(turns) + "\n"

# ---------------------------------------------------------------------------
# Upload to Modal endpoint
# ---------------------------------------------------------------------------
payload = json.dumps({
    "transcript": transcript,
    "session_id": session_id,
    "thread_id":  thread_id,
    "developer":  developer,
}).encode()

req = urllib.request.Request(
    upload_url,
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=15)
except Exception as e:
    print(f"Upload failed (non-fatal): {e}", file=sys.stderr)
PYEOF
