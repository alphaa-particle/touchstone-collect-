import { NextResponse, type NextRequest } from 'next/server';
import { sb } from '@/lib/supabase';
import { BUNDLE_HASH } from '@/lib/instances';

export const dynamic = 'force-dynamic';

/* The clock anchor.

   The client sends the performance.now() reading it took immediately before
   the request; the server pairs it with its own wall clock on arrival. That
   pair is the ONLY use of wall-clock time in the whole session (invariant M1)
   and the only permitted Date.now() in the codebase.

   Absolute timestamps therefore carry the outbound network leg as a constant
   offset (tens of milliseconds). Every measured interval -- solve,
   orientation, execution -- is a difference of two monotonic readings and is
   unaffected by it. Intervals are the measures; absolute times are only
   provenance.

   Re-called on every page load, including a resume after a force-quit: a new
   page load starts a new performance timeline and so needs a fresh anchor.
   Trials queued by the previous load carry their own anchor in their payload,
   so old rows still reconstruct correctly. */
export async function POST(req: NextRequest) {
  let body: { token?: string; perf_ms?: number; viewport_w?: number; viewport_h?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'bad json' }, { status: 400 });
  }
  const { token, perf_ms, viewport_w, viewport_h } = body;
  if (!token || typeof perf_ms !== 'number') {
    return NextResponse.json({ error: 'token and perf_ms required' }, { status: 400 });
  }

  const { data: rows, error } = await sb
    .from('sessions')
    .select('session_id,participant_id,block_order,language')
    .eq('token', token)
    .limit(1);
  if (error) return NextResponse.json({ error: 'db' }, { status: 503 });

  const s = rows?.[0];
  if (!s) return NextResponse.json({ error: 'unknown token' }, { status: 404 });

  const { data: pRows } = await sb
    .from('participants')
    .select('cohort,site')
    .eq('participant_id', s.participant_id)
    .limit(1);
  const p = pRows?.[0];
  if (!p) return NextResponse.json({ error: 'unknown participant' }, { status: 404 });

  const server_epoch_ms = Date.now();

  await sb
    .from('sessions')
    .update({
      clock_anchor_server_ms: server_epoch_ms,
      clock_anchor_perf_ms: perf_ms,
      instance_bundle: BUNDLE_HASH,
      user_agent: req.headers.get('user-agent'),
      viewport_w: typeof viewport_w === 'number' ? viewport_w : null,
      viewport_h: typeof viewport_h === 'number' ? viewport_h : null,
    })
    .eq('session_id', s.session_id);

  return NextResponse.json({
    session_id: s.session_id,
    server_epoch_ms,
    participant_id: s.participant_id,
    cohort: p.cohort,
    site: p.site,
    block_order: s.block_order,
    language: s.language,
  });
}
