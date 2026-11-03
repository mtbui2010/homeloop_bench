"""robot_agent:sage's seed pool (homeloop_robot planner/seed_memory.jsonl, R2-7b) does not leak the evaluation
tasks, and each example is a solved task: its plan reaches its goal on the mock robot in the example house.

* No example shares a family, gen_id or template id with a dev / test task; none names a dev / test id; the
  example house is used by no split and is not a homeloop_robot house.
* No EN / KO example text is a near duplicate of a dev / test text or template text: character-shingle Jaccard
  (gen/dedup.py, the validator's measure; near duplicate = 0.90) stays below 0.5 for every pair.
* robot_agent:sage and robot_agent:sage_norag are both listed and differ only in the seed pool; summary.json
  config records the variant and the pool's sha256.
"""
import json
import re
from pathlib import Path

import pytest

from homeloop_bench.gen.dedup import jaccard, shingles
from homeloop_bench.planners import REGISTRY, list_planners, planner_class
from homeloop_bench.planners import progprompt_examples as PE

DATA = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks"
MAX_J = 0.5


def _split(name):
    return [json.loads(line) for line in (DATA / f"{name}.jsonl").open(encoding="utf-8")]


@pytest.fixture(scope="module")
def pool():
    from homeloop_bench.planners.robot_agent_adapter import seed_pool_path
    p = seed_pool_path()
    assert p is not None and p.is_file()
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def held():
    return _split("dev") + _split("test")


def test_both_variants_listed_and_differ_only_in_the_pool():
    names = [n for n, _d, _a in list_planners()]
    assert "robot_agent:sage" in names and "robot_agent:sage_norag" in names
    a, b = planner_class("robot_agent:sage"), planner_class("robot_agent:sage_norag")
    assert issubclass(b, a) and a.seed_pool is True and b.seed_pool is False
    attrs = {k for k in dir(a) if not k.startswith("__") and not callable(getattr(a, k))}
    diff = {k for k in attrs if getattr(a, k) != getattr(b, k)}
    assert diff == {"seed_pool", "name"}, diff
    assert {k for k in vars(b) if not k.startswith("__")} == {"seed_pool", "name"}
    assert REGISTRY["robot_agent:sage_norag"][3] is True


def test_run_config_records_variant_and_sha(pool):
    import hashlib

    from homeloop_bench.planners.robot_agent_adapter import seed_pool_path
    ca, cb = planner_class("robot_agent:sage").run_config(), planner_class("robot_agent:sage_norag").run_config()
    assert ca["variant"] == "rag" and ca["seed_pool_n"] == len(pool)
    assert ca["seed_pool_sha"] == hashlib.sha256(seed_pool_path().read_bytes()).hexdigest()
    assert cb["variant"] == "norag" and cb["seed_pool"] is None and cb["seed_pool_n"] == 0
    assert {k: v for k, v in ca.items() if not k.startswith(("seed_pool", "variant"))} == \
           {k: v for k, v in cb.items() if not k.startswith(("seed_pool", "variant"))}


def test_no_family_gen_id_template_or_house_shared(pool, held):
    fam = {t["meta"]["family"] for t in held}
    gid = {t["meta"]["gen_id"] for t in held} | {t["id"] for t in held}
    tid = {t["template_id"] for t in held}
    houses = {t["house"] for t in held} | {t["house"] for t in _split("train")}
    from homeloop_robot.houses import list_houses
    for e in pool:
        o = e["origin"]
        assert o["family"] not in fam and o["gen_id"] not in gid and o["template_id"] not in tid
        assert e["house"] == PE.HOUSE_NAME and e["house"] not in houses and e["house"] not in list_houses()
        blob = json.dumps(e, ensure_ascii=False)
        assert not re.search(r"hl-(dev|test)-\d+", blob)


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_no_near_duplicate_text(pool, held, lang):
    mine = [e for e in pool if e["lang"] == lang]
    assert mine
    texts = []
    for t in held:
        texts.append(t["text"][lang])
        tt = (t["meta"].get("template_text") or {}).get(lang)
        if tt:
            texts.append(tt)
    sh = [shingles(x, lang) for x in dict.fromkeys(texts)]
    for e in mine:
        a = shingles(e["task"], lang)
        worst = max(jaccard(a, b) for b in sh)
        assert worst < MAX_J, (e["task"], worst)


def _run_plan(e):
    """The example's plan through the robot package's skill functions on the mock robot in example_flat (ideal):
    MoveTo / Place take the raw key as robot_agent's AssistLoop passes it, the other steps the adapter's bind."""
    from homeloop_robot.configs import ra_skills
    from homeloop_robot.configs.adapter import make_adapter
    from homeloop_robot.configs.backend import reset_backend, set_backend
    from homeloop_robot.configs.tasks import env_for
    from homeloop_robot.episode import make_episode
    from homeloop_robot.goals import evaluate
    ep = make_episode(PE.example_house(), 0, "ideal", 0, lang=e["lang"], key="seed-pool")
    set_backend(ep.robot)
    env = env_for(ep.world)
    try:
        import robot_agent.skill_configs as sc
    except ImportError:
        sc = None
    old = getattr(sc, "ENV", None) if sc is not None else None
    if sc is not None:
        sc.ENV = env
    try:
        ad = make_adapter()
        for s in json.loads(e["plan_text"])["steps"]:
            skill, params = ad.bind(s, None)
            if s["action"] in ("MoveTo", "Place"):
                params = {"inputs": s["object"]}
            r = getattr(ra_skills, skill)(None, **params)
            assert r.get("isdone"), (e["task"], s, r)
        return ep.world, bool(evaluate(e["goal"], ep.world).holds)
    finally:
        if sc is not None:
            sc.ENV = old
        reset_backend()


needs_ra = pytest.mark.skipif(__import__("importlib").util.find_spec("robot_agent") is None,
                              reason="the robot package's adapter needs robot_agent")


@needs_ra
def test_every_example_solves_its_task(pool):
    for e in pool:
        world, ok = _run_plan(e)
        assert ok, (e["task"], e["goal"])
        if not e["goal"].get("refuse"):
            assert any(a.get("pred") != "unmoved" for a in e["goal"]["all"])


@needs_ra
def test_reach_delivery_examples_end_on_a_reachable_surface(pool):
    from homeloop_robot.reach import delivered
    for e in pool:
        for a in e["goal"]["all"]:
            if a.get("pred") == "delivered":
                world, _ = _run_plan(e)
                assert delivered(world, a["args"][0], a["args"][1], a["mode"]), e["task"]


# ------------------------------------------------------------------- goals (R2-7 review add-on 1, pilot round 2)
# The two message seeds used to say said_to(son, come_kitchen) / said_to(son, leaving_soon): the goal of 112 / 72
# dev + test tasks (pilot task hl-dev-000013 is leaving_soon), with null origin fields, so the checks above passed
# trivially. The goal checks below compare NORMALISED goal atoms: an object -> its catalog class, a place -> its id
# prefix (the receptacle name), a person -> their role (the speaker / another person), plus the delivery mode.

def _norm_atom(a, w):
    def n(x):
        if x in w.objects:
            return w.objects[x].cls
        if x in w.house.places:
            return x.split("@")[0]
        if x in w.people:
            return "person:" + w.people[x].role
        return x
    return (a.get("pred"),) + tuple(n(x) for x in a.get("args") or []) + ((a["mode"],) if a.get("mode") else ())


def _norm_goal(g, w):
    return tuple(sorted(_norm_atom(a, w) for a in g.get("all") or [] if "pred" in a))


@pytest.fixture(scope="module")
def held_goals(held):
    from homeloop_robot.episode import make_episode
    worlds, goals, atoms = {}, {}, {}
    for t in held:
        if t["house"] not in worlds:
            worlds[t["house"]] = make_episode(t["house"], 0, "ideal", 0).world
        w = worlds[t["house"]]
        goals.setdefault(_norm_goal(t["goal"], w), t["id"])
        for a in t["goal"].get("all") or []:
            if "pred" in a:
                atoms.setdefault(_norm_atom(a, w), t["id"])
    return goals, atoms


def _example_world():
    from homeloop_robot.episode import make_episode
    return make_episode(PE.example_house(), 0, "ideal", 0).world


def test_origin_fields_are_filled_honestly(pool):
    for e in pool:
        o = e["origin"]
        assert o["source"] == "hand-written for example_flat", e["task"]
        assert all(o.get(k) for k in ("family", "gen_id", "template_id", "split")), o


def test_no_seed_goal_is_a_dev_test_goal(pool, held_goals):
    goals, atoms = held_goals
    w = _example_world()
    for e in pool:
        g = _norm_goal(e["goal"], w)
        assert g not in goals, (e["task"], g, goals.get(g))
        for a in e["goal"]["all"]:
            if a.get("pred") == "said_to":                  # a message: not even one atom in common
                na = _norm_atom(a, w)
                assert na not in atoms, (e["task"], na, atoms.get(na))


def test_no_seed_say_text_is_a_dev_test_message(pool, held):
    from homeloop_robot.catalog import MESSAGE_TEXT, MESSAGES, message_matches
    keys = {a["args"][1] for t in held for a in t["goal"].get("all") or [] if a.get("pred") == "said_to"}
    says = [(e["lang"], s["object"]) for e in pool for s in json.loads(e["plan_text"])["steps"]
            if s["action"] == "Say" and not e["goal"].get("refuse")]
    assert says
    for lang, text in says:
        for k in sorted(keys):
            # semantic: the Say would not count as any dev / test message (the goal check a Say must pass)
            assert not message_matches(k, text, lang), (text, k)
            ref = (MESSAGE_TEXT.get(k) or {}).get(lang)
            assert ref is None or jaccard(shingles(text, lang), shingles(ref, lang)) < MAX_J, (text, ref)
        assert not any(text == (MESSAGE_TEXT.get(k) or {}).get(lang) for k in MESSAGES)


def test_the_old_message_seeds_would_fail(held_goals):
    """The checks catch the leak they are for: the former seeds' message goals are dev / test goals."""
    goals, atoms = held_goals
    for key in ("come_kitchen", "leaving_soon"):
        assert ("said_to", "person:other", key) in atoms
