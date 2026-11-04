"""Planner registry (docs/planners.md). Listing never imports robot_agent.

A planner name is a registry key (``oracle``, ``robot_agent:sage``, ...) or a third-party class given as
``package.module:ClassName`` (docs/planners.md "Your own planner")."""

from __future__ import annotations

import importlib
import importlib.util

# name -> (module, class, one-line description, needs_llm)
REGISTRY = {
    "oracle": ("oracle", "OraclePlanner",
               "privileged reference: re-solves from the true world after every call; retries, waits, asks for help", False),
    "naive": ("naive", "NaivePlanner",
              "privileged ablation: the oracle's start-state plan, open loop, no recovery or asking", False),
    "saycan_like": ("saycan_like", "SayCanLike",
                    "after SayCan (Ahn et al. 2022): LLM picks one affordance-filtered call per step by index", True),
    "inner_monologue_like": ("inner_monologue_like", "InnerMonologueLike",
                             "after Inner Monologue (Huang et al. 2022): step-wise LLM with result and scene feedback", True),
    "progprompt_like": ("progprompt_like", "ProgPromptLike",
                        "after ProgPrompt (Singh et al. 2022): one LLM-written program with assert/recover lines", True),
    "knowno_like": ("knowno_like", "KnowNoLike",
                    "after KnowNo (Ren et al. 2023): conformal prediction set over interpretations, asks when > 1", True),
    "robot_agent:sage": ("robot_agent_adapter", "SagePlanner",
                         "robot_agent AssistLoop (SAGE, generator grace) with its seed-pool retrieval, through the homeloop robot package", True),
    "robot_agent:sage_norag": ("robot_agent_adapter", "SageNoRagPlanner",
                               "robot_agent:sage with an empty seed pool (zero-shot SAGE, the RAG ablation)", True),
    "robot_agent:sage_ask": ("robot_agent_adapter", "SageAskPlanner",
                             "robot_agent:sage with people tracking off: no positions of people in the ENV, SAGE asks where they are", True),
    "robot_agent:sage_nohazard": ("robot_agent_adapter", "SageNoHazardPlanner",
                                  "robot_agent:sage with its core hazard rules off (model-only safety, ablation)", True),
    "robot_agent:sage_pivot_none": ("robot_agent_adapter", "SagePivotNonePlanner",
                                    "robot_agent:sage with input_pivot=none: Korean words go to the understand prompt as they are (language-layer ablation)", True),
    "robot_agent:sage_pivot_translate": ("robot_agent_adapter", "SagePivotTranslatePlanner",
                                         "robot_agent:sage with input_pivot=translate: the understand prompt gets the English translation (language-layer ablation)", True),
    "robot_agent:sage_complete": ("robot_agent_adapter", "SageCompletePlanner",
                                  "robot_agent:sage with the gate's complete operator on (ablation)", True),
    "robot_agent:grace": ("robot_agent_adapter", "GracePlanner",
                          "robot_agent ClosedLoop with planner grace through the homeloop robot package", True),
    "robot_agent:llm_direct": ("robot_agent_adapter", "LlmDirectPlanner",
                               "robot_agent ClosedLoop with planner llm_direct through the homeloop robot package", True),
}


def robot_agent_available() -> bool:
    try:
        return importlib.util.find_spec("robot_agent") is not None
    except (ImportError, ValueError):
        return False


def list_planners() -> list:
    """[(name, description, available)] in registry order."""
    ra = robot_agent_available()
    return [(n, d, (ra or not n.startswith("robot_agent:"))) for n, (_m, _c, d, _l) in REGISTRY.items()]


def is_spec(name: str) -> bool:
    """``package.module:ClassName`` (a third-party planner), not a registry key."""
    if name in REGISTRY or ":" not in name:
        return False
    mod, _, cls = name.partition(":")
    return bool(mod) and bool(cls) and cls.isidentifier() and all(p.isidentifier() for p in mod.split("."))


def _unknown(name: str) -> KeyError:
    return KeyError(f"unknown planner {name!r}; known: {', '.join(REGISTRY)}, or package.module:ClassName")


def needs_llm(name: str) -> bool:
    if is_spec(name):
        return bool(getattr(planner_class(name), "needs_llm", False))
    if name not in REGISTRY:
        raise _unknown(name)
    return REGISTRY[name][3]


def planner_class(name: str):
    if is_spec(name):
        mod, _, cls = name.partition(":")
        return getattr(importlib.import_module(mod), cls)
    if name not in REGISTRY:
        raise _unknown(name)
    mod, cls, _d, _l = REGISTRY[name]
    return getattr(importlib.import_module(f"{__name__}.{mod}"), cls)


def planner_available(name: str) -> tuple:
    """(ok, reason): the planner can run here (robot_agent importable, a third-party class importable)."""
    if name.startswith("robot_agent:") and name in REGISTRY:
        return (True, "") if robot_agent_available() else (False, "robot_agent not importable (add it to PYTHONPATH)")
    try:
        planner_class(name)
    except KeyError as e:
        return False, str(e.args[0] if e.args else e)
    except (ImportError, AttributeError) as e:
        return False, f"{type(e).__name__}: {e}"
    return True, ""


def make_planner(name: str, llm=None, **kw):
    p = planner_class(name)(llm=llm, **kw)
    p.name = name
    return p
