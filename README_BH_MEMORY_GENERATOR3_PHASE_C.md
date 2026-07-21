# BH Memory Generator 3, Phase C screen

Phase C permutes the sampled `lambda_current` sequence within each track and chronological split, then regenerates every causal memory kernel from the surrogate sequence. It never permutes finished memory columns. Current state, next-state target, timestamps, and track identity remain fixed. Tau selection is repeated inside every null replicate.

The 200-replicate screen uses a deterministic cap of 100,000 rows per chronological split. Passing authorizes a frozen 2,000-replicate confirmation. It does not admit HRSM M.

```bash
unzip -o BH_Memory_Generator3_PhaseC_v1_0.zip -d .
python -m pytest tests/test_bh_memory_generator3_phase_c.py -q
time python scripts/46_screen_bh_memory_generator3_selection_null.py \
  --config configs/protocol/bh_memory_generator3_phase_c_v1.yaml \
  --repo-root .
git diff --check
```
