"""Translation A/B (data/quality/translate_ab.json): run with the A/B directory as argument, e.g.
``python tools/translate_ab/relat.py data/quality/translate_ab``."""
import json, sys, time, urllib.request, statistics as st
S = sys.argv[1]; M = "qwen3-vl:30b-a3b-instruct"
items = [json.loads(l) for l in open(f"{S}/items.jsonl")][::8]
lat = []; same = 0
for i in items:
    body = {"model": M, "messages": [{"role": "user", "content": "Translate into natural spoken Korean. Keep it short and polite. Output only the translation:\n" + i["en"]}],
            "stream": False, "options": {"temperature": 0, "seed": 0, "num_ctx": 8192}, "keep_alive": "2m"}
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11536/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=120))
    lat.append(time.time() - t); same += r["message"]["content"].strip() == i["out_raw"][M].strip()
lat.sort()
print(json.dumps({"n": len(lat), "latency_mean_s": round(st.mean(lat), 3), "latency_p50_s": round(st.median(lat), 3),
                  "latency_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 3), "same_output_as_step1": same}))
