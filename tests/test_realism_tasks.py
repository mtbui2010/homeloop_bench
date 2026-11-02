import copy

from homeloop_bench.gen.realism import check_record, report
from homeloop_bench.gen.textcheck import check_text
from homeloop_bench.tasks import read_records


def test_shipped_sample_passes():
    recs = read_records("dev")[:300]
    rep = report(recs)
    assert rep["ok"], rep["rules"]


def test_atypical_destination_is_flagged():
    rec = next(r for r in read_records("dev") if r["structure"] == "single" and r["kind"] == "feasible"
               and r["goal"]["all"][0].get("pred") == "on")
    bad = copy.deepcopy(rec)
    oid = bad["goal"]["all"][0]["args"][0]
    bad["goal"]["all"][0]["args"] = [oid, "dock@" + bad["goal"]["all"][0]["args"][1].split("@")[1]]
    bad["subtasks"][0]["goal"] = bad["goal"]
    v, _ = check_record(bad)
    assert any(x["rule"] in ("R-b", "R-f") for x in v)


def test_language_rules():
    assert check_text("Could you bring me the {obj}?", "en")
    assert check_text("Could you bring me the the mug?", "en")
    assert check_text("머그컵 좀 갖다줘.", "ko")                 # 반말
    assert check_text("머그컵 좀 가져다줄래요?", "ko") == []
    assert check_text("Bring me the 머그컵, please.", "en")
