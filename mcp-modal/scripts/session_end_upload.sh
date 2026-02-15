#!/usr/bin/env bash
# session_end_upload.sh — Claude Code SessionEnd hook
# Uploads the current session transcript to the Modal backend.
#
# Claude Code hook config (~/.claude/settings.json):
#   "hooks": {
#     "SessionEnd": [
#       { "command": "/path/to/mcp-modal/scripts/session_end_upload.sh" }
#     ]
#   }

set -euo pipefail

MODAL_UPLOAD_URL="${MODAL_UPLOAD_URL:-https://dmku33--rlm-repl-upload-endpoint.modal.run}"
THREAD_ID="${THREAD_ID:-transcripts}"
DEVELOPER="${DEVELOPER:-$(whoami)}"
SESSION_ID="$(date +%Y%m%dT%H%M%S)-$$"

# Claude Code pipes the session transcript to the hook's stdin.
# Write to a temp file to avoid shell escaping issues with large transcripts.
TMPFILE="$(mktemp)"
trap 'rm -f "$TMPFILE"' EXIT

cat > "$TMPFILE"

# Build JSON payload safely using Python (handles escaping correctly)
PAYLOAD="$(python3 -c "
import json, sys
transcript = open(sys.argv[1]).read()
print(json.dumps({
    'transcript': transcript,
    'session_id': sys.argv[2],
    'thread_id': sys.argv[3],
    'developer': sys.argv[4],
}))
" "$TMPFILE" "$SESSION_ID" "$THREAD_ID" "$DEVELOPER")"

curl -sf -X POST "$MODAL_UPLOAD_URL" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" \
  > /dev/null 2>&1 || echo "Warning: session upload failed" >&2
