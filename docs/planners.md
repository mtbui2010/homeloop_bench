# Planners

`homeloop-bench planners` lists them. Every planner implements `run(env)` (`planners/base.py`) and ends
with `env.finish("done" | "refuse" | "give_up")`. Only `oracle` and `naive` are privileged (they read the
true world and the hidden goal); every other planner sees only the [observation](runner.md#the-episode-environment-envpy).

| name | loop | asks | recovery | notes |
|---|---|---|---|---|
| `oracle` | re-solves with `homeloop_robot.oracle.solve` from the true world after every call | clarify tasks: the gold question once, then acts on the true intent | full re-solve; at most 3 consecutive attempts of a call; `wait(5)` before retrying perception_unavailable / blocked; an `ask` for help when a move is blocked, and before the last attempt of a still-blocked move it backs off to the room's floor spot and comes another way (a person in bed next to the target cannot clear the way); gives up on a persistent hardware fault or e-stop | refuses refuse tasks; declines the refuse part of a mixed task; finishes `done` only when the judge would score success, so its false success is 0 |
| `naive` | the oracle's plan from the start state, open loop | never | none: the first failed call ends the episode (`give_up`); all calls ok -> `done`, so silent failures become false successes | the ablation that shows what closed-loop recovery buys |
| `saycan_like` | each step: the calls whose preconditions hold in the planner's own belief (where it is, what it holds, what it found here, what it opened), the LLM picks one by index | no | none beyond the step choice; the prompt has the state only, no failure text | after SayCan (Ahn et al. 2022, https://arxiv.org/abs/2204.01691). SayCan multiplies LLM likelihoods by learned affordance values; a chat API gives no likelihoods, so here the LLM chooses by index among the affordable options |
| `inner_monologue_like` | step-wise: the LLM sees the history with every result text, user answers and `look` scenes, and returns the next call | yes | whatever the LLM decides after seeing the failure | after Inner Monologue (Huang et al. 2022, https://arxiv.org/abs/2207.05608) |
| `progprompt_like` | one LLM call writes a program: tool calls plus `assert pred(x) else: call` recovery lines; a small interpreter (no `exec`) runs it | no | the assertion lines only (`holding` reads the gripper sensor through `grasp_check`) | after ProgPrompt (Singh et al. 2022, https://arxiv.org/abs/2209.11302); the live-smoke baseline |
| `knowno_like` | the LLM lists up to 4 interpretations (goal conditions); 5 samples (temperature 0.7, seeds 0-4) give option frequencies; conformal set {y : freq(y) >= 1 - q_hat} | when the set does not have exactly one option | then the inner-monologue loop with the chosen interpretation | after KnowNo (Ren et al. 2023, https://arxiv.org/abs/2307.01928). KnowNo scores options with next-token probabilities; we use sample frequencies. q_hat comes from `planners/knowno_calib.json` |
| `robot_agent:sage` | robot_agent's AssistLoop (SAGE, generator grace) on the homeloop robot package | robot_agent's dialog | robot_agent's gate, guard, recovery and replanning | [robot_agent planners](robot_agent.md) |
| `robot_agent:grace` | robot_agent's ClosedLoop with planner grace | no | robot_agent | [robot_agent planners](robot_agent.md) |
| `robot_agent:llm_direct` | robot_agent's ClosedLoop with planner llm_direct (one `skill::input` program) | no | robot_agent's replan | [robot_agent planners](robot_agent.md) |

## Shared prompt parts (`planners/prompts.py`)

Every LLM prompt starts with `MODE: <mode>`, then the tool list (move, find, pick, place, put_in, open,
close, handover, say, announce, ask, look, vlm_check, wait, dock) and `Observation.text()`: the
instruction, places, people, object memory, robot state, budget, user events and the history. Step
answers are JSON: `{"action": {"skill", "args"}}`, `{"finish": "done" | "refuse" | "give_up", "say"}`, or
the pseudo-action `decline` (refuse one part of a mixed request and continue).

Answers are parsed with a tolerant JSON parser (code fences, `<think>` blocks and text around the JSON
are skipped). An answer that does not parse or names an unknown tool gets up to 2 repair prompts (each
counts as an LLM call); after that the planner gives up.

## KnowNo calibration

`homeloop-bench calibrate-knowno --split train --limit 300 --llm URL --model M` computes the
non-conformity score 1 - freq(true option) on train tasks and stores q_hat = the ceil((n + 1)(1 - epsilon)) / n
empirical quantile (epsilon = 0.15, KnowNo's 1 - epsilon = 0.85 coverage) in `planners/knowno_calib.json`.
The file shipped in the repo is an uncalibrated default (`"calibrated": false`, q_hat 0.7: keep options
chosen in at least 30 % of the samples). Calibrate before reporting knowno_like numbers.

## FakeLLM

`--llm fake` uses `homeloop_bench.llm.FakeLLM`, a rule-based reader of the prompt (`planners/keyword.py`:
names from the house lines, verbs, clause splitting in English and Korean, catalog common sense for
hazards). It makes the planners' loops, parsers and the runner testable without a model. Its numbers are
not a planner's results and are never reported.

## Your own planner

`homeloop-bench run --planner package.module:ClassName ...` runs any importable class (the module must be on
`PYTHONPATH`); the built-in names are registry keys. The class needs `__init__(self, llm=None)` and
`run(self, env)`, and may set `needs_llm = True` (the runner then requires `--llm`) and `privileged = True` (only for
reference planners that read `env.truth`; such results are not comparable). The helpers in
`homeloop_bench/planners/base.py` cover the two usual shapes:

```python
from homeloop_bench.env import Finish, ToolCall
from homeloop_bench.planners.base import StepPlanner


class LookThenGiveUp(StepPlanner):
    """One call per step: act(obs) returns a ToolCall or a Finish."""
    def act(self, obs):
        if not obs.history:
            return ToolCall("look", {})
        return Finish("give_up", "I don't know how")
```

`PlanPlanner.plan(obs)` returns a whole list of `ToolCall` (optionally ending with a `Finish`) and
`on_failure(call, result, obs)` may return recovery calls. The `Observation` fields: `task_text`, `lang`,
`places` (id, name, room, kind, openable, room_name, aliases), `people` (id, name, usual_place, role), `memory`
(id, cls, name, attrs, usual_place), `robot` (the robot's sensed state), `last` (the last result), `events` (user
events since the last observation), `history`, `step`, `t`, `calls_left`, `time_left_s`; `obs.text()` renders it as
the shared prompt. Decline one unsafe part with `env.note_refusal(text, subtask=None, obj=None)` naming it (runner.md
"Judge"); end with `env.finish("done" | "refuse" | "give_up")`. An exception inside `run` makes that episode
`status: "error"`; an `LLMError` or `ImportError` aborts the whole run (live_smoke.md).

## Deliveries (round 2)

`oracle` and `naive` never read a delivery atom's `mode` label. They choose reach or hand themselves from what a
robot observes when it gets the request (`planners/oracle.observed_modes` -> `homeloop_robot.oracle.delivery_modes`
-> `reach.choose_mode`): the heard instruction (an EN request form such as "hand me" / "in my hand", not "my hands are full";
KO 손에 / 건네 -> hand), the house profile (`prefers_handover` -> hand), the furniture around the person at the
start (no reachable support surface -> hand; reachable surfaces that are all full -> hand as the robot's own
choice, `surface_full`, while the task label stays reach), else reach; after a correction, the correction's words are added for its new deliveries. In reach mode
the robot oracle puts the object on the nearest reachable support surface with room where the person is now (room
that the goal's own `on` / `in` atoms need does not count), else hands it over. A test checks that the plans are
identical whatever the labels say (`tests/test_reach_bench.py`). The LLM planners see the same scene in
`People now (...)` and one line of the tool text: bring an object to a person by putting it on a table, desk,
counter, nightstand or shelf they can reach, or hand it over when they ask for it in their hand or no such surface
with room is near them.

