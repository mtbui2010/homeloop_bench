"""The sim-user audit (R2-7a, homeloop_robot docs/user_model.md "Accuracy audit"): gold = the majority of three
judges, 3-way disagreements left out and counted; the committed result reproduces from the committed classifier
cache without a server; the audit set is fixed."""
import json

from homeloop_bench import sim_user_audit as A


def _judges(*labels):
    return [{"q1": {"qid": "q1", "qtype": qt, "slots": sl}} for qt, sl in labels]


def test_gold_is_the_majority_and_three_way_disagreements_are_none():
    g = A.gold("q1", _judges(("where_is", {"obj": "remote"}), ("where_is", {"obj": "the remote"}), ("repeat", {})))
    assert g["qtype"] == "where_is" and g["votes"] == 2 and g["slots"]["obj"] == ["remote", "the remote"]
    assert A.gold("q1", _judges(("where_is", {}), ("repeat", {}), ("free", {}))) is None


def test_score_excludes_disagreements_and_checks_key_slots():
    rows = [{"qid": "a", "question": "?", "lang": "en"}, {"qid": "b", "question": "?", "lang": "ko"},
            {"qid": "c", "question": "?", "lang": "ko"}]
    judges = [{"a": {"qid": "a", "qtype": "where_is", "slots": {"obj": "remote"}},
               "b": {"qid": "b", "qtype": "repeat", "slots": {}}, "c": {"qid": "c", "qtype": "free", "slots": {}}},
              {"a": {"qid": "a", "qtype": "where_is", "slots": {"obj": "remote"}},
               "b": {"qid": "b", "qtype": "repeat", "slots": {}}, "c": {"qid": "c", "qtype": "confirm", "slots": {}}},
              {"a": {"qid": "a", "qtype": "where_is", "slots": {"obj": "remote"}},
               "b": {"qid": "b", "qtype": "free", "slots": {}}, "c": {"qid": "c", "qtype": "help", "slots": {}}}]
    reads = [{"qid": "a", "lang": "en", "path": "structured", "qtype": "where_is", "slots": {"obj": "the cup"},
              "rule": "", "planner": "x"},
             {"qid": "b", "lang": "ko", "path": "rules", "qtype": "repeat", "slots": {}, "rule": "", "planner": "x"},
             {"qid": "c", "lang": "ko", "path": "rules", "qtype": "free", "slots": {}, "rule": "", "planner": "x"}]
    res = A.score(rows, judges, reads)
    assert res["n"] == 2 and res["n_disagree_excluded"] == 1 and res["disagreements"][0]["qid"] == "c"
    assert res["accuracy_en"] == 0.0 and res["accuracy_ko"] == 1.0          # "the cup" is not the remote
    assert res["confusions"][0]["sim"] == "where_is (slot)" and res["key_slots"] == {"checked": 1, "matched": 0}


def test_committed_audit_reproduces_offline(tmp_path):
    out = tmp_path / "audit.json"
    assert A.main(["--out", str(out)]) == 0
    new = json.loads(out.read_text(encoding="utf-8"))
    old = json.loads(A.OUT.read_text(encoding="utf-8"))
    assert new == old
    assert new["n_questions"] == 533 and new["n"] + new["n_disagree_excluded"] == 533
    assert new["n_en"] >= 100 and new["n_ko"] >= 100
    assert set(new["by_path"]) <= {"structured", "structured_mismatch", "rules", "llm"}
