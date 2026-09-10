# GPT subscription benchmark

204/232 clue-bearing sessions solved (87.93%). 304 total sessions, including controls; 5 repetitions per item and condition.

## By model and condition

| Model | Condition | N | Solve % | Median output tokens | Median reasoning tokens | Median wall seconds | Parse failures |
|---|---|---|---|---|---|---|---|
| gpt-5.6-luna | thinking_off | 30 | 60.0 | 8.0 | 0.0 | 5.13 | 0 |
| gpt-5.6-luna | effort_low | 24 | 100.0 | 81.5 | 71.5 | 6.32 | 0 |
| gpt-5.6-luna | effort_high | 24 | 100.0 | 151.5 | 140.5 | 7.63 | 0 |
| gpt-5.6-luna | control_no_clues | 24 | 0.0 | 122.5 | 112.5 | 7.25 | 0 |
| gpt-5.6-terra | thinking_off | 29 | 62.07 | 11.0 | 0.0 | 5.11 | 0 |
| gpt-5.6-terra | effort_low | 24 | 100.0 | 62.5 | 49.5 | 6.06 | 0 |
| gpt-5.6-terra | effort_high | 24 | 100.0 | 74.0 | 62.5 | 6.44 | 0 |
| gpt-5.6-terra | control_no_clues | 24 | 0.0 | 132.0 | 120.5 | 8.59 | 0 |
| gpt-5.6-sol | thinking_off | 29 | 82.76 | 11.0 | 0.0 | 5.74 | 0 |
| gpt-5.6-sol | effort_low | 24 | 100.0 | 66.5 | 53.5 | 7.31 | 0 |
| gpt-5.6-sol | effort_high | 24 | 100.0 | 117.5 | 107.5 | 9.11 | 0 |
| gpt-5.6-sol | control_no_clues | 24 | 0.0 | 231.0 | 221.0 | 13.75 | 1 |

## No-clues control

| Model | Correct | N | % | Gate |
|---|---|---|---|---|
| gpt-5.6-luna | 0 | 24 | 0.0 | PASS |
| gpt-5.6-terra | 0 | 24 | 0.0 | PASS |
| gpt-5.6-sol | 0 | 24 | 0.0 | PASS |
| POOLED | 0 | 72 | 0.0 | PASS |

The predeclared gate is at most 25% correct, checked per model and pooled. Uniform random guessing would average 6.25% on a 4x4 grid. These fixed items and model guesses are not necessarily uniform or independent; passing this diagnostic alone does not prove absence of contamination.

## Isolation and comparability

- Same six canonical puzzles, prompt text, answer parser, visible-strategy heuristics and single-attempt design as the Claude subscription arm. This is not the three-attempt API arm.
- Collection reads only a strictly allowlisted prompt export. Preparation and offline grading are separate processes. No answer key, report, prior result, or correctness feedback is submitted.
- Fresh ephemeral CLI conversation and empty working directory for every attempt. User configuration, project instructions, skills, memories, plugins, MCP and model tools are disabled. A tool-only catalog override also disables the model's built-in tool selection.
- Before collection, a localhost fixture checks the actual serialized request for each model/effort: no tools (including additional-tools items), only the supplied base instructions and user prompt, no previous response. Every real result's JSON event stream is checked for non-text/tool activity. The fixture uses a local provider; it does not capture authenticated production traffic.
- `thinking_off` explicitly requests `none`; every accepted off run reports zero reasoning tokens. Low/high are requested explicitly. A model may choose zero reasoning tokens even when reasoning is enabled.
- Model IDs are exact configured/requested IDs, checked in local wire audits and subscription readiness probes. Codex JSON output does not expose an independent server-reported model ID; none is invented.
- Output and reasoning counters come directly from Codex `turn.completed.usage`; reasoning is a subset of total output. Input/cache counts include CLI overhead. Strategy metrics inspect the visible answer only, not hidden reasoning.
- Latency is end-to-end CLI wall time with 3 concurrent worker(s), including startup and transport overhead. API-only latency and dollar cost per solve are unavailable and left blank, never reported as zero. All model calls use ChatGPT subscription authentication.
- 3 failed collection attempts recorded; each planned session must have exactly one completed result before grading.

## Provenance

CLI: `codex-cli 0.153.4`. Collection created: `2026-09-10T06:58:45.885481+00:00`.

Manifest SHA256: `aa921ccf922b954acd2b9c9a79a10610393d7d7e5ffe8173ddc2091257012c26`. See the matching `.manifest.json` for code/input/catalog hashes, request audits, readiness probes and the full plan.

[Subscription authentication](https://learn.chatgpt.com/docs/auth), [Codex configuration schema](https://developers.openai.com/codex/config-schema.json).
