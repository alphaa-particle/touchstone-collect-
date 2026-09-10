# Model Benchmark — Tokens and Time Required to Solve the Touchstone CAPTCHA

**Project Touchstone · Claim D (model cost benchmark) · reasoning-CAPTCHA family: negative-constraint grid localisation**

Analysis directory: `touchstone-collect/analysis/model_benchmark/`
Item source: `touchstone-collect/data/instances.json` (`grid_localisation@2.0.0`)
Human reference: `touchstone-collect/analysis/rohan_study_report/output/`
Models under test: Claude Haiku 4.5, Claude Sonnet 5, Claude Opus 5

---

## 1. What this measures and why

The security argument for this CAPTCHA family is economic, not cryptographic. It rests on a
single asymmetry, stated in `AGENT_BUILD_SPEC.md`:

> A human reads "not row 1, not row 4" and eight boxes go dark in a single perceptual sweep.
> Two or three sweeps and a 4×4 grid is solved. A language model has no sweep. Generating
> serially, it must evaluate each of the 16 boxes against each clue and carry the surviving set
> forward one token at a time. It usually gets there — but it spends hundreds of tokens doing
> it, and tokens are seconds and money.

That predicts a cost ratio of **N² model cell-checks per human sweep** — 16× at 4×4. Each
instance in the bundle carries `human_sweeps`, `model_cell_checks` and `asymmetry_ratio` so the
prediction can be checked directly rather than assumed.

Claim D is therefore not "can a model solve it" — the spec already concedes that it usually
can. Claim D is **what a solve costs**: output tokens, wall-clock seconds, and dollars, per
successful solve, at three capability tiers. A CAPTCHA whose asymmetry is economic is only as
strong as the price it imposes on the cheapest model that clears it reliably.

This benchmark is fully independent of the Thursday session and of the human cohort. It runs
against the same `instances.json`, needs no participants, and can be re-run whenever the item
generator or the model line-up changes.

> **Headline result (§6A).** Across **270 blind sessions** with clues (plus a 90-session
> leakage control), Claude Haiku 4.5, Sonnet 5 and Opus 5 solved **every item, every condition,
> every replicate — 270/270, 100%**, against a human cohort accuracy of 95.37%. With thinking
> fully disabled (`MAX_THINKING_TOKENS=0`) they still score 100%, on medians of **81 output
> tokens (Opus)**, **84 (Sonnet)** and **378 (Haiku)**; Opus at low effort needs a median of
> **53**, and **13** on the two items whose clues are pure row/column wipes. Sonnet and Opus
> **never enumerate the grid**. **The N² cell-check asymmetry the family is built on does not
> hold at band 2.** A no-clue control scored **1/90 (1.11%), below the 6.25% chance rate**,
> confirming the models were solving rather than recovering answers (§6A.0). Dollar cost still
> needs the API arm (§6).

**Scope boundary, from the session runbook's hard rules:** *"Never run an automated solver
against a live third-party website."* This harness only ever posts our own generated instances
to the Claude API. The reCAPTCHA v2 baseline arm of the human study is deliberately **not**
model-benchmarked — see §8.9.

---

## 2. The items — identical to what the human applicants were asked

The human session used **band 2**: a 4×4 grid, four clues, and the fixed `canonical_set` of six
items, in a fixed order identical for every participant so that item difficulty could never be
confounded with participant. The benchmark runs the same six, resolved out of the same bundle by
the same rules the app applies in `lib/instances.ts` (`items.py` re-implements those checks and
hard-fails on any mismatch).

| Order | Item | Clues | Solution | Human trials | Human correct % | Human median solve s |
|---|---|---|---|---|---|---|
| 1 | I0009 | 4 | C2 | 18 | 94.44 | 66.11 |
| 2 | I0010 | 4 | C3 | 18 | 94.44 | 37.97 |
| 3 | I0011 | 4 | B4 | 18 | 100.00 | 69.33 |
| 4 | I0012 | 4 | D3 | 18 | 100.00 | 108.64 |
| 5 | I0013 | 4 | D2 | 18 | 88.89 | 68.12 |
| 6 | I0014 | 4 | C4 | 18 | 94.44 | 108.04 |

`PRAC01` (3 clues, band 0, solution B3) preceded the six for humans and is available behind
`--include-practice`. It is **excluded from every aggregate** in this report: humans used it to
learn the format, so it measures something different.

Every solution was **independently re-derived** from the clue text by a second solver written
for this benchmark (`items.py::solve`), not read from the bundle's `solution` field. All seven
items yield exactly one surviving cell, and all seven agree with the bundle. A model marked
wrong here is wrong against two independent readings of the puzzle.

### 2.1 Prompt fidelity

Every string a model sees was lifted verbatim from `app/run/[token]/Runner.tsx` or from
`instances.json`. Nothing is paraphrased, shortened, or reformatted for the model's benefit. The
system prompt carries the intro-screen text a participant heard once before the practice item;
the user turn carries the item screen in DOM order, which is the order a screen reader announces
it:

```
Puzzle 1 of 6

A circle is hidden in one box of a 4 by 4 grid. Columns are A, B, C, and D. Rows are 1, 2, 3,
and 4. A box is named by its column letter and then its row number, for example B3.

Clues
1. The circle is not in column B and not in column D.
2. The circle is not in row 1 and not in row 4.
3. The circle is not in row 3.
4. The circle is not in column A.

Which box holds the circle?
Choose the column, then the row, then select Submit.

Column: A, B, C, D
Row: 1, 2, 3, 4
```

Two deliberate deviations, both forced, both documented in §8:

1. **The decorative grid is withheld.** The 4×4 grid rendered on the item screen is
   `aria-hidden="true"` (invariants A3/A3b/A3c), so it never reached a screen-reader
   participant. Withholding it from the model reproduces the cohort the human data came from.
2. **The answer channel is a text line, not two radio groups.** A human submitted by selecting
   one column radio and one row radio. A model is told, in one line held constant across every
   condition, to end its reply with `ANSWER: <box>`.

Wrong answers replay the app's own dialog text verbatim as the next user turn, up to
`MAX_ATTEMPTS = 3` — the same three attempts a human had:

> Your answer was incorrect. You have 2 more tries. Close this message, change your answer, and
> submit again.

`prompts.py` is runnable on its own (`python prompts.py`) and prints every prompt in full, so
prompt fidelity is auditable without spending a token.

---

## 3. Test-case design

**Unit of observation — a "session":** one `(model, condition, item, replicate)`. Inside a
session the model gets up to three attempts as a single growing conversation, so attempts 2 and
3 resend the whole history and their input tokens grow exactly as a real multi-attempt
attacker's would. A session is *solved* only if some attempt returns the unique correct box.

**Grid:** 3 models × 3 conditions × 6 items × 5 replicates = **270 sessions**.

### 3.1 The three reasoning conditions

Replicates are not optional here. `temperature`, `top_p` and `top_k` are **rejected with a 400**
on Sonnet 5 and Opus 5, so there is no temperature-0 determinism to fall back on; five
replicates per cell are the only way to separate a real solve rate from a lucky draw.

| Condition | Reasoning setting | `max_tokens` | What it measures |
|---|---|---|---|
| `answer_only` | Thinking off; no visible working permitted | 64 | **Floor cost.** The cheapest a solve can possibly be, and the closest analogue to the human's single perceptual sweep. |
| `visible_reasoning` | Thinking off; step-by-step working in the visible reply | 4 000 | **The comparable condition.** Reasoning cost measured identically on all three models, because it is ordinary output text on all three. |
| `extended_thinking` | Thinking on, as each model ships it | 16 000 | **Deployment-realistic ceiling.** What a capable attacker running default settings actually spends. |

`answer_only` is the condition the security claim lives or dies on. If a model reliably clears
the item with a dozen output tokens and no visible working, the "hundreds of tokens" premise
fails regardless of what the other two conditions cost.

`visible_reasoning` exists because the thinking API is **not** uniform across the three models
and cannot be held constant (§8.2). Making the reasoning ordinary output text sidesteps that
entirely and is the one condition where a cross-model token comparison is strictly apples to
apples.

Effort is left at its default (`high`) everywhere, and no sampling parameters are set, so
condition is the only manipulated variable.

### 3.2 Metrics recorded, per attempt and per session

- `input_tokens`, `output_tokens` (thinking tokens are billed as output, so they are counted),
  `cache_read_input_tokens`, `cache_creation_input_tokens`
- `latency_ms` — measured around the API call only, with retry backoff excluded by design (§8.4)
- `stop_reason`, `attempts_used`, `submitted`, `correct`, `parse_failed`
- `response_chars`, `thinking_chars`, `api_retries`, and the full response text
- `cost_usd`, from Anthropic first-party rates: Haiku 4.5 $1/$5, Sonnet 5 $2/$10, Opus 5 $5/$25
  per million input/output tokens

Derived in analysis: **solve rate**, **first-attempt rate**, **output tokens per solve**,
**cost per solve**, **latency per solve**, and **output tokens per human sweep** — the direct
test of the 16× prediction.

Cost per solve, not cost per attempt, is the figure that matters: a cheap model that fails two
thirds of the time is not cheap.

### 3.3 The guessing floor

A 4×4 grid has 16 cells. Blind guessing succeeds 6.25% of the time on one attempt and 18.75%
across three distinct guesses. **Any solve rate must be read against 18.75%, not against zero.**
A model at 30% is barely above chance; only rates well clear of that floor indicate the puzzle
was actually solved.

---

## 4. Reproducing this benchmark

```bash
cd touchstone-collect/analysis/model_benchmark
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python items.py            # verify the six items, re-derive every solution
.venv/bin/python prompts.py          # print every prompt verbatim, no API calls

.venv/bin/python run_benchmark.py --dry-run     # plan + cost estimate, no API calls
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python run_benchmark.py               # the 270-session grid
.venv/bin/python analyze_benchmark.py           # CSVs + splices §6 of this report
```

`run_benchmark.py` appends one JSON object per session to `output/runs.jsonl` and flushes after
each, so an interrupted run resumes without re-spending. Sessions that recorded an error are
retried on the next run; sessions that completed are skipped.

Estimated spend for the default 270-session grid: **≈ $3.36**; ≈ $3.92 with
`--include-practice` (315 sessions). `--dry-run` quotes it before anything is charged. Expect roughly 45–75 minutes serially, dominated by the
`extended_thinking` cells.

---

## 5. Human baseline (measured, n = 18 per item)

From `analysis/rohan_study_report/output/`, the real screen-reader cohort:

| Metric | Value |
|---|---|
| Prototype trial-level accuracy | **95.37%** (103 / 108 trials) |
| Prototype trial-level median solve time | **72.25 s** (Q1 44.23, Q3 125.55) |
| Session-level success (all six correct) | 77.78% (14 / 18), 95% CI 54.8–91.0 |
| Median of per-item median **orientation** time | **52.86 s** |
| Median of per-item median **execution** time | **8.73 s** |
| Median of per-item mean attempts | 1.33 |
| Baseline reCAPTCHA v2 challenge completion | 21.05% (4 / 19), median 11.29 s |
| Paired prototype-vs-baseline difference | +50 pp, exact McNemar p = 0.021 |

**The orientation/execution split is the single most important number for interpreting this
benchmark.** `solve_time = orientation_time + execution_time`, where orientation is the
screen-reader navigation and reading phase and execution runs from first interaction to submit.
The human median decomposes as **52.86 s of reading the screen and 8.73 s of everything else**.

So the human's *deduction* phase was roughly **8.7 seconds**, not 72. The 72-second figure is
dominated by serial text-to-speech of the preamble and four clues — a cost the model does not
pay and which has nothing to do with reasoning. Any human-versus-model wall-clock ratio computed
against 72 s overstates the asymmetry by about 8×. §8.3 carries this through.

---

## 6. Model results

<!-- RESULTS:BEGIN -->

**Not yet collected.** The harness is complete, verified and dry-run clean, but this environment
has **no Anthropic credential** — no `ANTHROPIC_API_KEY`, no `ANTHROPIC_AUTH_TOKEN`, no `ant`
CLI and no OAuth profile under `~/.config/anthropic`. No API call has been made, so no model
number appears anywhere in this report. Nothing in this section is estimated, extrapolated or
placeheld with plausible values.

To fill this section:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python run_benchmark.py && .venv/bin/python analyze_benchmark.py
```

`analyze_benchmark.py` writes tables **R1–R5** in place of this notice and emits the matching
CSVs. It reads the human side directly out of `rohan_study_report/output/instance_summary.csv`,
so the comparison columns are never retyped by hand.

| Table | Contents |
|---|---|
| R1 | Solve rate, first-attempt rate, median tokens, median latency, output tokens per solve, cost per solve — by model × condition |
| R2 | Human versus model per item: human accuracy and median time against model solve rate, latency, time ratio, and output tokens per human sweep |
| R3 | Per-item model performance: solve rate, mean attempts, median tokens, median latency |
| R4 | Diagnostics: parse failures, `max_tokens` truncations, refusals, API retries, session errors, cache-read leaks, sessions exhausting all three attempts |
| R5 | Human reference figures, restated from the study output |

<!-- RESULTS:END -->

### 6.1 How to read the results against Claim D

> **Tests (1) and (2) are already settled — both failed.** The subscription arm
> (§6A) measured them on 270 blind sessions without needing the API, with a
> passing leakage gate. What the API arm adds is the dollar figure and clean
> input-token accounting, neither of which can move the verdict in the claim's
> favour. Read this section as the pre-registered
> criteria, and §6A.2 as the result against them.

The asymmetry claim survives only if **all** of the following hold once R1–R4 are populated:

1. **`answer_only` does not solve the item cheaply.** If any model clears the six at a rate well
   above the 18.75% guessing floor while spending only tens of output tokens, the "hundreds of
   tokens" premise is refuted and the economic argument collapses at its cheapest point. This is
   the decisive test, and it is the one most likely to fail.
2. **Output tokens per human sweep lands near the predicted 16×.** The bundle predicts 48 model
   cell-checks against 3 human sweeps per item. If measured tokens per sweep come in far below
   that, the model is exploiting structure the generator did not anticipate — most plausibly by
   intersecting the clues symbolically ("not A, not B, not D ⇒ C") instead of enumerating cells.
   Band-2 clue sets are pure row/column/region wipes, which is exactly the shape that invites
   that shortcut.
3. **Cost per solve is high enough to matter at scale.** A CAPTCHA that costs an attacker
   $0.0005 per solve deters nobody. Pick a defensible break-even before reading the table — for
   instance, cost per solve must exceed the ~$0.001–0.003 per solve of commercial human solving
   farms, or the puzzle is strictly cheaper to break by machine than to outsource.
4. **The cheapest tier does not dominate.** If Haiku 4.5 matches Opus 5's solve rate at a fifth
   of the price, the relevant attacker cost is Haiku's, and Opus figures are irrelevant to the
   threat model.

If (1) fails, raise the band — 5×5 lifts the predicted ratio to 25× — or add clue kinds that
resist symbolic intersection (the diagonal and middle-box clues in I0011/I0012/I0013/I0014 are
the existing seeds of that). Do **not** rescue the claim by reporting only
`extended_thinking`: that is the condition an attacker would switch off first.

---

## 6A. Subscription arm — blind solve behaviour and reasoning strategy

Run through the **Claude Code CLI on a Claude subscription**, because a subscription
authenticates that CLI but grants no Messages API access. This arm answers the correctness and
token-magnitude half of the question while §6 waits on an API key.

### 6A.0 Leakage: what went wrong, and what now prevents it

The first version of this arm is **discarded in full**. It invoked the CLI with `cwd` set to the
benchmark directory, and `--restricted` does *not* remove the built-in file tools. A probe
confirmed the consequence directly — asked for the solution to I0009, the model read
`MODEL_BENCHMARK_REPORT.md` out of that directory and answered `C2`, citing the table and line
number. `items.py`, `instances.json` and the results files were reachable on the same path.

Whether the original sessions actually used that route is a separate question, and the available
evidence says they did not: `--max-turns 1` leaves no room for a tool call, every session
recorded `num_turns: 1`, and no reply contained a tool signature. That is not good enough. A
result gathered with the answer key readable cannot be certified, so every file was deleted and
the arm was rebuilt and re-run.

Five defences now apply, four structural and one empirical:

| # | Defence | Verification |
|---|---|---|
| 1 | `--tools ""` — removes every built-in tool | With it set, the model emits a *fake* tool-call block as plain text and never receives file content |
| 2 | Fresh **empty temporary directory** as `cwd` per call | Nothing to read; no `CLAUDE.md` discoverable |
| 3 | `--restricted --strict-mcp-config --max-turns 1` | No code-running tools, no WebFetch, no MCP, settings ignored |
| 4 | **The runner holds no answers.** `run_cli_arm.py` never reads `.solution`; grading is a separate post-collection step in `grade_runs.py` | `grep -n "\.solution" run_cli_arm.py` returns nothing |
| 5 | **`control_no_clues`** — the same prompt with the clue list replaced by `(none provided)` | Unsolvable by reasoning, so chance is 6.25%. Result: **1/90 = 1.11%** |

Defence 4 is the structural one worth stating plainly: the process that talked to the models
could not grade them, and the process that grades never talked to a model. Defence 5 is the gate
— `grade_runs.py` **aborts instead of producing tables** if the control rises materially above
chance, if any session shows `num_turns != 1` or a permission denial, or if any row predates the
fix.

### 6A.1 Thinking can be disabled after all — the four conditions

An earlier draft of this report claimed the CLI could not turn thinking off, because only
`--effort` appears in `--help`. That was wrong. The environment variable
**`MAX_THINKING_TOKENS=0` disables thinking entirely** — verified: Opus returned 4 output tokens
and 0 thinking on a trivial prompt, and 0 thinking tokens across all 90 sessions of the
condition below. The API arm's decisive `answer_only` floor condition is therefore reachable
here, and §6.1 test (1) can be settled without a key.

| Condition | Setting | Clues | What it measures |
|---|---|---|---|
| `thinking_off` | `MAX_THINKING_TOKENS=0` | yes | **True floor cost.** No thinking at all. |
| `effort_low` | `--effort low` | yes | Cheapest thinking setting. |
| `effort_high` | `--effort high` | yes | CLI default depth. |
| `control_no_clues` | `--effort high`, clue list removed | **no** | Leakage gate (§6A.0). |

3 models × 4 conditions × 6 items × 5 replicates = **360 sessions**, of which 270 carry clues and
90 are control. Zero errors; all 360 verified `num_turns: 1` with no permission denials.

**Still invalid from this arm:** input tokens and dollar cost. Harness overhead of 4k–26k cached
input tokens per call swamps a ~250-token prompt, so cost per solve remains an API-arm
measurement. Output tokens, thinking tokens, solve rate, strategy and latency are sound.

<!-- CLIARM:BEGIN -->

Measured on **360 blind sessions** through the Claude Code CLI on a Claude subscription.

> **Isolation.** Every call ran with `--tools ""` (no built-in tools at all), from a fresh empty temporary working directory, under `--restricted --strict-mcp-config --max-turns 1`. The runner holds no solutions — grading happens afterwards in `grade_runs.py`. Every session was verified to show `num_turns == 1` with no permission denials, which is direct evidence no tool was reached and no file could have been read.

### C0. Validity gate — no-clue control

The clue list is replaced with `(none provided)`; everything else in the prompt is byte-identical. The item is then unsolvable by reasoning, so a model can only guess: **chance is 6.25%** (1 of 16 cells).

| Model | Correct | Sessions | Rate % |
|---|---|---|---|
| Haiku 4.5 | 1 | 30 | 3.33 |
| Sonnet 5 | 0 | 30 | 0.0 |
| Opus 5 | 0 | 30 | 0.0 |
| **Pooled** | 1 | 90 | 1.11 |

**Verdict: PASS** — pooled 1.11% against 6.25% chance. A rate near chance means the models were genuinely solving the clue sets in the other conditions rather than recovering answers from anywhere else.


### C1. Solve behaviour by model and condition

`thinking_off` sets `MAX_THINKING_TOKENS=0`, which disables thinking through the CLI — this is the true floor-cost condition, the API arm's `answer_only` equivalent. Token columns count the requested model only; a Claude Code auxiliary Haiku call fires on every request regardless of `--model` and is excluded.

| Model | Condition | Sessions | Solve rate % | Median out tok | Median thinking tok | Median API s | Parse fails | Enumeration % | Median cells named |
|---|---|---|---|---|---|---|---|---|---|
| Haiku 4.5 | thinking_off | 30 | 100.0 | 378 | 0 | 4.86 | 0 | 53.33 | 10.0 |
| Haiku 4.5 | effort_low | 30 | 100.0 | 873 | 546 | 8.46 | 0 | 40.0 | 9.0 |
| Haiku 4.5 | effort_high | 30 | 100.0 | 892 | 568 | 8.82 | 0 | 50.0 | 9.5 |
| Haiku 4.5 | control_no_clues | 30 | 3.33 | 2098 | 1952 | 23.92 | 0 | 0.0 | 1.0 |
| Sonnet 5 | thinking_off | 30 | 100.0 | 84 | 0 | 3.29 | 0 | 0.0 | 5.0 |
| Sonnet 5 | effort_low | 30 | 100.0 | 84 | 71 | 3.2 | 0 | 0.0 | 1.0 |
| Sonnet 5 | effort_high | 30 | 100.0 | 116 | 94 | 3.38 | 0 | 0.0 | 1.0 |
| Sonnet 5 | control_no_clues | 30 | 0.0 | 13 | 0 | 2.76 | 0 | 0.0 | 1.0 |
| Opus 5 | thinking_off | 30 | 100.0 | 81 | 0 | 4.67 | 0 | 0.0 | 5.0 |
| Opus 5 | effort_low | 30 | 100.0 | 53 | 43 | 4.58 | 0 | 0.0 | 1.0 |
| Opus 5 | effort_high | 30 | 100.0 | 128 | 63 | 5.19 | 0 | 0.0 | 2.0 |
| Opus 5 | control_no_clues | 30 | 0.0 | 52 | 18 | 4.48 | 0 | 0.0 | 1.0 |

Pooled over the three clue-bearing conditions: **270/270 solved (100.00%)** against a human trial accuracy of 95.37%.


### C2. Order-free item difficulty

Pooled across models and clue-bearing conditions; the control is excluded. Each session is an independent conversation with no memory of the other items, so this ranks items free of the sequence confound the human data cannot escape. `has_region_clue` marks *middle-boxes*, *diagonal* or *edge* clues — the kinds that cannot be decomposed one axis at a time.

| Item | Order | Region clue | Human correct % | Human median s | Human mean attempts | Model solve % | Model median out tok | Median cells named | Enumeration % |
|---|---|---|---|---|---|---|---|---|---|
| I0009 | 1 | no | 94.44 | 66.11 | 1.0 | 100.0 | 57 | 1 | 2.22 |
| I0010 | 2 | no | 94.44 | 37.97 | 1.056 | 100.0 | 52 | 1 | 22.22 |
| I0011 | 3 | yes | 100.0 | 69.33 | 1.222 | 100.0 | 122 | 5 | 17.78 |
| I0012 | 4 | yes | 100.0 | 108.64 | 1.444 | 100.0 | 97 | 5 | 13.33 |
| I0013 | 5 | yes | 88.89 | 68.12 | 1.5 | 100.0 | 159 | 5 | 20.0 |
| I0014 | 6 | yes | 94.44 | 108.04 | 1.5 | 100.0 | 159 | 9 | 20.0 |
<!-- CLIARM:END -->

### 6A.2 Verdict: the asymmetry does not hold at band 2

**270 of 270 clue-bearing sessions solved — 100%**, for every model at every condition, against
a human trial accuracy of 95.37%. Zero parse failures. The no-clue control sat at 1.11%, below
chance, so this is genuine solving (§6A.0).

Median output tokens per solve:

| Model | `thinking_off` | `effort_low` | `effort_high` | Enumerates? |
|---|---|---|---|---|
| Haiku 4.5 | **378** (0 thinking) | 873 (546 th) | 892 (568 th) | 40–53% of replies, ~9–10 cells named |
| Sonnet 5 | **84** (0 thinking) | 84 (71 th) | 116 (94 th) | never — 0% |
| Opus 5 | **81** (0 thinking) | **53** (43 th) | 128 (63 th) | never — 0% |

**§6.1 test (1) fails.** The pre-registered test was: *if any model clears the six well above the
guessing floor while spending only tens of output tokens, the "hundreds of tokens" premise is
refuted and the economic argument collapses at its cheapest point.* With thinking fully
disabled, Opus 5 solves the six at 100% on a median of **81 output tokens** and Sonnet 5 on
**84**. At low effort Opus needs **53**, and **13 tokens** on I0009 and I0010 — the two items
whose clues are pure row/column wipes. This is the floor condition, measured directly, and it
passes comfortably.

**§6.1 test (2) fails, and explains test (1).** The bundle predicts 48 model cell-checks against
3 human sweeps per item. Sonnet 5 and Opus 5 name a median of **one** cell — the answer — and
enumerate in **0%** of 180 replies. The traces show what they do instead: *"NOT B, NOT D, NOT A
→ column C. NOT 1, NOT 4, NOT 3 → row 2."* Four clue reads, intersected one axis at a time. The
premise that a model "has no sweep" and "must evaluate each of the 16 boxes against each clue"
is not how these models behave on axis-decomposable clues.

**The asymmetry survives only against the weakest model, which inverts the threat model.** Haiku
4.5 does pay a real cost — it enumerates in roughly half its replies and spends 378–892 output
tokens, 5–17× what Opus spends. So the puzzle taxes the cheap model and is nearly free for the
capable ones. An attacker picks the model that works, so the governing figure is 53–81 tokens,
not 892.

**An unexpected result: turning thinking off makes Haiku three times cheaper, not dearer.** Haiku
drops from 892 tokens at `effort_high` to **378** at `thinking_off`, with no accuracy loss
(100% either way). Thinking was making it *more* expensive without making it more correct. For
Sonnet and Opus the ordering is the opposite and mild — `thinking_off` costs slightly more than
`effort_low` (81 vs 53 on Opus), because with thinking disabled the model writes its short
reasoning into the visible reply instead. Either way the cheapest reliable setting for an
attacker is 53–84 tokens.

### 6A.3 The one defensive signal: region clues

The single actionable finding, and it replicates cleanly across all nine model × condition
cells. Splitting the six items by whether they carry a *middle-boxes*, *diagonal* or *edge*
clue — the kinds that cannot be decomposed one axis at a time:

| Model | Condition | No region clue | Region clue | Ratio |
|---|---|---|---|---|
| Haiku 4.5 | `thinking_off` | 289 | 412 | 1.42× |
| Haiku 4.5 | `effort_low` | 551 | 1030 | 1.87× |
| Haiku 4.5 | `effort_high` | 654 | 947 | 1.45× |
| Sonnet 5 | `thinking_off` | 52 | 115 | 2.23× |
| Sonnet 5 | `effort_low` | 23 | 96 | **4.15×** |
| Sonnet 5 | `effort_high` | 54 | 142 | 2.65× |
| Opus 5 | `thinking_off` | 48 | 88 | 1.80× |
| Opus 5 | `effort_low` | **13** | **56** | **4.27×** |
| Opus 5 | `effort_high` | 94 | 155 | 1.65× |

Median output tokens. The effect is largest exactly where cost is lowest — at `effort_low`,
where the frontier models are cheapest, region clues cost **4.2×** more. Pooled per item:
I0009/I0010 (no region clue) sit at 52–57 tokens against 97–159 for the four region items.

Three cautions before this is treated as the fix. First, 4× off a base of 13 tokens is still
only ~56 tokens — a large multiplier on a negligible number. Second, the same clues cost
*humans* more too: human mean attempts run 1.22–1.50 on the region items against 1.00–1.06 on
the other two, so hardening this way trades directly against the accessibility result the
project exists to defend. Third, one item's region clue is *"not touching the edge of the
grid"*, which is itself axis-decomposable — so not every clue tagged `region` here is equally
resistant, and the taxonomy needs refining before it becomes a generator parameter.

### 6A.4 The human comparison, stated honestly

| | Human cohort | Models (270 blind sessions) |
|---|---|---|
| Accuracy | 95.37% of trials | **100%** |
| Median solve time | 72.25 s (52.86 s orientation + 8.73 s execution) | 2.8–8.8 s API latency |
| Mean attempts | 1.33 | n/a — single blind attempt per session |

The models are more accurate than the human cohort, and even against the human's ~8.7 s
*deduction* phase alone — not the 72 s that is mostly screen-reader orientation — they are no
slower. There is no dimension measured here on which the human outperforms the machine.

One caveat on the attempts row: this arm gives each session a **single** attempt, where a human
had three. That is a consequence of blinding — the runner cannot know whether to retry without
knowing the answer. It makes the model figure *conservative*: three attempts could only raise a
solve rate that is already 100%.

### 6A.5 What is still open

- **No dollar cost.** Input tokens and cost per solve need the API arm (§6). Output-token counts
  above are the requested model's own, excluding the Claude Code auxiliary call, but CLI input
  accounting is swamped by harness overhead.
- **Single attempt per session**, by design (above).
- **No scripted-solver arm.** Still the largest untested threat, and the one most likely to make
  even 53 tokens look expensive.

None of these can rescue the claim. Every open measurement can only push attacker cost **down**.

---

## 7. What was established before any model ran

Four things were established by the harness itself, before any model ran. They are retained because they are what made the §6A result interpretable rather than anecdotal:

1. **The items are sound.** All seven have exactly one solution, independently re-derived from
   clue text. No human was marked wrong by a defective item, and no model can be.
2. **The prompts are faithful.** `python prompts.py` prints, verbatim and auditably, exactly
   what a model receives against what `Runner.tsx` rendered.
3. **The grid is affordable.** ≈$3.36 for the 270-session API grid. Cost is not a reason to
   under-power this benchmark; if anything, replicates should be raised.
4. **The human numbers are not what the spec assumed.** The spec's asymmetry narrative implicitly
   treats the human's 72 s as reasoning time. It is not: 52.86 s of it is screen-reader
   orientation. The honest human deduction figure is 8.73 s, and the benchmark must be read
   against that. This finding needs a line in the pre-registration before the model data is
   unblinded — otherwise the time ratio will be reported ~8× too favourably.

---

## 8. Difficulties encountered

### 8.1 No Messages API credential in the environment

`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are unset, the `ant` CLI is not installed, and
there is no OAuth profile at `~/.config/anthropic`. An unset key does not by itself mean no
credentials — the SDK also resolves `ant auth login` profiles and workload identity
federation — so all four sources were checked before concluding.

This blocked the API arm (§6) but, as it turned out, not the science. A Claude subscription
authenticates the Claude Code CLI, and once thinking could be disabled there (§8.13) the
subscription arm settled both decisive tests on its own (§6A.2). What remains genuinely blocked
is the **dollar figure and input-token accounting** — nothing more.

### 8.2 The thinking API is not uniform across the three models

There is no single `thinking` configuration that spans Haiku 4.5, Sonnet 5 and Opus 5:

| Model | Thinking on | Thinking off |
|---|---|---|
| Haiku 4.5 | `{"type": "enabled", "budget_tokens": 8000}` | omit the parameter — no disable object exists |
| Sonnet 5 | `{"type": "adaptive"}` | `{"type": "disabled"}` |
| Opus 5 | `{"type": "adaptive"}` — also the default when omitted | `{"type": "disabled"}`, accepted only at effort ≤ `high` |

So `extended_thinking` is *not* a controlled condition across models — Haiku runs a fixed 8 000
token budget while Sonnet and Opus allocate adaptively. It is reported as "extended thinking as
each model ships it", which is the deployment-realistic reading, and it is explicitly not the
condition to draw cross-model token conclusions from. `visible_reasoning` exists precisely to
provide the clean cross-model comparison, and it is the condition §6.1 test (2) should be
evaluated on.

A related trap: on Opus 5, thinking is **on by default**, so omitting the parameter does not
turn it off. `answer_only` had to disable it explicitly or the "floor cost" condition would have
silently measured full adaptive-thinking spend on the most expensive model in the set.

### 8.3 Wall-clock time is not comparable between humans and models

Three reasons, and they compound:

- **The human 72 s is mostly not reasoning.** 52.86 s of the median is screen-reader orientation
  (§5). Comparing it to a model's API latency compares text-to-speech throughput to GPU
  throughput.
- **Model latency is infrastructure, not cognition.** It carries network round-trip, server
  queueing and current load. Re-run the same grid at a different hour and the seconds move while
  the tokens do not.
- **Neither includes the human's motor cost.** Selecting two radios and a submit button is real
  time for a screen-reader user and has no model analogue.

Consequence for the report: **tokens are the primary metric; latency is descriptive only.** R2
prints the time ratio because it is the number people will ask for, but any claim resting on it
must state which human phase it uses. The human study made the same call for the same reason —
its own notes decline an inferential speed comparison because the baseline arm had one task
against the prototype's six.

### 8.4 Rate-limit backoff would have corrupted the latency metric

The SDK retries 429s and 5xx with exponential backoff by default. Left on, a rate-limited call
would report its backoff sleep as model latency and quietly inflate the headline number. The
harness sets `max_retries=0` on the client and implements its own retry loop *outside* the timed
region, recording `api_retries` per attempt so a cell that hit limits is visible in R4 rather
than hidden in its own latency.

### 8.5 Free-text answers introduce a failure mode humans could not have

A human's answer was a closed 16-way choice through two radio groups: unparseable answers were
structurally impossible. A model emits text, so a parse layer is unavoidable — `ANSWER: <box>`
first, falling back to the last box-shaped token in the reply. Two consequences:

- **Parse failure is a distinct outcome with no human analogue,** counted separately in R4. It
  must not be silently scored as a wrong answer: a model that reasoned correctly and formatted
  badly is a different finding from one that deduced the wrong cell.
- **The fallback regex can be over-generous.** A reply reasoning aloud about "row 3" and "column
  C" contains box-shaped substrings. The `ANSWER:` line is tried first for exactly this reason,
  and `answer_only` is capped at 64 tokens so there is almost no room for a stray match. If R4
  shows non-trivial parse failures, tighten the format instruction rather than loosening the
  regex.

### 8.6 Thinking tokens are billed but not readable

On Sonnet 5 and Opus 5, `thinking.display` defaults to `omitted`: thinking blocks come back with
empty text while still being billed as output tokens. Token accounting is therefore complete,
but the reasoning trace is not inspectable, and `thinking_chars` will read ≈0 in
`extended_thinking` even where thousands of thinking tokens were charged. The harness does not
set `display: "summarized"`, because a summary is generated content that would perturb the token
measurement this benchmark exists to take. **Accepted trade: we can price the reasoning but
cannot audit it.** Diagnosing *how* a model solved these items — enumeration versus symbolic
intersection, which §6.1 test (2) turns on — needs a separate, small, deliberately
non-token-accurate run with summaries enabled.

### 8.7 Prompt caching would silently distort every token figure

Repeated identical system prompts across 270 sessions are exactly the shape prompt caching
targets. A cache hit reports input tokens at a fraction of the true count and would understate
attacker cost. Caching is never enabled (no `cache_control` block is ever sent), and R4 counts
`cache_read_input_tokens` occurrences as a leak check. Any non-zero value there invalidates the
input-token column and must be investigated before the table is used.

### 8.8 Multi-attempt sessions inflate input tokens by design

Attempt 2 resends the item, the model's wrong answer and the dialog text; attempt 3 resends all
of that again. Input tokens therefore grow super-linearly in attempts, which is correct — it is
what a retrying attacker actually pays — but it means `median_input_tokens` is a function of the
solve rate and cannot be read as a per-attempt prompt size. Compare `cost_per_solve_usd` across
models, never raw input tokens.

### 8.9 The reCAPTCHA baseline arm cannot be benchmarked at all

The human study is a paired design: prototype against reCAPTCHA v2. The model benchmark can only
cover one arm. Benchmarking the baseline would mean running an automated solver against a live
third-party service, which the runbook forbids outright and which no framing makes acceptable.

This is a real gap, not a formality. The human result is *relative* (+50 pp for the prototype
over the baseline, p = 0.021), while the model result will be *absolute* (cost per solve for the
prototype alone). The two cannot be composed into a single "prototype beats baseline for humans
and machines" claim. State the asymmetry explicitly in any write-up, and if a bot-side
comparison is genuinely needed, source it from published third-party reCAPTCHA-solver
economics — with citations — rather than by running one.

### 8.10 Instance difficulty and sequence position are confounded in the human data, but not in the model data

The human study flags that I0012 and I0014 had the longest medians (108.64 s, 108.04 s) while
also appearing 4th and 6th in the fixed order — so item difficulty cannot be separated from
fatigue or practice. The model benchmark has no such confound: each session is an independent
conversation with no memory of the other items, and every item is seen in the same position (as
"Puzzle *k* of 6", preserving the human wording, but with no prior context).

This is an unexpected bonus. **R3 is a clean, order-free difficulty ranking of the six items** —
something the human data structurally cannot supply. If R3 also finds I0012 and I0014 hardest,
that is genuine item difficulty; if it finds them ordinary, the human effect was sequence, not
item. Worth a line in the human report either way.

### 8.11 No temperature control, so replicates are mandatory

`temperature`, `top_p` and `top_k` return a 400 on Sonnet 5 and Opus 5. There is no way to pin
sampling for a deterministic single-shot run, so five replicates per cell are load-bearing
rather than a nicety. With 5 replicates a per-cell solve rate has a resolution of 20
percentage points — adequate for detecting the difference between "solves it" and "at the
guessing floor", **not** adequate for a claim like "Haiku is 8 points worse than Sonnet". Raise
replicates to 20+ before making any fine-grained between-model claim; at $3.36 for 5, that is
affordable.

### 8.12 Python version and SDK constraints

The system Python is 3.9.6; the `anthropic` 1.x SDK requires ≥3.10. The harness pins
`/opt/homebrew/bin/python3.12` with a local `.venv` (`anthropic` 1.4.0 installed and verified)
and does not touch the separate `.venv-analysis` used by the human study, so the two analyses
cannot break each other.

### 8.13 What a Claude subscription can and cannot measure — and one claim I got wrong

The available credential is a Claude subscription, not a Messages API key. It authenticates the
Claude Code CLI, which is drivable non-interactively. Probing what that path can measure produced
one hard limit and one mistake worth recording.

**The hard limit — cost.** 22 454 cached input tokens survive even with the built-in system
prompt replaced and every code-running tool stripped; against a ~250-token puzzle prompt that is
a 16×–100× inflation. Reporting dollar cost from this path would overstate attacker cost by one
to two orders of magnitude, on the exact metric the security claim rests on. Input tokens and
cost per solve therefore remain API-arm measurements. `--bare` would strip the overhead but, by
design, reads auth strictly from `ANTHROPIC_API_KEY` or `apiKeyHelper` and never from OAuth or
the keychain — so it cannot run on a subscription.

**The mistake — thinking.** An earlier revision of this report stated that thinking could not be
disabled through the CLI and that the decisive `answer_only` condition was therefore
unreachable. That was wrong, and it was wrong in the direction that made the harness look more
limited than it is. I had checked only the command-line flags, where `--effort` is the sole
thinking control. **`MAX_THINKING_TOKENS=0` disables thinking entirely** — 0 thinking tokens
across all 90 sessions of the `thinking_off` condition. The lesson is narrow but general: absence
from `--help` is not absence from the tool, and an environment variable is not a flag.

Consequence: the subscription arm settles §6.1 tests (1) and (2) on its own (§6A.2). Only the
dollar figure still waits on a key.

**Repurposing the stored OAuth credential was never attempted.** Extracting Claude Code's
keychain token to call the raw Messages API would be credential misuse regardless of who owns
the machine, and the token is scoped to the CLI.

### 8.14 The CLI silently mislabelled which model ran — caught before it reached a table

The first 90-session pass recorded `claude-haiku-4-5` as the model for **all
three** aliases, which would have meant `--model sonnet` and `--model opus` were
being ignored and the whole arm was one model three times over.

It was not. A direct probe confirmed the flag works
(`sonnet -> claude-sonnet-5`, `opus -> claude-opus-5`). The defect was in this
harness: the CLI's `modelUsage` map carries **two** entries — the model that did
the work, plus a Claude Code auxiliary Haiku call (~16 output tokens against
~1k input) that fires on every request regardless of `--model`. The auxiliary
entry is inserted first, so reading `keys()[0]` labelled every Sonnet and Opus
session as Haiku.

What saved it was that the token profiles were implausible for one model —
median 915 output tokens under one alias against 112 under another. A single
model does not behave that way, so the label had to be wrong. **The lesson is
that the contradiction, not the label, is what flagged it**: had all three
aliases produced similar token counts, the mislabelling would have passed
review and three models would have been reported under one name.

Fixes applied:

- `run_cli_arm.py` matches the requested alias against the model-id prefix,
  stores the full `modelUsage` dict per attempt, records a `model_verified`
  flag, and prints `BADMODEL` if a session cannot confirm the model.
- `analyze_cli_arm.py` **hard-fails** rather than aggregating if any row lacks
  `model_verified`, fails verification, or shows an alias/model mismatch.
- The pre-fix file is retained as `cli_arm_runs_v1_mislabelled.jsonl` and is
  rejected by the analyzer, so it cannot re-enter the analysis.
- Token figures needed no correction: top-level `usage.output_tokens` was
  verified to count the main model only, excluding the auxiliary call.

The arm was then re-run in full, which also serves as an independent replication
of the headline result.

### 8.15 An inherited stdin killed 105 sessions, and every one of them looked like a model failure

The `--effort low` arm returned **90 errored sessions out of 90**, and the tail
of the default-effort arm lost a further 15 Opus sessions. All 105 carried the
same message:

```
cli exit 1: Warning: no stdin data received in 3s, proceeding without it.
```

`--effort low` was not at fault — the same command run straight from a shell
succeeds and returns valid JSON. The bug was in this harness:
`subprocess.run(...)` did not set `stdin`, so each CLI child inherited the
harness's own stdin. Run interactively that is harmless. Run as a background
job, stdin never delivers, so the CLI waited three seconds and exited 1. Fixed
with `stdin=subprocess.DEVNULL`, which is exactly what the CLI's own message
recommends.

Three things are worth recording about how this was caught:

- **It only surfaced because failures are recorded, not raised.** Each session
  stores its own `error` string, so the arm ran to completion and left 105
  diagnosable records. Had the harness aborted on the first failure, the run
  would have died at session 76 of the default arm with no low-effort data at
  all and no error trail.
- **A silent-skip resume would have buried it.** `load_done()` deliberately
  excludes errored rows from the completed set, so the fixed re-run picks up
  exactly the 105 failures and nothing else. A resume keyed only on "row
  exists" would have treated all 105 as done and reported an arm that never ran.
- **The failure mode is indistinguishable from a model failure at the summary
  level.** An aggregate over those rows would have shown a 0% solve rate at
  `low` effort and invited precisely the wrong conclusion — that low effort
  cannot solve the puzzle, i.e. that the CAPTCHA works. The truth was that no
  model was ever asked. This is why `analyze_cli_arm.py` hard-fails on
  unverified rows instead of averaging over them, and why solve rates are
  computed over `valid` sessions with the error count reported alongside.

### 8.16 The benchmark left its own answer key readable to the models under test

The most serious defect found in this work, and it was raised as a challenge to the results
rather than caught by the harness.

`run_cli_arm.py` v1 invoked the CLI with `cwd` set to the benchmark directory. `--restricted`
removes the code-running tools and WebFetch — but **not** `Read`, `Glob` or `Grep`. That
directory contained `MODEL_BENCHMARK_REPORT.md`, whose §2 table lists all six items beside their
solutions, plus `items.py` (a working solver), `instances.json` (the `solution` field) and the
accumulating results files. A direct probe settled it: asked for the solution to I0009, the model
read the report and answered `C2`, citing the section and line number.

The available evidence says the original runs did not exploit it — `--max-turns 1` leaves no room
for a tool call plus an answer, every session recorded `num_turns: 1`, and no reply contained a
tool signature. That evidence is not sufficient. **A benchmark whose answer key was readable by
the system under test cannot be certified**, so all result files were deleted and the arm was
rebuilt blind and re-run from scratch (§6A.0).

What this cost and what it bought:

- **Cost:** 180 sessions of collection discarded, plus the two earlier partial runs.
- **Bought:** a materially stronger design. Grading is now a separate post-collection step, so
  the runner cannot leak what it does not hold; every call runs from an empty temporary
  directory with `--tools ""`; and the arm carries its own empirical validity gate in
  `control_no_clues`, which came back at **1.11% against 6.25% chance**. The original design had
  no such gate, so it could not have detected leakage even in principle.

Two generalisations worth carrying forward:

- **Isolation must be positive, not incidental.** v1 was safe only because `--max-turns 1`
  happened to make tool use impractical. That is a coincidence of an unrelated setting, not a
  control. `--tools ""` plus an empty `cwd` is a control.
- **Every capability benchmark needs a leakage gate as a first-class condition.** A no-input
  control costs one condition and converts "we believe there was no leakage" into a measured
  number. It should have been in the design from the start, and its absence — not the readable
  file — was the real methodological error.

---

## 9. Limitations

- **One family, one band.** Only `grid_localisation` at band 2 (4×4, four clues). Nothing here
  speaks to band 1, band 3, 5×5, or the `haystack` family.
- **Three models, one vendor.** Claude Haiku 4.5, Sonnet 5, Opus 5. A real attacker picks the
  cheapest model that clears the puzzle, from any vendor. This benchmark bounds the Claude
  family only, and a genuine deployment decision needs the cheapest competent model on the
  market, not the cheapest Claude.
- **No tool use, no code execution, no multi-sample voting.** A determined attacker would write
  a constraint solver once and never pay per-token reasoning again. This benchmark measures the
  naive-prompting cost, which is an **upper bound on attacker cost, not a lower bound.** That
  matters more now than when it was written: the upper bound already came in at 53–84 output
  tokens and a 100% solve rate, so the scripted-solver arm can only make the picture worse.
- **Six items.** Enough to compare against the human cohort item-for-item; far too few to
  characterise the generator's difficulty distribution.
- **Nothing about detection.** Cost per solve says what an attack costs, not whether it would be
  noticed. Rate limiting, timing distributions and per-IP budgets are out of scope.
- **The withheld grid is a fidelity choice, not a neutral one.** Models are tested on the
  screen-reader presentation. A sighted-control comparison would require rendering the grid as
  text or image, which changes the task — and would need its own condition and its own human
  arm before it could be compared to anything.

---

## 10. Recommended next steps

0. **Treat band 2 as broken and decide what the project is now testing.** §6A settles this on
   270 blind sessions with a passing leakage gate: three models, 100% solve rate, and 53–84
   output tokens at the cheapest reliable setting — 13 on the two pure row/column items. Band 2
   does not impose meaningful machine cost. The accessibility result stands on its own and is worth
   publishing — screen-reader participants beat reCAPTCHA v2 by 50 pp (p = 0.021) — but it must
   no longer be paired with a security claim this data contradicts. Amend the pre-registration
   before anything is written up.
1. **Supply a key and run the 270-session API grid.** ≈$3.36, under an hour. The thinking-off
   floor is now measured (§6A.2), so what the API arm adds is the **dollar figure** and clean
   input-token accounting. It cannot revive the claim — every open measurement can only push
   attacker cost lower — but the number belongs in the record. **Port the two hardening lessons
   across before running it:** blind the runner from the answer key, and include a no-input
   control condition.
2. **Add a scripted-solver arm.** Give one model the six items with code execution and let it
   write the constraint solver. If that is cheap — and `items.py::solve` is 40 lines, so it
   will be — the per-token asymmetry is a statement about naive prompting, not about the puzzle.
   Report it alongside, however unwelcome the number.
3. **Raise replicates to 20+** before any between-model claim (§8.11).
4. **Sweep the bands — but test the right hypothesis.** The N² prediction is already falsified
   at 4×4 for Sonnet and Opus, because they never walk the grid. Going to 5×5 raises the
   *predicted* ratio to 25× and will very likely change nothing measured. The hypothesis worth
   testing is the one §6A.3 raises: **does cost scale with the number of non-axis-decomposable
   (region) clues, rather than with grid size?** Generate items at fixed 4×4 with 0, 1, 2, 3 and
   4 region clues and measure that curve. If cost scales with region clues, the generator has a
   real lever; if it plateaus, the family has no economic defence at any band.
5. ~~**Run a `display: "summarized"` probe** to see whether models enumerate or intersect.~~
   **Answered.** The CLI arm returns visible reasoning, so no probe was needed: Sonnet 5 and
   Opus 5 intersect (**0% enumeration across 180 replies**, median 1 cell named); Haiku 4.5
   enumerates in 40–53%. The generator does need intersection-resistant clue kinds — §6A.3
   measures which ones qualify, and note that *"not touching the edge of the grid"* is itself
   axis-decomposable, so the current `region` tag is too coarse to use as a generator parameter
   without refinement.
9. **Make a leakage gate standard in every future arm.** §8.16 is the methodological finding of
   this work: a no-input control costs one condition and converts "we believe nothing leaked"
   into a measured number (here 1.11% against 6.25% chance). The original design had no such
   gate and so could not have detected leakage even in principle. Any future band sweep,
   scripted-solver arm, or API run should carry one.
6. **Amend the pre-registration on three points:** the orientation/execution decomposition (§5,
   §7.4), the fact that Claim D covers only the prototype arm (§8.9), and the failure of the
   asymmetry premise itself (§6A.2).
8. **Measure the accessibility cost of region clues before hardening on them.** They are the only
   lever that bites machines (4–5×), but they also raised human mean attempts from ~1.03 to
   ~1.36 in the existing data. Hardening the puzzle against models by making it harder for
   screen-reader users would defeat the point of the project. Quantify that trade on the same
   harness before committing.
7. **Feed R3 back into the human report** as an order-free item-difficulty ranking, resolving the
   I0012/I0014 instance-versus-sequence confound (§8.10).

---

## 11. Files

| Path | Contents |
|---|---|
| `items.py` | Item loading, app-invariant checks, independent solver. Runnable. |
| `prompts.py` | Verbatim prompt construction and the three conditions. Runnable. |
| `run_benchmark.py` | The runner: retries, resume, per-attempt records, `--dry-run` costing. |
| `analyze_benchmark.py` | Aggregation to CSVs and the R1–R5 splice into §6. |
| `requirements.txt` | `anthropic>=1.0.0`. |
| `test_offline.py` | Offline harness verification: request shape, attempt state machine, answer parsing, error capture. No key, no cost. Runnable. |
| `run_cli_arm.py` | **Blind** subscription/CLI arm. Holds no answers; `--tools ""`, empty temp `cwd` per call. Records what was submitted, not whether it was right. |
| `grade_runs.py` | The **only** place the answer key is read, and it runs after collection. Enforces the integrity and leakage gates, then aggregates and splices §6A. |
| `output/runs.jsonl` | One JSON object per session, every attempt and response retained. |
| `output/model_condition_summary.csv` | One row per (model, condition). |
| `output/model_instance_summary.csv` | One row per (model, condition, item). |
| `output/human_vs_model.csv` | Per-item human/model comparison and cost ratios. |
| `output/diagnostics.csv` | Parse failures, truncations, retries, cache leaks. |
| `output/cli_arm_runs.jsonl` | 360 blind sessions, `harness_version: 2`. No answer key present. Never pooled with `runs.jsonl`. |
| `output/cli_arm_condition_summary.csv` | One row per (model, condition), control included. |
| `output/cli_arm_item_summary.csv` | Per-item, pooled over clue-bearing conditions, against the human figures. |
| `output/cli_arm_tables.md` | The C0–C2 markdown fragment spliced into §6A. |

All pre-fix result files were **deleted**, not archived: they were collected while the answer key
was readable by the models under test (§8.16) and must not be reachable by any later analysis.
`grade_runs.py` additionally refuses any row without `harness_version: 2`.

Nothing in this directory reads, writes or depends on participant data. It touches only
`data/instances.json` and the aggregate CSVs already published in
`analysis/rohan_study_report/output/`.
