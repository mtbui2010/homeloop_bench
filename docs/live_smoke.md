# Live smoke runs

The live smoke runs check that the real LLM planners work end to end on the benchmark. They are small:
100 dev tasks, profile `real`, one seed, English and Korean, two planners (`robot_agent:sage` and
`progprompt_like`) with `qwen3-vl:8b-instruct`.

## How to run

The LLM runs on GPU 0 only, in its own container (`tools/llm_gpu0.sh`, port 127.0.0.1:11536, the model
volume of the shared server mounted read-only). Start it, run, stop it:

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

A smoke run is 100 episodes: the Wilson interval of its success rate is about +/- 0.1 wide, so it shows
whether a planner works, not a ranking. Compare planners with paired runs on the same tasks and seeds
(`homeloop-bench compare`). The cache makes a rerun reproducible without the GPU.
