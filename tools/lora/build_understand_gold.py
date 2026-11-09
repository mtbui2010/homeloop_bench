"""Build the LoRA training set for robot_agent's UNDERSTAND step from the TRAIN split's gold goals (P1 data builder).

Task-specific: every HomeLoop fact lives here and in ``understand_labels.py`` (labels) / ``text_noise.py`` (generic noise);
the trainer (the lora-finetune skill's train_lora.py) reads only ``{"messages": [...], "format": {...}}`` lines.

Steps (config: tools/lora/configs/p1_data.yaml)
  1. tasks of the TRAIN split only (every id must start with ``hl-train-``), minus the known benchmark defects
     (``defects_file``: EN/KO mismatches, extra commands, reason mismatches found by the audit rules on train).
  2. prompts: the exact understand prompt the deployed robot builds (planner ``robot_agent:sage_s8n``, first reading) for
     each task and language, captured by running the bench episode setup and robot_agent's AssistLoop up to its
     ``understand`` event with a RECORDING LLM (no model call; ``Recorder``). The format (JSON schema) is the one the
     robot sends.
  3. targets: ``understand_labels.target`` per policy variant (``variants``); the request must support the label
     (``understand_labels.support``) or the example is dropped and counted.
  4. noise: for ``noise.frac`` of the (task, language) pairs a twin with a generically corrupted request
     (``text_noise.noisy``; its prompt captured the same way), the clean one kept, the twin flagged ``noise: true``.
  5. filters: duplicate prompts, near-duplicates of DEV texts (character 3-gram Jaccard >= ``dev_near_dup``), examples
     over ``max_tokens`` (prompt + answer under the model's chat template), all counted.
  6. split by task id: ``val_frac`` held out (loss monitoring only); JSONL + datasheet (json and md) per variant.

Usage (CPU only, no LLM, no GPU; about 3 minutes with 16 workers)
  HOMELOOP_NAS=<NAS> PYTHONPATH=<bench>:<homeloop_robot>:<robot_agent>:<embodiplan> \
      python tools/lora/build_understand_gold.py --config tools/lora/configs/p1_data.yaml [--limit N] [--workers 16]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import understand_labels as UL  # noqa: E402
from text_noise import noisy  # noqa: E402


# ── prompt capture ───────────────────────────────────────────────────────────────────────────────────────────

class Recorder:
    """An LLM that records every call and answers a fixed empty reading (never a model call)."""
    model = "qwen3-vl:8b-instruct"           # the planner's model name (the robot builds the same prompt for any name)

    def __init__(self):
        self.calls, self.n_calls = [], 0

    def chat(self, prompt, format=None, temperature=0.0, seed=0, num_predict=None):
        self.calls.append({"prompt": prompt, "format": format, "temperature": temperature, "seed": seed})
        self.n_calls += 1
        return json.dumps({"status": "clear", "reason": "", "reason_type": "", "question": "", "goals": []})

    def chat_messages(self, messages, temperature=0.0, seed=0, format=None, prompt="", num_predict=None):
        self.calls.append({"messages": messages, "format": format})
        self.n_calls += 1
        return "{}"


def is_understand(call: dict) -> bool:
    props = ((call.get("format") or {}).get("properties") or {})
    return {"status", "goals", "question"} <= set(props)


def capture(td: dict, lang: str, text: str, cfg: dict) -> dict:
    """The first understand prompt + schema robot_agent builds for ``text`` in this task's episode, the ENV it lists and
    the start world (for the labels)."""
    import contextlib
    import io

    from homeloop_bench.env import EpisodeEnv
    from homeloop_bench.planners import make_planner, planner_class
    from homeloop_bench.understand_eval import STOP_EVENTS
    from homeloop_robot.configs.tasks import env_for
    rec = Recorder()
    env = EpisodeEnv(td, cfg["profile"], int(cfg["seed"]), lang, llm=rec, privileged=False, interrupt_via="inject")
    env.planner_name = cfg["planner"]
    env.task_text = text
    p = make_planner(cfg["planner"], llm=env.llm())
    p.until = STOP_EVENTS
    with contextlib.redirect_stdout(io.StringIO()):
        p.run(env)
    calls = [c for c in rec.calls if is_understand(c)]
    other = [c for c in rec.calls if not is_understand(c)]
    out = {"n_calls": len(rec.calls), "n_other_calls": len(other),
           "reached": (p.reached or {}).get("event") if isinstance(p.reached, dict) else None}
    if calls:
        out.update(prompt=calls[0]["prompt"], format=calls[0]["format"],
                   options={"temperature": calls[0]["temperature"], "seed": calls[0]["seed"]})
    out["world"] = env.world0
    out["env"] = env_for(env.world0, people_tracking=getattr(planner_class(cfg["planner"]), "people_tracking", False))
    return out


# ── workers ──────────────────────────────────────────────────────────────────────────────────────────────────

_G: dict = {}


def _init(cfg, tasks):
    _G["cfg"], _G["tasks"] = cfg, tasks


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def work(job):
    """One (task, language): the clean prompt, the labels of every variant, the support check, the noisy twin."""
    i, lang = job
    cfg, td = _G["cfg"], _G["tasks"][i]
    clean = (td.get("text") or {}).get(lang) or ""
    out = {"task_id": td["id"], "lang": lang, "clean_text": clean, "items": [], "drops": []}
    try:
        cap = capture(td, lang, clean, cfg)
    except Exception as e:                       # noqa: BLE001 - counted, never silent
        out["drops"].append(("capture_error", f"{type(e).__name__}: {e}"[:200]))
        return out
    if "prompt" not in cap:
        out["drops"].append(("no_understand_call", cap.get("reached")))
        return out
    w, env = cap["world"], cap["env"]
    targets, found_all = {}, []
    for vname, pol in cfg["variants"].items():
        ans, info = UL.target(td, w, env, lang, clean, pol)
        if ans is None:
            out["drops"].append((f"{vname}:label_{info['skipped']}", None))
            continue
        ok, missing, found = UL.support(ans, td, w, env, lang, clean)
        if not ok:
            out["drops"].append((f"{vname}:unsupported", "; ".join(missing)))
            continue
        found_all += found
        targets[vname] = (UL.serialise(ans, cap.get("format")), info)
    if not targets:
        return out
    texts = [(clean, False, [])]
    nz = cfg.get("noise") or {}
    if nz.get("frac", 0) > 0 and (_h(nz.get("seed", 0), td["id"], lang) % 10000) < nz["frac"] * 10000:
        rng = random.Random(_h("noise", nz.get("seed", 0), td["id"], lang))
        txt, edits = noisy(clean, lang, rng, protect=sorted(set(found_all), key=len, reverse=True),
                           max_edits=int(nz.get("max_edits", 2)))
        if edits and txt != clean:
            texts.append((txt, True, edits))
        else:
            out["drops"].append(("noise_no_edit", None))
    for txt, is_noisy, edits in texts:
        c = cap if not is_noisy else capture(td, lang, txt, cfg)
        if "prompt" not in c:
            out["drops"].append(("no_understand_call_noisy", None))
            continue
        out["items"].append({"heard_text": txt, "noise": is_noisy, "noise_edits": edits, "prompt": c["prompt"],
                             "format": c["format"], "options": c["options"], "n_other_calls": c["n_other_calls"],
                             "targets": {k: v[0] for k, v in targets.items()},
                             "info": {k: v[1] for k, v in targets.items()}})
    return out


# ── filters, split, files ────────────────────────────────────────────────────────────────────────────────────

def grams(s: str, n: int = 3) -> set:
    t = " ".join(str(s).lower().split())
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


def near_dup(train_texts: dict, dev_texts: dict) -> dict:
    """{(task_id, lang): (max Jaccard, dev id)} of every train text against every dev text of the same language."""
    out = {}
    for lang in ("en", "ko"):
        dev = [(i, grams(t)) for i, t in dev_texts.get(lang, [])]
        for key, t in train_texts.items():
            if key[1] != lang:
                continue
            g = grams(t)
            best, bid = 0.0, None
            for did, dg in dev:
                inter = len(g & dg)
                if not inter:
                    continue
                j = inter / len(g | dg)
                if j > best:
                    best, bid = j, did
            out[key] = (round(best, 4), bid)
    return out


def ntok(tok, msgs, gen: bool) -> int:
    """Tokens of ``msgs`` under the model's chat template (``gen``: with the assistant header, for the prompt part)."""
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=gen)
    return len(tok(text, add_special_tokens=False)["input_ids"])


def pct(xs, ps=(50, 90, 95, 99, 100)) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    return {f"p{p}": s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))] for p in ps} | {"mean": round(statistics.mean(s), 1)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--limit", type=int, default=0, help="first N train tasks only (a dry run)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=None, help="override out_dir")
    a = ap.parse_args(argv)
    import yaml
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    nas = os.environ.get("HOMELOOP_NAS", "")
    for k, v in list(cfg.items()):                    # "<NAS>/..." paths: the storage root from $HOMELOOP_NAS
        if isinstance(v, str) and "<NAS>" in v:
            if not nas:
                raise SystemExit(f"config {k} uses <NAS>: set HOMELOOP_NAS to the storage root")
            cfg[k] = v.replace("<NAS>", nas.rstrip("/"))
    out_dir = Path(a.out or cfg["out_dir"])
    t0 = time.time()

    from homeloop_bench.tasks import read_records
    if cfg.get("split", "train") != "train":
        raise SystemExit("refused: the training set is built from the train split only")
    tasks = read_records("train")
    bad = [t["id"] for t in tasks if not str(t["id"]).startswith("hl-train-") or t.get("split", "train") != "train"]
    assert not bad, f"non-train ids in the train split: {bad[:5]}"
    n_all = len(tasks)
    defects = json.loads(Path(cfg["defects_file"]).read_text(encoding="utf-8")) if cfg.get("defects_file") else {"drop": []}
    drop_ids = set(defects.get("drop") or [])
    assert all(i.startswith("hl-train-") for i in drop_ids)
    tasks = [t for t in tasks if t["id"] not in drop_ids]
    if a.limit:
        tasks = tasks[: a.limit]
    langs = list(cfg.get("langs") or ["en", "ko"])
    jobs = [(i, lg) for i in range(len(tasks)) for lg in langs]
    print(f"[p1] {len(tasks)} tasks x {len(langs)} languages, {a.workers} workers", file=sys.stderr)

    results = []
    if a.workers > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(a.workers, initializer=_init, initargs=(cfg, tasks)) as pool:
            for k, r in enumerate(pool.imap_unordered(work, jobs, chunksize=8)):
                results.append(r)
                if (k + 1) % 500 == 0:
                    print(f"[p1] {k + 1}/{len(jobs)} {time.time() - t0:.0f}s", file=sys.stderr)
    else:
        _init(cfg, tasks)
        results = [work(j) for j in jobs]
    results.sort(key=lambda r: (r["task_id"], r["lang"]))
    by_id = {t["id"]: t for t in tasks}

    # near-duplicates of dev texts (dev is read for this check only; test is never read)
    dev = read_records("dev")
    assert all(str(t["id"]).startswith("hl-dev-") for t in dev)
    dev_ids = {t["id"] for t in dev}
    dev_texts = {lg: [(t["id"], (t.get("text") or {}).get(lg) or "") for t in dev] for lg in langs}
    nd = near_dup({(r["task_id"], r["lang"]): r["clean_text"] for r in results}, dev_texts)
    thr = float(cfg.get("dev_near_dup", 0.9))
    exact_dev = {lg: {(t.get("text") or {}).get(lg) for t in dev} for lg in langs}

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(cfg["model_path"])
    max_tokens = int(cfg.get("max_tokens", 4096))

    rng = random.Random(int(cfg.get("split_seed", 0)))
    tids = sorted({r["task_id"] for r in results})
    rng.shuffle(tids)
    n_val = max(1, int(round(len(tids) * float(cfg.get("val_frac", 0.05)))))
    val_tasks = set(tids[:n_val])

    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for vname in cfg["variants"]:
        drop = Counter()
        drop_examples: dict = {}
        rows = {"train": [], "val": []}
        seen = set()
        for r in results:
            for why, detail in r["drops"]:
                if why.startswith(vname + ":") or ":" not in why:
                    k = why.split(":", 1)[-1]
                    drop[k] += 1
                    drop_examples.setdefault(k, []).append({"task_id": r["task_id"], "lang": r["lang"], "detail": detail})
            sim, did = nd.get((r["task_id"], r["lang"]), (0.0, None))
            for it in r["items"]:
                if vname not in it["targets"]:
                    continue
                if r["clean_text"] in exact_dev[r["lang"]]:
                    drop["dev_exact_text"] += 1
                    continue
                if sim >= thr:
                    drop["dev_near_duplicate"] += 1
                    drop_examples.setdefault("dev_near_duplicate", []).append(
                        {"task_id": r["task_id"], "lang": r["lang"], "detail": f"{sim} vs {did}"})
                    continue
                key = hashlib.sha256((it["prompt"] + "\0" + it["targets"][vname]).encode()).hexdigest()[:16]
                if key in seen:
                    drop["duplicate_prompt"] += 1
                    continue
                seen.add(key)
                msgs = [{"role": "user", "content": it["prompt"]}, {"role": "assistant", "content": it["targets"][vname]}]
                n_prompt, n_full = ntok(tok, msgs[:1], True), ntok(tok, msgs, False)
                if n_full > max_tokens:
                    drop["over_token_limit"] += 1
                    continue
                td = by_id[r["task_id"]]
                info = it["info"][vname]
                rows["val" if r["task_id"] in val_tasks else "train"].append({
                    "id": key, "task_ids": [r["task_id"]], "task_id": r["task_id"], "lang": r["lang"],
                    "kind": td.get("kind"), "expect": info["expect"], "clarify_kind": info.get("clarify_kind"),
                    "structure": td.get("structure") or "single", "family": (td.get("meta") or {}).get("family"),
                    "noise": it["noise"], "noise_edits": it["noise_edits"], "heard_text": it["heard_text"],
                    "clean_text": r["clean_text"], "n_tokens": n_full, "n_prompt_tokens": n_prompt,
                    "n_target_tokens": n_full - n_prompt, "messages": msgs, "format": it["format"],
                    "options": it["options"]})
        vdir = out_dir / vname
        vdir.mkdir(parents=True, exist_ok=True)
        for part, rs in rows.items():
            with (vdir / f"{part}.jsonl").open("w", encoding="utf-8") as f:
                for x in rs:
                    f.write(json.dumps(x, ensure_ascii=False) + "\n")
        (vdir / "dropped.json").write_text(json.dumps({k: v[:200] for k, v in drop_examples.items()}, ensure_ascii=False,
                                                      indent=1), encoding="utf-8")
        sheets[vname] = datasheet(vname, cfg, rows, drop, n_all, len(drop_ids), defects, nd, thr, dev_ids, results)
        (vdir / "datasheet.json").write_text(json.dumps(sheets[vname], ensure_ascii=False, indent=1), encoding="utf-8")
        (vdir / "datasheet.md").write_text(datasheet_md(sheets[vname]), encoding="utf-8")
    summary = {"out_dir": str(out_dir), "seconds": round(time.time() - t0, 1),
               "variants": {k: {"train": v["counts"]["train"], "val": v["counts"]["val"]} for k, v in sheets.items()}}
    (out_dir / "build_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def datasheet(vname, cfg, rows, drop, n_all, n_defect, defects, nd, thr, dev_ids, results) -> dict:
    allr = rows["train"] + rows["val"]
    cnt = lambda key, rs: dict(sorted(Counter(key(x) for x in rs).items()))     # noqa: E731
    tids = {p: sorted({x["task_id"] for x in rs}) for p, rs in rows.items()}
    assert not set(tids["train"]) & set(tids["val"]), "a task is on both sides of the split"
    leak_dev = sorted({t for x in allr for t in x["task_ids"]} & dev_ids)
    leak_test = sorted({t for x in allr for t in x["task_ids"] if not t.startswith("hl-train-")})
    sims = [v[0] for v in nd.values()]
    return {
        "variant": vname, "policy": {**UL.POLICY_DEFAULT, **cfg["variants"][vname]},
        "source": {"split": "train", "n_tasks_split": n_all, "planner_prompt": cfg["planner"], "profile": cfg["profile"],
                   "seed": cfg["seed"], "model_path": cfg["model_path"], "max_tokens": cfg.get("max_tokens", 4096)},
        "counts": {"train": len(rows["train"]), "val": len(rows["val"]), "train_tasks": len(tids["train"]),
                   "val_tasks": len(tids["val"])},
        "by_lang": {p: cnt(lambda x: x["lang"], rs) for p, rs in rows.items()},
        "by_kind": {p: cnt(lambda x: x["kind"], rs) for p, rs in rows.items()},
        "by_expect": {p: cnt(lambda x: x["expect"], rs) for p, rs in rows.items()},
        "by_status": {p: cnt(lambda x: json.loads(x["messages"][1]["content"])["status"], rs) for p, rs in rows.items()},
        "by_structure": {p: cnt(lambda x: x["structure"], rs) for p, rs in rows.items()},
        "by_noise": {p: cnt(lambda x: "noisy" if x["noise"] else "clean", rs) for p, rs in rows.items()},
        "by_lang_kind_train": cnt(lambda x: f"{x['lang']}/{x['kind']}", rows["train"]),
        "noise_edits": dict(Counter(e for x in allr for e in x["noise_edits"]).most_common()),
        "clarify_kind": cnt(lambda x: str(x["clarify_kind"]), allr),
        "n_goals": cnt(lambda x: len(json.loads(x["messages"][1]["content"])["goals"]), allr),
        "goal_types": dict(Counter(g["type"] for x in allr for g in json.loads(x["messages"][1]["content"])["goals"]).most_common()),
        "tokens": {"total": pct([x["n_tokens"] for x in allr]), "prompt": pct([x["n_prompt_tokens"] for x in allr]),
                   "target": pct([x["n_target_tokens"] for x in allr]),
                   "by_lang_total": {lg: pct([x["n_tokens"] for x in allr if x["lang"] == lg]) for lg in ("en", "ko")}},
        "filters": {"benchmark_defects_tasks": n_defect, "benchmark_defects_by_rule": defects.get("counts"),
                    **{k: v for k, v in sorted(drop.items())}},
        "leakage": {"train_ids_only": not leak_test, "dev_id_overlap": len(leak_dev), "non_train_ids": len(leak_test),
                    "test_split_read": False, "dev_near_dup_threshold": thr,
                    "train_dev_jaccard": pct(sims) if sims else {},
                    "train_texts_jaccard_ge": {str(t): sum(1 for s in sims if s >= t) for t in (0.6, 0.7, 0.8, 0.9, 1.0)}},
        "other_llm_calls_before_understand": sum(it["n_other_calls"] for r in results for it in r["items"]),
        "mapping": UL.MAPPING,
    }


def datasheet_md(s: dict) -> str:
    j = lambda x: json.dumps(x, ensure_ascii=False)        # noqa: E731
    lines = [f"# Understand LoRA data: variant `{s['variant']}`", "",
             f"Source: {j(s['source'])}", f"Policy: {j(s['policy'])}", "",
             f"Counts: {j(s['counts'])}", ""]
    for k in ("by_lang", "by_kind", "by_expect", "by_status", "by_structure", "by_noise"):
        lines.append(f"- {k}: {j(s[k])}")
    for k in ("by_lang_kind_train", "noise_edits", "clarify_kind", "n_goals", "goal_types"):
        lines.append(f"- {k}: {j(s[k])}")
    lines += ["", "## Tokens (Qwen3-VL chat template, prompt + answer)", "", f"{j(s['tokens'])}", "",
              "## Filters (examples removed, by cause; tasks for benchmark defects)", "", f"{j(s['filters'])}", "",
              "## Leakage", "", f"{j(s['leakage'])}", "", "## Mapping decisions", ""]
    lines += [f"{i + 1}. {m}" for i, m in enumerate(s["mapping"])]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
