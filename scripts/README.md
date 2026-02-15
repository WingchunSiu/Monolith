# Modal Context Upload

Upload Claude Code session transcripts to a Modal volume (`rlm-context`) for shared RLM processing.

## Quick Setup

```bash
# 1. Install modal
pip install modal

# 2. Authenticate (opens browser)
modal setup

# 3. Create the volume
modal volume create rlm-context

# 4. Upload your latest session
python3 scripts/upload_context.py

# 5. Upload all sessions
python3 scripts/upload_context.py --all
```

## What Gets Uploaded

Each session is uploaded to `/sessions/<session-id>/` on the volume with:

- `transcript.txt` — human-readable transcript with metadata header
- `session.json` — structured JSON with full metadata + messages
- `transcript_<timestamp>.txt` — timestamped backup

### Metadata Header

Every transcript includes a header so RLM agents can differentiate developers/sessions:

```
========================================================================
SESSION METADATA
========================================================================
session_id:      86b31bd5-...
developer:       dmku33
email:           dmytrokj04@gmail.com
hostname:        Ds-MacBook-Pro.local
platform:        Darwin
os_user:         dmytro
git_branch:      main
project_dir:     /Users/dmytro/Desktop/Gits/rlm-explorations
claude_version:  2.1.42
message_count:   45
start_time:      2026-02-14T21:15:07.810Z
end_time:        2026-02-15T00:52:48.964Z
uploaded_at:     2026-02-15T00:52:52.759181+00:00
========================================================================
```

Developer name/email are auto-detected from `git config`. No manual config needed.

## Auto-Upload on Session End

The `SessionEnd` hook in `.claude/settings.local.json` automatically uploads the transcript when you exit Claude Code.

To enable it, copy the settings file:

```bash
cp .claude/settings.local.json.example .claude/settings.local.json
```

Then edit the path in the file to match your local clone location.

Logs go to `/tmp/rlm-session-upload.log`.

## Claude Code Skill

Run `/upload-context` inside Claude Code to manually trigger an upload.

## Inspecting the Volume

```bash
# List sessions
modal volume ls rlm-context /sessions/

# Read a transcript
modal volume get rlm-context /sessions/<id>/transcript.txt -

# Delete everything
modal volume rm rlm-context / -r
```
