-- ============================================================================
-- TOUCHSTONE-COLLECT :: Supabase / Postgres schema  (v2, adults only)
-- Project Touchstone, human testing harness
--
-- v2 CHANGES
--   * minor_mode removed entirely. Adults only is now a structural
--     constraint, not a runtime flag. Less code, no degraded path.
--   * has_lawful_guardian screening gate added (DPDP s.9(1)).
--   * Everything else unchanged. The trials contract did not move.
--
-- Idempotent. Safe to re-run.
-- Apply via Supabase Dashboard -> SQL Editor, or `psql < schema.sql`.
--
-- DESIGN RULES ENCODED HERE
--   1. No column may ever hold a name, email, phone, address, or IP.
--   2. `trials` mirrors the frozen trials_human.csv contract and nothing else.
--      Anything extra lives in `events`.
--   3. Every write is idempotent. Retries from a flaky school wifi are free.
--   4. All timing is reconstructed server-side from a monotonic client clock
--      plus a per-session server anchor. Device wall clocks are never trusted.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- participants : mirrors participants.csv (plan doc s5.3)
-- participant_id is the ONLY identifier that exists anywhere in this system.
-- ---------------------------------------------------------------------------
create table if not exists participants (
    participant_id        text primary key
        check (participant_id ~ '^[PC][0-9]{2,3}$'),

    cohort                text not null
        check (cohort in ('screen_reader_school',
                          'screen_reader_community',
                          'sighted_control')),
    site                  text not null
        check (site in ('school_01', 'xrcvc', 'remote')),

    age_band              text
        check (age_band in ('18_25', '26_40', '41_60', '60_plus')),
    vision_status         text
        check (vision_status in ('blind_no_light_perception',
                                 'blind_light_perception',
                                 'low_vision',
                                 'sighted')),
    primary_screen_reader text
        check (primary_screen_reader in ('nvda','jaws','talkback','voiceover','other','none')),
    screen_reader_version text,
    browser               text,
    browser_version       text,
    sr_experience_years   integer check (sr_experience_years >= 0),
    device_used           text check (device_used in ('desktop','mobile')),
    braille_display       boolean,

    -- Ethics gates. A row cannot exist unless all three hold.
    consent_recorded      boolean not null default true
        check (consent_recorded = true),
    consent_date          date not null,

    -- ADULTS ONLY. age_band has no sub-18 value, so the check constraint
    -- above is itself the age gate -- a minor cannot be represented in this
    -- table at all. This is deliberate: the ban is structural, not procedural.
    is_adult              boolean not null default true
        check (is_adult = true),

    -- DPDP Act 2023 s.9(1) requires verifiable guardian consent before
    -- processing the personal data of a person with disability who has a
    -- LAWFUL GUARDIAN -- a specific legal status, not a carer or family
    -- member. Screen for it in the consent script. If true, the person is
    -- not eligible under this protocol and no row should exist.
    has_lawful_guardian   boolean not null default false
        check (has_lawful_guardian = false),

    created_at            timestamptz not null default now()
);

comment on table participants is
    'Anonymised participant register. Adults only, enforced by constraint. No name, email, phone, employer, address beyond city, photograph, or face recording. Ever.';


-- ---------------------------------------------------------------------------
-- sessions : one row per participant sitting. Carries the clock anchor.
-- ---------------------------------------------------------------------------
create table if not exists sessions (
    session_id        uuid primary key default gen_random_uuid(),

    -- Unguessable URL token. The paper strip mapping token -> person is
    -- destroyed at the end of the session and never written down.
    token             text unique not null,

    participant_id    text not null references participants(participant_id),

    -- Counterbalancing, pre-assigned before the session. Never randomised
    -- at runtime -- you must be able to state the assignment in advance.
    block_order       text not null
        check (block_order in ('baseline_first', 'prototype_first')),

    baseline_source   text not null default 'recaptcha_v2'
        check (baseline_source in ('recaptcha_v2','replica','not_applicable')),

    language          text not null default 'en'
        check (language in ('en','hi')),

    instance_bundle   text not null,   -- build hash of the static instances file

    -- Clock anchor (dev plan s3.4). Client reports monotonic offsets;
    -- server reconstructs wall clock from these two values.
    clock_anchor_server_ms  bigint,
    clock_anchor_perf_ms    double precision,

    started_at        timestamptz not null default now(),
    completed_at      timestamptz,
    aborted           boolean not null default false,

    -- Environment, captured for reproducibility. NOT for identification.
    user_agent        text,
    viewport_w        integer,
    viewport_h        integer
);

create index if not exists sessions_participant_idx on sessions(participant_id);

comment on column sessions.token is
    'Unguessable session token. Not derived from participant_id. Never logged alongside any human-readable identifier.';


-- ---------------------------------------------------------------------------
-- trials : THE FROZEN CONTRACT. One row per participant per challenge.
--
-- Do not add columns to this table. Anything you want later goes in `events`.
-- Column order below is the export order of trials_human.csv.
-- ---------------------------------------------------------------------------
create table if not exists trials (
    trial_pk              uuid primary key default gen_random_uuid(),
    trial_id              text unique,          -- T0001..., assigned at export
    session_id            uuid not null references sessions(session_id),

    participant_id        text not null references participants(participant_id),
    cohort                text not null,
    site                  text not null,
    condition             text not null
        check (condition in ('audio_captcha_baseline',
                             'touchstone_grid',
                             'touchstone_haystack')),
    instance_id           text not null,        -- FK to instances.csv, or site_id for baseline
    baseline_source       text,
    order_position        integer not null,     -- 1,2,3 -- counterbalancing record
    item_index            integer not null,     -- position within its block

    -- --- timing (dev plan s3) -------------------------------------------
    item_start_ts         timestamptz,          -- participant pressed Start
    first_input_ts        timestamptz,          -- earliest-of-three, see s3.3
    submit_ts             timestamptz,

    solve_time_s          numeric(10,3),        -- submit - item_start   PRIMARY
    orientation_time_s    numeric(10,3),        -- first_input - item_start
    execution_time_s      numeric(10,3),        -- submit - first_input

    -- raw candidate signals, so any alternative definition can be recomputed
    first_focus_ts        timestamptz,
    first_keydown_ts      timestamptz,
    first_pointer_ts      timestamptz,

    -- --- outcome ---------------------------------------------------------
    correct               smallint check (correct in (0,1)),
    attempts              integer not null default 0 check (attempts >= 0),
    gave_up               smallint not null default 0 check (gave_up in (0,1)),
    perceived_difficulty  smallint check (perceived_difficulty between 1 and 5),
    tab_away_events       integer not null default 0,
    tab_away_max_ms       integer not null default 0,   -- drives the exclusion rule

    -- --- context ---------------------------------------------------------
    language              text not null default 'en',
    is_practice           smallint not null default 0 check (is_practice in (0,1)),
    excluded              smallint not null default 0 check (excluded in (0,1)),
    exclusion_reason      text,
    notes                 text check (char_length(notes) <= 500),

    -- --- integrity -------------------------------------------------------
    -- Idempotency. A retry from a dropped connection collides here and is
    -- discarded rather than creating a phantom trial.
    idem_key              text unique not null,
    received_at           timestamptz not null default now(),
    clock_suspect         boolean not null default false
);

create index if not exists trials_session_idx     on trials(session_id);
create index if not exists trials_participant_idx on trials(participant_id);
create index if not exists trials_condition_idx   on trials(condition);

comment on table trials is
    'Frozen contract mirroring trials_human.csv. DO NOT ADD COLUMNS. Extra measurements belong in events.';
comment on column trials.solve_time_s is
    'PRIMARY measure: submit_ts - item_start_ts. Computed server-side from the two raw timestamps so it is always reproducible from them.';
comment on column trials.idem_key is
    'session_id:item_index:attempt_no. Makes every write safe to retry.';


-- ---------------------------------------------------------------------------
-- events : append-only firehose. Everything the frozen schema does not carry.
-- Never used for the primary analysis. Used for debugging the interface and
-- for any post-hoc question you did not think of in August.
-- ---------------------------------------------------------------------------
create table if not exists events (
    event_id      bigserial primary key,
    session_id    uuid not null references sessions(session_id),
    item_index    integer,
    attempt_no    integer,

    event_type    text not null,
    -- item_start | focus | keydown | pointer | answer_change | submit
    -- attempt_result | give_up | visibility_hidden | visibility_visible
    -- window_blur | window_focus | difficulty_rating | consent | resume

    perf_ms       double precision not null,   -- monotonic offset from anchor
    payload       jsonb not null default '{}'::jsonb,

    idem_key      text unique not null,
    received_at   timestamptz not null default now()
);

create index if not exists events_session_idx on events(session_id, item_index);
create index if not exists events_type_idx    on events(event_type);


-- ---------------------------------------------------------------------------
-- Row Level Security
-- Nothing reaches this database except through the server-side API routes,
-- which hold the service role key. The anon key gets nothing.
-- ---------------------------------------------------------------------------
alter table participants enable row level security;
alter table sessions     enable row level security;
alter table trials       enable row level security;
alter table events       enable row level security;
-- No policies are created, so anon and authenticated roles have no access.
-- The service_role key bypasses RLS and is used only by /api/* on the server.


-- ---------------------------------------------------------------------------
-- Export view : byte-exact trials_human.csv column order.
-- /api/export selects * from this and streams it as text/csv.
-- ---------------------------------------------------------------------------
create or replace view v_trials_human as
select
    t.trial_id,
    t.participant_id,
    t.cohort,
    t.site,
    t.condition,
    t.instance_id,
    t.baseline_source,
    t.order_position,
    to_char(t.item_start_ts  at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as item_start_ts,
    to_char(t.first_input_ts at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as first_input_ts,
    to_char(t.submit_ts      at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') as submit_ts,
    t.solve_time_s,
    t.orientation_time_s,
    t.execution_time_s,
    t.correct,
    t.attempts,
    t.gave_up,
    t.perceived_difficulty,
    t.tab_away_events,
    t.language,
    t.is_practice,
    t.excluded,
    t.exclusion_reason,
    t.notes
from trials t
order by t.participant_id, t.order_position, t.item_index;


-- ---------------------------------------------------------------------------
-- Operator dashboard view : what /ops renders. One row per live session.
-- ---------------------------------------------------------------------------
create or replace view v_ops_status as
select
    s.token,
    s.participant_id,
    p.cohort,
    s.block_order,
    count(t.trial_pk) filter (where t.is_practice = 0) as items_done,
    max(t.received_at)                                  as last_write,
    extract(epoch from (now() - max(t.received_at)))    as seconds_since_write,
    s.completed_at is not null                          as completed
from sessions s
join participants p on p.participant_id = s.participant_id
left join trials t  on t.session_id = s.session_id
group by s.token, s.participant_id, p.cohort, s.block_order, s.completed_at
order by s.participant_id;


-- ---------------------------------------------------------------------------
-- Pre-committed exclusion rule (dev plan s3.5).
-- Set THRESHOLD before you see any data and never change it afterwards.
-- Run once, after the session, before analysis.
-- ---------------------------------------------------------------------------
-- update trials
--    set excluded = 1,
--        exclusion_reason = 'tab_away_gap_exceeds_threshold'
--  where tab_away_max_ms > 20000      -- <<< THRESHOLD, pre-registered
--    and excluded = 0;


-- ---------------------------------------------------------------------------
-- Sanity checks. Run these before you download anything for analysis.
-- ---------------------------------------------------------------------------
-- 1. Server arithmetic agrees with the raw timestamps.
--    Expect zero rows.
-- select trial_id, solve_time_s,
--        extract(epoch from (submit_ts - item_start_ts)) as recomputed
--   from trials
--  where solve_time_s is not null
--    and abs(solve_time_s - extract(epoch from (submit_ts - item_start_ts))) > 0.002;

-- 2. No duplicate trials survived a retry. Expect zero rows.
-- select session_id, item_index, count(*)
--   from trials group by 1,2 having count(*) > 1;

-- 3. Every participant completed both blocks. Expect zero rows.
-- select participant_id, count(distinct condition) as conditions
--   from trials where is_practice = 0
--  group by 1 having count(distinct condition) < 2;

-- 4. Every participant is an adult with no lawful guardian. Expect zero rows.
-- select participant_id from participants
--  where is_adult is not true or has_lawful_guardian is not false
--     or age_band not in ('18_25','26_40','41_60','60_plus');

-- 5. Nothing that could be PII leaked into notes. Eyeball this.
-- select trial_id, notes from trials where notes is not null;
