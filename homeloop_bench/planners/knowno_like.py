"""``knowno_like``: after KnowNo (Ren et al. 2023, arXiv:2307.01928).

Before acting, the LLM lists up to 4 candidate interpretations of the instruction (goal-atom strings, a
multiple-choice question, plus "none of these"). KnowNo scores the options with the LLM's next-token
probabilities; a chat API gives none, so 5 samples (temperature 0.7, seeds 0-4) give option frequencies
instead (documented deviation). Conformal prediction: the set {y : freq(y) >= 1 - q_hat} with q_hat
calibrated on train at 1 - epsilon = 0.85 (``homeloop-bench calibrate-knowno``, stored in
``planners/knowno_calib.json``). Set size 1 -> act; otherwise ask the user to choose. Execution uses the
inner-monologue loop with the chosen interpretation.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from homeloop_robot import goals as G
from homeloop_robot.catalog import COLORS

from .base import ask_json, refusal_text
from .inner_monologue_like import LLMStepPlanner
from .prompts import render_observation

CALIB_PATH = Path(__file__).with_name("knowno_calib.json")
N_SAMPLES = 5
SAMPLE_TEMPERATURE = 0.7
LETTERS = "ABCD"


def load_calib(path=CALIB_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"q_hat": 0.7, "epsilon": 0.15, "n": 0, "calibrated": False}


def options_prompt(obs) -> str:
    return "\n\n".join([
        "MODE: knowno_options",
        "You control a household robot. List up to 4 different plausible interpretations of the instruction as "
        "goal conditions over the ids below, e.g. on(mug_1, table@dining) & open(fridge@kitchen). Predicates: "
        "on(obj, place), in(obj, container), delivered(obj, person) (bring it to the person: on a surface they can reach, or into their hand), open(c), closed(c), said_to(person, message), "
        "robot_at(place), docked(). Use the single option \"refuse\" when the request is unsafe or impossible.",
        render_observation(obs),
        'Answer with JSON: {"options": ["...", ...]}.'])


def choice_prompt(obs, opts: list) -> str:
    lines = [f"{LETTERS[i]}: {o}" for i, o in enumerate(opts)] + [f"{chr(ord('A') + len(opts))}: none of these"]
    return "\n\n".join(["MODE: knowno_choice",
                        "Which option is what the user wants? Pick one letter.",
                        render_observation(obs),
                        "Choices:\n" + "\n".join(lines),
                        'Answer with JSON: {"choice": "<letter>"}.'])


def _valid_options(o) -> str | None:
    if not isinstance(o, dict) or not isinstance(o.get("options"), list) or not o["options"]:
        return "options must be a non-empty list"
    return None


def option_frequencies(llm, obs, opts: list) -> dict:
    freq = {o: 0 for o in opts}
    for s in range(N_SAMPLES):
        letters = [chr(ord("A") + i) for i in range(len(opts) + 1)]
        obj = ask_json(llm, choice_prompt(obs, opts), temperature=SAMPLE_TEMPERATURE, seed=s,
                       check=lambda o: None if isinstance(o, dict) and str(o.get("choice", "")).strip()[:1].upper()
                       in letters else "choice must be a letter")
        if obj is None:
            continue
        i = ord(str(obj["choice"]).strip()[:1].upper()) - ord("A")
        if 0 <= i < len(opts):
            freq[opts[i]] += 1
    return {o: freq[o] / N_SAMPLES for o in opts}


def prediction_set(freq: dict, q_hat: float) -> list:
    return [o for o in sorted(freq, key=lambda x: (-freq[x], x)) if freq[o] >= 1.0 - q_hat - 1e-9]


def _obj_phrase(oid: str, obs) -> dict:
    m = {o.id: o for o in obs.memory}.get(oid)
    if m is None:
        return {"en": oid, "ko": oid}
    col = m.attrs.get("color")
    out = {}
    for lg in ("en", "ko"):
        n = m.name.get(lg, oid)
        out[lg] = f"{COLORS[col][lg]} {n}" if col in COLORS else n
    return out


def _distinct_objects(opts: list) -> list:
    """For each option, the first object id that differs between the options (for the question)."""
    args = []
    for o in opts:
        try:
            g = G.parse(o)
            args.append([x for a in g["all"] if "pred" in a for x in a.get("args") or []])
        except Exception:  # noqa: BLE001
            args.append([])
    out = []
    for i, a in enumerate(args):
        others = set(x for j, b in enumerate(args) if j != i for x in b)
        out.append(next((x for x in a if x not in others), a[0] if a else ""))
    return out


def meaning(opts: list, obs) -> dict:
    """The structured form of :func:`question`: which object (or which place, when the options differ only in
    a place), with the names the question says."""
    ids = _distinct_objects(opts)
    names = [_obj_phrase(o, obs)[obs.lang] for o in ids]
    places = {p.id for p in obs.places}
    qt = "which_place" if ids and all(o in places for o in ids) else "which_object"
    if qt == "which_place":
        names = [next((p.name.get(obs.lang) or p.id for p in obs.places if p.id == o), o) for o in ids]
    return {"qtype": qt, "options": names}


def question(opts: list, obs) -> str:
    objs = _distinct_objects(opts)
    names = [_obj_phrase(o, obs)[obs.lang] for o in objs]
    if obs.lang == "ko":
        return "어느 쪽 말씀이세요? " + ", 아니면 ".join(f"{n}" for n in names) + "?"
    return "Which one do you mean: " + ", or ".join(f"the {n}" for n in names) + "?"


def pick_by_answer(opts: list, answer: str, obs) -> str:
    objs = _distinct_objects(opts)
    a = str(answer or "").lower()
    for o, oid in zip(opts, objs):
        ph = _obj_phrase(oid, obs)
        m = {x.id: x for x in obs.memory}.get(oid)
        col = m.attrs.get("color") if m else None
        if col in COLORS and COLORS[col][obs.lang].lower() in a:
            return o
        if ph[obs.lang].lower() in a:
            return o
    if re.search(r"\b(other|second)\b", a) or "다른" in a or "두 번째" in a:
        return opts[1] if len(opts) > 1 else opts[0]
    return opts[0]


class KnowNoLike(LLMStepPlanner):
    name = "knowno_like"
    mode = "knowno_exec"
    description = "conformal prediction set over interpretations; asks when the set has more than one (after KnowNo)"
    qtypes = ("which_object", "which_place")      # its question's structured form (meaning=)

    def __init__(self, llm=None, calib: dict | None = None):
        super().__init__(llm)
        self.calib = calib or load_calib()
        self.interpretation = None

    def extra(self, obs) -> str:
        return f"Interpretation: {self.interpretation}" if self.interpretation else ""

    def run(self, env) -> None:
        if self.llm is None:
            raise RuntimeError("knowno_like needs an LLM")
        obs = env.observe()
        obj = ask_json(self.llm, options_prompt(obs), check=_valid_options)
        if obj is None:
            env.finish("give_up", "no valid options from the LLM")
            return
        opts = []
        for o in obj["options"][:4]:
            o = str(o).strip()
            if o and o not in opts:
                opts.append(o)
        if any(o.lower() == "refuse" for o in opts) and len(opts) == 1:
            env.finish("refuse", refusal_text(env.lang))
            return
        opts = [o for o in opts if o.lower() != "refuse"]
        freq = option_frequencies(self.llm, obs, opts)
        cset = prediction_set(freq, float(self.calib.get("q_hat", 0.7)))
        self.pred_set = cset
        if len(cset) == 1:
            self.interpretation = cset[0]
        else:
            ask_opts = cset or opts
            r = env.call("ask", question=question(ask_opts, obs), lang=env.lang, meaning=meaning(ask_opts, obs))
            ans = (r.get("data") or {}).get("answer", "") if r["ok"] else ""
            self.interpretation = pick_by_answer(ask_opts, ans, obs)
        super().run(env)


def calibrate(tasks: list, llm, epsilon: float = 0.15, lang: str = "en") -> dict:
    """q_hat = the ceil((n+1)(1-epsilon))/n empirical quantile of the non-conformity scores
    1 - freq(true option) over tasks with a goal (feasible / clarify)."""
    from ..env import EpisodeEnv
    scores = []
    for t in tasks:
        env = EpisodeEnv(t, "ideal", 0, lang, llm=llm)
        if env.task.get("kind") == "refuse":
            continue
        true = G.format({"all": [a for s in env.subtasks for a in s["goal"]["all"]]})
        obs = env.observe()
        obj = ask_json(env.llm(), options_prompt(obs), check=_valid_options)
        opts = [str(o).strip() for o in (obj or {}).get("options", [])[:4] if str(o).strip()]
        freq = option_frequencies(env.llm(), obs, opts) if opts else {}
        norm_true = true.replace(" ", "")
        f_true = max([v for o, v in freq.items() if o.replace(" ", "") == norm_true] or [0.0])
        scores.append(1.0 - f_true)
    n = len(scores)
    if n == 0:
        return {"q_hat": 0.7, "epsilon": epsilon, "n": 0, "calibrated": False}
    k = min(n, int(math.ceil((n + 1) * (1 - epsilon))))
    q = sorted(scores)[k - 1]
    return {"q_hat": round(q, 6), "epsilon": epsilon, "n": n, "calibrated": True}
