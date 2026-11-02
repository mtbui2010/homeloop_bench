"""Sampler (DESIGN 10.4, 10.6, 13, 14): stratified task generation over the houses, split by split.

``generate(gen_seed, sizes)`` -> {split: [record, ...]} (records without ids; ``split.assign_ids`` orders and numbers
them). For every family in ``PLAN`` and every split, worlds (house, seed_state) are drawn round-robin over the
split's houses; an option of the family in that world is rendered in English and Korean and kept when:
  * its goal validates, is not already true, needs no hazard (feasible / clarify) and the oracle solves it; a refuse
    task's request has a sourced hazard (unsafe) or cannot be solved for a non-hazard reason (infeasible);
  * both texts pass the language rule R-g;
  * neither text duplicates (after normalisation) any text already generated, and neither is a near duplicate of a
    text in another split (dedup.py).
"""

from __future__ import annotations

import copy

from homeloop_robot import goals as G
from homeloop_robot import oracle
from homeloop_robot.hazards import goal_hazards
from homeloop_robot.rng import derive_seed, rng_for
from homeloop_robot.world import from_house

from . import compound as CP
from . import families as F
from . import single as S
from . import templates_en as EN
from .clauses import tidy
from .dedup import NearDupIndex, norm
from .lexicon import PERSONA, Lex
from .sources import activity_for, compound_activity, hazard_entries
from .textcheck import check_text, words

GENERATOR = "homeloop_bench 0.1.0"
HELD_OUT = ("korean_apt_84", "care_home_suite")
ALL_HOUSES = ("care_home_suite", "couple_flat", "family_house", "korean_apt_59", "korean_apt_84", "senior_flat",
              "shared_flat", "studio_flat")
SPLIT_HOUSES = {"train": tuple(h for h in ALL_HOUSES if h not in HELD_OUT),
                "dev": tuple(h for h in ALL_HOUSES if h not in HELD_OUT), "test": ALL_HOUSES}
SIZES = {"train": 6000, "dev": 1000, "test": 3000}
MOTION = {"move", "pick", "place", "put_in", "open", "close", "handover", "dock"}

# family key -> (type, generator, option filter, count over the whole dataset)
PLAN = [
    # single instructions
    ("fetch.me", "single", "fetch.me", None, 380),
    ("fetch.to", "single", "fetch.to", None, 230),
    ("rearrange.on", "single", "rearrange.on", None, 380),
    ("contain.in", "single", "contain.in", None, 380),
    ("articulate.open", "single", "articulate.open", None, 420),
    ("multi.place", "single", "multi", "multi.place", 260),
    ("multi.me", "single", "multi", "multi.me", 160),
    ("search.me", "single", "search", "search.me", 310),
    ("search.home", "single", "search", "search.home", 260),
    ("message.tell", "single", "message.tell", None, 380),
    ("navigate.room", "single", "navigate.room", None, 600),
    ("correction.object", "single", "correction", "correction.object", 200),
    ("correction.dest", "single", "correction", "correction.dest", 200),
    ("correction.stop", "single", "correction", "correction.stop", 100),
    ("clarify.pref", "single", "clarify.pref", None, 400),
    ("clarify.cs.drink", "single", "clarify.cs", "clarify.cs.drink", 130),
    ("clarify.cs.away", "single", "clarify.cs", "clarify.cs.away", 420),
    ("clarify.safety", "single", "clarify.safety", None, 320),
    ("refuse.unsafe", "single", "refuse.unsafe", None, 520),
    ("refuse.infeasible", "single", "refuse.infeasible", None, 260),
    # compound instructions: sequence
    ("errand_put_fetch", "compound", "errand_put_fetch", None, 150),
    ("fetch_tell", "compound", "fetch_tell", None, 110),
    ("fetch_dock", "compound", "fetch_dock", None, 90),
    ("tell_fetch", "compound", "tell_fetch", None, 120),
    ("mix_pref", "compound", "mix_pref", None, 220),
    ("mix_microwave_refuse", "compound", "mix_microwave_refuse", None, 110),
    # conjunction
    ("tidy_list", "compound", "tidy_list", None, 280),
    ("put_two", "compound", "put_two", None, 150),
    ("fetch_two_people", "compound", "fetch_two_people", None, 110),
    ("fetch_three", "compound", "fetch_three", None, 110),
    ("mix_fridge_refuse", "compound", "mix_fridge_refuse", None, 60),
    # ordered
    ("first_put_then_fetch", "compound", "first_put_then_fetch", None, 200),
    ("first_tell_then_fetch", "compound", "first_tell_then_fetch", None, 120),
    ("dinner", "compound", "dinner", None, 60),
    ("first_put_then_dock", "compound", "first_put_then_dock", None, 130),
    # conditional (assumed source: capped at 5 % of the tasks, USER_FEEDBACK 7)
    ("cond_put_fetch", "compound", "cond_put_fetch", None, 180),
    ("cond_put_tell", "compound", "cond_put_tell", None, 140),
    ("cond_bring_else", "compound", "cond_bring_else", None, 120),
    # shared object
    ("put_in_close", "compound", "put_in_close", None, 230),
    ("fetch_from_close", "compound", "fetch_from_close", None, 120),
    ("open_put", "compound", "open_put", None, 140),
    ("take_out_put", "compound", "take_out_put", None, 30),
    # with context
    ("ctx_tidy", "compound", "ctx_tidy", None, 200),
    ("ctx_going_out", "compound", "ctx_going_out", None, 60),
    ("ctx_evening", "compound", "ctx_evening", None, 130),
    ("ctx_cooking", "compound", "ctx_cooking", None, 130),
    ("mix_pills", "compound", "mix_pills", None, 110),
    ("mix_drink", "compound", "mix_drink", None, 90),
    ("mix_clean_refuse", "compound", "mix_clean_refuse", None, 130),
    # self-correction in the utterance
    ("corr_object", "compound", "corr_object", None, 200),
    ("corr_dest", "compound", "corr_dest", None, 250),
    ("corr_person", "compound", "corr_person", None, 120),
]
# when a family cannot fill its quota, the rest goes to these (in order)
FALLBACK = ["first_put_then_fetch", "put_two", "errand_put_fetch", "corr_dest", "rearrange.on", "contain.in",
            "fetch.me", "clarify.cs.away", "clarify.pref", "put_in_close"]
DOCK_P = 0.45


def quotas(target: int, weights: list) -> list:
    """Largest-remainder allocation of ``target`` over ``weights`` (sums to target exactly)."""
    tot = sum(weights)
    raw = [target * w / tot for w in weights]
    q = [int(x) for x in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - q[i]), i))
    for i in order[:target - sum(q)]:
        q[i] += 1
    return q


def split_quota(total: int, sizes: dict) -> dict:
    n = sum(sizes.values())
    q = {s: int(total * v / n) for s, v in sizes.items()}
    rem = total - sum(q.values())
    for s in sorted(sizes, key=lambda x: -sizes[x])[:rem]:
        q[s] += 1
    return q


class Gen:
    def __init__(self, gen_seed: int = 2026, sizes: dict | None = None, plan_scale: float = 1.0):
        self.seed = gen_seed
        self.sizes = dict(sizes or SIZES)
        self.scale = sum(self.sizes.values()) / sum(t for *_, t in PLAN) * plan_scale
        self.seen = {"en": set(), "ko": set()}
        self.near = NearDupIndex()
        self.out = {s: [] for s in self.sizes}
        self.stats = {"rejected": {}}
        self._k = 0

    def _rej(self, why):
        self.stats["rejected"][why] = self.stats["rejected"].get(why, 0) + 1

    # ── one split, one family ────────────────────────────────────────────────────────────────────────
    def fill(self, split: str, key: str, typ: str, gen: str, filt, n: int, max_tries: int | None = None) -> int:
        houses = SPLIT_HOUSES[split]
        got = 0
        tries = 0
        max_tries = max_tries or max(60, n * 25)
        dead = set()
        while got < n and tries < max_tries and len(dead) < len(houses):
            house = houses[(tries + got) % len(houses)]
            tries += 1
            if house in dead:
                continue
            rng = rng_for(self.seed, "gen", split, key, tries)
            seed_state = rng.randrange(10000)
            w = from_house(house, seed_state)
            lex = Lex(w)
            if typ == "single":
                ops = [o for o in F.FAMILIES[gen](lex) if filt is None or o["fam"] == filt]
            else:
                ops = CP.FAMILIES[gen](CP.Pools(lex), rng)
            if not ops:
                if tries > len(houses) * 6 and not self._any_ok.get((house, key)):
                    dead.add(house)
                continue
            rng.shuffle(ops)
            for op in ops[:4]:
                rec = self.make(split, lex, w, house, seed_state, typ, key, op, rng)
                if rec is not None:
                    self._any_ok[(house, key)] = True
                    self.out[split].append(rec)
                    got += 1
                    break
        return got

    _any_ok: dict = {}

    def _tid(self, split, rng, n, test_ids):
        if split == "test" and rng.random() < 0.35:
            return rng.choice(sorted(test_ids))
        return rng.choice([i for i in range(n) if i not in test_ids])

    # ── one record ───────────────────────────────────────────────────────────────────────────────────
    def make(self, split, lex, w, house, seed_state, typ, key, op, rng):
        if typ == "single":
            tid = self._tid(split, rng, S.N_WRAP, EN.WRAP_TEST)
            ok, why = self.check_single(w, op)
            if not ok:
                self._rej(why)
                return None
            r = S.render(lex, op, rng, tid)
            if r is None:
                self._rej("no_text")
                return None
            rec = self.single_record(split, lex, w, house, seed_state, key, op, r, tid, rng)
        else:
            nn = self._tid(split, rng, CP.N_PAT, CP.TEST_PATTERNS)
            cand = op
            r = CP.render(lex, cand, rng, nn)
            if r is None:
                self._rej("no_text")
                return None
            if rng.random() < DOCK_P:
                cand, r = CP.add_dock(lex, cand, r, rng, nn)
            ok, why = self.check_compound(w, cand)
            if not ok:
                self._rej(why)
                return None
            rec = self.compound_record(split, lex, w, house, seed_state, key, cand, r, nn, rng)
            if rec is None:
                return None
        compound = rec["n_subtasks"] > 1 or rec["structure"] != "single"
        rec["text"] = {lg: tidy(t) for lg, t in rec["text"].items()}
        rec["length_words"] = {lg: words(rec["text"][lg], lg) for lg in ("en", "ko")}
        for lg in ("en", "ko"):
            errs = check_text(rec["text"][lg], lg, compound)
            if errs:
                self._rej("R-g:" + errs[0].split(" ")[0])
                return None
        for lg in ("en", "ko"):
            if norm(rec["text"][lg], lg) in self.seen[lg]:
                self._rej("exact_dup")
                return None
            if self.near.find(rec["text"][lg], lg, other_than=split) is not None:
                self._rej("near_dup")
                return None
        # the oracle must solve it in the ideal profile through the real robot (protective stops included)
        from .oracle_check import run_shim
        probe = dict(rec, id=f"probe-{split}-{self._k}")
        res = run_shim(probe, "en")
        if not res["success"]:
            self._rej("oracle_ideal:" + res["reason"].split(":")[0][:40])
            return None
        rec["expected"]["oracle_calls"] = res["calls"]
        self._k += 1
        k = f"g{self._k}"
        rec["_key"] = k
        for lg in ("en", "ko"):
            self.seen[lg].add(norm(rec["text"][lg], lg))
            self.near.add(k, rec["text"][lg], lg, split)
        return rec

    def check_single(self, w, op):
        goal = op["goal"]
        if op["kind"] == "refuse":
            req = op["requested"]
            if G.validate(req, w):
                return False, "invalid_request"
            if op["refuse_reason"] == "unsafe":
                return (bool(goal_hazards(w, req)), "no_hazard")
            return (oracle.solve(w, req) is None, "infeasible_solvable")
        n = F.solvable(w, goal)
        if not n:
            return False, "unsolvable"
        it = op.get("interrupt")
        if it:
            plan = oracle.solve(w, goal)
            if sum(1 for c in plan if c.skill in MOTION) < 3:
                return False, "interrupt_short_plan"
            if it.get("new") and not F.solvable(w, {"all": [it["new"]]}):
                return False, "interrupt_new_unsolvable"
        for c in (op.get("clar") or {}).get("cands", []):
            if isinstance(c, dict):
                if not F.solvable(w, {"all": [c]}):
                    return False, "candidate_unsolvable"
        return True, ""

    def check_compound(self, w, cand):
        atoms = [a for s in cand["subs"] for a in s["goal"]["all"]]
        goal = {"all": atoms}
        if not 1 <= len(atoms) <= 6:
            return False, "n_atoms"
        if G.validate(goal, w):
            return False, "invalid_goal"
        if goal_hazards(w, goal):
            return False, "hazard"
        objs = [a["args"][0] for a in atoms if a["pred"] in ("on", "in", "held_by", "delivered", "unmoved")]
        if len(objs) != len(set(objs)):
            return False, "shared_object_conflict"
        for s in cand["subs"]:
            if s["kind"] in ("feasible", "clarify") and not s.get("restore") and not s.get("noop"):
                if G.evaluate(s["goal"], w).holds:
                    return False, "subtask_true"
            if s["kind"] == "refuse" and not goal_hazards(w, {"all": s["requested"]}):
                return False, "refuse_without_hazard"
        if G.evaluate(goal, w).holds:
            return False, "goal_true"
        plan = oracle.solve(w, goal)
        if plan is None:
            return False, "unsolvable"
        # ordered: each prefix must be solvable on its own (the bench oracle does the subtasks in order)
        if cand.get("order"):
            ww = w.copy()
            for i in range(len(cand["subs"])):
                pre = {"all": [a for s in cand["subs"][:i + 1] for a in s["goal"]["all"]]}
                if oracle.solve(ww, pre) is None:
                    return False, "ordered_prefix_unsolvable"
        return True, ""

    # ── record builders ──────────────────────────────────────────────────────────────────────────────
    def base(self, split, lex, w, house, seed_state):
        return {"split": split, "house": house, "seed_state": int(seed_state), "source": "template",
                "source_by_lang": {"en": "template", "ko": "template"}, "paraphrase_model": {"en": None, "ko": None},
                "user": {"persona": PERSONA.get(house, "adult"), "candidates": [], "answer": None,
                         "gold_question": None, "interrupt": None}}

    def single_record(self, split, lex, w, house, seed_state, key, op, r, tid, rng):
        rec = self.base(split, lex, w, house, seed_state)
        cap, kind, amb = op["capability"], op["kind"], op["ambiguity"]
        goal = copy.deepcopy(op["goal"])
        hz = hazard_entries(op["hazards"]) if op["hazards"] else []
        st = {"kind": kind, "capability": cap, "ambiguity": amb, "goal": goal}
        if kind == "refuse":
            st.update(refuse_reason=op["refuse_reason"], requested=op["requested"]["all"], hazards=hz)
        user = rec["user"]
        u = r.get("user") or {}
        if "interrupt" in u:
            it = dict(u["interrupt"])
            it.pop("ents", None)
            user["interrupt"] = it
        for k in ("slot", "intended", "candidates", "answer", "gold_question", "safe_resolution"):
            if k in u:
                user[k] = u[k]
        if kind == "clarify":
            st["candidates"] = [c.get("id") for c in user.get("candidates", [])]
        plan = oracle.solve(w, goal) if kind != "refuse" else []
        rec.update({
            "text": {"en": r["en"], "ko": r["ko"]}, "goal": goal, "kind": kind, "capability": cap, "ambiguity": amb,
            "template_id": f"{cap}.{kind}.{tid:02d}", "refuse_reason": op["refuse_reason"], "hazards": hz,
            "expected": {"must_ask": kind == "clarify", "must_refuse": kind == "refuse",
                         "oracle_calls": len(plan or []), "partial_refuse": []},
            "subtasks": [st], "n_subtasks": 1, "structure": "single", "order": None, "mixed_kind": False,
            "length_words": {lg: words(r[lg], lg) for lg in ("en", "ko")},
            "activity_source": activity_for(op["fam"]),
            "meta": {"family": op["fam"], "plan_key": key, "template_text": None, "paraphrase": None,
                     "generator": GENERATOR, "gen_seed": self.seed, "requested_goal": op.get("requested"),
                     "entities": r["ents"], "ko_particle_dropped": bool(r.get("ko_dropped")),
                     "reason": r.get("reason")},
        })
        return rec

    def compound_record(self, split, lex, w, house, seed_state, key, cand, r, nn, rng):
        rec = self.base(split, lex, w, house, seed_state)
        subs = copy.deepcopy(cand["subs"])
        kinds = [s["kind"] for s in subs]
        top = "refuse" if all(k == "refuse" for k in kinds) else ("clarify" if "clarify" in kinds else "feasible")
        goal = {"all": [a for s in subs for a in s["goal"]["all"]]}
        if top == "refuse":
            goal["refuse"] = True
        cl = [s for s in subs if s["kind"] == "clarify"]
        amb = cl[0]["ambiguity"] if cl else "none"
        hz = []
        for s in subs:
            if s.get("hazards"):
                s["hazards"] = hazard_entries(s["hazards"]) if isinstance(s["hazards"][0], str) else s["hazards"]
                hz += s["hazards"]
            for k in ("group", "cls", "reason", "pron"):
                s.pop(k, None)
        if cl:
            c = cand["subs"][[i for i, s in enumerate(cand["subs"]) if s["kind"] == "clarify"][0]]
            atom = c["goal"]["all"][0]
            u = S.clarify_object_user(lex, c["candidates"], atom["args"][0], atom, c.get("group"), rng)
            rec["user"].update(u)
        caps = [s["capability"] for s in subs]
        st = cand["structure"]
        if st == "correction":
            cap = "correction"
        elif cand["family"] in ("tidy_list", "ctx_tidy", "fetch_three", "put_two") or (
                len([c for c in caps if c in ("fetch", "rearrange", "contain")]) >= 3):
            cap = "multi_object"
        else:
            cap = [c for c in caps if c != "navigate"][0] if any(c != "navigate" for c in caps) else caps[0]
        plan = oracle.solve(w, {"all": goal["all"]})
        rec.update({
            "text": {"en": r["en"], "ko": r["ko"]}, "goal": goal, "kind": top, "capability": cap, "ambiguity": amb,
            "template_id": f"compound.{cand['family']}.{nn:02d}", "refuse_reason": "unsafe" if top == "refuse" else None,
            "hazards": hz,
            "expected": {"must_ask": bool(cl), "must_refuse": top == "refuse", "oracle_calls": len(plan or []),
                         "partial_refuse": [i for i, s in enumerate(subs) if s["kind"] == "refuse"]},
            "subtasks": subs, "n_subtasks": len(subs), "structure": st, "order": cand.get("order"),
            "mixed_kind": len(set(kinds)) > 1,
            "length_words": {lg: words(r[lg], lg) for lg in ("en", "ko")},
            "activity_source": compound_activity(cand["src"], cand.get("src2")),
            "meta": {"family": "compound." + cand["family"], "plan_key": key, "template_text": None, "paraphrase": None,
                     "generator": GENERATOR, "gen_seed": self.seed, "requested_goal": None, "entities": r["ents"],
                     "ko_particle_dropped": bool(r.get("ko_dropped")), "reason": None},
        })
        return rec

    # ── whole dataset ────────────────────────────────────────────────────────────────────────────────
    def run(self, log=None) -> dict:
        Gen._any_ok = {}
        for split in sorted(self.sizes, key=lambda s: {"test": 0, "dev": 1, "train": 2}[s]):
            target = self.sizes[split]
            deficit = 0
            qs = quotas(target, [t for *_, t in PLAN])
            for (key, typ, gen, filt, total), n in zip(PLAN, qs):
                got = self.fill(split, key, typ, gen, filt, n)
                deficit += n - got
                if log and n - got:
                    log(f"[{split}] {key}: {got}/{n}")
            missing = target - len(self.out[split])
            fb = 0
            while missing > 0 and fb < len(FALLBACK) * 3:
                key = FALLBACK[fb % len(FALLBACK)]
                fb += 1
                typ, gen, filt = next((t, g, f) for k, t, g, f, _ in PLAN if k == key)
                got = self.fill(split, key, typ, gen, filt, min(missing, max(10, missing // 3)))
                missing -= got
            if log:
                log(f"[{split}] {len(self.out[split])} records (target {target}, fallback used {deficit})")
        _ = derive_seed
        return self.out


def generate(gen_seed: int = 2026, sizes: dict | None = None, log=None) -> dict:
    return Gen(gen_seed, sizes).run(log=log)
