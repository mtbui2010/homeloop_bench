"""Translation A/B (data/quality/translate_ab.json): run with the A/B directory as argument, e.g.
``python tools/translate_ab/match.py data/quality/translate_ab``."""
import json, glob, collections, sys
S = sys.argv[1]; B = "/home/trung/trung_workdir/homeloop_bench"
it = [json.loads(l) for l in open(f"{S}/items.jsonl")]
ws = lambda s: " ".join(str(s or "").split())
m = collections.defaultdict(set)
files = glob.glob(f"{B}/results/**/episodes.jsonl", recursive=True)
for f in files:
    if "sage" not in f or "__ko" not in f: continue
    for l in open(f):
        try: e = json.loads(l)
        except Exception: continue
        for c in e.get("calls", []):
            a = c.get("args") or {}
            for k in ("question", "text", "message"):
                if isinstance(a.get(k), str): m[ws(a[k])].add(e["task_id"])
        if isinstance(e.get("final_say"), str): m[ws(e["final_say"])].add(e["task_id"])
hit = {}
for i in it:
    k = ws(i["cached_8b"]); ids = m.get(k)
    if not ids:  # substring: a translation inside a joined utterance
        ids = set().union(*[v for t, v in m.items() if k and k in t]) if k else set()
    hit[i["id"]] = sorted(ids)
print(len(files), sum(1 for v in hit.values() if v), collections.Counter(len(v) for v in hit.values()))
miss = [i for i in it if not hit[i["id"]]]
print(collections.Counter(i["context"]["kind_heuristic"] for i in miss))
for i in miss[:5]: print(i["id"], i["context"]["kind_heuristic"], i["cached_8b"][:80], i["context"]["sources"][:1])
json.dump(hit, open(f"{S}/task_match.json", "w"), indent=0)
