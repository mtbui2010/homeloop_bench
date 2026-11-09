# LoRA for the understand step (lab tooling)

A learned variant of robot_agent's reader: Qwen3-VL-8B-Instruct (Apache-2.0) with a LoRA adapter trained on the
UNDERSTAND step only. It is never the plain `robot_agent:sage` row; report it as a learned variant, with the split its
labels came from (train only; dev for validation; test never read).

## What lives where

| part | where |
|---|---|
| generic trainer, merge, GGUF splice, Ollama import, serve check | the lab's `lora-finetune` skill scripts (`train_lora.py`, `merge_lora.py`, `gguf_splice.py`, `ollama_import.sh`, `serve_check.py`); no HomeLoop facts |
| task-specific data builders and configs | `tools/lora/` (this repo) |
| weights, datasets, runs, GGUF files, the private Ollama store, the venv | `<NAS>/homeloop_lora/` (`HOMELOOP_LORA_DIR` in the configs), never git |

## Serving a fine-tuned model with the bench

Ollama 0.35 refuses LoRA adapters (`ADAPTER` in a Modelfile). The working path: merge the adapter into the bf16 base,
splice the merged language layers (Q8_0) into the Ollama build of `qwen3-vl:8b-instruct` (every other tensor, the
metadata, the tokenizer and the renderer stay as they are), and `ollama create` the result into a private, writable
store. That store reuses the base models' blobs through symlinks into the shared store, so the server mounts both, read-only:

```bash
OLLAMA_MODELS_DIR=<NAS>/homeloop_lora/ollama_store OLLAMA_EXTRA_RO=<shared model store dir> bash tools/llm_gpu0.sh start
homeloop-bench understand-eval --planner robot_agent:sage_s8n --split dev --limit 30 --lang en,ko \
    --llm http://127.0.0.1:11536 --understand-model qwen3-vl-8b-understand:p0 --out OUT
bash tools/llm_gpu0.sh stop
```

`OLLAMA_EXTRA_RO` mounts each listed host directory read-only at the same path (needed for the symlinked blobs). The
private store holds the stock models as well, so the planner and translator models keep working.

## The JSON key order

Ollama's `format` grammar emits keys in the ORDER of the schema's `properties` (required ones first). robot_agent sends
its UNDERSTAND schema in its own order (`status, reason, question, goals`; goal items `type, object, from, to`), but the
bench's llm_cache stores `format` with sorted keys. The data builder restores robot_agent's order for the training target
and for the schema it stores with each example, so the target, the served request and the grammar agree.

## P0 smoke test (2026-11-09, plumbing only, no quality claim)

200 examples from the train-split understand-eval cache (targets = the stock model's own answers), 40 steps, LoRA r16 on
the 252 language linear layers. The served model answered 20/20 validation prompts with schema-valid JSON and the same
prompt token count as the training template, and ran understand-eval on 30 dev tasks (EN + KO, clean + ASR, 120 calls,
0 fallbacks). Numbers and commands: the lab notes of round r20.

## P2 small real run (2026-11-09, learned variant; labels from the TRAIN split gold goals)

2,000 rows stratified by language, kind, expect, structure and noise from the P1 `inferable` set (seed 0); config
`tools/lora/configs/p2_small.yaml` (LoRA r16 on the 252 language linear layers, lr 2e-4, effective batch 16, one epoch =
125 steps, two GPUs data-parallel, 32 min). Validation loss on the 492 P1 validation rows: 0.046 (step 25) -> 0.0054 (step
125). Served as `hl-understand-ft-small` by the path above; the served model gave the same JSON as offline bf16 generation on
20/20 validation prompts.

understand-eval, `robot_agent:sage_s8n`, dev tasks 0..149, EN + KO, clean + ASR, profile real, seed 0, headline records
(484):

| reader | exact EN | exact KO | exact | atom P / R | dropped / spurious | confident wrong | asked (on exact) |
|---|---|---|---|---|---|---|---|
| stock 8B, run in the same session | 0.657 | 0.529 | 0.593 | 0.839 / 0.765 | 210 / 131 | 105 | 106 (18) |
| stock 8B, cached perf1 readings | 0.653 | 0.545 | 0.599 | 0.841 / 0.762 | 212 / 129 | 98 | 111 (17) |
| hl-understand-ft-small | 0.839 | 0.789 | 0.814 | 0.928 / 0.901 | 88 / 62 | 66 | 27 (4) |

Paired with the stock reader of the same session: 111 gains, 4 losses on exact match (two stock runs differ by 9 / 6:
Ollama at temperature 0 is not fully deterministic with parallel requests). Format failures: 0 of 488 responses (stock:
1 of 489). No fallback to the planner. A regression probe of 10 general English / Korean prompts passed 10/10 before and
after. KO ASR stays the weakest condition (0.686), and conditional tasks (left out of the training set) are 15 of the 90
remaining failures. Pre-registered gate (exact higher in both languages, confident wrong not higher, format failures under
1 %): passed. Prompt list of the probe: `tools/lora/configs/regression_probe.jsonl`.
