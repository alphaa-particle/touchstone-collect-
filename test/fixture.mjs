/* ===========================================================================
   BROWSER TEST FIXTURE   —   node test/fixture.mjs

   Test infrastructure, never deployed. Brings up everything needed to drive the
   real app in a real browser and assert against the real database:

     :3200  the app (next start, production build)
     :54331 the local Postgres (schema.sql in PGlite, PostgREST-shaped)
     :3301  helper — /axe.js serves axe-core, /q?sql=... runs read-only SQL

   Prints the seeded tokens, then stays up until killed.
   =========================================================================== */
import { startPgrest } from './pgrest.mjs';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import http from 'node:http';

const APP = 3200;
/* Must match NEXT_PUBLIC_SUPABASE_URL in .env.local: Next inlines every
   NEXT_PUBLIC_ variable at BUILD time, including in server code, so pointing a
   prebuilt bundle at a different port silently fails. Same trap in production —
   change that variable and you must redeploy, not just restart. */
const DB = 54321;
const HELPER = 3301;

const ENV = {
  ...process.env,
  NEXT_PUBLIC_SUPABASE_URL: `http://127.0.0.1:${DB}`,
  SUPABASE_SERVICE_ROLE_KEY: 'fixture-service-role-key',
  OPS_KEY: 'fixture-ops-key',
  NEXT_PUBLIC_RECAPTCHA_SITE_KEY: '',
  RECAPTCHA_SECRET_KEY: '',
  APP_URL: `http://127.0.0.1:${APP}`,
};

const pg = await startPgrest({ port: DB });

const axe = readFileSync('node_modules/axe-core/axe.min.js', 'utf8');
http
  .createServer(async (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${HELPER}`);
    res.setHeader('access-control-allow-origin', '*');
    if (url.pathname === '/axe.js') {
      res.writeHead(200, { 'content-type': 'application/javascript' });
      return res.end(axe);
    }
    if (url.pathname === '/q') {
      const sql = url.searchParams.get('sql') || '';
      if (!/^\s*select/i.test(sql)) {
        res.writeHead(400, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ error: 'select only' }));
      }
      try {
        const r = await pg.query(sql);
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(
          JSON.stringify(r.rows, (_, v) => (typeof v === 'bigint' ? v.toString() : v)),
        );
      } catch (e) {
        res.writeHead(400, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ error: e.message }));
      }
    }
    res.writeHead(404);
    res.end();
  })
  .listen(HELPER, '127.0.0.1');

const srv = spawn('npx', ['next', 'start', '-p', String(APP)], { env: ENV, stdio: 'inherit' });

const wait = async () => {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${APP}/api/health`)).ok) return true;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
};
if (!(await wait())) throw new Error('app did not start');

const seed = spawn('npx', ['tsx', 'scripts/seed_participants.ts'], { env: ENV });
let out = '';
seed.stdout.on('data', (d) => (out += d));
await new Promise((r) => seed.on('close', r));

const rows = (await pg.query(`select participant_id, token, block_order from sessions
  where participant_id in ('P01','P02','P03') order by participant_id`)).rows;

console.log('\n=========== FIXTURE READY ===========');
console.log(`app     http://127.0.0.1:${APP}`);
console.log(`ops     http://127.0.0.1:${APP}/ops?key=fixture-ops-key`);
console.log(`helper  http://127.0.0.1:${HELPER}/q?sql=select+...`);
for (const r of rows) {
  console.log(`${r.participant_id} ${r.block_order}  http://127.0.0.1:${APP}/run/${r.token}`);
}
console.log('=====================================\n');

process.on('SIGTERM', () => {
  srv.kill('SIGTERM');
  process.exit(0);
});
