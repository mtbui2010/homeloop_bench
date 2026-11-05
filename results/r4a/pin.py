"""Behaviour pin for the household domain profile (R4a).

    pin.py before|after [--root DIR]   record the pin artifacts into pin_before/ or pin_after/
    pin.py compare                     compare the two, write pin.json (identical: true|false)

Artifacts of one mode, in <results>/r4a/pin_<mode>/:
  <planner>__<lang>.episodes.jsonl   `--llm fake` HomeLoop dev run: first 12 tasks, real profile, seed 0,
                                     planners robot_agent:sage, sage_ask, sage_norag, EN and KO
  replay.json                        the first 5 dev tasks of the milestone-10 round-7 sage EN and KO
                                     runs, replayed offline from a COPY of their llm_cache (dead LLM URL,
                                     0 retries, as the live_perf probe does): the outcome of each task

The robot_agent code under test is chosen by PYTHONPATH (set it to the domain-profile worktree).
Episodes are compared modulo wall time (keys that mention wall / elapsed / timestamp).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = Path("/home/trung/trung_workdir")
PY = os.path.expanduser("~/miniconda3/envs/vlaserve/bin/python")
M10 = W / "homeloop_bench/results/milestones_r3/m10/round7"
PLANNERS = ["robot_agent:sage", "robot_agent:sage_ask", "robot_agent:sage_norag"]
LANGS = ["en", "ko"]
MODEL = "qwen3-vl:8b-instruct"
FAKE_N, REPLAY_N = 12, 5
WALL_KEYS = ("wall", "elapsed", "timestamp", "wall_time")


def env():
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if "PYTHONPATH" not in e:
        e["PYTHONPATH"] = ":".join([str(W / "homeloop_bench"), str(W / "homeloop_robot"),
                                    str(W / "hl_wt/domain/robot_agent"), str(W / "hl_wt/sagev2/embodiplan"),
                                    str(W / "base_robot")])
    return e


def fname(planner, lang):
    return f"{planner.replace(':', '_')}__{lang}.episodes.jsonl"


def record_fake(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for p in PLANNERS:
        for lang in LANGS:
            tmp = tempfile.mkdtemp(prefix="pin_fake_")
            cmd = [PY, "-m", "homeloop_bench.cli", "run", "--planner", p, "--split", "dev", "--limit", str(FAKE_N),
                   "--profile", "real", "--seeds", "1", "--lang", lang, "--llm", "fake", "--out", tmp]
            r = subprocess.run(cmd, env=env(), cwd=W / "homeloop_bench", capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"fake run failed {p} {lang}: {r.stderr[-800:]}")
            shutil.copy(f"{tmp}/episodes.jsonl", out / fname(p, lang))
            shutil.rmtree(tmp, ignore_errors=True)
            n = sum(1 for _ in open(out / fname(p, lang)))
            print(f"fake {p} {lang}: {n} episodes")


REPLAY_CODE = r'''
import glob, json, os, shutil, sys, tempfile
os.environ["HOMELOOP_LLM_RETRIES"] = "0"
from homeloop_bench import runner
from homeloop_bench.llm import make_llm
src, planner, model, lang, n = sys.argv[1:6]
tmp = tempfile.mkdtemp(prefix="pin_replay_")
os.makedirs(tmp + "/llm_cache")
for c in glob.glob(src + "/llm_cache/*.jsonl"):
    shutil.copy(c, tmp + "/llm_cache/" + os.path.basename(c))
llm = make_llm("http://127.0.0.1:9", model, cache_dir=tmp + "/llm_cache")
out = []
for t in runner.load_tasks("dev", 300)[: int(n)]:
    try:
        e = runner.run_episode(t, planner, "real", 0, lang, None, model=model, llm=llm)
        out.append({"task_id": e.get("task_id"), "ok": True, "status": e.get("status"), "success": e.get("success"),
                    "false_success": e.get("false_success"), "gc": e.get("gc"), "asked": e.get("asked"),
                    "n_calls": e.get("n_calls"), "llm_calls": e.get("llm_calls"), "final_say": e.get("final_say"),
                    "refused": e.get("refused"), "failures": e.get("failures"), "sim_time_s": e.get("sim_time_s")})
    except Exception as ex:
        out.append({"task_id": t.get("id") if isinstance(t, dict) else str(getattr(t, "id", "?")), "ok": False,
                    "error": type(ex).__name__ + ": " + str(ex)[:160]})
shutil.rmtree(tmp, ignore_errors=True)
print("JSON" + json.dumps(out, ensure_ascii=False))
'''


def record_replay(out: Path):
    res = {}
    for lang in LANGS:
        src = M10 / f"robot_agent:sage__{MODEL}__{lang}"
        r = subprocess.run([PY, "-c", REPLAY_CODE, str(src), "robot_agent:sage", MODEL, lang, str(REPLAY_N)],
                           env=env(), cwd=W / "homeloop_bench", capture_output=True, text=True)
        line = [x for x in r.stdout.splitlines() if x.startswith("JSON")]
        if r.returncode != 0 or not line:
            sys.exit(f"replay failed {lang}: {r.stderr[-800:]}")
        res[lang] = json.loads(line[0][4:])
        print(f"replay {lang}: " + ", ".join(f"{x['task_id']}={'MISS' if not x['ok'] else x['success']}" for x in res[lang]))
    (out / "replay.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, sort_keys=True))


def norm(o):
    if isinstance(o, dict):
        return {k: norm(v) for k, v in o.items() if not any(w in k.lower() for w in WALL_KEYS)}
    if isinstance(o, list):
        return [norm(v) for v in o]
    return o


def load_eps(p):
    return [norm(json.loads(x)) for x in open(p) if x.strip()]


def compare():
    b, a = HERE / "pin_before", HERE / "pin_after"
    rep = {"base": "pin_before", "after": "pin_after", "fake": {}, "replay": {}}
    ok = True
    for p in PLANNERS:
        for lang in LANGS:
            f = fname(p, lang)
            if not (b / f).exists() or not (a / f).exists():
                rep["fake"][f] = {"identical": False, "why": "missing file"}
                ok = False
                continue
            eb, ea = load_eps(b / f), load_eps(a / f)
            diff = [i for i in range(max(len(eb), len(ea))) if i >= len(eb) or i >= len(ea) or eb[i] != ea[i]]
            same = not diff and len(eb) == len(ea)
            rep["fake"][f] = {"identical": same, "n_before": len(eb), "n_after": len(ea),
                              "bytes_equal": (b / f).read_bytes() == (a / f).read_bytes(),
                              "differing_index": diff[:5]}
            ok &= same
    if (b / "replay.json").exists() and (a / "replay.json").exists():
        rb, ra = json.loads((b / "replay.json").read_text()), json.loads((a / "replay.json").read_text())
        for lang in LANGS:
            same = rb.get(lang) == ra.get(lang)
            rep["replay"][lang] = {"identical": same, "outcomes": [(x["task_id"], x.get("success") if x["ok"] else "MISS")
                                                                   for x in rb.get(lang, [])]}
            ok &= same
    else:
        rep["replay"] = {"identical": False, "why": "missing replay.json"}
        ok = False
    rep["identical"] = bool(ok)
    (HERE / "pin.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print("identical:", ok)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["before", "after", "compare"])
    a = ap.parse_args()
    if a.mode == "compare":
        sys.exit(compare())
    out = HERE / f"pin_{a.mode}"
    record_fake(out)
    record_replay(out)


if __name__ == "__main__":
    main()
