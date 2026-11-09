"""Generic text noise for data augmentation (own function, no simulator table): typing / hearing slips of a sentence.

Nothing here knows the benchmark. The noise is a few edits drawn from general slip types:

English  a letter replaced by a keyboard neighbour, a letter dropped, two letters swapped, a word dropped, a short word
         replaced by a common homophone, a word said twice.
Korean   one jamo of a syllable replaced by a confusable one (vowels ㅐ/ㅔ, ㅓ/ㅗ ...; plain / aspirated / tense initials;
         a final consonant dropped or changed), a syllable dropped, a space removed or added, a word dropped.

``protect`` lists phrases that must stay recognisable (the caller passes the entity phrases of the sentence): they are
never dropped or cut, at most one letter / jamo of them is replaced (a word of 4+ letters / 2+ syllables); words with a
negation, condition or self-correction marker are never edited, because an edit there can flip the meaning, so the label
would no longer be right. ``noisy(text, lang, rng)`` returns (new_text, [edit names]); the text is unchanged when no edit
applies (the caller then keeps no twin).
"""

from __future__ import annotations

import random
import re

# markers whose edit could change what is asked (never edited, never dropped)
MARKERS = {
    "en": {"not", "no", "don't", "dont", "never", "if", "sorry", "mean", "meant", "actually", "instead", "wait", "otherwise",
           "unless", "only", "then", "first", "before", "after"},
    "ko": ("아니", "말고", "않", "없으면", "있으면", "으면", "잠깐", "대신", "먼저", "다음", "전에", "후에", "말고요"),
}
KEY_NEIGHBOURS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij", "i": "uok", "o": "ipl", "p": "ol",
    "a": "qsz", "s": "awdx", "d": "sefc", "f": "drgv", "g": "fthb", "h": "gyjn", "j": "hukm", "k": "jil", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk"}
HOMOPHONES = {"to": "two", "for": "four", "there": "their", "your": "you're", "it's": "its", "the": "a", "a": "the",
              "then": "than", "here": "hear", "and": "an", "would": "wood", "right": "write", "know": "no"}
# words a slip may drop without changing what is asked (fillers and articles; a content word is never dropped)
DROPPABLE = {
    "en": {"the", "a", "an", "please", "could", "would", "can", "will", "just", "some", "hey", "okay", "ok", "also", "so",
           "really", "quickly", "now", "for", "that", "this", "you"},
    "ko": {"좀", "그냥", "혹시", "제발", "저기", "한번", "잠시", "잠깐만", "꼭", "빨리", "같이", "그리고", "그", "이"},
}
KO_PARTICLES = ("을", "를", "이", "가", "은", "는", "에", "에서", "으로", "로", "도", "랑", "하고")

# Hangul: syllable = 0xAC00 + (L * 21 + V) * 28 + T
_L, _V, _T = 19, 21, 28
L_CONF = {0: (15, 1), 15: (0,), 1: (0,), 3: (16, 4), 16: (3,), 4: (3,), 7: (17, 8), 17: (7,), 8: (7,), 12: (14, 13),
          14: (12,), 13: (12,), 9: (10,), 10: (9,)}                     # ㄱ/ㅋ/ㄲ, ㄷ/ㅌ/ㄸ, ㅂ/ㅍ/ㅃ, ㅈ/ㅊ/ㅉ, ㅅ/ㅆ
V_CONF = {1: (5,), 5: (1,), 4: (8,), 8: (4,), 6: (12,), 12: (6,), 13: (18,), 18: (13,), 11: (10, 15), 10: (11, 15),
          15: (10, 11), 0: (4,), 20: (18,)}                              # ㅐ/ㅔ, ㅓ/ㅗ, ㅕ/ㅛ, ㅜ/ㅡ, ㅚ/ㅙ/ㅞ, ㅏ/ㅓ, ㅣ/ㅡ
T_CONF = {4: (21,), 21: (4,), 1: (7,), 7: (1,), 8: (0,), 16: (0,), 17: (0,), 19: (20,), 20: (19,)}   # ㄴ/ㅇ, ㄱ/ㄷ, ㄹ, ㅁ, ㅂ, ㅅ/ㅆ


def _is_hangul(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3


def _jamo_slip(syl: str, rng: random.Random):
    """One syllable with one confusable jamo, or None."""
    n = ord(syl) - 0xAC00
    l, v, t = n // (_V * _T), (n // _T) % _V, n % _T
    opts = []
    if l in L_CONF:
        opts += [("L", x) for x in L_CONF[l]]
    if v in V_CONF:
        opts += [("V", x) for x in V_CONF[v]]
    if t and t in T_CONF:
        opts += [("T", x) for x in T_CONF[t]]
    if t:
        opts.append(("T", 0))
    if not opts:
        return None
    part, x = rng.choice(opts)
    l, v, t = (x, v, t) if part == "L" else (l, x, t) if part == "V" else (l, v, x)
    return chr(0xAC00 + (l * _V + v) * _T + t)


def _marked(word: str, lang: str) -> bool:
    w = word.lower()
    if lang == "en":
        return re.sub(r"[^a-z']", "", w) in MARKERS["en"]
    return w in ("안", "못") or any(m in w for m in MARKERS["ko"])


def _protected_spans(text: str, protect) -> list:
    spans = []
    low = text.lower()
    for p in protect or ():
        p = str(p).lower().strip()
        if len(p) < 2:
            continue
        for m in re.finditer(re.escape(p), low):
            spans.append((m.start(), m.end()))
    return spans


def _words(text: str) -> list:
    """[(start, end)] of the space-separated words."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _edit_en(text: str, rng: random.Random, prot: list):
    words = _words(text)
    if not words:
        return text, None
    inside = lambda s, e: any(a < e and s < b for a, b in prot)          # noqa: E731
    op = rng.choices(["sub", "del_char", "swap", "drop_word", "homophone", "repeat"], [3, 2, 2, 2, 1, 1])[0]
    order = list(range(len(words)))
    rng.shuffle(order)
    for i in order:
        s, e = words[i]
        w = text[s:e]
        core = re.sub(r"[^A-Za-z]", "", w)
        if _marked(w, "en"):
            continue
        if op == "drop_word":
            if inside(s, e) or len(words) < 4 or w.lower().strip(".,!?") not in DROPPABLE["en"] or w[-1:] in ".,!?":
                continue
            return (text[:s] + text[e:]).replace("  ", " ").strip(), "drop_word"
        if op == "homophone":
            k = w.lower().strip(".,!?")
            if k in HOMOPHONES:
                return text[:s] + HOMOPHONES[k] + text[s + len(k):], "homophone"
            continue
        if op == "repeat":
            if len(core) < 2:
                continue
            return text[:e] + " " + w.strip(".,!?") + text[e:], "repeat_word"
        if len(core) < 3 or inside(s, e) and (op != "sub" or len(core) < 4):
            continue                          # an entity word only gets one letter replaced, never cut
        letters = [j for j in range(s, e) if text[j].isalpha()]
        j = rng.choice(letters[1:]) if len(letters) > 1 else letters[0]
        if op == "sub":
            nb = KEY_NEIGHBOURS.get(text[j].lower())
            if not nb:
                continue
            c = rng.choice(nb)
            return text[:j] + (c.upper() if text[j].isupper() else c) + text[j + 1:], "char_sub"
        if op == "del_char":
            return text[:j] + text[j + 1:], "char_drop"
        if op == "swap" and j + 1 < e and text[j + 1].isalpha():
            return text[:j] + text[j + 1] + text[j] + text[j + 2:], "char_swap"
    return text, None


def _edit_ko(text: str, rng: random.Random, prot: list):
    words = _words(text)
    if not words:
        return text, None
    inside = lambda s, e: any(a < e and s < b for a, b in prot)          # noqa: E731
    op = rng.choices(["jamo", "drop_syl", "space", "drop_word", "particle"], [5, 2, 2, 1, 2])[0]
    order = list(range(len(words)))
    rng.shuffle(order)
    for i in order:
        s, e = words[i]
        w = text[s:e]
        if _marked(w, "ko"):
            continue
        hs = [j for j in range(s, e) if _is_hangul(text[j])]
        if op == "drop_word":
            if inside(s, e) or len(words) < 4 or w.strip(".,!?") not in DROPPABLE["ko"] or w[-1:] in ".,!?":
                continue
            return (text[:s] + text[e:]).replace("  ", " ").strip(), "drop_word"
        if op == "particle":                                  # a case particle not heard ("수건을" -> "수건")
            core = w.rstrip(".,!?")
            if inside(s + len(core) - 1, s + len(core)):
                continue                                      # the last letter belongs to an entity name
            p = next((x for x in sorted(KO_PARTICLES, key=len, reverse=True)
                      if core.endswith(x) and len(core) > len(x) + 1), None)
            if p is None:
                continue
            return text[:s] + core[: -len(p)] + w[len(core):] + text[e:], "particle_drop"
        if op == "space":
            if i + 1 < len(words) and rng.random() < 0.5:
                return text[:e] + text[e + 1:], "space_drop"          # two words run together
            if len(hs) >= 3:
                j = rng.choice(hs[1:-1])
                return text[:j] + " " + text[j:], "space_add"
            continue
        if op == "drop_syl":
            if len(hs) < 3 or inside(s, e):
                continue
            j = rng.choice(hs[1:])
            return text[:j] + text[j + 1:], "syllable_drop"
        if not hs or inside(s, e) and len(hs) < 2:
            continue
        j = rng.choice(hs)
        new = _jamo_slip(text[j], rng)
        if new is not None:
            return text[:j] + new + text[j + 1:], "jamo_sub"
    return text, None


def noisy(text: str, lang: str, rng: random.Random, protect=(), max_edits: int = 2):
    """(text with 1..max_edits generic slips, [edit names]). ``protect``: phrases never dropped."""
    k = 1 if max_edits <= 1 or rng.random() < 0.6 else max_edits
    edits, out = [], text
    edit = _edit_en if lang == "en" else _edit_ko
    for _ in range(k):
        prot = _protected_spans(out, protect)
        new, name = edit(out, rng, prot)
        if name is None:
            new, name = edit(out, rng, prot)                 # one more draw of another edit type
        if name is not None and new != out:
            out = new
            edits.append(name)
    return out, edits
