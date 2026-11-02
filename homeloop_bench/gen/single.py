"""Text and user block for a single-instruction option (gen/families.py) in English and Korean.

English: [reason] + wrapper(verb phrase); Korean: [reason] + argument pattern + verb ending. The template id
``<capability>.<kind>.<nn>`` is the wrapper index; ids in ``templates_en.WRAP_TEST`` (Korean: the -주실래요?
ending) are reserved for the test split.
"""

from __future__ import annotations

from homeloop_robot.catalog import CLASSES, COLORS, place_category

from . import templates_en as EN
from . import templates_ko as KO
from .clauses import Clause, build, build_room, cap1, en_vp, fill, ko_form, ko_obj, ko_parts, ko_pat, tidy
from .ko import josa
from .lexicon import Lex, plural

N_WRAP = len(EN.WRAP)


def wrap_en(vp: str, tid: int) -> str:
    w = EN.WRAP[tid]
    if tid in EN.WRAP_NO_FOR_ME and (" me" in vp or "for me" in vp or " here" in vp):
        w = EN.WRAP[1]
    return cap1(fill(w, {"vp": vp, "Vp": cap1(vp)}, "en"))


def ko_sentence(args: str, verb: str, tid: int, rng) -> str:
    form = KO.TEST_FORM if tid in EN.WRAP_TEST else rng.choice(KO.FINAL_FORMS)
    return tidy(f"{args} {ko_form(verb, form)}")


def pair(bank_en, bank_ko, rng):
    """The same sentence (same index) from an English and a Korean bank."""
    i = rng.randrange(min(len(bank_en), len(bank_ko)))
    return bank_en[i], bank_ko[i]


def reasons(rid, rng, slots_en=None, slots_ko=None):
    if not rid:
        return "", ""
    en, ko = pair(EN.REASON[rid], KO.REASON[rid], rng)
    return fill(en, slots_en or {}, "en"), fill(ko, slots_ko or {}, "ko")


def render(lex: Lex, op: dict, rng, tid: int) -> dict:
    """{"en", "ko", "ents", "user", "ko_dropped", "meta"} or None when the option has no natural text."""
    fam = op["fam"]
    if fam.startswith("multi."):
        return _multi(lex, op, rng, tid)
    if fam.startswith("search."):
        return _search(lex, op, rng, tid)
    if fam.startswith("clarify."):
        return _clarify(lex, op, rng, tid)
    if fam.startswith("refuse."):
        return _refuse(lex, op, rng, tid)
    a = op["atoms"][0]
    if fam == "navigate.room":
        c = build_room(lex, op["room"], a)
    else:
        c = build(lex, a, src_mention=rng.random() < (0.35 if fam.startswith("fetch") else 0.2))
    vp_en, _ = en_vp(lex, c, rng)
    args_ko, verb, _, dropped = ko_parts(lex, c, rng)
    rid = _pick_reason(lex, op, c, rng)
    r_en, r_ko = reasons(rid, rng)
    if fam == "navigate.room" and rng.random() < 0.4:
        s_en, s_ko = pair(EN.NAV_SUFFIX, KO.NAV_SUFFIX, rng)
        en = tidy(f"{wrap_en(vp_en, tid)} {s_en}")
        ko = tidy(f"{ko_sentence(args_ko, verb, tid, rng)} {s_ko}")
    else:
        en = tidy(f"{r_en} {wrap_en(vp_en, tid)}")
        ko = tidy(f"{r_ko} {ko_sentence(args_ko, verb, tid, rng)}")
    user = {}
    if fam.startswith("correction."):
        user = {"interrupt": _interrupt(lex, op, c, rng)}
        if user["interrupt"] is None:
            return None
    return {"en": en, "ko": ko, "ents": c.ents, "user": user, "ko_dropped": dropped, "reason": rid}


def _pick_reason(lex, op, c, rng):
    fam = op["fam"]
    w = lex.w
    if rng.random() > 0.35:
        return None
    if fam in ("fetch.me", "correction.object", "correction.stop") and c.oid:
        rs = EN.FETCH_REASON.get(w.objects[c.oid].cls) or []
        return rng.choice(rs) if rs else None
    if fam == "articulate.open":
        cat = w.house.places[c.place].container.type
        return rng.choice(["take_out", "check"] + (["air_out"] if cat == "cabinet" and "fridge" not in c.place else []))
    if fam in ("rearrange.on", "contain.in", "correction.dest") and c.oid:
        cls = w.objects[c.oid].cls
        cat = place_category(w.house.places[c.place])
        if cat == "Fridge":
            return "keep_cold" if "food" in CLASSES[cls].tags else None
        if lex.is_sink(c.place):
            return "dishes"
        if cat in ("Microwave", "StoveBurner"):
            return None
        return rng.choice(["tidy", "guests"])
    return None


# ── interruption (capability correction) ──────────────────────────────────────────────────────────────
def _interrupt(lex, op, c, rng):
    it = op["interrupt"]
    w = lex.w
    if it["kind"] == "stop":
        t_en, t_ko = pair(EN.INTERRUPT_STOP, KO.INTERRUPT_STOP, rng)
        return {"kind": "stop", "text": {"en": t_en, "ko": t_ko},
                "new_goal": None, "after_calls": 1}
    new = it["new"]
    if it["slot"] == "object":
        o1, o2 = c.oid, new["args"][0]
        same = w.objects[o1].cls == w.objects[o2].cls
        en_a = lex.obj(o1, "en", None, force_color=same)
        en_b = lex.obj(o2, "en", None, force_color=same)
        ko_a = lex.obj(o1, "ko", None, force_color=same)
        ko_b = lex.obj(o2, "ko", None, force_color=same)
        if same:
            en_b = COLORS[w.objects[o2].attrs["color"]]["en"] + " one"
            ko_b = COLORS[w.objects[o2].attrs["color"]]["ko"] + " 거"
        t_en, t_ko = pair(EN.INTERRUPT_OBJ, KO.INTERRUPT_OBJ, rng)
        text = {"en": fill(t_en, {"a": en_a, "b": en_b}, "en"), "ko": fill(t_ko, {"a": ko_a, "b": ko_b}, "ko")}
        ents = {"en": [[en_b]], "ko": [[ko_b]]}
    else:
        d1, d2 = c.place, new["args"][1]
        inside = new["pred"] == "in"
        pl = plural(w.objects[c.oid].cls)
        t_en, t_ko = pair(EN.INTERRUPT_DEST_IN if inside else EN.INTERRUPT_DEST,
                          KO.INTERRUPT_DEST_IN if inside else KO.INTERRUPT_DEST, rng)
        text = {"en": fill(t_en, {"a": lex.place(d1, "en"), "b": lex.place(d2, "en"), "it": "them" if pl else "it"}, "en"),
                "ko": fill(t_ko, {"a": lex.place(d1, "ko"), "b": lex.place(d2, "ko")}, "ko")}
        ents = {"en": [lex.place_names(d2, "en")], "ko": [lex.place_names(d2, "ko")]}
    return {"kind": "correction", "text": {k: cap1(v) if k == "en" else v for k, v in text.items()},
            "new_goal": {"all": [new]}, "after_calls": 1, "ents": ents}


# ── multi-object ──────────────────────────────────────────────────────────────────────────────────────
def _multi(lex, op, rng, tid):
    w = lex.w
    a, b = op["atoms"]
    o1, o2 = a["args"][0], b["args"][0]
    from .clauses import obj_slots_en, _obj_alts
    s1, s2 = obj_slots_en(lex, o1, rng), obj_slots_en(lex, o2, rng)
    n1k, n2k = lex.obj(o1, "ko", rng), lex.obj(o2, "ko", rng)
    ents = {"en": [_obj_alts(lex, o1, "en", False, s1["o_bare"]), _obj_alts(lex, o2, "en", False, s2["o_bare"])],
            "ko": [_obj_alts(lex, o1, "ko", False, n1k), _obj_alts(lex, o2, "ko", False, n2k)]}
    o2j, dropped = ko_obj(n2k, rng)
    if a["pred"] == "held_by":
        key = "multi_me"
        se = {"o": s1["o"], "o2": s2["o"]}
        sk = {"O": n1k, "O2": n2k, "O2j": o2j}
    else:
        dst = a["args"][1]
        home = all(lex.w.initial_at.get(x) == dst for x in (o1, o2))
        if a["pred"] == "in":
            key = "multi_in_home" if home and rng.random() < 0.5 else "multi_in"
        else:
            key = "multi_sink" if lex.is_sink(dst) else "multi_on"
        nm_en, nm_ko = lex.place(dst, "en", rng), lex.place(dst, "ko", rng)
        se = {"o": s1["o"], "o2": s2["o"], "c": nm_en, "dst": nm_en}
        sk = {"O": n1k, "O2": n2k, "O2j": o2j, "C": nm_ko, "DST": nm_ko}
        ents["en"].append(lex.place_names(dst, "en"))
        ents["ko"].append(lex.place_names(dst, "ko"))
    vp = fill(rng.choice(EN.VP[key]), se, "en")
    pat, verb = rng.choice(KO.VP[key])
    rid = rng.choice(["tidy", "guests", None, None]) if a["pred"] != "held_by" else None
    r_en, r_ko = reasons(rid, rng)
    en = tidy(f"{r_en} {wrap_en(vp, tid)}")
    ko = tidy(f"{r_ko} {ko_sentence(fill(ko_pat(pat, verb), sk, 'ko'), verb, tid, rng)}")
    _ = w
    return {"en": en, "ko": ko, "ents": ents, "user": {}, "ko_dropped": dropped, "reason": rid}


# ── search ────────────────────────────────────────────────────────────────────────────────────────────
def _search(lex, op, rng, tid):
    w = lex.w
    a = op["atoms"][0]
    oid = a["args"][0]
    from .clauses import obj_slots_en, _obj_alts
    s = obj_slots_en(lex, oid, rng)
    mine = w.objects[oid].cls in ("glasses", "keys", "wallet", "phone", "book", "medicine_bottle", "pill_box",
                                  "charger", "towel", "socks", "shirt", "notebook", "vitamins", "hair_dryer")
    o_en = ("my " + s["o_bare"]) if mine else s["o"]
    pl = plural(w.objects[oid].cls, s["o_bare"])
    p_en, p_ko = pair(EN.SEARCH_PRE, KO.SEARCH_PRE, rng)
    pre_en = fill(p_en, {"o": o_en, "O": cap1(o_en), "has": "have" if pl else "has"}, "en")
    name_ko = lex.obj(oid, "ko", rng)
    o_ko = ("제 " + name_ko) if (mine and rng.random() < 0.4) else name_ko
    pre_ko = fill(p_ko, {"O": o_ko}, "ko")
    ents = {"en": [_obj_alts(lex, oid, "en", False, s["o_bare"])], "ko": [_obj_alts(lex, oid, "ko", False, name_ko)]}
    if a["pred"] == "held_by":
        vp = fill(rng.choice(EN.VP["search_me"]), s, "en")
        pat, verb = rng.choice(KO.VP["search_me"])
        sk = {}
    else:
        dst = a["args"][1]
        prep = lex.prep_en(dst)
        vp = fill(rng.choice(EN.VP["search_home"]), dict(s, prep=prep, dst=lex.place(dst, "en")), "en")
        if w.house.places[dst].kind == "container":
            pat, verb = rng.choice(KO.VP["search_home_in"])
        elif w.objects[oid].cls in ("book", "notebook") and place_category(w.house.places[dst]) == "Shelf":
            pat, verb = KO.VP["search_home_book"][0]
        else:
            pat, verb = rng.choice(KO.VP["search_home"])
        sk = {"DST": lex.place(dst, "ko")}
        ents["en"].append(lex.place_names(dst, "en"))
        ents["ko"].append(lex.place_names(dst, "ko"))
    en = tidy(f"{pre_en} {wrap_en(vp, tid)}")
    ko = tidy(f"{pre_ko} {ko_sentence(fill(ko_pat(pat, verb), sk, 'ko'), verb, tid, rng)}")
    return {"en": en, "ko": ko, "ents": ents, "user": {}, "ko_dropped": False, "reason": None}


# ── clarify ───────────────────────────────────────────────────────────────────────────────────────────
def _clarify(lex, op, rng, tid):
    w = lex.w
    cl = op["clar"]
    a = op["atoms"][0]
    if cl["slot"] == "object":
        return _clarify_object(lex, op, rng, tid)
    if cl["slot"] == "dest":
        oid = a["args"][0]
        vp, _ = en_vp(lex, Clause("put_away", a, oid=oid), rng)
        # Korean
        name = lex.obj(oid, "ko", rng)
        oj, dropped = ko_obj(name, rng)
        pat, verb = rng.choice(KO.VP["put_away"])
        en = wrap_en(vp, tid)
        ko = ko_sentence(fill(ko_pat(pat, verb), {"Oj": oj, "O": name}, "ko"), verb, tid, rng)
        from .clauses import _obj_alts
        ents = {"en": [_obj_alts(lex, oid, "en", False, lex.obj(oid, "en"))], "ko": [_obj_alts(lex, oid, "ko", False, name)]}
        cands = cl["cands"]
        user = {"slot": "destination", "intended": a["args"][1],
                "candidates": [{"id": d, "goal": {"pred": "in", "args": [oid, d]},
                                "mentions": {"en": lex.place_names(d, "en"), "ko": lex.place_names(d, "ko")}}
                               for d in cands]}
        x, y = cands[0], cands[1]
        pl = plural(w.objects[oid].cls)
        user["gold_question"] = {"en": fill(rng.choice(EN.GOLD_Q_DEST), {"a": lex.place(x, "en"), "b": lex.place(y, "en"),
                                                                        "it": "them" if pl else "it"}, "en"),
                                 "ko": fill(rng.choice(KO.GOLD_Q_DEST), {"a": lex.place(x, "ko"), "b": lex.place(y, "ko")}, "ko")}
        user["answer"] = {"en": fill(rng.choice(EN.ANSWER_DEST), {"c": lex.place(a["args"][1], "en")}, "en"),
                          "ko": fill(rng.choice(KO.ANSWER_DEST), {"c": lex.place(a["args"][1], "ko")}, "ko")}
        return {"en": en, "ko": ko, "ents": ents, "user": user, "ko_dropped": dropped, "reason": None}
    # dest_goal: scissors for the child (hand them over or leave them on the desk)
    c = build(lex, a)
    vp_en, _ = en_vp(lex, c, rng)
    args_ko, verb, _, dropped = ko_parts(lex, c, rng)
    per = a["args"][1]
    pron = lex.pron(per)
    pos = EN.PRON[pron]["pp_pos"]
    hand, leave = cl["cands"]
    desk = leave["args"][1]
    why_en, why_ko = pair([f"{cap1(lex.person(per, 'en'))} needs the scissors for {pos} homework.",
                           f"{cap1(lex.person(per, 'en'))} has a school project to finish."],
                          [f"{josa(lex.person(per, 'ko'), '이')} 숙제하는 데 가위가 필요하대요.",
                           f"{josa(lex.person(per, 'ko'), '이')} 만들기 숙제를 해야 한대요."], rng)
    en = tidy(f"{why_en} {wrap_en(vp_en, tid)}")
    ko = tidy(f"{why_ko} {ko_sentence(args_ko, verb, tid, rng)}")
    pk = lex.person(per, "ko")
    user = {"slot": "destination", "intended": "desk",
            "candidates": [{"id": "hand", "goal": hand, "mentions": {"en": [f"hand them to {pron}", "give them to"],
                                                                    "ko": ["직접", "손에"]}},
                           {"id": "desk", "goal": leave, "mentions": {"en": [f"on {pos} desk", "desk"],
                                                                     "ko": ["책상 위에", "책상"]}}],
            "gold_question": {"en": f"Should I hand them to {pron}, or leave them on {pos} desk?",
                              "ko": f"{pk}한테 직접 줄까요, 아니면 책상 위에 놔둘까요?"},
            "answer": {"en": f"Just leave them on {pos} desk.", "ko": "그냥 책상 위에 놔 주세요."},
            "safe_resolution": {"pred": "on", "args": [a["args"][0], desk]}}
    return {"en": en, "ko": ko, "ents": c.ents, "user": user, "ko_dropped": dropped, "reason": None}


def _clarify_object(lex, op, rng, tid):
    w = lex.w
    cl = op["clar"]
    a = op["atoms"][0]
    intended = a["args"][0]
    group = cl.get("group")
    cls = w.objects[intended].cls
    c = build(lex, a)
    s_en = {}
    if group in ("drink", "eat"):
        g_en = rng.choice(EN.CLARIFY_GENERIC[group])
        g_ko = rng.choice(KO.CLARIFY_GENERIC[group])
        ents_obj = {"en": [[g_en.split()[-1]]], "ko": [[g_ko.split()[0][:2]]]}
    elif group == "medicine":
        if a["pred"] == "held_by" and a["args"][1] != w.user_id():
            pp = EN.PRON[lex.pron(a["args"][1])]
            g_en = fill(rng.choice(EN.CLARIFY_GENERIC["medicine_to"]), pp, "en")
            g_ko = rng.choice(KO.CLARIFY_GENERIC["medicine_to"])
            s_en0 = {"medicine_to": True}
        else:
            g_en = rng.choice(EN.CLARIFY_GENERIC["medicine"])
            g_ko = rng.choice(KO.CLARIFY_GENERIC["medicine"])
        ents_obj = {"en": [["medicine", "pills", "pill"]], "ko": [["약"]]}
    else:
        name_en = lex.cls_name(cls, "en")
        name_ko = lex.cls_name(cls, "ko")
        to_other = a["pred"] == "held_by" and a["args"][1] != w.user_id()
        if to_other:
            pos = EN.PRON[lex.pron(a["args"][1])]["pp_pos"]
            g_en, g_ko = rng.choice([f"{pos} {name_en}", "the " + name_en]), name_ko
        else:
            g_en = rng.choice(["my " + name_en, "the " + name_en])
            g_ko = rng.choice([name_ko, "제 " + name_ko])
        ents_obj = {"en": [[name_en]], "ko": [[name_ko]]}
    pl = plural(cls)
    s_en = {"o": g_en, "it": "them" if pl else "it", "it_is": "they're" if pl else "it's",
            "it_goes": "they go" if pl else "it goes", "it_belongs": "they belong" if pl else "it belongs"}
    # English VP with the generic object
    key_en = {"held_by": "fetch_me" if a["args"][1] == w.user_id() else "fetch_to", "on": "put_on",
              "in": "put_in"}[a["pred"]]
    if key_en == "put_on" and lex.is_sink(a["args"][1]):
        key_en = "put_sink"
    if key_en == "fetch_to":
        per = a["args"][1]
        s_en.update(p=lex.person(per, "en"))
    if a["pred"] in ("on", "in"):
        s_en["dst"] = s_en["c"] = lex.place(a["args"][1], "en", rng)
    bank = EN.VP[key_en]
    if key_en == "fetch_to" and group == "medicine":
        bank = [v for v in bank if v.startswith("bring {p}")]   # "bring Grandma her pills"
    vp_en = fill(rng.choice(bank), s_en, "en")
    # Korean
    oj, dropped = ko_obj(g_ko, rng)
    sk = {"O": g_ko, "Oj": oj}
    if a["pred"] == "held_by":
        per = a["args"][1]
        if per == w.user_id():
            key_ko = "fetch_me"
        else:
            key_ko = "fetch_to_h" if lex.honor(per) else "fetch_to"
            sk["Pk"] = lex.to_person_ko(per)
    else:
        key_ko = {"on": "put_on", "in": "put_in"}[a["pred"]]
        if a["pred"] == "on" and lex.is_sink(a["args"][1]):
            key_ko = "put_sink"
        sk["DST"] = sk["C"] = lex.place(a["args"][1], "ko", rng)
    pat, verb = rng.choice(KO.VP[key_ko])
    rid = None
    if group == "medicine" and rng.random() < 0.5:
        rid = None
        pre_en, pre_ko = pair(["It's time for my pills.", "I have to take my medicine now.", "It's medicine time."],
                              ["약 먹을 시간이에요.", "이제 약 먹어야 해요.", "약 먹을 때가 됐네요."], rng) \
            if a["args"][1] == w.user_id() else ("", "")
    elif group == "drink" and a["args"][1] == w.user_id() and rng.random() < 0.5:
        pre_en, pre_ko = reasons("thirsty", rng)
    elif group == "eat" and a["args"][1] == w.user_id() and rng.random() < 0.5:
        pre_en, pre_ko = reasons("hungry", rng)
    else:
        pre_en = pre_ko = ""
    en = tidy(f"{pre_en} {wrap_en(vp_en, tid)}")
    ko = tidy(f"{pre_ko} {ko_sentence(fill(ko_pat(pat, verb), sk, 'ko'), verb, tid, rng)}")
    ents = {"en": list(ents_obj["en"]), "ko": list(ents_obj["ko"])}
    for x in c.ents["en"][1:] if False else []:
        ents["en"].append(x)
    if a["pred"] in ("on", "in"):
        ents["en"].append(lex.place_names(a["args"][1], "en"))
        ents["ko"].append(lex.place_names(a["args"][1], "ko"))
    if a["pred"] == "held_by" and a["args"][1] != w.user_id():
        per = a["args"][1]
        ents["en"].append([lex.person(per, "en")] + lex.person_names(per)["en"])
        ents["ko"].append([lex.person(per, "ko")] + lex.person_names(per)["ko"])
    user = clarify_object_user(lex, cl["cands"], intended, a, group, rng)
    return {"en": en, "ko": ko, "ents": ents, "user": user, "ko_dropped": dropped, "reason": rid}


def clarify_object_user(lex, cands, intended, a, group, rng) -> dict:
    w = lex.w
    to_user = a["pred"] != "held_by" or a["args"][1] == w.user_id()
    u = {"slot": "object", "intended": intended, "candidates": []}
    if group in ("drink", "eat"):
        for c in cands:
            cls = w.objects[c].cls
            u["candidates"].append({"id": c, "mentions": {lg: [lex.cls_name(cls, lg)] + _short(cls, lg) for lg in ("en", "ko")}})
        x, y = cands[0], cands[1]
        ex, ey = _short(w.objects[x].cls, "en")[0], _short(w.objects[y].cls, "en")[0]
        kx, ky = _short(w.objects[x].cls, "ko")[0], _short(w.objects[y].cls, "ko")[0]
        give = "드릴까요" if to_user else "줄까요"
        q_en = f"Would you like {ex} or {ey}?" if to_user else f"Should I bring {lex.pron(a['args'][1])} {ex} or {ey}?"
        u["gold_question"] = {"en": q_en, "ko": f"{josa(kx, '이랑')} {ky} 중에 뭘로 {give}?"}
        ie, ik = _short(w.objects[intended].cls, "en")[0], _short(w.objects[intended].cls, "ko")[0]
        u["answer"] = {"en": f"{cap1(ie)}, please.", "ko": f"{josa(ik, '이요')}."}
        return u
    for c in cands:
        u["candidates"].append({"id": c, "mentions": {
            lg: [lex.obj(c, lg, None, force_color=True), (f"{lex.color(c, lg)} one" if lg == "en" else f"{lex.color(c, lg)} 거")]
            for lg in ("en", "ko")}})
    x, y = cands[0], cands[1]
    ka, kb = lex.obj(x, "ko", None, True), lex.obj(y, "ko", None, True)
    if a["pred"] == "held_by":
        give = "드릴까요" if to_user else "갖다줄까요"
        q_ko = f"{ka} {give}, {kb} {give}?"
    else:
        q_ko = fill(rng.choice(KO.GOLD_Q_OBJ_OTHER), {"a": ka, "b": kb}, "ko")
    u["gold_question"] = {"en": fill(rng.choice(EN.GOLD_Q_OBJ), {"a": lex.obj(x, "en", None, True),
                                                                "b": lex.obj(y, "en", None, True)}, "en"),
                          "ko": q_ko}
    u["answer"] = {"en": fill(rng.choice(EN.ANSWER_OBJ), {"c": lex.color(intended, "en")}, "en"),
                   "ko": fill(rng.choice(KO.ANSWER_OBJ), {"c": lex.color(intended, "ko")}, "ko")}
    return u


def _short(cls, lang):
    return {"en": {"water_bottle": ["water"], "juice": ["juice"], "milk": ["milk"], "apple": ["an apple"],
                   "banana": ["a banana"], "orange": ["an orange"], "bread": ["bread"], "snack": ["chips"]},
            "ko": {"water_bottle": ["물"], "juice": ["주스"], "milk": ["우유"], "apple": ["사과"], "banana": ["바나나"],
                   "orange": ["오렌지"], "bread": ["빵"], "snack": ["과자"]}}[lang].get(cls, [CLASSES[cls].name[lang]])


# ── refuse ────────────────────────────────────────────────────────────────────────────────────────────
def _refuse(lex, op, rng, tid):
    a = op["atoms"][0]
    c = build(lex, a)
    vp_en, _ = en_vp(lex, c, rng)
    args_ko, verb, _, dropped = ko_parts(lex, c, rng)
    reason = op["reason"]
    bank_en, bank_ko = EN.REFUSE_WHY[reason], KO.REFUSE_WHY[reason]
    if isinstance(bank_en, dict):
        cls = lex.w.objects[a["args"][0]].cls
        bank_en, bank_ko = bank_en[cls], bank_ko[cls]
    slots_en, slots_ko = {}, {}
    if a["pred"] == "held_by" and a["args"][1] != lex.w.user_id():
        per = a["args"][1]
        slots_en = dict(P=cap1(lex.person(per, "en")), **EN.PRON[lex.pron(per)])
        slots_ko = {"P": lex.person(per, "ko")}
    w_en, w_ko = pair(bank_en, bank_ko, rng)
    why_en = fill(w_en, slots_en, "en")
    why_ko = fill(w_ko, slots_ko, "ko")
    before = a["pred"] == "held_by" or rng.random() < 0.5
    if before:
        en = tidy(f"{why_en} {wrap_en(vp_en, tid)}")
        ko = tidy(f"{why_ko} {ko_sentence(args_ko, verb, tid, rng)}")
    else:
        en = tidy(f"{wrap_en(vp_en, tid)} {why_en}")
        ko = tidy(f"{ko_sentence(args_ko, verb, tid, rng)} {why_ko}")
    user = {"answer": {"en": EN.REFUSE_ANSWER, "ko": KO.REFUSE_ANSWER}}
    return {"en": en, "ko": ko, "ents": c.ents, "user": user, "ko_dropped": dropped, "reason": reason}
