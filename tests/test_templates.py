import random
import re

from homeloop_robot.houses import list_houses
from homeloop_robot.world import from_house

from homeloop_bench.gen import compound as CP
from homeloop_bench.gen import families as F
from homeloop_bench.gen import templates_en as EN
from homeloop_bench.gen import templates_ko as KO
from homeloop_bench.gen.single import render
from homeloop_bench.gen.lexicon import Lex
from homeloop_bench.gen.textcheck import check_text

FORMS = ("q", "q2", "q3", "imp", "imp2", "and", "and2", "seq", "after")


def test_korean_verbs_have_all_forms_in_haeyo():
    for verb, forms in KO.V.items():
        for f in FORMS:
            assert f in forms, (verb, f)
        for f in ("q", "q2", "q3", "imp", "imp2"):
            assert re.search(r"요[.?]$", forms[f]), (verb, f, forms[f])


def test_korean_patterns_end_with_their_verb():
    for key, pats in KO.VP.items():
        for pat, verb in pats:
            assert verb in KO.V, (key, verb)
            assert pat.endswith(verb), (key, pat)


def test_paired_banks_align():
    assert set(EN.REASON) == set(KO.REASON)
    for k in EN.REASON:
        assert len(EN.REASON[k]) == len(KO.REASON[k]), k
    assert set(EN.REFUSE_WHY) == set(KO.REFUSE_WHY)
    assert set(EN.MSG) == set(KO.MSG)
    assert len(EN.SEARCH_PRE) == len(KO.SEARCH_PRE)
    assert set(CP.CTX_EN) == set(CP.CTX_KO)
    assert len(CP.DOCK_EN) == len(CP.DOCK_KO) == CP.N_PAT
    for pats in (CP.EN_SEQ2, CP.EN_CONJ2, CP.EN_CONJ3, CP.EN_ORD, CP.EN_ORD3, CP.EN_TIDY, CP.KO_SEQ2, CP.KO_CONJ2,
                 CP.KO_CONJ3, CP.KO_ORD, CP.KO_ORD3, CP.EN_ERRAND, CP.KO_ERRAND):
        assert len(pats) == CP.N_PAT


def test_test_only_ids_are_a_fifth():
    assert 0.15 <= len(EN.WRAP_TEST) / len(EN.WRAP) <= 0.25          # 2 of 11 wrappers (DESIGN 10.3: ~20 %)
    assert len(CP.TEST_PATTERNS) / CP.N_PAT == 0.2


def _ok(errs, fam, text):
    """Rendering never leaves residue, repeats a word or breaks the language rules; a text that is too short or
    too long for its type is possible (the sampler rejects it)."""
    hard = [e for e in errs if not e.startswith("length")]
    assert not hard, (fam, text, hard)


def test_every_family_renders_clean_text_somewhere():
    rng = random.Random(7)
    seen = set()
    for h in list_houses():
        lex = Lex(from_house(h, 11))
        for fam, fn in F.FAMILIES.items():
            for op in list(fn(lex))[:3]:
                r = render(lex, op, rng, rng.randrange(len(EN.WRAP)))
                if r is None:
                    continue
                for lg in ("en", "ko"):
                    _ok(check_text(r[lg], lg), fam, r[lg])
                seen.add(fam)
        P = CP.Pools(lex)
        for fam, fn in CP.FAMILIES.items():
            cands = fn(P, rng)
            for c in cands[:2]:
                r = CP.render(lex, c, rng, rng.randrange(CP.N_PAT))
                if r is None:
                    continue
                for lg in ("en", "ko"):
                    _ok(check_text(r[lg], lg, compound=True), fam, r[lg])
                seen.add("c:" + fam)
    assert len([s for s in seen if not s.startswith("c:")]) >= 13
    assert len([s for s in seen if s.startswith("c:")]) >= 25
