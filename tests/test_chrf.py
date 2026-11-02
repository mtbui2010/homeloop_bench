from homeloop_bench.gen.chrf import chrf


def test_identical_and_disjoint():
    assert abs(chrf("bring me the red mug", "bring me the red mug") - 100.0) < 1e-9
    assert chrf("abc", "xyz") == 0.0
    assert chrf("", "abc") == 0.0


def test_closer_is_higher():
    ref = "Could you bring me the red mug?"
    assert chrf("Can you bring me the red mug?", ref) > chrf("Please open the fridge.", ref)


def test_whitespace_ignored():
    assert abs(chrf("red mug", "redmug") - 100.0) < 1e-9
