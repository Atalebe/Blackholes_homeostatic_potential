# Black-hole Tier 1 validity freeze candidate v1.2

This incremental bundle assumes the v1 claim audit is already installed. It does not fit
recoverability or memory. It audits the exact Tier 1 layer first. Version 1.2 compares row,
left-endpoint, and right-endpoint residence, forces non-negative slopes to fail the declared
one-sided negative test, and recognizes TNG-style identifier aliases without inferring joins.

Run:

```bash
python -m pytest tests/test_bh_tier1_validity_repair.py -q
python scripts/41_execute_bh_tier1_validity_repair.py \
  --config configs/protocol/bh_tier1_validity_repair_v1.yaml \
  --repo-root .
```

The runner emits exact formula concordance, an irregular-cadence black-box probe of the
residence implementation, H/S same-channel dependence, a frozen post-hoc sensitivity grid,
formal GAMA sigma quarantine, an identifier inventory and only an explicit dependence bridge.
It never assumes that `bh_id == subhalo_id`.
