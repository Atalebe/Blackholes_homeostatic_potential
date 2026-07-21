# BH Memory Generator 3 final closure

This bundle closes the frozen 2,000-replicate primary confirmation without
editing its raw output. It verifies all frozen hashes, computes the
null-adjusted order excess, writes a final adjudication, and generates Protocol
Entry 006 plus manuscript-safe claim text.

Run from the repository root:

```bash
python -m pytest tests/test_bh_memory_final_closure.py -q

python scripts/55_close_bh_memory_generator3_primary_confirmation.py \
  --repo-root .

mkdir -p paper/protocol_audit/build
pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory paper/protocol_audit/build \
  paper/protocol_audit/bh_memory_generator3_primary_confirmation_entry_006.tex

pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory paper/protocol_audit/build \
  paper/protocol_audit/bh_memory_generator3_primary_confirmation_entry_006.tex

git diff --check
```

The raw runner verdict is preserved unchanged. Its stale invitation to run a
2,000-replicate confirmation is superseded only in the final adjudication.
