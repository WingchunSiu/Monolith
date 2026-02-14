"""RLM wrapper that injects transcript-navigation helpers into the REPL."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure rlm-minimal is importable
_rlm_path = str(Path(__file__).resolve().parent.parent / "rlm-minimal")
if _rlm_path not in sys.path:
    sys.path.insert(0, _rlm_path)

from rlm.rlm_repl import RLM_REPL


# Extra instructions prepended to the system prompt so the root LLM knows
# about the transcript helpers available in its REPL environment.
TRANSCRIPT_PROMPT = """\
In addition to the standard REPL helpers (`context`, `llm_query`, `print`), \
you have the following transcript-navigation functions pre-loaded:

- `list_sessions()` -> list[str]
    Return session IDs available in the transcript store.

- `list_turns(session_id: str)` -> list[int]
    Return sorted turn numbers for a given session.

- `read_turn(session_id: str, turn_number: int)` -> dict
    Read a single turn JSON object (keys: turn_number, role, content, timestamp, session_id).

- `read_session(session_id: str)` -> str
    Read all turns in a session concatenated as readable text.

- `search_transcripts(keyword: str)` -> list[dict]
    Search across all turns for a keyword (case-insensitive). Returns a list of
    matching turn dicts with an extra `session_id` key.

Use these helpers to explore the transcripts before answering. You can combine
them with `llm_query()` for deeper analysis of individual turns or sessions.
"""


class TranscriptRLM(RLM_REPL):
    """RLM_REPL subclass that mounts transcript helpers into the REPL env."""

    def __init__(
        self,
        transcript_dir: str,
        *,
        api_key: Optional[str] = None,
        model: str = "gpt-5",
        recursive_model: str = "gpt-5",
        max_iterations: int = 10,
        enable_logging: bool = False,
    ):
        self.transcript_dir = transcript_dir
        super().__init__(
            api_key=api_key,
            model=model,
            recursive_model=recursive_model,
            max_iterations=max_iterations,
            enable_logging=enable_logging,
        )

    # ------------------------------------------------------------------
    # Transcript helper implementations (filesystem-backed)
    # ------------------------------------------------------------------

    def _list_sessions(self) -> List[str]:
        """List session directories under the transcript root."""
        root = Path(self.transcript_dir)
        if not root.exists():
            return []
        return sorted(
            d.name for d in root.iterdir() if d.is_dir()
        )

    def _list_turns(self, session_id: str) -> List[int]:
        """List turn numbers in a session, sorted."""
        session_dir = Path(self.transcript_dir) / session_id
        if not session_dir.exists():
            return []
        turns = []
        for f in session_dir.iterdir():
            if f.suffix == ".json" and f.stem.startswith("turn-"):
                try:
                    turns.append(int(f.stem.split("-", 1)[1]))
                except ValueError:
                    continue
        return sorted(turns)

    def _read_turn(self, session_id: str, turn_number: int) -> Dict:
        """Read a single turn JSON file."""
        path = Path(self.transcript_dir) / session_id / f"turn-{turn_number:03d}.json"
        if not path.exists():
            return {"error": f"Turn {turn_number} not found in session {session_id}"}
        with open(path) as f:
            return json.load(f)

    def _read_session(self, session_id: str) -> str:
        """Read all turns in a session as concatenated text."""
        turns = self._list_turns(session_id)
        if not turns:
            return f"No turns found for session {session_id}"
        parts = []
        for t in turns:
            data = self._read_turn(session_id, t)
            role = data.get("role", "unknown").upper()
            content = data.get("content", "")
            parts.append(f"[Turn {t} - {role}]\n{content}")
        return "\n\n".join(parts)

    def _search_transcripts(self, keyword: str) -> List[Dict]:
        """Case-insensitive keyword search across all turns."""
        results = []
        kw_lower = keyword.lower()
        for session_id in self._list_sessions():
            for turn_num in self._list_turns(session_id):
                data = self._read_turn(session_id, turn_num)
                content = data.get("content", "")
                if kw_lower in content.lower():
                    data["session_id"] = session_id
                    results.append(data)
        return results

    # ------------------------------------------------------------------
    # Override setup_context to inject helpers + custom prompt
    # ------------------------------------------------------------------

    def setup_context(
        self,
        context: List[str] | str | List[Dict[str, str]],
        query: Optional[str] = None,
    ):
        messages = super().setup_context(context, query)

        # Inject transcript helper functions into the REPL globals
        self.repl_env.globals["list_sessions"] = self._list_sessions
        self.repl_env.globals["list_turns"] = self._list_turns
        self.repl_env.globals["read_turn"] = self._read_turn
        self.repl_env.globals["read_session"] = self._read_session
        self.repl_env.globals["search_transcripts"] = self._search_transcripts

        # Prepend transcript instructions to the system message
        sys_msg = messages[0]
        sys_msg["content"] = TRANSCRIPT_PROMPT + "\n\n" + sys_msg["content"]

        return messages
