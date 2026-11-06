"""homeloop-bench understand-eval (docs/understand_eval.md): the common form and the metrics on synthetic cases, and
the probe through the real construction path (the robot_agent planner's episode setup, the real AssistLoop up to its
understand event) with a scripted language-model backend. Skipped when robot_agent is not importable."""

import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks, write_jsonl  # noqa: E402
from homeloop_bench import understand_eval as ue  # noqa: E402
from homeloop_bench.cli import main  # noqa: E402
from homeloop_bench.env import EpisodeEnv  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


def ctx_of(tid):
    return ue.Context(EpisodeEnv(TASKS[tid], "ideal", 0, "en").world0)


def A(kind, cls="", color="", dest="", person=""):
    return ue.Atom(kind, cls, color, dest, person)


# ── the common form ─────────────────────────────────────────────────────────────────────────────────────────
def test_gold_atoms_of_fixture_tasks():
    w = EpisodeEnv(TASKS["fx-feas-002"], "ideal", 0, "en").world0
    assert [a.text() for a in ue.gold_atoms(TASKS["fx-feas-002"], w)] == [
        "put_on(blue shirt, desk_chair@study)", "open(wardrobe@master)"]
    w = EpisodeEnv(TASKS["fx-feas-001"], "ideal", 0, "en").world0
    assert [a.text() for a in ue.gold_atoms(TASKS["fx-feas-001"], w)] == [
        "go(counter@kitchen)", "give(black knife, partner_a)"]
    w = EpisodeEnv(TASKS["fx-ref-000"], "ideal", 0, "en").world0
    assert ue.gold_atoms(TASKS["fx-ref-000"], w) == []                     # unmoved is not a goal; expectation is refuse
    assert ue.expectation(TASKS["fx-ref-000"], w) == "refuse"
    assert ue.expectation(TASKS["fx-clar-000"], w) == "ask"
    w = EpisodeEnv(TASKS["fx-cmp-001"], "ideal", 0, "en").world0           # a mixed task: the refused part is no gold goal
    assert [a.text() for a in ue.gold_atoms(TASKS["fx-cmp-001"], w)] == ["put_on(white milk, counter@kitchen)"]


def test_object_class_rules_R7():
    c = ctx_of("fx-feas-010")
    assert c.object_class("blue mug") == ("mug", "blue") and c.object_class("the mug") == ("mug", "")
    assert c.object_class("머그컵") == ("mug", "") or c.object_class("머그컵")[0].startswith("?")   # ko name if the class has it
    assert c.object_class("flux capacitor")[0] == "?flux capacitor"


def test_equivalent_forms_are_equal():
    c = ctx_of("fx-feas-003")                                              # the user is "resident" here
    user = c.user
    pairs = [
        # R2: a put on a person (the speaker's entry, "me", the person's key) and a deliver are one "give"
        (A("give", "detergent", "blue", person=user), ue.robot_atom({"type": "on", "object": "blue detergent", "to": "me"}, c)),
        (A("give", "detergent", "blue", person=user), ue.robot_atom({"type": "deliver", "object": "detergent", "to": "user"}, c)),
        # R7: the colour the person did not say is not wrong; R1: article and plural-free names
        (A("put_on", "mug", "blue", "desk@study"), A("put_on", "mug", "", "desk@study")),
        # R6
        (A("open", dest="fridge@kitchen"), ue.robot_atom({"type": "open", "object": "fridge@kitchen"}, c)),
    ]
    for gold, pred in pairs:
        assert pred is not None and ue.compatible(gold, pred, c), (gold, pred)


def test_different_forms_are_not_equal():
    c = ctx_of("fx-feas-003")
    bad = [
        (A("put_on", "mug", "blue", "desk@study"), A("put_in", "mug", "blue", "desk@study")),      # on is not in
        (A("put_on", "mug", "blue", "desk@study"), A("put_on", "mug", "red", "desk@study")),       # another colour
        (A("put_on", "mug", "", "desk@study"), A("put_on", "cup", "", "desk@study")),               # another class
        (A("put_on", "mug", "", "desk@study"), A("put_on", "mug", "", "desk_chair@study")),         # another place
        (A("give", "mug", "", person="grandma"), A("give", "mug", "", person="grandpa")),           # another person
        (A("say", person="grandma"), A("say", person="grandpa")),
        (A("open", dest="fridge@kitchen"), A("close", dest="fridge@kitchen")),
    ]
    for gold, pred in bad:
        assert not ue.compatible(gold, pred, c), (gold, pred)


def test_go_rules_R4_R5():
    c = ctx_of("fx-feas-000")                                              # care_home_suite: rooms sitting, bedroom, ...
    room = A("go", dest=("bed@bedroom", "dresser@bedroom"))
    assert ue.compatible(room, A("go", dest="dresser@bedroom"), c)                          # any one place of the room
    assert ue.compatible(room, A("go", dest="@bedroom"), c)                                 # the room itself
    assert not ue.compatible(room, A("go", dest="table@kitchenette"), c)
    assert not ue.compatible(A("go", dest=("dresser@bedroom",)), A("go", dest="bed@bedroom"), c)   # one named place: that place
    assert ue.compatible(A("go", dest=(c.dock,)), ue.robot_atom({"type": "go", "to": c.dock}, c), c)


def test_say_checks_the_person_not_the_words_R3():
    c = ctx_of("fx-feas-004")
    p = ue.robot_atom({"type": "say", "object": "Please drink water", "to": "grandma"}, c)
    assert p.person and ue.compatible(A("say", person=p.person), p, c)
    assert ue.robot_atom({"type": "say", "object": "hi", "to": "nobody"}, c).person.startswith("?")


def test_match_counts_dropped_spurious_and_duplicates():
    c = ctx_of("fx-feas-003")
    gold = [A("put_on", "mug", "", "a@x"), A("open", dest="b@x")]
    pred = [A("put_on", "mug", "", "a@x"), A("put_on", "mug", "", "a@x"), A("go", dest="c@x")]
    pairs, dropped, spurious = ue.match(gold, pred, c)
    assert len(pairs) == 1 and dropped == [gold[1]]
    assert spurious == [pred[1], pred[2]]                                  # a repeated atom is spurious


# ── metrics ─────────────────────────────────────────────────────────────────────────────────────────────────
def row(**kw):
    base = {"gold": [], "pred": [], "matched": 0, "dropped": [], "spurious": [], "exact": False, "status": "clear",
            "asked": False, "refused": False, "confident": False, "confident_wrong": False, "lang": "en", "text": "clean",
            "structure": "single", "expect": "act", "mixed": False}
    return {**base, **kw}


def test_stats_and_summary_on_synthetic_records():
    rows = [
        row(gold=["a", "b"], pred=["a", "b"], matched=2, exact=True, confident=True),
        row(gold=["a", "b"], pred=["a", "x"], matched=1, dropped=["b"], spurious=["x"], confident=True, structure="sequence"),
        row(gold=["a"], pred=[], dropped=["a"], status="ambiguous", asked=True),
        row(gold=["a"], pred=["a"], matched=1, exact=True, confident=True, lang="ko", text="asr"),
        row(expect="ask", gold=["a"], pred=["a"], matched=1, exact=True, confident=True),       # clarify task: not in the headline
        row(expect="act", mixed=True, gold=["a"], pred=["a", "z"], matched=1, spurious=["z"], confident=True),
    ]
    s = ue.summarize(rows, {})
    h = s["headline"]
    assert h["n"] == 4 and h["exact"] == 2 and h["exact_rate"] == 0.5
    assert (h["gold_atoms"], h["pred_atoms"], h["matched_atoms"]) == (6, 5, 4)
    assert h["atom_precision"] == 0.8 and h["atom_recall"] == round(4 / 6, 6)
    assert (h["dropped_atoms"], h["spurious_atoms"]) == (2, 1)
    assert h["n_confident"] == 3 and h["confident_wrong"] == 1 and h["confident_wrong_of_confident"] == round(1 / 3, 6)
    assert h["confident_wrong_rate"] == 0.25 and h["asked"] == 1
    assert s["by_lang"]["ko"]["n"] == 1 and s["by_lang"]["en"]["n"] == 3
    assert s["by_structure"]["sequence"]["exact"] == 0 and s["by_text"]["asr"]["n"] == 1
    assert s["by_expect"]["ask"]["n"] == 1 and s["mixed"]["n"] == 1
    assert "| headline |" in ue.report(s)


# ── the probe through the real construction path, scripted backend ──────────────────────────────────────────
class Scripted:
    """The language model: answers the understand prompt of a task by the task's sentence found in the prompt."""
    model = "scripted"

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.calls.append(prompt)
        for text, ans in self.answers.items():
            if text in prompt:
                return json.dumps(ans)
        raise AssertionError(f"no scripted answer for {prompt[:200]!r}")

    def chat_messages(self, messages, temperature=0.0, seed=0, format=None):
        return self.chat(messages[-1]["content"], format, temperature, seed)


def G(t, o="", to=""):
    return {"type": t, "object": o, "from": "", "to": to}


def ans(*goals, status="clear", question=""):
    return {"status": status, "reason": "", "question": question, "goals": list(goals)}


ANSWERS = {
    TASKS["fx-feas-010"]["text"]["en"]: ans(G("on", "blue mug", "kitchen_sink@kitchen")),                      # right
    TASKS["fx-feas-003"]["text"]["en"]: ans(G("on", "blue detergent", "me")),                                    # right, given to the speaker
    TASKS["fx-feas-002"]["text"]["en"]: ans(G("on", "blue shirt", "desk_chair@study")),                          # drops the open
    TASKS["fx-feas-000"]["text"]["en"]: ans(G("in", "white phone", "dresser@bedroom"), G("on", "white phone", "bed@bedroom")),  # a spurious second put
    TASKS["fx-clar-000"]["text"]["en"]: ans(status="ambiguous", question="Which mug do you mean?"),
    TASKS["fx-ref-000"]["text"]["en"]: ans(status="unsafe"),
}
IDS = ["fx-feas-010", "fx-feas-003", "fx-feas-002", "fx-feas-000", "fx-clar-000", "fx-ref-000"]


def run(tmp_path, name="a", llm=None, **kw):
    llm = llm or Scripted(ANSWERS)
    s = ue.run_eval([TASKS[i] for i in IDS], "robot_agent:sage", "ideal", 0, ["en"], ["clean"], None, tmp_path / name, llm=llm, **kw)
    recs = {r["task_id"]: r for r in map(json.loads, (tmp_path / name / "records.jsonl").read_text().splitlines())}
    return s, recs, llm


def test_probe_through_the_real_loop_with_a_scripted_backend(tmp_path):
    s, recs, llm = run(tmp_path)
    assert len(llm.calls) == len(IDS)                                      # one understand call per task, nothing else
    assert recs["fx-feas-010"]["exact"] and recs["fx-feas-010"]["confident"] and not recs["fx-feas-010"]["confident_wrong"]
    assert recs["fx-feas-003"]["exact"], recs["fx-feas-003"]               # "me" grounded to the speaker = give to the user
    r = recs["fx-feas-002"]
    assert r["dropped"] == ["open(wardrobe@master)"] and not r["spurious"] and r["confident_wrong"]
    r = recs["fx-feas-000"]
    assert r["spurious"] and r["spurious"][0].startswith("put_on(") and not r["dropped"] and r["confident_wrong"]
    r = recs["fx-clar-000"]
    assert r["asked"] and not r["confident"] and r["expect"] == "ask" and r["status"] == "ambiguous"
    r = recs["fx-ref-000"]
    assert r["refused"] and r["expect"] == "refuse" and not r["confident"]
    h = s["headline"]
    assert h["n"] == 4 and h["exact"] == 2 and h["dropped_atoms"] == 1 and h["spurious_atoms"] == 1
    assert h["n_confident"] == 4 and h["confident_wrong"] == 2
    assert s["by_expect"]["ask"]["asked"] == 1 and s["by_expect"]["refuse"]["refused"] == 1
    assert (tmp_path / "a" / "summary.json").exists() and (tmp_path / "a" / "report.md").exists()


def test_the_probe_never_plans_or_moves(tmp_path):
    """The run stops at the understand event: the robot made no skill call and the planner was never built."""
    from homeloop_bench.planners import make_planner
    env = EpisodeEnv(TASKS["fx-feas-010"], "ideal", 0, "en", llm=Scripted(ANSWERS))
    p = make_planner("robot_agent:sage", llm=env.llm())
    p.until = ue.STOP_EVENTS
    p.run(env)
    assert p.reached["event"] == "understand" and env.calls == []


def test_clean_and_asr_text_conditions(tmp_path):
    """asr = the text the robot hears after the profile's speech recognition; clean = the task's own words."""
    from homeloop_robot import load_profile  # noqa: F401
    out = {}
    for mode in ("clean", "asr"):
        r = ue.probe(TASKS["fx-feas-010"], "robot_agent:sage", "real", 3, "en", mode, Scripted({"": ans(G("on", "blue mug", "kitchen_sink@kitchen"))}))
        out[mode] = r
    env = EpisodeEnv(TASKS["fx-feas-010"], "real", 3, "en")
    assert out["clean"]["heard_text"] == TASKS["fx-feas-010"]["text"]["en"]
    assert out["asr"]["heard_text"] == env.task_text and out["asr"]["heard_event"] == env.instruction_event


def test_llm_calls_are_cached_in_the_run_dir(tmp_path, monkeypatch):
    from homeloop_bench import llm as L
    seen = []

    def fake_chat(self, messages, temperature=0.0, seed=0, format=None, prompt=""):
        seen.append(1)
        return Scripted(ANSWERS).chat(prompt or messages[-1]["content"])
    monkeypatch.setattr(L.OllamaHTTP, "chat_messages", fake_chat)
    for name in ("one", "two"):
        ue.run_eval([TASKS["fx-feas-010"], TASKS["fx-feas-002"]], "robot_agent:sage", "ideal", 0, ["en"], ["clean"],
                    "http://127.0.0.1:9", tmp_path / "cache_run", model="m")
    assert len(seen) == 2                                                  # the second run was served from OUT/llm_cache
    assert list((tmp_path / "cache_run" / "llm_cache").glob("*.jsonl"))


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_cli_with_fake_llm_and_window(tmp_path):
    f = write_jsonl(tmp_path / "t.jsonl", fixture_tasks())
    out = tmp_path / "o"
    assert main(["understand-eval", "--tasks", f, "--offset", "2", "--limit", "3", "--lang", "en,ko", "--text", "both",
                 "--profile", "ideal", "--llm", "fake", "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text())
    assert s["n_records"] == 3 * 2 * 2 and s["config"]["offset"] == 2 and s["config"]["limit"] == 3
    # the fake model answers with the gold goals, so a task with a plain reading is exact in both languages
    assert s["headline"]["exact_rate"] >= 0.8


def test_cli_refuses_test_split_and_unknown_planner(tmp_path):
    assert main(["understand-eval", "--split", "test", "--llm", "fake", "--out", str(tmp_path / "x")]) == 2
    assert main(["understand-eval", "--planner", "nope", "--llm", "fake", "--out", str(tmp_path / "x")]) == 2
    t = dict(TASKS["fx-feas-010"], split="test")
    f = write_jsonl(tmp_path / "t.jsonl", [t])
    assert main(["understand-eval", "--tasks", f, "--llm", "fake", "--out", str(tmp_path / "x")]) == 2
    assert main(["understand-eval", "--planner", "oracle", "--llm", "fake", "--out", str(tmp_path / "x")]) == 2


# ── metric fixes M1 (a colour-word class) and M2 (class id, head noun, plural) ──────────────────────────────
def test_M1_a_name_of_colour_words_only_is_the_class_when_a_class_has_that_name():
    c = ctx_of("fx-feas-010")
    assert c.object_class("orange") == ("orange", "")                      # the fruit, no colour said
    assert c.object_class("an orange") == ("orange", "")
    assert c.object_class("orange orange") == ("orange", "orange")         # as before: colour and class
    assert c.object_class("red") == ("", "red")                            # a colour with no class of that name: as before
    assert c.object_class("orange mug") == ("mug", "orange")


def test_M2_class_id_head_noun_and_plural_are_names():
    c = ctx_of("fx-feas-010")
    assert c.object_class("snack") == ("snack", "") and c.object_class("snacks") == ("snack", "")     # the class id; plural
    assert c.object_class("snack bag") == ("snack", "") and c.object_class("soup") == ("canned_soup", "")   # head noun
    assert c.object_class("canned soup") == ("canned_soup", "")                                      # the class id with a space
    assert c.object_class("mug") == ("mug", "")                                                      # a full name still wins
    assert c.object_class("flux capacitor")[0] == "?flux capacitor"                                  # unknown: still unknown
    # a head noun two classes share is not a name
    from homeloop_robot.catalog import CLASSES, class_names
    heads: dict = {}
    for cid in CLASSES:
        for n in class_names(cid, "en"):
            if len(n.split()) > 1:
                heads.setdefault(n.split()[-1].lower(), set()).add(cid)
    for h, cids in heads.items():
        if len(cids) > 1 and h not in c.classes.keys() - {h}:
            assert c.classes.get(h) is None or c.classes[h] in cids


def test_the_fixes_only_add_matches():
    c = ctx_of("fx-feas-010")
    idx_names = ue._class_index(None)
    for name, cid in idx_names.items():
        if cid:
            assert c.object_class(name)[0] == cid


# ── an understand model: counted apart, runaway falls back, records and summary say so ──────────────────────
class Seq:
    """The language model as a list of answers, in call order (the understand call first)."""
    model = "scripted"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def chat(self, prompt, format=None, temperature=0.0, seed=0, num_predict=None):
        self.calls.append(prompt)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return a if isinstance(a, str) else json.dumps(a)

    def chat_messages(self, messages, temperature=0.0, seed=0, format=None):
        return self.chat(messages[-1]["content"], format, temperature, seed)


GOOD = ans(G("on", "blue mug", "kitchen_sink@kitchen"))


def test_understand_calls_are_counted_apart_from_translation(tmp_path):
    llm = Seq(GOOD)
    r = ue.probe(TASKS["fx-feas-010"], "robot_agent:sage_um", "ideal", 0, "en", "clean", llm)
    assert r["llm_calls_understand"] == 1 and r["llm_calls"] == 1 and r["exact"]
    assert r["understand_model_used"] == "qwen3-vl:30b-a3b-instruct" and r["fallback"] is None
    plain = ue.probe(TASKS["fx-feas-010"], "robot_agent:sage_ground2", "ideal", 0, "en", "clean", Seq(GOOD))
    assert "llm_calls_understand" not in plain and "fallback" not in plain          # other variants: the records are as they were


def test_understand_model_equal_to_the_translator_is_still_understanding(tmp_path):
    """The translator's model is the 30B model too; the ROLE routes the call, so it is not counted as translation."""
    from homeloop_bench.planners.robot_agent_adapter import manifest_planner
    assert manifest_planner().get("translate_model") == "qwen3-vl:30b-a3b-instruct"
    env_probe = {}
    import homeloop_bench.planners.robot_agent_adapter as ad
    orig = ad.UnderstandCounter.chat

    def spy(self, *a, **k):
        env_probe["model"] = self.model
        return orig(self, *a, **k)
    ad.UnderstandCounter.chat = spy
    try:
        r = ue.probe(TASKS["fx-feas-010"], "robot_agent:sage_um", "ideal", 0, "en", "clean", Seq(GOOD))
    finally:
        ad.UnderstandCounter.chat = orig
    assert env_probe["model"] == "qwen3-vl:30b-a3b-instruct" and r["llm_calls_understand"] == 1


def test_a_runaway_falls_back_and_is_counted(tmp_path):
    llm = Seq("{" + "x" * 5000, GOOD)                    # the understand model runs away; the planner's one call is right
    r = ue.probe(TASKS["fx-feas-010"], "robot_agent:sage_um", "ideal", 0, "en", "clean", llm)
    assert r["fallback"] == "non_json" and r["understand_model_used"] == "scripted" and r["exact"]
    assert r["llm_calls_understand"] == 1 and r["llm_calls"] == 2 and len(llm.calls) == 2
    assert not any(c.startswith("Your previous answer") for c in llm.calls)       # no quoting repair
    s = ue.summarize([r], {})
    assert s["understand"]["fallbacks"] == 1 and s["understand"]["runaway"] == 1
    assert s["understand"]["fallbacks_by_reason"] == {"non_json": 1} and s["understand"]["ended"] == 0


def test_understand_model_flag_on_a_plain_variant(tmp_path):
    out = tmp_path / "f"
    s = ue.run_eval([TASKS["fx-feas-010"]], "robot_agent:sage_ground2", "ideal", 0, ["en"], ["clean"], None, out,
                    llm=Seq(GOOD), understand_model="some-other-model")
    rec = json.loads((out / "records.jsonl").read_text().splitlines()[0])
    assert rec["understand_model_used"] == "some-other-model" and s["config"]["understand_model"] == "some-other-model"
    assert s["understand"]["model_used"] == {"some-other-model": 1}


def test_cli_understand_model_flag(tmp_path):
    f = write_jsonl(tmp_path / "t.jsonl", fixture_tasks())
    out = tmp_path / "o"
    assert main(["understand-eval", "--tasks", f, "--limit", "2", "--lang", "en", "--text", "clean", "--profile", "ideal",
                 "--llm", "fake", "--understand-model", "other:1", "--out", str(out)]) == 0
    s = json.loads((out / "summary.json").read_text())
    assert s["config"]["understand_model"] == "other:1" and s["understand"]["n"] == 2


def test_the_new_variants_are_registered_and_say_what_they_set():
    from homeloop_bench.planners import REGISTRY, planner_class
    for n in ("sage_um", "sage_um_ko", "sage_um_strict", "sage_um_give", "sage_um_verdict", "sage_m1", "sage_m2"):
        assert f"robot_agent:{n}" in REGISTRY
    cfg = planner_class("robot_agent:sage_um").run_config()
    assert cfg["understand_model"] == "qwen3-vl:30b-a3b-instruct" and cfg["manifest_overlay"]["planner"]["understand_max_tokens"] == 512
    assert planner_class("robot_agent:sage_um_ko").run_config()["understand_model_lang"] == {"ko": "qwen3-vl:30b-a3b-instruct"}
    assert planner_class("robot_agent:sage_um_strict").run_config()["understand_schema_strict"] == 1
    assert planner_class("robot_agent:sage_m2").run_config()["understand_verify_verdict"] == 1
    assert "understand_model" not in planner_class("robot_agent:sage_ground2").run_config()
