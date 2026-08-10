import { NextResponse, type NextRequest } from 'next/server';
import { sb } from '@/lib/supabase';
import { TAB_AWAY_THRESHOLD_MS } from '@/lib/instances';
import type { Anchor, Marks, TrialPayload } from '@/lib/types';

export const dynamic = 'force-dynamic';

/* Session config is immutable for the life of a session, so it is looked up
   once per serverless instance rather than on every trial. Correctness does
   not depend on the cache surviving; a cold instance just re-reads. */
type Cfg = {
  participant_id: string;
  cohort: string;
  site: string;
  language: string;
  baseline_source: string;
};
const cfgCache = new Map<string, Cfg>();

async function config(session_id: string): Promise<Cfg | null> {
  const hit = cfgCache.get(session_id);
  if (hit) return hit;

  const { data: sRows } = await sb
    .from('sessions')
    .select('participant_id,language,baseline_source')
    .eq('session_id', session_id)
    .limit(1);
  const s = sRows?.[0];
  if (!s) return null;

  const { data: pRows } = await sb
    .from('participants')
    .select('cohort,site')
    .eq('participant_id', s.participant_id)
    .limit(1);
  const p = pRows?.[0];
  if (!p) return null;

  const cfg: Cfg = {
    participant_id: s.participant_id,
    cohort: p.cohort,
    site: p.site,
    language: s.language,
    baseline_source: s.baseline_source,
  };
  cfgCache.set(session_id, cfg);
  return cfg;
}

export async function POST(req: NextRequest) {
  let b: TrialPayload;
  try {
    b = (await req.json()) as TrialPayload;
  } catch {
    return NextResponse.json({ error: 'bad json' }, { status: 400 });
  }

  const a = b.anchor as Anchor | undefined;
  const m = b.marks as Marks | undefined;
  if (
    !b.session_id ||
    !b.idem_key ||
    !b.condition ||
    !b.instance_id ||
    typeof b.item_index !== 'number' ||
    !a ||
    typeof a.server_epoch_ms !== 'number' ||
    typeof a.perf_ms !== 'number' ||
    !m ||
    typeof m.item_start_perf !== 'number' ||
    typeof m.submit_perf !== 'number'
  ) {
    return NextResponse.json({ error: 'malformed trial' }, { status: 400 });
  }

  const cfg = await config(b.session_id);
  if (!cfg) return NextResponse.json({ error: 'unknown session' }, { status: 404 });

  /* ---- the arithmetic. Server-side only (invariant M2). --------------------
     Every mark is reconstructed to integer epoch milliseconds FIRST, and the
     durations are then differences of those same integers. That is why
     solve_time_s always reproduces exactly from item_start_ts and submit_ts in
     the CSV -- sanity query 1 in schema.sql returns zero rows by construction,
     not by luck. */
  const abs = (perf: number) => Math.round(a.server_epoch_ms + (perf - a.perf_ms));
  const iso = (ms: number | null) => (ms === null ? null : new Date(ms).toISOString());
  const secs = (from: number, to: number) => Number(((to - from) / 1000).toFixed(3));

  const startMs = abs(m.item_start_perf);
  const submitMs = abs(m.submit_perf);

  const focusMs = typeof m.first_focus_perf === 'number' ? abs(m.first_focus_perf) : null;
  const keyMs = typeof m.first_keydown_perf === 'number' ? abs(m.first_keydown_perf) : null;
  const ptrMs = typeof m.first_pointer_perf === 'number' ? abs(m.first_pointer_perf) : null;

  /* first_input_ts is the earliest of the three signals. All three are stored
     separately as well (invariant M4): each one alone is unreliable on at
     least one target configuration, and keeping the raw signals means any
     alternative definition can be recomputed after the fact. */
  const cands = [focusMs, keyMs, ptrMs].filter((v): v is number => v !== null);
  const firstMs = cands.length ? Math.min(...cands) : null;

  const overThreshold = (b.tab_away_max_ms ?? 0) > TAB_AWAY_THRESHOLD_MS;

  const row = {
    session_id: b.session_id,
    participant_id: cfg.participant_id,
    cohort: cfg.cohort,
    site: cfg.site,
    condition: b.condition,
    instance_id: b.instance_id,
    baseline_source:
      b.condition === 'audio_captcha_baseline' ? cfg.baseline_source : 'not_applicable',
    order_position: b.order_position,
    item_index: b.item_index,

    item_start_ts: iso(startMs),
    first_input_ts: iso(firstMs),
    submit_ts: iso(submitMs),

    solve_time_s: secs(startMs, submitMs),
    orientation_time_s: firstMs === null ? null : secs(startMs, firstMs),
    execution_time_s: firstMs === null ? null : secs(firstMs, submitMs),

    first_focus_ts: iso(focusMs),
    first_keydown_ts: iso(keyMs),
    first_pointer_ts: iso(ptrMs),

    correct: b.correct,
    attempts: b.attempts ?? 0,
    gave_up: b.gave_up ?? 0,
    tab_away_events: b.tab_away_events ?? 0,
    tab_away_max_ms: b.tab_away_max_ms ?? 0,

    language: cfg.language,
    is_practice: b.is_practice ?? 0,
    excluded: overThreshold ? 1 : 0,
    exclusion_reason: overThreshold ? 'tab_away_gap_exceeds_threshold' : null,
    notes: b.notes ?? null,

    idem_key: b.idem_key,
    /* A device whose wall clock is hours out still produces correct durations,
       because durations are monotonic differences. The flag records that its
       absolute timestamps should not be trusted. */
    clock_suspect: Math.abs(new Date().getTime() - submitMs) > 300000,
  };

  const { error } = await sb
    .from('trials')
    .upsert(row, { onConflict: 'idem_key', ignoreDuplicates: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 503 });
  return NextResponse.json({ ok: true });
}
