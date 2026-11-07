"""Lab round 8: the sage_s5 bundle, and the generic per-role model options of robot_agent (repair_model, dialog_model_lang,
understand_model_lang, request_coverage; default off, data driven). The Qwen3.5 9B / HyperCLOVAX variants and the step 4 / 5
bundles were removed from the registry; the role routing of the episode path (repair / dialog clients counted on the episode cap
and apart, think passed to the role client) is still tested here with a local planner that sets the options with placeholder model
names. Skipped when robot_agent is not importable."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.llm import OllamaHTTP  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402
from homeloop_bench.planners.robot_agent_adapter import SageGround2Planner, SagePlanner  # noqa: E402

REMOVED = ("sage_m9", "sage_mk", "sage_m9t", "sage_m9b", "sage_m9k8", "sage_s45m", "sage_s45m8", "sage_s45mk", "sage_s45m8k",
           "sage_s4", "sage_s45")


class RoleModels(SagePlanner):
    """Test planner: every generic role option on, with placeholder model names."""
    name = "robot_agent:test_roles"
    loop_options = {**SageGround2Planner.loop_options, "understand_model": "reader:1", "repair_model": "reader:1",
                    "dialog_model_lang": {"ko": "writer:1"}, "request_coverage": "1"}
    manifest_overlay = {"planner": {"understand_max_tokens": 512, "understand_think": 0, "repair_max_tokens": 1024,
                                    "repair_think": 0, "dialog_max_tokens": 128},
                        "assumed": True, "note": "test"}


SPEC = "test_lab_r8_variants:RoleModels"


def test_registered_removed_and_kept():
    for n in ("sage", "sage_ground2", "sage_s5", "sage_m1", "sage_r3u"):
        assert f"robot_agent:{n}" in REGISTRY
    for n in REMOVED:
        assert f"robot_agent:{n}" not in REGISTRY


def test_sage_s5_is_the_r3u_bundle():
    s5 = planner_class("robot_agent:sage_s5")
    assert s5.loop_options == planner_class("robot_agent:sage_r3u").loop_options
    assert s5.manifest_overlay == planner_class("robot_agent:sage_r3u").manifest_overlay
    assert "request_coverage" not in s5.loop_options


def test_generic_role_options_are_recorded():
    c = planner_class(SPEC).run_config()
    assert c["understand_model"] == "reader:1" and c["repair_model"] == "reader:1" and c["dialog_model_lang"] == {"ko": "writer:1"}
    assert c["request_coverage"] == 1 and c["manifest_overlay"]["assumed"] is True


def test_ollama_body_sends_think_only_when_set():
    llm = OllamaHTTP("http://x", "m")
    assert "think" not in llm.body("p")
    llm.think = False
    assert llm.body("p")["think"] is False


def test_the_other_variants_record_nothing_new():
    for n in ("sage", "sage_ground2", "sage_r3u", "sage_s5"):
        cfg = planner_class(f"robot_agent:{n}").run_config()
        assert not any(k in cfg for k in ("repair_model", "dialog_model", "dialog_model_lang", "request_coverage"))


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_episodes_of_the_role_variants_under_fake(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    for n, roles in ((SPEC, True), ("robot_agent:sage_s5", False)):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        eps = [json.loads(l) for l in (d / "episodes.jsonl").read_text().splitlines()]
        assert len(eps) == 3 and s["n_episodes"] == 3
        if roles:
            assert all("llm_calls_understand" in e and e["llm_calls_understand"] <= e["llm_calls"] for e in eps)
            assert all("llm_calls_repair" in e for e in eps)
        else:
            assert all("llm_calls_repair" not in e and "llm_calls_dialog" not in e for e in eps)
    base = run_many("robot_agent:sage_ground2", None, None, "ideal", 1, lang, "fake", tmp_path / "base", tasks=tasks)
    assert "llm_calls_repair_mean" not in base and "llm_calls_dialog_mean" not in base
