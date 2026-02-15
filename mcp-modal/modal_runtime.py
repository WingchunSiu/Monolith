"""Modal runtime with HTTP endpoints for RLM execution and context storage.

Exposes two web endpoints:
  POST /query   — run RLM against thread context on the volume
  POST /upload  — append transcript text to thread context on the volume

Deploy:
  modal deploy modal_runtime.py
"""

from __future__ import annotations

import os
import sys

import modal
from dotenv import load_dotenv

MODAL_APP_NAME = "rlm-repl"
MODAL_VOLUME_NAME = "rlm-shared-volume"
MOUNT_PATH = "/rlm-data"
SOURCE_PATH_IN_IMAGE = "/root/rlm-app"
ENV_RELATIVE_PATH = ".env"

app = modal.App(MODAL_APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("openai", "python-dotenv", "rich", "fastapi[standard]")
    .add_local_dir("rlm", remote_path=f"{SOURCE_PATH_IN_IMAGE}/rlm")
)

shared_volume = modal.Volume.from_name(MODAL_VOLUME_NAME, create_if_missing=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env_path = os.path.join(MOUNT_PATH, ENV_RELATIVE_PATH)
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)


def _read_volume_file(relpath: str) -> str:
    """Read a text file from the volume, returning '' if missing."""
    full = os.path.join(MOUNT_PATH, relpath)
    if not os.path.exists(full):
        return ""
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def _append_to_volume(relpath: str, text: str) -> None:
    """Append text to a file on the volume (creating dirs as needed)."""
    full = os.path.join(MOUNT_PATH, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "a", encoding="utf-8") as f:
        f.write(text)
    shared_volume.commit()


def _ensure_context_file(relpath: str) -> str:
    """Ensure context file exists on the volume, return its absolute path."""
    full = os.path.join(MOUNT_PATH, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if not os.path.exists(full):
        with open(full, "w", encoding="utf-8") as f:
            f.write("")
        shared_volume.commit()
    return full


def _run_rlm(query: str, context_relpath: str) -> str:
    """Run RLM_REPL with context from the volume."""
    sys.path.insert(0, SOURCE_PATH_IN_IMAGE)
    from rlm.rlm_repl import RLM_REPL

    _load_env()
    context_path = _ensure_context_file(context_relpath)

    rlm = RLM_REPL(
        model="gpt-5",
        recursive_model="gpt-5-nano",
        max_iterations=10,
        enable_logging=True,
        sub_rlm_mode="local",
    )
    return rlm.completion(query=query, context_path=context_path)


# ---------------------------------------------------------------------------
# Modal function (callable via .remote() from Python)
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
    timeout=3600,
)
def run_rlm_remote(
    query: str,
    context_relpath: str,
    model: str = "gpt-5",
    recursive_model: str = "gpt-5-nano",
    max_iterations: int = 10,
) -> str:
    """Run RLM_REPL on Modal with context read from a mounted volume file."""
    sys.path.insert(0, SOURCE_PATH_IN_IMAGE)
    from rlm.rlm_repl import RLM_REPL

    _load_env()
    context_path = _ensure_context_file(context_relpath)

    rlm = RLM_REPL(
        model=model,
        recursive_model=recursive_model,
        max_iterations=max_iterations,
        enable_logging=True,
        sub_rlm_mode="local",
    )
    return rlm.completion(query=query, context_path=context_path)


@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
)
def store_context(thread_id: str, session_id: str, transcript: str) -> dict:
    """Append transcript text to a thread's context file on the volume."""
    relpath = f"{thread_id}/context.txt"
    header = f"\n[SESSION {session_id}]\n"
    _append_to_volume(relpath, header + transcript + "\n")
    return {"status": "ok", "thread_id": thread_id, "session_id": session_id}


# ---------------------------------------------------------------------------
# Web endpoints (called by Cloudflare Worker via HTTP)
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
    timeout=3600,
)
@modal.fastapi_endpoint(method="POST")
def query_endpoint(item: dict) -> dict:
    """HTTP endpoint for Cloudflare Worker to call for RLM queries."""
    query = item["query"]
    thread_id = item["thread_id"]
    context_relpath = f"{thread_id}/context.txt"

    answer = _run_rlm(query, context_relpath)

    _append_to_volume(context_relpath, f"\nUSER: {query}\nASSISTANT: {answer}\n")

    return {"answer": answer}


@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
)
@modal.fastapi_endpoint(method="POST")
def upload_endpoint(item: dict) -> dict:
    """HTTP endpoint for transcript upload."""
    transcript = item["transcript"]
    thread_id = item.get("thread_id", "transcripts")
    session_id = item["session_id"]

    relpath = f"{thread_id}/context.txt"
    _append_to_volume(relpath, f"\n[SESSION {session_id}]\n{transcript}\n")

    return {"status": "ok", "thread_id": thread_id, "session_id": session_id}
