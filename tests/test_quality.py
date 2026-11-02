from homeloop_bench.gen.quality import sample, score
from homeloop_bench.tasks import read_records


def test_sample_is_stratified_and_large_enough():
    recs = [r for s in ("train", "dev", "test") for r in read_records(s)]
    smp = sample(recs, 600)
    assert len(smp) >= 500
    assert len({r["structure"] for r in smp}) == len({r["structure"] for r in recs})
    assert sample(recs, 600) == smp


def test_score_entities_and_markers():
    r = {"text": {"en": "First put the milk in the fridge, then bring me the red mug."}, "structure": "ordered",
         "meta": {"entities": {"en": [["milk", "milk carton"], ["fridge"], ["red mug"]]}}}
    s = score(r, "First put the milk in the fridge and then bring me the red mug.")
    assert s["entities"] == 1.0 and s["marker"] is True and s["chrf"] > 80
    s = score(r, "Bring me a cup.")
    assert s["entities"] == 0.0 and s["marker"] is False
