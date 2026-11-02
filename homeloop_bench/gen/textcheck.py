"""Language rule R-g (DESIGN 13.2): no template residue, no repeated words, English without Hangul, Korean in
Hangul (allow-listed letters only) with a consistent 해요체 speech level, length bounds per task type."""

from __future__ import annotations

import re

RESIDUE = re.compile(r"[{}<>\[\]]|\bNone\b|\bnull\b|_")
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
HANGUL = re.compile(r"[가-힣]")
# Latin tokens allowed in Korean text: the TV and the shared flat's room letters ("A 방", "B 룸메이트")
KO_LATIN_OK = {"TV", "A", "B", "C"}
# a Korean sentence ends in 해요체: -요 / -세요 / -죠 (with -요 after any stem: 줄래요, 있어요, 주고요, 거예요)
KO_END = re.compile(r"(요|죠)[.?!]?$")
LEN = {"single": {"en": (3, 50), "ko": (2, 35)}, "compound": {"en": (8, 95), "ko": (5, 70)}}


def words(text: str, lang: str) -> int:
    """English words; Korean 어절 (space-separated units)."""
    if lang == "en":
        return len(re.findall(r"[A-Za-z0-9']+", text))
    return len(text.split())


def sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s.strip()]


def check_text(text: str, lang: str, compound: bool = False) -> list:
    """Problems of one text (empty list = passes R-g)."""
    errs = []
    if not text or not text.strip():
        return ["empty text"]
    if RESIDUE.search(text):
        errs.append(f"template residue in {text!r}")
    toks = re.findall(r"\w+", text.lower())
    for a, b in zip(toks, toks[1:]):
        if a == b and a not in ("아니",):
            errs.append(f"repeated word {a!r}")
            break
    lo, hi = LEN["compound" if compound else "single"][lang]
    n = words(text, lang)
    if not lo <= n <= hi:
        errs.append(f"length {n} outside {lo}-{hi}")
    if lang == "en":
        if HANGUL.search(text):
            errs.append("Hangul in English text")
        if CJK.search(text):
            errs.append("CJK characters in English text")
        if not re.search(r"[.?!]$", text.strip()):
            errs.append("English text without final punctuation")
    else:
        if CJK.search(text):
            errs.append("Chinese / Japanese characters in Korean text")
        latin = [x for x in re.findall(r"[A-Za-z]+", text) if x not in KO_LATIN_OK]
        if latin:
            errs.append(f"non-Hangul words {latin}")
        letters = re.findall(r"[가-힣A-Za-z]", text)
        if letters and sum(1 for c in letters if "가" <= c <= "힣") / len(letters) < 0.9:
            errs.append("< 90 % Hangul letters")
        for s in sentences(text):
            if not KO_END.search(s):
                errs.append(f"sentence not in 해요체: {s!r}")
                break
    return errs
