from homeloop_bench.gen.dedup import NearDupIndex, jaccard, near_dup_pairs, norm, shingles


def test_norm():
    assert norm("Could you bring me the RED mug?!", "en") == "could you bring me the red mug"
    assert norm("빨간 머그컵 좀 갖다줄래요?", "ko") == "빨간머그컵좀갖다줄래요"


def test_shingles_and_jaccard():
    a = shingles("bring me the red mug please", "en")
    assert jaccard(a, a) == 1.0
    assert jaccard(a, shingles("open the kitchen drawer", "en")) < 0.3


def test_index_cross_split_only():
    idx = NearDupIndex()
    t = "Could you please bring me the red mug from the kitchen counter right now?"
    idx.add("a", t, "en", "train")
    near = "Could you please bring me the red mug from the kitchen counter right now"
    assert idx.find(near, "en", other_than="test") == "a"
    assert idx.find(near, "en", other_than="train") is None
    assert idx.find("Open the fridge.", "en", other_than="test") is None


def test_pairs():
    recs = [{"id": "x", "split": "train", "text": {"en": "Could you bring me the red mug from the counter, please?"}},
            {"id": "y", "split": "test", "text": {"en": "Could you bring me the red mug from the counter please"}},
            {"id": "z", "split": "test", "text": {"en": "Go tell Dad that dinner is ready."}}]
    pairs = near_dup_pairs(recs, "en")
    assert [(a, b) for a, b, _ in pairs] == [("x", "y")]
