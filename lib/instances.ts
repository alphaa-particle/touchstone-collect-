/* Instances are imported at BUILD time (invariant D5). Never fetched at
   runtime, never read from the database. An item therefore still renders with
   the wifi down, and item rendering generates zero read traffic. */
import raw from '../data/instances.json';
import type { Bundle, Instance } from './types';

const bundle = raw as unknown as Bundle;

/* Hard-fail the build (invariant D6). A non-unique instance records a correct
   human as wrong, silently, and quietly corrupts every downstream table. This
   runs at module load, so `next build` cannot produce an artefact without it. */
const bad = [bundle.practice, ...bundle.instances].filter(
  (i) => i.uniqueness_verified !== 1,
);
if (bad.length) {
  throw new Error(
    `Unverified instances: ${bad.map((i) => i.instance_id).join(', ')}`,
  );
}
if (bundle.canonical_set.length !== 6) throw new Error('canonical_set must be 6');

export const PRACTICE: Instance = bundle.practice;

/** The canonical six, band 2, fixed order, identical for every participant so
 *  that instance difficulty is never confounded with participant. */
export const CANONICAL: Instance[] = bundle.canonical_set.map((id) => {
  const found = bundle.instances.find((i) => i.instance_id === id);
  if (!found) throw new Error(`canonical_set references missing instance ${id}`);
  return found;
});

/* Build hash recorded on every session row, so a dataset can always be tied
   back to the exact item set that produced it. FNV-1a: no crypto import, so
   the identical value is computed on the server and in the client bundle. */
function fnv1a(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

export const BUNDLE_HASH = `${bundle.family}@${bundle.generator_version}#${fnv1a(
  JSON.stringify(bundle),
)}`;

export const ITEMS_PER_PARTICIPANT = 6;
export const MAX_ATTEMPTS = 3;
/** PRE-REGISTERED before any data existed. Never tune this afterwards. */
export const TAB_AWAY_THRESHOLD_MS = 20000;
export const BASELINE_INSTANCE_ID = 'RECAPTCHA_V2';
