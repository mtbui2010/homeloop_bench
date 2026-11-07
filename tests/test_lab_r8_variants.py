"""Lab round 8 variants (a model per role): robot_agent:sage_m9, sage_mk and the step 4 / 5 bundles sage_s4, sage_s5, sage_s45. What each
variant sets (run_config), the role routing of the episode path (repair / dialog clients counted on the episode cap and apart,
think passed to the role client), and episodes under --llm fake. Skipped when robot_agent is not importable."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.llm import OllamaHTTP  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402

NAMES = ("sage_m9", "sage_mk", "sage_s4", "sage_s5", "sage_s45", "sage_s45m", "sage_m9t", "sage_m9b", "sage_m9k8", "sage_s45m8",
         "sage_s45mk", "sage_s45m8k")


def test_registered_and_the_reference_is_kept():
    for n in NAMES + ("sage_m1", "sage_r3u"):
        assert f"robot_agent:{n}" in REGISTRY


def test_m9_and_mk_say_what_they_set():
    m9 = planner_class("robot_agent:sage_m9").run_config()
    assert m9["understand_model"] == "qwen3.5:9b" and m9["repair_model"] == "qwen3.5:9b" and "dialog_model_lang" not in m9
    assert m9["manifest_overlay"]["planner"]["understand_think"] == 0 and m9["manifest_overlay"]["planner"]["repair_max_tokens"] == 1024
    assert m9["manifest_overlay"]["assumed"] is True
    mk = planner_class("robot_agent:sage_mk").run_config()
    assert mk["dialog_model_lang"] == {"ko": "hyperclovax-seed-think-14b"} and mk["manifest_overlay"]["planner"]["dialog_max_tokens"] == 128
    assert mk["repair_model"] == "qwen3.5:9b"
    ref = planner_class("robot_agent:sage_m1").run_config()
    assert ref["understand_model"] == "qwen3-vl:30b-a3b-instruct" and "repair_model" not in ref and "dialog_model" not in ref


def test_the_korean_reader_variants_of_the_9b():
    """Round 8b: the 9B's Korean reading measured with the pivot or with the 8B reading Korean; nothing else differs from sage_m9."""
    m9 = planner_class("robot_agent:sage_m9")
    for n, pivot in (("sage_m9t", "translate"), ("sage_m9b", "both")):
        c = planner_class(f"robot_agent:{n}")
        assert c.loop_options == {**m9.loop_options, "input_pivot": pivot} and c.run_config()["input_pivot"] == pivot
    k8 = planner_class("robot_agent:sage_m9k8")
    assert k8.loop_options == m9.loop_options and k8.run_config()["understand_model_lang"] == {"ko": "qwen3-vl:8b-instruct"}
    assert k8.run_config()["understand_model"] == "qwen3.5:9b" and m9.run_config()["understand_model_lang"] is None
    s45 = planner_class("robot_agent:sage_s45m")
    assert planner_class("robot_agent:sage_s45m8").loop_options == s45.loop_options
    assert planner_class("robot_agent:sage_s45m8").run_config()["understand_model_lang"] == {"ko": "qwen3-vl:8b-instruct"}
    mk = planner_class("robot_agent:sage_s45mk").run_config()
    assert mk["dialog_model_lang"] == {"ko": "hyperclovax-seed-think-14b"} and mk["understand_model"] == "qwen3.5:9b"
    assert mk["request_coverage"] == 1 and mk["repair_model"] == "qwen3.5:9b"
    k8 = planner_class("robot_agent:sage_s45m8k").run_config()
    assert k8["dialog_model_lang"] == mk["dialog_model_lang"] and k8["understand_model_lang"] == {"ko": "qwen3-vl:8b-instruct"}


def test_the_step_bundles():
    s4 = planner_class("robot_agent:sage_s4").loop_options
    assert {k: s4[k] for k in ("dialog_unstick", "inventory_ask", "reask_anchor", "request_coverage")} == {
        "dialog_unstick": "1", "inventory_ask": "1", "reask_anchor": "1", "request_coverage": "1"}
    assert s4["go_steps"] == "1" and "exec_integrity" not in s4
    s5 = planner_class("robot_agent:sage_s5")
    assert s5.loop_options == planner_class("robot_agent:sage_r3u").loop_options          # the sage_r3u bundle
    assert s5.manifest_overlay == planner_class("robot_agent:sage_r3u").manifest_overlay
    s45 = planner_class("robot_agent:sage_s45")
    assert s45.loop_options == {**s5.loop_options, **s4} and s45.manifest_overlay == s5.manifest_overlay
    assert planner_class("robot_agent:sage_s4").run_config()["request_coverage"] == 1


def test_ollama_body_sends_think_only_when_set():
    llm = OllamaHTTP("http://x", "m")
    assert "think" not in llm.body("p")
    llm.think = False
    assert llm.body("p")["think"] is False


def test_the_other_variants_record_nothing_new():
    for n in ("sage", "sage_ground2", "sage_r3u"):
        cfg = planner_class(f"robot_agent:{n}").run_config()
        assert not any(k in cfg for k in ("repair_model", "dialog_model", "dialog_model_lang", "request_coverage"))


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_episodes_of_the_role_variants_under_fake(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    for n in NAMES:
        s = run_many(f"robot_agent:{n}", None, None, "ideal", 1, lang, "fake", tmp_path / n, tasks=tasks)
        eps = [json.loads(l) for l in (tmp_path / n / "episodes.jsonl").read_text().splitlines()]
        assert len(eps) == 3 and s["n_episodes"] == 3
        if n in ("sage_m9", "sage_mk", "sage_s45m", "sage_m9t", "sage_m9b", "sage_m9k8", "sage_s45m8", "sage_s45mk", "sage_s45m8k"):
            assert all("llm_calls_understand" in e and e["llm_calls_understand"] <= e["llm_calls"] for e in eps)
            assert all("llm_calls_repair" in e for e in eps)
            assert all(("llm_calls_dialog" in e) == (n in ("sage_mk", "sage_s45mk", "sage_s45m8k")) for e in eps)
        else:
            assert all("llm_calls_repair" not in e and "llm_calls_dialog" not in e for e in eps)
    base = run_many("robot_agent:sage_ground2", None, None, "ideal", 1, lang, "fake", tmp_path / "base", tasks=tasks)
    assert "llm_calls_repair_mean" not in base and "llm_calls_dialog_mean" not in base
