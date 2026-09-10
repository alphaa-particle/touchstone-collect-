#!/usr/bin/env python3
"""Offline GPT grading. No model calls. Answers are first consulted here."""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from gpt_transport import (CONDITIONS, HARNESS_VERSION, classify_strategy,
                           digest, parse_answer, parse_events)

HERE = Path(__file__).resolve().parent
DEFAULT_RUNS = HERE / "output" / "gpt_cli_arm_runs.jsonl"


def key(row):
    return tuple(row[k] for k in ("model_alias", "condition", "instance_id", "replicate"))


def integrity(path: Path) -> tuple[list[dict], dict, int]:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    identity = {k: v for k, v in manifest.items()
                if k not in {"manifest_id", "created_at", "authentication", "preflight"}}
    if digest(json.dumps(identity, sort_keys=True)) != manifest["manifest_id"]:
        raise ValueError("Manifest checksum mismatch")
    if manifest["harness_version"] != HARNESS_VERSION or manifest["authentication"] != "chatgpt":
        raise ValueError("Wrong harness or authentication")
    expected_audits = {(m, e) for m in manifest["models"] for e in ("none", "low", "high")}
    audits = manifest["preflight"]["wire_audits"]
    if {(a["model"], a["effort"]) for a in audits} != expected_audits:
        raise ValueError("Missing wire audits")
    if any(a["tools"] != [] or not all(a[k] for k in
           ("system_matches", "user_matches", "no_previous_response")) for a in audits):
        raise ValueError("Wire audit did not certify isolated requests")
    probes = manifest["preflight"]["subscription_probes"]
    if {(p["model"], p["effort"]) for p in probes} != expected_audits:
        raise ValueError("Missing subscription probes")
    for probe in probes:
        parse_events(probe["events"], probe["effort"])
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    complete, errors, threads = {}, 0, set()
    for row in rows:
        if row.get("manifest_id") != manifest["manifest_id"] or row.get("harness_version") != HARNESS_VERSION:
            raise ValueError("Mixed manifest/harness rows")
        if row.get("error"):
            errors += 1
            continue
        if key(row) in complete:
            raise ValueError("Duplicate completed session")
        if row["effort"] != CONDITIONS[row["condition"]]:
            raise ValueError("Condition/effort mismatch")
        parsed = parse_events(row["events"], row["effort"])
        if parsed["thread_id"] in threads:
            raise ValueError("Conversation reused")
        threads.add(parsed["thread_id"])
        if (row["text"] != parsed["text"] or row["num_turns"] != 1 or
                row["tool_events"] != 0 or row["usage"] != parsed["usage"] or
                row["output_tokens"] != parsed["usage"]["output_tokens"] or
                row["thinking_tokens"] != parsed["usage"]["reasoning_output_tokens"] or
                row["input_tokens"] != parsed["usage"]["input_tokens"] or
                row["cached_input_tokens"] != parsed["usage"]["cached_input_tokens"] or
                row["parse_failed"] != (parse_answer(parsed["text"]) is None) or
                row["submitted"] != parse_answer(parsed["text"]) or
                row["strategy"] != classify_strategy(parsed["text"])):
            raise ValueError("Saved metrics differ from the original event stream")
        if not isinstance(row["wall_ms"], (int, float)) or row["wall_ms"] <= 0:
            raise ValueError("Missing/invalid measured wall latency")
        if row["thinking_tokens"] > row["output_tokens"]:
            raise ValueError("Reasoning tokens exceed total output tokens")
        complete[key(row)] = row
    expected = {key(s) for s in manifest["plan"]}
    if set(complete) != expected:
        raise ValueError(f"Incomplete/extra sessions: {len(expected-set(complete))} missing, "
                         f"{len(set(complete)-expected)} extra. Resume collection first.")
    return list(complete.values()), manifest, errors


def grade(path: Path):
    rows, manifest, errors = integrity(path)
    # Imports that can read the answer bundle are deliberately below the
    # completed-collection gates and never imported by the runner.
    from items import load_items, verify
    from prepare_gpt_inputs import export
    _, items = load_items()
    if verify(items):
        raise ValueError("Independent solver disagrees with source key")
    exported = export()
    expected_export = json.dumps(exported, indent=2, ensure_ascii=False) + "\n"
    if digest(expected_export) != manifest["inputs_sha256"]:
        raise ValueError("Prompt export no longer matches the source puzzles")
    prompts = {i["instance_id"]: i for i in exported["items"]}
    answers = {i.instance_id: i.solution for i in items}
    for row in rows:
        clues = row["condition"] != "control_no_clues"
        prompt = prompts[row["instance_id"]]["prompt" if clues else "control_prompt"]
        if (row["clues_shown"] != clues or row["is_practice"] or
                digest(prompt) != row["prompt_sha256"] or
                digest(exported["system"]) != row["system_sha256"]):
            raise ValueError("Prompt hash/condition mismatch")
        row["correct"] = row["submitted"] == answers[row["instance_id"]]
    controls = []
    for model in [*manifest["models"], "POOLED"]:
        subset = [r for r in rows if r["condition"] == "control_no_clues"
                  and (model == "POOLED" or r["model_alias"] == model)]
        hits = sum(r["correct"] for r in subset)
        rate = 100 * hits / len(subset) if subset else None
        if rate is None or rate > 25:
            raise ValueError(f"No-clues control failed for {model}: {hits}/{len(subset)}; "
                             "refusing to publish accuracy tables")
        controls.append({"model": model, "correct": hits, "sessions": len(subset),
                         "solve_rate_percent": round(rate, 2), "gate": "PASS"})
    return rows, items, manifest, errors, controls


def median(rows, field, scale=1):
    return round(st.median(r[field] for r in rows) / scale, 2)


def summarize(rows):
    hits = sum(r["correct"] for r in rows)
    return {
        "sessions": len(rows), "correct": hits,
        "solve_rate_percent": round(100 * hits / len(rows), 2),
        "mean_attempts": 1, "median_output_tokens": median(rows, "output_tokens"),
        "median_thinking_tokens": median(rows, "thinking_tokens"),
        "median_input_tokens_including_harness": median(rows, "input_tokens"),
        "median_cached_input_tokens": median(rows, "cached_input_tokens"),
        "median_api_latency_s": "", "median_wall_latency_s": median(rows, "wall_ms", 1000),
        "parse_failures": sum(r["parse_failed"] for r in rows),
        "enumeration_percent": round(100 * sum(r["strategy"]["looks_like_enumeration"] for r in rows) / len(rows), 2),
        "median_cells_named": round(st.median(r["strategy"]["distinct_cells_named"] for r in rows), 1),
        "output_tokens_per_solve": round(sum(r["output_tokens"] for r in rows) / hits, 2) if hits else "",
        "wall_latency_s_per_solve": round(sum(r["wall_ms"] for r in rows) / 1000 / hits, 2) if hits else "",
        "cost_per_solve_usd": "",
    }


def write_csv(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |",
                       "|" + "|".join("---" for _ in headers) + "|"] +
                      ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    ap.add_argument("--out-dir", type=Path)
    args = ap.parse_args()
    rows, items, manifest, errors, controls = grade(args.runs)
    buckets = defaultdict(list)
    for row in rows:
        buckets[(row["model_alias"], row["condition"])].append(row)
    summary = [{"model_alias": m, "condition": c, **summarize(buckets[(m, c)])}
               for m in manifest["models"] for c in CONDITIONS]
    real = [r for r in rows if r["condition"] != "control_no_clues"]
    # Reuse the original per-item/human comparison definitions unchanged.
    from grade_runs import item_summary
    by_item = item_summary(real, items)
    model_items = []
    for m in manifest["models"]:
        for c in list(CONDITIONS)[:3]:
            for item in items:
                subset = [r for r in buckets[(m, c)] if r["instance_id"] == item.instance_id]
                model_items.append({"model_alias": m, "condition": c,
                                    "instance_id": item.instance_id, **summarize(subset)})
    out = args.out_dir or args.runs.parent
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "gpt_cli_arm_condition_summary.csv", summary)
    write_csv(out / "gpt_cli_arm_item_summary.csv", by_item)
    write_csv(out / "gpt_cli_arm_model_item_summary.csv", model_items)
    diagnostics = {"manifest_id": manifest["manifest_id"], "completed_sessions": len(rows),
                   "recorded_error_attempts": errors, "unique_threads": len(rows),
                   "tool_events": 0, "thinking_off_reasoning_tokens": sum(r["thinking_tokens"] for r in rows if r["condition"] == "thinking_off"),
                   "controls": controls}
    (out / "gpt_cli_arm_diagnostics.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
    hits = sum(r["correct"] for r in real)
    report = ["# GPT subscription benchmark\n",
              f"{hits}/{len(real)} clue-bearing sessions solved ({100*hits/len(real):.2f}%). "
              f"{len(rows)} total sessions, including controls; {manifest['replicates']} repetitions per item and condition.\n",
              "## By model and condition\n",
              table(["Model", "Condition", "N", "Solve %", "Median output tokens", "Median reasoning tokens", "Median wall seconds", "Parse failures"],
                    [[r[k] for k in ("model_alias", "condition", "sessions", "solve_rate_percent", "median_output_tokens", "median_thinking_tokens", "median_wall_latency_s", "parse_failures")] for r in summary]),
              "\n## No-clues control\n",
              table(["Model", "Correct", "N", "%", "Gate"], [list(r.values()) for r in controls]),
              "\nThe predeclared gate is at most 25% correct, checked per model and pooled. "
              "Uniform random guessing would average 6.25% on a 4x4 grid. These fixed items and model guesses are not necessarily uniform or independent; "
              "passing this diagnostic alone does not prove absence of contamination.\n",
              "## Isolation and comparability\n",
              "- Same six canonical puzzles, prompt text, answer parser, visible-strategy heuristics and single-attempt design as the Claude subscription arm. "
              "This is not the three-attempt API arm.\n"
              "- Collection reads only a strictly allowlisted prompt export. Preparation and offline grading are separate processes. "
              "No answer key, report, prior result, or correctness feedback is submitted.\n"
              "- Fresh ephemeral CLI conversation and empty working directory for every attempt. User configuration, project instructions, "
              "skills, memories, plugins, MCP and model tools are disabled. A tool-only catalog override also disables the model's built-in tool selection.\n"
              "- Before collection, a localhost fixture checks the actual serialized request for each model/effort: no tools (including additional-tools items), "
              "only the supplied base instructions and user prompt, no previous response. Every real result's JSON event stream is checked for non-text/tool activity. "
              "The fixture uses a local provider; it does not capture authenticated production traffic.\n"
              "- `thinking_off` explicitly requests `none`; every accepted off run reports zero reasoning tokens. Low/high are requested explicitly. "
              "A model may choose zero reasoning tokens even when reasoning is enabled.\n"
              "- Model IDs are exact configured/requested IDs, checked in local wire audits and subscription readiness probes. "
              "Codex JSON output does not expose an independent server-reported model ID; none is invented.\n"
              "- Output and reasoning counters come directly from Codex `turn.completed.usage`; reasoning is a subset of total output. "
              "Input/cache counts include CLI overhead. Strategy metrics inspect the visible answer only, not hidden reasoning.\n"
              f"- Latency is end-to-end CLI wall time with {manifest['workers']} concurrent worker(s), including startup and transport overhead. "
              "API-only latency and dollar cost per solve are unavailable and left blank, never reported as zero. "
              "All model calls use ChatGPT subscription authentication.\n"
              f"- {errors} failed collection attempts recorded; each planned session must have exactly one completed result before grading.\n",
              "## Provenance\n",
              f"CLI: `{manifest['cli_version']}`. Collection created: `{manifest['created_at']}`.\n\n"
              f"Manifest SHA256: `{manifest['manifest_id']}`. "
              "See the matching `.manifest.json` for code/input/catalog hashes, request audits, readiness probes and the full plan.\n\n"
              "[Subscription authentication](https://learn.chatgpt.com/docs/auth), "
              "[Codex configuration schema](https://developers.openai.com/codex/config-schema.json).\n"]
    (out / "gpt_cli_arm_tables.md").write_text("\n".join(report))
    print(f"Graded {len(rows)} sessions; {hits}/{len(real)} clue-bearing solves -> {out}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        raise SystemExit(f"REFUSING TO GRADE: {exc}")
