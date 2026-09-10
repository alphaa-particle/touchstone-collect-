#!/usr/bin/env python3
"""BLIND subscription arm — solve behaviour, run through the Claude Code CLI.

This runner never learns the answers. It records what each model submitted and
nothing else; correctness is computed afterwards by `grade_runs.py`. That split
is deliberate — see LEAKAGE below.

LEAKAGE — why this file is shaped the way it is
-----------------------------------------------
The first version of this arm invoked the CLI with cwd set to the benchmark
directory, and under `--restricted` the built-in file tools survive. A probe
confirmed the consequence: asked for the solution to I0009, the model read
`MODEL_BENCHMARK_REPORT.md` out of that directory and answered "C2" from the
solutions table. Every result collected that way was discarded.

Four independent defences now apply, in order of strength:

  1. `--tools ""` removes every built-in tool, so there is no file access at
     all. Verified: with it set, the model emits a fake tool-call block as plain
     text and never receives file content.
  2. Each call runs with cwd set to a **fresh empty temporary directory**, so
     there is nothing to read even if a tool were somehow available, and no
     CLAUDE.md is discoverable.
  3. `--restricted --strict-mcp-config` on top: no code-running tools, no
     WebFetch, no MCP servers, and user/project/local settings ignored.
  4. This process holds no solutions. `items.py` is imported for clue text only;
     the runner never reads `.solution`, so it cannot leak what it does not have,
     and no output row contains an answer key.

A fifth, empirical check runs as its own condition: `control_no_clues` presents
the item with the clue list removed. A model has to guess — 6.25% on one attempt.
If any model scores materially above that, the answers are reaching it by some
route this file has not anticipated, and the whole arm is void. Treat that
control as the arm's validity gate, not as a curiosity.

CONDITIONS
----------
`MAX_THINKING_TOKENS=0` disables thinking through the CLI (verified: Opus
returned 4 output tokens, 0 thinking). That makes the API arm's `answer_only`
floor-cost condition reachable here after all.

  thinking_off   MAX_THINKING_TOKENS=0            true floor cost
  effort_low     --effort low                     cheapest thinking setting
  effort_high    --effort high                     CLI default depth
  control_no_clues  --effort high, clues removed  leakage gate

    .venv/bin/python run_cli_arm.py --dry-run
    .venv/bin/python run_cli_arm.py --conditions thinking_off effort_low effort_high
    .venv/bin/python run_cli_arm.py --conditions control_no_clues --replicates 3
    .venv/bin/python grade_runs.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from items import Item, load_items
from prompts import item_prompt, system_prompt

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
RUNS = OUT / "cli_arm_runs.jsonl"

CLI = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
MODELS = ["haiku", "sonnet", "opus"]

ALIAS_PREFIX = {"haiku": "claude-haiku", "sonnet": "claude-sonnet",
                "opus": "claude-opus"}

CONDITIONS: dict[str, dict] = {
    "thinking_off": {"effort": None, "max_thinking_tokens": "0", "clues": True},
    "effort_low": {"effort": "low", "max_thinking_tokens": None, "clues": True},
    "effort_high": {"effort": "high", "max_thinking_tokens": None, "clues": True},
    # Validity gate. No clues, so the item is unsolvable by reasoning.
    "control_no_clues": {"effort": "high", "max_thinking_tokens": None,
                         "clues": False},
}

ANSWER_RE = re.compile(r"ANSWER\s*:\s*\**\s*([A-Ga-g])\s*([1-7])", re.IGNORECASE)
BOX_RE = re.compile(r"\b([A-Ga-g])\s?([1-7])\b")
CELL_RE = re.compile(r"\b([A-D])([1-4])\b")


def parse_answer(text: str) -> str | None:
    """Extract the submitted box. Mirrors what the two radio groups captured."""
    m = ANSWER_RE.findall(text) or BOX_RE.findall(text)
    if not m:
        return None
    col, row = m[-1]
    return f"{col.upper()}{row}"


def classify_strategy(text: str) -> dict:
    """Enumeration versus symbolic intersection — see the report, §6A.2."""
    cells = {f"{c}{r}" for c, r in CELL_RE.findall(text)}
    axis = len(re.findall(
        r"\b(column|row)s?\b.{0,40}\b(only|must be|remaining|left|eliminat)",
        text, re.IGNORECASE))
    return {"distinct_cells_named": len(cells), "axis_elimination_phrases": axis,
            "looks_like_enumeration": len(cells) >= 10}


def strip_clues(prompt: str) -> str:
    """Remove the clue block. Everything else — heading, preamble, question,
    option lists — is left byte-identical, so the control differs from the real
    condition in exactly one respect."""
    lines, out, skipping = prompt.split("\n"), [], False
    for ln in lines:
        if ln == "Clues":
            skipping = True
            out.append("Clues")
            out.append("(none provided)")
            continue
        if skipping:
            if re.match(r"^\d+\.\s", ln):
                continue
            skipping = False
        out.append(ln)
    return "\n".join(out)


def main_model(model_usage: dict, alias: str) -> tuple[str | None, int]:
    """(model that did the work, auxiliary output tokens).

    `modelUsage` also carries a Claude Code auxiliary Haiku entry that fires on
    every request regardless of --model, and it is inserted first — so keys()[0]
    mislabels every non-Haiku session. Match the requested alias instead.
    """
    prefix = ALIAS_PREFIX[alias]
    main = next((k for k in model_usage if k.startswith(prefix)), None)
    aux = sum(v.get("outputTokens", 0) or 0
              for k, v in model_usage.items() if k != main)
    return main, aux


def call_cli(model: str, prompt: str, system: str, cfg: dict,
             timeout: float = 600.0) -> tuple[dict, float]:
    cmd = [CLI, "-p", "--model", model,
           "--restricted",          # no code-running tools, settings ignored
           "--strict-mcp-config",   # no MCP servers
           "--tools", "",           # NO TOOLS AT ALL — the leakage fix
           "--output-format", "json", "--max-turns", "1",
           "--system-prompt", system]
    if cfg["effort"] is not None:
        cmd += ["--effort", cfg["effort"]]
    cmd.append(prompt)

    env = dict(os.environ)
    if cfg["max_thinking_tokens"] is not None:
        env["MAX_THINKING_TOKENS"] = cfg["max_thinking_tokens"]

    # Fresh empty cwd per call: nothing to read, no CLAUDE.md to discover.
    with tempfile.TemporaryDirectory(prefix="tsblind_") as sandbox:
        started = time.perf_counter()
        # stdin=DEVNULL: without it the child inherits this process's stdin,
        # and as a background job that never delivers — the CLI then waits 3s
        # and exits 1. That silently killed 105 sessions once.
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL,
                              cwd=sandbox, env=env)
        wall_ms = (time.perf_counter() - started) * 1000.0

    if proc.returncode != 0:
        raise RuntimeError(
            f"cli exit {proc.returncode}: {(proc.stderr or proc.stdout)[:400]}")
    try:
        return json.loads(proc.stdout), wall_ms
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"unparseable cli output: {proc.stdout[:400]}") from exc


def run_session(model: str, condition: str, item: Item, replicate: int,
                position: int, of: int) -> dict:
    """One blind attempt. No solution is read, so nothing here can grade."""
    cfg = CONDITIONS[condition]
    prompt = item_prompt(item, position, of)
    if not cfg["clues"]:
        prompt = strip_clues(prompt)

    session = {
        "arm": "cli_subscription_blind",
        "harness_version": 2,
        "model_alias": model,
        "model_reported": None,
        "model_verified": False,
        "condition": condition,
        "effort": cfg["effort"] or "n/a",
        "max_thinking_tokens": cfg["max_thinking_tokens"],
        "clues_shown": cfg["clues"],
        "instance_id": item.instance_id,
        "replicate": replicate,
        "is_practice": item.is_practice,
        "submitted": None,
        "parse_failed": None,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "aux_output_tokens": 0,
        "api_ms": 0.0,
        "wall_ms": 0.0,
        "stop_reason": None,
        "num_turns": None,
        "permission_denials": None,
        "strategy": None,
        "text": None,
        "error": None,
    }

    try:
        data, wall = call_cli(model, prompt, system_prompt("extended_thinking"), cfg)
    except Exception as exc:
        session["error"] = f"{type(exc).__name__}: {exc}"
        return session

    text = data.get("result") or ""
    usage = data.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    mu = data.get("modelUsage") or {}
    reported, aux = main_model(mu, model)

    session.update({
        "model_reported": reported,
        "model_verified": reported is not None,
        "submitted": parse_answer(text),
        "parse_failed": parse_answer(text) is None,
        "output_tokens": usage.get("output_tokens", 0),
        "thinking_tokens": details.get("thinking_tokens", 0),
        "aux_output_tokens": aux,
        "api_ms": data.get("duration_api_ms", 0),
        "wall_ms": wall,
        "stop_reason": data.get("stop_reason"),
        "num_turns": data.get("num_turns"),
        # Non-empty denials or num_turns > 1 would mean a tool was reached.
        "permission_denials": data.get("permission_denials"),
        "model_usage": mu,
        "strategy": classify_strategy(text),
        "text": text,
    })
    return session


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("error"):
            continue  # errored sessions are retried, never counted as done
        done.add(f"{r['model_alias']}|{r['condition']}|{r['instance_id']}"
                 f"|{r['replicate']}")
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--conditions", nargs="+", default=[
        "thinking_off", "effort_low", "effort_high"], choices=list(CONDITIONS))
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--include-practice", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=RUNS)
    args = ap.parse_args()

    practice, canonical = load_items()
    items = ([practice] if args.include_practice else []) + canonical
    plan = [(m, c, it, r) for m in args.models for c in args.conditions
            for it in items for r in range(1, args.replicates + 1)]

    if args.dry_run:
        print(f"{len(plan)} sessions: {len(args.models)} models x "
              f"{len(args.conditions)} conditions x {len(items)} items x "
              f"{args.replicates} replicates")
        print(f"CLI: {CLI}")
        for c in args.conditions:
            cfg = CONDITIONS[c]
            print(f"  {c:<18} effort={cfg['effort'] or '-':<5} "
                  f"MAX_THINKING_TOKENS={cfg['max_thinking_tokens'] or '-':<4} "
                  f"clues={'yes' if cfg['clues'] else 'NO (validity gate)'}")
        print("\nBlind: this runner holds no solutions. Grade with grade_runs.py.")
        print("Isolation: --tools \"\" (no tools), fresh empty cwd per call,")
        print("           --restricted --strict-mcp-config, --max-turns 1.")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(args.out)
    if done:
        print(f"Resuming: {len(done)} sessions already recorded.")
    todo = [p for p in plan
            if f"{p[0]}|{p[1]}|{p[2].instance_id}|{p[3]}" not in done]

    started = time.time()
    with args.out.open("a") as fh:
        for n, (model, condition, item, replicate) in enumerate(todo, start=1):
            position = 0 if item.is_practice else canonical.index(item) + 1
            s = run_session(model, condition, item, replicate, position,
                            len(canonical))
            fh.write(json.dumps(s) + "\n")
            fh.flush()
            if s["error"]:
                flag = "ERR "
            elif not s["model_verified"]:
                flag = "BADMODEL"
            else:
                flag = "ok  "
            print(f"[{n}/{len(todo)}] {flag} {model:<7} {condition:<17} "
                  f"{item.instance_id} r{replicate}  "
                  f"sub={str(s['submitted']):<5} "
                  f"{s['output_tokens']:>5} out ({s['thinking_tokens']:>5} th)  "
                  f"turns={s['num_turns']}  {s['api_ms'] / 1000:>5.1f}s"
                  + (f"  {s['error'][:70]}" if s["error"] else ""), flush=True)

    print(f"\n{len(todo)} sessions in {(time.time() - started) / 60:0.1f} min "
          f"-> {args.out}")
    print("Next: .venv/bin/python grade_runs.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
