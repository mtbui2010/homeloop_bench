"""Korean texts never put something inside an object ("접시 안에 넣어"; R2-5 B5, gen/kofix.py)."""
import copy
import random

import pytest

from homeloop_bench.gen import compound as CP
from homeloop_bench.gen import kofix
from homeloop_bench.gen.lexicon import Lex
from homeloop_bench.tasks import read_records
from homeloop_robot.houses import list_houses
from homeloop_robot.world import from_house


@pytest.mark.parametrize("text,hit", [
    ("냉장고 문 열어서 접시 안에 넣어 주실 수 있을까요?", ["접시"]),
    ("서랍장을 열어서 열쇠 안에 넣어 주세요.", ["열쇠"]),
    ("냉장고를 열고 하얀 접시 속에 담아 주세요.", ["접시"]),
])
def test_detects_an_object_as_the_container(text, hit):
    assert kofix.object_as_container(text, "shared_flat") == hit


@pytest.mark.parametrize("text", [
    "공용 냉장고 문 열어서 접시를 안에 넣어 주세요.",      # the plate goes inside (the fridge)
    "접시를 냉장고 안에 넣어 주세요.",                    # a place as the container
    "서랍 안에 넣어 주세요.",
    "접시 좀 안에 넣어 주세요.",
])
def test_a_place_or_an_object_with_its_particle_is_fine(text):
    assert kofix.object_as_container(text, "shared_flat") == []


def _rec(src_ko, text_ko, template_ko):
    return {"id": "x", "house": "shared_flat", "source": "llm_paraphrase",
            "source_by_lang": {"en": "llm_paraphrase", "ko": src_ko},
            "paraphrase_model": {"en": "m", "ko": "exaone3.5:latest" if src_ko == "llm_paraphrase" else None},
            "text": {"en": "Please open the fridge and slide the plate in there.", "ko": text_ko},
            "length_words": {"en": 10, "ko": 5},
            "meta": {"template_text": {"en": "Open the fridge and put the plate inside, please.", "ko": template_ko},
                     "paraphrase": {"en": {"model": "m"}, "ko": {"model": "exaone3.5:latest"}}}}


def test_a_paraphrase_falls_back_to_its_template_text():
    r = _rec("llm_paraphrase", "냉장고 문 열어서 접시 안에 넣어 주실 수 있을까요?", "냉장고 문 열어서 접시를 안에 넣어 주세요.")
    out, rule = kofix.fix_record(copy.deepcopy(r))
    assert rule == "template_fallback"
    assert out["text"]["ko"] == "냉장고 문 열어서 접시를 안에 넣어 주세요."
    assert out["source_by_lang"]["ko"] == "template" and out["paraphrase_model"]["ko"] is None
    assert "ko" not in out["meta"]["paraphrase"] and out["meta"]["ko_fix"]["from"] == r["text"]["ko"]
    assert out["text"]["en"] == r["text"]["en"]                      # English untouched
    again, rule2 = kofix.fix_record(copy.deepcopy(out))
    assert rule2 is None and again == out                           # idempotent


def test_a_template_text_gets_the_particle_back():
    r = _rec("template", "냉장고를 열고 오렌지 안에 넣어 줄래요?", "냉장고를 열고 오렌지 안에 넣어 줄래요?")
    r["meta"]["ko_particle_dropped"] = True
    out, rule = kofix.fix_record(copy.deepcopy(r))
    assert rule == "particle" and out["text"]["ko"] == "냉장고를 열고 오렌지를 안에 넣어 줄래요?"
    assert out["meta"]["template_text"]["ko"] == out["text"]["ko"] and not out["meta"]["ko_particle_dropped"]


def test_the_shipped_data_has_none():
    recs = [r for s in ("train", "dev", "test") for r in read_records(s)]
    assert kofix.problems(recs) == []
    fixed = {r["id"]: r for r in recs if (r.get("meta") or {}).get("ko_fix")}
    assert "hl-dev-000001" in fixed and fixed["hl-dev-000001"]["meta"]["ko_fix"]["how"] == "template_fallback"


def test_the_generator_keeps_the_particle_before_an_inside(monkeypatch):
    """open_put with the object particle dropped (the root cause): the patterns with 안에 keep it."""
    monkeypatch.setattr(CP, "ko_obj", lambda name, rng: (name, True))
    rng = random.Random(3)
    n = 0
    for h in list_houses():
        lex = Lex(from_house(h, 11))
        for c in CP.FAMILIES["open_put"](CP.Pools(lex), rng)[:3]:
            for nn in range(CP.N_PAT):
                r = CP.render(lex, c, rng, nn)
                if r is None:
                    continue
                n += 1
                assert kofix.object_as_container(r["ko"], h) == [], r["ko"]
    assert n > 0
