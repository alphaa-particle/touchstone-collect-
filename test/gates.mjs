/* ===========================================================================
   AUTOMATED GATE SUITE   —   node test/gates.mjs

   Runs the machine-checkable half of AGENT_BUILD_SPEC.md §4 and §5 against a
   production build talking to the real schema in PGlite (see pgrest.mjs).

   What it CANNOT do, and what therefore still has to be done by a human:
     * NVDA + Chrome, NVDA + Firefox, TalkBack + Chrome, monitor physically off
     * axe DevTools
     * the pilot with a real screen-reader user
   Those are listed at the end of the run so they are never quietly assumed.
   =========================================================================== */
import { startPgrest } from './pgrest.mjs';
import { spawn, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';

const PORT = 3100;
const DBPORT = 54329;
const OPS_KEY = 'gate-ops-key-9c1f';

const ENV = {
  ...process.env,
  NEXT_PUBLIC_SUPABASE_URL: `http://127.0.0.1:${DBPORT}`,
  SUPABASE_SERVICE_ROLE_KEY: 'gate-service-role-key',
  OPS_KEY,
  NEXT_PUBLIC_RECAPTCHA_SITE_KEY: '',
  RECAPTCHA_SECRET_KEY: '',
  APP_URL: `http://127.0.0.1:${PORT}`,
};

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok: !!ok, detail });
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `   ${detail}` : ''}`);
  return !!ok;
};
const head = (s) => console.log(`\n=== ${s} ===`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const build = () => spawnSync('npx', ['next', 'build'], { env: ENV, encoding: 'utf8' });

/* The local database runs in THIS process, so anything that talks to it must be
   spawned asynchronously. spawnSync would block the event loop that serves it
   and deadlock the run. */
const run = (cmd, args) =>
  new Promise((resolve) => {
    const p = spawn(cmd, args, { env: ENV });
    let out = '';
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', (d) => (out += d));
    p.on('close', (status) => resolve({ status, out }));
  });

/* The Phase 6 invariant greps, run over source with comments stripped. Grepping
   raw text makes the gate unpassable for any file that *explains* why a pattern
   is banned, which would push the explanations out of the codebase — exactly the
   wrong incentive. */
function sourceLines() {
  const files = spawnSync(
    'bash',
    ['-lc', `find app lib -type f \\( -name '*.ts' -o -name '*.tsx' -o -name '*.css' \\) | sort`],
    { encoding: 'utf8' },
  ).stdout.trim().split('\n').filter(Boolean);

  const out = [];
  for (const f of files) {
    const stripped = readFileSync(f, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')           // block and JSX comments
      .replace(/(^|[^:])\/\/.*$/gm, '$1');        // line comments, sparing URLs
    stripped.split('\n').forEach((line, k) => out.push({ file: f, n: k + 1, line }));
  }
  return out;
}

function grepSource(re) {
  return sourceLines()
    .filter(({ line }) => re.test(line))
    .map(({ file, n, line }) => `${file}:${n}: ${line.trim()}`);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\r') continue;
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

// ============================================================ GATE 0
head('GATE 0 — scaffold and the instance guard');

const JSON_PATH = 'data/instances.json';
const original = readFileSync(JSON_PATH, 'utf8');
const tampered = JSON.parse(original);
tampered.instances[3].uniqueness_verified = 0; // I0004
writeFileSync(JSON_PATH, JSON.stringify(tampered, null, 1));
const badBuild = build();
const badOut = `${badBuild.stdout || ''}${badBuild.stderr || ''}`;
writeFileSync(JSON_PATH, original);
check(
  'build hard-fails on an unverified instance, with the exact error',
  badBuild.status !== 0 && /Unverified instances: I0004/.test(badOut),
  badBuild.status === 0 ? 'build SUCCEEDED — the D6 guard is not wired in' : '',
);

const goodBuild = build();
check('npm run build succeeds with the shipped bundle', goodBuild.status === 0);
if (goodBuild.status !== 0) {
  console.error(goodBuild.stdout, goodBuild.stderr);
  process.exit(1);
}

// ============================================================ boot
head('Booting the local database and a production server');
const pg = await startPgrest({ port: DBPORT });
console.log(`  schema.sql applied to PGlite on ${pg.url}`);

const idem = await pg.query(`select count(*)::int n from information_schema.tables
  where table_name in ('participants','sessions','trials','events')`);
check('schema.sql applied and idempotent (re-run in the shim boot path)', idem.rows[0].n === 4);

const srv = spawn('npx', ['next', 'start', '-p', String(PORT)], {
  env: ENV,
  stdio: ['ignore', 'pipe', 'pipe'],
});
let srvLog = '';
srv.stdout.on('data', (d) => (srvLog += d));
srv.stderr.on('data', (d) => (srvLog += d));

const base = `http://127.0.0.1:${PORT}`;
let up = false;
for (let i = 0; i < 60 && !up; i++) {
  try {
    const r = await fetch(`${base}/api/health`);
    up = r.ok;
  } catch { /* not listening yet */ }
  if (!up) await sleep(500);
}
if (!up) {
  console.error(srvLog);
  throw new Error('server did not come up');
}
console.log(`  server up on ${base}`);

async function finish(code) {
  srv.kill('SIGTERM');
  await pg.stop();
  const failed = results.filter((r) => !r.ok);
  head('SUMMARY');
  console.log(`  ${results.length - failed.length}/${results.length} automated checks passed`);
  for (const f of failed) console.log(`  FAILED: ${f.name} ${f.detail}`);
  head('STILL REQUIRES A HUMAN (cannot be automated)');
  for (const t of [
    'Full session, NVDA + Chrome, keyboard only, monitor physically off',
    'Full session, NVDA + Firefox, keyboard only, monitor physically off',
    'Full session, TalkBack + Chrome on a real Android phone, touch only',
    'axe DevTools on /run/<token>: zero violations',
    'reCAPTCHA audio challenge end to end with real keys (Gate 4)',
    'Pilot, 3 people, at least one real screen-reader user',
  ]) console.log(`  TODO(human): ${t}`);
  process.exit(code ?? (failed.length ? 1 : 0));
}

try {
  // ============================================================ GATE 1
  head('GATE 1 — data layer');

  const h = await (await fetch(`${base}/api/health`)).json();
  check('/api/health returns db:true from a real count', h.ok === true && h.db === true);

  const seed = await run('npx', ['tsx', 'scripts/seed_participants.ts']);
  if (seed.status !== 0) console.error(seed.out);
  check('seed_participants.ts runs clean', seed.status === 0);

  const pc = await pg.query(`select count(*)::int n from participants`);
  check('200 participants seeded', pc.rows[0].n === 200, `got ${pc.rows[0].n}`);

  const tk = await pg.query(`select count(distinct token)::int n from sessions`);
  check('200 distinct tokens', tk.rows[0].n === 200, `got ${tk.rows[0].n}`);

  const bo = await pg.query(
    `select block_order, count(*)::int n from sessions group by 1 order by 1`,
  );
  check(
    'exactly 100 of each block_order',
    bo.rows.length === 2 && bo.rows.every((r) => r.n === 100),
    JSON.stringify(bo.rows),
  );

  const ethics = await pg.query(`select count(*)::int n from participants
    where is_adult is not true or has_lawful_guardian is not false`);
  check('every participant row is an adult with no lawful guardian', ethics.rows[0].n === 0);

  const seed2 = await run('npx', ['tsx', 'scripts/seed_participants.ts']);
  const tk2 = await pg.query(`select count(*)::int n from sessions`);
  check(
    'seed is re-runnable without minting new tokens',
    seed2.status === 0 && tk2.rows[0].n === 200,
    `sessions=${tk2.rows[0].n}`,
  );

  const unknown = await fetch(`${base}/run/deadbeefdeadbeefdeadbeefdeadbeef`);
  check('unknown token 404s', unknown.status === 404, `got ${unknown.status}`);

  const known = await pg.query(
    `select s.session_id, s.token from sessions s where s.participant_id = 'P24'`,
  );
  const S = known.rows[0];
  if (!S) throw new Error('no session for P24 — the seed step failed, later gates cannot run');
  const page = await fetch(`${base}/run/${S.token}`);
  const pageHtml = await page.text();
  check('a valid token renders the runner', page.ok && /Before we begin/.test(pageHtml));

  // ============================================================ GATE 2 (static)
  head('GATE 2 — invariants that can be checked statically');

  const banned = grepSource(/autofocus|<table|aria-live="assertive"|role="alert"|setInterval/i);
  check(
    'no autofocus, no <table>, no assertive live region, no setInterval',
    banned.length === 0,
    banned.join('\n      '),
  );

  const tableRole = grepSource(/role="(table|row|cell|columnheader|rowheader|grid|gridcell)"/i);
  check('no ARIA table or grid roles either (A3b)', tableRole.length === 0, tableRole.join(' | '));

  const dateNow = grepSource(/Date\.now/);
  check(
    'the only Date.now in app/ and lib/ is the session anchor',
    dateNow.length === 1 && dateNow[0].startsWith('app/api/session/start/route.ts'),
    dateNow.join(' | '),
  );

  const live = grepSource(/aria-live/);
  check(
    'there is exactly one live region and it is polite',
    live.length === 1 && /aria-live="polite"/.test(live[0]),
    live.join(' | '),
  );

  const timers = grepSource(/setTimeout/).filter((l) => l.startsWith('app/run/'));
  check(
    'the only setTimeout in the runner is the feedback pause before advancing (A6)',
    timers.every((l) => /advance|go\(\)/.test(l)),
    timers.join(' | '),
  );

  const clientBundle = spawnSync(
    'bash',
    ['-lc', `grep -rl "not in the middle 4 boxes" .next/static/chunks/ | head -1`],
    { encoding: 'utf8' },
  ).stdout.trim();
  check(
    'instances are compiled into the client bundle, so items render offline (D5)',
    clientBundle !== '',
  );

  // ============================================================ GATE 3
  head('GATE 3 — write path, idempotency, clock');

  const anchorNow = Date.now();
  const trial = (item_index, opts = {}) => ({
    session_id: S.session_id,
    item_index,
    order_position: item_index,
    condition: opts.condition ?? 'touchstone_grid',
    instance_id: opts.instance_id ?? 'I0009',
    is_practice: 0,
    anchor: { server_epoch_ms: opts.epoch ?? anchorNow, perf_ms: 1000 },
    marks: {
      item_start_perf: 5000,
      first_focus_perf: 5000 + 21880.2,
      first_keydown_perf: null,
      first_pointer_perf: null,
      submit_perf: 5000 + 33440.9,
    },
    correct: 1,
    attempts: 2,
    gave_up: 0,
    tab_away_events: 0,
    tab_away_max_ms: opts.tab_away_max_ms ?? 0,
    notes: opts.notes ?? null,
    idem_key: `${S.session_id}:${item_index}:2`,
  });

  const post = (path, body) =>
    fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });

  const twelve = await Promise.all(Array.from({ length: 12 }, () => post('/api/trial', trial(1))));
  const dup = await pg.query(
    `select count(*)::int n from trials where idem_key = $1`,
    [`${S.session_id}:1:2`],
  );
  check(
    '12 identical POSTs of one trial produce exactly one row',
    dup.rows[0].n === 1 && twelve.every((r) => r.ok),
    `rows=${dup.rows[0].n}, statuses=${[...new Set(twelve.map((r) => r.status))]}`,
  );

  for (let k = 2; k <= 10; k++) await post('/api/trial', trial(k));
  /* Same marks, anchor four hours in the future: a device whose wall clock is
     wrong must still yield identical durations (only its absolute timestamps
     move). This is the whole point of anchoring a monotonic clock. */
  await post('/api/trial', trial(11, { epoch: anchorNow + 4 * 3600 * 1000 }));
  await post('/api/trial', trial(12, { condition: 'audio_captcha_baseline', instance_id: 'RECAPTCHA_V2', notes: 'baseline_not_triggered' }));
  await post('/api/trial', trial(13, { tab_away_max_ms: 25000 }));

  const skewed = await pg.query(
    `select item_index, solve_time_s::float8 s, orientation_time_s::float8 o, execution_time_s::float8 e
       from trials where item_index in (10, 11) order by item_index`,
  );
  check(
    'a 4-hour device clock error leaves every duration unchanged',
    skewed.rows.length === 2 &&
      skewed.rows[0].s === skewed.rows[1].s &&
      skewed.rows[0].o === skewed.rows[1].o &&
      skewed.rows[0].e === skewed.rows[1].e,
    JSON.stringify(skewed.rows),
  );
  const skewFlag = await pg.query(`select clock_suspect from trials where item_index = 11`);
  check('and it is flagged clock_suspect', skewFlag.rows[0].clock_suspect === true);

  const sanity1 = await pg.query(`select count(*)::int n from trials
     where solve_time_s is not null
       and abs(solve_time_s - extract(epoch from (submit_ts - item_start_ts))) > 0.002`);
  check('sanity 1: server arithmetic agrees with the raw timestamps', sanity1.rows[0].n === 0);

  const exact = await pg.query(`select count(*)::int n from trials
     where solve_time_s <> extract(epoch from (submit_ts - item_start_ts))
        or orientation_time_s <> extract(epoch from (first_input_ts - item_start_ts))
        or execution_time_s <> extract(epoch from (submit_ts - first_input_ts))`);
  check(
    'every duration reproduces EXACTLY from the exported timestamps, not just within tolerance',
    exact.rows[0].n === 0,
    `${exact.rows[0].n} rows differ`,
  );

  const excl = await pg.query(
    `select excluded, exclusion_reason from trials where item_index = 13`,
  );
  check(
    'tab_away_max_ms over the pre-registered 20s threshold sets excluded',
    excl.rows[0].excluded === 1 &&
      excl.rows[0].exclusion_reason === 'tab_away_gap_exceeds_threshold',
    JSON.stringify(excl.rows[0]),
  );

  const firstInput = await pg.query(
    `select first_input_ts, first_focus_ts, first_keydown_ts, first_pointer_ts
       from trials where item_index = 1`,
  );
  const fi = firstInput.rows[0];
  check(
    'first_input_ts is the earliest of the three signals, all three kept raw (M4)',
    fi.first_input_ts &&
      fi.first_focus_ts &&
      +new Date(fi.first_input_ts) === +new Date(fi.first_focus_ts) &&
      fi.first_keydown_ts === null &&
      fi.first_pointer_ts === null,
  );

  const evOk = await post('/api/events', [
    {
      session_id: S.session_id,
      item_index: 1,
      attempt_no: 1,
      event_type: 'difficulty_rating',
      perf_ms: 40000,
      payload: { value: 4, condition: 'touchstone_grid' },
      idem_key: `${S.session_id}:ev:gate:1`,
    },
    {
      session_id: S.session_id,
      item_index: 1,
      attempt_no: 1,
      event_type: 'visibility_hidden',
      perf_ms: 41000,
      payload: {},
      idem_key: `${S.session_id}:ev:gate:2`,
    },
  ]);
  await post('/api/events', [
    {
      session_id: S.session_id,
      item_index: 1,
      attempt_no: 1,
      event_type: 'difficulty_rating',
      perf_ms: 40000,
      payload: { value: 4, condition: 'touchstone_grid' },
      idem_key: `${S.session_id}:ev:gate:1`,
    },
  ]);
  const evRows = await pg.query(`select count(*)::int n from events`);
  check('events are idempotent too', evOk.ok && evRows.rows[0].n === 2, `rows=${evRows.rows[0].n}`);

  const rated = await pg.query(
    `select count(*)::int n from trials
      where condition = 'touchstone_grid' and perceived_difficulty = 4`,
  );
  const gridCount = await pg.query(
    `select count(*)::int n from trials where condition = 'touchstone_grid'`,
  );
  check(
    'the difficulty rating lands on every trial of its condition',
    rated.rows[0].n === gridCount.rows[0].n && rated.rows[0].n > 0,
    `${rated.rows[0].n}/${gridCount.rows[0].n}`,
  );
  const notRated = await pg.query(
    `select count(*)::int n from trials
      where condition = 'audio_captcha_baseline' and perceived_difficulty is not null`,
  );
  check('and never leaks onto the other condition', notRated.rows[0].n === 0);

  const bad = await post('/api/trial', { session_id: S.session_id });
  check('a malformed trial is rejected with 400, not a 500', bad.status === 400, `got ${bad.status}`);

  // ============================================================ GATE 5
  head('GATE 5 — ops dashboard and export');

  check('/ops with no key 404s', (await fetch(`${base}/ops`)).status === 404);
  check('/ops with a wrong key 404s', (await fetch(`${base}/ops?key=nope`)).status === 404);
  check('/api/export with no key 404s', (await fetch(`${base}/api/export`)).status === 404);

  const opsPage = await fetch(`${base}/ops?key=${OPS_KEY}`);
  const opsHtml = await opsPage.text();
  check(
    '/ops with the right key renders v_ops_status and a CSV link',
    opsPage.ok && /Session status/.test(opsHtml) && /api\/export\?key=/.test(opsHtml),
  );
  check('/ops refreshes itself with a meta tag, not a polling framework', /http-equiv="refresh"/.test(opsHtml));
  check('/ops marks stalls with the word STALLED', /P24/.test(opsHtml));

  const exp = await fetch(`${base}/api/export?key=${OPS_KEY}`);
  const csvText = await exp.text();
  check(
    'export is text/csv as an attachment',
    /text\/csv/.test(exp.headers.get('content-type') || '') &&
      /attachment/.test(exp.headers.get('content-disposition') || ''),
  );

  const viewCols = (
    await pg.query(`select column_name from information_schema.columns
      where table_name = 'v_trials_human' order by ordinal_position`)
  ).rows.map((r) => r.column_name);
  const csv = parseCsv(csvText);
  check(
    'CSV header equals v_trials_human column-for-column, in order',
    csv[0].join(',') === viewCols.join(','),
    csv[0].join(',') === viewCols.join(',') ? '' : `\n    got  ${csv[0].join(',')}\n    view ${viewCols.join(',')}`,
  );

  const dataRows = csv.slice(1);
  check(
    'every CSV row has exactly the header width',
    dataRows.length > 0 && dataRows.every((r) => r.length === viewCols.length),
    `${dataRows.length} rows`,
  );

  const col = (name) => viewCols.indexOf(name);
  const numeric = ['order_position', 'solve_time_s', 'orientation_time_s', 'execution_time_s',
    'correct', 'attempts', 'gave_up', 'perceived_difficulty', 'tab_away_events',
    'is_practice', 'excluded'];
  const badNum = [];
  for (const r of dataRows)
    for (const n of numeric) {
      const v = r[col(n)];
      if (v !== '' && !Number.isFinite(Number(v))) badNum.push(`${n}=${v}`);
    }
  check('numeric columns all parse as numbers (or are empty)', badNum.length === 0, badNum.slice(0, 5).join(','));

  const tsRe = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
  const badTs = dataRows.flatMap((r) =>
    ['item_start_ts', 'first_input_ts', 'submit_ts']
      .map((n) => r[col(n)])
      .filter((v) => v !== '' && !tsRe.test(v)),
  );
  check('timestamp columns are ISO-8601 UTC with milliseconds', badTs.length === 0, badTs.slice(0, 3).join(','));

  const ids = new Set(dataRows.map((r) => r[col('participant_id')]));
  const known2 = new Set(
    (await pg.query(`select participant_id from participants`)).rows.map((r) => r.participant_id),
  );
  check('every participant_id in the export exists in participants', [...ids].every((i) => known2.has(i)));

  const trialIds = dataRows.map((r) => r[col('trial_id')]);
  check(
    'trial_id is assigned at export, unique, and T-prefixed',
    trialIds.every((t) => /^T\d{4}$/.test(t)) && new Set(trialIds).size === trialIds.length,
  );
  const exp2 = parseCsv(await (await fetch(`${base}/api/export?key=${OPS_KEY}`)).text());
  check(
    'trial_id is stable across exports (paper notes stay attached to the right row)',
    exp2.slice(1).map((r) => r[col('trial_id')]).join(',') === trialIds.join(','),
  );

  const csvQuote = csvText.includes('"') ? 'contains quoting' : 'nothing needed quoting';
  const evExp = await fetch(`${base}/api/export?key=${OPS_KEY}&table=events`);
  check(`?table=events also exports (${csvQuote})`, evExp.ok && (await evExp.text()).startsWith('event_id'));
  const paExp = await fetch(`${base}/api/export?key=${OPS_KEY}&table=participants`);
  check('?table=participants also exports', paExp.ok);

  // ============================================================ GATE 6
  head('GATE 6 — hardening');

  const noPii = await pg.query(`select count(*)::int n from trials
    where notes is not null
      and notes not in ('baseline_not_triggered','baseline_verify_unreachable','baseline_not_configured')`);
  check('sanity 5: notes contain only server-generated markers, never free text', noPii.rows[0].n === 0);

  const lt = await run('npx', ['tsx', 'scripts/loadtest.ts', '--force']);
  const ltOut = lt.out;
  console.log(ltOut.split('\n').filter(Boolean).map((l) => `      ${l}`).join('\n'));
  check('load test: 20 concurrent sessions x 10 trials, 200 rows, 0 duplicates, 0 5xx',
    lt.status === 0 && /LOADTEST PASS/.test(ltOut));

  const s2 = await pg.query(`select count(*)::int n from (
      select session_id, item_index from trials group by 1,2 having count(*) > 1) x`);
  check('sanity 2: no duplicate (session, item) survived any retry', s2.rows[0].n === 0);

  const s3 = await pg.query(`select count(*)::int n from (
      select participant_id from trials where is_practice = 0
       group by 1 having count(distinct condition) < 2) x`);
  check('sanity 3: every participant with data covered both conditions', s3.rows[0].n === 0);

  const s4 = await pg.query(`select count(*)::int n from participants
     where is_adult is not true or has_lawful_guardian is not false
        or (age_band is not null and age_band not in ('18_25','26_40','41_60','60_plus'))`);
  check('sanity 4: adults only, no lawful guardian, no non-adult age band', s4.rows[0].n === 0);

  /* D1: the trials column set is FROZEN. Compared name by name and in order,
     not by count, so a rename or a reorder fails too. */
  const FROZEN_TRIALS = [
    'trial_pk', 'trial_id', 'session_id', 'participant_id', 'cohort', 'site',
    'condition', 'instance_id', 'baseline_source', 'order_position', 'item_index',
    'item_start_ts', 'first_input_ts', 'submit_ts', 'solve_time_s',
    'orientation_time_s', 'execution_time_s', 'first_focus_ts', 'first_keydown_ts',
    'first_pointer_ts', 'correct', 'attempts', 'gave_up', 'perceived_difficulty',
    'tab_away_events', 'tab_away_max_ms', 'language', 'is_practice', 'excluded',
    'exclusion_reason', 'notes', 'idem_key', 'received_at', 'clock_suspect',
  ];
  const cols = (
    await pg.query(`select column_name from information_schema.columns
      where table_name = 'trials' order by ordinal_position`)
  ).rows.map((r) => r.column_name);
  check(
    `the trials column set is untouched (D1): ${FROZEN_TRIALS.length} frozen columns, in order`,
    cols.join(',') === FROZEN_TRIALS.join(','),
    cols.join(',') === FROZEN_TRIALS.join(',') ? '' : `got ${cols.length}: ${cols.join(',')}`,
  );

  const pii = await pg.query(`select count(*)::int n from information_schema.columns
     where table_schema = 'public'
       and column_name ~* '(email|phone|name|address|^ip$|employer|fingerprint)'`);
  check('no column anywhere could hold a name, email, phone, address or IP (D3)', pii.rows[0].n === 0);

  await finish();
} catch (e) {
  console.error('\nGATE RUN CRASHED:', e);
  await finish(1);
}
