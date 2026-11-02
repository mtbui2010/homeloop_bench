"""HomeLoop-Bench data: the task files and their quality reports (docs/datasheet.md).

DATA_DIR      homeloop_bench/data            (inside the package: tasks, label policy, LLM cache)
TASKS_DIR     homeloop_bench/data/tasks      ({train,dev,test}.jsonl)
QUALITY_DIR   <repo>/data/quality            (generated reports: realism, paraphrase and back-translation quality)

The reports and the generated docs (docs/datasheet.md, docs/paraphrase_quality.md) belong to the source checkout.
In an installed (non-editable) package there is no <repo>: the report commands then write to
``$HOMELOOP_QUALITY_DIR`` (default ``./homeloop_quality``) and do not write docs (``SOURCE_CHECKOUT`` is False).
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
TASKS_DIR = DATA_DIR / "tasks"
CACHE_DIR = DATA_DIR / "llm_cache"
POLICY = DATA_DIR / "label_policy.yaml"
REPO_DIR = DATA_DIR.parent.parent
SOURCE_CHECKOUT = (REPO_DIR / "pyproject.toml").is_file() and (REPO_DIR / "homeloop_bench").is_dir()
QUALITY_DIR = (REPO_DIR / "data" / "quality" if SOURCE_CHECKOUT
               else Path(os.environ.get("HOMELOOP_QUALITY_DIR", "homeloop_quality")).resolve())
SPLITS = ("train", "dev", "test")
