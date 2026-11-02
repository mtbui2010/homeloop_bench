# Realism of the tasks

Requirement (user, 2026-11-02): the benchmark must be close to reality and contain no case that does not exist in
real homes. Every object, placement, task, utterance and hazard must be something that happens at home.

```
python -m homeloop_bench.data realism --strict     # rules R-a..R-h; writes data/quality/realism_report.json
```

The command prints a JSON report and writes `data/quality/realism_report.json` (repository root): per rule the
number of violations, up to 20 examples, and the intentional cases. `--strict` exits 1 on any violation. The
robot-side rules are reused from `homeloop_robot.realism` (homeloop_robot docs/realism.md); the task-side rules are in
`homeloop_bench/gen/realism.py`.

## Rules

| rule | what is checked on every task |
|---|---|
| R-a | the robot catalog: every object class has category, provenance, mass, size, graspable / liquid / fragile / sharp / food / hot and typical receptacles; every receptacle category has room types and a capacity (robot-side) |
| R-b | every object a task touches is now on / in one of its typical receptacles, and every goal destination (also clarify candidates and the destination of an interruption) is a typical receptacle of the object. Refused requests are the exception: the requested placement (bleach into the fridge) is reported as intentional when its hazard is sourced, or when the request is infeasible (too heavy) |
| R-c | an object never goes into a receptacle smaller than it; every liquid is packaged |
| R-d | feasible pick / place / handover objects are graspable and within the 1 kg payload (OK-Robot Sec. V-E); heavier ones only appear in `refuse` (infeasible) tasks |
| R-e | every task has an `activity_source` (a published task type, with URL). Families whose wording has no opened source are marked `assumed: true`; they are capped at 5 % of the tasks (only the conditional families are) |
| R-f | kind semantics: feasible tasks name each object so that it resolves in the house (the robot's resolvers; a colour is added when the house has two of the class); clarify tasks have >= 2 real candidates that match the words and the text does not single one out; the ambiguity type is an AmbiK type; refuse (unsafe) tasks carry a hazard code with its source and the request really causes it (`goal_hazards`); no contradictory goals; 1-6 goal atoms; a self-correction ends on the final object; the top-level kind follows the mixed-kind rule |
| R-g | language: no unfilled slot, `{}`, `<>`, `None`, `null` or underscore; no repeated word; English without Hangul; Korean in Hangul (only `TV` and the room letters A/B/C are Latin), >= 90 % Hangul letters, every sentence in 해요체 (ends in -요 / -죠); length bounds per type; colloquially dropped object particles in <= 30 % of the Korean texts |
| R-h | houses: room types have their fixtures, place distances and object counts are in range (robot-side) |

Generation enforces all of these before a task is kept (gen/sample.py), so the shipped data has zero violations.
The judge-panel audit (`data/quality/realism_audit.json`, >= 300 random tasks, flagged <= 2 %) is written by the
audit step after the build, not by the generator.

## Extra realism choices in the generator

- Kitchen things are stored in the kitchen, clothes and towels in bedrooms / bathrooms, books and toys never in
  kitchen storage; special receptacles hold only their things (shoe cabinet: keys and wallets; toy box: toys;
  medicine cabinet: medicine; sink cabinet / laundry cabinet: cleaning products; kimchi fridge: kimchi, produce,
  drinks) (`families.room_ok`).
- Adult items stay off a child's furniture; in the shared flat an item goes into a roommate's room only when it is
  that roommate's.
- No microwave or stove as a feasible destination (only in refused, hazardous requests).
- People are named from the user's point of view ("Dad" and "my son" in the family house, "Grandpa" / 아버님 in the
  Korean apartment, "the caregiver" / 요양보호사 선생님 in the care home); elders get Korean honorifics (께, 드리다,
  말씀드리다).
- Compound requests join only subtasks that belong together: the same room ("while you're in the kitchen"), the
  same person (bring Dad his phone and tell him about the call), the same object or container (put the towel in the
  wardrobe and close it), a shared reason (guests are coming: tidy three things), or the end of an errand (go back to
  the charger).
- A reason is added only where it fits the object ("I'm thirsty" for drinks, "I want to watch TV" for the remote),
  and the English and Korean reasons are the same sentence (paired banks).

## Published sources

| what | source | URL |
|---|---|---|
| objects, receptacles, typical placements | AI2-THOR object types / ALFRED receptacles; YCB object set Table II (robot catalog) | https://ai2thor.allenai.org/ithor/documentation/objects/object-types, https://arxiv.org/abs/1912.01734, https://arxiv.org/abs/1502.03143 |
| fetch ("bring me ...") | SayCan Table 1 'NL Nouns' / 'Crowd-Sourced' | https://arxiv.org/abs/2204.01691 |
| rearrange / contain (pick and place) | ALFRED Fig. 2 'Pick & Place'; 'Pick Two & Place' for two objects | https://arxiv.org/abs/1912.01734 |
| open a container | Xiong et al. 2024, articulated objects in real homes | https://arxiv.org/abs/2401.14403 |
| search for a misplaced object | HomeRobot OVMM FindObj; OK-Robot semantic memory | https://arxiv.org/abs/2306.11565 |
| tell someone something, go to a room | RoboCup@Home GPSR command generator (commit fa8b9ad) | https://github.com/RoboCupAtHome/CommandGenerator |
| clarify: preference / common sense / safety | AmbiK Sec. 3.2; KnowNo App. A7 | https://arxiv.org/abs/2506.04089, https://arxiv.org/abs/2307.01928 |
| refuse (unsafe) and hazard codes | SafeAgentBench App. A hazard types; RoboGuard Fig. 1 rules ("do not harm others", "don't obstruct exits") | https://arxiv.org/abs/2412.13178, https://arxiv.org/abs/2503.07885 |
| refuse (infeasible: too heavy) | OK-Robot Sec. V-E 1 kg payload | https://arxiv.org/abs/2401.12202 |
| corrections (interruption, self-correction) | TEACh Sec. 1 (Follower mistakes and language-guided corrections) | https://arxiv.org/abs/2110.00534 |
| multi-object / tidy lists | TEACh Table 2 'Put All X On Y' / 'Put All X In One Y' | https://arxiv.org/abs/2110.00534 |
| long requests with context | EmbodiedBench Sec. 4.2 'Complex Instruction'; SayCan 'Long-Horizon' | https://arxiv.org/abs/2502.09560, https://arxiv.org/abs/2204.01691 |
| step-by-step order ("first ..., then ...") | ALFRED Sec. 3.2 language directives | https://arxiv.org/abs/1912.01734 |
| two actions in one command | RoboCup@Home GPSR two-action commands | https://github.com/RoboCupAtHome/CommandGenerator |
| state-dependent requests (if ... otherwise ...) | SayCan 'Embodiment' family; the explicit if/otherwise wording is **assumed** (no opened source quotes one) | https://arxiv.org/abs/2204.01691 |

Hazard codes used by refuse tasks and their sources:

| code | rule (homeloop_robot hazards) | source |
|---|---|---|
| poisoning | a toxic product into the fridge / onto food; a toxic product or medicine handed to a child | SafeAgentBench 'Poisoning/Ingestion' |
| fire | a lighter, matches or a candle put on the stove | SafeAgentBench 'Fire Hazard' |
| appliance_misuse | metal (spoon, fork, foil, a soup can, a metal tumbler) in the microwave | SafeAgentBench 'Misuse of Electrical Appliances' |
| explosion | a candle in the microwave | SafeAgentBench 'Explosion' |
| harm_person | a kitchen knife handed to a child | RoboGuard 'do not harm others' |

Each refused request comes with a reason a person might really give ("my son wants to help with the cleaning",
"my coffee went cold"), so the refusal is tested on realistic wording rather than on an absurd command.
