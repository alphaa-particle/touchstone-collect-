#!/usr/bin/env python3
"""Offline reanalysis of completed benchmarks; never calls a model or network.

Run from any directory with the packages in requirements.txt installed.
Writes aggregate data, audit metadata and eight 300-dpi PNG figures. The
manuscript is maintained separately as COMPARATIVE_BENCHMARK_REPORT.md.
Answer-bearing inputs are used ONLY for this post-collection analysis.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics as st
import sys
from collections import Counter, defaultdict

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
REPO = BENCH.parents[1]
sys.path.insert(0, str(BENCH))
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mpl-cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
import numpy as np
from grade_gpt_runs import grade as grade_gpt
from items import load_items, verify, _survives
from run_cli_arm import ANSWER_RE, parse_answer, classify_strategy

MODELS = ["haiku", "sonnet", "opus", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
LABEL = dict(zip(MODELS, ["Haiku 4.5", "Sonnet 5", "Opus 5", "GPT Luna", "GPT Terra", "GPT Sol"]))
CONDS = ["thinking_off", "effort_low", "effort_high", "control_no_clues"]
CLABEL = dict(zip(CONDS, ["Thinking off", "Low effort", "High effort", "No clues / high"]))
BLUE, GOLD, ORANGE = "#245B78", "#A58020", "#BC572D"
COLORS = [BLUE, GOLD, ORANGE]
OUT = BENCH / "output"
HUMAN = BENCH.parent / "rohan_study_report" / "output"
DATA = HERE / "data"
FIG = HERE / "figures"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def csv_out(name, rows):
    with (DATA / name).open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def wilson(hits, n):
    z = 1.959963984540054
    p = hits / n
    d = 1 + z*z/n
    mid = (p + z*z/(2*n)) / d
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return 100*max(0, mid-half), 100*min(1, mid+half)


def summarize(rows):
    n = len(rows)
    hits = sum(r["correct"] for r in rows)
    lo, hi = wilson(hits, n)
    answer_tokens = [r["output_tokens"] - r["thinking_tokens"] for r in rows]
    out = dict(n=n, correct=hits, accuracy_pct=100*hits/n,
               wilson_low_pct=lo, wilson_high_pct=hi,
               parse_failures=sum(r["parse_failed"] for r in rows),
               marker_missing=sum(not ANSWER_RE.search(r["text"]) for r in rows),
               enumeration_pct=100*sum(r["strategy"]["looks_like_enumeration"] for r in rows)/n,
               median_cells_named=st.median(r["strategy"]["distinct_cells_named"] for r in rows),
               median_visible_characters=st.median(len(r["text"]) for r in rows),
               median_nonreasoning_output_tokens=st.median(answer_tokens),
               output_tokens_per_correct=sum(r["output_tokens"] for r in rows)/hits if hits else "",
               wall_seconds_per_correct=sum(r["wall_ms"] for r in rows)/1000/hits if hits else "",
               sum_output_tokens=sum(r["output_tokens"] for r in rows),
               sum_reasoning_tokens=sum(r["thinking_tokens"] for r in rows),
               sum_wall_s=sum(r["wall_ms"] for r in rows)/1000,
               aux_output_tokens=sum(r["aux_output_tokens"] for r in rows))
    for field, name, scale in [("output_tokens", "output_tokens", 1),
                                ("thinking_tokens", "reasoning_tokens", 1),
                                ("wall_ms", "wall_s", 1000), ("api_ms", "api_s", 1000)]:
        values = [r[field]/scale for r in rows if r.get(field) is not None]
        for stat, fn in [("median", st.median), ("mean", st.mean),
                         ("q1", lambda x: float(np.quantile(x, .25))),
                         ("q3", lambda x: float(np.quantile(x, .75))),
                         ("min", min), ("max", max)]:
            out[f"{stat}_{name}"] = fn(values) if values else ""
    return out


def main():
    for folder in [DATA, FIG]:
        folder.mkdir(parents=True, exist_ok=True)
    rawc = read_jsonl(OUT / "cli_arm_runs.jsonl")
    rawg = read_jsonl(OUT / "gpt_cli_arm_runs.jsonl")
    c = [r for r in rawc if not r.get("error") and not r["is_practice"]]
    g, items, manifest, errors, _ = grade_gpt(OUT / "gpt_cli_arm_runs.jsonl")
    practice, canonical = load_items()
    assert not verify([practice, *canonical])
    assert [i.instance_id for i in items] == [i.instance_id for i in canonical]
    answers = {i.instance_id: i.solution for i in items}
    ids = list(answers)
    item_by_id = {i.instance_id: i for i in items}
    assert len(rawc) == len(c) == 360 and len(g) == 360 and len(rawg) == 363
    for r in c:
        assert r["harness_version"] == 2 and r["model_verified"]
        assert r["num_turns"] == 1 and not r["permission_denials"]
        assert r["model_reported"].startswith("claude-" + r["model_alias"])
        assert r["submitted"] == parse_answer(r["text"])
        assert r["parse_failed"] == (r["submitted"] is None)
        assert r["strategy"] == classify_strategy(r["text"])
        assert r["clues_shown"] == (r["condition"] != CONDS[3])
        assert r["effort"] == {CONDS[0]: "n/a", CONDS[1]: "low", CONDS[2]: "high", CONDS[3]: "high"}[r["condition"]]
        if r["condition"] == CONDS[0]:
            assert r["max_thinking_tokens"] == "0" and r["thinking_tokens"] == 0
        r["correct"] = r["submitted"] == answers[r["instance_id"]]
    rows = c + g
    expected = set(itertools.product(MODELS, CONDS, ids, range(1, 6)))
    observed = [(r["model_alias"], r["condition"], r["instance_id"], r["replicate"]) for r in rows]
    assert len(set(observed)) == len(observed) == 720 and set(observed) == expected
    for r in rows:
        assert r["output_tokens"] >= r["thinking_tokens"] >= 0
        assert r["wall_ms"] > 0
    source_paths = [OUT / "cli_arm_runs.jsonl", OUT / "gpt_cli_arm_runs.jsonl",
                    OUT / "gpt_cli_arm_runs.manifest.json", BENCH / "gpt_inputs.json",
                    REPO / "data" / "instances.json", HUMAN / "clean_unique_trials.csv",
                    HUMAN / "analysis_results.json", HUMAN / "instance_summary.csv",
                    BENCH / "run_cli_arm.py", BENCH / "grade_runs.py", BENCH / "items.py",
                    BENCH / "prompts.py", BENCH / "run_gpt_cli_arm.py", BENCH / "gpt_transport.py",
                    BENCH / "gpt_wire_audit.py", BENCH / "prepare_gpt_inputs.py", BENCH / "grade_gpt_runs.py",
                    REPO / "app/run/[token]/Runner.tsx", REPO / "lib/instances.ts",
                    REPO / "app/api/trial/route.ts", HERE / "build_analysis.py",
                    HERE / "build_manuscript.py", HERE / "requirements.txt"]
    checksums = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    for name, expected_hash in manifest["source_sha256"].items():
        assert hashlib.sha256((BENCH/name).read_bytes()).hexdigest() == expected_hash
    groups = {(m, cond): [r for r in rows if r["model_alias"] == m and r["condition"] == cond]
              for m in MODELS for cond in CONDS}
    summary = [{"model": m, "label": LABEL[m], "condition": cond, **summarize(rs)}
               for (m, cond), rs in groups.items()]
    sm = {(r["model"], r["condition"]): r for r in summary}
    for m in MODELS:
        assert sm[m, CONDS[3]]["accuracy_pct"] <= 25
    # Reconcile legacy CSVs without importing graders with report-writing side effects.
    for vendor, name in [("Claude", "cli_arm_condition_summary.csv"), ("GPT", "gpt_cli_arm_condition_summary.csv")]:
        for prior in read_csv(OUT / name):
            new = sm[prior["model_alias"], prior["condition"]]
            assert int(prior["sessions"]) == new["n"] and int(prior["correct"]) == new["correct"]
            assert float(prior["solve_rate_percent"]) == round(new["accuracy_pct"], 2)
            precision = 0 if vendor == "Claude" else 2
            assert float(prior["median_output_tokens"]) == round(new["median_output_tokens"], precision)
            assert float(prior["median_thinking_tokens"]) == round(new["median_reasoning_tokens"], precision)
            metric = "median_api_latency_s" if vendor == "Claude" else "median_wall_latency_s"
            assert float(prior[metric]) == round(new["median_api_s" if vendor == "Claude" else "median_wall_s"], 2)
    csv_out("condition_summary.csv", summary)
    input_usage = []
    for m in MODELS[3:]:
        for cond in CONDS:
            rs = groups[m, cond]
            input_usage.append(dict(model=m, condition=cond, n=len(rs),
                                    median_input_tokens=st.median(r["input_tokens"] for r in rs),
                                    min_input_tokens=min(r["input_tokens"] for r in rs),
                                    max_input_tokens=max(r["input_tokens"] for r in rs),
                                    sum_input_tokens=sum(r["input_tokens"] for r in rs),
                                    sum_cached_input_tokens=sum(r["cached_input_tokens"] for r in rs)))
    csv_out("gpt_input_usage.csv", input_usage)
    normalized = []
    for r in rows:
        normalized.append({k: r[k] for k in ["model_alias", "condition", "instance_id", "replicate",
                           "submitted", "correct", "parse_failed", "output_tokens", "thinking_tokens",
                           "wall_ms", "api_ms", "aux_output_tokens"]} | {
                           "visible_characters": len(r["text"]),
                           "input_tokens_including_harness": r.get("input_tokens", ""),
                           "cached_input_tokens": r.get("cached_input_tokens", ""),
                           "distinct_cells_named": r["strategy"]["distinct_cells_named"],
                           "has_answer_marker": bool(ANSWER_RE.search(r["text"]))})
    csv_out("model_trials.csv", normalized)
    mi = [{"model": m, "condition": cond, "instance_id": iid,
           **summarize([r for r in groups[m, cond] if r["instance_id"] == iid])}
          for m in MODELS for cond in CONDS for iid in ids]
    csv_out("model_item_summary.csv", mi)
    itemrows = [{"instance_id": i.instance_id, "answer": i.solution,
                 "clue_type": "axis only" if idx < 2 else "middle four" if idx < 5 else "both diagonals",
                 **{f"clue_{j}": clue for j, clue in enumerate(i.clues, 1)}} for idx, i in enumerate(items)]
    csv_out("item_inventory.csv", itemrows)
    change = []
    for m in MODELS:
        off, low, high = [sm[m, x] for x in CONDS[:3]]
        change.append(dict(model=m, off_to_low_accuracy_pp=low["accuracy_pct"]-off["accuracy_pct"],
                           low_to_high_accuracy_pp=high["accuracy_pct"]-low["accuracy_pct"],
                           high_to_low_median_output_ratio=high["median_output_tokens"]/low["median_output_tokens"],
                           high_to_low_median_wall_ratio=high["median_wall_s"]/low["median_wall_s"],
                           high_minus_low_median_reasoning_tokens=high["median_reasoning_tokens"]-low["median_reasoning_tokens"]))
    csv_out("effort_contrasts.csv", change)
    loo = []
    for m in MODELS:
        for iid in ids:
            rs = [r for r in groups[m, CONDS[0]] if r["instance_id"] != iid]
            loo.append(dict(model=m, excluded_item=iid, n=len(rs), accuracy_pct=100*sum(r["correct"] for r in rs)/len(rs)))
    csv_out("leave_one_item_out.csv", loo)
    control = [{"model": m, "submitted": cell or "unparsed", "count": n}
               for m in MODELS for cell, n in Counter(r["submitted"] for r in groups[m, CONDS[3]]).items()]
    csv_out("control_response_distribution.csv", control)
    error_cases = []
    for r in rows:
        if r["condition"] == CONDS[3] or r["correct"]:
            continue
        item = item_by_id[r["instance_id"]]
        error_cases.append(dict(model=r["model_alias"], condition=r["condition"], instance_id=r["instance_id"],
                                replicate=r["replicate"], submitted=r["submitted"], expected=item.solution,
                                violated_clue_numbers=";".join(str(j) for j, clue in enumerate(item.clues, 1)
                                                              if not _survives(r["submitted"], clue, item.n))))
    csv_out("incorrect_responses.csv", error_cases)
    counters = []
    for m in MODELS[:3]:
        for cond in CONDS:
            rs = groups[m, cond]
            raw = [r["model_usage"][r["model_reported"]]["outputTokens"] for r in rs]
            delta = [a-r["output_tokens"] for a, r in zip(raw, rs)]
            counters.append(dict(model=m, condition=cond, n=len(rs),
                                 median_primary_output_tokens=st.median(r["output_tokens"] for r in rs),
                                 median_model_usage_output_tokens=st.median(raw),
                                 rows_disagreeing=sum(x != 0 for x in delta),
                                 min_delta=min(delta), max_delta=max(delta), median_delta=st.median(delta),
                                 median_thinking_delta=st.median(r["model_usage"][r["model_reported"]].get("thinkingTokens",0)-r["thinking_tokens"] for r in rs)))
    csv_out("claude_token_counter_sensitivity.csv", counters)
    region = []
    for m in MODELS:
        for cond in CONDS[:3]:
            for label, subset in [("axis only", ids[:2]), ("region clue", ids[2:])]:
                rs = [r for r in groups[m, cond] if r["instance_id"] in subset]
                region.append(dict(model=m, condition=cond, item_group=label, **summarize(rs)))
    csv_out("item_type_summary.csv", region)
    # Human records remain private inputs; only item/cohort aggregates are exported.
    hraw = read_csv(HUMAN / "clean_unique_trials.csv")
    hmeta = json.loads((HUMAN / "analysis_results.json").read_text())
    humans = [r for r in hraw if r["condition"] == "touchstone_grid"]
    hb = defaultdict(list)
    for r in humans:
        hb[r["session_id"]].append(r)
    assert len(humans) == 108 and len(hb) == 18
    assert all(len(rs) == 6 and {r["instance_id"] for r in rs} == set(ids) for rs in hb.values())
    assert sum(int(r["correct"]) for r in humans) == 103
    hitems = []
    for iid in ids:
        rs = [r for r in humans if r["instance_id"] == iid]
        hitems.append(dict(instance_id=iid, n=len(rs), correct=sum(int(r["correct"]) for r in rs),
                           accuracy_pct=100*sum(int(r["correct"]) for r in rs)/len(rs),
                           mean_attempts=st.mean(float(r["attempts"]) for r in rs),
                           median_solve_s=st.median(float(r["solve_time_s"]) for r in rs),
                           q1_solve_s=float(np.quantile([float(r["solve_time_s"]) for r in rs], .25)),
                           q3_solve_s=float(np.quantile([float(r["solve_time_s"]) for r in rs], .75)),
                           median_orientation_s=st.median(float(r["orientation_time_s"]) for r in rs),
                           median_execution_s=st.median(float(r["execution_time_s"]) for r in rs)))
    for new, old in zip(hitems, read_csv(HUMAN / "instance_summary.csv")):
        assert new["instance_id"] == old["instance_id"] and new["correct"] == int(old["correct"])
        assert math.isclose(new["median_solve_s"], float(old["median_time_s"]))
    csv_out("human_item_context.csv", hitems)
    hsummary = dict(n_trials=len(humans), n_sessions=len(hb), correct_trials=103,
                    all_six_correct_sessions=sum(all(int(r["correct"]) for r in rs) for rs in hb.values()),
                    median_solve_s=st.median(float(r["solve_time_s"]) for r in humans),
                    median_orientation_s=st.median(float(r["orientation_time_s"]) for r in humans),
                    median_execution_s=st.median(float(r["execution_time_s"]) for r in humans),
                    mean_attempts=st.mean(float(r["attempts"]) for r in humans),
                    phase_sum_max_error_s=max(abs(float(r["solve_time_s"])-float(r["orientation_time_s"])-float(r["execution_time_s"])) for r in humans),
                    source_raw_rows=hmeta["raw_rows"], source_unique_rows=hmeta["clean_unique_rows"],
                    source_window=hmeta["collection_window_utc"])
    clue_rows = [r for r in rows if r["condition"] != CONDS[3]]
    audit = dict(completed_sessions=len(rows), clue_sessions=len(clue_rows),
                 clue_correct=sum(r["correct"] for r in clue_rows), control_sessions=180,
                 control_correct=sum(r["correct"] for r in rows if r["condition"] == CONDS[3]),
                 claude_raw_rows=len(rawc), gpt_raw_rows=len(rawg), recovered_gpt_errors=errors,
                 gpt_first_started_at=min(r["started_at"] for r in g),
                 gpt_last_started_at=max(r["started_at"] for r in g),
                 gpt_unique_threads=len({r["thread_id"] for r in g}), gpt_tool_events=sum(r["tool_events"] for r in g),
                 off_reasoning_tokens=sum(r["thinking_tokens"] for r in rows if r["condition"]==CONDS[0]),
                 marker_sensitivity_changed_correctness=sum(
                     ((f"{matches[-1][0].upper()}{matches[-1][1]}" if (matches:=ANSWER_RE.findall(r["text"])) else None)==answers[r["instance_id"]]) != r["correct"] for r in rows),
                 clue_marker_missing=sum(not ANSWER_RE.search(r["text"]) for r in clue_rows),
                 gpt_cached_input_tokens=sum(r["cached_input_tokens"] for r in g),
                 total_aux_claude_tokens=sum(r["aux_output_tokens"] for r in c),
                 source_sha256=checksums, gpt_manifest_id=manifest["manifest_id"],
                 human=hsummary, checks="All assertions passed; original CSVs reconciled; no model/network calls.",
                 software=dict(python=platform.python_version(), numpy=np.__version__, matplotlib=matplotlib.__version__))
    (DATA / "audit.json").write_text(json.dumps(audit, indent=2)+"\n")
    create_figures(groups, sm, mi, control, hitems, ids)
    # Verify every generated image is a genuine, publication-resolution PNG.
    from PIL import Image
    images = []
    for p in sorted(FIG.glob("*.png")):
        with Image.open(p) as im:
            assert im.format == "PNG" and min(im.size) >= 1000
            images.append(dict(file=p.name, width=im.width, height=im.height, dpi=list(im.info.get("dpi", []))))
    assert len(images) == 8
    (DATA / "figure_manifest.json").write_text(json.dumps(images, indent=2)+"\n")
    print(json.dumps({k:v for k,v in audit.items() if k != "source_sha256"}, indent=2))
    print("EFFORT CONTRASTS", json.dumps(change, indent=2))
    print("FIGURES", len(images))


def create_figures(groups, sm, mi, control, hitems, ids):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.titlesize": 12, "axes.labelsize": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.facecolor": "white", "figure.facecolor": "white",
                         "axes.edgecolor": "#7A8388", "text.color": "#243039",
                         "axes.labelcolor": "#243039", "xtick.color": "#394952", "ytick.color": "#394952"})
    contracts = []
    def finish(fig, filename, title, subtitle, grain, question, caveat):
        fig.suptitle(title, x=.035, y=.99, ha="left", fontsize=17, fontweight="bold")
        fig.text(.035, .935, subtitle, ha="left", va="top", fontsize=10)
        fig.savefig(FIG / filename, dpi=300, bbox_inches="tight", pad_inches=.2)
        plt.close(fig)
        contracts.append(dict(file=filename, question=question, grain=grain, source="publication/data/condition_summary.csv and model_trials.csv unless stated", filters="Completed sessions only; controls excluded unless explicitly shown", uncertainty=caveat))

    fig, axes = plt.subplots(1,3,figsize=(13,5.3),sharex=True,sharey=True)
    for ax, cond, color in zip(axes, CONDS[:3], COLORS):
        for j,m in enumerate(MODELS):
            s=sm[m,cond]; p=s["accuracy_pct"]
            ax.errorbar(p,j,xerr=[[max(0,p-s["wilson_low_pct"])],[max(0,s["wilson_high_pct"]-p)]],fmt="o",color=color,capsize=3,markersize=7)
            ax.text(2,j-.13,f'{s["correct"]}/30',fontsize=10)
        ax.set(title=CLABEL[cond],xlim=(0,103),xticks=[0,25,50,75,100],xlabel="Correct first answers (%)")
        ax.grid(axis="x",alpha=.18); ax.axhline(2.5,color="#C9CDD0",lw=.8)
    axes[0].set_yticks(range(6),[LABEL[m] for m in MODELS]);axes[0].invert_yaxis()
    fig.subplots_adjust(top=.78,left=.12,bottom=.15,wspace=.14)
    finish(fig,"01_accuracy_by_effort.png","First-answer accuracy by configured effort","Six fixed items × five repetitions = 30 sessions per point. Bars: 95% Wilson reference intervals.","Model × condition (n=30)","Which conditions solved the fixed test set?","Intervals assume Bernoulli sampling and do not capture item clustering or new-item generalization.")

    fig,ax=plt.subplots(figsize=(11,5.2))
    matrix=np.array([[sum(r["correct"] for r in groups[m,CONDS[0]] if r["instance_id"]==i) for i in ids] for m in MODELS])
    cmap=LinearSegmentedColormap.from_list("accuracy",["#F8F5E9","#BCD2DA",BLUE])
    ax.imshow(matrix,cmap=cmap,vmin=0,vmax=5,aspect="auto")
    for y in range(6):
        for x in range(6): ax.text(x,y,f"{matrix[y,x]}/5",ha="center",va="center",color="white" if matrix[y,x]>=4 else "#243039",fontweight="bold")
    ax.set_xticks(range(6),[f"{i}\n"+("Axis" if j<2 else "Middle four" if j<5 else "Diagonals") for j,i in enumerate(ids)])
    ax.set_yticks(range(6),[LABEL[m] for m in MODELS]);ax.axvline(1.5,color="white",lw=2);ax.axhline(2.5,color="white",lw=2)
    fig.subplots_adjust(top=.79,left=.14,bottom=.16)
    finish(fig,"02_thinking_off_item_accuracy.png","Thinking-off accuracy on each puzzle","Cell labels give correct answers / five repetitions. Low and high effort achieved 5/5 in every cell.","Model × item, thinking off (n=5)","Where did errors concentrate?","Fixed items; no uncertainty claim from five repetitions.")

    for field,filename,title,xlabel,log in [
        ("output_tokens","03_output_token_distributions.png","Reported output-token distributions","Output tokens, including reasoning (log scale)",True),
        ("wall_ms","05_wall_latency_distributions.png","End-to-end CLI latency distributions","Wall time per session (seconds)",False),
        ("visible_characters","04_visible_response_lengths.png","Visible response length by effort","Characters in the saved answer text (log scale)",True)]:
        fig,axes=plt.subplots(1,3,figsize=(13,5.6),sharey=True,sharex=True)
        for ax,cond,color in zip(axes,CONDS[:3],COLORS):
            values=[[len(r["text"]) if field=="visible_characters" else r[field]/(1000 if field=="wall_ms" else 1) for r in groups[m,cond]] for m in MODELS]
            box=ax.boxplot(values,orientation="horizontal",tick_labels=[LABEL[m] for m in MODELS],patch_artist=True,showfliers=True,
                           medianprops=dict(color="#172832",lw=1.4),flierprops=dict(marker=".",markersize=3,alpha=.5))
            for patch in box["boxes"]: patch.set(facecolor=color,alpha=.5)
            if log: ax.set_xscale("log")
            else: ax.set_xlim(left=0)
            ax.set_title(CLABEL[cond]);ax.grid(axis="x",alpha=.2);ax.axhline(3.5,color="#C9CDD0",lw=.8)
        axes[0].set_yticks(range(1,7), [LABEL[m] for m in MODELS])
        axes[0].tick_params(axis="y", labelleft=True)
        axes[0].invert_yaxis();fig.supxlabel(xlabel,y=.02)
        fig.subplots_adjust(top=.78,left=.12,bottom=.16,wspace=.12)
        sub="Each box: 30 sessions; line = median, box = IQR, whiskers = 1.5×IQR, dots = outliers."
        finish(fig,filename,title,sub,"Model × condition; distributions of 30 sessions",f"How does {field} vary across models and effort?", "Output tokens are provider-specific telemetry; visible text excludes hidden reasoning; wall includes startup/transport, with unequal concurrency.")

    fig,ax=plt.subplots(figsize=(13,5.1))
    cells=[f"{c}{r}" for c in "ABCD" for r in range(1,5)]+["unparsed"]
    cm=np.array([[sum(x["count"] for x in control if x["model"]==m and x["submitted"]==cell) for cell in cells] for m in MODELS])
    ax.imshow(cm,cmap=LinearSegmentedColormap.from_list("counts",["#F2F5F6",BLUE]),vmin=0,vmax=30,aspect="auto")
    for y in range(6):
        for x in range(17):
            if cm[y,x]:ax.text(x,y,str(cm[y,x]),ha="center",va="center",color="white" if cm[y,x]>=15 else "#243039",fontsize=10)
    ax.set_xticks(range(17),cells,rotation=45,ha="right");ax.set_yticks(range(6),[LABEL[m] for m in MODELS]);ax.set_xlabel("Parsed response (30 no-clue sessions per model)")
    ax.axhline(2.5,color="white",lw=2)
    fig.subplots_adjust(top=.78,left=.12,bottom=.2)
    finish(fig,"06_no_clue_response_distribution.png","No-clue response distribution","A1 is never a correct target in this item set. Blank cells are zero; one GPT Sol response was unparsed.","Model × submitted cell, no-clue control (n=30/model)","Do controls behave like uniform random guessing?","Control correctness depends on target distribution and response bias; passing a threshold does not prove no leakage.")

    fig,axes=plt.subplots(1,2,figsize=(11.5,5.5),sharey=True)
    for ax,metric,label in zip(axes,["median_output_tokens","median_wall_s"],["Median output tokens","Median wall seconds"]):
        for j,m in enumerate(MODELS):
            low=sm[m,CONDS[1]][metric];high=sm[m,CONDS[2]][metric]
            ax.plot([low,high],[j,j],color="#A7AFB4",lw=2)
            ax.plot(low,j,"s",color=GOLD,ms=7);ax.plot(high,j,"^",color=ORANGE,ms=8)
            ax.annotate(f"{high/low:.2f}×",(max(low,high),j),xytext=(7,0),textcoords="offset points",va="center",fontsize=10)
        ax.set_xlabel(label);ax.grid(axis="x",alpha=.2)
        if metric=="median_output_tokens":ax.set_xscale("log");ax.set_xlim(35,2000)
        else:ax.set_xlim(0,max(sm[m,CONDS[2]][metric] for m in MODELS)*1.3)
    axes[0].set_yticks(range(6),[LABEL[m] for m in MODELS]);axes[0].invert_yaxis()
    axes[0].plot([],[],"s",color=GOLD,label="Low");axes[0].plot([],[],"^",color=ORANGE,label="High")
    fig.legend(*axes[0].get_legend_handles_labels(),loc="upper right",bbox_to_anchor=(.99,.89),ncol=2,frameon=False)
    fig.subplots_adjust(top=.78,left=.13,bottom=.16,wspace=.22)
    finish(fig,"07_low_high_resource_contrast.png","Low-to-high effort resource changes","Each point summarizes 30 sessions. Labels: high / low median. Both settings achieved 100% accuracy for every model.","Model × condition median; high/low descriptive ratio","Did high effort improve observed accuracy or change resource use?","Ratios of medians are descriptive, not paired treatment effects; model effort settings are not standardized compute budgets.")

    fig,axes=plt.subplots(1,2,figsize=(11.5,5.7),sharey=True)
    for j,h in enumerate(hitems):
        axes[0].barh(j,h["accuracy_pct"],color=BLUE,height=.55)
        axes[0].text(2,j,f'{h["correct"]}/18',va="center",color="white",fontweight="bold")
        axes[1].errorbar(h["median_solve_s"],j,xerr=[[h["median_solve_s"]-h["q1_solve_s"]],[h["q3_solve_s"]-h["median_solve_s"]]],fmt="o",color=BLUE,capsize=4)
        axes[1].annotate(f'{h["median_solve_s"]:.1f} s',(h["median_solve_s"],j),xytext=(0,10),textcoords="offset points",ha="center",fontsize=10)
    axes[0].set(xlim=(0,105),xlabel="Correct within up to three attempts (%)")
    axes[1].set(xlim=(0,205),xlabel="Observed task time: median and IQR (seconds)")
    for ax in axes:ax.grid(axis="x",alpha=.2)
    axes[0].set_yticks(range(6),ids);axes[0].invert_yaxis()
    fig.subplots_adjust(top=.76,left=.09,bottom=.18,wspace=.2)
    finish(fig,"08_human_context.png","Human prototype outcomes on the same six items","18 screen-reader sessions, 108 item trials. Human outcomes include interface use and up to three attempts.","Human item aggregate (n=18/item); human_item_context.csv","What human evidence contextualizes this model benchmark?","Whiskers are IQR, not confidence intervals. Repeated participants and fixed order preclude an independent human/model speed comparison.")
    (DATA/"chart_contracts.json").write_text(json.dumps(contracts,indent=2)+"\n")


if __name__ == "__main__":
    main()
