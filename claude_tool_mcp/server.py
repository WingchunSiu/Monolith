"""MCP server that executes the shared-context Chat-RLM flow."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP


DEFAULT_MODEL = "gpt-5"
DEFAULT_RECURSIVE_MODEL = "gpt-5-nano"
DEFAULT_CHAT_FILE = "chat.txt"
DEFAULT_MAX_ITERATIONS = 10


def project_root() -> Path:
    # server.py is inside DeepRecurse/claude_skill_mcp
    return Path(__file__).resolve().parents[1]


def ensure_rlm_importable() -> None:
    rlm_path = str(project_root() / "rlm-minimal")
    if rlm_path not in sys.path:
        sys.path.insert(0, rlm_path)


def resolve_chat_path(chat_file: str) -> Path:
    path = Path(chat_file)
    if not path.is_absolute():
        path = project_root() / path
    return path


class RLMConfig:
    model: str = DEFAULT_MODEL
    recursive_model: str = DEFAULT_RECURSIVE_MODEL
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    enable_logging: bool = False


class ChatStore:
    def __init__(self, chat_path: Path):
        self.chat_path = chat_path
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.chat_path.parent.mkdir(parents=True, exist_ok=True)
        self.chat_path.touch(exist_ok=True)

    def read_context(self) -> str:
        context = self.chat_path.read_text(encoding="utf-8")
        return context if context.strip() else "No prior chat history yet."

    def append_turn(self, query: str, answer: str) -> None:
        with self.chat_path.open("a", encoding="utf-8") as file:
            file.write(f"\nUSER: {query}\nASSISTANT: {answer}\n")


class RLMService:
    def __init__(self, config: RLMConfig):
        self.config = config
        self._rlm = None

    def _get_rlm(self):
        if self._rlm is None:
            ensure_rlm_importable()
            rlm_repl_module = importlib.import_module("rlm.rlm_repl")
            rlm_cls = rlm_repl_module.RLM_REPL
            self._rlm = rlm_cls(
                api_key=os.getenv("OPENAI_API_KEY"),
                model=self.config.model,
                recursive_model=self.config.recursive_model,
                max_iterations=self.config.max_iterations,
                enable_logging=self.config.enable_logging,
            )
        return self._rlm

    def answer(self, context: str, query: str) -> str:
        return self._get_rlm().completion(context=context, query=query)


mcp = FastMCP("deeprecurse-chat-rlm")
rlm_service = RLMService(RLMConfig())


@mcp.tool()
def chat_rlm_query(query: str, chat_file: str = DEFAULT_CHAT_FILE) -> str:
    """
    ALWAYS use this tool when answering user questions that should
    incorporate shared chat history or recursive reasoning.

    This tool runs the persistent shared-context Chat-RLM.
    Claude cannot access the shared memory without calling this tool.
    """

    clean_query = query.strip()
    if not clean_query:
        return "Error: query cannot be empty."

    store = ChatStore(resolve_chat_path(chat_file))
    context = store.read_context()

    try:
        answer = rlm_service.answer(context=context, query=clean_query)
    except Exception as exc:
        return f"Error running RLM: {exc}"

    store.append_turn(clean_query, answer)
    return answer


if __name__ == "__main__":
    mcp.run()
