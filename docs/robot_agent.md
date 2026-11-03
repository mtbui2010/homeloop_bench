# robot_agent planners

`planners/robot_agent_adapter.py` runs robot_agent's own loops on the homeloop mock robot, through the
robot package in `homeloop_robot/configs/` (manifest, adapter, skill functions; see homeloop_robot's
docs/robot_agent.md). robot_agent is imported inside functions only; `homeloop-bench planners` works
without it and marks these planners unavailable.

| planner | loop |
|---|---|
| `robot_agent:sage` | `AssistLoop(agent, generator="grace")`: understand, clarify, the certified gate, guard, recovery, replan; SAGE retrieves from the robot's seed pool |
| `robot_agent:sage_norag` | the same loop with an empty seed pool (zero-shot SAGE) |
| `robot_agent:grace` | `ClosedLoop(agent, planner="grace")` |
| `robot_agent:llm_direct` | `ClosedLoop(agent, planner="llm_direct")` |

## Versions

| repository | URL | tested commit |
|---|---|---|
| robot_agent | https://github.com/mtbui2010/robot_agent | `895561b88987457b80cf35d9d733b29676a3f82d` (2026-11-02) |
| embodiplan | https://github.com/mtbui2010/pyplanner | `a69064255c697ea27c596425ed0efebb6af3c4ba` (2026-11-02) |

The repositories may not be public yet; access is needed to run these planners. The adapter patches robot_agent
internals (`state.current`, `assist_loop.current`, `skill_configs.ENV`, `connect.llm.init_llm_client`), so a change
upstream can change results: every run records the git commits of robot_agent and embodiplan in `summary.json`
(`config.versions.robot_agent_git`, `embodiplan_git`), next to homeloop_bench / homeloop_robot and, for a URL run,
the Ollama model digest (`config.model_digest`). Each episode's robot_agent logs go to a temporary directory that is
removed after the episode (`HOMELOOP_KEEP_RA_LOGS=1` keeps them).

## Per episode

1. `homeloop_robot.configs.backend.set_backend(RobotProxy(env))`. The proxy's `call` goes through
   `env.call`, so budgets, the call log and interruptions apply, and the robot package's skill functions
   (`configs/ra_skills.py`) are what robot_agent executes. The previous backend is restored afterwards.
2. The hooks robot_agent's own tests replace are set and restored after the episode:
   `robot_agent.state.current`, `assist_loop.current`, `loop.current` -> a FakeState
   (`robot_pkg="homeloop_robot"`, a temporary common dir); `host_id` -> "homeloop";
   `robot_agent.skill_configs.ENV` -> `homeloop_robot.configs.tasks.env_for(world)`;
   `robot_agent.connect.llm.init_llm_client` -> our client. A fresh run manager and run-control state.
3. robot_agent's object memory (`mem.json`, which a deployed robot_agent keeps across runs) is seeded with the
   object memory every planner observes (`EpisodeEnv.object_memory`: each object's usual place, the house
   default), by class name and colour + class name in English and Korean; a name shared by objects with different
   usual places is left out (`seed_memory`). Without it sage searched blind (sage EN 012, 049, 097).
4. The agent namespace: `skill_registry` calls the `ra_skills` function by name; `device_manager` has a
   fake node; `_llm_cfg = {"name": "llama", "url": URL, "model": M, "num_ctx": 8192}`.
5. A run is started on robot_agent's run manager and bound to the thread (`begin_run`), as the API does.
6. `loop.run_blocking(instruction, lang)` is drained until the `done` event, the episode budget, or (after
   a stop event) the next motion call. Final status: success -> done, refused -> refuse, else give_up.

## Seed pool (sage and sage_norag)

SAGE-v2 is designed with a seed memory: robot_agent passes the robot manifest's `planner.seed_memory`
(`RobotView.seed_memory()`) to the SAGE planner it builds, and SAGE puts the 3 most similar solved plans of that pool
(embodiplan `MemoryRetriever`, Jaccard over word tokens when Chroma is not installed, as here) into its decompose
and expand prompts. homeloop_robot ships such a pool: `homeloop_robot/planner/seed_memory.jsonl`, 12 examples in
robot_agent's memory format (`task`, `reasoning`, `plan_text`, `verified`, `source: seed`), 7 EN and 5 KO
instructions, written for `example_flat`, the house of progprompt_like's example programs, which no split uses
(its bedroom, side table, son, fork and cooking oil were added for the pool). They cover delivery to a surface
beside the person (`Place` on the person) and by handover, open before pick, putting into a closed container,
messages, refusals and a two-object task.

* `robot_agent:sage` runs SAGE as designed, with this pool. `robot_agent:sage_norag` differs only in the pool:
  `no_seed_pool(loop)` makes that loop's `RobotView.seed_memory()` return None, so SAGE retrieves nothing.
* Cross-episode memory stays off: each episode's live memory (`live.jsonl`) and object memory are in a temporary
  directory removed after it, so no episode learns from another.
* summary.json `config.planner_config` records `variant` (rag / norag), `seed_pool` (path), `seed_pool_sha`
  (sha256 of the file) and `seed_pool_n`.
* No leak: tests/test_seed_pool_leak.py checks that no example shares a family, gen_id or template id with a dev
  / test task, that none names a dev / test id or an evaluated house, that no EN / KO example text is within
  Jaccard 0.5 of a dev / test text or template text (near duplicate: 0.90), and that each example's plan, run on
  the mock robot in example_flat, reaches its goal. It also compares goals: no example's goal, normalised (object
  -> catalog class, place -> receptacle name, person -> speaker / other, delivery mode), is the goal of a dev /
  test task, no message atom is one, and no Say text would count as a dev / test message (`message_matches`) or is
  near its canonical text; `origin` must be filled ("hand-written for example_flat"). homeloop_robot tests/test_seed_pool.py checks the format and
  that every plan passes embodiplan's action model with this robot's plan actions.
* Retrieval is live for sage and absent for sage_norag: `homeloop-bench prompt TASK_ID --planner P --llm fake`
  sets the episode up as a run does, builds the loop's own SAGE planner and captures its first LLM call
  (tests/test_seed_pool_retrieval.py: 3 `RETRIEVED EXAMPLE` blocks for sage, none for sage_norag, the prompts
  otherwise identical). With `--llm fake` a run itself plans with the fake GoalPlanner, so fake runs of the two
  variants are the same.
* Two limits of SAGE's retrieval, measured with `prompt` (robot_agent / embodiplan not changed): its Jaccard
  tokenizer keeps only `[a-z0-9]` tokens, so a Korean instruction scores 0 against every example and always gets
  the first 3 examples of the pool (two English, one Korean delivery example); and the examples' plans are shown as
  ASCII-escaped JSON, so a Korean `Say` text reaches the prompt as `\uXXXX` escapes. The query is the heard
  instruction (after ASR), as a deployed robot would use it.

The R2-5 / R2-6 sage runs before this pool were zero-shot; they are reported as the RAG ablation's earlier
partial runs, and the live_smoke sage numbers before round 2.7 predate the pool.

## Interruptions

robot_agent ends a run when a step is `cancelled` (its recovery policy treats it as the person's stop), and
takes changes of mind through its live dialog channel. So for these planners a scripted correction is not a
cancelled skill call: when motion call `after_calls + 1` starts, the correction event is recorded (the goal
changes to its `new_goal`) and the call runs; the adapter then says the correction text into the run with
`run_manager.inject` (the router classifies it; AssistLoop applies pending changes at the next step
boundary). A stop still cancels the motion call, as for every planner. ClosedLoop (grace, llm_direct) does
not read pending changes, so it keeps the old goal.

## LLM calls

Live runs: the loops' client is our `OllamaHTTP` (urllib) behind the episode's call counter and cache.
embodiplan (the grace / SAGE generator) would talk to the server itself; its `LLMBackend.chat` is replaced during
the episode so those calls go through the same chain (`chat_messages`, the full message list kept): they are
counted, budgeted and cached in the run's `llm_cache/` (a rerun is served without the GPU), and they use the
bench client's options. One `num_ctx` (8192) for every request matters: a request with another context size
makes Ollama reload the model (in a first live run, sage's direct embodiplan calls used the server default and
the model was reloaded ~160 times in 40 min). embodiplan's temperature (0.2 by default) is kept; its seed is 0
when it sets none, so the sampled calls repeat.

`--llm fake` (tests): `robot_agent_fake.FakeUnderstandLLM` answers the understand prompt with the task's
gold goals in robot_agent's understand JSON (clarify tasks: "ambiguous" + the gold question until the
dialogue has an answer; refuse tasks: "unsafe" / "infeasible") and writes the oracle's plan as a
`skill::input` program for llm_direct. The generator is the plug-in
`homeloop_bench.planners.robot_agent_fake:GoalPlanner`, loaded by name through robot_agent's planner
registry; it plans the gold goals with the oracle from the current true world. This exercises the real
loops, gate, guard, recovery, ask channel and robot package without an LLM; it is a test double and its
scores are not results.

## Known limitations (found with the fake runs)

- ClosedLoop (grace, llm_direct) ignores injected corrections (only AssistLoop reads pending changes).
- robot_agent moves only to ENV places. The homeloop ENV (`env_for`, homeloop_robot) lists places and, since round
  2, one entry per person. The robot package binds `MoveTo` / `Place` of a person to `person_spot`: the nearest
  support surface with a free slot within 1.2 m of the person (Hall's personal zone; geometry only, not the
  judge's reach test). With none, `MoveTo` goes to the person and `Place` fails; the adapter never substitutes a
  handover (homeloop_robot docs/robot_agent.md). The bench passes `env_for` of the start world; it only
  translates names and positions, robot_agent is not changed. Since R2-5 (B1) the spot is applied in the robot
  package's skill functions, because AssistLoop passes the raw ENV key to them; a person's ENV loc is the spot or
  the robot's stop point beside the person. A person's ENV key is what sage reads back to the user, so it is a
  name, never a raw id: the speaker's entry is `spot near you`, anyone else's is their name (`husband`, `grandpa`);
  no key is a robot_agent user word (B2, pilot round 1; homeloop_robot `tasks.person_keys`). Tests:
  `tests/test_reach_ra_bind.py`, `tests/test_pilot_r1.py`.
- robot_agent has no fetch-and-hand-over goal for an arm robot. Its `deliver` goal (MoveTo + WaitForUnload)
  carries what is already loaded (a tray robot); the homeloop manifest keeps WaitForUnload as an alias of
  Handover, so deliver is not offered (declaring it made sage hand over an empty gripper, homeloop_robot
  b6af562). "Bring me X" is an `on` goal to the speaker. Measured behaviour: 3,269 of the 3,273 `reach`
  delivery atoms go to the speaker, and for the speaker sage does not use the person mapping. It asks "Where are
  you?", the simulated user names their seat, and sage plans `on(X -> seat)` (a seat fails a `reach` delivery)
  or stops at its confirmation question after "the me you mentioned is not in my plan". With `--llm fake` on
  the first 150 dev tasks (ideal, EN): `reach` 0 / 44, `hand` 0 / 18. The person mapping covers only
  deliveries to third parties (4 reach atoms, about 0.1 %). A `delivered[hand]` goal needs a handover, which
  sage plans only if its own goals ask for one. A message (`said_to`) reaches its person only when sage says
  it at the place where they are. Test: `tests/test_robot_agent_adapter.py`
  (`test_sage_delivery_to_the_speaker_end_to_end`).
- Planner information is not identical: since review round 1 the adapter's person spot uses only observed
  geometry (the same `people_now` positions and nearby furniture every planner gets), with no reach verdict and
  no automatic handover. The LLM baselines (progprompt_like, ...) get `people_now` and the delivery note and
  choose the surface themselves; sage gets the 1.2 m nearest-free-surface rule as a name translation. Report
  sage beside the baselines with this difference stated (docs/experiments.md).
- `--llm fake`: `robot_agent_fake.understand_goals` turns a delivery into `on(X -> person)` when the mode a robot
  would infer (the oracle's `observed_modes`, never the label) is reach, else the old mapping.
- `say::text` programs of llm_direct carry no language; the robot package's `say` defaults to English, so a
  Korean sentence is logged as English and the `said_to` check (Korean keywords) fails.
- ClosedLoop (grace, llm_direct) has no understand step and cannot refuse.
