# CLI

`homeloop-bench` (also `python -m homeloop_bench.cli`).

| command | what |
|---|---|
| `planners` | one line per planner: `name<TAB>description`, plus `<TAB>[unavailable: robot_agent not importable]` for robot_agent planners when robot_agent cannot be imported |
| `run --planner P --split S --limit N --profile R --seeds K --lang {en,ko} [--llm URL\|fake] [--model M] --out DIR [--workers W] [--tasks FILE]` | play tasks x seeds, write DIR/episodes.jsonl, DIR/summary.json, DIR/report.md |
| `run ... --shared-cache DIR` | a read-through, write-through prompt-sha response cache shared by paired runs (common random numbers; one `<model>.jsonl` per model, translator included): a prompt the baseline already answered gets the same answer in a variant; run the baseline first |
| `run ... --shard K/N --out DIR` | only the tasks at index `i % N == K` of the run's task list (same order, seeds, settings), written to DIR/shard<K>/ with its own llm_cache and a shard.json ([runner](runner.md#shards)) |
| `merge DIR` | merge DIR/shard0..N-1 into DIR: episodes in the unsharded order, a recomputed summary, report.md, the merged llm_cache |
| `prompt TASK_ID [--planner robot_agent:sage\|robot_agent:sage_norag] [--lang en\|ko] [--full] --llm fake` | the first prompt SAGE builds for the task, with what it retrieved from the seed pool ([robot_agent](robot_agent.md#seed-pool-sage-and-sage_norag)) |
| `understand-eval [--planner robot_agent:sage] [--split train\|dev \| --tasks FILE] [--limit N] [--offset K] [--lang en\|ko\|en,ko] [--text clean\|asr\|both] [--profile real] [--seed 0] --llm URL\|fake [--model M] --out DIR` | only robot_agent's understand step on the tasks, compared with the gold goals: DIR/records.jsonl (one record per task, language and text condition), DIR/summary.json, DIR/report.md, DIR/llm_cache. The test split is refused. Exit 4 when more than 5 % of the probes ended before the understand step ([understanding evaluation](understand_eval.md)) |
| `compare DIR_A DIR_B [--json]` | paired McNemar test on episodes with the same (task, seed) |
| `report DIR` | re-render DIR/report.md from the run's files |
| `run ... --shared-cache ROOT --replicate NAME` | the shared cache is ROOT/NAME: one per replicate, common to all configurations of it. Episodes carry `llm_cache` (`hits`, `shared`, `misses`, `touched`) |
| `aa-check` (the arguments of `run`) | A/A self-check: the same configuration twice on one shared cache; episodes whose prompts all hit must be identical (OUT/aa_check.json; exit 1 on a difference) |
| `tasks-file --split dev\|train [--ids 14,15] [--limit N] --out FILE` | write the current packaged records for `run --tasks` (the test split is refused) |
| `show TASK_ID [--tasks FILE]` | print one task record |
| `calibrate-knowno --split train --limit N --llm URL [--model M]` | conformal threshold for knowno_like -> planners/knowno_calib.json |
| `python -m homeloop_bench.data delivery` | round 2 delivery rewrite of the task files ([tasks](tasks.md#delivery)); writes data/quality/delivery_report.json |
| `python -m homeloop_bench.data datasheet` | rewrite docs/datasheet.md from the shipped quality reports (no LLM) |
| `live-smoke --llm URL --model M [--limit 100] [--planners robot_agent:sage,progprompt_like] [--langs en,ko]` | the live smoke runs -> results/live_smoke/<planner>__<model>__<lang>/ |

Defaults: `--split dev`, `--limit` all, `--seeds 1`, `--lang en`, `--profile real`, `--model
qwen3-vl:8b-instruct`. `--tasks FILE` reads tasks from a JSONL file instead of the packaged split; a file whose records differ from the packaged ones with the same id is refused unless `--allow-stale`.
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
