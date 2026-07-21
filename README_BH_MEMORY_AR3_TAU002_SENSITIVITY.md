# BH Memory Generator 3: fixed tau=0.02 under AR(3)

This is a separate post-hoc scale-robustness diagnostic. It does not alter the
frozen primary design or the existing AR(3), tau=0.005 discovery result.

The baseline contains the current value, explicit lags 1--3, the next-step gap,
and the corresponding lag gaps. The candidate kernel grid is the singleton
`[0.02]`; consequently neither the observed fit nor any null replicate selects
among timescales. Phase C retains the validated within-track-and-split signal
permutation, causal-kernel recomputation, and full repeated fitting procedure.

Run from the repository root:

```bash
python -m pytest tests/test_bh_memory_ar3_tau002_sensitivity.py -q

python scripts/51_audit_bh_memory_ar3_tau002_sensitivity.py --repo-root .

time python scripts/45_screen_bh_memory_generator3_predictive_gain.py \
  --config configs/protocol/bh_memory_generator3_ar3_tau002_phase_b.yaml \
  --repo-root .

time python scripts/46_screen_bh_memory_generator3_selection_null.py \
  --config configs/protocol/bh_memory_generator3_ar3_tau002_phase_c.yaml \
  --repo-root .

git diff --check
```

The decisive diagnostic is `observed.fractional_test_improvement` minus
`null_mean_fractional_improvement`. Apply the declared 0.01 practical floor to
that null-adjusted excess, not to the raw observed improvement or the runner's
generic `screen_pass` field.

No result from this diagnostic authorizes a physical timescale, confirmatory
HRSM M, independent H/S axes, or host-regulation claim.
