"""Korean particles (josa) chosen from the final consonant of the last syllable (DESIGN 10.3).

``josa(word, "을")`` -> word + 을/를; pairs: 을/를, 이/가, 은/는, 과/와, 으로/로, 이랑/랑, 이요/요, 이에요/예요,
아/야, 이나/나. For 으로/로 a final ㄹ takes 로. Latin letters and digits use their Korean reading ("TV" -> 티비,
no final consonant; "A 방" ends in 방).
"""

from __future__ import annotations

PAIRS = {"을/를": ("을", "를"), "이/가": ("이", "가"), "은/는": ("은", "는"), "과/와": ("과", "와"),
         "으로/로": ("으로", "로"), "이랑/랑": ("이랑", "랑"), "이요/요": ("이요", "요"),
         "이에요/예요": ("이에요", "예요"), "아/야": ("아", "야"), "이나/나": ("이나", "나")}
SHORT = {}
for _pair, (_a, _b) in PAIRS.items():
    SHORT[_a] = _pair
    SHORT[_b] = _pair
    SHORT[_pair] = _pair

# Latin letters / digits read aloud: does the reading end in a consonant? ('l' = ㄹ)
_LATIN_FINAL = {"l": "l", "m": "c", "n": "c", "r": "v"}
_DIGIT_FINAL = {"0": "c", "1": "l", "3": "c", "6": "c", "7": "l", "8": "l"}


def final(word: str) -> str:
    """'v' (no final consonant) | 'c' (final consonant) | 'l' (final ㄹ)."""
    w = word.rstrip(" )\"'.,?!")
    if not w:
        return "v"
    ch = w[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        jong = (code - 0xAC00) % 28
        return "v" if jong == 0 else ("l" if jong == 8 else "c")
    if ch.isdigit():
        return _DIGIT_FINAL.get(ch, "v")
    return _LATIN_FINAL.get(ch.lower(), "v")


def josa(word: str, pair: str) -> str:
    pair = SHORT.get(pair, pair)
    a, b = PAIRS[pair]
    f = final(word)
    if pair == "으로/로":
        return word + (b if f in ("v", "l") else a)
    return word + (a if f in ("c", "l") else b)


def has_batchim(word: str) -> bool:
    return final(word) != "v"
