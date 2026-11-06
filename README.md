# HomeLoop-Bench

HomeLoop-Bench evaluates household robot task planners in a closed loop: plan, act, check the result,
recover or replan, ask the person when the request is unclear, refuse when it is unsafe, and keep a safe
distance from people. The robot is homeloop_robot, a stochastic mock robot whose
skills check the true symbolic world and fail at rates taken from published robot studies. The tasks are
household requests in English and Korean, many of them long instructions with two or three parts.

## Install

```
pip install --no-deps --no-build-isolation -e ../homeloop_robot -e .
```

Python 3.10+ and pyyaml. No GPU, ROS or network is needed except for live LLM runs. The robot_agent
planners need robot_agent and embodiplan on `PYTHONPATH`.

## Quickstart

```
homeloop-bench planners
homeloop-bench run --planner oracle --split dev --limit 300 --profile ideal --seeds 2 --out runs/oracle_ideal
homeloop-bench run --planner oracle --split dev --limit 300 --profile real --seeds 2 --out runs/oracle_real
homeloop-bench run --planner naive  --split dev --limit 300 --profile real --seeds 2 --out runs/naive_real
homeloop-bench compare runs/oracle_real runs/naive_real
```

Each run writes `episodes.jsonl`, `summary.json` and `report.md`. The same command gives identical files.

## What is measured

Success with a Wilson 95 % interval, goal-condition success, false success (the planner says done but the
goal does not hold), recovery rate per failure code, help rate and correct-help rate, rejection rate on
unsafe or impossible requests, separation violations and minimum robot-person distance, semantic hazards,
LLM calls and simulated time. Definitions: [metrics](docs/metrics.md).

## Planners

`oracle` (privileged reference), `naive` (its open-loop ablation), `saycan_like`, `inner_monologue_like`,
`progprompt_like`, `knowno_like`, and robot_agent's `sage`, `grace` and `llm_direct`. See
[planners](docs/planners.md) and [robot_agent planners](docs/robot_agent.md).

## Results

Live smoke runs (100 dev tasks, profile real, one seed, qwen3-vl:8b-instruct): filled in by the live
phase, see [live smoke](docs/live_smoke.md).

| planner | lang | success | 95 % CI | false success | episodes |
|---|---|---|---|---|---|
| robot_agent:sage | en | - | - | - | - |
| robot_agent:sage | ko | - | - | - | - |
| progprompt_like | en | - | - | - | - |
| progprompt_like | ko | - | - | - | - |

## Docs

- [Runner](docs/runner.md): episodes, environment, budgets, judge, files
- [Metrics](docs/metrics.md): every summary.json key, recovery, paired tests
- [Planners](docs/planners.md): baselines, prompts, KnowNo calibration, FakeLLM
- [robot_agent planners](docs/robot_agent.md): how robot_agent's loops run on the mock robot
- [CLI](docs/cli.md), [live smoke](docs/live_smoke.md), [testing](docs/testing.md)

### Data
- [Datasheet](docs/datasheet.md): the datasheet for the dataset (Gebru et al.), licences, versions
- [Tasks](docs/tasks.md): the task record schema, goals, labels
- [Generation](docs/generation.md): templates, compound tasks, paraphrases, the pipeline
- [Splits](docs/splits.md): train / dev / test, held-out houses, leakage checks
- [Realism](docs/realism.md): realism rules and their sources
- [Paraphrase quality](docs/paraphrase_quality.md): paraphrase and Korean back-translation reports

## License

- Code: Apache-2.0 ([LICENSE](LICENSE)).
- Data: the English texts, the templates in both languages, the goals and labels are Apache-2.0. The Korean
  paraphrases written by EXAONE 3.5 (`text.ko` and `meta.paraphrase.ko` of records with
  `paraphrase_model.ko = exaone3.5:latest`, 5,192 tasks) and the whole Korean LLM cache `paraphrase_ko.jsonl`
  are EXAONE model Output, owned by LG and redistributed under the EXAONE AI Model License 1.1 - NC: research
  use only, no commercial use, and **no use to train, fine-tune or otherwise develop or improve models**. CC BY-NC
  4.0 covers only the authors' own contribution to that part (selection, filtering, labels)
  ([LICENSE-DATA](LICENSE-DATA), [NOTICE](NOTICE), [datasheet](docs/datasheet.md#distribution)).
- Training warning: the train split holds 2,086 records with EXAONE-written Korean text. To train or fine-tune a
  model, replace their `text.ko` with `meta.template_text.ko` (the authors' Apache-2.0 template) or use English
  only. The same replacement gives a fully Apache-2.0 dataset for commercial use.

Cite with [CITATION.cff](CITATION.cff).
