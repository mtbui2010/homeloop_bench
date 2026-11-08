"""Rescore recorded runs with the round 19 judge (docs/metrics.md "Rescoring recorded runs").

Two tools, both pure over recorded episodes:

* :func:`annotate` (``homeloop-bench rescore OLD_DIR --out NEW_DIR``): adds the part split (``subtask_outcome``,
  ``subtask_kinds``, ``misread_refusals``) to every episode the record is enough for, and writes a new summary. It never
  changes ``success``. An episode it cannot decide is listed in ``needs_rerun`` with the reason.
* :func:`diff` (``homeloop-bench rescore-diff OLD_DIR NEW_DIR``): compares an old run with a rerun of the same
  configuration (``run --llm cache-only --shared-cache C --replicate R``). The only differences allowed are the new fields
  and, on a mixed task with a refuse part, the fields the refusal fixes; any other difference means behaviour moved and
  the rescore is refused.

What the record is enough for: for a refuse part, "the unmoved atom holds" is in ``goal_atoms`` and "a refusal named it"
is ``subtask_correct`` (the r17 judge credited it only then). What it is NOT enough for: a robot_agent run that declared a
partial refusal in its ``done`` event (the old adapter did not pass it on, and the event is not recorded): any
robot_agent episode that claimed done and left a refuse part unrefused is listed for a rerun. A part credited through a
place or a person id (the r17 rule J1 removed) cannot be told from a credit through the subtask index: listed too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import refusals as R

NEW_FIELDS = ("refusals", "misread_refusals", "subtask_kinds", "subtask_outcome")
# on a mixed task with a refuse part, these may change when a refusal reaches the judge or J1 removes a credit
REFUSAL_FIELDS = ("success", "false_success", "gc", "subtask_correct", "partial_refusals", "unmatched_refusals",
                  "refusal_texts", "refused", "final_say_check", "events", "calls", "llm_cache", "failures")
IGNORED = ("llm_cache",)          # cache bookkeeping differs between a live run and a replay


def load_tasks(path=None) -> dict:
    """{id: task} of the packaged train and dev splits (never test), plus the records of a ``--tasks`` file."""
    from .data import SPLITS
    from .tasks import read_records
    out = {}
    for sp in SPLITS:
        if sp != "test":
            out.update({r["id"]: r for r in read_records(sp)})
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def _read(path) -> list:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def has_refuse_part(task: dict) -> bool:
    return any(s.get("kind") == "refuse" for s in task.get("subtasks") or []) or task.get("kind") == "refuse"


def annotate_episode(e: dict, task: dict) -> tuple:
    """(episode with the part split, reason it needs a rerun or None)."""
    from .env import EpisodeEnv
    if "subtask_outcome" in e:
        return e, None
    env = EpisodeEnv(task, e.get("profile") or "ideal", int(e.get("seed") or 0), e.get("lang") or "en", privileged=True)
    kinds = [s["kind"] for s in env.subtasks]
    atoms = e.get("goal_atoms") or []
    corr = e.get("subtask_correct") or []
    if e.get("goal_changed"):             # a stop or a correction: no parts (the same record as the r19 judge writes)
        return dict(e, subtask_kinds=[], subtask_outcome=[], misread_refusals=0, split_source="derived"), None
    if len(corr) != len(kinds) or len(atoms) != sum(len(s["goal"]["all"]) for s in env.subtasks):
        return e, "record lacks per-part goal atoms (stop/correction episode or incomplete record)"
    status = e.get("status")
    whole = status == "refuse"
    keys = [env._part_keys(i) for i in range(len(kinds))]
    texts = e.get("refusal_texts") or []
    partial_texts = texts[:int(e.get("partial_refusals") or 0)]      # (the partial refusals come first, a whole one last)
    named_text = [any(R.names_keys({"text": t}, ky) for t in partial_texts) for ky in keys]
    out, pos, reason = [], 0, None
    for i, (k, s) in enumerate(zip(kinds, env.subtasks)):
        n = len(s["goal"]["all"])
        holds = all(bool(h) for _a, h in atoms[pos:pos + n])
        pos += n
        if k == "refuse":
            if holds and corr[i] and not whole and not named_text[i]:
                reason = reason or "refuse part credited by an id or index the text does not show (J1 may remove it)"
            out.append(R.subtask_outcome(k, holds, bool(corr[i]) and holds, False, whole))
        else:
            out.append(R.subtask_outcome(k, holds, named_text[i], False, whole))
    claimed_unrefused = (str(e.get("planner", "")).startswith("robot_agent:") and status == "done"
                         and any(k == "refuse" and o == "not_refused" for k, o in zip(kinds, out)))
    if claimed_unrefused:
        reason = "a robot_agent run claimed done and left a refuse part unrefused: its `done` event may have declared " \
                 "a refusal the old adapter did not pass on (not recorded)"
    # misread: partial refusals that name no part at all. The record keeps the count of those naming no REFUSE part
    # (unmatched); of them, the ones whose text names a feasible part are not misread.
    unmatched = int(e.get("unmatched_refusals") or 0)
    on_feasible = sum(1 for t in partial_texts if any(
        R.names_keys({"text": t}, ky) for k, ky in zip(kinds, keys) if k != "refuse"))
    misread = max(0, unmatched - on_feasible)
    new = dict(e)
    new.update({"subtask_kinds": kinds, "subtask_outcome": out, "misread_refusals": misread, "split_source": "derived"})
    return new, reason


def annotate(episodes: list, tasks: dict) -> tuple:
    """(annotated episodes, needs_rerun [{task_id, seed, planner, lang, reason}], missing task ids)."""
    out, rerun, missing = [], [], []
    for e in episodes:
        t = tasks.get(e.get("task_id"))
        if t is None:
            out.append(e)
            missing.append(e.get("task_id"))
            continue
        new, why = annotate_episode(e, t)
        out.append(new)
        if why:
            rerun.append({"task_id": e["task_id"], "seed": e.get("seed"), "planner": e.get("planner"),
                          "lang": e.get("lang"), "reason": why})
    return out, rerun, sorted(set(missing))


def rescore_dir(old_dir, out_dir, tasks_file=None) -> dict:
    """Write OUT/episodes.jsonl (annotated), OUT/summary.json, OUT/report.md and OUT/rescore.json."""
    from .metrics import summarize
    from .report import render
    old = Path(old_dir)
    eps = _read(old / "episodes.jsonl")
    summ = json.loads((old / "summary.json").read_text(encoding="utf-8"))
    new_eps, rerun, missing = annotate(eps, load_tasks(tasks_file))
    cfg = dict(summ.get("config") or {})
    cfg["rescore"] = "r19 offline (part split added; success unchanged)"
    s = summarize(new_eps, cfg, split_shares=summ.get("split_shares") if summ.get("smoke") else None)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "episodes.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in new_eps),
                                        encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render(s, new_eps), encoding="utf-8")
    changed = [k for k in ("success", "false_success", "success_ci95", "goal_condition_success")
               if summ.get(k) != s.get(k)]
    info = {"old": str(old), "n_episodes": len(eps), "n_derived": sum(1 for e in new_eps if e.get("split_source")),
            "n_needs_rerun": len(rerun), "needs_rerun": rerun, "tasks_missing": missing,
            "headline_changed": changed}
    (out / "rescore.json").write_text(json.dumps(info, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return info


def diff(old_eps: list, new_eps: list, tasks: dict, subset: bool = False) -> dict:
    """Compare a run with its rerun, episode by episode on (task, seed). ``unexpected`` must be empty."""
    key = lambda e: (e["task_id"], e["seed"])           # noqa: E731
    o, n = {key(e): e for e in old_eps}, {key(e): e for e in new_eps}
    only_old, only_new = sorted(set(o) - set(n)), sorted(set(n) - set(o))
    if subset:                                   # the rerun covers some tasks of the old run only
        only_old = []
    identical = changed = 0
    allowed, unexpected, misses, flips = [], [], [], []
    for k in sorted(set(o) & set(n)):
        a, b = o[k], n[k]
        if b.get("status") == "replay_miss":
            misses.append({"task_id": k[0], "seed": k[1]})
            continue
        fields = sorted(f for f in set(a) | set(b) if f not in NEW_FIELDS and f not in IGNORED and a.get(f) != b.get(f))
        if not fields:
            identical += 1
            continue
        changed += 1
        mixed = has_refuse_part(tasks.get(k[0]) or {}) and a.get("n_subtasks", 1) > 1
        if mixed and set(fields) <= set(REFUSAL_FIELDS):
            allowed.append({"task_id": k[0], "seed": k[1], "fields": fields})
            if a["success"] != b["success"]:
                flips.append({"task_id": k[0], "seed": k[1], "success": [a["success"], b["success"]],
                              "false_success": [a["false_success"], b["false_success"]]})
        else:
            unexpected.append({"task_id": k[0], "seed": k[1], "fields": fields})
    return {"n_old": len(o), "n_new": len(n), "identical": identical, "changed": changed,
            "changed_allowed": allowed, "success_flips": flips, "unexpected": unexpected, "replay_miss": misses,
            "only_in_old": [list(x) for x in only_old], "only_in_new": [list(x) for x in only_new],
            "ok": not unexpected and not only_old and not only_new}


def diff_dirs(old_dir, new_dir, tasks_file=None, out: Optional[str] = None, subset: bool = False) -> dict:
    d = diff(_read(Path(old_dir) / "episodes.jsonl"), _read(Path(new_dir) / "episodes.jsonl"), load_tasks(tasks_file), subset)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(d, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return d
