#!/usr/bin/env python3
"""Independent release checks for the study analysis and report artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import nbformat
import pandas as pd
from scipy.stats import binomtest


GRID = "touchstone_grid"
BASELINE = "audio_captcha_baseline"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--analysis-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.analysis_dir / "output"

    raw = pd.read_excel(args.input)
    raw["received_at"] = pd.to_datetime(raw["received_at"], utc=True)
    clean = raw.sort_values("received_at").drop_duplicates(
        ["session_id", "condition", "item_index"], keep="first"
    )
    clean = clean.loc[clean["excluded"].fillna(0).astype(int) == 0]

    assert len(raw) == 130
    assert raw["participant_id"].nunique() == 21
    assert raw["session_id"].nunique() == 21
    assert len(clean) == 127
    assert len(raw) - len(clean) == 3

    grid = clean.loc[clean["condition"] == GRID]
    baseline = clean.loc[clean["condition"] == BASELINE]
    assert (len(grid), int(grid["correct"].sum()), int(grid["gave_up"].sum())) == (108, 103, 2)
    assert (len(baseline), int(baseline["correct"].sum()), int(baseline["gave_up"].sum())) == (19, 4, 15)

    grid_by_session = grid.groupby("session_id").agg(n=("trial_pk", "size"), correct=("correct", "sum"), gave_up=("gave_up", "sum"))
    base_by_session = baseline.groupby("session_id").agg(n=("trial_pk", "size"), correct=("correct", "first"))
    paired_ids = grid_by_session.index[(grid_by_session["n"] == 6)].intersection(
        base_by_session.index[base_by_session["n"] == 1]
    )
    proto = ((grid_by_session.loc[paired_ids, "correct"] == 6) & (grid_by_session.loc[paired_ids, "gave_up"] == 0)).astype(int)
    base = base_by_session.loc[paired_ids, "correct"].astype(int)
    assert len(paired_ids) == 16
    assert (int(proto.sum()), int(base.sum())) == (12, 4)
    proto_only = int(((proto == 1) & (base == 0)).sum())
    base_only = int(((proto == 0) & (base == 1)).sum())
    assert (proto_only, base_only) == (9, 1)
    assert binomtest(1, 10, .5).pvalue == 0.021484375

    result = json.loads((output / "analysis_results.json").read_text(encoding="utf-8"))
    assert result["paired_complete_n"] == 16
    assert result["paired_ratings_n"] == 15
    assert result["profile_onset_age_inconsistent_n"] == 8
    assert result["paired_outcomes"]["mcnemar_exact_two_sided_p"] == 0.021484375

    artifact = json.loads((args.analysis_dir / "artifact.json").read_text(encoding="utf-8"))
    assert artifact["surface"] == "report"
    assert artifact["snapshot"]["status"] == "ready"
    report_summary = artifact["snapshot"]["datasets"]["summary"][0]
    assert report_summary["participants"] == 21
    assert report_summary["paired_n"] == 16
    assert report_summary["prototype_success"] == .75
    assert report_summary["baseline_success"] == .25

    notebook = nbformat.read(args.analysis_dir / "study_analysis.ipynb", as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert code_cells and all(cell.get("execution_count") is not None for cell in code_cells)
    assert not any(
        output_item.get("output_type") == "error"
        for cell in code_cells
        for output_item in cell.get("outputs", [])
    )

    report = (args.analysis_dir / "report.html").read_text(encoding="utf-8")
    assert "Accessible Grid-Based Human Verification for Blind Users" in report
    assert len(report) > 100_000

    expected = [
        "condition_summary.csv", "paired_outcomes.csv", "rating_comparisons.csv",
        "instance_summary.csv", "demographic_summary.csv", "data_quality_summary.csv",
        "figure_1_paired_success.png", "figure_2_paired_ratings.png",
        "figure_3_instance_performance.png", "report_snapshot.sqlite",
    ]
    missing = [name for name in expected if not (output / name).exists()]
    assert not missing, f"Missing outputs: {missing}"
    print("VALIDATION PASSED: workbook, outputs, notebook, artifact, and HTML report agree.")


if __name__ == "__main__":
    main()
