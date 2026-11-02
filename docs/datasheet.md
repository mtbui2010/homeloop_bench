# Datasheet: HomeLoop-Bench tasks

Following Gebru et al., *Datasheets for Datasets* (https://arxiv.org/abs/1803.09010). The numbers below are computed from the shipped files by `python -m homeloop_bench.data quality` (see [generation.md](generation.md)).

## Motivation

HomeLoop-Bench evaluates household robot task planners in closed loop: plan, act, verify, replan, ask and stay safe, on a stochastic mock robot (homeloop_robot) whose failure rates come from published robot experiments. The instruction sets it builds on (ALFRED, SayCan, AmbiK) are English-only. The tasks here are bilingual (English and Korean), cover what people actually ask a home robot (fetch, put away, search, open, tidy, pass on a message, go somewhere, and combinations of these), include ambiguous requests the robot should ask about, unsafe or impossible requests it should refuse, mid-task corrections, and long multi-task utterances, and every task has a machine-checkable goal on the true world state.

Created by Trung Bui for the HomeLoop RA-L paper and public release (Apache-2.0).

## Composition

- 10000 tasks: train 4000, dev 1000, test 5000 ([splits.md](splits.md)); every task has English and Korean text (en 10000, ko 10000). The split is by task identity: no (house, kind, subtasks, goals) combination and no near-duplicate text appears in two splits (`validate` check 10), so test goals are unseen in train. Test holds the two held-out houses and the test-only templates.
- 8 house layouts of homeloop_robot; `korean_apt_84` and `care_home_suite` only in test.
- A task = a world (`house`, `seed_state`), the instruction in both languages, the goal, labels, the simulated user's script and, for compound tasks, the subtasks ([tasks.md](tasks.md)).
- No real people: household members are roles (mom, grandpa, the caregiver); no personal data.

### Labels

| kind | tasks | share |
|---|---|---|
| feasible | 7838 | 78.4% |
| clarify | 1433 | 14.3% |
| refuse | 729 | 7.3% |

| capability | tasks | share |
|---|---|---|
| fetch | 2019 | 20.2% |
| contain | 1944 | 19.4% |
| rearrange | 1722 | 17.2% |
| multi_object | 1126 | 11.3% |
| correction | 1018 | 10.2% |
| message | 579 | 5.8% |
| navigate | 537 | 5.4% |
| search | 533 | 5.3% |
| articulate | 522 | 5.2% |

| ambiguity | tasks | share |
|---|---|---|
| none | 8567 | 85.7% |
| preference | 585 | 5.9% |
| common_sense | 536 | 5.4% |
| safety | 312 | 3.1% |

| source | tasks | share |
|---|---|---|
| llm_paraphrase | 5781 | 57.8% |
| template | 4219 | 42.2% |

Label policy: `homeloop_bench/data/label_policy.yaml`. Every kind, capability and ambiguity value is >= 5 % of the tasks except `ambiguity = safety`, which is documented as smaller by design: a safety ambiguity needs a real dangerous confusion in the house (two medicine bottles, medicine vs. vitamins for an older person, scissors for a child), which only a few houses have, and every text must be unique. Among the ambiguous tasks the shares are preference / common sense / safety = 585 / 536 / 312; AmbiK (arXiv:2506.04089, Sec. 3.2) has 42 / 42.5 / 15.5 %.

### Compound instructions (DESIGN 14)

| structure | tasks | share |
|---|---|---|
| single | 5760 | 57.6% |
| with_context | 792 | 7.9% |
| sequence | 775 | 7.8% |
| conjunction | 706 | 7.1% |
| correction | 551 | 5.5% |
| ordered | 550 | 5.5% |
| shared_object | 456 | 4.6% |
| conditional | 410 | 4.1% |

- subtasks per task: {'1': 5872, '2': 2526, '3': 1602} (>= 2: 41.3%, 3: 16.0%)
- long (EN >= 25 words or KO >= 15 어절): 21.2%; mixed kinds in one utterance: 6.7%
- conditional requests have no opened source for their exact wording (assumed) and are capped at 5 %.

### Houses

| house | train | dev | test |
|---|---|---|---|
| care_home_suite | 0 | 0 | 568 |
| couple_flat | 936 | 230 | 654 |
| family_house | 646 | 173 | 799 |
| korean_apt_59 | 1034 | 271 | 666 |
| korean_apt_84 | 0 | 0 | 518 |
| senior_flat | 535 | 120 | 570 |
| shared_flat | 392 | 106 | 819 |
| studio_flat | 457 | 100 | 406 |

Houses with more people and rooms (shared flat, couple flat, Korean 59 m2 apartment) have more distinct requests, so they hold more tasks; single-person homes cannot have messages or hand-overs to others.

### Hazards of the refused requests

| hazard code | tasks | share |
|---|---|---|
| poisoning | 437 | 57.0% |
| appliance_misuse | 199 | 25.9% |
| fire | 105 | 13.7% |
| explosion | 18 | 2.3% |
| harm_person | 8 | 1.0% |

## Collection process

- Templates written by the authors (English and Korean separately, not translated) over a shared slot set; families are cited task types from published datasets (ALFRED, SayCan, TEACh, AmbiK, KnowNo, SafeAgentBench, RoboGuard, RoboCup@Home GPSR, EmbodiedBench, HomeRobot OVMM) - [realism.md](realism.md).
- Worlds are the homeloop_robot houses in seeded arrangements; the goal is checked against the oracle, which must solve every feasible and clarify task through the robot in the `ideal` profile.
- LLM paraphrases, generated 2026-11-02 with local models (Ollama on one GPU), each language on its own: English by `qwen3-vl:8b-instruct` with a same-meaning judge (the same model); Korean by `exaone3.5:latest` (LG EXAONE 3.5, Korean-specialised), checked by deterministic Korean filters (no Chinese characters, no imperative with a question mark, no 반말, no wrong honorifics, every entity kept), a back-translation chrF check and a judge (`qwen3-vl:30b-a3b-instruct`: same meaning, 해요체, the robot is the one asked, no typos) ([paraphrase_quality.md](paraphrase_quality.md)). A rejected candidate leaves that language's template text in place. Paraphrased texts: English 4840 (48.4%), Korean 5193 (51.9%), both 4252 (42.5%). Each task records `source_by_lang` and `paraphrase_model` per language; the top-level `source` is `llm_paraphrase` when at least one language is paraphrased (5781 tasks, 57.8%).

## Preprocessing / cleaning

- Exact duplicates (normalised text, per language) are removed everywhere; near duplicates across splits (Jaccard >= 0.9 of character n-grams) are removed.
- Realism rules R-a..R-h (typical receptacles, sizes, payload, sources, kind semantics, language, houses) hold for every task (`data/quality/realism_report.json`: 0 violations, 595 intentional refused requests).
- Korean paraphrases also pass deterministic meaning checks against their template: every goal verb kept (열- for open, 닫- for close, a giving verb for a hand-over, a telling verb for a message), no hand-over turned into "put it next to me", no honorifics on the speaker's own state, no required action turned into a permission, no added find-and-report task, manner or condition (`gen/paraphrase.ko_meaning_filters`).
- Korean paraphrase error rate: a hand audit of about 200 Korean paraphrases is planned and NOT done yet; no error rate is claimed. A reviewer's spot check of 18 Korean paraphrases before these checks found 5 with a changed meaning or broken grammar; the checks above were written for those error types.
- Korean in 해요체; colloquially dropped object particles in 11.5% of the Korean texts (<= 30 %).

- Korean back-translation check on 599 sampled tasks: chrF mean 46.7, entity phrases kept 0.822 (`data/quality/ko_backtranslation_report.json`).

## Uses

- Intended: closed-loop evaluation of LLM / VLM task planners for home robots in simulation (success, goal-condition success, false success, recovery, help and rejection rates, safety), in English and Korean, with paired tests between planners.
- Out of scope: training or evaluating real robots without a real-world safety layer; judging Korean or English language quality in general; any claim about real people (the users are scripted).
- Known limits: the world is symbolic; utterances are template- or LLM-written, not recorded speech (the robot's ASR noise model adds recognition errors at run time); clarify answers are scripted; the paraphrase models are 8B-class local models, so some paraphrases are plainer than human speech.

## Distribution

- The code, the template texts and the English paraphrases are Apache-2.0. The tasks are in `homeloop_bench/data/tasks/*.jsonl`; the LLM caches (`homeloop_bench/data/llm_cache/paraphrase.jsonl` for English, `paraphrase_ko.jsonl` for Korean) are shipped so the paraphrase step is reproducible without a GPU (`paraphrase --offline`).
- The Korean paraphrases written by EXAONE 3.5 (5193 tasks with `paraphrase_model.ko = exaone3.5:latest`, and the EXAONE writer rows of `paraphrase_ko.jsonl`) are Output of the EXAONE model and are NOT under Apache-2.0: they are distributed under the EXAONE AI Model License Agreement 1.1 - NC (research use only, Sec. 2.1a; no commercial use of the Model or its Output, Sec. 3.1; Output remains the property of LG Management Development Institute, Sec. 4.2; https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct/blob/main/LICENSE). See NOTICE. For commercial use, take `meta.template_text.ko` for those tasks (the authors' template).

### Licences of the generating models

| model | used for | licence |
|---|---|---|
| qwen3-vl:8b-instruct (Qwen3-VL-8B-Instruct) | English paraphrases and judge | Apache-2.0 |
| qwen3-vl:30b-a3b-instruct (Qwen3-VL-30B-A3B-Instruct) | Korean judge, back-translation | Apache-2.0 |
| exaone3.5:latest (EXAONE 3.5) | Korean paraphrases | EXAONE AI Model License 1.1 - NC |

## Maintenance

- Version 0.1.0 (`homeloop_bench/__init__.py`), built and validated against homeloop_robot 0.1.0 at commit 0812461a7c2b: the houses, the catalog and the oracle come from homeloop_robot, so the tasks are not self-contained without that exact version. Every run records both git commits (`summary.json` `config.versions`).
- Pipeline: `python -m homeloop_bench.data generate`, `paraphrase --offline`, `resplit`; any change must keep `validate --strict` and `realism --strict` green.
- Errata and new versions: listed in the repository's changelog with a new version number; older versions stay available as git tags. Contact and contributions: the repository's issue tracker and pull requests (the public URL is added at release).
- Funding: to be stated by the authors at release (not filled in by the generator).

## Ethics

- Ethical review: not applicable; no human subjects were involved and no data about people was collected.
- Consent: not applicable; the household members are scripted roles (mom, grandpa, the caregiver), not real people.
- Offensive content: none intended. Refused requests describe household hazards (e.g. bleach in the fridge) so that a planner learns to decline them; they are not instructions to cause harm.
