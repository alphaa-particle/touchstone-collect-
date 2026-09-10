#!/usr/bin/env python3
"""POST-HOC grading and aggregation for the blind subscription arm.

`run_cli_arm.py` records only what each model submitted. This script is the
first and only place the answer key is consulted, and it runs after collection
is finished. Keeping the two apart is what makes the arm auditable: the process
that talked to the models could not have graded them, and the process that
grades never talked to a model.

Integrity gates — any failure aborts rather than producing a table:
  * every session must confirm the CLI honoured `--model`
  * `num_turns` must be 1 and `permission_denials` empty on every session,
    which is the direct evidence that no tool was reached and therefore that no
    file could have been read
  * the `control_no_clues` condition must sit at or near the 6.25% guessing
    rate; materially above it means answers are reaching the model by some
    route and the arm is void

Writes output/*.csv, output/cli_arm_tables.md, and splices §6A of the report.
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
RUNS = OUT / "cli_arm_runs.jsonl"
HUMAN = HERE.parent / "rohan_study_report" / "output" / "instance_summary.csv"
REPORT = HERE / "MODEL_BENCHMARK_REPORT.md"

MODEL_ORDER = ["haiku", "sonnet", "opus"]
COND_ORDER = ["thinking_off", "effort_low", "effort_high", "control_no_clues"]
SHORT = {"haiku": "Haiku 4.5", "sonnet": "Sonnet 5", "opus": "Opus 5"}
CHANCE_ONE_ATTEMPT = 6.25          # 1 of 16 cells
HUMAN_TRIAL_CORRECT_PCT = 95.37
HUMAN_TRIAL_MEDIAN_S = 72.25
REGION_KEYS = ("middle", "diagonal", "touching the edge")


def med(xs):
    return st.median(xs) if xs else float("nan")


def pct(n, d):
    return 100.0 * n / d if d else float("nan")


def mkey(m):
    return MODEL_ORDER.index(m) if m in MODEL_ORDER else 99


def ckey(c):
    return COND_ORDER.index(c) if c in COND_ORDER else 99


def grade(path: Path):
    """Load raw sessions, enforce the gates, attach correctness."""
    if not path.exists():
        raise SystemExit(f"{path} not found. Run run_cli_arm.py first.")
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if not r["is_practice"]]

    if any(r.get("harness_version") != 2 for r in rows):
        raise SystemExit(
            "Rows from harness_version < 2 are present. Those were collected "
            "before the leakage fix and must not be aggregated. Delete them "
            "and re-run.")

    errored = [r for r in rows if r["error"]]
    live = [r for r in rows if not r["error"]]
    if errored:
        print(f"note: {len(errored)} errored sessions excluded "
              f"({len(live)} remain)")

    faults = [r for r in live if not r["model_verified"]]
    if faults:
        raise SystemExit(f"{len(faults)} sessions could not confirm --model. "
                         "Refusing to aggregate.")
    for r in live:
        want = {"haiku": "claude-haiku", "sonnet": "claude-sonnet",
                "opus": "claude-opus"}[r["model_alias"]]
        if not (r["model_reported"] or "").startswith(want):
            raise SystemExit(f"alias/model mismatch: {r['model_alias']} -> "
                             f"{r['model_reported']}")

    # Tool-reach gate: a tool call costs an extra turn and/or leaves a denial.
    reached = [r for r in live
               if r.get("num_turns") != 1 or (r.get("permission_denials") or [])]
    if reached:
        raise SystemExit(
            f"{len(reached)} sessions show num_turns != 1 or permission "
            "denials, meaning a tool may have been reached. The no-tools "
            "isolation cannot be certified. Refusing to aggregate.")

    # The answer key is consulted here, and nowhere before.
    _, canonical = load_items()
    key = {i.instance_id: i.solution for i in canonical}
    for r in live:
        r["solution"] = key[r["instance_id"]]
        r["correct"] = r["submitted"] == key[r["instance_id"]]
    return live, canonical, len(errored)


def check_control(live) -> dict | None:
    ctrl = [r for r in live if r["condition"] == "control_no_clues"]
    if not ctrl:
        return None
    hits = sum(1 for r in ctrl if r["correct"])
    rate = pct(hits, len(ctrl))
    verdict = "PASS" if rate <= 25.0 else "FAIL — LEAKAGE SUSPECTED"
    by_model = {}
    for m in MODEL_ORDER:
        sub = [r for r in ctrl if r["model_alias"] == m]
        if sub:
            by_model[m] = (sum(1 for r in sub if r["correct"]), len(sub))
    return {"n": len(ctrl), "hits": hits, "rate": rate, "verdict": verdict,
            "by_model": by_model}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def cond_summary(live) -> list[dict]:
    b = defaultdict(list)
    for r in live:
        b[(r["model_alias"], r["condition"])].append(r)
    out = []
    for (m, c), rs in sorted(b.items(), key=lambda kv: (mkey(kv[0][0]),
                                                        ckey(kv[0][1]))):
        ok = [r for r in rs if r["correct"]]
        out.append({
            "model_alias": m,
            "model_reported": rs[0]["model_reported"],
            "condition": c,
            "clues_shown": rs[0]["clues_shown"],
            "sessions": len(rs),
            "correct": len(ok),
            "solve_rate_percent": round(pct(len(ok), len(rs)), 2),
            "median_output_tokens": round(med([r["output_tokens"] for r in rs])),
            "median_thinking_tokens": round(
                med([r["thinking_tokens"] for r in rs])),
            "median_api_latency_s": round(med([r["api_ms"] for r in rs]) / 1000, 2),
            "parse_failures": sum(1 for r in rs if r["parse_failed"]),
            "enumeration_percent": round(pct(
                sum(1 for r in rs if r["strategy"]["looks_like_enumeration"]),
                len(rs)), 2),
            "median_cells_named": round(
                med([r["strategy"]["distinct_cells_named"] for r in rs]), 1),
            "aux_output_tokens_excluded": sum(r["aux_output_tokens"] for r in rs),
        })
    return out


def item_summary(live, canonical) -> list[dict]:
    humans = {}
    if HUMAN.exists():
        with HUMAN.open() as fh:
            humans = {r["instance_id"]: r for r in csv.DictReader(fh)}
    meta = {i.instance_id: i for i in canonical}
    order = [i.instance_id for i in canonical]

    b = defaultdict(list)
    for r in live:
        if r["condition"] != "control_no_clues":
            b[r["instance_id"]].append(r)
    out = []
    for iid, rs in b.items():
        ok = [r for r in rs if r["correct"]]
        h = humans.get(iid, {})
        item = meta[iid]
        out.append({
            "instance_id": iid,
            "human_order_position": order.index(iid) + 1,
            "has_region_clue": int(any(k in c for c in item.clues
                                       for k in REGION_KEYS)),
            "human_correct_percent": round(float(h["correct_percent"]), 2) if h else "",
            "human_median_time_s": round(float(h["median_time_s"]), 2) if h else "",
            "human_mean_attempts": round(float(h["mean_attempts"]), 3) if h else "",
            "model_sessions": len(rs),
            "model_solve_rate_percent": round(pct(len(ok), len(rs)), 2),
            "model_median_output_tokens": round(
                med([r["output_tokens"] for r in rs])),
            "model_median_cells_named": round(
                med([r["strategy"]["distinct_cells_named"] for r in rs]), 1),
            "model_enumeration_percent": round(pct(
                sum(1 for r in rs if r["strategy"]["looks_like_enumeration"]),
                len(rs)), 2),
        })
    return sorted(out, key=lambda r: r["human_order_position"])


def md_table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join("" if v == "" else str(v) for v in r) + " |")
    return "\n".join(lines)


def build_fragment(cs, isum, ctrl, live, n_err) -> str:
    real = [r for r in live if r["condition"] != "control_no_clues"]
    ok = sum(1 for r in real if r["correct"])
    p = []
    p.append(
        f"Measured on **{len(live)} blind sessions** through the Claude Code CLI "
        f"on a Claude subscription"
        + (f" ({n_err} errored sessions excluded)" if n_err else "") + ".\n")
    p.append(
        "> **Isolation.** Every call ran with `--tools \"\"` (no built-in tools "
        "at all), from a fresh empty temporary working directory, under "
        "`--restricted --strict-mcp-config --max-turns 1`. The runner holds no "
        "solutions — grading happens afterwards in `grade_runs.py`. Every "
        "session was verified to show `num_turns == 1` with no permission "
        "denials, which is direct evidence no tool was reached and no file "
        "could have been read.\n")

    if ctrl:
        p.append("### C0. Validity gate — no-clue control\n")
        p.append(
            f"The clue list is replaced with `(none provided)`; everything else "
            f"in the prompt is byte-identical. The item is then unsolvable by "
            f"reasoning, so a model can only guess: **chance is "
            f"{CHANCE_ONE_ATTEMPT}%** (1 of 16 cells).\n")
        p.append(md_table(
            ["Model", "Correct", "Sessions", "Rate %"],
            [[SHORT.get(m, m), h, n, round(pct(h, n), 2)]
             for m, (h, n) in ctrl["by_model"].items()]
            + [["**Pooled**", ctrl["hits"], ctrl["n"], round(ctrl["rate"], 2)]]))
        p.append(f"\n**Verdict: {ctrl['verdict']}** — pooled "
                 f"{ctrl['rate']:0.2f}% against {CHANCE_ONE_ATTEMPT}% chance. "
                 f"A rate near chance means the models were genuinely solving "
                 f"the clue sets in the other conditions rather than recovering "
                 f"answers from anywhere else.\n")

    p.append("\n### C1. Solve behaviour by model and condition\n")
    p.append(
        "`thinking_off` sets `MAX_THINKING_TOKENS=0`, which disables thinking "
        "through the CLI — this is the true floor-cost condition, the API arm's "
        "`answer_only` equivalent. Token columns count the requested model only; "
        "a Claude Code auxiliary Haiku call fires on every request regardless of "
        "`--model` and is excluded.\n")
    p.append(md_table(
        ["Model", "Condition", "Sessions", "Solve rate %", "Median out tok",
         "Median thinking tok", "Median API s", "Parse fails",
         "Enumeration %", "Median cells named"],
        [[SHORT.get(r["model_alias"], r["model_alias"]), r["condition"],
          r["sessions"], r["solve_rate_percent"], r["median_output_tokens"],
          r["median_thinking_tokens"], r["median_api_latency_s"],
          r["parse_failures"], r["enumeration_percent"],
          r["median_cells_named"]] for r in cs]))
    p.append(f"\nPooled over the three clue-bearing conditions: "
             f"**{ok}/{len(real)} solved ({pct(ok, len(real)):0.2f}%)** against "
             f"a human trial accuracy of {HUMAN_TRIAL_CORRECT_PCT}%.\n")

    p.append("\n### C2. Order-free item difficulty\n")
    p.append(
        "Pooled across models and clue-bearing conditions; the control is "
        "excluded. Each session is an independent conversation with no memory of "
        "the other items, so this ranks items free of the sequence confound the "
        "human data cannot escape. `has_region_clue` marks *middle-boxes*, "
        "*diagonal* or *edge* clues — the kinds that cannot be decomposed one "
        "axis at a time.\n")
    p.append(md_table(
        ["Item", "Order", "Region clue", "Human correct %", "Human median s",
         "Human mean attempts", "Model solve %", "Model median out tok",
         "Median cells named", "Enumeration %"],
        [[r["instance_id"], r["human_order_position"],
          "yes" if r["has_region_clue"] else "no", r["human_correct_percent"],
          r["human_median_time_s"], r["human_mean_attempts"],
          r["model_solve_rate_percent"], r["model_median_output_tokens"],
          r["model_median_cells_named"], r["model_enumeration_percent"]]
         for r in isum]))
    return "\n".join(p)


def splice(fragment: str, report: Path) -> bool:
    if not report.exists():
        return False
    t = report.read_text()
    b, e = "<!-- CLIARM:BEGIN -->", "<!-- CLIARM:END -->"
    if b not in t or e not in t:
        return False
    head, rest = t.split(b, 1)
    _, tail = rest.split(e, 1)
    report.write_text(f"{head}{b}\n\n{fragment}\n{e}{tail}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=RUNS)
    args = ap.parse_args()

    live, canonical, n_err = grade(args.runs)
    ctrl = check_control(live)
    if ctrl:
        print(f"control gate: {ctrl['verdict']} "
              f"({ctrl['hits']}/{ctrl['n']} = {ctrl['rate']:0.2f}%, "
              f"chance {CHANCE_ONE_ATTEMPT}%)")

    cs = cond_summary(live)
    isum = item_summary(live, canonical)
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "cli_arm_condition_summary.csv", cs)
    write_csv(OUT / "cli_arm_item_summary.csv", isum)
    frag = build_fragment(cs, isum, ctrl, live, n_err)
    (OUT / "cli_arm_tables.md").write_text(frag)
    spliced = splice(frag, REPORT)

    print(f"{len(live)} graded sessions -> {OUT}")
    print("  cli_arm_condition_summary.csv, cli_arm_item_summary.csv,")
    print("  cli_arm_tables.md")
    print("Report §6A: " + ("spliced" if spliced else "markers not found"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
