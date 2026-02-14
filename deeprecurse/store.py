"""Upload transcript files to S3.

Usage:
    # Upload a raw transcript file (alternating USER:/ASSISTANT: lines)
    python -m deeprecurse.store transcript.txt --repo myrepo --session abc123

    # Pipe from stdin
    cat transcript.txt | python -m deeprecurse.store - --repo myrepo --session abc123

Bucket layout produced:
    s3://deeprecurse-transcripts/{repo}/{session_id}/turn-001.json
    s3://deeprecurse-transcripts/{repo}/{session_id}/turn-002.json
    ...

Each turn JSON:
    {
        "turn_number": 1,
        "role": "user",
        "content": "...",
        "timestamp": "2026-02-14T...",
        "session_id": "abc123"
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone

import boto3

from deeprecurse.config import BUCKET_NAME


def parse_transcript(text: str) -> list[dict]:
    """Parse a raw transcript into a list of turn dicts.

    Expects lines starting with ``USER:`` or ``ASSISTANT:`` as turn
    boundaries.  Everything between two boundaries is treated as a single
    turn's content (supports multi-line content).
    """
    turns: list[dict] = []
    current_role: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        match = re.match(r"^(USER|ASSISTANT):\s*(.*)", line)
        if match:
            # Flush previous turn
            if current_role is not None:
                turns.append({
                    "role": current_role,
                    "content": "\n".join(current_lines).strip(),
                })
            current_role = match.group(1).lower()
            current_lines = [match.group(2)]
        else:
            current_lines.append(line)

    # Flush last turn
    if current_role is not None:
        turns.append({
            "role": current_role,
            "content": "\n".join(current_lines).strip(),
        })

    return turns


def upload_turns(
    turns: list[dict],
    repo: str,
    session_id: str,
    bucket: str = BUCKET_NAME,
) -> list[str]:
    """Upload parsed turns to S3 and return the list of S3 keys written."""
    s3 = boto3.client("s3")
    now = datetime.now(timezone.utc).isoformat()
    keys: list[str] = []

    for i, turn in enumerate(turns, start=1):
        obj = {
            "turn_number": i,
            "role": turn["role"],
            "content": turn["content"],
            "timestamp": now,
            "session_id": session_id,
        }
        key = f"{repo}/{session_id}/turn-{i:03d}.json"
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(obj, indent=2),
            ContentType="application/json",
        )
        keys.append(key)

    return keys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a transcript file to S3 as structured turn JSON."
    )
    parser.add_argument(
        "file",
        help="Path to transcript file, or '-' for stdin.",
    )
    parser.add_argument("--repo", required=True, help="Repository name.")
    parser.add_argument(
        "--session",
        default=None,
        help="Session ID (auto-generated if omitted).",
    )
    parser.add_argument(
        "--bucket",
        default=BUCKET_NAME,
        help=f"S3 bucket name (default: {BUCKET_NAME}).",
    )
    args = parser.parse_args()

    # Read input
    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file) as f:
            text = f.read()

    session_id = args.session or uuid.uuid4().hex[:12]
    turns = parse_transcript(text)

    if not turns:
        print("No turns found in input.", file=sys.stderr)
        sys.exit(1)

    keys = upload_turns(turns, repo=args.repo, session_id=session_id, bucket=args.bucket)
    print(f"Uploaded {len(keys)} turns to s3://{args.bucket}/")
    for k in keys:
        print(f"  {k}")


if __name__ == "__main__":
    main()
