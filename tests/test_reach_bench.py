"""Round 2 delivery on the bench side (docs/tasks.md "Delivery", docs/metrics.md): the judge's success and failure
cases, false successes, the person moving away, oracle / naive never reading the mode label, the observation, the
task data and the deterministic rewrite (gen/delivery.py)."""

import copy
import json

import pytest

from fixtures import base
from homeloop_bench.env import EpisodeEnv
from homeloop_bench.gen import delivery as D
from homeloop_bench.metrics import summarize
from homeloop_bench.runner import run_episode
from homeloop_bench.tasks import read_records
from homeloop_robot import reach
from homeloop_robot.world import from_house

H, SS = "senior_flat", 0           # grandma (the user) in the armchair; the side table is within her reach


def dl(obj, person, mode, reason=None):
    return {"pred": "delivered", "args": [obj, person], "mode": mode, "mode_reason": reason}


def task(mode, reason=None, text=None, tid="r2-000"):
    g = {"all": [dl("mug_1", "grandma", mode, reason)]}
    t = base(tid, H, SS, g, capability="fetch")
    t["subtasks"] = [{"kind": "feasible", "capability": "fetch", "ambiguity": "none", "goal": copy.deepcopy(g)}]
    t["n_subtasks"], t["structure"] = 1, "single"
    if text is not None:
        t["text"] = text
    return t


def fetch(env):
    for skill, args in (("move", {"target": "counter@kitchen"}), ("find", {"obj": "mug_1"}),
                        ("pick", {"obj": "mug_1"})):
        assert env.call(skill, **args)["ok"], (skill, env.last)


def drop_at(mode, place, claim="done", reason=None):
    env = EpisodeEnv(task(mode, reason), "ideal", 0, "en", privileged=True)
    fetch(env)
    assert env.call("move", target=place)["ok"]
    assert env.call("place", target=place)["ok"]
    env.finish(claim)
    return env, env.record()


def test_the_scene_matches_the_cases():
    w = from_house(H, SS)
    assert w.people["grandma"].seat == "armchair@living"
    assert reach.place_reachable(w, "side_table@living", "grandma")
    assert reach.is_support(w.place("coffee_table@living")) and not reach.place_reachable(w, "coffee_table@living",
                                                                                         "grandma")


# ── judge: success cases ──────────────────────────────────────────────────────────────────────────────────

def test_reach_on_a_reachable_support_surface_succeeds():
    _, rec = drop_at("reach", "side_table@living")
    assert rec["success"] and not rec["false_success"]
    assert rec["delivery"] == "reach" and rec["delivery_atoms"][0]["ok"]


@pytest.mark.parametrize("mode,reason", [("reach", None), ("hand", "explicit"), ("hand", "no_surface")])
def test_handover_satisfies_both_modes(mode, reason):
    env = EpisodeEnv(task(mode, reason), "ideal", 0, "en", privileged=True)
    fetch(env)
    assert env.call("move", target="grandma")["ok"] and env.call("handover", person="grandma")["ok"]
    env.finish("done")
    rec = env.record()
    assert rec["success"] and rec["delivery_atoms"][0]["mode"] == mode


# ── judge: failure cases ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("place,why", [("armchair@living", "a seat"), ("floor@living", "the floor"),
                                       ("coffee_table@living", "a support surface out of reach")])
def test_reach_fails_on_seat_floor_and_out_of_reach(place, why):
    _, rec = drop_at("reach", place)
    assert not rec["success"], why
    assert rec["false_success"], "claiming done when it is not done is a false success"


def test_hand_mode_needs_the_handover():
    _, rec = drop_at("hand", "side_table@living", reason="explicit")
    assert not rec["success"] and rec["false_success"] and rec["delivery"] == "hand"


def test_not_claimed_is_not_a_success():
    _, rec = drop_at("reach", "side_table@living", claim="give_up")
    assert not rec["success"] and not rec["false_success"]


def test_judged_where_the_person_is_at_the_end():
    env, rec = drop_at("reach", "side_table@living")
    assert rec["success"]
    # she gets up and goes to bed afterwards: the mug on the side table is no longer within her reach
    env._world.people_now = {"grandma": {"pos": tuple(env._world.place("bed@bedroom").person_pos), "moving": False}}
    assert not env.judge("done")["success"]


# ── planners infer the mode, never read it ─────────────────────────────────────────────────────────────

def _calls(rec):
    return [(c["skill"], json.dumps(c["args"], sort_keys=True)) for c in rec["calls"]]


@pytest.mark.parametrize("planner", ["oracle", "naive"])
def test_oracle_and_naive_never_read_the_mode_label(planner):
    for text, want in (({"en": "Please bring me the red mug.", "ko": "빨간 머그컵 좀 가져다줄래요?"}, "place"),
                       ({"en": "Please bring me the red mug and put it in my hand.",
                         "ko": "빨간 머그컵 가져다 제 손에 쥐여 주세요."}, "handover")):
        recs = [run_episode(task(m, r, text), planner, "ideal", 0, "en", None)
                for m, r in (("reach", None), ("hand", "explicit"), ("hand", "user_needs"))]
        assert _calls(recs[0]) == _calls(recs[1]) == _calls(recs[2])
        assert want in [s for s, _ in _calls(recs[0])]


def test_oracle_follows_the_words_and_the_scene():
    plain = {"en": "Please bring me the red mug.", "ko": "빨간 머그컵 좀 가져다줄래요?"}
    rec = run_episode(task("reach", None, plain), "oracle", "ideal", 0, "en", None)
    assert rec["success"] and ("place", '{"target": "side_table@living"}') in _calls(rec)
    hand = {"en": "Bring me the red mug and put it in my hand, please.", "ko": "빨간 머그컵 가져다 제 손에 쥐여 주세요."}
    for lang in ("en", "ko"):
        rec = run_episode(task("hand", "explicit", hand), "oracle", "ideal", 0, lang, None)
        assert rec["success"] and "handover" in [s for s, _ in _calls(rec)]


# ── observation ─────────────────────────────────────────────────────────────────────────────────────────

def test_observation_shows_posture_and_nearby_furniture_not_the_mode():
    env = EpisodeEnv(task("hand", "explicit"), "ideal", 0, "en", privileged=False)
    obs = env.observe()
    v = {p["id"]: p for p in obs.people_now}["grandma"]
    assert v["posture"] == "seated" and v["place"] == "armchair@living" and not v["moving"]
    assert "side_table@living" in [n["place"] for n in v["nearby"]]
    assert not any("mode" in k for k in v)
    txt = obs.text()
    assert "People now (" in txt and "side_table@living table" in txt
    assert "explicit" not in txt and "delivered" not in txt and "reach]" not in txt
    with pytest.raises(PermissionError):
        env.goal


# ── data ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dev():
    return read_records("dev")


def test_data_has_no_held_by_and_valid_labels(dev):
    from homeloop_bench.gen.validate import delivery_problems
    assert delivery_problems(dev) == []
    n = sum(1 for r in dev for _, a in D.delivery_atoms(r))
    assert n > 300
    st = D.delivery_stats(dev)
    assert 0.10 <= st["hand_share"] <= 0.50 and set(st["by_mode"]) == {"reach", "hand"}


def test_explicit_wording_in_both_languages(dev):
    ex = [r for r in dev for _, a in D.delivery_atoms(r) if a.get("mode_reason") == "explicit"]
    assert ex
    for r in ex:
        assert reach.wording_wants_hand(r["text"]["en"], "en") and reach.wording_wants_hand(r["text"]["ko"], "ko")


def test_variants_only_touch_template_text(dev):
    for r in dev:
        v = (r["meta"].get("delivery") or {}).get("variant")
        if v in ("append", "append_named"):
            assert r["source_by_lang"] == {"en": "template", "ko": "template"}
            assert r["meta"].get("template_text") in (None, r["text"])
            assert r["text"]["en"].lower().count("please") <= 1
        elif v == "ko_verb":
            assert r["source_by_lang"]["ko"] == "template" and "건네" in r["text"]["ko"]


def test_rewrite_is_deterministic_and_idempotent(dev):
    sub = dev[:200]
    a, rep_a = D.rewrite_all(sub)
    b, _ = D.rewrite_all(copy.deepcopy(sub))
    assert a == b == sub
    assert rep_a["within_reach_at_start"] == []


def test_rewrite_of_an_old_record():
    t = task("hand")
    t["goal"] = {"all": [{"pred": "held_by", "args": ["mug_1", "grandma"]}]}
    t["subtasks"][0]["goal"] = copy.deepcopy(t["goal"])
    t["text"] = {"en": "Bring me the red mug.", "ko": "빨간 머그컵 가져다줄래요?"}
    t["source_by_lang"] = {"en": "llm_paraphrase", "ko": "llm_paraphrase"}     # LLM text: never changed
    r, info = D.rewrite(t)
    assert r["text"] == t["text"] and info["variant"] is None
    assert r["goal"]["all"] == [dl("mug_1", "grandma", "reach", None)]
    assert r["subtasks"][0]["goal"]["all"] == r["goal"]["all"]
    t["text"] = {"en": "Hand me the red mug.", "ko": "빨간 머그컵 건네주세요."}
    assert D.rewrite(t)[0]["goal"]["all"] == [dl("mug_1", "grandma", "hand", "explicit")]


def test_explicit_append_variant_for_template_text():
    hits = 0
    for i in range(40):
        t = task("hand", tid=f"r2-{i:03d}")
        t["goal"] = {"all": [{"pred": "held_by", "args": ["mug_1", "grandma"]}]}
        t["subtasks"][0]["goal"] = copy.deepcopy(t["goal"])
        t["text"] = {"en": "Could you bring me the red mug?", "ko": "빨간 머그컵 가져다줄래요?"}
        t["source_by_lang"] = {"en": "template", "ko": "template"}
        t["meta"] = {"template_text": dict(t["text"])}
        r, info = D.rewrite(t)
        if info["variant"] == "append":
            hits += 1
            assert r["text"]["en"].startswith("Could you bring me the red mug? ")
            assert r["goal"]["all"][0]["mode_reason"] == "explicit" and r["meta"]["template_text"] == r["text"]
        else:
            assert r["goal"]["all"][0]["mode"] == "reach"
    assert 0 < hits < 40


def test_within_reach_at_start_is_reseeded():
    ss, oid = next((s, o) for s in range(1, 500) for o in sorted(from_house(H, s).objects)
                   if reach.reachable(o, "grandma", from_house(H, s)))
    w = from_house(H, ss)
    t = base("r2-rs", H, ss, {"all": [{"pred": "held_by", "args": [oid, "grandma"]}]}, capability="fetch")
    t["subtasks"] = [{"kind": "feasible", "capability": "fetch", "ambiguity": "none", "goal": copy.deepcopy(t["goal"])}]
    t["n_subtasks"], t["structure"] = 1, "single"
    r, info = D.rewrite(t)
    assert info["reseed"]["from"] == ss and r["seed_state"] != ss
    w2 = from_house(H, r["seed_state"])
    assert not D.within_reach(r, w2)
    if info["reseed"]["pass"] == 1:
        assert w2.people["grandma"].seat == w.people["grandma"].seat


# ── metrics ─────────────────────────────────────────────────────────────────────────────────────────────

def test_summary_splits_by_delivery():
    eps = [drop_at("reach", "side_table@living")[1], drop_at("reach", "armchair@living")[1],
           drop_at("hand", "side_table@living", reason="no_surface")[1]]
    s = summarize(eps, {})
    assert s["by_delivery"]["reach"]["n"] == 2 and s["by_delivery"]["reach"]["success"] == 0.5
    assert s["by_delivery"]["hand"]["success"] == 0.0
    assert s["delivery_atoms"] == {"hand:no_surface": {"n": 1, "held": 0.0}, "reach:None": {"n": 2, "held": 0.5}}


HAND_NOUN_IDS = ("hl-train-000333", "hl-train-000613", "hl-train-001338", "hl-train-001561", "hl-train-003566",
                 "hl-dev-000336", "hl-dev-000670", "hl-test-001341", "hl-test-001534", "hl-test-001850",
                 "hl-test-002818", "hl-test-002906", "hl-test-003389", "hl-test-003663", "hl-test-003762",
                 "hl-test-004586", "hl-test-004619")


@pytest.fixture(scope="module")
def every():
    return {s: read_records(s) for s in ("train", "dev", "test")}


def test_hands_full_is_not_a_handover_request(every):
    """Review round 1: 'My hands are full' / 'I just washed my hands' made 17 tasks explicit-hand and put 건네
    into their Korean text. They are labelled from the scene again and keep their template Korean."""
    by_id = {r["id"]: r for rs in every.values() for r in rs}
    for i in HAND_NOUN_IDS:
        r = by_id[i]
        assert (r["meta"].get("delivery") or {}).get("variant") is None, i
        assert not reach.wording_wants_hand(r["text"]["en"], "en"), i
        assert "건네" not in r["text"]["ko"], i
        for _, a in D.delivery_atoms(r):
            assert a["mode_reason"] != "explicit", i


def test_no_surface_is_geometry_only(every):
    """no_surface = no support surface within reach at all; a full reachable surface stays a reach task."""
    from homeloop_robot.world import from_house
    n_reach_full = 0
    for r in every["dev"]:
        w = from_house(r["house"], r["seed_state"])
        for path, a in D.delivery_atoms(r):
            o, p = a["args"]
            if a["mode_reason"] == "no_surface":
                assert reach.reachable_surfaces(w, p) == [], r["id"]
            if a["mode"] == "reach" and not reach.reachable_surfaces(w, p, free_only=True):
                n_reach_full += 1
    assert n_reach_full > 0          # such tasks exist (e.g. a nightstand full of small things) and stay reach


def test_explicit_and_user_needs_in_every_split(every):
    """Per-split counts are comparable (gen/delivery.QUOTA_SHARE): explicit 5-12 % of the delivery atoms in every
    split, and user_needs present in every split."""
    for s, rs in every.items():
        st = D.delivery_stats(rs)
        n = st["delivered_atoms"]
        ex = st["by_mode_reason"].get("hand:explicit", 0)
        assert 0.05 <= ex / n <= 0.12, (s, ex, n)
        assert st["by_mode_reason"].get("hand:user_needs", 0) > 0, s


def test_named_variant_names_the_object(every):
    from homeloop_robot.world import from_house
    from homeloop_bench.gen.lexicon import Lex
    n = 0
    for r in every["dev"] + every["train"]:
        if (r["meta"].get("delivery") or {}).get("variant") != "append_named":
            continue
        n += 1
        assert r["source_by_lang"] == {"en": "template", "ko": "template"} and r["structure"] != "single"
        w = from_house(r["house"], r["seed_state"])
        (o, _p), = {tuple(a["args"]) for _, a in D.delivery_atoms(r)}
        last_en = r["text"]["en"].rsplit(".", 2)[-2] if r["text"]["en"].endswith(".") else r["text"]["en"]
        assert any(nm in last_en.lower() for nm in Lex(w).obj_names(o, "en")), r["id"]
        assert r["text"]["en"].lower().count(" hand") >= 1 and "손" in r["text"]["ko"]
    assert n > 0


def test_unneeded_handover_is_reported():
    """A handover satisfies reach (success), but the delivery_mode metric counts it as unneeded."""
    env = EpisodeEnv(task("reach"), "ideal", 0, "en", privileged=True)
    fetch(env)
    assert env.call("move", target="grandma")["ok"]
    assert env.call("handover", person="grandma")["ok"], env.last
    env.finish("done")
    ho = env.record()
    assert ho["success"] and ho["delivery_atoms"][0]["handed"] is True
    env2, put = drop_at("reach", "side_table@living")
    assert put["success"] and put["delivery_atoms"][0]["handed"] is False
    m = summarize([ho, put], {"planner": "t"})["delivery_mode"]
    assert m["reach_atoms_held"] == 2 and m["reach_atoms_handed_over"] == 1 and m["unneeded_handover_rate"] == 0.5
