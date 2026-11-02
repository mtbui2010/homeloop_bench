"""Quality reports (``python -m homeloop_bench.data quality``; docs/paraphrase_quality.md).

1. ``data/quality/ko_backtranslation_report.json``: >= 500 tasks sampled by seed (stratified by source x structure).
   Each Korean text is translated back to English by the local LLM (temperature 0; cached, the same requests the
   paraphrase step used where they exist) and compared with the task's English text:
     chrF (n = 6, beta = 2), entity preservation (share of the English entity phrases that appear in the
     back-translation, aliases allowed) and structure-marker preservation (first / then, if, no wait ...).
   The report gives the distribution per source / structure / kind and the 25 lowest-scoring tasks.
2. ``data/quality/paraphrase_quality.json``: the paraphrase run (model, requested / accepted, rejections per filter,
   chrF of accepted Korean paraphrases, judge outcome) and 30 sampled template -> paraphrase pairs.
3. ``docs/paraphrase_quality.md``: both, as tables.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from statistics import mean, median

from homeloop_robot.rng import derive_seed

from ..data import QUALITY_DIR, REPO_DIR, SPLITS
from .chrf import chrf
from .dedup import norm
from .paraphrase import LLM, Cache, has_phrase

MARKERS = {"ordered": ["first", "then", "before", "after"], "conditional": ["if", "otherwise", "not"],
           "correction": ["no", "wait", "sorry", "mean", "actually", "not"]}
GEN_SEED = 2026


def _q(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    k = len(xs)
    return {"n": k, "mean": round(mean(xs), 2), "median": round(median(xs), 2), "p10": round(xs[int(0.1 * (k - 1))], 2),
            "p25": round(xs[int(0.25 * (k - 1))], 2), "p75": round(xs[int(0.75 * (k - 1))], 2), "min": round(xs[0], 2)}


def sample(recs, n, seed=GEN_SEED):
    by = defaultdict(list)
    for r in recs:
        by[(r["source"], r["structure"])].append(r)
    out = []
    total = len(recs)
    for k in sorted(by):
        rs = sorted(by[k], key=lambda r: derive_seed(seed, "quality", r["id"]))
        out += rs[:max(3, round(n * len(rs) / total))]
    return sorted(out, key=lambda r: r["id"])


def back_seed(r):
    if r["source"] == "llm_paraphrase":
        return derive_seed(GEN_SEED, "bp", r["id"])
    return derive_seed(GEN_SEED, "bt", r["id"])


def score(r, back):
    en = r["text"]["en"]
    ents = (r.get("meta") or {}).get("entities", {}).get("en", [])
    nb = norm(back, "en")
    kept = [any(has_phrase(nb, a, "en") for a in alts) for alts in ents]
    m = MARKERS.get(r["structure"])
    marker = None if not m else any(re.search(rf"\b{w}\b", back.lower()) for w in m)
    return {"chrf": round(chrf(back, en), 2), "entities": round(sum(kept) / len(kept), 3) if kept else None,
            "marker": marker}


def run(url="http://127.0.0.1:11536", model="qwen3-vl:8b-instruct", n=600, offline=False, log=print) -> int:
    from ..tasks import read_records
    recs = [r for s in SPLITS for r in read_records(s)]
    llm = LLM(url, model, Cache(), offline=offline)
    smp = sample(recs, n)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as pool:
        backs = list(pool.map(lambda r: llm.ask("back", {"text": r["text"]["ko"]}, back_seed(r)), smp))
    rows = []
    for r, (bt, sha) in zip(smp, backs):
        s = score(r, bt) if bt else {"chrf": 0.0, "entities": 0.0, "marker": False}
        rows.append({"id": r["id"], "source": r["source"], "structure": r["structure"], "kind": r["kind"],
                     "capability": r["capability"], "en": r["text"]["en"], "ko": r["text"]["ko"], "back_en": bt,
                     "sha": sha, **s})
    ok = [x for x in rows if x["back_en"]]

    def group(key):
        g = defaultdict(list)
        for x in ok:
            g[x[key]].append(x)
        return {k: {"chrf": _q([y["chrf"] for y in v]),
                    "entities_mean": round(mean([y["entities"] for y in v if y["entities"] is not None] or [0]), 3)}
                for k, v in sorted(g.items())}
    markers = [x["marker"] for x in ok if x["marker"] is not None]
    rep = {"model": model, "n_sampled": len(smp), "n_backtranslated": len(ok), "llm_calls_new": llm.n_calls,
           "metric": "chrF(back-translation of text.ko, text.en), n=6, beta=2; entity preservation = share of the "
                     "English entity phrases (aliases allowed) found in the back-translation",
           "chrf": _q([x["chrf"] for x in ok]),
           "entities_mean": round(mean([x["entities"] for x in ok if x["entities"] is not None] or [0]), 3),
           "entities_all_kept_share": round(sum(1 for x in ok if x["entities"] == 1.0) / max(1, len(ok)), 3),
           "structure_marker_kept_share": round(sum(markers) / max(1, len(markers)), 3) if markers else None,
           "by_source": group("source"), "by_structure": group("structure"), "by_kind": group("kind"),
           "lowest": sorted(ok, key=lambda x: x["chrf"])[:25], "rows": rows}
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    _write(QUALITY_DIR / "ko_backtranslation_report.json", rep)
    para = paraphrase_report(recs)
    _write(QUALITY_DIR / "paraphrase_quality.json", para)
    write_md(rep, para)
    realism = None
    rp = QUALITY_DIR / "realism_report.json"
    if rp.exists():
        realism = json.load(open(rp, encoding="utf-8"))
    write_datasheet(recs, para, {k: rep[k] for k in ("n_backtranslated", "chrf", "entities_mean")}, realism)
    log(f"back-translation report: {len(ok)} of {len(smp)} tasks, chrF mean {rep['chrf'].get('mean')}, "
        f"entities kept {rep['entities_mean']}; new LLM calls {llm.n_calls}")
    return 0 if len(ok) >= 500 else 1


def paraphrase_report(recs):
    run_info = {}
    p = QUALITY_DIR / "paraphrase_run.json"
    if p.exists():
        run_info = json.load(open(p, encoding="utf-8"))
    para = [r for r in recs if r["source"] == "llm_paraphrase"]
    chrfs = [r["meta"]["paraphrase"]["chrf_backtranslation"] for r in para]
    pairs = sorted(para, key=lambda r: derive_seed(GEN_SEED, "pairs", r["id"]))[:30]
    return {"run": run_info, "n_records": len(recs), "n_paraphrased": len(para),
            "share": round(len(para) / max(1, len(recs)), 4),
            "by_structure": dict(sorted(Counter(r["structure"] for r in para).items())),
            "by_kind": dict(sorted(Counter(r["kind"] for r in para).items())),
            "chrf_backtranslation_accepted": _q(chrfs),
            "pairs": [{"id": r["id"], "template": r["meta"]["template_text"], "paraphrase": r["text"],
                       "back_en": r["meta"]["paraphrase"]["back_en"],
                       "chrf": r["meta"]["paraphrase"]["chrf_backtranslation"]} for r in pairs]}


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True, ensure_ascii=False, indent=1)
        f.write("\n")


def write_md(rep, para):
    run_info = para.get("run") or {}
    L = ["# Paraphrase and Korean back-translation quality", "",
         "Generated by `python -m homeloop_bench.data quality` from the shipped data (see [generation.md](generation.md)). "
         "Raw numbers: `data/quality/paraphrase_quality.json`, `data/quality/ko_backtranslation_report.json`, "
         "`data/quality/paraphrase_run.json`.", "",
         "## Paraphrases", "",
         f"- model: `{run_info.get('model', 'n/a')}` (local Ollama on GPU 0), prompt version {run_info.get('prompt_version')}",
         f"- records selected for paraphrase: {run_info.get('selected')} (share {run_info.get('frac')}), "
         f"rounds {run_info.get('rounds')}",
         f"- accepted: English {run_info.get('accepted_en')}, Korean {run_info.get('accepted_ko')}, both "
         f"{run_info.get('accepted_both')}; applied {run_info.get('applied')}",
         f"- `llm_paraphrase` records: {para['n_paraphrased']} of {para['n_records']} ({para['share']:.1%})",
         f"- Korean back-translation chrF of the accepted paraphrases: {para['chrf_backtranslation_accepted']}", "",
         "Rejections per filter (a candidate can fail several):", "", "| filter | English | Korean |", "|---|---|---|"]
    rj = run_info.get("rejections") or {}
    for k in sorted(set(rj.get("en", {})) | set(rj.get("ko", {}))):
        L.append(f"| {k} | {rj.get('en', {}).get(k, 0)} | {rj.get('ko', {}).get(k, 0)} |")
    L += ["", "## Korean back-translation check (sampled tasks)", "",
          f"- tasks sampled: {rep['n_sampled']} (stratified by source x structure), back-translated: {rep['n_backtranslated']}",
          f"- {rep['metric']}",
          f"- chrF: {rep['chrf']}",
          f"- entity phrases kept: mean {rep['entities_mean']}, all kept in {rep['entities_all_kept_share']:.1%} of the tasks",
          f"- structure markers kept (ordered / conditional / correction): {rep['structure_marker_kept_share']}", "",
          "| source | n | chrF mean | chrF median | entities kept |", "|---|---|---|---|---|"]
    for k, v in rep["by_source"].items():
        L.append(f"| {k} | {v['chrf'].get('n')} | {v['chrf'].get('mean')} | {v['chrf'].get('median')} | {v['entities_mean']} |")
    L += ["", "| structure | n | chrF mean | entities kept |", "|---|---|---|---|"]
    for k, v in rep["by_structure"].items():
        L.append(f"| {k} | {v['chrf'].get('n')} | {v['chrf'].get('mean')} | {v['entities_mean']} |")
    L += ["", "Lowest five (Korean text, its back-translation, the English text):", ""]
    for x in rep["lowest"][:5]:
        L.append(f"- `{x['id']}` chrF {x['chrf']}: {x['ko']} -> \"{x['back_en']}\" vs \"{x['en']}\"")
    L += ["", "chrF between independent English and Korean wordings is low by nature (the templates are written "
              "separately, not translated), so the score is a meaning-drift alarm, not a translation-quality score; "
              "the entity check is the stronger signal.", "", "## Sampled pairs", ""]
    for x in para["pairs"][:10]:
        L.append(f"- `{x['id']}`: \"{x['template']['en']}\" -> \"{x['paraphrase']['en']}\"; "
                 f"{x['template']['ko']} -> {x['paraphrase']['ko']} (chrF {x['chrf']})")
    (REPO_DIR / "docs").mkdir(exist_ok=True)
    (REPO_DIR / "docs" / "paraphrase_quality.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── datasheet (Gebru et al., "Datasheets for Datasets", arXiv:1803.09010) ───────────────────────────────
def _tab(d, total, head):
    L = [f"| {head} | tasks | share |", "|---|---|---|"]
    for k, v in sorted(d.items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v} | {v / total:.1%} |")
    return L


def write_datasheet(recs, para=None, bt=None, realism=None):
    from .stats import stats
    s = stats(recs)
    n = s["total"]
    para = para or {}
    run_info = para.get("run") or {}
    by_split_house = Counter((r["split"], r["house"]) for r in recs)
    hz = Counter(h["code"] for r in recs for h in r["hazards"])
    L = ["# Datasheet: HomeLoop-Bench tasks", "",
         "Following Gebru et al., *Datasheets for Datasets* (https://arxiv.org/abs/1803.09010). The numbers below are "
         "computed from the shipped files by `python -m homeloop_bench.data quality` (see [generation.md](generation.md)).",
         "", "## Motivation", "",
         "HomeLoop-Bench evaluates household robot task planners in closed loop: plan, act, verify, replan, ask and "
         "stay safe, on a stochastic mock robot (homeloop_robot) whose failure rates come from published robot "
         "experiments. The instruction sets it builds on (ALFRED, SayCan, AmbiK) are English-only. The tasks here are "
         "bilingual (English and Korean), cover what people actually ask a home robot (fetch, put away, search, "
         "open, tidy, pass on a message, go somewhere, and combinations of these), include ambiguous requests the "
         "robot should ask about, unsafe or impossible requests it should refuse, mid-task corrections, and long "
         "multi-task utterances, and every task has a machine-checkable goal on the true world state.",
         "", "Created by Trung Bui for the HomeLoop RA-L paper and public release (Apache-2.0).", "",
         "## Composition", "",
         f"- {n} tasks: train {s['by_split'].get('train', 0)}, dev {s['by_split'].get('dev', 0)}, test "
         f"{s['by_split'].get('test', 0)} ([splits.md](splits.md)); every task has English and Korean text "
         f"(en {s['en']}, ko {s['ko']}).",
         f"- {len(s['by_house'])} house layouts of homeloop_robot; `korean_apt_84` and `care_home_suite` only in test.",
         "- A task = a world (`house`, `seed_state`), the instruction in both languages, the goal, labels, the "
         "simulated user's script and, for compound tasks, the subtasks ([tasks.md](tasks.md)).",
         "- No real people: household members are roles (mom, grandpa, the caregiver); no personal data.", ""]
    L += ["### Labels", ""] + _tab(s["by_kind"], n, "kind") + [""] + _tab(s["by_capability"], n, "capability") + [""] + \
        _tab(s["by_ambiguity"], n, "ambiguity") + [""] + _tab(s["by_source"], n, "source") + [""]
    L += ["Label policy: `homeloop_bench/data/label_policy.yaml`. Every kind, capability and ambiguity value is >= 5 % "
          "of the tasks except `ambiguity = safety`, which is documented as smaller by design: a safety ambiguity "
          "needs a real dangerous confusion in the house (two medicine bottles, medicine vs. vitamins for an older "
          "person, scissors for a child), which only a few houses have, and every text must be unique. Among the "
          "ambiguous tasks the shares are preference / common sense / safety = "
          f"{s['by_ambiguity'].get('preference', 0)} / {s['by_ambiguity'].get('common_sense', 0)} / "
          f"{s['by_ambiguity'].get('safety', 0)}; AmbiK (arXiv:2506.04089, Sec. 3.2) has 42 / 42.5 / 15.5 %.", ""]
    L += ["### Compound instructions (DESIGN 14)", ""] + _tab(s["by_structure"], n, "structure") + [""]
    L += [f"- subtasks per task: {s['by_subtasks']} (>= 2: "
          f"{sum(v for k, v in s['by_subtasks'].items() if int(k) >= 2) / n:.1%}, 3: "
          f"{sum(v for k, v in s['by_subtasks'].items() if int(k) >= 3) / n:.1%})",
          f"- long (EN >= 25 words or KO >= 15 어절): {s['long_share']:.1%}; mixed kinds in one utterance: "
          f"{s['mixed_kind_share']:.1%}",
          "- conditional requests have no opened source for their exact wording (assumed) and are capped at 5 %.", ""]
    L += ["### Houses", "", "| house | train | dev | test |", "|---|---|---|---|"]
    for h in sorted(s["by_house"]):
        L.append(f"| {h} | {by_split_house.get(('train', h), 0)} | {by_split_house.get(('dev', h), 0)} | "
                 f"{by_split_house.get(('test', h), 0)} |")
    L += ["", "Houses with more people and rooms (shared flat, couple flat, Korean 59 m2 apartment) have more distinct "
              "requests, so they hold more tasks; single-person homes cannot have messages or hand-overs to others.",
          "", "### Hazards of the refused requests", ""] + _tab(dict(hz), max(1, sum(hz.values())), "hazard code") + [""]
    L += ["## Collection process", "",
          "- Templates written by the authors (English and Korean separately, not translated) over a shared slot set; "
          "families are cited task types from published datasets (ALFRED, SayCan, TEACh, AmbiK, KnowNo, "
          "SafeAgentBench, RoboGuard, RoboCup@Home GPSR, EmbodiedBench, HomeRobot OVMM) - [realism.md](realism.md).",
          "- Worlds are the homeloop_robot houses in seeded arrangements; the goal is checked against the oracle, "
          "which must solve every feasible and clarify task through the robot in the `ideal` profile.",
          f"- LLM paraphrases: local `{run_info.get('model', 'qwen3-vl:8b-instruct')}` (Ollama on one GPU), generated "
          "2026-11-02; filters, back-translation chrF and a same-meaning judge "
          f"([paraphrase_quality.md](paraphrase_quality.md)); {para.get('n_paraphrased', 0)} tasks "
          f"({para.get('share', 0):.1%}) are `llm_paraphrase`, the rest `template`.", "",
          "## Preprocessing / cleaning", "",
          "- Exact duplicates (normalised text, per language) are removed everywhere; near duplicates across splits "
          "(Jaccard >= 0.9 of character n-grams) are removed.",
          "- Realism rules R-a..R-h (typical receptacles, sizes, payload, sources, kind semantics, language, houses) "
          "hold for every task (`data/quality/realism_report.json`" +
          (f": {realism.get('violations', 0)} violations, {realism.get('intentional', 0)} intentional refused "
           "requests" if realism else "") + ").",
          "- Korean in 해요체; colloquially dropped object particles in "
          f"{(realism or {}).get('ko_particle_dropped_share', 0):.1%} of the Korean texts (<= 30 %).", ""]
    if bt:
        L += [f"- Korean back-translation check on {bt.get('n_backtranslated')} sampled tasks: chrF mean "
              f"{bt.get('chrf', {}).get('mean')}, entity phrases kept {bt.get('entities_mean')} "
              "(`data/quality/ko_backtranslation_report.json`).", ""]
    L += ["## Uses", "",
          "- Intended: closed-loop evaluation of LLM / VLM task planners for home robots in simulation (success, goal-"
          "condition success, false success, recovery, help and rejection rates, safety), in English and Korean, with "
          "paired tests between planners.",
          "- Out of scope: training or evaluating real robots without a real-world safety layer; judging Korean or "
          "English language quality in general; any claim about real people (the users are scripted).",
          "- Known limits: the world is symbolic; utterances are template- or LLM-written, not recorded speech (the "
          "robot's ASR noise model adds recognition errors at run time); clarify answers are scripted; the "
          "paraphrase model is an 8B local model, so some paraphrases are plainer than human speech.", "",
          "## Distribution", "",
          "- Apache-2.0, with the code (`homeloop_bench`), in `homeloop_bench/data/tasks/*.jsonl`; the LLM cache "
          "(`homeloop_bench/data/llm_cache/paraphrase.jsonl`) is shipped so the paraphrase step is reproducible.", "",
          "## Maintenance", "",
          "- Regenerate with `python -m homeloop_bench.data generate` + `paraphrase --offline`; any change must keep "
          "`validate --strict` and `realism --strict` green. Issues and corrections go to the repository's tracker.",
          ""]
    (REPO_DIR / "docs" / "datasheet.md").write_text("\n".join(L), encoding="utf-8")
