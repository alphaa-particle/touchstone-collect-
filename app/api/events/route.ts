import { NextResponse, type NextRequest } from 'next/server';
import { sb } from '@/lib/supabase';
import type { EventPayload } from '@/lib/types';

export const dynamic = 'force-dynamic';

const MAX_BATCH = 200;

export async function POST(req: NextRequest) {
  let batch: EventPayload[];
  try {
    batch = (await req.json()) as EventPayload[];
  } catch {
    return NextResponse.json({ error: 'bad json' }, { status: 400 });
  }
  if (!Array.isArray(batch) || !batch.length) {
    return NextResponse.json({ error: 'expected a non-empty array' }, { status: 400 });
  }
  if (batch.length > MAX_BATCH) {
    return NextResponse.json({ error: `max ${MAX_BATCH} events` }, { status: 400 });
  }

  const rows = batch
    .filter((e) => e && e.session_id && e.event_type && e.idem_key && typeof e.perf_ms === 'number')
    .map((e) => ({
      session_id: e.session_id,
      item_index: e.item_index ?? null,
      attempt_no: e.attempt_no ?? null,
      event_type: e.event_type,
      perf_ms: e.perf_ms,
      payload: e.payload ?? {},
      idem_key: e.idem_key,
    }));
  if (!rows.length) return NextResponse.json({ error: 'no valid events' }, { status: 400 });

  /* Perceived difficulty is asked in-app, once per condition, and belongs on
     every trial of that condition -- but the trials were written minutes
     earlier, and the frozen trials contract has no room for a second insert.
     So it rides in on its event and is applied here.

     Applied before the insert and independent of its outcome, so a retried
     batch re-applies it rather than being swallowed by ON CONFLICT DO NOTHING.
     The queue is FIFO, so by the time this arrives the trials it refers to are
     already in the table. */
  const rating = rows.find((r) => r.event_type === 'difficulty_rating');
  if (rating) {
    const p = rating.payload as { value?: unknown; condition?: unknown };
    const value = Number(p?.value);
    const condition = typeof p?.condition === 'string' ? p.condition : '';
    if (Number.isInteger(value) && value >= 1 && value <= 5 && condition) {
      await sb
        .from('trials')
        .update({ perceived_difficulty: value })
        .eq('session_id', rating.session_id)
        .eq('condition', condition);
    }
  }

  const { error } = await sb
    .from('events')
    .upsert(rows, { onConflict: 'idem_key', ignoreDuplicates: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 503 });
  return NextResponse.json({ ok: true, n: rows.length });
}
