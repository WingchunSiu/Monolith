#!/usr/bin/env bash
# SessionEnd hook — uploads the session transcript to Modal Volume.
#
# Hook config (in .claude/settings.json):
#   "hooks": {
#     "SessionEnd": [{
#       "command": "/path/to/mcp-modal/scripts/session_end_upload.sh"
#     }]
#   }
#
# Environment variables set by Claude Code:
#   SESSION_ID    — unique session identifier
#   PROJECT_DIR   — project directory path
#   TRANSCRIPT    — path to session transcript JSONL file
#
# The script reads the JSONL transcript, extracts user/assistant messages,
# and uploads them to the Modal Volume via the store_context Modal function.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP_MODAL_DIR="$(dirname "$SCRIPT_DIR")"

# Derive thread_id from project directory name
THREAD_ID="${PROJECT_DIR##*/}"
if [ -z "$THREAD_ID" ]; then
  THREAD_ID="default"
fi

# Check required env vars
if [ -z "${SESSION_ID:-}" ]; then
  echo "SESSION_ID not set, skipping upload." >&2
  exit 0
fi

if [ -z "${TRANSCRIPT:-}" ] || [ ! -f "$TRANSCRIPT" ]; then
  echo "TRANSCRIPT file not found, skipping upload." >&2
  exit 0
fi

# Extract clean user/assistant conversation from JSONL (no tool use, no system noise)
TRANSCRIPT_TEXT=$(python3 -c "
import json, sys, re

SYSTEM_TAGS = re.compile(
    r'<(?:local-command-caveat|local-command-stdout|command-name'
    r'|command-message|command-args|system-reminder)[>\s]',
    re.IGNORECASE,
)

turns = []
for line in open(sys.argv[1]):
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue

    entry_type = entry.get('type', '')
    if entry_type not in ('user', 'assistant'):
        continue

    msg = entry.get('message', {})
    content = msg.get('content', '')

    if isinstance(content, list):
        content = '\n'.join(
            (c if isinstance(c, str) else c.get('text', ''))
            for c in content
            if isinstance(c, str) or (isinstance(c, dict) and c.get('type') == 'text')
        )

    content = content.strip()
    if not content:
        continue

    if SYSTEM_TAGS.search(content):
        continue

    role = msg.get('role', entry_type).upper()
    turns.append(f'[{role}]\n{content}')

print('\n\n---\n\n'.join(turns))
" "$TRANSCRIPT" 2>/dev/null || echo "")

if [ -z "$TRANSCRIPT_TEXT" ]; then
  echo "No transcript content to upload." >&2
  exit 0
fi

# Upload via Modal store_context function
cd "$MCP_MODAL_DIR"
python3 -c "
from modal_runtime import store_context
result = store_context.remote(
    thread_id='$THREAD_ID',
    session_id='$SESSION_ID',
    transcript='''$TRANSCRIPT_TEXT''',
)
print(f'Uploaded: {result}')
" 2>&1 || echo "Upload failed (non-fatal)." >&2
