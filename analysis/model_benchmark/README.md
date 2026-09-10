# Model benchmark — Claim D

Measures what it costs a language model to solve the **same six band-2 grid-localisation
items** the human screen-reader cohort solved: output tokens, wall-clock latency, attempts and
dollars per successful solve, across Claude Haiku 4.5, Sonnet 5 and Opus 5.

Read **`MODEL_BENCHMARK_REPORT.md`** for the design, the human baseline, the results section,
and the difficulties log. This file is just the runbook.

## Run

```bash
cd touchstone-collect/analysis/model_benchmark
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python items.py                       # verify items, re-derive every solution
.venv/bin/python prompts.py                     # print every prompt, no API calls
.venv/bin/python test_offline.py                # verify the harness offline, no key needed
.venv/bin/python run_benchmark.py --dry-run     # plan + cost estimate, no API calls

export ANTHROPIC_API_KEY=sk-ant-...             # or: ant auth login
.venv/bin/python run_benchmark.py               # 270 sessions, approx. $3.36
.venv/bin/python analyze_benchmark.py           # CSVs + splices results into the report
```

Requires Python >= 3.10 (the system 3.9 cannot install `anthropic` 1.x). This venv is separate
from the human study's `.venv-analysis`.

## Benchmark arms

### GPT arm using the existing ChatGPT subscription

The GPT equivalent of the **single-attempt Claude subscription arm** uses the
installed Codex CLI and its existing ChatGPT login. It does not use an OpenAI API
key. Defaults: GPT-5.6 Luna, Terra and Sol; `thinking_off` (`none`), `effort_low`,
`effort_high`, and mandatory `control_no_clues`; six canonical items and five
replicates = **360 independent conversations**. Practice is exported for fidelity
checks but excluded from collection and every aggregate.

```bash
cd touchstone-collect/analysis/model_benchmark
codex login status                        # must say Logged in using ChatGPT
python3 prepare_gpt_inputs.py              # offline, explicit prompt-field export
python3 test_gpt_offline.py                # no network/model calls
python3 run_gpt_cli_arm.py --dry-run
python3 run_gpt_cli_arm.py --workers 3      # audits first, then collects; resumable
python3 grade_gpt_runs.py                  # offline grading after full collection
```

Only Python's standard library is required (including system Python 3.9).
`--workers` defaults to 1; the execution above uses 3 concurrent CLI processes and
records that fact in the manifest. `--models`, `--replicates`, `--inputs`, `--out`
and `--preflight-only` are also available. Keep model/replicate/worker settings
unchanged when resuming. Code, prompt, CLI-version or model-catalog changes require
a new output path, so incompatible sessions cannot silently mix.

Files are separate from the Claude results:

- `gpt_inputs.json`: allowlisted prompt text and item identifiers; no answer fields.
- `output/gpt_cli_arm_runs.manifest.json`: run plan, hashes, local wire audits and
  subscription readiness probes for each model/effort.
- `output/gpt_cli_arm_runs.jsonl`: blind submissions, raw CLI events, token usage,
  latency and errors; no correctness or answer key.
- `output/gpt_cli_arm_condition_summary.csv`, `gpt_cli_arm_item_summary.csv`,
  `gpt_cli_arm_model_item_summary.csv`: offline metrics and human comparisons.
- `output/gpt_cli_arm_diagnostics.json`, `gpt_cli_arm_tables.md`: integrity checks
  and a separate report. The original Claude report and results are preserved.

**GPT isolation:** preparation can inspect the source bundle, but never calls a
model. Collection imports neither the item loader nor the grader and reads only
the exported prompts. Each CLI call uses an empty temporary working directory,
an ephemeral conversation, ignored user config/rules, no project instructions,
and disabled skills, memories, hooks, plugins, apps, MCP and agents. A temporary
model-catalog copy disables shell, patch, code execution and extra tool exposure;
model identity and advertised reasoning levels are preserved. The benchmark base
instructions replace the coding instructions. No session is resumed or forked,
and no correctness feedback is sent.

Before collecting puzzles, a localhost fixture inspects actual serialized
requests and fails on any exposed tool (including Responses Lite
`additional_tools`), extra context, altered model/effort, or conversation reuse.
It sends only a synthetic `READY` prompt and does not forward to a model. Separate
subscription probes confirm each setting is accepted. Real run event streams
must contain exactly one completed turn, only text/reasoning items, and no tool
events. Thinking off additionally requires an explicit **zero** reasoning-token
counter; missing counters or silently enabled thinking are rejected.

Grading requires complete coverage, unique conversations, matching prompt hashes,
valid event streams and successful no-clues controls. The same 25% control ceiling
as the Claude diagnostic is applied per model as well as pooled, and a failure
actually aborts GPT table generation. Uniform guessing is 6.25%; the fixed-item
control is a diagnostic, not a proof against training-data contamination.

**Metric limits:** Codex exposes input, cached-input, total output and reasoning
tokens. Input counts include CLI overhead. Only end-to-end CLI wall latency is
available; API-only latency and dollar cost are blank rather than fabricated.
Model IDs are configured/requested IDs validated in local request audits; CLI
JSON does not supply an independent server-reported model identity. The local
audit uses a fixture provider, not a capture of authenticated production traffic.
Visible-answer strategy metrics do not describe hidden reasoning.

Official references: [ChatGPT subscription authentication](https://learn.chatgpt.com/docs/auth)
and [Codex configuration schema](https://developers.openai.com/codex/config-schema.json).

### Existing Claude arms

| Arm | Scripts | Needs | Measures | Does NOT measure |
|---|---|---|---|---|
| **API benchmark** (Claim D) | `run_benchmark.py` -> `analyze_benchmark.py` | Messages API key | tokens, **cost per solve**, all three conditions | — |
| **Subscription arm** (blind) | `run_cli_arm.py` -> `grade_runs.py` | Claude subscription (Claude Code CLI) | solve rate, output/thinking tokens, reasoning strategy, item difficulty, latency | **input tokens, dollar cost** |

The CLI ships 4k-26k cached input tokens of harness overhead per call, so it cannot price an
attack. It can measure everything else — including the thinking-off floor, via
`MAX_THINKING_TOKENS=0`.

```bash
# subscription arm - no API key needed
.venv/bin/python run_cli_arm.py --dry-run
.venv/bin/python run_cli_arm.py --conditions thinking_off effort_low effort_high control_no_clues --replicates 5
.venv/bin/python grade_runs.py
```

## Leakage: read this before changing the CLI arm

`--restricted` does **not** remove the file tools. An earlier version of this arm ran with `cwd`
set to this directory, where `MODEL_BENCHMARK_REPORT.md` lists every item beside its solution -
and a probe confirmed the model would read it and answer from the table. All results from that
version were deleted. See report §8.16 and §6A.0.

Five defences now apply. Do not weaken any of them:

1. `--tools ""` - no built-in tools at all.
2. A fresh **empty temp directory** as `cwd` for every call (no files, no CLAUDE.md).
3. `--restricted --strict-mcp-config --max-turns 1`.
4. **`run_cli_arm.py` holds no answers.** It never reads `.solution`. Grading is `grade_runs.py`,
   run after collection. Keep that separation.
5. **`control_no_clues`** - the same prompt with clues removed, so chance is 6.25%. `grade_runs.py`
   aborts rather than producing tables if it rises materially above that, if any session shows
   `num_turns != 1` or a permission denial, or if any row lacks `harness_version: 2`.

Last measured control: **1/90 = 1.11%**, i.e. below chance. Run it with every future arm.

## Useful flags

| Flag | Effect |
|---|---|
| `--dry-run` | Print the plan and a cost estimate. No API calls, no key needed. |
| `--models claude-haiku-4-5` | Restrict the model set. |
| `--conditions answer_only` | Restrict the conditions. |
| `--replicates 20` | More replicates per cell. Needed for between-model claims. |
| `--include-practice` | Also run `PRAC01`. Excluded from every aggregate either way. |
| `--out path.jsonl` | Write elsewhere, e.g. for a pilot you intend to discard. |

## Resume and cost safety

`output/runs.jsonl` is appended and flushed per session. Re-running skips completed sessions and
retries only those that recorded an error, so an interrupted or rate-limited run never re-spends
on work already done.

## Invariants

- Items come from `../../data/instances.json` and are resolved by the same rules as
  `lib/instances.ts`. `items.py` hard-fails on any mismatch.
- Every solution is re-derived from the clue text by an independent solver, never read from the
  bundle's `solution` field.
- Prompts are byte-identical to what `app/run/[token]/Runner.tsx` rendered. Run `prompts.py` to
  audit that without spending a token.
- Prompt caching is never enabled; a cache read would understate attacker cost. `diagnostics.csv`
  counts any leak.
- No participant data is read or written anywhere in this directory.
- Nothing here is ever pointed at a live third-party CAPTCHA. Prototype items only.
