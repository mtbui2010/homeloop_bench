from homeloop_bench.gen.oracle_check import completion_times, order_ok, run_shim
from homeloop_bench.tasks import load_split


def test_completion_and_order():
    holds = [[False, True], [True, True], [True, False], [True, True]]
    comp = completion_times([{}, {}], holds)
    assert comp == [1, 3]
    assert order_ok([[0, 1]], comp) and not order_ok([[1, 0]], comp)
    assert not order_ok([[0, 1]], [None, 2])


def _pick(pred):
    for t in load_split("dev"):
        d = t.to_dict()
        if pred(d):
            return d
    return None


def test_shim_solves_each_kind_of_task():
    cases = [lambda d: d["kind"] == "feasible" and d["structure"] == "single",
             lambda d: d["kind"] == "clarify",
             lambda d: d["kind"] == "refuse",
             lambda d: (d["user"] or {}).get("interrupt") is not None,
             lambda d: d["structure"] == "ordered",
             lambda d: d["structure"] == "conditional",
             lambda d: d["mixed_kind"]]
    for pred in cases:
        d = _pick(pred)
        assert d is not None
        res = run_shim(d, "en")
        assert res["success"], (d["id"], res)
        res = run_shim(d, "ko")
        assert res["success"], (d["id"], res)
