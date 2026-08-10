/* 20 concurrent simulated sessions, 10 trials each, randomised think time.
 *
 *   npx tsx scripts/loadtest.ts            # refuses if real trials exist
 *   npx tsx scripts/loadtest.ts --force
 *
 * Its rows are namespaced with an LT: idem_key prefix and deleted afterwards,
 * so a run leaves the table exactly as it found it.
 */
import { existsSync } from 'node:fs';
import { createClient } from '@supabase/supabase-js';

const SESSIONS = 20;
const TRIALS = 10;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/* See the note in seed_participants.ts: REST only, no realtime socket. */
(globalThis as { WebSocket?: unknown }).WebSocket ??= class {
  constructor() {
    throw new Error('realtime is not used by this script');
  }
};

async function main() {
  for (const f of ['.env.local', '.env']) {
    if (existsSync(f)) process.loadEnvFile(f);
  }

  const base = (process.env.APP_URL || 'http://localhost:3000').replace(/\/$/, '');
  const sb = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false } },
  );

  const { count: preexisting } = await sb
    .from('trials')
    .select('*', { count: 'exact', head: true });
  if (preexisting && !process.argv.includes('--force')) {
    console.error(
      `refusing to run: ${preexisting} trial rows already exist.\n` +
        'The load test writes item_index 1..10 against real sessions, which would\n' +
        'collide with collected data. Run it on a scratch project, or --force.',
    );
    process.exit(1);
  }

  const { data: sessions, error } = await sb
    .from('sessions')
    .select('session_id,token')
    .order('participant_id')
    .limit(SESSIONS);
  if (error) throw new Error(error.message);
  if (!sessions || sessions.length < SESSIONS) {
    throw new Error(`need ${SESSIONS} sessions, found ${sessions?.length ?? 0}. Seed first.`);
  }

  let http5xx = 0;
  let posted = 0;

  const simulate = async (s: { session_id: string; token: string }) => {
    const r0 = await fetch(`${base}/api/session/start`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ token: s.token, perf_ms: 0, viewport_w: 1280, viewport_h: 800 }),
    });
    if (r0.status >= 500) http5xx++;
    const { server_epoch_ms } = (await r0.json()) as { server_epoch_ms: number };

    let perf = 1000;
    for (let k = 1; k <= TRIALS; k++) {
      await sleep(500 + Math.random() * 2500); // think time
      const item_start_perf = perf;
      const first = perf + 4000;
      const submit = perf + 12000;
      perf = submit + 1000;

      const r = await fetch(`${base}/api/trial`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          session_id: s.session_id,
          item_index: k,
          order_position: k,
          condition: 'touchstone_grid',
          instance_id: 'I0009',
          is_practice: 0,
          anchor: { server_epoch_ms, perf_ms: 0 },
          marks: {
            item_start_perf,
            first_focus_perf: first,
            first_keydown_perf: null,
            first_pointer_perf: null,
            submit_perf: submit,
          },
          correct: 1,
          attempts: 1,
          gave_up: 0,
          tab_away_events: 0,
          tab_away_max_ms: 0,
          notes: null,
          idem_key: `LT:${s.session_id}:${k}:1`,
        }),
      });
      if (r.status >= 500) http5xx++;
      if (r.ok) posted++;
    }
  };

  const t0 = Date.now();
  await Promise.all(sessions.map(simulate));
  const secs = ((Date.now() - t0) / 1000).toFixed(1);

  const { data: rows } = await sb.from('trials').select('idem_key,session_id,item_index');
  const mine = (rows ?? []).filter((r) => String(r.idem_key).startsWith('LT:'));
  const pairs = new Set(mine.map((r) => `${r.session_id}:${r.item_index}`));

  const expected = SESSIONS * TRIALS;
  console.log(`elapsed          ${secs}s`);
  console.log(`accepted POSTs   ${posted}/${expected}`);
  console.log(`rows written     ${mine.length}  (expected ${expected})`);
  console.log(`distinct items   ${pairs.size}  (duplicates ${mine.length - pairs.size})`);
  console.log(`5xx responses    ${http5xx}`);

  const { error: delErr } = await sb.from('trials').delete().like('idem_key', 'LT:%');
  console.log(`cleanup          ${delErr ? `FAILED ${delErr.message}` : 'load-test rows deleted'}`);

  const ok = mine.length === expected && pairs.size === expected && http5xx === 0;
  console.log(ok ? 'LOADTEST PASS' : 'LOADTEST FAIL');
  process.exit(ok ? 0 : 1);
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
