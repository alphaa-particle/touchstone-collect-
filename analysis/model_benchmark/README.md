# Model benchmark — Claim D

Measures how language models solve the **same six band-2 grid-localisation items** the
screen-reader cohort solved. Every completed run used **subscription command-line tools, not a
paid API**: Claude Code on a Claude subscription (Claude Haiku 4.5, Sonnet 5, Opus 5) and the Codex
CLI on a ChatGPT subscription (GPT-5.6 Luna, Terra, Sol).

**Start with [COMPARATIVE_BENCHMARK_REPORT.md](COMPARATIVE_BENCHMARK_REPORT.md).** It is the
audited analysis of all 720 completed sessions, rebuilt offline from `output/` by the scripts in
`publication/`. `MODEL_BENCHMARK_REPORT.md` is the earlier Claude-only report; it is superseded
and kept for its difficulties log and the leakage incident in §8.16.

## What "cost" means here

Subscriptions are not billed per call, so no exact dollar cost exists for any session. Two
list-price equivalents can be computed from logged usage, at Haiku 4.5 $1/$5, Sonnet 5 $2/$10 and
Opus 5 $5/$25 per million input/output tokens:

| Estimate | How it is computed | All 360 Claude sessions |
|---|---|---|
| Upper bound | Claude Code's own `costUSD` in each session's `model_usage`, which includes the CLI's context overhead | ≈ $3.10 |
| Lower bound | About 400 prompt tokens plus the measured output tokens, at list price | ≈ $1.38 |

For each model's cheapest setting (Sonnet 5 at low effort, Haiku 4.5 with thinking off, Opus 5 at
low effort) this brackets roughly $1.5–12 per 1,000 solves. Codex reports
token counts but no cost: the 360 GPT sessions used 100,330 input and 32,477 output tokens, 28,650
of them reasoning. Report any per-solve figure as a list-price equivalent, never as money spent.

## Run

Python 3.12 is used below; the collection and grading scripts need only the standard library.

```bash
cd touchstone-collect/analysis/model_benchmark
python3.12 items.py            # verify items, re-derive every solution
python3.12 prompts.py          # print every prompt, no model calls
```

### Claude arm — Claude Code subscription

```bash
python3.12 run_cli_arm.py --dry-run
python3.12 run_cli_arm.py --conditions thinking_off effort_low effort_high control_no_clues --replicates 5
python3.12 grade_runs.py       # offline grading and integrity gates; writes the §6A tables
```

### GPT arm — ChatGPT subscription through the Codex CLI

```bash
codex login status             # must say Logged in using ChatGPT
python3.12 prepare_gpt_inputs.py
python3.12 test_gpt_offline.py # no network or model calls
python3.12 run_gpt_cli_arm.py --dry-run
python3.12 run_gpt_cli_arm.py --workers 3
python3.12 grade_gpt_runs.py
```

Defaults: GPT-5.6 Luna, Terra and Sol; `thinking_off` (effort `none`), `effort_low`,
`effort_high` and the mandatory `control_no_clues`; six canonical items × five replicates = 360
conversations. Keep model, replicate and worker settings unchanged when resuming; code, prompt,
CLI-version or model-catalog changes require a new output path.

### Rebuild the comparative report (offline, no model calls)

```bash
python3.12 -m venv .venv-publication
.venv-publication/bin/python -m pip install -r publication/requirements.txt
.venv-publication/bin/python publication/build_analysis.py
.venv-publication/bin/python publication/build_manuscript.py
.venv-publication/bin/python publication/validate_publication.py
```

## Isolation rules — do not weaken

An early version of the Claude arm ran from this directory, where the report lists every
solution, and `--restricted` does not remove file tools. Those results were deleted (report §8.16).
Every model arm must keep:

1. **No tools**: `--tools ""` for Claude; tool-disabled model metadata for Codex.
2. **A fresh empty temporary directory** as the working directory for every call.
3. **Single-turn, isolated sessions**: `--restricted --strict-mcp-config --max-turns 1` for Claude;
   ephemeral conversations with user config, skills, memories, plugins and MCP disabled for Codex.
4. **Grading after collection only**, in `grade_runs.py` and `grade_gpt_runs.py`.
5. **A no-clue control** in every arm. Its value is a diagnostic, not proof: models answer A1 almost
   always, so balance target cells in any new item set.

A future arm that deliberately gives the model tools (for example, to write its own solver) must
run in an empty sandbox directory that contains no item bundle, report or grader.

## Files

| Path | Contents |
|---|---|
| `items.py` | Item loading, app-invariant checks, independent solver |
| `prompts.py` | Verbatim prompt construction |
| `run_cli_arm.py` / `grade_runs.py` | Claude Code subscription arm: blind collection, then offline grading |
| `gpt_transport.py`, `gpt_wire_audit.py`, `prepare_gpt_inputs.py`, `run_gpt_cli_arm.py`, `grade_gpt_runs.py`, `test_gpt_offline.py`, `gpt_inputs.json` | Codex subscription arm |
| `output/cli_arm_runs.jsonl`, `output/gpt_cli_arm_runs.jsonl` | The 723 retained session records (720 completed) |
| `output/*_summary.csv`, `output/*_tables.md`, `output/gpt_cli_arm_runs.manifest.json`, `output/gpt_cli_arm_diagnostics.json` | Arm-level summaries, run manifest and integrity checks |
| `publication/` | Offline re-analysis, 8 figures, audit hashes and validator |
| `COMPARATIVE_BENCHMARK_REPORT.md` | Current manuscript draft |
| `MODEL_BENCHMARK_REPORT.md` | Superseded Claude-only report |

## Removed on 15 September 2026

- `run_benchmark.py`, `analyze_benchmark.py`, `test_offline.py`, `requirements.txt` and `.venv/`:
  a Messages API arm that was designed but never run.
- `output/provisional_incomplete/`: summaries from an interrupted GPT collection, superseded by
  the completed run.

Both are recoverable from git history, for example
`git show 625197f:analysis/model_benchmark/run_benchmark.py`.

Nothing here reads or writes participant data beyond the aggregate human files in
`../rohan_study_report/output/`, and nothing is ever pointed at a live third-party CAPTCHA.
