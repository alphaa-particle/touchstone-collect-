/* Seeds P01..P24 and one session each, then prints the paper strips.
 *
 *   npx tsx scripts/seed_participants.ts > tokens.txt
 *
 * tokens.txt is the only place a token could ever be linked to a person.
 * Print it, keep it on paper, shred it before leaving the building, delete the
 * file. Re-running is safe: participants and sessions that already exist are
 * left alone and their existing token is reprinted, so a strip you have already
 * printed never goes stale.
 */
import { existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';
import { BUNDLE_HASH } from '../lib/instances';

const N = 24;

/* createClient builds a realtime client and refuses to start on Node 20, which
   has no global WebSocket. These scripts speak REST only and never open a
   socket, so a stub that throws if anyone ever tries is the honest fix. Next.js
   provides a real WebSocket, so the app itself is unaffected. */
(globalThis as { WebSocket?: unknown }).WebSocket ??= class {
  constructor() {
    throw new Error('realtime is not used by this script');
  }
};

async function main() {
  for (const f of ['.env.local', '.env']) {
    if (existsSync(f)) process.loadEnvFile(f);
  }

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  const base = (process.env.APP_URL || 'http://localhost:3000').replace(/\/$/, '');
  if (!url || !key) {
    throw new Error('NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required');
  }

  const sb = createClient(url, key, { auth: { persistSession: false } });
  const today = new Date().toISOString().slice(0, 10);
  const ids = Array.from({ length: N }, (_, i) => `P${String(i + 1).padStart(2, '0')}`);

  /* age_band is deliberately left null: the app never asks a participant for
     demographics, so it is filled in from the paper screening after the
     session. See README, "After the session". */
  const { error: pErr } = await sb.from('participants').upsert(
    ids.map((participant_id) => ({
      participant_id,
      cohort: 'screen_reader_school',
      site: 'school_01',
      consent_recorded: true,
      consent_date: today,
      is_adult: true,
      has_lawful_guardian: false,
    })),
    { onConflict: 'participant_id', ignoreDuplicates: true },
  );
  if (pErr) throw new Error(`participants: ${pErr.message}`);

  const { data: existing, error: eErr } = await sb
    .from('sessions')
    .select('participant_id,token,block_order');
  if (eErr) throw new Error(`sessions read: ${eErr.message}`);
  const have = new Map((existing ?? []).map((s) => [s.participant_id, s]));

  const fresh = ids
    .map((participant_id, i) => ({
      participant_id,
      token: randomUUID().replace(/-/g, ''), // 32 hex chars, unguessable
      /* Counterbalancing is assigned here, before the session, never randomised
         at runtime: you must be able to state the assignment in advance. */
      block_order: i % 2 === 0 ? 'prototype_first' : 'baseline_first',
      baseline_source: 'recaptcha_v2',
      language: 'en',
      instance_bundle: BUNDLE_HASH,
    }))
    .filter((s) => !have.has(s.participant_id));

  if (fresh.length) {
    const { error } = await sb.from('sessions').insert(fresh);
    if (error) throw new Error(`sessions insert: ${error.message}`);
    for (const s of fresh) have.set(s.participant_id, s);
  }

  console.log(`# Touchstone token strips — ${today}`);
  console.log(`# bundle ${BUNDLE_HASH}`);
  console.log(`# ${fresh.length} created, ${N - fresh.length} already existed`);
  console.log('');
  for (const id of ids) {
    const s = have.get(id)!;
    console.log(`${id}\t${s.block_order}\t${base}/run/${s.token}`);
  }

  const counts = ids.reduce<Record<string, number>>((acc, id) => {
    const b = have.get(id)!.block_order;
    acc[b] = (acc[b] ?? 0) + 1;
    return acc;
  }, {});
  console.log('');
  console.log(`# block_order: ${JSON.stringify(counts)}`);
  console.log(`# distinct tokens: ${new Set(ids.map((id) => have.get(id)!.token)).size}`);
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
