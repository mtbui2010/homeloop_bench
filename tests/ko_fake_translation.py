"""A fake Korean translation for robot_agent's AssistLoop._in_lang under --llm fake (test helper).

The fake LLM robot_agent talks to under --llm fake (planners/robot_agent_fake.FakeUnderstandLLM) echoes the English
of a translation request, so a Korean user would hear English, which it does not follow (homeloop_robot
docs/user_model.md "Heard-text check"). This translates SAGE's English templates into Korean, naming places and
people by the house's Korean names; any other text stays English (as when the translation call fails)."""
import re

HEAD = "Translate into natural spoken Korean. Keep it short and polite. Output only the translation:\n"
# robot_agent SAGE-v2 (translate_model): "Translate into natural polite spoken Korean, ... Output only the translation:\n"
HEAD_RX = re.compile(r"^Translate into natural[^\n]*Korean[^\n]*Output only the translation:\n")


def _place(world, key: str) -> str:
    from homeloop_robot import dialog as D
    key = key.strip().replace(" in the ", "@")
    return D.place_name(world, key, "ko") if world is not None and key in world.house.places else key


def _person(world, pid: str) -> str:
    from homeloop_robot import dialog as D
    return D.person_name(world, pid, "ko") if world is not None and pid in world.people else pid


def _step(world, s: str) -> str:
    m = re.match(r'^say "(?P<msg>[^"]+)"(?: to (?P<who>\w+))? in the (?P<place>\w+ in the \w+)$', s)
    if m:
        who = f"{_person(world, m['who'])}한테 " if m["who"] else ""
        return f'{_place(world, m["place"])}에서 {who}"{m["msg"]}"라고 말할게요'
    m = re.match(r"^go to the (?P<place>\w+ in the \w+)$", s)
    if m:
        return f"{_place(world, m['place'])}(으)로 갈게요"
    return "그렇게 할게요"


def translate(text: str, world=None) -> str:
    t = text.strip()
    pre = ""
    if t.startswith("Sorry, I didn't hear you. "):
        pre, t = "죄송해요, 잘 안 들렸어요. ", t[len("Sorry, I didn't hear you. "):]
    m = re.match(r"^I am not sure I understood \(.*?\)\. (?P<rest>.+)$", t)
    if m:
        pre, t = pre + "제가 잘 이해했는지 모르겠어요. ", m["rest"]
    if t == "Where are you? Which place should I bring it to?":
        return pre + "지금 어디 계세요? 어디로 가져다드릴까요?"
    if re.match(r"^(?:Sorry\. )?What should I do(?: exactly)?\?$", t):
        return pre + "죄송해요. 뭘 해야 할까요?"
    m = re.match(r"^I will (?P<steps>.+?)\. Is that right\?$", t)
    if m:
        steps = [_step(world, s) for s in re.split(r", then ", m["steps"])]
        return pre + ", 그리고 ".join(steps) + ". 맞죠?"
    return text                      # no translation: the English goes out as is


def install(monkeypatch, world=None):
    """Answer robot_agent's translation requests with :func:`translate` (``world``: the house, for its Korean
    place and person names)."""
    from homeloop_bench.planners import robot_agent_fake as fk
    chat = fk.FakeUnderstandLLM.chat

    def tr_chat(self, prompt="", format=None, **kw):
        m = HEAD_RX.match(str(prompt))
        if m:
            return translate(str(prompt)[m.end():], world)
        return chat(self, prompt, format, **kw)
    monkeypatch.setattr(fk.FakeUnderstandLLM, "chat", tr_chat)
