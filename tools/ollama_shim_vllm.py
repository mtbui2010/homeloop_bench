#!/usr/bin/env python3
"""Serve an Ollama-style ``/api/chat`` (what ``homeloop_bench.llm.OllamaHTTP`` speaks) on top of a vLLM OpenAI server.

For a model Ollama cannot load (HyperCLOVAX-SEED-Think-14B): ``vllm serve <dir> --served-model-name NAME --port 8100`` and
``python tools/ollama_shim_vllm.py --vllm http://127.0.0.1:8100 --port 11540``, then ``HOMELOOP_DIALOG_URL=http://127.0.0.1:11540``.

Mapping: options.temperature / seed / num_predict -> temperature / seed / max_tokens; ``think`` false -> the chat template's
``skip_reasoning`` (the model answers directly), true -> ``force_reasoning``; the stop tokens and ``skip_special_tokens`` false
the vendor documents; a leading ``<think>...</think>`` block and trailing special tokens are removed from the answer. A JSON
``format`` is passed on as a vLLM ``guided_json`` schema (a plain ``"json"`` as a JSON-object response format).
Stdlib only; one process, threaded.
"""
import argparse
import json
import re
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STOPS = ["<|im_end|><|endofturn|>", "<|im_end|><|stop|>"]
SPECIAL = re.compile(r"<\|[a-z_]+\|>")
THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


def to_vllm(body: dict, served: str) -> dict:
    """The OpenAI chat-completions request of one Ollama ``/api/chat`` body."""
    o = body.get("options") or {}
    req = {"model": served, "messages": body.get("messages") or [], "temperature": float(o.get("temperature", 0.0)),
           "skip_special_tokens": False, "stop": STOPS, "top_k": -1}
    if "seed" in o:
        req["seed"] = int(o["seed"])
    if o.get("num_predict"):
        req["max_tokens"] = int(o["num_predict"])
    think = body.get("think")
    if think is not None:
        req["chat_template_kwargs"] = {"force_reasoning": True} if think else {"skip_reasoning": True}
    fmt = body.get("format")
    if isinstance(fmt, dict):
        req["guided_json"] = fmt
    elif fmt == "json":
        req["response_format"] = {"type": "json_object"}
    return req


def clean(text: str) -> str:
    """The answer without a reasoning block and without special tokens."""
    return SPECIAL.sub("", THINK.sub("", str(text or ""))).strip()


def from_vllm(out: dict, model: str) -> dict:
    msg = ((out.get("choices") or [{}])[0].get("message") or {})
    return {"model": model, "message": {"role": "assistant", "content": clean(msg.get("content"))}, "done": True}


class Server(ThreadingHTTPServer):
    daemon_threads = True


def make_handler(vllm: str, served: str):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(200, {"models": [{"name": served}]})

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                req = urllib.request.Request(vllm.rstrip("/") + "/v1/chat/completions",
                                             data=json.dumps(to_vllm(body, served)).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    out = json.loads(r.read().decode("utf-8"))
                self._send(200, from_vllm(out, body.get("model") or served))
            except Exception as e:              # noqa: BLE001 - a 500 is what OllamaHTTP retries
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def log_message(self, *a):
            pass
    return H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vllm", default="http://127.0.0.1:8100")
    ap.add_argument("--served-model-name", default="hyperclovax-seed-think-14b")
    ap.add_argument("--port", type=int, default=11540)
    a = ap.parse_args(argv)
    Server(("127.0.0.1", a.port), make_handler(a.vllm, a.served_model_name)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
