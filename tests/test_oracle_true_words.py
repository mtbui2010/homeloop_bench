"""Privileged planners choose a delivery mode from the words the user said, not from the ASR output."""
from types import SimpleNamespace as NS

from homeloop_bench.planners.oracle import heard_text


def _env(said, heard, events=()):
    return NS(task_text=heard, user=NS(request=said), _events=list(events))


def test_heard_text_is_the_asr_text_by_default():
    e = _env("bring me the cup in my hand", "bring me the cup")
    assert heard_text(e) == "bring me the cup"


def test_privileged_planners_read_what_the_user_said_plus_corrections():
    e = _env("bring me the cup in my hand", "bring me the cup", [{"kind": "correction", "text": "the red one"}])
    assert heard_text(e, true_words=True) == "bring me the cup in my hand the red one"


def test_without_a_recorded_request_the_heard_text_is_used():
    e = _env(None, "bring me the cup")
    assert heard_text(e, true_words=True) == "bring me the cup"
