"""CLI entry point for querying transcripts via Modal + RLM.

Usage:
    python -m deeprecurse.query "why did we decide on PostgreSQL?" --repo myrepo
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query session transcripts using RLM on Modal."
    )
    parser.add_argument("query", help="Natural-language question to ask.")
    parser.add_argument("--repo", required=True, help="Repository name.")
    args = parser.parse_args()

    # Import here so modal isn't required just to see --help
    from deeprecurse.modal_app import run_query

    print(f"Querying repo '{args.repo}'...", file=sys.stderr)
    answer = run_query.remote(query=args.query, repo=args.repo)
    print(answer)


if __name__ == "__main__":
    main()
