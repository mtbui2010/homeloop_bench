"""LLM paraphrases (DESIGN 10.5; docs/generation.md "Paraphrases"; USER_FEEDBACK 9).

Local models only: Ollama on GPU 0 through ``tools/llm_gpu0.sh`` (http://127.0.0.1:11536). The two languages are
paraphrased independently, each with its own writer and judge:
  English  writer + same-meaning judge qwen3-vl:8b-instruct (prompt p1)
  Korean   writer exaone3.5:latest (LG EXAONE 3.5, Korean-specialised; prompt k2, 해요체 asked explicitly);
           judge and back-translator qwen3-vl:30b-a3b-instruct (meaning, objects, places, people, order and
           corrections kept, 해요체, the robot is the one asked, no typos or non-words)
One request per item and language (the cache is then robust to changes elsewhere in the data):
  para_en / para_ko2  rewrite the request         (temperature 0.8, seed per item and round)
  back                translate Korean to English (temperature 0): the Korean paraphrase, and the Korean template
  judge / judge_ko    same-meaning check          (temperature 0)
Caches: ``homeloop_bench/data/llm_cache/paraphrase.jsonl`` (English) and ``paraphrase_ko.jsonl`` (Korean), one line
per response {"sha", "model", "options", "task", "prompt_version", "input", "response"}
``sha`` = sha256 of (model, options, full prompt); the full prompt is rebuilt from ``task`` + ``input`` by the code
below, so the cache stays small and reruns need no GPU (``--offline``). The run is resumable: every response is
appended as it arrives.

A language's text is replaced only when the candidate passes every deterministic filter (``filters``), the judge,
and, for Korean, the back-translation check (chrF >= CHRF_MIN against the better of the English template and the
back-translated Korean template). Otherwise that language keeps the template text. Each record carries
``source_by_lang`` {en, ko} (template | llm_paraphrase) and ``paraphrase_model`` {en, ko}; the top-level ``source`` is
``llm_paraphrase`` when at least one language was paraphrased (docs/datasheet.md gives the per-language counts).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
import threading
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from homeloop_robot.catalog import CLASSES, COLORS
from homeloop_robot.houses import list_houses, load_house
from homeloop_robot.rng import derive_seed

from ..data import CACHE_DIR, QUALITY_DIR, SPLITS, TASKS_DIR
from .chrf import chrf
from .dedup import NearDupIndex, norm
from .textcheck import KO_BAD_HON, check_text, sentences, words

PROMPT_VERSION = "p1"          # English prompts (unchanged since the first run; the cache is keyed on them)
KO_PROMPT_VERSION = "k2"       # Korean prompts for the exaone3.5 writer and the qwen3-vl:30b judge
EN_MODEL = "qwen3-vl:8b-instruct"
KO_WRITER = "exaone3.5:latest"
KO_JUDGE = "qwen3-vl:30b-a3b-instruct"
CHRF_MIN = 35.0
CACHE = CACHE_DIR / "paraphrase.jsonl"
CACHE_KO = CACHE_DIR / "paraphrase_ko.jsonl"
LEAK = re.compile(r"paraphras|json|rewrite|template|\bitems?\b|\bkeep\b|패러프레이즈|다시 쓰|원문", re.I)

PROMPT = {
    "para_en": (
        "You rewrite a request that a family member says out loud to their home robot. Write ONE natural spoken "
        "English variant with exactly the same meaning and the same goal. Keep every phrase listed under 'keep' "
        "(articles and my/the may change). Do not add any object, place, person, colour or detail that is not in "
        "the original, and do not drop any task (who gets each object and where each one goes must stay the same). "
        "Change the wording or the sentence structure, not only the politeness phrase. Keep it casual, like real "
        "speech.{compound}\nAnswer only JSON: {{\"text\": \"...\"}}\n\nOriginal: {text}\nKeep: {keep}"),
    "para_ko": (
        "가정용 로봇에게 가족이 말로 하는 부탁을 다른 표현으로 바꿔 써 주세요. 뜻과 목표가 똑같은 자연스러운 한국어 구어체 "
        "문장을 하나만 쓰세요. 모든 문장은 해요체(-요, -세요)로 끝내고 반말은 쓰지 마세요. 'keep'에 있는 표현은 그대로 넣고"
        "(조사는 바꿔도 돼요), 원문에 없는 물건, 장소, 사람, 색깔, 정보는 더하지 말고, 있는 일도 빼지 마세요(누구에게 주는지, "
        "어디에 두는지도 그대로). 끝맺음만 바꾸지 말고 단어나 문장 구성을 바꿔 주세요. '주세요?'처럼 명령형에 물음표를 붙이지 "
        "마세요.{compound}\nJSON으로만 답하세요: {{\"text\": \"...\"}}\n\n원문: {text}\nkeep: {keep}"),
    "para_ko2": (
        "가정용 로봇에게 집에 사는 사람이 말로 하는 부탁이에요. 뜻이 똑같은 자연스러운 한국어 구어 문장으로 한 번 바꿔 말해 "
        "주세요.\n규칙:\n"
        "1. 모든 문장을 해요체로 끝내세요(예: ~해 줄래요?, ~해 주세요., ~해 줄 수 있어요?, ~해 주실래요?). 반말(~해, ~줘, "
        "~줄래?, ~니?, ~할래?, ~겠니?)과 합쇼체(~합니다, ~하십시오)는 쓰지 마세요.\n"
        "2. 부탁을 받는 쪽은 로봇이에요. 말하는 사람이 로봇에게 시키는 말로 쓰고, '가져다 드릴게요'처럼 말하는 사람이 "
        "직접 하겠다는 말로 바꾸지 마세요.\n"
        "3. 'keep'에 있는 표현은 글자 그대로 넣으세요(뒤에 붙는 조사만 바꿔도 돼요). 비슷한 말로 바꾸지 마세요.\n"
        "4. 원문에 없는 물건, 장소, 사람, 색깔, 조건은 더하지 말고, 원문에 있는 일은 하나도 빼지 마세요. 누구에게 주는지, "
        "어디에 두는지도 그대로 두세요.\n"
        "5. 끝맺음만 바꾸지 말고 단어 선택이나 문장 구조를 바꾸세요.\n"
        "6. 사람을 부르는 말은 원문 그대로 쓰세요(원문이 '남편한테'면 '남편한테'나 '남편에게'). '남편님', '아들님', "
        "'딸님'처럼 가족에게 '님'을 붙이지 말고, 로봇에게 '가셔서', '마치시면'처럼 높여 말하지 마세요.\n"
        "7. '주세요?'처럼 명령형 뒤에 물음표를 붙이지 마세요. 한자, 일본어, 영어를 쓰지 말고, '~하겠습니다', "
        "'감사하겠습니다' 같은 합쇼체도 쓰지 마세요.{compound}\n"
        "JSON으로만 답하세요: {{\"text\": \"...\"}}\n\n원문: {text}\nkeep: {keep}"),
    "judge_ko": (
        "You check a Korean paraphrase of a request that a person says out loud to their home robot.\n"
        "A (original): {a}\nB (paraphrase): {text}\n\n"
        "Answer each question with true or false.\n"
        "same_meaning: B asks the robot to do exactly the same things as A: the same actions on the same objects, "
        "places and people, nothing added and nothing left out, the same order, the same if / otherwise conditions, "
        "and the same self-correction if A has one. Reasons, greetings and politeness words may differ.\n"
        "robot_asked: in B the speaker asks the robot to do it (B is not the speaker offering to do it, and not "
        "addressed to someone else).\n"
        "haeyo: every sentence of B ends in the polite 해요체 (-요) style: no 반말, no 합쇼체, and no imperative "
        "ending with a question mark such as 주세요?.\n"
        "fluent: B is natural, correct spoken Korean: no typos, no made-up words, no Chinese or Japanese characters, "
        "no wrong honorifics such as 남편님 or 딸님.\n"
        "Answer only JSON: {{\"same_meaning\": true, \"robot_asked\": true, \"haeyo\": true, \"fluent\": true}} "
        "with each value set to your answer."),
    "back": ("Translate this Korean sentence into natural English. Answer only JSON: {{\"text\": \"...\"}}\n\n"
             "Korean: {text}"),
    "judge": ("Request A and request B were said to a home robot. Do they ask the robot to do exactly the same "
              "things: the same actions on the same objects, places and people, nothing added and nothing left out, "
              "the same conditions (if / otherwise) and order, and the same self-correction if A has one? Reasons, "
              "greetings and politeness may differ. Answer only JSON: {{\"same\": true}} or {{\"same\": false}}."
              "\n\nA: {a}\nB: {text}"),
}
COMPOUND_NOTE = {
    "para_en": " The request holds several tasks: keep every task, its order words (first, then), its if/otherwise "
               "branches and any self-correction ('no wait, the other one') exactly as meant.",
    "para_ko2": " 여러 가지 일을 한 번에 부탁하는 말이에요. 모든 일을 빠짐없이 두고, 순서(먼저, 그다음에), "
                "조건(있으면/없으면), 말을 고치는 부분(아니, 잠깐만요, ~ 말고)도 뜻이 그대로 유지되게 쓰세요.",
    "para_ko": " 여러 가지 일을 한 번에 부탁하는 말이에요. 모든 일을 빠짐없이 두고, 순서(먼저, 그다음에), 조건(있으면/없으면), "
               "말을 고치는 부분(아니, 잠깐만요, ~ 말고)도 뜻이 그대로 유지되게 써 주세요.",
}
OPTIONS = {"para": {"temperature": 0.8, "num_predict": 256, "num_ctx": 2048},
           "back": {"temperature": 0.0, "num_predict": 256, "num_ctx": 2048},
           "judge": {"temperature": 0.0, "num_predict": 32, "num_ctx": 2048},
           "judge_ko": {"temperature": 0.0, "num_predict": 64, "num_ctx": 2048}}


# ── cache + LLM ──────────────────────────────────────────────────────────────────────────────────────
class Cache:
    def __init__(self, path=CACHE):
        self.path = path
        self.lock = threading.Lock()
        self.d = {}
        if path.exists():
            for line in open(path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    self.d[r["sha"]] = r

    def put(self, rec):
        with self.lock:
            if rec["sha"] in self.d:
                return
            self.d[rec["sha"]] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_prompt(task: str, inp: dict) -> str:
    tpl = PROMPT[task]
    comp = COMPOUND_NOTE.get(task, "") if inp.get("compound") else ""
    return tpl.format(text=inp["text"], keep=json.dumps(inp.get("keep", []), ensure_ascii=False), compound=comp,
                      a=inp.get("a", ""))


def request_sha(model: str, options: dict, prompt: str) -> str:
    return hashlib.sha256(json.dumps([model, options, prompt], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class LLM:
    def __init__(self, url, model, cache: Cache, offline=False):
        self.url, self.model, self.cache, self.offline = url.rstrip("/"), model, cache, offline
        self.n_calls = 0
        self.n_miss = 0

    def ask(self, task: str, inp: dict, seed: int) -> tuple:
        """(response text or "", sha)."""
        opts = dict(OPTIONS[task if task in ("back", "judge", "judge_ko") else "para"], seed=int(seed) % 2**31)
        prompt = build_prompt(task, inp)
        sha = request_sha(self.model, opts, prompt)
        hit = self.cache.d.get(sha)
        if hit is not None:
            return _decode(task, hit["response"]), sha
        if self.offline:
            self.n_miss += 1
            return "", sha
        body = json.dumps({"model": self.model, "prompt": prompt, "format": "json", "stream": False,
                           "options": opts, "think": False}).encode()
        req = urllib.request.Request(self.url + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.loads(r.read())["response"]
        except Exception as e:  # noqa: BLE001 - one failed request must not stop a multi-hour run
            print(f"llm error {type(e).__name__}: {e}", file=sys.stderr)
            return "", sha
        self.n_calls += 1
        self.cache.put({"sha": sha, "model": self.model, "options": opts, "task": task,
                        "prompt_version": PROMPT_VERSION, "input": inp, "response": resp})
        return _decode(task, resp), sha


def _decode(task: str, resp: str) -> str:
    if task == "judge":
        return _judge(resp)
    if task == "judge_ko":
        return _judge_ko(resp)
    return _parse(resp)


JUDGE_KO_KEYS = ("same_meaning", "robot_asked", "haeyo", "fluent")


def _judge_ko(resp: str) -> str:
    """"same" when the judge says true to all four questions, else the first failed one ("not_haeyo" ...)."""
    try:
        d = json.loads(resp)
    except Exception:  # noqa: BLE001
        return "unparsed"
    if not isinstance(d, dict):
        return "unparsed"
    for k in JUDGE_KO_KEYS:
        if d.get(k) is not True:
            return "not_" + k
    return "same"


def _judge(resp: str) -> str:
    try:
        d = json.loads(resp)
        return "same" if isinstance(d, dict) and d.get("same") is True else "different"
    except Exception:  # noqa: BLE001
        return "different"


def _parse(resp: str) -> str:
    try:
        d = json.loads(resp)
        t = d.get("text") if isinstance(d, dict) else None
        if isinstance(t, list):
            t = " ".join(str(x) for x in t)
        return clean(str(t or ""))
    except Exception:  # noqa: BLE001
        return ""


def clean(t: str) -> str:
    t = t.replace("’", "'").replace("‘", "'").replace("—", ", ").replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t).replace(" ,", ",").replace(",,", ",").strip().strip('"').strip()
    return t


# ── filters ──────────────────────────────────────────────────────────────────────────────────────────
def _names():
    out = {"en": set(), "ko": set()}
    for c in CLASSES.values():
        for lg in out:
            out[lg].add(norm(c.name[lg], lg))
            out[lg].update(norm(a, lg) for a in (c.aliases or {}).get(lg) or [])
    for h in list_houses():
        H = load_house(h)
        for p in H.places.values():
            if p.kind in ("floor", "dock"):
                continue
            for lg in out:
                out[lg].add(norm(p.name.get(lg, ""), lg))
                out[lg].update(norm(a, lg) for a in (p.aliases or {}).get(lg) or [])
        for per in H.people:
            for lg in out:
                out[lg].add(norm(per.name.get(lg, ""), lg))
    return {lg: sorted((n for n in s if len(n) >= 2), key=len, reverse=True) for lg, s in out.items()}


_NAMES = None
COLOR_WORDS = {lg: sorted({COLORS[c][lg] for c in COLORS}) for lg in ("en", "ko")}
# politeness / wrapper words removed before the "only the ending changed" check (USER_FEEDBACK 2)
EN_WRAP = re.compile(r"\b(could|can|would|will|you|please|for me|hey|just|kindly|do me a favor and|i'd like you to|"
                     r"i need you to|when you get a chance|when you have a moment|mind)\b", re.I)
KO_END = re.compile(r"(줄래요|줄 수 있어요|주실래요|주세요|줘요|주실 수 있어요|주시겠어요|줄래|주실래|해 줘|"
                    r"요|좀|을|를|이|가|은|는|에|에게|한테|께)")


def _core(t: str, lang: str) -> str:
    if lang == "en":
        t = EN_WRAP.sub(" ", t.lower())
        return re.sub(r"[^a-z0-9]", "", t)
    t = re.sub(r"[^가-힣0-9 ]", " ", t)
    toks = [KO_END.sub("", w) for w in t.split()]
    return "".join(toks)


def has_phrase(normed_text: str, phrase: str, lang: str) -> bool:
    """Phrase in a normalised text: whole words in English, a substring in Korean (particles attach)."""
    p = norm(phrase, lang)
    if not p:
        return False
    if lang == "ko":
        return p in normed_text
    return re.search(rf"(^| ){re.escape(p)}( |$)", normed_text) is not None


KO_REQUEST = re.compile(r"(주세요|줘요|줄래요|줄 수 있어요|주실래요|주시겠어요|주실 수 있어요|세요|둘래요|둘 수 있어요|"
                        r"두실래요|둬요|부탁해요|돌아가요|드릴래요|드릴 수 있어요|가 있어요|돼요|수 있나요\?|주시겠어요|주실래요|"
                        r"수 있을까요\?|주시겠어요\?|줄래요\?)")
KO_BANMAL = re.compile(r"(거야|이야|했어(?!요)|할래(?!요)|해줘(?!요)|줘(?![요 서야도])|가져와(?=[.?!,]|$)|해\.|줄래(?!요)|"
                       r"니\?|냐\?|할게(?!요)|놔(?![ 요두둬주서야])|있어(?![요서 야도]))")


# a sentence that ends in 반말 (the checker's rule, per sentence): …해 / 줘 / 돼 / 자 / 니 / 렴 / 겠니 / 줄래? / 어? / 아?
_BANMAL_END = re.compile(r"(겠니|렴|줄래|해|줘|돼|자|니|어|아)[?.!]?\s*$")
_POLITE_END = re.compile(r"(해요|줘요|돼요|세요|어요|아요|예요|이에요|까요|래요|게요|네요|죠)[?.!]?\s*$")
KO_ROBOT_HON = re.compile(r"께 가셔서|가셔서 (전해|말씀)")


def ko_banmal_end(sentence: str) -> bool:
    s = sentence.strip()
    if len(s.split()) <= 1 and re.fullmatch(r"(아니|아니다|아|어|잠깐|잠깐만)[.,!?]*", s):
        return False                         # an interjection inside a self-correction ("아니.")
    return bool(_BANMAL_END.search(s)) and not _POLITE_END.search(s)


def filters(rec: dict, lang: str, para: str, near: NearDupIndex | None = None, seen: dict | None = None) -> list:
    """Reasons to reject a paraphrase (empty list = accepted)."""
    global _NAMES
    if _NAMES is None:
        _NAMES = _names()
    tpl = rec["text"][lang]
    why = []
    if not para:
        return ["empty"]
    if norm(para, lang) == norm(tpl, lang):
        return ["unchanged"]
    sim = difflib.SequenceMatcher(None, re.sub(r"\W", "", tpl.lower()), re.sub(r"\W", "", para.lower())).ratio()
    if sim >= 0.85:
        why.append("too_similar")
    c1, c2 = _core(tpl, lang), _core(para, lang)
    if c1 == c2 or difflib.SequenceMatcher(None, c1, c2).ratio() >= 0.92:
        why.append("ending_only")
    ratio = len(para) / max(1, len(tpl))
    if not 0.5 <= ratio <= 2.0:
        why.append("length_ratio")
    if LEAK.search(para):
        why.append("instruction_leak")
    np_ = norm(para, lang)
    ents = (rec.get("meta") or {}).get("entities", {}).get(lang, [])
    for alts in ents:
        if not any(has_phrase(np_, a, lang) for a in alts):
            why.append("entity_missing")
            break
    nt = norm(tpl, lang)
    allowed = {norm(a, lang) for alts in ents for a in alts}
    for name in _NAMES[lang]:
        if name in np_ and name not in nt and not any(name in a or a in name for a in allowed if a):
            why.append("new_entity")
            break
    for cw in COLOR_WORDS[lang]:
        pat = rf"(^|\W){re.escape(cw)}(\W|$)"
        if re.search(pat, para, re.I) and not re.search(pat, tpl, re.I):
            why.append("new_colour")
            break
    if re.search(r"[぀-ヿ㐀-鿿]", para):
        why.append("foreign_script")
    if lang == "en" and re.search(r"[가-힣]", para):
        why.append("hangul_in_en")
    if lang == "ko":
        if re.search(r"드릴게|드려요|드릴까요", para) and not re.search(r"드릴게|드려요|드릴까요", tpl):
            why.append("speaker_role_flip")       # the speaker offers instead of asking: meaning changed
        if re.search(r"(세요|줘요|둬요)\?", para):
            why.append("ko_imperative_question")
        if re.search(r"줘 주|주시면 고마워요|부탁드립니다|하십시오|합니다\b", para):
            why.append("ko_register")
        letters = re.findall(r"[가-힣A-Za-z]", para)
        if letters and sum(1 for c in letters if "가" <= c <= "힣") / len(letters) < 0.5:
            why.append("ko_hangul_lt_50")
        if not KO_REQUEST.search(para):
            why.append("ko_no_request")            # a statement ("정리해 놓아요.") instead of a request
        if KO_BANMAL.search(para) or any(ko_banmal_end(x) for x in sentences(para)):
            why.append("ko_banmal")
        if KO_BAD_HON.search(para) or KO_ROBOT_HON.search(para):
            why.append("ko_wrong_honorific")       # 남편님 / 딸님, or subject honorifics on the robot (…께 가셔서)
    compound = rec.get("n_subtasks", 1) > 1 or rec.get("structure", "single") != "single"
    if check_text(para, lang, compound):
        why.append("R-g")
    if seen is not None and norm(para, lang) in seen[lang]:
        why.append("duplicate")
    if near is not None and near.find(para, lang, other_than=rec["split"]) is not None:
        why.append("near_duplicate")
    return why


# ── selection ────────────────────────────────────────────────────────────────────────────────────────
def select(recs: list, frac: float, gen_seed: int = 2026) -> list:
    """A stratified share of the template records (by split x structure x kind), chosen by seed."""
    by = {}
    for r in recs:
        if r["source"] == "template":
            by.setdefault((r["split"], r["structure"], r["kind"]), []).append(r)
    out = []
    for k, rs in sorted(by.items()):
        rs = sorted(rs, key=lambda r: derive_seed(gen_seed, "para", r["id"]))
        out += rs[:round(len(rs) * frac)]
    return sorted(out, key=lambda r: r["id"])


def _inp(rec, lang, text=None):
    keep = [alts[0] for alts in (rec.get("meta") or {}).get("entities", {}).get(lang, [])]
    compound = rec.get("n_subtasks", 1) > 1 or rec.get("structure", "single") != "single"
    return {"text": text if text is not None else rec["text"][lang], "keep": keep, "compound": compound}


# ── run ──────────────────────────────────────────────────────────────────────────────────────────────
def load_records():
    from ..tasks import read_records
    return {s: read_records(s) for s in SPLITS}


def restore_template(r):
    """Undo an applied paraphrase (reruns start from the template texts)."""
    tt = (r.get("meta") or {}).get("template_text")
    if tt:
        r["text"] = dict(tt)
        r["length_words"] = {lg: words(r["text"][lg], lg) for lg in r["text"]}
    r["meta"]["template_text"] = None
    r["meta"]["paraphrase"] = None
    r["source"] = "template"
    r["source_by_lang"] = {"en": "template", "ko": "template"}
    r["paraphrase_model"] = {"en": None, "ko": None}


def realism_ok(rec, lang, text) -> list:
    """The task's realism rules (R-a..R-h) with the candidate in place of the template text: a paraphrase must not
    break a rule the template passes (e.g. a self-correction that no longer ends on the final object)."""
    from .realism import check_record
    cand = dict(rec, text=dict(rec["text"], **{lang: text}))
    bad, _ = check_record(cand)
    return ["realism_" + bad[0]["rule"]] if bad else []


def _rounds(lang, sel, writer, judge, back, rounds, seen, near, gen_seed, batch, log):
    """Ask, filter, back-translate (Korean), judge; a rejected record is asked again next round (new seed).
    English: writer = judge = qwen3-vl:8b-instruct (prompt p1). Korean: writer exaone3.5, judge and back-translator
    qwen3-vl:30b-a3b-instruct (prompt k2; USER_FEEDBACK 9)."""
    acc, rej = {}, Counter()
    task = "para_en" if lang == "en" else "para_ko2"
    back_tpl = {}
    if lang == "ko":
        back_tpl = dict(zip([r["id"] for r in sel],
                            batch(back, [("back", {"text": r["text"]["ko"]}, derive_seed(gen_seed, "bt", r["id"]))
                                         for r in sel])))
    pending = list(sel)
    asked = 0
    for rnd in range(rounds):
        todo = pending
        if not todo:
            break
        asked += len(todo)
        outs = batch(writer, [(task, _inp(r, lang), derive_seed(gen_seed, lang, rnd, r["id"])) for r in todo])
        whys = [filters(r, lang, text, near, seen) for r, (text, _sha) in zip(todo, outs)]
        whys = [w_ or realism_ok(r, lang, text) for r, (text, _sha), w_ in zip(todo, outs, whys)]
        backs = {}
        if lang == "ko":
            cand = [(r, o) for r, o, wy in zip(todo, outs, whys) if not wy]
            bres = batch(back, [("back", {"text": o[0]}, derive_seed(gen_seed, "bp", r["id"])) for r, o in cand])
            backs = {r["id"]: b for (r, _), b in zip(cand, bres)}
        still, jobs, pend = [], [], []
        for r, (text, sha), why in zip(todo, outs, whys):
            sc, bsha, bt = None, None, None
            if lang == "ko" and not why:
                bt, bsha = backs.get(r["id"], ("", None))
                ref_tpl = back_tpl[r["id"]][0]
                sc = max(chrf(bt, r["text"]["en"]), chrf(bt, ref_tpl) if ref_tpl else 0.0) if bt else 0.0
                if sc < CHRF_MIN:
                    why = why + ["chrf_backtranslation"]
            if not why and (norm(text, lang) in seen[lang] or near.find(text, lang, other_than=r["split"]) is not None):
                why = ["duplicate_of_accepted"]
            if not why:
                if lang == "en":   # the same-meaning judge: English paraphrase vs the English template
                    jobs.append(("judge", {"a": r["text"]["en"], "text": text}, derive_seed(gen_seed, "judge", "en", r["id"])))
                else:              # Korean paraphrase vs the Korean template, in Korean (meaning, 해요체, role, spelling)
                    jobs.append(("judge_ko", {"a": r["text"]["ko"], "text": text}, derive_seed(gen_seed, "judge", "ko", r["id"])))
                pend.append((r, text, sha, sc, bt, bsha))
                continue
            for x in why:
                rej[x] += 1
            still.append(r)
        verdicts = batch(judge, jobs)
        for (r, text, sha, sc, bt, bsha), (v, jsha) in zip(pend, verdicts):
            if v != "same":
                rej["judge_" + v] += 1
                still.append(r)
                continue
            if norm(text, lang) in seen[lang] or near.find(text, lang, other_than=r["split"]) is not None:
                rej["duplicate_of_accepted"] += 1
                still.append(r)
                continue
            acc[r["id"]] = {"text": text, "sha": sha, "round": rnd, "chrf": sc, "back": bt, "back_sha": bsha,
                            "judge_sha": jsha, "back_template_sha": (back_tpl.get(r["id"]) or (None, None))[1]}
            seen[lang].add(norm(text, lang))
            near.add(r["id"] + ":p" + lang, text, lang, r["split"])
        pending = still
        log(f"round {rnd} {lang}: {len(todo)} asked, {len(todo) - len(still)} accepted, {len(acc)} so far; "
            f"llm calls {writer.n_calls + (judge.n_calls if judge is not writer else 0)}")
    return acc, rej, asked


def run(url="http://127.0.0.1:11536", model=EN_MODEL, ko_model=KO_WRITER, ko_judge=KO_JUDGE, frac=0.6, rounds=3,
        ko_rounds=4, workers=8, apply=True, offline=False, langs=("en", "ko"), gen_seed=2026, log=print) -> int:
    data = load_records()
    recs = [r for s in SPLITS for r in data[s]]
    for r in recs:
        restore_template(r)
    byid = {r["id"]: r for r in recs}
    llm = {"en": LLM(url, model, Cache(CACHE), offline=offline)}
    ko_cache = Cache(CACHE_KO)
    llm["ko_w"] = LLM(url, ko_model, ko_cache, offline=offline)
    llm["ko_j"] = LLM(url, ko_judge, ko_cache, offline=offline)
    sel = select(recs, frac, gen_seed)
    log(f"paraphrase: {len(sel)} of {len(recs)} records selected (frac {frac}); en {model}, ko {ko_model} "
        f"(judge {ko_judge}); offline={offline}")
    seen = {"en": set(), "ko": set()}
    near = NearDupIndex()
    for r in recs:
        for lg in ("en", "ko"):
            seen[lg].add(norm(r["text"][lg], lg))
            near.add(r["id"] + ":" + lg, r["text"][lg], lg, r["split"])
    pool = ThreadPoolExecutor(max(1, workers))

    def batch(client, jobs):
        return list(pool.map(lambda j: client.ask(*j), jobs))

    acc, rej, asked = {}, {}, {}
    if "en" in langs:
        acc["en"], rej["en"], asked["en"] = _rounds("en", sel, llm["en"], llm["en"], None, rounds, seen, near,
                                                    gen_seed, batch, log)
    if "ko" in langs:
        acc["ko"], rej["ko"], asked["ko"] = _rounds("ko", sel, llm["ko_w"], llm["ko_j"], llm["ko_j"], ko_rounds, seen,
                                                    near, gen_seed, batch, log)
    pool.shutdown()
    models = {"en": model, "ko": ko_model}
    used = {"en": set(), "ko": set()}
    n_app = Counter()
    for i in sorted(byid):
        r = byid[i]
        new, mp = dict(r["text"]), {}
        for lg in langs:
            a = acc[lg].get(i)
            if not a or norm(a["text"], lg) in used[lg]:
                continue                     # two records paraphrased to the same text: keep the first
            used[lg].add(norm(a["text"], lg))
            new[lg] = a["text"]
            r["source_by_lang"][lg] = "llm_paraphrase"
            r["paraphrase_model"][lg] = models[lg]
            m = {"model": models[lg], "prompt_version": PROMPT_VERSION if lg == "en" else KO_PROMPT_VERSION,
                 "round": a["round"], "sha_req": a["sha"], "sha_judge": a["judge_sha"],
                 "judge_model": model if lg == "en" else ko_judge}
            if lg == "ko":
                m.update(back_model=ko_judge, back_en=a["back"], sha_back=a["back_sha"],
                         sha_back_template=a["back_template_sha"], chrf_backtranslation=round(a["chrf"], 2))
            mp[lg] = m
            n_app[lg] += 1
        if mp:
            r["meta"]["template_text"] = dict(r["text"])
            r["text"] = new
            r["source"] = "llm_paraphrase"
            r["length_words"] = {lg: words(new[lg], lg) for lg in new}
            r["meta"]["paraphrase"] = mp
            n_app["any"] += 1
            if len(mp) == 2:
                n_app["both"] += 1
    n = len(recs)
    summary = {"models": {"en": {"writer": model, "judge": model, "prompt_version": PROMPT_VERSION},
                          "ko": {"writer": ko_model, "judge": ko_judge, "back_translation": ko_judge,
                                 "prompt_version": KO_PROMPT_VERSION}},
               "selected": len(sel), "frac": frac, "rounds": {"en": rounds, "ko": ko_rounds},
               "asked": asked, "accepted": {lg: len(acc[lg]) for lg in acc},
               "applied": dict(sorted(n_app.items())),
               "share_of_all": {k: round(v / max(1, n), 4) for k, v in sorted(n_app.items())},
               "chrf_min": CHRF_MIN, "rejections": {lg: dict(sorted(rej[lg].items())) for lg in rej},
               "llm_calls": {k: c.n_calls for k, c in llm.items()},
               "cache_misses_offline": {k: c.n_miss for k, c in llm.items()}}
    log(json.dumps(summary["applied"]))
    if apply:
        for s in SPLITS:
            _write(TASKS_DIR / f"{s}.jsonl", data[s])
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_DIR / "paraphrase_run.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, sort_keys=True, ensure_ascii=False, indent=1)
        f.write("\n")
    return 0


def _write(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
