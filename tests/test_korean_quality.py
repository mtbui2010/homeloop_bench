"""Korean quality of the shipped tasks (USER_FEEDBACK 5, 9; the checker's "Korean quality" line)."""

import re

import pytest

from homeloop_bench.gen.paraphrase import KO_WRITER, ko_banmal_end
from homeloop_bench.gen.textcheck import sentences
from homeloop_bench.tasks import read_records

RECS = [r for s in ("train", "dev", "test") for r in read_records(s)]


@pytest.mark.parametrize("pat,name", [(r"[㐀-鿿぀-ヿ]", "CJK"), (r"(주세요|줘요|하세요|둬요)\?", "imperative question"),
                                      (r"(남편님|딸님|아들님|아내님)", "wrong honorific")])
def test_no_korean_error_pattern(pat, name):
    bad = [r["id"] for r in RECS if re.search(pat, r["text"]["ko"])]
    assert not bad, (name, bad[:5])


def test_no_banmal_unless_labelled():
    bad = [r["id"] for r in RECS if not (r.get("meta") or {}).get("banmal")
           and any(ko_banmal_end(s) for s in sentences(r["text"]["ko"]))]
    assert not bad, bad[:5]


def test_dropped_particles_in_moderation():
    share = sum(1 for r in RECS if r["meta"].get("ko_particle_dropped")) / len(RECS)
    assert share <= 0.30


def test_per_language_sources_and_models():
    n = len(RECS)
    ko = [r for r in RECS if r["source_by_lang"]["ko"] == "llm_paraphrase"]
    en = [r for r in RECS if r["source_by_lang"]["en"] == "llm_paraphrase"]
    assert len(ko) >= 0.25 * n
    assert all(r["paraphrase_model"]["ko"] == KO_WRITER for r in ko)
    assert sum(1 for r in RECS if r["source"] == "llm_paraphrase") >= 0.15 * n
    for r in RECS:
        any_para = "llm_paraphrase" in r["source_by_lang"].values()
        assert (r["source"] == "llm_paraphrase") == any_para, r["id"]
        for lg in ("en", "ko"):
            if r["source_by_lang"][lg] == "template" and r["meta"].get("template_text"):
                assert r["text"][lg] == r["meta"]["template_text"][lg], r["id"]
    assert en, "no English paraphrases"
