// src/index.ts
// Streamable-HTTP MCP gateway that proxies tool calls to Modal backend.
// No Durable Objects — all state lives on Modal's shared volume.

export interface Env {
  MODAL_BACKEND_URL: string;
}

type JsonRpcId = string | number | null;

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: JsonRpcId;
  method: string;
  params?: unknown;
}

interface ToolCallParams {
  name: string;
  arguments?: {
    query?: string;
    thread_id?: string;
    transcript?: string;
    session_id?: string;
    developer?: string;
  };
}

/* ----------------------- Streamable HTTP helpers ----------------------- */

function wantsSse(request: Request): boolean {
  const accept = request.headers.get("accept") ?? "";
  return accept.toLowerCase().includes("text/event-stream");
}

function streamableResponse(request: Request, payload: unknown, status = 200): Response {
  if (!wantsSse(request)) {
    return Response.json(payload, { status });
  }

  const sse = `event: message\ndata: ${JSON.stringify(payload)}\n\n`;
  return new Response(sse, {
    status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

function jsonRpcResult(request: Request, id: JsonRpcId, result: unknown): Response {
  return streamableResponse(request, { jsonrpc: "2.0", id, result });
}

function jsonRpcError(request: Request, id: JsonRpcId, code: number, message: string): Response {
  return streamableResponse(request, { jsonrpc: "2.0", id, error: { code, message } });
}

/* ----------------------- Modal proxy ----------------------- */

async function proxyToModal(
  env: Env,
  endpoint: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const url = `${env.MODAL_BACKEND_URL.replace(/\/$/, "")}/${endpoint}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`Modal ${endpoint} error (${resp.status}): ${detail.slice(0, 400)}`);
  }

  return (await resp.json()) as Record<string, unknown>;
}

/* ----------------------- MCP handler ----------------------- */

async function handleOneRpc(request: Request, env: Env, rpc: JsonRpcRequest): Promise<Response> {
  const id = rpc.id ?? null;

  if (rpc.jsonrpc !== "2.0" || typeof rpc.method !== "string") {
    return jsonRpcError(request, id, -32600, "Invalid Request");
  }

  // Lifecycle
  if (rpc.method === "notifications/initialized") return new Response(null, { status: 202 });

  if (rpc.method === "initialize") {
    return jsonRpcResult(request, id, {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "deeprecurse-worker-mcp", version: "0.2.0" },
    });
  }

  if (rpc.method === "ping") return jsonRpcResult(request, id, {});

  // Compatibility no-ops
  if (rpc.method === "resources/list") return jsonRpcResult(request, id, { resources: [] });
  if (rpc.method === "prompts/list") return jsonRpcResult(request, id, { prompts: [] });

  // Tools
  if (rpc.method === "tools/list") {
    return jsonRpcResult(request, id, {
      tools: [
        {
          name: "chat_rlm_query",
          description:
            "Use this to query the Python RLM backend while reading/updating shared persistent thread context (thread_id).",
          inputSchema: {
            type: "object",
            properties: {
              query: { type: "string" },
              thread_id: { type: "string" },
            },
            required: ["query", "thread_id"],
          },
        },
        {
          name: "upload_context",
          description:
            "Upload a Claude Code session transcript to the shared context store. The transcript is stored under a thread so the RLM can reason over past sessions.",
          inputSchema: {
            type: "object",
            properties: {
              transcript: { type: "string", description: "The full session transcript text to upload." },
              session_id: { type: "string", description: "Session identifier." },
              thread_id: { type: "string", description: "Thread to store the transcript under (default: 'transcripts')." },
              developer: { type: "string", description: "Developer name/identifier." },
            },
            required: ["transcript", "session_id"],
          },
        },
      ],
    });
  }

  if (rpc.method === "tools/call") {
    const params = (rpc.params ?? {}) as ToolCallParams;

    if (params.name === "chat_rlm_query") {
      const query = params.arguments?.query?.trim();
      const threadId = params.arguments?.thread_id?.trim();
      if (!query || !threadId) {
        return jsonRpcError(request, id, -32602, "query and thread_id are required");
      }

      try {
        const data = await proxyToModal(env, "query_endpoint", {
          query,
          thread_id: threadId,
        });

        if (data.error) {
          return jsonRpcError(request, id, -32000, String(data.error));
        }

        return jsonRpcResult(request, id, {
          content: [{ type: "text", text: String(data.answer ?? "") }],
        });
      } catch (err) {
        return jsonRpcError(
          request,
          id,
          -32000,
          err instanceof Error ? err.message : "Unknown internal error",
        );
      }
    }

    if (params.name === "upload_context") {
      const transcript = params.arguments?.transcript?.trim();
      const sessionId = params.arguments?.session_id?.trim();
      const threadId = params.arguments?.thread_id?.trim() || "transcripts";
      const developer = params.arguments?.developer || "unknown";

      if (!transcript || !sessionId) {
        return jsonRpcError(request, id, -32602, "transcript and session_id are required");
      }

      try {
        const data = await proxyToModal(env, "upload_endpoint", {
          transcript,
          session_id: sessionId,
          thread_id: threadId,
          developer,
        });

        if (data.error) {
          return jsonRpcError(request, id, -32000, String(data.error));
        }

        const msg = data.message || `Uploaded session ${sessionId} to thread '${threadId}'.`;
        return jsonRpcResult(request, id, {
          content: [{ type: "text", text: String(msg) }],
        });
      } catch (err) {
        return jsonRpcError(
          request,
          id,
          -32000,
          err instanceof Error ? err.message : "Unknown internal error",
        );
      }
    }

    return jsonRpcError(request, id, -32602, "Unknown tool");
  }

  return jsonRpcError(request, id, -32601, "Method not found");
}

async function handleMcp(request: Request, env: Env): Promise<Response> {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "POST,OPTIONS",
        "access-control-allow-headers": "content-type,accept,mcp-session-id,authorization",
      },
    });
  }

  if (request.method !== "POST") return new Response("Method Not Allowed", { status: 405 });

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonRpcError(request, null, -32700, "Parse error");
  }

  if (Array.isArray(body)) {
    const responses: unknown[] = [];
    for (const item of body) {
      if (typeof item !== "object" || item === null) continue;
      const rpc = item as JsonRpcRequest;
      const resp = await handleOneRpc(
        new Request(request, { headers: { ...Object.fromEntries(request.headers) } }),
        env,
        rpc,
      );
      const json = await resp.json().catch(() => null);
      if (json) responses.push(json);
    }
    return Response.json(responses);
  }

  return handleOneRpc(request, env, body as JsonRpcRequest);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") return new Response("ok", { status: 200 });
    if (url.pathname === "/mcp") return handleMcp(request, env);

    return new Response("Not Found", { status: 404 });
  },
};
