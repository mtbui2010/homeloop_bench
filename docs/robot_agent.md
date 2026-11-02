# robot_agent planners

`planners/robot_agent_adapter.py` runs robot_agent's own loops on the homeloop mock robot, through the
robot package in `homeloop_robot/configs/` (manifest, adapter, skill functions; see homeloop_robot's
docs/robot_agent.md). robot_agent is imported inside functions only; `homeloop-bench planners` works
without it and marks these planners unavailable.

| planner | loop |
|---|---|
| `robot_agent:sage` | `AssistLoop(agent, generator="grace")`: understand, clarify, the certified gate, guard, recovery, replan |
| `robot_agent:grace` | `ClosedLoop(agent, planner="grace")` |
| `robot_agent:llm_direct` | `ClosedLoop(agent, planner="llm_direct")` |

## Per episode

1. `homeloop_robot.configs.backend.set_backend(RobotProxy(env))`. The proxy's `call` goes through
   `env.call`, so budgets, the call log and interruptions apply, and the robot package's skill functions
   (`configs/ra_skills.py`) are what robot_agent executes. The previous backend is restored afterwards.
2. The hooks robot_agent's own tests replace are set and restored after the episode:
   `robot_agent.state.current`, `assist_loop.current`, `loop.current` -> a FakeState
   (`robot_pkg="homeloop_robot"`, a temporary common dir); `host_id` -> "homeloop";
   `robot_agent.skill_configs.ENV` -> `homeloop_robot.configs.tasks.env_for(world)`;
   `robot_agent.connect.llm.init_llm_client` -> our client. A fresh run manager and run-control state.
3. The agent namespace: `skill_registry` calls the `ra_skills` function by name; `device_manager` has a
   fake node; `_llm_cfg = {"name": "llama", "url": URL, "model": M, "num_ctx": 8192}`.
4. `loop.run_blocking(instruction, lang)` is drained until the `done` event, the episode budget, or (after
   a stop event) the next motion call. Final status: success -> done, refused -> refuse, else give_up.

## LLM calls

Live runs: the loops' client is our `OllamaHTTP` (urllib) behind the episode's call counter and cache.
embodiplan (the grace / SAGE generator) talks to the server itself; its `LLMBackend.chat` is wrapped during
the episode so those calls are counted and budgeted too.

`--llm fake` (tests): `robot_agent_fake.FakeUnderstandLLM` answers the understand prompt with the task's
gold goals in robot_agent's understand JSON (clarify tasks: "ambiguous" + the gold question until the
dialogue has an answer; refuse tasks: "unsafe" / "infeasible") and writes the oracle's plan as a
`skill::input` program for llm_direct. The generator is the plug-in
`homeloop_bench.planners.robot_agent_fake:GoalPlanner`, loaded by name through robot_agent's planner
registry; it plans the gold goals with the oracle from the current true world. This exercises the real
loops, gate, guard, recovery, ask channel and robot package without an LLM; it is a test double and its
scores are not results.

## Known limitations (found with the fake runs)

- Interruptions reach robot_agent as `cancelled` skill results. A correction's new goal is not injected
  into the loop (robot_agent's run manager needs a live run thread for `inject`), so on correction tasks
  the robot_agent planners keep the old goal.
- robot_agent moves only to ENV places. The homeloop ENV (`env_for`) lists places, not people, so a goal
  that needs the robot next to a person (a message, a handover to someone other than the user) has to go
  through the person's usual place.
- Delivering to someone other than the user maps to robot_agent's `deliver` goal, which needs the
  `WaitForUnload` action; the homeloop manifest lists it only as an alias of Handover, and robot_agent's
  goal kinds check the plan actions without aliases, so such goals are refused.
- `say::text` programs of llm_direct carry no language; the robot package's `say` defaults to English, so a
  Korean sentence is logged as English and the `said_to` check (Korean keywords) fails.
- ClosedLoop (grace, llm_direct) has no understand step and cannot refuse.
