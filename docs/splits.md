# Splits

| split | tasks | houses | template ids |
|---|---|---|---|
| train | 6,000 | 6: couple_flat, family_house, korean_apt_59, senior_flat, shared_flat, studio_flat | not the test-only ids |
| dev | 1,000 | the same 6 | not the test-only ids |
| test | 3,000 | all 8 (also korean_apt_84 and care_home_suite, held out) | all, including test-only ids |

- **Held-out houses**: `korean_apt_84` (an 84 m2 Korean apartment with a child and a grandmother) and
  `care_home_suite` (a care-home resident and a caregiver) appear only in test, so test measures generalisation to
  new layouts, people and object sets.
- **Test-only templates** (DESIGN 10.3): single-instruction wrappers 08 ("{Vp} when you get a chance.") and 09 ("Do
  me a favor and {vp}.") with the Korean -주실래요? ending, and compound join pattern 4 of every family. Test draws
  them in about 35 % of its tasks; `validate` check 8 fails if any appears in train or dev.
- **Duplicates**: no two tasks anywhere share a normalised text in either language (NFKC, lower case, punctuation
  removed, whitespace collapsed; Korean also without spaces). No text is a near duplicate of a text in another split
  (Jaccard >= 0.90 of character 5-grams in English, 3-grams in Korean; MinHash LSH candidates, then the exact
  Jaccard). Both are enforced while generating and paraphrasing, and checked by `validate` (check 3).
- **File order**: shuffled by the generation seed, then interleaved round-robin over (kind, capability), so the
  first few hundred dev tasks contain every kind and every capability (the acceptance check runs dev with
  `--limit 300`).
- **Ids**: `hl-<split>-<6 digits>` in file order.

Implementation: `homeloop_bench/gen/split.py`, `homeloop_bench/gen/dedup.py`; the house sets are
`gen/sample.SPLIT_HOUSES`.
