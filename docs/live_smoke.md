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

| planner | lang | success [95 % CI] | false_success | help_rate | safety_violations | llm_calls_mean | episodes |
|---|---|---|---|---|---|---|---|
| progprompt_like | en | 0.12 [0.07, 0.20] | 0.88 | 0.00 | 0 | 1.00 | 100 |
| progprompt_like | ko | 0.10 [0.06, 0.17] | 0.90 | 0.00 | 0 | 1.00 | 100 |
| robot_agent:sage | en | 0.07 [0.03, 0.14] | 0.02 | 0.76 | 0 | 6.33 | 100 |
| robot_agent:sage | ko | 0.05 [0.02, 0.11] | 0.03 | 0.80 | 1 | 9.39 | 100 |

Read with the smoke-run caveats above. `progprompt_like` runs its program open-loop and always ends with
`finish("done")`, so every failed episode is a false success; most failures are `absent` (the program runs
`find` / `pick` at a place where the object is not, e.g. the fridge it is about to put the object in).
`robot_agent:sage` rarely claims a success it did not reach, but asks on most tasks (14 % of these tasks are
clarify tasks) and gives up when the answer does not resolve its question; frequent questions were "Where are
you? Which place should I bring it to?", "Where should I put the ?" (an empty object slot) and place
disambiguations. Each directory's `llm_cache/` reproduces its run without the GPU.
