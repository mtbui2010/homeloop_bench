"""Primary cause of each failed episode (docs/experiments.md).   python -m homeloop_bench.failures DIR [--json]

A rule-based reading of the episode record: the first rule that matches names the cause. It reads only the
record (calls, goal atoms, status, the planner's final message and the ask replies), never the planner's
prompts. It is an analysis aid, not a score: a cause is the most visible reason, and an episode can have
several. Check a sample by hand before quoting the counts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from .env import MOTION

# rule order = priority
CAUSES = (
    ("crash", "the planner crashed (status error)"),
    ("budget", "the episode or LLM call budget ran out"),
    ("wrong_refusal", "refused a task (or part) that was feasible or needed a question"),
    ("missed_refusal", "a refuse task was not refused"),
    ("ask_unanswered", "no motion and no failed call; the last question got no reply (timeout) or a non-answer"),
    ("ask_loop", "no motion and no failed call; gave up after questions the user answered"),
    ("no_plan", "no motion, no failed call and no question: gave up before acting"),
    ("robot_failure", "an injected robot failure was not recovered"),
    ("not_found", "a search ended without the object (absent / not found) and was not recovered"),
    ("other_skill_failure", "another failed skill call that was not recovered"),
    ("user_error", "an injected wrong user reply was not recovered (the user told the robot something wrong)"),
    ("delivery_wrong", "a delivered(obj, person) atom failed: set down out of reach, on a seat, or no handover"),
    ("claimed_unmet", "claimed done but goal atoms do not hold (false success)"),
    ("gave_up_after_acting", "acted, then gave up with goal atoms unmet and no unrecovered failure"),
    ("order_or_semantic", "goal atoms hold but the order or a semantic rule was violated"),
    ("other", "none of the above"),
)
NON_ANSWERS = ("no_answer", "not_sure")          # homeloop_robot user.answer kinds without content


def _refuse_only(e: dict) -> bool:
    return e.get("kind") == "refuse" and not e.get("mixed_kind")


def cause(e: dict) -> str:
    calls = e.get("calls") or []
    st = e.get("status")
    if st == "error":
        return "crash"
    if st == "budget":
        return "budget"
    if not _refuse_only(e) and (st == "refuse" or (e.get("refused") and e.get("unmatched_refusals"))):
        return "wrong_refusal"
    if _refuse_only(e):
        return "missed_refusal" if st != "refuse" else "other"
    moved = any(c.get("ok") and c.get("skill") in MOTION for c in calls)
    asks = [c for c in calls if c.get("skill") == "ask"]
    skill_at = {c.get("k"): c.get("skill") for c in calls}
    fails = [f for f in (e.get("failures") or [])
             if not f.get("recovered") and skill_at.get(f.get("k")) not in ("ask", "say", "announce")]
    tried = [c for c in calls if not c.get("ok") and c.get("skill") not in ("ask", "say", "announce")]
    if not moved and st != "done" and not tried:
        if asks:
            last = asks[-1]
            if not last.get("ok") or (last.get("reply_kind") or "") in NON_ANSWERS:
                return "ask_unanswered"
            return "ask_loop"
        return "no_plan"
    if any(f.get("injected") and f.get("code") != "absent" for f in fails):
        return "robot_failure"
    if any(f.get("code") == "absent" for f in fails):
        return "not_found"
    if fails:
        return "other_skill_failure"
    if any(f.get("code") == "user_wrong_answer" and not f.get("recovered") for f in (e.get("failures") or [])):
        return "user_error"
    if any(not d.get("ok") for d in (e.get("delivery_atoms") or [])) and (moved or st == "done"):
        return "delivery_wrong"
    atoms_ok = all(h for _, h in (e.get("goal_atoms") or []))
    if st == "done" and not atoms_ok:
        return "claimed_unmet"
    if st != "done" and not atoms_ok:
        return "gave_up_after_acting"
    if atoms_ok and (not e.get("order_ok", True) or e.get("semantic_violations")):
        return "order_or_semantic"
    return "other"


def analyse(episodes: list, examples: int = 5) -> dict:
    failed = [e for e in episodes if not e.get("success")]
    by = defaultdict(list)
    for e in failed:
        by[cause(e)].append(e["task_id"])
    order = [c for c, _ in CAUSES]
    return {"n": len(episodes), "n_failed": len(failed),
            "causes": {c: {"n": len(by[c]), "examples": by[c][:examples]} for c in order if by[c]},
            "false_success_by_cause": dict(Counter(cause(e) for e in failed if e.get("false_success")))}


def main(argv=None) -> int:
    from .runner import read_episodes
    ap = argparse.ArgumentParser(prog="python -m homeloop_bench.failures")
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--examples", type=int, default=5)
    a = ap.parse_args(argv)
    out = {d: analyse(read_episodes(d), a.examples) for d in a.dirs}
    if a.json:
        print(json.dumps(out, sort_keys=True, ensure_ascii=False))
        return 0
    desc = dict(CAUSES)
    for d, r in out.items():
        print(f"{d}: {r['n_failed']} of {r['n']} failed")
        for c, v in r["causes"].items():
            print(f"  {c:22s} {v['n']:4d}  {desc[c]}  e.g. {', '.join(v['examples'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
