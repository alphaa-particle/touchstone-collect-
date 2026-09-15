-- Touchstone: export the already-collected tables the re-analysis still needs.
--
-- Every statement is a read-only SELECT. Run them one at a time in the Supabase SQL editor
-- and use "Download CSV" on each result. Save the files next to this script as:
--   events_export_<YYYY-MM-DD>.csv
--   trials_full_export_<YYYY-MM-DD>.csv
--   sessions_export_<YYYY-MM-DD>.csv
--
-- Do NOT use the app's /ops "Download CSV" link or /api/export for trials: that route writes
-- trial_id values back into the database before exporting.


-- 1. Every logged interaction, with the participant code.
--    Contains the submitted answer for each attempt (event_type = 'attempt_result'),
--    reCAPTCHA challenge_shown flags, "Read the clues again" presses (reread), focus targets,
--    keydown and pointer events, visibility changes and resumes.
select s.participant_id, e.*
from events e
join sessions s on s.session_id = e.session_id
order by s.participant_id, e.received_at, e.perf_ms;


-- 2. All trial rows with every column, including notes (baseline_not_triggered),
--    item_start_ts, submit_ts, first_focus_ts, first_keydown_ts, first_pointer_ts,
--    tab_away_max_ms and the practice rows.
select *
from trials
order by participant_id, order_position, item_index, received_at;


-- 3. Session metadata (user agent, viewport, completion), with the URL token removed.
select to_jsonb(s) - 'token' as session_row
from sessions s
order by s.participant_id;
