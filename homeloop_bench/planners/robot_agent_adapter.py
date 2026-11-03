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
import importlib
import json
import os
import shutil
import tempfile
import types
from pathlib import Path

from ..env import MOTION
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
        return self.llm.chat(prompt, format=format, temperature=float(kw.get("temperature") or 0.0),
                             seed=int(kw.get("seed") or 0))

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
        proxy.meaning = derive(question)
        try:
            return orig(question, node, log_fn, lang)
        finally:
            proxy.meaning = None
    loop._ask_io = _ask_io
    return True


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
                raise BudgetExceeded(f"LLM budget of {counter.max_calls} calls exhausted")
            counter.calls += 1
        return chat(self, messages, temperature)
    return [(backend, "chat", routed)]


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
    now = time.time()
    objs = {n: {"place": next(iter(ps)), "ts": now, "how": "house memory"}
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


def _status(final: dict | None) -> str:
    st = (final or {}).get("status") or ""
    if st == "success":
        return "done"
    if st == "refused":
        return "refuse"
    return "give_up"


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

    @classmethod
    def run_config(cls) -> dict:
        """What summary.json ``config.planner_config`` records: the variant and its seed pool (path, sha256, size)."""
        info = seed_pool_info() if cls.seed_pool else {"seed_pool": None, "seed_pool_sha": None, "seed_pool_n": 0}
        return {"variant": "rag" if cls.seed_pool else "norag", "loop": cls.loop_kind, "generator": cls.ra_planner,
                "live_memory": "per episode (deleted after it)", **info}

    def __init__(self, llm=None):
        self.llm = llm
        self.events: list = []
        self.generator = None        # None: SAGE (grace), or the fake GoalPlanner under --llm fake
        self.on_loop = None          # inspection hook (loop, env) -> True to stop before the run (built_prompt)

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
        tmp = Path(tempfile.mkdtemp(prefix="homeloop_ra_"))
        node = FakeNode()
        state = FakeState(tmp, node)
        cur = (lambda: state)
        pairs = [(AL, "current", cur), (LP, "current", cur), (state_mod, "current", cur),
                 (AL, "host_id", lambda: "homeloop"), (LP, "host_id", lambda: "homeloop"),
                 (sc, "ENV", env_for(env.world0)), (ra_llm, "init_llm_client", lambda cfg=None, **k: client)]
        if not fake:
            pairs += _count_embodiplan(env)
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
                for ev in loop.run_blocking(env.task_text, lang=env.lang):
                    n += 1
                    e = {k: v for k, v in ev.items() if k not in ("world", "say_audio")}
                    if e.get("event") in ("done", "error"):
                        final = e
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
                env.finish("done", "stopped")
            else:
                env.finish(_status(final), str((final or {}).get("say") or ""))

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
            return AssistLoop(agent, emit=None, generator=gen,
                              health_wait_s=0, memory_path=str(tmp / "mem.json"), **common)
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
