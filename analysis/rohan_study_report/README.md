# Reproducible study analysis

This folder contains the scripts, notebook, tables, figures, and technical
report generated from `Rohan.xlsx`. The source workbook is never modified.

## Run from the repository root

```bash
python3 -m venv .venv-analysis
.venv-analysis/bin/python -m pip install -r analysis/rohan_study_report/requirements.txt
.venv-analysis/bin/python analysis/rohan_study_report/analyze_study.py \
  --input "/Users/vaibhav_joshi/Downloads/Rohan.xlsx" \
  --output analysis/rohan_study_report/output
```

The primary analysis uses the earliest row for repeated
`session_id + condition + item_index` keys and compares only sessions containing
six prototype trials and one baseline trial. The sensitivity table excludes
every session that contained a repeated submission.

The HTML report is the copy-ready publication draft. Bracketed placeholders
mark study-administration facts that are not present in the workbook and must
be completed by the research team before submission.

## Rebuild and validate the report

```bash
.venv-analysis/bin/python analysis/rohan_study_report/make_notebook.py
.venv-analysis/bin/python analysis/rohan_study_report/build_report_artifact.py
.venv-analysis/bin/python analysis/rohan_study_report/validate_results.py \
  --input "/Users/vaibhav_joshi/Downloads/Rohan.xlsx" \
  --analysis-dir analysis/rohan_study_report
```

`report.html` is self-contained and can be opened directly in a browser. Its
text, tables, references, and figure captions can be copied into a journal
template. The `output` directory contains exact CSV values and separate PNG/SVG
figures for manuscript submission systems.
