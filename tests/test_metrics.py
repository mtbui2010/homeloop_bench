"""metrics.py: Wilson interval, McNemar, recovery accounting, summary keys (docs/metrics.md)."""

import math

from homeloop_bench.metrics import (binom_two_sided, failure_events, help_correct, mcnemar, percentile,
                                    summarize, wilson)

REQUIRED = ("success", "success_ci95", "goal_condition_success", "false_success", "recovery_rate_by_code",
            "help_rate", "correct_help_rate", "rejection_rate", "safety_violations", "min_separation_m",
            "llm_calls_mean", "time_mean_s", "n_episodes")


def test_wilson_known_values():
    lo, hi = wilson(8, 10)
    # Wilson 95 % interval for 8/10: [0.490, 0.943] (standard textbook value)
    assert abs(lo - 0.4902) < 1e-3 and abs(hi - 0.9433) < 1e-3
    assert wilson(0, 0) == [0.0, 1.0]
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo < 1.0


def test_mcnemar_exact_and_chi2():
    a = {(f"t{i}", 0): True for i in range(30)}
    b = dict(a)
    for i in range(5):
        b[(f"t{i}", 0)] = False
    r = mcnemar(a, b)
    assert r["n_pairs"] == 30 and r["b"] == 5 and r["c"] == 0 and r["method"] == "exact_binomial"
    assert abs(r["p_value"] - 2 * 0.5 ** 5) < 1e-9
    a2 = {(f"t{i}", 0): i < 40 for i in range(60)}
    b2 = {(f"t{i}", 0): i >= 30 for i in range(60)}
    r2 = mcnemar(a2, b2)
    assert r2["method"] == "chi2_continuity" and r2["b"] == 30 and r2["c"] == 20
    stat = (abs(30 - 20) - 1) ** 2 / 50
    assert abs(r2["statistic"] - stat) < 1e-6 and abs(r2["p_value"] - math.erfc(math.sqrt(stat / 2))) < 1e-6
    assert mcnemar({}, {})["n_pairs"] == 0
    assert binom_two_sided(0, 0) == 1.0


def _call(k, skill, args, ok, code=None):
    return {"k": k, "skill": skill, "args": args, "ok": ok, "code": code, "injected": not ok, "t": 0.0, "dur": 1.0,
            "event": None}


def test_failure_events_recovery_rules():
    calls = [_call(0, "pick", {"obj": "mug_1"}, False, "grasp_failed"),
             _call(1, "pick", {"obj": "mug_1"}, True),
             _call(2, "move", {"target": "a@x"}, False, "blocked"),
             _call(3, "find", {"obj": "cup_1"}, False, "absent"),
             _call(4, "place", {"target": "b@x"}, False, "dropped")]
    held = [None, None, "mug_1", "mug_1", "mug_1"]
    atoms = [["on(mug_1, b@x)", True], ["on(cup_1, c@x)", False]]
    ev = failure_events(calls, held, atoms)
    assert [e["recovered"] for e in ev] == [True, True, False, True]
    # retried same call -> recovered; blocked move: the held mug's atom holds; absent cup: its atom fails;
    # dropped: the held mug's atom holds


def test_help_correct():
    assert help_correct([_call(0, "ask", {"question": "q"}, True)], True) is True
    assert help_correct([_call(0, "ask", {"question": "q"}, True)], False) is False
    calls = [_call(0, "move", {"target": "a"}, False, "blocked"), _call(1, "ask", {"question": "q"}, True)]
    assert help_correct(calls, False) is True
    calls = [_call(0, "find", {"obj": "a"}, False, "absent"), _call(1, "find", {"obj": "a"}, False, "absent"),
             _call(2, "ask", {"question": "where"}, True)]
    assert help_correct(calls, False) is True
    assert help_correct([_call(0, "look", {}, True)], False) is None


def _ep(i, success, kind="feasible", claimed=True, asked=0, status="done", sep=None):
    return {"task_id": f"t{i}", "seed": 0, "kind": kind, "capability": "fetch", "ambiguity": "none", "lang": "en",
            "house": "h", "structure": None, "n_subtasks": 1, "success": success, "claimed": claimed,
            "gc": 1.0 if success else 0.5, "failures": [], "asked": asked, "help_correct": True if asked else None,
            "status": status, "semantic_violations": [], "safety": {"violations": 0, "severe": 0, "min_sep_m": sep,
                                                                    "n_stops": 0, "slow_s": 0.0},
            "llm_calls": 2, "sim_time_s": 100.0, "n_calls": 5, "subtask_correct": [success]}


def test_summarize_keys_and_values():
    eps = [_ep(0, True), _ep(1, False), _ep(2, True, kind="refuse", claimed=False, status="refuse", sep=1.5),
           _ep(3, False, kind="clarify", asked=1, sep=0.9)]
    s = summarize(eps, {"planner": "x"})
    for k in REQUIRED:
        assert k in s, k
    assert s["n_episodes"] == 4 and s["success"] == 0.5
    assert s["false_success"] == 0.5                    # t1 and t3 claimed done and failed
    assert s["rejection_rate"] == 1.0 and s["help_rate"] == 0.25 and s["help_recall"] == 1.0
    assert s["min_separation_m"] == 0.9 and s["llm_calls_mean"] == 2.0
    assert set(s["by_kind"]) == {"clarify", "feasible", "refuse"}
    assert s["config"] == {"planner": "x"}


def test_percentile():
    assert percentile([], 5) is None
    assert percentile([3.0, 1.0, 2.0], 5) == 1.0
    assert percentile(list(range(1, 101)), 5) == 5
