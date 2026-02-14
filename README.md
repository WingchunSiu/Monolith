# DeepRecurse

Local prototype for a shared-history chat interface using the bundled `rlm-minimal` Recursive Language Model implementation.

## Run

From the repository root:

```bash
python DeepRecurse/main.py
```

Then chat interactively in the terminal. Type `exit` (or `quit`) to stop.

Useful flags:

- `--chat-file` path to shared chat context log (default: `DeepRecurse/chat.txt`)
- `--model` root model (default: `gpt-5`)
- `--recursive-model` recursive model (default: `gpt-5-nano`)
- `--max-iterations` max RLM iterations (default: `10`)
- `--enable-logging` enable colorful RLM logs

Each turn:
1. Reads prior turns from `chat.txt` as context.
2. Runs `RLM_REPL.completion(context, query)`.
3. Prints the assistant response.
4. Appends `USER` + `ASSISTANT` entries back to the same chat file.
