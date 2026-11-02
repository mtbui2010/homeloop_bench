"""Task records (DESIGN 10.1, 14): the dataclass and loaders. docs/tasks.md describes every field."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator, Optional

from .data import SPLITS, TASKS_DIR


@dataclass(frozen=True)
class Task:
    id: str
    split: str
    house: str
    seed_state: int
    text: dict
    goal: dict
    kind: str
    capability: str
    ambiguity: str
    source: str
    template_id: str
    refuse_reason: Optional[str]
    hazards: list
    user: dict
    expected: dict
    meta: dict
    subtasks: list = field(default_factory=list)
    n_subtasks: int = 1
    structure: str = "single"
    order: Optional[list] = None
    mixed_kind: bool = False
    length_words: dict = field(default_factory=dict)
    activity_source: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        names = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in names})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _path(split: str):
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r} (one of {SPLITS})")
    return TASKS_DIR / f"{split}.jsonl"


def read_records(split: str, path=None) -> list:
    p = path or _path(split)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@lru_cache(maxsize=8)
def _load(split: str) -> tuple:
    return tuple(Task.from_dict(d) for d in read_records(split))


def load_split(split: str) -> list:
    """Tasks of a split in file order."""
    return list(_load(split))


def iter_tasks(splits=SPLITS) -> Iterator[Task]:
    for s in splits:
        yield from _load(s)


def task_by_id(task_id: str) -> Task:
    split = task_id.split("-")[1] if task_id.count("-") >= 2 else None
    for t in iter_tasks((split,) if split in SPLITS else SPLITS):
        if t.id == task_id:
            return t
    raise KeyError(task_id)
