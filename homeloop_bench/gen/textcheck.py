"""Language rule R-g (DESIGN 13.2): no template residue, no repeated words, English without Hangul, Korean in
Hangul (allow-listed letters only) with a consistent 해요체 speech level, length bounds per task type."""

from __future__ import annotations

import re

RESIDUE = re.compile(r"[{}<>\[\]]|\bNone\b|\bnull\b|_")
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
HANGUL = re.compile(r"[가-힣]")
# Latin tokens allowed in Korean text: the TV
KO_LATIN_OK = {"TV"}
# letter placeholders instead of names ("roommate B", "room A", "B 룸메이트", "A 방")
LETTER_NAME = re.compile(r"\b(roommate|room|person|user|guest)\s+[A-Z]\b|\b[A-Z]\s+(룸메이트|방)|[A-Z]\s*룸메이트")
# a Korean sentence ends in 해요체: -요 / -세요 / -죠 (with -요 after any stem: 줄래요, 있어요, 주고요, 거예요)
KO_END = re.compile(r"(요|죠)[.?!]?$")
# an article before a possessive ("the my desk")
EN_ART_POSS = re.compile(r"\b[Tt]he (my|your|our|his|her|their)\b")
# an imperative with a question mark ("가져다 주세요?"), USER_FEEDBACK 9
KO_IMP_Q = re.compile(r"(주세요|줘요|하세요|둬요)\?")
# subject honorifics that Koreans do not put on their own family members (USER_FEEDBACK 9)
KO_BAD_HON = re.compile(r"(남편님|딸님|아들님|아내님)")
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
    if LETTER_NAME.search(text):
        errs.append(f"letter placeholder name in {text!r}")
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
        if EN_ART_POSS.search(text):
            errs.append("article before a possessive")
    else:
        if CJK.search(text):
            errs.append("Chinese / Japanese characters in Korean text")
        latin = [x for x in re.findall(r"[A-Za-z]+", text) if x not in KO_LATIN_OK]
        if latin:
            errs.append(f"non-Hangul words {latin}")
        if KO_IMP_Q.search(text):
            errs.append("imperative with a question mark")
        if KO_BAD_HON.search(text):
            errs.append("honorific suffix on a family member")
        letters = re.findall(r"[가-힣A-Za-z]", text)
        if letters and sum(1 for c in letters if "가" <= c <= "힣") / len(letters) < 0.9:
            errs.append("< 90 % Hangul letters")
        for s in sentences(text):
            if not KO_END.search(s):
                errs.append(f"sentence not in 해요체: {s!r}")
                break
    return errs
