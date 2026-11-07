"""The `asr_off` sensitivity condition (docs/experiments.md) must silence every speech-recognition error source.

Rounds before Round 7 step 5 set three parameters and left `asr.p_not_heard` on, so an utterance could still be lost.
The documented definition lists four; with them the user is always heard exactly. The old three-parameter form is
kept here as the counter-example."""
import random
import re
from pathlib import Path

from homeloop_robot.asr import ASRRates, corrupt
from homeloop_robot.profiles import load_profile

DOC = Path(__file__).resolve().parents[1] / "docs" / "experiments.md"
FOUR = {"asr.en.app_wer", "asr.ko.app_cer", "asr.p_partial", "asr.p_not_heard"}
EN = "could you please bring the red mug from the kitchen counter to grandma in the living room"
KO = "부엌 조리대에 있는 빨간 머그컵을 거실에 계신 할머니께 가져다 주세요"


def _documented_set():
    m = re.search(r"\*\*Definition of `asr_off`\*\*.*?`--set ([^`]+)`", DOC.read_text(encoding="utf-8"), re.S)
    assert m, "docs/experiments.md has no 'Definition of `asr_off`'"
    return m.group(1)


def _events(spec, n=3000):
    r = ASRRates(load_profile("real+" + spec))
    out = set()
    for i in range(n):
        for text, lang in ((EN, "en"), (KO, "ko")):
            h = corrupt(text, lang, "app", random.Random(i), r)
            out.add((h.event, h.text == text))
    return out


def test_definition_lists_all_four_parameters_at_zero():
    items = dict(x.split("=") for x in _documented_set().split(","))
    assert set(items) == FOUR and all(float(v) == 0 for v in items.values())


def test_asr_off_hears_every_utterance_exactly():
    assert _events(_documented_set()) == {("ok", True)}


def test_three_parameter_form_still_loses_utterances():
    three = ",".join(f"{k}=0" for k in sorted(FOUR - {"asr.p_not_heard"}))
    assert ("not_heard", False) in _events(three)
