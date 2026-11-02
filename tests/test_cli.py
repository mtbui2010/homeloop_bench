"""homeloop-bench CLI (docs/cli.md)."""

import json
import subprocess
import sys

from fixtures import fixture_tasks, write_jsonl
from homeloop_bench.cli import main

NAMES = ("oracle", "naive", "saycan_like", "inner_monologue_like", "progprompt_like", "knowno_like",
         "robot_agent:sage", "robot_agent:grace", "robot_agent:llm_direct")


def test_planners_listing(capsys):
    assert main(["planners"]) == 0
    lines = capsys.readouterr().out.splitlines()
    for n in NAMES:
        assert any(l.split("\t")[0] == n for l in lines), n


def test_listing_does_not_import_robot_agent():
    code = ("import sys; from homeloop_bench.cli import main; main(['planners']); "
            "print('RA' if 'robot_agent' in sys.modules else 'NO')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip().splitlines()[-1] == "NO"


def test_run_compare_report_show(tmp_path, capsys):
    f = write_jsonl(tmp_path / "t.jsonl", fixture_tasks())
    a, b = tmp_path / "a", tmp_path / "b"
    assert main(["run", "--planner", "oracle", "--split", "dev", "--profile", "real", "--seeds", "2",
                 "--lang", "en", "--tasks", f, "--out", str(a)]) == 0
    assert main(["run", "--planner", "naive", "--split", "dev", "--limit", "10", "--profile", "real",
                 "--seeds", "2", "--tasks", f, "--out", str(b)]) == 0
    for d in (a, b):
        for x in ("episodes.jsonl", "summary.json", "report.md"):
            assert (d / x).exists()
    capsys.readouterr()
    assert main(["compare", str(a), str(b), "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["n_pairs"] == 20 and r["method"] in ("exact_binomial", "chi2_continuity")
    assert main(["compare", str(a), str(b)]) == 0
    assert "McNemar" in capsys.readouterr().out
    assert main(["report", str(a)]) == 0
    assert "## Headline" in capsys.readouterr().out
    assert main(["show", "fx-clar-000", "--tasks", f]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "clarify"


def test_llm_planner_needs_llm(tmp_path, capsys):
    f = write_jsonl(tmp_path / "t.jsonl", fixture_tasks()[:2])
    assert main(["run", "--planner", "progprompt_like", "--tasks", f, "--out", str(tmp_path / "x")]) == 2
    assert "needs --llm URL or --llm fake" in capsys.readouterr().err
    assert main(["run", "--planner", "progprompt_like", "--llm", "fake", "--tasks", f,
                 "--out", str(tmp_path / "y")]) == 0
    s = json.loads((tmp_path / "y" / "summary.json").read_text())
    assert s["config"]["llm"] == "fake" and s["config"]["model"] is None


def test_live_smoke_dir_names(tmp_path):
    f = write_jsonl(tmp_path / "t.jsonl", fixture_tasks()[:3])
    assert main(["live-smoke", "--llm", "fake", "--model", "qwen3-vl:8b-instruct", "--limit", "3",
                 "--planners", "progprompt_like", "--langs", "en,ko", "--root", str(tmp_path / "ls"),
                 "--tasks", f]) == 0
    for lang in ("en", "ko"):
        assert (tmp_path / "ls" / f"progprompt_like__qwen3-vl:8b-instruct__{lang}" / "summary.json").exists()
