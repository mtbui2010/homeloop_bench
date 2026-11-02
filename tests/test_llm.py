"""LLM clients: Ollama request body, cache, counting (no network)."""

import pytest

from homeloop_bench.llm import BudgetExceeded, CachedLLM, CountingLLM, OllamaHTTP, make_llm, FakeLLM


class Echo:
    model = "echo"

    def __init__(self):
        self.n = 0

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.n += 1
        return f"{prompt}|{seed}"


def test_ollama_body():
    c = OllamaHTTP("http://127.0.0.1:1/", "m:1")
    b = c.body("hi", format="json", temperature=0.7, seed=3)
    assert c.url == "http://127.0.0.1:1"
    assert b == {"model": "m:1", "messages": [{"role": "user", "content": "hi"}], "stream": False,
                 "options": {"temperature": 0.7, "seed": 3, "num_ctx": 8192}, "format": "json"}


def test_cache_roundtrip(tmp_path):
    e = Echo()
    c = CachedLLM(e, tmp_path / "c.jsonl")
    assert c.chat("a", seed=1) == "a|1" and c.chat("a", seed=1) == "a|1" and e.n == 1
    c2 = CachedLLM(Echo(), tmp_path / "c.jsonl")
    assert c2.chat("a", seed=1) == "a|1" and c2.inner.n == 0 and c2.hits == 1


def test_counting_budget():
    c = CountingLLM(Echo(), 2)
    c.chat("a")
    c.chat("b")
    with pytest.raises(BudgetExceeded):
        c.chat("c")
    assert c.calls == 2


def test_make_llm():
    assert make_llm(None) is None
    assert isinstance(make_llm("fake"), FakeLLM)
    assert isinstance(make_llm("http://x:1", "m"), OllamaHTTP)
    with pytest.raises(ValueError):
        make_llm("ftp://x")
