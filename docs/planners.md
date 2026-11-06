# Planners

`homeloop-bench planners` lists them. Every planner implements `run(env)` (`planners/base.py`) and ends
with `env.finish("done" | "refuse" | "give_up")`. Only `oracle`, `naive` and the diagnostic `robot_agent:sage_gold` are privileged (they read the
true world or the hidden goal); every other planner sees only the [observation](runner.md#the-episode-environment-envpy).

| name | loop | asks | recovery | notes |
|---|---|---|---|---|
| `oracle` | re-solves with `homeloop_robot.oracle.solve` from the true world after every call | clarify tasks: the gold question once, then acts on the true intent | full re-solve; at most 3 consecutive attempts of a call; `wait(5)` before retrying perception_unavailable / blocked; an `ask` for help when a move is blocked, and before the last attempt of a still-blocked move it backs off to the room's floor spot and comes another way (a person in bed next to the target cannot clear the way); gives up on a persistent hardware fault or e-stop | refuses refuse tasks; declines the refuse part of a mixed task; finishes `done` only when the judge would score success, so its false success is 0 |
| `naive` | the oracle's plan from the start state, open loop | never | none: the first failed call ends the episode (`give_up`); all calls ok -> `done`, so silent failures become false successes | the ablation that shows what closed-loop recovery buys |
| `saycan_like` | each step: the calls whose preconditions hold in the planner's own belief (where it is, what it holds, what it found here, what it opened), the LLM picks one by index | no | none beyond the step choice; the prompt has the state only, no failure text | after SayCan (Ahn et al. 2022, https://arxiv.org/abs/2204.01691). SayCan multiplies LLM likelihoods by learned affordance values; a chat API gives no likelihoods, so here the LLM chooses by index among the affordable options |
| `inner_monologue_like` | step-wise: the LLM sees the history with every result text, user answers and `look` scenes, and returns the next call | yes | whatever the LLM decides after seeing the failure | after Inner Monologue (Huang et al. 2022, https://arxiv.org/abs/2207.05608) |
| `progprompt_like` | one LLM call writes a program: tool calls plus `assert pred(x) else: call` recovery lines; a small interpreter (no `exec`) runs it. The prompt holds three fixed example programs, as in ProgPrompt (see below) | no | the assertion lines only (`holding` reads the gripper sensor through `grasp_check`) | after ProgPrompt (Singh et al. 2022, https://arxiv.org/abs/2209.11302); the live-smoke baseline |
| `knowno_like` | the LLM lists up to 4 interpretations (goal conditions); 5 samples (temperature 0.7, seeds 0-4) give option frequencies; conformal set {y : freq(y) >= 1 - q_hat} | when the set does not have exactly one option | then the inner-monologue loop with the chosen interpretation | after KnowNo (Ren et al. 2023, https://arxiv.org/abs/2307.01928). KnowNo scores options with next-token probabilities; we use sample frequencies. q_hat comes from `planners/knowno_calib.json` |
| `robot_agent:sage` | robot_agent's AssistLoop (SAGE, generator grace) on the homeloop robot package, with SAGE's retrieval: the top 3 examples of the robot's seed pool in its prompts | robot_agent's dialog | robot_agent's gate, guard, recovery and replanning | [robot_agent planners](robot_agent.md) |
| `robot_agent:sage_norag` | the same, with an empty seed pool (zero-shot SAGE): the RAG ablation, the only difference | as sage | as sage | [seed pool](robot_agent.md#seed-pool-sage-and-sage_norag) |
| `robot_agent:sage_ask` | `robot_agent:sage` with people tracking off: the ENV has no positions of people, so SAGE asks "Where are you?" and maps the answer onto the house (same seed pool) | robot_agent's dialog | as sage | [experiments: SAGE-v2 changes](experiments.md#sage-v2-changes-round-3) |
| `robot_agent:sage_nohazard` | `robot_agent:sage` with its core hazard rules off (`hazard_rules=off`, model-only safety): ablation | as sage | as sage | as above |
| `robot_agent:sage_pivot_none` / `robot_agent:sage_pivot_translate` | `robot_agent:sage` with the language layer's `input_pivot` = `none` (the Korean words as they are) / `translate` (the English translation; the original only as the source of `said`). `robot_agent:sage` itself uses the manifest's `input_pivot` (manifest `none`; the KO comparison chose it). KO-only ablations; for English users the layer does nothing | as sage | as sage | [experiments: R3 language layer](experiments.md#r3-language-layer-3-mode-ko-comparison) |
| `robot_agent:sage_complete` | `robot_agent:sage` with the gate's `complete` operator on (the gate writes a missing goal's segment; `completed_by_gate`): ablation | as sage | as sage | as above |
| `robot_agent:sage_lab` | `robot_agent:sage` with the solution-lab prototype `person_goals` on (robot_agent option, env `ROBOT_AGENT_PERSON_GOALS`, manifest `planner.person_goals`; default off): in a request that mixes go / say goals with moves, the go and say steps are the loop's own fixed sub-goals (the exact sentence, a MoveTo to the named person), the planner expands only the moves; a hand-over for a hand goal goes to the person the goal names; an exactly repeated goal is dropped; an Open of what cannot be opened is removed. A prototype under test, not a result | as sage | as sage | as above |
| `robot_agent:sage_ground2` | `robot_agent:sage` with the grounding chain v2 on (robot_agent options `go_steps`, `kind_anchor`, `name_canon`; default off): drops a `go` that is a step (to a person, the speaker, a `say` listener, the source of a later move), drops an `open` end state when the words carry no open verb, maps an English object name onto the remembered name (several remembered places give a which-one question). `sage_g2_go`, `sage_g2_kind`, `sage_g2_name` switch on one each. No extra call. A prototype under test, not a result | as sage | as sage | as above |
| `robot_agent:sage_exec` | `robot_agent:sage` with execution integrity on (robot_agent option family `exec_integrity`; default off): a per-goal repair kept only if it certifies and a plan object bound to the one goal object whose word tokens contain it (`gate_strict`), a checked and retried return to the last `go` goal (`endstate_check`), a reset of a BLOCKED PutIn into an open container (`reset_container`), and a wait on the robot where a `planner.recovery.wait` is declared (`wait_on_robot`). The robot package declares none, so `sage_exec`, `sage_ei_wait` and `sage_r3` carry a variant overlay (`manifest_overlay`, ASSUMED schedule 2, 4, 8 s of the pack's Wait action, recorded in `summary.json` `planner_config`); without it the flag would be inert. `sage_ei_gate`, `sage_ei_end`, `sage_ei_reset`, `sage_ei_wait` switch on one each. No extra call. A prototype under test, not a result | as sage | as sage | as above |
| `robot_agent:sage_inv` | `robot_agent:sage` with `inventory_ask` on: a named object that matches more than one instance in the robot's own object memory is narrowed by the person's words, else asked once as a closed choice (the pack's `planner.canonical_lang` and `plural_fold` data). A prototype under test, not a result | as sage | as sage | as above |
| `robot_agent:sage_unstick` | `robot_agent:sage` with `dialog_unstick` on (lab round 4; default off): a restatement that reproduces a refused reading is read back once more instead of ending the run, a not-sure answer to a where-is question makes the robot search (one more understand call, once), and a question that opens with its own apology is not prefixed with the silence apology. A prototype under test, not a result | as sage | as sage | as above |
| `robot_agent:sage_r3` | `sage_ground2` + `sage_exec` + `sage_inv` in one variant (lab round 3 combination); differs from `robot_agent:sage` in robot_agent options only | as sage | as sage | as above |
| `robot_agent:sage_reask` | `robot_agent:sage` with `reask_abstain` on: a goal-less reading whose own question asks where an object is, is understood once more with the robot's Find skill stated. Killed in round 2 (clarify tasks become confident readings); kept for the record | as sage | as sage | as above |
| `robot_agent:sage_gold` | **DIAGNOSTIC, PRIVILEGED. Never a headline planner; label it privileged in every table.** `robot_agent:sage` that does not understand the request: the task's gold goals, converted to robot_agent goals (`homeloop_bench/gold_goals.py`: no source location, so the robot uses its memory and searches; the delivery mode as the robot would infer it from the words and the scene, never the label), are handed to `AssistLoop.run_blocking(goals=...)` with robot_agent's option `accept_goals` on, which skips the understand step (no LLM call for it, no question, no read-back). It measures the execution-only ceiling: plan, gate, search, recovery and the dialogue about what is still unknown. A task with no gold goal to give (a request to refuse) is understood as usual; a clarify task is not asked about (its goals are known), so help and question metrics are not comparable with `robot_agent:sage`. Loss from understanding = `sage_gold` minus `sage`; loss from execution and the world = `oracle` minus `sage_gold`. `summary.json` `config.planner_config` has `privileged: true` | none for the understand step, as sage afterwards | as sage | [understanding evaluation](understand_eval.md) |
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

## Structured questions (round 2.7)

`env.call("ask", question=..., lang=..., meaning={"qtype": ..., <slots>})`: a planner may say what its question
asks, from the frozen qtype list of homeloop_robot `docs/user_model.md`
("Structured questions"). The user hears the question text; the answer comes from the task script by qtype and
slots, with the same wrong / not-sure / silence mix and ASR noise. A question without a meaning is read by the user
model's rules, then (only when the rules do not understand it and the run has an LLM) by the cached LLM intent
classifier `homeloop_bench/user_intent.py`. Declared meanings: `oracle` (its gold clarification question:
`which_object` / `which_place`; its help request: `help`), `knowno_like` (its choice question), `naive` never
asks. robot_agent:sage: the adapter wraps `AssistLoop._ask_io` and derives the meaning of SAGE's own English
template questions before translation (`homeloop_robot/configs/ra_dialog.py`); `HOMELOOP_RA_STRUCTURED=0` turns
that off. LLM planners that write their own questions (progprompt_like, saycan_like, inner_monologue_like) send
free text. Each ask in `episodes.jsonl` has `intent: {path, qtype, rule}`.

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

## progprompt_like example programs

ProgPrompt (Singh et al. 2022, arXiv:2209.11302) prompts the LLM with example programs: Pythonic functions named
after the task, with comments and `assert ... else:` recovery lines. Until R2-5 (B4) progprompt_like had none
(zero-shot). It now has three (`planners/progprompt_examples.py`), written for three train-split tasks and placed
in `example_flat` (`planners/progprompt_example_house.yaml`), a house that no split uses (all eight benchmark
houses appear in the test split, so no evaluated house is free of evaluation tasks):

| example | source task (train) | shows |
|---|---|---|
| take the green mug off the dining table and put it on the coffee table | hl-train-000183 | move to where the object is before `find` |
| look for my towel and put it back on the drying rack | hl-train-000133 | open the closed container before `find` |
| store the dish soap in the fridge | hl-train-000218 | decline an unsafe request (`decline`, `finish("refuse")`) |

The instruction of each example is the source task's English template text; the program uses the example
house's ids. Each example runs with the planner's own interpreter on the mock robot (`ideal`) and reaches its
goal (`tests/test_progprompt_examples.py`). The finished zero-shot runs are kept as an ablation in
`results/exp_r2/ablation/progprompt_like_zeroshot__qwen3-vl:8b-instruct__{en,ko}/` ([experiments.md](experiments.md)).
