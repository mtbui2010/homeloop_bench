"""Markdown tables of docs/experiments.md from results/<exp>/*/summary.json.

    python tools/exp_tables.py results/exp_r2

Every number is read from a summary.json; nothing is computed here except the formatting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = ("oracle", "naive", "progprompt_like", "robot_agent:sage")


def f3(x):
    return "-" if x is None else f"{x:.3f}"


def ci(s):
    lo, hi = s.get("success_ci95") or (None, None)
    return f"{f3(s['success'])} [{f3(lo)}, {f3(hi)}]"


def runs(root: Path):
    out = []
    for d in sorted(root.iterdir()):
        f = d / "summary.json"
        if f.exists():
            planner, model, lang = d.name.rsplit("__", 2)
            out.append((planner, model, lang, json.loads(f.read_text(encoding="utf-8"))))
    out.sort(key=lambda r: (ORDER.index(r[0]) if r[0] in ORDER else 99, r[0], r[2]))
    return out


def split_cell(s, key, label):
    v = (s.get(key) or {}).get(label)
    if not v:
        return "-"
    return f"{f3(v['success'])} (n={v['n']})"


def main(root: str) -> int:
    R = runs(Path(root))
    print("| planner | model | lang | n | success [95 % CI] | false_success | help_rate | rejection_rate | "
          "safety_violations | llm_calls_mean |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for p, m, lang, s in R:
        print(f"| {p} | {m} | {lang} | {s['n_episodes']} | {ci(s)} | {f3(s['false_success'])} | {f3(s['help_rate'])} | "
              f"{f3(s['rejection_rate'])} | {s['safety_violations']} | {s['llm_calls_mean']:.2f} |")
    for key, labels, title in (("by_delivery", ("none", "reach", "hand", "mixed"), "delivery mode of the task"),
                               ("by_kind", ("feasible", "clarify", "refuse"), "kind"),
                               ("by_n_subtasks", ("1", "2", "3"), "number of subtasks")):
        print(f"\nSuccess by {title} (success, n):\n")
        print("| planner | lang | " + " | ".join(labels) + " |")
        print("|---|---|" + "---|" * len(labels))
        for p, m, lang, s in R:
            print(f"| {p} | {lang} | " + " | ".join(split_cell(s, key, lab) for lab in labels) + " |")
    print("\nDelivery atoms held at the end, by label (held share, n), and handovers on reach atoms:\n")
    labs = ("reach:None", "hand:explicit", "hand:no_surface", "hand:user_needs")
    print("| planner | lang | " + " | ".join(labs) + " | unneeded_handover_rate |")
    print("|---|---|" + "---|" * (len(labs) + 1))
    for p, m, lang, s in R:
        da = s.get("delivery_atoms") or {}
        cells = [f"{f3(da[k]['held'])} (n={da[k]['n']})" if k in da else "-" for k in labs]
        print(f"| {p} | {lang} | " + " | ".join(cells) +
              f" | {f3((s.get('delivery_mode') or {}).get('unneeded_handover_rate'))} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "results/exp_r2"))
