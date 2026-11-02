"""USER_FEEDBACK 8: real names instead of letter placeholders, no dominant text frame, articles before possessives."""

import collections
import re

from homeloop_bench.gen.textcheck import LETTER_NAME, check_text
from homeloop_bench.tasks import read_records

RECS = [r for s in ("train", "dev", "test") for r in read_records(s)]


def _frame(t):
    return " ".join(re.sub(r"\d+", " ", re.sub(r"\b(the|a|an|my|your|his|her)\b", " ", t.lower())).split()[:6])


def test_no_letter_placeholder_names():
    assert not [r["id"] for r in RECS if LETTER_NAME.search(r["text"]["en"]) or LETTER_NAME.search(r["text"]["ko"])]


def test_no_opening_frame_over_half_a_percent():
    top = collections.Counter(_frame(r["text"]["en"]) for r in RECS).most_common(1)[0]
    assert top[1] <= 0.005 * len(RECS), top


def test_no_article_before_possessive():
    assert not [r["id"] for r in RECS if re.search(r"\b[Tt]he (my|your|our|his|her|their)\b", r["text"]["en"])]
    assert check_text("Put it on the my desk.", "en") and not check_text("Put it on my desk.", "en")


def test_microwave_refusals_come_with_a_related_second_task():
    from homeloop_bench.gen.compound import MEAL_WITH
    rel = set(MEAL_WITH) | {"snack", "bread"}
    for r in RECS:
        if r["meta"]["family"] != "compound.mix_microwave_refuse":
            continue
        other = [s for s in r["subtasks"] if s["kind"] != "refuse"][0]
        atom = other["goal"]["all"][0]
        if atom["pred"] == "said_to":
            assert atom["args"][1] in ("dinner_ready", "lunch_ready", "come_kitchen"), r["id"]
        else:
            assert atom["args"][0].rsplit("_", 1)[0] in rel, (r["id"], atom)
