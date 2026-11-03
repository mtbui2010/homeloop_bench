"""Fresh pilot round 1 (docs/experiments.md "Pilot rounds", hl-dev-000057 / 000016 EN): robot_agent's
``understand.place_mentions`` also takes the last word of a multi-word ENV head as a place phrase, so the
speaker's earlier ENV key "spot near you" made every "you" of an instruction ("Can you put ...") a mention of the
speaker's spot (3,947 of the 6,000 dev / test EN instructions). SAGE then asked "You mentioned the you. What
should I do there?" and read back "(the you you mentioned is not in my plan)". Here robot_agent's own matcher runs
on every dev / test instruction, EN and KO: a person's ENV entry is mentioned only by one of that person's names
(the key or an alias), never by a stray word of the key."""
import json

import pytest

pytest.importorskip("robot_agent")

from robot_agent.core.planning.assist_loop import Places  # noqa: E402
from robot_agent.core.planning.understand import place_mentions  # noqa: E402

from homeloop_bench.data import DATA_DIR  # noqa: E402
from homeloop_robot.configs.tasks import env_for  # noqa: E402
from homeloop_robot.world import from_house  # noqa: E402


def test_people_are_mentioned_only_by_their_names():
    envs: dict = {}
    stray: dict = {}
    n = 0
    for split in ("dev", "test"):
        for line in (DATA_DIR / "tasks" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            if t["house"] not in envs:
                env = env_for(from_house(t["house"], 0))
                envs[t["house"]] = (env, Places(env))
            env, places = envs[t["house"]]
            for lang in ("en", "ko"):
                n += 1
                for _s, _e, phrase, keys, _src in place_mentions(t["text"][lang], places):
                    for k in keys:
                        e = env[k]
                        if e.get("person") and phrase.lower() not in {k.lower()} | {a.lower() for a in e["aliases"]}:
                            stray.setdefault((lang, k, phrase), t["id"])
    assert n == 12000
    assert not stray, sorted(stray.items())[:10]
