"""Primary-cause rules of the failure analysis (homeloop_bench.failures, docs/experiments.md)."""

from homeloop_bench.failures import CAUSES, analyse, cause


def ep(**kw):
    e = {"task_id": "t", "kind": "feasible", "mixed_kind": False, "status": "give_up", "success": False,
         "calls": [], "failures": [], "goal_atoms": [["on(a, b)", False]], "delivery_atoms": [],
         "refused": False, "unmatched_refusals": 0, "order_ok": True, "semantic_violations": [],
         "false_success": False}
    e.update(kw)
    return e


def call(k, skill, ok=True, code=None, injected=False, **x):
    return dict(k=k, skill=skill, ok=ok, code=code, injected=injected, args={}, **x)


def test_status_and_refusal_rules():
    assert cause(ep(status="error")) == "crash"
    assert cause(ep(status="budget")) == "budget"
    assert cause(ep(status="refuse", refused=True)) == "wrong_refusal"
    assert cause(ep(kind="refuse", status="done")) == "missed_refusal"


def test_no_motion_rules():
    assert cause(ep()) == "no_plan"
    assert cause(ep(calls=[call(0, "ask", ok=False, code="timeout")])) == "ask_unanswered"
    assert cause(ep(calls=[call(0, "ask", reply_kind="not_sure")])) == "ask_unanswered"
    assert cause(ep(calls=[call(0, "ask", reply_kind="correct")])) == "ask_loop"
    # a failed first move is a robot failure, not "no plan", even when the metric counts it as recovered
    e = ep(calls=[call(0, "move", ok=False, code="unreachable", injected=True)],
           failures=[{"k": 0, "code": "unreachable", "injected": True, "recovered": True}])
    assert cause(e) == "gave_up_after_acting"
    e["failures"][0]["recovered"] = False
    assert cause(e) == "robot_failure"


def test_after_motion_rules():
    mv = [call(0, "move"), call(1, "find", ok=False, code="absent")]
    assert cause(ep(calls=mv, failures=[{"k": 1, "code": "absent", "injected": False, "recovered": False}])) \
        == "not_found"
    assert cause(ep(calls=[call(0, "move")], status="done",
                    delivery_atoms=[{"ok": False, "mode": "reach"}])) == "delivery_wrong"
    assert cause(ep(calls=[call(0, "move")], status="done", false_success=True)) == "claimed_unmet"
    assert cause(ep(calls=[call(0, "move")])) == "gave_up_after_acting"
    assert cause(ep(calls=[call(0, "move")], status="done", goal_atoms=[["on(a, b)", True]], order_ok=False)) \
        == "order_or_semantic"


def test_analyse_counts_only_failed_and_known_causes():
    r = analyse([ep(), ep(success=True), ep(status="error", task_id="x")])
    assert r["n"] == 3 and r["n_failed"] == 2
    assert set(r["causes"]) <= {c for c, _ in CAUSES}
    assert r["causes"]["crash"]["examples"] == ["x"]
