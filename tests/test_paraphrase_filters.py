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
