# BH Time-Track Integrity Freeze v1.0

This patch closes the monotonicity gap identified after FREEZE-002. It audits timestamps in original parquet row order before any sorting, independently inspects `compute_residence_fraction` for internal sorting, and checks the full track-window contract.

Blocking checks:

- finite timestamps;
- no duplicate `(bh_id, t)` pairs;
- either monotonic file order or internal sorting in the residence function;
- finite `phi_bh` and window bounds;
- strict `phi_window_low < phi_window_high`;
- exact agreement of `in_window_t` with inclusive window membership.

Recorded interpretation exposures:

- within-track irregular cadence;
- short-span tracks;
- sparse tracks;
- file-order versus canonically sorted right-endpoint residence differences.

Install and run from the repository root:

```bash
unzip -o BH_Time_Track_Integrity_Freeze_v1_0.zip -d .
python -m pytest tests/test_bh_time_track_integrity_freeze.py -q
python scripts/42_freeze_bh_time_track_integrity.py \
  --config configs/protocol/bh_time_track_integrity_freeze_v1.yaml \
  --repo-root .
git diff --check
```

Exit status `0` authorizes the pinned right-interval residence implementation and Generator 3 ordering only. Exit status `2` freezes a blocking failure. Neither status authorizes a memory, physical-timescale, independent-axis, or host-regulation claim.
