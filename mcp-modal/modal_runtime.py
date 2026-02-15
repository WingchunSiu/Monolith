"""Modal runtime for RLM — exposes FastAPI endpoints for Cloudflare Worker gateway."""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone

import modal
from pydantic import BaseModel
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODAL_APP_NAME = "rlm-repl"
MODAL_VOLUME_NAME = "rlm-shared-volume"
MOUNT_PATH = "/rlm-data"
SOURCE_PATH_IN_IMAGE = "/root/rlm-app"
ENV_RELATIVE_PATH = ".env"

# ---------------------------------------------------------------------------
# Modal resources
# ---------------------------------------------------------------------------
app = modal.App(MODAL_APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("openai", "python-dotenv", "rich", "fastapi[standard]")
    .add_local_dir("rlm", remote_path=f"{SOURCE_PATH_IN_IMAGE}/rlm")
)

shared_volume = modal.Volume.from_name(MODAL_VOLUME_NAME, create_if_missing=True)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    thread_id: str
    model: str = "gpt-5"
    recursive_model: str = "gpt-5-nano"
    max_iterations: int = 10


class UploadRequest(BaseModel):
    transcript: str
    session_id: str
    thread_id: str = "transcripts"
    developer: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load .env from the shared volume if present."""
    from dotenv import load_dotenv

    env_path = os.path.join(MOUNT_PATH, ENV_RELATIVE_PATH)
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)


def _ensure_context_file(thread_id: str) -> str:
    """Return the absolute path of the context file for *thread_id*, creating it if needed."""
    thread_dir = os.path.join(MOUNT_PATH, thread_id)
    os.makedirs(thread_dir, exist_ok=True)
    context_path = os.path.join(thread_dir, "context.txt")
    if not os.path.exists(context_path):
        with open(context_path, "w") as f:
            f.write("")
    return context_path


def _append_to_volume(thread_id: str, text: str) -> str:
    """Append *text* to the context file and commit the volume. Returns the file path."""
    context_path = _ensure_context_file(thread_id)
    with open(context_path, "a") as f:
        f.write(text)
    shared_volume.commit()
    return context_path


def _run_rlm(query: str, thread_id: str, model: str, recursive_model: str, max_iterations: int) -> str:
    """Run RLM_REPL against the context file for *thread_id*."""
    sys.path.insert(0, SOURCE_PATH_IN_IMAGE)
    from rlm.rlm_repl import RLM_REPL

    _load_env()
    context_path = _ensure_context_file(thread_id)

    rlm = RLM_REPL(
        model=model,
        recursive_model=recursive_model,
        max_iterations=max_iterations,
        enable_logging=True,
        sub_rlm_mode="local",
    )
    return rlm.completion(query=query, context_path=context_path)


# ---------------------------------------------------------------------------
# Modal function (for direct .remote() calls from local server.py)
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
    shared_volume.reload()

    normalized_relpath = context_relpath.lstrip("/")
    # Extract thread_id from relpath (e.g. "my-thread/context.txt" -> "my-thread")
    thread_id = normalized_relpath.split("/")[0] if "/" in normalized_relpath else normalized_relpath
    context_path = _ensure_context_file(thread_id)

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
    timeout=60,
)
def store_context(thread_id: str, text: str) -> str:
    """Append *text* to the context file for *thread_id*. Returns confirmation."""
    path = _append_to_volume(thread_id, text)
    return f"Stored to {path}"


# ---------------------------------------------------------------------------
# FastAPI endpoints (called by Cloudflare Worker)
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
    timeout=3600,
)
@modal.fastapi_endpoint(method="POST")
def query_endpoint(req: QueryRequest):
    """POST /query_endpoint — Run RLM against thread context, append turn, return answer."""
    try:
        # Reload volume to see latest writes
        shared_volume.reload()

        answer = _run_rlm(
            query=req.query,
            thread_id=req.thread_id,
            model=req.model,
            recursive_model=req.recursive_model,
            max_iterations=req.max_iterations,
        )

        # Append the turn to context
        turn_text = f"\nUSER: {req.query}\nASSISTANT: {answer}\n"
        _append_to_volume(req.thread_id, turn_text)

        return {"answer": answer}
    except Exception as exc:
        return {"error": str(exc)}


@app.function(
    image=image,
    volumes={MOUNT_PATH: shared_volume},
    timeout=120,
)
@modal.fastapi_endpoint(method="POST")
def upload_endpoint(req: UploadRequest):
    """POST /upload_endpoint — Store a session transcript on the shared volume."""
    try:
        shared_volume.reload()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        developer = req.developer or "unknown"
        header = f"\n[SESSION UPLOAD] {req.session_id} | developer={developer} | {timestamp}\n"
        text = header + req.transcript + "\n"

        path = _append_to_volume(req.thread_id, text)
        return {
            "ok": True,
            "message": f"Uploaded session {req.session_id} to {req.thread_id}",
            "path": path,
        }
    except Exception as exc:
        return {"error": str(exc)}
