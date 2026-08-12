'use client';

/* ===========================================================================
   THE SESSION STATE MACHINE
   Ported from runner-reference.html, which was validated with a screen reader
   before this build started. The structure below is not a style choice; each
   piece maps to a numbered invariant in AGENT_BUILD_SPEC.md §2.

     consent -> profile -> intro -> practice -> block A -> rating -> block B -> rating -> done

   Per item:  IDLE (heading + one Start button; challenge NOT in the DOM)
                -> ACTIVE (challenge rendered, focus moved to the item heading)
                -> DONE
   =========================================================================== */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BASELINE_INSTANCE_ID,
  CANONICAL,
  ITEMS_PER_PARTICIPANT,
  MAX_ATTEMPTS,
  PRACTICE,
} from '@/lib/instances';
import { now } from '@/lib/clock';
import { getQueue, type Queue } from '@/lib/queue';
import type {
  Anchor,
  Condition,
  EventPayload,
  Instance,
  SessionConfig,
  TrialPayload,
} from '@/lib/types';

type ItemSlot = {
  kind: 'item';
  condition: Condition;
  instance: Instance | null; // null for the baseline arm
  item_index: number;
  is_practice: 0 | 1;
  pos: number;
  of: number;
};
type Slot = ItemSlot | { kind: 'rating'; condition: Condition };

/* item_index is session-global (1..7, practice 0), not per-block. It is the
   uniqueness key for a session's trials -- sanity query 2 in schema.sql groups
   on (session_id, item_index) and must return zero rows -- and it is half of
   every idem_key. The label shown to the participant uses the position within
   its own block instead, so "Puzzle 3 of 6" is true under both block orders. */
function buildFlow(order: string): Slot[] {
  const grid: ItemSlot[] = CANONICAL.map((instance, k) => ({
    kind: 'item',
    condition: 'touchstone_grid',
    instance,
    item_index: 0,
    is_practice: 0,
    pos: k + 1,
    of: ITEMS_PER_PARTICIPANT,
  }));
  const baseline: ItemSlot[] = [
    {
      kind: 'item',
      condition: 'audio_captcha_baseline',
      instance: null,
      item_index: 0,
      is_practice: 0,
      pos: 1,
      of: 1,
    },
  ];
  const [first, second] = order === 'baseline_first' ? [baseline, grid] : [grid, baseline];

  const flow: Slot[] = [
    {
      kind: 'item',
      condition: 'touchstone_grid',
      instance: PRACTICE,
      item_index: 0,
      is_practice: 1,
      pos: 0,
      of: 0,
    },
    ...first,
    { kind: 'rating', condition: first[0].condition },
    ...second,
    { kind: 'rating', condition: second[0].condition },
  ];

  let n = 0;
  for (const s of flow) if (s.kind === 'item' && !s.is_practice) s.item_index = ++n;
  return flow;
}

type Live = {
  slot: ItemSlot;
  started: boolean;
  settled: boolean;
  attempts: number;
  tab_away_events: number;
  tab_away_max_ms: number;
  item_start_perf: number;
  first_focus_perf: number | null;
  first_keydown_perf: number | null;
  first_pointer_perf: number | null;
};

type Screen = 'consent' | 'profile' | 'intro' | 'flow' | 'done';

const PROFILE_FIELDS = [
  {
    name: 'blindness_onset',
    label: 'When did your blindness begin?',
    options: [
      ['congenital', 'Congenital — from birth'],
      ['early_onset', 'Early-onset — after birth but before age 18'],
      ['acquired', 'Acquired — at age 18 or later'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'age_at_vision_loss',
    label: 'Approximately how old were you when you became blind?',
    options: [
      ['from_birth', 'From birth'],
      ['age_1_5', '1 to 5'],
      ['age_6_12', '6 to 12'],
      ['age_13_17', '13 to 17'],
      ['age_18_25', '18 to 25'],
      ['age_26_40', '26 to 40'],
      ['age_41_60', '41 to 60'],
      ['age_61_plus', '61 or older'],
      ['not_sure', 'Not sure'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'primary_language',
    label: 'What is your primary language?',
    options: [
      ['english', 'English'],
      ['hindi', 'Hindi'],
      ['other', 'Another language'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'language_proficiency',
    label: 'How would you describe your proficiency in the language used in this study?',
    options: [
      ['basic', 'Basic'],
      ['intermediate', 'Intermediate'],
      ['advanced', 'Advanced'],
      ['fluent', 'Fluent'],
      ['native', 'Native or first-language proficiency'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'education_level',
    label: 'What is the highest level of education you have completed?',
    options: [
      ['below_secondary', 'Below secondary school'],
      ['secondary', 'Secondary school'],
      ['higher_secondary', 'Higher secondary school'],
      ['undergraduate', 'Undergraduate degree'],
      ['postgraduate', 'Postgraduate degree'],
      ['other', 'Other'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'captcha_familiarity',
    label: 'How familiar are you with CAPTCHA or “I am not a robot” checks?',
    options: [
      ['never', 'Never used one'],
      ['slightly', 'Slightly familiar'],
      ['moderately', 'Moderately familiar'],
      ['very', 'Very familiar'],
      ['extremely', 'Extremely familiar'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'screen_reader_frequency',
    label: 'How often do you use a screen reader?',
    options: [
      ['never', 'Never'],
      ['less_than_weekly', 'Less than once a week'],
      ['weekly', 'At least once a week'],
      ['most_days', 'Most days'],
      ['daily', 'Every day'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'computer_proficiency',
    label: 'How would you rate your computer or smartphone proficiency?',
    options: [
      ['1', '1 — Beginner'],
      ['2', '2 — Basic'],
      ['3', '3 — Intermediate'],
      ['4', '4 — Advanced'],
      ['5', '5 — Expert'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
  {
    name: 'primary_input_method',
    label: 'What is your primary input method?',
    options: [
      ['keyboard', 'Keyboard'],
      ['touch_gestures', 'Touch gestures'],
      ['braille_keyboard', 'Braille keyboard or display'],
      ['voice', 'Voice input'],
      ['other', 'Other'],
      ['prefer_not_to_say', 'Prefer not to say'],
    ],
  },
] as const;

const CONDITION_MEASURES = [
  {
    name: 'difficulty',
    label: 'Overall, how difficult did you find this task?',
    options: ['Very easy', 'Easy', 'Neither easy nor hard', 'Hard', 'Very hard'],
  },
  {
    name: 'mental_effort',
    label: 'How much mental effort did this task require?',
    options: ['Very low', 'Low', 'Moderate', 'High', 'Very high'],
  },
  {
    name: 'frustration',
    label: 'How frustrated did you feel during this task?',
    options: ['Not at all', 'Slightly', 'Moderately', 'Very', 'Extremely'],
  },
  {
    name: 'perceived_accessibility',
    label: 'How accessible was this task with your assistive technology?',
    options: [
      'Not accessible at all',
      'Slightly accessible',
      'Moderately accessible',
      'Very accessible',
      'Completely accessible',
    ],
  },
  {
    name: 'ease_of_navigation',
    label: 'How easy was it to navigate and enter your answer?',
    options: ['Very difficult', 'Difficult', 'Neither difficult nor easy', 'Easy', 'Very easy'],
  },
] as const;

const SITE_KEY = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY ?? '';

export default function Runner({
  token,
  config,
}: {
  token: string;
  config: SessionConfig;
}) {
  const flow = useMemo(() => buildFlow(config.block_order), [config.block_order]);

  const [screen, setScreen] = useState<Screen>('consent');
  const [i, setI] = useState(0);
  const [phase, setPhase] = useState<'idle' | 'active'>('idle');
  const [status, setStatus] = useState('');
  const [connected, setConnected] = useState(false);
  const [wrongAnswer, setWrongAnswer] = useState('');

  const anchorRef = useRef<Anchor | null>(null);
  const liveRef = useRef<Live | null>(null);
  const hiddenAt = useRef<number | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const cluesRef = useRef<HTMLHeadingElement | null>(null);
  const wrongDialogRef = useRef<HTMLDialogElement | null>(null);
  const wrongHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const wrongReturnFocusRef = useRef<HTMLElement | null>(null);
  const advanceAfterWrongRef = useRef(false);
  const queueRef = useRef<Queue | null>(null);
  const evBuf = useRef<EventPayload[]>([]);
  const evSeq = useRef(0);
  /* Per page load, so event idem_keys stay unique across a resume without
     having to persist a counter. */
  const loadId = useRef(Math.random().toString(36).slice(2, 10));

  const PROGRESS = `touchstone_progress_${token}`;
  const queue = () => (queueRef.current ??= getQueue(config.session_id));

  // ---------------------------------------------------------------- events
  const logEvent = (event_type: string, payload: Record<string, unknown> = {}) => {
    const live = liveRef.current;
    evBuf.current.push({
      session_id: config.session_id,
      item_index: live ? live.slot.item_index : null,
      attempt_no: live ? live.attempts : null,
      event_type,
      perf_ms: now(),
      payload,
      idem_key: `${config.session_id}:ev:${loadId.current}:${++evSeq.current}`,
    });
    if (evBuf.current.length >= 100) flushEvents();
  };

  const flushEvents = () => {
    if (!evBuf.current.length) return;
    const batch = evBuf.current;
    evBuf.current = [];
    queue().push('/api/events', batch);
  };

  // ------------------------------------------------- clock anchor + resume
  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let tries = 0;
    const go = async () => {
      const perf_ms = now();
      try {
        const r = await fetch('/api/session/start', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            token,
            perf_ms,
            viewport_w: window.innerWidth,
            viewport_h: window.innerHeight,
          }),
        });
        if (!r.ok) throw new Error(String(r.status));
        const j = (await r.json()) as { server_epoch_ms: number };
        anchorRef.current = { server_epoch_ms: j.server_epoch_ms, perf_ms };
        setConnected(true);
      } catch {
        setTimeout(() => void go(), Math.min(1000 * 2 ** tries++, 30000));
      }
    };
    void go();
  }, [token]);

  /* Resume after a force-quit. The cursor is persisted only AFTER a trial is
     recorded, so a resumed item is always one that produced no row yet and can
     be restarted cleanly. Anything still queued is flushed by getQueue. */
  useEffect(() => {
    try {
      const p = JSON.parse(localStorage.getItem(PROGRESS) || 'null') as
        | { screen: Screen; i: number }
        | null;
      if (p?.screen && p.screen !== 'consent') {
        setScreen(p.screen);
        setI(p.i ?? 0);
        setPhase('idle');
        logEvent('resume', { screen: p.screen, i: p.i });
      }
    } catch {
      /* no resume state */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const mark = (screenName: Screen, idx: number) => {
    try {
      localStorage.setItem(PROGRESS, JSON.stringify({ screen: screenName, i: idx }));
    } catch {
      /* storage blocked; resume is a convenience, not a requirement */
    }
  };

  // ------------------------------------------------------- tab-away tracking
  /* visibilitychange and blur are counted separately (invariant M6). Only
     visibility feeds tab_away_* and therefore the exclusion rule: a bare blur
     fires benignly when a screen reader opens its own dialog or Android drops
     the notification shade, and excluding on those would discard valid trials. */
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) {
        hiddenAt.current = now();
        logEvent('visibility_hidden');
        return;
      }
      if (hiddenAt.current === null) return;
      const dur = Math.round(now() - hiddenAt.current);
      hiddenAt.current = null;
      logEvent('visibility_visible', { duration_ms: dur });
      const live = liveRef.current;
      if (live?.started) {
        live.tab_away_events += 1;
        live.tab_away_max_ms = Math.max(live.tab_away_max_ms, dur);
      }
    };
    const onBlur = () => logEvent('window_blur');
    const onFocus = () => logEvent('window_focus');

    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --------------------------------------------------------- focus on advance
  /* Focus moves to the item heading, never to an input and never on
     load (invariants A1, A5). The whole screen is keyed on stepKey so the
     heading is a genuinely new node each time -- re-focusing a node that
     already has focus announces nothing at all. */
  const stepKey = `${screen}:${i}:${phase}`;
  useEffect(() => {
    headingRef.current?.focus();
  }, [stepKey]);

  const say = (m: string) => setStatus(m);

  useEffect(() => {
    const dialog = wrongDialogRef.current;
    if (!wrongAnswer || !dialog || dialog.open) return;
    wrongReturnFocusRef.current = document.activeElement as HTMLElement | null;
    dialog.showModal();
    wrongHeadingRef.current?.focus();
  }, [wrongAnswer]);

  const showWrongAnswer = (moveOn = false) => {
    const left = MAX_ATTEMPTS - liveRef.current!.attempts;
    advanceAfterWrongRef.current = moveOn;
    setStatus('');
    setWrongAnswer(
      moveOn
        ? 'Your answer was incorrect and you have used all three attempts. Close this message to move to the next task.'
        : `Your answer was incorrect. You have ${left} more ${left === 1 ? 'try' : 'tries'}. Close this message, change your answer, and submit again.`,
    );
  };

  const closeWrongAnswer = () => wrongDialogRef.current?.close();

  const afterWrongAnswer = () => {
    setWrongAnswer('');
    if (advanceAfterWrongRef.current) {
      advanceAfterWrongRef.current = false;
      advance();
      return;
    }
    wrongReturnFocusRef.current?.focus();
  };

  // ------------------------------------------------------------- trial write
  const recordTrial = (o: {
    correct: 0 | 1 | null;
    gave_up: 0 | 1;
    submit_perf: number;
    notes?: string | null;
  }) => {
    const live = liveRef.current;
    const anchor = anchorRef.current;
    if (!live || !anchor) return;
    live.settled = true;

    const payload: TrialPayload = {
      session_id: config.session_id,
      item_index: live.slot.item_index,
      condition: live.slot.condition,
      instance_id: live.slot.instance?.instance_id ?? BASELINE_INSTANCE_ID,
      order_position: live.slot.item_index,
      is_practice: live.slot.is_practice,
      anchor,
      marks: {
        item_start_perf: live.item_start_perf,
        first_focus_perf: live.first_focus_perf,
        first_keydown_perf: live.first_keydown_perf,
        first_pointer_perf: live.first_pointer_perf,
        submit_perf: o.submit_perf,
      },
      correct: o.correct,
      attempts: live.attempts,
      gave_up: o.gave_up,
      tab_away_events: live.tab_away_events,
      tab_away_max_ms: live.tab_away_max_ms,
      notes: o.notes ?? null,
      idem_key: `${config.session_id}:${live.slot.item_index}:${live.attempts}`,
    };
    queue().push('/api/trial', payload);
    flushEvents();
  };

  const advance = () => {
    setStatus('');
    liveRef.current = null;
    const next = i + 1;
    if (next < flow.length) {
      setI(next);
      setPhase('idle');
      mark('flow', next);
    } else {
      setScreen('done');
      mark('done', next);
      flushEvents();
      queue().pump();
    }
  };

  const beginItem = (slot: ItemSlot) => {
    liveRef.current = {
      slot,
      started: true,
      settled: false,
      attempts: 0,
      tab_away_events: 0,
      tab_away_max_ms: 0,
      item_start_perf: now(), // invariant M3: the clock starts on this press
      first_focus_perf: null,
      first_keydown_perf: null,
      first_pointer_perf: null,
    };
    logEvent('item_start', { instance_id: slot.instance?.instance_id ?? BASELINE_INSTANCE_ID });
    setPhase('active');
  };

  /* Three independent first-interaction signals (invariant M4), first
     occurrence only. Each one alone is unreliable on at least one target
     configuration: NVDA browse mode swallows arrow keys, TalkBack fires
     nothing until a double-tap. */
  const onFirstFocus = (e: React.FocusEvent) => {
    const live = liveRef.current;
    if (!live || live.first_focus_perf !== null) return;
    const t = e.target as HTMLElement & { name?: string };
    const isAnswer = t.name === 'col' || t.name === 'row' || t.tagName === 'IFRAME';
    if (!isAnswer) return;
    live.first_focus_perf = now();
    logEvent('focus', { target: t.id || t.tagName.toLowerCase() });
  };
  const onFirstKey = () => {
    const live = liveRef.current;
    if (!live || live.first_keydown_perf !== null) return;
    live.first_keydown_perf = now();
    logEvent('keydown');
  };
  const onFirstPointer = () => {
    const live = liveRef.current;
    if (!live || live.first_pointer_perf !== null) return;
    live.first_pointer_perf = now();
    logEvent('pointer');
  };

  const settle = (correct: 0 | 1 | null, gave_up: 0 | 1, notes?: string | null) => {
    const live = liveRef.current!;
    const submit_perf = now();
    recordTrial({ correct, gave_up, submit_perf, notes });
    if (gave_up) {
      say('Skipped. Moving on.');
      setTimeout(advance, 900);
    } else if (correct === 1) {
      say('Correct.');
      setTimeout(advance, 900);
    } else {
      showWrongAnswer(true);
    }
  };

  const skip = () => {
    const live = liveRef.current;
    if (!live || live.settled) return;
    logEvent('give_up');
    settle(0, 1);
  };

  // =========================================================== the baseline arm
  const boxRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<number | null>(null);
  const tokenRef = useRef<string | null>(null);
  const challengeRef = useRef(false);

  const slot = screen === 'flow' ? flow[i] : null;
  const baselineActive =
    phase === 'active' && slot?.kind === 'item' && slot.condition === 'audio_captcha_baseline';

  /* reCAPTCHA is the only third-party script in the app and it is injected
     here, on this route, only when the baseline item actually becomes active
     (invariant S2). */
  useEffect(() => {
    if (!baselineActive || !SITE_KEY) return;
    type G = { render?: (el: HTMLElement, o: object) => number; ready?: (f: () => void) => void };
    const draw = () => {
      const g = (window as unknown as { grecaptcha?: G }).grecaptcha;
      if (!g?.render || !boxRef.current || widgetRef.current !== null) return;
      widgetRef.current = g.render(boxRef.current, {
        sitekey: SITE_KEY,
        callback: (t: string) => {
          tokenRef.current = t;
          logEvent('baseline_checkbox_passed', { challenge_shown: challengeRef.current ? 1 : 0 });
          say('The check is complete. Select Submit answer.');
        },
        'expired-callback': () => {
          tokenRef.current = null;
        },
        'error-callback': () => {
          tokenRef.current = null;
        },
      });
    };
    if ((window as unknown as { grecaptcha?: G }).grecaptcha?.render) {
      draw();
      return;
    }
    const s = document.createElement('script');
    s.src = 'https://www.google.com/recaptcha/api.js?render=explicit&hl=en';
    s.async = true;
    s.defer = true;
    s.onload = () => {
      const g = (window as unknown as { grecaptcha?: G }).grecaptcha;
      if (g?.ready) g.ready(draw);
      else draw();
    };
    document.head.appendChild(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineActive]);

  /* A clean browsing context can pass reCAPTCHA on the checkbox alone. Whether
     an actual challenge appeared is itself a datum, so it is observed rather
     than assumed: Google's challenge lives in an iframe inside a container it
     toggles visible. Best-effort by nature -- if Google changes that markup
     this flag goes quiet, which is why it is reported as a rate and never used
     to decide `correct`. No timer is involved (invariant A6). */
  useEffect(() => {
    if (!baselineActive) return;
    const look = () => {
      const f = document.querySelector('iframe[title^="recaptcha challenge"]');
      const host = f?.parentElement?.parentElement as HTMLElement | null;
      if (host && host.style.visibility !== 'hidden' && host.getBoundingClientRect().height > 0) {
        challengeRef.current = true;
      }
    };
    const mo = new MutationObserver(look);
    mo.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['style'],
    });
    look();
    return () => mo.disconnect();
  }, [baselineActive]);

  const submitBaseline = async () => {
    const live = liveRef.current;
    if (!live || live.settled) return;

    if (!SITE_KEY) {
      settle(null, 0, 'baseline_not_configured');
      return;
    }
    if (!tokenRef.current) {
      say(
        'The check is not finished yet. Select the box that says I am not a robot, ' +
          'then select Submit answer.',
      );
      return;
    }

    /* submit_perf is taken now, before the verification round trip: it marks
       the participant's action, not Google's latency. */
    const submit_perf = now();
    live.attempts += 1;
    const sent = tokenRef.current;
    tokenRef.current = null;

    let correct: 0 | 1 | null = null;
    try {
      const r = await fetch('/api/baseline/verify', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ token: sent }),
      });
      if (!r.ok) throw new Error(String(r.status));
      correct = ((await r.json()) as { correct: 0 | 1 }).correct === 1 ? 1 : 0;
    } catch {
      correct = null;
    }
    logEvent('attempt_result', {
      correct,
      attempt_no: live.attempts,
      challenge_shown: challengeRef.current ? 1 : 0,
    });

    if (correct === null) {
      recordTrial({ correct: null, gave_up: 0, submit_perf, notes: 'baseline_verify_unreachable' });
      say('Thank you. Moving on to the next task.');
      setTimeout(advance, 1400);
      return;
    }
    if (correct === 1) {
      /* Not triggered is a legitimate outcome, recorded honestly rather than
         retried or forced. The rate belongs in the paper. */
      recordTrial({
        correct: 1,
        gave_up: 0,
        submit_perf,
        notes: challengeRef.current ? null : 'baseline_not_triggered',
      });
      say('Correct.');
      setTimeout(advance, 900);
      return;
    }
    if (live.attempts >= MAX_ATTEMPTS) {
      recordTrial({ correct: 0, gave_up: 0, submit_perf, notes: null });
      showWrongAnswer(true);
      return;
    }
    const g = (window as unknown as { grecaptcha?: { reset?: (id?: number) => void } }).grecaptcha;
    if (g?.reset && widgetRef.current !== null) g.reset(widgetRef.current);
    showWrongAnswer();
  };

  // ============================================================ grid grading
  const submitGrid = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const live = liveRef.current;
    if (!live) return;
    /* A double-press inside the feedback window must never write a second row
       for one item: that would break the one-row-per-item guarantee the whole
       dataset rests on (sanity query 2). It is a pointer artefact, not a second
       attempt at the puzzle. */
    if (live.settled) {
      logEvent('submit_after_settle');
      return;
    }

    const fd = new FormData(e.currentTarget);
    const col = fd.get('col') as string | null;
    const row = fd.get('row') as string | null;

    /* Validate on submit only, never on keystroke or blur (invariant A9). */
    if (!col || !row) {
      say(
        !col && !row
          ? 'No answer chosen yet. Choose a column and a row, then select Submit.'
          : !col
            ? 'No column chosen yet. Choose a column, then select Submit.'
            : 'No row chosen yet. Choose a row, then select Submit.',
      );
      return;
    }

    const answer = col + row;
    live.attempts += 1;
    const correct = answer === live.slot.instance!.solution;
    logEvent('attempt_result', {
      answer,
      correct: correct ? 1 : 0,
      attempt_no: live.attempts,
    });

    if (correct) return settle(1, 0);
    if (live.attempts >= MAX_ATTEMPTS) return settle(0, 0);
    showWrongAnswer();
  };

  // ================================================================== render
  const h2 = (text: string) => (
    <h2 id="hd" tabIndex={0} ref={headingRef}>
      {text}
    </h2>
  );

  let body: React.ReactNode = null;

  if (screen === 'consent') {
    body = (
      <>
        {h2('Before we begin')}
        <p tabIndex={0}>
          You will be asked to solve some short word puzzles. There is no time limit
          and nothing is being judged about you. You can stop at any moment, for any
          reason, and you do not have to give a reason.
        </p>
        <p tabIndex={0}>
          We record how long each puzzle takes, whether the answer was right, your task
          ratings, and non-identifying background information about vision, education,
          language and technology use. No name, no contact detail, no recording of you.
        </p>
        <fieldset>
          <legend tabIndex={0}>Consent</legend>
          <p className="opt">
            <label htmlFor="consent">
              <input type="checkbox" id="consent" /> I have had this read to me and I
              agree to take part.
            </label>
          </p>
        </fieldset>
        <button
          onClick={() => {
            const box = document.getElementById('consent') as HTMLInputElement | null;
            if (!box?.checked) {
              say('Please confirm consent before continuing.');
              box?.focus();
              return;
            }
            if (!anchorRef.current) {
              say(
                'Still connecting to the server. Wait a moment, then select Continue again.',
              );
              return;
            }
            logEvent('consent');
            setScreen('profile');
            mark('profile', 0);
          }}
        >
          Continue
        </button>
        {!connected ? <p className="meta">Connecting to the server.</p> : null}
      </>
    );
  } else if (screen === 'profile') {
    body = (
      <>
        {h2('About you')}
        <p tabIndex={0}>
          These questions help us understand whether different backgrounds and ways of
          using technology affect the results. Choose “Prefer not to say” whenever you
          do not wish to answer.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            logEvent(
              'participant_profile',
              Object.fromEntries(
                PROFILE_FIELDS.map(({ name }) => [name, String(form.get(name))]),
              ),
            );
            flushEvents();
            setScreen('intro');
            mark('intro', 0);
          }}
        >
          {PROFILE_FIELDS.map(({ name, label, options }) => (
            <fieldset key={name}>
              <legend tabIndex={0}>{label}</legend>
              <label className="select-answer" htmlFor={name}>
                Choose one answer
                <select id={name} name={name} required defaultValue="">
                  <option value="" disabled>
                    Select an option
                  </option>
                  {options.map(([value, text]) => (
                    <option key={value} value={value}>
                      {text}
                    </option>
                  ))}
                </select>
              </label>
            </fieldset>
          ))}
          <button type="submit">Continue</button>
        </form>
      </>
    );
  } else if (screen === 'intro') {
    body = (
      <>
        {h2('How this works')}
        <p tabIndex={0}>
          A circle is hidden in one box of a grid. Each clue tells you where the circle
          is <em>not</em>. Rule out boxes until only one is left.
        </p>
        <p tabIndex={0}>
          A box is named by its column letter and then its row number. B3 means column
          B, row 3.
        </p>
        <p tabIndex={0}>
          When you press Start, the puzzle appears. Take as long as you like — there is
          no clock showing and nothing runs out.
        </p>
        <p tabIndex={0}>We will do one practice puzzle first. The practice one does not count.</p>
        <button
          onClick={() => {
            setScreen('flow');
            setI(0);
            setPhase('idle');
            mark('flow', 0);
          }}
        >
          Continue to the practice puzzle
        </button>
      </>
    );
  } else if (screen === 'flow' && slot?.kind === 'rating') {
    body = (
      <>
        {h2('Questions about this task')}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            logEvent('difficulty_rating', {
              value: Number(form.get('difficulty')),
              condition: slot.condition,
              mental_effort: Number(form.get('mental_effort')),
              frustration: Number(form.get('frustration')),
              perceived_accessibility: Number(form.get('perceived_accessibility')),
              ease_of_navigation: Number(form.get('ease_of_navigation')),
            });
            flushEvents();
            advance();
          }}
        >
          {CONDITION_MEASURES.map((measure) => (
            <fieldset key={measure.name}>
              <legend tabIndex={0}>{measure.label}</legend>
              {measure.options.map((label, index) => {
                const value = index + 1;
                const id = `${measure.name}-${value}`;
                return (
                  <span className="opt" key={id}>
                    <label htmlFor={id}>
                      <input
                        type="radio"
                        name={measure.name}
                        id={id}
                        value={value}
                        required
                      />{' '}
                      {value} — {label}
                    </label>
                  </span>
                );
              })}
            </fieldset>
          ))}
          <button type="submit">Continue</button>
        </form>
      </>
    );
  } else if (screen === 'flow' && slot?.kind === 'item') {
    const label = slot.is_practice
      ? 'Practice puzzle'
      : slot.condition === 'audio_captcha_baseline'
        ? 'Website verification check'
        : `Puzzle ${slot.pos} of ${slot.of}`;

    if (phase === 'idle') {
      // IDLE. Nothing about the challenge is in the DOM yet (invariant M3).
      body = (
        <>
          {h2(label)}
          <p tabIndex={0}>
            Press the button when you are ready. The task will appear and you can read
            it at your own pace.
          </p>
          <button
            onClick={() => {
              if (!anchorRef.current) {
                say(
                  'Still connecting to the server. Wait a moment, then select Start again.',
                );
                return;
              }
              beginItem(slot);
            }}
          >
            Start this puzzle
          </button>
        </>
      );
    } else if (slot.condition === 'audio_captcha_baseline') {
      body = (
        <div onFocus={onFirstFocus} onKeyDown={onFirstKey} onPointerDown={onFirstPointer}>
          {h2(label)}
          <p id="preamble" tabIndex={0}>
            This is the kind of check many websites use to tell people apart from
            robots. Select the box labelled I am not a robot. If the check then asks you
            to do more, it offers its own audio option. When the check is complete,
            select Submit answer. There is no time limit.
          </p>
          {SITE_KEY ? (
            <div ref={boxRef} />
          ) : (
            <p tabIndex={0}>
              This check is not configured on this deployment. Select Submit answer to
              move on, and tell the researcher.
            </p>
          )}
          <p>
            <button type="button" onClick={() => void submitBaseline()}>
              Submit answer
            </button>
            <button type="button" className="secondary" onClick={skip}>
              Skip this puzzle
            </button>
          </p>
        </div>
      );
    } else {
      const ins = slot.instance!;
      const cells: React.ReactNode[] = [];
      for (let r = 1; r <= ins.n; r++) {
        for (let c = 0; c < ins.n; c++) {
          const id = 'ABCDEFG'[c] + r;
          const isMarker = ins.marker === id;
          cells.push(
            <div className={isMarker ? 'cell marker' : 'cell'} key={id}>
              {isMarker ? `${id} ■` : id}
            </div>,
          );
        }
      }
      const radios = (group: 'col' | 'row', values: string[]) =>
        values.map((v, k) => (
          <span className="opt" key={v}>
            <label htmlFor={`${group}${k}`}>
              <input type="radio" name={group} id={`${group}${k}`} value={v} />{' '}
              {group === 'col' ? 'Column' : 'Row'} {v}
            </label>
          </span>
        ));

      body = (
        <>
          {h2(label)}
          <p id="preamble" tabIndex={0}>{ins.preamble}</p>

          {/* Decorative. A screen reader never reaches it, and the puzzle is
              fully solvable without it (invariants A3, A3b, A3c). Never a
              <table>: a 4x4 table forces NVDA into table-navigation mode and
              you would be measuring table proficiency, not reasoning. */}
          <div
            className="grid"
            aria-hidden="true"
            style={{ ['--n' as string]: ins.n } as React.CSSProperties}
          >
            {cells}
          </div>

          <h3 id="clues-hd" tabIndex={0} ref={cluesRef}>
            Clues
          </h3>
          <ol className="clues" id="clues">
            {ins.clues.map((c, k) => (
              <li key={k} tabIndex={0}>{c}</li>
            ))}
          </ol>

          <form
            noValidate
            onSubmit={submitGrid}
            onFocus={onFirstFocus}
            onKeyDown={onFirstKey}
            onPointerDown={onFirstPointer}
          >
            <fieldset>
              <legend id="q" tabIndex={0}>{ins.question}</legend>
              <div id="hint" className="meta" tabIndex={0}>
                Choose the column, then the row, then select Submit.
              </div>
              {/* The aria-describedby chain is load-bearing: screen readers
                  enter forms mode inside <form> and read only form elements,
                  so content outside this chain can be skipped silently. */}
              <div
                role="radiogroup"
                aria-labelledby="colhd"
                aria-describedby="preamble clues hint"
              >
                <h3 id="colhd" tabIndex={0}>Column</h3>
                {radios('col', ins.column_options)}
              </div>
              <div role="radiogroup" aria-labelledby="rowhd">
                <h3 id="rowhd" tabIndex={0}>Row</h3>
                {radios('row', ins.row_options)}
              </div>
            </fieldset>

            <button type="submit">Submit answer</button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                logEvent('reread');
                cluesRef.current?.focus();
              }}
            >
              Read the clues again
            </button>
            <button type="button" className="secondary" onClick={skip}>
              Skip this puzzle
            </button>
          </form>
        </>
      );
    }
  } else {
    body = (
      <>
        {h2('That is everything. Thank you.')}
        <p tabIndex={0}>
          You have finished. You can tell the researcher you are done.
        </p>
      </>
    );
  }

  return (
    <>
      <a className="skip-link" href="#main-region">
        Skip to the current task
      </a>
      <main id="main-region">
        <h1>Touchstone challenge session</h1>

        {/* Polite only. Never assertive, never role="alert" while an item is
            active (invariant A4): an assertive announcement interrupts the
            screen reader mid-utterance, which is the documented primary cause
            of audio CAPTCHA failure. */}
        <div id="status" role="status" aria-live="polite" aria-atomic="true">
          {status}
        </div>

        <div key={stepKey}>{body}</div>
      </main>
      <dialog
        ref={wrongDialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="wrong-answer-title"
        aria-describedby="wrong-answer-message wrong-answer-help"
        onClose={afterWrongAnswer}
      >
        <h2 id="wrong-answer-title" ref={wrongHeadingRef} tabIndex={-1}>
          Incorrect answer
        </h2>
        <p id="wrong-answer-message">{wrongAnswer}</p>
        <p id="wrong-answer-help">Press Escape or select the button below to close this message.</p>
        <button type="button" onClick={closeWrongAnswer}>
          {advanceAfterWrongRef.current ? 'Close and continue' : 'Close and try again'}
        </button>
      </dialog>
    </>
  );
}
