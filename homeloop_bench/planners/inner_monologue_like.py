"""``inner_monologue_like``: after Inner Monologue (Huang et al. 2022, arXiv:2207.05608).

A step-wise LLM loop: every step the LLM sees the instruction, the house, its full history WITH the result
text of every call (success-detection feedback), the answers of the user and the ``look`` scene
descriptions, and chooses the next tool call, a question, or the end. Failures are handled only by what
the LLM decides after seeing them (implicit replanning). Docs: docs/planners.md.
"""

from __future__ import annotations

from ..env import Finish, ToolCall, give_up_text
from .base import ask_json, finish_with, step_check
from .prompts import step_prompt


class LLMStepPlanner:
    """Shared loop of the step-wise LLM planners: prompt -> JSON -> one tool call (or decline / finish)."""

    name = "llm_step"
    privileged = False
    needs_llm = True
    mode = "inner_monologue"
    description = ""

    def __init__(self, llm=None):
        self.llm = llm
        self.declined: list = []

    def extra(self, obs) -> str:
        return ""

    def decide(self, obs):
        prompt = step_prompt(self.mode, obs, self.extra(obs), declined=self.declined)
        obj = ask_json(self.llm, prompt, check=step_check)
        if obj is None:
            return Finish("give_up", reason="no valid answer from the LLM")
        if "finish" in obj:
            return Finish(obj["finish"], str(obj.get("say") or ""))
        a = obj["action"]
        return ToolCall(a["skill"], dict(a.get("args") or {}))

    def run(self, env) -> None:
        if self.llm is None:
            raise RuntimeError(f"planner {self.name} needs an LLM")
        self.env = env
        n_decline = 0
        while env.status is None:
            if env.over:
                env.finish("give_up", give_up_text(env.lang), reason="budget exhausted")
                return
            obs = env.observe()
            a = self.decide(obs)
            if isinstance(a, Finish):
                finish_with(env, a)
                return
            if a.skill == "decline":
                n_decline += 1
                reason = str(a.args.get("reason", ""))
                self.declined.append(reason)
                env.note_refusal(reason, subtask=a.args.get("subtask"), obj=a.args.get("obj"))
                if n_decline > 2:
                    env.finish("give_up", give_up_text(env.lang), reason="repeated declines")
                    return
                continue
            env.call(a.skill, **a.args)


class InnerMonologueLike(LLMStepPlanner):
    name = "inner_monologue_like"
    mode = "inner_monologue"
    description = "step-wise LLM with result and scene feedback (after Inner Monologue)"
