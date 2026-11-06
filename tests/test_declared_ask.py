"""V2: a question that declares its qtype (robot_agent LocalText.ask) reaches the simulated user in structured form, so
the user does not fall back to reading the words (rules, then the classifier)."""
import types

import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.planners.robot_agent_adapter import declared_meaning, structured_asks  # noqa: E402
from robot_agent.core.planning import speech  # noqa: E402


def test_declared_meaning_of_the_inventory_question():
    q = speech.LocalText("q_which_known", {"object": "mug", "text": "the red mug or the blue mug"},
                         text="I know of more than one mug: the red mug or the blue mug. Which one do you mean?",
                         ask={"qtype": "which_object", "options": ["red mug", "blue mug"], "obj": "mug"})
    m = declared_meaning(q)
    assert m == {"qtype": "which_object", "options": ["red mug", "blue mug"], "obj": "mug", "template": ["declared"]}
    assert declared_meaning(speech.LocalText.join(speech.LocalText("q_silence"), q))["qtype"] == "which_object"
    assert declared_meaning(speech.LocalText("q_where_go")) is None and declared_meaning("a plain string") is None


def test_the_ask_wrapper_hands_the_declared_meaning_to_the_proxy():
    seen = []
    loop = types.SimpleNamespace(_ask_io=lambda question, node, log_fn, lang: seen.append(proxy.meaning) or "the red one")
    proxy = types.SimpleNamespace(meaning=None)
    assert structured_asks(loop, proxy)
    q = speech.LocalText("q_which_known", {"object": "mug", "text": "x"}, text="I know of more than one mug: x. Which one do you mean?",
                         ask={"qtype": "which_object", "options": ["a", "b"], "obj": "mug"})
    assert loop._ask_io(q, None, None, "en") == "the red one"
    assert seen[0]["qtype"] == "which_object" and seen[0]["options"] == ["a", "b"] and proxy.meaning is None
    # a template question is still derived from its words
    loop._ask_io(speech.LocalText("q_where_are_you"), None, None, "en")
    assert seen[1]["qtype"] == "where_are_you"
