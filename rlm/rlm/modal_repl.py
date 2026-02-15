"""
Modal-based REPL environment with broker pattern for recursive RLM calls.

This module provides a persistent Modal Sandbox with a Flask broker server
for handling LLM requests from within the sandbox. Enables true recursive
RLM architecture where sub-LLMs can spawn their own REPL environments.
"""

from __future__ import annotations

import base64
import json
import textwrap
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import modal
import requests


# =============================================================================
# Broker Server Script (runs inside sandbox)
# =============================================================================

_BROKER_SCRIPT = textwrap.dedent(
    '''
import json
import threading
import uuid
from flask import Flask, request, jsonify

app = Flask(__name__)

# Request queue: {request_id: {"request": {...}, "response": None, "event": Event}}
pending_requests = {}
lock = threading.Lock()

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/enqueue", methods=["POST"])
def enqueue():
    """Called by sandbox code to submit an LLM request and wait for response."""
    data = request.json
    request_id = str(uuid.uuid4())
    event = threading.Event()

    with lock:
        pending_requests[request_id] = {
            "request": data,
            "response": None,
            "event": event,
        }

    # Wait for response (with timeout)
    event.wait(timeout=300)

    with lock:
        entry = pending_requests.pop(request_id, None)

    if entry and entry["response"] is not None:
        return jsonify(entry["response"])
    else:
        return jsonify({"error": "Request timed out"}), 504

@app.route("/pending")
def get_pending():
    """Called by ModalREPL to get pending requests."""
    with lock:
        pending = [
            {"id": rid, "request": entry["request"]}
            for rid, entry in pending_requests.items()
            if entry["response"] is None
        ]
    return jsonify({"pending": pending})

@app.route("/respond", methods=["POST"])
def respond():
    """Called by ModalREPL to submit a response."""
    data = request.json
    request_id = data.get("id")
    response = data.get("response")

    with lock:
        if request_id in pending_requests:
            pending_requests[request_id]["response"] = response
            pending_requests[request_id]["event"].set()
            return jsonify({"status": "ok"})

    return jsonify({"error": "Request not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
'''
)


# =============================================================================
# Execution Script Builder
# =============================================================================

def _build_exec_script(code: str, broker_port: int = 8080, depth: int = 1) -> str:
    """
    Build a script that executes code with state persistence.
    LLM queries go through the local broker server.
    """
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys
import io
import json
import base64
import traceback
import os
import requests

try:
    import dill
except ImportError:
    import pickle as dill

# =============================================================================
# LLM Query Functions (via local broker)
# =============================================================================

BROKER_URL = "http://127.0.0.1:{broker_port}"

def llm_query(prompt, model=None):
    """Query the LM via the broker."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "single", "prompt": prompt, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return f"Error: {{data['error']}}"
        return data.get("response", "Error: No response")
    except Exception as e:
        return f"Error: LM query failed - {{e}}"


def llm_query_batched(prompts, model=None):
    """Query the LM with multiple prompts."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "batched", "prompts": prompts, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return [f"Error: {{data['error']}}"] * len(prompts)
        return data.get("responses", ["Error: No response"] * len(prompts))
    except Exception as e:
        return [f"Error: LM query failed - {{e}}"] * len(prompts)


# =============================================================================
# State Management
# =============================================================================

STATE_FILE = "/tmp/rlm_state.dill"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(state):
    clean_state = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            clean_state[k] = v
        except:
            pass
    with open(STATE_FILE, "wb") as f:
        dill.dump(clean_state, f)

def serialize_locals(state):
    result = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            result[k] = repr(v)
        except:
            result[k] = f"<{{type(v).__name__}}>"
    return result

# =============================================================================
# Execution
# =============================================================================

_locals = load_state()

def FINAL_VAR(variable_name):
    variable_name = variable_name.strip().strip("\\"\\'")
    if variable_name in _locals:
        return str(_locals[variable_name])
    available = [k for k in _locals.keys() if not k.startswith("_")]
    if available:
        return f"Error: Variable '{{variable_name}}' not found. Available variables: {{available}}. You must create and assign a variable BEFORE calling FINAL_VAR on it."
    return f"Error: Variable '{{variable_name}}' not found. No variables have been created yet. You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."

def SHOW_VARS():
    available = {{k: type(v).__name__ for k, v in _locals.items() if not k.startswith("_")}}
    if not available:
        return "No variables created yet. Use ```repl``` blocks to create variables."
    return f"Available variables: {{available}}"

_globals = {{
    "__builtins__": __builtins__,
    "__name__": "__main__",
    "llm_query": llm_query,
    "llm_query_batched": llm_query_batched,
    "FINAL_VAR": FINAL_VAR,
    "SHOW_VARS": SHOW_VARS,
}}

code = base64.b64decode("{code_b64}").decode()

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for key, value in combined.items():
        if key not in _globals and not key.startswith("_"):
            _locals[key] = value
except Exception as e:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr

save_state(_locals)

result = {{
    "stdout": stdout_buf.getvalue(),
    "stderr": stderr_buf.getvalue(),
    "locals": serialize_locals(_locals),
}}
print(json.dumps(result))
'''
    )


# =============================================================================
# REPLResult dataclass (compatible with rlm.repl.REPLResult)
# =============================================================================

@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float

    def __str__(self):
        return f"REPLResult(stdout={self.stdout}, stderr={self.stderr}, locals={self.locals}, execution_time={self.execution_time})"


# =============================================================================
# ModalREPL Class
# =============================================================================

class ModalREPL:
    """
    Modal REPL environment that runs Python code in a persistent Modal Sandbox.

    Uses Modal tunnels for LLM communication:
    - Sandbox runs a broker server exposed via encrypted_ports
    - ModalREPL polls the broker for pending LLM requests
    - ModalREPL forwards requests to the LM handler and posts responses back

    Compatible with REPLEnv interface for use in RLM_REPL.
    """

    BROKER_PORT = 8080

    def __init__(
        self,
        lm_handler: Callable[[str, Optional[str], int], str],
        depth: int = 0,
        max_depth: int = 3,
        app_name: str = "rlm-sandbox",
        image: modal.Image | None = None,
        volumes: dict[str, modal.Volume] | None = None,
        timeout: int = 600,
        context_payload: dict | list | str | None = None,
        context_path: str | None = None,
        setup_code: str | None = None,
    ):
        """
        Initialize ModalREPL with a persistent sandbox and broker.

        Args:
            lm_handler: Function to handle LLM requests. Signature: (prompt, model, depth) -> response
            depth: Current recursion depth (0 for root)
            max_depth: Maximum recursion depth allowed
            app_name: Modal app name
            image: Modal image to use (if None, creates default)
            volumes: Modal volumes to mount
            timeout: Sandbox timeout in seconds
            context_payload: Context data (dict/list/str) to load into sandbox
            context_path: Path to context file (if using file-based context)
            setup_code: Python code to run during initialization
        """
        self.lm_handler = lm_handler
        self.depth = depth
        self.max_depth = max_depth
        self.app_name = app_name
        self.timeout = timeout
        self.volumes = volumes or {}

        # Create or use provided image
        if image is None:
            self.image = self._create_default_image()
        else:
            self.image = image

        # Sandbox state
        self.app = None
        self.sandbox = None
        self.broker_process = None
        self.broker_url: str | None = None
        self.poller_thread: threading.Thread | None = None
        self.poller_stop = threading.Event()
        self.locals = {}  # Synced from sandbox

        # Setup sandbox and broker
        self.setup()

        # Load context if provided
        if context_payload is not None:
            self.load_context(context_payload)
        elif context_path is not None:
            self.load_context_from_path(context_path)

        # Run setup code if provided
        if setup_code:
            self.code_execution(setup_code)

    def _create_default_image(self) -> modal.Image:
        """Create default Modal image with common packages for sandbox execution."""
        return (
            modal.Image.debian_slim(python_version="3.12")
            .pip_install("flask", "requests", "dill")
        )

    def setup(self):
        """Create the Modal app, sandbox, broker, and start polling."""
        # Create or lookup Modal app
        self.app = modal.App.lookup(self.app_name, create_if_missing=True)

        # Create sandbox with encrypted port for broker
        create_kwargs = {
            "app": self.app,
            "image": self.image,
            "timeout": self.timeout,
            "encrypted_ports": [self.BROKER_PORT],
        }
        if self.volumes:
            create_kwargs["volumes"] = self.volumes

        self.sandbox = modal.Sandbox.create(**create_kwargs)

        # Start the broker server in the sandbox
        self.broker_process = self.sandbox.exec(
            "python",
            "-c",
            _BROKER_SCRIPT,
        )

        # Wait for broker to be ready
        time.sleep(2)

        # Get the tunnel URL
        tunnels = self.sandbox.tunnels()
        if self.BROKER_PORT in tunnels:
            self.broker_url = tunnels[self.BROKER_PORT].url

        # Start polling thread
        self.poller_stop.clear()
        self.poller_thread = threading.Thread(target=self._poll_broker, daemon=True)
        self.poller_thread.start()

    def _poll_broker(self):
        """Poll the broker for pending LLM requests and handle them."""
        while not self.poller_stop.is_set():
            try:
                # Get pending requests
                resp = requests.get(
                    f"{self.broker_url}/pending",
                    timeout=5,
                )
                pending = resp.json().get("pending", [])

                for item in pending:
                    request_id = item["id"]
                    req_data = item["request"]

                    # Handle the request
                    response = self._handle_llm_request(req_data)

                    # Send response back
                    requests.post(
                        f"{self.broker_url}/respond",
                        json={"id": request_id, "response": response},
                        timeout=10,
                    )

            except requests.exceptions.RequestException:
                pass
            except Exception:
                pass

            time.sleep(0.1)

    def _handle_llm_request(self, req_data: dict) -> dict:
        """Handle an LLM request from the sandbox."""
        req_type = req_data.get("type")
        model = req_data.get("model")
        depth = req_data.get("depth", self.depth + 1)

        if req_type == "single":
            prompt = req_data.get("prompt")
            response = self.lm_handler(prompt, model, depth)
            return {"response": response}

        elif req_type == "batched":
            prompts = req_data.get("prompts", [])
            # Handle batched requests by calling lm_handler for each
            responses = []
            for prompt in prompts:
                response = self.lm_handler(prompt, model, depth)
                responses.append(response)
            return {"responses": responses}

        return {"error": "Unknown request type"}

    def load_context(self, context_payload: dict | list | str):
        """Load context into the sandbox environment."""
        if isinstance(context_payload, str):
            escaped = context_payload.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            context_code = f'context = """{escaped}"""'
        else:
            context_json = json.dumps(context_payload)
            escaped_json = context_json.replace("\\", "\\\\").replace("'", "\\'")
            context_code = f"import json; context = json.loads('{escaped_json}')"

        self.code_execution(context_code)

    def load_context_from_path(self, context_path: str):
        """Load context from a file path (file must be accessible in sandbox via volume mount)."""
        # Set both context and context_path variables in the sandbox
        context_code = f'context_path = r"{context_path}"\nwith open(context_path, "r") as f: context = f.read()'
        self.code_execution(context_code)

    def code_execution(self, code: str) -> REPLResult:
        """Execute code in the Modal sandbox and return result."""
        start_time = time.perf_counter()

        # Build and execute the script
        script = _build_exec_script(code, self.BROKER_PORT, self.depth + 1)
        process = self.sandbox.exec("python", "-c", script)

        # Read output
        stdout = process.stdout.read()
        stderr = process.stderr.read()

        execution_time = time.perf_counter() - start_time

        # Parse the JSON result
        try:
            lines = stdout.strip().split("\n")
            result_json = lines[-1] if lines else "{}"
            result = json.loads(result_json)

            # Update local copy of variables
            self.locals = result.get("locals", {})

            return REPLResult(
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", "") + stderr,
                locals=self.locals,
                execution_time=execution_time,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=stdout,
                stderr=stderr or "Failed to parse execution result",
                locals={},
                execution_time=execution_time,
            )

    def cleanup(self):
        """Terminate the sandbox and stop polling."""
        # Stop the poller thread
        if self.poller_thread is not None:
            self.poller_stop.set()
            self.poller_thread.join(timeout=2)
            self.poller_thread = None

        if self.sandbox is not None:
            try:
                self.sandbox.terminate()
            except Exception:
                pass
            self.sandbox = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
