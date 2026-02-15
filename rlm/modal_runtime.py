"""Modal runtime wiring for RLM root function and shared resources."""

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
    .pip_install("openai", "python-dotenv", "rich")
    .add_local_dir("rlm", remote_path=SOURCE_PATH_IN_IMAGE)
)

shared_volume = modal.Volume.from_name(MODAL_VOLUME_NAME, create_if_missing=True)


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

    env_path = os.path.join(MOUNT_PATH, ENV_RELATIVE_PATH)
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)

    normalized_relpath = context_relpath.lstrip("/")
    context_path = os.path.join(MOUNT_PATH, normalized_relpath)
    if not os.path.exists(context_path):
        raise FileNotFoundError(f"Context file not found: {context_path}")

    rlm = RLM_REPL(
        model=model,
        recursive_model=recursive_model,
        max_iterations=max_iterations,
        enable_logging=True,
        sub_rlm_mode="local",  # Simple API calls, no Modal sandboxes
    )
    return rlm.completion(query=query, context_path=context_path)
