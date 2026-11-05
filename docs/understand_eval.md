# Understanding evaluation

`homeloop-bench understand-eval` measures one thing: how well robot_agent's **understand step** turns a request into goals.
It runs nothing else (no question, read-back, plan or motion) and costs one LLM call per task, so hundreds of tasks take
minutes. It is the fast inner loop for changes to the understand step; an end-to-end run (`run`) confirms them.

Gold goals are read on the evaluation side only. They never reach the robot.

## What runs

For each task, language and text condition the command builds the episode as `run` does (the planner class's own
construction: the robot package, the ENV, the per-episode object memory, the translate model, the loop options and the LLM
chain with its cache) and drains `AssistLoop.run_blocking` only up to its `understand` event (`planner.until`, then the
generator is closed). The event carries the model's status, its question and the goals **after grounding** on the ENV
(robot_agent's `_take_understanding`: one call, repairs and re-asks included, the goal filters and the destination
repairs). That goal set is "the understood goal set". The read-back, the hazard gate and the clarify dialogue come later in the
loop and are not simulated, so a task that the loop would have corrected by asking is still judged on its first reading.

`--planner` is any SAGE planner (`robot_agent:sage` by default; `sage_pivot_translate`, `sage_norag`, ...): the same ENV,
translate model and options as in a run. It must not be a closed-loop planner.

## Conditions

| flag | meaning |
|---|---|
| `--text clean` | the task's own text of the language (the template or paraphrase text, as written in the task file) |
| `--text asr` | the text after the profile's simulated speech recognition (`--profile real`, the task seed `--seed`; the same draw a run makes: `EpisodeEnv`'s `hear_instruction`) |
| `--text both` (default) | both, as two records per task |
| `--lang en`, `ko`, `en,ko` | the language of the text |
| `--split train` (default), `dev` / `--tasks FILE` | tune on train, validate on dev. The test split, and any task whose `split` is `test`, is refused |
| `--limit N --offset K` | tasks `K .. K+N-1` of the split or file |

LLM calls are cached in `OUT/llm_cache/` like the other runs (the same prompts are never asked twice; a rerun into the same
`--out` makes no call). Same arguments give identical `records.jsonl` and `summary.json`.

## Common form of goals

Gold atoms and robot_agent goals are mapped to one form, an atom `(kind, class, colour, destination, person)`, and compared as
multisets. Every rule below is in `homeloop_bench/understand_eval.py` (`gold_atoms`, `robot_atom`, `compatible`).

| rule | the two forms that are treated as equal |
|---|---|
| R1 | `on(obj, place)` and `in(obj, place)` keep their kind: `on` is **not** `in`. The place is compared by ENV key (the gold place id is the ENV key). The `from` slot is not a goal and is not compared |
| R2 | A person receives an object: gold `delivered(obj, person)` (either mode) is the robot's `on` / `in` / `deliver` with a person as the destination (the speaker's ENV entry, `me`, the person's key or alias, the person's seat for `deliver`). All are the atom `give(class, person)`. The delivery mode (hand or reach) is not compared: robot_agent infers it from the words |
| R3 | Gold `said_to(person, message)` and the robot's `say(sentence, to)` are the atom `say(person)`. **Only the person is compared, not the words of the message** (a limit: a wrong sentence to the right person is a match) |
| R4 | Gold `robot_at` in any one of a room's places (an `any` group) is matched by a robot `go` to any place of the group, or to the room key `@room` when the group is all of that room. A single named place is matched by that place only |
| R5 | Gold `docked` is a `go` to the house's dock place |
| R6 | Gold `open(c)` / `closed(c)` are the robot's `open` / `close` of the same container |
| R7 | An object is compared by **class**: gold object id -> class by the start world; the robot's name -> class by the class names and aliases in English and Korean, after dropping articles and colour words (`kitchen knife` finds `knife`). A colour that the robot names must equal the gold object's colour; a colour it does not name is not wrong. A name that is no class is the atom class `?name` and never matches |
| R8 | A repeated atom is spurious: the matching uses each predicted atom once |
| R9 | A person is compared by id: ENV key, alias, English or Korean name, speaker word (`me`, `user`, `here`, ...) and the id itself all resolve to the id of the start world; an unknown name is `?name` and never matches |

Gold atoms come from the task's subtasks with conditions resolved on the start world (the correction's final goal, the
conditional's branch). A subtask of kind `refuse` has no goal (its `unmoved` atom is the judge's, not a goal).

## Metrics

Per record: `exact` (the sets match: nothing dropped, nothing spurious), `dropped` (gold atoms with no match), `spurious` (predicted
atoms with no gold atom), `matched`. Per group (`summary.json`, `report.md`):

| key | meaning |
|---|---|
| `exact_rate` | share of tasks with an exact set match |
| `atom_precision`, `atom_recall` | micro: matched atoms over predicted atoms, over gold atoms |
| `dropped_atoms`, `spurious_atoms` (and `tasks_with_...`) | counts |
| `n_confident` | readings the robot would act on without asking: status `clear`, no question, at least one goal |
| `confident_wrong` | confident readings that are not exact. `confident_wrong_rate` is over all tasks of the group, `confident_wrong_of_confident` over the confident ones. This is the source of false successes |
| `asked`, `refused`, `no_goal` | the model asked a question (or the loop asked to repeat), refused, or gave no goal |
| `ended` | probes that ended before the understand step (the LLM failed): an error, not a reading. Exit code 4 above 5 % |

**Headline population:** tasks of kind `feasible` with no refused part (`expect = act`, not `mixed`): they have a gold goal
set to understand and no question is wanted. Clarify tasks (`expect = ask`) and refuse tasks (`expect = refuse`) are in
`by_expect` (for them read `asked` and `refused`, and `confident_wrong` is a reading that should have been a question or a
refusal); mixed tasks (a refused part: the unsafe goal is still in the first reading, the hazard gate removes it later) are
the `mixed` row.

Breakdowns, all on the headline population: `by_condition` (`lang/text`), `by_lang`, `by_text`, `by_structure` (the task's
`structure`: single, sequence, conjunction, correction, ordered, conditional, shared_object, with_context),
`by_lang_structure`, `by_lang_text_structure`.

Each record also has the text the robot read (`heard_text`), the clean text, the speech-recognition event, the model's status, reason and
question, and its raw goals (`raw_goals`), so a failure can be read in `records.jsonl` without a rerun.

## Files

`OUT/records.jsonl`, `OUT/summary.json` (`config` records planner, profile, seed, languages, texts, model, window),
`OUT/report.md` (the tables), `OUT/llm_cache/`.

Tests: `tests/test_understand_eval.py` (rules, metrics, the probe through the real adapter and loop with a scripted backend).
The diagnostic planner that uses the same gold conversion is `robot_agent:sage_gold` ([planners](planners.md)).
