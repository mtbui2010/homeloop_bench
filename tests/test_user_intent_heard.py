"""The heard-text check on the bench side (review round 1, homeloop_robot docs/user_model.md "Heard-text check"):
through the ask API a planner's meaning counts only when the question text says it (both languages); SAGE's
"What should I open?" is answered with the container on the dev tasks it was found on; a message in another
language than the household's does not reach the listener."""
import pytest

from homeloop_bench.env import EpisodeEnv
from homeloop_bench.tasks import task_by_id
from homeloop_robot.configs.ra_dialog import derive

MILK = "hl-dev-000003"


def _ask(tid, lang, q, meaning=None):
    env = EpisodeEnv(task_by_id(tid), "ideal", 0, lang)
    args = {"question": q, "lang": lang}
    if meaning is not None:
        args["meaning"] = meaning
    r = env.call("ask", **args)
    return r, env.calls[-1]["intent"]


@pytest.mark.parametrize("tid,answer", [("hl-dev-000001", {"en": "The fridge.", "ko": "냉장고요."}),
                                        ("hl-dev-000028", {"en": "The microwave.", "ko": "전자레인지요."})])
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_what_should_i_open_on_dev_tasks(tid, answer, lang):
    q = {"en": "What should I open?", "ko": "뭘 열까요?"}[lang]
    r, it = _ask(tid, lang, q, derive("What should I open?"))
    assert it["path"] == "structured" and it["qtype"] == "which_place" and r["data"]["answer"] == answer[lang]


@pytest.mark.parametrize("lang,q", [("en", "Okay."), ("en", "Beep."), ("ko", "네."), ("ko", "삐.")])
@pytest.mark.parametrize("m", [{"qtype": "which_place", "options": ["fridge", "kimchi fridge"]},
                               {"qtype": "which_object"}, {"qtype": "where_are_you"},
                               {"qtype": "confirm", "goal": "Put the milk in the kimchi fridge"}])
def test_meaning_on_unrelated_text_is_a_mismatch(lang, q, m):
    r, it = _ask(MILK, lang, q, m)
    assert it["path"] == "structured_mismatch"
    assert "kimchi" not in r["data"]["answer"].lower() and "김치" not in r["data"]["answer"]


def test_untranslated_question_in_a_korean_episode():
    env = EpisodeEnv(task_by_id(MILK), "ideal", 0, "ko")
    r = env.call("ask", question="Fridge or kimchi fridge?", lang="ko",
                 meaning={"qtype": "which_place", "options": ["fridge", "kimchi fridge"]})
    it = env.calls[-1]["intent"]
    assert it["path"] == "structured_mismatch" and it["rule"] == "not_in_lang" and "김치" not in r["data"]["answer"]
    env.call("ask", question="냉장고요, 김치냉장고요?", lang="ko")
    env.finish("give_up")
    rec = env.record()
    assert rec["dialog_not_in_lang"] == 1 and rec["dialog_paths"] == {"rules": 1, "structured_mismatch": 1}
    from homeloop_bench.metrics import summarize
    assert summarize([rec], {})["dialog_not_in_lang"] == 1


@pytest.mark.parametrize("lang,text,ok", [("ko", "Dad, lunch is ready.", False), ("ko", "아빠, 점심 준비됐어요.", True),
                                          ("en", "Dad, lunch is ready.", True)])
def test_message_in_the_household_language(lang, text, ok):
    """KO hl-dev-000040 ("tell dad lunch is ready"): said in English in the Korean home, it does not tell dad."""
    from homeloop_robot import goals as G
    from homeloop_robot.types import Utterance
    env = EpisodeEnv(task_by_id("hl-dev-000040"), "ideal", 0, lang)
    w = env.ep.world
    w.utterances.append(Utterance(t=0.0, skill="say", text=text, lang="en" if text.startswith("Dad") else "ko",
                                  heard_by=("dad",)))
    assert G.holds({"pred": "said_to", "args": ["dad", "lunch_ready"]}, w) == ok
