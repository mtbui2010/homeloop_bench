# CLI

`homeloop-bench` (also `python -m homeloop_bench.cli`).

| command | what |
|---|---|
| `planners` | one line per planner: `name<TAB>description`, plus `<TAB>[unavailable: robot_agent not importable]` for robot_agent planners when robot_agent cannot be imported |
| `run --planner P --split S --limit N --profile R --seeds K --lang {en,ko} [--llm URL\|fake] [--model M] --out DIR [--workers W] [--tasks FILE]` | play tasks x seeds, write DIR/episodes.jsonl, DIR/summary.json, DIR/report.md |
| `compare DIR_A DIR_B [--json]` | paired McNemar test on episodes with the same (task, seed) |
| `report DIR` | re-render DIR/report.md from the run's files |
| `show TASK_ID [--tasks FILE]` | print one task record |
| `calibrate-knowno --split train --limit N --llm URL [--model M]` | conformal threshold for knowno_like -> planners/knowno_calib.json |
| `python -m homeloop_bench.data delivery` | round 2 delivery rewrite of the task files ([tasks](tasks.md#delivery)); writes data/quality/delivery_report.json |
| `python -m homeloop_bench.data datasheet` | rewrite docs/datasheet.md from the shipped quality reports (no LLM) |
| `live-smoke --llm URL --model M [--limit 100] [--planners robot_agent:sage,progprompt_like] [--langs en,ko]` | the live smoke runs -> results/live_smoke/<planner>__<model>__<lang>/ |

Defaults: `--split dev`, `--limit` all, `--seeds 1`, `--lang en`, `--profile real`, `--model
qwen3-vl:8b-instruct`. `--tasks FILE` reads tasks from a JSONL file instead of the packaged split.
Budgets can be changed with `--max-calls`, `--max-sim-time-s`, `--max-llm-calls` (defaults in
[runner](runner.md#budgets)). `--set KEY=V[,KEY=V]` overrides scalar parameters of the profile for a sensitivity
run (e.g. `--set asr.ko.app_cer=0.02,asr.en.app_wer=0.02`); `config.profile` and `config.profile_sha` record it
(homeloop_robot docs/profiles.md).

An LLM planner without `--llm` is an error: `planner X needs --llm URL or --llm fake` (exit 2).
`--llm fake` is for tests only.

Examples:

```
homeloop-bench run --planner oracle --split dev --limit 300 --profile ideal --seeds 2 --lang en --out runs/oracle_ideal
homeloop-bench run --planner naive --split dev --limit 300 --profile real --seeds 2 --out runs/naive_real
homeloop-bench compare runs/oracle_real runs/naive_real
homeloop-bench run --planner progprompt_like --split dev --limit 100 --llm http://127.0.0.1:11536 --lang ko --out runs/pp_ko
```
