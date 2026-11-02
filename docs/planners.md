# Planners

`homeloop-bench planners` lists them. Every planner implements `run(env)` (`planners/base.py`) and ends
with `env.finish("done" | "refuse" | "give_up")`. Only `oracle` and `naive` are privileged (they read the
true world and the hidden goal); every other planner sees only the [observation](runner.md#the-episode-environment-envpy).

| name | loop | asks | recovery | notes |
|---|---|---|---|---|
| `oracle` | re-solves with `homeloop_robot.oracle.solve` from the true world after every call | clarify tasks: the gold question once, then acts on the true intent | full re-solve; at most 3 consecutive attempts of a call; `wait(5)` before retrying perception_unavailable / blocked; an `ask` for help when a move is blocked; gives up on a persistent hardware fault or e-stop | refuses refuse tasks; declines the refuse part of a mixed task; finishes `done` only when the judge would score success, so its false success is 0 |
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
