"""robot_agent planners through the homeloop robot package with --llm fake (docs/robot_agent.md).
Skipped when robot_agent is not importable."""

import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.runner import run_episode, run_many  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}
PICK = [TASKS["fx-feas-000"], TASKS["fx-clar-000"], TASKS["fx-ref-000"]]
PLANNERS = ("robot_agent:sage", "robot_agent:grace", "robot_agent:llm_direct")


@pytest.mark.parametrize("planner", PLANNERS)
def test_records_complete(planner):
    for t in PICK:
        e = run_episode(t, planner, "ideal", 0, "en", "fake")
        assert e.get("error") is None, (planner, t["id"], e.get("error"))
        assert e["status"] in ("done", "refuse", "give_up") and e["planner"] == planner
        assert isinstance(e["calls"], list)


def test_sage_feasible_clarify_refuse():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["success"] and e["status"] == "done" and e["llm_calls"] >= 1
    e = run_episode(TASKS["fx-clar-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["asked"] >= 1
    e = run_episode(TASKS["fx-ref-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["status"] == "refuse" and e["success"]


def test_robot_package_skills_are_exercised():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:grace", "ideal", 0, "en", "fake")
    skills = [c["skill"] for c in e["calls"]]
    assert {"move", "find", "pick"} <= set(skills)


def test_deterministic_summary(tmp_path):
    a = run_many("robot_agent:sage", "dev", None, "ideal", 1, "en", "fake", tmp_path / "a", tasks=PICK)
    b = run_many("robot_agent:sage", "dev", None, "ideal", 1, "en", "fake", tmp_path / "b", tasks=PICK)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert (tmp_path / "a" / "summary.json").read_bytes() == (tmp_path / "b" / "summary.json").read_bytes()


def test_backend_restored_after_episode():
    from homeloop_robot.configs import backend as hb
    before = hb._backend
    run_episode(TASKS["fx-feas-000"], "robot_agent:llm_direct", "ideal", 0, "en", "fake")
    assert hb._backend is before


def test_correction_is_injected_into_the_sage_run():
    e = run_episode(TASKS["fx-cor-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["goal_changed"] and e["events"][0]["kind"] == "correction"
    assert not any(c["code"] == "cancelled" for c in e["calls"])     # injected, not a cancelled call


def test_sage_object_memory_is_seeded_from_the_observed_memory(tmp_path):
    from homeloop_bench.env import EpisodeEnv
    from homeloop_bench.planners.robot_agent_adapter import seed_memory
    env = EpisodeEnv(TASKS["fx-feas-000"], "ideal", 0, "en")
    n = seed_memory(env, tmp_path / "mem.json")
    data = json.loads((tmp_path / "mem.json").read_text())
    assert n == len(data["objects"]) > 0 and data["answers"] == []
    usual = {}
    for o in env.object_memory():
        usual.setdefault(o.cls, set()).add(o.usual_place)
    for name, e in data["objects"].items():
        assert e["how"] == "house memory" and e["place"] in env.world0.house.places
    # a class whose objects usually sit at different places is not remembered by its bare name
    for cls, ps in usual.items():
        if len(ps) > 1:
            from homeloop_robot.catalog import CLASSES
            assert CLASSES[cls].name["en"].lower() not in data["objects"]


def test_sage_delivery_to_the_speaker_end_to_end():
    """'Bring me the red mug' to the speaker (senior_flat, grandma in the armchair, the side table in reach) with
    --llm fake. SAGE-v2 (round 3): "me" grounds to the speaker's ENV entry (its last-seen spot beside her) without
    asking; the mug is put down on that spot, which a reach delivery accepts. With people tracking off
    (robot_agent:sage_ask) SAGE asks "Where are you?" first. The adapter never turns a Place into a handover."""
    import copy
    g = {"all": [{"pred": "delivered", "args": ["mug_1", "grandma"], "mode": "reach", "mode_reason": None}]}
    from fixtures import base
    t = base("r2-e2e-000", "senior_flat", 0, g, capability="fetch")
    t["subtasks"] = [{"kind": "feasible", "capability": "fetch", "ambiguity": "none", "goal": copy.deepcopy(g)}]
    t["n_subtasks"], t["structure"] = 1, "single"
    t["text"] = {"en": "Bring me the red mug.", "ko": "빨간 머그컵 좀 가져다주세요."}
    e = run_episode(t, "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["delivery_atoms"][0]["mode"] == "reach" and e["delivery_atoms"][0]["ok"] == e["success"]
    asks = [c["args"].get("question", "") for c in e["calls"] if c["skill"] == "ask"]
    assert not any(q.startswith("Where are you?") for q in asks)
    assert not any(c["skill"] == "handover" for c in e["calls"])
    assert e["success"], (e["status"], e["finish_reason"], asks)
    e2 = run_episode(t, "robot_agent:sage_ask", "ideal", 0, "en", "fake")
    asks2 = [c["args"].get("question", "") for c in e2["calls"] if c["skill"] == "ask"]
    assert asks2 and asks2[0].startswith("Where are you?")
