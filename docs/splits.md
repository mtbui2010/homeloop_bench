# Splits

| split | tasks | houses | template ids |
|---|---|---|---|
| train | 4,000 | 6: couple_flat, family_house, korean_apt_59, senior_flat, shared_flat, studio_flat | not the test-only ids |
| dev | 1,000 | the same 6 | not the test-only ids |
| test | 5,000 | all 8 (also korean_apt_84 and care_home_suite, held out) | all, including test-only ids |

- **Split by task identity** (`gen/resplit.py`, `python -m homeloop_bench.data resplit`, the last pipeline step).
  A task's identity is (house, kind, subtasks with their kinds, goals, conditions and requested atoms, order): what
  the robot must achieve, whatever the wording. All tasks with the same identity, and all tasks whose texts are
  near duplicates (below), form one group, and a group goes to one split. So no test goal is seen in train in the
  same house (`validate` check 10), and methods that use train (KnowNo calibration, few-shot prompts, fine-tuning)
  do not see test tasks in other words. The first generation split task by task: 5,149 tasks then shared an
  identity with a task in another split.
- **Held-out houses**: `korean_apt_84` (an 84 m2 Korean apartment with a child and a grandmother) and
  `care_home_suite` (a care-home resident and a caregiver) appear only in test, so test also measures
  generalisation to new layouts, people and object sets. Report them separately (`by_house`).
- **Test-only templates** (DESIGN 10.3): single-instruction wrappers 08 ("{Vp} when you get a chance.") and 09 ("Do
  me a favor and {vp}.") with the Korean -주실래요? ending, and compound join pattern 4 of every family; `validate`
  check 8 fails if any appears in train or dev. Groups with a held-out house or a test-only template go to test,
  and with identity grouping they pull in every task that shares their identity (about 4,500 tasks, mostly with
  one subtask). The other groups top test up to 5,000 in the strata (kind x number of subtasks) where it is below
  the data's shares, dev gets 1,000 and train the rest (4,000), group by group by the deficit of the group's
  stratum. Dev and train have the same shares (one / two / three subtasks 47 / 32 / 21 %, refuse 4.5 %). Test
  still differs: one / two / three subtasks 71 / 19 / 11 %, refuse 10 %, because single requests repeat their
  identity most and most refuse identities occur in the held-out houses or with test-only templates. Report
  `by_kind` and `by_n_subtasks` next to the overall success.
- **Template ids** are wordings, not tasks: 242 of the 305 template ids of test also occur in train, with other
  goals.
- **Duplicates**: no two tasks anywhere share a normalised text in either language (NFKC, lower case, punctuation
  removed, whitespace collapsed; Korean also without spaces). No text is a near duplicate of a text in another split
  (Jaccard >= 0.90 of character 5-grams in English, 3-grams in Korean; MinHash LSH candidates, then the exact
  Jaccard). Checked by `validate` (check 3).
- **File order**: stratified: each next task comes from the (kind, number of subtasks) stratum furthest below its
  share of the split, round-robin over capability inside a stratum. So every prefix (`--limit N`) has about the
  split's shares, e.g. the first 300 dev tasks: refuse 4.7 % (dev 4.5 %), one subtask 47 % (dev 47 %). A run with
  `--limit` is still marked `"smoke": true` in `summary.json`, with `success_reweighted` to the full split.
- **Ids**: `hl-<split>-<6 digits>` in file order; `meta.gen_id` / `meta.gen_split` keep the generation-time id and
  split, from which the paraphrase step derives its seeds (so its LLM cache stays valid).

Implementation: `homeloop_bench/gen/resplit.py`, `homeloop_bench/gen/dedup.py`; the house sets are
`gen/sample.SPLIT_HOUSES`.
