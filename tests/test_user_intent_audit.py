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
    assert res["confusions"][0]["sim"] == "where_is (slot)"
    assert res["key_slots"]["checked"] == 1 and res["key_slots"]["matched"] == 0
    assert res["key_slots"]["by_slot"] == {"where_is.obj": {"checked": 1, "matched": 0}}


def _world():
    from homeloop_robot.episode import make_episode
    return make_episode("korean_apt_59", 0, "ideal", 0).world


def test_place_and_read_back_slots_are_scored():
    """which_place.obj / options and confirm.goal are key slots (review round 1): a read-back naming another
    place than the gold's, or options naming other places, is a slot error; the same places in another language
    match; a gold value naming nothing of the house is not comparable."""
    w = _world()
    rows = [{"qid": q, "question": "?", "lang": "ko"} for q in ("a", "b", "c", "d")]
    lab = {"a": ("confirm", {"goal": "리모컨을 티비장 위에 놓을게요"}), "b": ("confirm", {"goal": "리모컨을 소파에 둘게요"}),
           "c": ("which_place", {"options": ["냉장고", "김치냉장고"]}), "d": ("confirm", {"goal": "부두로 갈게요"})}
    judges = [{q: {"qid": q, "qtype": qt, "slots": sl} for q, (qt, sl) in lab.items()} for _ in range(3)]
    sim = {"a": {"goal": "I will put the remote on the TV stand."}, "b": {"goal": "I will put the remote on the TV stand."},
           "c": {"options": ["fridge", "kimchi fridge"]}, "d": {"goal": "I will go to the dock in the living."}}
    reads = [{"qid": q, "lang": "ko", "path": "structured", "qtype": lab[q][0], "slots": sim[q], "rule": "",
              "planner": "x", "_world": w} for q in ("a", "b", "c", "d")]
    res = A.score(rows, judges, reads)
    assert [e["qid"] for e in res["errors"]] == ["b"]
    assert res["key_slots"]["by_slot"]["confirm.goal"] == {"checked": 2, "matched": 1}
    assert res["key_slots"]["by_slot"]["which_place.options"] == {"checked": 1, "matched": 1}


def test_untranslated_korean_questions_are_listed_not_scored():
    rows = [{"qid": "a", "question": "Where is the remote?", "lang": "ko"}]
    judges = [{"a": {"qid": "a", "qtype": "where_is", "slots": {"obj": "remote"}}} for _ in range(3)]
    reads = [{"qid": "a", "lang": "ko", "path": "rules", "qtype": "free", "slots": {}, "rule": "not_in_lang",
              "planner": "x", "in_lang": False}]
    res = A.score(rows, judges, reads)
    assert res["n"] == 0 and res["n_untranslated_ko_excluded"] == 1 and res["untranslated_ko"][0]["qid"] == "a"


def test_committed_audit_reproduces_offline(tmp_path):
    out = tmp_path / "audit.json"
    assert A.main(["--out", str(out)]) == 0
    new = json.loads(out.read_text(encoding="utf-8"))
    old = json.loads(A.OUT.read_text(encoding="utf-8"))
    assert new == old
    assert new["n_questions"] == 533
    assert new["n"] + new["n_disagree_excluded"] + new["n_untranslated_ko_excluded"] == 533
    assert new["n_untranslated_ko_excluded"] <= 5           # listed one by one in untranslated_ko
    assert new["n_en"] >= 100 and new["n_ko"] >= 100
    assert set(new["by_path"]) <= {"structured", "structured_mismatch", "rules", "llm"}
