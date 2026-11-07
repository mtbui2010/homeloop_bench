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

from .env import Budgets, EpisodeEnv, give_up_text, task_dict
from .llm import BudgetExceeded, CachedLLM, FakeLLM, LLMError, llm_kind, make_llm
from .user_intent import classifier_kind
from .planners import make_planner, needs_llm, planner_available, planner_class

ERROR_RATE_MAX = 0.05     # a run with more planner errors than this exits non-zero (cli)


def dumps(obj) -> str:
    return json.dumps(_round_tree(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class PlannerConfigError(ValueError):
    pass


class StaleTasksError(PlannerConfigError):
    """A ``--tasks`` file holds records that differ from the packaged ones with the same id (H1: a file written before a
    data fix, e.g. the tell_fetch re-render, silently measures the old text)."""


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
    tally0 = CachedLLM.tally_snapshot()
    env = EpisodeEnv(task, profile, seed, lang, budgets, llm=llm, privileged=bool(getattr(cls, "privileged", False)),
                     interrupt_via=getattr(cls, "interrupt_via", "robot"))
    env.planner_name = planner_name
    planner = make_planner(planner_name, llm=env.llm())
    try:
        planner.run(env)
        if env.status is None:
            env.finish("give_up", give_up_text(env.lang), reason="planner returned without finishing")
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
    rec = env.record()
    # H4: how many of this episode's LLM prompts were answered from the run's own cache ("hits"), from the file shared
    # by the configurations of a replicate ("shared") and by the server ("misses"). misses > 0 = the episode is
    # "touched": it asked something no earlier configuration asked, so a difference to them may come from there.
    # Only a cached URL run has the field (a run with no cache or the fake LLM writes the record as before).
    t1 = CachedLLM.tally_snapshot()
    d = {k: t1[k] - tally0[k] for k in t1}
    if any(d.values()):
        rec["llm_cache"] = {**d, "touched": d["misses"] > 0}
    return rec


# ── task loading ────────────────────────────────────────────────────────────────────────────────────────

def stale_records(records: list) -> list:
    """Ids of ``records`` (dicts of a task file) that exist in the packaged train / dev split with other content.
    A record whose id is not packaged (fixtures, custom tasks) is never stale. The test split is not read: a record
    of the test split (by its ``split`` field or its id) is not compared."""
    from .data import SPLITS
    from .tasks import read_records
    packaged: dict = {}
    for sp in SPLITS:
        if sp == "test":
            continue
        for r in read_records(sp):
            packaged[r.get("id")] = r
    bad = []
    for r in records:
        if not isinstance(r, dict):
            continue
        ref = packaged.get(r.get("id"))
        if ref is not None and json.dumps(ref, sort_keys=True) != json.dumps(r, sort_keys=True):
            bad.append(r.get("id"))
    return bad


def check_fresh_tasks(records: list, path, allow_stale: bool = False) -> None:
    """Refuse a task file whose records differ from the packaged ones (see :func:`stale_records`) unless ``allow_stale``."""
    if allow_stale:
        return
    try:
        bad = stale_records(records)
    except (ImportError, OSError):          # no packaged data to compare with: nothing to check
        return
    if bad:
        raise StaleTasksError(
            f"{path}: {len(bad)} of {len(records)} records differ from the packaged split (first: "
            f"{', '.join(map(str, bad[:5]))}). The file is older than the data; regenerate it from the packaged split "
            f"(`homeloop-bench tasks-file`) or pass --allow-stale to measure the old text on purpose")


def load_tasks(split: Optional[str] = None, limit: Optional[int] = None, tasks_file: Optional[str] = None,
               allow_stale: bool = False) -> list:
    """Tasks of a split (``homeloop_bench.tasks.load_split``) or of a JSONL file, first ``limit``. A file whose
    records differ from the packaged ones with the same id is refused (:class:`StaleTasksError`) unless
    ``allow_stale``."""
    if tasks_file:
        out = []
        with open(tasks_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        check_fresh_tasks(out, tasks_file, allow_stale)
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


def planner_run_config(planner_name: str) -> Optional[dict]:
    """The planner's own settings for summary.json (``run_config()``: e.g. robot_agent:sage's variant and seed-pool
    sha256), None when it has none."""
    fn = getattr(planner_class(planner_name), "run_config", None)
    return fn() if callable(fn) else None


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
    tasks, idx, planner_name, profile, seeds, lang, llm_spec, model, budgets, cache_dir = args
    llm = make_llm(llm_spec, model, cache_dir=cache_dir) if llm_spec else None
    out = []
    for i, t in zip(idx, tasks):
        for s in range(seeds):
            out.append((i, s, run_episode(t, planner_name, profile, s, lang, llm_spec, budgets, model, llm=llm)))
    return out


def run_many(planner_name: str, split: Optional[str], limit: Optional[int], profile: str, seeds: int, lang: str,
             llm_spec: Optional[str], out_dir, model: Optional[str] = None, workers: int = 1,
             tasks: Optional[list] = None, tasks_file: Optional[str] = None, budgets: Budgets = Budgets(),
             llm=None, progress: bool = False, shard: Optional[tuple] = None, allow_stale: bool = False) -> dict:
    """Run ``tasks x range(seeds)``, write DIR/episodes.jsonl, DIR/summary.json, DIR/report.md;
    returns the summary. ``shard=(k, n)``: only the tasks at index ``i % n == k`` of the run's task list (same
    order, seeds and settings), written to DIR/shard<k>/ with a shard.json for :func:`merge_shards`."""
    from .metrics import summarize
    from homeloop_robot import load_profile

    check_llm(planner_name, llm_spec if llm is None else "given")
    check_planner(planner_name)
    shares = None
    if tasks is None:
        full = load_tasks(split, None, tasks_file, allow_stale)
        tasks = full[: int(limit)] if limit is not None else full
        if len(tasks) < len(full):
            shares = split_shares(full)
    else:
        if limit is not None and int(limit) < len(tasks):
            shares = split_shares(tasks)
            tasks = list(tasks)[: int(limit)]
    all_tasks = list(tasks)
    if shard is not None:
        k, n_sh = int(shard[0]), int(shard[1])
        if not (n_sh >= 1 and 0 <= k < n_sh):
            raise PlannerConfigError(f"--shard {k}/{n_sh}: need 0 <= K < N")
        tasks = [t for i, t in enumerate(all_tasks) if i % n_sh == k]
        out_dir = Path(out_dir) / f"shard{k}"
    t0 = time.monotonic()
    episodes = []
    if planner_name.startswith("robot_agent:"):
        workers = 1                     # robot_agent keeps module-level state
    if workers > 1 and llm is None and len(tasks) > 1:
        import concurrent.futures as cf
        import multiprocessing as mp
        n = min(workers, len(tasks))
        chunks = [list(range(i, len(tasks), n)) for i in range(n)]
        cache_dir = str(Path(out_dir) / "llm_cache") if llm_spec and llm_spec != "fake" else None
        jobs = [([tasks[i] for i in ch], ch, planner_name, profile, seeds, lang, llm_spec, model, budgets, cache_dir)
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
              "user_classifier": classifier_kind(llm_spec if llm is None else ("given" if not isinstance(
                  llm, FakeLLM) else "fake")),
              "planner_config": planner_run_config(planner_name),
              "profile_sha": prof.sha, "data_sha": data_sha(all_tasks), "n_tasks": len(all_tasks),
              "versions": _versions(planner_name), "model_digest": _digest(llm, llm_spec, model),
              "budgets": {"max_calls": budgets.max_calls, "max_sim_time_s": r6(budgets.max_sim_time_s),
                          "max_llm_calls": budgets.max_llm_calls}}
    if any("llm_calls_understand" in e for e in episodes) and isinstance(config["planner_config"], dict):
        # a variant with its own understand model: how many readings fell back to the planner (robot_agent's runaway guard)
        config["planner_config"] = {**config["planner_config"],
                                    "n_fallbacks": sum(len(e.get("understand_fallbacks") or []) for e in episodes)}
    if shard is not None:
        sh_info = {"k": k, "n": n_sh, "task_ids": [task_dict(t)["id"] for t in all_tasks], "seeds": int(seeds),
                   "config": config, "split_shares": shares}
        summary = summarize(episodes, {**config, "shard": {"k": k, "n": n_sh, "n_tasks": len(tasks)}},
                            split_shares=shares)
    else:
        summary = summarize(episodes, config, split_shares=shares)
    out = write_run(out_dir, episodes, summary)
    if shard is not None:
        (out / "shard.json").write_text(json.dumps(_round_tree(sh_info), sort_keys=True, ensure_ascii=False,
                                                   indent=1) + "\n", encoding="utf-8")
    print(f"[run] {planner_name} {len(episodes)} episodes in {time.monotonic() - t0:.1f}s wall -> {out}",
          file=sys.stderr)
    return summary


def write_run(out_dir, episodes: list, summary: dict) -> Path:
    """DIR/episodes.jsonl, DIR/summary.json and DIR/report.md of a run."""
    from . import report
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "episodes.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for e in episodes:
            f.write(dumps(e) + "\n")
    (out / "summary.json").write_text(json.dumps(_round_tree(summary), sort_keys=True, ensure_ascii=False, indent=1)
                                      + "\n", encoding="utf-8")
    (out / "report.md").write_text(report.render(summary, episodes), encoding="utf-8")
    return out


def _untouched(e: dict) -> bool:
    """Every LLM prompt of the episode was answered from a cache (or it used no cached LLM)."""
    return not (e.get("llm_cache") or {}).get("misses")


def aa_compare(eps_a: list, eps_b: list, strict: bool = False) -> dict:
    """A/A self-check of two runs of ONE configuration on a shared cache (common random numbers). Episodes are paired by
    (task_id, seed). A run-B episode is *untouched* when all its prompts hit a cache (``llm_cache.misses`` is 0, or
    the field is absent); an untouched episode must equal run A's, apart from the ``llm_cache`` field, because the
    code then saw the same answers. A touched one asked something new (a prompt that changed between the runs) and is
    only counted. ``ok``: no untouched episode differs and at least one was compared. ``strict`` (two passes run at the same
    time on a cold cache, lock mode): every episode counts as untouched, because both passes must have read the same first
    answer to every key, whoever asked the server."""
    key = lambda e: (e["task_id"], int(e["seed"]))                                   # noqa: E731
    a = {key(e): e for e in eps_a}
    strip = lambda e: json.dumps({k: v for k, v in e.items() if k != "llm_cache"}, sort_keys=True)   # noqa: E731
    differ, same, touched, missing = [], 0, [], []
    n_un = 0
    for e in eps_b:
        k = key(e)
        if k not in a:
            missing.append(f"{k[0]}#{k[1]}")
            continue
        if not strict and not _untouched(e):
            touched.append(f"{k[0]}#{k[1]}")
            continue
        n_un += 1
        if strip(e) == strip(a[k]):
            same += 1
        else:
            differ.append(f"{k[0]}#{k[1]}")
    return {"n_episodes": len(eps_b), "n_untouched": n_un, "n_touched": len(touched), "touched": touched,
            "n_identical_untouched": same, "n_differ_untouched": len(differ), "differ_untouched": differ,
            "unpaired": missing, "ok": not differ and not missing and n_un > 0}


class MergeError(RuntimeError):
    pass


def merge_shards(out_dir) -> dict:
    """Merge DIR/shard<k>/ (``run --shard k/N``) into DIR: the episodes in the unsharded run's order (task order of
    the run, then seed), the summary recomputed from them (``config`` as the unsharded run's, plus
    ``merged_shards``), report.md, and DIR/llm_cache/ = the shards' caches (one line per key, shard order).
    Every shard 0..N-1 must be complete and from the same run settings."""
    from .metrics import summarize
    out = Path(out_dir)
    infos = []
    for f in sorted(out.glob("shard*/shard.json")):
        infos.append((f.parent, json.loads(f.read_text(encoding="utf-8"))))
    if not infos:
        raise MergeError(f"no shard*/shard.json under {out}")
    n = infos[0][1]["n"]
    ks = sorted(i["k"] for _, i in infos)
    if ks != list(range(n)):
        raise MergeError(f"shards {ks} found, need 0..{n - 1}")
    ref = infos[0][1]

    def same(i) -> dict:
        return {k: v for k, v in i.items() if k != "k"}
    for d, i in infos:
        if i["n"] != n or i["task_ids"] != ref["task_ids"] or same(i)["config"] != ref["config"] \
                or i.get("split_shares") != ref.get("split_shares") or i["seeds"] != ref["seeds"]:
            raise MergeError(f"{d.name} was run with other settings than {infos[0][0].name}")
    order = {tid: j for j, tid in enumerate(ref["task_ids"])}
    episodes = []
    for d, i in infos:
        eps = read_episodes(d)
        want = [tid for j, tid in enumerate(ref["task_ids"]) if j % n == i["k"]]
        got = list(dict.fromkeys(e["task_id"] for e in eps))
        if got != want or len(eps) != len(want) * int(ref["seeds"]):
            raise MergeError(f"{d.name}: {len(eps)} episodes for {len(got)} of its {len(want)} tasks (incomplete)")
        episodes += eps
    episodes.sort(key=lambda e: (order[e["task_id"]], int(e["seed"])))
    summary = summarize(episodes, {**ref["config"], "merged_shards": n}, split_shares=ref.get("split_shares"))
    write_run(out, episodes, summary)
    _merge_caches([d for d, _ in infos], out / "llm_cache")
    return summary


def _merge_caches(shard_dirs: list, dest: Path) -> None:
    """Each cache file of the shards' llm_cache/ into ``dest``: lines in shard order, one per key (``sha``)."""
    names = sorted({f.name for d in shard_dirs for f in (d / "llm_cache").glob("*.jsonl")})
    for name in names:
        seen, lines = set(), []
        for src in [dest / name] + [d / "llm_cache" / name for d in shard_dirs]:
            if not src.is_file():
                continue
            for line in src.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    key = json.loads(line).get("sha") or line
                except ValueError:
                    key = line
                if key not in seen:
                    seen.add(key)
                    lines.append(line)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_text("".join(x + "\n" for x in lines), encoding="utf-8")


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
