import ast
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "43_apply_bh_sigma_claim_quarantine.py"


def test_script_parses():
    ast.parse(SCRIPT.read_text(encoding="utf-8"))


def test_binding_terms_present():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "fail\\\\_nonconcordant" in text
    assert "b=-0.7070" in text
    assert "PROHIBITED" in text
