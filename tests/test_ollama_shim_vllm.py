"""tools/ollama_shim_vllm.py: the Ollama chat body -> the vLLM request, and the answer cleaned of reasoning and special tokens;
one round trip against a fake vLLM server (no GPU, no network beyond localhost)."""
import importlib.util
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("shim", Path(__file__).resolve().parents[1] / "tools" / "ollama_shim_vllm.py")
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)


def test_request_mapping():
    r = shim.to_vllm({"model": "m", "messages": [{"role": "user", "content": "hi"}], "think": False,
                      "options": {"temperature": 0.2, "seed": 3, "num_predict": 128, "num_ctx": 8192}}, "served")
    assert r["model"] == "served" and r["max_tokens"] == 128 and r["seed"] == 3 and r["temperature"] == 0.2
    assert r["chat_template_kwargs"] == {"skip_reasoning": True} and r["skip_special_tokens"] is False
    assert "<|im_end|><|endofturn|>" in r["stop"]
    assert shim.to_vllm({"messages": [], "think": True}, "s")["chat_template_kwargs"] == {"force_reasoning": True}
    assert "chat_template_kwargs" not in shim.to_vllm({"messages": []}, "s")
    assert shim.to_vllm({"messages": [], "format": {"type": "object"}}, "s")["guided_json"] == {"type": "object"}


def test_clean_drops_reasoning_and_special_tokens():
    assert shim.clean("<think>plan it</think>\n안녕하세요.<|im_end|><|endofturn|>") == "안녕하세요."
    assert shim.clean(None) == ""


def test_round_trip_against_a_fake_vllm():
    seen = {}

    class V(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps({"choices": [{"message": {"content": "<think>x</think>네, 알겠어요.<|im_end|>"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    v = HTTPServer(("127.0.0.1", 0), V)
    s = shim.Server(("127.0.0.1", 0), shim.make_handler(f"http://127.0.0.1:{v.server_port}", "served"))
    for srv in (v, s):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{s.server_port}/api/chat", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": "m", "messages": [{"role": "user", "content": "q"}], "stream": False,
                                                      "think": False, "options": {"seed": 1}}).encode())
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert out["message"]["content"] == "네, 알겠어요." and seen["body"]["model"] == "served"
        assert json.loads(urllib.request.urlopen(f"http://127.0.0.1:{s.server_port}/api/tags", timeout=10).read())["models"][0]["name"] == "served"
    finally:
        v.shutdown(); s.shutdown()
