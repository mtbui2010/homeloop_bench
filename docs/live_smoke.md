# Live smoke runs

The live smoke runs check that the real LLM planners work end to end on the benchmark. They are small:
100 dev tasks, profile `real`, one seed, English and Korean, two planners (`robot_agent:sage` and
`progprompt_like`) with `qwen3-vl:8b-instruct`.

## How to run

Any Ollama-compatible server works: pass its root URL with `--llm URL` and the model tag with `--model`, after
`ollama pull qwen3-vl:8b-instruct` on that server. `tools/llm_gpu0.sh` is an optional helper that starts one in a
container (image pinned by digest) on one GPU (`HOMELOOP_GPU`, default 0) at 127.0.0.1:11536. It mounts a model
store from `OLLAMA_MODELS_DIR` or `OLLAMA_VOLUME` (read-only), else the volume of an existing `ollama`
container (read-only), else its own volume `homeloop_ollama_models`, which `tools/llm_gpu0.sh pull MODEL` fills.
Start it, run, stop it:

```
bash tools/llm_gpu0.sh start
homeloop-bench live-smoke --llm http://127.0.0.1:11536 --model qwen3-vl:8b-instruct --limit 100
bash tools/llm_gpu0.sh stop
```

Each (planner, language) pair writes `results/live_smoke/<planner>__<model>__<lang>/` with
`summary.json`, `report.md`, `episodes.jsonl` and the LLM cache (`llm_cache/`), e.g.
`results/live_smoke/robot_agent:sage__qwen3-vl:8b-instruct__en/`. The directory names keep the planner
and model names as they are (colons included). These directories are tracked in git (`.gitignore` keeps
`results/live_smoke/`).

## Reading the numbers

A smoke run uses the first 100 dev tasks, so its `summary.json` has `"smoke": true` and
`success_reweighted` (success post-stratified to the full dev split's kind and subtask-count shares); the dev file
order is stratified, so the prefix is already close to the split's shares. A smoke run is 100 episodes: the Wilson interval of its success rate is about +/- 0.1 wide, so it shows
whether a planner works, not a ranking. Compare planners with paired runs on the same tasks and seeds
(`homeloop-bench compare`). The cache makes a rerun reproducible without the GPU.

## Failures of the infrastructure

If the LLM server cannot be reached (after 3 retries with backoff; `HOMELOOP_LLM_RETRIES`), or a planner's code
cannot be imported (e.g. robot_agent not on `PYTHONPATH`), the run stops with exit code 3 (2 for an unavailable
planner) and writes no `summary.json`, so an outage never looks like a 0 % score. Episodes in which the planner
itself crashed are `status: "error"` with `error` / `error_msg`; `summary.json` counts them (`n_error`,
`error_rate`, `errors_by_type`) and the command exits 4 when more than 5 % of the episodes crashed.

## Results (2026-11-02, qwen3-vl:8b-instruct, 100 dev tasks, profile real, seed 0)

Re-run after the harness / adapter / simulated-user fixes below (homeloop_bench 065057e, homeloop_robot
c6176b2, robot_agent 895561b, embodiplan a690642). The first run (ab4c262) is in the "before" columns. The
scripted baselines on the same 100 tasks and seed are given for reference (no LLM; `run --planner naive|oracle`).

| planner | lang | success [95 % CI] | false_success | help_rate | safety_violations | llm_calls_mean | before: success / false_success / help_rate |
|---|---|---|---|---|---|---|---|
| progprompt_like | en | 0.12 [0.07, 0.20] | 0.88 | 0.00 | 0 | 1.00 | 0.12 / 0.88 / 0.00 |
| progprompt_like | ko | 0.10 [0.06, 0.17] | 0.90 | 0.00 | 0 | 1.00 | 0.10 / 0.90 / 0.00 |
| robot_agent:sage | en | 0.12 [0.07, 0.20] | 0.08 | 0.72 | 1 | 11.64 | 0.07 / 0.02 / 0.76 |
| robot_agent:sage | ko | 0.06 [0.03, 0.12] | 0.05 | 0.75 | 1 | 12.31 | 0.05 / 0.03 / 0.80 |
| naive | en, ko | 0.51 [0.41, 0.61] | 0.01 | 0.00 | - | 0 | 0.51 / 0.01 / 0.00 |
| oracle | en, ko | 0.84 [0.76, 0.90] | 0.00 | 0.16 | - | 0 | 0.84 / 0.00 / 0.15 |

Read with the smoke-run caveats above. `progprompt_like` runs its program open-loop and always ends with
`finish("done")`, so every failed episode is a false success; most failures are `absent` (the program runs
`find` / `pick` at a place where the object is not). It never asks, so the fixes did not change it (its
episodes are identical).

### What was wrong in the first sage run, and what was fixed

The first run's sage episodes were replayed from the cache and read in full (prompts, replies, robot_agent
events, calls, the user's answers). Primary cause of each failed episode (EN: all 93 read by hand; KO: 95, by a
rule-based classifier checked by hand on 16):

| cause | EN | KO | fixed by |
|---|---|---|---|
| the question reached nobody: the user starts at their seat, the instruction was "heard" as if spoken next to the robot, the robot's ask went to its speaker (78 of 83 EN ask timeouts came before any motion) | 30 | 31 | homeloop_robot b40ff7c: `user.dialog_channel = app`, the channel of the deployed robot_agent dashboard |
| the simulated user could not answer questions about their own request (read-backs, "where should I put X?" read as "where is X?", choices) | 18 | 29 | homeloop_robot b90a858, d418f99, c6176b2; homeloop_bench c970d34 (`user.set_wants`) |
| "go back and charge" did not name the dock in the ENV, so robot_agent asked "Where should I put the ?" | 5 | 4 | homeloop_robot 4208f26 (dock aliases; moving to the charger docks) |
| sage's object memory was empty (every other planner observes the usual places) | 3 | 6 | homeloop_bench 917c8a0 (`seed_memory`) |
| skill results named world ids ("plate_1 not found"), the replanner then looked for "plate 1" | 3 | 2 | homeloop_robot 4208f26 |
| the instruction was not heard at all (empty task text) | 1 | 1 | not changed (see below) |
| injected robot failures not recovered (calibrated hw faults, drops, blocked doors) | 5 | 1 | not a bug |
| planner / LLM (wrong refusals, plans that fail robot_agent's gate, questions about filler words of the instruction or with an empty slot, the 8B model's Korean translations, a planner exception) | 28 | 20 | not changed (robot_agent / embodiplan are not edited) |

A try that declared WaitForUnload as its own skill (so robot_agent offers its `deliver` goal) was reverted
(homeloop_robot b6af562): deliver carries what the robot already holds, so sage handed over an empty gripper, and
the extra prompt lines made the 8B model refuse tasks it did before.

### Why sage stays below naive

- 43 of the 100 tasks (44 in KO) need a handover (`held_by`: "bring me X", "give X to Grandpa"). robot_agent has
  no fetch-and-hand-over goal for an arm robot: it asks "Where are you?" and puts X down at that place. sage
  reached 0 of these tasks in both runs; naive solves 19 of them (KO 20), oracle 35 (KO 36).
- On the other 57 tasks (56 in KO) sage succeeds on 12 (EN) and 6 (KO); naive on 32 (KO 31). The failed ones end in
  a third clarification round on questions the user cannot answer (EN 26, KO 49: questions about filler words
  of the heard instruction such as "What should I do with the neighbors?", empty-slot questions, open questions,
  the Korean "여기 있어요?" for "Where are you?"), plans that fail robot_agent's certified gate (EN 19, KO 14;
  7 EN / 11 KO of all episodes used the 30-call LLM budget, which counts each embodiplan call), wrong refusals
  (EN 9, KO 4) and searches that end without the object (EN 11, KO 12).
- false_success rose (EN 0.02 -> 0.08) because the user now answers read-backs: a read-back that puts X on the
  user's own seat ("I will put the mug on the sofa") is confirmed, and the put-down does not satisfy
  `held_by`.

Each directory's `llm_cache/` holds exactly the calls of its run (a rerun from it gives the same episodes without
the GPU).
