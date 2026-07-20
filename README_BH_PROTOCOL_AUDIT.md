# Black-hole protocol-aware claim audit

This bundle adds a deterministic, non-destructive audit to `bh_stability_vector_space`.
It does not rerun scientific analyses, change existing outputs, activate recoverability, or
fit a memory kernel. It inventories current evidence and emits manuscript claim caps.

## Install

Copy the bundle contents into the repository root, preserving directories.

## Run

```bash
python -m pytest tests/test_bh_protocol_claim_audit.py -q
python scripts/40_execute_bh_protocol_claim_audit.py \
  --config configs/protocol/bh_claim_audit_v1.yaml \
  --repo-root .
```

## Required outputs

- `outputs/protocol/audits/bh_claim_inventory.csv`
- `outputs/protocol/audits/bh_axis_definition_audit.csv`
- `outputs/protocol/audits/bh_formula_code_concordance.csv`
- `outputs/protocol/audits/bh_effective_unit_inventory.csv`
- `outputs/protocol/audits/bh_numeric_quarantine.csv`
- `outputs/protocol/audits/bh_claim_to_artifact_matrix.csv`
- `outputs/protocol/adjudication/bh_closing_contract.json`
- `outputs/protocol/adjudication/bh_claim_audit_summary.json`
- `outputs/protocol/manifests/bh_claim_audit_manifest.json`
- `paper/protocol_audit/bh_protocol_claim_audit.tex`

The audit deliberately sets `next_stage_authorized` to false. Human review must freeze
the validity remediations before the R/M generator ladder is added.
