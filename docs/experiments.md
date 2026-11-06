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
| 11 | milestone 10 round 1 leftovers: F6.1 the post-step verify applies a step with the robot's body (a release action of the contract, a Handover, empties the hand; AssistLoop only, ClosedLoop unchanged); F6.2 a goal met by a successful hand-over is observed from the hand-over's success, not by looking at the person's spot | hand-over deliveries judged failed (m10 round 1, id 008) | `StepVerifier(capabilities=...)`, `AssistLoop._verify_with_body`, `_observe_goal` | `tests/test_sage_v2_r3_m10_fixes.py` (synthetic objects) |
| 12 | milestone 10 round 1, second fixer. F7.1 clarify hygiene: an answer that says the whole request again is not a spent round (once per run); a run that still gives up says one plain phrase in the user's language (`say_gave_up`, `say_no_answer`, `say_not_confirmed`, `say_stopped`), not its internal message with the last question; F7.2 language: the find_issues questions and doubts (`q_mentioned`, `iss_*`, `rb_unsure`, `q_unclear_task`, `q_what_exactly`, `q_what_do`) are robot phrases (LocalText), so the Korean user hears Korean without a translation call; no empty-slot question; F7.3 a person's place is taken only from the answer to "Where are you?" (an answer to another question that names a place of the task moved the delivery to a surface near the armchair); F7.4 search: the ranking prompt shows the places grouped by room (house layout) and asks for the whole home, not the room the robot is in; F7.5 hazards: the core list names household brands of cleaning chemicals (a model that translates a word may say a brand); no benchmark tags | clarify cap after an informative answer (m10 round 1 id 005 EN); internal text and English questions said to a Korean user (007, 008 KO); false success from a delivery to a wrong place for an untracked person (008 sage_ask); search ranked the kitchen first and stopped before the bedroom wardrobe (006 EN); a brand name hid a cleaning chemical (009 KO) | `AssistLoop._ask_clarify` / `_restates` / `_finish`, `understand.issue_question`, `persons` use in `_person_destination`, `SearchBelief._layout`, `safety.hazards.HAZARDS` | `robot_agent/tests/test_sage_v2_r3_m10_round1b.py` (synthetic words and places) |
| 13 | milestone 10 round 2, fixer round 1. F8.1 `plan_repair.op_finish`: a replan's suffix that repairs the failed step but drops a goal still to do (the held object put down on another surface) gets the goal's delivery back, symbolically, no LLM call | m10 round 2 id 005 EN (Find of a container failed `absent`, the suffix placed the apple on the counter and lost PutIn) | robot_agent `core/planning/plan_repair.py` `op_finish`, `assist_loop._repair_suffix` | robot_agent `tests/test_sage_v2_r3_m10_round2.py` |
| 12b | bench / robot pack side of the same round: the stopped run's final say is the robot's own words or the stop phrase of the user's language (`stopped_say`; it was the English placeholder "stopped", counted as a wrong-language say in KO, id 007); the simulated user answers "Did you mean X?" about a word of its own last answer with yes and that answer, answers a plain read-back of a refused request about the plan (yes when the read-back names every object of the request, else no and the request again) instead of with the refusal script, and a nightstand is no `electrical` place (a bottle of water on a bedside table was judged electrical_shock + liquid_spill, id 008 sage_ask EN) | simulator gaps: m10 round 1 ids 006 KO, 007 KO, 008 sage_ask EN, 009 KO | `homeloop_robot/dialog.py` `repair` / `plan_readback_answer`, `intent.py`, houses `care_home_suite` `couple_flat` `senior_flat`, `robot_agent_adapter.stopped_say` | `homeloop_robot/tests/test_dialog_m10_r1.py`, `test_hazards_m10_r1.py`, `homeloop_bench/tests/test_m10_r1.py` |

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



### Milestone 10, round 1: verdicts of the second fixer (reruns of tasks 005-009 with the changes above)

Unrecoverable injected faults, with the oracle failing the same way (rule (b)):
- 005 KO and EN: the hand-over is hit by an injected persistent `hw_fault` (`handover` of the mug, oracle KO fails on
  it; the oracle EN heard a corrupted instruction and put the mug on a desk instead of handing it over, a
  heard-words limit of the privileged planner, not a SAGE fault).
- 006 KO and EN: `open wardrobe@master` is hit by an injected `open_fail` (blocked, then unreachable three times); the
  oracle fails on the same call in EN and KO (the same four events), so SAGE, which now searches the bedroom
  wardrobe (the ranking prompt shows the layout), ends on the same fault.

Dev numbers after this tuning are optimistic; the paper reports the TEST split.

### R3 language layer, 3-mode KO comparison

SAGE-v2 now has one robot-agnostic module, `core/planning/language.py` (`LanguageAdapter`). The core works in English;
a Korean user is an I/O layer. IN: each user utterance is translated once by `translate_model` (cached, in the
translate budget), the original stays the task, `said` and the read-back; a translation is distrusted (ask to repeat)
when the translator answers `UNCLEAR`, answers non-English, or loses an ENV place or person named by alias. OUT: every
spoken text passes one `speak()`; the pack's phrases cost no call; failure gives the pack's plain Korean phrase, never
English. Option `input_pivot` = `none | translate | both`; the manifest budget is now 22 planning + 8 translate
calls (was 26 + 4), the 30-call episode cap is unchanged.

Run: the 10 milestone-10 dev tasks, `robot_agent:sage` (people tracking on), profile real, seed 0, qwen3-vl:8b planner,
qwen3-vl:30b-a3b translator; planners `robot_agent:sage_pivot_none`, `robot_agent:sage_pivot_translate`, and `robot_agent:sage`
with the manifest set to `both`. Three of the ten tasks end in an injected, unrecoverable fault that the oracle shares
(002, 005, 006), so 7 is the ceiling.

| mode | KO success (of 10) | KO - EN gap | questions asked (10 tasks) | translate calls | not-in-language texts | false success |
|---|---|---|---|---|---|---|
| EN (reference) | 7 | - | 22 | 0 | 0 | 0 |
| none | 7 | 0 | 24 | 54 | 0 | 0 |
| translate | 6 | -1 | 20 | 58 | 0 | 0 |
| both | 6 | -1 | 27 | 61 | 0 | 0 |

Entity changes caused by translation: 1 of 10 tasks (000). The instruction was an ASR garble ("전자인지" for
"전자레인지"); the translator turned it into a fluent, wrong English sentence ("the electronic door lock ... open the
door"), the model then refused "cannot open room doors", and both `translate` and `both` failed a task that `none`
solves (the understand model reads the garbled Hangul together with the ENV aliases). A translation that sounds
fluent hides the garble, so the UNCLEAR signal did not fire. We found no task where translation helped. The sample is
small (10 tasks, one seed): the difference between the modes is one task.

Decision, by these numbers: default `input_pivot` = `none` (manifest and code). The IN side stays available as an
option. The OUT side of the layer (one `speak()`, no English to a Korean user, `names`, pack-line trimming) is on in
all modes. Re-test on the 50-task milestone before the 300 run.

#### SAGE-v2 changes: m10 round 3 (failure classes, not tasks)

- Wrong-language speech when the translator cannot be used (003 KO). The translate budget (4) was spent, so
  `_in_lang` returned the English text; a second read-back came out half English. Fix: `speak()` never returns
  English for a non-English user (pack phrase `q_unclear_task` / `say_untranslated`), an English slot in a pack phrase
  is translated alone and cached, raw ENV keys are said as names, an English reason after a pack line is dropped,
  translate budget 8.
- Clarification hygiene (007 sage_ask EN). A question asked word for word before is replaced once by "say the task
  in other words"; the delivery's "Where are you?" may take one round past `clarify_rounds`.
- A refused put left its open-container goal (009 sage_ask KO). The hazard gate refused the put; the remaining
  `open fridge` goal was read back three times and never converged. Fix: open/close goals that only served a refused
  goal are refused with it (a full refusal when nothing else is left).
- Found while rerunning (008 sage_ask KO, false success). A "Where are you?" that was built but replaced by another
  question in the same round stayed marked as asked, so a later answer that named a place (the armchair the user
  had corrected away) became the person's position. Fix: the mark is cleared when another question is asked.
Each has a unit test without benchmark text (`tests/test_sage_v2_r3_language_layer.py`). Dev numbers after this
tuning are optimistic; the paper reports the TEST split.

#### SAGE-v2 changes: m10 round 4 (failure class: raw id in speech)
- Failure class: a goal that is not a delivery (open / close of a container) got a "Where should I put X?" question
  whose object was the canonical ENV key, spoken as a raw id in Korean (m10 ids 000, 007, sage / sage_ask KO).
  Fix: `understand.find_issues` gives open / close issues no object (so `issue_question` asks nothing), and
  `speech.render` says a spoken name for an ENV key in the `object` slot too. Test without benchmark text:
  `robot_agent/tests/test_sage_v2_r3_round4_open_slot.py`. Dev numbers after this tuning are optimistic; the paper
  reports the TEST split. The language layer and its 3-mode comparison are in "R3 language layer" above.

#### SAGE-v2 changes: m10 round 5 (failure class: a forgotten answer) and a harness fix
- Failure class (sage_ask KO, m10 id 007): the answer to "Where are you?" was read from the latest answer only, so a
  later answer (to another question) lost the place and the robot asked again until the clarify cap ended the run
  with nothing done. Fix: the place the person said is kept for the run, per person, and used only after the question
  was asked (`AssistLoop._person_at`). Test without benchmark text:
  `robot_agent/tests/test_sage_v2_r3_m10_round5_where_memory.py`.
- Harness bug (oracle EN, m10 id 005): the oracle chose reach or hand from the ASR text. The recogniser had dropped
  the words that ask for a hand-over, so the reference parked the object on a desk and then found no plan. Privileged
  planners (oracle, naive) now choose the delivery mode from the words the user said plus the corrections
  (`planners/oracle.heard_text(true_words=True)`); the labels are still never read, and the LLM planners hear the ASR
  text as before. Test: `tests/test_oracle_true_words.py`. Rerun of oracle and naive on the m10 tasks: same outcomes
  as round 5, except that 005 EN now ends on the injected persistent `hw_fault` like KO.
- Round 6 (same class): an essential question (Where are you?) no longer skips the repeat guard, and takes no
  extra round past the clarify cap once the person's place is known. Test:
  `test_an_essential_question_does_not_skip_the_repeat_guard` in the same file.
Dev numbers after this tuning are optimistic; the paper reports the TEST split.

#### SAGE-v2 changes: m10 round 6 fixer (failure class: ASR-garbled request, clarification loop ends in give-up)
- Failure class (m10 id 005 EN, sage and sage_ask): the first hearing was garbled; a clean full restatement was
  understood, but the object-coverage check still read the garbled original, so the stale noun became an object issue,
  then a repeat question, and the clarify cap ended the run before any action. Fix: `AssistLoop._object_source`
  reads the latest answer that restates the request instead of the first hearing. Test without benchmark text:
  `robot_agent/tests/test_sage_v2_r3_m10_round6_restated.py`. Targeted rerun of 005 EN (sage, sage_ask): the run now
  reaches the handover and ends on the injected persistent `hw_fault`, the same event that ends the oracle (EN and KO).
- The two targeted items of this round (oracle dead end after the mug is parked; the forgotten Where-are-you answer
  and the repeat guard) were committed in rounds 5 and 6 (see the entries above). Dev numbers after this tuning are
  optimistic; the paper reports the TEST split.

#### SAGE-v2 changes: m50 round 1 fixer (failure classes of the 30 non-ok tasks; branch `sage-v2/homeloop`)
Every change is robot-agnostic and has a unit test with synthetic text (`robot_agent/tests/test_sage_v2_r3_m50_round1_*.py`,
`test_wiring_robot.py`, `test_fix_execute_verify.py`). "ids" are the dev ids where the class was seen. Dev numbers after
this tuning are optimistic; the paper reports the TEST split. Design: `DESIGN_SAGEV2.md` section 15.

| class | ids | change |
|---|---|---|
| room-level go raises an "unsaid place" question | 020 | a `go` goal is covered when the words name its room |
| raw ENV ids in English speech | 042, 043 | `plain_names` in the language layer for English too |
| a step's internal text as the final sentence | 033, 043 | the pack phrase `say_could_not_do` (KO in the robot pack) |
| request with a lost verb is guessed | 027 | `verb_lost` -> one question, first hearing only |
| a dropped object is given up | 034, 038, 048 | contract rule DROPPED = REFIND: floor of the room, Find, Pick, the step again; one more look where the grasp failed or the object fell |
| search ends on a miss count while places remain | 043, 046 | with search legs the end is the look total (`search_total`) or no place left |
| a noisy check after a pick or a release | 024, 034, 041 | two more readings settle it (2 of 3), only when the skill reported success and only the sensor layer fails; a sensor that failed with a device fault is unknown, not a contradiction |
| a move ends away from the target | 025 | its own retry for a localization failure |
| one camera miss at the final look | 038 | one repeat look where a verified step put the object |
| a message's listener is also the delivery's recipient | 039 | `shared_listener`: a person named once is the listener; the recipient is the speaker |
| plan gate does not converge | 021, 039 | symbolic operators `say`, `putin`, `fetch`, `unclose` |

Harness fix (homeloop_robot): the pose read after a move used the motion-call hardware rate and a persistent base fault;
docs/failure_model.md already lists `pose` as a sensor call. A robot that reads its pose after each move was exposed twice
as much as the calibration counts (task 041: a persistent fault on the pose read ended a run the oracle finished). Now
`hw.p_per_sensor_call`; test `tests/test_failure_paths.py::test_pose_reading_uses_the_sensor_rate_not_the_motion_rate`.
Earlier milestone numbers (m5, m10) were measured with the old rate and must be re-run when the milestones are repeated.

Open after this round (not fixed): KO relay messages (013, 044), clarify and read-back rounds that end in give-up under
injected ask timeouts (011, 023, 030, 032, 042), conditional goals (037), "a drink" not grounded to the ENV objects (047),
a relation word that names two people (017), plan-gate losses in KO (021, 024, 046).

#### SAGE-v2 changes: m50 round 2 fixer (failure class: a goal set that only walks, for a non-English request; branch `sage-v2/homeloop`)
Class: false success where the model read a request as "go to X" and dropped the object it names. The object check
(`find_issues`) reads English only, so a Korean request with a go-only goal set passed it and the run ended with
"task done" against its own goals (ids 025; the same dropped-goal family as 016 and 047, which are not covered by this
change). Change: `understand.vacuous_goal_issues` reads the language layer's cached English translation of the request
when every goal is `go`, and returns an `object` issue per object in object position (re-sample, then ask). It adds
no translation call and is skipped when the translation is untrusted. Test: `robot_agent/tests/test_vacuous_goal_issues.py`
(synthetic text). Not fixed here: dropped goals when some other goal does move an object (needs a per-goal match of the
translation to the goals), read-back loops under injected ask timeouts, search and plan-gate classes listed above.
The 50-task milestone has not been re-run for this change; it is only reported when it is. Dev numbers are optimistic.

## SAGE-v2 improvements (R4b)

Each change is measured on the fresh slice (dev tasks 51-100, never used for tuning). Keep rule: kept if sage EN+KO
successes are not lower and false successes did not rise by more than 2. One seed and 50 tasks: noise is about plus or
minus 3 tasks.

### Step 1: `input_pivot` default (KO slice)

Setup: KO, 50 tasks, real profile, seed 0, planner qwen3-vl:8b-instruct, 3 shards per mode, one mode at a time, merged,
n_error 0 in all three modes.

| mode (planner `robot_agent:...`) | successes /50 | false successes /50 |
|---|---|---|
| none (`sage_pivot_none`) | 19 | 6 |
| translate (`sage_pivot_translate`) | 13 | 9 |
| `sage` (its default is `none`: the SAME configuration as the first row, so this row only measures run-to-run noise; the baseline run of `sage` gave 16 / 8) | 18 | 7 |

Decision: BEST = none (the recorded decision is that the default stays none). `none` is not a clear win.

Correction (orchestrator, after reading the adapter and the manifest): the mode `both` was NOT run in this step. `robot_agent:sage` takes its mode from the manifest (`input_pivot: none`, `robot_agent_adapter.py:386`), so the three KO runs of the same configuration gave 16 (baseline), 18 and 19 successes: **identical settings differ by up to 3 tasks of 50 from run to run** (GPU batching makes temperature 0 not exactly repeatable). Only `translate` (13 / 9) is clearly worse. The hybrid `both` (original text plus the English translation in the understand prompt) still has to be measured, with repeated runs; see the follow-up.
`none` vs `both` is 19 vs 18, inside the noise. The earlier baseline run of `sage` KO in `results/r4b/base` gave 16 / 8,
so the same `both` configuration moved by 2 tasks between runs. `translate` alone is a negative result: 6 fewer
successes than `none` and 3 more false successes (5 fewer and 2 more than `both`).

### Step 2: dialogue convergence (class C1) — measured on the slice: KEPT

robot_agent worktree commit 7a8e019 (branch sage-v2/homeloop), option `dialog_converge` (default on, `0` = earlier loop).
Root causes, read from the cached dialogues of the failing episodes of `results/r4b/base` (replayed from the llm cache,
no GPU; EN 63, 69, 90, 93, 94, 58, 71, 81 and KO 54, 65, 66, 67, 68, 69 among them):

1. A correction after a read-back "no" was applied to ALL move goals (`pin_to`), or the task was understood again and the
   model moved the other object too (KO 65, 67, 69; EN 69, 90): one goal fixed, another broken, every read-back.
2. The same reading was read back again after it was refused (EN 93, KO 68, EN/KO 90, 94): same sentence, same "no".
3. The clarify cap and the read-back cap counted every question, also those that changed the goals (KO 54, 66).
4. A question reworded only in politeness passed the word-for-word check (EN 71).
5. The read-back said "from the you" for a source that is a person (EN 69).

Changes: a correction edits the one goal it names (rules, no model call); a refused reading gets a choice question once
instead of a second identical read-back; the caps give back a round for an answer that produced new goals (read-backs:
+2 at most, questions: +2 at most); near-duplicate questions are reworded once. Not done: executing the uncontradicted
goals before confirmation (needs a plan-phase split; the failing dialogues show wrong goals, not right ones left
unconfirmed). Several of the slice's failures stay out of reach of this change: the simulated user answers "I don't
know" or a garbled yes / no (EN 58, 71, 81, 94), and EN 93 / KO 68 are refused although the read-back is right.
LLM calls per episode: a patched correction replaces one understand call; the extra rounds the caps allow can add
calls only in dialogues that gave up before.

Slice measurement (dev tasks 51-100, profile real, seed 0, qwen3-vl:8b-instruct planner, `robot_agent:sage`, n_error 0 in all runs):

| run | EN success | KO success | EN false success | KO false success | EN+KO false success |
|---|---|---|---|---|---|
| before (`results/r4b/base`, `dialog_converge` off) | 22 / 50 | 16 / 50 | 6 | 8 | 14 |
| after (`results/r4b/i2`, `dialog_converge` on) | 24 / 50 | 16 / 50 | 6 | 9 | 15 |

Decision: KEPT. EN+KO successes 38 → 40 (not lower) and false successes rose by 1 (not more than 2), so the keep rule holds.
Mechanism of the gain: the give-up rate fell (EN 0.42 → 0.38, KO 0.52 → 0.50) and mean LLM calls per episode fell
(EN 6.0 → 5.8, KO 10.2 → 9.9). KO successes did not change (16 → 16), so this run shows no KO gain on the targeted KO dialogues (54, 65–69).
Noise caveat: one seed and 50 tasks; the noise is about plus or minus 3 tasks. The same KO configuration gave 16, 18 and 19
successes in Step 1, so the +2 EN gain and the 0 KO change are within noise and do not prove the change helps.
EN severe violation and min separation 0.27 m (protective stop) appear in both runs (before and after), so this change
did not cause them. Tests: `tests/test_sage_v2_r4b_dialog_converge.py` with `tests/test_sage_v2_r3_m5_fixes.py` (52 passed,
robot_agent worktree, commit 7a8e019; embodiplan on PYTHONPATH from the sage-v2/homeloop worktree).

### Step 3: perception and search (C4, C5, C6, C7) — measured on the slice: KEPT

Three robot_agent commits on sage-v2/homeloop, measured together as one change (run `results/r4b/i3`, started after the
third commit):

- **Miss is not absence (C4, C5), commit cba8d0a.** A detector miss is a false negative with rate `detector_miss_rate`
  (the robot pack's own manifest value, default 0.1, never a benchmark profile). Each place keeps `rate ** misses` of its
  prior weight, so a strong earlier sighting is re-checked before the unlikely places. The second-look budget follows the
  rate (0 for a perfect detector, 2 at the default). Misses survive unsearch and save/load. Code: `core/planning/search.py`.
- **Phantom pick is a search miss (C6), commit 994d6c0.** A Pick that fails with "absent" right after a Find that saw the
  object is a false positive, not a grasp failure. The robot does one look in place, restores the search state from before
  the Find, and records a miss. Only with `search_legs`; other packs keep the old Pick recovery. Code:
  `core/planning/assist_loop.py`.
- **Two equal objects are asked about (C7), commit 929049c.** When a Find returns `candidates` and the words the person used
  leave more than one, the robot asks "which one?" once and then searches for the chosen description. Packs without
  `candidates` are unchanged. Code: `core/planning/which_one.py`, `assist_loop.py`, `speech.py`.

Targets: failure classes C4 and C5 (search), C6 (phantom pick), C7 (duplicate objects not asked). The R4b brief lists no
task ids for these classes, so none are claimed here. Tasks whose outcome changed on the slice (before → after):
EN 50 F→S, 83 F→S, 94 F→S, 52 S→F, 90 S→F; KO 68 F→S, 83 F→S, 93 F→S, 59 S→F, 96 S→F, 97 S→F. Among the per-task false-success flips: EN 83 and KO 93 lost a false success; KO 59 and 96 gained one.

Tests (robot_agent worktree, run for this step): `tests/test_sage_v2_r4b_relook.py`, `tests/test_sage_v2_r4b_phantom.py`,
`tests/test_sage_v2_r4b_which_one.py` with `tests/test_sage_v2_r3_m5_fixes.py` and `tests/test_sage_v2_r4b_dialog_converge.py`
(all pass, exit 0).

Slice measurement (dev tasks 51-100, profile real, seed 0, qwen3-vl:8b-instruct planner, `robot_agent:sage`, one seed, n_error 0):

| run | EN success | KO success | EN false success | KO false success | EN+KO false success |
|---|---|---|---|---|---|
| before (`results/r4b/i2`, Step 2 kept) | 24 / 50 | 16 / 50 | 6 | 9 | 15 |
| after (`results/r4b/i3`, Step 3 changes) | 25 / 50 | 16 / 50 | 4 | 9 | 13 |

Decision: KEPT. EN+KO successes 40 → 41 (not lower) and false successes fell 15 → 13 (did not rise), so the keep rule holds.
Per task, 6 tasks gained a success and 5 lost one (EN +3 −2, KO +3 −3), so the net is +1 EN and 0 KO.
Noise caveat: one seed and 50 tasks; the noise is about plus or minus 3 tasks. The same KO configuration gave 16, 18 and 19
successes in Step 1, so the +1 EN success and the EN false-success drop (6 → 4) are within noise and do not prove the
change helps. KO successes did not change (16 → 16); the KO false-success count stayed at 9.

### Step 4: `gate_complete` (registered variant `robot_agent:sage_complete`) — measured on the slice: NOT KEPT, stays off

Setup: same slice and settings as Step 3 (dev tasks 51-100, profile real, seed 0, qwen3-vl:8b-instruct planner, EN and KO,
n_error 0 in both). Run `results/r4b/i4` (`sage_complete`, 3 shards per language, merged) against `results/r4b/i3`
(`sage`, the Step 3 state, the reference for this step).

| run | EN success | KO success | EN false success | KO false success | EN+KO false success |
|---|---|---|---|---|---|
| before (`results/r4b/i3`, `sage`, gate_complete off) | 25 / 50 | 16 / 50 | 4 | 9 | 13 |
| after (`results/r4b/i4`, `sage_complete`, gate_complete on) | 23 / 50 | 15 / 50 | 4 | 11 | 15 |

Decision: NOT KEPT, the default stays off. EN+KO successes fell 41 → 38, which fails the keep rule (not lower). False
successes rose 13 → 15, within the allowed +2, but the success rule already rules the change out. The variant
`sage_complete` stays registered as a negative result; the `gate_complete` default is unchanged. The change is not
reverted in code because it was never made the default.
Noise caveat: one seed and 50 tasks; the noise is about plus or minus 3 tasks, so the −3 EN+KO difference is at the
edge of noise. It is recorded as worse, not as proven worse.

### Step 5: planner size ablation (`robot_agent:sage` with qwen3-vl:30b-a3b-instruct as planner), measurement only, default unchanged

Setup: same slice as Steps 3-4 (dev tasks 51-100, profile real, seed 0, EN and KO, one seed, 50 tasks per language). Only the
planner model differs. No default was changed.

| planner | EN success | KO success | EN+KO success | KO−EN gap | EN+KO false success |
|---|---|---|---|---|---|
| qwen3-vl:8b-instruct (current default, `results/r4b/i3`) | 25 / 50 | 16 / 50 | 41 / 100 | 9 | 13 |
| qwen3-vl:30b-a3b-instruct | 23 / 50 | 12 / 50 | 35 / 100 | 11 | 21 |

Reading: the 30b planner did not help. It scored 6 successes fewer in total (EN −2, KO −4) and produced 8 more false
successes. The false-success figure of 21 is taken as the EN+KO total; the per-language split was not given for this run.

What it means for the gap: model capacity does not explain the KO−EN gap. The larger planner widened the gap from 9 to 11
points, because its KO loss (−4) is larger than its EN loss (−2). So a bigger planner closes none of the gap here. The
remaining KO gap comes from parts of the pipeline the planner does not control (the Korean read-back and translation path,
the dialogue, and the simulated user's answers, as in Step 2). The 8b planner stays the default.

Noise caveat: one seed, 50 tasks per language, and the same configuration varied by up to 3 successes per run (Step 1).
The 6-success total drop is at the edge of that noise, so the result is recorded as "no gain from 30b", not as "30b is
proven worse". The false-success increase (13 → 21) is larger than the keep-rule margin of 2, so it is noted, not ignored.

## Solution lab round 1 (SAGE-v2, 2026-11-06)

Method: the solution-lab process (frame the problem from cached evidence, read prior art, ideate under several lenses, red-team
the ideas, check the survivors offline on cached episodes, prototype the best one behind a flag, then measure on a few tasks,
paired and repeated). Stages 1-5 used only cached episodes and needed no GPU. The lab notes are kept outside the repository.
The user asked to switch off speech-recognition noise for the validation, so every validation table below is the sensitivity
condition `asr_off`, never a headline.

### Problem brief (summary)

SAGE-v2 (`robot_agent:sage`, branch `sage-v2/homeloop`) scores about 44-50 % EN and 32 % KO on the fresh dev slice 51-100
(naive 48 %, oracle 86 %). Fixing failures one by one had stopped paying: dialogue fixes (I2), belief search (I3), `gate_complete`,
translate-first and the 30b planner all moved the total by less than the noise or lost. Three facts from the cached runs:

- Across three code versions most tasks keep their outcome (EN: 21 tasks always succeed, 23 never, 6 move; KO: 11 / 29 / 10).
  The run-to-run noise (about 3 tasks of 50) sits on 6 to 10 unstable tasks per language. Only per-task, paired comparisons mean anything.
- Under a proxy for "no recognition error" (instruction heard correctly) the dialogue give-ups fall from 24 to 7 (EN) and 36 to 7 (KO)
  task-runs, and false successes from 16 to 5 and 26 to 5. What stays is failure after a correct understanding.
- A deterministic family sits under many failures: requests that mix a spoken message or a delivery to a named person with another
  step. On the slice, EN mixed-message sets: 16 task-runs (7 tasks), 0 successes in all three code versions; oracle 7 of 7.
  The causes seen in the kept debug logs: the free planner paraphrases the sentence, puts a go goal on "the spot within reach", swaps
  recipients, hands over to the speaker instead of the named person (a false success), or invents a source container that cannot be opened.

### Ideas that survived (after the offline check)

- Person-destination and template goals compiled into the robot's own steps, with a recipient receipt (ranked first; offline bound
  +3 EN and +3 KO tasks per 50 on the design slice, +2 EN on tasks the rules were not read from; removes the wrong-recipient false success).
- Commit the stable reading at the dialogue cap (rule R2). Survives only in a reduced form: +0 to +2 tasks per 50 with ASR on, about
  +1 or less with ASR off, and half of the KO commits are wrong. Ranked second, checked offline only.
- Act on skill-result events, starting with a partial open (about +1 task per 50, deterministic, small). Not built.
- Search prior from the robot's own find history: parked (1 to 2 tasks on fresh data, clean-room risk for any seed table).

### Ideas refuted or dropped (one line each)

- Goal-hypothesis ledger, entropy questions, clause-wise understanding, extra LLM views: red team found the pool is the oracle-ensemble
  pool, the second view is the same 8B model, and translate-first already lost (i1); about 400 lines for no measured pool.
- Case memory and glossary built from the benchmark TRAIN split (M1, M2, M3, M5): clean-room violation, or trains on the simulated user;
  object-name headroom is about 6 points and not specific to Korean.
- Act first, ask later: cannot be tested offline (the cache has no Find candidates), and the "which one?" question already works from candidates.
- Do not ask where an object is, search instead: asking is not a measured loss (same success as other runs); 28 of 34 such answers carry no goals; bound +0.7 EN.
- Completion audit by word cues: flags 1 of 42 false successes, 0 of 107 successes, so no recall. Only the recipient receipt is kept (merged into the first idea).

### Prototype

Flag `person_goals` (default off), registered variant `robot_agent:sage_lab` (SAGE with the flag on). Commits: robot_agent worktree
42b731d and 93e3edc; homeloop_bench 9d9146c (variant registration). Changes when the flag is on: a request that mixes template goals
(go, say, deliver) with moves gets the template goals as fixed sub-goals compiled from the robot's own steps (the planner expands only
the moves and never paraphrases a sentence); a goal whose destination is a person gets a typed recipient resolved through the robot's
person entries, and an unknown place is not driven to; two new gate repair operators (recipient mismatch, container that cannot be
opened); repeated goals are de-duplicated. No extra LLM call. Unit tests: `tests/test_sage_lab_person_goals.py`. With the flag off the
old behaviour is unchanged: a fake-LLM comparison on 12 dev tasks per language gave identical successes for the old code, the new code
with the flag off, and `sage_lab` (EN 6 of 12 each; KO 6 of 12 each; the same task ids).

### Pilot results

Setup: dev tasks 50-59 (the first ten of the fresh slice), profile `real` with `asr_off`
(`asr.en.app_wer=0, asr.ko.app_cer=0, asr.p_partial=0`; wrong or unsure answers, silence, interruptions and device faults stay), qwen3-vl:8b-instruct,
two runs per configuration. S = success, F* = false success (said done, goals not met), f = other failure. Results are in `results/lab1/`.
The first five tasks were the pilot gate (same outcome pattern as the first five rows below).

| task | sage EN r1 | sage EN r2 | lab EN r1 | lab EN r2 | sage KO r1 | sage KO r2 | lab KO r1 | lab KO r2 |
|---|---|---|---|---|---|---|---|---|
| 050 | S | S | S | S | S | S | S | S |
| 051 | S | S | S | S | S | S | S | S |
| 052 | f | f | f | f | f | f | f | f |
| 053 | f | f | f | f | f | f | f | f |
| 054 | F* | F* | F* | F* | f | f | f | f |
| 055 | S | S | S | S | S | S | S | S |
| 056 | S | S | S | S | F* | F* | F* | F* |
| 057 | f | f | f | f | f | f | f | f |
| 058 | F* | f | f | f | F* | F* | F* | F* |
| 059 | f | f | f | f | f | f | f | f |

| configuration (asr_off, 10 tasks) | success | false successes |
|---|---|---|
| sage EN, run 1 / run 2 | 4 / 4 | 2 / 1 |
| sage_lab EN, run 1 / run 2 | 4 / 4 | 1 / 1 |
| sage KO, run 1 / run 2 | 3 / 3 | 2 / 2 |
| sage_lab KO, run 1 / run 2 | 3 / 3 | 2 / 2 |

One extra run of `sage_lab` under the unchanged `real` profile (ASR errors on, single run, no baseline pair, so it is not a comparison):
EN 5 of 10 (1 false success), KO 2 of 10 (1 false success).

Per-task reading:
- The only paired difference is 058 EN run 1: the baseline reported done without meeting the goals, the lab variant gave up after
  three questions; in run 2 both failed. It turns one false success into a give-up and no success. It could be this mechanism or run-to-run
  variation; it was not traced to a line and is not claimed.
- 059 is the one validation task in the target family (a spoken message plus a delivery to a named person). It still ends in the plan-gate
  give-up ("I could not make a plan that passes my checks", `assist_loop.py` near line 2014, under the lab flag), with the recipient
  goal `delivered(...)` not met. The lab flag did not turn it into a success. The gate findings are not stored in the episode, so
  the remaining cause (which finding blocks the plan after the new operators) is not yet established. 054, 056 and 058 in KO and 052, 053,
  057 are outside the family (hardware stops, search, read-back); their identical outcomes are the expected no-change result.
- The tasks 87, 95 (EN and KO) and 15, 18 (EN), which the offline check named as the family's best triggers, were not part of this
  10-task run, so the main claim of the offline estimate (+1 to +2 tasks per language on those) has not been tested online yet.

### Verdict

Not proven, not refuted. The prototype is safe on this sample (no task lost in either language, fake-LLM regression identical, no error
runs), but it also gained nothing on the ten tasks: successes 4 vs 4 (EN) and 3 vs 3 (KO) in both runs. The one validation task in the target
family (059) was not fixed. So the flag stays off by default and `robot_agent:sage_lab` stays registered as a candidate. It is not
promoted to the default and it is not recorded as a negative result either, because the ten tasks hold almost no trigger (as the offline
check predicted: tasks 50-59 have one task in the family).

### Noise caveat

Ten tasks, two runs, one seed per run. The earlier work measured about plus or minus 3 tasks of 50 between runs, and the outcomes of
single tasks are mostly fixed, so identical totals here mean "nothing moved", not "no effect on other tasks". The `asr_off` condition
removes recognition noise only; answers can still be wrong or unsure, and the user can be silent or interrupt. The proxy used offline
for `asr_off` (instruction heard correctly) is an upper bound, so the offline pools are overestimates of what remains. Do not quote
any number of this section as a headline.

### Next proposals

1. Trace 059 first: replay the plan-gate findings for the lab variant on the cached plans (CPU only), and fix the finding that still
   blocks it. Store the gate findings in the episode record so the cause is visible without the debug logs.
2. Test the prototype where it can fire: tasks 87 and 95 (EN and KO) from the design slice and 15 and 18 (EN) from the earlier 50, labelled as
   extras, two runs each, `asr_off`. Keep rule: at least 2 of the 5 EN tasks succeed with the flag on, nothing the baseline solves is lost, no error runs.
3. If it passes, run the whole fresh slice (50 tasks, EN and KO) once, paired with the baseline, and only then consider making it default.
4. Build the skill-event rule (partial open) as a separate flag, with a fake-skill replay of the failing call sequence before any LLM run.
5. Rule R2 (commit at the cap) only after the KO read-back path is more precise: half of its KO commits are wrong today. Check it offline and with a scripted user, not by a total.

## Solution lab round 1b (SAGE-v2, trigger tasks, 2026-11-06)

Question: does the lab flag `person_goals` (`robot_agent:sage_lab`) help on the tasks where it should fire? The 10-task pilot above held
almost no trigger, so its verdict was open. This round runs 59 tasks per language: 49 tasks chosen for a mixed request (a spoken message
or a delivery to a named person plus other steps) or a person destination, and 10 control tasks where the flag has nothing to do.
Same conditions as the pilot: profile `real` with the sensitivity condition `asr_off` (`asr.en.app_wer=0, asr.ko.app_cer=0, asr.p_partial=0`),
qwen3-vl:8b-instruct, one seed, two runs per configuration, paired by task. Everything below is `asr_off`, never a headline. Results in
`results/lab1/trigger/`. 8 configurations, 3 shards each; all 24 shard logs and all 8 merge logs end with EXIT=0 and `n_error` is 0 in all 8 summaries.

### Result

S = success, F* = false success (said done, goals not met), f = other failure. "base" = `robot_agent:sage`, "lab" = `robot_agent:sage_lab`.

| configuration (59 tasks) | success | false successes | trigger tasks (49) success | control tasks (10) success |
|---|---|---|---|---|
| base EN run 1 / run 2 | 34 / 34 | 4 / 4 | 24 / 24 | 10 / 10 |
| lab EN run 1 / run 2 | 35 / 35 | 4 / 5 | 25 / 25 | 10 / 10 |
| base KO run 1 / run 2 | 17 / 20 | 10 / 9 | 9 / 10 | 8 / 10 |
| lab KO run 1 / run 2 | 19 / 18 | 11 / 11 | 11 / 10 | 8 / 8 |

The five EN tasks named in the kill criterion (the family where the offline check expected a gain), and the KO tasks of the same family:

| task | base EN r1 r2 | lab EN r1 r2 | what the flag did |
|---|---|---|---|
| 059 | f f | f f | nothing: same plan, same gate give-up as the baseline |
| 087 | F* F* | F* F* | nothing: hand-over still goes to the speaker's reach spot |
| 095 | f f | S S | the only gain: gate operator `unopenable` removed the Open/Close of a cabinet that cannot be opened |
| 015 | S S | S S | baseline already solves it; plan identical |
| 018 | S S | S S | baseline already solves it; plan identical |

| task (KO) | base r1 r2 | lab r1 r2 | note |
|---|---|---|---|
| 024, 054, 090 | f f | f f | plan-gate give-up, as in the baseline |
| 066 | f F* | f f | dialogue and gate noise, no flag path |
| 087 | F* F* | F* F* | same as EN |
| 059 | f S | S f | noise: the two arms swap outcomes |

Over all 49 trigger tasks per language: EN 24 tasks are never solved and 24 always solved, only 095 moves (a gain). KO 37 never solved, 8 always, the
rest move between runs of the same code (see Noise).

### Verdict against the kill criterion of proposals.md

- At least 2 of the 5 EN tasks succeed with the flag: 3 of 5 (095, 015, 018), but only 095 is caused by the flag; 015 and 018 are solved by the
  baseline in both runs. The proposal listed them as plan-gate give-ups; under `asr_off` the baseline no longer fails them.
- No baseline-solved task lost: EN none. KO control task 009 went from S S (the baseline refuses the request, which is correct) to f f.
  Traced below: it is not the flag.
- No false-success rise: EN 4/4 to 4/5 (task 047 run 2, a different reading of the request, plan path without the flag), KO 10/9 to 11/11 (understanding
  differences). Both inside the noise.
- `n_error`: 0 in all 8 runs.

Read literally, the KO loss on 009 is a kill. It is not credited to the flag (see below), and the more important finding is that **half of the
prototype did not run at all** (next section). So the verdict is **inconclusive**: the flag as built was tested, it gained one task (095 EN) and
lost none for a reason that is its own, but the mechanism the proposal ranked first (fixed template sub-goals) was never active. The result
neither supports nor refutes the idea. Do not promote the flag and do not record the idea as a negative result.

### Finding 1: the fixed template sub-goals never ran in any episode

`assist_loop.py:2108` builds the fixed blocks only if `getattr(r.planner, "fixed_subgoals", False)`. In a run, `r.planner` is a `GraceBackend`
(`robot_agent/core/planning/backends/pyplanner_grace.py:166`), a wrapper around the embodiplan planner. The attribute lives on the wrapped
`SAGEPlanner` (`embodiplan/sage.py:356`), the wrapper has no such attribute and no `__getattr__`, so the check is always False
(checked by calling `getattr(GraceBackend.wrap(embodiplan.get("GRACE")), "fixed_subgoals", False)`: False). The unit tests use a stub with the
attribute set (`tests/test_sage_lab_person_goals.py:102`), so they passed.
Evidence in the runs: the sub-goal blocks of 059 EN in the lab arm are all expanded and refined by the LLM (`refined_blocks` all true, block sizes
[2, 2, 7, 2], 8 LLM calls, three `Announce` steps with a paraphrased sentence), identical to the baseline; a fixed block would be one or two
steps, not refined, and would use `Say` with the exact sentence. Over the 49 trigger tasks the gate-repair log of the lab arm shows the flag at work only through the
two gate operators: `unopenable` on EN 069, 094, 095. The operator `recipient` never fired, and the fixed sub-goals never fired.
So this round tested "two gate operators plus goal de-duplication", not the proposal.

### Analysis of the trigger tasks where the flag did not turn a failure into a success

Cause groups, from the lab-arm debug logs and episode records (task ids are slice numbers; the lab arm and the baseline have the same cause
unless noted). "Flag acted as designed?" asks whether the part of the flag that applies did what it was written to do.

| group | tasks (EN) | tasks (KO) | what the planner did, cause | flag acted as designed? |
|---|---|---|---|---|
| A. Mixed set, plan gate gives up | 059, 066, 023 | 024, 054, 066 (some runs), 006 (some runs) | The free planner expands the say / go blocks itself: three `Announce` steps with paraphrased sentences, a `Place` where the goal needs a hand-over, a go-to-dock block that drops the earlier goals. The gate repair stops when the findings do not fall (`subgoal_repair.py:127`: "edits stopped: ... not fewer than the round before"), the plan is uncertified and never runs (`assist_loop.py:2012-2017`). 059 EN ends with only "go to the dock" unmet. | No. The fixed blocks that were meant to prevent exactly this were inactive (Finding 1). |
| B. Hand-over to the wrong recipient, false success | 087 | 087 | The understood goal puts the wallet's destination on "the spot within your reach", a place, while the person is named only in the say goal. `op_recipient` needs a goal whose `to` is a person (`plan_repair.py:286`), so it has nothing to repair; the run says done, the hand-over goes to the speaker. The wrong recipient comes from the understanding, upstream of the operator. | The operator is correct but cannot fire. The offline estimate assumed it would. |
| C. Hand goal to a person executed as `Place` | (066 EN) | 054, 090 | The planner writes `Place grandpa` for a hand goal. `op_recipient` only rewrites a release action (`plan_repair.py:282`: `a not in rel`), a `Place` to a person is outside its scope. | As designed, but the design does not cover this form. |
| D. Searches fail ("absent") | 032, 053, 088, 047 (run 1), 033 | 032, 033, 053, 078, 094, 080, 048 | The object is not at any of the six places searched. Not in the flag's scope (search). KO 094 ends on an Open of a cabinet the map says cannot be opened; the lab operator did not remove it in that run (not traced further). | Not applicable. |
| E. Hardware or manipulation stop | 002, 005, 036, 057, 079 (injected `hw_fault`), 021, 034 (grasp collision), 048 (drop), 086 (drawer only partly open) | 002, 005, 034, 036, 057, 069, 079, 084 | Skill failures or injected device faults end the run. Not in the flag's scope. 086 and the `partial_open` event are the target of Proposal 3, not built. | Not applicable. |
| F. Dialogue gives up | 030, 063 | 007, 008, 023, 064, 066, 071, 077, 086, 099, 032 | The read-back or clarify loop ends at the cap ("could not confirm"), no plan is made. Proposal 2 territory. | Not applicable (the flag acts after understanding). |
| G. False success from understanding | 054, 069, 071 | 021, 038, 061, 063, 075, 088, 095 | The understood goal set misses a goal (KO 095: the repeated go goals replace the delivery; KO 061, 088: one go goal for a whole request), the plan achieves what was understood, the run says done. The EN ones (054, 069, 071) are not mixed-person tasks: same result in all four runs. | Not applicable; `goals.dedupe` ran but removed repeats only. |

Reading of the one gain, 095 EN: baseline run 1 stops at the dialogue cap, run 2 reaches the gate and gives up on "upper_cabinet cannot be
opened or closed" (twice). In the lab arm the operator `unopenable` removes the two Open/Close steps in four edits (the gate log shows "gate
repair (unopenable): 0 critical finding(s) left") and the plan runs and succeeds in both runs. The first part of the plan still has the `Announce` of a
paraphrased sentence; the gate's existing `say` operator turned the first one into `Say`, which is why it passes. This is the mechanism
acting as designed, but it is the smaller half of the idea (an unopenable container), not the person-goal compile.

On EN 069 and 094 the same operator fired and the outcome did not change (069 stays a false success because the glass never reaches the person, 094 already
succeeded).

### Noise

- EN: the repeats are close to identical. Success differs between run 1 and run 2 of the same code on 0 of 59 tasks (base) and 0 of 59 (lab); outcome class
  (S / F* / f) differs on 0 and 1 tasks.
- KO: the repeats are not identical. Success differs between run 1 and run 2 on 5 of 59 tasks for the baseline (17 vs 20 successes) and 1 of 59 for the lab;
  outcome class differs on 7 and 3. Lab vs base in the same run position: 4 to 6 tasks differ in success. So the KO difference between the arms
  (19 / 18 vs 17 / 20) is not distinguishable from run-to-run variation, and the earlier estimate of about 3 tasks of 50 holds for KO, not for EN.
- The cause is the model server, not the agent. For the same prompt (same cache key) the response differs in 25 to 35 of 326 common prompts in EN and 41 to 45 of about
  300 in KO, between two runs of the same code and between the arms alike. KO 009 is an example: the request is the same prompt in both arms (cache key `3cf99a0d`);
  the baseline runs read the cleaning product as a detergent and refuse (correct), the lab runs read it as a harmless soap and ask three questions
  before giving up. The flag does not touch that path (no template goal, no gate), so the "lost" task is model-server variation, in two runs per arm.
- Two runs per arm and one seed per run therefore add little in EN (repeats agree) and are too few in KO (repeats disagree by 3 tasks).

### What to do next

1. Fix the wiring first. Make the wrapper expose the capability of the planner it wraps (for example a `fixed_subgoals` property on `GraceBackend` that
   reads the wrapped planner), and change the unit test so that it builds the real `GraceBackend.wrap(...)` around a scripted `SAGEPlanner` instead of a stub with the
   attribute. A fake-LLM run of 059 EN must show `Say` with the exact sentence and `refined_blocks` false for the template blocks before any LLM run.
2. Record in the episode, for the flag, whether it was active: the gate findings, `repaired_by_op` and a `fixed_blocks` count. Today the proof had to be rebuilt from
   debug logs that are deleted with the temp directory.
3. Re-run the same 59 tasks per language, EN and KO, two runs per arm, in a new output directory, after the fix. Same kill / keep rule, with one change: judge "baseline-solved task lost"
   only on tasks where the lab arm's plan path differs from the baseline's (the gate log), so model-server variation (KO 009) cannot decide it.
4. Handle the two cases the log shows the operators cannot reach: the recipient named only in the say goal (087), where the understanding must give the hand goal a person as
   destination (an understanding-side rule, checked offline on the cached understand outputs first), and a `Place` to a person written for a hand goal (KO 054, 090), where
   `op_recipient` could rewrite a `Place` to a person to the pack's release action.
5. For KO use more than two runs, or fewer claims: with repeats that differ by up to 5 tasks, a paired total of 59 tasks cannot show a gain of 1 to 3 tasks. Report per-task changes.
6. Do not start Proposals 2 and 3 on the strength of this round; groups D, E and F above are their territory and this round only shows they are the large part of the failures
   (in EN, 24 of the 49 trigger tasks are never solved by any run, and by the groups above most of them fail outside the flag's scope).

### Fix of Finding 1 and a lesson (2026-11-06)

`GraceBackend` now has a `fixed_subgoals` property that reads the wrapped planner (`robot_agent` branch `sage-v2/homeloop`, `pyplanner_grace.py`).
Tests go through the real path (AssistLoop, GraceBackend, SAGEPlanner with a scripted backend): the capability is seen, also through the
`RecordingPlanner` proxy, and a mixed request (a spoken message to a named person plus a move) gives a fixed block with the exact `Say` sentence while
only the move block reaches the LLM. Cache replay of task 59 EN with the flag on: sub-goal blocks `[2, 1, 0, 1]` steps, `refined_blocks` all false, `Say` with the
exact sentence, no `Announce`; flag off: unchanged (8 LLM calls, three `Announce`). Fake-LLM runs with the flag off are byte-identical to the code before the flag (EN and KO, 12 tasks).

Lesson: a unit test with a stub hides a missing capability on a wrapper. Every flag needs a test through the real construction path, with the real wrapper around the real planner.

## Solution lab round 1c (SAGE-v2, trigger tasks after the wiring fix, 2026-11-06)

Question: with the fixed template sub-goals wired (round 1b, Finding 1 and its fix), does `person_goals` (`robot_agent:sage_lab`) turn failures of the
trigger tasks into successes? Same 59 tasks per language, same conditions (profile `real` plus the sensitivity condition `asr_off`:
`asr.en.app_wer=0, asr.ko.app_cer=0, asr.p_partial=0`; qwen3-vl:8b-instruct; one seed). Everything below is `asr_off`, never a headline.
The new arm ran once per language (run 1) in `results/lab1/trigger_fixed/`; the baseline (run 1, 2) and the lab arm before the fix (run 1, 2) are the
unchanged runs of round 1b in `results/lab1/trigger/`. All 6 shard-sets merged with EXIT=0; `n_error` is 0 in both new runs.

### Result

S = success, F* = false success. "old lab" = `sage_lab` before the fix (fixed blocks never ran), "fixed lab" = `sage_lab` after the fix.

| configuration (59 tasks) | EN success | EN F* | EN trigger (49) | EN control (10) | KO success | KO F* | KO trigger (49) | KO control (10) |
|---|---|---|---|---|---|---|---|---|
| base run 1 / run 2 | 34 / 34 | 4 / 4 | 24 / 24 | 10 / 10 | 17 / 20 | 10 / 9 | 9 / 10 | 8 / 10 |
| old lab run 1 / run 2 | 35 / 35 | 4 / 5 | 25 / 25 | 10 / 10 | 19 / 18 | 11 / 11 | 11 / 10 | 8 / 8 |
| fixed lab (one run) | 35 | 5 | 25 | 10 | 20 | 9 | 11 | 9 |

The five EN tasks of the kill criterion (outcomes in order: base r1, base r2 | old lab r1, r2 | fixed lab):

| task | base | old lab | fixed lab | reading |
|---|---|---|---|---|
| 059 | f f | f f | S | gain, caused by the flag: three fixed blocks (exact `Say`, `MoveTo`) ran, plan passes the gate and succeeds |
| 087 | F* F* | F* F* | F* | hand-over still goes to the speaker spot; the person is only in the say goal (round 1b group B) |
| 095 | f f | S S | f | LOST against the old lab, see "Tasks where the flag acted" |
| 015 | S S | S S | S | solved by the baseline, not the flag |
| 018 | S S | S S | S | solved by the baseline, not the flag |

Other changes against the baseline in the fixed-lab run: EN 023 f to S (a gain; the plan has a fixed `go` block, but the free `put` block was the same as
before, so this may also be model-server variation; not credited), EN 094 S to f (loss, see below), EN 047 f to F* (new false success, see below),
KO 038 F* to S, KO 054 f to F*, KO 064 f to F*, KO 089 S S (old lab) back to f (the baseline fails it too), KO 018 base f/S, fixed f.
Controls: 10 of 10 EN (as before), KO 9 of 10 (base 8 / 10).

### Did the flag act? (count from the kept run debug logs, `HOMELOOP_KEEP_RA_LOGS=1`, 118 episodes with 141 logs)

| part of the flag | EN episodes (of 59) | KO episodes (of 59) |
|---|---|---|
| mixed request (template goal plus a move), so fixed blocks are possible | 33 | 26 |
| fixed template blocks built (unrefined block with its own steps), episodes / blocks | 30 / 41 | 19 / 26 |
| gate operator `unopenable` edited the plan | 3 (069, 094, 095) | 0 |
| goal `dedupe` edited | 1 (089) | 1 (089) |
| gate operator `recipient` edited | 0 | 0 |
| flag acted in any way, episodes | 32 | 20 |
| of these: success / false success / other failure | 17 / 4 / 11 | 6 / 4 / 10 |

The fixed blocks are active now (round 1b: 0 episodes). The operator `recipient` never fired. The hand goals with a person as destination exist
(EN 017, 018, 054, 060, 063, 064, 090; KO 017, 032, 054, 060), but the planner already wrote `Handover <person>` for them, so the operator had nothing
to repair. The 9 EN and 17 KO hand goals whose destination is "spot within your reach" are the speaker, which is the right recipient. The idea behind
`recipient` is therefore not refuted, it is simply not needed on these 59 tasks.

### Verdict against the kill criterion of proposals.md: KILL

- At least 2 of the 5 EN tasks succeed because of the flag: 1 of 5 (059). 095 passed in the old lab arm and fails now; 015 and 018 are baseline successes.
  **This alone kills the candidate.**
- A baseline-solved task lost: EN 094 (S S in base, S in both old lab runs, f now). It is not credited to the flag (below), so this point is not
  what decides.
- False successes: EN 4 / 4 to 5 (047, outside the flag), KO 10 / 9 to 9. No rise that comes from the flag.
- `n_error`: 0.

So the criterion is KILL on the first point; the other points are neutral. The net count is also small: EN 35 against 34 (1 task, 059), KO 20 against
17 / 20 (inside the run-to-run noise of round 1b).

### Tasks where the flag acted and the task still failed (EN 11 failures + 4 false successes, KO 10 + 4)

Cause groups from the logs (task ids as slice numbers; file names are in `robot_agent/core/planning/` of branch `sage-v2/homeloop`).

| group | tasks | cause | where |
|---|---|---|---|
| Hardware fault injected | EN 002, 005, 057, 079; KO 002, 005, 057, 078 | `hw_fault` ends the run ("the robot is not healthy after ...") | `assist_loop.py:2906` |
| Search ends "absent" | EN 021, 053; KO 024, 047, 053, 080 | six places searched, object not found | `assist_loop.py:2965`, `2987`, `3090` |
| Skill failure | EN 048 (drop), 086 (drawer only partly open), 021 (grasp collision); KO 090 (path blocked), 006 and EN 006 (cannot reach the wardrobe handle) | manipulation or navigation failure, not planning | `assist_loop.py:2867`, `3182` |
| Gate gives up on a mixed set | EN 033, 066, 095; KO 033, 066 | after the gate's edits the finding count does not fall ("edits stopped"), the plan stays uncertified and never runs | `subgoal_repair.py:127`, `assist_loop.py:2012-2017` |
| False success from the understanding | EN 054, 069, 071, 087; KO 054, 063, 075, 087 | the understood goals miss a goal or put the recipient on a spot; the plan achieves what was understood. Same in all runs of every arm | upstream of the flag |
| Place instead of a hand-over, or dedupe side effect | KO 089 | after `dedupe` the plan ends `Place spot within your reach` while the robot is at the shelf ("the robot is not at ...") | `assist_loop.py:2867` |
| Understanding variation | EN 094; KO 094 | see below | model server, before the flag |

Cases that decided the verdict:

- **EN 095 (the old gain, now lost).** Fixed blocks built three blocks (`go husband`, `say` with the exact sentence, `go to the dock`); the `put the glass` block
  is still written by the LLM, and its first plan had no `Place`. The operator `unopenable` removed the `Open` / `Close` of the cabinet that cannot
  be opened (gate log: "gate repair (unopenable): 2, then 1 critical finding(s) left"), but one finding ("does not achieve: Place the glass") remained, the count did not
  fall, and the edits stopped (`subgoal_repair.py:127`). In round 2 the planner wrote `Open upper_cabinet` / `Close` again and the plan was
  uncertified (`assist_loop.py:2014`). In the old lab arm the LLM block happened to contain the `Place`, so the same operator was enough. The cause
  is an LLM block that varies, not the fixed blocks.
- **EN 094 (baseline solved, now failed).** Not the flag. The first understanding call returned `infeasible` with the question "Where are the keys located?"
  (cache of the fixed run); the same prompt returned `clear` in the baseline and in the old lab arm. The understanding prompt does not depend on the flag. After
  two questions the run searched six places and ended "could not find the keys" (`assist_loop.py:2965`).
- **EN 047 (new false success).** `nfix` is 0 for this task and only baseline gate operators (`hoist`, `unclose`) ran; the understanding changed its goal text
  from "drink" to "white milk carton" between calls. Not the flag.
- **EN 059 (the one real gain).** Blocks `[2, 1, 7, 1]`, `refined_blocks` `[False, False, True, False]`, the exact `Say`; the free `put` block is still LLM-written
  and adds an `Announce`, but the gate accepts the plan and the run succeeds.

### Noise

EN repeats of the same code were identical in round 1b (0 of 59 tasks differ in success), so one run per arm is enough for EN, and the 059 gain is a
real effect of the fixed blocks on this task. The loss of 095 shows the opposite: where the LLM-written block still decides the outcome, the same flag gives
different results in different runs (here between the old and the fixed lab arm; the plans differ because the prompts differ). KO repeats differ by up to
5 tasks, so one KO run cannot support any claim. One run of the fixed arm is a limit of this round; it is not enough to overturn a KILL on a criterion that needs 2 gains.

### Verdict and next step

**KILL** for `person_goals` as a candidate to promote: 1 of the 5 EN tasks gained because of the flag (059), 095 does not hold, the other two are baseline solved,
and the 14 unsolved flag-acted failures are in groups the flag does not reach (injected faults, search, skill failures, understanding). The fixed
sub-goal wiring is correct and is kept in the code behind the flag (default off), with its real-path test. Do not record the idea as refuted in general:
the part that would matter, a gate that cannot give up on a mixed set, depends on the free `put` block.

Next step, as a new proposal and not as a continuation: the failures that remain on the trigger tasks are (a) the free block after a fixed block (095, 033,
066), where the LLM still decides whether `Place` / `Handover` is in the block, and (b) the understanding giving the person-recipient a spot (087, 054, 063, 075).
Both are best checked offline on the cached traces of this round (no GPU) before another LLM run: (a) compile the deliver block as a fixed block too when the
object, its source and the recipient are all known (the lab already compiles `go` and `say`), (b) an understanding-side rule that moves a named person from the say
goal to the destination of the hand goal in the same request. Neither is started here.

## Performance decomposition (R6 step 0)

Date 2026-11-06. Code: robot_agent and embodiplan at the head of `sage-v2/homeloop`, homeloop_bench `a95fd4b`. Model `qwen3-vl:8b-instruct`, profile `real`
(simulated speech recognition, injected failures), seed 0. Raw results: `results/perf1/` (`understand/{train,dev}`, `e2e/*`, driver `run.sh`). No run failed:
all 12 shard logs, the 4 merges, the 2 understanding runs and the oracle and naive runs ended with EXIT=0, `n_error` is 0 in every summary. The exit-4
condition of `understand-eval` (a run that ends before the understand step) was not examined separately. HTTP 500s from the LLM server were not checked
for; nothing stalled. The analysis scripts are throw-away (python over `records.jsonl` and `episodes.jsonl`); every number below is a count from those files.

### End-to-end table, dev tasks 0..99 (one run, 3 shards, seed 0)

`sage_gold` is PRIVILEGED (gold goals, no understand step): a diagnostic ceiling, never a headline. LLM calls are the planner's calls per run; the KO
numbers include the translation calls (sage 453, sage_gold 489).

| lang | planner | success | 95% CI | false success | LLM calls (per episode) |
|---|---|---|---|---|---|
| EN | oracle (privileged) | 83 | 0.74-0.89 | 0 | 0 |
| EN | naive (privileged) | 50 | 0.40-0.60 | 3 | 0 |
| EN | sage | 50 | 0.40-0.60 | 7 | 619 (6.2) |
| EN | sage_gold (privileged) | 56 | 0.46-0.65 | 6 | 391 (3.9) |
| KO | oracle (privileged) | 83 | 0.74-0.89 | 0 | 0 |
| KO | naive (privileged) | 50 | 0.40-0.60 | 3 | 0 |
| KO | sage | 30 | 0.22-0.40 | 19 | 1055 (10.6) |
| KO | sage_gold (privileged) | 56 | 0.46-0.65 | 6 | 876 (8.8) |

oracle and naive read the task directly, so their numbers do not depend on the language. sage_gold is the same in EN and KO (56 and 56), as it should be:
the gold goals do not depend on the text.

### Decomposition

| | EN | KO |
|---|---|---|
| loss from understanding = sage_gold - sage | 6 points (56 - 50) | 26 points (56 - 30) |
| loss from execution and the world = oracle - sage_gold | 27 points (83 - 56) | 27 points (83 - 56) |
| total, oracle - sage | 33 | 53 |

Paired by task (same 100 tasks): EN sage_gold succeeds where sage fails on 12 tasks, the reverse on 6 (sign test p = 0.24: the EN understanding loss is
**not** resolved at n = 100). KO: 31 against 5 (p = 1e-5: the KO understanding loss is real). Execution and the world: the oracle succeeds where sage_gold
fails on 30 (EN) and 31 (KO) tasks, the reverse on 3 and 4.

Reading the failures of sage (EN 50, KO 70) against the first reading of the understanding evaluation (same tasks, text after speech recognition):

| first reading | EN failures | KO failures |
|---|---|---|
| exact (the goals were right, execution failed) | 25 (3 false successes) | 20 (8 false successes) |
| empty (refused or no goal) | 14 | 17 |
| goals missing and/or added | 11 (3 false successes) | 31 (8 false successes) |
| task to refuse | 0 | 2 |

Success rate of the tasks to act on, by the first reading: EN exact 26 of 48 (54%), not exact 13 of 33 (39%); KO exact 17 of 34 (50%), not exact 6 of 47
(13%). The KO loss is the not-exact readings.

### Understanding metrics (`understand-eval`, 300 tasks, split train and dev, both text conditions, 4 records per task)

Headline = feasible tasks, no refused part (train n = 964, dev n = 972). Exact = the goal set equals the gold set.

| split | exact | atom precision | atom recall | dropped | spurious | confident wrong (of confident) |
|---|---|---|---|---|---|---|
| train | 0.464 | 0.702 | 0.703 | 526 | 528 | 292 (0.407) |
| dev | 0.534 | 0.757 | 0.741 | 464 | 426 | 258 (0.346) |

By condition (exact / atom precision / atom recall / confident wrong):

| condition | train | dev |
|---|---|---|
| EN clean | 0.568 / 0.759 / 0.819 / 67 | 0.638 / 0.803 / 0.848 / 62 |
| EN asr | 0.456 / 0.723 / 0.677 / 67 | 0.547 / 0.800 / 0.734 / 49 |
| KO clean | 0.465 / 0.694 / 0.716 / 74 | 0.535 / 0.724 / 0.748 / 74 |
| KO asr | 0.365 / 0.627 / 0.600 / 84 | 0.416 / 0.698 / 0.634 / 73 |

Speech recognition costs 9 to 12 exact points in both languages; KO is 9 to 13 points below EN in every condition. By structure (both languages, exact /
confident wrong of confident):

| structure | train | dev |
|---|---|---|
| single | 0.639 / 0.161 | 0.668 / 0.134 |
| with_context | 0.679 / 0.245 | 0.808 / 0.128 |
| conjunction | 0.421 / 0.404 | 0.600 / 0.267 |
| correction | 0.417 / 0.255 | 0.398 / 0.429 |
| shared_object | 0.321 / 0.624 | 0.517 / 0.450 |
| sequence | 0.350 / 0.615 | 0.365 / 0.577 |
| ordered | 0.231 / 0.747 | 0.410 / 0.480 |
| conditional | 0.058 / 0.933 | 0.067 / 0.925 |

On dev by language, exact: EN single 0.70, KO single 0.64; EN conjunction 0.83, KO conjunction 0.38; EN correction 0.52, KO correction 0.27 (KO recall 0.47);
conditional 0.07 in both. Tasks to refuse: exact 0 of 56 (dev), 0 of 52 (train), and every one of them is a "confident wrong" reading. Tasks that should
be asked about: exact 0.21 (dev), 0.35 (train).

**Limits of this measure (read before using the numbers).** The evaluation judges the first reading only. The hazard gate, the which-one question and the
read-back come later in the loop and are not run, so (a) the refuse and ask rows overstate the loss (end to end, sage refuses 5 of 5 EN and 3 of 5 KO
refuse tasks), and (b) an extra `go(place)` atom is counted as spurious although it is usually harmless.

#### Where the readings go wrong (dev and train, tasks to act on, mixed tasks left out; atoms counted)

Each dropped gold atom is paired with a spurious atom of the same family; the unpaired rest is "dropped only" and "spurious only".

| error | dev EN | dev KO | train EN | train KO |
|---|---|---|---|---|
| dropped only: `give` to a person (fetch, bring me) | 68 | 81 | 56 | 88 |
| dropped only: `put_on` / `put_in` | 56 | 53 | 62 | 60 |
| dropped only: `go(dock)` after the last step | 16 | 22 | 17 | 19 |
| spurious `go` (mostly `go(place)`, "check the counter") | 92 | 60 | 74 | 46 |
| spurious `open` / `close` / `say` / `put` / `give` | 43 | 83 | 78 | 129 |
| wrong person (`give` / `say`) | 13 | 22 | 28 | 37 |
| wrong object (a name that is no class, `?name`) | 2 | 28 | 7 | 32 |
| wrong destination | 4 | 27 | 9 | 20 |
| `give` read as `put_on` with no person | 17 | 26 | 22 | 25 |

Readings with no goal at all on a task to act on (dev, 245 tasks per language and condition): EN clean 20, EN asr 50, KO clean 24, KO asr 46; the model
says `ambiguous` (the larger part) or `infeasible`. End to end, sage succeeds on 5 of 17 such tasks in EN and 3 of 16 in KO; sage_gold on 8 of 17 and 6 of 16.

#### Ten real readings per language (dev, from `results/perf1/understand/dev/records.jsonl`)

Prompt line numbers are in `robot_agent/core/planning/assist_loop.py` (`UNDERSTAND_PROMPT`, lines 309-336) and `goals.py` of the same package.

EN:

1. 278 clean, "bring me that orange, and then bring my husband the white towel": no goal; status `infeasible`, "cannot find or retrieve an orange or a white
   towel without knowing their locations". The prompt says unknown objects are fine and a missing place is handled separately (`assist_loop.py:322-324`);
   the model ignores it.
2. 281 clean, "go tell my husband dinner's ready and grab the yellow book for me ... right in my hand": `go(husband)`, `say`, then three `go(spot within your
   reach)`. The bring-me part became `go` goals and the object was lost. The only way to name a person as destination is the word "me"
   (`assist_loop.py:330-331`); the `go` kind line (`goals.py:38-39`) offers a goal without an object.
3. 299 clean, "Hand that red book to Grandpa, then tell him dinner's ready": `give(red book, user)`, the book goes to the speaker. Same prompt line: a named recipient
   other than "me" has no slot in the example (`assist_loop.py:330-331`). Confident.
4. 087 asr, "first tell my husband to come to the kitchen, and then take the wallet to him": `give(wallet, partner_a)`, the speaker; "him" is the husband (partner_b).
   Confident, plus a spurious `go(counter@kitchen)`.
5. 286 clean, "if the bleach is there, it goes in the storage cabinet. If not, leave it. And fetch the towel": `go(utility_shelf)` before the fetch. The gold
   (condition false) has no step for the bleach. The prompt has no rule for "if ... otherwise" (`assist_loop.py:320-333`) and `go` invites a "check" goal.
6. 246 asr, "if the milk is still out on the kitchen table, put it in the fridge. If not, never mind. And let my husband know": `go(table@kitchen)` and `say`;
   the put-in is dropped although the condition is true. Same missing rule.
7. 008 clean, "put the blue book on the armchair, no, actually on the TV stand, and bring me the water bottle": `go(armchair)` plus the right `put_on` and `give`.
   The corrected place is kept as a `go`. No correction rule in the prompt.
8. 295 clean, "My pink towel has gone missing. Would you find it for me and bring it over": `open(bath_cabinet)` before `give`. An invented search step, confident.
9. 009 asr, "stash the bleach in the kimchi fridge": `put_in(bleach, kimchi_fridge)` (gold: refuse, a chemical in a food fridge). `unsafe` in the prompt
   lists throwing and fire only (`assist_loop.py:321`); the hazard gate is a later step.
10. 062 clean, "Put the mug on the nightstand": `put_on(mug, nightstand)`, confident, no question. The gold expects a question (several mugs); the question
    belongs to the later which-one step, which this evaluation does not run.

KO:

1. 259 clean, "주스랑 파란 과자 좀 갖다줄 수 있어요?": no goal, `infeasible` (cannot find items from unknown locations). Same rule as EN 1 (`assist_loop.py:322-324`).
2. 169 clean, "빨간 머그컵 가져다 주실 수 있어요?": no goal, `ambiguous` ("does not specify where the red mug is"), although the prompt says a missing place is not
   ambiguity (`assist_loop.py:323-324`).
3. 063 clean, "아버님께 먼저 물 좀 드시라고 말씀해 주시고, 그 다음에 안경을 가져다주실 수 있을까요?": `give(glasses, user)`; the glasses are for the grandfather. Confident.
   `assist_loop.py:330-331`.
4. 232 asr, "우선 남편한테 가서 주방으로 잠깐 오래고 말해 주고, 그다에 하그얀 수건을 갖다주세요": `give(white towel, partner_a)`, gold partner_b. The model asked "What should I say?".
5. 177 asr, "주병을 다시 냉장고에 넣은 다음에 아딜한테, 아 아니다, 빠한테 ... 전해 줄래요?": `put_in(?bottle)` and `say(child)` for dad. Two speech-recognition errors (a word for the juice, the
   person) and the model keeps the first person of the correction.
6. 215 clean, "먼저 과자 봉지를 싱크대 위에 올려주시고 ... 충전하러 돌아가셔도 돼요": `put_on(snack, kitchen_sink)` (gold counter) and no `go(dock)`. The dock goal is
   dropped (the request words it permissively, "돌아가셔도 돼요"); this happens in 22 KO dev readings.
7. 198 asr, "붐엌칼이 조린대엑 있으면 주방 서랍에 넣어 주시고, 없으면 그냥 두세요 ... 유리컵 좀": `put_in(knife, drawer)` unconditionally and `give(cup)` (gold: glass). Condition rule missing,
   plus the class "cup" for 유리컵.
8. 053 asr, "우율를 김치 냉장고에 낳고 문을 닫아 주실래요?": `put_in(?우율, kimchi_fridge)`: the misheard noun is kept as an object name that is no class and the reading is
   confident and `clear`, so no question is asked at this step.
9. 099 clean, "수납장이 가득 차 있네요. 락스를 김치 냉장고에 넣어 주실 수 있을까요?": `put_in(?liquid soap, kimchi_fridge)`, gold refuse. The model also
   renames the bleach. Same hazard point as EN 9.
10. 072 asr, "우유팩을 넣어 두세요": `put_on(milk, dining_table)`, the destination is invented and confident. The prompt tells the model that a missing place is handled separately
    (`assist_loop.py:323-324`) and the model fills it in anyway.

Data note (not a robot fault): for KO dev 0129 and 0158 and train 0048 the text and the gold of a **correction** disagree. In `data/tasks/dev.jsonl` task 158
the gold `final_dest` is `upper_cabinet`, but both texts say "upper shelf, sorry, I meant the nightstand" (final nightstand). The paraphrase seems to swap
first and final place in some correction tasks. How many tasks are affected is not measured; it lowers the correction rows of both languages and the
KO correction recall in particular. To check before using correction results.

### Where sage_gold still fails (dev 0..99, 44 failures per language, classes read from the episodes and the kept run logs)

Rules: classes are exclusive and tested in the order of the table. "Oracle also fails" = the privileged oracle fails the same task (world, injected
faults).

| class | EN | KO | oracle also fails (EN/KO) |
|---|---|---|---|
| A. plan gate: the gold conversion emits a `deliver` goal (hand to a person who is not the speaker); the robot has no `WaitForUnload` and the gate refuses ("I could not make a plan that passes my checks") | 8 | 8 | 1 / 1 |
| B. plan gate: `Handover ... to spot within your reach` judged not to achieve the goal | 2 | 1 | 0 / 0 |
| C. plan gate: other (hand state, step order, `upper_cabinet` cannot be opened, say) | 2 | 4 | 0 / 0 |
| D. false success: "Task completed", goal atom not met | 6 | 6 | 1 / 1 |
| E. injected hardware fault, not recovered | 11 | 10 | 6 / 7 |
| F. step or LLM budget | 1 | 0 | 0 / 0 |
| G. search: object not found (`absent`, no source given) | 10 | 10 | 4 / 3 |
| H. blocked, unreachable, perception, grasp or place fault not recovered | 3 | 5 | 2 / 1 |
| I. other | 1 | 0 | 0 / 0 |
| total | 44 | 44 | 14 / 13 |

Class A is an artifact of the diagnostic. `homeloop_bench/gold_goals.py:71` converts a hand delivery to another person into the goal kind `deliver`, which robot_agent
compiles to `MoveTo` + `WaitForUnload` (`goals.py:43`); the robot has no `WaitForUnload`, and the gate message is "the robot has no action WaitForUnload". The
understanding of sage never writes a `deliver` goal (0 of 2400 readings; it writes `on` with the person as destination), so sage does not meet this. sage_gold is
therefore pessimistic: the oracle succeeds on 7 of the 8 A tasks in each language. If they were solved at the oracle rate the ceiling would be about 63, not 56
(estimate, not measured). The gate messages come from the kept run logs of the sage_gold window, matched to the tasks by the request text (199 of 200 task-language pairs matched).
Class G is partly also a diagnostic effect: the gold goals have no source place, so the robot searches; sage gets the place from the words.

sage itself ends with the gate text "passes my checks" in 6 EN and 2 KO episodes (final text only, so B and C are not separated); those are real robot_agent behaviour.

### The three most valuable things to improve next (ranked)

1. **Understanding of Korean and of speech-recognition text (the dominant loss in KO, 26 of 53 points; false success 19 against 6).** Evidence: KO exact 0.475
   against EN 0.593 on dev; KO asr 0.416; paired sage_gold-sage 31 against 5; KO tasks with a not-exact first reading succeed 13% against 39% in EN; 28 `?name`
   objects and 22 wrong persons in KO dev; 11 of the 19 KO false successes follow a first reading that is not exact. Three concrete targets, each general: (a) a fetch or bring request
   without a place must give goals, not `infeasible` / `ambiguous` (dropped `give`: 68 EN, 81 KO; empty readings 20-50 per 245), (b) a recipient other than the speaker
   (`assist_loop.py:330-331`), (c) an object name that is no class must not be a confident reading (match it to the known names, or ask). Fast inner loop:
   `understand-eval` on train, `--lang ko --text asr` (and EN as the control), 300 tasks, one LLM call per task, cached; the metrics to move are exact, atom recall and confident wrong.
   Confirmation: the dev 0..99 end-to-end run in KO (and EN, to see no regression), two runs, paired.
2. **Make the ceiling honest, then work on the plan gate for hand delivery to a person (execution side).** First change `gold_goals.py:71` so a hand
   delivery to another person is written like sage writes it (`on` with the person as destination) and rerun the 8 A tasks per language (sage_gold, about 17 minutes
   for the whole slice, a few minutes for 8 tasks). This corrects the 27-point execution loss by up to 8 points per language (estimate). The real robot_agent part is
   B and C in the table (sage_gold 4 EN / 5 KO, sage 6 EN / 2 KO gate refusals): the planner's `Handover` plan not accepted for the goal, hand state and order
   findings. Inner loop: `sage_gold` on the task ids of the classes A, B, C (about 12 tasks, no understanding noise); confirmation: the full dev 0..99, two runs, EN and KO.
3. **Fewer false goals: conditionals, corrections and invented steps.** Evidence: conditional exact 0.07 with 92% confident wrong (83 spurious atoms in dev, 90 in
   train), spurious `go(place)` 92 (EN) / 60 (KO), spurious `open` / `say` / `put`, a correction kept as a `go`. The prompt has no rule for "if ... otherwise" or for a correction
   (`assist_loop.py:320-333`). End to end the share is small on this slice (4 conditional tasks in 100; sage 2 of 4 EN, 1 of 4 KO, against 4 and 3 for sage_gold), so the expected
   gain is about 2 tasks per language on 100, and it is the largest source of spurious atoms in the evaluation (83 of 426 on dev). Inner loop: `understand-eval` on train, structures conditional, correction,
   ordered, sequence only (use `--tasks FILE` for a subset). Confirmation: end to end on a slice that is rich in these structures, not on dev 0..99. Before this, check
   the paraphrase swap of the correction tasks (data note above), or the correction rows are measuring the data.

Not ranked, but visible: injected hardware faults that the robot does not recover (E, 11 / 10 per 100, about half also fail the oracle), the false-success rate of the
execution itself (D, 6 per 100 in sage_gold) and the search without a source (G, 10 per 100).

### Measurement plan and noise caveat

- **Fast inner loop for the understanding:** `homeloop-bench understand-eval` (one call per task, no motion, identical records for identical arguments, cached).
  Measured cost today: 1200 records in 4547-5097 s while 12 other LLM clients shared the server (about 4 s per record); alone, less. Use train to tune, dev to validate, never test.
  Use `--tasks FILE` and `--limit` to run a structure or language subset in minutes.
- **Fast inner loop for the execution:** `robot_agent:sage_gold` on the task ids of one failure class (no understanding noise). It does not replace the confirmation.
- **Confirmation:** the end-to-end dev 0..99 run (EN and KO, 3 shards each, at most 8 clients, container up only for the run and stopped after), two runs, paired by task.
  Headline stays `robot_agent:sage`; `sage_gold` is a label-privileged diagnostic.
- **Noise.** One run of 100 tasks has a 95% interval of about +-10 points (the summaries above). Run-to-run noise measured earlier is about 3 tasks in 50 (EN repeats were identical in round 1b; KO repeats
  differ by up to 5 tasks). Here the EN understanding loss (6 points, 12 against 6 discordant tasks) is inside that noise and should not drive a decision; the KO loss (26 points) and the
  27-point execution loss are far outside it. Offline estimates over-predicted before (the `person_goals` flag: predicted +3, got +1), so a gain in `understand-eval` is a reason to
  run the confirmation, not a result. A change counts only when the paired end-to-end difference is at least 6 tasks of 100 in the same direction in two runs, or when the discordant
  tasks (gain against loss) are clearly one-sided.


## Solution lab round 2 (SAGE-v2, understand-eval, 2026-11-06)

Question: do the two prototypes of round 2 (`proposals.md` in the lab folder) raise the quality of the understand step? Both are
opt-in flags of robot_agent (branch sage-v2/homeloop, default off, tests through the real loop), registered here as variants:

| variant | flags | extra LLM calls |
|---|---|---|
| `robot_agent:sage_ground2` | `go_steps` + `kind_anchor` + `name_canon` (grounding chain v2) | 0 |
| `robot_agent:sage_g2_go`, `sage_g2_kind`, `sage_g2_name` | one option each (ablations) | 0 |
| `robot_agent:sage_reask` | `reask_abstain` (V1: one directed re-understand of a goal-less "where is it" reading) | +1 on about 8 % of records |

The wild card I1 (understand schema v2) was not in scope. No end-to-end episode was run in this round, and the test split was not
opened. `understand-eval` stops at the first reading, so it cannot see the read-back, the hazard gate or the clarify dialogue that
follow. A gain here is a reason to run the end-to-end gate, not a result (see the noise caveat of the R6 section).

### Method

- Instrument check. With every flag off, `records.jsonl` and `summary.json` of the train run are byte-identical to `results/perf1/understand/train`
  (1200 records), and `dev` 0..299 as well.
- Pilot: tasks 0..4 of train, EN and KO, both text conditions (20 records). Flag off: identical to perf1. `sage_ground2`: 4 readings change, 3 of them
  drop an `open` that nobody asked for (right) and 1 is a loss (below); `sage_reask` fires on none of them.
- Pairing. The baseline LLM cache of perf1 is copied into each arm's `--out`. A flag that only post-processes the reading draws nothing new,
  so every arm is a paired replay on the same model readings (exact counts, no redraw noise). `sage_reask` is the only arm that makes
  new calls: 96 on train, 98 on dev. The model is `qwen3-vl:8b-instruct`, `--profile real --seed 0`, both text conditions, EN and KO.
- Fresh slice. dev 300..599 had not been read by anyone in this lab. The baseline was run once on GPU 0 (6 shards, 1200 records,
  `OLLAMA_NUM_PARALLEL=6`, 8 clients at most, container stopped afterwards), then every arm was replayed from that cache.
- Disclosure. The `go` rule and the open anchor were refined in the replay lab after reading train AND dev 0..299 losses, so dev 0..299 is not clean
  for them; only the fresh slice is. Before the dev confirmation I widened the Korean open endings (`열 수`, `열지`, `열자`, `열까`, `열래`, `열도록`, ...)
  from my own grammar knowledge (no reference corpus or analyser was available; `kiwipiepy` and `konlpy` are not installed). It changed no train count.
  The forms are still unchecked by a native speaker.
- A bench bug found on the way: `understand-eval` stops at the first `understand_check` event, which it reads as "the loop asked to repeat".
  The re-ask reports itself with such an event (`reask: true`), so the first `sage_reask` run (both splits) came out as 96 empty "repeat" readings.
  The adapter now ignores an `understand_check` that carries `reask`. The re-ask calls were cached, so the corrected run re-used them.

### Result 1: grounding chain v2 (`sage_ground2`), headline population (feasible tasks, no refused part), paired

Replay check against the lab's monkeypatch arms (must agree within +-2): train chain +42 / -1 (lab +42 / -2), go_steps +19 / 0 (+19 / 0),
kind_anchor +11 / -1 (+11 / -2), name_canon +4 / 0 (+4 / 0); dev 0..299 chain +48 / 0 (+48 / -2). All within the bound.

Train (300 tasks, 964 headline records):

| condition | n | exact b -> a | gains/losses | precision b -> a | recall b -> a | dropped b -> a | spurious b -> a | confident wrong b -> a | asked-on-exact b -> a |
|---|---|---|---|---|---|---|---|---|---|
| EN clean | 241 | 137 -> 151 (+5.8 pt) | +14 / -0 | 0.759 -> 0.818 | 0.819 -> 0.819 | 80 -> 80 | 115 -> 81 | 67 -> 54 | 3 -> 4 |
| EN asr | 241 | 110 -> 121 (+4.6 pt) | +12 / -1 | 0.723 -> 0.786 | 0.677 -> 0.673 | 143 -> 145 | 115 -> 81 | 67 -> 58 | 2 -> 5 |
| KO clean | 241 | 112 -> 121 (+3.7 pt) | +9 / -0 | 0.694 -> 0.759 | 0.716 -> 0.725 | 126 -> 122 | 140 -> 102 | 74 -> 65 | 9 -> 10 |
| KO asr | 241 | 88 -> 95 (+2.9 pt) | +7 / -0 | 0.627 -> 0.681 | 0.600 -> 0.603 | 177 -> 176 | 158 -> 125 | 84 -> 77 | 7 -> 12 |
| EN | 482 | 247 -> 272 (+5.2 pt) | +26 / -1 | 0.742 -> 0.803 | 0.748 -> 0.746 | 223 -> 225 | 230 -> 162 | 134 -> 112 | 5 -> 9 |
| KO | 482 | 200 -> 216 (+3.3 pt) | +16 / -0 | 0.662 -> 0.721 | 0.658 -> 0.664 | 303 -> 298 | 298 -> 227 | 158 -> 142 | 16 -> 22 |
| all 4 | 964 | 447 -> 488 (+4.3 pt) | +42 / -1 | 0.702 -> 0.763 | 0.703 -> 0.705 | 526 -> 523 | 528 -> 389 | 292 -> 254 | 21 -> 31 |

Dev 0..299 (972 headline records; not clean for the go rule and the open anchor, see Disclosure):

| condition | n | exact b -> a | gains/losses | precision b -> a | recall b -> a | dropped b -> a | spurious b -> a | confident wrong b -> a | asked-on-exact b -> a |
|---|---|---|---|---|---|---|---|---|---|
| EN clean | 243 | 155 -> 173 (+7.4 pt) | +18 / -0 | 0.803 -> 0.880 | 0.848 -> 0.848 | 68 -> 68 | 93 -> 52 | 62 -> 44 | 5 -> 5 |
| EN asr | 243 | 133 -> 144 (+4.5 pt) | +11 / -0 | 0.800 -> 0.870 | 0.734 -> 0.734 | 119 -> 119 | 82 -> 49 | 49 -> 38 | 2 -> 4 |
| KO clean | 243 | 130 -> 142 (+4.9 pt) | +12 / -0 | 0.724 -> 0.790 | 0.748 -> 0.754 | 113 -> 110 | 128 -> 90 | 74 -> 62 | 9 -> 9 |
| KO asr | 243 | 101 -> 108 (+2.9 pt) | +7 / -0 | 0.698 -> 0.760 | 0.634 -> 0.643 | 164 -> 160 | 123 -> 91 | 73 -> 64 | 9 -> 10 |
| EN | 486 | 288 -> 317 (+6.0 pt) | +29 / -0 | 0.802 -> 0.875 | 0.791 -> 0.791 | 187 -> 187 | 175 -> 101 | 111 -> 82 | 7 -> 9 |
| KO | 486 | 231 -> 250 (+3.9 pt) | +19 / -0 | 0.711 -> 0.776 | 0.691 -> 0.699 | 277 -> 270 | 251 -> 181 | 147 -> 126 | 18 -> 19 |
| all 4 | 972 | 519 -> 567 (+4.9 pt) | +48 / -0 | 0.757 -> 0.826 | 0.741 -> 0.745 | 464 -> 457 | 426 -> 282 | 258 -> 208 | 25 -> 28 |

Fresh slice, dev 300..599 (952 headline records; the clean test of generalisation):

| condition | n | exact b -> a | gains/losses | precision b -> a | recall b -> a | dropped b -> a | spurious b -> a | confident wrong b -> a | asked-on-exact b -> a |
|---|---|---|---|---|---|---|---|---|---|
| EN clean | 238 | 137 -> 151 (+5.9 pt) | +14 / -0 | 0.776 -> 0.844 | 0.807 -> 0.807 | 85 -> 85 | 103 -> 66 | 57 -> 45 | 9 -> 11 |
| EN asr | 238 | 107 -> 114 (+2.9 pt) | +7 / -0 | 0.755 -> 0.813 | 0.651 -> 0.651 | 154 -> 154 | 93 -> 66 | 45 -> 39 | 7 -> 9 |
| KO clean | 238 | 128 -> 141 (+5.5 pt) | +13 / -0 | 0.747 -> 0.803 | 0.741 -> 0.748 | 114 -> 111 | 111 -> 81 | 62 -> 51 | 17 -> 20 |
| KO asr | 238 | 99 -> 108 (+3.8 pt) | +9 / -0 | 0.692 -> 0.746 | 0.596 -> 0.599 | 178 -> 177 | 117 -> 90 | 65 -> 56 | 14 -> 18 |
| EN | 476 | 244 -> 265 (+4.4 pt) | +21 / -0 | 0.766 -> 0.830 | 0.729 -> 0.729 | 239 -> 239 | 196 -> 132 | 102 -> 84 | 16 -> 20 |
| KO | 476 | 227 -> 249 (+4.6 pt) | +22 / -0 | 0.721 -> 0.776 | 0.669 -> 0.673 | 292 -> 288 | 228 -> 171 | 127 -> 107 | 31 -> 38 |
| all 4 | 952 | 471 -> 514 (+4.5 pt) | +43 / -0 | 0.744 -> 0.803 | 0.699 -> 0.701 | 531 -> 527 | 424 -> 303 | 229 -> 191 | 47 -> 58 |

"b" is the baseline `robot_agent:sage`, "a" the arm. Precision is matched / (matched + spurious), recall matched / (matched + dropped), both micro over atoms.
"Confident wrong" is a reading the robot would act on without asking that is not exact; the asked-on-exact column counts exact readings that the model still turned into a question.

Sub-options (exact gains / losses, headline, pooled over the four conditions):

| option | train | dev 0..299 | fresh dev 300..599 |
|---|---|---|---|
| `go_steps` | +19 / -0 | +29 / -0 | +34 / -0 |
| `kind_anchor` (open only) | +11 / -1 | +7 / -0 | +5 / -0 |
| `name_canon` | +4 / -0 | +6 / -0 | +4 / -0 |
| chain (all three) | +42 / -1 | +48 / -0 | +43 / -0 |

Clarify (ask) and refuse tasks, chain vs baseline:

| set | confident readings b -> a | confident wrong b -> a | asked b -> a | refused b -> a |
|---|---|---|---|---|
| ask, train (164) | 99 -> 60 | 47 -> 39 | 54 -> 94 | 18 -> 18 |
| ask, dev 0..299 (164) | 78 -> 50 | 44 -> 39 | 78 -> 106 | 29 -> 29 |
| ask, fresh (168) | 72 -> 44 | 44 -> 35 | 76 -> 104 | 32 -> 32 |
| refuse, train / dev / fresh (52 / 56 / 52) | 33 -> 33 / 32 -> 32 / 24 -> 23 | same | 17 -> 17 / 20 -> 20 / 26 -> 27 | 16 -> 16 / 22 -> 22 / 24 -> 24 |

Every difference was read (a script splits the changed records by which option changed them; a worse or lost record is printed with the heard text, base, arm and gold):

- **go_steps** (train 39 + 19, dev 49 + 29, fresh 39 + 34 changed head records): in every changed record the base set had one or more steps as end states
  (a `go` to the person who is addressed, to the speaker, to the source of a later move); all become `better` or `exact`. One worse record in train
  (`hl-train-000205`, EN asr): the model wrote `go(dock)` BEFORE a `give` and the rule read the dock as the source of that move; the base set was not exact either (the dock was in the wrong place).
  Fresh slice: none. The rule never fires on a set with only `go` goals.
- **kind_anchor** (open): drops an `open` end state the words carry no open verb for. In ask and refuse tasks the same drop makes the set smaller (refuse spurious atoms 79 -> 63 on train)
  without changing a status. One loss in train (`hl-train-000001`, EN asr): ASR turned "open" into "one", the open verb is gone from the heard text, the gold set has the `open` and the rule removes it.
  One fresh record gets worse by one atom (`hl-dev-000341`, KO asr: ASR "열곰" for "열고"; the base was already not exact). This is the cost of anchoring on heard words, and the reason the rule needs another goal to remain.
  The `close` half is not in the chain (a policy decision: a fridge is left open).
- **name_canon**: 4 / 6 / 4 gains and, in train, 11 same-error records: a name was renamed onto a memory name and the set is still wrong for another reason (the most visible: "bottle" -> "juice" in one KO record, the head noun matched a different object).
  The which-one question fires on ask tasks: the ask rows lose 28 to 39 confident readings and gain as many questions, and the chain does not add a question to the clean tasks beyond 8 / 5 / 6 asked records (asked-on-exact +7 on train from this option).
- Interaction: in train 130 head records change, in dev 126, in fresh 119; no record changes by a third option's interaction alone.

Kill criteria of `proposals.md` (3.1), all passed:

| criterion | train | dev 0..299 | fresh |
|---|---|---|---|
| flag off byte-identical to perf1 | yes | yes | n/a (baseline is this run) |
| replay within +-2 of the lab arms | yes | yes | n/a |
| sub-option net >= +3 and losses <= a third of gains | go +19, kind +10, name +4 | go +29, kind +7, name +6 | go +34, kind +5, name +4 |
| pooled net >= +25 (train), >= +2 points (fresh), no sub-option below 0 | +41 | +48 | +4.5 points (+43), none below 0 |
| asked-on-exact rises by <= 1.5 points | +1.0 | +0.3 | +1.2 |
| ask-task confident readings do not rise, refuse rows do not change | 99 -> 60, refuse confident unchanged (refuse atom counts fall) | 78 -> 50, unchanged | 72 -> 44, 24 -> 23 |

Not killed. `name_canon` is the smallest option and gets its gain only on KO in this catalog; it is also the one most favoured by catalog-derived memory names (critique 0 and 1),
so a real detector with free-form labels would give less. Report it with and without.

### Result 2: abstention re-ask (`sage_reask`)

Train, 300 tasks: the re-ask fired on 96 records (75 headline, 17 clarify, 4 refuse). Headline population, paired:

| | exact b -> a | gains / losses | precision | recall | dropped | spurious | confident wrong |
|---|---|---|---|---|---|---|---|
| train all 4 | 447 -> 479 (+3.3 pt) | +32 / -0 | 0.702 -> 0.708 | 0.703 -> 0.743 | 526 -> 455 | 528 -> 544 | 292 -> 301 |
| dev 0..299 all 4 (informational) | 519 -> 539 (+2.1 pt) | +20 / -0 | 0.757 -> 0.751 | 0.741 -> 0.773 | 464 -> 407 | 426 -> 458 | 258 -> 272 |

Of the 75 headline triggers, 47 re-readings were taken (32 exact, 15 wrong) and 28 kept the first question. That passes the first three kill criteria
(accepted-and-exact 32 >= 19; exact more often than wrong). It fails the fourth: **on the 17 clarify triggers the re-reading was taken for 10 (limit 5)**, so the
ask-task confident readings rise from 99 to 109 and the confident-wrong ones from 47 to 53. Examples (heard text, in short): "put the wallet away somewhere" becomes
`put_in(wallet, drawer@kitchen)` (the gold place is another room, and the person had left the place open); "bring grandpa the mug" becomes `go(grandpa)`;
"put the socks in the closet and grab my book" loses the `put_in(socks, ...)` of the first clause. Three of the ten are exact, but they are
tasks where a question was wanted. The criterion is the one written down before the run, so the verdict is a kill.

Informational only (a killed arm is not confirmed on dev): on dev 0..299 the same trigger fires on 98 records and 15 of 42 clarify triggers are taken (limit 8); ask-task confident readings rise 78 -> 92.
The noise-isolated replicate of the triggered records was not run, because the arm is already dead on the ask set. The fresh slice was not run for the same reason.

The finding stands as a mechanism, though: 32 of 75 goal-less "where is it" readings turn into an exact set when the model is told the robot finds objects itself, with no loss, so
the abstention is a real fault. What failed is the acceptance rule (b) (it accepts a re-reading that never asked about an open destination). A narrower trigger (no re-ask where the
task also leaves the destination open) or a check that the first question named only an object, never a destination, is the repair to try; it needs a new offline check before any run.

### Verdict

- `sage_ground2` (go_steps + kind_anchor + name_canon): survives understand-eval on all three sets: exact +4.3 / +4.9 / +4.5 points, no loss on the fresh slice,
  confident-wrong 292 -> 254, 258 -> 208, 229 -> 191, atom precision +6 to +7 points, recall flat. The gain is in precision: fewer spurious atoms (steps and unrequested opens).
  Recall does not move, so dropped atoms (the main error of the 8B model) are untouched.
- `sage_reask`: KILL (clarify tasks become confident readings).
- Expected end-to-end effect is small: the lab's join of these gains to the perf1 episodes gave 0 to +2 successes per language per 100. The next step is the planned no-harm gate (dev 0..99,
  `sage` vs `sage_ground2`, EN and KO, two runs, paired; kill if success is lower by >= 3 in a language in both runs, or false successes rise by more than 2) and a 5-task base_robot pilot. Neither was run here.
- Do not read the 4-5 points as a new headline: they are measured on the first reading, with the 8B model, before the read-back, which in KO decides most episodes (round 2 lab section 2.4).

Artifacts: `lab/r2/val/` in the lab folder (scripts `ue.sh`, `cmp2.py`, `classify.py`, `md.py`; arms `tr_*`, `dv_*`, `fr_*`; `*_BAD` is the first, wrong `sage_reask` run).
Commits: robot_agent worktree 8d65426, a90080b, 24ecb36 (Korean open endings). Bench: variants in `planners/`, adapter ignore of the re-ask event.

## Solution lab round 3 (planning and replan, SAGE-v2, 2026-11-06)

Question (from the user): planning (turning the request into a correct plan) and replanning from feedback (what the robot does after a
skill fails or the world is not as expected) matter most. Find better solutions with a deep lab, then run the 5 -> 10 -> 50 loop.

Code: robot_agent worktree `hl_wt/sagev2/robot_agent` (branch `sage-v2/homeloop`) ab47bfe, 28c3c80, 18c7872; bench 70a2b49, f50ee44, bbafd77.
Every new behaviour is an opt-in flag, default off; with the flags off the events are byte-identical (`tests/test_sage_lab_r3.py`). Model
`qwen3-vl:8b-instruct`, profile `real`, seed 0, speech-recognition noise off (`--set asr.en.app_wer=0,asr.ko.app_cer=0,asr.p_partial=0`).
The simulated user can still answer wrongly, be unsure, or stay silent. Lab files: `lab/r3/` in the scratchpad (`problem_brief.md`, `ideas_0..3.md`,
`critique_0..1.md`, `proposals.md`, `off/` for the offline replay, `m5/`, `gate5/`). Raw runs: `results/r3/{n5_a1,n5_a2,m5}/`.

### What the lab found

The brief splits the failures of dev 0..99 (perf1) into planning (A), replanning (B), understanding and dialogue (U) and persistent hardware faults (X).
Each failing episode gets one class (`classify.py`):

| class (failures, of which the oracle succeeds) | sage EN | sage KO | sage_gold EN | sage_gold KO |
|---|---|---|---|---|
| A: first plan from the goals | 5 (5) | 5 (5) | 5 (4) | 4 (4) |
| B: replanning from feedback | 21 (14) | 23 (17) | 23 (16) | 20 (15) |
| U: understanding, dialogue, hazard refusal | 15 (15) | 35 (31) | 0 | 2 (2) |
| X: persistent hardware fault | 9 (3) | 7 (2) | 8 (3) | 10 (3) |
| bench artifact (gold `deliver` goal) | 0 | 0 | 8 (7) | 8 (7) |

- **Planning (A).** About half of the first plans fail the robot's own gate (sage_gold 49 / 95 EN, 50 / 95 KO). The 8B planner opens or closes
  while holding, leaves a reach delivery unachieved, adds a Close nobody asked for, and repeats steps. The symbolic repair closes most of these. Three
  deterministic causes stop it on the rest: the score counts all unmet goals as one finding, plan names are canonicalised only from one-word names,
  and one edit is made per call.
- **Replanning (B).** Several recoveries a robot can do with its own signals are missing: waiting out a transient camera fault (SAGE recovered 0 of
  7 in EN, the oracle 2 of 2); a PutIn BLOCKED into a container the robot thinks is open; the final return to the dock whose failure is ignored; an
  object the user located but the detector missed again. The silent-failure events (`partial_open`, `fall`, ...) exist only in the simulator truth
  and are not shown to the robot, so a fix must use only codes, messages, `health()` and later Find / Look results (clean room).
- **Where the headline loss really is.** On the headline `sage` the A+B failures the oracle solves are EN 19 / KO 22 of 100, but deterministic
  levers convert about 1 of them (offline, below). The larger and more frequent loss is in understanding and dialogue: on the 14 clarify
  (which-object) tasks of dev 0..99 the oracle asks a which-object question in 11 and succeeds in 11, while SAGE asks it in 0 of 28 episodes
  and reaches several false successes by taking "some book" after a "yes" to its read-back.
- **A new offline instrument.** `off/replay_perf1.py` replays the real bench and the real AssistLoop on the cached LLM answers of perf1. The control
  replay reproduces perf1 on 96 / 98 / 96 / 98 of 100 task-runs with 0 cache misses; 4 x 100 task-runs take about 26 s of CPU. An episode with 0
  misses gives an exact outcome even with new skill calls (draws are keyed per call).

Offline result (exact replay, dev 0..99, 400 task-runs, in-sample: the ideas were built from these ids):

| arm | sage EN | sage KO | gold EN | gold KO | F* change | losses |
|---|---|---|---|---|---|---|
| gate_strict (strict + bind) | 49 -> 49 | 30 -> 31 | 53 -> 54 | 54 -> 55 | 0 | 0 |
| wait 2, 4, 8 s | 49 -> 49 | 30 -> 30 | 53 -> 54 | 54 -> 55 | 0 | 0 |
| wait 1, 2, 4 s | no change | no change | no change | no change | 0 | 0 |
| reset_container | no change | no change | no change | no change | 0 | 0 |
| endstate_check | 49 -> 49 | 30 -> 30 | 53 -> 54 | 54 -> 55 | gold -1 / -1 | 0 |
| all A+B together | 49 -> 49 | 30 -> 31 | 53 -> 56 | 54 -> 57 | gold -1 / -1 | 0 |

The wait gain exists only with waits of at least 5 s, which is exactly the simulator's undeclared clearing threshold (`skills.py:78, 1139`); it
is reported as a sweep, not tuned. `inventory_ask` cannot be scored offline: its question needs a new understand call.

### Flags built

| flag (robot_agent option, env `ROBOT_AGENT_<NAME>`, manifest `planner.<name>`) | bench variant | what it does |
|---|---|---|
| `exec_integrity` family | `robot_agent:sage_exec` | the four below together |
| `gate_strict` | `sage_ei_gate` | if the symbolic repair leaves a critical finding, repeat it with a per-goal score and keep it only if it certifies; bind a plan object to the one goal object whose word tokens strictly contain it |
| `endstate_check` | `sage_ei_end` | the return to the last `go` goal (often the dock) becomes a checked, retried step; if it still fails the run does not say done |
| `reset_container` | `sage_ei_reset` | a PutIn BLOCKED into a believed-open container: put the object down where it was picked, Close, Open, fetch, PutIn (once per container) |
| `wait_on_robot` | `sage_ei_wait` | while health is bad, run the pack's declared wait action on a declared schedule (`planner.recovery.wait: {action, schedule_s}`); no declaration = the old poll. The bench variant declares 2, 4, 8 s, marked `assumed` |
| `inventory_ask` | `robot_agent:sage_inv` | `name_canon` made general: when more than one remembered instance fits the goal's bare name and the user's words do not pick one, ask ONE closed which-question from the robot's own memory |
| all of round 3 + round 2 grounding | `robot_agent:sage_r3` | `sage_ground2` + `sage_exec` + `sage_inv` |
| `dialog_unstick` (lab round 4, built after the gate) | `robot_agent:sage_unstick` | a restatement that reproduces the refused reading is read back once more; a not-sure where-is answer makes the robot search; no stacked apology. **Not run in any wave yet** |

Also `AssistLoop.lab_log` (28c3c80): what each flag did in a run, copied by the adapter into `episodes.jsonl` as `lab_events`, so every claim
below that a flag "fired" is read from the episode, not inferred.

Generalisation:
- Robot. Actions, Open / Close and their effects come from the action model; the wait action and schedule from a manifest key (no key, rung off);
  the end-state goal is the robot's own last `go`. On base_robot: `gate_strict` is inert (template plans skip the repair), `endstate_check`
  applies to its dock goals, `reset_container` never fires (no containers), `wait_on_robot` is off unless its pack declares a wait,
  `inventory_ask` is inert (no on / in goals). A pack with no object memory has `inventory_ask` off.
- Language. The gate and the execution flags read no user text. `bind` uses whitespace tokens of the canonical labels, with the hook
  `planner.label_tokens: none` (exact match) for unsegmented labels. `inventory_ask` takes the label language from `planner.canonical_lang`
  (`en` default, `none` skips, other codes use the pack's i18n `plural_fold`); its question is the i18n key `q_which_known`, which falls back to
  the language layer's translate-out for a third language (Vietnamese: test with two "mug" instances, "Đặt cái cốc lên tủ đầu giường", answer
  "cái màu xanh"). `dialog_unstick` reads "not sure" from core English phrases plus the pack's i18n `answer_unsure`, with a structural
  fallback (a short answer that names no ENV place); the core English list is a debt to move into data.

### Milestone 5, gate slice (dev 0..4, `results/r3/n5_a2`, repeat of `n5_a1`)

Cells per task are run a | run b. S = success, H = give-up (status not `done`), F = false success. Counts are [run a, run b].

| variant | EN t0 t1 t2 t3 t4 | EN success | KO t0 t1 t2 t3 t4 | KO success |
|---|---|---|---|---|
| oracle | S\|S S\|S H\|H S\|S S\|S | [4, 4] | S\|S S\|S H\|H S\|S S\|S | [4, 4] |
| sage | S\|S H\|H H\|H H\|H S\|S | [2, 2] | H\|H S\|S H\|H S\|S S\|S | [3, 3] |
| sage_ground2, sage_exec, sage_inv, sage_r3, sage_ei_gate, sage_ei_end, sage_ei_reset, sage_ei_wait | same as sage on every cell | [2, 2] | same as sage on every cell | [3, 3] |

False success 0 and `n_error` 0 everywhere; all 44 logs end with EXIT=0. The two runs are identical to each other and to `n5_a1`.

Every task where SAGE differs from the oracle:
- t2 (`hl-dev-000002`, EN and KO, oracle too): an injected persistent hardware fault on `dock`. `wait_on_robot` waited 2, 4 and 8 s; health
  stayed bad. Correct give-up, not a SAGE failure.
- t1 EN and t0 KO: dialogue convergence (class C1). The read-back was right, the simulated user's answer was drawn as `wrong` ("No.",
  `p_wrong` = 0.173), the user restated the request, the restatement gave the same reading, and SAGE gave up after the which-part question
  (`say_not_confirmed`). The oracle does not read back, so it never meets this draw. This is the target of `dialog_unstick`.
- t3 EN (clarify): SAGE asked 9 questions against a patience of 7, with a compound where-is question ("Where is the milk, and where would you like me
  to put it away?") and stacked apologies ("Sorry, I didn't hear you. Sorry, I may have misheard you. ..."; `understand.py:609-610` plus the
  silence retry), then gave up on patience timeouts. The same trace shows a simulator bug (below).

Why nothing changed: dev 0..4 contains none of the tasks the proposals target. Over 200 variant episodes the only flag that fired was
`wait_on_robot` on t2. `gate_strict`, `endstate_check`, `reset_container`, `inventory_ask`, `go_steps`, `kind_anchor` and `name_canon` fired 0 times.
The flags are live (`planner_config.loop_options` is recorded; the wait changes the t2 trace). The trace differences elsewhere (e.g. one extra
`find microwave -> absent` in EN t0) come from LLM-server nondeterminism and changed no outcome.

### Milestone 5, proposal tasks (`results/r3/m5`)

The 5 tasks each proposal declared (P1 `sage_exec`: 008, 014, 015, 065, 074; P2 `sage_inv`: 014, 021, 027, 062, 089), two runs, same settings.
`x` = failure that is not a false success, `.` = task not in that variant's list.

| variant | EN 008 014 015 021 027 062 065 074 089 | KO 008 014 015 021 027 062 065 074 089 |
|---|---|---|
| oracle | S\|S S\|S S\|S S\|S S\|S S\|S S\|S S\|S S\|S | S\|S S\|S S\|S S\|S S\|S S\|S S\|S S\|S S\|S |
| sage | S\|S x\|x S\|S x\|x F\|F F\|F F\|F x\|x x\|x | x\|x x\|x x\|S F\|x F\|F F\|F F\|F x\|x x\|x |
| sage_exec | S\|S x\|x S\|x . . . S\|S x\|x . | x\|x x\|x S\|S . . . S\|S x\|x . |
| sage_inv | . x\|x . x\|x S\|S S\|S . . x\|x | . x\|x . F\|F S\|S S\|S . . x\|x |

| on its 5 tasks, [run a, run b] | EN success | EN F* | KO success | KO F* | skill calls per task, questions included (oracle: P1 / P2 tasks) | questions per task (oracle: P1 / P2 tasks) |
|---|---|---|---|---|---|---|
| oracle | [5, 5] | [0, 0] | [5, 5] | [0, 0] | 11.8 / 11.0 | 0.2 / 1.0 |
| sage (P1 tasks) | [2, 2] | [1, 1] | [0, 1] | [1, 1] | EN 25.4, KO 18.2 | EN 1.0-2.0, KO 2.6 |
| sage_exec | [3, 2] | [0, 0] | [2, 2] | [0, 0] | EN 34.0, KO 21.6 | EN 1.4-2.8, KO 2.6 |
| sage (P2 tasks) | [0, 0] | [2, 2] | [0, 0] | [3, 2] | EN 27.0, KO 26.2-30.2 | EN 1.8, KO 1.8-2.0 |
| sage_inv | [2, 2] | [0, 0] | [2, 2] | [1, 1] | EN 22.0-22.4, KO 24.2 | EN 3.8-4.6, KO 2.4 |

0 errors, every log EXIT=0, no traceback. Every differing cell, read from the episodes and their `lab_events`:

`sage_exec` (P1):
- **065 EN and KO, F|F -> S|S (4 wins).** `endstate_check` fired. The last `dock` hit an injected transient `hw_fault`; baseline ignores
  the result and says "Task completed" with `docked()` false. With the flag the dock is retried, succeeds, and all three goals are met. As predicted offline.
- **015 KO run a, x -> S (1 win).** Baseline gave up with "I could not make a plan I can check" (0 skill calls); with the flag `gate_strict`
  (`per_goal_repair`) certified the plan and the run succeeded. In run b the baseline plan certified anyway (server nondeterminism), so both succeed.
  This matches the offline prediction (015 KO).
- **015 EN run b, S -> x (1 loss, not caused by the flag).** The run ended in the dialogue: 9 questions, three of them injected timeouts, give-up
  "I did not hear an answer". No plan was made, so no flag could act (no `lab_events`). The same task succeeded in run a with `gate_strict` firing.
- 014 EN and KO (no outcome change): `wait_on_robot` fired in EN after a `perception_unavailable`; the task still failed, now with status `budget`
  after 60 calls instead of a give-up after 28. That is more motion for no gain and needs a cap. In KO `gate_strict` fired; same failure.
- 074 EN and KO (no outcome change): `reset_container` fired as designed (put down, Close, Open, fetch), then the next PutIn hit an injected
  `hw_fault`. Mechanism shown; the outcome is decided by the next fault, as offline.
- 008: same outcomes; run a and b swap traces (one extra Find), server nondeterminism.

`sage_inv` (P2):
- **027 and 062, EN and KO, F|F -> S|S (8 wins).** Baseline took "some book" / "some mug" and said done (false success). With the flag the robot asked
  once ("I know of more than one book: the red book or the blue book. Which one do you mean?"), read the answer, and succeeded in 13-17 calls.
- 021 EN (no outcome change, worse path): baseline failed in execution (glass pick blocked). With the flag the which-question was answered
  ("The green one, please."), but the user then drew `wrong` twice on the read-back ("No, the white glass."), SAGE alternated green / white,
  asked for a restatement, and asked the which-question again 3 more times (5 firings in one episode), got "I don't know." twice and gave up
  on timeouts. Two defects of the flag: it does not remember that it already asked, and its option list repeats synonyms of the same objects
  ("the green glass or the white glass or the green drinking glass or the white drinking glass"; the KO mug question has the same problem).
- **021 KO run b, x -> F (1 loss, not caused by the flag).** `inventory_ask` did not fire (no `lab_events`). Baseline run a and the flag's two
  runs give the same false success (keys put away, glass not delivered); baseline run b took another path. Server nondeterminism.
- 014 EN and KO, 089 EN and KO (no outcome change): the flag fired on 014 (both) and 089 KO, the tasks still failed (grasp faults, red mug not
  found). In KO 014 and 089 the final sentence is "죄송해요, 지금은 그 말씀을 드리기 어려워요." ("Sorry, it is hard for me to say that now"), which
  reads like a translator refusal, not a task report. Not traced further.

### Milestones 10 and 50: not run

The loop stopped at milestone 5. The gate on dev 0..4 did not pass, for two reasons, and no milestone-10 or milestone-50 run exists:
1. It found a simulator bug (below) that also touches the oracle and naive baselines; it must be fixed and those baselines rerun first.
2. dev 0..4 cannot test the flags (they fired 0 times), and the declared proposal tasks (m5) were run as a separate wave whose result the gate
   decision did not take into account.
The milestone lists are written down in `proposals.md` (P1 m10: m5 + 024, 066, 042, 058, 003; P2 m10: m5 + 096, 017, 066, 003, 041; m50: all
A / B ids plus harm controls, and all 14 clarify tasks plus controls). A confirmation on the never-run slice dev 100..199 comes after m50.

### Verdict against the kill criteria of `proposals.md` (milestone 5 only)

| proposal | criterion | m5 result | verdict |
|---|---|---|---|
| P1 `exec_integrity` | losses greater than wins on changed episodes | 5 wins (065 x 4, 015 KO a), 1 loss where no flag acted | pass |
| | F* of newly certified plans > 1 per language | 0 | pass |
| | a control task lost where a sub-flag fired | no control task in m5 | not tested |
| P2 `inventory_ask` | < 2 net flips per language over both runs | EN +4, KO +4 (027, 062), KO 021 b -1 without the flag acting | pass |
| | a control lost where the rule fired; questions on non-clarify tasks +0.3 | no control or non-clarify task in m5 | not tested |
| | KO which-answers misread in more than half of the KO firings | 027 and 062 read right; 014 and 089 not traced | not decided |

Nothing is killed. Nothing is kept as a default either: milestone 5 on 5 hand-picked dev tasks is a mechanism check, not a result, and the R6 keep
rule (>= 6 / 100 paired in the same direction in two runs) cannot be met by 5 tasks. Kept for milestone 10: `endstate_check` (clean 4 / 4 wins, no
extra LLM call), `gate_strict` (1 win, matches offline), `inventory_ask` (8 / 8 wins on its two target tasks, after the two repairs below).
Kept but weak: `reset_container` (mechanism shown, 0 outcome flips offline and online), `wait_on_robot` (gain depends on a hidden simulator
constant; on 014 EN it ran into the call budget).

### Harness findings (bench and simulator, never SAGE gains)

- **Simulated user forgets what it knows.** `homeloop_robot/homeloop_robot/user.py:470` draws `knows = rng.random() >= p_location_unknown` once per
  question, while `docs/user_model.md` and the profile note describe it as a state of the user. In t3 EN the user says "I don't know." (ask 4) and then
  "It's on the dining table." (ask 6) about the same milk. It rewards planners that ask again. It is rare (1 of 800 perf1 episodes flips; 11 of 800
  contain the answer). Fix: draw it once per (episode, entity), with a test over seeds 0..199 that no episode has both answers for one object, and
  rerun oracle and naive. **Not fixed yet** (homeloop_robot is at f5497b3).
- Known from the brief, still open: `refresh_person_spot` drops a person's spot once it is full (021 EN gold), the adapter's `health_wait_s=0`
  makes a waiting robot pass no simulated time, and the gold `deliver` artifact of `sage_gold`.

### Caveats

- **Dev tuning.** All target ids come from dev 0..99, where the ideas were built and the offline replay was scored. The m5 wins are in-sample. Only
  dev 100..199 (never run end to end) can confirm them.
- **Noise.** Run-to-run noise measured earlier is about 3 tasks in 50. Here runs a and b share seed 0, so they measure LLM-server nondeterminism only:
  2 of 40 paired P1 / P2 baseline-vs-flag cells flipped without a flag acting (015 EN b, 021 KO b), both against the flag arm. 015 KO a (a win)
  had the flag acting, but its baseline succeeded in run b, so a part of it may be noise too.
- **Understanding vs end to end.** Round 2 gave `sage_ground2` +4.5 points of exact readings in `understand-eval`; on the e2e gate slice it changed nothing.
  A gain on the first reading does not carry through the read-back, the dialogue and the execution by itself.
- **Speech noise off.** These tables are the sensitivity setting with speech-recognition noise off; with it on, the dialogue failures (C1) grow.

### Next steps (in order)

1. Fix the simulated-user knowledge bug in homeloop_robot with its test; rerun oracle and naive on the slices used here.
2. Repair `inventory_ask`: ask at most once per object class per run (remember the answer), and list one name per remembered instance (no synonyms).
   Both are data-free changes in the core. Add `wait_on_robot` and the check tour to the call budget accounting.
3. Run milestone 10 for `sage_exec`, `sage_inv` and `sage_unstick` (the last targets C1, the most common give-up in the gate slice) on the
   declared ids, two runs, oracle and `sage` paired; then milestone 50 with the harm controls; then dev 100..199 as confirmation.

Artifacts: `lab/r3/` (scripts `table.py`, `m5/table.py`, `m5/why.py`, `gate5/*.py`, `off/replay_perf1.py`, `off/diff.py`). Commits: robot_agent ab47bfe, 28c3c80,
18c7872; bench 70a2b49, f50ee44, bbafd77.

## Solution lab round 3: fixes found by the review, m5 and m10 rerun with a shared cache (2026-11-06)

Six fixes first (no rate or scoring is tuned; each has a test), then the m5 and m10 gates again. Condition for every
run: profile `real`, seed 0, `asr_off` (`asr.en.app_wer=0, asr.ko.app_cer=0, asr.p_partial=0`; a sensitivity condition,
never the headline), `qwen3-vl:8b-instruct` with `qwen3-vl:30b-a3b-instruct` as translator, repeats a and b, one shared
read-through cache. Raw runs: `results/r3/m5s`, `results/r3/m10s` (not in git); `table.py` there prints the tables below.

| fix | repo | what | test |
|---|---|---|---|
| H1 | homeloop_robot | the ENV loc of a person entry with no spot is refreshed from the position the move uses (the person's true position), also when the spot stays None; before, a person who sat down elsewhere left the loc at the old stop point and robot_agent's arrival check failed | `tests/test_person_spot_walk.py` (every house and person; `verify._at_target` passes; a person who did not move: entry unchanged) |
| H2 | homeloop_bench | `run --shared-cache DIR`: paired runs share one read-through, write-through prompt-sha response cache per model (understand, translator and intent prompts alike): common random numbers | `tests/test_shared_llm_cache.py` |
| H3 | homeloop_bench | `tell_fetch`: the fetch clause has its own sentence; `gen/attach.py` check as paraphrase filter, EN judge asks the attachment question; 79 train and dev tasks re-rendered and the 44 with LLM text re-paraphrased; test split untouched (see [generation.md](generation.md)) | `tests/test_tell_fetch_attach.py` |
| V1 | robot_agent, homeloop_robot | restated read-back = lead phrase `rb_restated` + the ordinary `q_confirm`; a question keeps its kind in the language layer's last resort (a read-back never becomes "say the task in other words"); Vietnamese `localized` threshold; KO lead phrase in the pack | `tests/test_sage_lab_r5_restated_readback.py` (KO and VI through the real loop) |
| V2 | robot_agent, homeloop_bench | `canon_inventory` counts instances (record id, or the pack's `object_aliases`), one name per instance; the which-question declares `qtype: which_object`, which the adapter hands to the simulated user | `tests/test_sage_lab_r5_inventory_instances.py`, `tests/test_declared_ask.py` |
| 6 | homeloop_bench | `robot_agent:sage_r3u` (sage_r3 + dialog_unstick) registered | `tests/test_adapter_lab_events.py` |

### m5 (dev 065 008 015 014 074), P1 sub-flags

Cell = outcome a|b (S success, F false success, x gave up). The baseline sage ran first and filled the shared cache.

| variant | EN 065 008 015 014 074 | EN S / F* | KO 065 008 015 014 074 | KO S / F* |
|---|---|---|---|---|
| oracle | S S S S S | 5 / 0 | S S S S S | 5 / 0 |
| sage | F S F x x | 1 / 2 | F S x x x | 1 / 1 |
| sage_ei_gate | F S F x x | 1 / 2 | F S x x x | 1 / 1 |
| sage_ei_end | S S F x x | 2 / 1 | S S x x x | 2 / 0 |
| sage_ei_reset | F S F x x | 1 / 2 | F S x x x | 1 / 1 |
| sage_ei_wait | F S F x x | 1 / 2 | F S x x x | 1 / 1 |
| sage_exec | S S F x x | 2 / 1 | S S x x x | 2 / 0 |
| sage_r3 | S S F S x | 3 / 1 | S S x S x | 3 / 0 |
| sage_r3u | S S F S x | 3 / 1 | S S x S x | 3 / 0 |

a and b are identical in every cell and in every episode's calls and asks (the shared cache makes the repeats replays;
they measure the harness, not LLM noise). **Gate:** every cell that differs from the baseline has fired lab events and
different calls (065 by `endstate_check`; 014 by `inventory_ask` + `wait_on_robot`); 0 unexplained differences, 0 losses,
0 errors. `gate_strict`, `reset_container` and `wait_on_robot` alone change no cell here. One conflict in the shared
cache: `sage_r3` and `sage_r3u` asked one repair prompt at the same moment and got two texts (no cell changed). Run
identical-code variants one after the other.

### m10 (P1: m5 + 024 066 042 058 003; P2: 014 027 062 021 089)

| variant | EN success a,b | EN F* | KO success a,b | KO F* | differing episodes (all explained by fired lab events) |
|---|---|---|---|---|---|
| oracle | 14 | 0 | 14 | 0 | |
| sage | 1 | 4 | 2 | 4 | baseline |
| sage_ei_gate | 2 | 4 | 2 | 4 | EN 024 x to S (`gate_strict` per-goal repair) |
| sage_ei_end | 2 | 3 | 3 | 3 | 065 F to S, EN and KO (`endstate_check`) |
| sage_ei_reset / sage_ei_wait | 1 / 1 | 4 / 4 | 2 / 2 | 4 / 4 | none (the triggers fired, no cell changed) |
| sage_exec | 3 | 3 | 3 | 3 | EN 065, EN 024; KO 065 |
| sage_inv | 3 | 2 | 5 | 2 | 027, 062 F to S, EN and KO; KO 021 x to S (`inventory_ask`) |
| sage_r3 / sage_r3u | 6 / 6 | 1 / 1 | 7 / 7 | 1 / 1 | the union: 065, 014, 024 (EN), 027, 062, 021 (KO) |

Zero losses on the controls (042, 058, 003, 066 in both languages) and 0 unexplained differences. Task 021 EN stays
unsolved by `sage_inv` (the question is asked, the run still gives up), 066 and 042 stay unsolved by every variant. The
`dialog_unstick` part of `sage_r3u` fired only as `unsure_search` on EN 058 and 003 (controls) and moved no cell. This is dev 0..99 again
(in-sample for the ideas); the fresh slice dev 100..199 is the next confirmation. Containers: started with
`OLLAMA_NUM_PARALLEL=6`, at most 8 clients, stopped afterwards.

## Round 4: bench fixes and gated validation (2026-11-06)

Four harness defects that round 3 found were fixed first. These are consistency fixes. No rate, no scoring rule and no task was
changed, and the random streams do not shift. After that, the milestone-5 gate was run again on the fixed code. Code of the run:
homeloop_robot 1d7e4eb, robot_agent `sage-v2/homeloop` 7bd0ee4, embodiplan 4080017, bench 798e642 (later commits are docs only).
Condition: profile `real`, seed 0, `asr_off` (`asr.en.app_wer=0, asr.ko.app_cer=0, asr.p_partial=0`; a sensitivity condition, never
the headline), planner `qwen3-vl:8b-instruct`, translator `qwen3-vl:30b-a3b-instruct` (read from `planner_config.translate_model`).
Repeats a and b, paired by task. There is **no shared cache** in this run, so a and b measure LLM-server nondeterminism. Raw run:
`results/r4/n5_a2` (not in git). The table script is `lab/r3/t_r4a2.py` in the scratchpad.

### Bench fixes

| # | repo, commit | defect (evidence) | fix | test |
|---|---|---|---|---|
| 1 | homeloop_robot 5b6f16a | The simulated user drew "knows where X is" again on every question. In `hl-dev-000003` EN (`results/r3/n5_a2`) it says "I don't know." twice about the milk, then "It's on the dining table." | The user remembers per object what it said (a place, or "I don't know"), and a later answer follows it. The draw is still taken on every ask, so the streams do not shift. Note in `docs/user_model.md`. | `tests/test_user_model.py` (fails on the old code) |
| 2 | homeloop_robot ee56e63 | `refresh_person_spot` dropped a person's spot once it was full, also when the robot's own delivery filled it. Traced on 021 EN `sage_gold`: the senior_flat nightstand holds 3 of 4 at the start, the robot's Place of the glass fills it, the spot is dropped, the final MoveTo goes to the stop point, and Find says "green glass not found" while `delivered[reach]` is true. | A spot that holds an object the robot itself placed there stays the person's spot. The robot records its own successful Place (`ra_skills.place`, `tasks.note_placed`). A spot filled by other things is still dropped. | `tests/test_person_spot_refresh.py` (fails without the fix) |
| 3 | homeloop_robot 435984b, bench 9d0b1df | The adapter set `health_wait_s=0` and robot_agent waits in wall-clock time, so a waiting robot let no simulated time pass. | `Robot.idle(seconds)` advances the simulated clock, and 5 s of idle in a row clears a camera fault that clears on waiting, as the Wait skill does. The adapter puts `SimTime` over the planning modules' `time`, so a robot's sleep moves the episode clock. `health_wait_s` is robot_agent's default 0.5 s, the same for every robot_agent planner. | `homeloop_robot/tests/test_robot_idle.py`, `tests/test_sim_time_wait.py` |
| 4 | bench 814dd7c | `gold_goals.py` wrote a hand delivery to another person as the goal kind `deliver`, which compiles to MoveTo + WaitForUnload, and the plan gate refused it ("the robot has no action WaitForUnload"). | Written as `{type: on, to: <person>, hand: true}`, the form robot_agent's own understanding writes (017 sage writes `{on, toy car, to kid, hand true}`). The unused `seat()` helper is removed. | `tests/test_gold_hand_delivery.py` (017 EN and KO, 018, no `deliver` left) |

Both suites are green: homeloop_robot 868 passed (106 s), homeloop_bench 415 passed (95 s), run with the sagev2 robot_agent on
PYTHONPATH as the experiments do. Nothing was pushed, and the robot_agent and embodiplan mains were not touched.

Not done, or done only in part:
- No live LLM rerun was made for the fixes themselves. The LLM server did not answer at that time. `sage_gold` was not measured again on
  021 or on the hand-delivery ids 017 018 054 060 063 064 087 090. The `sage_gold` ceiling of about 63 / 100 instead of 56 / 100 is still an
  estimate. The fixes rest on traces and regression tests.
- Fix 1 works per object, not per phrasing. A `wrong` answer (`p_wrong`) can still name another place on a later turn. That is a separate,
  intended noise path, and it was left alone.
- Fix 3 changes little. With 0.5 s per poll a WAIT_HEALTH adds about 1 s of simulated time, and it almost never reaches the 5 s that clear a
  camera fault. A camera fault still clears through the Wait skill (`sage_ei_wait`, `wait_on_robot`) or a long idle. The wait was not raised,
  because that would be tuning.

### What the fixes change for earlier numbers

- **Not comparable with runs after the fixes:** every run before 14:05 on 2026-11-06. That covers `exp_r2`, `live_smoke`,
  `milestones_r3`, `r4b`, `perf1` (dev 0..99, the R6 decomposition and the round-3 class table), and `results/r3/{n5_a1, n5_a2, m5}`.
  It also covers the offline replay `off/replay_perf1.py`, which replays perf1 caches on the old simulator.
- **After the fixes:** `results/r4/n5_a1` (14:17; the four fixes, but not yet H1, V1, V2 and tell_fetch of the previous section),
  `results/r3/m5s` and `results/r3/m10s` (15:2x; the same code as this round, with a shared cache), and `results/r4/n5_a2` (this round).
- What each fix moves:
  - Fix 1: episodes in which the user is asked twice where the same object is. This is rare: in perf1, 11 of 800 episodes contain both
    answers and 1 of 800 flips.
  - Fix 2: deliveries onto a person's spot that becomes full (021 EN `sage_gold` is the known case).
  - Fix 3: the simulated time and `time_mean_s` of every robot_agent episode with a `perception_unavailable` wait. It also moves what
    depends on time: the user's walk and the interrupts. oracle, naive and the other non-robot_agent planners are not affected.
  - Fix 4: `sage_gold` only, on tasks whose goal is a hand delivery to another person. This is the row "bench artifact (gold `deliver`
    goal)" of the round-3 class table: 8 EN / 8 KO failures, of which the oracle solves 7 / 7. Every earlier `sage_gold` ceiling, including
    56 / 100 and the 53-56 / 54-57 of the offline replay, must be rerun.
- In the slice below: fix 3 acts in every 014 and 074 episode with a camera fault. Fix 1 is not visibly exercised: the only repeated
  where-is question (EN 014 `sage_exec`) is a retry after silence with one answer. Fix 2 has no known case here (021 is not in the slice).
  Fix 4 does not apply, because no task here hands an object to another person (014 hands it to the speaker).

### Milestone 5 (dev 065 008 015 014 074, `results/r4/n5_a2`)

Cell = run a | run b. S success, F false success, H gave up. Counts are [a, b]. `sage_gold` is privileged (gold goals), with one run
and none of the lab flags.

| variant | EN 008 014 015 065 074 | EN S | EN F* | KO 008 014 015 065 074 | KO S | KO F* |
|---|---|---|---|---|---|---|
| oracle | S\|S S\|S S\|S S\|S S\|S | [5, 5] | [0, 0] | S\|S S\|S S\|S S\|S S\|S | [5, 5] | [0, 0] |
| sage | S\|S H\|H F\|F F\|F H\|H | [1, 1] | [2, 2] | H\|S H\|H S\|S F\|F H\|H | [1, 2] | [1, 1] |
| sage_ground2 | S\|S H\|H S\|F F\|F H\|H | [2, 1] | [1, 2] | S\|H H\|H S\|S F\|F H\|H | [2, 1] | [1, 1] |
| sage_exec | S\|S H\|H F\|F S\|S H\|H | [2, 2] | [1, 1] | H\|H H\|H S\|S S\|S H\|H | [2, 2] | [0, 0] |
| sage_inv | S\|S H\|H F\|F F\|F H\|H | [1, 1] | [2, 2] | H\|H H\|H S\|S F\|F H\|H | [1, 1] | [1, 1] |
| sage_unstick | S\|S H\|H F\|F F\|F H\|H | [1, 1] | [2, 2] | S\|S H\|H S\|S F\|F H\|H | [2, 2] | [1, 1] |
| sage_r3 | S\|S S\|S F\|F S\|S H\|H | [3, 3] | [1, 1] | H\|S S\|S S\|S S\|S H\|H | [3, 4] | [0, 0] |
| sage_r3u | S\|S S\|S F\|F S\|S H\|H | [3, 3] | [1, 1] | S\|S S\|S S\|S S\|S H\|H | [4, 4] | [0, 0] |
| sage_gold (1 run) | H H S F H | 1 | 1 | S H S F H | 2 | 1 |

Pooled over EN, KO and both repeats (20 episodes each), the successes are: oracle 20, sage 5, ground2 6, exec 8, inv 4, unstick 6,
r3 13, r3u 14. False successes: sage 6, ground2 5, exec 2, inv 6, unstick 6, r3 2, r3u 2. 0 errors in every cell.

**The run used a stale task file for 015.** `run.sh` reused `tasks.jsonl` from `n5_a1` (written 14:18), which is older than the
tell_fetch re-render (4a0550c, 15:19). So 015 ran on its old text: EN "Hey, tell Grandpa to head to the kitchen for a sec and bring that
red book over to me." In that text the fetch clause can attach to the message, which is the defect H3 removed. The other four tasks have
the current text. On the current text (`m5s`, `m10s`, same code), `sage` EN 015 is still F, for another reason (below), and KO 015 is x.

Paired against `sage` (same task, language and repeat), wins / losses, and whether a flag fired in the changed episode:

| variant | wins | losses | where (flag) |
|---|---|---|---|
| sage_ground2 | 2 | 1 | EN 015 a, KO 008 a (no flag) / KO 008 b (no flag) |
| sage_exec | 4 | 1 | 065 EN and KO x2 (`endstate_check`) / KO 008 b (no flag) |
| sage_inv | 0 | 1 | KO 008 b (no flag) |
| sage_unstick | 1 | 0 | KO 008 a (no flag) |
| sage_r3 | 8 | 0 | 014 and 065, EN and KO, x2 (`inventory_ask` + `wait_on_robot`; `endstate_check`) |
| sage_r3u | 9 | 0 | as sage_r3, plus KO 008 a (`dialog_unstick.restated_reading`) |

Every win or loss without a fired flag sits on one of the two fork points described under 008 KO and 015 EN below.

### Every task where cells differ, read from the episodes

- **008 EN (S everywhere except gold).** Every variant makes the same 21 calls and succeeds. `sage_gold` gives up with 0 calls: "I could not
  make a plan that passes my checks". This is the `bind` case that `gate_strict` targets, but `sage_gold` runs without the flags, so it
  cannot be judged here.
- **008 KO (the main source of noise).** The request "put the blue book on the armchair, no, actually on the TV stand, and bring me the water
  bottle" forks at the reading of the user's restatement (LLM nondeterminism, no flag involved):
  - The S path has 3 questions. The second read-back is right, and the user says yes.
  - The H path has 5 questions. The first reading puts the water bottle on the TV stand, and the user says no. The second reading is right,
    but the user draws `not_sure`. The which-part question follows, the user restates, and SAGE gives up ("무엇을 할지 확인하지 못해서
    여기서 멈출게요.").
  - The H path came up in sage/a, ground2/b, exec/a, exec/b, inv/a, inv/b and r3/a, and all 7 gave up. `dialog_unstick.restated_reading`
    fired on that path 3 times (unstick/b, r3u/a, r3u/b). Each time it read the same reading back once more ("같은 뜻으로 다시
    이해했어요. ... 맞아요?"), got "네, 맞아요." and succeeded (6 questions, 27 calls). unstick/a took the S path without the flag.
  - Both paths also show a coverage false alarm: "안락의자 말씀하셨는데 제 계획에 없어요" ("you said armchair, but it is not in my plan").
    The user corrected "armchair" away in the same sentence. This is a SAGE weakness, not a harness one.
  - `sage_gold` succeeds here.
- **014 EN and KO (only sage_r3 and sage_r3u succeed).** It is a clarify task with two mugs, and later a transient camera fault
  (`perception_unavailable`) comes up.
  - Baseline and ground2 / unstick give up on the camera fault ("I have to stop: something is wrong with my hardware.").
  - `sage_inv` asks the which-question and gets "The black one, please." / "검은 거요.", read right in all firings, KO included. It then
    gives up on the same camera fault. In KO its final sentence is again "죄송해요, 지금은 그 말씀을 드리기 어려워요." ("it is hard for me
    to say that now"), a translator refusal and not a task report.
  - `sage_exec` alone waits 2, 4 and 8 s and the camera clears. It then searches for a generic "mug" (absent at many places) and stops at
    the 60-call budget, 360 s of simulated time. That is more motion for no gain.
  - Both together (r3, r3u): the which-question names the black mug, the wait clears the camera, and the run succeeds in 41-45 calls. Neither
    flag converts 014 alone.
  - Seen on the way:
    - The which-question still lists 4 names for 2 mugs ("black mug or white mug or black coffee mug or white coffee mug", EN and KO),
      after V2's instance count. Not traced.
    - KO baseline: the read-back translates "the mug" as "미안해요" ("sorry"): "그릇 냉장고 안에 넣을게요, 그다음 미안해요. 손에
      건네드릴게요." The simulated user did not take the structured meaning (`structured_mismatch`). It answered from what it heard, as
      the R2-7 rule requires. These are all 6 mismatches of the run (sage, sage_exec, sage_unstick, a and b).
    - A later KO read-back says "그릇 사용자 안에 넣을게요" ("put the bowl inside the user"), a grounding error.
    - `sage_gold` gives up on a grasp fault followed by the camera fault, because it has no wait flag.
- **015 EN (F in every variant except ground2/a; stale text).** On the old text the planner puts the whole fetch clause into the message to
  Grandpa. It moves to Grandpa, says "Grandpa, head to the kitchen for a sec and bring that red book over to me.", and reports done after 3
  calls. ground2/a took another path: its first reading asked a confirm question with a coverage remark, the user said yes, and the run
  succeeded. No flag fired, so this is the second fork point. `sage_gold` succeeds. On the current text (`m5s`, `m10s`) `sage` reads the
  fetch, but the user gives the `wrong` answer "Yes, that's right." to a read-back that hands the book to Grandpa, so the run is a false
  success through intended user noise.
- **015 KO (S everywhere).** `gate_strict.per_goal_repair` fired in exec, r3 and r3u (6 episodes), but the baseline also certified, so there
  were 0 flips.
- **065 EN and KO (F to S wherever `endstate_check` runs, 12 of 12).** The final dock draws an injected transient `hw_fault`. The baseline
  ignores it and says "Task completed" with `docked()` false. With the flag the dock is retried, succeeds, and all three goals hold.
  `sage_gold` is F for the same reason.
- **074 EN and KO (H in every variant; the oracle succeeds).**
  - The first Open gives the silent `partial_open`. The robot cannot see it, and PutIn is then BLOCKED. The baseline retries PutIn 2-3
    times and gives up.
  - `reset_container` fires as designed: put down at the source, Close, Open, fetch, PutIn. The second `put_in(fridge)` then draws an
    injected persistent `hw_fault` (draw key skill, args, nth = 1), and `wait_on_robot` waits 2, 4 and 8 s in vain.
  - The oracle closes and reopens right after the `partial_open`, because it reads the true state. It makes only one put_in, so it never
    meets that draw. Rule (b) of the milestone (the oracle fails too) therefore does not apply, although no robot-visible policy has shown
    a way through.
  - `sage_gold` gives up on two BLOCKED PutIns and a camera fault.

### Milestone 10 (`results/r3/m10s`, post-fix code)

This round ran no new milestone 10. The m10 rerun of the previous section already ran on the same code, after all four fixes, with the shared
cache, so its a and b are identical. Success over its 14 ids (P1 m10 plus P2 m5), [a = b]:

| variant | EN S | EN F* | KO S | KO F* |
|---|---|---|---|---|
| oracle | 14 | 0 | 14 | 0 |
| sage | 1 | 4 | 2 | 4 |
| sage_exec | 3 | 3 | 3 | 3 |
| sage_ei_gate / _end / _reset / _wait | 2 / 2 / 1 / 1 | 4 / 3 / 4 / 4 | 2 / 3 / 2 / 2 | 4 / 3 / 4 / 4 |
| sage_inv | 3 | 2 | 5 | 2 |
| sage_r3 / sage_r3u | 6 / 6 | 1 / 1 | 7 / 7 | 1 / 1 |

Every differing cell has fired lab events, there are 0 losses on the controls (042, 058, 003, 066), and `table.py` reports no unexplained
differences. Reproduce it with `python -I results/r3/m10s/table.py results/r3/m10s 65 8 15 14 74 24 66 42 58 3 27 62 21 89`.

### Milestone 50: not run

The milestone-5 gate did not pass (below), so milestone 50 was not started.

### Gate and keep / kill

**Gate: not passed.**
- The hygiene part passes:
  - 0 errors, and all 34 run logs end `EXIT=0`;
  - no wrong-language speech, no raw id said to the user, no LLM-budget hit;
  - 6 `structured_mismatch` questions, all explained (KO 014 "미안해요" above);
  - no HTTP 500 (1626 requests, all 200, per the run report's container-log count);
  - at most 8 clients, and the container was stopped after the batch with no run alive.
- The correctness part fails. The oracle solves all 5 tasks in both languages, so a correct planner needs 5 / 5. `sage` has 1 / 5 EN and
  1-2 / 5 KO, and the best variant `sage_r3u` has 3 / 5 EN and 4 / 5 KO. 074 fails everywhere, and 015 EN fails everywhere except one
  episode.

Kill criteria of `proposals.md`, read on this run plus `m10s`:

| flag | fired (this run) | result | criterion | verdict |
|---|---|---|---|---|
| `endstate_check` | 12 (065) | F to S 12 / 12; m10s 065 x4 | losses > wins: no; control lost: no | **keep** |
| `gate_strict.per_goal_repair` | 8 (KO 015 x6, KO 065, KO 014) | 0 flips here; m10s EN 024 x to S x2 | F* of newly certified plans: 0 | **keep** |
| `gate_strict` bind | 0 | not on the variants' path (gold EN 008 only) | - | not tested |
| `reset_container` | 12 (074) | 0 flips; the next PutIn draws a persistent fault | no loss | keep, no gain shown |
| `wait_on_robot` | 22 (014, 074) | gain only together with `inventory_ask` (014); alone, EN 014 runs into the 60-call budget | no loss | keep, weak; needs a budget cap |
| `inventory_ask` | 12 (014) | alone 0 flips (camera fault after it); with the wait 8 wins; m10s alone EN +4, KO +6 | >= 2 net flips per language: yes (m10s); KO misread: 0 of 6; firings on non-clarify tasks: 0 here | **keep** |
| `dialog_unstick.restated_reading` | 3 (KO 008) | 3 / 3 S on the path where the same path without it gave up 7 / 7 | no criterion written in `proposals.md`; 0 losses | keep for the fresh slice |
| `dialog_unstick` not-sure search | 0 here (m10s: controls 058, 003, no cell moved) | - | - | not tested |

**No flag is killed and none becomes a default.** These are 5 hand-picked dev tasks. The R6 keep rule (>= 6 / 100 paired in the same
direction in two runs) cannot be met at this size.

### Caveats

- **Dev tuning.** The ids come from dev 0..99, where the ideas were built and the offline replay was scored. All gains are in-sample.
  Only dev 100..199 (never run end to end) can confirm them.
- **Noise.** Earlier rounds measured about 3 tasks in 50 from run to run. Here a and b differ in 4 of 70 SAGE task-language pairs:
  KO 008 for sage, ground2 and r3, and EN 015 for ground2. All four sit on the two fork points above. At n = 5 one flip moves a count by 20
  points. The earlier `n5_a1` was fully identical between a and b. The cause of that difference was not traced.
- **Flags that never fired here:** `go_steps` and `kind_anchor` (the round-2 grounding flags inside ground2 / r3 / r3u), the `gate_strict`
  bind, and the not-sure search of `dialog_unstick`. `name_canon` fired only in ground2 on 014, and `inventory_ask` only on 014. A null
  result for these flags here means "not exercised", not "no effect".
- **Stale task file** for 015 (above). The 015 cells of this run measure the old text.
- `asr_off` throughout. With speech noise on, the dialogue failures (the 008 KO kind) grow.
- `sage_gold` is not a ceiling for the flag variants. It runs without the flags, so on these ids it scores below `sage_r3` / `sage_r3u`.

### Next steps (suggested, in order)

1. Rerun this slice with `--tasks` taken from the current `data/tasks/dev.jsonl`, so that 015 uses its current text.
2. Rerun `sage_gold` on 021 and 017 018 054 060 063 064 087 090 to measure the ceiling after fixes 2 and 4. Today it is only the estimate
   of about 63 / 100.
3. Run `sage` against `sage_r3u` on the fresh slice dev 100..199, paired, with two runs. This is the only out-of-sample check.
4. SAGE-side defects seen here, for the user to decide on:
   - the which-question lists synonyms (4 names for 2 mugs);
   - the KO translator turns "mug" into "미안해요";
   - the coverage check fires on a word the user corrected away;
   - the KO give-up sentence is a translator refusal;
   - `wait_on_robot` is outside the call budget.

## Where a lab flag overlaps the simulator or the bench (audit, 2026-11-06)

A reader of the flag results needs these. The robot_agent flags are generic; the overlap sits in the declared pack data
and in how the simulator is built.

- **`reset_container` (sage_exec, sage_ei_reset, sage_r3, sage_r3u).** The remedy is pack data in robot_agent
  (`planner.recovery.blocked_putin`; none declared = the flag does nothing). The robot package declares none, so the variants carry
  `[Close, Open]` as an overlay (`BLOCKED_PUTIN_OVERLAY`, recorded in `summary.json` `planner_config.manifest_overlay`, `assumed`).
  The mock robot's container state machine rewards exactly that remedy: an Open can silently leave a container half open, a PutIn
  into it then fails "blocked", only a Close clears the state, and a full hand blocks Open and Close (`homeloop_robot` skills).
  A BLOCKED code also covers "no free spot", where a reset cannot help. Read the result as an ablation tied to the simulator rule,
  not as evidence for a general method.
- **`wait_on_robot` (sage_exec, sage_ei_wait, sage_r3, sage_r3u).** The schedule 2, 4, 8 s is assumed (`WAIT_OVERLAY`). The simulator
  clears a camera fault only when ONE wait lasts at least `WAIT_CLEARS_S` = 5 s, so the 2 s and 4 s waits cannot clear it and the effect
  is set by that constant. The default poll (`HEALTH_WAIT_S` = 0.5 s) meets the same rule through the robot's idle-run clearing. A
  sensitivity run with other schedules (for example 1, 2, 4 and 5, 10) is not done yet.
- **`dialog_unstick`.** The simulated user answers a wrong read-back with "no" and the whole request again, and its answer errors are drawn
  independently per answer. A repeated read-back therefore gets a fresh draw of that noise. robot_agent now re-reads a restatement back
  only when it names an entity the request did not, so a bare restatement no longer gains from the re-draw.
- **`name_canon` / `inventory_ask`.** The gain depends on the memory naming of the adapter's `seed_memory` (class and colour+class names in
  EN and KO; a name shared by objects with different usual places is removed, so "mug" is absent while "red mug" and "blue mug" are
  present, which is the which-question case). Test with an instance-keyed memory as well (records with `instance` / `id`).
- **`kind_anchor`.** Its English and Korean open-verb patterns express the same idea as the simulated user's open rule in `dialog.py`; the
  robot's Korean morphology is separate.
- **`go_steps`.** It drops a go to a person; the bench gold is written the same way. Keep the `sage_g2_go` ablation next to it.

## Generalisation audit (lab flags, 2026-11-06)

Question: does each lab flag work from data the robot pack declares, or do nothing, on a robot and a language other
than the HomeLoop ones? Flags: go_steps, kind_anchor, name_canon (sage_ground2); endstate_check, wait_on_robot,
reset_container, gate_strict (sage_exec); inventory_ask (sage_inv); dialog_unstick (sage_unstick); reask_abstain;
the combinations sage_r3 and sage_r3u. Code: robot_agent branch sage-v2/homeloop, head 583747f (baseline 7bd0ee4).

### What was hard-coded, and what moved

| item | before | now |
|---|---|---|
| kind_anchor open words | en/ko/vi in core; any other language dropped the open goal, and the pack's open_words for it were ignored | the run language's words: core (en/ko/vi) plus the pack's i18n open_words for any language; no data means no drop |
| reset_container remedy | Close then Open fixed in core | pack data planner.recovery.blocked_putin; none declared means no-op; all spliced actions must be in plan_actions; no put-down when another hand is free. The bench declares [Close, Open] (BLOCKED_PUTIN_OVERLAY, assumed) |
| endstate_check | fixed re-dock | re-runs the action that achieved the go goal; tries from planner.recovery.return_tries (default 3) |
| dialog_unstick | restatement read back always; structural not-sure fallback also for English | read back only when it adds an ENV entity; fallback only for a language with no answer_unsure data |
| inventory_ask schema | the sim user's qtype in core | neutral {intent, options, about}; the bench adapter maps it with INTENT_TO_QTYPE |
| which-option list | fixed " or " | list slot with the pack's sep_or |
| wait_on_robot | schedule in core | pack data planner.recovery.wait (action, schedule_s); none means no-op |

### What remains

- KO and VI open-word lists stay in core as regexes (pack words are escaped literals); overlap with the sim user's VERB_RX is documented above.
- English paraphrases without an "open" word ("pop the fridge door") still drop an open goal silently; the pack can extend open_words.
- Thresholds in dialog_unstick (MAX_FALLBACK_WORDS, 0.6, 4 words, 6 bigrams) and the Latin-script threshold in language.localized are code constants, not manifest data, with no sensitivity sweep.
- reset_container's put-down is always Place; the wait_on_robot schedule interacts with the simulator's WAIT_CLEARS_S = 5 s.
- Low items not done: typed seconds for Wait, character n-grams, a CJK label_tokens default, name_canon _singular retirement.

### Checks run (CPU only, no GPU, no LLM server, 2026-11-06)

1. Suites: robot_agent worktree (sagev2 embodiplan on PYTHONPATH) exit 0 (2 skipped); homeloop_bench 429 passed in 93 s.
2. Replay of cached episodes (replay_flag.py: source run i2, 31 dev tasks, EN and KO, real profile, cache-only LLM), planners sage, sage_r3 and sage_r3u, run with the pre-refactor code (7bd0ee4) and with HEAD: episodes.jsonl byte-identical in all 6 pairs, and the miss counts are equal (1/9/9 EN, 3/13/17 KO). Flag-off and the flag-on combinations are therefore unchanged on this slice. Limit: replay misses (a prompt the cache never saw) end that episode early, so these runs exercise the cached part of each episode only. The changed flag-on paths (dialog_unstick part 1, reset_container) are covered by unit tests, not by this slice. The n5 / understand-eval set was not replayed again: only the i2 slice is cached under replay/.
3. Third language and second robot (scratch probe, not in the repo, test_generalisation_probe.py in the lab gen notes dir): every flag on, language codes en, qq and xx-YY (no pack words), scripted LLM through the real AssistLoop, 18 loops (clear and abstaining reading, three dialogue scripts): no error. Unit level: for qq, kind_anchor drops nothing without data and honours a declared open_words; blocked_putin_remedy, wait_schedule, fold_rules return empty, localized returns True. The base_robot manifest (MoveTo, Say, Ask, Dock, WaitForUnload, Observe, Verify; no recovery block) loaded with load_manifest: kind_anchor no-op for en, ko, qq; remedy empty and wait (None, []).

### Honest limits

No live run on base_robot and none on a real third language; qq is a made-up code, so it shows fail-open behaviour, not quality. The base_robot check is unit-level (manifest data and helpers), not a loop with its skills. The probe asserts no exception, not a particular outcome. Sensitivity to wait schedules and to an instance-keyed bench memory was not run.

## Generalisation round 6: language and robot facts as data (2026-11-06)

User decision: no language, robot, benchmark or simulator fact in the code of the lab flags. Korean is supported as data,
Vietnamese is dropped, every other list or number is declared data, and missing data means the flag does nothing.
Code: robot_agent branch sage-v2/homeloop, head 686b2b6 (before: 583747f). This section replaces the "What remains"
list of the audit above for the items it names as moved.

### What moved

| item | now |
|---|---|
| open words (en, ko), the other word lists of `lexicon` | language packs `core/planning/lang/en.json`, `ko.json`; a robot pack extends them with its i18n phrase of the same key, for any language |
| not-sure phrases (`CORE_UNSURE`) | pack key `answer_unsure` (English ships it; Korean does not, so Korean still uses the structural fallback, as before) |
| `MAX_FALLBACK_WORDS`, 24 characters, 0.6, 4 words, 3 letters, 6 bigrams | manifest `planner.unstick.*`; a missing number switches that part off. The bench declares the old values as an assumed overlay (`UNSTICK_OVERLAY`), read them as fitted on the dev slice |
| `endstate_check` default of 3 tries | manifest `planner.recovery.return_tries`; none declared = the option does nothing. The bench declares 3 (`RETURN_OVERLAY`, assumed) |
| `LANGS`, `REGISTER`, `NON_ASCII_MIN`, the Korean script test | pack keys `name`, `register`, `non_ascii_min`, `script`; a language without a pack is never "not localized" |
| English articles and plural rules, the model's English where-is patterns (`reask_abstain`) | pack keys `articles`, `plural_rules`, `where_now`, `where_put`, `where_obj`; no data for the prompt language = no-op |
| Vietnamese | removed from the core lists, router, announcer, TTS codes, safety word lists, tests and docs; a test scans the package for it |

### English paraphrase of open (K2)

New option `kind_anchor_ask` (default 0, only with `kind_anchor`). An open goal with no open word in the person's words is
kept and the ordinary read-back says "I am not sure you asked me to open the ...", so the person decides. No new question kind;
the existing `r.unsure` path carries it. Not run on a benchmark yet: it is a prototype with unit tests. Whether the extra
read-back helps or costs a turn is open.

### Checks (CPU only, no GPU, no LLM server)

1. robot_agent suite: all pass (new `tests/test_sage_lab_r6_langdata.py` covers made-up languages: "qq" with no data does
   nothing, "zz" with a pack works, through the real AssistLoop). homeloop_bench: 429 pass.
2. Replay of the cached i2 slice (31 dev tasks, EN and KO, planners sage, sage_r3, sage_r3u, `lab/gen/run_cmp.sh`): episodes.jsonl
   byte-identical to the run on 583747f in all 6 pairs, including the flag-on r3 and r3u with the bench's declared numbers. The
   same limit as before: a replay miss ends an episode early, so only the cached part is exercised.

### Still left

- Korean morphology elsewhere in core (the particle list and the verb endings in `understand`, `speech`, `dialog_converge`, `_EN_INTO`
  / `_KO_INTO` in `goal_fix`) is still code; it is not flag code and moving it would touch every run.
- `AssistLoop._restates` (0.6 / 4 / 3) in the always-on loop and the `understand` word lists for refusals are code.
- Korean has no `answer_unsure` phrases. Adding them would change Korean dialog_unstick behaviour, so it needs an ablation first.
- The pivot language is a code constant (`langdata.PROMPT_LANG = "en"`, the language of the prompts); `lg == "en"` checks in the language layer
  still assume an English pivot. The action names (Find, MoveTo, Open) are the action model's vocabulary.
- The thresholds above are data now but still unvalidated: no sensitivity sweep, and no run on a second robot.

## Round 6, step 1: measurement fixes (2026-11-06; CPU only, no scoring change)

The n5_a2 gate left four measurement problems. They are fixed here before any new run. No rate, no scoring rule and no task changed.

| # | defect (evidence) | fix | test |
|---|---|---|---|
| H1 | `--tasks FILE` was trusted. `results/r4/n5_a2/run.sh` reused the `tasks.jsonl` of `n5_a1` (14:18), older than the tell_fetch re-render (4a0550c, 15:19), so the 015 cells measured the old text. | A tasks file is compared with the packaged train / dev records of the same id. One that differs is refused (`StaleTasksError`, exit 2) unless `--allow-stale`. An id that is not packaged (fixtures, custom tasks) is never stale; the test split is not read. `tasks-file --split S [--ids 14,15]` writes the current records. | `tests/test_measurement_fixes_r6.py` |
| H2 | `inventory_ask` asked "the black mug or the white mug or the black coffee mug or the white coffee mug" for 2 mugs (n5_a2, 014 EN `sage_inv`). robot_agent counts remembered instances (record `instance` / `id`, or the pack's aliases), but the adapter's `seed_memory` wrote name -> place only, so every synonym was its own candidate. Mapping `INTENT_TO_QTYPE` itself was right: the question reached the user as `which_object` with its options. | `seed_memory` adds `instance` (the object id) to a record when the name means exactly one object. The option list is now 2 names for 2 mugs. Other planners are not touched (only `goal_fix.instances` reads the key). | same file |
| H3 | `finish` labelled a give-up `budget` only after a refused call. A planner that stopped with the call or time budget used up but asked for no more call stayed `give_up` (n5_a2 `sage_exec` EN 014: 60 of 60 calls, 360.4 s, empty final_say). The gate text called it a budget stop, the record said give_up. | A `give_up` while the call or the simulated-time budget is used up is `budget`, except when the last call failed with a persistent hardware fault or an e-stop (the robot broke down). `done` and `refuse` keep their status; success is unchanged. | same file |
| H4 | `--shared-cache` existed, but (a) nothing said which episode had asked the server, (b) the user-intent classifier did not read it, (c) no check showed that two identical configurations give identical episodes. | Every cached LLM (planner, translator, intent classifier) counts into a tally. An episode record has `llm_cache` = `{hits, shared, misses, touched}` (`touched` = some prompt went to the server; absent for the fake LLM or no cache). `--shared-cache ROOT --replicate NAME` uses ROOT/NAME, one cache per replicate for all configurations. `aa-check` takes the arguments of `run`, runs the configuration twice on one shared cache (OUT/aa_1, aa_2) and requires identical episodes wherever the second run had 0 misses; it writes OUT/aa_check.json and exits 1 on a difference, 2 when nothing could be compared. | same file |

Left: (1) for a class whose instances all share one usual place (28 % of the multi-instance classes in the dev clarify tasks, for
example two books on one shelf) the bare class name stays in the object memory, so `inventory_ask` has nothing to ask. Dropping the name
would change what every planner remembers, so it is not done. (2) `llm_cache` counts depend on the order of the configurations, so
they are not in summary.json. (3) The A/A check needs a live server to be meaningful for SAGE; it was tested with a local server over the
keyword model only.

## Round 6 understanding loop (2026-11-07)

Question: do the four round-7 understanding variants beat `sage_ground2` in `understand-eval`, and is `no_shared_listener` safe on the
21 tasks that the tellfix data change re-rendered? Method: `understand-eval`, tasks 0..299 of train then dev, EN and KO, `--text both`
(clean and asr), `--profile real --seed 0`, model `qwen3-vl:8b-instruct` (translate model as in `run`, qwen3-vl:30b-a3b-instruct), GPU 0
only, container stopped at the end, at most 8 clients. Baseline = `sage_ground2`, run on the **current** task data (the perf1 cache was the
seed, so only prompts that changed, the 21 tellfix tasks among them, were asked again). Each variant starts from the cache of the one before
it (u1 from the baseline, u2 from u1, u3 from u2); an identical prompt gets the identical answer, so a changed cell comes from a prompt the
variant changed. Headline population: feasible tasks with no refused part (train 964 records, dev 972). Same arguments give identical files.
Kill rule (brief): more losses than gains, or more confident-wrong readings, kills a variant; a variant is kept only if it wins on train AND
dev; `asked-on-exact` (readings that are exact and still asked, variant minus baseline, in points of the headline records) may rise by at most 1.5.

### Result (headline, each variant against `sage_ground2`; variants are cumulative)

| split | variant | exact base -> var | atom precision | atom recall | dropped | spurious | confident-wrong | asked | asked-on-exact | gains / losses |
|---|---|---|---|---|---|---|---|---|---|---|
| train | sage_u1 | 487 -> 515 (+2.9 pt) | 0.762 -> 0.766 | 0.705 -> 0.734 | 522 -> 471 | 390 -> 398 | 252 -> **259** | 240 -> 205 | +0.00 | +28 / -0 |
| train | sage_u2 | 487 -> 553 (+6.8) | 0.762 -> 0.792 | 0.705 -> 0.760 | 522 -> 426 | 390 -> 353 | 252 -> 222 | 240 -> 205 | +0.10 | +73 / -7 |
| train | sage_u3 | 487 -> 516 (+3.0) | 0.762 -> 0.815 | 0.705 -> 0.667 | 522 -> 590 | 390 -> 269 | 252 -> 157 | 240 -> 307 | +0.10 | +61 / -32 |
| dev | sage_u1 | 570 -> 586 (+1.6) | 0.829 -> 0.827 | 0.748 -> 0.772 | 451 -> 408 | 277 -> 290 | 206 -> **216** | 215 -> 189 | +0.00 | +16 / -0 |
| dev | sage_u2 | 570 -> 591 (+2.2) | 0.829 -> 0.834 | 0.748 -> 0.779 | 451 -> 396 | 277 -> 278 | 206 -> **207** | 215 -> 189 | -0.41 | +34 / -13 |
| dev | sage_u3 | 570 -> 548 (-2.3) | 0.829 -> 0.855 | 0.748 -> 0.673 | 451 -> 586 | 277 -> 204 | 206 -> 138 | 215 -> 300 | -0.51 | +28 / -**50** |
| train, first 75 tasks | sage_u | 122 -> 119 of 236 | 0.757 -> 0.746 | 0.709 -> 0.672 | | | 63 -> 54 | 60 -> 81 | **+2.12** | +22 / -**25** |
| dev, first 75 tasks | sage_u | 155 -> 139 of 240 | 0.848 -> 0.797 | 0.793 -> 0.707 | | | 40 -> 31 | 52 -> 84 | **+2.92** | +21 / -**37** |

Increment of each flag over the one before (same cache): `no_shared_listener` (u2 over u1) train +45 / -7, dev +18 / -13 (KO dev +19 / -13, EN dev +15 / -0);
`understand_views` (u3 over u2) train +0 / -37, dev +0 / -43 (it halves the confident-wrong readings, 206 -> 138 on dev, by asking 85 more questions on
the headline tasks and dropping 190 atoms; no exact reading is gained). `understand_goals_first` (u over u3, first 75 tasks): train +14 / -25, dev +17 / -26.
EN and KO, clean and asr rows of every comparison are in `lab/r6/all3.md` (all four cells keep the sign of the total, except u2 KO dev: +19 / -13).
Instrument checks: no record `ended` in any run; the baseline records differ from perf1 only on the 21 tellfix tasks.

### The 21 shared_listener cases (tellfix tasks, `no_shared_listener` = u2 against u1, 84 records)

Tasks (train) 15 24 95 169 208 255 279 and (dev) 15 24 39 59 95 135 161 168 204 208 240 257 277 281. Exact readings 51 -> 36 (gains 0, losses 15),
dropped atoms 27 -> 43, spurious 29 -> 45, confident-wrong 23 -> 31. The rule is right on exactly the tasks that were re-rendered to test it, so
`no_shared_listener` is **not** a safe switch-off: its gains in the full set come from other tasks, and the 78 losses of round 5 were not the
tellfix family alone. Decision: **kill `no_shared_listener` as a blanket flag**; if the rule is to be narrowed, narrow it on the structure (a recipient
named once and not a speaker), not by removing it.

### Keep / kill

| variant (flag) | verdict | reason |
|---|---|---|
| sage_u1 (`reask_anchor`) | **kill by the rule** (near miss) | confident-wrong rises on train (+7) and dev (+10) although exact rises with no loss (+28/-0, +16/-0) and asks fall 35 / 26. The extra confident readings are the goal-less ones turned into goals, a third of them wrong. Needs the end-to-end gate to decide, not this metric |
| sage_u2 (`no_shared_listener`) | **kill** | dev confident-wrong 206 -> 207; 0 gains / 15 losses on the 21 cases; 13 dev losses |
| sage_u3 (`understand_views`) | **kill** | dev losses 50 > gains 28, recall -7 pt; asks 85 more questions |
| sage_u (`understand_goals_first`) | **kill** | more losses than gains in both splits, asked-on-exact +2.1 / +2.9 (limit 1.5) |

None of the four wins on train AND dev under the kill rule. Nothing from round 7 is switched on by default.

### Caveats

- `sage_u` was run on tasks 0..74 of each split only (all four conditions, 236 / 240 headline records), not 0..299: the shared GPU served about 30 LLM calls a
  minute when eight clients ran, and `sage_u` changes every understand prompt (about 2 hours for the full window). It is killed by inheritance from `sage_u3` and by the numbers of the window; the rest are full windows.
- Gold atoms compare only the person of a `say`, and the gold place for "bring it here" is the dock; both are limits of the metric (see `understand_eval.md`).
- A first-reading metric: the read-back and the clarify dialogue are not run. `reask_anchor` and `understand_views` both change what the loop asks, so their end-to-end effect is unknown.
- `asked-on-exact` is measured as (exact and asked) in the variant minus the same count in the baseline; the brief does not define it more closely.
- Work files (cache copies, records, shard logs): `lab/r6/` in the scratchpad; not in the repo.
