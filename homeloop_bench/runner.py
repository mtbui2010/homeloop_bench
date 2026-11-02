"""Seeded Monte Carlo runner (docs/runner.md).

``run_episode`` plays one (task, seed) with one planner and returns the episode record;
``run_many`` plays ``tasks x seeds`` in (task order, seed) order and writes ``episodes.jsonl``,
``summary.json`` and ``report.md``. Same arguments -> identical files: every random draw is seeded from
(task id, seed) and no wall-clock value is written (wall time goes to stderr only).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from homeloop_robot.rng import r6
from homeloop_robot.types import _round_tree

from .env import Budgets, EpisodeEnv, task_dict
from .llm import BudgetExceeded, LLMError, llm_kind, make_llm
from .planners import make_planner, needs_llm, planner_available, planner_class

ERROR_RATE_MAX = 0.05     # a run with more planner errors than this exits non-zero (cli)


def dumps(obj) -> str:
    return json.dumps(_round_tree(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class PlannerConfigError(ValueError):
    pass


class InfraError(RuntimeError):
    """The run cannot be scored: the LLM server failed or the planner's code is not importable. The run is
    aborted (no summary is written), so an infrastructure failure never looks like a 0 % planner score."""


def check_llm(planner_name: str, llm_spec: Optional[str]) -> None:
    if needs_llm(planner_name) and not llm_spec:
        raise PlannerConfigError(f"planner {planner_name} needs --llm URL or --llm fake")


def check_planner(planner_name: str) -> None:
    ok, why = planner_available(planner_name)
    if not ok:
        raise PlannerConfigError(f"planner {planner_name} is unavailable: {why}")


def run_episode(task, planner_name: str, profile: str, seed: int, lang: str, llm_spec: Optional[str],
                budgets: Budgets = Budgets(), model: Optional[str] = None, llm=None) -> dict:
    """One episode -> its record (docs/runner.md "Episode record"). ``llm`` overrides ``llm_spec``
    (``run_many`` builds one client for the whole run)."""
    if llm is None and llm_spec:
        llm = make_llm(llm_spec, model)
    cls = planner_class(planner_name)
    env = EpisodeEnv(task, profile, seed, lang, budgets, llm=llm, privileged=bool(getattr(cls, "privileged", False)),
                     interrupt_via=getattr(cls, "interrupt_via", "robot"))
    env.planner_name = planner_name
    planner = make_planner(planner_name, llm=env.llm())
    try:
        planner.run(env)
        if env.status is None:
            env.finish("give_up", "planner returned without finishing")
    except BudgetExceeded:
        env.set_budget()
    except (LLMError, ImportError) as e:
        raise InfraError(f"task {env.task_id} seed {seed}: {type(e).__name__}: {e}") from e
    except Exception as e:  # noqa: BLE001 - any other planner crash is a failed episode (status "error")
        env.set_error(e)
        if getattr(planner, "raise_errors", False):
            raise
    failed = getattr(env.llm(), "failed", None)
    if failed is not None:              # an LLM error that the planner's own code swallowed
        raise InfraError(f"task {env.task_id} seed {seed}: {type(failed).__name__}: {failed}") from failed
    return env.record()


# ── task loading ────────────────────────────────────────────────────────────────────────────────────────

def load_tasks(split: Optional[str] = None, limit: Optional[int] = None, tasks_file: Optional[str] = None) -> list:
    """Tasks of a split (``homeloop_bench.tasks.load_split``) or of a JSONL file, first ``limit``."""
    if tasks_file:
        out = []
        with open(tasks_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        if split:
            same = [t for t in out if t.get("split") in (None, split)]
            out = same
    else:
        try:
            from .tasks import load_split
        except ImportError as e:
            raise RuntimeError("homeloop_bench.tasks is missing (bench data not installed); use --tasks FILE") from e
        out = list(load_split(split))
    if limit is not None:
        out = out[: int(limit)]
    return out


def data_sha(tasks: list) -> str:
    h = hashlib.sha256()
    for t in tasks:
        h.update(dumps(task_dict(t)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def git_commit(path) -> Optional[str]:
    """``git describe --always --dirty --abbrev=12`` of the checkout holding ``path`` (None outside git)."""
    try:
        p = Path(path).resolve()
        d = p if p.is_dir() else p.parent
        r = subprocess.run(["git", "-C", str(d), "describe", "--always", "--dirty", "--abbrev=12"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _versions(planner_name: str = "") -> dict:
    import importlib.util

    import homeloop_robot

    from . import __version__ as hb
    out = {"homeloop_bench": hb, "homeloop_robot": getattr(homeloop_robot, "__version__", ""),
           "homeloop_bench_git": git_commit(Path(__file__).parent),
           "homeloop_robot_git": git_commit(Path(homeloop_robot.__file__).parent)}
    if planner_name.startswith("robot_agent:"):
        for mod in ("robot_agent", "embodiplan"):
            try:
                spec = importlib.util.find_spec(mod)
            except (ImportError, ValueError):
                spec = None
            loc = (list(spec.submodule_search_locations or []) or [spec.origin]) if spec else []
            out[f"{mod}_git"] = git_commit(loc[0]) if loc and loc[0] else None
    return out


def split_shares(tasks: list) -> dict:
    """Label shares of a task list, for reweighting a prefix run (``summarize(split_shares=...)``)."""
    out = {"kind": {}, "n_subtasks": {}}
    for t in tasks:
        d = task_dict(t)
        out["kind"][str(d.get("kind"))] = out["kind"].get(str(d.get("kind")), 0) + 1
        ns = str(len(d.get("subtasks") or []) or 1)
        out["n_subtasks"][ns] = out["n_subtasks"].get(ns, 0) + 1
    n = max(1, len(tasks))
    return {k: {a: b / n for a, b in v.items()} for k, v in out.items()}


def _worker(args) -> list:
    tasks, idx, planner_name, profile, seeds, lang, llm_spec, model, budgets = args
    llm = make_llm(llm_spec, model) if llm_spec else None
    out = []
    for i, t in zip(idx, tasks):
        for s in range(seeds):
            out.append((i, s, run_episode(t, planner_name, profile, s, lang, llm_spec, budgets, model, llm=llm)))
    return out


def run_many(planner_name: str, split: Optional[str], limit: Optional[int], profile: str, seeds: int, lang: str,
             llm_spec: Optional[str], out_dir, model: Optional[str] = None, workers: int = 1,
             tasks: Optional[list] = None, tasks_file: Optional[str] = None, budgets: Budgets = Budgets(),
             llm=None, progress: bool = False) -> dict:
    """Run ``tasks x range(seeds)``, write DIR/episodes.jsonl, DIR/summary.json, DIR/report.md;
    returns the summary."""
    from . import report
    from .metrics import summarize
    from homeloop_robot import load_profile

    check_llm(planner_name, llm_spec if llm is None else "given")
    check_planner(planner_name)
    shares = None
    if tasks is None:
        full = load_tasks(split, None, tasks_file)
        tasks = full[: int(limit)] if limit is not None else full
        if len(tasks) < len(full):
            shares = split_shares(full)
    else:
        if limit is not None and int(limit) < len(tasks):
            shares = split_shares(tasks)
            tasks = list(tasks)[: int(limit)]
    t0 = time.monotonic()
    episodes = []
    if planner_name.startswith("robot_agent:"):
        workers = 1                     # robot_agent keeps module-level state
    if workers > 1 and llm is None and len(tasks) > 1:
        import concurrent.futures as cf
        import multiprocessing as mp
        n = min(workers, len(tasks))
        chunks = [list(range(i, len(tasks), n)) for i in range(n)]
        jobs = [([tasks[i] for i in ch], ch, planner_name, profile, seeds, lang, llm_spec, model, budgets)
                for ch in chunks]
        res = []
        with cf.ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn")) as ex:
            for part in ex.map(_worker, jobs):
                res += part
        res.sort(key=lambda x: (x[0], x[1]))
        episodes = [r for _, _, r in res]
    else:
        if llm is None and llm_spec:
            llm = make_llm(llm_spec, model, cache_dir=str(Path(out_dir) / "llm_cache") if llm_spec != "fake" else None)
        for i, t in enumerate(tasks):
            for s in range(int(seeds)):
                episodes.append(run_episode(t, planner_name, profile, s, lang, llm_spec, budgets, model, llm=llm))
            if progress and (i + 1) % 50 == 0:
                print(f"[run] {planner_name} {i + 1}/{len(tasks)} tasks {time.monotonic() - t0:.1f}s", file=sys.stderr)
    prof = load_profile(profile)
    config = {"planner": planner_name, "split": split, "limit": limit, "profile": profile, "seeds": int(seeds),
              "lang": lang, "llm": llm_kind(llm_spec), "model": (model if llm_spec and llm_spec != "fake" else None),
              "profile_sha": prof.sha, "data_sha": data_sha(tasks), "n_tasks": len(tasks),
              "versions": _versions(planner_name), "model_digest": _digest(llm, llm_spec, model),
              "budgets": {"max_calls": budgets.max_calls, "max_sim_time_s": r6(budgets.max_sim_time_s),
                          "max_llm_calls": budgets.max_llm_calls}}
    summary = summarize(episodes, config, split_shares=shares)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "episodes.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for e in episodes:
            f.write(dumps(e) + "\n")
    (out / "summary.json").write_text(json.dumps(_round_tree(summary), sort_keys=True, ensure_ascii=False, indent=1)
                                      + "\n", encoding="utf-8")
    (out / "report.md").write_text(report.render(summary, episodes), encoding="utf-8")
    print(f"[run] {planner_name} {len(episodes)} episodes in {time.monotonic() - t0:.1f}s wall -> {out}",
          file=sys.stderr)
    return summary


def _digest(llm, llm_spec, model) -> Optional[str]:
    """The Ollama model digest (``/api/tags``) of a URL run; None for fake / no LLM."""
    if not llm_spec or llm_spec == "fake":
        return None
    from .llm import model_digest
    try:
        return model_digest(llm_spec, model)
    except LLMError:
        return None


def read_episodes(dir_) -> list:
    out = []
    with (Path(dir_) / "episodes.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out
