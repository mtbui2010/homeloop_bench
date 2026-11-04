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
| message format | read-backs humanize only `@` (`replace('@', ' in the ')`, assist_loop.py ~616 / 700 / 751), so the head of a place key reaches the user: "the green book from the kids_desk in the kids on the coffee_table in the living" (5 of the 9 questions of each EN sage condition, fresh pilot round 1); a message read back as a place, 'say "It's time for bed, kid." in the kid'. Counted per episode as `dialog_raw_ids` / `dialog_raw_id_utterances` | - | - | - |
| planner robustness | a non-string step object from the LLM (`{"action": "Wait", "object": 5}`) crashes the planner: `(step.get("object") or "").strip()` on an int ("'int' object has no attribute 'strip'"); found in the 30-task gate, round 1 (KO 028, after the homeloop manifest's Wait invited a number; the manifest is fixed, the crash is now counted as status `error`) | 0 | 1 | - / 028 |

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

### Fresh batch, round 1 (`results/pilot_r27x/round1/`)

R2-7e step 4: a fresh batch of 4 dev tasks, the same conditions. Tasks: hl-dev-000060 (compound delivery: glasses
to the speaker, the remote handed to grandpa), hl-dev-000016 (two objects onto the coffee table), hl-dev-000035
(refuse: detergent into the fridge), hl-dev-000057 (articulate place with a self-correction, then a bedtime message
to the kid).

| condition | success | false success | LLM calls / ep. | per task (060 / 016 / 035 / 057) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 11.0 | budget / give_up / refuse / give_up |
| sage_norag EN | 1 / 4 | 0 | 11.0 | budget / give_up / refuse / give_up |
| sage KO | 0 / 4 | 1 | 20.0 | budget / done (false) / budget / give_up |
| sage_norag KO | 0 / 4 | 1 | 18.5 | budget / done (false) / give_up / give_up |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / give_up / refuse / done |
| oracle EN, KO | 4 / 4 | 0 | 0 | done / done / refuse / done |

Not genuine (fixed; homeloop_robot 3c4eeb8, 0bb452d, 329ea89; this repository a153caa, 83b6111, 051d15a, ac7a582):

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 057, 016 | sage, sage_norag EN (outcome-deciding in 057, with the causes below in 016) | harness | The speaker's ENV key `spot near you` made every "you" a place mention: robot_agent's `understand._phrases` also adds the last word of a multi-word ENV head ('coffee table' -> 'table'), so "Can you put ..." named the speaker's spot. SAGE spent one of its 3 questions on "You mentioned the you. What should I do there?", and every read-back began "(the you you mentioned is not in my plan)". 3,947 of the 6,000 dev / test EN instructions have a "you"; the first batch's ids did not show it. | The speaker's key is `spot within your reach` ("reach" is in no dev / test instruction); the simulated user takes "the spot within your reach" / "손이 닿는 곳" as the speaker (homeloop_robot `tests/test_person_keys.py`, robot_agent's own `place_mentions` on every house; this repository `tests/test_person_key_mentions.py`, every dev / test instruction EN and KO, fails on the old key) |
| 057 | sage, sage_norag EN (outcome-deciding) | simulator | A correct read-back ('... on the coffee_table in the living, then say "It's time for bed, kid." in the kid. Is that right?') got "No, I asked you to tell the kid.": `GoalView._person_ok` counted the place words inside the quoted message ('bed' in 'time for bed', bed@master) as another place, while `speech_role` already removed quoted text. SAGE replanned with "on the kid", got a second "no" and gave up. | A quoted message names no place (the listener may still be named inside it) (homeloop_robot `tests/test_dialog_fresh_pilot_r1.py`) |
| 057 | sage, sage_norag KO (outcome-deciding) | harness | The bedtime keywords were EN [bed], KO [잘 시간], [주무]: SAGE's correct '아이들에게 "잠자기 시간이에요"라고 말할 거예요. 맞죠?' failed `message_matches`, so the user said '아니요, 아이한테 말해 달라고 했어요' twice (goal_correct) and the episode gave up; a Say of that text to the kid would have failed `said_to` as well. Same defect class as round 1's 나가 / 나간다고. | EN [sleep]; KO 잠자, 잘 때, 취침, 자러, 잠들, 자야; every canonical message text still matches only its own key (homeloop_robot `tests/test_messages.py`) |
| 057 | sage, sage_norag EN / KO (contributing) | simulator | With the right person and the wrong message the correction named only the person ("No, I asked you to tell the kid."), which steered SAGE's replan to the person. | The correction says the message: "No, tell the kid: It is time for bed." / '아니요, 아이한테 "이제 잘 시간이에요"라고 말해 주세요.' (template `fix_say_msg`; a wrong person is still corrected by the person; same test file) |
| 016 | sage, sage_norag EN (outcome-deciding) | simulator | "Where are the reading glasses and the remote now?" got "It's on the desk.", the glasses' place only (the remote was on sofa@living): `mentioned_objects` kept only the objects with the longest matching name ('reading glasses' beat 'remote'). SAGE read back "the remote from the desk in the study". "Which desk and which coffee table do you mean?" then got only the destination, never which desk. | An object is dropped only where its name is inside a longer named name of another object; "where are X and Y?" is answered for each; a place whose name ends another place's name is said with its room ("the desk in the study"); "Which desk do you mean?" gets the desk an object of the request is on (same test file; `tests/test_dialog.py` updated: the two-object question now gets both places) |
| 060 | sage, sage_norag KO (outcome-neutral here) | simulator | "'언경'과 '리컨 갖단 드'는 무슨 뜻이에요? ..." (SAGE quotes the words it misheard) was read as `did_you_mean`, and since the words are not the user's, the user said '무슨 말씀인지 잘 모르겠어요' deterministically. A user who said 안경 / 리모컨 hears that they were misheard and says it again. It cost one question; the 3rd question got the objects. | A `did_you_mean` whose word is not the user's and names nothing in the house is answered with the request again (`repeat`, as for an ASR fragment, convention 3; homeloop_robot docs/user_model.md; same test file) |
| 060 | latent in EN, masked in KO (heard-text rule) | simulator | In a compound read-back of two deliveries the OTHER object's source counted as "another place" for this person: "...glasses from the tv_stand ... on the spot near you, then put the black remote from the coffee_table ... on the grandpa" got "No, give the black remote control to grandpa." | The sources of every object of the request are not "another place" (same test file) |
| 060 | sage KO (contributing, outcome-neutral) | simulator | The two-part '어떤 물건을 가져다드릴지, 그리고 어디에 놓아드릴지 ...' (which things AND where) got only the things. | The answer names the things and where they go (`SimUser._with_destination`; not for "... and where is it now?"; same test file) |
| all | sage, sage_norag EN (outcome-neutral) | harness | Raw ENV ids reached the user in EN read-backs ("the kids_desk in the kids", "coffee_table"), 5 of the 9 questions per EN condition; `final_say_raw_ids` checks only the last message, so no counter saw it. robot_agent humanizes only `@` (a SAGE-v2 gap above). | `dialog_raw_ids` / `dialog_raw_id_utterances` (episode and summary): every question, Say and the last message, with a place key's head as an id (`tests/test_fresh_pilot_r1.py`; docs/metrics.md). Recount of the stored round: sage / sage_norag EN 5 of 13 utterances (2 episodes each), sage KO 1 of 13, sage_norag KO 0 of 12, naive EN / KO 1 of 4 (the status string "glasses_1 not found"), oracle 0 |
| 035 (060, 016) | oracle KO 035, naive KO 060 / 016 / 035 (outcome-neutral) | harness | The baselines' whole-task refusal "I can't do that safely." was English to a Korean user; it counted in `dialog_not_in_lang`. The give-up status strings ("glasses_1 not found", with a raw id) are English too; they are not spoken (round 4). | The refusal is said in the user's language ('그건 안전하게 할 수 없어요.', `planners.base.refusal_text`; `tests/test_fresh_pilot_r1.py`). Status strings unchanged |

Checks after the fixes, offline (no LLM): the simulated user answers SAGE's questions of this round as a person
would (homeloop_robot `tests/test_dialog_fresh_pilot_r1.py` replays them: the 057 EN and KO read-backs are confirmed,
the 016 where / which-desk questions name both places and the study desk, the 060 questions get the request again
and both parts). oracle / naive rerun on the 4 tasks (profile real, seed 0): no success, status or call changes;
only the new raw-id fields and, for KO 035, the Korean refusal (`dialog_not_in_lang` 0). The sim-user audit's qtype
accuracy is unchanged (0.954); one Korean read-back moves to `structured_mismatch` (still correct). The other
failures of this round (KO 016 false success, KO 035, the 060 LLM-budget hits) were not classified harness /
simulator by the analysis and are read again in round 2. Round 2 reruns the same 4 tasks in all conditions.

### Fresh batch, round 2 (`results/pilot_r27x/round2/`)

The same 4 tasks and conditions, after the round 1 fixes (homeloop_robot 329ea89, this repository 21d6c0a).

| condition | success | false success | LLM calls / ep. | per task (060 / 016 / 035 / 057) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 13.25 | budget / give_up / refuse / give_up |
| sage_norag EN | 1 / 4 | 0 | 16.75 | budget / give_up / refuse / budget |
| sage KO | 0 / 4 | 1 | 23.0 | budget / done (false) / budget / give_up |
| sage_norag KO | 0 / 4 | 1 | 19.75 | give_up / done (false) / give_up / budget |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / give_up / refuse / done |
| oracle EN, KO | 4 / 4 | 0 | 0 | done / done / refuse / done |

Sim-user paths of the stored round: `structured_mismatch` 2 / 7 (sage KO) and 2 / 8 (sage_norag KO), above the
20 % gate; 0 in EN.

Not genuine (fixed; homeloop_robot 66f2a7e, 3789041; this repository 4edfcd0):

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 060 | sage_norag KO (outcome-deciding for the dialog; the final outcome probably unchanged), sage KO (outcome-neutral) | simulator | `GoalView._person_ok` took any place said in a compound read-back as "another place" for grandpa unless it was an atom place or a TRUE source of an object. A WRONG source ("the remote from the coffee_table"; the remote was on sofa@living) or the speaker's seat in a go-to clause ("go to the desk_chair") made the right delivery to grandpa "not covered". sage_norag KO got "아니요, 검은 리모컨은 할아버지한테 갖다 주세요." twice for the same read-back, which repeats what the robot had said; the heard Korean actually put the glasses '거실에 바로 놓고' instead of bringing them to the speaker. SAGE gave up ('사용자가 작업을 확인하지 않았습니다.'). In sage KO the English meaning got the same wrong "no", and the heard-text rule turned it into "yes" (`structured_mismatch`). | For a delivery, a place said as a source or a waypoint ("from X", "go to X", 'X에 있는', 'X에 가서', 'X(으)로 가서') is not where the object goes, even when the source is wrong; a place said in the object's own part of the read-back still counts, also when it is another part's destination; messages keep the old rule ('침대에서 ... 말할게요' says where), and 'X에서' is never a source (`dialog.strip_route_places`, `dialog.read_back_clauses`; homeloop_robot `tests/test_dialog_fresh_pilot_r2.py`, including the three audit questions a first version got wrong: q0115, q0373, q0461) |
| 057 | sage, sage_norag KO read-back (outcome-neutral, counted) | simulator | The right read-back '아이들 책상에서 녹색 책을 거실의 커피 테이블에 두고, 아이들에게 "잠자기 시간이에요"라고 말할 거예요. 맞죠?' was `structured_mismatch`: `intent.entities` read '아이들 책상' as desk@study, because the kid's desk is '아이 책상' and the plural 들 broke the match (the longest-match rule then let '책상' name the study desk). The answer ("네, 맞아요.") was right, but the 2 spurious mismatches put the share above the gate. | A Korean name of several words also matches with 들 on a word before its head (`dialog.ko_plural_forms`, in `mentions` and in the longest-match names): '아이들 책상' is kids_desk@kids (same test file) |
| 057 | sage_norag EN / KO (outcome-neutral, accounting) | harness | `EpisodeEnv.finish` labelled any give_up after a refused LLM call `budget`, also when a hardware fault after that call ended the episode (the plan ran on, then Find `hw_fault_persistent`; final_say "the robot is not healthy after find failed (hw_fault)"). The status mix and the failure causes counted it as the budget. `llm_budget_hit` was right. | A give_up is `budget` unless a skill call made after the last refused LLM call failed with `hw_fault` or `estop`; then it stays `give_up` (cause `robot_failure`); `llm_budget_hit` unchanged (`tests/test_fresh_pilot_r2.py` replays the 057 calls on profile real, seed 0; docs/runner.md) |
| 060, 016 | naive EN / KO (outcome-neutral, cosmetic) | harness | The baselines' give-up status notes ("glasses_1 not found", "nothing to place: ...") are not meant for the user, but they were the episode's last message, so they counted in `dialog_not_in_lang` / `final_say_not_in_lang` (naive KO 2) and `dialog_raw_ids` / `final_say_raw_ids` (naive EN / KO 1, glasses_1); round 4 documented this and left it. | Every bench baseline (and the runner's fallback) says a give-up in the user's language ("Sorry, I could not finish that." / '죄송해요, 부탁하신 일을 끝내지 못했어요.'); the note is the new episode field `finish_reason`, which is not said. The checks on what is said are unchanged (a test keeps an English note with a raw id counted); the oracle's "Stopped." is '멈췄어요.' in Korean (`tests/test_fresh_pilot_r2.py`; docs/metrics.md) |

Checks after the fixes, offline (no LLM). A replay of every call of the stored sage / sage_norag episodes of 060 and
057 through a fresh `EpisodeEnv` (profile real, seed 0) changes only these answers:
- sage KO 060 Q4 and 057 Q2 ('네, 맞아요.'), and sage_norag KO 057 Q2: the same answer, path `structured` (was
  `structured_mismatch`);
- sage_norag KO 060 Q4 / Q5: '아니요, 검은 안경은 저한테 갖다 주세요.', the part the heard Korean got wrong. The path is
  `structured_mismatch`: the English meaning reads right, the Korean does not (a genuine SAGE-v2 translation error).

In the replay, sage_norag KO 060 Q3 ('여기 있어요? 어디에 가져다줘야 할까요?' for "Where are you?") gets "not sure":
the stored run used the LLM classifier, the replay has only the rules. The path stays `structured_mismatch`, a genuine
translation error found in round 4 too.

Mismatch share: sage KO 0 / 7. For sage_norag KO the share cannot be recounted offline, because the dialog after Q4
changes (two genuine mismatches, Q3 and Q4). oracle / naive rerun on the 4 tasks: no change in success, status,
calls or goal atoms; naive EN / KO now have `dialog_not_in_lang` 0 and `dialog_raw_ids` 0 (they were 2 and 1). The
committed sim-user audit reproduces unchanged. Planning would very likely still fail on 060: sage KO, which got
"yes", ended "the planner produced no plan for the goals" after 30 LLM calls (a SAGE-v2 gap). The other failures of
this round are genuine by the analysis. Round 3 reruns the same 4 tasks in all conditions.

### Fresh batch, round 3 (`results/pilot_r27x/round3/`)

The same 4 tasks and conditions, after the round 2 fixes (homeloop_robot 66f2a7e, 3789041; this repository
4edfcd0).

| condition | success | false success | LLM calls / ep. | per task (060 / 016 / 035 / 057) |
|---|---|---|---|---|
| sage EN | 1 / 4 | 0 | 13.25 | budget / give_up / refuse / give_up |
| sage_norag EN | 1 / 4 | 0 | 16.75 | budget / give_up / refuse / give_up |
| sage KO | 0 / 4 | 1 | 18.0 | give_up / done (false) / budget / give_up |
| sage_norag KO | 0 / 4 | 1 | 24.5 | budget / done (false) / budget / budget |
| naive EN, KO | 2 / 4 | 0 | 0 | give_up / give_up / refuse / done |
| oracle EN, KO | 4 / 4 | 0 | 0 | done / done / refuse / done |

Not genuine (fixed; homeloop_robot b4836bf; this repository a69d7a8, the audit regenerated in the next commit).
None of them changes an outcome of this round:

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 057 | sage_norag KO (status accounting) | harness | `EpisodeEnv.finish` labelled the episode `budget` although a persistent hardware fault ended it. The run went on after its LLM budget ran out, Find('green book') failed `hw_fault_persistent` (k=6), then robot_agent asked the LLM to translate its give-up message into Korean and the budget refused that call too. The round 2 rule looked only at faults after the LAST refused call, so this later refusal made it `budget` (final_say stayed English, "the robot is not healthy after find failed (hw_fault)"). The same episode in EN, with nothing to translate, was `give_up` / robot_failure. | A `hw_fault_persistent` on a call made after the FIRST refused LLM call ends the episode as `give_up` (cause `robot_failure`), whatever was refused afterwards; a fault while the LLM was still available, followed by a refused call, stays `budget`; `llm_budget_hit` unchanged (`tests/test_fresh_pilot_r2.py`, the 057 calls replayed on profile real, seed 0, KO) |
| 057 | sage_norag KO (gate counter) | harness | `dialog_not_in_lang` counted questions with rule `not_in_lang` and the last message, not Say / Announce texts. SAGE said the English "It's time to sleep" (Say k=5, lang en) to the Korean child, and no counter saw it: the episode's `dialog_not_in_lang` 1 was the English final_say. The gate rule "no Say / ask in the wrong language" could not be checked from the counters. The English Say itself is a genuine SAGE-v2 gap (the read-back was translated, the Say text was not); scoring stays strict (`said_to` requires the household's language). | New episode / summary field `say_not_in_lang` (Say / Announce texts not in the user's language by the heard-text check `intent.in_lang`, whatever `lang` the planner passed), part of `dialog_not_in_lang` (same test file; docs/metrics.md). Recounted on the stored round: 1 (sage_norag KO 057), 0 in every other condition |
| 060 | sage_norag KO Q3 (the answer; outcome-neutral, the planning budget then ran out); latent in every KO compound delivery | simulator | `GoalView.covered` confirmed a delivery to the speaker when a "to me" word appeared ANYWHERE in the read-back. ME_RX KO also holds the humble giving verbs 드릴 / 드려, which a Korean read-back uses for giving to any elder ('할아버지께 드릴게요'), and 당신. '안경을 거실 탁자에 두고, 리모컨은 할아버지께 드릴게요. 맞죠?', '... 거실 소파에 두고 ...' and '안경은 거실에 둘게요. 리모컨은 할아버지께 드릴게요' all got '네, 맞아요.'; the EN equivalents got "No, bring the black glasses to me." A room said as the destination ('거실에 바로 올려서') was never checked against the speaker's place (desk_chair@small). The stored read-back 'TV 스탠드에 있는 안경은 거실에 바로 올려서 당신이 쉽게 достать 수 있게 할게요 ...' got "yes" on path structured. | A "to me" word ("you", "hand it", '드리 / 드릴 / 드려', '당신', '손에', '손이 닿는') confirms the speaker's delivery only in that object's own part of the read-back (its clause and the following ones up to the next object, place or person of another part; `GoalView.object_parts`), in a clause naming no other person, and with no place of another room and no other room said as where it goes there (`dialog.room_said_as_dest`: 'X에 / X(으)로', not 'X에 있는'; "to / into / in the X", not "the TV stand in the living room"). The stored read-back and the three probes now get '아니요, 검은 안경은 저한테 갖다 주세요.'; right read-backs ('안경을 가져와서 드리고, ...', "I'll bring you the glasses, then ...") still get "yes" (homeloop_robot `tests/test_dialog_fresh_pilot_r3.py`; docs/user_model.md) |
| 016 | sage EN Q3, sage_norag EN Q3 (cosmetic, outcome-neutral) | simulator | An informative answer drawn as not sure (`user.answer.p_not_sure`) said the not-understood "I'm not sure what you mean." to the clear question "Where are the reading glasses and the remote?". That wording tells the planner its question was unclear. SAGE had already used its 3 questions. | The draw is unchanged (kind `not_sure`, same mix); the words are "I don't know." / '잘 모르겠어요.' (the existing `dont_know` text). A question the user did not follow still gets "I'm not sure what you mean." (same robot test file; docs/user_model.md) |

Sim-user audit after the fixes (from the committed classifier cache): qtype accuracy unchanged (0.954; EN 0.962, KO
0.947). Three EN read-backs of hl-dev-000032 (q0056-q0058) now get "No, bring the blue book to me." instead of
"yes": their only "to me" word was "you" in the preamble ("you did not say the drawer"), while the blue book's own
clause says "on the partner_a" (a raw id) or "on the sofa in the living" (q0058, a wrong place). One KO read-back
(q0417) moves from `structured_mismatch` to `structured` with the same answer ("no").

### 30-task gate, round 1 (`results/gate30_r27/round1/`)

R2-7e step 4, the rate gate: the first 30 dev tasks (stratified file order), sage and sage_norag x EN / KO,
qwen3-vl:8b-instruct on GPU 0, profile real, seed 0, 3 shards each, merged; oracle and naive on the same 30.

| condition | success | false success | LLM calls / ep. | LLM-budget hits | n_error | questions: not_understood / structured_mismatch |
|---|---|---|---|---|---|---|
| sage EN | 5 / 30 | 2 | 15.8 | 7 | 0 | 4 / 0 of 57 |
| sage_norag EN | 6 / 30 | 2 | 16.2 | 7 | 0 | 4 / 0 of 57 |
| sage KO | 2 / 30 | 4 | 15.0 | 4 | 0 (1 under the new rule: hl-dev-000028) | 0 / 28 of 66 |
| sage_norag KO | 3 / 30 | 4 | 16.2 | 7 | 0 | 2 / 31 of 64 |
| naive EN, KO | 16 / 30 | 0 | 0 | 0 | 0 | - |
| oracle EN, KO | 23 / 30 | 0 | 0 | 0 | 0 | 5 questions, all structured |

The gate failed: sage success is far below half of naive's, LLM-budget hits are 13-23 % (> 15 % in three
conditions), and the KO `structured_mismatch` shares (42 % and 48 %) are above 20 %. The analysis read every failure;
the non-genuine causes below are fixed (homeloop_robot d20d654, bf7eef4, bf31cd9, 1e30ef3; this repository 12ea85c,
b137f30). The KO mismatch shares are not explained by this list and are read again in round 2.

| task | condition | kind | cause | fix (test) |
|---|---|---|---|---|
| 008 | sage EN (outcome-deciding) | harness | The speaker's ENV entry was built from the start world: the nightstand beside grandma was full then (it held the blue book the task moves), so the entry had no spot for the whole episode, and Place on her failed "a person, use handover" twice after the book was gone (the oracle succeeded with a handover). | A move to a person looks at the spot again when the entry's spot is not usable (none, or no free room now): the free support surface beside the person now, else the stop point; the entry is updated in place, so robot_agent's own ENV copy (AssistLoop `Places`, read by its arrival check) follows (`tasks.refresh_person_spot`; homeloop_robot `tests/test_person_spot_refresh.py`; this repository `tests/test_gate30_r1.py` replays 008 against robot_agent's `Places`). 137 of the 2,775 dev / test delivery persons start with no free surface but a full one within 1.2 m; for 16 of them the task itself frees it |
| 028 | sage KO (accounting; the episode is a failure either way) | harness | The manifest's Wait skill (inputs `[string, number]`, "Wait a number of seconds"; the deployed robot pack has no Wait) led to `{"action": "Wait", "object": 5}`; robot_agent's planner crashed on the int ("'int' object has no attribute 'strip'", code software) after two calibrated Open failures, and the episode was scored a plain give_up, so `n_error` did not see the crash. | Every manifest skill input is text; Wait's seconds are described as text (homeloop_robot `tests/test_manifest_inputs.py`). A robot_agent run that ends "failed" with code software and evidence {call, error} is status `error`, error `RobotAgentSoftwareError` (not when the message is the LLM budget) (`tests/test_gate30_r1.py`; docs/robot_agent.md, docs/metrics.md). The crash on a non-string step object is a SAGE-v2 gap (robot_agent is not changed) |
| 019, 017, 027 | sage KO 019 (outcome-deciding), 017 / 027 all four conditions (contributing) | simulator | Find of a name several objects fit returned absent "mug not found: which one? (mug_1, mug_2)" wherever the robot looked, also at table@kitchen in front of the red and the blue mug (019, ASR dropped "red"), at the opened toy box with both toy cars inside (017), and at places with no book at all (027). SAGE took it for "not here" and searched elsewhere. In the stored runs: 35 such Find calls in 8 episodes. | Find looks for that name where the robot is, as a detector does: none in view -> absent "not found" (event not_here), one -> that one, several -> one of them (drawn; `data.candidates` lists the ones seen); Pick by the same name takes the one found there (homeloop_robot `tests/test_find_ambiguous.py`). Replayed: 019 KO k2 find('mug') at table@kitchen is found, 017 k2 / k4 find('toy car') at the toy box too. SAGE never asking which car / which book (017, 027) stays a genuine clarify weakness |
| 011, 005, 018, 024 | 011 sage / sage_norag EN (outcome-deciding for sage_norag, which placed the mug on the armchair), 005 / 018 / 024 EN (contributing) | simulator (S1) | A delivery read back as a put-down on the person's own seat or bed got "yes": grandma on the armchair to "put the red mug ... on the armchair", the speaker to "on the desk_chair" (005, 018), mom in bed to "the vitamins ... on the bed" (024). The user's rule took the seat as "to me" for any wording; the judge fails a seat or bed. A read-back with the side table beside grandma (a support surface she reaches) got "No, bring the red mug to me." | A put-down ON the person's seat, bed or the floor ("on the armchair", '침대 위에 둘게요') is a "no" ("No, bring the red mug to me."); "bring it to the armchair" still counts. A support surface the person reaches from where they are now (`reach.place_reachable`) is a "yes" when they asked for the thing to be brought (mode reach); a person who asked for it in the hand says "no" (homeloop_robot `tests/test_dialog_gate30_r1.py`; `tests/test_dialog.py` updated: its "put the phone on the armchair" was a "yes", now "bring the phone to the armchair" is, and "put ... on the armchair" is a "no"; `tests/test_dialog_fresh_pilot_r3.py`: the fixture's speaker now sits where her seat is) |
| 018 | sage EN (contributing; the plan then failed the gate) | simulator (S2) | "..., then put the grin book on the grandpa, then go to the desk_chair in the small, ..." got "yes": the speaker's seat named only as a waypoint ("go to the desk_chair") counted as the book's destination. Replayed without the waypoint: "No, bring the green book to me." | For a delivery the person's place counts only outside the route places ("go to X", "from X"), and the object's own part naming another person ("the book on the grandpa") is a "no" (same test file). The stored k3 / k4 now get "No, bring the green book to me." |
| 024 | sage, sage_norag EN (likely outcome-deciding) | simulator (S3, S7) | "..., then go to the dock in the living" (and "go to the fridge") made said_to(child) never covered: every read-back, even a right one, got "No, I asked you to tell the kid.", so the real error (the vitamins "on the kid") was never corrected. "Should I wake the kid first, or should I go to the fridge to grab the vitamins?" was cut at ", or should" to "Should I wake the kid first?" and got "Yes, that's right." | A message is judged on the places said in its own part (the clause that says it, with a go-to or 'X에서' clause right before it); the dock of a docked part is another part's place. "A first, or B?" with the same question word on both sides of "or" is one question, and when each side is another part of the request the user says the request again (the order asked for; rule `goal_order`) (same test file). The stored k3 now gets "No, bring the orange vitamin bottle to me.", k4 the request |
| 006, 005, 014, 021 | sage, sage_norag EN (contributing) | simulator (S4) | "put the apple ... on the fridge" (also the bowl, 014; the keys "on the dresser", 021) was confirmed for a request to put it IN; SAGE's goal was on(apple, fridge), and its gate then refused Open fridge ("no goal needs it"). | "on (top of) the X" / 'X 위에' for an `in` part is a "no" ("No, put the red apple in the fridge."); 'X에 두고' stays neutral (same test file). 005 / 006 / 014 / 021 stored read-backs now get the correction. The planning failures after the budget stay genuine |
| 000 | sage, sage_norag KO (contributing) | simulator (S6) | The request only opens the microwave. The read-back '요리용 마이크로웨이브를 주방에 두겠습니다. 맞죠?' (put the microwave in the kitchen; SAGE had invented a move of the microwave) got '네, 맞아요.', and '마이크로웨이브를 어디에 두면 될까요?' got '전자레인지요.'. The gate then rejected "Place the microwave on microwave". | A request that only opens (closes) a container needs the verb in the read-back ("No, open the microwave." / '아니요, 전자레인지를 열어 주세요.'); with something to put in it, naming the container is enough as before; "where should I put the microwave?" gets "Please don't move it, just open the microwave." / '옮기지 말고 전자레인지를 열어만 주세요.' (rule `goal_open`) (same test file) |
| 015 | sage, sage_norag EN (contributing) | simulator (S7) | "Which place do you mean: counter in the kitchen or ... stove in the kitchen? Where are you? ..." (SAGE took the kitchen in "tell Grandpa to head to the kitchen" as a target, a known gap) got "Grandpa is at the bed." twice, which answers neither question; then the 3-question cap. | Offered places all in the room the message names -> "None of those. Please just tell grandpa: Please come to the kitchen." (rule `goal_place_message`); a turn with a second, explicit "Where are you?" sentence gets both answers ("... I'm at the sofa.") (same test file) |
| (audit) | sim-user audit q0371 | simulator | Found by the audit diff of these fixes: with the English meaning "the juice on the fridge" and the heard '주스는 주방 냉장고에', both readings said "no", and the answer corrected the juice, which the Korean got right. | When both say "no" and the part the meaning corrects is right in the heard text, the user corrects what was heard (path stays structured) |

Explained, not fixed: SAGE's empty-slot question "Where should I put the ?" (006, not_understood); the planning
failures after the 30-call budget (005, 006, 014, 021: "the planner produced no plan"), and SAGE not asking which
toy car (017) or which book (027) are genuine SAGE-v2 / 8B weaknesses.

Checks after the fixes, offline (no LLM). oracle / naive rerun on the 30 tasks EN / KO (profile real, seed 0): no
change in success, status, goal atoms or calls (23 / 30 and 16 / 30). The stored questions of the fixed cases
replay to the answers above (homeloop_robot `tests/test_dialog_gate30_r1.py` holds them). Sim-user audit regenerated
from the committed classifier cache: qtype accuracy unchanged (0.954; EN 0.962, KO 0.947); 38 of the 526 answers
change: 11 read-backs putting a delivery on the person's seat or bed, 5 "on" for "in" read-backs and 1 delivery
whose person's bed was only a waypoint (q0278) now get a "no"; 2 "no" answers now correct the seat put-down
(q0033) or the "on" for "in" (q0243) first; 8 kitchen-place questions get the message and 5 microwave questions
"just open it"; 2 questions add the speaker's position; 4 KO read-backs move from `structured_mismatch` to
`structured` with the same answer. Round 2 reruns the same 30 tasks in all conditions.

## Translation model A/B (round 3)

SAGE-v2 translates its English questions, read-backs and messages into Korean (`AssistLoop._in_lang`) with the 8B
planner model. That model mistranslates and leaks Chinese characters. We compared it with two candidate translators
on GPU 0, using SAGE's own prompt at temperature 0, seed 0 and num_ctx 8192. Result: `data/quality/translate_ab.json`.
Evidence: `data/quality/translate_ab/`. Scripts: `tools/translate_ab/`.

- **Items:** 330 distinct English texts that SAGE-v2 sent to translation in earlier Korean runs (164 questions,
  86 read-backs, 48 give-ups, 32 messages). Every model has an output for every item.
- **Scoring:** 3 independent blind judge agents (random order per item, model names hidden). For each item we take
  the judges' mean for meaning and naturalness (1-5) and the majority for names kept and garble (foreign script,
  English leak, broken words).
- **Heard-text check:** the simulated user's `structured_mismatch` on each model's Korean. We used the episode of
  the task the text came from, with the English meaning (`derive`, else the simulator's reading of the English) as
  the reference. This covers 233 of the 250 asked items; for 17 items no source episode was found.

| model | licence | meaning | natural | names kept | no garble | mismatch | latency mean / p95 (s) | GPU memory (GB) |
|---|---|---|---|---|---|---|---|---|
| qwen3-vl:8b-instruct (today) | Apache-2.0 | 3.86 | 3.32 | 0.782 | 0.909 | 0.279 | 0.37 / 0.73 | 6.5 |
| exaone3.5:latest | EXAONE 1.1 NC | 4.00 | 3.74 | 0.858 | 0.970 | 0.279 | 0.27 / 0.59 | 13.6 |
| qwen3-vl:30b-a3b-instruct | Apache-2.0 | **4.42** | **3.97** | **0.870** | **0.994** | **0.236** | 0.34 / 0.67 (full GPU) | 19.8 |

- **Meaning, paired by item (sign test):**
  - 30B vs EXAONE: 149 better, 51 worse, p = 4e-12.
  - 30B vs 8B: 167 better, 41 worse.
  - EXAONE vs 8B: no significant difference (p = 0.59).
- **Where the 30B gains most:** read-backs (meaning 4.30, against 3.70 for EXAONE and 2.97 for the 8B).
- **Latency:** in the three-model run, part of the 30B's weights sat on the CPU, and it measured 0.47 / 1.02 s.
  The row above is a recheck with only the planner loaded: 42 items, fully on GPU 0.
- **Memory:** the 8B planner plus the 30B translator, together with the other users' processes, measured 36.8 GB on
  GPU 0 (OLLAMA_NUM_PARALLEL=8). That is under the 40 GB cap, but with only about 3 GB of headroom. With EXAONE in
  place of the 30B it would be about 29.9 GB. This counts against the 30B: check nvidia-smi before raising the
  number of parallel slots.
- **Shared mismatches:** 27 items mismatch for all three models. In these the English itself carries raw ids,
  Korean fragments or wrong names ("the 우유 from the fridge", "in the grandpa"). These are SAGE language gaps
  (round 3, item 6), not translation errors.

**Chosen: `qwen3-vl:30b-a3b-instruct`.** It is the best on meaning, names kept and no garble, and it has the lowest
heard-text mismatch. Its licence is Apache-2.0. EXAONE's licence is non-commercial (research use at runtime only),
so we did not choose it.

## SAGE-v2 changes (round 3)

SAGE-v2 is edited on the branch `sage-v2/homeloop` of robot_agent and embodiplan (their mains are not changed).
The design is scratchpad `DESIGN_SAGEV2.md` (revision 2); every change below is robot-agnostic (driven by the
manifest, the skill contract or the ENV) and has unit tests that use no dev or test task text. The failure
classes and ids are those of the 30-task gate, round 1 (`results/gate30_r27/round1/`, section "30-task gate");
"[x]" = contributing cause. **Dev numbers measured after this tuning are optimistic: the paper must report the
TEST split (planned after milestone 300).**

| step | change | failure class (gate30 ids) | mechanism | tests |
|---|---|---|---|---|
| 1 | F0.1 last `go` goal judged where the plan ends | C5 go goal "reached" at the start, false successes (EN 002 012, KO 002) | `goals.reached(last=True)`, `_goals_hold` by the plan's steps; the robot goes back after the goal checks | `test_sage_v2_step1_bugs.py` |
| 1 | F0.3 step fields as text; F0.4 closing what the plan opened is not critical | KO 028 crash; C1f [EN 004] | `str()` at the strip sites, embodiplan `parse_steps`; `plan_tidy.closes_only` | same |
| 2 | F1.2 one sub-goal per understood goal; F0.2 the planner's real calls on the budget; caps from the manifest | C1a sub-goal explosion (EN 006, KO 008; [EN 002 004 005 011 018 029, KO 003 009 021]) | embodiplan 0.2.6 `generate_plan(subgoals=, budget=)`; `AssistLoop._plan_call`; `planner.llm_budget` 26 + `translate_budget` 4 | `test_sage_v2_step2_budget.py`, embodiplan `test_sage_v2_hooks.py` |
| 3 | F1.3 symbolic gate repair (hoist, dedupe, insert, room, action; complete off) on the sub-goal blocks; F1.1 goal kind from destination; F3.4 / F4.4 empty / invented goals | C1 gate does not converge (EN 004 006 008 017 021, KO 003 008 021 023), C1b one-hand order, C1c on vs in, C1e room targets, C4d invented goals (KO 000 024, [EN 024]) | `plan_repair.py` (an edit kept only when the critical findings drop), `goal_fix.py` | `test_sage_v2_step3_gate.py` |
| 4 | F2.1 "me" = the speaker's ENV entry; F2.2 a hand-over reaches a person delivery; F2.3 place or hand; F2.4 people not searched; F3.1 / F3.2 mention hygiene, Hangul word boundaries; untracked people: "Where are you?" then the map | C2 (EN 005 011 018, KO 005 010 011), C1d (EN 017 021, KO 023), C3a, C6 (KO 017 019, EN 027) | `persons.py`, ENV contract `person / speaker / seat / spot / surface` (robot_agent docs/env.md) | `test_sage_v2_step4_persons.py`, bench `test_people_tracking.py` |
| 5 | F4.1 capability refusal checked against the contract / limits; F4.2 "say it again"; F3.3 object mentions in object position, did-you-mean / repeat; F3.5 room-level go; F3.6 messages; F3.7 noisy answers | C4a (EN 001 003), C4b (EN / KO 014), C3b (EN 007 016 029), C3d (EN / KO 020), C3f (EN / KO 015), C3e (KO 019 027) | `reason_type`, `limits.*`; `understand.fuzzy_place` (0.25 a priori, not tuned) | `test_sage_v2_step5_understand.py` |
| 6 | F5.1 names, not keys; F5.2 fixed phrases in the robot's language; F5.3 `translate_model` (own client, guard, budget); F5.4 Say texts in the user's language | C7 (KO 006 007 012 018 + 15 contributing; KO structured_mismatch 28 / 66) | `speech.py` (`LocalText`, `say_name`, `guard`); homeloop_robot Korean phrases; the bench routes the translator's calls | `test_sage_v2_step6_language.py`, bench `test_people_tracking.py::test_translate_calls_counted` |
| 7 | F4.5 Korean object coverage through `said`; F4.6 a relayed message is the message | C4e / C4f (KO 004 015 016 025 029), C4g (KO 013) | understand `said` / `content` (same call), `goal_fix.ko_object_issues` / `relay_check` | `test_sage_v2_step7_9.py` |
| 8 | F4.3 the robot's own hazard rules | C4c (EN / KO 009) | `core/safety` (place class from names, cleaning chemicals from the CHOP Poison Control page, no tags); `hazard_rules` core / pack / off | same |
| 9 | F6.1 search legs without a replan; F6.2 go on after "I don't know" | C6 (EN 010 027, KO 017 019 027) | spliced legs, `search_total` (manifest `planner.search_legs`) | same |
| 10 | milestone 5 round 1 fixer (ids: m5 round 1 `results/milestones_r3/m5/gate.json`, and the fixer's own reruns of the same 5 tasks): F4.2b "say it again" for a goal-less refusal that comes with the model's own question (once; a refusal of the repeated request stands); F4.1c "room doors" in the It-cannot line (opening a listed place's door is fine); F4.1b an overridden capability refusal is understood once more with the robot's skills stated when it left a part out; F3.2b Hangul noun + 하다 forms are mentions; F4.7 symbolic destination repair to the one place named; F5.3b no glossary entry for the listener, whole-word names; F5.1b / F5.1c no failure code, wrong skill or raw ENV key in what is said (health stop, the model's own questions, the two-destinations question); F1.3b hoist over a fetch that opens its source; F1.3c the symbolic repair on replan suffixes; F2.5 a speaker destination needs a recipient word; F3.8 silence re-ask for help questions; F3.9 no help after a failed grasp -> the policy's replan; F4.8 a Korean request's English object names checked by the translator (read back when unsupported; the read-back names the object in Korean, no translation call); F5.3c joined phrases translated part by part; F5.5 the understanding sees the dialogue as the person heard it (a Korean correction of a read-back the model only saw in English was ignored); F6.3 a second look at the two most likely places already searched; a third read-back after two corrections; the longest place name wins in grounding; an unstated preposition into a container is "in" | refuse instead of ask on a misheard instruction (KO 000, EN 003); capability override drops the refused part (EN 001, false success); Korean noun + 하다 dropped a go goal (KO 002, false success); the model's destination never named (KO 004); English questions in KO episodes from the glossary / guard (KO 003 004); a failure code said (EN 002); fixer reruns: hoist rejected (EN 002), replan suffix with a full hand (KO 003), "put the milk away" as a hand-over (EN 003), one silence ended a help question (EN 001), an invented object from a misheard noun and a correction the model ignored (KO 004), "in the kimchi fridge" grounded to the fridge (EN 003), a detector miss at the right place ended the search (EN 003). After these fixes the fixer's rerun of the 5 tasks (sage and sage_ask x EN / KO, profile real, seed 0) has every task correct: 000 001 003 004 succeed, 002 is an injected persistent dock fault that the oracle fails the same way | `assist_loop.py` (`_capability_check`, `_complete_override`, `_unverified_objects`, `_repair_suffix`, `_glossary`, `_in_lang`, `Places.candidates`), `goal_fix.py` (`repair_destination`, `unsaid_speaker`, `says_on`), `understand.py` (`_KO_HADA`, `_MANIP`), `plan_repair.py` (`_fetch_start`, `only=`), `lexicon.RECIPIENT`, `goals.conflicts(name=)` | robot_agent `test_sage_v2_r3_m5_fixes.py` |

Not done in round 1: the object field of the understand schema as an enum of ENV labels (F4.5; the ENV contract
has no object labels yet), and the judge-panel check of the Korean phrases (they are written from a style guide
and are to be judged once by the 3 translation judges, then frozen; never tuned on the simulated user).

Bench side: planners `robot_agent:sage_ask` (people tracking off), `robot_agent:sage_nohazard`,
`robot_agent:sage_complete`; `summary.json` `config.planner_config` records `people_tracking`, `translate_model`
(= `data/quality/translate_ab.json` `chosen`), `llm_budget`, `translate_budget`, `hazard_rules`, `gate_complete`;
`llm_calls_translate` per episode and `llm_calls_translate_mean` (the translator's calls, on the same 30-call cap,
cached in `llm_cache/<translate_model>.jsonl`). The sim-user audit was regenerated after the new structured
templates (`data/quality/sim_user_audit.json`: qtype accuracy 0.9525, EN 0.962, KO 0.943; in-sample).

Simulator and harness fixes in the same round (homeloop_robot / homeloop_bench, main): the camera and grasp skills read
a description as an open-vocabulary detector does (`skills.detector_hits`: "white milk pack" finds the milk carton;
it was exact catalog names only, so KO 003's correct object was "no such object" everywhere; `tests/test_find_description.py`),
and `raw_ids` also flags internal failure codes with an underscore ("move failed (hw_fault)", EN 002;
`tests/test_final_say_check.py::test_failure_codes_are_raw_ids`). Found and left as is: the understand model never
fills `said` (0 of 254 KO move goals in the earlier caches), so F4.5 did not run; F4.8 covers the misheard-object
case without it.

Overlap risk (clean-room rule): the hand words, into-words, tell verbs, the place-class table and the hazard
words are written from general sources, not from homeloop_robot's judge or the generator; they may still overlap
with the benchmark's vocabulary, which is why `robot_agent:sage_nohazard` (and `sage_norag`) run as ablations.

