"""Capture a synthetic request at a local HTTP fixture, without a model call.

This tests the installed Codex binary's actual serialized request, including
tool registries and automatically injected context. Never forwards a request.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gpt_transport import call, digest

SYSTEM = "You are a test responder. Reply with READY only."
PROMPT = "Reply with READY only."


def validate_request(body: dict, model: str, effort: str) -> dict:
    if body.get("model") != model or body.get("reasoning", {}).get("effort") != effort:
        raise ValueError("Outgoing model or reasoning effort differs from request")
    if body.get("tools", []) != []:
        raise ValueError("Tools are exposed: " + json.dumps(body.get("tools"))[:1500])
    if body.get("previous_response_id") or body.get("conversation"):
        raise ValueError("Conversation reuse detected")
    expected = [("user", PROMPT)]
    # Responses Lite represents base instructions as a developer message.
    if body.get("instructions") is None:
        expected.insert(0, ("developer", SYSTEM))
    elif body["instructions"] != SYSTEM:
        raise ValueError("Unexpected base instructions")
    messages = []
    for item in body.get("input", []):
        if item.get("type") == "additional_tools":
            if (item.get("tools") != [] or item.get("role") != "developer" or
                    set(item) - {"type", "id", "role", "tools"}):
                raise ValueError("Additional tools/context exposed: " + json.dumps(item)[:2000])
        else:
            messages.append(item)
    if len(messages) != len(expected):
        raise ValueError("Extra tools/context injected: " + json.dumps(messages)[:4000])
    for message, (role, text) in zip(messages, expected):
        if message.get("type", "message") != "message" or message.get("role") != role:
            raise ValueError("Unexpected message/tool item: " + json.dumps(message)[:2000])
        if message.get("content") != [{"type": "input_text", "text": text}]:
            raise ValueError("Extra context injected: " + json.dumps(message)[:2000])
    return {"model": model, "effort": effort, "tools": [],
            "input_messages": len(messages), "system_matches": True,
            "user_matches": True, "no_previous_response": True,
            "request_sha256": digest(json.dumps(body, sort_keys=True))}


def audit(model: str, effort: str, catalog: dict) -> dict:
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                body = json.loads(raw)
                captured.append(body)
            except Exception:
                captured.append({"invalid_request": True})
            response = {
                "id": "resp_fixture", "object": "response", "created_at": 0,
                "model": model, "status": "completed",
                "output": [{"id": "msg_fixture", "type": "message",
                            "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "READY",
                                         "annotations": []}]}],
                "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}},
            }
            item = response["output"][0]
            events = [
                {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                {"type": "response.output_item.added", "output_index": 0, "item": {**item, "content": []}},
                {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": "READY"},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            data = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        call(model, effort, PROMPT, SYSTEM, catalog, timeout=40, overrides={
            "model_provider": "touchstone_fixture",
            "model_providers.touchstone_fixture.name": "Local request audit (no model)",
            "model_providers.touchstone_fixture.base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model_providers.touchstone_fixture.wire_api": "responses",
            "model_providers.touchstone_fixture.requires_openai_auth": False,
            "model_providers.touchstone_fixture.request_max_retries": 0,
            "model_providers.touchstone_fixture.stream_max_retries": 0,
        })
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    if len(captured) != 1:
        raise ValueError(f"Expected one request, observed {len(captured)}")
    return validate_request(captured[0], model, effort)


if __name__ == "__main__":
    from gpt_transport import catalog_path, isolated_catalog
    model = "gpt-5.6-luna"
    catalog = isolated_catalog(json.loads(catalog_path().read_text()), [model])
    print(json.dumps(audit(model, "none", catalog), indent=2))
