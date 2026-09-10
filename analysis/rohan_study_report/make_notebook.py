#!/usr/bin/env python3
"""Create the executable companion notebook for the study analysis."""

from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[2]
TARGET = Path(__file__).resolve().parent / "study_analysis.ipynb"

nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.9"},
}
nb["cells"] = [
    nbf.v4.new_markdown_cell(
        "# Blind-user CAPTCHA study: reproducible analysis\n\n"
        "This notebook executes the checked analysis script, then displays the exact "
        "cohort, quality, inferential, and figure outputs used in the technical report. "
        "The Excel source is read-only."
    ),
    nbf.v4.new_code_cell(
        "from pathlib import Path\n"
        "import os, subprocess, sys\n"
        "import pandas as pd\n"
        "from IPython.display import Image, display\n\n"
        f"PROJECT_ROOT = Path({str(ROOT)!r})\n"
        "INPUT = Path('/Users/vaibhav_joshi/Downloads/Rohan.xlsx')\n"
        "ANALYSIS_DIR = PROJECT_ROOT / 'analysis/rohan_study_report'\n"
        "OUTPUT = ANALYSIS_DIR / 'output'\n"
        "assert INPUT.exists(), 'Update INPUT to the location of Rohan.xlsx'\n"
        "OUTPUT.mkdir(parents=True, exist_ok=True)"
    ),
    nbf.v4.new_markdown_cell(
        "## Analysis specification\n\n"
        "The primary unit is one participant session. Repeated trial keys are resolved "
        "with a deterministic earliest-record rule. A paired-complete session must contain "
        "six unique prototype trials and one baseline trial. The primary binary comparison "
        "uses exact McNemar inference. Five paired ordinal ratings use exact sign-randomized "
        "signed-rank tests with Holm family-wise correction."
    ),
    nbf.v4.new_code_cell(
        "env = os.environ.copy()\n"
        "env.update({'MPLBACKEND': 'Agg', 'MPLCONFIGDIR': '/tmp/touchstone-mpl', "
        "'XDG_CACHE_HOME': '/tmp/touchstone-cache'})\n"
        "run = subprocess.run([sys.executable, str(ANALYSIS_DIR / 'analyze_study.py'), "
        "'--input', str(INPUT), '--output', str(OUTPUT)], cwd=PROJECT_ROOT, env=env, "
        "text=True, capture_output=True, check=True)\n"
        "print(run.stdout)"
    ),
    nbf.v4.new_markdown_cell("## Cohort flow and data quality"),
    nbf.v4.new_code_cell(
        "display(pd.read_csv(OUTPUT / 'sample_flow.csv'))\n"
        "display(pd.read_csv(OUTPUT / 'data_quality_summary.csv'))\n"
        "display(pd.read_csv(OUTPUT / 'profile_consistency.csv'))"
    ),
    nbf.v4.new_markdown_cell("## Primary paired task-success result"),
    nbf.v4.new_code_cell(
        "display(pd.read_csv(OUTPUT / 'paired_outcomes.csv'))\n"
        "display(pd.read_csv(OUTPUT / 'sensitivity_summary.csv'))\n"
        "display(Image(filename=str(OUTPUT / 'figure_1_paired_success.png')))"
    ),
    nbf.v4.new_markdown_cell("## Paired subjective ratings"),
    nbf.v4.new_code_cell(
        "display(pd.read_csv(OUTPUT / 'rating_comparisons.csv'))\n"
        "display(Image(filename=str(OUTPUT / 'figure_2_paired_ratings.png')))"
    ),
    nbf.v4.new_markdown_cell("## Prototype instance performance"),
    nbf.v4.new_code_cell(
        "display(pd.read_csv(OUTPUT / 'instance_summary.csv'))\n"
        "display(Image(filename=str(OUTPUT / 'figure_3_instance_performance.png')))"
    ),
    nbf.v4.new_markdown_cell("## Participant characteristics and order diagnostics"),
    nbf.v4.new_code_cell(
        "display(pd.read_csv(OUTPUT / 'demographic_summary.csv'))\n"
        "display(pd.read_csv(OUTPUT / 'order_effects.csv'))"
    ),
    nbf.v4.new_markdown_cell(
        "## Interpretation guardrails\n\n"
        "The six prototype trials and the single baseline challenge are not matched in task "
        "content or workload. Therefore, solve-time values are descriptive and not treated as "
        "a causal speed comparison. The workbook lacks the baseline `challenge_shown` flag and "
        "trial notes, so successful checkbox-only responses cannot be separated from actual "
        "audio challenges. The grid task measures performance on the implemented elimination "
        "puzzles; it is not a validated general reasoning-ability instrument."
    ),
]

nbf.write(nb, TARGET)
print(TARGET)
