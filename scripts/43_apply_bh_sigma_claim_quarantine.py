#!/usr/bin/env python3
"""Apply the binding FREEZE-002 sigma-claim quarantine to the BH manuscript."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


REPLACEMENTS = [
    (
        "The leading observational result comes from source-driven GAMA rebuilds in which throughput is traced by [OIII] emission and stability is defined through class-relative stellar-age and kinematic offsets; the strongest branch yields a negative variance slope under a corrected permutation null.",
        "A bounded observational support result comes from a source-driven GAMA rebuild in which throughput is traced by [OIII] emission and stability is defined through a class-relative D4000 offset; this branch yields a negative variance slope under a corrected permutation null. The candidate $\\sigma_\\star$ branch is quarantined because its implemented target is nonconcordant with the manuscript definition and carries no positive claim.",
    ),
    (
        "a demonstration that a reduced homeostatic vector space can separate robust time-domain regulation, source-driven observational analogues, and structurally interpretable maturity ranking within a single falsifiable framework.",
        "a demonstration that a reduced homeostatic vector space can separate bounded order-invariant stability geometry, source-driven observational analogues, and structurally interpretable maturity ranking within a single falsifiable framework.",
    ),
    (
        "Source-driven GAMA rebuilds provide the strongest current observational analogues, especially when stability is defined as a class-relative kinematic offset.",
        "The source-driven GAMA D4000 rebuild provides bounded, post-hoc observational support under a corrected permutation null.",
    ),
    (
        "and either a stellar-age stability coordinate,\n  \\begin{equation}\n  S_{\\rm D4000,offset}=-\\left|\\log_{10}({\\rm D4000N})-\\widetilde{\\log_{10}({\\rm D4000N})}_{\\rm class}\\right|,\n  \\end{equation}\n  or a kinematic stability coordinate,\n  \\begin{equation}\n  S_{\\sigma_\\star,offset}=-\\left|\\log_{10}(\\sigma_{\\star,\\rm corr})-\\widetilde{\\log_{10}(\\sigma_{\\star,\\rm corr})}_{\\rm class}\\right|.\n  \\end{equation}",
        "and a stellar-age stability coordinate,\n  \\begin{equation}\n  S_{\\rm D4000,offset}=-\\left|\\log_{10}({\\rm D4000N})-\\widetilde{\\log_{10}({\\rm D4000N})}_{\\rm class}\\right|.\n  \\end{equation}\n  A candidate kinematic branch was also audited. The implementation computed an $M_{\\rm BH}$--$\\sigma_\\star$ residual rather than the class-relative $\\sigma_\\star$ dispersion specified in the manuscript. The resulting formula verdict is \\texttt{fail\\_nonconcordant}; the branch is quarantined and is not used as positive evidence.",
    ),
    (
        "This quantity is central to the paper because it compresses time-domain regulation into a bounded statistic that is less sensitive to local trajectory shape than the per-track median potential.",
        "This quantity is central to the paper because it summarizes bounded occupancy geometry in a statistic that is less sensitive to local trajectory shape than the per-track median potential. Occupancy is order invariant and therefore does not itself establish retained memory.",
    ),
    (
        "\\subsection{GAMA Robustness}\n\n  After establishing the class-relative \\(\\sigma_\\star\\)-offset branch as the strongest observational black-hole variance-scaling signal in the current programme, the next step was to test whether the fitted negative slope could be driven by a single populated black-hole-mass bin.\n\n\n  The branch tested here is the source-driven GAMA realization with:\n  \\begin{equation}\n  H = \\log_{10}({\\rm OIIIB\\_FLUX}),\n  \\end{equation}\n  and\n  \\begin{equation}\n  S_{\\sigma_\\star,\\mathrm{offset}} =\n  -\\left|\n  \\log_{10}(\\sigma_{\\star,\\mathrm{corr}}) -\n  \\widetilde{\\log_{10}(\\sigma_{\\star,\\mathrm{corr}})}_{\\rm class}\n  \\right|.\n  \\end{equation}\n\n  The retained sample for this branch contained:\n  \\begin{equation}\n  N_{\\rm retained}=574,\n  \\end{equation}\n  distributed across three populated black-hole-mass bins with midpoints:\n  \\[\n  6.5,\\quad 7.5,\\quad 8.5.\n  \\]\n\n  The corresponding binned variances of \\(\\Phi_{\\rm BH}\\) were:\n  \\begin{align}\n  \\mathrm{Var}(\\Phi_{\\rm BH})_{6.5} &\\approx 1.118\\times10^{12},\\\\\n  \\mathrm{Var}(\\Phi_{\\rm BH})_{7.5} &\\approx 1.875\\times10^{11},\\\\\n  \\mathrm{Var}(\\Phi_{\\rm BH})_{8.5} &\\approx 4.30.\n  \\end{align}\n  The purpose of this stage was therefore not to replace the main permutation-calibrated fit, but to perform a direct leave-one-mass-bin-out stress test on the GAMA dynamical branch and verify whether the sign of the slope survives each bin removal.",
        "\\subsection{GAMA protocol disposition}\n\n  The source-driven GAMA D4000-offset branch is retained as bounded, post-hoc observational support. The candidate $\\sigma_\\star$ branch is not retained: formula-to-code concordance showed that the implementation computed an $M_{\\rm BH}$--$\\sigma_\\star$ residual while the manuscript specified a class-relative $\\sigma_\\star$ dispersion. Under the binding \\texttt{fail\\_nonconcordant} verdict, its numerical result, figure, and leave-one-bin-out analysis are quarantined and carry no positive manuscript claim.",
    ),
    (
        "The strongest observational result is the source-driven GAMA branch.",
        "The retained observational result is the bounded source-driven GAMA D4000 branch.",
    ),
    (
        "Source-driven GAMA static branch & Strongest observational analogue & Main observational support \\\\",
        "Source-driven GAMA D4000 branch & Bounded post-hoc analogue & Limited observational support \\\\",
    ),
    (
        "That distinction matters because it shows that regulated occupancy is more stable than regulated position under the present coordinate construction.",
        "That distinction shows that bounded occupancy has a more robust dispersion pattern than the track-median position under the present coordinate construction; because occupancy is order invariant, it is not evidence for memory.",
    ),
    (
        "\\section{Source-Driven Observational Results: GAMA as the Main Anchor}",
        "\\section{Source-Driven Observational Results: Bounded GAMA Support}",
    ),
    (
        "which remains stable under modest quality-cut and normalization changes and becomes even cleaner under tighter clipping. A second, stronger observational branch replaces the stellar-age stability coordinate with a class-relative stellar-velocity-dispersion offset. That branch retains $574$ galaxies and yields\n  \\begin{equation}\n  b=-2.0637, \\qquad p_{\\rm one\\text{-}sided,negative}=0.0015.\n  \\end{equation}",
        "which remains stable under modest quality-cut and normalization changes and becomes cleaner under tighter clipping. This result is retained as bounded, post-hoc observational support rather than as a universal law. The previously reported $\\sigma_\\star$ branch is excluded under the protocol concordance quarantine.",
    ),
    (
        "\\begin{figure}[H]\n  \\centering\n  \\begin{subfigure}{0.48\\textwidth}\n  \\centering\n  \\includegraphics[width=\\linewidth]{obs_gama_rebuilt_oiiibH_d4000S_variance_scaling.png}\n  \\caption{Maturation branch: $[\\mathrm{OIII}]$ + D4000 offset.}\n  \\end{subfigure}\n  \\hfill\n  \\begin{subfigure}{0.48\\textwidth}\n  \\centering\n  \\includegraphics[width=\\linewidth]{obs_gama_rebuilt_oiiibH_sigmaS_variance_scaling.png}\n  \\caption{Dynamical branch: $[\\mathrm{OIII}]$ + $\\sigma_\\star$ offset.}\n  \\end{subfigure}\n  \\caption{Source-driven GAMA variance scaling. The dynamical branch provides the strongest current observational black-hole signal in the project.}",
        "\\begin{figure}[H]\n  \\centering\n  \\includegraphics[width=0.72\\linewidth]{obs_gama_rebuilt_oiiibH_d4000S_variance_scaling.png}\n  \\caption{Source-driven GAMA variance scaling for the retained $[\\mathrm{OIII}]$ + D4000-offset branch. The result is bounded, post-hoc observational support.}",
    ),
    (
        "\\caption{Stress-tested source-driven GAMA branches preserved for manuscript extraction.}",
        "\\caption{Source-driven GAMA branches retained or used as negative controls after protocol adjudication.}",
    ),
    (
        "  $[\\mathrm{OIII}]$ + $\\sigma_\\star$ offset & 574 & $-2.0637$ & 0.0015 \\\\\n",
        "",
    ),
    (
        "\\subsection {Leave-one-bin-out results}\n  A leave-one-mass-bin-out stress test was then applied to the strongest source-driven GAMA branch, using the class-relative \\(\\sigma_\\star\\)-offset stability coordinate. The fitted variance slope remained negative in every refit: \\(b=-5.59\\times10^{11}\\) in the full three-bin run, \\(b=-1.87\\times10^{11}\\) after dropping the lowest populated bin, \\(b=-5.59\\times10^{11}\\) after dropping the middle bin, and \\(b=-9.30\\times10^{11}\\) after dropping the highest bin. Because each leave-one-out refit retains only two populated bins, these tests should be interpreted as directional sign-stability checks rather than standalone inferential fits. Nevertheless, they show that the negative GAMA trend is not carried by any single populated mass bin.\n\n  The full fit and leave-one-bin-out refits gave:\n\n  \\begin{center}\n  \\begin{tabular}{lccc}\n  \\toprule\n  Variant & Rows used & Bins used & Slope \\(b\\) \\\\\n  \\midrule\n  Full run & 574 & 3 & \\(-5.59\\times10^{11}\\) \\\\\n  Drop lowest bin (\\(6.5\\)) & 434 & 2 & \\(-1.87\\times10^{11}\\) \\\\\n  Drop middle bin (\\(7.5\\)) & 317 & 2 & \\(-5.59\\times10^{11}\\) \\\\\n  Drop highest bin (\\(8.5\\)) & 397 & 2 & \\(-9.30\\times10^{11}\\) \\\\\n  \\bottomrule\n  \\end{tabular}\n  \\end{center}\n\n  The crucial result is that the slope remained negative in every leave-one-bin-out refit.\n\n  Because the GAMA branch has only three populated black-hole-mass bins, each leave-one-bin-out refit necessarily reduces to a two-bin comparison.\n  These refits should therefore be interpreted as directional sign-stability checks rather than as independent inferential fits.\n\n  Within that limited but appropriate role, the result is clear:\n  the negative observational trend in the GAMA dynamical branch is not being carried by any single populated mass bin.\n  The sign remains negative whether the lowest, middle, or highest populated bin is removed.",
        "\\subsection{Quarantined GAMA kinematic branch}\n  The earlier $\\sigma_\\star$ leave-one-bin-out calculations are retained only in the audit archive. They test a nonconcordant target construction and therefore cannot rescue or support the quarantined positive claim.",
    ),
    (
        "Third, the observational picture is supportive but not uniform. GAMA supplies a meaningful source-driven analogue, especially in the dynamical branch built from class-relative velocity-dispersion offsets. Because that observational result still uses only three populated black-hole-mass bins, it should be read as strong support rather than as a finished observational law. Standard quality-cut, clipping, and coordinate-definition stress tests already show that the negative GAMA slope is not a trivial proxy artifact, but an explicit leave-one-mass-bin-out audit remains a natural next robustness step before any stronger observational generalization is claimed.",
        "Third, the observational picture is supportive but not uniform. GAMA supplies bounded, post-hoc support through the source-driven D4000-offset branch. The candidate velocity-dispersion branch is quarantined because the implemented target is nonconcordant with the manuscript formula; neither its slope nor its leave-one-bin-out analysis is used as positive evidence.",
    ),
    (
        "The strongest observational and simulation signals arise when stability is defined as distance from a class-conditioned equilibrium state, not as a raw absolute variable. That pattern recurs in the GAMA success branches, in the MaNGA IFU age/kinematic split, and in the settlement term of the ripeness module.",
        "The retained simulation result and bounded GAMA D4000 support use distance from a class-conditioned equilibrium state rather than a raw absolute variable. Related structure also appears in the MaNGA channel comparison and in the settlement term of the ripeness module, without implying a universal law.",
    ),
    (
        "The observational GAMA branches provide meaningful source-driven support, yet they rely on only three populated black-hole-mass bins. That is enough to establish a credible directional signal and to reject obvious pipeline artefacts, but not enough to exhaust all possible binning sensitivities.",
        "The retained observational GAMA D4000 branch provides bounded source-driven support but relies on only three populated black-hole-mass bins. It is therefore a limited directional result rather than a finished observational law; the nonconcordant $\\sigma_\\star$ branch is excluded from positive interpretation.",
    ),
    (
        "The strongest observational analogue currently comes from source-driven GAMA rebuilds, especially when stability is defined through a class-relative kinematic offset.",
        "A bounded observational analogue comes from the source-driven GAMA D4000-offset rebuild, while the candidate kinematic branch is quarantined as formula-to-code nonconcordant.",
    ),
    (
        "one credible source-driven observational anchor",
        "one bounded source-driven observational support branch",
    ),
]


PROHIBITED = [
    "strongest observational black-hole variance-scaling signal",
    "second, stronger observational branch",
    "dynamical branch provides the strongest",
    "negative observational trend in the GAMA dynamical branch",
    "especially in the dynamical branch built from class-relative velocity-dispersion offsets",
    "obs_gama_rebuilt_oiiibH_sigmaS_variance_scaling.png",
    "$[\\mathrm{OIII}]$ + $\\sigma_\\star$ offset & 574",
]


def transform(text: str) -> str:
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count == 1:
            text = text.replace(old, new)
            continue
        if count > 1:
            raise RuntimeError(f"Expected exactly one occurrence, found {count}: {old[:100]!r}")
        # TeX source snapshots can differ only in indentation or line wrapping.
        # Preserve exact token order while allowing whitespace runs to vary.
        tokens = old.split()
        pattern = r"\s+".join(re.escape(token) for token in tokens)
        matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one exact or whitespace-flexible occurrence, found {len(matches)}: {old[:100]!r}"
            )
        text = text[:matches[0].start()] + new + text[matches[0].end():]
    remaining = [phrase for phrase in PROHIBITED if phrase in text]
    if remaining:
        raise RuntimeError(f"Prohibited positive sigma language remains: {remaining}")
    required = ["b=-0.7070", "p_{\\rm one\\text{-}sided,negative}=0.0345", "fail\\_nonconcordant"]
    absent = [phrase for phrase in required if phrase not in text]
    if absent:
        raise RuntimeError(f"Required survivor/disposition text missing: {absent}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manuscript", default="paper/manuscript_snapshot/main.tex")
    parser.add_argument("--check", action="store_true", help="Validate transformation without writing")
    args = parser.parse_args()
    path = Path(args.manuscript)
    original = path.read_text(encoding="utf-8")
    revised = transform(original)
    if args.check:
        print(f"[ok] manuscript surgery is applicable: {len(REPLACEMENTS)} guarded replacements")
        return 0
    path.write_text(revised, encoding="utf-8")
    print(f"[ok] updated {path}: {len(REPLACEMENTS)} guarded replacements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
