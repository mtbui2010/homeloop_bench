# homeloop_bench: rules for agents

HomeLoop-Bench: tasks, a seeded Monte Carlo runner, planners and metrics on the homeloop_robot mock robot.

## Rules
- Python: `~/miniconda3/envs/vlaserve/bin/python` (3.12); run with `PYTHONDONTWRITEBYTECODE=1`.
- Tests: `python -m pytest -q tests` with `PYTHONPATH=.:../homeloop_robot` (+ robot_agent, embodiplan for
  the adapter test); green, < 120 s, no network. Do not commit while tests fail.
- No private project / company names anywhere (.py .yaml .md .toml .json).
- Determinism: randomness only through `homeloop_robot.rng`; no wall clock, `hash()` or set order in any
  output; JSON with sorted keys and floats rounded by `r6`. Same args -> identical summary.json.
- Never fabricate numbers or sources; a design choice is labelled as one.
- robot_agent is imported only inside functions of `planners/robot_agent_adapter.py` / `robot_agent_fake.py`;
  `homeloop-bench planners` must work without it.
- LLM planners are tested with `--llm fake` only; FakeLLM numbers are never reported.
- GPU 0 only, through `tools/llm_gpu0.sh start|stop`; stop the container when done.
- Commits: explicit `git add <paths>`; message ends with the attribution lines; no push.

## Docs
- [Runner](docs/runner.md): episodes, observation, budgets, judge, output files
- [Metrics](docs/metrics.md): summary.json keys, recovery, McNemar, Wilson
- [Planners](docs/planners.md): baselines, prompts, KnowNo calibration, FakeLLM
- [robot_agent planners](docs/robot_agent.md): adapter, hooks, fake mode, limitations
- [CLI](docs/cli.md): every command
- [Live smoke](docs/live_smoke.md): live LLM runs and their result folders
- [Testing](docs/testing.md): test map and long checks
- Data: [datasheet](docs/datasheet.md), [tasks](docs/tasks.md), [generation](docs/generation.md),
  [splits](docs/splits.md), [realism](docs/realism.md), [paraphrase quality](docs/paraphrase_quality.md)
