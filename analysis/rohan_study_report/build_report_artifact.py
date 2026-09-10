#!/usr/bin/env python3
"""Build the canonical portable-report artifact from checked analysis outputs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
OUT = HERE / "output"


def records(name: str) -> list[dict]:
    frame = pd.read_csv(OUT / name)
    return json.loads(frame.to_json(orient="records"))


def pct(n: int, d: int) -> str:
    return f"{100*n/d:.1f}%"


results = json.loads((OUT / "analysis_results.json").read_text(encoding="utf-8"))
paired = results["paired_outcomes"]
ratings = records("rating_comparisons.csv")
instances = records("instance_summary.csv")
demographics = records("demographic_summary.csv")
quality = records("data_quality_summary.csv")
flow = records("sample_flow.csv")
condition = records("condition_summary.csv")
performance = records("performance_detail.csv")
order = records("order_effects.csv")
sensitivity = records("sensitivity_summary.csv")[0]
profile_check = records("profile_consistency.csv")[0]
generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

summary = [{
    "participants": results["participants"],
    "paired_n": results["paired_complete_n"],
    "prototype_success": paired["prototype_all_six_successes"] / paired["paired_n"],
    "baseline_success": paired["baseline_successes"] / paired["paired_n"],
    "difference_pp": paired["paired_difference_percentage_points"],
    "mcnemar_p": paired["mcnemar_exact_two_sided_p"],
}]
paired_success = [
    {"condition": "reCAPTCHA baseline (one check)", "success_rate": paired["baseline_successes"] / paired["paired_n"], "successes": paired["baseline_successes"], "n": paired["paired_n"]},
    {"condition": "Accessible prototype (all six correct)", "success_rate": paired["prototype_all_six_successes"] / paired["paired_n"], "successes": paired["prototype_all_six_successes"], "n": paired["paired_n"]},
]
rating_chart = []
for row in ratings:
    rating_chart.extend([
        {"measure": row["label"], "condition": "reCAPTCHA baseline", "median": row["baseline_median"]},
        {"measure": row["label"], "condition": "Accessible prototype", "median": row["prototype_median"]},
    ])

rating_table = [{
    "measure": r["label"],
    "baseline": f"{r['baseline_median']:.1f} ({r['baseline_q1']:.1f}–{r['baseline_q3']:.1f})",
    "prototype": f"{r['prototype_median']:.1f} ({r['prototype_q1']:.1f}–{r['prototype_q3']:.1f})",
    "effect": round(r["rank_biserial_favoring_prototype"], 3),
    "raw_p": round(r["exact_signed_rank_p"], 4),
    "holm_p": round(r["holm_adjusted_p"], 4),
} for r in ratings]

instance_table = [{
    "instance": r["instance_id"],
    "correct": f"{int(r['correct'])}/{int(r['trials'])} ({r['correct_percent']:.1f}%)",
    "median_time": round(r["median_time_s"], 2),
    "iqr_time": f"{r['q1_time_s']:.2f}–{r['q3_time_s']:.2f}",
    "mean_attempts": round(r["mean_attempts"], 2),
} for r in instances]

demographic_table = [{
    "variable": r["variable"].replace("_", " ").title(),
    "category": str(r["category"]).replace("_", " ").title(),
    "n": int(r["n"]),
    "percent": round(r["percent"] / 100, 4),
} for r in demographics]

quality_labels = {
    "raw_rows": "Raw rows",
    "unique_trial_pk": "Unique row identifiers",
    "participant_ids": "Participant IDs",
    "session_ids": "Session IDs",
    "duplicate_extra_rows": "Repeated extra rows",
    "duplicate_sessions": "Sessions containing repeats",
    "excluded_rows": "Rows pre-marked excluded",
    "clock_suspect_rows": "Clock-suspect rows",
    "tab_away_rows": "Rows with a tab-away event",
    "blank_trial_id_rows": "Rows with blank trial_id",
    "time_decomposition_mismatches_gt_0_01s": "Timing decomposition mismatches >0.01 s",
}
quality_table = [{"check": quality_labels.get(r["check"], r["check"]), "value": int(r["value"])} for r in quality]

snapshot_datasets = {
    "summary": summary,
    "paired_success": paired_success,
    "rating_chart": rating_chart,
    "rating_table": rating_table,
    "instances": instances,
    "instance_table": instance_table,
    "flow": flow,
    "demographics": demographic_table,
    "quality": quality_table,
    "condition_summary": condition,
    "performance_detail": performance,
    "order_effects": order,
    "sensitivity": [sensitivity],
    "profile_consistency": [profile_check],
}

# Materialize the reviewed report snapshot as a queryable audit database. The
# source query below is executed here and is the exact query exposed by the
# portable report's source affordances.
evidence_db = OUT / "report_snapshot.sqlite"
with sqlite3.connect(evidence_db) as connection:
    connection.execute("drop table if exists report_evidence")
    connection.execute(
        "create table report_evidence (dataset text not null, row_index integer not null, row_json text not null)"
    )
    for dataset, rows in snapshot_datasets.items():
        connection.executemany(
            "insert into report_evidence(dataset, row_index, row_json) values (?, ?, ?)",
            [(dataset, i, json.dumps(row, sort_keys=True)) for i, row in enumerate(rows)],
        )
    connection.commit()
    connection.execute(
        "select dataset, row_index, row_json from report_evidence order by dataset, row_index"
    ).fetchall()

analysis_source = {
    "id": "analysis_pipeline",
    "label": "Reproducible Python analysis of the Supabase workbook export",
    "path": "analysis/rohan_study_report/output/report_snapshot.sqlite",
    "query": {
        "engine": "SQLite",
        "language": "sql",
        "sql": "SELECT dataset, row_index, row_json FROM report_evidence ORDER BY dataset, row_index;",
        "description": "Reviewed report evidence produced by analyze_study.py from the supplied workbook and materialized by build_report_artifact.py.",
        "executed_at": generated,
        "tables_used": ["report_evidence"],
        "filters": [
            "excluded = 0 in the upstream analysis",
            "earliest row per session_id + condition + item_index",
            "paired analysis requires six prototype trials and one baseline trial",
            "rating analysis requires nonmissing ratings for both conditions",
        ],
        "metric_definitions": [
            "Prototype success: all six unique prototype trials correct and none gave up.",
            "Baseline success: the single reCAPTCHA v2 row has correct = 1.",
            "Paired difference: prototype success minus baseline success within complete sessions.",
        ],
    },
}
workbook_source = {
    "id": "source_workbook",
    "label": "Supabase merged study export",
    "path": "Rohan.xlsx",
}
application_source = {
    "id": "application_protocol",
    "label": "Implemented study protocol and data contract",
    "path": "app/run/[token]/Runner.tsx",
}
sources = [analysis_source, workbook_source, application_source]

title = "Accessible Grid-Based Human Verification for Blind Users"

blocks = [
    {"id": "title", "type": "markdown", "body": f"# {title}"},
    {
        "id": "technical_summary",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Technical summary\n\n"
        "In the **16 participant sessions with complete data for both conditions**, "
        "**12/16 (75.0%)** met the prototype condition-success criterion of answering all six "
        "reasoning grids correctly, whereas **4/16 (25.0%)** completed the single reCAPTCHA v2 "
        "baseline check. The paired difference was **50.0 percentage points** (participant "
        "bootstrap 95% CI **18.75 to 81.25**); nine participants succeeded only on the prototype, "
        "one succeeded only on the baseline, three succeeded on both, and three on neither "
        "(exact two-sided McNemar **p = .0215**).\n\n"
        "This is promising evidence for **task-specific usability**, not evidence that the prototype "
        "is a validated measure of general reasoning ability or a production-ready security mechanism. "
        "The conditions were not equivalent in content or workload, five sessions lacked one condition, "
        "and the export does not contain the flag needed to determine whether Google displayed an audio "
        "challenge. The five paired ratings did not survive Holm correction; their direction should be "
        "treated as exploratory."
    },
    {"id": "metrics", "type": "metric-strip", "cardIds": ["sample_card", "success_card", "difference_card"]},
    {
        "id": "abstract",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Abstract\n\n"
        "**Background.** Conventional CAPTCHAs can impose disproportionate access barriers on blind users. "
        "This study evaluated a keyboard- and screen-reader-oriented grid-localisation prototype against a "
        "reCAPTCHA v2 baseline. **Method.** Twenty-one blind participants contributed 130 recorded trial rows "
        "in a counterbalanced within-participant design. After resolving three repeated submissions with a "
        "predefined earliest-record rule, 127 unique trials remained. Sixteen sessions contained all six "
        "prototype trials and one baseline trial; 15 also contained complete paired condition ratings. The "
        "primary outcome was participant-level condition success, compared with an exact McNemar test. Five "
        "1–5 ratings were assessed with exact sign-randomized signed-rank tests and Holm correction. "
        "**Results.** Prototype condition success was 75.0% (12/16) versus 25.0% (4/16) for baseline, a paired "
        "difference of 50.0 percentage points (bootstrap 95% CI 18.75–81.25; p=.0215). Across all available "
        "prototype sessions, 103/108 trials (95.4%) were eventually correct and 82/108 (75.9%) were correct "
        "on the first attempt. No subjective outcome was significant after multiplicity correction. "
        "**Conclusion.** The prototype supported substantially more successful task completion in this small "
        "sample, but conclusions are limited by non-equivalent tasks, incomplete paired data, repeated "
        "submissions, missing baseline challenge-exposure fields, sparse subgroups, and the absence of a "
        "security evaluation.\n\n**Keywords:** accessibility; blindness; CAPTCHA; screen reader; human "
        "verification; reasoning; assistive technology; within-participant study."
    },
    {
        "id": "introduction",
        "type": "markdown",
        "body": "## Accessible verification remains an unsolved interaction problem\n\n"
        "CAPTCHAs are intended to separate human activity from automation, but sensory and interaction "
        "requirements can exclude legitimate users. WCAG 2.2 requires alternative forms of CAPTCHA using "
        "different sensory modalities, and its accessible-authentication guidance cautions against cognitive "
        "function tests in authentication contexts. Prior work with blind users has shown that conventional "
        "audio CAPTCHA interfaces can be difficult and time-consuming, while interfaces designed specifically "
        "for non-visual interaction can improve success. More recent work likewise found that alternative audio "
        "designs can improve accuracy and speed, while emphasizing that the best design depends on context.\n\n"
        "The present study asks a narrower question: can a text-based elimination puzzle, implemented with "
        "semantic controls and screen-reader-compatible navigation, provide a more usable human-verification "
        "experience for blind participants than a deployed third-party baseline? The study evaluates human "
        "performance and perceived usability. It does **not** test resistance to bots, automated solvers, or "
        "adversarial attacks."
    },
    {
        "id": "research_questions",
        "type": "markdown",
        "body": "## Research questions\n\n"
        "1. Do paired participants meet the prototype condition-success criterion more often than they complete the baseline check?\n"
        "2. How do difficulty, mental effort, frustration, perceived accessibility, and ease of navigation differ between conditions?\n"
        "3. What do trial timing, attempts, give-up behavior, and item-level performance reveal about prototype interaction?\n"
        "4. Are conclusions robust to repeated-submission sessions and block-order imbalance?\n\n"
        "These questions were reconstructed from the implemented protocol and available fields. They should not be described as preregistered unless a dated preregistration exists."
    },
    {
        "id": "success_result",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Paired task success favored the accessible prototype\n\n"
        "Among the 16 complete paired sessions, prototype success was 75.0% and baseline success was 25.0%. "
        "The primary participant-level analysis preserves the within-person dependency and avoids inflating "
        "the sample size by treating 96 prototype trials as 96 independent people. The exact McNemar result "
        "was p=.0215. The bootstrap interval is wide, as expected with only 16 pairs, but its lower endpoint "
        "remains positive."
    },
    {"id": "success_chart", "type": "chart", "chartId": "paired_success_chart", "layout": "full"},
    {
        "id": "success_caveat",
        "type": "markdown",
        "body": "### Interpretation boundary\n\n"
        "The prototype criterion is deliberately demanding—six of six items correct—whereas the baseline "
        "criterion is one completed check. This makes the prototype result notable, but not a like-for-like "
        "comparison of task difficulty. Because the workbook does not include reCAPTCHA's `challenge_shown` "
        "event or trial notes, baseline success cannot be separated into checkbox-only and audio-challenge success."
    },
    {
        "id": "ratings_result",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Subjective ratings were directional but inconclusive\n\n"
        "Fifteen paired sessions had complete ratings for both conditions. Median difficulty was lower for the "
        "prototype (2.0, IQR 1.0–3.0) than baseline (3.0, IQR 2.0–3.5), but the exact signed-rank p value was "
        ".3122 and the Holm-adjusted p value was 1.000. Perceived accessibility had a positive matched "
        "rank-biserial effect (0.611) but identical medians of 3.0 and an adjusted p value of .8984. No rating "
        "met the family-wise .05 threshold. The appropriate conclusion is uncertainty, not equivalence."
    },
    {"id": "ratings_chart", "type": "chart", "chartId": "ratings_chart", "layout": "full"},
    {"id": "ratings_table_block", "type": "table", "tableId": "ratings_table", "layout": "full"},
    {
        "id": "task_process",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Prototype accuracy improved across permitted attempts\n\n"
        "Across 18 sessions with six prototype rows, 82/108 trials (75.9%) were correct on the first attempt "
        "and 103/108 (95.4%) were eventually correct within the permitted interaction. Two prototype trials "
        "ended in give-up. The median prototype trial took 72.25 seconds (IQR 44.23–125.55), including a "
        "median 55.19 seconds before first recorded answer interaction and 8.77 seconds thereafter. The "
        "baseline median of 11.29 seconds is not evidence of greater efficiency: 15/19 baseline rows were "
        "give-ups, and the conditions contained one versus six tasks with different content. Time is therefore "
        "reported descriptively rather than tested as a primary between-condition outcome."
    },
    {
        "id": "instance_result",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Item-level performance identifies candidates for refinement\n\n"
        "Prototype accuracy ranged from 88.9% to 100% across the six fixed instances. Median solve time ranged "
        "from 37.97 seconds for I0010 to 108.64 seconds for I0012. I0013 had the lowest accuracy (16/18, 88.9%), "
        "while I0012 and I0014 had the longest median times. Because the same instance order was used within "
        "the prototype block, instance identity is perfectly confounded with sequence; these observations can "
        "guide redesign but cannot distinguish inherent item difficulty from learning or fatigue."
    },
    {"id": "instance_chart", "type": "chart", "chartId": "instance_time_chart", "layout": "full"},
    {"id": "instance_table_block", "type": "table", "tableId": "instance_table", "layout": "full"},
    {
        "id": "scope_data",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Scope, cohort, and analysis denominators\n\n"
        "The workbook covers data received from 11 August through 26 August 2026 UTC. It contains 21 unique "
        "participant IDs and 21 unique session IDs. Eighteen sessions contain all six prototype trials, 19 "
        "contain one baseline trial, and 16 contain both. Five sessions were incomplete for the paired design: "
        "two contained only the prototype and three only the baseline. Block order was baseline-first for 12 "
        "sessions and prototype-first for nine. The primary paired denominator is therefore 16, while rating "
        "tests use 15 because one paired session lacked baseline ratings."
    },
    {"id": "flow_table_block", "type": "table", "tableId": "flow_table", "layout": "full"},
    {
        "id": "participants",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Participant characteristics show a specific, heterogeneous school cohort\n\n"
        "All 21 records were from one screen-reader-school cohort and one site. Fifteen participants (71.4%) "
        "selected congenital blindness and four (19.0%) early-onset blindness; two preferred not to say. "
        "Primary language was Hindi for 11 (52.4%), English for one (4.8%), and another language for nine "
        "(42.9%). Thirteen (61.9%) reported never having used a CAPTCHA. Primary input was keyboard for 10 "
        "(47.6%), voice for seven (33.3%), and Braille keyboard/display for two (9.5%); two preferred not to say. "
        "Computer proficiency was rated beginner by nine (42.9%) and basic by five (23.8%). These distributions "
        "support the relevance of the accessibility question but limit generalization to experienced adult "
        "screen-reader users or other sites."
    },
    {"id": "demographic_table_block", "type": "table", "tableId": "demographic_table", "layout": "full"},
    {
        "id": "protocol",
        "type": "markdown",
        "sourceId": "application_protocol",
        "body": "## Implemented study protocol\n\n"
        "After consent and background questions, participants received a text explanation and one unscored "
        "practice puzzle. Each scored prototype item described a hidden circle in a 4×4 grid and presented "
        "verbal elimination clues; participants selected a column and row. The six verified instances were "
        "fixed for all participants. The baseline embedded reCAPTCHA v2 and instructed users to select “I am "
        "not a robot,” use its audio option if a challenge appeared, and submit or skip. Order was "
        "counterbalanced as baseline-first or prototype-first. After each condition, participants rated "
        "difficulty, mental effort, frustration, perceived accessibility, and navigation ease from 1 to 5. "
        "The interface recorded solve, orientation, and execution time; correctness; attempts; give-up; tab-away "
        "events; and profile fields.\n\n"
        "**Publication placeholders:** [INSERT ethics committee, approval number, consent procedure, recruitment "
        "dates, eligibility criteria, participant compensation, testing location, device, browser, screen-reader "
        "name/version, assistance policy, and investigator role]. These facts are not inferable from the workbook."
    },
    {
        "id": "methods",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Statistical analysis\n\n"
        "Rows were sorted by server receipt time. For repeated `session_id + condition + item_index` keys, the "
        "earliest row was retained to reduce repeat-exposure bias. The primary inferential unit was the session. "
        "A prototype session succeeded only if all six unique trials were correct and none was a give-up; baseline "
        "success required `correct=1` on its single row. Paired binary success was tested with an exact two-sided "
        "McNemar test; the percentage-point difference received a 20,000-resample participant bootstrap percentile "
        "interval using seed 20260904. Trial proportions received Wilson intervals.\n\n"
        "Condition ratings were collapsed to one value per session-condition before testing. Direction was "
        "standardized so positive effects favored the prototype: baseline minus prototype for difficulty, mental "
        "effort, and frustration; prototype minus baseline for accessibility and navigation. Two-sided exact "
        "sign-randomized signed-rank tests handled the small sample and ties; matched rank-biserial correlations "
        "quantified effect direction and magnitude. Holm correction controlled family-wise error across five "
        "ratings. Medians and IQRs describe skewed timing and ordinal outcomes. Order effects and item summaries "
        "were exploratory. No missing values were imputed. Analyses used Python 3.9, pandas 2.3.3, NumPy 2.0.2, "
        "SciPy 1.13.1, and statsmodels 0.14.6."
    },
    {
        "id": "data_quality",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Data quality is usable for an exploratory report, with material caveats\n\n"
        "All 130 `trial_pk` values were unique, no row was marked excluded or clock-suspect, and every cleaned "
        "row satisfied `solve_time = orientation_time + execution_time` within 0.01 seconds. One row recorded a "
        "tab-away event. However, two sessions contained three extra repeated rows, all 130 human-readable "
        "`trial_id` values were blank, and two baseline rows lacked condition ratings. Most importantly, eight "
        "of 21 profiles (38.1%) contained an onset/age combination that contradicted the response categories—for "
        "example, congenital blindness paired with an age after birth. Those fields are retained separately but "
        "not combined or used for subgroup inference."
    },
    {"id": "quality_table_block", "type": "table", "tableId": "quality_table", "layout": "full"},
    {
        "id": "robustness",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Sensitivity and order checks did not reverse the primary conclusion\n\n"
        "Removing both sessions that contained any repeated submission left 14 pairs: 11 prototype successes "
        "versus two baseline successes, with nine prototype-only successes and none baseline-only (exact McNemar "
        "p=.0039). Paired completion did not differ detectably by block order (Fisher exact p=1.000), and median "
        "prototype item time did not differ detectably between order groups (Mann–Whitney p=.331). These are "
        "small-sample robustness checks, not evidence that carryover effects are absent."
    },
    {
        "id": "discussion",
        "type": "markdown",
        "body": "## Discussion\n\n"
        "The clearest result is behavioral: most paired participants completed all six prototype problems, while "
        "only one quarter completed the baseline check. This pattern is consistent with prior accessibility "
        "research showing that non-visual interfaces should be designed around non-visual interaction rather "
        "than copied directly from visual workflows. The prototype's text-first structure, semantic controls, "
        "explicit clue sequence, and separate column/row responses may have reduced interface uncertainty.\n\n"
        "The subjective results are more restrained. Difficulty moved in the expected direction, and accessibility "
        "showed a moderately large directional rank effect, but neither survived multiplicity correction. The "
        "small n, coarse five-point scales, heterogeneous technology experience, and one missing paired rating "
        "leave substantial uncertainty. The behavioral and self-report findings should therefore be discussed as "
        "complementary rather than forced into a single claim.\n\n"
        "From a cognitive-psychology perspective, the prototype requires maintenance of verbal constraints, "
        "elimination of alternatives, spatial coding of rows and columns, and response selection. Those demands "
        "are relevant to working memory and deductive reasoning, but the current task has no validated latent "
        "score, reliability estimate, convergent measure, or difficulty calibration. The data support statements "
        "about performance on these six puzzles—not a statement that one participant or condition has greater "
        "general reasoning ability."
    },
    {
        "id": "limitations",
        "type": "markdown",
        "body": "## Limitations and uncertainty\n\n"
        "1. **Small, single-site sample.** Twenty-one sessions and 16 paired completers yield imprecise estimates and sparse demographic cells.\n"
        "2. **Non-equivalent conditions.** Six custom reasoning trials were compared with one third-party check; task content, workload, and success definitions differ.\n"
        "3. **Unknown baseline exposure.** The workbook omits challenge-shown events and trial notes, so actual audio-challenge exposure cannot be reported.\n"
        "4. **Incomplete and repeated sessions.** Five sessions lacked one condition; two contained repeated submissions. Deterministic cleaning and sensitivity analysis reduce but do not eliminate bias.\n"
        "5. **Measurement inconsistency.** Eight blindness-onset/age combinations were logically discordant, suggesting wording or administration problems.\n"
        "6. **Fixed item sequence.** Prototype item and position effects are inseparable.\n"
        "7. **No security evaluation.** Human usability does not demonstrate bot resistance, replay resistance, entropy, or adversarial robustness.\n"
        "8. **No qualitative corpus.** The workbook contains rating scales but no open-ended responses, so thematic analysis is not possible.\n"
        "9. **No validated cognitive outcome.** The task cannot support clinical, diagnostic, or general intelligence claims.\n"
        "10. **Unreported administration details.** Ethics, recruitment, compensation, hardware, browser, screen reader, and researcher assistance must be supplied before submission."
    },
    {
        "id": "recommendations",
        "type": "markdown",
        "body": "## Recommended next study\n\n"
        "1. Export and join the full `events` and raw `trials` tables so baseline challenge exposure, verification notes, tab-away duration, and exact timestamps are available.\n"
        "2. Randomize prototype instance order and use equal numbers of baseline and prototype challenges.\n"
        "3. Define a single comparable primary endpoint in advance, preregister exclusions and hypotheses, and perform an a priori precision or power analysis.\n"
        "4. Add a validated external reasoning or working-memory measure only if the paper intends to make cognitive-ability claims; otherwise frame the outcome as task-specific verification performance.\n"
        "5. Pilot the blindness-onset questions with cognitive interviewing and enforce logically compatible follow-up options.\n"
        "6. Record device, operating system, browser, screen reader and version, input method used during the task, assistance received, and actual audio-challenge exposure.\n"
        "7. Add a short open-ended prompt after each condition and a final preference question if qualitative explanations are part of the research aims.\n"
        "8. Conduct a separate security analysis against scripted solvers and language models before proposing deployment as a CAPTCHA."
    },
    {
        "id": "conclusion",
        "type": "markdown",
        "sourceId": "analysis_pipeline",
        "body": "## Conclusion\n\n"
        "In this exploratory, counterbalanced study of blind participants, the accessible grid prototype achieved "
        "a higher paired condition-success rate than the reCAPTCHA v2 baseline: 75.0% versus 25.0%, even though "
        "prototype success required six correct items. The exact paired result was statistically detectable, and "
        "the direction persisted after excluding repeated-submission sessions. Subjective ratings were not "
        "conclusive after multiplicity correction. The prototype merits a larger, better-instrumented usability "
        "study, but the present evidence does not establish general reasoning ability, equal task efficiency, or "
        "security effectiveness."
    },
    {
        "id": "further_questions",
        "type": "markdown",
        "body": "## Further questions\n\n"
        "- How often did reCAPTCHA display only the checkbox, an image task, or an audio task?\n"
        "- Did researcher assistance differ by condition or participant technology?\n"
        "- Are I0012 and I0014 intrinsically harder, or did fixed sequence create fatigue?\n"
        "- Would results replicate with daily screen-reader users, multiple sites, adult participants, and non-English interfaces?\n"
        "- Can the prototype retain usability under a security-strengthened, randomized item generator?"
    },
    {
        "id": "publication_checklist",
        "type": "markdown",
        "body": "## Before journal submission\n\n"
        "Replace every bracketed placeholder; confirm the author list and affiliations; insert the ethics approval "
        "and recruitment details; verify whether data collection dates and participant labels may be disclosed; "
        "state whether the analysis was preregistered; select a target journal and apply its word, table, figure, "
        "and reference style; have a statistician review the non-equivalent success endpoint; and decide whether "
        "de-identified data and code can be deposited in a controlled repository."
    },
    {
        "id": "references",
        "type": "markdown",
        "body": "## References\n\n"
        "Bigham, J. P., & Cavender, A. C. (2009). [Evaluating existing audio CAPTCHAs and an interface optimized for non-visual use](https://www.cs.cmu.edu/~jbigham/pubs/pdfs/2009/audio-captchas.pdf). *Proceedings of CHI 2009*, 1829–1838.\n\n"
        "Fanelle, V., Karimi, S., Shah, A., Subramanian, B., & Das, S. (2020). [Blind and human: Exploring more usable audio CAPTCHA designs](https://www.usenix.org/conference/soups2020/presentation/fanelle). *Sixteenth Symposium on Usable Privacy and Security*, 111–125.\n\n"
        "Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics, 6*(2), 65–70. https://doi.org/10.2307/4615733\n\n"
        "World Wide Web Consortium. (2024). [Web Content Accessibility Guidelines (WCAG) 2.2](https://www.w3.org/TR/wcag/). W3C Recommendation.\n\n"
        "Google. (2024). [reCAPTCHA v2 developer documentation](https://developers.google.com/recaptcha/docs/display)."
    },
]

artifact = {
    "surface": "report",
    "manifest": {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "Copy-ready technical manuscript and reproducible analysis of a blind-user CAPTCHA comparison study.",
        "generatedAt": generated,
        "cards": [
            {
                "id": "sample_card",
                "description": "Participant sessions in the supplied workbook and paired-complete sessions used for the primary comparison.",
                "dataset": "summary",
                "sourceId": "analysis_pipeline",
                "metrics": [
                    {"label": "Participant sessions", "field": "participants", "format": "number"},
                    {"label": "Paired-complete sessions", "field": "paired_n", "format": "number"},
                ],
            },
            {
                "id": "success_card",
                "description": "Participant-level condition success in paired-complete sessions.",
                "dataset": "summary",
                "sourceId": "analysis_pipeline",
                "metrics": [
                    {"label": "Prototype: all six correct", "field": "prototype_success", "format": "percent"},
                    {"label": "Baseline: one check completed", "field": "baseline_success", "format": "percent"},
                ],
            },
            {
                "id": "difference_card",
                "description": "Prototype minus baseline within participants; exact McNemar inference.",
                "dataset": "summary",
                "sourceId": "analysis_pipeline",
                "metrics": [
                    {"label": "Paired difference, percentage points", "field": "difference_pp", "format": "number", "signed": True},
                    {"label": "Exact two-sided p", "field": "mcnemar_p", "format": "number"},
                ],
            },
        ],
        "charts": [
            {
                "id": "paired_success_chart",
                "title": "Paired condition success",
                "subtitle": "Complete paired sessions; n=16. Prototype success required all six grid items correct.",
                "type": "bar",
                "dataset": "paired_success",
                "sourceId": "analysis_pipeline",
                "encodings": {
                    "x": {"field": "condition", "type": "nominal", "label": "Condition"},
                    "y": {"field": "success_rate", "type": "quantitative", "label": "Success rate", "format": "percent"},
                },
                "yAxisTitle": "Participants meeting success criterion",
                "valueFormat": "percent",
                "layout": "full",
            },
            {
                "id": "ratings_chart",
                "title": "Paired subjective ratings",
                "subtitle": "Medians on 1–5 scales; n=15 paired sessions with complete ratings.",
                "type": "bar",
                "dataset": "rating_chart",
                "sourceId": "analysis_pipeline",
                "encodings": {
                    "x": {"field": "measure", "type": "nominal", "label": "Measure"},
                    "y": {"field": "median", "type": "quantitative", "label": "Median rating"},
                    "color": {"field": "condition", "type": "nominal", "label": "Condition"},
                },
                "yAxisTitle": "Median rating (1–5)",
                "valueFormat": "number",
                "layout": "full",
            },
            {
                "id": "instance_time_chart",
                "title": "Prototype solve time by fixed instance",
                "subtitle": "Median seconds across 18 sessions; item and sequence effects are confounded.",
                "type": "bar",
                "dataset": "instances",
                "sourceId": "analysis_pipeline",
                "encodings": {
                    "x": {"field": "instance_id", "type": "ordinal", "label": "Instance"},
                    "y": {"field": "median_time_s", "type": "quantitative", "label": "Median solve time", "unit": "seconds"},
                },
                "yAxisTitle": "Median solve time (seconds)",
                "valueFormat": "number",
                "unit": "seconds",
                "layout": "full",
            },
        ],
        "tables": [
            {
                "id": "ratings_table",
                "title": "Paired rating comparisons",
                "subtitle": "Median (IQR), matched rank-biserial effect favoring the prototype, and two-sided exact p values.",
                "dataset": "rating_table",
                "sourceId": "analysis_pipeline",
                "defaultSort": {"field": "measure", "direction": "asc"},
                "density": "spacious",
                "layout": "full",
                "columns": [
                    {"field": "measure", "label": "Measure", "type": "text"},
                    {"field": "baseline", "label": "Baseline median (IQR)", "type": "text"},
                    {"field": "prototype", "label": "Prototype median (IQR)", "type": "text"},
                    {"field": "effect", "label": "Rank-biserial effect", "format": "number"},
                    {"field": "raw_p", "label": "Raw p", "format": "number"},
                    {"field": "holm_p", "label": "Holm-adjusted p", "format": "number"},
                ],
            },
            {
                "id": "instance_table",
                "title": "Prototype instance outcomes",
                "subtitle": "All 18 sessions containing the complete six-item prototype block.",
                "dataset": "instance_table",
                "sourceId": "analysis_pipeline",
                "defaultSort": {"field": "instance", "direction": "asc"},
                "density": "spacious",
                "layout": "full",
                "columns": [
                    {"field": "instance", "label": "Instance", "type": "text"},
                    {"field": "correct", "label": "Correct", "type": "text"},
                    {"field": "median_time", "label": "Median seconds", "format": "number"},
                    {"field": "iqr_time", "label": "IQR seconds", "type": "text"},
                    {"field": "mean_attempts", "label": "Mean attempts", "format": "number"},
                ],
            },
            {
                "id": "flow_table",
                "title": "Analytical sample flow",
                "subtitle": "Counts at each cleaning and eligibility stage from the supplied workbook.",
                "dataset": "flow",
                "sourceId": "analysis_pipeline",
                "defaultSort": {"field": "n", "direction": "desc"},
                "density": "spacious",
                "layout": "full",
                "columns": [
                    {"field": "stage", "label": "Stage", "type": "text"},
                    {"field": "n", "label": "Count", "format": "number"},
                ],
            },
            {
                "id": "demographic_table",
                "title": "Participant characteristics",
                "subtitle": "All 21 unique participant sessions; categories are displayed as recorded.",
                "dataset": "demographics",
                "sourceId": "analysis_pipeline",
                "defaultSort": {"field": "variable", "direction": "asc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "variable", "label": "Variable", "type": "text"},
                    {"field": "category", "label": "Category", "type": "text"},
                    {"field": "n", "label": "n", "format": "number"},
                    {"field": "percent", "label": "%", "format": "percent"},
                ],
            },
            {
                "id": "quality_table",
                "title": "Data-quality checks",
                "subtitle": "Raw workbook and earliest-record cleaned dataset; exact counts.",
                "dataset": "quality",
                "sourceId": "analysis_pipeline",
                "defaultSort": {"field": "check", "direction": "asc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "check", "label": "Check", "type": "text"},
                    {"field": "value", "label": "Count", "format": "number"},
                ],
            },
        ],
        "sources": sources,
        "blocks": blocks,
    },
    "snapshot": {
        "version": 1,
        "generatedAt": generated,
        "status": "ready",
        "datasets": snapshot_datasets,
    },
    "sources": sources,
}

(HERE / "artifact.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
print(HERE / "artifact.json")
