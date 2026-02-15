"""CLI entry point for querying a codebase context via Modal + RLM.

Usage:
    python -m deeprecurse.query "why did we decide on PostgreSQL?" --codebase myproject
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query a codebase context using RLM on Modal."
    )
    parser.add_argument("query", help="Natural-language question to ask.")
    parser.add_argument("--codebase", required=True, help="Codebase name.")
    parser.add_argument("--model", default="gpt-5", help="Root model.")
    parser.add_argument("--recursive-model", default="gpt-5-nano", help="Sub-LLM model.")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max RLM iterations.")
    args = parser.parse_args()

    # Add mcp-modal/ to path so we can import modal_runtime
    mcp_modal_path = str(Path(__file__).resolve().parent.parent / "mcp-modal")
    if mcp_modal_path not in sys.path:
        sys.path.insert(0, mcp_modal_path)

    import modal
    from modal_runtime import app, run_rlm_remote

    context_relpath = f"{args.codebase}/context.txt"

    print(f"Querying codebase '{args.codebase}'...", file=sys.stderr)
    with modal.enable_output():
        with app.run():
            answer = run_rlm_remote.remote(
                query=args.query,
                context_relpath=context_relpath,
                model=args.model,
                recursive_model=args.recursive_model,
                max_iterations=args.max_iterations,
            )
    print(answer)


if __name__ == "__main__":
    main()
