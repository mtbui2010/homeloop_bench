"""Round 16: the pack numbers and action roles the round 12-15 variants carry as (assumed) overlay, and the sensitivity switch
``HOMELOOP_RA_SET`` that sets one of them for a run. Skipped when robot_agent is not importable."""
import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.planners import planner_class  # noqa: E402
from homeloop_bench.planners import robot_agent_adapter as A  # noqa: E402

ROLES = {"put_down": "Place", "move": "MoveTo", "open": "Open", "close": "Close"}


def test_variants_with_the_round_14_and_15_options_declare_the_roles_and_the_guard_numbers():
    for name in ("robot_agent:sage_s7", "robot_agent:sage_s8", "robot_agent:sage_s6d"):
        ov = planner_class(name).manifest_overlay
        assert ov["assumed"] and ov["planner"]["action_roles"] == ROLES, name
    for name in ("robot_agent:sage_s7", "robot_agent:sage_s8"):
        assert planner_class(name).manifest_overlay["planner"]["agree_guard"] == {"garble_ratio": 0.6, "particle_chain": 2,
                                                                                  "tail_chars": 2}
    for name in ("robot_agent:sage_s8", "robot_agent:sage_s6d"):
        assert planner_class(name).manifest_overlay["planner"]["person_snapshot"] == {"trust_s": 60}
    assert "action_roles" not in planner_class("robot_agent:sage_s6").manifest_overlay["planner"]        # s6 is the reference


def test_the_overlays_are_valid_manifest_data():
    from robot_agent.contract.manifest import Manifest
    for name in ("robot_agent:sage_s7", "robot_agent:sage_s8", "robot_agent:sage_s6d", "robot_agent:sage_s6"):
        Manifest.from_dict({"robot": "toy", "planner": planner_class(name).manifest_overlay["planner"]})     # raises if not


def test_nothing_set_leaves_the_overlay_and_the_recorded_config_as_they_are(monkeypatch):
    monkeypatch.delenv(A.RA_SET_ENV, raising=False)
    cls = planner_class("robot_agent:sage_s8")
    assert A.effective_overlay(cls.manifest_overlay) is cls.manifest_overlay
    assert "sensitivity_set" not in cls.run_config()["manifest_overlay"]
    monkeypatch.setenv(A.RA_SET_ENV, "")
    assert A.effective_overlay(cls.manifest_overlay) is cls.manifest_overlay


def test_the_sensitivity_switch_sets_a_pack_number_and_is_recorded(monkeypatch):
    cls = planner_class("robot_agent:sage_s8")
    monkeypatch.setenv(A.RA_SET_ENV, "person_snapshot.trust_s=30,agree_guard.garble_ratio=0.5,unstick.restate_frac=0.4")
    ov = A.effective_overlay(cls.manifest_overlay)
    assert ov["planner"]["person_snapshot"]["trust_s"] == 30 and ov["planner"]["agree_guard"]["garble_ratio"] == 0.5
    assert ov["planner"]["agree_guard"]["tail_chars"] == 2 and ov["planner"]["unstick"]["restate_frac"] == 0.4
    assert ov["planner"]["unstick"]["fallback_words"] == 5 and ov["planner"]["action_roles"] == ROLES      # the rest as it was
    assert ov["sensitivity_set"].startswith("person_snapshot.trust_s=30") and ov["assumed"]
    assert cls.manifest_overlay["planner"]["person_snapshot"]["trust_s"] == 60                               # the class is untouched
    assert cls.run_config()["manifest_overlay"]["planner"]["person_snapshot"]["trust_s"] == 30
    monkeypatch.setenv(A.RA_SET_ENV, "recovery.wait.schedule_s=[1,2],relook_x=abc")
    ov = A.effective_overlay(planner_class("robot_agent:sage_s6").manifest_overlay)
    assert ov["planner"]["recovery"]["wait"] == {"action": "Wait", "schedule_s": [1, 2]} and ov["planner"]["relook_x"] == "abc"


def test_a_variant_without_overlay_takes_the_set_alone(monkeypatch):
    monkeypatch.setenv(A.RA_SET_ENV, "detector_miss_rate=0.2")
    ov = A.effective_overlay(planner_class("robot_agent:sage").manifest_overlay)
    assert ov["planner"] == {"detector_miss_rate": 0.2}


@pytest.mark.parametrize("spec", ["nokey", "=3", "a.b"])
def test_a_malformed_switch_is_refused(spec):
    with pytest.raises(ValueError):
        A.effective_overlay({}, spec)


def test_the_switch_reaches_the_loops_manifest(monkeypatch):
    import types
    loop = types.SimpleNamespace(robot=types.SimpleNamespace(manifest=types.SimpleNamespace(planner={"person_snapshot": {"trust_s": 60}})))
    monkeypatch.setenv(A.RA_SET_ENV, "person_snapshot.trust_s=45")
    A.apply_overlay(loop, A.effective_overlay({"planner": {"person_snapshot": {"trust_s": 60}}}))
    assert loop.robot.manifest.planner["person_snapshot"]["trust_s"] == 45
