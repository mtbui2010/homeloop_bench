"""The simulated user's LLM intent classifier (R2-7a "C", homeloop_robot docs/user_model.md).

A robot question with no structured meaning goes to the user model's rules first. Only when the rules do not
understand it (``homeloop_robot.intent.NOT_CONFIDENT``) is this classifier asked: a deterministic LLM call
(temperature 0, seed 0, the fixed prompt below, JSON output) that maps the question onto the frozen qtype list
(``homeloop_robot.intent.QTYPES``) plus slots. It only classifies; the answer always comes from the task script
(``intent.answer_structured``).

Classifications are cached per run in ``<out>/llm_cache/user_intent.jsonl`` (``llm.CachedLLM`` lines), so a
rerun gives the same episodes without the server. With no LLM (or ``--llm fake``, or
``HOMELOOP_USER_CLASSIFIER=rules``) the rules alone apply: ``summary.json`` config ``user_classifier: rules``.

CLI (the audit, docs/user_model.md "Accuracy audit")::

    python -m homeloop_bench.user_intent interpret --questions Q.jsonl --out OUT.jsonl [--llm URL] [--model M]

reads ``{qid, lang, question, task_id, ...}`` lines and writes how the user simulator reads each question
(path, qtype, rule) in that task's episode (profile ideal, seed 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from homeloop_robot.intent import QTYPES, clean

from .llm import CachedLLM, FakeLLM, LLMError, parse_json, shared_cache_path

PROMPT_VERSION = "ui2"
CACHE_NAME = "user_intent.jsonl"

# ui2 (R2-7a audit, data/quality/sim_user_audit.json): ui1 plus the reading conventions of
# homeloop_robot docs/user_model.md "Free text" (first question decides, open "what should I do?" = repeat,
# a statement = free, a proposal = confirm, a choice among places = which_place)
PROMPT = """You read one question that a household robot asked the person who gave it a task. Say what kind of \
question it is, as the person hearing it would understand it. Pick exactly one qtype:

- which_object: asks which object or thing the person means or wants ("Which cup, the red one or the blue \
one?", "What should I bring?", "What is the second item you want me to grab?", "우유랑 물 중에 뭘로 드릴까요?", \
"냉장고에 무엇을 넣을까요?"). slots: options (the things offered, as written), obj.
- which_place: asks which place, or where something should go / be put / be brought, or where the robot should \
go ("Where should I put the mug?", "Which shelf do you mean: A or B?", "Should I put it in the fridge or the \
kimchi fridge?", "어디에 둘까요?", "어떤 서랍이요?"). A choice among places or furniture is which_place. \
slots: options (the places offered), obj (the thing to be placed).
- confirm: a yes / no check of one proposed action or reading: a read-back of its plan ("I will put the mug on \
the counter. Is that right?"), a proposal ("Should I bring it to you?", "저한테 가져다드릴까요?") or one thing \
("Is it the red mug?", "빨간 컵 맞아요?"). slots: goal (the read-back / proposed action) or obj.
- where_are_you: asks where the person is now ("Where are you?", "지금 어디 계세요?").
- where_is: asks where an object or another person is now ("Where is the remote?", "할아버지 어디 계세요?", \
"전화기 위치를 알려주세요"). slots: obj.
- repeat: asks the person to say their request or their last answer again, or to restate the task because the \
robot does not know what to do: an open question that names nothing specific ("Could you repeat that?", "What \
should I do exactly?", "Which objects should I move and where?", "무슨 물건을 어디에 둘까요?", "다시 말씀해 \
주시겠어요?"). slots: about = "request" or "answer".
- did_you_mean: checks a word the robot may have misheard in the person's own words, or asks what a quoted word \
means ("Did you say 'kitchen'?", "What do you mean by 'sec'?", "'주방'이라고 하셨어요?", "'여쇠'가 뭐예요?"). \
slots: word (that word).
- what_to_say: asks what message to give someone ("What should I tell your husband?"). slots: person.
- help: asks the person to help with an obstacle or to clear the way.
- free: none of these, or no question at all (a remark or a message to someone, "Grandpa, here is your towel.").

Rules: when the robot asks several questions at once, classify the FIRST question. Ignore an apology before it \
("Sorry, I didn't hear you."). A sentence like "You mentioned the X." only introduces the question after it.
Copy slot values exactly as they appear in the question (do not translate). Leave out slots that do not apply.
Answer with JSON only: {{"qtype": "...", "options": [...], "obj": "...", "goal": "...", "word": "...", \
"person": "...", "about": "..."}}

Question ({lang}): {question}"""

LANG_NAME = {"en": "English", "ko": "Korean"}


def prompt(question: str, lang: str) -> str:
    return PROMPT.format(lang=LANG_NAME.get(lang, lang), question=" ".join(str(question or "").split()))


class IntentClassifier:
    """``classifier(question, lang) -> {"qtype", slots...} | None`` over a chat LLM; None = an unusable answer
    (the user then reads the question as not understood). An LLM error is kept in ``failed`` (the episode
    record raises it: a run with a broken classifier is not a result)."""

    kind = "llm"

    def __init__(self, llm):
        self.llm = llm
        self.model = getattr(llm, "model", "")
        self.failed: Optional[BaseException] = None
        self._memo: dict = {}

    def __call__(self, question: str, lang: str) -> Optional[dict]:
        p = prompt(question, lang)
        if p in self._memo:
            return self._memo[p]
        try:
            raw = self.llm.chat(p, format="json", temperature=0.0, seed=0)
        except LLMError as e:
            if self.failed is None:
                self.failed = e
            return None
        try:
            out = clean(parse_json(raw))
        except ValueError:
            out = None
        self._memo[p] = out
        return out


_SHARED: dict = {}


def _unwrap(llm):
    """The run's LLM below the episode's counter: (cached LLM or None, the raw client)."""
    x = llm
    for _ in range(4):
        if isinstance(x, CachedLLM):
            return x, x.inner
        inner = getattr(x, "inner", None)
        if inner is None or type(x).__name__ != "CountingLLM":
            break
        x = inner
    return None, x


def make_classifier(llm) -> Optional[IntentClassifier]:
    """The classifier for an episode whose planner runs with ``llm`` (the run's client), or None (rules only):
    no LLM, the fake LLM, or ``HOMELOOP_USER_CLASSIFIER=rules``. A cached run LLM (``<out>/llm_cache/<model>.jsonl``)
    gives a classifier cached in ``<out>/llm_cache/user_intent.jsonl``; one classifier per cache file and model."""
    mode = os.environ.get("HOMELOOP_USER_CLASSIFIER", "auto")
    if mode == "rules" or llm is None:
        return None
    cached, raw = _unwrap(llm)
    if isinstance(raw, FakeLLM) or raw is None:
        return None
    if cached is not None:
        path = Path(cached.path).parent / CACHE_NAME
        key = (str(path), getattr(raw, "model", ""))
        if key not in _SHARED:
            _SHARED[key] = IntentClassifier(CachedLLM(raw, path, shared=shared_cache_path(getattr(raw, "model", "") or "")
                                                      if getattr(raw, "model", None) else None))
        return _SHARED[key]
    key = (id(raw), getattr(raw, "model", ""))
    if key not in _SHARED:
        _SHARED[key] = IntentClassifier(raw)
    return _SHARED[key]


def classifier_kind(llm_spec: Optional[str]) -> str:
    """``summary.json`` config ``user_classifier``: llm | rules."""
    if os.environ.get("HOMELOOP_USER_CLASSIFIER", "auto") == "rules" or not llm_spec or llm_spec == "fake":
        return "rules"
    return "llm"


# ── the audit: how the simulator reads given questions ────────────────────────────────────────────────────
def interpret(rows: list, llm=None, profile: str = "ideal") -> list:
    """For each ``{qid, lang, question, task_id}``: the user simulator's reading (path, qtype, rule) in that
    task's episode. Answers' randomness is not used (the reading does not depend on it)."""
    from homeloop_robot.dialog import GoalView

    from .env import EpisodeEnv, task_dict
    from .tasks import load_split
    tasks = {}
    for sp in ("train", "dev", "test"):
        for t in load_split(sp):
            tasks[str(task_dict(t)["id"])] = t
    clf = IntentClassifier(llm) if llm is not None else None
    out = []
    for r in rows:
        t = tasks.get(r.get("task_id"))
        lang = r.get("lang") or "en"
        if t is None:
            out.append({"qid": r.get("qid"), "error": "unknown task"})
            continue
        env = EpisodeEnv(t, profile, 0, lang)
        u = env.user
        u.classifier = clf
        gv = GoalView(u.world, u.wants, u.user_id, lambda pid: u.place_of(pid, 0.0)[0]) if u.wants else None
        kw = dict(knows_location=True, other_place=None, user_place=u.place_of(u.user_id, 0.0) if u.user_id else None,
                  goal=gv, request=u.request, last_answer=None)
        c, path, qtype = u._content(str(r.get("question") or ""), lang, r.get("meaning"), kw)
        out.append({"qid": r.get("qid"), "lang": lang, "path": path, "qtype": qtype, "rule": c.rule,
                    "kind": c.kind, "answer": c.text})
    if clf is not None and clf.failed is not None:
        raise clf.failed
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m homeloop_bench.user_intent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("interpret")
    p.add_argument("--questions", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--llm", default=None, help="Ollama URL; none = rules only")
    p.add_argument("--model", default=None)
    p.add_argument("--cache", default=None, help="JSONL cache for the classifier (default: next to --out)")
    a = ap.parse_args(argv)
    rows = [json.loads(x) for x in Path(a.questions).read_text(encoding="utf-8").splitlines() if x.strip()]
    llm = None
    if a.llm:
        from .llm import OllamaHTTP
        llm = CachedLLM(OllamaHTTP(a.llm, a.model or "qwen3-vl:8b-instruct"),
                        a.cache or str(Path(a.out).with_name(CACHE_NAME)))
    res = interpret(rows, llm)
    Path(a.out).write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in res),
                           encoding="utf-8")
    print(f"[user_intent] {len(res)} questions -> {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["QTYPES", "IntentClassifier", "make_classifier", "classifier_kind", "interpret", "prompt"]
