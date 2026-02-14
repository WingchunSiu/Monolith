"""Modal App that runs TranscriptRLM with S3-mounted transcripts.

Bucket layout:
    s3://deeprecurse-transcripts/{repo}/{session_id}/turn-001.json
                                                   /turn-002.json

Mounted at /transcripts inside the container, so the TranscriptRLM
gets transcript_dir="/transcripts/{repo}".
"""

from __future__ import annotations

import modal

from deeprecurse.config import (
    BUCKET_NAME,
    MAX_ITERATIONS,
    MODAL_APP_NAME,
    MODAL_IMAGE_PYTHON,
    MODAL_SECRET_NAME,
    MOUNT_PATH,
    RECURSIVE_MODEL,
    ROOT_MODEL,
)

app = modal.App(MODAL_APP_NAME)

image = (
    modal.Image.debian_slim(python_version=MODAL_IMAGE_PYTHON)
    .pip_install("openai", "python-dotenv", "rich")
    .add_local_dir(
        "rlm-minimal/rlm",
        remote_path="/root/rlm-minimal/rlm",
    )
    .add_local_dir(
        "deeprecurse",
        remote_path="/root/deeprecurse",
    )
)

bucket_mount = modal.CloudBucketMount(
    bucket_name=BUCKET_NAME,
    secret=modal.Secret.from_name(MODAL_SECRET_NAME),
    read_only=True,
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name(MODAL_SECRET_NAME)],
    volumes={MOUNT_PATH: bucket_mount},
    timeout=600,
)
def run_query(query: str, repo: str) -> str:
    """Run a transcript-aware RLM query inside Modal.

    Args:
        query: The natural-language question to answer.
        repo: Repository name — maps to subdirectory inside the bucket.

    Returns:
        The final answer string from RLM.
    """
    import sys

    sys.path.insert(0, "/root/rlm-minimal")
    sys.path.insert(0, "/root")

    from deeprecurse.rlm_runner import TranscriptRLM

    transcript_dir = f"{MOUNT_PATH}/{repo}"

    rlm = TranscriptRLM(
        transcript_dir=transcript_dir,
        model=ROOT_MODEL,
        recursive_model=RECURSIVE_MODEL,
        max_iterations=MAX_ITERATIONS,
        enable_logging=True,
    )

    sessions = rlm._list_sessions()
    context = (
        f"Transcript store mounted at {transcript_dir}\n"
        f"Available sessions: {sessions}\n"
        f"Use the transcript helper functions to explore the data."
    )

    return rlm.completion(context=context, query=query)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name(MODAL_SECRET_NAME)],
    volumes={MOUNT_PATH: bucket_mount},
    timeout=60,
)
def list_transcripts(repo: str) -> dict:
    """Smoke-test helper: list sessions and turns from the mounted bucket."""
    import json
    import os

    transcript_dir = f"{MOUNT_PATH}/{repo}"
    result: dict = {}

    if not os.path.isdir(transcript_dir):
        return {"error": f"No transcripts found for repo '{repo}'"}

    for entry in sorted(os.listdir(transcript_dir)):
        session_path = os.path.join(transcript_dir, entry)
        if os.path.isdir(session_path):
            turns = sorted(
                f for f in os.listdir(session_path) if f.endswith(".json")
            )
            result[entry] = turns

    return result


@app.local_entrypoint()
def main():
    """Quick smoke test — list transcripts from a test repo."""
    result = list_transcripts.remote(repo="test")
    print("Transcripts found:", result)
