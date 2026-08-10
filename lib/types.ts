export type Instance = {
  instance_id: string;
  family: string;
  n: number;
  clues: string[];
  preamble: string;
  question: string;
  solution: string;
  marker: string | null;
  column_options: string[];
  row_options: string[];
  difficulty_band: number;
  asymmetry_ratio: number;
  uniqueness_verified: number;
};

export type Bundle = {
  generator_version: string;
  family: string;
  base_seed: number;
  practice: Instance;
  canonical_set: string[];
  instances: Instance[];
};

export type Condition = 'touchstone_grid' | 'audio_captcha_baseline';

/** Wall clock is anchored exactly once per session, by the server. */
export type Anchor = { server_epoch_ms: number; perf_ms: number };

export type SessionConfig = {
  session_id: string;
  participant_id: string;
  cohort: string;
  site: string;
  block_order: 'prototype_first' | 'baseline_first';
  language: string;
};

/** The five raw monotonic marks. Everything in the CSV is derived from these,
 *  server-side, so any alternative definition can be recomputed later (M4). */
export type Marks = {
  item_start_perf: number;
  first_focus_perf: number | null;
  first_keydown_perf: number | null;
  first_pointer_perf: number | null;
  submit_perf: number;
};

export type TrialPayload = {
  session_id: string;
  item_index: number;
  condition: Condition;
  instance_id: string;
  order_position: number;
  is_practice: 0 | 1;
  anchor: Anchor;
  marks: Marks;
  /** null only on the baseline arm when Google could not be reached to grade. */
  correct: 0 | 1 | null;
  attempts: number;
  gave_up: 0 | 1;
  tab_away_events: number;
  tab_away_max_ms: number;
  notes: string | null;
  idem_key: string;
};

export type EventPayload = {
  session_id: string;
  item_index: number | null;
  attempt_no: number | null;
  event_type: string;
  perf_ms: number;
  payload: Record<string, unknown>;
  idem_key: string;
};
