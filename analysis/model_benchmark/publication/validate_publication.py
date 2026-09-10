#!/usr/bin/env python3
"""Validate source provenance, key numerical findings, Markdown links and PNGs."""
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
REPO = BENCH.parents[1]
DATA = HERE / "data"
REPORT = BENCH / "COMPARATIVE_BENCHMARK_REPORT.md"


def read_csv(name):
    with (DATA / name).open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    audit = json.loads((DATA / "audit.json").read_text())
    for name, expected in audit["source_sha256"].items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == expected, name
    trials = read_csv("model_trials.csv")
    assert len(trials) == 720
    assert len({tuple(r[k] for k in ["model_alias", "condition", "instance_id", "replicate"]) for r in trials}) == 720
    clues = [r for r in trials if r["condition"] != "control_no_clues"]
    controls = [r for r in trials if r["condition"] == "control_no_clues"]
    assert len(clues) == 540 and sum(r["correct"] == "True" for r in clues) == 510
    assert len(controls) == 180 and sum(r["correct"] == "True" for r in controls) == 1
    assert sum(r["correct"] == "True" and r["has_answer_marker"] == "True" for r in clues) == 507
    summary = read_csv("condition_summary.csv")
    assert len(summary) == 24 and all(int(r["n"]) == 30 for r in summary)
    for row in summary:
        rs = [r for r in trials if r["model_alias"] == row["model"] and r["condition"] == row["condition"]]
        assert sum(r["correct"] == "True" for r in rs) == int(row["correct"])
        assert sum(int(r["output_tokens"]) for r in rs) == int(row["sum_output_tokens"])
        assert sum(int(r["thinking_tokens"]) for r in rs) == int(row["sum_reasoning_tokens"])
    errors = read_csv("incorrect_responses.csv")
    assert len(errors) == 30 and all(r["condition"] == "thinking_off" for r in errors)
    assert Counter(r["instance_id"] for r in errors) == {"I0011": 4, "I0012": 1, "I0013": 10, "I0014": 15}
    item_key = {r["instance_id"]: r for r in read_csv("item_inventory.csv")}
    for r in errors:
        clue = item_key[r["instance_id"]]["clue_" + r["violated_clue_numbers"]]
        assert "middle" in clue or "diagonal" in clue
    assert sum(int(r["correct"]) for r in read_csv("human_item_context.csv")) == 103
    assert len(read_csv("model_item_summary.csv")) == 144
    assert len(read_csv("gpt_input_usage.csv")) == 12
    # New data exports must not duplicate participant/session identifiers.
    for p in DATA.glob("*.csv"):
        with p.open(newline="") as f:
            headers = next(csv.reader(f))
        assert not {"participant_id", "session_id", "trial_id", "trial_pk"}.intersection(headers), p.name
    report = REPORT.read_text()
    links = re.findall(r"\]\(([^)]+)\)", report)
    local_links = [x for x in links if not x.startswith(("https://", "http://", "#"))]
    for target in local_links:
        assert (BENCH / unquote(target.split("#", 1)[0])).exists(), target
    figure_paths = re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", report)
    assert len(figure_paths) == len(set(figure_paths)) == 8
    assert re.findall(r"\*\*Figure (\d+)\.", report) == [str(i) for i in range(1,9)]
    table_labels = re.findall(r"\*\*Table ([A-Z]?\d+)\.", report)
    assert table_labels == [str(i) for i in range(1,23)] + ["B1", "B2", "C1"]
    # Catch broken Markdown tables without needing an HTML report renderer.
    active_columns = None
    for line in report.splitlines():
        if line.startswith("| "):
            columns = len(re.split(r"(?<!\\)\|", line))
            if active_columns is None:
                active_columns = columns
            assert columns == active_columns, line
        else:
            active_columns = None
    from PIL import Image
    images = []
    for target in figure_paths:
        p = BENCH / target
        with Image.open(p) as im:
            assert im.format == "PNG" and min(im.size) >= 1000
            assert all(abs(dpi - 300) < 1 for dpi in im.info["dpi"])
            im.verify()
        images.append({"file": target, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    assert not list(HERE.rglob("*.html")) and not list(HERE.rglob("*.pdf"))
    receipt = {
        "status": "PASS", "source_files_verified": len(audit["source_sha256"]),
        "completed_model_sessions": len(trials), "clue_correct": 510,
        "marker_required_clue_correct": 507, "control_correct": 1,
        "numbered_tables": len(table_labels), "png_figures": len(images),
        "local_links_verified": len(local_links),
        "report_sha256": hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        "validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "figures": images,
        "visual_review": "All eight plots inspected; model labels and the effort legend corrected before final validation."
    }
    (DATA / "validation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k:v for k,v in receipt.items() if k != "figures"}, indent=2))


if __name__ == "__main__":
    main()
