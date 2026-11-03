"""The simulated user's structured questions and LLM intent classifier on the bench side (R2-7a,
homeloop_robot docs/user_model.md "Structured questions"): the ask API's meaning channel, the classifier chain
(rules -> cached LLM classifier), the per-episode path records, and the planners that declare a meaning."""

import json
import re

import pytest

from homeloop_bench import user_intent as UI
from homeloop_bench.env import EpisodeEnv
from homeloop_bench.llm import CachedLLM, CountingLLM, FakeLLM, LLMError, cache_key
from homeloop_bench.tasks import task_by_id
from homeloop_robot import intent

MILK = "hl-dev-000003"           # korean_apt_59, clarify: put the milk away -> into the kimchi fridge
TELL = "hl-dev-000013"           # couple_flat: let my husband know we're leaving in ten minutes
FREE_Q = {"en": "Any particular words you want me to use for him?", "ko": "그분께 쓰고 싶은 특별한 표현이 있으세요?"}  # the rules do not read these


class StubLLM:
    """A chat LLM returning a fixed JSON classification; counts calls; ``fail`` raises LLMError."""

    def __init__(self, out=None, fail=False, model="stub"):
        self.model = model
        self.out = out if out is not None else {"qtype": "what_to_say"}
        self.fail = fail
        self.prompts = []

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.prompts.append((prompt, format, temperature, seed))
        if self.fail:
            raise LLMError("down")
        return json.dumps(self.out)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    UI._SHARED.clear()
    monkeypatch.delenv("HOMELOOP_USER_CLASSIFIER", raising=False)
    yield
    UI._SHARED.clear()


def _env(tid, lang="en", llm=None, profile="ideal"):
    return EpisodeEnv(task_by_id(tid), profile, 0, lang, llm=llm)


# ── the ask API's meaning channel ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_meaning_through_env_call_is_structured_and_recorded(lang):
    env = _env(MILK, lang)
    r = env.call("ask", question={"en": "Fridge or kimchi fridge?", "ko": "냉장고요, 김치냉장고요?"}[lang], lang=lang,
                 meaning={"qtype": "which_place", "options": ["fridge", "kimchi fridge"]})
    assert r["ok"]
    c = env.calls[-1]
    assert c["intent"]["path"] == "structured" and c["intent"]["qtype"] == "which_place"
    assert c["args"]["meaning"]["qtype"] == "which_place"
    assert {"en": "kimchi fridge", "ko": "김치냉장고"}[lang] in r["data"]["answer"]
    assert "intent" not in r["data"] and "meaning" not in r["data"]       # planners never see the reading
    env.finish("give_up")
    assert env.record()["dialog_paths"] == {"structured": 1}


def test_free_text_rules_path_without_llm():
    env = _env(TELL)
    assert env.user_classifier is None
    env.call("ask", question="Where are you?", lang="en")
    env.call("ask", question=FREE_Q["en"], lang="en")
    assert [c["intent"]["path"] for c in env.calls] == ["rules", "rules"]
    assert env.calls[1]["reply_kind"] == "not_sure"


# ── the classifier chain ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lang,msg", [("en", "leaving in ten minutes"), ("ko", "출발")])
def test_llm_only_when_rules_do_not_understand(lang, msg):
    stub = StubLLM({"qtype": "what_to_say", "person": "husband"})
    env = _env(TELL, lang, llm=stub)
    assert isinstance(env.user_classifier, UI.IntentClassifier)
    env.call("ask", question={"en": "Where are you?", "ko": "지금 어디 계세요?"}[lang], lang=lang)
    assert stub.prompts == [] and env.calls[-1]["intent"]["path"] == "rules"
    r = env.call("ask", question=FREE_Q[lang], lang=lang)
    assert len(stub.prompts) == 1 and env.calls[-1]["intent"] == {"path": "llm", "qtype": "what_to_say",
                                                                  "rule": "goal_message"}
    assert msg in r["data"]["answer"]
    assert env.llm_calls == 0                    # the simulator's calls are not the planner's


def test_classifier_is_deterministic_json_temperature_zero():
    stub = StubLLM()
    clf = UI.IntentClassifier(stub)
    clf("What should I tell him?", "en")
    clf("What should I tell him?", "en")
    assert len(stub.prompts) == 1
    p, fmt, temp, seed = stub.prompts[0]
    assert fmt == "json" and temp == 0.0 and seed == 0
    assert p == UI.prompt("What should I tell him?", "en")
    for q in UI.QTYPES:
        assert f"- {q}:" in p


@pytest.mark.parametrize("raw,out", [
    ('{"qtype": "where_is", "obj": "remote"}', {"qtype": "where_is", "obj": "remote"}),
    ('```json\n{"qtype": "which_place", "options": ["sink", "counter"], "junk": 1}\n```',
     {"qtype": "which_place", "options": ["sink", "counter"]}),
    ('{"qtype": "where_is"}', None),             # a required slot missing
    ('{"qtype": "teleport"}', None),
    ("no json here", None),
])
def test_classifier_output_is_cleaned(raw, out):
    class Raw(StubLLM):
        def chat(self, prompt, format=None, temperature=0.0, seed=0):
            return raw
    assert UI.IntentClassifier(Raw())("q", "en") == out


def test_classifications_are_cached_per_run(tmp_path):
    stub = StubLLM({"qtype": "what_to_say"})
    run_llm = CachedLLM(stub, tmp_path / "llm_cache" / "stub.jsonl")
    env = _env(TELL, "en", llm=run_llm)
    env.call("ask", question=FREE_Q["en"], lang="en")
    path = tmp_path / "llm_cache" / UI.CACHE_NAME
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["sha"] == cache_key("stub", UI.prompt(FREE_Q["en"], "en"), "json", 0.0, 0)
    first = env.calls[-1]["answer"]
    # a rerun with the server down is served from the cache: the same episode
    UI._SHARED.clear()
    down = CachedLLM(StubLLM(fail=True), tmp_path / "llm_cache" / "stub.jsonl")
    env2 = _env(TELL, "en", llm=down)
    env2.call("ask", question=FREE_Q["en"], lang="en")
    assert env2.calls[-1]["answer"] == first and env2.calls[-1]["intent"]["path"] == "llm"


def test_rules_only_for_no_llm_fake_or_flag(monkeypatch):
    assert UI.make_classifier(None) is None
    assert UI.make_classifier(FakeLLM()) is None
    assert UI.make_classifier(CountingLLM(FakeLLM())) is None
    assert UI.classifier_kind(None) == "rules" and UI.classifier_kind("fake") == "rules"
    assert UI.classifier_kind("http://127.0.0.1:1") == "llm"
    monkeypatch.setenv("HOMELOOP_USER_CLASSIFIER", "rules")
    assert UI.make_classifier(StubLLM()) is None and UI.classifier_kind("http://127.0.0.1:1") == "rules"


def test_classifier_server_failure_is_not_a_result():
    env = _env(TELL, "en", llm=StubLLM(fail=True))
    env.call("ask", question=FREE_Q["en"], lang="en")
    env.finish("give_up")
    with pytest.raises(LLMError):
        env.record()


# ── planners that declare a meaning ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_oracle_gold_question_is_structured(lang):
    from homeloop_bench.runner import run_episode
    e = run_episode(task_by_id(MILK), "oracle", "ideal", 0, lang, None)
    asks = [c for c in e["calls"] if c["skill"] == "ask"]
    assert asks and asks[0]["args"]["meaning"]["qtype"] == "which_place"
    assert asks[0]["intent"]["path"] == "structured" and e["success"]
    assert e["dialog_paths"] == {"structured": len(asks)}


def test_planner_qtype_declarations():
    from homeloop_bench.planners.knowno_like import KnowNoLike
    from homeloop_bench.planners.naive import NaivePlanner
    from homeloop_bench.planners.oracle import OraclePlanner
    from homeloop_robot.intent import QTYPES
    for cls in (OraclePlanner, NaivePlanner, KnowNoLike):
        assert set(cls.qtypes) <= set(QTYPES)
    assert "help" in OraclePlanner.qtypes and NaivePlanner.qtypes == ()


def test_knowno_meaning_object_and_place():
    from homeloop_bench.planners.knowno_like import meaning
    env = _env(MILK, "ko")
    obs = env.observe()
    m = meaning(["in(milk_1, fridge@kitchen)", "in(milk_1, kimchi_fridge@kitchen)"], obs)
    assert m["qtype"] == "which_place" and m["options"] == ["냉장고", "김치냉장고"]
    m = meaning(["on(mug_1, counter@kitchen)", "on(mug_2, counter@kitchen)"], obs)
    assert m["qtype"] == "which_object" and len(m["options"]) == 2


def test_oracle_help_request_is_structured():
    from homeloop_robot.oracle import HELP_QUESTION, recovery_call
    env = _env(TELL)
    c = recovery_call("blocked", "move", env._world, env.user, 0.0, "en")
    assert c.skill == "ask" and c.args["meaning"] == {"qtype": "help"} and c.args["question"] == HELP_QUESTION["en"]


# ── robot_agent: SAGE's template questions carry their qtype ───────────────────────────────────────────
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_sage_template_questions_are_structured(lang, monkeypatch):
    """SAGE's template questions carry their meaning; in a Korean episode the user hears the Korean translation
    (a fake one here, robot_agent's _in_lang through the fake LLM), and the meaning counts only when that Korean
    reads the same way. A question robot_agent did not translate (the English went out as is) is not followed:
    structured_mismatch (homeloop_robot docs/user_model.md "Heard-text check")."""
    pytest.importorskip("robot_agent")
    from homeloop_bench.runner import run_episode
    if lang == "ko":
        import ko_fake_translation
        ko_fake_translation.install(monkeypatch)
    seen = []
    for tid in ("hl-dev-000003", "hl-dev-000013", "hl-dev-000015", "hl-dev-000001", "hl-dev-000002"):
        # SAGE-v2: "Where are you?" is asked only when the ENV does not track people (robot_agent:sage_ask)
        for pl in ("robot_agent:sage", "robot_agent:sage_ask"):
            e = run_episode(task_by_id(tid), pl, "real", 0, lang, "fake")
            seen += [c for c in e["calls"] if c["skill"] == "ask" and c.get("intent")]
    structured = [c for c in seen if c["intent"]["path"] == "structured"]
    assert structured, "no SAGE template question was structured"
    for c in structured:
        m = c["args"]["meaning"]
        assert m["qtype"] == c["intent"]["qtype"] and m["template"]
        if lang == "ko":                     # the user heard Korean
            assert intent.in_lang(c["args"]["question"], "ko"), c["args"]["question"]
    for c in seen:
        if not intent.in_lang(c["args"]["question"], lang):
            assert c["intent"]["path"] in ("structured_mismatch", "rules") and c["intent"]["rule"] == "not_in_lang"
    if lang == "ko":
        assert any(c["intent"]["path"] == "structured" and c["args"]["meaning"]["qtype"] == "where_are_you"
                   for c in seen)
        # untranslated English templates in this run ("You mentioned the 남편. What should I do there?")
        untr = [c for c in seen if "meaning" in c["args"] and not intent.in_lang(c["args"]["question"], "ko")]
        assert untr and all(c["intent"]["path"] == "structured_mismatch" for c in untr)
    # the adapter can be turned off: the same questions are then free text
    monkeypatch.setenv("HOMELOOP_RA_STRUCTURED", "0")
    e = run_episode(task_by_id("hl-dev-000003"), "robot_agent:sage", "real", 0, lang, "fake")
    assert all("meaning" not in c["args"] for c in e["calls"] if c["skill"] == "ask")


def test_summary_has_classifier_flag_and_path_shares(tmp_path):
    from homeloop_bench.runner import run_many
    s = run_many("oracle", "dev", 6, "real", 1, "en", None, tmp_path / "o")
    assert s["config"]["user_classifier"] == "rules"
    assert set(s["dialog_paths"]) >= {"n"}


def test_interpret_cli(tmp_path):
    q = tmp_path / "q.jsonl"
    q.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"qid": "a", "lang": "en", "question": "Where are you?", "task_id": TELL},
        {"qid": "b", "lang": "ko", "question": "냉장고요, 김치냉장고요?", "task_id": MILK},
        {"qid": "c", "lang": "en", "question": "Hm?", "task_id": "nope"}]) + "\n", encoding="utf-8")
    out = tmp_path / "o.jsonl"
    assert UI.main(["interpret", "--questions", str(q), "--out", str(out)]) == 0
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["qtype"] == "where_are_you" and rows[0]["path"] == "rules"
    assert rows[1]["qtype"] == "which_place"
    assert rows[2]["error"] == "unknown task"
