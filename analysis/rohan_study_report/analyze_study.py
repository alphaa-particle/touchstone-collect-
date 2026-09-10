#!/usr/bin/env python3
"""Reproducible analysis of the blind-user CAPTCHA comparison study.

The source workbook is read-only. All derived data, statistics, and figures are
written to the requested output directory. The primary inferential unit is a
participant session, not an individual grid trial.
"""

from __future__ import annotations

import argparse
import json
import math
from itertools import product
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import binomtest, fisher_exact, mannwhitneyu, rankdata
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint


GRID = "touchstone_grid"
BASELINE = "audio_captcha_baseline"
RATING_COLUMNS = [
    "difficulty_rating",
    "mental_effort",
    "frustration",
    "perceived_accessibility",
    "ease_of_navigation",
]
LOWER_IS_BETTER = {"difficulty_rating", "mental_effort", "frustration"}
RATING_LABELS = {
    "difficulty_rating": "Difficulty",
    "mental_effort": "Mental effort",
    "frustration": "Frustration",
    "perceived_accessibility": "Perceived accessibility",
    "ease_of_navigation": "Ease of navigation",
}
PROFILE_COLUMNS = [
    "blindness_onset",
    "age_at_vision_loss",
    "primary_language",
    "language_proficiency",
    "education_level",
    "captcha_familiarity",
    "screen_reader_frequency",
    "computer_proficiency",
    "primary_input_method",
]
SEED = 20260904


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path, help="Source .xlsx file")
    parser.add_argument("--output", required=True, type=Path, help="Derived-output directory")
    return parser.parse_args()


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (math.nan, math.nan)
    low, high = proportion_confint(successes, total, alpha=0.05, method="wilson")
    return float(low), float(high)


def bootstrap_ci(values: Iterable[float], statistic=np.mean, n_resamples: int = 20000) -> tuple[float, float]:
    values = np.asarray(list(values), dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return (math.nan, math.nan)
    rng = np.random.default_rng(SEED)
    draws = rng.choice(values, size=(n_resamples, len(values)), replace=True)
    estimates = np.apply_along_axis(statistic, 1, draws)
    return tuple(float(v) for v in np.quantile(estimates, [0.025, 0.975]))


def exact_signed_rank(differences: Iterable[float]) -> tuple[float, float, int]:
    """Two-sided exact sign-randomization p and matched rank-biserial effect.

    Zero differences are removed. Average ranks handle tied absolute differences.
    The effect is positive when the supplied difference favors the prototype.
    """
    diff = np.asarray(list(differences), dtype=float)
    diff = diff[np.isfinite(diff) & (diff != 0)]
    n = len(diff)
    if n == 0:
        return (1.0, 0.0, 0)
    ranks = rankdata(np.abs(diff), method="average")
    observed = abs(float(np.sum(np.sign(diff) * ranks)))
    if n <= 20:
        stats = np.fromiter(
            (abs(float(np.dot(signs, ranks))) for signs in product((-1, 1), repeat=n)),
            dtype=float,
            count=2**n,
        )
        p_value = float(np.mean(stats >= observed - 1e-12))
    else:
        rng = np.random.default_rng(SEED)
        signs = rng.choice((-1, 1), size=(200000, n))
        stats = np.abs(signs @ ranks)
        p_value = float((np.sum(stats >= observed - 1e-12) + 1) / (len(stats) + 1))
    effect = float(np.sum(np.sign(diff) * ranks) / np.sum(ranks))
    return p_value, effect, n


def median_iqr(values: Iterable[float]) -> tuple[float, float, float]:
    s = pd.Series(list(values), dtype="float64").dropna()
    return float(s.median()), float(s.quantile(0.25)), float(s.quantile(0.75))


def save_figure(fig: plt.Figure, output: Path, stem: str) -> None:
    fig.savefig(output / f"{stem}.png", dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(output / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    df = pd.read_excel(args.input)
    df["received_at"] = pd.to_datetime(df["received_at"], utc=True)

    required = {
        "trial_pk", "participant_id", "session_id", "block_order", "condition",
        "instance_id", "item_index", "solve_time_s", "orientation_time_s",
        "execution_time_s", "correct", "attempts", "gave_up", "excluded",
        "clock_suspect", "received_at", *RATING_COLUMNS, *PROFILE_COLUMNS,
    }
    missing_required = sorted(required - set(df.columns))
    if missing_required:
        raise ValueError(f"Missing required columns: {missing_required}")

    raw_rows = len(df)
    key = ["session_id", "condition", "item_index"]
    duplicate_mask = df.duplicated(key, keep=False)
    duplicates = df.loc[duplicate_mask].sort_values(key + ["received_at"]).copy()
    duplicates.to_csv(args.output / "duplicate_rows.csv", index=False)

    # Earliest-record rule minimizes repeat-exposure/learning contamination.
    clean = df.sort_values("received_at").drop_duplicates(key, keep="first").copy()
    clean = clean.loc[clean["excluded"].fillna(0).astype(int) == 0].copy()
    clean.to_csv(args.output / "clean_unique_trials.csv", index=False)

    profile = clean.sort_values("received_at").drop_duplicates("session_id", keep="first")
    session_counts = clean.groupby("session_id").agg(
        participant_id=("participant_id", "first"),
        block_order=("block_order", "first"),
        grid_trials=("condition", lambda s: int((s == GRID).sum())),
        baseline_trials=("condition", lambda s: int((s == BASELINE).sum())),
    ).reset_index()
    session_counts["paired_complete"] = (
        (session_counts["grid_trials"] == 6) & (session_counts["baseline_trials"] == 1)
    )
    session_counts["duplicate_session"] = session_counts["session_id"].isin(duplicates["session_id"])
    session_counts.to_csv(args.output / "cohort_flow.csv", index=False)

    grid = clean.loc[clean["condition"] == GRID].copy()
    baseline = clean.loc[clean["condition"] == BASELINE].copy()
    grid_sessions = grid.groupby("session_id").agg(
        participant_id=("participant_id", "first"),
        block_order=("block_order", "first"),
        grid_n=("trial_pk", "size"),
        grid_correct=("correct", "sum"),
        grid_gave_up=("gave_up", "sum"),
        grid_total_time_s=("solve_time_s", "sum"),
        grid_median_time_s=("solve_time_s", "median"),
        grid_median_orientation_s=("orientation_time_s", "median"),
        grid_median_execution_s=("execution_time_s", "median"),
        grid_mean_attempts=("attempts", "mean"),
    ).reset_index()
    grid_sessions["prototype_all_six_correct"] = (
        (grid_sessions["grid_n"] == 6)
        & (grid_sessions["grid_correct"] == 6)
        & (grid_sessions["grid_gave_up"] == 0)
    ).astype(int)
    baseline_sessions = baseline.groupby("session_id").agg(
        baseline_correct=("correct", "first"),
        baseline_gave_up=("gave_up", "first"),
        baseline_time_s=("solve_time_s", "first"),
        baseline_attempts=("attempts", "first"),
    ).reset_index()
    participant = session_counts.merge(grid_sessions, how="left", on=["session_id", "participant_id", "block_order"])
    participant = participant.merge(baseline_sessions, how="left", on="session_id")
    participant = participant.merge(profile[["session_id", *PROFILE_COLUMNS]], how="left", on="session_id")
    participant.to_csv(args.output / "participant_analysis.csv", index=False)

    paired_ids = set(session_counts.loc[session_counts["paired_complete"], "session_id"])
    paired = participant.loc[participant["session_id"].isin(paired_ids)].copy()

    # Cohort and data-quality summaries.
    flow = pd.DataFrame([
        {"stage": "participant sessions in workbook", "n": int(df["session_id"].nunique())},
        {"stage": "raw trial rows", "n": raw_rows},
        {"stage": "unique trial rows after earliest-record rule", "n": len(clean)},
        {"stage": "sessions with six prototype trials", "n": int((session_counts["grid_trials"] == 6).sum())},
        {"stage": "sessions with one baseline trial", "n": int((session_counts["baseline_trials"] == 1).sum())},
        {"stage": "paired-complete sessions", "n": len(paired)},
        {"stage": "paired sessions with both condition ratings", "n": 0},
        {"stage": "sessions containing repeated submissions", "n": int(session_counts["duplicate_session"].sum())},
    ])

    quality_rows = [
        ("raw_rows", raw_rows),
        ("unique_trial_pk", int(df["trial_pk"].nunique())),
        ("participant_ids", int(df["participant_id"].nunique())),
        ("session_ids", int(df["session_id"].nunique())),
        ("duplicate_extra_rows", int(raw_rows - len(clean))),
        ("duplicate_sessions", int(session_counts["duplicate_session"].sum())),
        ("excluded_rows", int(df["excluded"].fillna(0).sum())),
        ("clock_suspect_rows", int(df["clock_suspect"].fillna(False).sum())),
        ("tab_away_rows", int((df["tab_away_events"].fillna(0) > 0).sum())),
        ("blank_trial_id_rows", int(df["trial_id"].isna().sum())),
        ("time_decomposition_mismatches_gt_0_01s", int(((clean["solve_time_s"] - clean["orientation_time_s"] - clean["execution_time_s"]).abs() > .01).sum())),
    ]
    pd.DataFrame(quality_rows, columns=["check", "value"]).to_csv(args.output / "data_quality_summary.csv", index=False)

    missingness = pd.DataFrame({
        "column": df.columns,
        "missing_n": [int(df[c].isna().sum()) for c in df.columns],
        "missing_percent": [float(df[c].isna().mean() * 100) for c in df.columns],
    })
    missingness.to_csv(args.output / "missingness.csv", index=False)

    # Condition-level descriptive outcomes with independent session/trial denominators.
    condition_rows = []
    for condition, part, trials, success_col in [
        ("Prototype: all six correct", participant.loc[participant["grid_n"] == 6], grid, "prototype_all_six_correct"),
        ("Baseline: challenge completed", participant.loc[participant["baseline_trials"] == 1], baseline, "baseline_correct"),
    ]:
        successes = int(part[success_col].fillna(0).sum())
        n_sessions = len(part)
        low, high = wilson(successes, n_sessions)
        tmed, tq1, tq3 = median_iqr(trials["solve_time_s"])
        condition_rows.append({
            "condition": condition,
            "session_successes": successes,
            "session_denominator": n_sessions,
            "session_success_percent": 100 * successes / n_sessions,
            "wilson_95ci_low_percent": 100 * low,
            "wilson_95ci_high_percent": 100 * high,
            "trial_rows": len(trials),
            "trial_correct": int(trials["correct"].fillna(0).sum()),
            "trial_correct_percent": float(100 * trials["correct"].fillna(0).mean()),
            "trial_time_median_s": tmed,
            "trial_time_q1_s": tq1,
            "trial_time_q3_s": tq3,
        })
    condition_summary = pd.DataFrame(condition_rows)
    condition_summary.to_csv(args.output / "condition_summary.csv", index=False)

    performance_detail = pd.DataFrame([
        {
            "measure": "prototype trial first-attempt correct",
            "numerator": int(((grid["correct"] == 1) & (grid["attempts"] == 1)).sum()),
            "denominator": len(grid),
            "percent": float(100 * ((grid["correct"] == 1) & (grid["attempts"] == 1)).mean()),
        },
        {
            "measure": "prototype trial eventually correct",
            "numerator": int(grid["correct"].sum()),
            "denominator": len(grid),
            "percent": float(100 * grid["correct"].mean()),
        },
        {
            "measure": "prototype trial gave up",
            "numerator": int(grid["gave_up"].sum()),
            "denominator": len(grid),
            "percent": float(100 * grid["gave_up"].mean()),
        },
        {
            "measure": "baseline challenge completed",
            "numerator": int(baseline["correct"].sum()),
            "denominator": len(baseline),
            "percent": float(100 * baseline["correct"].mean()),
        },
        {
            "measure": "baseline gave up",
            "numerator": int(baseline["gave_up"].sum()),
            "denominator": len(baseline),
            "percent": float(100 * baseline["gave_up"].mean()),
        },
    ])
    performance_detail.to_csv(args.output / "performance_detail.csv", index=False)

    # Primary paired success comparison.
    proto_success = paired["prototype_all_six_correct"].astype(int).to_numpy()
    base_success = paired["baseline_correct"].astype(int).to_numpy()
    b = int(np.sum((proto_success == 1) & (base_success == 0)))
    c = int(np.sum((proto_success == 0) & (base_success == 1)))
    mcnemar_p = float(binomtest(min(b, c), b + c, 0.5, alternative="two-sided").pvalue) if b + c else 1.0
    paired_diff = proto_success - base_success
    diff_low, diff_high = bootstrap_ci(paired_diff, np.mean)
    paired_outcomes = pd.DataFrame([{
        "paired_n": len(paired),
        "prototype_all_six_successes": int(proto_success.sum()),
        "baseline_successes": int(base_success.sum()),
        "paired_difference_percentage_points": float(100 * paired_diff.mean()),
        "bootstrap_95ci_low_pp": float(100 * diff_low),
        "bootstrap_95ci_high_pp": float(100 * diff_high),
        "prototype_only_success": b,
        "baseline_only_success": c,
        "both_success": int(np.sum((proto_success == 1) & (base_success == 1))),
        "neither_success": int(np.sum((proto_success == 0) & (base_success == 0))),
        "mcnemar_exact_two_sided_p": mcnemar_p,
    }])
    paired_outcomes.to_csv(args.output / "paired_outcomes.csv", index=False)

    # Collapse copied condition ratings before paired tests.
    ratings = clean.groupby(["session_id", "condition"], as_index=False)[RATING_COLUMNS].first()
    ratings_wide = ratings.pivot(index="session_id", columns="condition", values=RATING_COLUMNS)
    rating_rows = []
    for measure in RATING_COLUMNS:
        pair = ratings_wide.loc[:, [(measure, BASELINE), (measure, GRID)]].dropna()
        base = pair[(measure, BASELINE)].astype(float)
        proto = pair[(measure, GRID)].astype(float)
        improvement = base - proto if measure in LOWER_IS_BETTER else proto - base
        p_value, effect, nonzero_n = exact_signed_rank(improvement)
        ci_low, ci_high = bootstrap_ci(improvement, np.median)
        bm, bq1, bq3 = median_iqr(base)
        pm, pq1, pq3 = median_iqr(proto)
        rating_rows.append({
            "measure": measure,
            "label": RATING_LABELS[measure],
            "paired_n": len(pair),
            "baseline_median": bm,
            "baseline_q1": bq1,
            "baseline_q3": bq3,
            "prototype_median": pm,
            "prototype_q1": pq1,
            "prototype_q3": pq3,
            "median_improvement": float(np.median(improvement)),
            "bootstrap_95ci_low": ci_low,
            "bootstrap_95ci_high": ci_high,
            "nonzero_pairs": nonzero_n,
            "exact_signed_rank_p": p_value,
            "rank_biserial_favoring_prototype": effect,
        })
    rating_comparisons = pd.DataFrame(rating_rows)
    rating_comparisons["holm_adjusted_p"] = multipletests(
        rating_comparisons["exact_signed_rank_p"], method="holm"
    )[1]
    rating_comparisons["holm_significant_0_05"] = rating_comparisons["holm_adjusted_p"] < .05
    rating_comparisons.to_csv(args.output / "rating_comparisons.csv", index=False)
    paired_rating_n = int(rating_comparisons["paired_n"].min())
    flow.loc[flow["stage"] == "paired sessions with both condition ratings", "n"] = paired_rating_n
    flow.to_csv(args.output / "sample_flow.csv", index=False)

    # Per-instance performance; instance identity and within-block sequence are confounded.
    instance_summary = grid.groupby("instance_id").agg(
        trials=("trial_pk", "size"),
        correct=("correct", "sum"),
        gave_up=("gave_up", "sum"),
        median_time_s=("solve_time_s", "median"),
        q1_time_s=("solve_time_s", lambda s: s.quantile(.25)),
        q3_time_s=("solve_time_s", lambda s: s.quantile(.75)),
        median_orientation_s=("orientation_time_s", "median"),
        median_execution_s=("execution_time_s", "median"),
        mean_attempts=("attempts", "mean"),
    ).reset_index()
    instance_summary["correct_percent"] = 100 * instance_summary["correct"] / instance_summary["trials"]
    instance_summary.to_csv(args.output / "instance_summary.csv", index=False)

    # Demographic distributions only; sparse cells make subgroup inference unreliable.
    demographic_rows = []
    for column in PROFILE_COLUMNS:
        counts = profile[column].fillna("missing").astype(str).value_counts(dropna=False)
        for value, count in counts.items():
            demographic_rows.append({
                "variable": column,
                "category": value,
                "n": int(count),
                "percent": float(100 * count / len(profile)),
                "denominator": len(profile),
            })
    demographics = pd.DataFrame(demographic_rows)
    demographics.to_csv(args.output / "demographic_summary.csv", index=False)

    onset_age_crosscheck = pd.crosstab(
        profile["blindness_onset"], profile["age_at_vision_loss"], dropna=False
    )
    onset_age_crosscheck.to_csv(args.output / "blindness_onset_age_crosscheck.csv")
    expected_ages = {
        "congenital": {"from_birth"},
        "early_onset": {"age_1_5", "age_6_12", "age_13_17"},
        "acquired": {"age_18_25", "age_26_40", "age_41_60", "age_61_plus"},
        "prefer_not_to_say": {"prefer_not_to_say"},
    }
    inconsistent_profile = profile.apply(
        lambda row: str(row["age_at_vision_loss"])
        not in expected_ages.get(str(row["blindness_onset"]), {str(row["age_at_vision_loss"])}),
        axis=1,
    )
    profile_consistency = pd.DataFrame([{
        "check": "blindness onset category agrees with reported age-at-vision-loss category",
        "consistent_n": int((~inconsistent_profile).sum()),
        "inconsistent_n": int(inconsistent_profile.sum()),
        "denominator": len(profile),
        "inconsistent_percent": float(100 * inconsistent_profile.mean()),
    }])
    profile_consistency.to_csv(args.output / "profile_consistency.csv", index=False)

    # Order/attrition diagnostics (exploratory).
    order_rows = []
    order_tab = pd.crosstab(session_counts["block_order"], session_counts["paired_complete"])
    for col in (False, True):
        if col not in order_tab.columns:
            order_tab[col] = 0
    order_matrix = order_tab.reindex(
        index=["baseline_first", "prototype_first"], columns=[True, False], fill_value=0
    ).to_numpy()
    odds, completion_p = fisher_exact(order_matrix)
    order_rows.append({"analysis": "paired completion by block order", "statistic": odds, "p_value": completion_p})
    a = participant.loc[(participant["grid_n"] == 6) & (participant["block_order"] == "baseline_first"), "grid_median_time_s"].dropna()
    btime = participant.loc[(participant["grid_n"] == 6) & (participant["block_order"] == "prototype_first"), "grid_median_time_s"].dropna()
    u, ptime = mannwhitneyu(a, btime, alternative="two-sided")
    order_rows.append({"analysis": "prototype median item time by block order", "statistic": u, "p_value": ptime})
    pd.DataFrame(order_rows).to_csv(args.output / "order_effects.csv", index=False)

    # Sensitivity: remove every session that had any repeated submission.
    sens = paired.loc[~paired["duplicate_session"]].copy()
    sp = sens["prototype_all_six_correct"].astype(int).to_numpy()
    sb = sens["baseline_correct"].astype(int).to_numpy()
    s_b = int(np.sum((sp == 1) & (sb == 0)))
    s_c = int(np.sum((sp == 0) & (sb == 1)))
    s_p = float(binomtest(min(s_b, s_c), s_b + s_c, .5).pvalue) if s_b + s_c else 1.0
    sensitivity = pd.DataFrame([{
        "analysis": "exclude sessions with repeated submissions",
        "paired_n": len(sens),
        "prototype_all_six_successes": int(sp.sum()),
        "baseline_successes": int(sb.sum()),
        "prototype_only_success": s_b,
        "baseline_only_success": s_c,
        "mcnemar_exact_two_sided_p": s_p,
    }])
    sensitivity.to_csv(args.output / "sensitivity_summary.csv", index=False)

    # Figures use colorblind-safe colors and expose exact values in CSV outputs.
    sns.set_theme(style="whitegrid", context="paper", font_scale=1.25)
    colors = ["#D55E00", "#0072B2"]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    values = [100 * base_success.mean(), 100 * proto_success.mean()]
    bars = ax.bar(["reCAPTCHA baseline\n(one challenge)", "Accessible prototype\n(all 6 correct)"], values, color=colors)
    for bar, val, n_success in zip(bars, values, [base_success.sum(), proto_success.sum()]):
        ax.text(bar.get_x() + bar.get_width()/2, val + 2, f"{int(n_success)}/{len(paired)} ({val:.0f}%)", ha="center", va="bottom", fontsize=12)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Participants meeting success criterion (%)", fontsize=12)
    ax.set_title("Paired condition success among complete sessions")
    ax.text(.5, -0.21, "Prototype criterion is conservative: all six grid items correct; baseline criterion is one completed check.", transform=ax.transAxes, ha="center", fontsize=10)
    save_figure(fig, args.output, "figure_1_paired_success")

    plot_rows = []
    for measure in RATING_COLUMNS:
        pair = ratings_wide.loc[:, [(measure, BASELINE), (measure, GRID)]].dropna()
        for condition, display in [(BASELINE, "reCAPTCHA baseline"), (GRID, "Accessible prototype")]:
            for value in pair[(measure, condition)]:
                plot_rows.append({"measure": RATING_LABELS[measure], "condition": display, "rating": value})
    plot_df = pd.DataFrame(plot_rows)
    plot_df["measure"] = plot_df["measure"].replace({
        "Mental effort": "Mental\neffort",
        "Perceived accessibility": "Perceived\naccessibility",
        "Ease of navigation": "Ease of\nnavigation",
    })
    fig, ax = plt.subplots(figsize=(11, 6.5))
    sns.pointplot(data=plot_df, x="measure", y="rating", hue="condition", estimator=np.median,
                  errorbar=("pi", 50), dodge=.28, palette=colors, markers=["o", "s"], linestyles="none", ax=ax)
    ax.set_ylim(.75, 5.25)
    ax.set_ylabel("Median rating (IQR error bars; scale 1–5)")
    ax.set_xlabel("")
    ax.set_title("Paired subjective ratings by condition")
    ax.tick_params(axis="x", rotation=0)
    ax.legend(title="")
    ax.text(.5, -0.30, "Lower is better for difficulty, mental effort, and frustration; higher is better for accessibility and navigation.", transform=ax.transAxes, ha="center", fontsize=10)
    save_figure(fig, args.output, "figure_2_paired_ratings")

    fig, ax1 = plt.subplots(figsize=(10, 6))
    order = sorted(instance_summary["instance_id"])
    medians = instance_summary.set_index("instance_id").loc[order, "median_time_s"]
    rates = instance_summary.set_index("instance_id").loc[order, "correct_percent"]
    bars = ax1.bar(order, medians, color="#56B4E9", alpha=.9)
    ax1.set_ylabel("Median solve time (seconds)")
    ax1.set_xlabel("Prototype instance (fixed sequence)")
    ax1.set_title("Prototype performance by fixed instance")
    ax1.margins(y=.16)
    for bar, rate in zip(bars, rates):
        ax1.text(bar.get_x()+bar.get_width()/2, bar.get_height()+3, f"{rate:.0f}% correct", ha="center", fontsize=10)
    ax1.text(.5, -0.18, "Instance identity was not randomized, so these differences cannot distinguish item difficulty from sequence effects.", transform=ax1.transAxes, ha="center", fontsize=10)
    save_figure(fig, args.output, "figure_3_instance_performance")

    # Machine-readable summary used to populate and audit the report.
    result = {
        "source_file": args.input.name,
        "source_sheet": "Supabase Snippet Untitled query",
        "collection_window_utc": [str(df["received_at"].min()), str(df["received_at"].max())],
        "raw_rows": raw_rows,
        "clean_unique_rows": len(clean),
        "participants": int(df["participant_id"].nunique()),
        "sessions": int(df["session_id"].nunique()),
        "paired_complete_n": len(paired),
        "paired_ratings_n": paired_rating_n,
        "grid_sessions_n": int((session_counts["grid_trials"] == 6).sum()),
        "baseline_sessions_n": int((session_counts["baseline_trials"] == 1).sum()),
        "duplicate_extra_rows": int(raw_rows - len(clean)),
        "duplicate_sessions": int(session_counts["duplicate_session"].sum()),
        "profile_onset_age_inconsistent_n": int(inconsistent_profile.sum()),
        "paired_outcomes": paired_outcomes.iloc[0].to_dict(),
        "rating_comparisons": rating_comparisons.to_dict(orient="records"),
        "sensitivity": sensitivity.iloc[0].to_dict(),
    }
    with (args.output / "analysis_results.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=lambda x: x.item() if hasattr(x, "item") else str(x))

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
