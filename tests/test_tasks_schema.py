from collections import Counter

from homeloop_bench.gen.stats import stats
from homeloop_bench.gen.validate import _compound, _schema
from homeloop_bench.tasks import load_split, read_records, task_by_id

SIZES = {"train": 6000, "dev": 1000, "test": 3000}


def _all():
    return [r for s in SIZES for r in read_records(s)]


def test_split_sizes_and_ids():
    recs = _all()
    assert Counter(r["split"] for r in recs) == SIZES
    assert len({r["id"] for r in recs}) == len(recs) == 10000


def test_every_record_matches_the_schema():
    for r in _all():
        assert not _schema(r), (r["id"], _schema(r))
        assert not _compound(r), (r["id"], _compound(r))


def test_bilingual_and_quotas():
    s = stats(_all())
    n = s["total"]
    assert s["en"] == s["ko"] == n
    assert sum(v for k, v in s["by_subtasks"].items() if int(k) >= 2) >= 0.35 * n
    assert sum(v for k, v in s["by_subtasks"].items() if int(k) >= 3) >= 0.12 * n
    assert s["long_share"] >= 0.15 and s["mixed_kind_share"] >= 0.05
    for st in ("sequence", "conjunction", "ordered", "conditional", "shared_object", "with_context", "correction"):
        assert s["by_structure"][st] >= 0.03 * n, st
    assert s["by_structure"]["conditional"] <= 0.05 * n          # assumed-source cap (USER_FEEDBACK 7)
    assert len(s["by_house"]) >= 6
    for k in ("feasible", "clarify", "refuse"):
        assert s["by_kind"][k] >= 0.05 * n


def test_held_out_houses_only_in_test():
    for s in ("train", "dev"):
        assert not {t.house for t in load_split(s)} & {"korean_apt_84", "care_home_suite"}
    assert {"korean_apt_84", "care_home_suite"} <= {t.house for t in load_split("test")}


def test_first_300_dev_tasks_cover_every_kind_and_capability():
    first = load_split("dev")[:300]
    assert {t.kind for t in first} == {"feasible", "clarify", "refuse"}
    assert len({t.capability for t in first}) == 9


def test_task_by_id():
    t = load_split("dev")[0]
    assert task_by_id(t.id) == t
