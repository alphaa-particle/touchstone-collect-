import { NextResponse } from 'next/server';
import { sb } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* Hit daily by the Vercel cron in vercel.json. A Supabase free project pauses
   after 7 days of inactivity; without this the database can be offline on
   session morning with 20 people waiting. A real count, never a stub. */
export async function GET() {
  const { error } = await sb
    .from('participants')
    .select('*', { count: 'exact', head: true });

  const db = !error;
  return NextResponse.json(
    { ok: db, db, ts: new Date().toISOString() },
    { status: db ? 200 : 503 },
  );
}
