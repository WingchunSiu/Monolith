"""Append transcript text to a codebase's context.txt on the Modal Volume.

Usage:
    # Append a transcript file
    python -m deeprecurse.store transcript.txt --codebase myproject

    # Pipe from stdin
    cat session.txt | python -m deeprecurse.store - --codebase myproject

Volume layout:
    /rlm-data/{codebase}/context.txt   ← single file, appended to over time
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append transcript text to a codebase context on the Modal Volume."
    )
    parser.add_argument(
        "file",
        help="Path to transcript file, or '-' for stdin.",
    )
    parser.add_argument(
        "--codebase",
        required=True,
        help="Codebase name (used as subdirectory on the volume).",
    )
    args = parser.parse_args()

    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file) as f:
            text = f.read()

    if not text.strip():
        print("No content to store.", file=sys.stderr)
        sys.exit(1)

    # Add rlm/ to path so we can import modal_runtime
    rlm_path = str(Path(__file__).resolve().parent.parent / "rlm")
    if rlm_path not in sys.path:
        sys.path.insert(0, rlm_path)

    from modal_runtime import shared_volume

    context_relpath = f"{args.codebase}/context.txt"

    # Read existing content (if any), append new text, re-upload
    existing = b""
    try:
        for chunk in shared_volume.read_file(context_relpath):
            existing += chunk
    except Exception:
        pass  # file doesn't exist yet

    new_content = existing.decode("utf-8", errors="replace") + text
    if not new_content.endswith("\n"):
        new_content += "\n"

    with shared_volume.batch_upload(force=True) as batch:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name
        batch.put_file(tmp_path, context_relpath)

    import os
    os.unlink(tmp_path)

    print(f"Appended {len(text)} chars to {context_relpath} (total: {len(new_content)} chars)")


if __name__ == "__main__":
    main()
