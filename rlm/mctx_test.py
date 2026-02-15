from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time
import tempfile
import uuid

import modal
from dotenv import load_dotenv
from openai import OpenAI

try:
    from modal_runtime import ENV_RELATIVE_PATH, app, run_rlm_remote, shared_volume
except ImportError:
    from rlm.modal_runtime import ENV_RELATIVE_PATH, app, run_rlm_remote, shared_volume

TOTAL_LINES = 500
CHUNK_LINES = 120
BATCH_SEED_LINES = 120
NUM_CHATS = 4
MIN_CHAT_TURNS = 50
GEN_MODEL = "gpt-5-mini"


def build_injected_fact_entries() -> list[dict[str, str | list[str]]]:
    return [
        {
            "fact": "Duplicate writes root cause: todo-service/src/sync/apply_remote_patch.py::merge_remote_changes was appending remote tasks without checking mutation_id.",
            "lines": [
                "USER: We need the exact root cause file and function for the duplicate todo write bug.",
                "ASSISTANT: It is in todo-service/src/sync/apply_remote_patch.py inside merge_remote_changes where remote tasks are appended without checking mutation_id.",
            ],
        },
        {
            "fact": "Fix agreed: add idempotency gate on mutation_id and upsert by task_id before append.",
            "lines": [
                "USER: What was the agreed implementation-level fix?",
                "ASSISTANT: We agreed to add a mutation_id idempotency gate and upsert by task_id before append in merge_remote_changes.",
            ],
        },
        {
            "fact": "Test file updated: todo-service/tests/test_sync_dedupe.py with cases for replayed mutations.",
            "lines": [
                "USER: Which regression test file captured replayed mutation cases?",
                "ASSISTANT: The team added todo-service/tests/test_sync_dedupe.py for replayed mutation_id and duplicate payload scenarios.",
            ],
        },
        {
            "fact": "Server-side note: do not patch ui/store/reducer.ts for this bug; issue is server sync merge path.",
            "lines": [
                "USER: Is this a UI reducer bug in ui/store/reducer.ts?",
                "ASSISTANT: No, this is server-side in the sync merge path and the UI only exposed duplicates written upstream.",
            ],
        },
        {
            "fact": "Postmortem summary repeats same final remedy in merge_remote_changes.",
            "lines": [
                "USER: Please restate the final postmortem remedy in one line.",
                "ASSISTANT: Final remedy: in merge_remote_changes add mutation_id dedupe plus task_id upsert to block retry-based duplicate inserts.",
            ],
        },
    ]


def build_chunk_messages(chunk_index: int, line_count: int, style_seed: int) -> list[dict[str, str]]:
    system_msg = (
        "You generate raw plaintext engineering chat logs. "
        "Do not use markdown or code fences. Keep lines short and realistic."
    )
    user_msg = (
        f"Generate exactly {line_count} lines of fictional developer chat history for a TODO app project.\n"
        "Output rules:\n"
        "- Exactly one line per newline.\n"
        "- EVERY line must start with either 'USER:' or 'ASSISTANT:'.\n"
        "- Alternate USER and ASSISTANT frequently to look like real back-and-forth.\n"
        "- Messages should be medium/long with concrete technical details, not short fragments.\n"
        "- Cover debugging, code review, testing, refactors, CI, and incident follow-ups.\n"
        "- Do NOT include these exact filenames: todo-service/src/sync/apply_remote_patch.py, todo-service/tests/test_sync_dedupe.py\n"
        f"- Chunk index: {chunk_index}\n"
        f"- Variation seed: {style_seed}\n"
    )
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def build_batch_requests(total_lines: int, chunk_lines: int) -> tuple[list[dict], dict[int, int]]:
    num_chunks = (total_lines + chunk_lines - 1) // chunk_lines
    requests: list[dict] = []
    expected_sizes: dict[int, int] = {}
    for idx in range(num_chunks):
        line_count = min(chunk_lines, total_lines - (idx * chunk_lines))
        expected_sizes[idx] = line_count
        requests.append(
            {
                "custom_id": f"chunk-{idx:03d}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": GEN_MODEL,
                    "input": build_chunk_messages(
                        chunk_index=idx,
                        line_count=line_count,
                        style_seed=random.randint(0, 1_000_000),
                    ),
                    "max_output_tokens": 7000,
                    "reasoning": {"effort": "minimal"},
                },
            }
        )
    return requests, expected_sizes


def parse_chunk_index(custom_id: str) -> int:
    return int(custom_id.split("-", 1)[1])


def coerce_to_exact_lines(lines: list[str], line_count: int, chunk_index: int) -> list[str]:
    clean = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("USER:") or stripped.startswith("ASSISTANT:"):
            clean.append(stripped)

    if len(clean) < line_count:
        raise RuntimeError(
            f"Chunk {chunk_index} returned {len(clean)} valid dialogue lines, "
            f"expected {line_count}. Re-run generation."
        )
    return clean[:line_count]


def generate_base_lines_with_batch(client: OpenAI, total_lines: int) -> list[str]:
    requests, expected_sizes = build_batch_requests(total_lines=total_lines, chunk_lines=CHUNK_LINES)
    print(f"Prepared {len(requests)} batch requests for {total_lines} lines total.")

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as temp_file:
        input_jsonl_path = Path(temp_file.name)
        for req in requests:
            temp_file.write(json.dumps(req) + "\n")
    print(f"Wrote batch input JSONL to {input_jsonl_path}")

    print("Uploading batch input file...")
    with open(input_jsonl_path, "rb") as handle:
        input_file = client.files.create(file=handle, purpose="batch")
    print(f"Uploaded input file: {input_file.id}")

    print("Creating batch job...")
    batch = client.batches.create(
        input_file_id=input_file.id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    print(f"Batch created: {batch.id} (status={batch.status})")

    start = time.perf_counter()
    terminal_states = {"completed", "failed", "cancelled", "expired"}
    while batch.status not in terminal_states:
        elapsed = time.perf_counter() - start
        counts = getattr(batch, "request_counts", None)
        if counts is not None:
            print(
                f"[{elapsed:6.1f}s] status={batch.status} "
                f"completed={counts.completed} failed={counts.failed} total={counts.total}"
            )
        else:
            print(f"[{elapsed:6.1f}s] status={batch.status}")
        time.sleep(5)
        batch = client.batches.retrieve(batch.id)

    total_elapsed = time.perf_counter() - start
    print(f"Batch terminal status: {batch.status} after {total_elapsed:.1f}s")
    if batch.status != "completed":
        raise RuntimeError(f"Batch did not complete successfully: status={batch.status}")
    if not batch.output_file_id:
        raise RuntimeError("Batch completed without output_file_id.")

    print(f"Downloading batch output file: {batch.output_file_id}")
    output_text = client.files.content(batch.output_file_id).text
    output_lines = [line for line in output_text.splitlines() if line.strip()]
    print(f"Downloaded {len(output_lines)} output records.")

    chunk_results: dict[int, list[str]] = {}
    for raw_line in output_lines:
        record = json.loads(raw_line)
        custom_id = record.get("custom_id")
        if not custom_id:
            continue
        chunk_idx = parse_chunk_index(custom_id)

        response = record.get("response")
        if not response or response.get("status_code") != 200:
            status = response.get("status_code") if response else "missing"
            raise RuntimeError(f"Chunk {chunk_idx} returned non-200 or missing response (status={status}).")

        body = response.get("body", {})
        content = body.get("output_text", "") or ""
        if not content:
            output_items = body.get("output", [])
            text_parts: list[str] = []
            for item in output_items:
                if item.get("type") != "message":
                    continue
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            content = "\n".join(part for part in text_parts if part)
        chunk_results[chunk_idx] = content.splitlines()
        print(f"Parsed chunk {chunk_idx}: raw model lines={len(chunk_results[chunk_idx])}")

    assembled: list[str] = []
    for idx in sorted(expected_sizes):
        expected_count = expected_sizes[idx]
        raw_lines = chunk_results.get(idx, [])
        normalized = coerce_to_exact_lines(raw_lines, expected_count, idx)
        print(f"Chunk {idx}: normalized to {len(normalized)} lines")
        assembled.extend(normalized)

    assembled = assembled[:total_lines]
    print(f"Assembled {len(assembled)} base lines from batch output.")
    return assembled


def build_chat_log_lines(seed_lines: list[str], target_lines: int) -> list[str]:
    if not seed_lines:
        raise RuntimeError("No seed lines generated from batch output.")

    user_pool = [line for line in seed_lines if line.startswith("USER:")]
    assistant_pool = [line for line in seed_lines if line.startswith("ASSISTANT:")]
    if not user_pool:
        raise RuntimeError("No USER lines found in generated seed data.")
    if not assistant_pool:
        raise RuntimeError("No ASSISTANT lines found in generated seed data.")

    metadata_template = [
        "========================================",
        "chat_id: chat-{chat_id:03d}",
        "timestamp: 2026-01-{day:02d}T{hour:02d}:{minute:02d}:00Z",
        "participants: USER, ASSISTANT",
        "repo: fictional-monocontext-todo-app",
        "export: append-only",
    ]
    metadata_lines_per_chat = len(metadata_template)
    fixed_metadata_total = metadata_lines_per_chat * NUM_CHATS
    dialogue_budget = target_lines - fixed_metadata_total
    min_required = NUM_CHATS * MIN_CHAT_TURNS
    if dialogue_budget < min_required:
        raise ValueError(
            f"Not enough line budget for {NUM_CHATS} chats with {MIN_CHAT_TURNS} turns each."
        )

    base_turns = dialogue_budget // NUM_CHATS
    remainder = dialogue_budget % NUM_CHATS
    turns_plan = [base_turns + (1 if i < remainder else 0) for i in range(NUM_CHATS)]

    lines: list[str] = []
    u_idx = 0
    a_idx = 0
    for chat_idx in range(NUM_CHATS):
        day = (chat_idx % 28) + 1
        hour = (9 + chat_idx) % 24
        minute = (chat_idx * 7) % 60
        for m in metadata_template:
            lines.append(m.format(chat_id=chat_idx + 1, day=day, hour=hour, minute=minute))

        chat_turns = turns_plan[chat_idx]
        print(f"Building chat {chat_idx + 1}/{NUM_CHATS} with {chat_turns} turns")
        for turn in range(chat_turns):
            if turn % 2 == 0:
                raw = user_pool[u_idx % len(user_pool)]
                u_idx += 1
                role = "USER"
            else:
                raw = assistant_pool[a_idx % len(assistant_pool)]
                a_idx += 1
                role = "ASSISTANT"

            content = raw.split(":", 1)[1].strip() if ":" in raw else raw
            if len(content) < 90:
                content = (
                    f"{content} We also traced this to concrete implementation behavior in sync and "
                    f"coordination across review threads, CI checks, and deployment notes for turn {turn + 1}."
                )
            lines.append(f"{role}: {content}")

    return lines[:target_lines]


def inject_facts_into_lines(
    base_lines: list[str],
    fact_entries: list[dict[str, str | list[str]]],
) -> list[str]:
    if not fact_entries:
        return base_lines

    insertion_positions = sorted(
        random.sample(range(100, len(base_lines) - 100), k=len(fact_entries))
    )
    insertion_map: dict[int, list[str]] = {
        pos: entry["lines"] for pos, entry in zip(insertion_positions, fact_entries)
    }

    result: list[str] = []
    for idx, line in enumerate(base_lines):
        if idx in insertion_map:
            result.extend(insertion_map[idx])
        result.append(line)
    return result


def get_eval_prompt_and_expected() -> tuple[str, str]:
    query = (
        "Looking through the monocontext todo app logs, which file and function were identified "
        "as causing duplicate todo writes, and what exact fix was agreed?"
    )
    expected_answer = (
        "Root cause was todo-service/src/sync/apply_remote_patch.py in merge_remote_changes; "
        "fix was adding a mutation_id idempotency gate and upserting by task_id before append."
    )
    return query, expected_answer


def resolve_env_file() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    candidates = [
        project_root / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find .env file. Expected one at project root (.env) or rlm/.env."
    )


def upload_inputs_to_volume(context_file: Path, env_file: Path) -> str:
    run_id = uuid.uuid4().hex
    context_relpath = f"runs/{run_id}/context.txt"
    with shared_volume.batch_upload(force=True) as batch:
        batch.put_file(str(context_file), context_relpath)
        batch.put_file(str(env_file), ENV_RELATIVE_PATH)
    return context_relpath


def resolve_existing_context_file(path_text: str) -> Path:
    requested = Path(path_text).expanduser()
    candidates = [
        requested,
        Path.cwd() / requested,
        Path(__file__).resolve().parent / requested,
        Path(__file__).resolve().parent / requested.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find context file: {path_text}")


def generate_context_file(context_path: Path) -> tuple[str, str, list[str]]:
    print("Generating monocontext-style chat logs with gpt-5-mini via Batch API...")
    load_dotenv()
    client = OpenAI()

    injected_entries = build_injected_fact_entries()
    injected_line_count = sum(len(entry["lines"]) for entry in injected_entries)
    base_target = TOTAL_LINES - injected_line_count
    if base_target <= 0:
        raise ValueError("Injected fact lines exceed TOTAL_LINES.")

    total_start = time.perf_counter()
    seed_target = min(base_target, BATCH_SEED_LINES)
    print(
        f"Generating {seed_target} seed lines with Batch API, then expanding locally to {base_target} lines."
    )
    seed_lines = generate_base_lines_with_batch(client=client, total_lines=seed_target)
    all_lines = build_chat_log_lines(seed_lines=seed_lines, target_lines=base_target)
    print(f"Built {len(all_lines)} structured base lines.")

    mixed_lines = inject_facts_into_lines(all_lines, injected_entries)
    mixed_lines = mixed_lines[:TOTAL_LINES]

    with open(context_path, "w", encoding="utf-8") as file:
        file.write("\n".join(mixed_lines))
    total_elapsed = time.perf_counter() - total_start
    print(
        f"Finished generation in {total_elapsed:.1f}s. "
        f"Wrote {len(mixed_lines)} lines to {context_path}"
    )

    query, expected_answer = get_eval_prompt_and_expected()
    injected_facts = [entry["fact"] for entry in injected_entries]
    return query, expected_answer, injected_facts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--context-file",
        type=str,
        default="mctx_generated_test.txt",
        help="Use a pre-generated context file instead of generating a new one.",
    )
    args = parser.parse_args()

    env_file = resolve_env_file()
    if args.context_file:
        output_path = resolve_existing_context_file(args.context_file)
        print(f"Using pre-generated context file: {output_path}")
        query, expected_answer = get_eval_prompt_and_expected()
        injected_facts = [entry["fact"] for entry in build_injected_fact_entries()]
    else:
        output_path = Path(__file__).resolve().parent / "mctx_generated_test.txt"
        query, expected_answer, injected_facts = generate_context_file(output_path)

    context_relpath = upload_inputs_to_volume(output_path, env_file)
    with modal.enable_output():
        with app.run():
            result = run_rlm_remote.remote(
                query=query,
                context_relpath=context_relpath,
                model="gpt-5-mini",
                recursive_model="gpt-5-nano",
                max_iterations=10,
            )

    print("\n--- QUERY ---")
    print(query)
    print("\n--- EXPECTED ---")
    print(expected_answer)
    print("\n--- MODEL RESPONSE ---")
    print(result)
    print("\n--- INJECTED FACTS ---")
    for idx, fact in enumerate(injected_facts, start=1):
        print(f"{idx}. {fact}")
    print(f"\nContext file used: {output_path}")


if __name__ == "__main__":
    main()
