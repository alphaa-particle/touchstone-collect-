'use client';

/* Offline-first write queue.

   Every payload is written to localStorage BEFORE the network is touched, so a
   dropped school wifi link, a locked screen or a force-quit cannot lose a
   trial. Nothing in the interface ever awaits a network call.

   Strictly FIFO, one request in flight at a time. Order is load-bearing: the
   difficulty rating arrives as an event that updates trials already inserted,
   so it must not overtake the trial rows it refers to.

   Retries are free because every write is idempotent on idem_key (invariant
   D4), which also makes the pagehide sendBeacon safe to duplicate. */

type Job = { u: string; b: unknown };

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
const registry = new Map<string, Queue>();

export type Queue = {
  push: (url: string, body: unknown) => void;
  pump: () => void;
  pending: () => number;
};

export function getQueue(sessionKey: string): Queue {
  const existing = registry.get(sessionKey);
  if (existing) return existing;

  const KEY = `touchstone_q_${sessionKey}`;
  const DEAD = `touchstone_dead_${sessionKey}`;

  let jobs: Job[] = [];
  try {
    jobs = JSON.parse(localStorage.getItem(KEY) || '[]') as Job[];
  } catch {
    jobs = [];
  }

  let inFlight = false;
  let tries = 0;

  const save = () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(jobs));
    } catch {
      /* storage blocked or full: the in-memory queue still drains */
    }
  };

  /* A 4xx will never succeed on retry, so it must not block every later row
     behind it. Park it where it is still recoverable from the device rather
     than discarding it. */
  const park = (job: Job) => {
    try {
      const dead = JSON.parse(localStorage.getItem(DEAD) || '[]') as Job[];
      dead.push(job);
      localStorage.setItem(DEAD, JSON.stringify(dead));
    } catch {
      /* nothing more we can do here */
    }
  };

  async function pump(): Promise<void> {
    if (inFlight || !jobs.length || typeof navigator === 'undefined') return;
    inFlight = true;
    const job = jobs[0];
    let done = false;
    try {
      const r = await fetch(job.u, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(job.b),
        keepalive: true,
      });
      if (r.ok) {
        done = true;
      } else if (r.status >= 400 && r.status < 500 && r.status !== 408 && r.status !== 429) {
        park(job);
        done = true;
      } else {
        throw new Error(`http ${r.status}`);
      }
    } catch {
      inFlight = false;
      const wait = BACKOFF_MS[Math.min(tries++, BACKOFF_MS.length - 1)];
      setTimeout(() => void pump(), wait);
      return;
    }
    if (done) {
      jobs.shift();
      save();
      tries = 0;
    }
    inFlight = false;
    if (jobs.length) void pump();
  }

  /* Last-chance flush on pagehide. localStorage is intentionally NOT cleared:
     delivery cannot be confirmed, and a duplicate costs nothing. */
  const flushBeacon = () => {
    if (!navigator.sendBeacon) return;
    for (const j of jobs) {
      try {
        navigator.sendBeacon(
          j.u,
          new Blob([JSON.stringify(j.b)], { type: 'application/json' }),
        );
      } catch {
        /* ignore */
      }
    }
  };

  window.addEventListener('online', () => void pump());
  window.addEventListener('pagehide', flushBeacon);

  const q: Queue = {
    push(u, b) {
      jobs.push({ u, b });
      save();
      void pump();
    },
    pump() {
      void pump();
    },
    pending: () => jobs.length,
  };

  registry.set(sessionKey, q);
  void pump(); // drain anything left over from a previous page load
  return q;
}
