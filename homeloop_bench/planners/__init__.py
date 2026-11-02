"""Planner registry (docs/planners.md). Listing never imports robot_agent."""

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
                         "robot_agent AssistLoop (SAGE, generator grace) through the homeloop robot package", True),
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


def needs_llm(name: str) -> bool:
    if name not in REGISTRY:
        raise KeyError(f"unknown planner {name!r}; known: {', '.join(REGISTRY)}")
    return REGISTRY[name][3]


def planner_class(name: str):
    if name not in REGISTRY:
        raise KeyError(f"unknown planner {name!r}; known: {', '.join(REGISTRY)}")
    mod, cls, _d, _l = REGISTRY[name]
    return getattr(importlib.import_module(f"{__name__}.{mod}"), cls)


def make_planner(name: str, llm=None, **kw):
    p = planner_class(name)(llm=llm, **kw)
    p.name = name
    return p
