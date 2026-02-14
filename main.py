"""Local multi-turn chat interface backed by rlm-minimal."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODEL = "gpt-5"
DEFAULT_RECURSIVE_MODEL = "gpt-5-nano"
DEFAULT_CHAT_FILE = "chat.txt"
EXIT_COMMANDS = {"exit", "quit", ":q"}


def project_root() -> Path:
    return Path(__file__).resolve().parent


def ensure_rlm_importable() -> None:
    rlm_path = str(project_root() / "rlm-minimal")
    if rlm_path not in sys.path:
        sys.path.insert(0, rlm_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prototype local chat-RLM CLI")
    parser.add_argument("--chat-file", default=DEFAULT_CHAT_FILE, help="Shared chat log path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Root model name")
    parser.add_argument("--recursive-model", default=DEFAULT_RECURSIVE_MODEL, help="Recursive model")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max root iterations")
    parser.add_argument("--enable-logging", action="store_true", help="Enable RLM logs")
    return parser.parse_args()


@dataclass
class ChatConfig:
    chat_path: Path
    model: str
    recursive_model: str
    max_iterations: int
    enable_logging: bool


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

    def append_turn(self, user_query: str, assistant_answer: str) -> None:
        with self.chat_path.open("a", encoding="utf-8") as file:
            file.write(f"\nUSER: {user_query}\nASSISTANT: {assistant_answer}\n")


class RLMEngine:
    def __init__(
        self,
        *,
        model: str,
        recursive_model: str,
        max_iterations: int,
        enable_logging: bool,
    ):
        ensure_rlm_importable()
        rlm_repl_module = importlib.import_module("rlm.rlm_repl")
        RLM_REPL = rlm_repl_module.RLM_REPL

        self.rlm = RLM_REPL(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=model,
            recursive_model=recursive_model,
            max_iterations=max_iterations,
            enable_logging=enable_logging,
        )

    def answer(self, context: str, query: str) -> str:
        return self.rlm.completion(context=context, query=query)


class ChatSession:
    def __init__(self, store: ChatStore, engine: RLMEngine):
        self.store = store
        self.engine = engine

    def run(self) -> None:
        print("Chat-RLM ready. Type your question, or 'exit' to quit.")
        while True:
            query = input("You: ").strip()
            if not query:
                continue
            if query.lower() in EXIT_COMMANDS:
                print("Goodbye!")
                break

            context = self.store.read_context()
            print(f"Context:\n{context}\n---")
            print(f"Query: {query}")
            print("Generating answer...")
            answer = self.engine.answer(context=context, query=query)
            print(f"Assistant: {answer}")
            self.store.append_turn(query, answer)


def build_config(args: argparse.Namespace) -> ChatConfig:
    chat_path = Path(args.chat_file)
    if not chat_path.is_absolute():
        chat_path = project_root() / chat_path

    return ChatConfig(
        chat_path=chat_path,
        model=args.model,
        recursive_model=args.recursive_model,
        max_iterations=args.max_iterations,
        enable_logging=args.enable_logging,
    )


def main() -> None:
    args = parse_args()
    config = build_config(args)

    store = ChatStore(config.chat_path)
    engine = RLMEngine(
        model=config.model,
        recursive_model=config.recursive_model,
        max_iterations=config.max_iterations,
        enable_logging=config.enable_logging,
    )
    session = ChatSession(store, engine)
    session.run()


if __name__ == "__main__":
    main()
