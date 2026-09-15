# Study data

## `human_trials_export_2026-09-04.csv`

The human-study trial table, exported from Supabase with a joined SQL query on 4 September 2026
(downloaded as `Rohan Data - Supabase Snippet Untitled query (1).csv.csv`). It is the analysis
source for `analysis/rohan_study_report/`.

| Property | Value |
|---|---|
| SHA-256 | `d89312a1f266d404ad33dd998535a4c947a406ad012b91be904d495c7480aa27` |
| Rows | 130 trial rows (110 prototype, 20 reCAPTCHA baseline); 127 after the earliest-record rule |
| People | 21 participants in 21 sessions, collected 11–26 August 2026 |
| Columns | 38: trial outcome and timing fields, the five 1–5 condition ratings, and the participant profile answers |
| Identifiers | Pseudonymous participant codes (P02–P27) and session UUIDs; no names or contact details |

**Verified on 15 September 2026.** Every row and value matches the `Rohan.xlsx` workbook the
committed outputs were built from; the only differences are how some timestamps are written. All
17 published headline numbers recompute exactly from this file: 127 surviving trials, 16 paired
sessions, 12/16 versus 4/16 successes, exact McNemar p = 0.021484375, 103/108 prototype items
correct, and every per-item median time.

### What this export does not contain

| Needed for | Missing field | Where it is |
|---|---|---|
| Whether reCAPTCHA showed an audio challenge (plan H1) | trial `notes` (`baseline_not_triggered`) and `challenge_shown` | `trials.notes`, `events.payload` |
| Which cell a participant chose on a wrong attempt (plan H4) | the submitted answer for each attempt | `events` rows with `event_type = 'attempt_result'` |
| Alternative reading and acting time definitions (plan H5) | `item_start_ts`, `submit_ts`, `first_focus_ts`, `first_keydown_ts`, `first_pointer_ts` | `trials` |
| Tab-away rule and the practice item | `tab_away_max_ms`, rows with `is_practice = 1` | `trials` |
| Device and screen-reader platform | `user_agent`, viewport | `sessions` |

The profile fields `age_band`, `vision_status`, `primary_screen_reader`, `screen_reader_version`,
`sr_experience_years`, `device_used` and `braille_display` were never filled in for any participant.

Run `export_remaining_tables.sql` in the Supabase SQL editor and save each result in this folder.
Every statement is read-only. Do not use the app's `/ops` "Download CSV" link for this: its default
trials export writes `trial_id` values back into the database.

### Handling

Raw participant-level exports in this folder are git-ignored. Keep them out of the GitHub repository
until the team confirms that consent covers secondary analysis and data release. Derived
participant-level tables in `../rohan_study_report/output/` are already in the repository history.
