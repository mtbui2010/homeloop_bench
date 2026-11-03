# Experiments (round 2)

The results table, the per-mode / kind / subtask splits and the failure analysis of R2-4 go here when the runs
are done (`results/exp_r2/<planner>__<model-or-none>__<lang>/`). This page already holds what must be read
next to them. No result below is a planner score.

## Runs after the early-analysis fixes (R2-5)

A mid-run probe found harness bugs that biased robot_agent:sage (B1 person moves / places, B2 the person id
`user`, B3 ASR repair questions) and a progprompt_like prompt without ProgPrompt's example programs (B4), plus
Korean paraphrases with an object as the container (B5). The fixes are in homeloop_robot 1cb5d9d, 8f43038 and in
this repository (tests: `tests/test_reach_ra_bind.py`, `tests/test_progprompt_examples.py`, homeloop_robot
`tests/test_dialog_repair.py`). The sage runs that predate them were stopped and deleted; oracle / naive (full
dev), sage and progprompt_like (300) and live_smoke are rerun after them.

Ablation: the finished **zero-shot** progprompt_like runs (no example programs, before B4) are kept in
`results/exp_r2/ablation/progprompt_like_zeroshot__qwen3-vl:8b-instruct__{en,ko}/` (300 dev tasks, profile real,
seed 0). They predate B3 and B5 as well, so compare them with the with-examples runs only as "zero-shot vs three
examples" under that caveat.

## Delivery labels per split

Delivery atoms of the task goals after review round 1 (`data/quality/delivery_report.json`, `by_split`):

| split | atoms | reach | hand:explicit | hand:no_surface | hand:user_needs | hand share |
|---|---|---|---|---|---|---|
| train | 2263 | 1458 | 184 (8.1 %) | 509 | 112 (4.9 %) | 0.356 |
| dev | 490 | 337 | 39 (8.0 %) | 92 | 22 (4.5 %) | 0.312 |
| test | 2418 | 1478 | 192 (7.9 %) | 429 | 319 (13.2 %) | 0.389 |

- Explicit-hand wording is topped up per split (`gen/delivery.QUOTA_SHARE`, [tasks.md](tasks.md#delivery)),
  so explicit is about 8 % everywhere. Before round 1, dev had 6 explicit atoms (2 of them caused by "my hands
  are full") and no `user_needs`.
- `user_needs` on dev / train comes from one person (grandpa, korean_apt_59); on test also from the care-home
  resident (a test-only house). Dev n for `hand:explicit` (39) and `hand:user_needs` (22) is small: report
  their success with the clustered interval and do not compare planners on them alone.

## Mode appropriateness

A handover satisfies a `reach` atom, so success does not reward choosing `reach`. Report
`delivery_mode.unneeded_handover_rate` next to `by_delivery.reach.success` ([metrics.md](metrics.md#delivery-mode)).

## Planner information for deliveries

The planners do not get the same help for "bring it near the person":

- every planner observes `people_now` (posture, place, the furniture within 2 m with type, height, distance and
  free slots) and no reach verdict or label;
- robot_agent:sage additionally has the robot package's name translation of a person used as a place:
  `person_spot`, the nearest support surface with a free slot within 1.2 m of the person (Hall's personal zone;
  geometry only, not the judge's reach test, and never an automatic handover);
- in practice sage names the speaker as "me" and asks "Where are you?" instead, so the translation applies to
  about 0.1 % of the reach atoms (third-party deliveries) ([robot_agent.md](robot_agent.md)).

State this next to the sage vs progprompt_like comparison.

### Why sage's delivery successes are near 0 (read next to the R2-5 rerun numbers)

Measured after the R2-5 fixes (homeloop_robot 2b3c862, this repository 42c711c, robot_agent 895561b, no GPU):
`homeloop-bench run --planner robot_agent:sage --llm fake --split dev --limit 80 --profile ideal --seeds 1
--lang en`. `--llm fake` builds sage's understanding from the gold goals, so what fails here is sage's own
grounding and plan check, not the language model. Delivery success: `reach` 0 / 21, `hand` 0 / 8 (no-delivery
tasks 30 / 48). Of the 21 `reach` episodes:

- 15 asked "Where are you? Which place should I bring it to?" (assist_loop `_ground_goals`, the `_USER_WORDS`
  path for "me"), and the simulated user named their seat ("I'm at the sofa.", a realistic answer that the
  harness must not change). In 14 of them sage then grounded the goal as `on(X -> <seat>)` and its own verifier
  rejected the correct plan, for example "the pink towel must go to sofa@living, not side_table@living"
  (hl-dev-000007; also hl-dev-000006, 000010, 000011, 000015, 000021 -> bed, 000036, 000039 -> desk_chair, 000047,
  000051, 000059, 000061, 000069, 000070). The 15th (hl-dev-000046) stopped "still unclear after 3 questions";
- 3 grounded "me" to a seat without that question (hl-dev-000032 -> reading_chair, 000033 -> sofa, 000008 ->
  armchair), 2 to another surface than the one the plan used (hl-dev-000012, 000037), and 1 claimed "Task
  completed" (hl-dev-000048). Most of these also asked "You mentioned the me. What should I do there?" (answer:
  "I'm not sure what you mean.") and then read back "I will put X on the <seat>. Is that right?", which the
  simulated user confirmed (`dialog.compose_from_goal`, rule `goal_confirm`: the seat is where the person is);
- only 1 of the 21 reached a `place` call.

So `person_spot` (the name translation of a person used as a place, above) almost never takes effect for sage:
its speaker deliveries never name a person as the place. This is a property of sage's grounding (a seat is not a
surface in a `reach` delivery, docs/metrics.md), not a harness bug, and the scoring is not tuned for it. The
judge's reach rule does not leak into the adapter: `person_spot` uses only the support type, the room, free
slots and the 1.2 m radius, and can pick a surface the person cannot reach (homeloop_robot
`tests/test_reach.py::test_person_spot_may_be_out_of_reach_and_then_the_delivery_fails`).

## ASR sensitivity

The per-token ASR model of the app channel gives an assumed upper bound on the share of corrupted
instructions (homeloop_robot docs/calibration.md, "Near-field ASR": KO 77.1 %, EN 58.4 % changed on dev). Run
each LLM planner also with `--set asr.ko.app_cer=0.01,asr.en.app_wer=0.01` and `--set
asr.ko.app_cer=0.02,asr.en.app_wer=0.02` (same tasks and seed) and report success against the rate.

## Known SAGE-v2 gaps (for the user to decide; robot_agent and embodiplan are not changed)

Counted on the stopped zero-shot sage runs of R2-6 (exp_r2, profile real, seed 0, the first ~50 dev tasks per
language, qwen3-vl:8b-instruct; one cause per episode, read from the event traces: scratchpad analysis
`sage_rag/causes.tsv`, ids are hl-dev-000NNN). These runs predate the seed pool, so the RAG runs of round 2.7
must recount them.

| side | cause | EN | KO | episodes (EN / KO) |
|---|---|---|---|---|
| gate | plan explosion (duplicate steps across sub-goals) then the 30-call LLM budget | 9 | 5 | 006 008 021 023 026 032 033 047 048 / 005 019 043 044 046 |
| gate | one-hand ordering: Open / Close while holding; the sub-goal-local edit cannot move the Open before the Pick | 3 | 0 | 001 002 004 |
| gate | a person destination vs Handover (the checker wants Place on the person) | 1 | 0 | 017 |
| gate | a room as MoveTo target (`@kitchen`, `@living`) | 0 | 2 | 011 016 |
| understand / clarify | find_issues flags "me" / 나 / 저 or asks "Where are you?" again and again | 5 | 2 | 011 018 024 037 039 / 002 033 |
| understand / clarify | colloquial words or ASR fragments flagged as unknown objects | 4 | 0 | 005 015 029 043 |
| understand / clarify | a person named by relation (my husband, 남편, partner_a) not grounded | 3 | 3 | 013 030 044 / 007 013 030 |
| understand / clarify | a spurious go / say goal from understand | 1 | 0 | 046 |
| understand | KO -> EN entity confusion of the 8B model (과자 -> fruit, 수건 -> shoe, 김치냉장고 as an object) | 0 | 4 | 003 004 023 029 |
| understand | an object goal dropped (socks -> "go to the bed"), then a false success | 0 | 1 | 025 |
| understand | "here" grounded to the counter, then a false success | 1 | 0 | 012 |
| dialog (KO) | the question mistranslated or garbled ("Where are you?" -> "여기 있어요?") | 0 | 8 | 012 015 018 021 024 032 037 047 |
| dialog (KO) | the read-back mistranslated (person_user, raw ids, kana) | 0 | 5 | 006 008 010 036 048 |
| safety | missed refusal (bleach / detergent into a fridge) | 1 | 2 | 009 / 009 035 |
| safety | wrong refusal (ASR "nut the milk" read as pour) | 1 | 0 | 003 |
| ambiguity | room-level or compound place names (서랍장 vs 서랍, my closet, the owner's place) | 2 | 3 | 020 042 / 020 031 042 |
| ambiguity | compound container name and on / in (kimchi fridge vs fridge) | 1 | 0 | 041 |
| retrieval | Korean instructions retrieve no similar example: embodiplan's Jaccard keeps only `[a-z0-9]` tokens, so every Korean query scores 0 and gets the first 3 seed examples (measured with `homeloop-bench prompt`, hl-dev-000003 / 000017 KO) | - | all | - |
| retrieval | example plans are shown as ASCII-escaped JSON, so a Korean `Say` text reaches the prompt as `\uXXXX` | - | - | - |
| message format | the give-up "could not find X (looked at ...)" joins the searched ENV keys verbatim (assist_loop.py ~2036 / 2044), and the gate's give-up quotes plan steps with keys ('Close fridge@kitchen'); every other message humanizes them (`replace('@', ' in the ')`). Raw place ids reach the user (KO: '김치_냉장고@주방'). Counted per episode as `final_say_raw_ids` (pilot rounds, below) | - | - | - |
| message language | a give-up after the LLM budget ran out is said in English: `_in_lang` translates with an LLM call, which the budget refuses, and falls back to the English text ("the planner produced no plan for the goals", "I could not make a plan that passes my checks: ..."; pilot rounds 1-2, KO 003). Counted in `final_say_not_in_lang` | - | - | - |

Not SAGE-v2 gaps: the harness bugs fixed in round 2.7, the Korean `Say` sent as English (R2-6 H1, KO 040) and the
simulated user's 냉장고-inside-김치냉장고 match (H2, KO 041); the calibrated skill / hardware faults (EN 6: 010 025
031 034 036 038; KO 2: 034 039); instructions not heard (EN / KO 014); objects not found (EN 1: 027; KO 5: 017 026
027 038 049); an ASR-corrupted entity (KO 000: 전자인지).

## Pilot rounds

R2-7e: 4 dev tasks, the same ids in every condition (robot_agent:sage and robot_agent:sage_norag x EN / KO,
qwen3-vl:8b-instruct on GPU 0, profile real, seed 0; oracle and naive on the same tasks for reference). Each
failure is traced from the prompts, the replies, the dialog and the calls, and classified as harness / simulator /
genuine. Harness and simulator bugs are fixed with a test before the next round; the pilot ids stay fixed.

### Round 1 (`results/pilot_r27/round1/`)

Tasks: hl-dev-000010 (delivery to the speaker), hl-dev-000013 (message to the husband), hl-dev-000003 (clarify,
kimchi fridge), hl-dev-000001 (articulate / compound).

| condition | success | false success | LLM calls / ep. | per task (010 / 013 / 003 / 001) |
|---|---|---|---|---|
| sage EN | 0 / 4 | 1 | 3.0 | give_up / done (false) / refuse / refuse |
| sage_norag EN | 0 / 4 | 1 | 3.0 | give_up / done (false) / refuse / refuse |
| sage KO | 1 / 4 | 1 | 14.0 | give_up / done (false) / give_up (30 LLM calls) / done |
| sage_norag KO | 1 / 4 | 1 | 17.5 | give_up / done (false) / give_up (30 LLM calls) / done |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / done / give_up / done |
| oracle EN, KO | 3 / 4 | 0 | 0 | give_up / done / done / done |

Not genuine (fixed; homeloop_robot 40104e3, e04071a, f19e07c; this repository 3c8da20, 3f1ff32):

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 010 | sage, sage_norag EN | harness | The speaker's ENV entry was keyed `person_user`; robot_agent reads plans back with the key ("... on the person_user. Is that right?"), so a raw id reached the user twice. | Person ENV keys are names: the speaker's entry is `spot near you`, others their name (`husband`); homeloop_robot `tests/test_person_keys.py`, `tests/test_pilot_r1.py` |
| 010 | sage, sage_norag EN (outcome-deciding) | simulator | For a delivery to the speaker the user accepted only "you" / "to me" / their place, never their own name ("on the user" -> "No, bring the green mug to me."), and a named source place ("from the counter") counted as another place. | The speaker may be named; the object's source place is not "another place" (homeloop_robot `tests/test_dialog_pilot_r1.py`) |
| 010 | KO, both (outcome-neutral here) | simulator | A structured confirm was answered from the English goal, not the Korean heard: "…주방에 놓겠습니다. 맞죠?" with the English "…on you" got "네, 맞아요"; "파트너B에게 …" with "…to husband" got yes. `slots_agree` lets a text that names fewer things pass. | A read-back is answered for the sentence heard when that sentence states something (path `structured_mismatch`); same test file |
| 010 | KO (outcome-neutral) | harness | The adapter's `where_put` slot ran across "?": obj = "? Where should I put the green mug". | Template slots are `[^?]+?` (same test file) |
| 013 | KO, both | harness | `said_to` keywords were plain substrings: `나가` is not in `나간다고`, so SAGE's "10분 있다가 나간다고 합니다." could never count; 273 / 689 KO and 101 / 689 EN dev+test message instructions failed their own goal key. | Korean verb-ending finals and the instructions' wordings; every canonical text matches only its key (homeloop_robot `tests/test_messages.py`; `tests/test_pilot_r1.py`: every dev / test message instruction matches its key, except hl-test-002020 / 002764, whose KO paraphrase lost the message: a data defect, listed) |
| 013 | EN, KO, both | harness | The raw id `partner_b` reached the user in the read-back ("… to partner_b. Is that right?", KO "파트너B에게"); the "Yes" was a p_wrong draw (reply_kind `wrong`), so the episode went on by luck. | Person keys are names (`husband`) |
| 003 | sage, sage_norag KO (accounting) | harness | The 30-call LLM budget ran out inside SAGE / AssistLoop, which catch `BudgetExceeded` and go on; the episode ended `give_up` ("the planner produced no plan"), so the budget-hit metric undercounted robot_agent planners. | `CountingLLM.refused`; episode field `llm_budget_hit`; a give-up after a refused call is status `budget`; summary `llm_budget_hit_rate` (`tests/test_pilot_r1.py`). The judge is unchanged: done / refuse keep their status |

The heard-read-back rule moved 9 Korean read-backs of the sim-user audit set from `structured` to
`structured_mismatch`; the qtype accuracy is unchanged (0.954; `data/quality/sim_user_audit.json` regenerated,
homeloop_robot docs/user_model.md). Round 2 reruns the same 4 tasks in all conditions.

### Round 2 (`results/pilot_r27/round2/`)

Same 4 tasks and conditions, after the round 1 fixes.

| condition | success | false success | LLM calls / ep. | per task (010 / 013 / 003 / 001) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 4.0 | give_up / done / refuse / refuse |
| sage_norag EN | 1 / 4 | 0 | 4.25 | give_up / done / refuse / refuse |
| sage KO | 1 / 4 | 0 | 15.75 | give_up / give_up / budget / done |
| sage_norag KO | 1 / 4 | 0 | 14.5 | give_up / give_up / budget / done |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / done / give_up / done |
| oracle EN, KO | 3 / 4 | 0 | 0 | give_up / done / done / done |

Not genuine (fixed; homeloop_robot 592ae2d, 787c256, 9ffb93e, ff7600c, ae27740; this repository 6605cd4):

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 013 | sage, sage_norag KO (outcome-deciding) | harness | The adapter copied the speaker's Korean aliases 나 / 저 into the ENV entry `spot near you`; robot_agent matches a non-ASCII place phrase as a plain substring, so the 나 inside 나간다고 was a place mention: "You mentioned the 나. What should I do there?", then read-backs "(the 나 you mentioned is not in my plan)" until "the user did not confirm the task" (give_up). 220 of 1000 dev KO instructions have 나 or 저 inside another word (하나, 나중에, 저녁). Round 1 had it too (cache [12] / [14]) and it was missed. | A one-syllable Korean person name goes into the ENV as its dative forms (나한테, 나에게, 내게, 저한테, 저에게, 제게; X한테 / X에게 for 애, 딸); homeloop_robot `tests/test_person_alias_forms.py` (robot_agent's own `place_mentions`) |
| 013 | sage, sage_norag KO (plausibly outcome-deciding) | simulator | The heard read-back '남편이 “10분 있다가 나간다고 말해 주세요”라고 말하는 거죠? 맞죠?' makes the husband the speaker, yet it was judged a correct confirmation: `said_to` was covered once the person was named. The norag wording ('…라고 말할 거예요, 맞죠?') matched the Korean did-you-mean pattern and got "yes + request" (repair_confirm). The p_wrong draw then gave '아니요' (sage) and not_sure (norag); with the correct content "no" the same draw would have said "yes". | A person named as the speaker (subject particle 이 / 가 / 께서, "X will say") does not cover `said_to`; a quoted message must carry the message's keywords (`message_matches`, the test a Say must pass); a read-back of a message is not a heard-word check (homeloop_robot `tests/test_dialog_pilot_r2.py`) |
| 010 | sage, sage_norag EN (outcome-neutral) | simulator | After a move to a person with no surface beside them (grandpa on a bed without a nightstand), Find returned unreachable "cannot reach green mug: not at a place", a hint that the object is out of reach, which a robot that looked around cannot know. robot_agent counts unreachable and absent alike in `find_fails`, so the ask and the give-up were the same. | Find at no place looks where the robot stands and reports absent (event `not_at_place`); docs/skills.md (homeloop_robot `tests/test_find_at_person.py`) |
| 010 | sage KO (outcome-neutral, the run had used its 2 read-backs) | simulator | The wrong answer to "hand it to you or put it nearby?" was a place drawn from every surface and container: "옷장 안에 넣어 주세요" for a mug wanted for tea. | A mistaken place is one where an object of the task is usually kept (catalog typical receptacle that fits it, realism R-b); docs/user_model.md item 5 (homeloop_robot `tests/test_user_wrong_place.py`) |
| seed pool | sage (outcome-neutral here: 013 never reached SAGE planning; EN 010 retrieved the son / come_kitchen seed) | harness | R2-7 review add-on 1 was still open: the message seeds had the dev / test goals said_to(son, come_kitchen) and said_to(son, leaving_soon) (leaving_soon is pilot task 013's goal), with null origin fields, so the leak test passed trivially. Normalised, four fetch seeds also had dev / test goals. | Seeds rewritten with goals no dev / test task has (two example-only messages, `catalog.EXAMPLE_MESSAGES`), origin "hand-written for example_flat"; `tests/test_seed_pool_leak.py` compares normalised goals, message atoms and Say texts (`message_matches`) |

The sim-user audit is unchanged by these fixes (`python -m homeloop_bench.sim_user_audit` from the committed cache
gives the same `sim_user_audit.json`). The seed pool sha changes, so sage's next runs record the new pool. Round 3
reruns the same 4 tasks in all conditions.

### Round 3 (`results/pilot_r27/round3/`)

Same 4 tasks and conditions, after the round 2 fixes.

| condition | success | false success | LLM calls / ep. | per task (010 / 013 / 003 / 001) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 4.0 | give_up / done / refuse / refuse |
| sage_norag EN | 1 / 4 | 0 | 4.25 | give_up / done / refuse / refuse |
| sage KO | 2 / 4 | 0 | 15.5 | give_up / done / give_up / done |
| sage_norag KO | 2 / 4 | 0 | 12.0 | give_up / done / budget / done |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / done / give_up / done |
| oracle EN, KO | 3 / 4 | 0 | 0 | give_up / done / done / done |

Not genuine (fixed; homeloop_robot 0c0f73a, df2795f, 7b2fb70):

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 003 | sage, sage_norag KO (outcome-deciding) | simulator | SAGE's "I am not sure I understood (the 김치냉장고 you mentioned is not in my plan). I will put the 우유 on the fridge in the kitchen. Is that right?" was translated as '김치냉장고 얘기가 제 계획에 없나요? 제가 우유를 주방 냉장고에 두겠습니다. 맞죠?'. The heard-text check read only the first question (`intent.first_question`, convention 2); `CONTEXT_RX` knows "…얘기하셨죠?" but not the remark turned into a question, so the answered text named only the kimchi fridge and the rules said yes (`yes_no_intended`), overriding the structured "no" (path `structured_mismatch`, reply '네, 맞아.'). The goal became fridge@kitchen; sage then rejected its own kimchi-fridge plan and gave up, sage_norag placed on the closed kimchi fridge (blocked) and hit the 30-call budget. A user who hears '…주방 냉장고에 두겠습니다. 맞죠?' corrects it. The same rule also said "no" to a right read-back behind such a remark. | A question sentence that is the robot's plan remark (`dialog.REMARK_RX`, the remark `strip_plan_remarks` already drops) is context when another question follows it; the read-back after it is answered (homeloop_robot `tests/test_dialog_pilot_r3.py`, structured and free text, wrong and right read-backs; docs/user_model.md convention 1) |
| 013 | sage, sage_norag KO (passes counted by a lax check) | harness | SAGE said the user's whole ASR-corrupted request to the husband: '남편한테 갈서 10분 있다가 나간다고 맬해 주세요.' ("go to the husband and tell him we leave in 10 minutes, please"). `said_to` checked only the message keywords (`catalog.message_matches`), so the request relayed word for word counted as the message (gc 1.0, done). EN said "We are leaving in ten minutes." | `said_to` does not count an utterance that names the listener as the one to be told (`dialog.speech_role` = listener) and asks or announces the telling (a tell verb; in Korean a quoted clause "…다고 / 라고" with a verb after it): `goals.relayed_request`. A message that only names its listener ("남편한테 전화 왔어요.") still counts (homeloop_robot `tests/test_said_to_relay.py`; docs/world.md, Goals). R2-1: scoring stays strict. **For the user to decide:** the husband could still work out the content; if a word-for-word relay should count, revert df2795f. |

Effect of the `said_to` rule on the stored runs (re-scored offline from the recorded Say calls, no rerun): besides
the two round 3 sage KO passes of 013, it changes one stored episode, hl-dev-000040 in the zero-shot
progprompt_like KO ablation ('아빠한테 가서 점심 준비됐다고 말해 줘요.', counted a success). The other matches
(progprompt_like KO hl-dev-000087, 000135, 000208, 000293) failed already. No oracle, naive or exp_r2 progprompt_like
success changes. The sim-user audit is unchanged (`python -m homeloop_bench.sim_user_audit` gives the same
`sim_user_audit.json`). The other draws in 003 (not_heard, not_sure, wrong, no_answer) are sourced profile noise, not
bugs. Round 4 reruns the same 4 tasks in all conditions; with these two fixes the round 3 KO passes of 013 are
expected to become failures (a genuine SAGE-v2 / 8B relay weakness), and 003 KO is decided by the read-back answer.

### Round 4 (`results/pilot_r27/round4/`)

Same 4 tasks and conditions, after the round 3 fixes.

| condition | success | false success | LLM calls / ep. | per task (010 / 013 / 003 / 001) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 4.0 | give_up / done / refuse / refuse |
| sage_norag EN | 1 / 4 | 0 | 4.25 | give_up / done / refuse / refuse |
| sage KO | 1 / 4 | 1 | 12.5 | give_up / done (false) / give_up / done |
| sage_norag KO | 1 / 4 | 1 | 8.5 | give_up / done (false) / give_up / done |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / done / give_up / done |
| oracle EN, KO | 3 / 4 | 0 | 0 | give_up / done / done / done |

Not genuine (fixed or reported; homeloop_robot 4a6ec64; this repository
104202c). Both are outcome-neutral: the judge reads `final_say` only through
`refusal_texts` of a refuse.

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 013, 001 (003 in round 3) | sage, sage_norag KO, rounds 1-4 | harness | robot_agent's Announcer takes the milestone phrases from the robot's i18n and falls back to its core table (English and Vietnamese only; announcer.py ~133-149). The adapter's `PHRASES` had only cannot_do / done / which_one, so a Korean user heard "Task completed" / "Task failed" at the end. A deployed robot pack ships them in Korean. `dialog_not_in_lang` counted only questions, so the gate missed it. | The adapter's i18n has every milestone and the verbs of the robot's actions in Korean (plain polite Korean); English is unchanged (homeloop_robot `tests/test_announcer_ko.py`). The episode's last message is checked for the user's language: `final_say_not_in_lang`, included in `dialog_not_in_lang` (`tests/test_final_say_check.py`, also a KO message task through the real AssistLoop, which now ends '작업을 완료했습니다') |
| 010 (003 KO in round 3) | sage, sage_norag EN | harness, reported | robot_agent's give-up joins the searched ENV keys verbatim: "could not find the green mug (looked at counter@kitchen, spot near you, grandpa, sofa@living, coffee_table@living)" (assist_loop.py ~2036 / 2044); translated, '김치_냉장고@주방'. Round 1 made the person keys names; the place keys stay `head@room`, because robot_agent derives the room and the head noun from the key (`split('@')`, `in_room`, the `@room` targets of its gate), so readable place keys would change its grounding, not only the message. | Not changed in the ENV (the place keys are part of robot_agent's grounding contract); listed under "Known SAGE-v2 gaps" (message format), and every episode lists the raw ids of its last message, `final_say_raw_ids`, with the summary count (`tests/test_final_say_check.py`) |

Recount of the stored rounds with the two new fields (offline, no rerun). Last message not in the user's language:
sage / sage_norag KO "Task completed" on 001 in every round and on 013 in rounds 1, 3 and 4, "Task failed" (sage_norag KO 003, round 3), and
two English give-ups after the LLM budget ran out (KO 003 rounds 1-2, a SAGE-v2 gap above). The baselines' last
messages are status strings that are not spoken to the user and not translated: naive / oracle KO 010 "hardware
fault: base motor", naive KO 003 "cannot reach the handle of kimchi_fridge@kitchen"; they count in the new fields
too (KO episodes of naive / oracle will show `final_say_not_in_lang` > 0; no success changes). Raw ids in the last
message: sage / sage_norag EN 010 in rounds 2-4 (the give-up above), the gate's give-up on 003 (KO, rounds 1-3),
naive 003 (EN, KO). Round 5 reruns the same 4 tasks in all conditions.
