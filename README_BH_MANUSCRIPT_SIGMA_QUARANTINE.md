# BH manuscript sigma-claim quarantine

This patch executes the binding FREEZE-002 manuscript action. It retains the bounded GAMA D4000 result, removes the positive sigma-star evidentiary chain, records formula-to-code nonconcordance, and replaces memory-adjacent regulation language with the admitted bounded, order-invariant interpretation.

Run from the repository root:

```bash
unzip -o BH_Manuscript_Sigma_Quarantine_v1_0.zip -d .
python -m pytest tests/test_bh_sigma_claim_quarantine.py -q
python scripts/43_apply_bh_sigma_claim_quarantine.py --check
python scripts/43_apply_bh_sigma_claim_quarantine.py
cd paper/manuscript_snapshot
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
cd ../..
git diff --check
git diff -- paper/manuscript_snapshot/main.tex
```

The script requires every expected source passage to occur exactly once and refuses partial surgery. It also refuses completion if listed positive sigma-star language remains.
