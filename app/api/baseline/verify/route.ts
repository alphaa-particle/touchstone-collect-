import { NextResponse, type NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

/* Grades the baseline arm with zero operator judgement: the client's reCAPTCHA
   token is verified against Google, and `correct` comes straight back from
   that. Nobody watches over a participant's shoulder and decides. */
export async function POST(req: NextRequest) {
  let body: { token?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'bad json' }, { status: 400 });
  }
  const secret = process.env.RECAPTCHA_SECRET_KEY;
  if (!secret) return NextResponse.json({ error: 'not configured' }, { status: 503 });
  if (!body.token) return NextResponse.json({ correct: 0 });

  try {
    const r = await fetch('https://www.google.com/recaptcha/api/siteverify', {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ secret, response: body.token }),
      cache: 'no-store',
    });
    const j = (await r.json()) as { success?: boolean };
    return NextResponse.json({ correct: j.success ? 1 : 0 });
  } catch {
    return NextResponse.json({ error: 'verify unreachable' }, { status: 503 });
  }
}
