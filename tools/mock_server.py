"""Tiny offline mock of an OpenAI-compatible chat server.

Lets llama-benchy (CLI and GUI) run end-to-end without a real inference
server: useful for smoke tests, screenshots and CI.

    python tools/mock_server.py            # listens on 127.0.0.1:8080

The "model" streams one chunk per requested token with a fixed per-token
delay, so the reported pp/tg numbers are synthetic but structurally valid.
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "demo-model"
PREFILL_MS_PER_TOKEN = 0.8   # ~1250 t/s prompt processing
GEN_MS_PER_TOKEN = 25        # ~40 t/s generation


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path.endswith("/models"):
            self._json({"data": [{"id": MODEL, "object": "model"}]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            self._json({"error": "not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json({"error": "bad json"}, 400)
            return

        prompt = "".join(str(m.get("content", "")) for m in req.get("messages", []))
        prompt_tokens = approx_tokens(prompt)
        max_tokens = max(1, int(req.get("max_tokens", 32)))

        # The tool's coherence check asks for the capital of France.
        if "capital of france" in prompt.lower():
            answer = "Paris " * max_tokens
        else:
            answer = "tok " * max_tokens

        if not req.get("stream"):
            self._json({
                "id": "mock-1",
                "model": MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": max_tokens,
                          "total_tokens": prompt_tokens + max_tokens},
            })
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # prefill
        time.sleep(PREFILL_MS_PER_TOKEN * prompt_tokens / 1000.0)
        for _ in range(max_tokens):
            chunk = {"choices": [{"index": 0, "delta": {"content": "tok "}}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.flush()
            time.sleep(GEN_MS_PER_TOKEN / 1000.0)

        final = {"choices": [{"index": 0, "delta": {}}],
                 "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": max_tokens,
                           "total_tokens": prompt_tokens + max_tokens}}
        self.wfile.write(b"data: " + json.dumps(final).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock {MODEL} listening on http://127.0.0.1:{port}/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
