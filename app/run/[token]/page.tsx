import { notFound } from 'next/navigation';
import { sb } from '@/lib/supabase';
import Runner from './Runner';

export const dynamic = 'force-dynamic';

/* Resolve the token, 404 on anything unknown, hand the config down. Access
   control is the unguessable URL and nothing else: no auth, no accounts, no
   login (invariant S1). */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;

  const { data: sRows } = await sb
    .from('sessions')
    .select('session_id,participant_id,block_order,language')
    .eq('token', token)
    .limit(1);
  const s = sRows?.[0];
  if (!s) notFound();

  const { data: pRows } = await sb
    .from('participants')
    .select('cohort,site')
    .eq('participant_id', s.participant_id)
    .limit(1);
  const p = pRows?.[0];
  if (!p) notFound();

  return (
    <Runner
      token={token}
      config={{
        session_id: s.session_id,
        participant_id: s.participant_id,
        cohort: p.cohort,
        site: p.site,
        block_order: s.block_order,
        language: s.language,
      }}
    />
  );
}
