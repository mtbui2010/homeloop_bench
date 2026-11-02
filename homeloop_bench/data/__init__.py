"""HomeLoop-Bench data: the task files and their quality reports (docs/datasheet.md).

DATA_DIR      homeloop_bench/data            (inside the package: tasks, label policy, LLM cache)
TASKS_DIR     homeloop_bench/data/tasks      ({train,dev,test}.jsonl)
QUALITY_DIR   <repo>/data/quality            (generated reports: realism, paraphrase and back-translation quality)
"""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
TASKS_DIR = DATA_DIR / "tasks"
CACHE_DIR = DATA_DIR / "llm_cache"
POLICY = DATA_DIR / "label_policy.yaml"
REPO_DIR = DATA_DIR.parent.parent
QUALITY_DIR = REPO_DIR / "data" / "quality"
SPLITS = ("train", "dev", "test")
