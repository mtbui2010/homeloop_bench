"""LLM paraphrases (DESIGN 10.5; docs/generation.md "Paraphrases").

Local model only: Ollama on GPU 0 through ``tools/llm_gpu0.sh`` (http://127.0.0.1:11536), qwen3-vl:8b-instruct by
default. One request per item and language (the cache is then robust to changes elsewhere in the data):
  para_en  rewrite the English request          (temperature 0.8, seed per item and round)
  para_ko  rewrite the Korean request (해요체)   (temperature 0.8)
  back     translate a Korean text to English   (temperature 0): the Korean paraphrase, and the Korean template
Cache: ``homeloop_bench/data/llm_cache/paraphrase.jsonl``, one line per response
  {"sha", "model", "options", "task", "prompt_version", "input", "response"}
``sha`` = sha256 of (model, options, full prompt); the full prompt is rebuilt from ``task`` + ``input`` by the code
below, so the cache stays small and reruns need no GPU (``--offline``). The run is resumable: every response is
appended as it arrives.

A record becomes ``source: llm_paraphrase`` only when BOTH languages pass every filter (``filters``) and the Korean
back-translation is close to the meaning (chrF >= CHRF_MIN against the better of the English template and the
back-translated Korean template). Otherwise it stays a template.
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
from .textcheck import check_text, words

PROMPT_VERSION = "p1"
CHRF_MIN = 35.0
CACHE = CACHE_DIR / "paraphrase.jsonl"
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
    "para_ko": " 여러 가지 일을 한 번에 부탁하는 말이에요. 모든 일을 빠짐없이 두고, 순서(먼저, 그다음에), 조건(있으면/없으면), "
               "말을 고치는 부분(아니, 잠깐만요, ~ 말고)도 뜻이 그대로 유지되게 써 주세요.",
}
OPTIONS = {"para": {"temperature": 0.8, "num_predict": 256, "num_ctx": 2048},
           "back": {"temperature": 0.0, "num_predict": 256, "num_ctx": 2048},
           "judge": {"temperature": 0.0, "num_predict": 32, "num_ctx": 2048}}


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
        opts = dict(OPTIONS[task if task in ("back", "judge") else "para"], seed=int(seed) % 2**31)
        prompt = build_prompt(task, inp)
        sha = request_sha(self.model, opts, prompt)
        hit = self.cache.d.get(sha)
        if hit is not None:
            return (_judge(hit["response"]) if task == "judge" else _parse(hit["response"])), sha
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
        return (_judge(resp) if task == "judge" else _parse(resp)), sha


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
                        r"두실래요|둬요|부탁해요|돌아가요|드릴래요|드릴 수 있어요|가 있어요|돼요)")
KO_BANMAL = re.compile(r"(거야|이야|했어(?!요)|할래(?!요)|해줘(?!요)|줘(?![요 서야도])|가져와(?!요)|해\.|줄래(?!요)|"
                       r"니\?|냐\?|할게(?!요)|놔(?![ 요두주서야])|있어(?![요서 야도]))")


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
        if KO_BANMAL.search(para):
            why.append("ko_banmal")
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


def run(url="http://127.0.0.1:11536", model="qwen3-vl:8b-instruct", frac=0.45, rounds=3, workers=4, apply=True,
        offline=False, gen_seed=2026, log=print) -> int:
    data = load_records()
    recs = [r for s in SPLITS for r in data[s]]
    byid = {r["id"]: r for r in recs}
    cache = Cache()
    llm = LLM(url, model, cache, offline=offline)
    sel = select(recs, frac, gen_seed)
    log(f"paraphrase: {len(sel)} of {len(recs)} records selected (frac {frac}), model {model}, offline={offline}")
    # dedup state: every current text except the selected one's own
    seen = {"en": set(), "ko": set()}
    near = NearDupIndex()
    for r in recs:
        for lg in ("en", "ko"):
            seen[lg].add(norm(r["text"][lg], lg))
            near.add(r["id"] + ":" + lg, r["text"][lg], lg, r["split"])
    pool = ThreadPoolExecutor(max(1, workers))

    def batch(jobs):
        return list(pool.map(lambda j: llm.ask(*j), jobs))

    # back-translations of the Korean templates (the reference for Korean paraphrases)
    back_tpl = dict(zip([r["id"] for r in sel], batch([("back", {"text": r["text"]["ko"]}, derive_seed(gen_seed, "bt", r["id"]))
                                                      for r in sel])))
    acc = {"en": {}, "ko": {}}
    rej = {"en": Counter(), "ko": Counter()}
    tries = {r["id"]: {"en": 0, "ko": 0} for r in sel}
    pending = {"en": list(sel), "ko": list(sel)}
    for rnd in range(rounds):
        for lg in ("en", "ko"):
            todo = pending[lg]
            if not todo:
                continue
            outs = batch([(f"para_{lg}", _inp(r, lg), derive_seed(gen_seed, lg, rnd, r["id"])) for r in todo])
            whys = [filters(r, lg, text, near, seen) for r, (text, _sha) in zip(todo, outs)]
            backs = {}
            if lg == "ko":
                cand = [(r, o) for r, o, wy in zip(todo, outs, whys) if not wy]
                bres = batch([("back", {"text": o[0]}, derive_seed(gen_seed, "bp", r["id"])) for r, o in cand])
                backs = {r["id"]: b for (r, _), b in zip(cand, bres)}
            still, judge_jobs, pend = [], [], []
            for r, (text, sha), why in zip(todo, outs, whys):
                tries[r["id"]][lg] += 1
                sc, bsha, bt = None, None, None
                if lg == "ko" and not why:
                    bt, bsha = backs.get(r["id"], ("", None))
                    ref_tpl = back_tpl[r["id"]][0]
                    sc = max(chrf(bt, r["text"]["en"]), chrf(bt, ref_tpl) if ref_tpl else 0.0) if bt else 0.0
                    if sc < CHRF_MIN:
                        why = why + ["chrf_backtranslation"]
                if not why and (norm(text, lg) in seen[lg] or near.find(text, lg, other_than=r["split"]) is not None):
                    why = ["duplicate_of_accepted"]
                if not why:
                    judge_jobs.append((r, text if lg == "en" else bt))
                    pend.append((r, text, sha, sc, bt, bsha))
                    continue
                for x in why:
                    rej[lg][x] += 1
                still.append(r)
            # the same-meaning judge (same model, temperature 0): English paraphrase vs the English template, Korean
            # back-translation vs the English template
            verdicts = batch([("judge", {"a": r["text"]["en"], "text": t}, derive_seed(gen_seed, "judge", lg, r["id"]))
                              for r, t in judge_jobs])
            for (r, text, sha, sc, bt, bsha), (v, jsha) in zip(pend, verdicts):
                if v != "same":
                    rej[lg]["judge_different"] += 1
                    still.append(r)
                    continue
                if norm(text, lg) in seen[lg] or near.find(text, lg, other_than=r["split"]) is not None:
                    rej[lg]["duplicate_of_accepted"] += 1
                    still.append(r)
                    continue
                acc[lg][r["id"]] = {"text": text, "sha": sha, "round": rnd, "chrf": sc, "back": bt, "back_sha": bsha,
                                    "judge_sha": jsha}
                seen[lg].add(norm(text, lg))
                near.add(r["id"] + ":p" + lg, text, lg, r["split"])
            pending[lg] = still
            log(f"round {rnd} {lg}: {len(todo)} asked, {len(todo) - len(still)} accepted; llm calls {llm.n_calls}")
    pool.shutdown()
    both = [i for i in acc["en"] if i in acc["ko"]]
    log(f"accepted in both languages: {len(both)} ({len(both) / max(1, len(recs)):.3f} of all records)")
    summary = {"model": model, "prompt_version": PROMPT_VERSION, "selected": len(sel), "frac": frac, "rounds": rounds,
               "accepted_en": len(acc["en"]), "accepted_ko": len(acc["ko"]), "accepted_both": len(both),
               "share_of_all": round(len(both) / max(1, len(recs)), 4), "chrf_min": CHRF_MIN,
               "rejections": {lg: dict(sorted(rej[lg].items())) for lg in rej}, "llm_calls": llm.n_calls,
               "cache_misses_offline": llm.n_miss}
    if apply:
        n_applied = 0
        used = {"en": set(), "ko": set()}
        for i in sorted(both):
            r = byid[i]
            new = {lg: acc[lg][i]["text"] for lg in ("en", "ko")}
            if any(norm(new[lg], lg) in used[lg] for lg in new):
                continue                         # two records paraphrased to the same text: keep the first
            for lg in new:
                used[lg].add(norm(new[lg], lg))
            r["meta"]["template_text"] = dict(r["text"])
            r["text"] = new
            r["source"] = "llm_paraphrase"
            r["length_words"] = {lg: words(new[lg], lg) for lg in new}
            r["meta"]["paraphrase"] = {"model": model, "prompt_version": PROMPT_VERSION,
                                       "chrf_backtranslation": round(acc["ko"][i]["chrf"], 2),
                                       "back_en": acc["ko"][i]["back"], "sha_req_en": acc["en"][i]["sha"],
                                       "sha_req_ko": acc["ko"][i]["sha"], "sha_back": acc["ko"][i]["back_sha"],
                                       "sha_back_template": back_tpl[i][1],
                                       "sha_judge": {"en": acc["en"][i]["judge_sha"], "ko": acc["ko"][i]["judge_sha"]},
                                       "round": {"en": acc["en"][i]["round"], "ko": acc["ko"][i]["round"]}}
            n_applied += 1
        for s in SPLITS:
            _write(TASKS_DIR / f"{s}.jsonl", data[s])
        summary["applied"] = n_applied
        log(f"applied {n_applied} paraphrases")
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_DIR / "paraphrase_run.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, sort_keys=True, ensure_ascii=False, indent=1)
        f.write("\n")
    return 0


def _write(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
