# BH Memory Generator 3, Phase A

This patch constructs strictly causal exponential self-history candidates on each black-hole track. It uses the well-formed ordering coordinate frozen in `v2.0.0`, normalizes time within track, excludes the current and all future samples from each candidate memory value, and assigns chronological train/validation/test partitions.

The output is a candidate coordinate, not an admitted HRSM memory result. Physical timescale, independent-axis, host-regulation, and confirmatory-memory claims remain prohibited.

Run from the repository root:

```bash
unzip -o BH_Memory_Generator3_PhaseA_v1_0.zip -d .
python -m pytest tests/test_bh_memory_generator3_phase_a.py -q
time python scripts/44_build_bh_memory_generator3_candidates.py \
  --config configs/protocol/bh_memory_generator3_phase_a_v1.yaml \
  --repo-root .
git diff --check
```

Phase B is authorized only when the emitted verdict reports finite coordinates, no excluded tracks, and `phase_b_predictive_comparison_authorized: true`.
