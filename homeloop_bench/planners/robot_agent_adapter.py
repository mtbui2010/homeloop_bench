"""robot_agent planners on the homeloop robot: ``robot_agent:sage``, ``robot_agent:grace``,
``robot_agent:llm_direct`` (docs/robot_agent.md).

robot_agent is imported inside functions only, so the planner listing works without it. Per episode:

1. ``homeloop_robot.configs.backend.set_backend(proxy)``: the proxy's ``call`` goes through
   ``env.call`` (budgets, the call log and interruptions apply), so the robot package's own skill
   functions (``configs/ra_skills.py``) are what robot_agent executes.
2. The module-level hooks robot_agent's own tests replace (``state.current``, ``assist_loop.current`` /
   ``loop.current`` -> a FakeState with ``robot_pkg="homeloop_robot"``; ``host_id`` -> "homeloop";
   ``skill_configs.ENV`` -> ``env_for(world)``; ``connect.llm.init_llm_client``), restored after the episode;
   a fresh run manager and run-control state.
3. The loop: sage = ``AssistLoop`` (generator ``grace``), grace = ``ClosedLoop(planner="grace")``,
   llm_direct = ``ClosedLoop(planner="llm_direct")``. Its LLM client is our counted client (live: Ollama
   over urllib; ``--llm fake``: :mod:`robot_agent_fake`).
4. ``run_blocking`` is drained until the ``done`` event or the episode budget; the final status maps
   success -> done, refused -> refuse, anything else -> give_up.
"""

from __future__ import annotations

import contextlib
import copy
import importlib
import json
import os
import shutil
import tempfile
import types
from pathlib import Path

from ..env import MOTION, STOP_TEXT
from ..llm import BudgetExceeded, CountingLLM, FakeLLM

MAX_EVENTS = 2000
FAKE_GENERATOR = "homeloop_bench.planners.robot_agent_fake:GoalPlanner"


class RobotProxy:
    """What ``homeloop_robot.configs.backend`` hands the skill functions: the episode's robot behind
    ``env.call``."""

    def __init__(self, env):
        self.env = env
        self.world = env._world          # the robot side of the bridge (homeloop_robot backend), not the planner
        self.meaning = None              # the structured form of the question being asked (structured_asks)

    def call(self, skill: str, **args):
        from homeloop_robot.types import FailureCode, SkillResult
        if skill == "ask" and self.meaning is not None and "meaning" not in args:
            args = {**args, "meaning": dict(self.meaning)}
        r = self.env.call(skill, **args)
        if self.env.last_result is not None and self.env.calls and r.get("msg") != "episode budget exhausted":
            return self.env.last_result
        return SkillResult(ok=False, code=FailureCode.TIMEOUT if r.get("code") == "timeout" else FailureCode.SOFTWARE,
                           msg=r.get("msg", "episode budget exhausted"), data={}, duration_s=0.0)

    def observe(self) -> dict:
        return self.env.robot.observe()

    def health(self) -> dict:
        return self.env.robot.health()

    @property
    def believed(self) -> dict:
        return self.env.robot.believed

    @property
    def lang(self) -> str:
        """The episode's language (ra_skills.speech_lang: a sentence with no script of its own)."""
        return self.env.lang


class RAClient:
    """robot_agent's chat-client surface (``chat(prompt=, format=, temperature=, seed=, ...)``,
    ``chat_guide``) over our counted LLM."""

    def __init__(self, llm):
        self.llm = llm
        self.model = getattr(llm, "model", "")
        self.current_model = self.model
        self.current_tag = "untagged"
        self.history: dict = {}

    def chat(self, prompt: str = "", format=None, **kw) -> str:
        # ``num_predict`` (robot_agent's cap on the guarded understand call) is passed on only when given
        extra = {"num_predict": int(kw["num_predict"])} if kw.get("num_predict") else {}
        return self.llm.chat(prompt, format=format, temperature=float(kw.get("temperature") or 0.0),
                             seed=int(kw.get("seed") or 0), **extra)

    def chat_guide(self, prompt, guide=None, reuse=False, **kw) -> str:
        p = guide.replace("COMMAND_HERE", prompt) if isinstance(guide, str) and "COMMAND_HERE" in guide else prompt
        return self.chat(prompt=p, **kw)

    def reset_history(self, tag="untagged"):
        self.history = {}


class HomeloopRegistry:
    """``skill_registry.execute(skill, params, node=None, log_fn=None)``: the robot package's own skill
    function by name."""

    def __init__(self):
        self.ra = importlib.import_module("homeloop_robot.configs.ra_skills")

    def execute(self, skill, params, node=None, log_fn=None):
        fn = getattr(self.ra, skill, None)
        if fn is None:
            return {"isdone": False, "msg": f"NameError: skill {skill!r} is not defined", "code": "software"}
        return fn(node, **dict(params or {}))


class FakeNode:
    """The node surface run_control touches (cancel_all / clear_cancel)."""

    def __init__(self):
        self.agents: dict = {}

    def cancel_all(self) -> dict:
        return {"cancelled": []}

    def clear_cancel(self) -> None:
        return None


class FakeState:
    """The bits of ``robot_agent.state.AgentState`` the loops and run_control read."""

    def __init__(self, common_dir, node):
        from robot_agent.core.planning.base import WorldState
        self.robot_pkg = "homeloop_robot"
        self.common_dir = str(common_dir)
        self.world = WorldState()
        self.dm = types.SimpleNamespace(_ros_node=node)

    def save_world(self):
        return None


def apply_overlay(loop, overlay: dict) -> None:
    """Merge ``overlay`` ({"planner": {...}}) into this loop instance's manifest (only this loop's robot view changes,
    never the pack's file). A dict value is merged key by key, anything else replaces."""
    def merge(base: dict, extra: dict) -> dict:
        out = dict(base or {})
        for k, v in extra.items():
            out[k] = merge(out.get(k) or {}, v) if isinstance(v, dict) else copy.deepcopy(v)
        return out
    for section, data in (overlay or {}).items():
        if isinstance(data, dict):
            setattr(loop.robot.manifest, section, merge(getattr(loop.robot.manifest, section, None) or {}, data))


# The wait schedule of the execution-integrity variants. ASSUMED: the robot pack declares no recovery wait and no
# published spec gives one; a doubling backoff from 2 s is this variant's own assumption (a camera or detector that
# gave no image is usually back within a few seconds), not a property of the robot. The action name is the pack's
# own Wait action. Recorded in summary.json under planner_config.manifest_overlay.
WAIT_OVERLAY = {"planner": {"recovery": {"wait": {"action": "Wait", "schedule_s": [2, 4, 8]}}},
                "assumed": True,
                "note": "assumed: no spec sheet declares a wait schedule for the mock robot; doubling backoff from 2 s"}


# robot_agent declares what a question is in its OWN schema (``speech.LocalText.ask``: ``{intent, options, about}``,
# docs/env.md). This table maps it onto the simulated user's qtype list (homeloop_robot docs/user_model.md); a
# question whose intent is not here stays free text. The mapping lives here, in the bench adapter, not in robot_agent.
INTENT_TO_QTYPE = {"choose": ("which_object", {"about": "obj"})}


# The recovery of a BLOCKED PutIn into a container believed open (option ``reset_container``) is pack data in
# robot_agent (``planner.recovery.blocked_putin``; none declared = the option does nothing). The mock robot package
# declares none, so the variants carry it as an overlay. ASSUMED, and it OVERLAPS the simulator: [Close, Open] is the
# remedy the mock robot's state machine rewards (an Open that silently half-opens, a PutIn that fails "only partly
# open", and only a Close clears that state; homeloop_robot docs/calibration.md). Read the reset_container results as
# an ablation tied to that rule, not as a general finding.
BLOCKED_PUTIN_OVERLAY = {"planner": {"recovery": {"blocked_putin": ["Close", "Open"]}},
                         "assumed": True,
                         "note": "assumed: remedy for a PutIn blocked by a container believed open; overlaps the mock robot's partial-open rule"}
# How many times ``endstate_check`` runs the return to the last go goal again (``planner.recovery.return_tries``; none
# declared = the option does nothing). ASSUMED: three tries, the value used by lab round 3; no spec sheet gives one.
RETURN_OVERLAY = {"planner": {"recovery": {"return_tries": 3}}, "assumed": True,
                  "note": "assumed: three tries to re-achieve the last go goal (lab round 3 value)"}
# execution-integrity variants: all three declarations (a deep merge of the overlays above)
EXEC_OVERLAY = {"planner": {"recovery": {**WAIT_OVERLAY["planner"]["recovery"], **BLOCKED_PUTIN_OVERLAY["planner"]["recovery"],
                                         **RETURN_OVERLAY["planner"]["recovery"]}},
                "assumed": True, "note": "; ".join((WAIT_OVERLAY["note"], BLOCKED_PUTIN_OVERLAY["note"], RETURN_OVERLAY["note"]))}
# The numbers of ``dialog_unstick`` (manifest ``planner.unstick``; any missing = that part does nothing). ASSUMED: the
# values of lab round 4, fitted by eye on the 100-task dev slice and never validated on train; no source gives them.
# Read the dialog_unstick results with that in mind.
UNSTICK_OVERLAY = {"planner": {"unstick": {"fallback_words": 5, "fallback_chars": 24, "restate_frac": 0.6,
                                           "restate_word_len": 3, "restate_min_words": 4, "restate_min_bigrams": 6}},
                   "assumed": True,
                   "note": "assumed: dialog_unstick thresholds of lab round 4 (dev slice, not validated)"}
EXEC_UNSTICK_OVERLAY = {"planner": {**EXEC_OVERLAY["planner"], **UNSTICK_OVERLAY["planner"],
                                    "recovery": EXEC_OVERLAY["planner"]["recovery"]},
                        "assumed": True, "note": EXEC_OVERLAY["note"] + "; " + UNSTICK_OVERLAY["note"]}


def declared_meaning(question) -> dict | None:
    """The structured form a question DECLARES about itself (robot_agent ``speech.LocalText.ask``: ``intent`` plus slots,
    e.g. the inventory which-question), mapped onto the simulated user's qtype; else None: the question is then read
    from its words (``ra_dialog.derive``). A declaration that already carries a ``qtype`` is passed on as it is."""
    try:
        from robot_agent.core.planning.speech import declared_ask
    except ImportError:
        return None
    d = declared_ask(question)
    if not d:
        return None
    if not d.get("qtype"):
        hit = INTENT_TO_QTYPE.get(d.get("intent"))
        if hit is None:
            return None
        qtype, rename = hit
        d = {"qtype": qtype, **{rename.get(k, k): v for k, v in d.items() if k != "intent"}}
    return {**{k: v for k, v in d.items() if v}, "template": ["declared"]}


def structured_asks(loop, proxy) -> bool:
    """Give the AssistLoop's questions their structured form (homeloop_robot docs/user_model.md): wrap
    ``_ask_io`` on this loop instance (robot_agent is not changed). It receives the English question before
    robot_agent translates it (``_in_lang``); ``homeloop_robot.configs.ra_dialog.derive`` maps it onto SAGE's
    template and its slots, which the proxy attaches to the Ask skill's ``ask`` call. False = the loop has no
    ``_ask_io`` (ClosedLoop): its questions stay free text (rules, then the classifier)."""
    from homeloop_robot.configs.ra_dialog import derive
    orig = getattr(loop, "_ask_io", None)
    if orig is None:
        return False

    def _ask_io(question, node, log_fn, lang):
        proxy.meaning = declared_meaning(question) or derive(question)
        try:
            return orig(question, node, log_fn, lang)
        finally:
            proxy.meaning = None
    loop._ask_io = _ask_io
    return True


HEALTH_WAIT_S = 0.5     # robot_agent's own default wait for a sensor to recover (written here so a run does not
                        # depend on ROBOT_AGENT_HEALTH_WAIT_S); the wait is spent in simulated time, see SimTime


class SimTime:
    """The ``time`` module as robot_agent's loops see it in an episode: ``sleep(dt)`` is the robot waiting, so the
    episode's simulated clock advances by ``dt`` (``Robot.idle``) and no wall-clock time is spent; ``time()`` is the
    wall clock plus the time slept, so a deadline loop (``while time.time() < t_end``) ends after the simulated wait.
    The same for every robot_agent planner (consistency fix, not tuning: before, a robot that waited, polling its
    sensor health, never let simulated time pass because the adapter set ``health_wait_s=0``)."""

    def __init__(self, robot):
        import time as _t
        self._t, self._robot, self._slept = _t, robot, 0.0

    def time(self) -> float:
        return self._t.time() + self._slept

    def sleep(self, seconds: float) -> None:
        dt = max(0.0, float(seconds))
        self._slept += self._robot.idle(dt)

    def __getattr__(self, name):
        return getattr(self._t, name)


@contextlib.contextmanager
def _patched(pairs):
    """Set (module, attribute, value) triples; restore the old values afterwards."""
    old = []
    try:
        for mod, attr, val in pairs:
            old.append((mod, attr, getattr(mod, attr, None), hasattr(mod, attr)))
            setattr(mod, attr, val)
        yield
    finally:
        for mod, attr, val, had in reversed(old):
            if had:
                setattr(mod, attr, val)
            else:
                delattr(mod, attr)


def _count_embodiplan(env):
    """Route embodiplan's own LLM calls (the sage / grace generator talks to the server directly) through the
    episode's LLM chain: counted and budgeted, served from / written to the run's llm_cache, and sent with
    the bench client's options (one ``num_ctx`` for every request, so the server never reloads the model;
    seed 0 when embodiplan sets none, so its sampled calls repeat)."""
    try:
        import embodiplan
    except ImportError:
        return []
    backend = getattr(embodiplan, "LLMBackend", None)
    chat = getattr(backend, "chat", None)
    if chat is None:
        return []
    counter = env.llm()
    routed_ok = counter is not None and hasattr(counter, "chat_messages")

    def routed(self, messages, temperature=None):
        temp = float(self.temperature if temperature is None else temperature)
        if routed_ok and getattr(self, "provider", "ollama") == "ollama":
            seed = int(self.seed) if getattr(self, "seed", None) is not None else 0
            content = counter.chat_messages(list(messages), temp, seed)
            if not content:
                raise RuntimeError(f"Ollama returned empty content (model {counter.model})")
            approx = getattr(embodiplan.base, "_approx_tokens", lambda t: max(1, len(t) // 4))
            return content, approx(" ".join(str(m.get("content", "")) for m in messages)), approx(content)
        if counter is not None:
            if counter.max_calls is not None and counter.calls >= counter.max_calls:
                counter.refused = getattr(counter, "refused", 0) + 1
                raise BudgetExceeded(f"LLM budget of {counter.max_calls} calls exhausted")
            counter.calls += 1
        return chat(self, messages, temperature)
    return [(backend, "chat", routed)]


class TranslateCounter:
    """The translator's client (robot_agent's ``translate_model``, SAGE-v2 F5.3): its own model on the same server,
    its own cache (``llm_cache/<model>.jsonl``), counted on the EPISODE's call counter (the 30-call cap stays one cap)
    and separately (``env.llm_calls_translate``)."""

    def __init__(self, env, model: str, inner=None):
        self.env, self.model, self.inner = env, model, inner

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0) -> str:
        counter = self.env.llm()
        inner = self.inner if self.inner is not None else counter.inner
        out = counter._count(lambda: inner.chat(prompt, format=format, temperature=temperature, seed=seed))
        self.env.llm_calls_translate = getattr(self.env, "llm_calls_translate", 0) + 1
        return out


class RoleCounter:
    """The client of one robot_agent ROLE model (``understand_model`` / ``repair_model`` / ``dialog_model``; lab rounds 7 and
    8): its own model on the same server, counted on the episode's call counter (the one cap) and apart in
    ``env.llm_calls_<role>``. A failed call does not abort the episode (robot_agent's guard falls back to the baseline model); a
    budget that is used up refuses it. See UnderstandCounter for the routing rule."""
    role = ""

    def __init__(self, env, model: str, inner=None):
        self.env, self.model, self.inner = env, model, inner

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        counter = self.env.llm()
        inner = self.inner if self.inner is not None else counter.inner
        if counter.max_calls is not None and counter.calls >= counter.max_calls:
            counter.refused += 1
            raise BudgetExceeded(f"LLM budget of {counter.max_calls} calls exhausted")
        counter.calls += 1
        attr = "llm_calls_" + self.role
        setattr(self.env, attr, getattr(self.env, attr, 0) + 1)
        extra = {"num_predict": num_predict} if num_predict else {}
        return inner.chat(prompt, format=format, temperature=temperature, seed=seed, **extra)


class RepairCounter(RoleCounter):
    """Role ``repair``: the plan gate's repair prompts (lab round 8)."""
    role = "repair"


class DialogCounter(RoleCounter):
    """Role ``dialog``: what the robot says in the user's language (lab round 8)."""
    role = "dialog"


ROLE_COUNTERS = {"repair": RepairCounter, "dialog": DialogCounter}


class UnderstandCounter:
    """The client of robot_agent's ``understand_model`` (role ``understand``): its own model on the same server, its own cache
    (``llm_cache/<model>.jsonl``), counted on the EPISODE's call counter (the one cap) and apart in
    ``env.llm_calls_understand``. Routed by the ROLE robot_agent gives the client, not by the model name: with the understand
    model equal to the translator's, the understand calls would otherwise be counted as translation. A failed call does not
    abort the episode (robot_agent's runaway guard falls back to the planner's model); a budget that is used up refuses it."""

    def __init__(self, env, model: str, inner=None):
        self.env, self.model, self.inner = env, model, inner

    def chat(self, prompt: str, format=None, temperature: float = 0.0, seed: int = 0, num_predict=None) -> str:
        counter = self.env.llm()
        inner = self.inner if self.inner is not None else counter.inner
        if counter.max_calls is not None and counter.calls >= counter.max_calls:
            counter.refused += 1
            raise BudgetExceeded(f"LLM budget of {counter.max_calls} calls exhausted")
        counter.calls += 1
        self.env.llm_calls_understand = getattr(self.env, "llm_calls_understand", 0) + 1
        extra = {"num_predict": num_predict} if num_predict else {}
        return inner.chat(prompt, format=format, temperature=temperature, seed=seed, **extra)


def translator_inner(env, model: str, think=None, url=None):
    """The translate model's client on the episode's server and cache dir (None under --llm fake: the fake
    answers translation prompts itself). ``think``: Ollama's switch for a role client (None = not sent); ``url``: another
    server for this model (the dialog role: ``$HOMELOOP_DIALOG_URL``)."""
    from ..llm import CachedLLM, OllamaHTTP, shared_cache_path
    url = url or _url(env)
    if not url or not model:
        return None
    llm = OllamaHTTP(url, model)
    if think is not None:
        llm.think = bool(think)
    x = getattr(env, "_llm_inner", None)
    cache_dir = None
    for _ in range(4):
        if x is None:
            break
        if isinstance(x, CachedLLM):
            cache_dir = x.path.parent
            break
        x = getattr(x, "inner", None)
    if cache_dir is not None:
        llm = CachedLLM(llm, Path(cache_dir) / (model.replace("/", "_").replace(":", "_") + ".jsonl"),
                        shared=shared_cache_path(model))
    return llm


def manifest_planner() -> dict:
    """The homeloop robot package's manifest ``planner:`` section (read without robot_agent)."""
    import yaml

    import homeloop_robot
    path = Path(homeloop_robot.__file__).resolve().parent / "configs" / "manifest.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("planner") or {}


def seed_pool_path():
    """The homeloop robot package's seed pool (its manifest's ``planner.seed_memory``), None without one."""
    import yaml

    import homeloop_robot
    MANIFEST_PATH = Path(homeloop_robot.__file__).resolve().parent / "configs" / "manifest.yaml"   # no robot_agent
    rel = ((yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}).get("planner") or {}).get("seed_memory")
    return (MANIFEST_PATH.parent / rel).resolve() if rel else None


def seed_pool_info() -> dict:
    """{seed_pool: path relative to the homeloop_robot package, seed_pool_sha: sha256 of the file, seed_pool_n}."""
    import hashlib

    import homeloop_robot
    p = seed_pool_path()
    if p is None or not p.is_file():
        return {"seed_pool": None, "seed_pool_sha": None, "seed_pool_n": 0}
    data = p.read_bytes()
    root = Path(homeloop_robot.__file__).resolve().parent
    try:
        rel = str(p.relative_to(root.parent))
    except ValueError:
        rel = p.name
    return {"seed_pool": rel, "seed_pool_sha": hashlib.sha256(data).hexdigest(),
            "seed_pool_n": sum(1 for line in data.decode("utf-8").splitlines() if line.strip())}


def no_seed_pool(loop) -> None:
    """``robot_agent:sage_norag``: this loop's robot view reports no seed pool, so the SAGE planner it builds
    (``ClosedLoop._make_planner``: ``seed_memory=self.robot.seed_memory()``) retrieves from nothing. Only this
    loop instance's view is changed (robot_agent is not edited, the shared adapter is not touched)."""
    loop.robot.seed_memory = lambda: None


def seed_memory(env, path) -> int:
    """Write robot_agent's object memory (``mem.json``: {objects: {name: {place, ts, how}}}) with the object
    memory every planner observes (``EpisodeEnv.object_memory``: each object's usual place). A deployed
    robot_agent keeps this file across runs (object_memory), so it knows where things usually are; the
    benchmark's other planners get the same list in their observation. Names: the class names and colour +
    class name in English and Korean; a name shared by objects with different usual places is left out.
    Returns the number of names written."""
    import time

    from robot_agent.core.planning.assist_loop import words

    from homeloop_robot.catalog import COLORS, class_names
    places: dict = {}
    who: dict = {}                      # name -> ids of the objects it can mean
    for o in env.object_memory():
        for lg in ("en", "ko"):
            try:
                base = list(class_names(o.cls, lg))
            except KeyError:
                base = []
            base = list(dict.fromkeys(base + [o.name.get(lg) or o.cls]))
            color = (o.attrs or {}).get("color")
            cname = (COLORS.get(color) or {}).get(lg, color) if color else None
            names = base + ([f"{cname} {b}" for b in base] if cname else [])
            for n in names:
                places.setdefault(words(n), set()).add(o.usual_place)
                who.setdefault(words(n), set()).add(o.id)
    now = time.time()
    # H2: a record names the object it is about (``instance``) when the name means exactly one. robot_agent's
    # ``inventory_ask`` counts remembered INSTANCES (goal_fix.instances: the same instance id, or the pack's aliases),
    # not names; without the id "black mug" and "black coffee mug" of one mug were two candidates, the which-question
    # listed 4 names for 2 mugs, and the person's one-word answer picked among synonyms.
    objs = {n: {"place": next(iter(ps)), "ts": now, "how": "house memory",
                **({"instance": next(iter(who[n]))} if len(who[n]) == 1 else {})}
            for n, ps in sorted(places.items()) if n and len(ps) == 1}
    Path(path).write_text(json.dumps({"objects": objs, "answers": []}, ensure_ascii=False, indent=1))
    return len(objs)


def _url(env):
    x = getattr(env, "_llm_inner", None)
    for _ in range(4):
        if x is None:
            return None
        if getattr(x, "url", None):
            return x.url
        x = getattr(x, "inner", None)
    return None


def _software_crash(final: dict | None) -> bool:
    """robot_agent's run ended on an exception raised inside one of its own planner / LLM calls that was not the
    server being down (``AssistLoop._llm_failed``: status failed, code ``software``, evidence {call, error})."""
    f = final or {}
    return f.get("status") == "failed" and f.get("code") == "software" and isinstance(f.get("evidence"), dict) \
        and bool(f["evidence"].get("call"))


def stopped_say(final: dict | None, lang: str) -> str:
    """What a run stopped by the user says: the robot's own last words (in the user's language), else the stop
    phrase of that language (never an English placeholder: it counted as a wrong-language final say in KO)."""
    return str((final or {}).get("say") or "") or STOP_TEXT.get(lang, STOP_TEXT["en"])


def _status(final: dict | None) -> str:
    st = (final or {}).get("status") or ""
    if st == "success":
        return "done"
    if st == "refused":
        return "refuse"
    return "give_up"


def _roles_apart(loop_options: dict, overlay: dict) -> list:
    """The lab-round-8 roles (repair, dialog) a variant gives a model of its own (option or manifest overlay)."""
    ov = (overlay or {}).get("planner") or {}
    has = lambda *ks: any((loop_options or {}).get(k) or ov.get(k) for k in ks)      # noqa: E731
    return [r for r, ks in (("repair", ("repair_model",)), ("dialog", ("dialog_model", "dialog_model_lang"))) if has(*ks)]


def _understands_apart(loop_options: dict, overlay: dict) -> bool:
    ov = (overlay or {}).get("planner") or {}
    return any((loop_options or {}).get(k) or ov.get(k) for k in ("understand_model", "understand_model_lang"))


class _RobotAgentPlanner:
    privileged = False
    # a correction reaches robot_agent as an utterance injected into the run (its live dialog channel),
    # not as a cancelled skill (robot_agent stops a run on a cancelled step); a stop still cancels the call
    interrupt_via = "inject"
    needs_llm = True
    loop_kind = "assist"         # assist | closed
    ra_planner = "grace"
    description = ""
    structured = True            # SAGE's template questions carry their qtype (structured_asks)
    seed_pool = True             # the robot package's seed pool (manifest planner.seed_memory) is retrieved from
    people_tracking = True       # the ENV gives people's last-seen positions (False: the robot must ask)
    loop_options: dict = {}      # AssistLoop options of the variant (hazard_rules, gate_complete)
    _LAB_FLAGS = ("exec_integrity", "gate_strict", "endstate_check", "reset_container", "wait_on_robot",
                  "inventory_ask", "dialog_unstick",       # lab round 3 (and 4: dialog_unstick)
                  "reask_anchor", "no_shared_listener", "understand_views", "understand_goals_first",   # round 7
                  "understand_schema_strict", "understand_give_kind", "understand_verify_verdict",
                  "request_coverage")                       # round 8
    # (round 2's flags were never recorded: their summary.json stay as they were)
    # every option the loop reads from the variant: the episodes of a variant that sets one carry ``lab_events``
    _ALL_LAB_FLAGS = _LAB_FLAGS + ("person_goals", "go_steps", "kind_anchor", "name_canon", "reask_abstain",
                                   "understand_model", "repair_model", "dialog_model", "request_coverage")
    # Data the variant adds to the robot pack's manifest for this run (a dict merged key by key into the loop's
    # ``robot.manifest.planner``), declared apart from the pack: the pack stays as it is, the summary records the overlay.
    manifest_overlay: dict = {}

    @classmethod
    def understands_apart(cls) -> bool:
        """Does this variant read the request with a model other than the planner's (robot_agent's ``understand_model`` /
        ``understand_model_lang``, set as a loop option or in the manifest overlay)?"""
        return _understands_apart(cls.loop_options, cls.manifest_overlay)

    @classmethod
    def run_config(cls) -> dict:
        """What summary.json ``config.planner_config`` records: the variant, its seed pool (path, sha256, size),
        people tracking, the translate model and the loop options (SAGE-v2 round 3)."""
        info = seed_pool_info() if cls.seed_pool else {"seed_pool": None, "seed_pool_sha": None, "seed_pool_n": 0}
        mp = manifest_planner() if cls.loop_kind == "assist" else {}
        return {"variant": "rag" if cls.seed_pool else "norag", "loop": cls.loop_kind, "generator": cls.ra_planner,
                "live_memory": "per episode (deleted after it)", **info,
                "people_tracking": bool(cls.people_tracking),
                "translate_model": mp.get("translate_model"), "llm_budget": mp.get("llm_budget"),
                "translate_budget": mp.get("translate_budget"),
                "hazard_rules": cls.loop_options.get("hazard_rules", "core") if cls.loop_kind == "assist" else None,
                "gate_complete": int(cls.loop_options.get("gate_complete", 0)) if cls.loop_kind == "assist" else None,
                # recorded only where the flag is set, so the other variants' summary.json stay as they were
                **({"person_goals": 1} if cls.loop_kind == "assist" and cls.loop_options.get("person_goals") else {}),
                # lab-round options, likewise only where set
                **({k: 1 for k in cls._LAB_FLAGS if cls.loop_options.get(k)} if cls.loop_kind == "assist" else {}),
                # every loop option the variant sets, as given (also the round-2 flags), and the manifest data it adds
                **({"loop_options": {k: str(v) for k, v in sorted(cls.loop_options.items())}}
                   if cls.loop_kind == "assist" and cls.loop_options else {}),
                **({"manifest_overlay": copy.deepcopy(cls.manifest_overlay)} if cls.manifest_overlay else {}),
                # the model that reads the request, where the variant sets one (and its per-language map; "n_fallbacks" is
                # the run's count, in summary.json under llm_stats)
                **({"understand_model": cls.loop_options.get("understand_model")
                    or ((cls.manifest_overlay or {}).get("planner") or {}).get("understand_model"),
                    "understand_model_lang": cls.loop_options.get("understand_model_lang")
                    or ((cls.manifest_overlay or {}).get("planner") or {}).get("understand_model_lang")}
                   if cls.loop_kind == "assist" and cls.understands_apart() else {}),
                # lab round 8: the models of the repair and dialog roles, where the variant sets them
                **({"repair_model": cls.loop_options.get("repair_model")
                    or ((cls.manifest_overlay or {}).get("planner") or {}).get("repair_model")}
                   if cls.loop_kind == "assist" and "repair" in _roles_apart(cls.loop_options, cls.manifest_overlay) else {}),
                **({"dialog_model": cls.loop_options.get("dialog_model")
                    or ((cls.manifest_overlay or {}).get("planner") or {}).get("dialog_model"),
                    "dialog_model_lang": cls.loop_options.get("dialog_model_lang")
                    or ((cls.manifest_overlay or {}).get("planner") or {}).get("dialog_model_lang")}
                   if cls.loop_kind == "assist" and "dialog" in _roles_apart(cls.loop_options, cls.manifest_overlay) else {}),
                # the language layer (robot_agent core/planning/language.py): what a Korean user says reaches the
                # understand prompt as the original (none), its English (translate) or both
                "input_pivot": str(cls.loop_options.get("input_pivot", mp.get("input_pivot", "none"))
                                   ) if cls.loop_kind == "assist" else None}

    def __init__(self, llm=None):
        self.llm = llm
        self.events: list = []
        self.generator = None        # None: SAGE (grace), or the fake GoalPlanner under --llm fake
        self.on_loop = None          # inspection hook (loop, env) -> True to stop before the run (built_prompt)
        self.until = None            # event names: the run stops (the generator is closed) at the first of them
        self.reached = None          # the event it stopped at (understand-eval reads the `understand` event)
        self.loop_info = None        # understand_model_used / fallback of the last reading (a variant with an understand model)

    def run(self, env) -> None:
        import robot_agent.connect.llm as ra_llm
        import robot_agent.core.planning.assist_loop as AL
        import robot_agent.core.planning.loop as LP
        import robot_agent.skill_configs as sc
        import robot_agent.state as state_mod
        from robot_agent.core import run_control
        from robot_agent.interact.run_manager import reset_manager

        from homeloop_robot.configs import backend as hb
        from homeloop_robot.configs.tasks import env_for

        from . import robot_agent_fake as fk

        fake = isinstance(getattr(env, "_llm_inner", None), FakeLLM) or self.llm is None
        if fake:
            env._llm = CountingLLM(fk.FakeUnderstandLLM(), env.budgets.max_llm_calls)
        client = RAClient(env.llm())
        env.llm_calls_translate = 0
        tm = str(manifest_planner().get("translate_model") or "") if self.loop_kind == "assist" else ""
        tr_client = RAClient(TranslateCounter(env, tm, None if fake else translator_inner(env, tm))) if tm else None

        um_clients: dict = {}
        if self.loop_kind == "assist" and _understands_apart(self.loop_options, self.manifest_overlay):
            env.llm_calls_understand = 0
        if self.loop_kind == "assist":
            for role in _roles_apart(self.loop_options, self.manifest_overlay):
                setattr(env, "llm_calls_" + role, 0)

        def init_client(cfg=None, **k):
            """robot_agent's LLM client: by ROLE ``understand`` (its own model, counted apart), else by model: the
            translator's own (counted apart), else the planner's."""
            m = (cfg or {}).get("model")
            role, th = (cfg or {}).get("role"), (cfg or {}).get("think")
            if role == "understand" and m and m != client.model:
                if m not in um_clients:
                    um_clients[m] = RAClient(UnderstandCounter(env, m, None if fake else translator_inner(env, m, th)))
                return um_clients[m]
            if role in ROLE_COUNTERS and m and m != client.model:        # lab round 8: repair / dialog role models
                if (role, m) not in um_clients:
                    url = os.environ.get("HOMELOOP_DIALOG_URL") if role == "dialog" else None
                    um_clients[(role, m)] = RAClient(ROLE_COUNTERS[role](
                        env, m, None if fake else translator_inner(env, m, th, url)))
                return um_clients[(role, m)]
            return tr_client if tr_client is not None and m == tm and m != client.model else client
        tmp = Path(tempfile.mkdtemp(prefix="homeloop_ra_"))
        node = FakeNode()
        state = FakeState(tmp, node)
        cur = (lambda: state)
        pairs = [(AL, "current", cur), (LP, "current", cur), (state_mod, "current", cur),
                 (AL, "host_id", lambda: "homeloop"), (LP, "host_id", lambda: "homeloop"),
                 (sc, "ENV", env_for(env.world0, people_tracking=self.people_tracking)),
                 (ra_llm, "init_llm_client", init_client)]
        if not fake:
            pairs += _count_embodiplan(env)
        simtime = SimTime(env.robot)
        pairs += [(m, "time", simtime) for m in (AL, LP) if hasattr(m, "time")]
        old_backend = getattr(hb, "_backend", None)
        fk.CURRENT["env"] = env
        try:
            with _patched(pairs):
                proxy = RobotProxy(env)
                hb.set_backend(proxy)
                manager = reset_manager()
                run_control._CANCEL.clear()
                dec = manager.start(goal=env.task_text, user_id="owner", role="owner")
                run = dec.run if getattr(dec, "started", False) else None
                run_control.begin_run()
                agent = types.SimpleNamespace(skill_registry=HomeloopRegistry(),
                                              device_manager=types.SimpleNamespace(_ros_node=node),
                                              _llm_cfg={"name": "llama", "url": _url(env),
                                                        "model": getattr(client, "model", ""), "num_ctx": 8192})
                if self.loop_kind == "assist":
                    seed_memory(env, tmp / "mem.json")
                loop = self._make_loop(agent, tmp, fake)
                loop._llm_client = client
                if not self.seed_pool:
                    no_seed_pool(loop)
                if self.structured and os.environ.get("HOMELOOP_RA_STRUCTURED", "1") != "0":
                    structured_asks(loop, proxy)
                if self.on_loop is not None and self.on_loop(loop, env):
                    return                       # an inspection (built_prompt): the run is not played
                final = None
                n = 0
                injected = 0
                events = loop.run_blocking(env.task_text, lang=env.lang, **self.run_kwargs(env))
                for ev in events:
                    n += 1
                    e = {k: v for k, v in ev.items() if k not in ("world", "say_audio")}
                    if e.get("event") in ("done", "error"):
                        final = e
                    if self.until and e.get("event") in self.until and not e.get("reask"):
                        # (an understand_check that only reports a re-ask of the understand step is not the stop)
                        self.reached = e         # a probe (understand-eval) wants the loop up to this event only
                        events.close()
                        break
                    # a user interruption (correction / stop) is said to the run, as a person would say it
                    while run is not None and injected < len(env._events):
                        uev = env._events[injected]
                        injected += 1
                        try:
                            manager.inject(run.run_id, str(uev.get("text") or ""), user_id="owner", role="owner")
                        except Exception:       # noqa: BLE001 - an injection failure leaves the run as it is
                            pass
                    if env.over or n > MAX_EVENTS or env.stop_k is not None and self._stop_after(env):
                        break
                self.final = final
                if getattr(env, "llm_calls_understand", None) is not None:
                    env.understand_fallbacks = list(getattr(loop, "um_fallbacks", None) or [])
                    self.loop_info = {"understand_model_used": (getattr(loop, "um_last", None) or {}).get("model"),
                                      "fallback": (getattr(loop, "um_last", None) or {}).get("fallback")}
                if any(self.loop_options.get(k) for k in self._ALL_LAB_FLAGS):
                    # what the opt-in options did in this run (robot_agent AssistLoop.lab_log), into episodes.jsonl
                    env.lab_events = [dict(e) for e in (getattr(loop, "lab_log", None) or [])]
                if run is not None:
                    try:
                        manager.finish(run.run_id, ok=_status(final) == "done", outcome=str((final or {}).get("status")))
                    except Exception:           # noqa: BLE001
                        pass
        finally:
            fk.CURRENT["env"] = None
            hb.set_backend(old_backend)
            if not os.environ.get("HOMELOOP_KEEP_RA_LOGS"):
                shutil.rmtree(tmp, ignore_errors=True)     # run logs, live.jsonl, mem.json of this episode
        if env.status is None:
            if env.stop_k is not None:
                env.finish("done", stopped_say(final, env.lang))
            elif _software_crash(final) and not (env.llm_budget_hit and "budget" in str(final.get("msg")).lower()):
                # robot_agent caught an exception of its own code in a planner / LLM call and ended the run "failed"
                # (code software): a crash, status error, not a plain give-up (gate pilot round 1, hl-dev-000028 KO:
                # "the planner failed: 'int' object has no attribute 'strip'" was scored give_up, n_error 0)
                ev = (final or {}).get("evidence") or {}
                env.set_crash("RobotAgentSoftwareError", f"{ev.get('call') or final.get('device') or '?'}: "
                              f"{ev.get('error') or final.get('msg') or ''}", str(final.get("say") or ""))
            else:
                env.finish(_status(final), str((final or {}).get("say") or ""))

    def run_kwargs(self, env) -> dict:
        """Extra keyword arguments of ``run_blocking`` for this variant (none for the planners that understand the request)."""
        return {}

    @staticmethod
    def _stop_after(env) -> bool:
        """After a stop event: end the run once a further motion call was attempted (the loop did not stop)."""
        return any(c["skill"] in MOTION for c in env.calls[env.stop_k + 1:])

    def _make_loop(self, agent, tmp: Path, fake: bool):
        common = dict(mute_skill_tts=False, speak_backend=False, vlm_enabled=False,
                      log_dir=str(tmp / "runs"), live_path=str(tmp / "live.jsonl"))
        if self.loop_kind == "assist":
            from robot_agent.core.planning.assist_loop import AssistLoop
            gen = self.generator or (FAKE_GENERATOR if fake else self.ra_planner)
            loop = AssistLoop(agent, emit=None, generator=gen,
                              health_wait_s=HEALTH_WAIT_S, memory_path=str(tmp / "mem.json"), **dict(self.loop_options), **common)
            apply_overlay(loop, self.manifest_overlay)
            if self.manifest_overlay and hasattr(loop, "_um_cfg"):      # the keys robot_agent reads once, at construction
                loop.cfg.update(loop._um_cfg(dict(self.loop_options)))
                if hasattr(loop, "_rm_cfg"):                            # lab round 8 (role models, request_coverage)
                    loop.cfg.update(loop._rm_cfg(dict(self.loop_options)))
            return loop
        from robot_agent.core.planning.loop import ClosedLoop
        planner = self.ra_planner
        if fake and planner == "grace":
            planner = FAKE_GENERATOR
        return ClosedLoop(agent, emit=None, planner=planner, **common)


class SagePlanner(_RobotAgentPlanner):
    """SAGE as designed: its retrieval over the robot's seed pool (top-3 similar solved plans in every prompt)."""
    name = "robot_agent:sage"
    loop_kind = "assist"
    ra_planner = "grace"


class SageNoRagPlanner(SagePlanner):
    """The same SAGE with an empty seed pool (zero-shot): the only difference from ``robot_agent:sage``."""
    name = "robot_agent:sage_norag"
    seed_pool = False


class SageAskPlanner(SagePlanner):
    """SAGE with people tracking off: the ENV has no positions for people, so SAGE asks "Where are you?" and maps
    the answer onto the house (the same seed pool as robot_agent:sage)."""
    name = "robot_agent:sage_ask"
    people_tracking = False


class SageNoHazardPlanner(SagePlanner):
    """robot_agent:sage with the core safety rules off (``hazard_rules=off``: the model's own 'unsafe' only)."""
    name = "robot_agent:sage_nohazard"
    loop_options = {"hazard_rules": "off"}


class SagePivotNonePlanner(SagePlanner):
    """robot_agent:sage with ``input_pivot=none``: the Korean words go to the understand prompt as they are
    (the language layer's IN side off; its OUT side, the one speak(), stays)."""
    name = "robot_agent:sage_pivot_none"
    loop_options = {"input_pivot": "none"}


class SagePivotTranslatePlanner(SagePlanner):
    """robot_agent:sage with ``input_pivot=translate``: the understand prompt gets the English translation of what
    the user said (the original only as the source of each goal's ``said``)."""
    name = "robot_agent:sage_pivot_translate"
    loop_options = {"input_pivot": "translate"}


class SageCompletePlanner(SagePlanner):
    """robot_agent:sage with the gate's 'complete' operator on (it writes a missing goal's segment; reported
    apart, ``completed_by_gate``)."""
    name = "robot_agent:sage_complete"
    loop_options = {"gate_complete": "1"}


class SageLabPlanner(SagePlanner):
    """robot_agent:sage with the solution-lab prototype ``person_goals`` on (SAGE-v2 branch sage-v2/homeloop):
    a request that mixes go / say goals with moves keeps the go / say steps as the loop's own fixed sub-goals,
    a hand-over goes to the person its goal names, a repeated goal is dropped, an Open of what cannot be opened is
    removed. Default off for every other variant; this one differs from ``robot_agent:sage`` in that flag only."""
    name = "robot_agent:sage_lab"
    loop_options = {"person_goals": "1"}


class SageGround2Planner(SagePlanner):
    """robot_agent:sage with grounding chain v2 on (go_steps, kind_anchor, name_canon): deterministic, 0 extra calls."""
    name = "robot_agent:sage_ground2"
    loop_options = {"go_steps": "1", "kind_anchor": "1", "name_canon": "1"}


class SageGoStepsPlanner(SagePlanner):
    """Ablation of sage_ground2: go_steps only."""
    name = "robot_agent:sage_g2_go"
    loop_options = {"go_steps": "1"}


class SageKindAnchorPlanner(SagePlanner):
    """Ablation of sage_ground2: kind_anchor only."""
    name = "robot_agent:sage_g2_kind"
    loop_options = {"kind_anchor": "1"}


class SageNameCanonPlanner(SagePlanner):
    """Ablation of sage_ground2: name_canon only."""
    name = "robot_agent:sage_g2_name"
    loop_options = {"name_canon": "1"}


class SageReaskPlanner(SagePlanner):
    """robot_agent:sage with reask_abstain on: one directed re-understand of a goal-less where-is-it reading."""
    name = "robot_agent:sage_reask"
    loop_options = {"reask_abstain": "1"}


class SageExecPlanner(SagePlanner):
    """robot_agent:sage with execution integrity on (SAGE-v2 lab round 3, robot_agent option family ``exec_integrity``:
    gate_strict, endstate_check, reset_container, wait_on_robot; default off). A certifying per-goal repair, a checked
    return to the last go goal, a reset of a BLOCKED container, a wait on the robot where the pack declares one.
    No extra LLM call. A prototype under test, not a result."""
    name = "robot_agent:sage_exec"
    loop_options = {"exec_integrity": "1"}
    manifest_overlay = EXEC_OVERLAY             # wait_on_robot / reset_container act only where the pack declares them


class SageInventoryPlanner(SagePlanner):
    """robot_agent:sage with ``inventory_ask`` on (lab round 3): an object the person names that matches more than one
    instance in the robot's own object memory is narrowed by the person's words, else asked once (closed choice)."""
    name = "robot_agent:sage_inv"
    loop_options = {"inventory_ask": "1"}


class SageUnstickPlanner(SagePlanner):
    """robot_agent:sage with ``dialog_unstick`` on (lab round 4): a restatement that reproduces a refused reading is read
    back once more instead of ending the run; a not-sure answer to a where-is question makes the robot search (one more
    understand call, once); a question with its own apology is not prefixed with the silence apology. A prototype."""
    name = "robot_agent:sage_unstick"
    loop_options = {"dialog_unstick": "1"}
    manifest_overlay = UNSTICK_OVERLAY          # its numbers are pack data: none declared, the numeric parts do nothing


class SageEiGatePlanner(SagePlanner):
    """Ablation of sage_exec: gate_strict only."""
    name = "robot_agent:sage_ei_gate"
    loop_options = {"gate_strict": "1"}


class SageEiEndPlanner(SagePlanner):
    """Ablation of sage_exec: endstate_check only."""
    name = "robot_agent:sage_ei_end"
    loop_options = {"endstate_check": "1"}
    manifest_overlay = RETURN_OVERLAY


class SageEiResetPlanner(SagePlanner):
    """Ablation of sage_exec: reset_container only."""
    name = "robot_agent:sage_ei_reset"
    loop_options = {"reset_container": "1"}
    manifest_overlay = BLOCKED_PUTIN_OVERLAY


class SageEiWaitPlanner(SagePlanner):
    """Ablation of sage_exec: wait_on_robot only (acts only where the robot package declares planner.recovery.wait)."""
    name = "robot_agent:sage_ei_wait"
    loop_options = {"wait_on_robot": "1"}
    manifest_overlay = WAIT_OVERLAY


class SageR3Planner(SagePlanner):
    """The lab-round-3 combination: grounding chain v2 (go_steps, kind_anchor, name_canon) + execution integrity +
    inventory_ask. Every option is default off in robot_agent; this variant differs from robot_agent:sage in them only."""
    name = "robot_agent:sage_r3"
    loop_options = {"go_steps": "1", "kind_anchor": "1", "name_canon": "1", "exec_integrity": "1", "inventory_ask": "1"}
    manifest_overlay = EXEC_OVERLAY


class SageR3uPlanner(SagePlanner):
    """sage_r3 + dialog_unstick (lab round 4 combination)."""
    name = "robot_agent:sage_r3u"
    loop_options = {**SageR3Planner.loop_options, "dialog_unstick": "1"}
    manifest_overlay = EXEC_UNSTICK_OVERLAY


class SageU1Planner(SagePlanner):
    """Lab round 7, step 1: sage_ground2 + ``reask_anchor`` (a goal-less where-is-it reading is understood once more and the
    new reading is taken only when every place in it is in the person's words). One extra understand call on about 8 % of
    readings. Needs a robot_agent with the round-7 options (an older one drops unknown options silently). A prototype."""
    name = "robot_agent:sage_u1"
    loop_options = {**SageGround2Planner.loop_options, "reask_anchor": "1"}


class SageU2Planner(SagePlanner):
    """sage_u1 + ``no_shared_listener`` (the shared_listener rule is off: a person who is the listener of a message and the
    recipient of a delivery stays the recipient). The GPU re-read of the cases this changes is still open."""
    name = "robot_agent:sage_u2"
    loop_options = {**SageU1Planner.loop_options, "no_shared_listener": "1"}


class SageU3Planner(SagePlanner):
    """sage_u2 + ``understand_views``: a non-English request is read from the original and from the translator's English
    (the translator is the planner's model unless ``translate_model`` says otherwise, as for ``sage_pivot_translate``); equal readings act, different ones ask one
    'which one?' question. About +2 calls per non-English episode."""
    name = "robot_agent:sage_u3"
    loop_options = {**SageU2Planner.loop_options, "understand_views": "1"}


class SageUPlanner(SagePlanner):
    """sage_u3 + ``understand_goals_first`` (the understand schema lists the goals before the verdict)."""
    name = "robot_agent:sage_u"
    loop_options = {**SageU3Planner.loop_options, "understand_goals_first": "1"}


# The runaway guard of a model other than the planner's (robot_agent planner.understand_max_tokens / _max_goals; none declared
# = no guard). ASSUMED: 512 tokens is robot_agent's suggested cap (a valid answer to the bench's tasks is a few hundred
# characters; the runaways seen in lab round 7 were 22000 characters), and 8 goals is above any request in the task files
# (at most 3 gold atoms) and above the most the 8B model reads (6). Not tuned on any outcome. Recorded in summary.json.
UM_MODEL = "qwen3-vl:30b-a3b-instruct"
UM_GUARD = {"planner": {"understand_max_tokens": 512, "understand_max_goals": 8},
            "assumed": True,
            "note": "assumed: understand guard of 512 tokens and 8 goals (a cap far above a valid reading; lab round 7)"}


class SageUmPlanner(SagePlanner):
    """Lab round 7: sage_ground2 + ``understand_model`` (the 30B model reads the request; the 8B planner plans and gates) with the
    runaway guard (a non-JSON, over-long or repeating answer falls back to the planner once, event understand_fallback).
    Understand calls are counted on the episode cap and apart (``llm_calls_understand``). A prototype."""
    name = "robot_agent:sage_um"
    loop_options = {**SageGround2Planner.loop_options, "understand_model": UM_MODEL}
    manifest_overlay = UM_GUARD


class SageUmKoPlanner(SagePlanner):
    """sage_um with the model chosen by language, as manifest data: Korean requests are read by the 30B model, English ones by the
    planner (``understand_model_lang`` = {ko: 30B}); the guard as for sage_um."""
    name = "robot_agent:sage_um_ko"
    loop_options = dict(SageGround2Planner.loop_options)
    manifest_overlay = {"planner": {**UM_GUARD["planner"], "understand_model_lang": {"ko": UM_MODEL}},
                        "assumed": True, "note": UM_GUARD["note"]}


class SageUmStrictPlanner(SagePlanner):
    """sage_um + ``understand_schema_strict`` (every goal carries ``said`` and ``content``)."""
    name = "robot_agent:sage_um_strict"
    loop_options = {**SageUmPlanner.loop_options, "understand_schema_strict": "1"}
    manifest_overlay = UM_GUARD


class SageUmGivePlanner(SagePlanner):
    """sage_um + ``understand_give_kind`` (a ``give`` goal kind for a hand-over, and the say-to-the-speaker echo filter)."""
    name = "robot_agent:sage_um_give"
    loop_options = {**SageUmPlanner.loop_options, "understand_give_kind": "1"}
    manifest_overlay = UM_GUARD


class SageUmVerdictPlanner(SagePlanner):
    """sage_um + ``understand_verify_verdict`` (an infeasible verdict must name a missing action; location_unknown is clear)."""
    name = "robot_agent:sage_um_verdict"
    loop_options = {**SageUmPlanner.loop_options, "understand_verify_verdict": "1"}
    manifest_overlay = UM_GUARD


class SageM1Planner(SageUmPlanner):
    """Workflow name for the understand-model option on top of sage_ground2 (the same configuration as sage_um)."""
    name = "robot_agent:sage_m1"


class SageM2Planner(SagePlanner):
    """sage_m1 + the three schema / prompt flags (strict, give kind, verify verdict)."""
    name = "robot_agent:sage_m2"
    loop_options = {**SageUmPlanner.loop_options, "understand_schema_strict": "1", "understand_give_kind": "1",
                    "understand_verify_verdict": "1"}
    manifest_overlay = UM_GUARD


# Lab round 8 (user decision 2026-11-07): Qwen3.5 9B reads the request and repairs the plan gate's findings, HyperCLOVAX-SEED-
# Think-14B writes the Korean. ASSUMED guard values, not tuned on any outcome: 512 tokens / 8 goals as for the 30B reader; a
# repair answer (a block's steps or one plan) 1024 tokens; one spoken sentence 128 tokens. ``think`` is off for the 9B (a
# thinking model answers EMPTY when its reasoning uses the cap: smoke test 2026-11-07). The Korean model's name is the tag the
# server registers it under, and its server comes from $HOMELOOP_DIALOG_URL (Ollama 0.35 and 0.40 cannot load it; without a server
# every Korean sentence falls back to the translator after one failed call).
M9_MODEL = "qwen3.5:9b"
KO_DIALOG_MODEL = "hyperclovax-seed-think-14b"
M9_OVERLAY = {"planner": {"understand_max_tokens": 512, "understand_max_goals": 8, "understand_think": 0,
                          "repair_max_tokens": 1024, "repair_think": 0},
              "assumed": True,
              "note": "assumed: guards of 512 tokens / 8 goals (understand) and 1024 tokens (repair), think off for the 9B (lab round 8)"}
MK_OVERLAY = {"planner": {**M9_OVERLAY["planner"], "dialog_model_lang": {"ko": KO_DIALOG_MODEL}, "dialog_max_tokens": 128},
              "assumed": True, "note": M9_OVERLAY["note"] + "; dialog guard of 128 tokens (one sentence)"}


class SageM9Planner(SagePlanner):
    """Lab round 8: sage_ground2 + Qwen3.5 9B for ``understand_model`` and ``repair_model`` (the plan gate's repair prompts); the
    translator is unchanged. Guards fall back to the baseline model once (events ``understand_fallback``, lab_events
    ``repair_model``). Calls of both roles are counted on the episode cap and apart (``llm_calls_understand`` /
    ``llm_calls_repair``). A prototype."""
    name = "robot_agent:sage_m9"
    loop_options = {**SageGround2Planner.loop_options, "understand_model": M9_MODEL, "repair_model": M9_MODEL}
    manifest_overlay = M9_OVERLAY


class SageMkPlanner(SagePlanner):
    """sage_m9 + a Korean dialog model (``dialog_model_lang`` {ko: HyperCLOVAX-SEED-Think-14B}): the Korean questions, read-backs
    and translations are written by it, English by the translator as before. Needs a server for it
    (``$HOMELOOP_DIALOG_URL``); without one the guard falls back to the translator on every sentence."""
    name = "robot_agent:sage_mk"
    loop_options = dict(SageM9Planner.loop_options)
    manifest_overlay = MK_OVERLAY


# Round 8b: the 9B reader was worse than the 8B in Korean (dev KO exact 202 vs 251; the runs used input_pivot none). Three ways to
# measure it fairly: the Korean request goes to the 9B as its English translation (input_pivot translate) or as both texts
# (both), or the Korean request is read by the planner's own 8B model (``understand_model_lang`` {ko: the 8B}; a language whose
# model is the planner's keeps the planner as reader) while English stays with the 9B. The 8B tag is the one of the lab runs.
PLANNER_8B = "qwen3-vl:8b-instruct"
M9_KO8_LANG = {"ko": PLANNER_8B}


class SageM9TranslatePlanner(SagePlanner):
    """sage_m9 with ``input_pivot=translate``: the 9B reads the English translation of what the user said."""
    name = "robot_agent:sage_m9t"
    loop_options = {**SageM9Planner.loop_options, "input_pivot": "translate"}
    manifest_overlay = M9_OVERLAY


class SageM9BothPlanner(SagePlanner):
    """sage_m9 with ``input_pivot=both``: the 9B reads the user's words and their English translation."""
    name = "robot_agent:sage_m9b"
    loop_options = {**SageM9Planner.loop_options, "input_pivot": "both"}
    manifest_overlay = M9_OVERLAY


class SageM9Ko8Planner(SagePlanner):
    """sage_m9 with the reader chosen by language: English requests by the 9B, Korean ones by the planner's 8B
    (``understand_model_lang`` {ko: 8B}); the 9B still repairs plans in both languages."""
    name = "robot_agent:sage_m9k8"
    loop_options = dict(SageM9Planner.loop_options)
    manifest_overlay = {"planner": {**M9_OVERLAY["planner"], "understand_model_lang": M9_KO8_LANG},
                        "assumed": True, "note": M9_OVERLAY["note"] + "; Korean requests read by the planner's 8B"}


# Steps 4 and 5 of the earlier design as flag bundles (all default off in robot_agent; ``reask_anchor`` needs the round-7 build).
S4_FLAGS = {"dialog_unstick": "1", "inventory_ask": "1", "reask_anchor": "1", "request_coverage": "1"}


class SageS4Planner(SagePlanner):
    """Step 4: sage_ground2 + dialog_unstick + inventory_ask + reask_anchor + request_coverage (one extra LLM call before
    done; a named part of the request with no goal or no executed step is asked about instead of claimed)."""
    name = "robot_agent:sage_s4"
    loop_options = {**SageGround2Planner.loop_options, **S4_FLAGS}
    manifest_overlay = UNSTICK_OVERLAY


class SageS5Planner(SagePlanner):
    """Step 5: the sage_r3u bundle (grounding chain v2, exec_integrity = endstate_check + wait_on_robot + reset_container +
    gate_strict, inventory_ask, dialog_unstick) with the same pack declarations."""
    name = "robot_agent:sage_s5"
    loop_options = dict(SageR3uPlanner.loop_options)
    manifest_overlay = EXEC_UNSTICK_OVERLAY


class SageS45Planner(SagePlanner):
    """Steps 4 and 5 together."""
    name = "robot_agent:sage_s45"
    loop_options = {**SageS5Planner.loop_options, **S4_FLAGS}
    manifest_overlay = EXEC_UNSTICK_OVERLAY


class SageS45mPlanner(SagePlanner):
    """sage_s45 flags + Qwen3.5 9B for ``understand_model`` and ``repair_model`` (the sage_m9 models and guards, lab round 8).
    The Korean dialog model is not part of it (no server; see sage_mk)."""
    name = "robot_agent:sage_s45m"
    loop_options = {**SageS45Planner.loop_options, "understand_model": M9_MODEL, "repair_model": M9_MODEL}
    manifest_overlay = {"planner": {**EXEC_UNSTICK_OVERLAY["planner"], **M9_OVERLAY["planner"]},
                        "assumed": True, "note": EXEC_UNSTICK_OVERLAY["note"] + "; " + M9_OVERLAY["note"]}


class SageS45m8Planner(SagePlanner):
    """sage_s45m with the Korean request read by the planner's 8B (``understand_model_lang`` {ko: 8B}); English by the 9B."""
    name = "robot_agent:sage_s45m8"
    loop_options = dict(SageS45mPlanner.loop_options)
    manifest_overlay = {"planner": {**SageS45mPlanner.manifest_overlay["planner"], "understand_model_lang": M9_KO8_LANG},
                        "assumed": True, "note": SageS45mPlanner.manifest_overlay["note"] + "; Korean requests read by the planner's 8B"}


class SageS45mkPlanner(SagePlanner):
    """sage_s45m + a Korean dialog model (``dialog_model_lang`` {ko: HyperCLOVAX-SEED-Think-14B}, server at
    ``$HOMELOOP_DIALOG_URL``; as sage_mk)."""
    name = "robot_agent:sage_s45mk"
    loop_options = dict(SageS45mPlanner.loop_options, **{"understand_model": M9_MODEL, "repair_model": M9_MODEL})
    manifest_overlay = {"planner": {**SageS45mPlanner.manifest_overlay["planner"], "dialog_model_lang": {"ko": KO_DIALOG_MODEL},
                                    "dialog_max_tokens": 128},
                        "assumed": True, "note": SageS45mPlanner.manifest_overlay["note"] + "; dialog guard of 128 tokens (one sentence)"}


class SageGoldPlanner(SagePlanner):
    """DIAGNOSTIC, PRIVILEGED: ``robot_agent:sage`` that does not understand the request. The task's gold goals, converted
    to robot_agent goals (``homeloop_bench.gold_goals``: no source location, the robot searches), are handed to
    robot_agent, whose option ``accept_goals`` is on and which then skips its understand step. It measures what is left
    after understanding: plan, gate, search, recovery and the dialogue about the unknowns that remain. Never a headline
    planner; mark it privileged in every table. A task with no gold goal to give (a request to refuse) is understood as
    usual. Clarify tasks are not asked about: the goals are known."""
    name = "robot_agent:sage_gold"
    privileged = True
    loop_options = {"accept_goals": "1"}

    @classmethod
    def run_config(cls) -> dict:
        return {**super().run_config(), "privileged": True, "accept_goals": 1,
                "goals_from": "task gold goals (no source location)"}

    def run_kwargs(self, env) -> dict:
        from ..gold_goals import understand_goals
        goals = understand_goals(env, with_source=False) if env.goal.get("all") else []
        return {"goals": goals} if goals else {}


class GracePlanner(_RobotAgentPlanner):
    name = "robot_agent:grace"
    loop_kind = "closed"
    ra_planner = "grace"


class LlmDirectPlanner(_RobotAgentPlanner):
    name = "robot_agent:llm_direct"
    loop_kind = "closed"
    ra_planner = "llm_direct"


class _Captured(Exception):
    pass


def built_prompt(task, planner_name: str = "robot_agent:sage", lang: str = "en", profile: str = "real",
                 seed: int = 0) -> dict:
    """The first prompt SAGE's generator sends for ``task`` (its decompose call), built by the same episode setup
    a run uses (robot package, ENV, per-episode memory, the variant's seed pool), with ``--llm fake``: the episode
    starts as ``run`` starts it, the loop's own SAGE planner is built (generator ``grace``, not the fake
    GoalPlanner) and its ``generate_plan`` is called once with the task text; the LLM call is captured and not
    sent. Returns {planner, task_id, lang, query, seed_pool_n, retrieved: [{task, score, source}], prompt}.
    Shows that ``robot_agent:sage`` retrieves from the seed pool and ``robot_agent:sage_norag`` does not."""
    import embodiplan

    from ..env import EpisodeEnv
    from . import make_planner, planner_class
    cls = planner_class(planner_name)
    if getattr(cls, "loop_kind", None) != "assist":
        raise ValueError(f"{planner_name}: built_prompt is for the SAGE planners (robot_agent:sage, _norag)")
    env = EpisodeEnv(task, profile, seed, lang, llm=FakeLLM(), privileged=False, interrupt_via="inject")
    env.planner_name = planner_name
    planner = make_planner(planner_name, llm=env.llm())
    planner.generator = planner.ra_planner
    out: dict = {"planner": planner_name, "task_id": env.task_id, "lang": lang, "query": env.task_text}

    def inspect(loop, env_):
        gen = loop._make_planner()
        sage = gen
        for _ in range(4):                     # registry proxy -> GraceBackend -> SAGEPlanner
            if hasattr(sage, "retrieve_examples") and hasattr(sage, "memory"):
                break
            sage = getattr(sage, "_p", None) or getattr(sage, "inner", None) or getattr(sage, "_inner", None)
        mem = getattr(sage, "memory", None)
        out["seed_pool_n"] = (mem.size.get("seed", 0) if mem is not None else 0)
        ex, _block = sage.retrieve_examples(env_.task_text) if sage is not None else ([], "")
        out["retrieved"] = [{"task": e.task, "score": round(float(e.score), 4), "source": e.source} for e in ex]

        prompts = out.setdefault("prompts", [])

        def capture(self, messages, temperature=None):
            # every call fails (nothing is sent): SAGE falls back (decompose -> one sub-goal -> expand), so the
            # decompose prompt and the expand prompt of the first sub-goal are both seen
            prompts.append("\n\n".join(str(m.get("content", "")) for m in messages))
            raise _Captured()
        with _patched([(embodiplan.LLMBackend, "chat", capture)]):
            try:
                gen.generate_plan(env_.task_text, "Robot state: " + loop.robot.adapter.observe().text, [])
            except _Captured:
                pass
            except Exception:                  # noqa: BLE001 - SAGE falls back after a failed call; the
                pass                           # first captured prompt is what is reported
        return True
    planner.on_loop = inspect
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):        # SAGE prints its fallbacks
        planner.run(env)
    ps = out.pop("prompts", [])
    out["prompt"] = ps[0] if ps else None
    out["n_prompts"] = len(ps)
    out["prompts_with_examples"] = sum(1 for p in ps if "RETRIEVED EXAMPLE" in p)
    return out
