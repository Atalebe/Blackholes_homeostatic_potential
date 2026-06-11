# Reproducibility Guide

This repository is archived in Zenodo at:

DOI: 10.5281/zenodo.20635940

The archival manuscript-supporting snapshot corresponds to Git tag:

bh-homeostasis-manuscript-snapshot-2026-05-29-v2

## Scope of the archived snapshot

The repository preserves the code, configurations, frozen manuscript-supporting tables, and figure files used for:

1. Reduced Tier 1 black hole HRSM time-domain analyses in simulation
2. Residence-based black hole ripeness and contextual maturity ranking
3. Source-driven GAMA observational black hole branches
4. Full MaNGA IFU extraction, state-vector construction, and robustness analyses
5. Manuscript-supporting LaTeX materials

## Repository structure

- `src/sim/`  
  Simulation-side scripts for time-domain black hole extraction, ripeness construction, variance scaling, robust dispersion tests, and ranking diagnostics

- `src/obs/`  
  Observational-side scripts for GAMA and MaNGA rebuilding, IFU extraction, robustness tests, and comparison analyses

- `configs/`  
  YAML configuration files controlling each run

- `outputs/tables/`  
  Frozen manuscript-facing summary tables retained in the archival snapshot

- `outputs/figures/`  
  Frozen manuscript-facing figures retained in the archival snapshot

- `paper/manuscript_snapshot/`  
  Manuscript-supporting LaTeX source snapshot

## Execution pattern

Runs are configuration-driven and are launched through:

python run_script.py <script_path> <config_path>

## Main manuscript-facing branches

### 1. Simulation time-domain HRSM branch
This branch provides the main simulation-level result:
- reduced Tier 1 black hole state-vector construction
- residence-based ripeness
- robust dispersion scaling
- contextual ripeness ranking
- anomaly and stable-core diagnostics

### 2. GAMA observational branch
This branch provides the main observational anchor:
- source-driven OIIIB plus D4000-offset branch
- source-driven OIIIB plus class-relative sigma-offset branch
- corrected null and stress tests
- leave-one-mass-bin-out sign-stability checks

### 3. Full MaNGA IFU branch
This branch serves as the main survey-scale robustness and portability test:
- near-full MAPS extraction
- age-conditioned and kinematic-conditioned IFU state vectors
- extraction failure audit
- clean-only verification
- host-mass sensitivity tests

## Notes on upstream data

The repository does not fully redistribute all upstream survey and simulation products where file size, licensing, or archival practicality make that inappropriate. Instead, it preserves:
- the code
- run configurations
- provenance paths
- frozen manuscript-supporting outputs
- reference links or local reference structure where applicable

This means the archival snapshot is intended as a reproducibility package for the manuscript-level analyses rather than as a complete mirror of every upstream raw dataset.

## Citation

If you use this archive, cite both:

- the Zenodo DOI: 10.5281/zenodo.20635940
- the GitHub repository: Atalebe/Blackholes_homeostatic_potential
