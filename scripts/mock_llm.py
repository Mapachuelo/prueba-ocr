#!/usr/bin/env python3
"""Mock mínimo de servidor OpenAI-compatible para probar el modo 2 (VLM).

Uso:
    python3 scripts/mock_llm.py --port 18081 --model qwen2.5-vl-7b-instruct
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CANNED = {
    "numero": "80123456",
    "apellidos": "PEREZ GOMEZ",
    "nombres": "JUAN CARLOS",
    "fecha_nacimiento": "15-MAR-1990",
    "lugar_nacimiento": "BOGOTA",
    "rh": "O+",
    "sexo": "M",
    "estatura": "175",
    "fecha_expedicion": "20-ENE-2015",
    "lugar_expedicion": "MEDELLIN",
}


class Handler(BaseHTTPRequestHandler):
    model = "mock-vlm"

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"data": [{"id": self.model}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        content = json.dumps(CANNED, ensure_ascii=False)
        self._send(200, {
            "id": "mock-1",
            "object": "chat.completion",
            "model": body.get("model", self.model),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        })

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18081)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--model", default="qwen2.5-vl-7b-instruct")
    args = ap.parse_args()
    Handler.model = args.model
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock LLM en http://{args.host}:{args.port}/v1 (modelo {args.model})")
    server.serve_forever()


if __name__ == "__main__":
    main()
