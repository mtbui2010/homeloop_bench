"""Data licence statements match the data (LICENSE-DATA, NOTICE, README, datasheet)."""

from pathlib import Path

from homeloop_bench.tasks import read_records

ROOT = Path(__file__).resolve().parents[1]


def _exaone(split):
    return sum(1 for r in read_records(split) if (r.get("paraphrase_model") or {}).get("ko") == "exaone3.5:latest")


def test_exaone_part_and_training_warning():
    lic = (ROOT / "LICENSE-DATA").read_text(encoding="utf-8")
    part3 = lic[lic.index("3. Task data, EXAONE part"):]
    part2 = lic[lic.index("2. Task data, Apache"):lic.index("3. Task data, EXAONE part")]
    # the whole Korean cache (EXAONE rows and the Qwen rows whose input is EXAONE text) is in the EXAONE part
    assert "paraphrase_ko.jsonl" in part3 and "paraphrase_ko.jsonl" not in part2
    assert "Qwen3-VL models" not in part2
    assert "develop or improve other models" in part3 and "fine-tune" in part3
    assert "CC BY-NC 4.0 does not extend to the EXAONE Output" in part3
    n_train = _exaone("train")
    assert f"{n_train:,}" in part3
    assert f"{n_train + _exaone('dev') + _exaone('test'):,}" in part3
    for f in ("README.md", "NOTICE", "docs/datasheet.md"):
        t = (ROOT / f).read_text(encoding="utf-8")
        assert "fine-tun" in t and ("improve" in t or "develop" in t), f
        assert str(n_train) in t.replace(",", ""), f
