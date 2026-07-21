# BH Memory Generator 3 primary confirmation freeze

This bundle records the post-hoc AR(3) scale disposition and freezes the
unchanged primary design for one 2,000-replicate selection-aware confirmation.
The primary baseline remains `[lambda_current, delta_u_next]`; the grid remains
`[0.02, 0.05, 0.10, 0.20]`.

Run from the repository root:

```bash
python -m pytest tests/test_bh_memory_primary_confirmation_freeze.py -q

python scripts/52_record_bh_memory_diagnostic_disposition.py --repo-root .

python scripts/53_freeze_bh_memory_primary_confirmation.py --repo-root .

time python scripts/54_run_frozen_bh_memory_primary_confirmation.py \
  --repo-root .

git diff --check
```

Script 54 verifies every frozen hash immediately before invoking the existing
Phase C runner. Any change to the candidate, configs, model code, null code,
runner, or prerequisite verdicts aborts the run.

This confirmation can license only a small order-dependent self-history gain in
the TNG lambda-track branch. It cannot admit HRSM M or license a physical
timescale, independent H/S coordinates, or host-galaxy regulation.
