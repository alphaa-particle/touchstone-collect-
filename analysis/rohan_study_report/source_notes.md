# Report source and QA notes

- Audience: technical/research manuscript readers.
- Delivery mode: self-contained portable HTML.
- Source workbook: `Rohan.xlsx`, worksheet `Supabase Snippet Untitled query`.
- Snapshot period: 11–26 August 2026 UTC.
- Data status: usable for exploratory paired analysis with material caveats.
- Primary analysis grain: participant session.
- Raw source handling: read-only; the workbook was not copied or modified.

## Technical-report structure mapping

- Technical summary: `Technical summary` and `Abstract`.
- Key findings with visual evidence: paired success, ratings, and instance-performance sections.
- Scope, data, and metric definitions: cohort/denominator, protocol, and statistical-analysis sections.
- Methodology: implemented protocol, cleaning rule, estimands, inference, multiplicity, and software versions.
- Limitations and robustness: data-quality, sensitivity/order, and limitations sections.
- Recommended next steps: `Recommended next study`.
- Further questions: `Further questions`.

## Chart map

| Report segment | Question | Visual | Fields | Supported claim |
| --- | --- | --- | --- | --- |
| Paired task success | How often did complete paired participants succeed in each condition? | Two-bar rate comparison | condition, success_rate | Prototype condition success was 75% versus 25% baseline in 16 pairs. |
| Subjective ratings | How did the five 1–5 condition ratings differ? | Grouped bars plus exact-results table | measure, condition, median | Directional differences were not significant after Holm correction. |
| Instance performance | Which fixed prototype items were slower? | Bar chart plus accuracy/time table | instance_id, median_time_s | I0012 and I0014 had the longest medians; instance and sequence are confounded. |

Standalone PNG/SVG figures use a colorblind-safe palette. Exact chart values are
available in the adjacent CSV tables and in the report's semantic fallback.

## Omitted or bounded analyses

- No inferential speed comparison: the baseline contained one task, the
  prototype contained six, and baseline failures were terminated by give-up;
  timing is descriptive only.
- No demographic moderator tests: the sample is too small and categories are
  sparse; eight onset/age profiles are logically inconsistent.
- No qualitative analysis: the workbook has no open-text responses.
- No claim about general reasoning ability: the six grid items are not a validated
  cognitive instrument.
- No security-effectiveness analysis: the dataset contains human usability outcomes,
  not adversarial or bot-performance data.

## Validation receipt

The packaged report passed canonical artifact validation, packaging, native-chart
extraction, source-dialog keyboard interaction, and responsive browser checks at
1440 px and 390 px. It contains 34 ordered blocks, three charts, three metric
cards, and five tables. The independent validator also recomputed the primary
counts and exact McNemar p value from the workbook, confirmed all notebook code
cells executed without errors, and verified report/snapshot consistency.
