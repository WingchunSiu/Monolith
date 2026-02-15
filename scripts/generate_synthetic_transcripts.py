from __future__ import annotations

import argparse
import json
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


WORDS = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
    "golf", "hotel", "india", "juliet", "kilo", "lima",
    "micro", "nano", "omega", "pixel", "quantum", "radar",
    "signal", "tensor", "vector", "widget", "zenith",
]

NAMES = [
    "Avery", "Blake", "Casey", "Devon", "Emery", "Finley",
    "Harper", "Jordan", "Kai", "Logan", "Morgan", "Parker",
    "Quinn", "Riley", "Rowan", "Sawyer", "Taylor", "Tatum",
]

DEPLOY_WINDOWS = [
    "Monday 10am PT",
    "Tuesday 2pm PT",
    "Wednesday 3pm PT",
    "Thursday 11am PT",
    "Friday 4pm PT",
]


@dataclass
class FactSet:
    deployment_window: str
    rollback_code: str
    release_owner: str


def random_sentence(word_count: int) -> str:
    return " ".join(random.choice(WORDS) for _ in range(word_count)).capitalize() + "."


def build_metadata(session_id: str, message_count: int, start: datetime, end: datetime) -> str:
    return "\n".join(
        [
            "========================================================================",
            "SESSION METADATA",
            "========================================================================",
            f"session_id:      {session_id}",
            "developer:       synthetic-user",
            "email:           synthetic@example.com",
            "hostname:        dev-machine",
            "platform:        Darwin",
            "os_user:         tester",
            "git_branch:      modal",
            "project_dir:     /Users/tester/DeepRecurse",
            "claude_version:  2.1.99",
            f"message_count:   {message_count}",
            f"start_time:      {start.isoformat().replace('+00:00', 'Z')}",
            f"end_time:        {end.isoformat().replace('+00:00', 'Z')}",
            f"uploaded_at:     {datetime.now(timezone.utc).isoformat()}",
            "========================================================================",
            "",
        ]
    )


def build_message(role: str, timestamp: datetime, content: str) -> str:
    return "\n".join(
        [
            f"[{role}] [{timestamp.isoformat().replace('+00:00', 'Z')}]",
            content,
            "",
            "---",
            "",
        ]
    )


def generate_transcript(message_count: int, seed: int) -> tuple[str, FactSet]:
    random.seed(seed)
    session_id = f"synthetic-{uuid.uuid4().hex[:8]}"

    release_owner = random.choice(NAMES)
    rollback_code = f"MONO-{random.randint(10, 99)}"
    deployment_window = random.choice(DEPLOY_WINDOWS)
    facts = FactSet(
        deployment_window=deployment_window,
        rollback_code=rollback_code,
        release_owner=release_owner,
    )

    start = datetime(2026, 2, 15, 16, 0, 0, tzinfo=timezone.utc)
    current = start
    step = timedelta(seconds=45)

    messages: list[str] = []
    for i in range(message_count):
        role = "USER" if i % 2 == 0 else "ASSISTANT"
        if i == 0:
            content = (
                "Synthetic test: record the deployment window as "
                f"{facts.deployment_window}. The rollback code is {facts.rollback_code}. "
                f"The release owner is {facts.release_owner}."
            )
        else:
            content = random_sentence(random.randint(8, 16))
        messages.append(build_message(role, current, content))
        current += step

    header = build_metadata(session_id, message_count, start, current - step)
    return header + "\n".join(messages), facts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic transcript files.")
    parser.add_argument("--out", default="scripts/generated", help="Output directory.")
    parser.add_argument("--num-files", type=int, default=3, help="Number of transcripts.")
    parser.add_argument("--messages", type=int, default=200, help="Messages per transcript.")
    parser.add_argument("--seed", type=int, default=13, help="Random seed base.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    answers_path = out_dir / "answers.jsonl"
    with answers_path.open("w", encoding="utf-8") as answers_file:
        for i in range(args.num_files):
            transcript, facts = generate_transcript(args.messages, args.seed + i)
            session_id = transcript.splitlines()[3].split()[-1]
            transcript_path = out_dir / f"{session_id}.txt"
            transcript_path.write_text(transcript, encoding="utf-8")

            answers_file.write(
                json.dumps(
                    {
                        "session_id": session_id,
                        "deployment_window": facts.deployment_window,
                        "rollback_code": facts.rollback_code,
                        "release_owner": facts.release_owner,
                        "query": (
                            "From the transcript, what is the deployment window, "
                            "rollback code, and release owner?"
                        ),
                    }
                )
                + "\n"
            )

    print(f"Wrote {args.num_files} transcripts to {out_dir}")
    print(f"Wrote answer key to {answers_path}")


if __name__ == "__main__":
    main()
