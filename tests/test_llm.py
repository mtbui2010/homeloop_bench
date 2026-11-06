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


class EchoMsgs(Echo):
    def chat_messages(self, messages, temperature=0.0, seed=0, format=None):
        self.n += 1
        return "/".join(m["content"] for m in messages) + f"|{seed}"


def test_ollama_body_with_messages():
    c = OllamaHTTP("http://127.0.0.1:1/", "m:1")
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    b = c.body("", temperature=0.2, seed=0, messages=msgs)
    assert b["messages"] == msgs and b["options"]["num_ctx"] == 8192


def test_cache_and_count_chat_messages(tmp_path):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    e = EchoMsgs()
    c = CountingLLM(CachedLLM(e, tmp_path / "c.jsonl"), 2)
    assert c.chat_messages(msgs, 0.2, 0) == "s/u|0" and c.chat_messages(msgs, 0.2, 0) == "s/u|0"
    assert e.n == 1 and c.calls == 2                     # every call counts, the second is a cache hit
    with pytest.raises(BudgetExceeded):
        c.chat_messages(msgs, 0.2, 0)
    c2 = CachedLLM(EchoMsgs(), tmp_path / "c.jsonl")
    assert c2.chat_messages(msgs, 0.2, 0) == "s/u|0" and c2.inner.n == 0
    assert c2.chat_messages(msgs, 0.2, 1) == "s/u|1" and c2.inner.n == 1   # the seed is part of the key
    # a single user message shares its key with chat(prompt)
    assert c2.chat_messages([{"role": "user", "content": "p"}], 0.0, 0) == "p|0"
    assert c2.chat("p") == "p|0" and c2.inner.n == 2


# ── round 7: a per-call num_predict (a cap on the answer's tokens), out of every cache key ──
class Capped:
    model = "capped"

    def __init__(self):
        self.seen = []

    def chat(self, prompt, format=None, temperature=0.0, seed=0, num_predict=None):
        self.seen.append(num_predict)
        return "ok"


def test_ollama_body_carries_num_predict_only_when_given():
    c = OllamaHTTP("http://127.0.0.1:1", "m:1")
    assert "num_predict" not in c.body("hi")["options"]
    assert c.body("hi", num_predict=512)["options"] == {"temperature": 0.0, "seed": 0, "num_ctx": 8192, "num_predict": 512}


def test_num_predict_is_passed_down_and_not_part_of_the_cache_key(tmp_path):
    inner = Capped()
    c = CountingLLM(CachedLLM(inner, tmp_path / "c.jsonl"))
    c.chat("a", num_predict=512)
    c.chat("a")                                          # the same prompt, no cap: the cached answer, no new call
    assert inner.seen == [512] and c.calls == 2
    from homeloop_bench.llm import cache_key
    assert cache_key("capped", "a", None, 0.0, 0) in CachedLLM(Capped(), tmp_path / "c.jsonl")._mem
    # a client that does not know the keyword is never given it
    e = Echo()
    CountingLLM(CachedLLM(e, tmp_path / "d.jsonl")).chat("a")
    assert e.n == 1
