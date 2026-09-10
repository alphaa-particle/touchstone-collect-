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