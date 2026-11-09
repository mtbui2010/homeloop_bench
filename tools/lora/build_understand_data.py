"""Build chat-format LoRA data for robot_agent's UNDERSTAND step from understand-eval runs (task-specific data builder).

The generic trainer (the lora-finetune skill's train_lora.py) knows nothing about HomeLoop. Every task fact lives here: where
the prompts come from (the llm_cache of an `homeloop-bench understand-eval` run, i.e. the exact prompt and JSON schema the
deployed robot sends), which split they belong to, and what the assistant target is.

Modes
  smoke   target = the cached model answer itself, re-serialised (a plumbing test: valid JSON of the served schema; no quality).
  gold    (P1, not used yet) target = the train split's gold goals in the understand schema.

Leakage: the source run must be a TRAIN-split run (its summary.json config.split); any other split is refused. Each example
is tied to its task id through records.jsonl (the prompt ends with "Task: <heard text>"); examples whose heard text maps to
no train task are dropped and counted. The validation hold-out is by task id.

Usage
  python tools/lora/build_understand_data.py --run results/perf1/understand/train --mode smoke --n 200 --val 20 \
      --out <NAS>/homeloop_lora/data/smoke_p0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

TASK_MARK = "\nTask: "
# robot_agent's UNDERSTAND_SCHEMA property order (core/planning/assist_loop.py). Ollama's JSON-schema decoding follows the
# ORDER of `properties` (required keys first, then optional ones), and the bench cache stores `format` with sorted keys, so
# the order is restored here: the served request, the training target and the grammar must agree.
KEY_ORDER = ("status", "reason", "reason_type", "question", "goals")
GOAL_KEY_ORDER = ("type", "object", "said", "content", "from", "to")


def ordered(d: dict, order) -> dict:
    out = {k: d[k] for k in order if k in d}
    out.update({k: v for k, v in d.items() if k not in out})
    return out


def robot_order_schema(fmt: dict) -> dict:
    """The cached (sorted) schema with robot_agent's property order (top level and goal items)."""
    fmt = json.loads(json.dumps(fmt))
    fmt["properties"] = ordered(fmt["properties"], KEY_ORDER)
    items = fmt["properties"].get("goals", {}).get("items")
    if isinstance(items, dict) and "properties" in items:
        items["properties"] = ordered(items["properties"], GOAL_KEY_ORDER)
    return ordered(fmt, ("type", "properties", "required"))


def grammar_order(obj, schema):
    """``obj`` with its keys in the order the JSON-schema grammar emits them: the REQUIRED properties first, in the order of
    ``properties``, then the optional ones (seen in the stock model's served answers: goal items ``type, object, from, to,
    content``). Same rule as the lora-finetune skill's ``schema_order.order_like_grammar``."""
    if isinstance(obj, dict) and isinstance(schema, dict):
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        order = [k for k in props if k in req] + [k for k in props if k not in req]
        out = {k: grammar_order(obj[k], props.get(k)) for k in order if k in obj}
        out.update({k: v for k, v in obj.items() if k not in out})
        return out
    if isinstance(obj, list) and isinstance(schema, dict) and isinstance(schema.get("items"), dict):
        return [grammar_order(x, schema["items"]) for x in obj]
    return obj


def canonical(obj: dict, schema: dict) -> str:
    """The target text: keys in the served grammar's order for ``schema`` (robot order), two-space indent (the style the
    served model writes)."""
    return json.dumps(grammar_order(obj, schema), ensure_ascii=False, indent=2)


def is_understand_row(row: dict) -> bool:
    props = ((row.get("format") or {}).get("properties") or {})
    return {"status", "goals"} <= set(props)


def load_run(run: Path):
    cfg = json.loads((run / "summary.json").read_text(encoding="utf-8")).get("config", {})
    if cfg.get("split") != "train" or cfg.get("tasks_file"):
        raise SystemExit(f"refused: {run} is not a train-split run (config.split={cfg.get('split')!r}, "
                         f"tasks_file={cfg.get('tasks_file')!r})")
    by_text: dict = {}
    for line in (run / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            by_text.setdefault(r["heard_text"], set()).add((r["task_id"], r["lang"], r.get("text")))
    rows = []
    for f in sorted((run / "llm_cache").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return cfg, by_text, rows


def build(args) -> dict:
    run = Path(args.run)
    cfg, by_text, rows = load_run(run)
    drop = Counter()
    examples = []
    for row in rows:
        if not is_understand_row(row):
            drop["not_understand_prompt"] += 1
            continue
        prompt = row["prompt"]
        heard = prompt.rsplit(TASK_MARK, 1)[-1].strip() if TASK_MARK in prompt else None
        ids = by_text.get(heard) if heard is not None else None
        if not ids:
            drop["no_train_task"] += 1
            continue
        task_ids = sorted({t for t, _, _ in ids})
        if any("-test-" in t for t in task_ids) or any("-dev-" in t for t in task_ids):
            drop["non_train_id"] += 1
            continue
        if args.mode == "smoke":
            try:
                target = canonical(json.loads(row["response"]), robot_order_schema(row["format"]))
            except ValueError:
                drop["response_not_json"] += 1
                continue
        else:
            raise SystemExit(f"mode {args.mode!r} is not implemented yet (P1)")
        langs = sorted({lang for _, lang, _ in ids})
        examples.append({"id": hashlib.sha256(prompt.encode()).hexdigest()[:16], "task_ids": task_ids, "lang": langs,
                         "messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": target}],
                         "format": robot_order_schema(row["format"])})
    seen, uniq = set(), []
    for e in examples:
        if e["id"] in seen:
            drop["duplicate_prompt"] += 1
            continue
        seen.add(e["id"])
        uniq.append(e)
    rng = random.Random(args.seed)
    rng.shuffle(uniq)
    uniq = uniq[: args.n]
    tasks = sorted({t for e in uniq for t in e["task_ids"]})
    rng.shuffle(tasks)
    val_tasks, n_val = set(), 0
    for t in tasks:                       # hold out whole tasks until about args.val examples are held out
        if n_val >= args.val:
            break
        val_tasks.add(t)
        n_val = sum(1 for e in uniq if set(e["task_ids"]) & val_tasks)
    train = [e for e in uniq if not set(e["task_ids"]) & val_tasks]
    val = [e for e in uniq if set(e["task_ids"]) & val_tasks]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("val", val)):
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for e in part:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    stats = {"source_run": str(run), "source_config": cfg, "mode": args.mode, "seed": args.seed,
             "n_rows": len(rows), "dropped": dict(drop), "n_train": len(train), "n_val": len(val),
             "train_tasks": len({t for e in train for t in e["task_ids"]}),
             "val_tasks": len({t for e in val for t in e["task_ids"]}),
             "by_lang_train": dict(Counter(",".join(e["lang"]) for e in train)),
             "by_status_train": dict(Counter(json.loads(e["messages"][1]["content"])["status"] for e in train))}
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="an understand-eval output dir of the TRAIN split")
    ap.add_argument("--mode", default="smoke", choices=["smoke", "gold"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--val", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    print(json.dumps(build(ap.parse_args(argv)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
