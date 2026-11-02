"""embodiplan's own LLM calls (sage / grace generator) go through the episode's LLM chain: counted, budgeted,
cached in the run's llm_cache, with seed 0 when embodiplan sets none (docs/robot_agent.md)."""

import types

import pytest

from homeloop_bench.llm import BudgetExceeded, CachedLLM, CountingLLM
from homeloop_bench.planners.robot_agent_adapter import _count_embodiplan, _patched

embodiplan = pytest.importorskip("embodiplan")


class Inner:
    model = "m:1"

    def __init__(self):
        self.seen = []

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        raise AssertionError("embodiplan calls must keep their message list")

    def chat_messages(self, messages, temperature=0.0, seed=0, format=None):
        self.seen.append((messages, temperature, seed))
        return "PLAN"


def test_embodiplan_calls_are_routed_cached_and_counted(tmp_path):
    inner = Inner()
    counter = CountingLLM(CachedLLM(inner, tmp_path / "llm_cache" / "m.jsonl"), 3)
    env = types.SimpleNamespace(llm=lambda: counter)
    be = embodiplan.LLMBackend(provider="ollama", model="m:1", host="http://127.0.0.1:9", temperature=0.2)
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    with _patched(_count_embodiplan(env)):
        out, tin, tout = be.chat(msgs)
        assert out == "PLAN" and tin > 0 and tout > 0
        assert inner.seen == [(msgs, 0.2, 0)]
        be.chat(msgs)                                     # cache hit, still counted
        assert len(inner.seen) == 1 and counter.calls == 2
        be.chat(msgs, temperature=0.0)
        with pytest.raises(BudgetExceeded):
            be.chat(msgs)
    assert (tmp_path / "llm_cache" / "m.jsonl").read_text().count("\n") == 2
    assert embodiplan.LLMBackend.chat is not None and "routed" not in embodiplan.LLMBackend.chat.__name__
