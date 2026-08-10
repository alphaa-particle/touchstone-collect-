import 'server-only';
import { createClient } from '@supabase/supabase-js';

/* One service-role client, server-side only. PostgREST over HTTP: no direct
   Postgres connection, no ORM, no connection pool to exhaust on a serverless
   platform. RLS is enabled with no policies, so the anon key reaches nothing
   and every read and write in this app goes through here. */

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) {
  throw new Error(
    'NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set',
  );
}

export const sb = createClient(url, key, {
  auth: { persistSession: false, autoRefreshToken: false },
});
