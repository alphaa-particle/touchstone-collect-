#!/usr/bin/env python3
"""Aggregate output/runs.jsonl into CSV tables and the report's results section.

Reads the human side from analysis/rohan_study_report/output/instance_summary.csv
(the real cohort figures, 18 trials per item) so the human-vs-model comparison is
never retyped by hand. Writes:

    output/model_condition_summary.csv   one row per (model, condition)
    output/model_instance_summary.csv    one row per (model, condition, item)
    output/human_vs_model.csv            per-item human/model cost ratios
    output/diagnostics.csv               parse failures, truncations, errors
    output/results_tables.md             markdown fragment
and splices that fragment into MODEL_BENCHMARK_REPORT.md between the
<!-- RESULTS:BEGIN --> / <!-- RESULTS:END --> markers.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from items import load_items

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
RUNS = OUT / "runs.jsonl"
HUMAN = HERE.parent / "rohan_study_report" / "output" / "instance_summary.csv"
REPORT = HERE / "MODEL_BENCHMARK_REPORT.md"

# Human trial-level reference, from condition_summary.csv of the human study.
HUMAN_TRIAL_MEDIAN_S = 72.2525
HUMAN_TRIAL_CORRECT_PCT = 95.37037037037037
HUMAN_TRIAL_ROWS = 108

MODEL_ORDER = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]
COND_ORDER = ["answer_only", "visible_reasoning", "extended_thinking"]
SHORT = {"claude-haiku-4-5": "Haiku 4.5",
         "claude-sonnet-5": "Sonnet 5",
         "claude-opus-5": "Opus 5"}


def med(xs):
    return st.median(xs) if xs else float("nan")


def pct(num, den):
    return 100.0 * num / den if den else float("nan")


def load_runs(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Run run_benchmark.py first "
            "(ANTHROPIC_API_KEY must be set)."
        )
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    # Exclude the practice item from every aggregate: the human comparison is
    # against the canonical six only.
    return [r for r in rows if not r["is_practice"]]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def sort_key(rows, model_field="model", cond_field="condition"):
    def k(r):
        m = MODEL_ORDER.index(r[model_field]) if r[model_field] in MODEL_ORDER else 99
        c = COND_ORDER.index(r[cond_field]) if r[cond_field] in COND_ORDER else 99
        return (m, c, r.get("instance_id", ""))
    return sorted(rows, key=k)


def condition_summary(runs: list[dict]) -> list[dict]:
    buckets = defaultdict(list)
    for r in runs:
        buckets[(r["model"], r["condition"])].append(r)

    out = []
    for (model, cond), rs in buckets.items():
        ok = [r for r in rs if r["solved"]]
        errs = [r for r in rs if r["error"]]
        valid = [r for r in rs if not r["error"]]
        first_try = [r for r in valid if r["solved"] and r["attempts_used"] == 1]
        out.append({
            "model": model,
            "condition": cond,
            "sessions": len(rs),
            "errors": len(errs),
            "solved": len(ok),
            "solve_rate_percent": round(pct(len(ok), len(valid)), 2),
            "first_attempt_rate_percent": round(pct(len(first_try), len(valid)), 2),
            "mean_attempts": round(
                st.mean([r["attempts_used"] for r in valid]), 3) if valid else "",
            "median_input_tokens": round(med([r["total_input_tokens"] for r in valid])),
            "median_output_tokens": round(
                med([r["total_output_tokens"] for r in valid])),
            "median_total_tokens": round(med(
                [r["total_input_tokens"] + r["total_output_tokens"] for r in valid])),
            "median_latency_s": round(
                med([r["total_latency_ms"] for r in valid]) / 1000, 3),
            "q1_latency_s": round(
                st.quantiles([r["total_latency_ms"] for r in valid], n=4)[0] / 1000, 3)
                if len(valid) >= 4 else "",
            "q3_latency_s": round(
                st.quantiles([r["total_latency_ms"] for r in valid], n=4)[2] / 1000, 3)
                if len(valid) >= 4 else "",
            "median_cost_usd": round(med([r["cost_usd"] for r in valid]), 6),
            "cost_per_solve_usd": round(
                sum(r["cost_usd"] for r in valid) / len(ok), 6) if ok else "",
            "output_tokens_per_solve": round(
                sum(r["total_output_tokens"] for r in valid) / len(ok)) if ok else "",
            "latency_s_per_solve": round(
                sum(r["total_latency_ms"] for r in valid) / 1000 / len(ok), 2)
                if ok else "",
        })
    return sort_key(out)


def instance_summary(runs: list[dict]) -> list[dict]:
    buckets = defaultdict(list)
    for r in runs:
        buckets[(r["model"], r["condition"], r["instance_id"])].append(r)

    out = []
    for (model, cond, iid), rs in buckets.items():
        valid = [r for r in rs if not r["error"]]
        ok = [r for r in valid if r["solved"]]
        out.append({
            "model": model,
            "condition": cond,
            "instance_id": iid,
            "sessions": len(rs),
            "solved": len(ok),
            "solve_rate_percent": round(pct(len(ok), len(valid)), 2),
            "mean_attempts": round(
                st.mean([r["attempts_used"] for r in valid]), 3) if valid else "",
            "median_output_tokens": round(
                med([r["total_output_tokens"] for r in valid])),
            "median_latency_s": round(
                med([r["total_latency_ms"] for r in valid]) / 1000, 3),
            "median_cost_usd": round(med([r["cost_usd"] for r in valid]), 6),
        })
    return sort_key(out)


def human_rows() -> dict[str, dict]:
    if not HUMAN.exists():
        return {}
    with HUMAN.open() as fh:
        return {r["instance_id"]: r for r in csv.DictReader(fh)}


def human_vs_model(inst_rows: list[dict], items) -> list[dict]:
    humans = human_rows()
    meta = {i.instance_id: i for i in items}
    out = []
    for r in inst_rows:
        h = humans.get(r["instance_id"])
        if not h:
            continue
        h_med = float(h["median_time_s"])
        m_med = r["median_latency_s"]
        item = meta[r["instance_id"]]
        out.append({
            "instance_id": r["instance_id"],
            "model": r["model"],
            "condition": r["condition"],
            "human_trials": int(h["trials"]),
            "human_correct_percent": round(float(h["correct_percent"]), 2),
            "human_median_time_s": round(h_med, 3),
            "human_mean_attempts": round(float(h["mean_attempts"]), 3),
            "model_solve_rate_percent": r["solve_rate_percent"],
            "model_median_latency_s": m_med,
            "model_mean_attempts": r["mean_attempts"],
            "model_median_output_tokens": r["median_output_tokens"],
            "human_sweeps": item.human_sweeps,
            "predicted_model_cell_checks": item.model_cell_checks,
            "asymmetry_ratio_predicted": item.asymmetry_ratio,
            "time_ratio_human_over_model": round(h_med / m_med, 3) if m_med else "",
            "output_tokens_per_human_sweep": round(
                r["median_output_tokens"] / item.human_sweeps, 1),
        })
    return sort_key(out)


def diagnostics(runs: list[dict]) -> list[dict]:
    buckets = defaultdict(list)
    for r in runs:
        buckets[(r["model"], r["condition"])].append(r)

    out = []
    for (model, cond), rs in buckets.items():
        attempts = [a for r in rs for a in r["attempts"]]
        out.append({
            "model": model,
            "condition": cond,
            "attempts_total": len(attempts),
            "parse_failures": sum(1 for a in attempts if a["parse_failed"]),
            "max_tokens_truncations": sum(
                1 for a in attempts if a["stop_reason"] == "max_tokens"),
            "refusals": sum(1 for a in attempts if a["stop_reason"] == "refusal"),
            "api_retries": sum(a["api_retries"] for a in attempts),
            "session_errors": sum(1 for r in rs if r["error"]),
            "cache_reads_nonzero": sum(
                1 for a in attempts if a["cache_read_input_tokens"]),
            "sessions_exhausting_3_attempts": sum(
                1 for r in rs if r["attempts_used"] == 3 and not r["solved"]),
            "median_thinking_chars": round(
                med([a["thinking_chars"] for a in attempts])),
        })
    return sort_key(out)


def md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join("" if v == "" else str(v) for v in r) + " |")
    return "\n".join(lines)


def build_fragment(cond, inst, hvm, diag, runs) -> str:
    n_sessions = len(runs)
    n_attempts = sum(len(r["attempts"]) for r in runs)
    total_cost = sum(r["cost_usd"] for r in runs)
    parts = []

    parts.append(
        f"Measured on {n_sessions} sessions ({n_attempts} API calls) against the "
        f"canonical six. Total spend on the reported grid: ${total_cost:0.4f}.\n"
    )

    parts.append("### R1. Cost and accuracy by model and condition\n")
    parts.append(md_table(
        ["Model", "Condition", "Solve rate %", "1st-attempt %", "Median out tok",
         "Median in tok", "Median latency s", "Output tok / solve",
         "Cost / solve USD"],
        [[SHORT.get(r["model"], r["model"]), r["condition"], r["solve_rate_percent"],
          r["first_attempt_rate_percent"], r["median_output_tokens"],
          r["median_input_tokens"], r["median_latency_s"],
          r["output_tokens_per_solve"], r["cost_per_solve_usd"]] for r in cond]))

    parts.append("\n### R2. Human versus model, per item\n")
    parts.append(
        "`human_median_time_s` is the real cohort median over 18 trials per item. "
        "`time_ratio` above 1 means the human cohort was slower in wall-clock "
        "seconds than the model.\n")
    parts.append(md_table(
        ["Item", "Model", "Condition", "Human correct %", "Human median s",
         "Model solve %", "Model median s", "Time ratio H/M",
         "Model out tok", "Out tok per human sweep"],
        [[r["instance_id"], SHORT.get(r["model"], r["model"]), r["condition"],
          r["human_correct_percent"], r["human_median_time_s"],
          r["model_solve_rate_percent"], r["model_median_latency_s"],
          r["time_ratio_human_over_model"], r["model_median_output_tokens"],
          r["output_tokens_per_human_sweep"]] for r in hvm]))

    parts.append("\n### R3. Per-item model performance\n")
    parts.append(md_table(
        ["Model", "Condition", "Item", "Solve rate %", "Mean attempts",
         "Median out tok", "Median latency s"],
        [[SHORT.get(r["model"], r["model"]), r["condition"], r["instance_id"],
          r["solve_rate_percent"], r["mean_attempts"], r["median_output_tokens"],
          r["median_latency_s"]] for r in inst]))

    parts.append("\n### R4. Run diagnostics\n")
    parts.append(md_table(
        ["Model", "Condition", "Attempts", "Parse fail", "max_tokens cut",
         "Refusals", "API retries", "Session errors", "Cache-read leaks",
         "Failed all 3 attempts"],
        [[SHORT.get(r["model"], r["model"]), r["condition"], r["attempts_total"],
          r["parse_failures"], r["max_tokens_truncations"], r["refusals"],
          r["api_retries"], r["session_errors"], r["cache_reads_nonzero"],
          r["sessions_exhausting_3_attempts"]] for r in diag]))

    parts.append(
        f"\n### R5. Human reference\n\n"
        f"- Human trial-level accuracy: **{HUMAN_TRIAL_CORRECT_PCT:0.2f}%** "
        f"over {HUMAN_TRIAL_ROWS} prototype trials.\n"
        f"- Human trial-level median solve time: **{HUMAN_TRIAL_MEDIAN_S:0.2f} s**.\n"
        f"- Source: `analysis/rohan_study_report/output/` "
        f"(`condition_summary.csv`, `instance_summary.csv`).\n")
    return "\n".join(parts)


def splice(fragment: str, report: Path) -> bool:
    if not report.exists():
        return False
    text = report.read_text()
    begin, end = "<!-- RESULTS:BEGIN -->", "<!-- RESULTS:END -->"
    if begin not in text or end not in text:
        return False
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    report.write_text(f"{head}{begin}\n\n{fragment}\n{end}{tail}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=RUNS)
    args = ap.parse_args()

    runs = load_runs(args.runs)
    _, canonical = load_items()

    cond = condition_summary(runs)
    inst = instance_summary(runs)
    hvm = human_vs_model(inst, canonical)
    diag = diagnostics(runs)

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "model_condition_summary.csv", list(cond[0]), cond)
    write_csv(OUT / "model_instance_summary.csv", list(inst[0]), inst)
    if hvm:
        write_csv(OUT / "human_vs_model.csv", list(hvm[0]), hvm)
    write_csv(OUT / "diagnostics.csv", list(diag[0]), diag)

    fragment = build_fragment(cond, inst, hvm, diag, runs)
    (OUT / "results_tables.md").write_text(fragment)
    spliced = splice(fragment, REPORT)

    print(f"{len(runs)} sessions aggregated -> {OUT}")
    print("  model_condition_summary.csv, model_instance_summary.csv,")
    print("  human_vs_model.csv, diagnostics.csv, results_tables.md")
    print("Report results section: " + ("spliced" if spliced else "markers not found"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
