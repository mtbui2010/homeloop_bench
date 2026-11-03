"""Translation A/B: the simulated user's heard-text check (structured_mismatch) on each model's Korean. Argument: data/quality/translate_ab."""
import json, sys, collections
S = sys.argv[1]
from homeloop_robot import intent as _intent
from homeloop_robot.dialog import GoalView
from homeloop_robot.configs.ra_dialog import derive
from homeloop_bench.env import EpisodeEnv, task_dict
from homeloop_bench.tasks import load_split
from homeloop_bench.llm import CachedLLM, OllamaHTTP
from homeloop_bench.user_intent import IntentClassifier, PROMPT_VERSION
tasks = {}
for sp in ("train", "dev", "test"):
    for t in load_split(sp):
        tasks[str(task_dict(t)["id"])] = t
clf = IntentClassifier(CachedLLM(OllamaHTTP("http://127.0.0.1:11536", "qwen3-vl:8b-instruct"), f"{S}/user_intent_cache.jsonl"))
items = [json.loads(l) for l in open(f"{S}/items.jsonl")]
match = json.load(open(f"{S}/task_match.json"))
MODELS = ["qwen3-vl:8b-instruct", "exaone3.5:latest", "qwen3-vl:30b-a3b-instruct"]

def read(t, q, L, meaning):
    env = EpisodeEnv(t, "ideal", 0, L); u = env.user; u.classifier = clf
    gv = GoalView(u.world, u.wants, u.user_id, lambda pid: u.place_of(pid, 0.0)[0]) if u.wants else None
    kw = dict(knows_location=True, other_place=None, user_place=u.place_of(u.user_id, 0.0) if u.user_id else None,
              goal=gv, request=u.request, last_answer=None)
    u.last_reading = None
    c, path, qt = u._content(q, L, meaning, kw)
    return path, qt, c.kind

rows = []
for i in items:
    if i["context"]["kind_heuristic"] not in ("question", "read_back"):
        continue
    ids = match.get(i["id"]) or []
    if not ids:
        rows.append({"id": i["id"], "skip": "no_task"}); continue
    t = tasks[ids[0]]
    m = derive(i["en"])
    if m is not None and m.get("qtype") == "free":
        m = None
    if m is not None:
        ref = {"kind": "structured", "qtype": m["qtype"]}
    else:
        _p, qt_en, _k = read(t, i["en"], "en", None)
        if qt_en == "free":
            rows.append({"id": i["id"], "skip": "en_reads_free"}); continue
        ref = {"kind": "en_reading", "qtype": qt_en}
    r = {"id": i["id"], "task": ids[0], "ref": ref, "per_model": {}}
    for name, ko in [("cached_8b_run", i["cached_8b"])] + [(mm, i["out"][mm]) for mm in MODELS]:
        path, qt, kind = read(t, ko, "ko", m)
        mis = (path == "structured_mismatch") if m is not None else (qt != ref["qtype"] or not _intent.in_lang(ko, "ko"))
        r["per_model"][name] = {"path": path, "qtype": qt, "mismatch": bool(mis)}
    rows.append(r)
if clf.failed is not None:
    raise clf.failed
ok = [r for r in rows if "skip" not in r]
summ = {}
for name in ["cached_8b_run"] + MODELS:
    n = len(ok); k = sum(r["per_model"][name]["mismatch"] for r in ok)
    by = collections.Counter(r["ref"]["kind"] for r in ok if r["per_model"][name]["mismatch"])
    summ[name] = {"n": n, "mismatch_n": k, "mismatch_rate": round(k / n, 4), "by_ref": dict(by)}
out = {"n_asked_items": sum(1 for i in items if i["context"]["kind_heuristic"] in ("question", "read_back")),
       "n_scored": len(ok), "skipped": dict(collections.Counter(r["skip"] for r in rows if "skip" in r)),
       "n_ref": dict(collections.Counter(r["ref"]["kind"] for r in ok)),
       "classifier": {"model": "qwen3-vl:8b-instruct", "prompt_version": PROMPT_VERSION},
       "summary": summ, "rows": rows}
json.dump(out, open(f"{S}/mismatch.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("n_asked_items", "n_scored", "skipped", "n_ref", "summary")}, ensure_ascii=False, indent=1))
