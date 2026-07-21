#!/usr/bin/env python3
"""Make Phase C honor an optional declared baseline_continuous list."""
from pathlib import Path


path = Path("scripts/46_screen_bh_memory_generator3_selection_null.py")
text = path.read_text(encoding="utf-8")
old = '    base = [c["current"], c["delta_time"]]\n'
new = '    base = list(c.get("baseline_continuous", [c["current"], c["delta_time"]]))\n'
if text.count(old) == 1:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"[ok] enabled declared Phase C baseline in {path}")
elif text.count(new) == 1:
    print(f"[ok] declared Phase C baseline already enabled in {path}")
else:
    raise RuntimeError("Expected exactly one Phase C baseline assignment")
