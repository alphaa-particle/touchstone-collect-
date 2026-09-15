# Reproducible study analysis

Scripts, notebook, tables, figures and the technical report for the blind-user study: 21 adult
screen-reader users, accessible grid prototype versus reCAPTCHA v2, 11–26 August 2026.

## Data

The source is `analysis/data/human_trials_export_2026-09-04.csv`, the Supabase trial export of
4 September 2026. It is identical, row for row, to the `Rohan.xlsx` workbook the committed outputs
were first built from. `analysis/data/README.md` records its checksum, contents and the fields it
does not contain. The export is never modified.

## Run from `touchstone-collect/`

```bash
python3 -m venv .venv-analysis
.venv-analysis/bin/python -m pip install -r analysis/rohan_study_report/requirements.txt
.venv-analysis/bin/python analysis/rohan_study_report/analyze_study.py
```

`--input` defaults to the CSV above (an `.xlsx` export also works) and `--output` to
`analysis/rohan_study_report/output`.

The primary analysis uses the earliest row for repeated `session_id + condition + item_index`
keys and compares only sessions containing six prototype trials and one baseline trial. The
sensitivity table excludes every session that contained a repeated submission.

`report.html` is the copy-ready draft of 4 September 2026. Bracketed placeholders mark
study-administration facts that are not in the data and must be completed by the research team.

## Rebuild and validate the report

```bash
.venv-analysis/bin/python analysis/rohan_study_report/make_notebook.py
.venv-analysis/bin/python analysis/rohan_study_report/build_report_artifact.py
.venv-analysis/bin/python analysis/rohan_study_report/validate_results.py
```

The committed notebook, `artifact.json` and `report.html` were produced on 4 September 2026 from
`Rohan.xlsx`. The CSV holds the same data, so their numbers stand.

## Known gaps

This export cannot show whether a participant was actually presented with reCAPTCHA's audio
challenge, or which cell a participant chose on a wrong attempt. Those fields were logged and are
still in Supabase; export them with `analysis/data/export_remaining_tables.sql`.
