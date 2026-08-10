/* ===========================================================================
   LOCAL TEST DATABASE  —  test infrastructure, never deployed.

   Applies schema.sql verbatim to PGlite (Postgres compiled to WASM, no daemon)
   and puts a PostgREST-compatible HTTP surface in front of it, so the app runs
   against real Postgres: real unique constraints, real check constraints, real
   views in their real column order.

   That matters. A hand-written fake would happily accept two rows with the same
   idem_key and the idempotency gate would pass while being wrong.

   Supports exactly the PostgREST subset this app uses: select with eq/like/is
   filters, order, limit, exact counts, insert with ON CONFLICT DO NOTHING,
   update, delete. Embedded resources (`select=a(b)`) are rejected loudly rather
   than half-implemented.

     node test/pgrest.mjs [port]
   =========================================================================== */
import { PGlite } from '@electric-sql/pglite';
import { readFileSync } from 'node:fs';
import http from 'node:http';

const ident = (s) => `"${String(s).replace(/"/g, '')}"`;
const json = (v) => JSON.stringify(v, (_, x) => (typeof x === 'bigint' ? x.toString() : x));

const OPS = {
  eq: '=', neq: '<>', gt: '>', gte: '>=', lt: '<', lte: '<=',
  like: 'like', ilike: 'ilike',
};

function parseQuery(url) {
  const out = { select: '*', order: null, limit: null, onConflict: null, filters: [] };
  for (const [k, v] of url.searchParams) {
    if (k === 'select') out.select = v;
    else if (k === 'order') out.order = v;
    else if (k === 'limit') out.limit = v;
    else if (k === 'on_conflict') out.onConflict = v;
    else if (k === 'columns') continue;
    else out.filters.push([k, v]);
  }
  return out;
}

function whereClause(filters, params) {
  const parts = [];
  for (const [col, raw] of filters) {
    const dot = raw.indexOf('.');
    const op = dot < 0 ? 'eq' : raw.slice(0, dot);
    const val = dot < 0 ? raw : raw.slice(dot + 1);
    const c = ident(col);
    if (op === 'is') {
      parts.push(`${c} is ${val === 'null' ? 'null' : val === 'true' ? 'true' : 'false'}`);
    } else if (op === 'in') {
      const items = val.replace(/^\(|\)$/g, '').split(',').map((s) => s.replace(/^"|"$/g, ''));
      parts.push(`${c} in (${items.map((v) => `$${params.push(v)}`).join(',')})`);
    } else if (OPS[op]) {
      parts.push(`${c} ${OPS[op]} $${params.push(val.replace(/\*/g, '%'))}`);
    } else {
      throw Object.assign(new Error(`unsupported operator "${op}"`), { status: 400 });
    }
  }
  return parts.length ? ` where ${parts.join(' and ')}` : '';
}

function selectClause(select) {
  if (select === '*' || !select) return '*';
  if (select.includes('(')) {
    throw Object.assign(new Error('embedded resources are not supported by this test shim'), {
      status: 400,
    });
  }
  return select.split(',').map((c) => ident(c.trim())).join(', ');
}

function orderClause(order) {
  if (!order) return '';
  const cols = order.split(',').map((part) => {
    const [col, ...mods] = part.split('.');
    const dir = mods.includes('desc') ? 'desc' : 'asc';
    const nulls = mods.includes('nullsfirst') ? ' nulls first' : mods.includes('nullslast') ? ' nulls last' : '';
    return `${ident(col)} ${dir}${nulls}`;
  });
  return ` order by ${cols.join(', ')}`;
}

export async function startPgrest({ port = 54321, schemaPath = 'schema.sql' } = {}) {
  const db = new PGlite();

  /* schema.sql is applied VERBATIM apart from this one line: PGlite does not
     ship the pgcrypto extension. Nothing in the schema needs it —
     gen_random_uuid() has been core Postgres since 13 — so removing it changes
     no behaviour under test. Supabase has pgcrypto and gets the file unedited. */
  const raw = readFileSync(schemaPath, 'utf8');
  const sql = raw.replace(
    /create extension if not exists "pgcrypto";/i,
    '-- [local test] pgcrypto not bundled with PGlite; gen_random_uuid() is core in PG13+',
  );
  if (sql === raw) console.error('[pgrest] warning: pgcrypto line not found in schema.sql');
  await db.exec(sql);

  const server = http.createServer(async (req, res) => {
    const send = (status, body, headers = {}) => {
      res.writeHead(status, { 'content-type': 'application/json', ...headers });
      res.end(req.method === 'HEAD' ? undefined : body === undefined ? '' : body);
    };

    try {
      const url = new URL(req.url, `http://localhost:${port}`);
      if (!url.pathname.startsWith('/rest/v1/')) return send(404, json({ message: 'not found' }));

      const rel = ident(url.pathname.slice('/rest/v1/'.length));
      const q = parseQuery(url);
      const prefer = String(req.headers.prefer || '');
      const wantCount = /count=exact/.test(prefer);
      const wantRows = /return=representation/.test(prefer);

      let raw = '';
      if (req.method === 'POST' || req.method === 'PATCH') {
        for await (const chunk of req) raw += chunk;
      }

      if (req.method === 'GET' || req.method === 'HEAD') {
        const params = [];
        const where = whereClause(q.filters, params);
        const sqlText =
          `select ${selectClause(q.select)} from ${rel}${where}${orderClause(q.order)}` +
          (q.limit ? ` limit ${parseInt(q.limit, 10)}` : '');
        const r = await db.query(sqlText, params);
        const headers = {};
        if (wantCount) {
          const c = await db.query(`select count(*)::int as n from ${rel}${where}`, params);
          const n = c.rows[0].n;
          headers['content-range'] = `0-${Math.max(0, n - 1)}/${n}`;
        }
        return send(200, json(r.rows), headers);
      }

      if (req.method === 'POST') {
        const body = JSON.parse(raw || '[]');
        const rows = Array.isArray(body) ? body : [body];
        const ignoreDup = /resolution=ignore-duplicates/.test(prefer);
        const returned = [];
        for (const row of rows) {
          const cols = Object.keys(row);
          if (!cols.length) continue;
          const params = cols.map((c) => row[c]);
          let conflict = '';
          if (q.onConflict) {
            const target = q.onConflict.split(',').map(ident).join(', ');
            if (ignoreDup) conflict = ` on conflict (${target}) do nothing`;
            else {
              const sets = cols
                .filter((c) => !q.onConflict.split(',').includes(c))
                .map((c) => `${ident(c)} = excluded.${ident(c)}`);
              conflict = sets.length
                ? ` on conflict (${target}) do update set ${sets.join(', ')}`
                : ` on conflict (${target}) do nothing`;
            }
          }
          const r = await db.query(
            `insert into ${rel} (${cols.map(ident).join(', ')}) ` +
              `values (${cols.map((_, i) => `$${i + 1}`).join(', ')})${conflict} returning *`,
            params,
          );
          returned.push(...r.rows);
        }
        return send(wantRows ? 201 : 201, wantRows ? json(returned) : json([]));
      }

      if (req.method === 'PATCH') {
        const patch = JSON.parse(raw || '{}');
        const cols = Object.keys(patch);
        if (!cols.length) return send(400, json({ message: 'empty patch' }));
        const params = cols.map((c) => patch[c]);
        const sets = cols.map((c, i) => `${ident(c)} = $${i + 1}`).join(', ');
        const where = whereClause(q.filters, params);
        const r = await db.query(`update ${rel} set ${sets}${where} returning *`, params);
        return send(wantRows ? 200 : 204, wantRows ? json(r.rows) : undefined);
      }

      if (req.method === 'DELETE') {
        const params = [];
        const where = whereClause(q.filters, params);
        const r = await db.query(`delete from ${rel}${where} returning *`, params);
        return send(wantRows ? 200 : 204, wantRows ? json(r.rows) : undefined);
      }

      return send(405, json({ message: 'method not allowed' }));
    } catch (e) {
      const status = e.status || (String(e.message).includes('duplicate key') ? 409 : 400);
      return send(status, json({ message: e.message, code: e.code ?? null }));
    }
  });

  await new Promise((r) => server.listen(port, '127.0.0.1', r));
  return {
    db,
    server,
    url: `http://127.0.0.1:${port}`,
    query: (sql, params) => db.query(sql, params),
    stop: () => new Promise((r) => server.close(r)),
  };
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())) {
  const port = Number(process.argv[2] || 54321);
  const { url } = await startPgrest({ port });
  console.log(`[pgrest] schema.sql applied to PGlite; listening on ${url}`);
}
