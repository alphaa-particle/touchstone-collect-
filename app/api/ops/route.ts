import { NextResponse, type NextRequest } from 'next/server';
import { sb } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/** v_ops_status as JSON. Same key gate as /ops, same 404-not-401 behaviour. */
export async function GET(req: NextRequest) {
  const key = req.nextUrl.searchParams.get('key');
  if (!process.env.OPS_KEY || key !== process.env.OPS_KEY) {
    return new NextResponse('Not found', { status: 404 });
  }
  const { data, error } = await sb.from('v_ops_status').select('*');
  if (error) return NextResponse.json({ error: error.message }, { status: 503 });
  return NextResponse.json(data ?? []);
}
