"""Modal sandbox worker for sub-RLM calls.

Protocol:
- Reads a single JSON payload from stdin.
- Emits model response text to stdout.
"""

from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from rlm.utils.llm import OpenAIClient


def _read_payload() -> dict:
    raw = sys.stdin.buffer.read()
    if not raw:
        raise ValueError("No payload received on stdin")
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    try:
        payload = _read_payload()
        env_file_path = payload.get("env_file_path")
        if env_file_path:
            load_dotenv(env_file_path, override=True)

        prompt = payload.get("prompt")
        model = payload.get("model", "gpt-5")

        client = OpenAIClient(model=model)
        response = client.completion(messages=prompt, timeout=300)
        sys.stdout.write(response or "")
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
