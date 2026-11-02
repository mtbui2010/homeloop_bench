from homeloop_bench.gen import paraphrase as P

REC_EN = {"id": "hl-dev-000001", "split": "dev", "n_subtasks": 1, "structure": "single",
          "text": {"en": "Could you bring me the red mug from the counter?", "ko": "조리대에 있는 빨간 머그컵 좀 갖다줄래요?"},
          "meta": {"entities": {"en": [["red mug"], ["counter", "kitchen counter"]],
                                "ko": [["빨간 머그컵"], ["조리대", "싱크대"]]}}}


def test_accepts_a_real_paraphrase():
    assert P.filters(REC_EN, "en", "Can you grab the red mug off the counter and bring it over to me?") == []
    assert P.filters(REC_EN, "ko", "조리대 위에 빨간 머그컵 있죠? 그거 저한테 가져다줄 수 있어요?") == []


def test_rejects_unchanged_and_ending_only():
    assert "unchanged" in P.filters(REC_EN, "en", "Could you bring me the red mug from the counter?")
    why = P.filters(REC_EN, "ko", "조리대에 있는 빨간 머그컵 좀 갖다주세요.")
    assert "ending_only" in why or "too_similar" in why


def test_rejects_meaning_and_language_problems():
    assert "entity_missing" in P.filters(REC_EN, "en", "Can you grab the mug and bring it to me?")
    assert "new_colour" in P.filters(REC_EN, "en", "Can you get the red mug and the blue towel off the counter for me?")
    assert "new_entity" in P.filters(REC_EN, "en", "Grab the red mug from the counter and the remote, please.")
    assert "foreign_script" in P.filters(REC_EN, "ko", "조리대那儿 빨간 머그컵 좀 가져다주세요.")
    assert "ko_banmal" in P.filters(REC_EN, "ko", "조리대에 있는 빨간 머그컵 좀 가져와.") or \
        "R-g" in P.filters(REC_EN, "ko", "조리대에 있는 빨간 머그컵 좀 가져와.")
    assert "ko_imperative_question" in P.filters(REC_EN, "ko", "조리대 위의 빨간 머그컵을 저한테 가져다주세요?")
    assert "ko_no_request" in P.filters(REC_EN, "ko", "조리대에 빨간 머그컵이 있어요.")
    assert "instruction_leak" in P.filters(REC_EN, "en", "Paraphrase: grab the red mug from the counter for me.")


def test_english_entities_match_whole_words():
    rec = dict(REC_EN, meta={"entities": {"en": [["red mug"], ["counter"], ["no", "wait"]], "ko": []}})
    assert "entity_missing" in P.filters(rec, "en", "Bring the red mug from the counter, not the shelf, okay?")


def test_prompt_and_sha_are_deterministic():
    inp = {"text": "Could you open the fridge?", "keep": ["fridge"], "compound": False}
    p1, p2 = P.build_prompt("para_en", inp), P.build_prompt("para_en", dict(inp))
    assert p1 == p2 and "Could you open the fridge?" in p1
    assert P.request_sha("m", {"seed": 1}, p1) == P.request_sha("m", {"seed": 1}, p2)
    assert P.request_sha("m", {"seed": 1}, p1) != P.request_sha("m", {"seed": 2}, p1)


def test_offline_llm_never_calls_out(tmp_path):
    llm = P.LLM("http://127.0.0.1:9", "m", P.Cache(tmp_path / "c.jsonl"), offline=True)
    text, sha = llm.ask("para_en", {"text": "x", "keep": []}, 1)
    assert text == "" and llm.n_miss == 1 and len(sha) == 64


def test_cache_roundtrip(tmp_path):
    c = P.Cache(tmp_path / "c.jsonl")
    llm = P.LLM("http://127.0.0.1:9", "m", c, offline=True)
    inp = {"text": "Could you open the fridge?", "keep": []}
    opts = dict(P.OPTIONS["para"], seed=5)
    sha = P.request_sha("m", opts, P.build_prompt("para_en", inp))
    c.put({"sha": sha, "model": "m", "options": opts, "task": "para_en", "prompt_version": P.PROMPT_VERSION,
           "input": inp, "response": '{"text": "Can you open up the fridge for me?"}'})
    assert llm.ask("para_en", inp, 5)[0] == "Can you open up the fridge for me?"
    assert P.Cache(tmp_path / "c.jsonl").d[sha]["task"] == "para_en"


# ── Korean filters added for USER_FEEDBACK 9 ──────────────────────────────────────────────────────────
REC_KO = {"id": "hl-dev-000002", "split": "dev", "n_subtasks": 1, "structure": "single",
          "text": {"en": "Could you take the towel to my husband?", "ko": "남편한테 수건 좀 갖다줄래요?"},
          "meta": {"entities": {"en": [["towel"], ["husband"]], "ko": [["수건"], ["남편"]]}}}


def test_ko_wrong_honorifics_are_rejected():
    assert "ko_wrong_honorific" in P.filters(REC_KO, "ko", "남편님께 수건 좀 가져다주실 수 있을까요?")
    assert "ko_wrong_honorific" in P.filters(REC_KO, "ko", "남편께 가셔서 수건 좀 전해 주실래요?")


def test_ko_polite_question_requests_are_requests():
    assert P.filters(REC_KO, "ko", "수건 좀 남편에게 가져다줄 수 있을까요?") == []


def test_ko_banmal_sentence_endings():
    assert P.ko_banmal_end("수건 좀 갖다줘.")
    assert P.ko_banmal_end("남편한테 수건 좀 갖다줄래?")
    assert not P.ko_banmal_end("남편한테 수건 좀 갖다줄래요?")
    assert not P.ko_banmal_end("아니.")                     # an interjection in a self-correction
    assert "ko_banmal" in P.filters(REC_KO, "ko", "추워요. 남편한테 수건 좀 가져다줘.")


def test_ko_banmal_does_not_flag_gajyeowa_ju():
    assert "ko_banmal" not in P.filters(REC_KO, "ko", "수건 좀 남편한테 가져와 주실래요?")


def test_judge_ko_needs_all_four_answers():
    assert P._judge_ko('{"same_meaning": true, "robot_asked": true, "haeyo": true, "fluent": true}') == "same"
    assert P._judge_ko('{"same_meaning": true, "robot_asked": true, "haeyo": false, "fluent": true}') == "not_haeyo"
    assert P._judge_ko('{"same_meaning": false}') == "not_same_meaning"
    assert P._judge_ko("no json") == "unparsed"


def test_korean_prompt_asks_for_haeyo_and_keeps_entities():
    pr = P.build_prompt("para_ko2", {"text": "수건 좀 갖다줄래요?", "keep": ["수건"], "compound": False})
    assert "해요체" in pr and '["수건"]' in pr and "님" in pr
    jp = P.build_prompt("judge_ko", {"a": "수건 좀 갖다줄래요?", "text": "수건 좀 가져다줄 수 있어요?"})
    assert "same_meaning" in jp and "haeyo" in jp and "robot_asked" in jp and "fluent" in jp


class _Fake:
    """A scripted LLM client: answers by task, records the calls."""

    def __init__(self, answers):
        self.answers, self.n_calls, self.n_miss, self.calls = answers, 0, 0, []

    def ask(self, task, inp, seed):
        self.calls.append(task)
        self.n_calls += 1
        a = self.answers[task]
        return (a(inp) if callable(a) else a), f"sha-{task}-{len(self.calls)}"


def test_korean_rounds_accept_only_filtered_and_judged(monkeypatch):
    from homeloop_bench.gen.dedup import NearDupIndex
    monkeypatch.setattr(P, "realism_ok", lambda rec, lang, text: [])   # REC_KO has no world
    seen = {"en": {"x"}, "ko": {"y"}}
    writer = _Fake({"para_ko2": "수건 좀 남편에게 가져다줄 수 있을까요?"})
    judge = _Fake({"judge_ko": "same", "back": "Could you bring the towel to my husband?"})
    batch = lambda client, jobs: [client.ask(*j) for j in jobs]  # noqa: E731
    acc, rej, asked = P._rounds("ko", [REC_KO], writer, judge, judge, 2, seen, NearDupIndex(), 2026, batch,
                                lambda m: None)
    assert list(acc) == [REC_KO["id"]] and asked == 1 and acc[REC_KO["id"]]["chrf"] >= P.CHRF_MIN
    bad = _Fake({"judge_ko": "not_same_meaning", "back": "Could you bring the towel to my husband?"})
    acc, rej, asked = P._rounds("ko", [REC_KO], writer, bad, bad, 2, {"en": set(), "ko": set()}, NearDupIndex(),
                                2026, batch, lambda m: None)
    assert not acc and rej["judge_not_same_meaning"] == 2 and asked == 2


def test_realism_filter_rejects_a_broken_self_correction():
    from homeloop_bench.tasks import read_records
    rec = next(r for r in read_records("dev") if r["structure"] == "correction"
               and any("first" in (s.get("correction") or {}) for s in r["subtasks"]))
    tpl = (rec["meta"].get("template_text") or rec["text"])
    assert P.realism_ok(dict(rec, text=dict(tpl)), "en", tpl["en"]) == []
    c = next(s["correction"] for s in rec["subtasks"] if "first" in (s.get("correction") or {}))
    from homeloop_bench.gen.realism import world
    from homeloop_bench.gen.lexicon import Lex
    lex = Lex(world(rec))
    broken = tpl["en"].replace(lex.color(c["first"], "en"), "@@").replace(lex.color(c["final"], "en"),
                                                                            lex.color(c["first"], "en")).replace("@@", lex.color(c["final"], "en"))
    assert P.realism_ok(dict(rec, text=dict(tpl)), "en", broken)
