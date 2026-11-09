"""The P1 LoRA data builder's pure parts (tools/lora: understand_labels colour attribution and serialisation, text_noise)."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "lora"))

import text_noise as TN  # noqa: E402
import understand_labels as UL  # noqa: E402


def test_colour_attached_to_its_own_object_only():
    t = "Can you take the phone back to the bed? And after that, fetch the black mug for me, oh wait, not the black one, the white one."
    assert UL.color_said("black", t, "en", "phone", ["phone", "mug"]) == ""
    assert UL.color_said("white", t, "en", "mug", ["phone", "mug"]) == "white"
    assert UL.color_said("red", "Put the red mug on the table.", "en", "mug", ["mug"]) == "red"


def test_colour_in_korean_and_class_inside_another_name():
    t = "핸드폰을 침대에 도로 올려놓은 다음에 검은 머그컵, 아니 하얀 거 가져다줄 수 있어요?"
    assert UL.color_said("white", t, "ko", "mug", ["phone", "mug", "cup"]) == "하얀"
    assert UL.color_said("green", "초록색 유리잔 좀 가져와 주세요.", "ko", "glass", ["glass"]) == "초록색"


def test_class_name_that_is_a_colour_word_is_no_colour():
    assert UL.color_said("orange", "Please stick the orange in the fridge.", "en", "orange", ["orange"]) == ""


def test_serialise_follows_the_schema_order():
    ans = {"goals": [{"to": "me", "from": "", "type": "on", "object": "cup", "_cls": "cup"}], "question": "", "status": "clear",
           "reason_type": "", "reason": "r"}
    out = UL.serialise(ans)                                   # required keys first, an empty reason_type left out
    assert list(json.loads(out)) == ["status", "reason", "question", "goals"]
    assert list(json.loads(out)["goals"][0]) == ["type", "object", "from", "to"]
    ans2 = {**ans, "reason_type": "payload", "goals": [{"type": "on", "object": "cup", "said": "컵", "from": "", "to": "me"}]}
    out2 = json.loads(UL.serialise(ans2))
    assert list(out2) == ["status", "reason", "question", "goals", "reason_type"]
    assert list(out2["goals"][0]) == ["type", "object", "from", "to", "said"]


def test_noise_is_deterministic_and_keeps_markers_and_entities():
    text = "Put the glasses on the desk, sorry, I mean the bed, and do not touch the medicine bottle."
    a = TN.noisy(text, "en", random.Random(3), protect=["glasses", "medicine bottle", "bed", "desk"])
    b = TN.noisy(text, "en", random.Random(3), protect=["glasses", "medicine bottle", "bed", "desk"])
    assert a == b
    for seed in range(200):
        out, edits = TN.noisy(text, "en", random.Random(seed), protect=["glasses", "medicine bottle", "bed", "desk"])
        for w in ("sorry", "mean", "not"):
            assert w in out
        words = out.replace(",", " ").replace(".", " ").split()
        for p in ("glasses", "bed", "desk", "medicine"):            # kept, at most one letter replaced
            assert any(len(w) == len(p) and sum(a != b for a, b in zip(w, p)) <= 1 for w in words), (seed, out, edits)


def test_korean_noise_never_cuts_an_entity():
    text = "김치냉장고에 세제를 넣어 주실 수 있을까요? 싱크대 밑이 좁아서요."
    for seed in range(300):
        out, _ = TN.noisy(text, "ko", random.Random(seed), protect=["세제", "김치냉장고"])
        assert "세를" not in out and "세에" not in out                      # the entity is never cut ("세제를" -> "세를")
        assert out.split()[0][:5] != "김치냉장고"[:4] + "에"                # nor shortened
        assert len(out.replace(" ", "")) >= len(text.replace(" ", "")) - 2
