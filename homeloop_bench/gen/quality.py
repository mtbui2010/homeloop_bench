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
