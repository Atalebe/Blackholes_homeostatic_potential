import csv
import json
import subprocess
import sys
from pathlib import Path

import yaml


SCRIPT = Path(__file__).parents[1] / "scripts" / "40_execute_bh_protocol_claim_audit.py"
CONFIG = Path(__file__).parents[1] / "configs" / "protocol" / "bh_claim_audit_v1.yaml"


def test_audit_refuses_missing_positive_evidence(tmp_path):
    (tmp_path / "configs" / "protocol").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "outputs" / "tables").mkdir(parents=True)
    (tmp_path / "outputs" / "catalogs").mkdir(parents=True)
    (tmp_path / "outputs" / "logs").mkdir(parents=True)
    (tmp_path / "paper").mkdir()
    cfg = yaml.safe_load(CONFIG.read_text())
    (tmp_path / "configs" / "protocol" / "bh_claim_audit_v1.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(tmp_path)], check=True)
    rows = list(csv.DictReader((tmp_path / "outputs/protocol/audits/bh_claim_inventory.csv").open()))
    c05 = next(r for r in rows if r["claim_id"] == "BH-C05")
    assert c05["audit_verdict"] == "blocked_missing_artifact"
    contract = json.loads((tmp_path / "outputs/protocol/adjudication/bh_closing_contract.json").read_text())
    assert len(contract["claims"]) == 14
    manifest = json.loads((tmp_path / "outputs/protocol/manifests/bh_claim_audit_manifest.json").read_text())
    assert manifest["policy"]["scientific_inputs_modified"] is False
    assert manifest["policy"]["memory_activated"] is False


def test_numeric_quarantine_detects_extreme_non_id_value(tmp_path):
    for rel in ["configs/protocol", "scripts", "src/core", "outputs/tables", "outputs/catalogs", "outputs/logs", "paper"]:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(CONFIG.read_text())
    (tmp_path / "configs/protocol/bh_claim_audit_v1.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (tmp_path / "outputs/tables/gama_sigma_audit.csv").write_text("variant,slope,bh_id\nsigma,-5.59e11,112236586657\n")
    subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(tmp_path)], check=True)
    rows = list(csv.DictReader((tmp_path / "outputs/protocol/audits/bh_numeric_quarantine.csv").open()))
    assert any(r["column"] == "slope" and r["reason"] == "extreme_absolute_value" for r in rows)
    assert not any(r["column"] == "bh_id" for r in rows)

