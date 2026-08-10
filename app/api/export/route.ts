import { NextResponse, type NextRequest } from 'next/server';
import { sb } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* The frozen export contract: v_trials_human in schema.sql, in this order,
   byte for byte (invariant D2). Hardcoded rather than inferred from JSON key
   order so that a change to the view fails loudly here instead of silently
   reshaping a dataset mid-collection. */
const TRIALS_HUMAN = [
  'trial_id',
  'participant_id',
  'cohort',
  'site',
  'condition',
  'instance_id',
  'baseline_source',
  'order_position',
  'item_start_ts',
  'first_input_ts',
  'submit_ts',
  'solve_time_s',
  'orientation_time_s',
  'execution_time_s',
  'correct',
  'attempts',
  'gave_up',
  'perceived_difficulty',
  'tab_away_events',
  'language',
  'is_practice',
  'excluded',
  'exclusion_reason',
  'notes',
] as const;

const cell = (v: unknown) => {
  const s = v === null || v === undefined ? '' : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

const csv = (cols: readonly string[], rows: Record<string, unknown>[]) =>
  [cols.join(','), ...rows.map((r) => cols.map((c) => cell(r[c])).join(','))].join('\r\n') +
  '\r\n';

/* trial_id is assigned at export, in the view's own ordering, and written back
   so that it is stable across exports. The operator writes paper notes against
   trial ids; an id that shifted on the next download would misattribute them. */
async function assignTrialIds() {
  const { data } = await sb
    .from('trials')
    .select('trial_pk,trial_id,participant_id,order_position,item_index')
    .order('participant_id')
    .order('order_position')
    .order('item_index');
  if (!data) return;

  let n = data.reduce((max, r) => {
    const parsed = r.trial_id ? parseInt(String(r.trial_id).slice(1), 10) : 0;
    return Number.isFinite(parsed) && parsed > max ? parsed : max;
  }, 0);

  for (const r of data) {
    if (r.trial_id) continue;
    n += 1;
    await sb
      .from('trials')
      .update({ trial_id: `T${String(n).padStart(4, '0')}` })
      .eq('trial_pk', r.trial_pk);
  }
}

export async function GET(req: NextRequest) {
  const key = req.nextUrl.searchParams.get('key');
  if (!process.env.OPS_KEY || key !== process.env.OPS_KEY) {
    return new NextResponse('Not found', { status: 404 });
  }

  const table = req.nextUrl.searchParams.get('table') ?? 'trials_human';
  let name: string;
  let cols: readonly string[] | null = null;

  if (table === 'trials_human') {
    await assignTrialIds();
    name = 'v_trials_human';
    cols = TRIALS_HUMAN;
  } else if (table === 'events' || table === 'participants') {
    name = table;
  } else {
    return new NextResponse('Unknown table', { status: 400 });
  }

  const { data, error } = await sb.from(name).select('*');
  if (error) return new NextResponse(`export failed: ${error.message}`, { status: 503 });
  const rows = (data ?? []) as Record<string, unknown>[];

  if (cols && rows.length) {
    const got = Object.keys(rows[0]);
    const missing = cols.filter((c) => !got.includes(c));
    const extra = got.filter((c) => !(cols as readonly string[]).includes(c));
    if (missing.length || extra.length) {
      return new NextResponse(
        `v_trials_human drifted from the frozen contract. missing=[${missing}] extra=[${extra}]`,
        { status: 500 },
      );
    }
  }
  if (!cols) cols = rows.length ? Object.keys(rows[0]) : ['(empty)'];

  return new NextResponse(csv(cols, rows), {
    status: 200,
    headers: {
      'content-type': 'text/csv; charset=utf-8',
      'content-disposition': `attachment; filename="${table}.csv"`,
      'cache-control': 'no-store',
    },
  });
}
