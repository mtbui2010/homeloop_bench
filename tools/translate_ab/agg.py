"""Translation A/B (data/quality/translate_ab.json): run with the A/B directory as argument, e.g.
``python tools/translate_ab/agg.py data/quality/translate_ab``."""
import json, sys, collections, statistics as st, math, re
S = sys.argv[1]
J = [json.load(open(f"{S}/judge_{k}.json")) for k in (1, 2, 3)]
M = ["qwen3-vl:8b-instruct", "exaone3.5:latest", "qwen3-vl:30b-a3b-instruct"]
items = [json.loads(l) for l in open(f"{S}/items.jsonl")]
per = collections.defaultdict(list)
for j in J:
    for s in j["scores"]:
        per[(s["id"], s["model"])].append(s)
assert all(len(per[(i["id"], m)]) == 3 for i in items for m in M), "missing judge scores"
agg = {}
for (iid, m), ss in per.items():
    agg[(iid, m)] = {"meaning": st.mean(s["meaning"] for s in ss), "natural": st.mean(s["natural"] for s in ss),
                     "names_kept": sum(bool(s["names_kept"]) for s in ss) >= 2,
                     "cjk_or_garble": sum(bool(s["cjk_or_garble"]) for s in ss) >= 2}
# regex garble check, independent of judges
RX = re.compile(r"[぀-ヿ㐀-䶿一-鿿Ѐ-ӿ฀-๿�]")
summ = {}
for m in M:
    a = [agg[(i["id"], m)] for i in items]
    n = len(a)
    summ[m] = {"n": n,
               "meaning_mean": round(st.mean(x["meaning"] for x in a), 3),
               "natural_mean": round(st.mean(x["natural"] for x in a), 3),
               "names_kept_rate": round(sum(x["names_kept"] for x in a) / n, 3),
               "no_garble_rate": round(1 - sum(x["cjk_or_garble"] for x in a) / n, 3),
               "cjk_or_garble_n": sum(x["cjk_or_garble"] for x in a),
               "meaning_le2_n": sum(x["meaning"] <= 2 for x in a),
               "regex_foreign_script_n": sum(bool(RX.search(i["out"][m])) for i in items),
               "per_judge_meaning_mean": [j["summary"][m]["meaning_mean"] for j in J]}
    summ[m]["composite"] = round((summ[m]["meaning_mean"] - 1) / 4 + summ[m]["names_kept_rate"] + summ[m]["no_garble_rate"], 3)
# paired comparison on meaning: 30b vs others (sign test, two-sided, normal approx)
def paired(a, b):
    d = [agg[(i["id"], a)]["meaning"] - agg[(i["id"], b)]["meaning"] for i in items]
    w = sum(x > 0 for x in d); l = sum(x < 0 for x in d); n = w + l
    z = (w - n / 2) / math.sqrt(n / 4) if n else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"a": a, "b": b, "a_better": w, "b_better": l, "ties": len(d) - n, "mean_diff": round(st.mean(d), 3), "sign_test_p": float(f"{p:.2g}")}
pairs = [paired("qwen3-vl:30b-a3b-instruct", "exaone3.5:latest"), paired("qwen3-vl:30b-a3b-instruct", "qwen3-vl:8b-instruct"),
         paired("exaone3.5:latest", "qwen3-vl:8b-instruct")]
# judge agreement on booleans
agree = {}
for k in ("names_kept", "cjk_or_garble"):
    ss = list(per.values())
    agree[k] = round(sum(len({bool(s[k]) for s in x}) == 1 for x in ss) / len(ss), 3)
agree["meaning_within_1"] = round(sum(max(s["meaning"] for s in x) - min(s["meaning"] for s in x) <= 1 for x in per.values()) / len(per), 3)
by_kind = {}
for kd in sorted({i["context"]["kind_heuristic"] for i in items}):
    its = [i for i in items if i["context"]["kind_heuristic"] == kd]
    by_kind[kd] = {"n": len(its), **{m: round(st.mean(agg[(i["id"], m)]["meaning"] for i in its), 3) for m in M}}
json.dump({"summary": summ, "paired_meaning": pairs, "judge_agreement": agree, "meaning_by_kind": by_kind,
           "per_item": [{"id": i["id"], **{m: agg[(i["id"], m)] for m in M}} for i in items]},
          open(f"{S}/agg.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({"summary": summ, "paired_meaning": pairs, "judge_agreement": agree, "meaning_by_kind": by_kind}, indent=1))
