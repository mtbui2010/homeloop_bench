"""H3 (lab round 3): in a "tell P <message> and bring me X" request the fetch clause cannot attach to the message.

The generator puts the fetch clause in its own sentence (EN_TELLFETCH / KO_TELLFETCH), the train / dev tasks were
re-rendered through it (`data tellfix`), and every accepted paraphrase passes the same check. The test split is not
re-rendered (its tasks keep the old wording; this is reported, not hidden)."""
import json
import random

import pytest

from homeloop_robot.houses import list_houses
from homeloop_robot.world import from_house

from homeloop_bench.gen import compound as CP
from homeloop_bench.gen import paraphrase as PP
from homeloop_bench.gen.attach import FAMILIES, attach_problem, message_before_fetch
from homeloop_bench.gen.lexicon import Lex
from homeloop_bench.tasks import read_records


def _fake(subs_tell_first=True, family="compound.tell_fetch"):
    st_t = {"goal": {"all": [{"pred": "said_to", "args": ["grandpa", "come_kitchen"]}]}}
    st_f = {"goal": {"all": [{"pred": "delivered", "args": ["book_1", "user"]}]}}
    return {"meta": {"family": family}, "subtasks": [st_t, st_f] if subs_tell_first else [st_f, st_t], "text": {}}


def test_attached_and_separate_texts():
    r = _fake()
    bad = ["Could you tell Grandpa to come to the kitchen and bring me the red book?",
           "Please tell my husband we leave in ten minutes, and grab the keys for me.",
           "Tell Grandpa to come to the kitchen, and then bring me the book, please."]
    good = ["Could you tell Grandpa to come to the kitchen? And bring me the red book.",
            "Tell Grandpa to come to the kitchen. Then bring the book over to me, please.",
            "Bring me the red book, and tell Grandpa to come to the kitchen.",
            "Please let Grandpa know someone is on the phone for him. And get me my phone."]
    assert all(attach_problem(r, "en", t) for t in bad)
    assert not any(attach_problem(r, "en", t) for t in good)
    kb = ["남편한테 가서 10분 있다가 나간다고 말해 주고 오렌지를 갖다줄래요?"]
    kg = ["남편한테 10분 뒤에 출발한다고 전해 주세요. 그리고 오렌지를 갖다줄래요?",
          "오렌지를 가져다주세요. 그리고 남편한테 곧 나간다고 말해 주세요."]
    assert all(attach_problem(r, "ko", t) for t in kb) and not any(attach_problem(r, "ko", t) for t in kg)
    # not judged: another family, or the fetch first in the order of the subtasks
    assert attach_problem(_fake(family="compound.fetch_tell"), "en", bad[0]) is None
    assert not message_before_fetch(_fake(subs_tell_first=False))


def test_every_template_pattern_keeps_the_fetch_apart():
    """All five request wrappers (nn 0..4, 4 is the test-only one), EN and KO, over every house and many draws."""
    n = 0
    for house in list_houses():
        for seed in (0, 7, 31):
            lex = Lex(from_house(house, seed))
            rng = random.Random(seed)
            ops = CP.fam_tell_fetch(CP.Pools(lex), rng)
            rng.shuffle(ops)
            for cand in ops[:12]:
                for nn in range(CP.N_PAT):
                    r = CP.render(lex, cand, rng, nn)
                    if r is None:
                        continue
                    rec = {"meta": {"family": "compound.tell_fetch"}, "subtasks": [
                        {"goal": {"all": [{"pred": "said_to", "args": ["p", "m"]}]}},
                        {"goal": {"all": [{"pred": "held_by", "args": ["o", "u"]}]}}]}
                    for lg in ("en", "ko"):
                        assert attach_problem(rec, lg, r[lg]) is None, (house, nn, r[lg])
                    n += 1
    assert n >= 100


@pytest.mark.parametrize("split", ["train", "dev"])
def test_every_tell_fetch_task_in_the_data_keeps_the_fetch_apart(split):
    recs = [r for r in read_records(split) if r["meta"]["family"] in FAMILIES]
    assert len(recs) >= 15
    for r in recs:
        for lg in ("en", "ko"):
            assert attach_problem(r, lg) is None, (r["id"], lg, r["source_by_lang"][lg], r["text"][lg])
            # the text still has a message verb, so the check judged something
            from homeloop_bench.gen.attach import TELL
            assert TELL[lg].search(r["text"][lg]), (r["id"], lg, r["text"][lg])
        assert r["meta"].get("tellfix")                               # re-rendered through the generator (data tellfix)
        for lg in ("en", "ko"):                                       # template_text follows paraphrases
            if r["source_by_lang"][lg] == "llm_paraphrase":
                assert attach_problem(r, lg, r["meta"]["template_text"][lg]) is None


def test_the_test_split_is_left_alone():
    recs = [r for r in read_records("test") if r["meta"]["family"] in FAMILIES]
    assert recs and not any(r["meta"].get("tellfix") for r in recs)


def test_paraphrase_filter_rejects_an_attached_candidate():
    r = {"meta": {"family": "compound.tell_fetch", "entities": {"en": [["Grandpa"], ["kitchen"], ["red book"]], "ko": []}},
         "subtasks": _fake()["subtasks"], "n_subtasks": 2, "structure": "sequence",
         "text": {"en": "Tell Grandpa to come to the kitchen. And bring me the red book.", "ko": ""}}
    why = PP.filters(r, "en", "Hey, tell Grandpa to come to the kitchen and bring me the red book.")
    assert "fetch_attached_to_message" in why
    ok = PP.filters(r, "en", "Go ask Grandpa to come to the kitchen for a minute. After that, get me the red book.")
    assert "fetch_attached_to_message" not in ok


def test_english_judge_asks_the_attachment_question_separately():
    assert "judge_attach" in PP.PROMPT and PP.PROMPT["judge"].count("{") == PP.PROMPT["judge"].count("{")
    assert PP._decode("judge_attach", json.dumps({"separate": True})) == "same"
    assert PP._decode("judge_attach", json.dumps({"separate": False})) == "attached"
    assert PP._decode("judge_attach", "not json") == "attached"
    p = PP.build_prompt("judge_attach", {"text": "Tell Grandpa to come. And bring me the book."})
    assert "Tell Grandpa to come. And bring me the book." in p and "{" not in p.replace('{"separate": true}', "").replace(
        '{"separate": false}', "")
    # the same-meaning judge prompt (and so every cached judgement) is unchanged
    assert PP.PROMPT["judge"].startswith("Request A and request B were said to a home robot.")
