"""The coverage question (SAGE-v2 request_coverage, clarify kind 'coverage') through the real AssistLoop, the homeloop_robot
package and the simulated user, in EN and KO: the robot's own phrase reaches the user (the pack's Korean phrase, no mixed
text), the question is mapped onto the structured confirm with the part as the goal slot, the heard-text check reads the same
question, and the user answers from the true state. The coverage model is a double that names the whole request as one part
(the deterministic pre-filter is switched off so the question is asked: it is the dialog path that is under test)."""
import pytest

pytest.importorskip("robot_agent")
rc = pytest.importorskip("robot_agent.core.planning.request_coverage")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import robot_agent_fake as F  # noqa: E402
from homeloop_bench.runner import run_episode  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_the_coverage_question_is_a_structured_confirm_and_a_done_part_gets_no(monkeypatch, lang):
    orig = F.FakeUnderstandLLM.chat
    seen = []

    def chat(self, prompt="", format=None, **kw):
        if "about to say it is done" in str(prompt):
            env = F._env()
            seen.append(env.task_text)
            import json
            return json.dumps({"unserved": [{"part": env.task_text, "why": "not_touched"}]}, ensure_ascii=False)
        return orig(self, prompt, format, **kw)

    monkeypatch.setattr(F.FakeUnderstandLLM, "chat", chat)
    monkeypatch.setattr(rc, "covered_names", lambda *a, **k: [])
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage_s4", "ideal", 0, lang, "fake")
    assert seen, "the coverage call was made"
    asks = [c for c in e["calls"] if c["skill"] == "ask"]
    assert len(asks) == 1, e["calls"]
    q = asks[0]["args"]["question"]
    assert "You also asked me for this" in q if lang == "en" else "부탁하셨는데" in q, q
    assert e["dialog_paths"] == {"structured": 1}, e["dialog_paths"]       # derived as a structured confirm, heard text agrees
    assert asks[0].get("reply_kind") == "no"                           # the part holds in the true world
    assert e["success"] and e["status"] == "done"                          # every goal held: the user says no, done as before
    assert e["dialog_not_in_lang"] == 0 and e["say_not_in_lang"] == 0      # no mixed-language text reached the user
