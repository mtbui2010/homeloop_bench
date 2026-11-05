"""``homeloop-bench`` command line (docs/cli.md). Also ``python -m homeloop_bench.cli``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .llm import DEFAULT_MODEL

LIVE_PLANNERS = "robot_agent:sage,progprompt_like"


def cmd_planners(a) -> int:
    from .planners import list_planners
    for name, desc, avail in list_planners():
        line = f"{name}\t{desc}"
        if not avail:
            line += "\t[unavailable: robot_agent not importable]"
        print(line)
    return 0


def _budgets(a):
    from .env import Budgets
    d = Budgets()
    return Budgets(max_calls=a.max_calls or d.max_calls, max_sim_time_s=a.max_sim_time_s or d.max_sim_time_s,
                   max_llm_calls=a.max_llm_calls or d.max_llm_calls)


def cmd_run(a) -> int:
    from .planners import REGISTRY, is_spec
    from .runner import InfraError, PlannerConfigError, run_many
    if a.planner not in REGISTRY and not is_spec(a.planner):
        print(f"unknown planner {a.planner!r}; see `homeloop-bench planners` (or give package.module:ClassName)",
              file=sys.stderr)
        return 2
    try:
        prof = f"{a.profile}+{a.set}" if getattr(a, "set", None) else a.profile
        shard = None
        if getattr(a, "shard", None):
            try:
                k, n = (int(x) for x in a.shard.split("/"))
            except ValueError:
                print(f"--shard {a.shard!r}: use K/N, e.g. 0/3", file=sys.stderr)
                return 2
            shard = (k, n)
        s = run_many(a.planner, a.split, a.limit, prof, a.seeds, a.lang, a.llm, a.out, model=a.model,
                     workers=a.workers, tasks_file=a.tasks, budgets=_budgets(a), progress=True, shard=shard)
    except PlannerConfigError as e:
        print(str(e), file=sys.stderr)
        return 2
    except InfraError as e:
        print(f"run aborted, no summary written: {e}", file=sys.stderr)
        return 3
    print(json.dumps({k: s[k] for k in ("n_episodes", "success", "success_ci95", "false_success",
                                         "goal_condition_success", "help_rate", "rejection_rate", "n_error",
                                         "smoke")},
                     sort_keys=True))
    return error_rc(s)


def cmd_merge(a) -> int:
    from .runner import MergeError, merge_shards
    try:
        s = merge_shards(a.dir)
    except MergeError as e:
        print(f"merge failed: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: s[k] for k in ("n_episodes", "success", "success_ci95", "false_success", "n_error")},
                     sort_keys=True))
    return error_rc(s)


def cmd_prompt(a) -> int:
    """The first prompt SAGE builds for a task (robot_agent:sage / _norag), with --llm fake: shows its retrieval."""
    if a.llm != "fake":
        print("prompt builds the prompt without an LLM: use --llm fake", file=sys.stderr)
        return 2
    from .planners.robot_agent_adapter import built_prompt
    from .env import task_dict
    from .runner import load_tasks
    ts = [t for t in load_tasks(a.split, None, a.tasks) if task_dict(t).get("id") == a.task_id]
    if not ts:
        print(f"no task {a.task_id} in {a.tasks or a.split}", file=sys.stderr)
        return 1
    r = built_prompt(ts[0], a.planner, a.lang, a.profile, a.seed)
    if not a.full:
        r = {k: v for k, v in r.items() if k != "prompt"} | {"prompt_head": (r.get("prompt") or "")[:1500]}
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


def cmd_understand_eval(a) -> int:
    """Only robot_agent's understand step on a split / task file, compared with the gold goals (docs/understand_eval.md)."""
    from . import understand_eval as ue
    from .planners import REGISTRY
    from .runner import InfraError, PlannerConfigError, check_llm, check_planner, load_tasks
    if a.planner not in REGISTRY:
        print(f"unknown planner {a.planner!r}; see `homeloop-bench planners`", file=sys.stderr)
        return 2
    if a.split == "test" and not a.tasks:
        print("understand-eval does not run on the test split (tune on train, validate on dev)", file=sys.stderr)
        return 2
    try:
        check_llm(a.planner, a.llm)
        check_planner(a.planner)
        tasks = load_tasks(None if a.tasks else a.split, None, a.tasks)
    except PlannerConfigError as e:
        print(str(e), file=sys.stderr)
        return 2
    from .planners import planner_class
    if getattr(planner_class(a.planner), "loop_kind", None) != "assist":
        print(f"{a.planner}: understand-eval needs a SAGE planner (robot_agent:sage, ...)", file=sys.stderr)
        return 2
    if any(ue.task_dict(t).get("split") == "test" for t in tasks):
        print("understand-eval does not run on test tasks (tune on train, validate on dev)", file=sys.stderr)
        return 2
    tasks = tasks[int(a.offset or 0):][: int(a.limit)] if a.limit is not None else tasks[int(a.offset or 0):]
    langs = [x.strip() for x in a.lang.split(",") if x.strip()]
    texts = ["clean", "asr"] if a.text == "both" else [a.text]
    if not tasks or any(x not in ("en", "ko") for x in langs):
        print("no tasks, or --lang is not en / ko / en,ko", file=sys.stderr)
        return 2
    try:
        s = ue.run_eval(tasks, a.planner, a.profile, a.seed, langs, texts, a.llm, a.out, model=a.model, budgets=_budgets(a),
                        progress=True, config={"split": a.split if not a.tasks else None, "tasks_file": a.tasks,
                                               "offset": int(a.offset or 0), "limit": a.limit})
    except InfraError as e:
        print(f"understand-eval aborted, no summary written: {e}", file=sys.stderr)
        return 3
    print(json.dumps({"n_records": s["n_records"], "headline": {k: s["headline"][k] for k in (
        "n", "exact_rate", "atom_precision", "atom_recall", "dropped_atoms", "spurious_atoms", "confident_wrong",
        "confident_wrong_of_confident")}}, sort_keys=True))
    if s["all"]["ended"] > 0.05 * max(1, s["n_records"]):
        print(f"{s['all']['ended']} of {s['n_records']} probes ended before the understand step (an error, not a reading); "
              f"see records.jsonl 'ended'", file=sys.stderr)
        return 4
    return 0


def error_rc(s: dict) -> int:
    """Non-zero when more than ERROR_RATE_MAX of the episodes crashed (status "error")."""
    from .runner import ERROR_RATE_MAX
    if s.get("n_episodes") and (s.get("error_rate") or 0.0) > ERROR_RATE_MAX:
        print(f"{s['n_error']} of {s['n_episodes']} episodes crashed (status error, {s.get('errors_by_type')}); "
              f"the scores are not a planner result", file=sys.stderr)
        return 4
    return 0


def _success_map(dir_) -> dict:
    from .runner import read_episodes
    return {(e["task_id"], e["seed"]): bool(e["success"]) for e in read_episodes(dir_)}


def cmd_compare(a) -> int:
    from .metrics import compare
    res = compare(_success_map(a.dir_a), _success_map(a.dir_b))
    res["a"], res["b_dir"] = str(a.dir_a), str(a.dir_b)
    if a.json:
        print(json.dumps(res, sort_keys=True))
        return 0
    print(f"paired McNemar test on (task, seed): A = {a.dir_a}  B = {a.dir_b}")
    print("| n_pairs | success A | success B | b (A ok, B fail) | c (A fail, B ok) | statistic | p | method |")
    print("|---|---|---|---|---|---|---|---|")
    fmt = lambda x: "n/a" if x is None else (f"{x:.4f}" if isinstance(x, float) else str(x))  # noqa: E731
    print(f"| {res['n_pairs']} | {fmt(res['success_a'])} | {fmt(res['success_b'])} | {res['b']} | {res['c']} | "
          f"{fmt(res['statistic'])} | {fmt(res['p_value'])} | {res['method']} |")
    if "task_permutation" in res:
        m, pt = res["task_majority_mcnemar"], res["task_permutation"]
        print(f"\n{res['max_seeds_per_task']} seeds per task: seeds of one task are correlated, so use the "
              f"task-level tests below for claims (docs/metrics.md).")
        print("| test | n | statistic | p |")
        print("|---|---|---|---|")
        print(f"| McNemar on per-task majority ({m['method']}) | {m['n_pairs']} tasks | {fmt(m['statistic'])} | "
              f"{fmt(m['p_value'])} |")
        print(f"| task sign-flip permutation ({pt['n_perm']} perms) | {pt['n_tasks']} tasks | {fmt(pt['statistic'])} | "
              f"{fmt(pt['p_value'])} |")
    return 0


def cmd_report(a) -> int:
    from .report import render
    from .runner import read_episodes
    s = json.loads((Path(a.dir) / "summary.json").read_text(encoding="utf-8"))
    text = render(s, read_episodes(a.dir))
    (Path(a.dir) / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


def cmd_show(a) -> int:
    from .runner import load_tasks
    if a.tasks:
        ts = [t for t in load_tasks(None, None, a.tasks) if t.get("id") == a.task_id]
        if not ts:
            print(f"no task {a.task_id}", file=sys.stderr)
            return 1
        t = ts[0]
    else:
        from .tasks import task_by_id
        from .env import task_dict
        t = task_dict(task_by_id(a.task_id))
    print(json.dumps(t, ensure_ascii=False, sort_keys=True, indent=1))
    return 0


def cmd_calibrate(a) -> int:
    from .llm import make_llm
    from .planners.knowno_like import CALIB_PATH, calibrate
    from .runner import load_tasks
    llm = make_llm(a.llm, a.model)
    tasks = load_tasks(a.split, a.limit, a.tasks)
    c = calibrate(tasks, llm, epsilon=a.epsilon, lang=a.lang)
    c.update({"split": a.split, "limit": a.limit, "model": a.model if a.llm != "fake" else "fake", "lang": a.lang})
    out = Path(a.out) if a.out else CALIB_PATH
    out.write_text(json.dumps(c, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(c, sort_keys=True))
    return 0


def live_dir(root, planner: str, model: str, lang: str) -> Path:
    return Path(root) / f"{planner}__{model}__{lang}"


def cmd_live_smoke(a) -> int:
    from .runner import InfraError, PlannerConfigError, run_many
    root = Path(a.root)
    rc = 0
    for p in [x.strip() for x in a.planners.split(",") if x.strip()]:
        for lang in [x.strip() for x in a.langs.split(",") if x.strip()]:
            out = live_dir(root, p, a.model, lang)
            try:
                s = run_many(p, a.split, a.limit, a.profile, a.seeds, lang, a.llm, out, model=a.model,
                             tasks_file=a.tasks, progress=True)
            except PlannerConfigError as e:
                print(str(e), file=sys.stderr)
                return 2
            except InfraError as e:
                print(f"live smoke aborted at {p} / {lang}, no summary written: {e}", file=sys.stderr)
                return 3
            print(json.dumps({"planner": p, "lang": lang, "dir": str(out), "success": s["success"],
                              "n_episodes": s["n_episodes"], "false_success": s["false_success"],
                              "n_error": s["n_error"]}, sort_keys=True))
            rc = rc or error_rc(s)
    return rc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="homeloop-bench", description="HomeLoop-Bench runner (docs/cli.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("planners", help="list planners").set_defaults(fn=cmd_planners)

    r = sub.add_parser("run", help="run a planner on a split")
    r.add_argument("--planner", required=True)
    r.add_argument("--split", default="dev")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--profile", default="real", choices=["ideal", "real", "stress"])
    r.add_argument("--seeds", type=int, default=1)
    r.add_argument("--lang", default="en", choices=["en", "ko"])
    r.add_argument("--llm", default=None, help="Ollama URL (http://host:port) or 'fake' (tests only)")
    r.add_argument("--model", default=DEFAULT_MODEL)
    r.add_argument("--out", required=True)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--tasks", default=None, help="a task JSONL file instead of the packaged split")
    r.add_argument("--set", default=None, metavar="KEY=V[,KEY=V]",
                   help="override scalar profile parameters, e.g. asr.ko.app_cer=0.02 (sensitivity runs; the "
                        "summary's config.profile and profile_sha record it)")
    r.add_argument("--shard", default=None, metavar="K/N",
                   help="run only the tasks at index i %% N == K (same order, seeds, settings) -> OUT/shard<K>/; "
                        "then `merge OUT`")
    r.add_argument("--max-calls", type=int, default=None)
    r.add_argument("--max-sim-time-s", type=float, default=None)
    r.add_argument("--max-llm-calls", type=int, default=None)
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("compare", help="paired McNemar test of two run directories")
    c.add_argument("dir_a")
    c.add_argument("dir_b")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_compare)

    mg = sub.add_parser("merge", help="merge DIR/shard<K>/ runs into DIR (episodes, summary, report, llm_cache)")
    mg.add_argument("dir")
    mg.set_defaults(fn=cmd_merge)

    pr = sub.add_parser("prompt", help="the first prompt robot_agent:sage(_norag) builds for a task (--llm fake)")
    pr.add_argument("task_id")
    pr.add_argument("--planner", default="robot_agent:sage")
    pr.add_argument("--split", default="dev")
    pr.add_argument("--tasks", default=None)
    pr.add_argument("--lang", default="en", choices=["en", "ko"])
    pr.add_argument("--profile", default="real", choices=["ideal", "real", "stress"])
    pr.add_argument("--seed", type=int, default=0)
    pr.add_argument("--llm", default="fake")
    pr.add_argument("--full", action="store_true", help="print the whole prompt")
    pr.set_defaults(fn=cmd_prompt)

    ue = sub.add_parser("understand-eval", help="robot_agent's understand step only, compared with the gold goals "
                                                "(records.jsonl, summary.json, report.md in --out)")
    ue.add_argument("--planner", default="robot_agent:sage", help="a SAGE planner; its options, ENV and translate model are used")
    ue.add_argument("--split", default="train", choices=["train", "dev", "test"], help="the test split is refused")
    ue.add_argument("--tasks", default=None, help="a task JSONL file instead of the packaged split")
    ue.add_argument("--limit", type=int, default=None)
    ue.add_argument("--offset", type=int, default=0)
    ue.add_argument("--lang", default="en", help="en, ko or en,ko")
    ue.add_argument("--text", default="both", choices=["clean", "asr", "both"],
                    help="clean: the task's own text; asr: the text after the profile's simulated speech recognition")
    ue.add_argument("--profile", default="real", choices=["ideal", "real", "stress"], help="the speech-recognition profile")
    ue.add_argument("--seed", type=int, default=0, help="the episode seed (the speech-recognition draw)")
    ue.add_argument("--llm", default=None, help="Ollama URL (http://host:port) or 'fake' (tests only)")
    ue.add_argument("--model", default=DEFAULT_MODEL)
    ue.add_argument("--out", required=True)
    ue.add_argument("--max-calls", type=int, default=None)
    ue.add_argument("--max-sim-time-s", type=float, default=None)
    ue.add_argument("--max-llm-calls", type=int, default=None)
    ue.set_defaults(fn=cmd_understand_eval)

    rp = sub.add_parser("report", help="re-render DIR/report.md")
    rp.add_argument("dir")
    rp.set_defaults(fn=cmd_report)

    sh = sub.add_parser("show", help="print one task")
    sh.add_argument("task_id")
    sh.add_argument("--tasks", default=None)
    sh.set_defaults(fn=cmd_show)

    k = sub.add_parser("calibrate-knowno", help="conformal threshold for knowno_like")
    k.add_argument("--split", default="train")
    k.add_argument("--limit", type=int, default=300)
    k.add_argument("--llm", required=True)
    k.add_argument("--model", default=DEFAULT_MODEL)
    k.add_argument("--epsilon", type=float, default=0.15)
    k.add_argument("--lang", default="en", choices=["en", "ko"])
    k.add_argument("--tasks", default=None)
    k.add_argument("--out", default=None)
    k.set_defaults(fn=cmd_calibrate)

    ls = sub.add_parser("live-smoke", help="live smoke runs -> results/live_smoke/<planner>__<model>__<lang>/")
    ls.add_argument("--llm", required=True)
    ls.add_argument("--model", default=DEFAULT_MODEL)
    ls.add_argument("--limit", type=int, default=100)
    ls.add_argument("--split", default="dev")
    ls.add_argument("--profile", default="real", choices=["ideal", "real", "stress"])
    ls.add_argument("--seeds", type=int, default=1)
    ls.add_argument("--planners", default=LIVE_PLANNERS)
    ls.add_argument("--langs", default="en,ko")
    ls.add_argument("--root", default="results/live_smoke")
    ls.add_argument("--tasks", default=None)
    ls.set_defaults(fn=cmd_live_smoke)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
