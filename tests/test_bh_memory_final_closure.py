import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/55_close_bh_memory_generator3_primary_confirmation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_closure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sha256_is_stable(tmp_path):
    module = load_module()
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert module.sha256(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_latex_escape_handles_protocol_identifiers():
    module = load_module()
    assert module.latex_escape("a_b%") == r"a\_b\%"
