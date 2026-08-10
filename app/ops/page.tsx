import { notFound } from 'next/navigation';
import { sb } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

type Row = {
  participant_id: string;
  cohort: string;
  block_order: string;
  items_done: number;
  seconds_since_write: number | null;
  completed: boolean;
};

/* Server-rendered, refreshed by a meta tag. No polling framework, no client
   JavaScript at all. Leave this tab open all session: it also keeps the
   serverless function warm. */
export default async function Ops({
  searchParams,
}: {
  searchParams: Promise<{ key?: string }>;
}) {
  const { key } = await searchParams;
  /* Wrong or missing key is a 404, not a 401: a 401 confirms the route exists. */
  if (!process.env.OPS_KEY || key !== process.env.OPS_KEY) notFound();

  const { data, error } = await sb.from('v_ops_status').select('*');
  const rows = (data ?? []) as Row[];

  return (
    <main>
      <meta httpEquiv="refresh" content="15" />
      <h1>Session status</h1>

      {error ? <p>Database unreachable: {error.message}</p> : null}

      <p>
        <a href={`/api/export?key=${encodeURIComponent(key)}`}>Download CSV</a>
        {' · '}
        <a href={`/api/export?key=${encodeURIComponent(key)}&table=events`}>
          Download event log
        </a>
      </p>

      {/* Deliberately not a <table>: the spec bans the element anywhere in the
          app, and grid alignment costs one CSS rule. */}
      <ul className="ops">
        <li className="head">
          <span>State</span>
          <span>Participant</span>
          <span>Items done</span>
          <span>Seconds since write</span>
          <span>Block order / cohort</span>
        </li>
        {rows.map((r) => {
          const secs =
            r.seconds_since_write === null || r.seconds_since_write === undefined
              ? null
              : Number(r.seconds_since_write);
          /* STALLED is a word. Never colour alone (invariant A7). State comes
             first on the line so a stall is the first thing the eye lands on. */
          const state = r.completed
            ? 'COMPLETED'
            : secs === null
              ? 'NOT STARTED'
              : secs > 300
                ? 'STALLED'
                : 'ACTIVE';
          return (
            <li key={r.participant_id}>
              <span>{state}</span>
              <span>{r.participant_id}</span>
              <span>{r.items_done}</span>
              <span>{secs === null ? '—' : Math.round(secs)}</span>
              <span>
                {r.block_order} / {r.cohort}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="meta">
        {rows.length} sessions. STALLED means no write for over 5 minutes — check
        wifi and the screen lock. Queued data flushes on reconnect; do not reload
        the participant&apos;s page.
      </p>
    </main>
  );
}
