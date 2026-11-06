"""Clause attachment of a "tell P ... and bring me X" request (lab round 3, H3).

In "Could you tell Grandpa to come to the kitchen and bring me the red book?" the fetch clause can be read as part of
the message ("... to come to the kitchen and bring me the red book"). A request that tells a message first and
fetches an object second therefore keeps the message and the fetch clause in different sentences, or puts the fetch
first. :func:`attach_problem` is the deterministic check (templates, paraphrases in both languages); the EN
paraphrase judge also asks the attachment question (``judge_attach`` in ``paraphrase.py``).

The fetch clause is found by its verb after the message verb in the same sentence. A text with no message verb is not
judged (``None``)."""

from __future__ import annotations

import re

TELL = {
    "en": re.compile(r"\b(tell|tells|let\b[^.?!]{0,40}?\bknow|wake|remind|ask|inform|notify|say to)\b", re.I),
    "ko": re.compile(r"(전해|전하|말해|말씀|알려|깨워|이야기|얘기|일러)"),
}
FAMILIES = ("compound.tell_fetch",)      # "tell P <message> and bring me X": no order word keeps the clauses apart
# a verb that fetches or hands over an object (the fetch clause; "get up" / "take his medicine" belong to messages); Korean 드리- is left out (말씀드려 is a message verb)
FETCH = {
    "en": re.compile(r"\b(bring|brings|fetch|grab|hand|deliver)\b|\bget(?= (?:me|us|him|her|them|the|my|his|our|a|an|some|that|this)\b)", re.I),
    "ko": re.compile(r"(가져|갖다|갖고|건네|쥐여)"),
}
DOCK_GROUP = re.compile(r"charg|dock|충전")


def message_before_fetch(rec: dict) -> bool:
    """A message subtask comes before an object-delivery subtask (the order of the subtasks is the order of the
    clauses in the template)."""
    msg = fetch = None
    for i, st in enumerate(rec.get("subtasks") or []):
        for a in (st.get("goal") or {}).get("all") or []:
            if a.get("pred") == "said_to" and msg is None:
                msg = i
            if a.get("pred") in ("delivered", "held_by") and fetch is None:
                fetch = i
    return msg is not None and fetch is not None and msg < fetch


def attach_problem(rec: dict, lang: str, text: str | None = None) -> str | None:
    """None when the message and the fetch clause are apart; else why not. ``text`` defaults to the record's text.
    Only a tell_fetch record (message before fetch) is judged. The fetch clause is read by its verb, not by the object
    name: a message may name the object's word ("someone is on the phone" while the robot fetches the phone)."""
    if (rec.get("meta") or {}).get("family") not in FAMILIES or not message_before_fetch(rec):
        return None
    text = rec["text"][lang] if text is None else text
    m = TELL[lang].search(text)
    if m is None:
        return None
    p = m.end()
    for f in FETCH[lang].finditer(text, p):
        if not re.search(r"[.?!]", text[p:f.start()]):
            return f"fetch verb {f.group(0)!r} inside the sentence of the message"
    return None
