# Testing

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:../homeloop_robot:/path/to/robot_agent:/path/to/embodiplan python -m pytest -q tests
```

The suite runs in well under 120 s with no network and no GPU. LLM planners are tested with the FakeLLM
only. Until the full task data is installed, the tests use a small generated fixture set
(`tests/fixtures.py`): feasible tasks from random reachable goals on every house, a clarify task with two
candidates, unsafe and infeasible refuse tasks, an ordered 3-subtask compound, a mixed feasible + refuse
compound, a conditional and a scripted correction.

| test file | covers |
|---|---|
| `test_env.py` | observation, privileged access, budgets, finish statuses, the per-subtask judge (order, mixed refusal, conditional, correction, semantic hazards), record schema |
| `test_metrics.py` | Wilson interval, McNemar (exact and chi-square), recovery accounting, help correctness, summary keys |
| `test_planners_oracle_naive.py` | oracle ideal = 1.0 with no false success; real: naive < oracle < 1.0; oracle asks / refuses / follows corrections |
| `test_planners_llm_fake.py` | every LLM baseline on the FakeLLM in EN and KO, determinism, repairs and give-up, LLM budget, parsers, SayCan options, KnowNo sets |
| `test_runner_determinism.py` | same args -> identical files; workers; no wall clock |
| `test_llm.py` | Ollama request body, cache, counting budget (no network) |
| `test_cli.py` | listing (without importing robot_agent), run / compare / report / show, `--llm` check, live-smoke directory names |
| `test_robot_agent_adapter.py` | robot_agent sage / grace / llm_direct with `--llm fake` (skipped without robot_agent): complete records, sage solves the feasible task and refuses the unsafe one, deterministic summary, backend restored |

Long checks are CLI commands, not tests (they need the full data): the oracle on 300 dev tasks x 2 seeds
in `ideal` (success 1.0, false success 0, identical summary twice) and in `real` (naive < oracle < 1.0).
