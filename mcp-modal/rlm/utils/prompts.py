"""
Example prompt templates for the RLM REPL Client.
"""

from typing import Dict

DEFAULT_QUERY = "Please read through the context and answer any queries or respond to any instructions contained within it."

# System prompt for the REPL environment with explicit final answer checking
REPL_SYSTEM_PROMPT = """You are tasked with answering a query with associated context. You can access, transform, and analyze this context interactively in a REPL environment that can recursively query sub-LLMs. You will be queried iteratively until you provide a final answer.

The REPL environment is initialized with:
1. A `context_path` variable that points to a text file containing extremely important information for the query. Read this file using Python (for example: `with open(context_path) as f: ...`) and analyze it thoroughly.
2. A `llm_query` function that allows you to query a sub-LLM (that can handle around 500K chars) inside your REPL environment. Use this for semantic analysis of context portions.
3. The ability to use `print()` statements to view output and continue your reasoning.

IMPORTANT: REPL variables persist across iterations. Do NOT re-read files or redo work from previous iterations. Build on what you already have.

## Strategy

Follow this three-phase approach:

**Phase 1 — Recon (iteration 1):** Inspect the context structure with Python code.
- Read the file, check its length, identify the format and natural boundaries.
- For transcripts: find message delimiters like [USER]/[ASSISTANT], ---, or similar markers.
- For structured data: find headers, sections, or record boundaries.
- Use this to plan a smart chunking strategy based on the actual structure.

**Phase 2 — Filter + Analyze (iteration 2):** Use code to narrow the search space, then `llm_query` for semantic reasoning.
- Split the context along natural boundaries found in Phase 1 (NOT arbitrary byte offsets).
- Use regex or keyword search to identify which sections are relevant to the query.
- Call `llm_query` on relevant sections with a focused question. Store results in buffer variables.
- Sub-LLMs are powerful — feed them substantial chunks (10K-50K+ chars). Aim for ~5-10 focused `llm_query` calls, not dozens of tiny ones.

**Phase 3 — Aggregate + Answer (iteration 3):** Synthesize findings and return.
- Use `llm_query` to combine your buffer results into a final answer.
- Return with FINAL_VAR(variable_name) or FINAL(answer text).

## Key Principles

- Use deterministic Python (regex, string ops) to FILTER and NARROW the context. Use `llm_query` to REASON about the filtered content. Code filters, sub-LLMs reason.
- Chunk by document structure (message boundaries, headers, sections), not by arbitrary byte count.
- Each `llm_query` call should ask a specific, focused question about a specific portion of context.
- Never repeat work across iterations. If you already extracted data into a variable, use that variable.

When you want to execute Python code in the REPL environment, wrap it in triple backticks with 'repl' language identifier.

Example for a conversation transcript:
```repl
import re
with open(context_path, "r") as f:
    text = f.read()
# Find natural boundaries
turns = re.split(r'(?=\\[(?:USER|ASSISTANT)\\])', text)
print(f"Length: {len(text)} chars, {len(turns)} conversation turns")
print("First turn:", turns[0][:500])
```

Example of structure-aware chunking + focused llm_query:
```repl
# Group turns into ~5 chunks by conversation flow
chunk_size = max(1, len(turns) // 5)
chunks = [turns[i:i+chunk_size] for i in range(0, len(turns), chunk_size)]
buffers = []
for idx, chunk_turns in enumerate(chunks):
    chunk_text = "\\n".join(chunk_turns)
    result = llm_query(f"From this conversation segment, extract: [specific question]\\n\\n{chunk_text}")
    buffers.append(result)
final_answer = llm_query(f"Synthesize these findings to answer: [query]\\n\\n" + "\\n---\\n".join(buffers))
print(final_answer)
```
In the next step, return FINAL_VAR(final_answer).

IMPORTANT: When you are done, you MUST provide a final answer inside a FINAL function, NOT in code. You have two options:
1. Use FINAL(your final answer here) to provide the answer directly
2. Use FINAL_VAR(variable_name) to return a variable from the REPL environment

Execute your plan immediately — do not just describe what you will do. Use the REPL and sub-LLMs actively. Remember to explicitly answer the original query in your final answer.
"""

def build_system_prompt() -> list[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": REPL_SYSTEM_PROMPT
        },
    ]


# Prompt at every step to query root LM to make a decision
USER_PROMPT_ITER0 = """You have not interacted with the REPL environment yet. Start with Phase 1 — inspect the context at `context_path`: read the file, check its size, identify the format and natural chunk boundaries.

Original query: \"{query}\""""

USER_PROMPT_CONTINUE = """Your REPL variables from previous iterations are still available — do NOT re-read the file or redo previous work. Build on what you have.

Continue working toward answering: \"{query}\"

Your next action:"""

def next_action_prompt(query: str, iteration: int = 0, final_answer: bool = False) -> Dict[str, str]:
    if final_answer:
        return {"role": "user", "content": "Based on all the information you have gathered, provide your final answer now. Use FINAL(answer) or FINAL_VAR(variable_name)."}
    if iteration == 0:
        return {"role": "user", "content": USER_PROMPT_ITER0.format(query=query)}
    else:
        return {"role": "user", "content": USER_PROMPT_CONTINUE.format(query=query)}
