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
    "robot_agent:sage_lab": ("robot_agent_adapter", "SageLabPlanner",
                             "robot_agent:sage with the lab prototype person_goals on (go / say steps kept as fixed sub-goals, hand-over to the named person)", True),
    "robot_agent:sage_ground2": ("robot_agent_adapter", "SageGround2Planner", "robot_agent:sage with grounding chain v2 on (go_steps, kind_anchor, name_canon)", True),
    "robot_agent:sage_g2_go": ("robot_agent_adapter", "SageGoStepsPlanner", "ablation: go_steps only", True),
    "robot_agent:sage_g2_kind": ("robot_agent_adapter", "SageKindAnchorPlanner", "ablation: kind_anchor only", True),
    "robot_agent:sage_g2_name": ("robot_agent_adapter", "SageNameCanonPlanner", "ablation: name_canon only", True),
    "robot_agent:sage_reask": ("robot_agent_adapter", "SageReaskPlanner", "robot_agent:sage with reask_abstain on (one directed re-understand of a goal-less where-is-it reading)", True),
    "robot_agent:sage_unstick": ("robot_agent_adapter", "SageUnstickPlanner", "robot_agent:sage with dialog_unstick on (restated refused reading read back again, not-sure where-is answer searches, no stacked apology)", True),
    "robot_agent:sage_exec": ("robot_agent_adapter", "SageExecPlanner", "robot_agent:sage with execution integrity on (exec_integrity: gate_strict, endstate_check, reset_container, wait_on_robot)", True),
    "robot_agent:sage_inv": ("robot_agent_adapter", "SageInventoryPlanner", "robot_agent:sage with inventory_ask on (which instance of the robot's own object memory)", True),
    "robot_agent:sage_ei_gate": ("robot_agent_adapter", "SageEiGatePlanner", "ablation of sage_exec: gate_strict only", True),
    "robot_agent:sage_ei_end": ("robot_agent_adapter", "SageEiEndPlanner", "ablation of sage_exec: endstate_check only", True),
    "robot_agent:sage_ei_reset": ("robot_agent_adapter", "SageEiResetPlanner", "ablation of sage_exec: reset_container only", True),
    "robot_agent:sage_ei_wait": ("robot_agent_adapter", "SageEiWaitPlanner", "ablation of sage_exec: wait_on_robot only", True),
    "robot_agent:sage_r3": ("robot_agent_adapter", "SageR3Planner", "robot_agent:sage_ground2 + sage_exec + sage_inv (lab round 3 combination)", True),
    "robot_agent:sage_r3u": ("robot_agent_adapter", "SageR3uPlanner", "robot_agent:sage_r3 + dialog_unstick (lab round 4 combination)", True),
    "robot_agent:sage_u1": ("robot_agent_adapter", "SageU1Planner", "robot_agent:sage_ground2 + reask_anchor (lab round 7: the abstention re-reading is taken only when every place in it is in the person's words)", True),
    "robot_agent:sage_u2": ("robot_agent_adapter", "SageU2Planner", "robot_agent:sage_u1 + no_shared_listener (shared_listener rule off)", True),
    "robot_agent:sage_u3": ("robot_agent_adapter", "SageU3Planner", "robot_agent:sage_u2 + understand_views (original and translator pivot read separately; act on agreement, ask on disagreement)", True),
    "robot_agent:sage_u": ("robot_agent_adapter", "SageUPlanner", "robot_agent:sage_u3 + understand_goals_first (schema order: goals before the verdict)", True),
    "robot_agent:sage_um": ("robot_agent_adapter", "SageUmPlanner", "robot_agent:sage_ground2 + understand_model (the 30B model reads the request, the 8B plans) with the runaway guard that falls back to the planner (lab round 7)", True),
    "robot_agent:sage_um_ko": ("robot_agent_adapter", "SageUmKoPlanner", "robot_agent:sage_um with the model chosen by language (understand_model_lang {ko: 30B}; English is read by the planner)", True),
    "robot_agent:sage_um_strict": ("robot_agent_adapter", "SageUmStrictPlanner", "robot_agent:sage_um + understand_schema_strict (said and content required in every goal)", True),
    "robot_agent:sage_um_give": ("robot_agent_adapter", "SageUmGivePlanner", "robot_agent:sage_um + understand_give_kind (a give goal kind, and the say-to-the-speaker echo filter)", True),
    "robot_agent:sage_um_verdict": ("robot_agent_adapter", "SageUmVerdictPlanner", "robot_agent:sage_um + understand_verify_verdict (an infeasible verdict names a missing action; location_unknown is clear)", True),
    "robot_agent:sage_m1": ("robot_agent_adapter", "SageM1Planner", "robot_agent:sage_ground2 + the understand-model option with the runaway guard (same configuration as sage_um)", True),
    "robot_agent:sage_m2": ("robot_agent_adapter", "SageM2Planner", "robot_agent:sage_m1 + understand_schema_strict + understand_give_kind + understand_verify_verdict", True),
    "robot_agent:sage_m9": ("robot_agent_adapter", "SageM9Planner", "robot_agent:sage_ground2 + Qwen3.5 9B for understand_model and repair_model (guards fall back to the planner's model; translator unchanged; lab round 8)", True),
    "robot_agent:sage_mk": ("robot_agent_adapter", "SageMkPlanner", "robot_agent:sage_m9 + a Korean dialog model (dialog_model_lang {ko: HyperCLOVAX-SEED-Think-14B}) for the robot's Korean questions, read-backs and translations", True),
    "robot_agent:sage_s4": ("robot_agent_adapter", "SageS4Planner", "robot_agent:sage_ground2 + dialog_unstick + inventory_ask + reask_anchor + request_coverage (step 4)", True),
    "robot_agent:sage_s5": ("robot_agent_adapter", "SageS5Planner", "the sage_r3u bundle (ground2 + exec_integrity: endstate_check, wait_on_robot, reset_container, gate_strict + inventory_ask + dialog_unstick; step 5)", True),
    "robot_agent:sage_s45": ("robot_agent_adapter", "SageS45Planner", "sage_s5 + reask_anchor + request_coverage (steps 4 and 5 together)", True),
    "robot_agent:sage_gold": ("robot_agent_adapter", "SageGoldPlanner",
                              "DIAGNOSTIC, PRIVILEGED: robot_agent:sage started from the task's gold goals (understand step skipped): the execution-only ceiling", True),
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
