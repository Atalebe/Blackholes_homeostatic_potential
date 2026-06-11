# src/sim/59_bh_ripeness_regime_plots.py
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.config import load_yaml

cfg = load_yaml(CONFIG_PATH)

catalog_csv = Path(cfg["data"]["catalog_csv"])
stable_core_csv = Path(cfg["data"]["stable_core_csv"])
settlement_csv = Path(cfg["data"]["settlement_summary_csv"])

out_dir = Path(cfg["outputs"]["figure_dir"])
out_dir.mkdir(parents=True, exist_ok=True)

focus_ids = set(str(x) for x in cfg["focus"].get("bh_ids", []))

df = pd.read_csv(catalog_csv).copy()
df["bh_id"] = df["bh_id"].astype(str)

stable = pd.read_csv(stable_core_csv).copy() if stable_core_csv.exists() else pd.DataFrame(columns=["bh_id"])
stable_ids = set(stable["bh_id"].astype(str).tolist())

settlement = pd.read_csv(settlement_csv).copy() if settlement_csv.exists() else pd.DataFrame()

# 1. Score vs residence, stable core highlighted
plt.figure(figsize=(7, 5))
base = df[~df["bh_id"].isin(stable_ids)]
core = df[df["bh_id"].isin(stable_ids)]
focus = df[df["bh_id"].isin(focus_ids)]

plt.scatter(base["ripeness_bh"], base["ripeness_score"], alpha=0.35, label="all others")
if len(core):
    plt.scatter(core["ripeness_bh"], core["ripeness_score"], s=60, marker="o", label="stable core")
if len(focus):
    plt.scatter(focus["ripeness_bh"], focus["ripeness_score"], s=80, marker="x", label="focus outliers")

for _, r in focus.iterrows():
    plt.annotate(r["bh_id"], (r["ripeness_bh"], r["ripeness_score"]), fontsize=7)

plt.xlabel("ripeness_bh")
plt.ylabel("ripeness_score")
plt.title("BH ripeness score versus residence ripeness")
plt.legend()
plt.tight_layout()
plt.savefig(out_dir / "bh_ripeness_score_vs_residence.png", dpi=300)
plt.close()

# 2. Quietness vs settlement with focus labels
plt.figure(figsize=(7, 5))
plt.scatter(df["quiet_hat"], df["settlement_hat"], alpha=0.35, label="all BH")
if len(core):
    cc = df[df["bh_id"].isin(stable_ids)]
    plt.scatter(cc["quiet_hat"], cc["settlement_hat"], s=60, label="stable core")
if len(focus):
    plt.scatter(focus["quiet_hat"], focus["settlement_hat"], s=80, marker="x", label="focus outliers")
    for _, r in focus.iterrows():
        plt.annotate(r["bh_id"], (r["quiet_hat"], r["settlement_hat"]), fontsize=7)

plt.axhline(0.0)
plt.axvline(0.0)
plt.xlabel("quiet_hat")
plt.ylabel("settlement_hat")
plt.title("Quietness and settlement regime map")
plt.legend()
plt.tight_layout()
plt.savefig(out_dir / "bh_ripeness_quiet_vs_settlement.png", dpi=300)
plt.close()

# 3. Rank stability comparison for stable core
if len(stable):
    plt.figure(figsize=(7, 5))
    plt.scatter(stable["rank_full"], stable["rank_drop_quiet"], label="drop_quiet")
    plt.scatter(stable["rank_full"], stable["rank_drop_persistence"], label="drop_persistence")
    lim = max(
        stable["rank_full"].max(),
        stable["rank_drop_quiet"].max(),
        stable["rank_drop_persistence"].max(),
    ) + 1
    plt.plot([0, lim], [0, lim])
    plt.xlabel("rank_full")
    plt.ylabel("variant rank")
    plt.title("Stable core rank preservation")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "bh_ripeness_stable_core_rank_preservation.png", dpi=300)
    plt.close()

# 4. Settlement penalty histogram with focus markers
plt.figure(figsize=(7, 5))
plt.hist(df["settlement_hat"].dropna(), bins=40)
if len(focus):
    ymin, ymax = plt.ylim()
    for _, r in focus.iterrows():
        plt.axvline(r["settlement_hat"], linestyle="--")
        plt.text(r["settlement_hat"], 0.9 * ymax, r["bh_id"], rotation=90, fontsize=7)
plt.xlabel("settlement_hat")
plt.ylabel("count")
plt.title("Settlement penalty distribution")
plt.tight_layout()
plt.savefig(out_dir / "bh_ripeness_settlement_hat_distribution.png", dpi=300)
plt.close()

print(f"[ok] wrote figures to {out_dir}")
