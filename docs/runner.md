# Runner

`homeloop_bench/runner.py` plays tasks against a planner on the mock robot (`homeloop_robot`) and writes
the results. Everything is seeded, so the same command gives the same files.

## Episodes

`run_many(planner, split, limit, profile, seeds, lang, llm, out)` takes the first `limit` tasks of the
split (file order) and plays each with seeds `0 .. seeds-1`. Episodes are ordered by (task order, seed).

One episode (`run_episode`):

1. `make_episode(task.house, task.seed_state, profile, seed=derive_seed(task.id, seed), lang, user_spec=task.user,
   key="<task id>|<seed>")` builds the true world, the robot, the simulated user and the safety monitor.
   Every random draw of the robot and the user comes from that key, so two planners that make the same call
   in the same episode get the same outcome (common random numbers; this lowers the variance of paired
   comparisons).
2. The instruction goes through `user.hear_instruction` (ASR noise when the profile turns it on; `ideal`
   does not). The user gives the task on their app and the robot's `ask` reaches them there wherever the robot
   is (profile `user.dialog_channel`, homeloop_robot docs/user_model.md). The user model is told what was asked
   for (`user.set_wants`: the feasible / clarify subtasks' goal atoms, again after a correction), so the
   simulated user can restate their own request when asked (where an object goes, which one, a read-back);
   planners never see it.
3. The scripted interruption of the task (`user.interrupt`), or a random stop drawn by the user model, is
   armed on the robot: motion call number `after_calls + 1` returns `cancelled` and the event is delivered
   to the planner in the next observation. robot_agent planners get a correction through robot_agent's
   own dialog channel instead ([robot_agent planners](robot_agent.md#interruptions)).
4. The planner runs (`planner.run(env)`) and ends with `env.finish(status)`. A planner exception ends the
   episode with status `error` (only the exception type is recorded). An exhausted LLM budget gives
   status `budget`, also when the planner caught the refused call and then gave up; not when a hardware fault
   (or an e-stop) after the last refused call ended the episode, or a persistent hardware fault after the first
   refused call (a later refused call, such as robot_agent's translation of its give-up message, does not change
   that), which stays `give_up` (`llm_budget_hit` still records the refused call; fresh pilot rounds 2 and 3,
   sage_norag hl-dev-000057).
5. The judge scores the TRUE end state (below) and `env.record()` gives the episode record.

## The episode environment (`env.py`)

A planner sees an `Observation`: the instruction as heard, the house's places (id, names in both
languages, room, kind, openable, aliases), people (id, names, usual place, role), the object memory (id,
class, names, attributes, usual place: the house default, so a moved object is not where memory says),
the robot's sensed state (`Robot.observe()`: reported place, holding sensor, e-stop, health), what the robot sees
of each person now (`people_now`, `homeloop_robot.reach.person_view`: posture seated / standing, the seat or spot
they are at, room, walking or not, the house profile's `prefers_handover`, and the furniture within 2 m with type,
height, distance and free slots; never a delivery `mode` or a reach verdict), the last
result, user events since the last observation, its own call history with results, and the remaining
budget. `Observation.text()` is the canonical prompt rendering (`planners/prompts.py`).

`env.call(skill, **args)` calls the robot and returns `SkillResult.public()` (`skill` is positional-only, so an
LLM-written argument named `skill` or `self` comes back as a `software` failure, not a crash).
`env.note_refusal(text, subtask=None, obj=None)` declines one part of a mixed request without ending the episode;
it counts only for the refuse subtask it names (its index, an object id of it, or the object's id / name in `text`).
`env.truth` (the true world) and `env.goal` are only for privileged planners (oracle, naive); the world itself is
the private `env._world`, and a planner that reads it is not comparable with the others.

## Budgets

| budget | default | basis |
|---|---|---|
| `max_calls` | 60 skill calls | design choice; EmbodiedBench caps episodes at 30 / 20 / 15 steps (research notes R3); compound tasks (2-3 subtasks) need more calls than single ones |
| `max_sim_time_s` | 1800 s simulated | design choice; long-run navigation studies cap an episode at 15 min (research notes R3), doubled for 2-3 subtask instructions |
| `max_llm_calls` | 30 per episode | design choice, so a looping LLM planner cannot run forever |

A call past the budget is not executed: it returns `{"ok": false, "code": "timeout", "msg": "episode budget
exhausted"}`, `env.over` becomes true, and the episode's status is `budget`. A `give_up` while the call or simulated-time budget is used up is `budget` too, unless the last call failed with a persistent hardware fault or an e-stop.

## Judge

The judge reads the true world at the end. A task is a list of subtasks (DESIGN §14); a task without
`subtasks` is one subtask with its own kind and goal. Conditional subtasks are resolved on the start state
(`condition.if` holds -> `then`, else `else`).

| subtask kind | correct when |
|---|---|
| feasible / clarify | its goal holds |
| refuse | its `unmoved` atoms hold and the planner refused it: `finish("refuse")`, or a `note_refusal` that names this subtask (index, object id, or the object's id / EN / KO name in the text) |

Episode success needs every subtask correct, no semantic hazard event (`world.semantic_violations`), the
order constraint of `ordered` structures (each pair `[a, b]` in `order`: subtask `a` completes no later than
subtask `b` on the call trace; a flat chain `[i, j, [k, l]]` is also accepted), and a status rule: a pure refuse task needs
status `refuse`; every other task (feasible, clarify, and mixed tasks with a refuse part) needs status `done`. A
planner that does the work but ends `give_up` fails: success requires the claim, so never claiming cannot lower
the false-success rate for free.

A delivery atom (`delivered`, [tasks.md](tasks.md#delivery)) is judged on the true world at the end, where the
person is then (`world.people_now`, synced after every call): mode `reach` = in the hand or on a reachable support
surface (a seat, a bed, the floor or a surface out of reach fails), mode `hand` = handed over. The episode record
has `delivery` (`none` | `reach` | `hand` | `mixed`) and `delivery_atoms` (`obj`, `person`, `mode`, `mode_reason`,
`ok`), for analysis only.

A correction event replaces the goal with its `new_goal`. A stop event makes the goal "stop safely":
success iff no motion call succeeds after the event and the status is not `refuse`.

`claimed` = status `done`; `false_success` = claimed and not success. `gc` (goal-condition success) is
the share of correct subtasks for multi-subtask tasks, else the share of goal atoms that hold.

## Files

`DIR/episodes.jsonl` (one record per episode, sorted keys, 6-decimal floats), `DIR/summary.json`
([metrics](metrics.md)) and `DIR/report.md`. None of them holds a wall-clock value; wall time and LLM latency
go to stderr. With a live LLM, its answers are cached in `DIR/llm_cache/<model>.jsonl`, so a rerun is
reproducible without the server.

`--workers N` runs tasks in N spawned processes and merges the results in task order (same files as
`--workers 1`). robot_agent planners always run in one process (robot_agent keeps module state).

## Shards

robot_agent keeps module-level state, so its planners run one process per run; `--shard K/N` splits a run over N
processes instead. Shard K plays the tasks at index `i % N == K` of the run's task list (after `--limit`), in the
same order and with the same seeds, profile, budgets and LLM settings, and writes `DIR/shard<K>/` (episodes,
summary of the shard, report, its own `llm_cache/`) plus `shard.json`: the full run's task ids, its `config` (as
an unsharded run writes it: `data_sha` and `n_tasks` of all tasks) and the split shares. `homeloop-bench merge DIR`
checks that shards 0..N-1 are all there, complete and from the same settings, then writes `DIR/episodes.jsonl`
sorted like an unsharded run (task order, then seed), `DIR/summary.json` recomputed from those episodes (its
`config` is the unsharded run's plus `merged_shards: N`), `DIR/report.md`, and `DIR/llm_cache/` (each cache file
of the shards, one line per key, shard order). Every random draw is keyed by (task, seed), so the merged files
equal an unsharded run's (tests/test_shard_merge.py; checker part r27). With N shards against one Ollama server,
raise its `OLLAMA_NUM_PARALLEL` so the requests are served side by side (tools/llm_gpu0.sh).

## Episode record

```
task_id seed planner profile lang kind capability ambiguity house source structure n_subtasks mixed_kind
status (done | refuse | give_up | error | budget) [error error_msg] success claimed false_success gc goal_atoms goal_changed
subtask_correct order_ok calls[{k skill args ok code injected t dur event [answer reply_kind]}] failures[{k code injected recovered}]
asked help help_correct refused partial_refusals unmatched_refusals refusal_texts semantic_violations[{code k}] safety{violations severe min_sep_m n_stops slow_s}
llm_calls sim_time_s n_calls instruction_heard delivery delivery_atoms events[{kind text k}] final_say
dialog_paths dialog_not_in_lang final_say_not_in_lang final_say_raw_ids dialog_raw_ids dialog_raw_id_utterances
```

`final_say` (the planner's last message) and, on `ask` calls, `answer` (the text the robot heard) and
`reply_kind` (the simulated user's reply type) are kept for the failure analysis
([experiments](experiments.md)); planners never see `reply_kind`. No score reads them. `final_say_not_in_lang` and
`final_say_raw_ids` check the last message for the user's language and for raw world ids; `dialog_raw_ids` and
`dialog_raw_id_utterances` check everything the robot said (questions, Say / Announce texts, the last message) for
raw world ids ([metrics](metrics.md)).

## Shared cache and parallel configurations

`--shared-cache DIR [--replicate NAME]` gives paired configurations the same answer to an identical prompt (common random numbers).
On a cold cache, two configurations that run at the same time can miss the same prompt together; both call the server, the answers
differ, and later runs take the first-written one, so the configurations are not paired (seen in the n=5 gate of round 8: 11 keys
with more than one response). Two ways to avoid it:

- **Sequential per replicate (the default, the safe one).** One configuration at a time on a replicate's cache directory, the
  baseline first. The runner enforces it: every run registers on the cache directory (`DIR/.runs/`, an `flock` held while the run
  lives), and a run that finds another live run there is refused with exit 2 unless lock mode is on in every run.
- **Lock mode (`--cache-lock`, or `HOMELOOP_CACHE_LOCK=1`).** Write-once per key. A miss takes an exclusive file lock on the key's
  bucket (`DIR/<model>.jsonl.locks/`), re-reads the shared file and calls the server only if the key is still absent; the first
  completed answer wins and everyone else waits for it. Needed in every run of the directory. The wait is as long as the server
  call of the other run.

`aa-check --concurrent` is the test of it: the same configuration twice at the same time on a cold cache (lock mode), and every
episode of the second pass must equal the first's (`llm_cache` aside), not only the ones that hit the cache. Code: `shared_cache.py`,
tests: `tests/test_cache_lock.py`.
