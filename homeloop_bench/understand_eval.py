"""Understanding evaluation (docs/understand_eval.md): runs ONLY robot_agent's understand step on tasks and compares the
goal set it builds with the task's gold goals.

The probe is the real thing. ``planner.run(env)`` builds the episode exactly as ``homeloop-bench run`` does (the robot
package, the ENV, the per-episode object memory, the translate model and the loop options of the planner class), and
robot_agent's ``AssistLoop.run_blocking`` is drained only up to its ``understand`` event (``planner.until``): one
understand call, the goals grounded on the ENV, before any question, read-back, plan or motion. Gold goals are read
here, on the evaluation side, and never reach the robot.

Common form (rules R1 to R9, one place: :func:`robot_atom` and :func:`gold_atoms`; the text is docs/understand_eval.md):
an atom is ``(kind, cls, color, dest, person)``. Two atoms are equal when :func:`compatible` says so.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from homeloop_robot.rng import r6
from homeloop_robot.types import _round_tree

from .env import Budgets, EpisodeEnv, resolve_subtasks, task_dict
from .llm import BudgetExceeded, LLMError, make_llm
from .planners import make_planner, planner_class

STOP_EVENTS = ("understand", "understand_check", "done", "error")
SPEAKER_WORDS = {"me", "user", "here", "you", "myself", "person", "the user", "the person"}
PUT = {"on": "put_on", "in": "put_in"}


# ── the common form ─────────────────────────────────────────────────────────────────────────────────────────

class Atom(tuple):
    """``(kind, cls, color, dest, person)``; ``dest`` is a place id (or, for a gold ``robot_at`` group, a tuple of ids)."""
    __slots__ = ()

    def __new__(cls, kind, obj_cls="", color="", dest="", person=""):
        return super().__new__(cls, (kind, obj_cls, color, dest, person))

    kind = property(lambda s: s[0])
    cls = property(lambda s: s[1])
    color = property(lambda s: s[2])
    dest = property(lambda s: s[3])
    person = property(lambda s: s[4])

    def text(self) -> str:
        d = "|".join(self.dest) if isinstance(self.dest, tuple) else self.dest
        obj = f"{self.color} {self.cls}".strip()
        return f"{self.kind}({', '.join(x for x in (obj, d, self.person) if x)})"


def _words(s) -> str:
    return " ".join(str(s or "").lower().replace("_", " ").split())


def _class_index(world) -> dict:
    """{normalised class name (en and ko, aliases too): class id}; a name two classes share maps to None (unusable).
    M2 (docs/understand_eval.md): the class id itself is a name ("snack" for a class whose names are "snack bag" and
    "chips"), and the head noun of a multi-word name ("soup" of "can of soup") is a name when no full name and no other
    class claims it. Both only ADD names a robot may use; a full name always wins."""
    from homeloop_robot.catalog import CLASSES, class_names
    idx: dict = {}
    heads: dict = {}
    for cid in CLASSES:
        for lg in ("en", "ko"):
            try:
                names = list(class_names(cid, lg))
            except KeyError:
                continue
            if lg == "en":
                names.append(cid.replace("_", " "))
            for n in names:
                k = _words(n)
                if k:
                    idx[k] = cid if idx.get(k, cid) == cid else None
                    parts = k.split()
                    if len(parts) > 1:
                        h = parts[-1] if "of" not in parts[:-1] else parts[-1]       # "can of soup": the noun after "of"
                        heads[h] = cid if heads.get(h, cid) == cid else None
    for h, cid in heads.items():
        idx.setdefault(h, cid)
    return idx


def _color_words() -> dict:
    from homeloop_robot.catalog import COLORS
    return {_words(v[lg]): c for c, v in COLORS.items() for lg in ("en", "ko") if v.get(lg)}


class Context:
    """What the common form needs of one episode's world (the start state): classes, colours, people, places."""

    def __init__(self, world):
        from homeloop_robot.configs.tasks import env_for
        self.world = world
        self.user = world.user_id()
        self.classes = _class_index(world)
        self.colors = _color_words()
        self.person_of: dict = {}                  # normalised ENV key / alias / name -> person id
        for k, e in env_for(world).items():
            if isinstance(e, dict) and e.get("person"):
                for name in [k] + list(e.get("aliases") or []):
                    self.person_of[_words(name)] = e["person"]
        for pid, p in world.people.items():
            for lg in ("en", "ko"):
                n = (p.name or {}).get(lg)
                if n:
                    self.person_of.setdefault(_words(n), pid)
            self.person_of.setdefault(_words(pid), pid)
        self.seat_of = {p.seat: pid for pid, p in world.people.items() if getattr(p, "seat", None)}
        self.places = set(world.house.places)
        self.room_of = {k: p.room for k, p in world.house.places.items()}
        self.dock = world.house.dock

    def person(self, name) -> str:
        """Person id of a name, an ENV key, a speaker word, the id itself or '' (R9)."""
        w = _words(name)
        if not w:
            return ""
        if w in SPEAKER_WORDS:
            return self.user or ""
        if str(name) in self.world.people:
            return str(name)
        return self.person_of.get(w, "")

    def object_class(self, name) -> tuple:
        """(class id or '?<name>', colour id or '') of a robot goal's object name (R7)."""
        w = _words(name)
        color = ""
        parts, color_words = [], []
        for tok in w.split():
            if tok in self.colors:
                color_words.append(tok)
            if tok in self.colors and not color:
                color = self.colors[tok]
            elif tok not in ("a", "an", "the", "some", "my", "your"):
                parts.append(tok)
        base = " ".join(parts)
        if not base:
            # M1: a name made of colour words only is the class when a class has that name ("orange" the fruit)
            hit = self.classes.get(" ".join(color_words)) if color else None
            return (hit, "") if hit else ("", color)
        hit = self.classes.get(base)
        if not hit and len(parts) == 1 and base.endswith("s") and len(base) > 3:       # M2: a plural ("snacks")
            hit = self.classes.get(base[:-1]) or (self.classes.get(base[:-2]) if base.endswith("es") else None)
        if hit:
            return hit, color
        for k in range(1, len(parts)):                       # "kitchen knife" for a class "knife", "mug cup" ...
            hit = self.classes.get(" ".join(parts[k:])) or self.classes.get(" ".join(parts[:-k]))
            if hit:
                return hit, color
        return f"?{base}", color


def gold_atoms(td: dict, world) -> list:
    """The gold goal atoms of a task in the common form, of every subtask that is not a refusal (conditions resolved on
    the start world, a correction's final goal). Returns ``[Atom]``; ``unmoved`` atoms (the refusal's) are not goals."""
    ctx = Context(world)
    out = []
    for sub in resolve_subtasks(td, world):
        if sub["kind"] == "refuse":
            continue
        for a in sub["goal"].get("all") or []:
            out += _gold_atom(a, world, ctx)
    return out


def _gold_obj(world, oid):
    o = world.objects.get(oid)
    return (o.cls, str((o.attrs or {}).get("color") or "")) if o is not None else (f"?{oid}", "")


def _gold_atom(a: dict, world, ctx: Context) -> list:
    p, args = a.get("pred"), list(a.get("args") or [])
    if "any" in a:                                                          # R4: any one of a room's places
        places = sorted({x["args"][0] for x in a["any"] if x.get("pred") == "robot_at"})
        return [Atom("go", dest=tuple(places))] if places else []
    if p in ("on", "in"):
        c, col = _gold_obj(world, args[0])
        return [Atom(PUT[p], c, col, args[1])]
    if p in ("open", "closed"):
        return [Atom("open" if p == "open" else "close", dest=args[0])]
    if p in ("delivered", "held_by"):                                       # R2: a person receives the object
        c, col = _gold_obj(world, args[0])
        return [Atom("give", c, col, person=ctx.person(args[1]) or str(args[1]))]
    if p == "said_to":                                                      # R3: the person addressed (not the words)
        return [Atom("say", person=ctx.person(args[0]) or str(args[0]))]
    if p == "robot_at":
        return [Atom("go", dest=(args[0],))]
    if p == "docked":                                                       # R5
        return [Atom("go", dest=(ctx.dock,))]
    return []                                                               # unmoved and unknown predicates


def robot_atom(g: dict, ctx: Context) -> Optional[Atom]:
    """One robot_agent goal ``{type, object, from, to}`` in the common form (None for a goal that is not one)."""
    t, to = g.get("type"), str(g.get("to") or "")
    obj = g.get("object")
    if t in ("on", "in", "deliver"):
        c, col = ctx.object_class(obj)
        who = ctx.person(to) or (ctx.seat_of.get(to, "") if t == "deliver" else "")
        if who:                                                                      # R2: to a person = give
            return Atom("give", c, col, person=who)
        return Atom(PUT.get(t, "put_on"), c, col, to)
    if t in ("open", "close"):
        return Atom(t, dest=str(obj or ""))
    if t == "go":
        return Atom("go", dest=to)
    if t == "say":                                                                   # R3
        who = ctx.person(to) or ctx.seat_of.get(to, "")
        return Atom("say", person=who or f"?{to}")
    return Atom(f"?{t}")


def compatible(gold: Atom, pred: Atom, ctx: Context) -> bool:
    """R1 to R9: whether a predicted atom is the gold atom (equivalent forms count)."""
    if gold.kind != pred.kind or gold.cls != pred.cls or gold.person != pred.person:
        return False
    if gold.color and pred.color and gold.color != pred.color:                       # R7: an unsaid colour is not wrong
        return False
    if gold.kind == "go":                                                            # R4 / R5
        places = gold.dest if isinstance(gold.dest, tuple) else (gold.dest,)
        d = str(pred.dest)
        if d.startswith("@"):                                                        # a room key: gold must be that room only
            return bool(places) and all(ctx.room_of.get(x) == d[1:] for x in places)
        return d in places
    return gold.dest == pred.dest


def match(gold: list, pred: list, ctx: Context) -> tuple:
    """(matched [(gold, pred)], dropped [gold], spurious [pred]): a multiset matching, a predicted atom used once; an
    exact colour match is taken before a wildcard one."""
    free = list(range(len(pred)))
    pairs, dropped = [], []
    for g in gold:
        cands = [i for i in free if compatible(g, pred[i], ctx)]
        cands.sort(key=lambda i: (pred[i].color != g.color, i))
        if cands:
            free.remove(cands[0])
            pairs.append((g, pred[cands[0]]))
        else:
            dropped.append(g)
    return pairs, dropped, [pred[i] for i in free]


# ── one probe ───────────────────────────────────────────────────────────────────────────────────────────────

def expectation(td: dict, world) -> str:
    """act | ask | refuse: what the task wants of the first reading (kind clarify / refuse, a refusal-only compound)."""
    kinds = [s["kind"] for s in resolve_subtasks(td, world)]
    if td.get("kind") == "refuse" or (kinds and all(k == "refuse" for k in kinds)):
        return "refuse"
    return "ask" if td.get("kind") == "clarify" or "clarify" in kinds else "act"


def probe(task, planner_name: str, profile: str, seed: int, lang: str, text_mode: str, llm,
          budgets: Budgets = Budgets(), understand_model: Optional[str] = None) -> dict:
    """The understanding of one (task, language, text) and its comparison with the gold goals -> a record.
    ``understand_model``: robot_agent's option of that name for this probe (the planner model stays ``--model``)."""
    from .runner import InfraError
    td = task_dict(task)
    cls = planner_class(planner_name)
    if getattr(cls, "loop_kind", None) != "assist":
        raise ValueError(f"{planner_name}: understand-eval needs a SAGE planner (robot_agent:sage, ...)")
    env = EpisodeEnv(td, profile, seed, lang, budgets, llm=llm, privileged=False, interrupt_via="inject")
    env.planner_name = planner_name
    clean = (td.get("text") or {}).get(lang) or ""
    heard_event = env.instruction_event
    if text_mode == "clean":
        env.task_text = clean
    planner = make_planner(planner_name, llm=env.llm())
    if understand_model:
        planner.loop_options = {**planner.loop_options, "understand_model": understand_model}
    planner.until = STOP_EVENTS
    try:
        planner.run(env)
    except BudgetExceeded:
        planner.reached = {"event": "done", "status": "failed", "msg": "LLM budget exhausted"}
    except (LLMError, ImportError) as e:
        raise InfraError(f"task {env.task_id}: {type(e).__name__}: {e}") from e
    failed = getattr(env.llm(), "failed", None)
    if failed is not None:
        raise InfraError(f"task {env.task_id}: {type(failed).__name__}: {failed}") from failed
    ev = planner.reached or getattr(planner, "final", None) or {"event": "none"}
    rec = record(td, env, ctx_world=env.world0, ev=ev, lang=lang, text_mode=text_mode, clean=clean,
                 heard=env.task_text, heard_event=heard_event, llm_calls=env.llm_calls)
    if getattr(env, "llm_calls_understand", None) is not None:        # a variant (or --understand-model) with its own model
        info = getattr(planner, "loop_info", None) or {}
        rec["understand_model_used"] = info.get("understand_model_used")
        rec["fallback"] = info.get("fallback")
        rec["llm_calls_understand"] = int(env.llm_calls_understand)
    return rec


def record(td: dict, env, ctx_world, ev: dict, lang: str, text_mode: str, clean: str, heard: str, heard_event: str,
           llm_calls: int) -> dict:
    ctx = Context(ctx_world)
    gold = gold_atoms(td, ctx_world)
    kind = ev.get("event")
    goals = [g for g in (ev.get("goals") or []) if isinstance(g, dict)] if kind == "understand" else []
    status = ev.get("status") if kind == "understand" else {"understand_check": "repeat", "done": "ended"}.get(kind, "none")
    pred = [a for a in (robot_atom(g, ctx) for g in goals) if a is not None]
    pairs, dropped, spurious = match(gold, pred, ctx)
    question = str(ev.get("question") or "") if kind == "understand" else ""
    asked = bool(question) or status in ("ambiguous", "repeat")
    refused = status in ("infeasible", "unsafe") or (kind == "done" and ev.get("status") == "refused")
    confident = status == "clear" and not asked and bool(pred)
    exact = not dropped and not spurious and bool(gold)
    expect = expectation(td, ctx_world)
    mixed = expect != "refuse" and any(s["kind"] == "refuse" for s in resolve_subtasks(td, ctx_world))
    return {"task_id": td["id"], "lang": lang, "text": text_mode, "heard_text": heard, "clean_text": clean,
            "heard_event": heard_event, "kind": td.get("kind"), "structure": td.get("structure") or "single",
            "n_subtasks": td.get("n_subtasks") or 1, "mixed": mixed, "expect": expect,
            "gold": [a.text() for a in gold], "pred": [a.text() for a in pred],
            "matched": len(pairs), "dropped": [a.text() for a in dropped], "spurious": [a.text() for a in spurious],
            "exact": exact, "status": status, "reason": str(ev.get("reason") or ev.get("msg") or "")[:200],
            "question": question, "asked": asked, "refused": refused, "confident": confident,
            "confident_wrong": bool(confident and not exact), "raw_goals": goals,
            "ended": ev.get("msg") if kind == "done" else None, "llm_calls": llm_calls}


# ── summary ─────────────────────────────────────────────────────────────────────────────────────────────────

def _rate(a, b):
    return r6(a / b) if b else None


def stats(rows: list) -> dict:
    """Metrics of a group of records. Atom precision and recall are micro (summed over tasks); the task rates are over
    the group's tasks. ``confident_wrong`` counts a reading the robot would act on without asking (status clear, no
    question, some goal) that is not the gold set."""
    n = len(rows)
    gold = sum(len(r["gold"]) for r in rows)
    pred = sum(len(r["pred"]) for r in rows)
    tp = sum(r["matched"] for r in rows)
    conf = [r for r in rows if r["confident"]]
    return {"n": n, "exact": sum(1 for r in rows if r["exact"]), "exact_rate": _rate(sum(1 for r in rows if r["exact"]), n),
            "gold_atoms": gold, "pred_atoms": pred, "matched_atoms": tp,
            "atom_precision": _rate(tp, pred), "atom_recall": _rate(tp, gold),
            "dropped_atoms": sum(len(r["dropped"]) for r in rows), "spurious_atoms": sum(len(r["spurious"]) for r in rows),
            "tasks_with_dropped": sum(1 for r in rows if r["dropped"]), "tasks_with_spurious": sum(1 for r in rows if r["spurious"]),
            "n_confident": len(conf), "confident_wrong": sum(1 for r in conf if not r["exact"]),
            "confident_wrong_rate": _rate(sum(1 for r in conf if not r["exact"]), n),
            "confident_wrong_of_confident": _rate(sum(1 for r in conf if not r["exact"]), len(conf)),
            "asked": sum(1 for r in rows if r["asked"]), "refused": sum(1 for r in rows if r["refused"]),
            "no_goal": sum(1 for r in rows if not r["pred"]),
            "ended": sum(1 for r in rows if r["status"] == "ended" and not r["refused"])}


def _by(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(str(key(r)), []).append(r)
    return {k: stats(v) for k, v in sorted(out.items())}


def summarize(rows: list, config: dict) -> dict:
    """The run summary. ``headline`` = tasks of kind feasible with no refused part (a gold goal set to understand, no
    question wanted); clarify and refuse tasks, and mixed ones, have their own rows (``by_expect``, ``mixed``)."""
    head = [r for r in rows if r["expect"] == "act" and not r["mixed"]]
    by_cond = {}
    for r in head:
        by_cond.setdefault(f"{r['lang']}/{r['text']}", []).append(r)
    return {"config": config, "n_records": len(rows), "all": stats(rows), "headline": stats(head),
            "by_expect": _by(rows, lambda r: r["expect"]), "mixed": stats([r for r in rows if r["mixed"]]),
            "by_condition": {k: stats(v) for k, v in sorted(by_cond.items())},
            "by_lang": _by(head, lambda r: r["lang"]), "by_text": _by(head, lambda r: r["text"]),
            "by_structure": _by(head, lambda r: r["structure"]),
            "by_lang_structure": _by(head, lambda r: f"{r['lang']}/{r['structure']}"),
            "by_lang_text_structure": _by(head, lambda r: f"{r['lang']}/{r['text']}/{r['structure']}"),
            **({"understand": understand_counts(rows)} if any("understand_model_used" in r for r in rows) else {})}


def understand_counts(rows: list) -> dict:
    """Records of a run with an understand model: which model answered the reading, how many readings fell back to the
    planner (``runaway`` = the understand model's answer was no JSON, too long or repeating; ``unavailable`` = the model
    could not be called), calls on the understand model."""
    why: dict = {}
    for r in rows:
        if r.get("fallback"):
            why[r["fallback"]] = why.get(r["fallback"], 0) + 1
    used: dict = {}
    for r in rows:
        used[str(r.get("understand_model_used"))] = used.get(str(r.get("understand_model_used")), 0) + 1
    return {"n": len(rows), "model_used": dict(sorted(used.items())), "fallbacks": sum(why.values()),
            "fallbacks_by_reason": dict(sorted(why.items())),
            "runaway": sum(v for k, v in why.items() if k != "unavailable"),
            "llm_calls_understand": sum(int(r.get("llm_calls_understand") or 0) for r in rows),
            "ended": sum(1 for r in rows if r["status"] == "ended" and not r["refused"])}


def report(summary: dict) -> str:
    """report.md: the tables of summary.json."""
    def row(name, s):
        f = lambda x: "n/a" if x is None else f"{x:.3f}"        # noqa: E731
        return (f"| {name} | {s['n']} | {f(s['exact_rate'])} | {f(s['atom_precision'])} | {f(s['atom_recall'])} | "
                f"{s['dropped_atoms']} | {s['spurious_atoms']} | {s['confident_wrong']} ({f(s['confident_wrong_of_confident'])}) |")
    head = "| group | n | exact | atom precision | atom recall | dropped | spurious | confident wrong (of confident) |\n|---|---|---|---|---|---|---|---|"
    out = [f"# Understanding evaluation\n\nconfig: `{json.dumps(summary['config'], sort_keys=True, ensure_ascii=False)}`\n"]
    for title, key in (("Headline (feasible, no refused part)", None), ("By condition", "by_condition"),
                       ("By language", "by_lang"), ("By structure", "by_structure"),
                       ("By language and structure", "by_lang_structure"), ("By expected behaviour", "by_expect")):
        out.append(f"## {title}\n\n{head}")
        if key is None:
            out.append(row("headline", summary["headline"]))
            out.append(row("mixed (a refused part)", summary["mixed"]))
        else:
            out += [row(k, v) for k, v in summary[key].items()]
        out.append("")
    return "\n".join(out)


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────

def dumps(obj) -> str:
    return json.dumps(_round_tree(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def run_eval(tasks: list, planner_name: str, profile: str, seed: int, langs: list, texts: list, llm_spec: Optional[str],
             out_dir, model: Optional[str] = None, llm=None, budgets: Budgets = Budgets(), progress: bool = False,
             config: Optional[dict] = None, understand_model: Optional[str] = None) -> dict:
    """Probe every task in every language and text condition; write OUT/records.jsonl, summary.json, report.md. LLM
    calls are cached in OUT/llm_cache (a rerun with the same prompts makes no call). Returns the summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if llm is None and llm_spec:
        llm = make_llm(llm_spec, model, cache_dir=str(out / "llm_cache") if llm_spec != "fake" else None)
    rows, t0 = [], time.monotonic()
    for i, t in enumerate(tasks):
        for lang in langs:
            for tx in texts:
                rows.append(probe(t, planner_name, profile, seed, lang, tx, llm, budgets, understand_model))
        if progress and (i + 1) % 25 == 0:
            print(f"[understand-eval] {i + 1}/{len(tasks)} tasks {time.monotonic() - t0:.1f}s", file=sys.stderr)
    cfg = {"planner": planner_name, "profile": profile, "seed": int(seed), "langs": list(langs), "texts": list(texts),
           "model": model if llm_spec and llm_spec != "fake" else None, "llm": "fake" if llm_spec == "fake" else "live",
           "n_tasks": len(tasks), **({"understand_model": understand_model} if understand_model else {}), **(config or {})}
    summary = summarize(rows, cfg)
    if "understand" in summary:
        summary["config"]["n_fallbacks"] = summary["understand"]["fallbacks"]
    with (out / "records.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(dumps(r) + "\n")
    (out / "summary.json").write_text(json.dumps(_round_tree(summary), sort_keys=True, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    (out / "report.md").write_text(report(summary), encoding="utf-8")
    return summary
