# BH Memory Generator 3, Phase B

Phase B compares a current-state Markov baseline with memory-augmented models. Kernel scale is chosen exclusively on the chronological validation partition. Both models are then refit on train plus validation and evaluated once on the untouched test partition.

The preregistered screen requires at least 1% pooled test-RMSE improvement and a 95% track-bootstrap lower bound above zero. Passing authorizes Phase C selection-within-null testing; it does not admit HRSM M.

```bash
unzip -o BH_Memory_Generator3_PhaseB_v1_0.zip -d .
python -m pytest tests/test_bh_memory_generator3_phase_b.py -q
time python scripts/45_screen_bh_memory_generator3_predictive_gain.py \
  --config configs/protocol/bh_memory_generator3_phase_b_v1.yaml \
  --repo-root .
git diff --check
```
