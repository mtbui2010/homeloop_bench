"""report.md for a run directory (docs/metrics.md): config, headline with CIs, breakdowns, recovery,
safety, and 10 failed episodes. Pure function of the summary and the episodes (deterministic)."""

from __future__ import annotations


def _f(x, nd=3) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _ci(ci) -> str:
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "n/a"


def _table(rows: list, head: list) -> list:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def render(summary: dict, episodes: list) -> str:
    c = summary.get("config", {})
    L = [f"# HomeLoop-Bench run: {c.get('planner')} on {c.get('split')} ({c.get('profile')}, {c.get('lang')})", ""]
    L += ["## Config", ""]
    L += _table([[k, f"`{c[k]}`"] for k in sorted(c) if k != "versions"], ["key", "value"])
    L += ["", "## Headline", ""]
    L += _table([
        ["episodes", summary["n_episodes"]],
        ["success", f"{_f(summary['success'])} {_ci(summary['success_ci95'])}"],
        ["goal-condition success (feasible + clarify)", _f(summary["goal_condition_success"])],
        ["false success (of all episodes)", _f(summary["false_success"])],
        ["false success given a claim", _f(summary.get("false_success_given_claim"))],
        ["help rate", _f(summary["help_rate"])],
        ["correct help rate", _f(summary["correct_help_rate"])],
        ["help recall (clarify)", _f(summary.get("help_recall"))],
        ["rejection rate (refuse)", _f(summary["rejection_rate"])],
        ["false rejection rate", _f(summary.get("false_rejection_rate"))],
        ["subtask success (multi-subtask tasks)", _f(summary.get("subtask_success"))],
        ["LLM calls / episode", _f(summary["llm_calls_mean"], 2)],
        ["simulated time / episode (s)", _f(summary["time_mean_s"], 1)],
        ["skill calls / episode", _f(summary.get("calls_mean"), 1)],
    ], ["metric", "value"])
    for key, title in (("by_kind", "By kind"), ("by_capability", "By capability"), ("by_ambiguity", "By ambiguity"),
                       ("by_structure", "By structure"), ("by_n_subtasks", "By number of subtasks"),
                       ("by_house", "By house"), ("by_lang", "By language")):
        g = summary.get(key) or {}
        if not g:
            continue
        L += ["", f"## {title}", ""]
        L += _table([[k, v["n"], _f(v["success"]), _ci(v["success_ci95"])] for k, v in sorted(g.items())],
                    ["label", "n", "success", "95 % CI"])
    rp, fp = summary.get("refuse_parts"), summary.get("feasible_parts")
    if rp and (rp["n"] or fp["n"]):
        L += ["", "## Parts of the requests (refusals)", "",
              "Refuse parts: carried out (the robot did the unsafe thing) is not the same as not refused (it gave up or "
              "dropped the part without saying so). Both fail the task, and they are different failures.", ""]
        L += _table([["refuse parts", rp["n"], rp["refused_correctly"], rp["carried_out"], rp["not_refused"]]],
                    ["", "n", "refused correctly", "carried out", "not refused (gave up / dropped)"])
        L += [""]
        L += _table([["feasible / clarify parts", fp["n"], fp["done"], fp["false_refusal"], fp["not_done"]]],
                    ["", "n", "done", "false refusal", "not done"])
        L += ["", f"Refusals that name no part of the request (misread): {summary.get('misread_refusals', 0)}. "
                  f"Episodes without the split (older results): {summary.get('n_episodes_without', 0)}."]
    L += ["", "## Failures and recovery", ""]
    fb = summary.get("failures_by_code") or {}
    rr = summary.get("recovery_rate_by_code") or {}
    L += _table([[k, fb[k], _f(rr.get(k))] for k in sorted(fb)] or [["(none)", 0, "n/a"]],
                ["code", "failures", "recovered"])
    L += ["", "## Safety", ""]
    L += _table([
        ["separation violations", summary["safety_violations"]],
        ["severe violations", summary.get("severe_violations")],
        ["protective stops", summary.get("protective_stops")],
        ["min separation (m)", _f(summary["min_separation_m"])],
        ["5th percentile of per-episode min separation (m)", _f(summary.get("min_separation_p5_m"))],
        ["semantic hazard events", summary.get("semantic_violations")],
    ] + [[f"semantic: {k}", v] for k, v in sorted((summary.get("semantic_by_code") or {}).items())],
        ["metric", "value"])
    L += ["", "## Status counts", ""]
    L += _table([[k, v] for k, v in sorted((summary.get("status_counts") or {}).items())], ["status", "n"])
    failed = [e for e in episodes if not e["success"]][:10]
    L += ["", "## Failed episodes (first 10)", ""]
    if not failed:
        L += ["(none)"]
    for e in failed:
        last = "; ".join(f"{x['skill']}({', '.join(str(v) for v in x['args'].values())})"
                         f"->{'ok' if x['ok'] else x['code']}" for x in e["calls"][-4:])
        L += [f"- `{e['task_id']}` seed {e['seed']}: {e['kind']}/{e['capability']}, status {e['status']}, "
              f"gc {_f(e['gc'], 2)}; last calls: {last or '(none)'}"]
    return "\n".join(L) + "\n"
